"""Base comum das entidades da integração."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_FRIENDLY_NAME, ATTR_LATITUDE, ATTR_LONGITUDE
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util
from homeassistant.util import slugify

from .cge_alertas import CgeAlertasData
from .cge_alertas_coordinator import CgeAlertasCoordinator
from .cge_radar import LeituraRadar
from .cge_radar_coordinator import CgeRadarCoordinator
from .const import DATA_RADAR_COORDINATOR, DOMAIN, ESTACOES, ESTACOES_REGIAO, ZONAS

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


def obter_radar(hass: HomeAssistant) -> CgeRadarCoordinator | None:
    return hass.data.get(DOMAIN, {}).get(DATA_RADAR_COORDINATOR)


class CgeRadarEntity(CoordinatorEntity[CgeRadarCoordinator]):
    _attr_attribution = "Radar: SAISP/FCTH, publicado por cgesp.org"

    @property
    def device_info(self) -> DeviceInfo:
        return cgesp_device_info()

    @property
    def leitura(self) -> LeituraRadar:
        return self.coordinator.data

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data is not None


class EntidadeAcompanhada:
    """Mistura para entidades ligadas a uma pessoa, rastreador ou zona:
    nome, posição e atualização quando ela se move."""

    hass: HomeAssistant

    def _acompanhar(self, entidade: str) -> None:
        self.entidade = entidade
        dominio, objeto = entidade.split(".", 1)
        self._objeto = objeto
        # person.joao -> joao; zone.home -> zone_home
        self.sufixo = slugify(objeto if dominio == "person" else f"{dominio}_{objeto}")

    def _nome_da_entidade(self) -> str:
        estado = self.hass.states.get(self.entidade) if self.hass else None
        if estado is not None and estado.attributes.get(ATTR_FRIENDLY_NAME):
            return estado.attributes[ATTR_FRIENDLY_NAME]
        return self._objeto

    def _posicao(self) -> tuple[float, float] | None:
        estado = self.hass.states.get(self.entidade)
        if estado is None:
            return None
        try:
            return (
                float(estado.attributes.get(ATTR_LATITUDE)),  # type: ignore[arg-type]
                float(estado.attributes.get(ATTR_LONGITUDE)),  # type: ignore[arg-type]
            )
        except (TypeError, ValueError):
            return None

    def _sem_posicao(self) -> str:
        return f"{self.entidade} não tem localização (latitude/longitude)"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()  # type: ignore[misc]
        self.async_on_remove(  # type: ignore[attr-defined]
            async_track_state_change_event(self.hass, [self.entidade], self._entidade_mudou)
        )

    @callback
    def _entidade_mudou(self, _evento: Event) -> None:
        self.async_write_ha_state()  # type: ignore[attr-defined]


def remover_orfas(
    hass: HomeAssistant,
    entry: ConfigEntry,
    dominio: str,
    prefixos: tuple[str, ...],
    validos: set[str],
) -> None:
    """Entidades de pessoas/zonas que saíram das opções (ou cuja opção foi
    desligada) não devem ficar órfãs no registro."""
    registro = er.async_get(hass)
    for registrada in er.async_entries_for_config_entry(registro, entry.entry_id):
        if (
            registrada.domain == dominio
            and registrada.unique_id.startswith(prefixos)
            and registrada.unique_id not in validos
        ):
            registro.async_remove(registrada.entity_id)


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
