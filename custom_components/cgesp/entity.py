"""Base comum das entidades da integração."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .cge_alertas import CgeAlertasData
from .cge_alertas_coordinator import CgeAlertasCoordinator
from .const import DOMAIN, ESTACOES, ESTACOES_REGIAO, ZONAS

_LOGGER = logging.getLogger(__name__)


def cgesp_device_info() -> DeviceInfo:
    """Dispositivo único "CGE - SP", compartilhado por todas as entidades."""
    return DeviceInfo(
        name="CGE - SP",
        entry_type=DeviceEntryType.SERVICE,
        identifiers={(DOMAIN,)},  # type: ignore[arg-type]
        manufacturer="cgesp.org",
        model="CGE",
        configuration_url="https://www.cgesp.org/v3/",
    )


class CgeAlertasEntity(CoordinatorEntity[CgeAlertasCoordinator]):
    _attr_attribution = "Dados fornecidos por cgesp.org"

    @property
    def device_info(self) -> DeviceInfo:
        return cgesp_device_info()

    @property
    def dados(self) -> CgeAlertasData:
        return self.coordinator.data

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data is not None


class CgeEstacaoAlertaEntity(CgeAlertasEntity):
    """Entidade ligada ao estado da área monitorada em que fica a estação."""

    def __init__(self, coordinator: CgeAlertasCoordinator, estacao_id: int) -> None:
        super().__init__(coordinator)
        self.estacao_id = estacao_id
        self.zona, self.area = ESTACOES_REGIAO[estacao_id]  # type: ignore[misc]
        self.nome_estacao = ESTACOES[estacao_id]
        self._avisou_area_ausente = False

    @property
    def estado(self) -> str | None:
        return self.dados.estado_da_area(self.area) if self.coordinator.data else None

    def _verificar_area_no_mapa(self) -> None:
        dados = self.coordinator.data
        if dados is None or not dados.mapa_disponivel:
            return
        if self.estado is not None:
            self._avisou_area_ausente = False
        elif not self._avisou_area_ausente:
            self._avisou_area_ausente = True
            _LOGGER.warning(
                "CGE: área '%s' da estação %s não encontrada (ou sem cor reconhecida) "
                "no mapa de alertas; o nome pode ter mudado no site",
                self.area,
                self.nome_estacao,
            )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._verificar_area_no_mapa()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._verificar_area_no_mapa()
        super()._handle_coordinator_update()

    @property
    def available(self) -> bool:
        return super().available and self.estado is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        atualizado_em = self.dados.mapa_atualizado_em if self.coordinator.data else None
        return {
            "estacao": self.nome_estacao,
            "zona": ZONAS[self.zona],
            "area_monitorada": self.area,
            "estado": self.estado,
            "atualizado_em": dt_util.as_local(atualizado_em) if atualizado_em else None,
        }
