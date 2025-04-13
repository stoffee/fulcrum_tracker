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

from .coordinator import FulcrumDataUpdateCoordinator
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

# Define this helper function outside of async_setup_entry so it's accessible
async def async_schedule_delayed_refresh(hass, coordinator, delay):
    """Schedule a delayed refresh after startup."""
    _LOGGER.info("⏰ Scheduling delayed refresh in %s minutes", delay.total_seconds() / 60)
    await asyncio.sleep(delay.total_seconds())
    _LOGGER.info("🔄 Performing delayed incremental refresh")
    await coordinator.async_refresh()

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

    _LOGGER.info("Starting setup of Fulcrum Tracker sensors with user: %s", username)
    _LOGGER.info("Calendar ID: %s", calendar_id)
    _LOGGER.info("Service account path exists: %s", service_account_path and hass.config.is_allowed_path(service_account_path))

    _LOGGER.debug("Setting up sensors with calendar_id: %s", calendar_id)

    # Initialize API handlers
    auth = ZenPlannerAuth(username, password)
    calendar = ZenPlannerCalendar(auth)
    pr_handler = PRHandler(auth, DEFAULT_USER_ID)
    google_calendar = AsyncGoogleCalendarHandler(service_account_path, calendar_id)
    matrix_handler = MatrixCalendarHandler(google_calendar)
    
    # Get storage from domain data
    storage = hass.data[DOMAIN][config_entry.entry_id]["storage"]

    _LOGGER.info("Storage retrieved with historical load status: %s", storage.historical_load_done)


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

    # this line stores the coordinator reference
    hass.data[DOMAIN][config_entry.entry_id]["coordinator"] = coordinator

    _LOGGER.info("Coordinator created successfully")

    # First load cached data if available
    if storage.historical_load_done:
        _LOGGER.info("🔍 Using cached data from storage for initial setup")
        # Create a background task for delayed refresh (5 minutes later)
        hass.async_create_task(
            async_schedule_delayed_refresh(hass, coordinator, timedelta(minutes=5))
        )
    else:
        # Only force refresh for new installations
        _LOGGER.info("🔄 New installation - performing initial data load")
        await coordinator.async_config_entry_first_refresh()

    entities = [
        FulcrumSensor(
            coordinator=coordinator,
            description=description,
            config_entry=config_entry,
        )
        for description in SENSOR_TYPES
    ]

    async_add_entities(entities)

    _LOGGER.info("Created %d sensor entities", len(entities))

    _LOGGER.info("🔄 Adding %d Fulcrum entities to Home Assistant", len(entities))
    async_add_entities(entities)
    _LOGGER.info("✅ Entities successfully added")

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
        _LOGGER.debug("🔍 Getting native_value for %s", self.entity_description.key)
        if self.coordinator.data is None:
            _LOGGER.debug("⚠️ Coordinator data is None for %s", self.entity_description.key)
            # Return a valid default for total_fulcrum_sessions
            if self.entity_description.key == "total_fulcrum_sessions":
                stored_count = self.coordinator.storage.total_sessions
                _LOGGER.debug("Using stored session count as default: %s", stored_count)
                return stored_count or 0
            
            # Defaults for other sensors...
            default_state = SensorDefaults.get_loading_state(self.entity_description.key)
            return default_state["state"]

        # Add debug logging for total_fulcrum_sessions
        if self.entity_description.key == "total_fulcrum_sessions":
            _LOGGER.info("📊 Total Fulcrum Sessions sensor received data: %s", 
                        self.coordinator.data.get("total_fulcrum_sessions"))
            
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
                    "workout_type": workout.get('type', 'Unknown'),
                    "lifts": workout.get('lifts', 'Not specified'),
                    "meps_target": workout.get('meps', 'Not specified'),
                    "raw_summary": workout.get('raw_summary', ''),
                    "created_by": workout.get('created_by', 'Unknown'),
                    "last_updated": workout.get('last_updated', None),
                    "loading_status": "complete"
                })
                _LOGGER.debug("📊 Workout attributes updated: %s", attrs)

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