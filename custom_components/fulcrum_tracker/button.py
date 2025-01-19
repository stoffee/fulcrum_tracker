"""Button platform for Fulcrum Tracker."""
from __future__ import annotations

import logging
from datetime import datetime

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import FulcrumDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Fulcrum Tracker button."""
    button = FulcrumRefreshButton(hass, config_entry)
    async_add_entities([button], True)

class FulcrumRefreshButton(ButtonEntity):
    """Representation of a Fulcrum Tracker refresh button."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        """Initialize the button."""
        self.hass = hass
        self._attr_unique_id = f"{config_entry.entry_id}_refresh"
        self._attr_name = "Fulcrum Tracker Refresh"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, config_entry.entry_id)},
            name="Fulcrum Fitness",
            manufacturer="Fulcrum Fitness PDX",
            model="Training Tracker"
        )
        self._config_entry = config_entry

    async def async_press(self) -> None:
        """Handle the button press."""
        try:
            # Get coordinator from hass data
            entry_data = self.hass.data[DOMAIN][self._config_entry.entry_id]
            coordinator = entry_data.get("coordinator")
            
            if coordinator:
                # Trigger manual refresh
                await coordinator.manual_refresh()
                # Update button state
                self._attr_available = True
                _LOGGER.info("🔄 Manual refresh triggered successfully")
            else:
                _LOGGER.error("Coordinator not available for manual refresh")
                self._attr_available = False
            
            # Force state update
            self.async_write_ha_state()
            
        except Exception as err:
            _LOGGER.error("Failed to trigger manual refresh: %s", str(err))
            self._attr_available = False
            self.async_write_ha_state()