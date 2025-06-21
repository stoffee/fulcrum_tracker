"""Sensor platform for Fulcrum Tracker integration - FIXED VERSION."""
from __future__ import annotations

import asyncio
import json
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
    # Cost Analysis Sensors
    SensorEntityDescription(
        key="training_tco",
        name="Total Training Cost",
        icon="mdi:cash",
        native_unit_of_measurement="$",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="training_cost_per_class",
        name="Cost Per Class",
        icon="mdi:calculator",
        native_unit_of_measurement="$/class",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="training_session_metrics",
        name="Training Session Metrics",
        icon="mdi:clipboard-text-clock",
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

    _LOGGER.info("Starting setup of Fulcrum Tracker sensors with user: %s", username)
    _LOGGER.info("Calendar ID: %s", calendar_id)
    _LOGGER.info("Service account path exists: %s", service_account_path and hass.config.is_allowed_path(service_account_path))

    try:
        # Initialize API handlers - no more person_id/client_id needed!
        auth = ZenPlannerAuth(username, password)
        calendar = ZenPlannerCalendar(auth)
        # PR handler will auto-detect user ID after login
        pr_handler = PRHandler(auth, user_id=None)  # Let it auto-detect
        google_calendar = AsyncGoogleCalendarHandler(service_account_path, calendar_id)
        matrix_handler = MatrixCalendarHandler(google_calendar)
        
        # Get storage from domain data
        storage = hass.data[DOMAIN][config_entry.entry_id]["storage"]

        _LOGGER.info("Storage retrieved with historical load status: %s", storage.historical_load_done)

        # Pre-populate coordinator with stored data if available
        initial_data = None
        if storage.historical_load_done:
            # Create minimal data structure from storage
            initial_data = {
                "total_fulcrum_sessions": storage.total_sessions,
                "collection_stats": {
                    "total_sessions": storage.total_sessions,
                    "current_phase": storage.initialization_phase,
                    "last_update": storage.last_update,
                    "fast_startup": True
                }
            }
            
            # Add trainer session counts if available
            trainer_counts = storage.get_all_trainer_sessions()
            for trainer, count in trainer_counts.items():
                key = f"trainer_{trainer}_sessions"
                initial_data[key] = count
                
            _LOGGER.info("🔍 Pre-populated with stored data (total sessions: %s)", storage.total_sessions)

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
        
        # If we have initial data, set it on the coordinator
        if initial_data:
            coordinator.data = initial_data
    except Exception as err:
        _LOGGER.error("Failed to initialize API handlers: %s", str(err))
        raise

    # Store the coordinator reference
    hass.data[DOMAIN][config_entry.entry_id]["coordinator"] = coordinator

    _LOGGER.info("Coordinator created successfully")

    try:
        # Create the entities
        entities = []
        entity_ids = set()  # Track entity IDs to avoid duplicates
        
        for description in SENSOR_TYPES:
            # Create a unique ID for this entity
            entity_id = f"{config_entry.entry_id}_{description.key}"
            
            # Only add the entity if we haven't seen this ID before
            if entity_id not in entity_ids:
                entities.append(
                    FulcrumSensor(
                        coordinator=coordinator,
                        description=description,
                        config_entry=config_entry,
                    )
                )
                entity_ids.add(entity_id)
            else:
                _LOGGER.warning("Skipping duplicate entity: %s", description.key)

        _LOGGER.info("Created %d sensor entities", len(entities))
        
        # Add entities immediately using stored data
        async_add_entities(entities)
        _LOGGER.info("✅ Entities successfully added with stored data")
        
        # Schedule the data refresh to happen non-blocking after entities are added
        async def delayed_refresh(delay):
            """Execute a delayed refresh that can be safely interrupted."""
            try:
                _LOGGER.debug("⏰ Waiting %d seconds before refresh", delay.total_seconds())
                # Split sleep into small chunks to allow for cancellation
                for i in range(int(delay.total_seconds())):
                    await asyncio.sleep(1)
                    # Check if task was cancelled
                    if asyncio.current_task().cancelled():
                        _LOGGER.debug("Delayed refresh task cancelled")
                        return
                
                _LOGGER.info("🔄 Starting background data refresh")
                await coordinator.async_refresh()
                _LOGGER.info("✅ Background data refresh completed")
            except asyncio.CancelledError:
                _LOGGER.debug("Delayed refresh task cancelled during execution")
            except Exception as err:
                _LOGGER.error("❌ Background refresh failed: %s", str(err))

        # Schedule the refresh but don't block setup
        if storage.historical_load_done:
            # Existing installation - longer delay to prioritize HA startup
            delay = timedelta(minutes=5)
            _LOGGER.info("🔍 Scheduling background refresh in %d minutes", delay.total_seconds() / 60)
            hass.async_create_task(delayed_refresh(delay))
        else:
            # New installation - shorter delay but still non-blocking
            delay = timedelta(seconds=30)
            _LOGGER.info("🔄 New installation - scheduling initial data load in %d seconds", delay.total_seconds())
            hass.async_create_task(delayed_refresh(delay))
        
    except Exception as err:
        _LOGGER.error("Error creating entities: %s", str(err))
        raise

    _LOGGER.info("⚡ Fulcrum Tracker setup completed - data will refresh in background")


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
    def available(self) -> bool:
        """Return True if entity is available."""
        # Always return True to prevent "unavailable" state
        return True

    @property
    def native_value(self) -> StateType:
        """Return the state of the sensor with ROBUST defaults."""
        _LOGGER.debug("🔍 Getting native_value for %s", self.entity_description.key)
        
        # Handle cost analysis sensors with GUARANTEED numeric returns
        if self.entity_description.key == "training_tco":
            try:
                # Fixed payment data - always returns a number
                payments = [
                    (1892.10, datetime(2023, 4, 4).timestamp()),
                    (1892.10, datetime(2022, 7, 7).timestamp()),
                    (96.00, datetime(2021, 11, 8).timestamp())
                ]
                return round(sum(payment[0] for payment in payments), 2)
            except Exception as err:
                _LOGGER.error("Error calculating TCO: %s", str(err))
                return 3880.20  # Fallback to known total
            
        elif self.entity_description.key == "training_cost_per_class":
            try:
                if self.coordinator.data is None:
                    return 31.54  # Reasonable fallback value
                    
                sessions = self.coordinator.data.get("total_fulcrum_sessions", 0)
                if not sessions or sessions == 0:
                    return 31.54  # Reasonable default if no sessions yet
                    
                start_date = datetime(2023, 9, 15).timestamp()
                monthly_cost = 315.35
                months_active = round((datetime.now().timestamp() - start_date) / (60*60*24*30), 1)
                total_cost = monthly_cost * months_active
                
                result = round(total_cost / sessions, 2)
                return result if result > 0 else 31.54
            except Exception as err:
                _LOGGER.error("Error calculating cost per class: %s", str(err))
                return 31.54  # Always return a reasonable number
        
        # Handle tomorrow's workout with TEMPLATE-SAFE format
        elif self.entity_description.key == "tomorrow_workout":
            try:
                if self.coordinator.data is None:
                    return "Unknown | No workout scheduled"  # Template-safe format
                
                workout = self.coordinator.data.get("tomorrow_workout_details")
                if workout and isinstance(workout, dict):
                    display_format = workout.get('display_format', '')
                    if display_format and '|' in display_format:
                        return display_format
                    # Fallback formatting - ALWAYS include the pipe
                    workout_type = workout.get('type', 'Unknown')
                    lifts = workout.get('lifts', 'Not specified')
                    return f"{workout_type} | {lifts}"
                
                # CRITICAL: Always return template-safe format with pipe
                return "No Workout | Scheduled"
            except Exception as err:
                _LOGGER.error("Error formatting workout: %s", str(err))
                return "Error | Loading workout"
        
        # Handle other cases
        if self.coordinator.data is None:
            # Return proper defaults based on sensor type
            if self.entity_description.key == "total_fulcrum_sessions":
                stored_count = self.coordinator.storage.total_sessions
                _LOGGER.debug("Using stored session count as default: %s", stored_count)
                return stored_count or 0
            
            # Better defaults for PR sensors
            elif self.entity_description.key.startswith("pr_"):
                return "No PR recorded"  # Simple default
                
            # Default for other numeric sensors
            elif hasattr(self.entity_description, 'native_unit_of_measurement'):
                return 0  # Return 0 for numeric sensors
            
            # Default for text sensors
            else:
                return "Loading..."

        # Add debug logging for total_fulcrum_sessions
        if self.entity_description.key == "total_fulcrum_sessions":
            _LOGGER.info("📊 Total Fulcrum Sessions sensor received data: %s", 
                        self.coordinator.data.get("total_fulcrum_sessions"))
            
        # Handle PR sensors
        if self.entity_description.key.startswith("pr_"):
            exercise_type = self.entity_description.key[3:]
            prs = self.coordinator.data.get("prs_by_type", {})
            if exercise_type in prs and prs[exercise_type]:
                return prs[exercise_type].get("value", "No PR recorded")
            return "No PR recorded"
            
        # Format next session nicely if that's what we're showing
        if self.entity_description.key == "next_session" and self.coordinator.data.get("next_session"):
            next_session = self.coordinator.data["next_session"]
            return f"{next_session['date']} {next_session['time']} with {next_session['instructor']}"

        elif self.entity_description.key == "training_session_metrics":
            # Return JSON data that can be parsed in templates
            try:
                start_date = datetime(2023, 9, 15).timestamp()
                sessions_attended = self.coordinator.data.get("total_fulcrum_sessions", 0)
                monthly_cost = 315.35
                months_active = round((datetime.now().timestamp() - start_date) / (60*60*24*30), 1)
                total_cost = monthly_cost * months_active
                actual_cost = total_cost / sessions_attended if sessions_attended > 0 else 0
                
                return json.dumps({
                    "sessions_attended": sessions_attended,
                    "months_active": months_active,
                    "total_cost": round(total_cost, 2),
                    "actual_cost": round(actual_cost, 2)
                })
            except Exception as err:
                _LOGGER.error("Error calculating training metrics: %s", str(err))
                return json.dumps({
                    "sessions_attended": 0,
                    "months_active": 0,
                    "total_cost": 0,
                    "actual_cost": 0
                })
            
        value = self.coordinator.data.get(self.entity_description.key)
        if value is None:
            # Return appropriate defaults based on sensor type
            if hasattr(self.entity_description, 'native_unit_of_measurement'):
                return 0  # Numeric sensors get 0
            else:
                return "Loading..."  # Text sensors get Loading
        return value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return entity specific state attributes."""
        attrs = {}

        # If we don't have coordinator data yet, return minimal defaults
        if self.coordinator.data is None:
            return {"loading_status": "initializing"}
            
        data = self.coordinator.data or {}

        # PR-specific attributes
        if self.entity_description.key.startswith("pr_"):
            exercise_type = self.entity_description.key[3:]
            prs = self.coordinator.data.get("prs_by_type", {}).get(exercise_type, {})
            if prs:
                attrs.update({
                    "last_attempt": prs.get("last_result", "Unknown"),
                    "days_since": prs.get("days_since", "Unknown"),
                    "attempts": prs.get("attempts", 0),
                    "date_achieved": prs.get("date", "Unknown"),
                    "loading_status": "complete"
                })
            else:
                attrs.update({
                    "last_attempt": "No data",
                    "days_since": "N/A",
                    "attempts": 0,
                    "date_achieved": "Never",
                    "loading_status": "no_data"
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
                    "loading_status": "complete"
                })
            else:
                attrs.update({
                    "workout_type": "None",
                    "lifts": "No workout scheduled",
                    "meps_target": "N/A",
                    "raw_summary": "No workout data available",
                    "loading_status": "no_data"
                })

        # Total sessions attributes
        elif self.entity_description.key == "total_fulcrum_sessions":
            attrs.update({
                "sessions_this_month": data.get("monthly_sessions", 0),
                "last_session_date": data.get("last_session", "Unknown"),
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
                
        # Cost analysis attributes
        elif self.entity_description.key == "training_tco":
            attrs.update({
                "payments": [
                    {"amount": 1892.10, "date": "2023-04-04"},
                    {"amount": 1892.10, "date": "2022-07-07"},
                    {"amount": 96.00, "date": "2021-11-08"}
                ],
                "loading_status": "complete"
            })
            
        elif self.entity_description.key == "training_cost_per_class":
            try:
                start_date = datetime(2023, 9, 15)
                sessions = self.coordinator.data.get("total_fulcrum_sessions", 0)
                monthly_cost = 315.35
                months_active = round((datetime.now().timestamp() - start_date.timestamp()) / (60*60*24*30), 1)
                total_cost = monthly_cost * months_active
                
                attrs.update({
                    "start_date": "2023-09-15",
                    "monthly_cost": monthly_cost,
                    "months_active": months_active,
                    "total_cost": round(total_cost, 2),
                    "total_sessions": sessions,
                    "loading_status": "complete"
                })
            except Exception as err:
                _LOGGER.error("Error calculating cost attributes: %s", str(err))
                attrs.update({"loading_status": "error", "error": str(err)})
                
        elif self.entity_description.key == "training_session_metrics":
            try:
                start_date = datetime(2023, 9, 15).timestamp()
                sessions_attended = self.coordinator.data.get("total_fulcrum_sessions", 0)
                monthly_cost = 315.35
                months_active = round((datetime.now().timestamp() - start_date) / (60*60*24*30), 1)
                total_cost = monthly_cost * months_active
                
                attrs.update({
                    "sessions_attended": sessions_attended,
                    "months_active": months_active,
                    "total_cost": round(total_cost, 2),
                    "actual_cost": round(total_cost / sessions_attended, 2) if sessions_attended > 0 else 0,
                    "monthly_cost": monthly_cost,
                    "start_date": "2023-09-15",
                    "loading_status": "complete"
                })
            except Exception as err:
                _LOGGER.error("Error calculating metrics attributes: %s", str(err))
                attrs.update({"loading_status": "error", "error": str(err)})

        return attrs