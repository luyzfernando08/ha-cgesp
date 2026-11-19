"""Config flow for Centro de Gerenciamento de Emergências Climáticas da Prefeitura de São Paulo integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import selector

from .cge_alertas import CgeAlertas, CgeAlertasError
from .cge_scrape import CgeScrape, CgeScrapeError
from .const import (
    CONF_ENTIDADES_PROXIMIDADE,
    CONF_ESTACAO_ID,
    CONF_GEOCODIFICAR,
    CONF_INTERVALO_ADAPTATIVO,
    CONF_RAIO_KM,
    CONF_TIPO,
    DOMAIN,
    ENTRADA_ESTACAO_METEOROLOGICA,
    ESTACOES,
    TIPO_ALERTAS_CIDADE,
    RAIO_KM_PADRAO,
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
                    options={
                        CONF_GEOCODIFICAR: user_input.get(CONF_GEOCODIFICAR, False),
                        CONF_INTERVALO_ADAPTATIVO: user_input.get(
                            CONF_INTERVALO_ADAPTATIVO, True
                        ),
                    },
                )

        return self.async_show_form(
            step_id=TIPO_ALERTAS_CIDADE,
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_GEOCODIFICAR, default=False): bool,
                    vol.Optional(CONF_INTERVALO_ADAPTATIVO, default=True): bool,
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        return AlertasCidadeOptionsFlow(config_entry)

    @classmethod
    @callback
    def async_supports_options_flow(
        cls, config_entry: config_entries.ConfigEntry
    ) -> bool:
        # Só "Alertas da cidade" tem opções; estações não.
        return config_entry.data.get(CONF_TIPO) == TIPO_ALERTAS_CIDADE


def _schema_opcoes_alertas(opcoes: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Optional(
                CONF_GEOCODIFICAR, default=bool(opcoes.get(CONF_GEOCODIFICAR, False))
            ): bool,
            vol.Optional(
                CONF_ENTIDADES_PROXIMIDADE,
                default=list(opcoes.get(CONF_ENTIDADES_PROXIMIDADE, [])),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain=["person", "device_tracker", "zone"], multiple=True
                )
            ),
            vol.Optional(
                CONF_RAIO_KM, default=float(opcoes.get(CONF_RAIO_KM, RAIO_KM_PADRAO))
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0.5,
                    max=20,
                    step=0.5,
                    unit_of_measurement="km",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(
                CONF_INTERVALO_ADAPTATIVO,
                default=bool(opcoes.get(CONF_INTERVALO_ADAPTATIVO, True)),
            ): bool,
        }
    )


class AlertasCidadeOptionsFlow(config_entries.OptionsFlow):
    """Mapa, pessoas/zonas acompanhadas (alagamentos e chuva) e intervalo."""

    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        # Não usar o nome `config_entry`: em versões novas do HA ele é
        # fornecido pela classe base e não deve ser atribuído.
        self._entry = entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            # Sem os pontos no mapa, as pessoas e zonas escolhidas ganham só
            # os sensores de chuva (os alagamentos por perto precisam deles).
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=_schema_opcoes_alertas(
                user_input if user_input is not None else dict(self._entry.options)
            ),
            errors=errors,
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""
