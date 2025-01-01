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
                self.context["user_input"] = user_input
                return await self.async_step_upload_json()

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

    async def async_step_upload_json(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step to upload the service account JSON file."""
        errors = {}

        if user_input is not None:
            try:
                # Validate JSON structure
                json_content = user_input.get("service_account_json")
                self._validate_json(json_content)

                # Save the file securely
                json_path = self.hass.config.path("fulcrum_service_account.json")
                with open(json_path, "w") as json_file:
                    json_file.write(json_content)

                # Proceed to create entry
                return self.async_create_entry(
                    title=f"Fulcrum ({self.context['user_input'][CONF_USERNAME]})",
                    data={**self.context["user_input"], "service_account_path": json_path},
                )

            except InvalidJSON:
                errors["base"] = "invalid_json"
            except Exception as e:
                _LOGGER.exception("Unexpected exception: %s", e)
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="upload_json",
            data_schema=vol.Schema({vol.Required("service_account_json"): str}),
            errors=errors,
        )

    @staticmethod
    def _validate_json(json_content: str) -> None:
        """Validate the service account JSON file."""
        import json

        try:
            parsed = json.loads(json_content)
            required_keys = ["type", "project_id", "private_key_id", "private_key", "client_email"]

            if not all(key in parsed for key in required_keys):
                raise InvalidJSON("Missing required keys in JSON.")
        except json.JSONDecodeError:
            raise InvalidJSON("Invalid JSON format.")

class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""

class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""

class InvalidJSON(HomeAssistantError):
    """Error to indicate the uploaded JSON is invalid."""
