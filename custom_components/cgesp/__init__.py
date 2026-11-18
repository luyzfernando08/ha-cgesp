"""The Centro de Gerenciamento de Emergências Climáticas da Prefeitura de São Paulo integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .cge_alertas_coordinator import (
    async_obter_coordinator,
    liberar_coordinator,
    obter_coordinator_existente,
)
from .const import CONF_GEOCODIFICAR, CONF_TIPO, TIPO_ALERTAS_CIDADE

PLATFORMS_ESTACAO: list[Platform] = [
    Platform.WEATHER,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
]
PLATFORMS_ALERTAS_CIDADE: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.GEO_LOCATION,
]


def _e_alertas_cidade(entry: ConfigEntry) -> bool:
    return entry.data.get(CONF_TIPO) == TIPO_ALERTAS_CIDADE


def _plataformas(entry: ConfigEntry) -> list[Platform]:
    return PLATFORMS_ALERTAS_CIDADE if _e_alertas_cidade(entry) else PLATFORMS_ESTACAO


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Centro de Gerenciamento de Emergências Climáticas da Prefeitura de São Paulo from a config entry."""

    if _e_alertas_cidade(entry):
        coordinator = await async_obter_coordinator(hass, entry.entry_id)
        await coordinator.async_definir_geocodificacao(
            bool(entry.options.get(CONF_GEOCODIFICAR, False))
        )
        entry.async_on_unload(entry.add_update_listener(_async_recarregar))

    await hass.config_entries.async_forward_entry_setups(entry, _plataformas(entry))

    return True


async def _async_recarregar(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Opções mudaram (ex.: localização no mapa ligada/desligada)."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""

    descarregou = await hass.config_entries.async_unload_platforms(
        entry, _plataformas(entry)
    )
    if descarregou:
        if _e_alertas_cidade(entry):
            coordinator = obter_coordinator_existente(hass)
            if coordinator is not None:
                await coordinator.async_definir_geocodificacao(False)
        liberar_coordinator(hass, entry.entry_id)
    return descarregou
