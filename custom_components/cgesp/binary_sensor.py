"""Binary sensors: alagamento por zona e estado de atenção por estação."""
from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import slugify

from .cge_alertas_coordinator import CgeAlertasCoordinator, async_obter_coordinator
from .const import (
    CONF_ESTACAO_ID,
    CONF_TIPO,
    ESTACOES_REGIAO,
    ESTADO_OBSERVACAO,
    TIPO_ALERTAS_CIDADE,
    ZONAS,
)
from .entity import CgeAlertasEntity, CgeEstacaoAlertaEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    if entry.data.get(CONF_TIPO) == TIPO_ALERTAS_CIDADE:
        coordinator = await async_obter_coordinator(hass, entry.entry_id)
        async_add_entities(
            CgeAlagamentoZonaBinarySensor(coordinator, zona) for zona in ZONAS
        )
        return

    estacao_id: int = entry.data[CONF_ESTACAO_ID]
    if not ESTACOES_REGIAO.get(estacao_id):
        return

    coordinator = await async_obter_coordinator(hass, entry.entry_id)
    async_add_entities([CgeAtencaoEstacaoBinarySensor(coordinator, estacao_id)])


class CgeAlagamentoZonaBinarySensor(CgeAlertasEntity, BinarySensorEntity):
    """Ligado quando a zona tem ao menos um ponto de alagamento ativo."""

    _attr_device_class = BinarySensorDeviceClass.MOISTURE

    def __init__(self, coordinator: CgeAlertasCoordinator, zona: str) -> None:
        super().__init__(coordinator)
        self.zona = zona
        self._attr_unique_id = f"cgesp_alagamento_{zona}"
        self._attr_name = f"Alagamento {ZONAS[zona]}"
        self.entity_id = f"binary_sensor.cgesp_alagamento_{slugify(ZONAS[zona])}"

    @property
    def available(self) -> bool:
        # Se só o mapa falhar, os alagamentos seguem disponíveis (e vice-versa).
        return super().available and self.dados.alagamentos_disponiveis

    @property
    def _pontos_ativos(self):
        return [p for p in self.dados.pontos_da_zona(self.zona) if p.ativo]

    @property
    def is_on(self) -> bool:
        return bool(self._pontos_ativos)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        todos = self.dados.pontos_da_zona(self.zona)
        ativos = self._pontos_ativos
        return {
            "zona": ZONAS[self.zona],
            "data_referencia": self.dados.data_referencia,
            "bairros": list(dict.fromkeys(p.bairro for p in ativos)),
            "ruas": list(dict.fromkeys(p.local for p in ativos)),
            "pontos_ativos": len(ativos),
            "pontos_intransitaveis": sum(1 for p in ativos if not p.transitavel),
            "pontos_encerrados_hoje": len(todos) - len(ativos),
            "pontos": [p.como_atributo() for p in ativos],
        }


class CgeAtencaoEstacaoBinarySensor(CgeEstacaoAlertaEntity, BinarySensorEntity):
    """Ligado quando a área da estação está em Atenção ou pior."""

    _attr_device_class = BinarySensorDeviceClass.SAFETY

    def __init__(self, coordinator: CgeAlertasCoordinator, estacao_id: int) -> None:
        super().__init__(coordinator, estacao_id)
        self._attr_unique_id = f"cge_{estacao_id}_atencao"
        self._attr_name = f"{self.nome_estacao} Estado de atenção"
        self.entity_id = f"binary_sensor.cgesp_{slugify(self.nome_estacao)}_atencao"

    @property
    def is_on(self) -> bool | None:
        estado = self.estado
        if estado is None:
            return None
        return estado != ESTADO_OBSERVACAO
