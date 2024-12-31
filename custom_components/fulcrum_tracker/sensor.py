"""Sensor platform for Fulcrum Tracker integration."""
from __future__ import annotations

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
from .api.pr import PRHandler
from .const import (
    DOMAIN,
    DEFAULT_UPDATE_INTERVAL,
    DEFAULT_USER_ID,
)

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(minutes=DEFAULT_UPDATE_INTERVAL)

SENSOR_TYPES: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key="total_sessions",
        name="Total Training Sessions",
        icon="mdi:dumbbell",
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
        key="last_session",
        name="Last Training Session",
        icon="mdi:calendar-clock",
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

    # Create authentication handler
    auth = ZenPlannerAuth(username, password)
    
    # Create data handlers
    calendar = ZenPlannerCalendar(auth)  # Removed hass parameter
    pr_handler = PRHandler(auth, DEFAULT_USER_ID)  # Removed hass parameter

    # Create update coordinator
    coordinator = FulcrumDataUpdateCoordinator(
        hass=hass,
        logger=_LOGGER,
        name="fulcrum_tracker",
        calendar=calendar,
        pr_handler=pr_handler,
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
        self._is_initial_load = True

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from Fulcrum."""
        try:
            # Get calendar/attendance data
            attendance_data = await self.hass.async_add_executor_job(
                self.calendar.get_attendance_data
            )
            
            # Get PR data
            pr_data = await self.hass.async_add_executor_job(
                self.pr_handler.get_formatted_prs
            )

            # Combine all data
            return {
                "total_sessions": attendance_data["total_sessions"],
                "monthly_sessions": attendance_data["monthly_sessions"],
                "last_session": attendance_data["last_session"],
                "recent_prs": pr_data["recent_prs"],
                "total_prs": pr_data["total_prs"],
                "recent_pr_count": pr_data["recent_pr_count"],
                "all_sessions": attendance_data["all_sessions"],
                "pr_details": pr_data["pr_details"],
            }

        except Exception as err:
            self.logger.error("Error fetching data: %s", err)
            raise


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
            
            if "all_sessions" in data:
                # Calculate weekly stats
                today = datetime.now().date()
                week_start = today - timedelta(days=today.weekday())
                week_sessions = sum(
                    1 for session in data["all_sessions"]
                    if datetime.strptime(session['date'], '%Y-%m-%d').date() >= week_start
                )
                attrs["sessions_this_week"] = week_sessions

        elif self.entity_description.key == "recent_prs":
            attrs["total_prs"] = data.get("total_prs", 0)
            attrs["recent_pr_count"] = data.get("recent_pr_count", 0)
            
            if "pr_details" in data:
                # Add most recent PRs with dates
                recent_prs = [
                    pr for pr in data["pr_details"]
                    if pr.get('days') and int(pr['days']) <= 7
                ]
                attrs["recent_pr_details"] = recent_prs

        elif self.entity_description.key == "monthly_sessions":
            if "all_sessions" in data:
                # Add monthly trend
                monthly_counts = {}
                for session in data["all_sessions"]:
                    month = datetime.strptime(session['date'], '%Y-%m-%d').strftime('%Y-%m')
                    monthly_counts[month] = monthly_counts.get(month, 0) + 1
                attrs["monthly_trend"] = monthly_counts

        elif self.entity_description.key == "last_session":
            if "all_sessions" in data and data["all_sessions"]:
                last_session = data["all_sessions"][-1]
                attrs["had_results"] = last_session.get("has_results", False)
                attrs["was_pr"] = last_session.get("is_pr", False)
                attrs["details"] = last_session.get("details", "")

        return attrs