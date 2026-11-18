"""Config flow for Centro de Gerenciamento de Emergências Climáticas da Prefeitura de São Paulo integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError

from .cge_alertas import CgeAlertas, CgeAlertasError
from .cge_scrape import CgeScrape, CgeScrapeError
from .const import (
    CONF_ESTACAO_ID,
    CONF_TIPO,
    DOMAIN,
    ENTRADA_ESTACAO_METEOROLOGICA,
    ESTACOES,
    TIPO_ALERTAS_CIDADE,
    TIPO_ESTACAO,
    UNIQUE_ID_ALERTAS_CIDADE,
)

_LOGGER = logging.getLogger(__name__)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Centro de Gerenciamento de Emergências Climáticas da Prefeitura de São Paulo."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return self.async_show_menu(
            step_id="user",
            menu_options=[TIPO_ESTACAO, TIPO_ALERTAS_CIDADE],
        )

    async def async_step_estacao(
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
                    data={CONF_TIPO: TIPO_ESTACAO, CONF_ESTACAO_ID: estacao_id},
                )

        return self.async_show_form(
            step_id=TIPO_ESTACAO,
            data_schema=schema,
            errors=errors,
        )

    async def async_step_alertas_cidade(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        await self.async_set_unique_id(UNIQUE_ID_ALERTAS_CIDADE)
        self._abort_if_unique_id_configured()

        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                await CgeAlertas(hass=self.hass).get()
            except CgeAlertasError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001 - fronteira externa (site do CGE)
                _LOGGER.exception("Erro inesperado ao validar os alertas do CGE")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title="Alertas da cidade",
                    data={CONF_TIPO: TIPO_ALERTAS_CIDADE},
                )

        return self.async_show_form(
            step_id=TIPO_ALERTAS_CIDADE,
            data_schema=vol.Schema({}),
            errors=errors,
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""
