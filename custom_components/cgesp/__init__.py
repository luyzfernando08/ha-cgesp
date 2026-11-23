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
from .cge_radar_coordinator import CgeRadarCoordinator, remover_reparo_radar
from .const import (
    CONF_GEOCODIFICAR,
    CONF_INTERVALO_ADAPTATIVO,
    CONF_TIPO,
    DATA_RADAR_COORDINATOR,
    DOMAIN,
    TIPO_ALERTAS_CIDADE,
)
from .mapa_radar import registrar_mapa_radar

PLATFORMS_ESTACAO: list[Platform] = [
    Platform.WEATHER,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
]
PLATFORMS_ALERTAS_CIDADE: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.CAMERA,
    Platform.GEO_LOCATION,
    Platform.SENSOR,
]


def _e_alertas_cidade(entry: ConfigEntry) -> bool:
    return entry.data.get(CONF_TIPO) == TIPO_ALERTAS_CIDADE


def _plataformas(entry: ConfigEntry) -> list[Platform]:
    return PLATFORMS_ALERTAS_CIDADE if _e_alertas_cidade(entry) else PLATFORMS_ESTACAO


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Centro de Gerenciamento de Emergências Climáticas da Prefeitura de São Paulo from a config entry."""

    if _e_alertas_cidade(entry):
        adaptativo = bool(entry.options.get(CONF_INTERVALO_ADAPTATIVO, True))
        coordinator = await async_obter_coordinator(
            hass, entry.entry_id, alertas_cidade=True
        )
        coordinator.definir_intervalo_adaptativo(adaptativo)
        # Radar: pertence a esta entrada. Uma falha aqui não impede o resto.
        radar = CgeRadarCoordinator(hass, entry, coordinator)
        radar.definir_intervalo_adaptativo(adaptativo)
        await radar.async_refresh()
        hass.data[DOMAIN][DATA_RADAR_COORDINATOR] = radar
        registrar_mapa_radar(hass)
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
                coordinator.definir_intervalo_adaptativo(True)
                coordinator.buscar_boletim = False
            hass.data.get(DOMAIN, {}).pop(DATA_RADAR_COORDINATOR, None)
            remover_reparo_radar(hass)
        liberar_coordinator(hass, entry.entry_id)
    return descarregou
