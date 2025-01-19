"""Coordinator for Fulcrum Tracker integration."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api.calendar import ZenPlannerCalendar
from .api.pr import PRHandler
from .api.google_calendar import AsyncGoogleCalendarHandler
from .api.the_matrix_calendar import MatrixCalendarHandler
from .const import SCAN_INTERVAL
from .storage import FulcrumTrackerStore

_LOGGER = logging.getLogger(__name__)

class FulcrumDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching Fulcrum data."""

    def __init__(
        self,
        hass: HomeAssistant,
        logger: logging.Logger,
        name: str,
        calendar: ZenPlannerCalendar,
        pr_handler: PRHandler,
        google_calendar: AsyncGoogleCalendarHandler,
        matrix_handler: MatrixCalendarHandler,
        storage: FulcrumTrackerStore,
    ) -> None:
        """Initialize."""
        super().__init__(
            hass=hass,
            logger=logger,
            name=name,
            update_interval=SCAN_INTERVAL,
        )
        self.calendar = calendar
        self.pr_handler = pr_handler
        self.google_calendar = google_calendar
        self.matrix_handler = matrix_handler
        self.storage = storage
        self._last_update_time = None
        self._cache = {}
        self._cache_time = None
        self._collection_stats = {
            "total_sessions": 0,
            "new_sessions_today": 0,
            "last_full_update": None,
            "update_streak": 0,
            "current_phase": storage.initialization_phase,
            "refresh_in_progress": False,
            "refresh_start_time": None,
            "last_refresh_completed": None,
            "refresh_duration": 0,
            "refresh_success": None,
            "refresh_type": None
        }
        _LOGGER.debug("🎮 Coordinator initialized in phase: %s", self._collection_stats["current_phase"])

    def _format_workout(self, workout: Optional[Dict[str, Any]]) -> str:
        """Format workout details for display."""
        if not workout:
            return "No workout scheduled"
        
        parts = []
        if workout.get('type'):
            parts.append(workout['type'])
        if workout.get('lifts'):
            parts.append(f"Lifts: {workout['lifts']}")
        if workout.get('meps'):
            parts.append(f"MEPs: {workout['meps']}")
            
        return " | ".join(parts) if parts else "Workout details not available"

    async def manual_refresh(self) -> None:
        """Handle manual refresh request."""
        try:
            _LOGGER.info("🔄 Starting manual refresh")
            
            # Reset storage phase
            await self.storage.async_transition_phase("historical_load", {
                "trigger": "manual_refresh",
                "start_time": datetime.now(timezone.utc).isoformat()
            })
            
            # Clear any cached data
            self._cache = {}
            self._cache_time = None
            
            # Force a full refresh
            await self._async_update_data(manual_refresh=True)
            
            _LOGGER.info("✅ Manual refresh completed successfully")
            
        except Exception as err:
            _LOGGER.error("❌ Manual refresh failed: %s", str(err))
            self._collection_stats.update({
                "refresh_in_progress": False,
                "refresh_success": False,
                "last_error": str(err)
            })
            raise

    async def _async_update_data(self, manual_refresh: bool = False) -> dict[str, Any]:
        """Fetch data from APIs with phase-aware updates."""
        try:
            now = datetime.now(timezone.utc)
            
            # Track refresh state
            self._collection_stats["refresh_in_progress"] = True
            self._collection_stats["refresh_start_time"] = now.isoformat()
            self._collection_stats["refresh_type"] = "manual" if manual_refresh else "scheduled"
            
            # Get tomorrow's workout regardless of phase
            tomorrow_workout = await self.matrix_handler.get_tomorrow_workout()
            
            current_phase = self.storage.initialization_phase
            _LOGGER.debug("🔄 Running update in phase: %s", current_phase)

            if current_phase == "init":
                # Initial setup - transition to historical load
                await self.storage.async_transition_phase("historical_load", {
                    "start_time": now.isoformat()
                })
                current_phase = "historical_load"

            if current_phase == "historical_load":
                _LOGGER.info("📚 Performing historical data load...")
                # Get full historical data
                attendance_data = await self.calendar.get_attendance_data()
                pr_data = await self.pr_handler.get_formatted_prs()
                calendar_events = await self.google_calendar.get_calendar_events()
                next_session = await self.google_calendar.get_next_session()
                
                # Process trainer stats
                trainer_stats = self._process_trainer_stats(calendar_events)
                
                if attendance_data and calendar_events:
                    total_sessions = self._reconcile_sessions(attendance_data, calendar_events)
                    await self.storage.async_update_session_count(total_sessions)
                    await self.storage.async_transition_phase("incremental", {
                        "total_sessions": total_sessions,
                        "completion_time": now.isoformat()
                    })

                # Update collection stats with completion info
                self._collection_stats.update({
                    "refresh_in_progress": False,
                    "last_refresh_completed": now.isoformat(),
                    "refresh_duration": (now - datetime.fromisoformat(self._collection_stats["refresh_start_time"])).total_seconds(),
                    "refresh_success": True,
                    "total_items_processed": total_sessions,
                    "last_update_type": "manual" if manual_refresh else "scheduled"
                })

                return {
                    **trainer_stats,
                    "zenplanner_fulcrum_sessions": attendance_data.get("total_sessions", 0),
                    "google_calendar_fulcrum_sessions": len(calendar_events) if calendar_events else 0,
                    "total_fulcrum_sessions": total_sessions,
                    "monthly_sessions": attendance_data.get("monthly_sessions", 0),
                    "last_session": attendance_data.get("last_session"),
                    "next_session": next_session,
                    "recent_prs": pr_data.get("recent_prs", "No recent PRs"),
                    "total_prs": pr_data.get("total_prs", 0),
                    "prs_by_type": pr_data.get("prs_by_type", {}),
                    "collection_stats": self._collection_stats,
                    "tomorrow_workout": self._format_workout(tomorrow_workout),
                    "tomorrow_workout_details": tomorrow_workout
                }

            else:  # Incremental mode
                _LOGGER.debug("♻️ Performing incremental update...")
                # Get recent data (2 days)
                update_start = now - timedelta(days=2)
                next_session = await self.google_calendar.get_next_session()
                pr_data = await self.pr_handler.get_formatted_prs()
                
                recent_events = await self.google_calendar.get_calendar_events(
                    start_date=update_start,
                    end_date=now
                )
                
                if recent_events:
                    self._collection_stats["new_sessions_today"] = len(recent_events)
                    self._collection_stats["update_streak"] += 1
                    trainer_stats = self._process_trainer_stats(recent_events)
                    
                    # Record the update with proper error handling
                    try:
                        await self.storage.async_record_update(now.isoformat())
                    except Exception as err:
                        _LOGGER.warning("Failed to record update timestamp: %s", err)

                # Update collection stats with completion info for incremental update
                self._collection_stats.update({
                    "refresh_in_progress": False,
                    "last_refresh_completed": now.isoformat(),
                    "refresh_duration": (now - datetime.fromisoformat(self._collection_stats["refresh_start_time"])).total_seconds(),
                    "refresh_success": True,
                    "total_items_processed": len(recent_events) if recent_events else 0,
                    "last_update_type": "manual" if manual_refresh else "scheduled"
                })

                return {
                    **(self.data if self.data else {}),
                    **(trainer_stats if recent_events else {}),
                    "next_session": next_session,
                    "recent_prs": pr_data.get("recent_prs", "No recent PRs"),
                    "prs_by_type": pr_data.get("prs_by_type", {}),
                    "collection_stats": self._collection_stats,
                    "tomorrow_workout": self._format_workout(tomorrow_workout),
                    "tomorrow_workout_details": tomorrow_workout
                }

        except Exception as err:
            self._collection_stats.update({
                "refresh_in_progress": False,
                "refresh_success": False,
                "last_error": str(err),
                "update_streak": 0
            })
            _LOGGER.error("💥 Update failed: %s", str(err))
            raise