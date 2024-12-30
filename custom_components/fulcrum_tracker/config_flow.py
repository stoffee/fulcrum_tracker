"""Config flow for Fulcrum Fitness Tracker integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .const import (
    DOMAIN,
    CONF_PERSON_ID,
    CONF_CLIENT_ID,
    CONF_MONTHLY_COST,
    DEFAULT_MONTHLY_COST,
)
from .api.auth import ZenPlannerAuth

_LOGGER = logging.getLogger(__name__)

class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Fulcrum Tracker."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            try:
                await self.async_validate_input(user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                # Create unique ID based on username
                await self.async_set_unique_id(user_input[CONF_USERNAME])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Fulcrum ({user_input[CONF_USERNAME]})",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): str,
                    vol.Required(CONF_PERSON_ID): str,
                    vol.Required(CONF_CLIENT_ID): str,
                    vol.Optional(CONF_MONTHLY_COST, default=DEFAULT_MONTHLY_COST): cv.positive_float,
                }
            ),
            errors=errors,
        )

    async def async_validate_input(self, data: dict[str, Any]) -> None:
        """Validate the user input allows us to connect.
        
        Data passed to this method is automatically saved to the config entry.
        Invalid data raises an exception that shows up as a persistent error to the user.
        """
        # Create ZenPlanner auth instance
        auth = ZenPlannerAuth(data[CONF_USERNAME], data[CONF_PASSWORD])
        
        # Test the connection and credentials
        try:
            # Convert to async
            result = await self.hass.async_add_executor_job(auth.login)
            if not result:
                raise InvalidAuth
        except Exception as ex:
            _LOGGER.error("Connection test failed: %s", ex)
            raise CannotConnect from ex

        # Validate monthly cost is positive
        if data.get(CONF_MONTHLY_COST, DEFAULT_MONTHLY_COST) <= 0:
            raise vol.Invalid("Monthly cost must be greater than 0")


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""