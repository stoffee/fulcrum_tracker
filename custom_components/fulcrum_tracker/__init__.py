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
    try:
        hass.data.setdefault(DOMAIN, {})
        
        # Store the credentials and setup state
        hass.data[DOMAIN][entry.entry_id] = {
            "username": entry.data["username"],
            "password": entry.data["password"],
            "setup_complete": False,
            "last_update": None,
            "update_failures": 0,
        }
        
        async def scheduled_update(now: datetime) -> None:
            """Handle the scheduled daily update."""
            try:
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
                        
                        if coordinator.data.get("collection_stats", {}).get("new_sessions_today", 0) > 0:
                            _LOGGER.info("💪 Found %d new sessions today!", 
                                    coordinator.data["collection_stats"]["new_sessions_today"])
                        
                    except Exception as err:
                        entry_data["update_failures"] += 1
                        _LOGGER.error("❌ Scheduled update failed: %s", str(err))
                        
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
            except Exception as err:
                _LOGGER.error("Error in scheduled update: %s", str(err))
        
        async def delayed_setup() -> None:
            """Perform delayed setup tasks."""
            try:
                await asyncio.sleep(120)  # 2 minute delay
                await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
                entry_data = hass.data[DOMAIN][entry.entry_id]
                entry_data["setup_complete"] = True
                _LOGGER.info("✨ Initial setup completed for Fulcrum Tracker")
                
                # Schedule daily update only after setup is complete
                async_track_time_change(
                    hass,
                    scheduled_update,
                    hour=UPDATE_TIME_HOUR,
                    minute=UPDATE_TIME_MINUTE,
                    second=0,
                    timezone=UPDATE_TIMEZONE
                )
            except Exception as err:
                _LOGGER.error("Error in delayed setup: %s", str(err))
                raise
        
        # Start initial setup
        hass.async_create_task(delayed_setup())
        
        return True

    except Exception as err:
        _LOGGER.error("Failed to set up Fulcrum Tracker: %s", str(err))
        raise

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    try:
        if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
            hass.data[DOMAIN].pop(entry.entry_id)
        return unload_ok
    except Exception as err:
        _LOGGER.error("Error unloading Fulcrum Tracker: %s", str(err))
        return False