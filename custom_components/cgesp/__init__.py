"""The Centro de Gerenciamento de Emergências Climáticas da Prefeitura de São Paulo integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .cge_alertas_coordinator import liberar_coordinator
from .const import CONF_TIPO, TIPO_ALERTAS_CIDADE

PLATFORMS_ESTACAO: list[Platform] = [
    Platform.WEATHER,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
]
PLATFORMS_ALERTAS_CIDADE: list[Platform] = [Platform.BINARY_SENSOR]


def _plataformas(entry: ConfigEntry) -> list[Platform]:
    if entry.data.get(CONF_TIPO) == TIPO_ALERTAS_CIDADE:
        return PLATFORMS_ALERTAS_CIDADE
    return PLATFORMS_ESTACAO


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Centro de Gerenciamento de Emergências Climáticas da Prefeitura de São Paulo from a config entry."""

    await hass.config_entries.async_forward_entry_setups(entry, _plataformas(entry))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""

    descarregou = await hass.config_entries.async_unload_platforms(
        entry, _plataformas(entry)
    )
    if descarregou:
        liberar_coordinator(hass, entry.entry_id)
    return descarregou
