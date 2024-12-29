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
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import DOMAIN, CONF_PERSON_ID, CONF_CLIENT_ID
from .zenplanner_auth import ZenPlannerAuth
from .zenplanner_calendar import ZenPlannerCalendar

_LOGGER = logging.getLogger(__name__)

# Update frequency
UPDATE_INTERVAL = timedelta(minutes=30)

# Sensor descriptions
SENSOR_TYPES: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key="total_sessions",
        name="Total Training Sessions",
        icon="mdi:dumbbell",
        native_unit_of_measurement="sessions",
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    SensorEntityDescription(
        key="monthly_attendance",
        name="Monthly Sessions",
        icon="mdi:calendar-check",
        native_unit_of_measurement="sessions",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="cost_per_session",
        name="Cost Per Session",
        icon="mdi:currency-usd",
        native_unit_of_measurement="USD",
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
    person_id = config_entry.data[CONF_PERSON_ID]
    client_id = config_entry.data[CONF_CLIENT_ID]

    # Create auth instance
    auth = ZenPlannerAuth(username, password)

    # Create update coordinator
    coordinator = FulcrumDataUpdateCoordinator(
        hass=hass,
        logger=_LOGGER,
        name="fulcrum_tracker",
        auth=auth,
        person_id=person_id,
        client_id=client_id,
    )

    # Fetch initial data
    await coordinator.async_config_entry_first_refresh()

    # Create entities
    entities: list[FulcrumSensor] = []
    
    for description in SENSOR_TYPES:
        entities.append(FulcrumSensor(coordinator, description, config_entry))

    async_add_entities(entities)


class FulcrumDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching Fulcrum data."""

    def __init__(
        self,
        hass: HomeAssistant,
        logger: logging.Logger,
        name: str,
        auth: ZenPlannerAuth,
        person_id: str,
        client_id: str,
    ) -> None:
        """Initialize."""
        super().__init__(
            hass=hass,
            logger=logger,
            name=name,
            update_interval=UPDATE_INTERVAL,
        )
        self.auth = auth
        self.person_id = person_id
        self.client_id = client_id
        self._monthly_cost = 315.35  # We'll make this configurable later

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from Fulcrum."""
        data = {}
        
        try:
            # Login check
            is_logged_in = await self.hass.async_add_executor_job(
                self.auth.login
            )
            if not is_logged_in:
                raise Exception("Failed to login to ZenPlanner")

            # Fetch attendance data
            calendar = ZenPlannerCalendar(self.auth, self.person_id, self.client_id)
            attendance = await self.hass.async_add_executor_job(
                calendar.get_attendance_data
            )
            
            # Calculate current month sessions
            current_month = datetime.now().strftime('%B %Y')
            monthly_sessions = attendance.get('monthly_sessions', 0)
            
            # Calculate cost per session
            cost_per_session = self._monthly_cost / monthly_sessions if monthly_sessions > 0 else 0
            
            return {
                "total_sessions": attendance.get('total_sessions', 0),
                "monthly_attendance": monthly_sessions,
                "cost_per_session": round(cost_per_session, 2),
                "last_session": attendance.get('last_session'),
                "trainer_stats": attendance.get('trainer_stats', {}),
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
            name="Fulcrum Fitness Tracker",
            manufacturer="Fulcrum Fitness PDX",
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
        
        if self.entity_description.key == "total_sessions":
            if "trainer_stats" in data:
                attrs["trainer_sessions"] = data["trainer_stats"]
            if "last_session" in data:
                attrs["last_session"] = data["last_session"]
            
        elif self.entity_description.key == "cost_per_session":
            attrs["monthly_cost"] = self.coordinator._monthly_cost
            if "monthly_attendance" in data:
                attrs["monthly_sessions"] = data["monthly_attendance"]

        return attrs