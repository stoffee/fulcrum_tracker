"""Coordinator for Fulcrum Tracker integration."""
from __future__ import annotations

import asyncio
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
    TRAINERS = [
        "ash", "cate", "charlotte", "cheryl", "curtis", 
        "dakayla", "devon", "ellis", "emma", "eric", 
        "genevieve", "reggie", "shane", "shelby", "sonia", 
        "sydney", "walter", "zei", "unknown"
    ]

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

        # Determine initial phase based on storage state
        initial_phase = "init"
        if storage.historical_load_done:
            _LOGGER.info("♻️ Historical data exists - continuing in incremental mode")
            initial_phase = "incremental"
        else:
            _LOGGER.info("🆕 No historical data found - starting in initial load phase")

        # Initialize collection stats with storage data
        self._collection_stats = {
            "total_sessions": storage._data.get("total_sessions", 0),
            "new_sessions_today": 0,
            "last_full_update": storage._data.get("last_update"),
            "update_streak": 0,
            "current_phase": initial_phase,
            "refresh_in_progress": False,
            "refresh_start_time": None,
            "last_refresh_completed": None,
            "refresh_duration": 0,
            "refresh_success": None,
            "refresh_type": None,
            "initialization_status": {
                "historical_load_done": storage.historical_load_done,
                "last_setup_time": storage._data.get("last_setup_time"),
                "total_tracked_sessions": storage._data.get("total_sessions", 0)
            }
        }

        _LOGGER.info("🎮 Coordinator initialized in phase: %s (Historical data: %s)", 
                    initial_phase, 
                    "exists" if storage.historical_load_done else "needed")

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

    def _process_trainer_stats(self, calendar_events: list[dict[str, Any]]) -> dict[str, Any]:
        """Process trainer statistics from calendar events with improved validation and deduplication."""
        _LOGGER.info("Starting trainer stats processing with %d events", len(calendar_events))
        
        # Initialize counters for all trainers
        trainer_stats = {f"trainer_{trainer.lower()}_sessions": 0 for trainer in self.TRAINERS}
        _LOGGER.debug("Initialized trainer stats: %s", trainer_stats)
        
        if not calendar_events:
            _LOGGER.warning("No calendar events to process!")
            return trainer_stats
            
        # Track unique sessions to prevent duplicates
        processed_sessions = set()
        unmatched_trainers = set()
        invalid_events = []
        
        for event in calendar_events:
            try:
                # Create unique session identifier
                session_id = f"{event.get('date', '')}_{event.get('time', '')}_{event.get('instructor', '')}"
                
                # Skip if we've already processed this session
                if session_id in processed_sessions:
                    _LOGGER.debug("Skipping duplicate session: %s", session_id)
                    continue
                    
                # Validate event data
                if not self._validate_event(event):
                    #_LOGGER.warning("Invalid event data: %s", event)
                    invalid_events.append(event)
                    continue
                
                raw_instructor = event.get('instructor', 'Unknown')
                instructor = raw_instructor.lower()
                stat_key = f"trainer_{instructor}_sessions"
                
                if stat_key in trainer_stats:
                    trainer_stats[stat_key] += 1
                    processed_sessions.add(session_id)
                else:
                    unmatched_trainers.add(raw_instructor)
                    _LOGGER.warning("Unmatched trainer found: %s", raw_instructor)
                    
            except Exception as err:
                _LOGGER.error("Error processing event: %s - Error: %s", event, str(err))
                continue
        
        # Log collection statistics
        collection_stats = {
            "total_processed": len(processed_sessions),
            "duplicates_skipped": len(calendar_events) - len(processed_sessions),
            "invalid_events": len(invalid_events),
            "unmatched_trainers": list(unmatched_trainers)
        }
        _LOGGER.info("Collection statistics: %s", collection_stats)
        
        # Log final counts for active trainers
        active_trainers = {k: v for k, v in trainer_stats.items() if v > 0}
        _LOGGER.info("Final trainer session counts: %s", active_trainers)
        
        return {
            **trainer_stats,
            "collection_stats": collection_stats
        }

    def _validate_event(self, event: dict) -> bool:
        """Validate event data for trainer session processing."""
        if not isinstance(event, dict):
            return False
            
        required_fields = ['date', 'time', 'instructor']
        
        # Check for required fields
        if not all(field in event for field in required_fields):
            return False
                
        # Validate date format (YYYY-MM-DD)
        try:
            date_str = event['date']
            datetime.strptime(date_str, '%Y-%m-%d')
        except (ValueError, TypeError):
            return False
                
        # Validate time format (HH:MM)
        try:
            time_str = event['time']
            datetime.strptime(time_str, '%H:%M')
        except (ValueError, TypeError):
            return False
                
        # Validate instructor
        instructor = event.get('instructor', '').lower()
        if not instructor or instructor == 'unknown':
            return False
                
        return True

    def _get_session_history(self, calendar_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Process and return session history with trainer information."""
        session_history = []
        
        for event in sorted(calendar_events, key=lambda x: (x['date'], x['time'])):
            if self._validate_event(event):
                session_history.append({
                    'date': event['date'],
                    'time': event['time'],
                    'instructor': event['instructor'],
                    'location': event.get('location', 'Unknown'),
                    'description': event.get('description', ''),
                    'processed_at': datetime.now().isoformat()
                })
        
        return session_history

    def _reconcile_sessions(self, attendance_data: dict[str, Any], calendar_events: list[dict[str, Any]]) -> int:
        """Reconcile session counts between attendance and calendar data."""
        # Get base count from attendance data
        total_sessions = attendance_data.get("total_sessions", 0)
        
        # Add any calendar events not counted in attendance
        if calendar_events:
            calendar_count = len([event for event in calendar_events if isinstance(event, dict)])
            # If attendance data is significantly different, use calendar data
            if abs(total_sessions - calendar_count) > 5:  # Threshold for mismatch
                _LOGGER.warning(
                    "Session count mismatch - Attendance: %d, Calendar: %d",
                    total_sessions,
                    calendar_count
                )
                total_sessions = max(total_sessions, calendar_count)
        
        return total_sessions

    async def _async_update_data(self, manual_refresh: bool = False) -> dict[str, Any]:
        """Fetch data from APIs with phase-aware updates."""
        try:
            now = datetime.now(timezone.utc)
            current_phase = self.storage.initialization_phase

            # Add debug logging
            _LOGGER.info("🔍 Debug - Storage Data:")
            _LOGGER.info("  - Total Sessions in Storage: %s", self.storage._data.get("total_sessions", 0))
            _LOGGER.info("  - Phase: %s", current_phase)
            _LOGGER.info("  - Historical Load Done: %s", self.storage.historical_load_done)

            # Track refresh state
            self._collection_stats.update({
                "refresh_in_progress": True,
                "refresh_start_time": now.isoformat(),
                "refresh_type": "manual" if manual_refresh else "scheduled",
                "current_phase": current_phase
            })
            
            _LOGGER.info("🔄 Starting data update in phase: %s (Manual: %s)", 
                        current_phase, manual_refresh)

            # Always get tomorrow's workout in parallel
            workout_task = self.matrix_handler.get_tomorrow_workout()
            
            if current_phase == "init":
                _LOGGER.info("🎬 Beginning initial setup phase")
                await self.storage.async_transition_phase("historical_load", {
                    "trigger": "initial_setup",
                    "start_time": now.isoformat()
                })
                current_phase = "historical_load"

            # Full historical data load
            if current_phase == "historical_load" or manual_refresh:
                _LOGGER.info("📚 Starting full historical data load...")
                attendance_data = {}
                calendar_events = []
                pr_data = {}

                try:
                    # Create all fetch tasks
                    tasks = {
                        "attendance": self.calendar.get_attendance_data(),
                        "prs": self.pr_handler.get_formatted_prs(),
                        "calendar": self.google_calendar.get_calendar_events(),
                        "next_session": self.google_calendar.get_next_session(),
                        "workout": workout_task
                    }

                    # Execute all tasks in parallel
                    results = await asyncio.gather(*tasks.values(), return_exceptions=True)
                    data = dict(zip(tasks.keys(), results))
                    
                    # Check for any exceptions
                    for key, result in data.items():
                        if isinstance(result, Exception):
                            _LOGGER.error("Failed to fetch %s: %s", key, str(result))
                            raise result

                    attendance_data = data["attendance"] or {}
                    pr_data = data["prs"] or {}
                    calendar_events = data["calendar"] or []
                    next_session = data["next_session"]
                    tomorrow_workout = data["workout"]

                    if not attendance_data or not calendar_events:
                        raise ValueError("Failed to fetch required historical data")

                    # Process trainer statistics
                    trainer_stats = self._process_trainer_stats(calendar_events)
                    
                    # Update total sessions count
                    total_sessions = self._reconcile_sessions(attendance_data, calendar_events)
                    await self.storage.async_update_session_count(total_sessions)

                    # Only transition to incremental if this wasn't a manual refresh
                    if not manual_refresh:
                        _LOGGER.info("🎯 Completing historical data collection with %d sessions", total_sessions)
                        await self.storage.async_mark_historical_load_complete(total_sessions)
                        
                        if current_phase != "incremental":
                            await self.storage.async_transition_phase("incremental", {
                                "total_sessions": total_sessions,
                                "completion_time": now.isoformat(),
                                "historical_data": {
                                    "calendar_events": len(calendar_events),
                                    "attendance_total": attendance_data.get("total_sessions", 0),
                                    "completion_status": "success"
                                }
                            })

                    # Update collection stats
                    self._collection_stats.update({
                        "refresh_in_progress": False,
                        "last_refresh_completed": now.isoformat(),
                        "refresh_duration": (now - datetime.fromisoformat(
                            self._collection_stats["refresh_start_time"]
                        )).total_seconds(),
                        "refresh_success": True,
                        "total_items_processed": total_sessions
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

                except Exception as fetch_err:
                    _LOGGER.error("💥 Historical data fetch failed: %s", str(fetch_err))
                    raise

            else:  # Incremental mode
                _LOGGER.debug("♻️ Performing incremental update...")
                try:
                    # Get stored sessions count first
                    stored_sessions = self.storage._data.get("total_sessions", 0)
                    _LOGGER.info("🔍 Starting incremental update with storage sessions: %s", stored_sessions)

                    # Create all incremental tasks
                    tasks = {
                        "next_session": self.google_calendar.get_next_session(),
                        "pr_data": self.pr_handler.get_formatted_prs(),
                        "workout": workout_task,
                        "recent_events": self.google_calendar.get_calendar_events(
                            start_date=now - timedelta(days=2),
                            end_date=now
                        )
                    }
                    
                    # Execute all tasks in parallel
                    results = await asyncio.gather(*tasks.values(), return_exceptions=True)
                    data = dict(zip(tasks.keys(), results))
                    
                    # Check for any exceptions
                    for key, result in data.items():
                        if isinstance(result, Exception):
                            _LOGGER.error("Failed to fetch %s: %s", key, str(result))
                            raise result
                    
                    # Process results
                    next_session = data["next_session"]
                    pr_data = data["pr_data"]
                    tomorrow_workout = data["workout"]
                    recent_events = data["recent_events"]
                    
                    # Initialize trainer_stats
                    trainer_stats = {}
                    
                    if recent_events:
                        self._collection_stats["new_sessions_today"] = len(recent_events)
                        self._collection_stats["update_streak"] += 1
                        trainer_stats = self._process_trainer_stats(recent_events)
                        
                        try:
                            await self.storage.async_record_update(now.isoformat())
                        except Exception as err:
                            _LOGGER.warning("Failed to record update timestamp: %s", err)

                    # Update collection stats
                    self._collection_stats.update({
                        "refresh_in_progress": False,
                        "last_refresh_completed": now.isoformat(),
                        "refresh_duration": (now - datetime.fromisoformat(
                            self._collection_stats["refresh_start_time"]
                        )).total_seconds(),
                        "refresh_success": True,
                        "total_items_processed": len(recent_events) if recent_events else 0,
                        "last_update_type": "manual" if manual_refresh else "scheduled",
                        "total_sessions": stored_sessions  # Add stored sessions to stats
                    })

                    _LOGGER.info("📊 Preparing incremental return data with sessions: %s", stored_sessions)

                    # Create base return data with essential values
                    return_data = {
                        "total_fulcrum_sessions": stored_sessions,  # Explicitly include total sessions
                        "next_session": next_session,
                        "recent_prs": pr_data.get("recent_prs", "No recent PRs"),
                        "prs_by_type": pr_data.get("prs_by_type", {}),
                        "collection_stats": self._collection_stats,
                        "tomorrow_workout": self._format_workout(tomorrow_workout),
                        "tomorrow_workout_details": tomorrow_workout
                    }

                    # Add trainer stats if we have recent events
                    if trainer_stats:
                        return_data.update(trainer_stats)

                    # Add any existing data we want to preserve
                    if self.data:
                        for key, value in self.data.items():
                            if key not in return_data:
                                return_data[key] = value

                    _LOGGER.info("📊 Final return data contains %s sessions", return_data.get("total_fulcrum_sessions"))
                    return return_data

                except Exception as fetch_err:
                    _LOGGER.error("💥 Incremental data fetch failed: %s", str(fetch_err))
                    raise

        except Exception as err:
            self._collection_stats.update({
                "refresh_in_progress": False,
                "refresh_success": False,
                "last_error": str(err),
                "update_streak": 0
            })
            _LOGGER.error("💥 Update failed: %s", str(err))
            raise