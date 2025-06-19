"""Coordinator for Fulcrum Tracker integration."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from enum import Enum

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api.calendar import ZenPlannerCalendar
from .api.pr import PRHandler
from .api.google_calendar import AsyncGoogleCalendarHandler
from .api.the_matrix_calendar import MatrixCalendarHandler
from .storage import FulcrumTrackerStore

from .const import (
    SCAN_INTERVAL,
    HISTORICAL_CALENDAR_SEARCH_TERMS,
    INCREMENTAL_CALENDAR_SEARCH_TERMS,
    DEFAULT_START_DATE
)

_LOGGER = logging.getLogger(__name__)

class UpdatePhase(Enum):
    """Enum for update phases - makes code more readable!"""
    INIT = "init"
    HISTORICAL_LOAD = "historical_load"
    INCREMENTAL = "incremental"

class FulcrumDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching Fulcrum data with improved async patterns."""
    
    TRAINERS = [
        "ash", "cate", "charlotte", "cheryl", "curtis", 
        "dakayla", "devon", "ellis", "emma", "eric", 
        "genevieve", "reggie", "rj", "shane", "shelby", "sonia", 
        "walt", "zei", "squid", "unknown"
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
        """Initialize with cleaner structure."""
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

        # Determine initial phase - cleaner logic!
        initial_phase = (UpdatePhase.INCREMENTAL if storage.historical_load_done 
                        else UpdatePhase.INIT)
        
        self._collection_stats = {
            "total_sessions": storage._data.get("total_sessions", 0),
            "new_sessions_today": 0,
            "last_full_update": storage._data.get("last_update"),
            "update_streak": 0,
            "current_phase": initial_phase.value,
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
                    initial_phase.value, 
                    "exists" if storage.historical_load_done else "needed")

    async def manual_refresh(self) -> None:
        """Handle manual refresh request with better error handling."""
        try:
            _LOGGER.info("🔄 Starting manual refresh")
            
            await self._prepare_refresh("manual_refresh")
            await self._async_update_data(manual_refresh=True)
            
            _LOGGER.info("✅ Manual refresh completed successfully")
            
        except Exception as err:
            _LOGGER.error("❌ Manual refresh failed: %s", str(err))
            self._update_refresh_status(success=False, error=str(err))
            raise

    async def _prepare_refresh(self, trigger: str) -> None:
        """Prepare storage and state for refresh."""
        await self.storage.async_transition_phase("historical_load", {
            "trigger": trigger,
            "start_time": datetime.now(timezone.utc).isoformat()
        })
        self._cache = {}
        self._cache_time = None

    def _update_refresh_status(self, success: bool, error: str = None) -> None:
        """Update refresh status in collection stats."""
        self._collection_stats.update({
            "refresh_in_progress": False,
            "refresh_success": success,
            "last_error": error
        })

    async def _async_update_data(self, manual_refresh: bool = False) -> dict[str, Any]:
        """Main update method - now much cleaner and focused!"""
        _LOGGER.info("🔄 Starting data update for Fulcrum Tracker")
        
        try:
            # Setup update tracking
            start_time = datetime.now(timezone.utc)
            await self._start_update_tracking(start_time, manual_refresh)
            
            # Handle fast startup case
            if await self._should_use_fast_startup(manual_refresh):
                return await self._get_fast_startup_data()
            
            # Determine update strategy based on phase
            current_phase = UpdatePhase(self.storage.initialization_phase)
            
            if current_phase == UpdatePhase.INIT:
                current_phase = await self._handle_init_phase()
            
            # Execute the appropriate update strategy
            if current_phase in [UpdatePhase.HISTORICAL_LOAD] or manual_refresh:
                result = await self._execute_historical_update(manual_refresh, start_time)
            else:
                result = await self._execute_incremental_update(start_time)
            
            return result
            
        except Exception as err:
            await self._handle_update_error(err)
            raise

    async def _start_update_tracking(self, start_time: datetime, manual_refresh: bool) -> None:
        """Start tracking the update process."""
        current_phase = self.storage.initialization_phase
        self._collection_stats.update({
            "refresh_in_progress": True,
            "refresh_start_time": start_time.isoformat(),
            "refresh_type": "manual" if manual_refresh else "scheduled",
            "current_phase": current_phase
        })
        _LOGGER.info("🔄 Starting data update in phase: %s (Manual: %s)", 
                    current_phase, manual_refresh)

    async def _should_use_fast_startup(self, manual_refresh: bool) -> bool:
        """Check if we should use fast startup with stored data."""
        return (not self.data and 
                self.storage.historical_load_done and 
                not manual_refresh)

    async def _get_fast_startup_data(self) -> dict[str, Any]:
        """Get basic data from storage for fast startup."""
        _LOGGER.info("📊 Fast startup: Using stored data (sessions: %s)", 
                    self.storage.total_sessions)
        
        stored_sessions = self.storage.total_sessions
        trainer_counts = self.storage.get_all_trainer_sessions()
        
        # Create basic return data
        basic_data = {
            "total_fulcrum_sessions": stored_sessions,
            "collection_stats": {
                "total_sessions": stored_sessions,
                "current_phase": self.storage.initialization_phase,
                "last_update": self.storage.last_update,
                "refresh_in_progress": False,
                "fast_startup": True
            }
        }
        
        # Add trainer session counts
        trainer_stats = {f"trainer_{trainer.lower()}_sessions": 0 for trainer in self.TRAINERS}
        for trainer, count in trainer_counts.items():
            key = f"trainer_{trainer}_sessions"
            if key in trainer_stats:
                trainer_stats[key] = count
        
        # Schedule delayed update
        await self._schedule_delayed_update()
        
        return {**basic_data, **trainer_stats}

    async def _schedule_delayed_update(self) -> None:
        """Schedule a delayed incremental update after fast startup."""
        if not getattr(self, "_delayed_update_scheduled", False):
            self._delayed_update_scheduled = True
            
            async def do_delayed_update():
                _LOGGER.info("⏰ Running delayed incremental update (5 min after startup)")
                await asyncio.sleep(300)  # 5 minutes
                try:
                    _LOGGER.info("🔄 Performing delayed incremental update")
                    await self.async_refresh()
                    self._delayed_update_scheduled = False
                except Exception as err:
                    _LOGGER.error("❌ Delayed update failed: %s", str(err))
                    self._delayed_update_scheduled = False
            
            asyncio.create_task(do_delayed_update())

    async def _handle_init_phase(self) -> UpdatePhase:
        """Handle initialization phase transition."""
        _LOGGER.info("🎬 Beginning initial setup phase")
        await self.storage.async_transition_phase("historical_load", {
            "trigger": "initial_setup",
            "start_time": datetime.now(timezone.utc).isoformat()
        })
        return UpdatePhase.HISTORICAL_LOAD

    async def _execute_historical_update(self, manual_refresh: bool, start_time: datetime) -> dict[str, Any]:
        """Execute full historical data load - now cleaner and more focused!"""
        _LOGGER.info("📚 Starting full historical data load...")
        
        try:
            # Fetch all data in parallel - much faster!
            fetch_tasks = await self._create_historical_fetch_tasks()
            results = await self._execute_fetch_tasks(fetch_tasks)
            
            # Process results
            data_bundle = await self._process_historical_results(results)
            
            # Update storage and phase
            await self._finalize_historical_update(data_bundle, manual_refresh, start_time)
            
            return await self._build_historical_response(data_bundle)
            
        except Exception as err:
            _LOGGER.error("💥 Historical data fetch failed: %s", str(err))
            raise

    async def _create_historical_fetch_tasks(self) -> dict[str, Any]:
        """Create all the fetch tasks for historical data."""
        start_date = datetime.strptime(DEFAULT_START_DATE, "%Y-%m-%d")
        end_date = datetime.now(timezone.utc)
        
        return {
            "attendance": self.calendar.get_attendance_data(),
            "prs": self.pr_handler.get_formatted_prs(),
            "calendar": self.google_calendar.get_calendar_events(
                start_date=start_date,
                end_date=end_date,
                search_terms=HISTORICAL_CALENDAR_SEARCH_TERMS,
                force_refresh=True
            ),
            "next_session": self.google_calendar.get_next_session(),
            "workout": self.matrix_handler.get_tomorrow_workout()
        }

    async def _execute_fetch_tasks(self, tasks: dict[str, Any]) -> dict[str, Any]:
        """Execute all fetch tasks in parallel with proper error handling."""
        try:
            results = await asyncio.gather(*tasks.values(), return_exceptions=True)
            data = dict(zip(tasks.keys(), results))
            
            # Check for any exceptions
            for key, result in data.items():
                if isinstance(result, Exception):
                    _LOGGER.error("Failed to fetch %s: %s", key, str(result))
                    raise result
                    
            return data
            
        except Exception as err:
            _LOGGER.error("💥 Fetch tasks failed: %s", str(err))
            raise

    async def _process_historical_results(self, data: dict[str, Any]) -> dict[str, Any]:
        """Process the fetched historical data."""
        attendance_data = data["attendance"] or {}
        calendar_events = data["calendar"] or []
        
        if not attendance_data or not calendar_events:
            raise ValueError("Failed to fetch required historical data")
        
        # Process trainer statistics
        trainer_stats = self._process_trainer_stats(calendar_events)
        total_sessions = self._reconcile_sessions(attendance_data, calendar_events)
        
        return {
            "attendance_data": attendance_data,
            "calendar_events": calendar_events,
            "trainer_stats": trainer_stats,
            "total_sessions": total_sessions,
            "pr_data": data["prs"] or {},
            "next_session": data["next_session"],
            "tomorrow_workout": data["workout"]
        }

    async def _execute_incremental_update(self, start_time: datetime) -> dict[str, Any]:
        """Execute incremental update - cleaner and more focused!"""
        _LOGGER.debug("♻️ Performing incremental update...")
        
        try:
            stored_sessions = self.storage._data.get("total_sessions", 0)
            _LOGGER.info("🔍 Starting incremental update with storage sessions: %s", stored_sessions)

            # Create incremental tasks
            tasks = await self._create_incremental_fetch_tasks(start_time)
            results = await self._execute_fetch_tasks(tasks)
            
            # Process results
            await self._process_incremental_results(results, start_time)
            
            return await self._build_incremental_response(results, stored_sessions)
            
        except Exception as err:
            _LOGGER.error("💥 Incremental data fetch failed: %s", str(err))
            raise

    async def _create_incremental_fetch_tasks(self, start_time: datetime) -> dict[str, Any]:
        """Create fetch tasks for incremental update."""
        return {
            "next_session": self.google_calendar.get_next_session(),
            "pr_data": self.pr_handler.get_formatted_prs(),
            "workout": self.matrix_handler.get_tomorrow_workout(),
            "recent_events": self.google_calendar.get_calendar_events(
                start_date=start_time - timedelta(days=2),
                end_date=start_time,
                search_terms=INCREMENTAL_CALENDAR_SEARCH_TERMS
            )
        }

    async def _handle_update_error(self, err: Exception) -> None:
        """Handle update errors with better logging and state management."""
        self._collection_stats.update({
            "refresh_in_progress": False,
            "refresh_success": False,
            "last_error": str(err),
            "update_streak": 0
        })
        _LOGGER.error("💥 Update failed: %s", str(err))

    async def _process_incremental_results(self, results: dict[str, Any], start_time: datetime) -> None:
        """Process incremental update results."""
        recent_events = results.get("recent_events", [])
        
        if recent_events:
            self._collection_stats["new_sessions_today"] = len(recent_events)
            self._collection_stats["update_streak"] += 1
            
            try:
                await self.storage.async_record_update(start_time.isoformat())
            except Exception as err:
                _LOGGER.warning("Failed to record update timestamp: %s", err)

    async def _build_incremental_response(self, results: dict[str, Any], stored_sessions: int) -> dict[str, Any]:
        """Build response data for incremental update."""
        recent_events = results.get("recent_events", [])
        
        # Update collection stats
        self._collection_stats.update({
            "refresh_in_progress": False,
            "last_refresh_completed": datetime.now(timezone.utc).isoformat(),
            "refresh_duration": (datetime.now(timezone.utc) - datetime.fromisoformat(
                self._collection_stats["refresh_start_time"]
            )).total_seconds(),
            "refresh_success": True,
            "total_items_processed": len(recent_events) if recent_events else 0,
            "last_update_type": "incremental",
            "total_sessions": stored_sessions
        })

        _LOGGER.info("📊 Preparing incremental return data with sessions: %s", stored_sessions)

        # Create base return data
        return_data = {
            "total_fulcrum_sessions": stored_sessions,
            "next_session": results.get("next_session"),
            "recent_prs": results.get("pr_data", {}).get("recent_prs", "No recent PRs"),
            "prs_by_type": results.get("pr_data", {}).get("prs_by_type", {}),
            "collection_stats": self._collection_stats,
            "tomorrow_workout": self._format_workout(results.get("workout")),
            "tomorrow_workout_details": results.get("workout")
        }

        # Add trainer stats if we have recent events
        if recent_events:
            trainer_stats = self._process_trainer_stats(recent_events)
            return_data.update(trainer_stats)

        # Preserve existing data
        if self.data:
            for key, value in self.data.items():
                if key not in return_data:
                    return_data[key] = value

        _LOGGER.info("📊 Final return data contains %s sessions", return_data.get("total_fulcrum_sessions"))
        return return_data

    async def _finalize_historical_update(self, data_bundle: dict[str, Any], manual_refresh: bool, start_time: datetime) -> None:
        """Finalize historical update with storage updates."""
        total_sessions = data_bundle["total_sessions"]
        await self.storage.async_update_session_count(total_sessions)

        # Only transition to incremental if this wasn't a manual refresh
        if not manual_refresh:
            _LOGGER.info("🎯 Completing historical data collection with %d sessions", total_sessions)
            await self.storage.async_mark_historical_load_complete(total_sessions)
            
            if self.storage.initialization_phase != "incremental":
                await self.storage.async_transition_phase("incremental", {
                    "total_sessions": total_sessions,
                    "completion_time": start_time.isoformat(),
                    "historical_data": {
                        "calendar_events": len(data_bundle["calendar_events"]),
                        "attendance_total": data_bundle["attendance_data"].get("total_sessions", 0),
                        "completion_status": "success"
                    }
                })

        # Update collection stats
        self._collection_stats.update({
            "refresh_in_progress": False,
            "last_refresh_completed": start_time.isoformat(),
            "refresh_duration": (datetime.now(timezone.utc) - start_time).total_seconds(),
            "refresh_success": True,
            "total_items_processed": total_sessions
        })

    async def _build_historical_response(self, data_bundle: dict[str, Any]) -> dict[str, Any]:
        """Build response data for historical update."""
        return {
            **data_bundle["trainer_stats"],
            "zenplanner_fulcrum_sessions": data_bundle["attendance_data"].get("total_sessions", 0),
            "google_calendar_fulcrum_sessions": len(data_bundle["calendar_events"]),
            "total_fulcrum_sessions": data_bundle["total_sessions"],
            "monthly_sessions": data_bundle["attendance_data"].get("monthly_sessions", 0),
            "last_session": data_bundle["attendance_data"].get("last_session"),
            "next_session": data_bundle["next_session"],
            "recent_prs": data_bundle["pr_data"].get("recent_prs", "No recent PRs"),
            "total_prs": data_bundle["pr_data"].get("total_prs", 0),
            "prs_by_type": data_bundle["pr_data"].get("prs_by_type", {}),
            "collection_stats": self._collection_stats,
            "tomorrow_workout": self._format_workout(data_bundle["tomorrow_workout"]),
            "tomorrow_workout_details": data_bundle["tomorrow_workout"]
        }

    def _format_workout(self, workout: Optional[Dict[str, Any]]) -> str:
        """Format workout details for display with improved error handling."""
        if not workout:
            _LOGGER.debug("❌ No workout data available")
            return "No workout scheduled"
        
        try:
            display_format = workout.get('display_format', '')
            if display_format and '|' in display_format:
                return display_format
                
            # Fallback formatting
            workout_type = workout.get('type', 'Unknown')
            lifts = workout.get('lifts', 'Not specified')
            return f"{workout_type} | {lifts}"
                
        except Exception as err:
            _LOGGER.error("💥 Error formatting workout: %s", str(err))
            return "Unknown | Unknown"

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

    async def async_shutdown(self) -> None:
        """Shutdown the coordinator with improved cleanup."""
        _LOGGER.info("🛑 Shutting down coordinator")
        
        try:
            # Close API handlers with proper async handling
            await asyncio.gather(
                self._close_calendar_auth(),
                self._close_google_calendar(),
                self._save_final_state(),
                return_exceptions=True
            )
            
            self._collection_stats.update({
                "refresh_in_progress": False,
                "shutdown_time": datetime.now(timezone.utc).isoformat()
            })
            
            _LOGGER.info("✅ Coordinator shutdown complete")
            
        except Exception as err:
            _LOGGER.error("💥 Error during coordinator shutdown: %s", str(err))

    async def _close_calendar_auth(self) -> None:
        """Close calendar auth safely."""
        if hasattr(self, 'calendar') and hasattr(self.calendar, 'auth'):
            await self.calendar.auth.close()

    async def _close_google_calendar(self) -> None:
        """Close Google calendar safely."""
        if hasattr(self, 'google_calendar'):
            await self.google_calendar.close()

    async def _save_final_state(self) -> None:
        """Save final state to storage."""
        if hasattr(self, 'storage'):
            await self.storage.async_save()