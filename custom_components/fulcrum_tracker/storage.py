"""Storage handling for Fulcrum Tracker integration."""
import logging
from typing import Any, Dict, Optional

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
            self._data = stored if stored else {}
        except Exception as err:
            _LOGGER.error("💥 Failed to load stored data: %s", str(err))
            self._data = {}

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

    async def async_mark_historical_load_complete(self) -> None:
        """Mark historical data load as complete."""
        _LOGGER.info("📚 Marking historical data load as complete")
        await self.async_update_data({
            "historical_load_done": True,
            "initialization_phase": "incremental"
        })

    async def async_update_session_count(self, count: int) -> None:
        """Update total session count."""
        _LOGGER.debug("🔢 Updating total session count to: %d", count)
        await self.async_update_data({
            "total_sessions": count
        })

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