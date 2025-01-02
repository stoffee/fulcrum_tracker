"""The Fulcrum Fitness Tracker integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

DOMAIN = "fulcrum_tracker"
PLATFORMS: list[Platform] = [Platform.SENSOR]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Fulcrum Tracker from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    
    # Store config data
    hass.data[DOMAIN][entry.entry_id] = {
        "username": entry.data["username"],
        "password": entry.data["password"]
    }
    
    # Schedule delayed data collection
    async def delayed_setup():
        await asyncio.sleep(120)  # 2 minute delay
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        
    hass.async_create_task(delayed_setup())
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok