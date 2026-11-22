"""Câmeras de imagem: radar de chuva (atual e última hora) e mapa de alertas.

As imagens vêm dos coordinators (já baixadas a cada atualização); as câmeras
não geram consultas extras.
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.camera import Camera
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .cge_alertas_coordinator import CgeAlertasCoordinator, async_obter_coordinator
from .cge_radar_coordinator import CgeRadarCoordinator
from .const import INTERVALO_RADAR
from .entity import CgeAlertasEntity, CgeRadarEntity, obter_radar


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = await async_obter_coordinator(hass, entry.entry_id)
    cameras: list[Camera] = [CgeMapaAlertasCamera(coordinator)]
    radar = obter_radar(hass)
    if radar is not None:
        cameras += [CgeRadarCamera(radar), CgeRadarAnimacaoCamera(radar)]
    async_add_entities(cameras)


class _CgeRadarCameraBase(CgeRadarEntity, Camera):
    _attr_frame_interval = INTERVALO_RADAR.total_seconds()

    def __init__(self, coordinator: CgeRadarCoordinator) -> None:
        CgeRadarEntity.__init__(self, coordinator)
        Camera.__init__(self)


class CgeRadarCamera(_CgeRadarCameraBase):
    """Precipitação estimada pelo radar (imagem publicada pelo CGE/SAISP)."""

    _attr_name = "Radar de chuva"
    _attr_unique_id = "cgesp_radar"
    _attr_icon = "mdi:radar"

    def __init__(self, coordinator: CgeRadarCoordinator) -> None:
        super().__init__(coordinator)
        self.entity_id = "camera.cgesp_radar"
        self.content_type = "image/jpeg"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        leitura = self.leitura
        movimento = leitura.movimento
        return {
            "atualizado_em": dt_util.as_local(leitura.obtida_em),
            "horario_do_radar": dt_util.as_local(leitura.horario) if leitura.horario else None,
            "area_com_chuva_pct": round(leitura.area_com_chuva() * 100, 2),
            "chuva_indo_para": movimento.indo_para if movimento else None,
            "chuva_velocidade_kmh": round(movimento.velocidade_kmh) if movimento else None,
        }

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        leitura = self.coordinator.data
        return leitura.imagem if leitura is not None else None


class CgeRadarAnimacaoCamera(_CgeRadarCameraBase):
    """Animação (GIF) com as imagens do radar da última hora."""

    _attr_name = "Radar de chuva (última hora)"
    _attr_unique_id = "cgesp_radar_animacao"
    _attr_icon = "mdi:radar"

    def __init__(self, coordinator: CgeRadarCoordinator) -> None:
        super().__init__(coordinator)
        self.entity_id = "camera.cgesp_radar_animacao"
        self.content_type = "image/gif"

    @property
    def available(self) -> bool:
        return super().available and len(self.coordinator.animacao) > 0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        horarios = self.coordinator.animacao.horarios
        return {
            "quadros": len(horarios),
            "inicio": dt_util.as_local(horarios[0]) if horarios else None,
            "fim": dt_util.as_local(horarios[-1]) if horarios else None,
        }

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        return await self.hass.async_add_executor_job(self.coordinator.animacao.gif)


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
