"""Câmeras de imagem: radar de chuva e mapa de alertas do CGE.

As imagens só são baixadas quando alguém está vendo a câmera (painel ou
miniatura), com cache para não consultar o servidor a cada poucos segundos.
"""
from __future__ import annotations

import logging
import time

import aiohttp

from homeassistant.components.camera import Camera
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .cge_alertas_coordinator import CgeAlertasCoordinator, async_obter_coordinator
from .cge_extras import URL_RADAR
from .entity import CgeAlertasEntity, cgesp_device_info

_LOGGER = logging.getLogger(__name__)

# O radar é atualizado a cada ~5–10 min; não adianta buscar mais que isso.
CACHE_RADAR_SEGUNDOS = 5 * 60
TIMEOUT_RADAR = aiohttp.ClientTimeout(total=30)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = await async_obter_coordinator(hass, entry.entry_id)
    async_add_entities([CgeRadarCamera(), CgeMapaAlertasCamera(coordinator)])


class CgeRadarCamera(Camera):
    """Precipitação estimada pelo radar (imagem publicada pelo CGE/SAISP)."""

    _attr_name = "Radar de chuva"
    _attr_unique_id = "cgesp_radar"
    _attr_icon = "mdi:radar"
    _attr_attribution = "Radar: SAISP/FCTH, publicado por cgesp.org"
    _attr_frame_interval = CACHE_RADAR_SEGUNDOS

    def __init__(self) -> None:
        super().__init__()
        self.entity_id = "camera.cgesp_radar"
        self.content_type = "image/jpeg"
        self._imagem: bytes | None = None
        self._baixada_em = 0.0
        self._falhou = False

    @property
    def device_info(self):
        return cgesp_device_info()

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        if self._imagem is not None and time.monotonic() - self._baixada_em < CACHE_RADAR_SEGUNDOS:
            return self._imagem
        sessao = async_get_clientsession(self.hass)
        try:
            async with sessao.get(URL_RADAR, timeout=TIMEOUT_RADAR) as resposta:
                resposta.raise_for_status()
                imagem = await resposta.read()
        except (aiohttp.ClientError, TimeoutError) as err:
            if not self._falhou:
                _LOGGER.info("CGE: não foi possível baixar a imagem do radar: %s", err)
            self._falhou = True
            return self._imagem  # mostra a última imagem boa, se houver
        self._falhou = False
        self._imagem = imagem
        self._baixada_em = time.monotonic()
        return imagem


class CgeMapaAlertasCamera(CgeAlertasEntity, Camera):
    """O mapa de alertas usado para o estado das regiões (já baixado a cada
    atualização; não gera consultas extras)."""

    _attr_name = "Mapa de alertas"
    _attr_unique_id = "cgesp_mapa_alertas"
    _attr_icon = "mdi:map-legend"

    def __init__(self, coordinator: CgeAlertasCoordinator) -> None:
        CgeAlertasEntity.__init__(self, coordinator)
        Camera.__init__(self)
        self.entity_id = "camera.cgesp_mapa_alertas"
        self.content_type = "image/png"

    @property
    def available(self) -> bool:
        return super().available and self.dados.mapa_png is not None

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        dados = self.coordinator.data
        return dados.mapa_png if dados is not None else None
