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
from .storage import FulcrumTrackerStore

_LOGGER = logging.getLogger(__name__)
PLATFORMS: list[Platform] = [Platform.SENSOR]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Fulcrum Tracker from a config entry."""
    try:
        hass.data.setdefault(DOMAIN, {})
        
        # Initialize storage
        storage = FulcrumTrackerStore(hass)
        await storage.async_load()
        
        # Store the credentials, setup state, and storage
        hass.data[DOMAIN][entry.entry_id] = {
            "username": entry.data["username"],
            "password": entry.data["password"],
            "setup_complete": False,
            "last_update": None,
            "update_failures": 0,
            "tasks": set(),  # Track running tasks
            "storage": storage,  # Add storage handler
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
                        current_time = dt_now().astimezone(ZoneInfo(UPDATE_TIMEZONE))
                        entry_data["last_update"] = current_time
                        
                        # Update storage with latest update time and session data
                        await entry_data["storage"].async_record_update(
                            current_time.isoformat()
                        )
                        if coordinator.data:
                            await entry_data["storage"].async_update_session_count(
                                coordinator.data.get("total_fulcrum_sessions", 0)
                            )
                        
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
            """Perform delayed setup tasks with optimized phase handling."""
            try:
                entry_data = hass.data[DOMAIN][entry.entry_id]
                storage = entry_data["storage"]
                _LOGGER.info("🚀 Starting Fulcrum Tracker setup...")

                # First, check if platforms need setup
                if not entry_data.get("platforms_setup"):
                    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
                    entry_data["platforms_setup"] = True
                    _LOGGER.debug("✅ Platforms initialized")

                # Determine initialization phase from storage
                current_phase = storage.initialization_phase
                _LOGGER.info("📊 Current initialization phase: %s", current_phase)

                if current_phase == "init":
                    _LOGGER.info("🆕 First run detected - preparing for historical load")
                    await storage.async_update_data({
                        "initialization_phase": "historical_load",
                        "first_setup_time": dt_now().isoformat()
                    })
                elif current_phase == "historical_load" and not storage.historical_load_done:
                    _LOGGER.info("📚 Resuming interrupted historical data load")
                else:
                    _LOGGER.info("♻️ Entering incremental update mode")
                    await storage.async_update_data({
                        "initialization_phase": "incremental"
                    })

                # Setup is complete, schedule daily updates
                if not entry_data.get("scheduler_setup"):
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
                    entry_data["scheduler_setup"] = True
                    _LOGGER.info("✅ Daily update scheduler registered")

                entry_data["setup_complete"] = True
                await storage.async_update_data({
                    "setup_complete": True,
                    "last_setup_time": dt_now().isoformat()
                })

                _LOGGER.info("✨ Fulcrum Tracker setup completed in %s phase", storage.initialization_phase)

            except Exception as err:
                _LOGGER.error("💥 Error in delayed setup: %s", str(err))
                raise

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

        async def handle_shutdown(event: Event) -> None:
            """Handle shutdown event."""
            _LOGGER.info("🛑 Shutting down Fulcrum Tracker integration")
            entry_data = hass.data[DOMAIN][entry.entry_id]
            # Save final state to storage
            if "storage" in entry_data:
                await entry_data["storage"].async_save()
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
            # Save final state before unloading
            entry_data = hass.data[DOMAIN][entry.entry_id]
            if "storage" in entry_data:
                await entry_data["storage"].async_save()
            hass.data[DOMAIN].pop(entry.entry_id)
        return unload_ok
    except Exception as err:
        _LOGGER.error("Error unloading Fulcrum Tracker: %s", str(err))
        return False