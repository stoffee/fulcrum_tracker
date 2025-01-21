"""Storage handling for Fulcrum Tracker integration."""
import logging
from typing import Any, Dict, Optional
from datetime import datetime
from typing import List

from homeassistant.util.dt import now as dt_now
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import STORAGE_VERSION, STORAGE_KEY, DOMAIN_STORAGE

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
                    "last_update": None
                }
                _LOGGER.info("📦 New installation detected - initializing storage")
                await self.async_save()
            else:
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