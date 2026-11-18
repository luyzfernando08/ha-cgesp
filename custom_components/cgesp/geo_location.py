"""Pontos de alagamento ativos no mapa do Home Assistant.

Uma entidade `geo_location` por ponto ativo que pôde ser localizado. Elas
aparecem e somem conforme o CGE abre e encerra os alagamentos, e funcionam
com o cartão de mapa (`geo_location_sources: [cgesp]`) e com o gatilho
`geo_location` das automações.
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.geo_location import GeolocationEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfLength
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import async_generate_entity_id
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util.location import distance

from .cge_alertas import PontoAlagamento
from .cge_alertas_coordinator import CgeAlertasCoordinator, async_obter_coordinator
from .const import CONF_GEOCODIFICAR, DOMAIN, ZONAS


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    if not entry.options.get(CONF_GEOCODIFICAR):
        return

    coordinator = await async_obter_coordinator(hass, entry.entry_id)
    gerente = _GerentePontos(hass, coordinator, async_add_entities)
    entry.async_on_unload(coordinator.async_add_listener(gerente.atualizar))
    entry.async_on_unload(gerente.remover_todos)
    gerente.atualizar()


class _GerentePontos:
    """Cria e remove entidades conforme os pontos ativos mudam."""

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: CgeAlertasCoordinator,
        async_add_entities: AddEntitiesCallback,
    ) -> None:
        self.hass = hass
        self.coordinator = coordinator
        self.async_add_entities = async_add_entities
        self.entidades: dict[str, CgePontoAlagamentoEvent] = {}

    def _pontos_atuais(self) -> dict[str, PontoAlagamento]:
        dados = self.coordinator.data
        if dados is None or not dados.alagamentos_disponiveis:
            # Sem dados novos (site fora do ar): mantém o que está no mapa.
            return {chave: e.ponto for chave, e in self.entidades.items()}
        return {p.chave: p for p in dados.pontos_ativos() if p.localizado}

    @callback
    def atualizar(self) -> None:
        atuais = self._pontos_atuais()

        for chave in list(self.entidades):
            if chave not in atuais:
                self._remover(self.entidades.pop(chave))

        novas = []
        for chave, ponto in atuais.items():
            entidade = self.entidades.get(chave)
            if entidade is None:
                # Dois pontos na mesma rua viram ..._rua e ..._rua_2.
                entity_id = async_generate_entity_id(
                    "geo_location.{}",
                    f"cgesp {ponto.local}",
                    current_ids=[e.entity_id for e in self.entidades.values()],
                    hass=self.hass,
                )
                entidade = CgePontoAlagamentoEvent(ponto, entity_id)
                self.entidades[chave] = entidade
                novas.append(entidade)
            else:
                entidade.atualizar(ponto)

        if novas:
            self.async_add_entities(novas)

    def _remover(self, entidade: CgePontoAlagamentoEvent) -> None:
        if entidade.hass is not None:
            self.hass.async_create_task(entidade.async_remove(force_remove=True))

    @callback
    def remover_todos(self) -> None:
        for entidade in self.entidades.values():
            self._remover(entidade)
        self.entidades.clear()


class CgePontoAlagamentoEvent(GeolocationEvent):
    """Um ponto de alagamento ativo. O estado é a distância até a sua casa (km)."""

    _attr_should_poll = False
    _attr_source = DOMAIN
    _attr_unit_of_measurement = UnitOfLength.KILOMETERS
    _attr_icon = "mdi:home-flood"
    _attr_attribution = "Dados: cgesp.org; localização: © OpenStreetMap"

    def __init__(self, ponto: PontoAlagamento, entity_id: str) -> None:
        self.ponto = ponto
        self._attr_name = f"Alagamento {ponto.local}"
        self.entity_id = entity_id
        self._aplicar(ponto)

    def _aplicar(self, ponto: PontoAlagamento) -> None:
        self.ponto = ponto
        self._attr_latitude = ponto.latitude
        self._attr_longitude = ponto.longitude
        self._attr_distance = None
        if self.hass is not None and ponto.localizado:
            self._calcular_distancia()

    def _calcular_distancia(self) -> None:
        metros = distance(
            self.hass.config.latitude,
            self.hass.config.longitude,
            self.ponto.latitude,
            self.ponto.longitude,
        )
        self._attr_distance = round(metros / 1000, 1) if metros is not None else None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._calcular_distancia()
        self.async_write_ha_state()

    @callback
    def atualizar(self, ponto: PontoAlagamento) -> None:
        self._aplicar(ponto)
        if self.hass is not None:
            self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        ponto = self.ponto
        return {
            "rua": ponto.local,
            "bairro": ponto.bairro,
            "zona": ZONAS.get(ponto.zona, ponto.zona),
            "referencia": ponto.referencia,
            "sentido": ponto.sentido,
            "inicio": ponto.inicio,
            "transitavel": ponto.transitavel,
            "precisao_localizacao": ponto.precisao_localizacao,
        }
