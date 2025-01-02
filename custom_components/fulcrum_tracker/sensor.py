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
)

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(minutes=DEFAULT_UPDATE_INTERVAL)

SENSOR_TYPES: tuple[SensorEntityDescription, ...] = (
    # Source-specific session counts
    SensorEntityDescription(
        key="zenplanner_fulcrum_sessions",
        name="ZenPlanner Fulcrum Sessions",
        icon="mdi:dumbbell",  # Changed to dumbbell for ZenPlanner
        native_unit_of_measurement="sessions",
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    SensorEntityDescription(
        key="google_calendar_fulcrum_sessions",
        name="Google Calendar Fulcrum Sessions",
        icon="mdi:calendar-check",  # Kept calendar for Google Calendar
        native_unit_of_measurement="sessions",
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    # Combined total
    SensorEntityDescription(
        key="total_fulcrum_sessions",
        name="Total Fulcrum Sessions",
        icon="mdi:dumbbell-variant",  # Different dumbbell icon for combined total
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

    # Create data handlers
    auth = ZenPlannerAuth(username, password)
    calendar = ZenPlannerCalendar(auth)
    pr_handler = PRHandler(auth, DEFAULT_USER_ID)
    
    # Initialize Google Calendar handler
    google_calendar = AsyncGoogleCalendarHandler(service_account_path, calendar_id)

    # Create update coordinator
    coordinator = FulcrumDataUpdateCoordinator(
        hass=hass,
        logger=_LOGGER,
        name="fulcrum_tracker",
        calendar=calendar,
        pr_handler=pr_handler,
        google_calendar=google_calendar,
    )

    # Fetch initial data
    await coordinator.async_config_entry_first_refresh()

    # Create entities
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

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from Fulcrum and Google Calendar."""
        try:
            # Create tasks for parallel execution
            attendance_task = self._hass.async_add_executor_job(
                self.calendar.get_attendance_data
            )
            pr_task = self._hass.async_add_executor_job(
                self.pr_handler.get_formatted_prs
            )
            calendar_task = self.google_calendar.get_calendar_events()
            next_session_task = self.google_calendar.get_next_session()

            # Wait for all tasks to complete
            attendance_data, pr_data, calendar_events, next_session = await asyncio.gather(
                attendance_task,
                pr_task,
                calendar_task,
                next_session_task,
            )

            # Combine all data
            return {
                # ZenPlanner data
                "total_sessions": attendance_data["total_sessions"],
                "monthly_sessions": attendance_data["monthly_sessions"],
                "last_session": attendance_data["last_session"],
                "recent_prs": pr_data["recent_prs"],
                "total_prs": pr_data["total_prs"],
                "recent_pr_count": pr_data["recent_pr_count"],
                "all_sessions": attendance_data["all_sessions"],
                "pr_details": pr_data["pr_details"],
                
                # Google Calendar data
                "calendar_events": calendar_events,
                "next_session": next_session,
                "calendar_total_sessions": len(calendar_events) if calendar_events else 0,
            }

        except Exception as err:
            self.logger.error("Error fetching data: %s", err)
            raise

    def _reconcile_sessions(self, zenplanner_data: dict, calendar_events: list) -> int:
        """Reconcile session counts between ZenPlanner and Google Calendar."""
        try:
            # Add debug logging
            _LOGGER.debug("Reconciling sessions - ZenPlanner data type: %s, Calendar events type: %s",
                        type(zenplanner_data), type(calendar_events))
            _LOGGER.debug("ZenPlanner data keys: %s", 
                        list(zenplanner_data.keys()) if isinstance(zenplanner_data, dict) else "Not a dict")
            # Get all session dates from ZenPlanner
            zen_dates = set()
            if "all_sessions" in zenplanner_data:
                for session in zenplanner_data["all_sessions"]:
                    if isinstance(session, dict) and "date" in session:
                        zen_dates.add(session["date"])

            # Get all session dates from Google Calendar
            calendar_dates = set()
            if calendar_events:
                for event in calendar_events:
                    if isinstance(event, dict) and "date" in event:
                        calendar_dates.add(event["date"])

            # Find union of all unique dates
            all_unique_dates = zen_dates.union(calendar_dates)
            
            # Count overlapping dates
            overlapping_dates = zen_dates.intersection(calendar_dates)
            
            _LOGGER.debug(
                "Session reconciliation: ZenPlanner=%d, Calendar=%d, Unique=%d, Overlapping=%d",
                len(zen_dates), len(calendar_dates), len(all_unique_dates), len(overlapping_dates)
            )

            return len(all_unique_dates)
        except Exception as err:
            _LOGGER.error("Error reconciling sessions: %s", str(err))
            return 0

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
            
        return self.coordinator.data.get(self.entity_description.key)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return entity specific state attributes."""
        attrs = {}
        data = self.coordinator.data or {}

        # Add detailed attributes based on sensor type
        if self.entity_description.key == "total_sessions":
            attrs["sessions_this_month"] = data.get("monthly_sessions", 0)
            attrs["last_session_date"] = data.get("last_session")
            attrs["calendar_total"] = data.get("calendar_total_sessions", 0)
            
            if "calendar_events" in data:
                # Calculate weekly stats from both sources
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

        elif self.entity_description.key == "calendar_total_sessions":
            if "calendar_events" in data:
                # Add monthly breakdown
                monthly_counts = {}
                for session in data["calendar_events"]:
                    month = datetime.strptime(session['date'], '%Y-%m-%d').strftime('%Y-%m')
                    monthly_counts[month] = monthly_counts.get(month, 0) + 1
                attrs["monthly_breakdown"] = monthly_counts

        return attrs