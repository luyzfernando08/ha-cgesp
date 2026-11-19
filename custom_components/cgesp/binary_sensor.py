"""Binary sensors: alagamento por zona, estado de atenção por estação e
chovendo agora no local de cada pessoa, rastreador ou zona escolhida."""
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
from .cge_radar import NIVEIS, SEM_CHUVA
from .cge_radar_coordinator import CgeRadarCoordinator
from .const import (
    CONF_ENTIDADES_PROXIMIDADE,
    CONF_ESTACAO_ID,
    CONF_TIPO,
    ESTACOES_REGIAO,
    ESTADO_OBSERVACAO,
    TIPO_ALERTAS_CIDADE,
    ZONAS,
)
from .entity import (
    CgeAlertasEntity,
    CgeEstacaoAlertaEntity,
    CgeRadarEntity,
    EntidadeAcompanhada,
    obter_radar,
    remover_orfas,
)

PREFIXO_CHOVENDO = "cgesp_chovendo_"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    if entry.data.get(CONF_TIPO) == TIPO_ALERTAS_CIDADE:
        coordinator = await async_obter_coordinator(hass, entry.entry_id)
        entidades: list[BinarySensorEntity] = [
            CgeAlagamentoZonaBinarySensor(coordinator, zona) for zona in ZONAS
        ]
        radar = obter_radar(hass)
        chovendo = (
            [
                CgeChovendoBinarySensor(radar, entidade)
                for entidade in entry.options.get(CONF_ENTIDADES_PROXIMIDADE, [])
            ]
            if radar is not None
            else []
        )
        remover_orfas(
            hass,
            entry,
            "binary_sensor",
            (PREFIXO_CHOVENDO,),
            {e.unique_id for e in chovendo if e.unique_id},
        )
        async_add_entities([*entidades, *chovendo])
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


class CgeChovendoBinarySensor(EntidadeAcompanhada, CgeRadarEntity, BinarySensorEntity):
    """Ligado quando o radar mostra chuva (de fraca para cima) no local."""

    _attr_device_class = BinarySensorDeviceClass.MOISTURE
    _attr_icon = "mdi:weather-pouring"

    def __init__(self, coordinator: CgeRadarCoordinator, entidade: str) -> None:
        super().__init__(coordinator)
        self._acompanhar(entidade)
        self._attr_unique_id = f"{PREFIXO_CHOVENDO}{entidade}"
        self.entity_id = f"binary_sensor.cgesp_chovendo_{self.sufixo}"

    @property
    def name(self) -> str:
        return f"Chovendo em {self._nome_da_entidade()}"

    def _nivel(self) -> int | None:
        posicao = self._posicao()
        return None if posicao is None else self.leitura.nivel_em(*posicao)

    @property
    def is_on(self) -> bool | None:
        nivel = self._nivel()
        return None if nivel is None else nivel > SEM_CHUVA

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        nivel = self._nivel()
        return {
            "entidade": self.entidade,
            "intensidade": None if nivel is None else NIVEIS[nivel],
        }
