"""Config flow for Centro de Gerenciamento de Emergências Climáticas da Prefeitura de São Paulo integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError

from .cge_scrape import CgeScrape, CgeScrapeError
from .const import CONF_ESTACAO_ID, DOMAIN, ENTRADA_ESTACAO_METEOROLOGICA, ESTACOES

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
            estacao_id = user_input[ENTRADA_ESTACAO_METEOROLOGICA]
            await self.async_set_unique_id(f"cge_{estacao_id}")
            self._abort_if_unique_id_configured()

            try:
                await CgeScrape(hass=self.hass, estacao_id=estacao_id).get()
            except CgeScrapeError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001 - fronteira externa (site do CGE)
                _LOGGER.exception(
                    "Erro inesperado ao validar a estação meteorológica"
                )
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title=ESTACOES[estacao_id],
                    data={CONF_ESTACAO_ID: estacao_id},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""
