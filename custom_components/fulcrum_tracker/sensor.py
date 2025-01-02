"""Sensor platform for Fulcrum Tracker integration."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
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

SENSOR_TYPES: tuple[SensorEntityDescription, ...] = (
    # Trainer session counts
    *TRAINER_SENSORS,
    # Source-specific session counts
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
    # Combined total
    SensorEntityDescription(
        key="total_fulcrum_sessions",
        name="Total Fulcrum Sessions",
        icon="mdi:dumbbell-variant",
        native_unit_of_measurement="sessions",
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    # Time-based metrics
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
    # Performance metrics
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
)

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Fulcrum Tracker sensors."""
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

    await coordinator.async_config_entry_first_refresh()

    entities = [
        FulcrumSensor(
            coordinator=coordinator,
            description=description,
            config_entry=config_entry,
        )
        for description in SENSOR_TYPES
    ]

    _LOGGER.debug("Created %d sensor entities including %d trainer sensors", 
                len(entities), len(TRAINER_SENSORS))

    async_add_entities(entities)

class FirstRunHandler:
    """Handle first run detection and initialization."""
    
    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the handler."""
        self.hass = hass
        self._storage_key = f"{DOMAIN}.first_run_completed"
        
    async def is_first_run(self) -> bool:
        """Check if this is the first run."""
        return not await self.hass.helpers.storage.async_storage_get(self._storage_key)
        
    async def mark_initialized(self, stats: dict) -> None:
        """Mark system as initialized with initial stats."""
        await self.hass.helpers.storage.async_storage_set(
            self._storage_key,
            {
                "initialized_at": datetime.now().isoformat(),
                "initial_stats": stats,
                "version": 1
            }
        )
        
    async def get_initialization_stats(self) -> Optional[dict]:
        """Get stats from when system was first initialized."""
        data = await self.hass.helpers.storage.async_storage_get(self._storage_key)
        return data if data else None

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
        _LOGGER.debug("Coordinator initialized with trainers: %s", TRAINERS)

    def _process_trainer_stats(self, calendar_events: list) -> dict:
        """Process trainer statistics from calendar events."""
        trainer_stats = {f"trainer_{name.lower()}_sessions": 0 for name in TRAINERS}
        _LOGGER.debug("Initial trainer stats keys: %s", list(trainer_stats.keys()))
        
        for event in calendar_events:
            if 'instructor' in event:
                instructor = event['instructor'].strip().split()[0]  # Get first name
                key = f"trainer_{instructor.lower()}_sessions"
                _LOGGER.debug("Processing instructor: %s -> key: %s", instructor, key)
                if key in trainer_stats:
                    trainer_stats[key] += 1
                else:
                    _LOGGER.warning("Unrecognized trainer key: %s", key)
        
        _LOGGER.debug("Final trainer stats: %s", trainer_stats)
        return trainer_stats

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            _LOGGER.debug("Starting data update")
            
            attendance_task = self._hass.async_add_executor_job(
                self.calendar.get_attendance_data
            )
            pr_task = self._hass.async_add_executor_job(
                self.pr_handler.get_formatted_prs
            )
            calendar_task = self.google_calendar.get_calendar_events()
            next_session_task = self.google_calendar.get_next_session()
            
            attendance_data, pr_data, calendar_events, next_session = await asyncio.gather(
                attendance_task, pr_task, calendar_task, next_session_task,
            )

            _LOGGER.debug("Data fetched - Calendar events: %d", 
                       len(calendar_events) if calendar_events else 0)

            # Process trainer stats
            trainer_stats = self._process_trainer_stats(calendar_events if calendar_events else [])

            data = {
                **trainer_stats,  # Include trainer session counts
                "zenplanner_fulcrum_sessions": attendance_data.get("total_sessions", 0),
                "google_calendar_fulcrum_sessions": len(calendar_events) if calendar_events else 0,
                "total_fulcrum_sessions": self._reconcile_sessions(attendance_data, calendar_events),
                "monthly_sessions": attendance_data.get("monthly_sessions", 0),
                "last_session": attendance_data.get("last_session"),
                "next_session": next_session,
                "recent_prs": pr_data.get("recent_prs", "No recent PRs"),
                "total_prs": pr_data.get("total_prs", 0)
            }

            _LOGGER.debug("Update complete. Trainer stats: %s", 
                       {k: v for k, v in data.items() if k.startswith('trainer_')})
            return data

        except Exception as err:
            _LOGGER.error("Error fetching data: %s", str(err))
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

    async def async_setup_entry(
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        async_add_entities: AddEntitiesCallback,
    ) -> None:
        """Set up the Fulcrum Tracker sensors."""
        first_run_handler = FirstRunHandler(hass)
        
        coordinator = FulcrumDataUpdateCoordinator(
            hass=hass,
            logger=_LOGGER,
            name="fulcrum_tracker",
            first_run_handler=first_run_handler
        )
        
        # Initialize on first run
        if await first_run_handler.is_first_run():
            _LOGGER.info("First run detected - performing full data load")
            await coordinator.async_do_full_load()
        
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

    async def _async_stop(self) -> None:
        """Clean up resources when stopping."""
        await self.google_calendar.close()
        await super()._async_stop()

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
            model="Training Tracker",
        )

    @property
    def native_value(self) -> StateType:
        """Return the state of the sensor."""
        if self.coordinator.data is None:
            return None
            
        # Format next session nicely if that's what we're showing
        if self.entity_description.key == "next_session" and self.coordinator.data.get("next_session"):
            next_session = self.coordinator.data["next_session"]
            return f"{next_session['date']} {next_session['time']} with {next_session['instructor']}"
            
        value = self.coordinator.data.get(self.entity_description.key)
        _LOGGER.debug("Sensor %s value: %s", self.entity_description.key, value)
        return value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return entity specific state attributes."""
        attrs = {}
        data = self.coordinator.data or {}

        # Add detailed attributes based on sensor type
        if self.entity_description.key == "total_fulcrum_sessions":
            attrs["sessions_this_month"] = data.get("monthly_sessions", 0)
            attrs["last_session_date"] = data.get("last_session")
            attrs["calendar_total"] = data.get("google_calendar_fulcrum_sessions", 0)
            
            if "calendar_events" in data:
                today = datetime.now().date()
                week_start = today - timedelta(days=today.weekday())
                week_sessions = sum(
                    1 for session in data["calendar_events"]
                    if datetime.strptime(session['date'], '%Y-%m-%d').date() >= week_start
                )
                attrs["sessions_this_week"] = week_sessions

        elif self.entity_description.key == "next_session" and data.get("next_session"):
            next_session = data["next_session"]
            attrs.update({
                "instructor": next_session.get("instructor", "Unknown"),
                "location": next_session.get("location", ""),
                "description": next_session.get("description", ""),
                "event_id": next_session.get("event_id", ""),
            })

        elif self.entity_description.key.startswith("trainer_"):
            # Add trainer-specific attributes if available
            trainer_name = self.entity_description.key.split("_")[1]
            if f"trainer_{trainer_name}_sessions" in data:
                attrs["total_sessions"] = data[f"trainer_{trainer_name}_sessions"]

        return attrs