"""The Fulcrum Fitness Tracker integration."""
from __future__ import annotations

import asyncio
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)
DOMAIN = "fulcrum_tracker"
PLATFORMS: list[Platform] = [Platform.SENSOR]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Fulcrum Tracker from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    
    hass.data[DOMAIN][entry.entry_id] = {
        "username": entry.data["username"],
        "password": entry.data["password"]
    }
    
    async def delayed_setup(delay: int = 120) -> None:
        """Set up platforms with delay."""
        try:
            await asyncio.sleep(delay)
            await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        except asyncio.CancelledError:
            _LOGGER.debug("Delayed setup was cancelled")
            raise
        except Exception as err:
            _LOGGER.error("Error in delayed setup: %s", err)
            raise
    
    hass.async_create_task(delayed_setup(), f"{DOMAIN}_delayed_setup")
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok