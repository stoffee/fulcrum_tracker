"""Storage handling for Fulcrum Tracker integration."""
import logging
from typing import Any, Dict, Optional, List
from datetime import datetime
from typing import List

from homeassistant.util.dt import now as dt_now
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import (
    STORAGE_VERSION,
    STORAGE_KEY,
    DOMAIN_STORAGE,
    TRAINERS,
)

_LOGGER = logging.getLogger(__name__)

class FulcrumTrackerStore:
    """Class to handle storage of Fulcrum Tracker state."""
    
    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the storage."""
        self.hass = hass
        self.store = Store[Dict[str, Any]](
            hass, STORAGE_VERSION, DOMAIN_STORAGE, private=True
        )
        self._data: Dict[str, Any] = {}
        self._trainer_list = [trainer.lower() for trainer in TRAINERS]

    async def async_load(self) -> None:
        """Load stored data."""
        try:
            stored = await self.store.async_load()
            _LOGGER.debug("🎮 Loading stored state data")
            
            if not stored:
                # New installation - set initial state
                self._data = {
                    "initialization_phase": "init",
                    "historical_load_done": False,
                    "first_setup_time": None,
                    "total_sessions": 0,
                    "last_update": None,
                    "trainer_sessions": {
                        trainer.lower(): {
                            "total_sessions": 0,
                            "last_update": None
                        } for trainer in self._trainer_list
                    }
                }
                _LOGGER.info("📦 New installation detected - initializing storage")
                await self.async_save()
            else:
                # Ensure trainer_sessions exists in existing installations
                if "trainer_sessions" not in stored:
                    stored["trainer_sessions"] = {
                        trainer.lower(): {
                            "total_sessions": 0,
                            "last_update": None
                        } for trainer in self._trainer_list
                    }
                self._data = stored
                _LOGGER.debug("📋 Loaded existing storage data: %s", 
                            {k: v for k, v in self._data.items() if k != "credentials"})
        except Exception as err:
            _LOGGER.error("💥 Failed to load stored data: %s", str(err))
            self._data = {}

    async def async_verify_phase(self) -> None:
        """Verify and correct phase if necessary."""
        current_phase = self._data.get("initialization_phase", "init")
        historical_done = self._data.get("historical_load_done", False)
        
        if not historical_done and current_phase == "incremental":
            _LOGGER.warning("⚠️ Found incremental phase without historical load - correcting")
            await self.async_transition_phase("init", {
                "reason": "phase_correction",
                "previous_phase": current_phase
            })

    async def async_save(self) -> None:
        """Save data to storage."""
        try:
            _LOGGER.debug("💾 Saving state data")
            await self.store.async_save(self._data)
        except Exception as err:
            _LOGGER.error("💥 Failed to save data: %s", str(err))

    async def async_update_trainer_stats(self, trainer_data: Dict[str, Any], session_history: List[Dict[str, Any]] = None) -> None:
        """Update comprehensive trainer statistics."""
        current_time = dt_now().isoformat()
        
        # Initialize trainer_sessions if it doesn't exist
        if "trainer_sessions" not in self._data:
            self._data["trainer_sessions"] = {}
            
        # Update version tracking
        self._data["trainer_data_version"] = "1.1"
        self._data["last_trainer_update"] = current_time
        
        # Update each trainer's statistics
        for trainer, stats in trainer_data.items():
            trainer_key = trainer.lower()
            if trainer_key not in self._data["trainer_sessions"]:
                self._data["trainer_sessions"][trainer_key] = {
                    "total_sessions": 0,
                    "last_update": None,
                    "session_history": []
                }
            
            trainer_info = self._data["trainer_sessions"][trainer_key]
            trainer_info["total_sessions"] = stats.get("total_sessions", 0)
            trainer_info["last_update"] = current_time
            
            # Add new session history if provided
            if session_history:
                trainer_sessions = [
                    session for session in session_history 
                    if session.get("instructor", "").lower() == trainer_key
                ]
                if trainer_sessions:
                    if "session_history" not in trainer_info:
                        trainer_info["session_history"] = []
                    trainer_info["session_history"].extend(trainer_sessions)
                    # Keep only last 100 sessions
                    trainer_info["session_history"] = sorted(
                        trainer_info["session_history"],
                        key=lambda x: x["date"]
                    )[-100:]
        
        await self.async_save()

    async def async_get_trainer_stats(self, trainer: str = None) -> Dict[str, Any]:
        """Get comprehensive trainer statistics."""
        if trainer:
            trainer = trainer.lower()
            trainer_data = self._data.get("trainer_sessions", {}).get(trainer, {})
            return {
                "total_sessions": trainer_data.get("total_sessions", 0),
                "last_update": trainer_data.get("last_update"),
                "session_history": trainer_data.get("session_history", [])[-10:],  # Last 10 sessions
                "data_version": self._data.get("trainer_data_version", "1.0")
            }
        
        return {
            trainer: {
                "total_sessions": data.get("total_sessions", 0),
                "last_update": data.get("last_update"),
                "recent_sessions": len(data.get("session_history", [])),
                "data_version": self._data.get("trainer_data_version", "1.0")
            }
            for trainer, data in self._data.get("trainer_sessions", {}).items()
        }

    async def async_cleanup_trainer_data(self) -> None:
        """Clean up and optimize trainer data storage."""
        if "trainer_sessions" not in self._data:
            return
            
        current_time = dt_now()
        cleaned_data = {}
        
        for trainer, data in self._data["trainer_sessions"].items():
            # Skip empty trainer data
            if not data.get("total_sessions", 0):
                continue
                
            # Cleanup session history
            if "session_history" in data:
                # Keep only last 100 sessions
                data["session_history"] = sorted(
                    data["session_history"],
                    key=lambda x: x["date"]
                )[-100:]
                
            cleaned_data[trainer] = data
            
        self._data["trainer_sessions"] = cleaned_data
        self._data["last_cleanup"] = current_time.isoformat()
        
        await self.async_save()

    async def async_migrate_trainer_data(self) -> None:
        """Migrate trainer data to latest version."""
        current_version = self._data.get("trainer_data_version", "1.0")
        
        if current_version == "1.0":
            # Migrate from 1.0 to 1.1
            _LOGGER.info("📊 Migrating trainer data from v1.0 to v1.1")
            
            for trainer_data in self._data.get("trainer_sessions", {}).values():
                if "session_history" not in trainer_data:
                    trainer_data["session_history"] = []
                    
            self._data["trainer_data_version"] = "1.1"
            await self.async_save()

    # Existing methods remain unchanged
    @property
    def historical_load_done(self) -> bool:
        """Check if historical data load is complete."""
        return self._data.get("historical_load_done", False)

    @property
    def last_update(self) -> Optional[str]:
        """Get the last update timestamp."""
        return self._data.get("last_update")

    @property
    def total_sessions(self) -> int:
        """Get total number of tracked sessions."""
        return self._data.get("total_sessions", 0)

    @property
    def initialization_phase(self) -> str:
        """Get current initialization phase."""
        return self._data.get("initialization_phase", "init")

    async def async_update_data(self, data: Dict[str, Any]) -> None:
        """Update storage data."""
        self._data.update(data)
        await self.async_save()

    async def async_mark_historical_load_complete(self, session_count: Optional[int] = None) -> None:
        """Mark historical data load as complete."""
        _LOGGER.info("🎯 Marking historical data load as complete")
        completion_data = {
            "historical_load_done": True,
            "initialization_phase": "incremental",
            "completion_timestamp": dt_now().isoformat()
        }
        
        if session_count is not None:
            _LOGGER.debug("📊 Including session count: %d", session_count)
            completion_data["total_sessions"] = session_count
            
        await self.async_update_data(completion_data)

    def get_all_trainer_sessions(self) -> Dict[str, int]:
        """Get session counts for all trainers."""
        return {
            trainer: data.get("total_sessions", 0)
            for trainer, data in self._data.get("trainer_sessions", {}).items()
        }

    async def async_update_data(self, data: Dict[str, Any]) -> None:
        """Update storage data."""
        self._data.update(data)
        await self.async_save()

    @property
    def historical_load_done(self) -> bool:
        """Check if historical data load is complete."""
        return self._data.get("historical_load_done", False)

    @property
    def last_update(self) -> Optional[str]:
        """Get the last update timestamp."""
        return self._data.get("last_update")

    @property
    def total_sessions(self) -> int:
        """Get total number of tracked sessions."""
        return self._data.get("total_sessions", 0)

    @property
    def initialization_phase(self) -> str:
        """Get current initialization phase."""
        return self._data.get("initialization_phase", "init")

    async def async_mark_historical_load_complete(self, session_count: Optional[int] = None) -> None:
        """Mark historical data load as complete."""
        _LOGGER.info("🎯 Marking historical data load as complete")
        completion_data = {
            "historical_load_done": True,
            "initialization_phase": "incremental",
            "completion_timestamp": dt_now().isoformat()
        }
        
        if session_count is not None:
            _LOGGER.debug("📊 Including session count: %d", session_count)
            completion_data["total_sessions"] = session_count
            
        await self.async_update_data(completion_data)

    async def async_update_session_count(self, count: int) -> None:
        """Update total session count."""
        _LOGGER.debug("🔢 Updating total session count to: %d", count)
        await self.async_update_data({
            "total_sessions": count
        })

    async def async_force_completion(self) -> None:
        """Force completion of historical load (recovery function)."""
        _LOGGER.warning("🔧 Forcing historical load completion")
        current_sessions = self._data.get("total_sessions", 0)
        await self.async_mark_historical_load_complete(current_sessions)

    async def async_record_update(self, timestamp: str) -> None:
        """Record successful update."""
        _LOGGER.debug("⏰ Recording update timestamp: %s", timestamp)
        await self.async_update_data({
            "last_update": timestamp
        })

    async def async_clear(self) -> None:
        """Clear all stored data."""
        _LOGGER.warning("🧹 Clearing all stored data")
        self._data = {}
        await self.async_save()
    
    async def async_transition_phase(self, new_phase: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        """Handle phase transitions with proper state management."""
        try:
            current_phase = self.initialization_phase
            _LOGGER.info("🔄 Phase transition request: %s -> %s", current_phase, new_phase)

            # Validate phase transition
            valid_transitions = {
                "init": ["historical_load"],
                "historical_load": ["incremental"],
                "incremental": ["historical_load"]  # Only allowed for manual refresh
            }

            if new_phase not in valid_transitions.get(current_phase, []):
                _LOGGER.error("❌ Invalid phase transition: %s -> %s", current_phase, new_phase)
                return

            transition_data = {
                "initialization_phase": new_phase,
                "last_phase_change": dt_now().isoformat(),
                "previous_phase": current_phase
            }

            if metadata:
                transition_data.update(metadata)

            # Phase-specific handling
            if new_phase == "incremental":
                if not self.historical_load_done:
                    _LOGGER.warning("⚠️ Entering incremental mode without historical load!")
                    if not metadata or not metadata.get("force_transition"):
                        _LOGGER.error("🛑 Blocked transition to incremental without historical load")
                        return
                transition_data["historical_load_done"] = True
            
            elif new_phase == "historical_load":
                transition_data["historical_load_start"] = dt_now().isoformat()
                if self.historical_load_done:
                    _LOGGER.warning("⚠️ Restarting historical load - this may cause duplicate data!")
                    # Reset historical load flag for fresh start
                    transition_data["historical_load_done"] = False
            
            # Track phase transition history
            phase_history = self._data.get("phase_history", [])
            phase_history.append({
                "from": current_phase,
                "to": new_phase,
                "timestamp": dt_now().isoformat(),
                "metadata": metadata
            })
            
            # Keep only last 10 transitions
            transition_data["phase_history"] = phase_history[-10:]
            
            await self.async_update_data(transition_data)
            _LOGGER.debug("✅ Phase transition complete: %s", new_phase)

        except Exception as err:
            _LOGGER.error("💥 Phase transition failed: %s", str(err))
            raise

    @property
    def phase_history(self) -> List[Dict[str, str]]:
        """Get phase transition history."""
        return self._data.get("phase_history", [])

    async def async_force_phase(self, phase: str) -> None:
        """Force a specific phase (for debugging/recovery)."""
        _LOGGER.warning("⚠️ Forcing phase transition to: %s", phase)
        await self.async_transition_phase(phase, {"forced": True})