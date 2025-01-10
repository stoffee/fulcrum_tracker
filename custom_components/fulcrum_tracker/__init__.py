"""The Fulcrum Tracker integration."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time
from zoneinfo import ZoneInfo

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform, EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant, Event
from homeassistant.helpers.event import async_track_time_change
from homeassistant.util.dt import now as dt_now

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
            "tasks": set(),  # New: Track running tasks
        }
        
        async def scheduled_update(now: datetime) -> None:
            """Handle the scheduled daily update."""
            _LOGGER.info(
                "🔄 Starting scheduled daily update at %s", 
                now.astimezone(ZoneInfo(UPDATE_TIMEZONE)).strftime("%Y-%m-%d %H:%M:%S %Z")
            )
            try:
                entry_data = hass.data[DOMAIN][entry.entry_id]
                if not entry_data["setup_complete"]:
                    _LOGGER.debug("Skipping scheduled update - setup not complete")
                    return
                    
                coordinator = entry_data.get("coordinator")
                if coordinator:
                    try:
                        await coordinator.async_refresh()
                        entry_data["last_update"] = dt_now().astimezone(ZoneInfo(UPDATE_TIMEZONE))
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
                _LOGGER.info("✅ Scheduled update completed successfully")
            except Exception as err:
                _LOGGER.error("Error in scheduled update: %s", str(err))

        async def delayed_setup() -> None:
            """Perform delayed setup tasks."""
            try:
                # await asyncio.sleep(20)  # 20 sec delay
                await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
                entry_data = hass.data[DOMAIN][entry.entry_id]
                entry_data["setup_complete"] = True
                _LOGGER.info("✨ Initial setup completed for Fulcrum Tracker")
                
                # Schedule daily update only after setup is complete
                # add debug
                _LOGGER.info(
                    "🕒 Registering daily update for %02d:%02d %s", 
                    UPDATE_TIME_HOUR, 
                    UPDATE_TIME_MINUTE, 
                    UPDATE_TIMEZONE
                )
                async_track_time_change(
                    hass,
                    scheduled_update,
                    hour=UPDATE_TIME_HOUR,
                    minute=UPDATE_TIME_MINUTE,
                    second=0
                )
                _LOGGER.info("✅ Daily update scheduler registered")
            except Exception as err:
                _LOGGER.error("Error in 7pm scheduler: %s", str(err))
                raise

        # New: Handle cleanup of tasks during shutdown
        async def cleanup_tasks() -> None:
            """Clean up running tasks."""
            entry_data = hass.data[DOMAIN][entry.entry_id]
            while entry_data["tasks"]:
                task = entry_data["tasks"].pop()
                if not task.done():
                    _LOGGER.debug("Canceling task during shutdown")
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                    except Exception as err:
                        _LOGGER.error("Error canceling task: %s", str(err))

        # New: Handle shutdown event
        async def handle_shutdown(event: Event) -> None:
            """Handle shutdown event."""
            _LOGGER.info("🛑 Shutting down Fulcrum Tracker integration")
            await cleanup_tasks()

        # Register shutdown handler
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, handle_shutdown)
        
        # Start initial setup and track the task
        setup_task = hass.async_create_task(delayed_setup())
        hass.data[DOMAIN][entry.entry_id]["tasks"].add(setup_task)
        
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