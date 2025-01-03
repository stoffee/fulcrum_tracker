"""The Fulcrum Fitness Tracker integration."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_change

from .const import (
    DOMAIN,
    UPDATE_TIME_HOUR,
    UPDATE_TIME_MINUTE,
    UPDATE_TIMEZONE,
    UPDATE_MAX_RETRIES,
)

_LOGGER = logging.getLogger(__name__)
PLATFORMS: list[Platform] = [Platform.SENSOR]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Fulcrum Tracker from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    
    # Store the credentials
    hass.data[DOMAIN][entry.entry_id] = {
        "username": entry.data["username"],
        "password": entry.data["password"],
        "setup_complete": False,  # Track setup state
        "last_update": None,  # Track last successful update
        "update_failures": 0,  # Track consecutive failures
    }
    
    # Do initial setup after delay
    async def delayed_setup() -> None:
        await asyncio.sleep(120)  # 2 minute delay
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        hass.data[DOMAIN][entry.entry_id]["setup_complete"] = True
        _LOGGER.info("Initial setup completed for Fulcrum Tracker")
    
    # Schedule daily update at 7pm PST
    async def scheduled_update(now: datetime) -> None:
        """Handle the scheduled daily update."""
        entry_data = hass.data[DOMAIN][entry.entry_id]
        if not entry_data["setup_complete"]:
            _LOGGER.debug("Skipping scheduled update - setup not complete")
            return
            
        coordinator = entry_data.get("coordinator")
        if coordinator:
            try:
                await coordinator.async_refresh()
                entry_data["last_update"] = datetime.now(ZoneInfo(UPDATE_TIMEZONE))
                entry_data["update_failures"] = 0
                _LOGGER.info("🎉 Scheduled update completed successfully!")
                
                # Log any new sessions found
                if coordinator.data.get("collection_stats", {}).get("new_sessions_today", 0) > 0:
                    _LOGGER.info("💪 Found %d new sessions today!", 
                               coordinator.data["collection_stats"]["new_sessions_today"])
                
            except Exception as err:
                entry_data["update_failures"] += 1
                _LOGGER.error("❌ Scheduled update failed: %s", str(err))
                
                # Add notification for repeated failures
                if entry_data["update_failures"] >= UPDATE_MAX_RETRIES:
                    await hass.services.async_call(
                        "persistent_notification",
                        "create",
                        {
                            "title": "Fulcrum Tracker Update Failed",
                            "message": (
                                f"Fulcrum Tracker update failed {entry_data['update_failures']} times.\n"
                                f"Last error: {str(err)}"
                            ),
                            "notification_id": "fulcrum_tracker_update_failed"
                        }
                    )
    
    # Start initial setup
    hass.async_create_task(delayed_setup())
    
    # Schedule daily update
    async_track_time_change(
        hass,
        scheduled_update,
        hour=UPDATE_TIME_HOUR,
        minute=UPDATE_TIME_MINUTE,
        second=0,
        timezone=UPDATE_TIMEZONE
    )
    
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok