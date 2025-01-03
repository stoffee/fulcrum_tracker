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
    
    # Store the credentials
    hass.data[DOMAIN][entry.entry_id] = {
        "username": entry.data["username"],
        "password": entry.data["password"],
        "setup_complete": False  # Track setup state
    }
    
    # Do initial setup after delay
    async def delayed_setup() -> None:
        await asyncio.sleep(120)  # 2 minute delay
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        hass.data[DOMAIN][entry.entry_id]["setup_complete"] = True
        
    hass.async_create_task(delayed_setup())
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok