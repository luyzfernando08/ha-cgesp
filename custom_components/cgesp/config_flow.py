"""Config flow for Centro de Gerenciamento de Emergências Climáticas da Prefeitura de São Paulo integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.selector import selector

from .const import DOMAIN, ESTACOES, ENTRADA_ESTACAO_METEOROLOGICA

_LOGGER = logging.getLogger(__name__)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Centro de Gerenciamento de Emergências Climáticas da Prefeitura de São Paulo."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        schema = vol.Schema(
            {vol.Required(ENTRADA_ESTACAO_METEOROLOGICA): vol.In(ESTACOES)}
        )

        errors: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id(f"cge_{user_input.get(ENTRADA_ESTACAO_METEOROLOGICA)}")
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=ESTACOES[user_input.get(ENTRADA_ESTACAO_METEOROLOGICA)],
                data={"ESTACAO_ID": user_input.get(ENTRADA_ESTACAO_METEOROLOGICA)},
            )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""
