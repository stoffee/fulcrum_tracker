"""Sensor platform for Fulcrum Tracker integration."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

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

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(minutes=DEFAULT_UPDATE_INTERVAL)

# Trainer session sensors
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

# PR sensors for each exercise type
PR_SENSORS = [
    SensorEntityDescription(
        key=f"pr_{exercise_type}",
        name=f"{exercise_type.replace('_', ' ').title()} PR",
        icon="mdi:weight-lifter",
    )
    for exercise_type in EXERCISE_TYPES
]

SENSOR_TYPES: tuple[SensorEntityDescription, ...] = (
    # Include all sensor types
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

    auth = ZenPlannerAuth(username, password)
    calendar = ZenPlannerCalendar(auth)
    pr_handler = PRHandler(auth, DEFAULT_USER_ID)
    google_calendar = AsyncGoogleCalendarHandler(service_account_path, calendar_id)

    coordinator = FulcrumDataUpdateCoordinator(
        hass=hass,
        logger=_LOGGER,
        name="fulcrum_tracker",
        calendar=calendar,
        pr_handler=pr_handler,
        google_calendar=google_calendar,
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

class FirstRunHandler:
    """Handle first run detection and initialization."""
    
    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the handler."""
        self.hass = hass
        self.store = hass.helpers.storage.Store(version=1, key=f"{DOMAIN}_initialization")
        
    async def is_first_run(self) -> bool:
        """Check if this is the first run."""
        data = await self.store.async_load()
        return data is None
        
    async def mark_initialized(self, stats: dict) -> None:
        """Mark system as initialized with initial stats."""
        await self.store.async_save({
            "initialized_at": datetime.now().isoformat(),
            "initial_stats": stats,
        })
        
    async def get_initialization_stats(self) -> Optional[dict]:
        """Get stats from when system was first initialized."""
        return await self.store.async_load()

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
        self._hass = hass
        self._first_update_done = False
        self._historical_load_done = False
        self._historical_load_in_progress = False
        self._last_update_time = None
        self._collection_stats = {
            "total_sessions": 0,
            "new_sessions_today": 0,
            "last_full_update": None,
            "update_streak": 0,
            "current_phase": "init"
        }
        _LOGGER.debug("🎮 Coordinator initialized and ready to rock!")

    def _process_trainer_stats(self, calendar_events: list) -> dict:
        """Process trainer statistics from calendar events."""
        trainer_stats = {f"trainer_{name.lower()}_sessions": 0 for name in TRAINERS}
        _LOGGER.debug("Initial trainer stats keys: %s", list(trainer_stats.keys()))
        
        for event in calendar_events:
            if 'instructor' in event:
                instructor = event['instructor'].strip().split()[0]
                key = f"trainer_{instructor.lower()}_sessions"
                _LOGGER.debug("Processing instructor: %s -> key: %s", instructor, key)
                if key in trainer_stats:
                    trainer_stats[key] += 1
                else:
                    _LOGGER.warning("Unrecognized trainer key: %s", key)
        
        _LOGGER.debug("Final trainer stats: %s", trainer_stats)
        return trainer_stats

    async def _load_historical_data(self) -> None:
        """Background task to load all historical data."""
        try:
            if self._historical_load_done or self._historical_load_in_progress:
                return

            _LOGGER.info("🕰️ Starting background historical data load...")
            self._historical_load_in_progress = True
            self._collection_stats["current_phase"] = "historical_load"

            # Get full historical data
            attendance_data = await self._hass.async_add_executor_job(
                self.calendar.get_attendance_data
            )
            calendar_events = await self.google_calendar.get_calendar_events()

            # Update our stats with the full data
            if attendance_data and calendar_events:
                self.data = {
                    **self.data,
                    "zenplanner_fulcrum_sessions": attendance_data.get("total_sessions", 0),
                    "google_calendar_fulcrum_sessions": len(calendar_events),
                    "total_fulcrum_sessions": self._reconcile_sessions(attendance_data, calendar_events),
                }
                
                trainer_stats = self._process_trainer_stats(calendar_events)
                self.data.update(trainer_stats)

            self._historical_load_done = True
            self._collection_stats["current_phase"] = "incremental"
            _LOGGER.info("📚 Historical data load complete! Total sessions: %d", 
                        self.data.get("total_fulcrum_sessions", 0))

        except Exception as err:
            _LOGGER.error("💥 Historical data load failed: %s", str(err))
            self._collection_stats["current_phase"] = "historical_load_failed"
        finally:
            self._historical_load_in_progress = False

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from APIs."""
        try:
            matrix_handler = MatrixCalendarHandler(self.google_calendar)
            now = datetime.now(timezone.utc)

            # Always get tomorrow's workout
            tomorrow_workout = await matrix_handler.get_tomorrow_workout()
            
            # PHASE 1: Quick Initial Load (30 days)
            if not self._first_update_done or not self.data:
                _LOGGER.info("🚀 PHASE 1: Quick Load - Getting last 30 days...")
                self._collection_stats["current_phase"] = "quick_load"
                
                # Get just last 30 days
                start_date = now - timedelta(days=30)
                attendance_data = await self._hass.async_add_executor_job(
                    lambda: self.calendar.get_recent_attendance(start_date)
                )
                pr_data = await self._hass.async_add_executor_job(
                    self.pr_handler.get_formatted_prs
                )
                calendar_events = await self.google_calendar.get_calendar_events()
                next_session = await self.google_calendar.get_next_session()

                initial_data = {
                    "zenplanner_fulcrum_sessions": attendance_data.get("total_sessions", 0),
                    "google_calendar_fulcrum_sessions": len(calendar_events) if calendar_events else 0,
                    "total_fulcrum_sessions": self._reconcile_sessions(attendance_data, calendar_events),
                    "monthly_sessions": attendance_data.get("monthly_sessions", 0),
                    "last_session": attendance_data.get("last_session"),
                    "next_session": next_session,
                    "recent_prs": pr_data.get("recent_prs", "No recent PRs"),
                    "total_prs": pr_data.get("total_prs", 0),
                    "prs_by_type": pr_data.get("prs_by_type", {}),
                    "collection_stats": self._collection_stats,
                    "tomorrow_workout": self._format_workout(tomorrow_workout) if tomorrow_workout else "No workout scheduled",
                    "tomorrow_workout_details": tomorrow_workout
                }

                self._first_update_done = True
                self._last_update_time = now

                # PHASE 2: Start Historical Load
                if not self._historical_load_done and not self._historical_load_in_progress:
                    _LOGGER.info("🕰️ PHASE 2: Starting background historical load...")
                    self._hass.async_create_task(self._load_historical_data())

                return initial_data

            # PHASE 3: Regular Incremental Updates
            else:
                _LOGGER.debug("🔄 PHASE 3: Incremental update...")
                self._collection_stats["current_phase"] = "incremental"
                
                # Get recent data (2 days)
                update_start = now - timedelta(days=2)
                next_session = await self.google_calendar.get_next_session()
                pr_data = await self._hass.async_add_executor_job(
                    self.pr_handler.get_formatted_prs
                )
                
                # Get recent calendar events
                recent_events = await self.google_calendar.get_calendar_events(
                    start_date=update_start,
                    end_date=now
                )
                
                if recent_events:
                    self._collection_stats["new_sessions_today"] = len(recent_events)
                    self._collection_stats["update_streak"] += 1
                    
                    if len(recent_events) > 0:
                        _LOGGER.info("🎉 Found %d new sessions! Streak: %d days", 
                                   len(recent_events), 
                                   self._collection_stats["update_streak"])

                return {
                    **self.data,
                    "next_session": next_session,
                    "recent_prs": pr_data.get("recent_prs", "No recent PRs"),
                    "prs_by_type": pr_data.get("prs_by_type", {}),
                    "collection_stats": self._collection_stats,
                    "tomorrow_workout": self._format_workout(tomorrow_workout) if tomorrow_workout else "No workout scheduled",
                    "tomorrow_workout_details": tomorrow_workout
                }

        except Exception as err:
            self._collection_stats["update_streak"] = 0
            _LOGGER.error("💥 Update failed: %s", str(err))
            raise

    def _reconcile_sessions(self, zenplanner_data: dict, calendar_events: list) -> int:
        """Reconcile session counts between ZenPlanner and Google Calendar."""
        try:
            zen_dates = set()
            if isinstance(zenplanner_data, dict) and "all_sessions" in zenplanner_data:
                for session in zenplanner_data["all_sessions"]:
                    if isinstance(session, dict) and "date" in session:
                        zen_dates.add(session["date"])

            calendar_dates = set()
            if isinstance(calendar_events, list):
                for event in calendar_events:
                    if isinstance(event, dict) and "date" in event:
                        calendar_dates.add(event["date"])

            unique_dates = zen_dates.union(calendar_dates)
            overlapping = zen_dates.intersection(calendar_dates)

            _LOGGER.debug(
                "Session reconciliation - ZenPlanner: %d, Calendar: %d, Unique: %d, Overlap: %d",
                len(zen_dates), len(calendar_dates), len(unique_dates), len(overlapping)
            )

            return len(unique_dates)

        except Exception as err:
            _LOGGER.error("Error reconciling sessions: %s", str(err))
            return 0

    def _format_workout(self, workout: Optional[dict]) -> str:
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

    async def _async_stop(self) -> None:
        """Clean up resources when stopping."""
        await self.google_calendar.close()
        await super()._async_stop()

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
        data = self.coordinator.data or {}

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
                    "date_achieved": prs.get("date")
                })

        # Tomorrow's workout attributes
        if self.entity_description.key == "tomorrow_workout":
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
                "loading_status": "complete"
            })
            
            if "collection_stats" in data:
                attrs.update({
                    "new_sessions_today": data["collection_stats"].get("new_sessions_today", 0),
                    "update_streak": data["collection_stats"].get("update_streak", 0),
                    "last_full_update": data["collection_stats"].get("last_full_update"),
                    "current_phase": data["collection_stats"].get("current_phase", "unknown"),
                    "phase_description": self._get_phase_description(
                        data["collection_stats"].get("current_phase", "unknown")
                    )
                })
            
            if "calendar_events" in data:
                today = datetime.now().date()
                week_start = today - timedelta(days=today.weekday())
                week_sessions = sum(
                    1 for session in data["calendar_events"]
                    if datetime.strptime(session['date'], '%Y-%m-%d').date() >= week_start
                )
                attrs["sessions_this_week"] = week_sessions

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


    def _get_phase_description(self, phase: str) -> str:
        """Get a user-friendly description of the current phase."""
        phase_descriptions = {
            "init": "🚀 Starting up...",
            "quick_load": "⚡ Loading last 30 days",
            "historical_load": "📚 Loading historical data in background",
            "historical_load_failed": "❌ Historical load failed - using recent data only",
            "incremental": "✅ Regular updates active",
            "unknown": "❓ Status unknown"
        }
        return phase_descriptions.get(phase, "❓ Status unknown")