"""Sensor platform for Fulcrum Tracker integration."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .api.the_matrix_calendar import MatrixCalendarHandler
from .api.auth import ZenPlannerAuth
from .api.calendar import ZenPlannerCalendar
from .api.google_calendar import AsyncGoogleCalendarHandler
from .api.pr import PRHandler
from .const import (
    DOMAIN,
    DEFAULT_UPDATE_INTERVAL,
    DEFAULT_USER_ID,
    CONF_CALENDAR_ID,
    CONF_SERVICE_ACCOUNT_PATH,
    TRAINERS,
    EXERCISE_TYPES,
)
from .storage import FulcrumTrackerStore

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(minutes=DEFAULT_UPDATE_INTERVAL)

# Sensor Type Definitions
TRAINER_SENSORS = [
    SensorEntityDescription(
        key=f"trainer_{name.lower()}_sessions",
        name=f"Sessions with {name}",
        icon="mdi:account-tie",
        native_unit_of_measurement="sessions",
        state_class=SensorStateClass.TOTAL_INCREASING,
    )
    for name in TRAINERS
]

PR_SENSORS = [
    SensorEntityDescription(
        key=f"pr_{exercise_type}",
        name=f"{exercise_type.replace('_', ' ').title()} PR",
        icon="mdi:weight-lifter",
    )
    for exercise_type in EXERCISE_TYPES
]

SENSOR_TYPES: tuple[SensorEntityDescription, ...] = (
    *TRAINER_SENSORS,
    *PR_SENSORS,
    SensorEntityDescription(
        key="zenplanner_fulcrum_sessions",
        name="ZenPlanner Fulcrum Sessions",
        icon="mdi:dumbbell",
        native_unit_of_measurement="sessions",
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    SensorEntityDescription(
        key="google_calendar_fulcrum_sessions",
        name="Google Calendar Fulcrum Sessions",
        icon="mdi:calendar-check",
        native_unit_of_measurement="sessions",
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    SensorEntityDescription(
        key="total_fulcrum_sessions",
        name="Total Fulcrum Sessions",
        icon="mdi:dumbbell-variant",
        native_unit_of_measurement="sessions",
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    SensorEntityDescription(
        key="monthly_sessions",
        name="Monthly Training Sessions",
        icon="mdi:calendar-month",
        native_unit_of_measurement="sessions",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="last_session",
        name="Last Training Session",
        icon="mdi:calendar-clock",
    ),
    SensorEntityDescription(
        key="next_session",
        name="Next Training Session",
        icon="mdi:calendar-arrow-right",
    ),
    SensorEntityDescription(
        key="recent_prs",
        name="Recent PRs",
        icon="mdi:trophy",
    ),
    SensorEntityDescription(
        key="total_prs",
        name="Total PRs",
        icon="mdi:trophy-variant",
        native_unit_of_measurement="PRs",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="tomorrow_workout",
        name="Tomorrow's Workout",
        icon="mdi:dumbbell",
    ),
)

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Fulcrum Tracker sensors."""
    username = config_entry.data[CONF_USERNAME]
    password = config_entry.data[CONF_PASSWORD]
    calendar_id = config_entry.data[CONF_CALENDAR_ID]
    service_account_path = config_entry.data[CONF_SERVICE_ACCOUNT_PATH]

    _LOGGER.debug("Setting up sensors with calendar_id: %s", calendar_id)

    # Initialize API handlers
    auth = ZenPlannerAuth(username, password)
    calendar = ZenPlannerCalendar(auth)
    pr_handler = PRHandler(auth, DEFAULT_USER_ID)
    google_calendar = AsyncGoogleCalendarHandler(service_account_path, calendar_id)
    matrix_handler = MatrixCalendarHandler(google_calendar)
    
    # Get storage from domain data
    storage = hass.data[DOMAIN][config_entry.entry_id]["storage"]

    coordinator = FulcrumDataUpdateCoordinator(
        hass=hass,
        logger=_LOGGER,
        name="fulcrum_tracker",
        calendar=calendar,
        pr_handler=pr_handler,
        google_calendar=google_calendar,
        matrix_handler=matrix_handler,
        storage=storage,
    )

    await coordinator.async_refresh()

    entities = [
        FulcrumSensor(
            coordinator=coordinator,
            description=description,
            config_entry=config_entry,
        )
        for description in SENSOR_TYPES
    ]

    async_add_entities(entities)

class FulcrumDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching Fulcrum data."""

    def __init__(
        self,
        hass: HomeAssistant,
        logger: logging.Logger,
        name: str,
        calendar: ZenPlannerCalendar,
        pr_handler: PRHandler,
        google_calendar: AsyncGoogleCalendarHandler,
        matrix_handler: MatrixCalendarHandler,
        storage: FulcrumTrackerStore,  # Add storage parameter
    ) -> None:
        """Initialize."""
        super().__init__(
            hass=hass,
            logger=logger,
            name=name,
            update_interval=SCAN_INTERVAL,
        )
        self.calendar = calendar
        self.pr_handler = pr_handler
        self.google_calendar = google_calendar
        self.matrix_handler = matrix_handler
        self.storage = storage  # Store storage reference
        self._last_update_time = None
        self._collection_stats = {
            "total_sessions": 0,
            "new_sessions_today": 0,
            "last_full_update": None,
            "update_streak": 0,
            "current_phase": storage.initialization_phase  # Use storage phase
        }
        _LOGGER.debug("🎮 Coordinator initialized in phase: %s", self._collection_stats["current_phase"])

    def _format_workout(self, workout: Optional[Dict[str, Any]]) -> str:
        """Format workout details for display."""
        if not workout:
            return "No workout scheduled"
        
        parts = []
        if workout.get('type'):
            parts.append(workout['type'])
        if workout.get('lifts'):
            parts.append(f"Lifts: {workout['lifts']}")
        if workout.get('meps'):
            parts.append(f"MEPs: {workout['meps']}")
            
        return " | ".join(parts) if parts else "Workout details not available"

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from APIs with phase-aware updates."""
        try:
            now = datetime.now(timezone.utc)

            # Always get tomorrow's workout regardless of phase
            tomorrow_workout = await self.matrix_handler.get_tomorrow_workout()
            
            current_phase = self.storage.initialization_phase
            _LOGGER.debug("🔄 Running update in phase: %s", current_phase)

            if current_phase == "init":
                # Initial setup - transition to historical load
                await self.storage.async_transition_phase("historical_load", {
                    "start_time": now.isoformat()
                })
                current_phase = "historical_load"

            if current_phase == "historical_load":
                _LOGGER.info("📚 Performing historical data load...")
                # Get full historical data
                attendance_data = await self.calendar.get_attendance_data()
                pr_data = await self.pr_handler.get_formatted_prs()
                calendar_events = await self.google_calendar.get_calendar_events()
                next_session = await self.google_calendar.get_next_session()
                # Process trainer stats
                trainer_stats = self._process_trainer_stats(calendar_events)
                if attendance_data and calendar_events:
                    total_sessions = self._reconcile_sessions(attendance_data, calendar_events)
                    await self.storage.async_update_session_count(total_sessions)
                    await self.storage.async_transition_phase("incremental", {
                        "total_sessions": total_sessions,
                        "completion_time": now.isoformat()
                    })
                return {
                    **trainer_stats,
                    "zenplanner_fulcrum_sessions": attendance_data.get("total_sessions", 0),
                    "google_calendar_fulcrum_sessions": len(calendar_events) if calendar_events else 0,
                    "total_fulcrum_sessions": total_sessions,
                    "monthly_sessions": attendance_data.get("monthly_sessions", 0),
                    "last_session": attendance_data.get("last_session"),
                    "next_session": next_session,
                    "recent_prs": pr_data.get("recent_prs", "No recent PRs"),
                    "total_prs": pr_data.get("total_prs", 0),
                    "prs_by_type": pr_data.get("prs_by_type", {}),
                    "collection_stats": self._collection_stats,
                    "tomorrow_workout": self._format_workout(tomorrow_workout),
                    "tomorrow_workout_details": tomorrow_workout
                }

            else:  # Incremental mode
                _LOGGER.debug("♻️ Performing incremental update...")
                # Get recent data (2 days)
                update_start = now - timedelta(days=2)
                next_session = await self.google_calendar.get_next_session()
                pr_data = await self.pr_handler.get_formatted_prs()
                
                recent_events = await self.google_calendar.get_calendar_events(
                    start_date=update_start,
                    end_date=now
                )
                
                if recent_events:
                    self._collection_stats["new_sessions_today"] = len(recent_events)
                    self._collection_stats["update_streak"] += 1
                    trainer_stats = self._process_trainer_stats(recent_events)
                    
                    # Record the update with proper error handling
                    try:
                        await self.storage.async_record_update(now.isoformat())
                    except Exception as err:
                        _LOGGER.warning("Failed to record update timestamp: %s", err)

                return {
                    **(self.data if self.data else {}),
                    **(trainer_stats if recent_events else {}),
                    "next_session": next_session,
                    "recent_prs": pr_data.get("recent_prs", "No recent PRs"),
                    "prs_by_type": pr_data.get("prs_by_type", {}),
                    "collection_stats": self._collection_stats,
                    "tomorrow_workout": self._format_workout(tomorrow_workout),
                    "tomorrow_workout_details": tomorrow_workout
                }

        except Exception as err:
            self._collection_stats["update_streak"] = 0
            _LOGGER.error("💥 Update failed: %s", str(err))
            raise


class SensorDefaults:
    """Handle default values for all sensor types."""

    @staticmethod
    def get_loading_state(sensor_key: str) -> Dict[str, Any]:
        """Get appropriate loading state for a sensor type."""
        
        # PR-specific defaults
        if sensor_key.startswith("pr_"):
            return {
                "state": "Loading PR data...",
                "attributes": {
                    "last_attempt": "Not yet loaded",
                    "days_since": "?",
                    "attempts": 0,
                    "date_achieved": None,
                    "loading_status": "initializing"
                }
            }
        
        # Trainer session counters
        if sensor_key.startswith("trainer_"):
            trainer_name = sensor_key.split("_")[1].title()
            return {
                "state": 0,
                "attributes": {
                    "total_sessions": 0,
                    "trainer_name": trainer_name,
                    "loading_status": "initializing"
                }
            }
        
        # Special case sensors
        SPECIAL_DEFAULTS = {
            "zenplanner_fulcrum_sessions": {
                "state": 0,
                "attributes": {"source": "ZenPlanner", "loading_status": "initializing"}
            },
            "google_calendar_fulcrum_sessions": {
                "state": 0,
                "attributes": {"source": "Google Calendar", "loading_status": "initializing"}
            },
            "total_fulcrum_sessions": {
                "state": 0,
                "attributes": {
                    "sessions_this_month": 0,
                    "last_session_date": "Loading...",
                    "calendar_total": 0,
                    "new_sessions_today": 0,
                    "update_streak": 0,
                    "current_phase": "initializing",
                    "loading_status": "initializing"
                }
            },
            "monthly_sessions": {
                "state": 0,
                "attributes": {"loading_status": "initializing"}
            },
            "last_session": {
                "state": "Loading last session data...",
                "attributes": {"loading_status": "initializing"}
            },
            "next_session": {
                "state": "Loading next session data...",
                "attributes": {
                    "instructor": "Loading...",
                    "location": "Loading...",
                    "description": "Initializing session data...",
                    "loading_status": "initializing"
                }
            },
            "recent_prs": {
                "state": "Loading PR history...",
                "attributes": {"loading_status": "initializing"}
            },
            "total_prs": {
                "state": 0,
                "attributes": {"loading_status": "initializing"}
            },
            "tomorrow_workout": {
                "state": "Loading workout data...",
                "attributes": {
                    "workout_type": "Loading...",
                    "lifts": "Loading...",
                    "meps": "Loading...",
                    "loading_status": "initializing"
                }
            }
        }
        
        # Return special case or generic default
        return SPECIAL_DEFAULTS.get(sensor_key, {
            "state": "Initializing...",
            "attributes": {"loading_status": "initializing"}
        })

    @staticmethod
    def is_loading_state(state_dict: Dict[str, Any]) -> bool:
        """Check if a state dictionary represents a loading state."""
        return (
            isinstance(state_dict, dict) and 
            state_dict.get("attributes", {}).get("loading_status") == "initializing"
        )


class FulcrumSensor(CoordinatorEntity, SensorEntity):
    """Representation of a Fulcrum sensor."""

    def __init__(
        self,
        coordinator: FulcrumDataUpdateCoordinator,
        description: SensorEntityDescription,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{config_entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, config_entry.entry_id)},
            name="Fulcrum Fitness",
            manufacturer="Fulcrum Fitness PDX",
            model="Training Tracker"
        )

    @property
    def native_value(self) -> StateType:
        """Return the state of the sensor."""
        if self.coordinator.data is None:
            default_state = SensorDefaults.get_loading_state(self.entity_description.key)
            _LOGGER.debug(
                "🏗️ Using default state for %s: %s", 
                self.entity_description.key,
                default_state["state"]
            )
            return default_state["state"]
            
        # Handle PR sensors
        if self.entity_description.key.startswith("pr_"):
            exercise_type = self.entity_description.key[3:]
            prs = self.coordinator.data.get("prs_by_type", {})
            if exercise_type in prs and prs[exercise_type]:
                return prs[exercise_type].get("value")
            return SensorDefaults.get_loading_state(self.entity_description.key)["state"]
            
        # Format next session nicely if that's what we're showing
        if self.entity_description.key == "next_session" and self.coordinator.data.get("next_session"):
            next_session = self.coordinator.data["next_session"]
            return f"{next_session['date']} {next_session['time']} with {next_session['instructor']}"
            
        value = self.coordinator.data.get(self.entity_description.key)
        if value is None:
            return SensorDefaults.get_loading_state(self.entity_description.key)["state"]
        return value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return entity specific state attributes."""
        # Start with default attributes
        default_state = SensorDefaults.get_loading_state(self.entity_description.key)
        attrs = default_state["attributes"].copy()

        # If we don't have coordinator data yet, return defaults
        if self.coordinator.data is None:
            return attrs
            
        data = self.coordinator.data or {}

        # PR-specific attributes
        if self.entity_description.key.startswith("pr_"):
            exercise_type = self.entity_description.key[3:]
            prs = self.coordinator.data.get("prs_by_type", {}).get(exercise_type, {})
            if prs:
                attrs.update({
                    "last_attempt": prs.get("last_result"),
                    "days_since": prs.get("days_since"),
                    "attempts": prs.get("attempts"),
                    "date_achieved": prs.get("date"),
                    "loading_status": "complete"
                })

        # Tomorrow's workout attributes
        elif self.entity_description.key == "tomorrow_workout":
            workout = data.get("tomorrow_workout_details", {})
            if workout:
                attrs.update({
                    "workout_type": workout.get('type'),
                    "lifts": workout.get('lifts'),
                    "meps": workout.get('meps'),
                    "raw_summary": workout.get('raw_summary'),
                    "loading_status": "complete"
                })

        # Total sessions attributes
        elif self.entity_description.key == "total_fulcrum_sessions":
            attrs.update({
                "sessions_this_month": data.get("monthly_sessions", 0),
                "last_session_date": data.get("last_session"),
                "calendar_total": data.get("google_calendar_fulcrum_sessions", 0),
                "loading_status": "complete",
                "storage_state": {
                    "historical_load_done": self.coordinator.storage.historical_load_done,
                    "last_update": self.coordinator.storage.last_update,
                    "initialization_phase": self.coordinator.storage.initialization_phase
                }
            })
            
            if "collection_stats" in data:
                attrs.update({
                    "new_sessions_today": data["collection_stats"].get("new_sessions_today", 0),
                    "update_streak": data["collection_stats"].get("update_streak", 0),
                    "current_phase": data["collection_stats"].get("current_phase", "unknown")
                })

        # Next session attributes
        elif self.entity_description.key == "next_session" and data.get("next_session"):
            next_session = data["next_session"]
            attrs.update({
                "instructor": next_session.get("instructor", "Unknown"),
                "location": next_session.get("location", ""),
                "description": next_session.get("description", ""),
                "event_id": next_session.get("event_id", ""),
                "loading_status": "complete"
            })

        # Trainer-specific attributes
        elif self.entity_description.key.startswith("trainer_"):
            trainer_name = self.entity_description.key.split("_")[1]
            if f"trainer_{trainer_name}_sessions" in data:
                attrs.update({
                    "total_sessions": data[f"trainer_{trainer_name}_sessions"],
                    "loading_status": "complete"
                })

        return attrs