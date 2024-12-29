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

from .const import DOMAIN
from .zenplanner_auth import ZenPlannerAuth
from ...old_app.fetch_classes import ZenPlannerCalendar
from ...old_app.fetch_pr import PRFetcher

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
        key="recent_prs",
        name="Recent PRs",
        icon="mdi:trophy",
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

    # Create auth instance
    auth = ZenPlannerAuth(username, password)

    # Create update coordinator
    coordinator = FulcrumDataUpdateCoordinator(
        hass=hass,
        logger=_LOGGER,
        name="fulcrum_tracker",
        auth=auth,
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
    ) -> None:
        """Initialize."""
        super().__init__(
            hass=hass,
            logger=logger,
            name=name,
            update_interval=UPDATE_INTERVAL,
        )
        self.auth = auth
        self._monthly_cost = 315.35  # Current monthly rate

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
            attendance = await self.hass.async_add_executor_job(
                self._fetch_attendance_data
            )
            data.update(attendance)

            # Fetch PR data
            prs = await self.hass.async_add_executor_job(
                self._fetch_pr_data
            )
            data.update(prs)

            return data

        except Exception as err:
            self.logger.error("Error fetching data: %s", err)
            raise

    def _fetch_attendance_data(self) -> dict[str, Any]:
        """Fetch attendance data from ZenPlanner."""
        try:
            # Use existing fetch_classes functionality
            calendar = ZenPlannerCalendar(self.auth)
            start_date = datetime(2021, 11, 1)  # Your original start date
            history = calendar.fetch_all_history(start_date)
            
            # Calculate current month sessions
            current_month = datetime.now().strftime('%B %Y')
            monthly_sessions = sum(1 for s in history['sessions'] 
                                 if s['month_year'] == current_month)
            
            # Calculate cost per session
            if monthly_sessions > 0:
                cost_per_session = round(self._monthly_cost / monthly_sessions, 2)
            else:
                cost_per_session = self._monthly_cost
            
            return {
                "total_sessions": history['total_sessions'],
                "monthly_sessions": monthly_sessions,
                "cost_per_session": cost_per_session,
                "last_session": history['sessions'][0]['date'] if history['sessions'] else None,
                "trainer_stats": self._calculate_trainer_stats(history['sessions']),
            }
            
        except Exception as err:
            _LOGGER.error("Error fetching attendance data: %s", err)
            return {
                "total_sessions": None,
                "monthly_sessions": None,
                "cost_per_session": None,
                "last_session": None,
                "trainer_stats": {},
            }
            
    def _calculate_trainer_stats(self, sessions: list) -> dict:
        """Calculate statistics per trainer."""
        trainer_counts = {}
        for session in sessions:
            if 'description' in session:
                # Extract trainer name from description
                trainer = self._extract_trainer(session['description'])
                if trainer:
                    trainer_counts[trainer] = trainer_counts.get(trainer, 0) + 1
        return trainer_counts
        
    @staticmethod
    def _extract_trainer(description: str) -> Optional[str]:
        """Extract trainer name from session description."""
        if "Instructor:" in description:
            return description.split("Instructor:")[1].strip()

    def _fetch_pr_data(self) -> dict[str, Any]:
        """Fetch PR data from ZenPlanner."""
        try:
            # Use existing fetch_pr functionality
            pr_fetcher = PRFetcher()
            prs = pr_fetcher.fetch_prs()
            
            # Find recent PRs (last 7 days)
            recent_prs = []
            for pr in prs:
                if pr.get('days') and int(pr['days']) <= 7:
                    recent_prs.append({
                        'name': pr['name'],
                        'value': pr['pr'],
                        'days_ago': pr['days']
                    })
            
            # Format for display
            if recent_prs:
                recent_pr_text = ", ".join(
                    f"{pr['name']}: {pr['value']}" for pr in recent_prs
                )
            else:
                recent_pr_text = "No recent PRs"
            
            return {
                "recent_prs": recent_pr_text,
                "total_prs": len(prs),
                "recent_pr_count": len(recent_prs),
                "pr_details": prs,  # Store full PR details for attributes
            }
            
        except Exception as err:
            _LOGGER.error("Error fetching PR data: %s", err)
            return {
                "recent_prs": "Error fetching PRs",
                "total_prs": None,
                "recent_pr_count": 0,
                "pr_details": [],
            }


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
        
        if self.entity_description.key == "recent_prs":
            if "pr_details" in data:
                attrs["all_prs"] = data["pr_details"]
                attrs["total_prs"] = data["total_prs"]
                attrs["recent_pr_count"] = data["recent_pr_count"]
                
        elif self.entity_description.key == "total_sessions":
            if "trainer_stats" in data:
                attrs["trainer_sessions"] = data["trainer_stats"]
            if "last_session" in data:
                attrs["last_session"] = data["last_session"]
            if "monthly_sessions" in data:
                attrs["current_month_sessions"] = data["monthly_sessions"]
            
        elif self.entity_description.key == "cost_per_session":
            attrs["monthly_cost"] = self.coordinator._monthly_cost
            if "monthly_sessions" in data:
                attrs["monthly_sessions"] = data["monthly_sessions"]

        return attrs