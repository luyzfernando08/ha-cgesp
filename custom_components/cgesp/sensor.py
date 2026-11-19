"""Sensores.

Estações: estado de alerta da área monitorada.
Alertas da cidade: contadores de alagamentos, último boletim do CGE e
alagamentos perto de pessoas, rastreadores ou zonas.
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_FRIENDLY_NAME, ATTR_LATITUDE, ATTR_LONGITUDE
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import dt as dt_util
from homeassistant.util import slugify

from .cge_alertas import PontoAlagamento
from .cge_alertas_coordinator import (
    FUSO_SAO_PAULO,
    CgeAlertasCoordinator,
    async_obter_coordinator,
)
from .cge_extras import pontos_proximos
from .const import (
    CONF_ENTIDADES_PROXIMIDADE,
    CONF_ESTACAO_ID,
    CONF_GEOCODIFICAR,
    CONF_RAIO_KM,
    CONF_TIPO,
    ESTACOES_REGIAO,
    ESTADOS_ALERTA,
    RAIO_KM_PADRAO,
    TIPO_ALERTAS_CIDADE,
    ZONAS,
)
from .entity import CgeAlertasEntity, CgeEstacaoAlertaEntity

UNIDADE_PONTOS = "pontos"
PREFIXO_PROXIMIDADE = "cgesp_proximidade_"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    if entry.data.get(CONF_TIPO) == TIPO_ALERTAS_CIDADE:
        coordinator = await async_obter_coordinator(hass, entry.entry_id)
        entidades: list[SensorEntity] = [
            CgeAlagamentosAtivosSensor(coordinator, None),
            *(CgeAlagamentosAtivosSensor(coordinator, zona) for zona in ZONAS),
            CgeAlagamentosHojeSensor(coordinator),
            CgeBoletimSensor(coordinator),
        ]
        raio = float(entry.options.get(CONF_RAIO_KM, RAIO_KM_PADRAO))
        geocodificar = bool(entry.options.get(CONF_GEOCODIFICAR, False))
        acompanhadas = list(entry.options.get(CONF_ENTIDADES_PROXIMIDADE, []))
        _remover_proximidade_antiga(hass, entry, acompanhadas)
        entidades.extend(
            CgeProximidadeSensor(coordinator, entidade, raio, geocodificar)
            for entidade in acompanhadas
        )
        async_add_entities(entidades)
        return

    estacao_id: int = entry.data[CONF_ESTACAO_ID]
    if not ESTACOES_REGIAO.get(estacao_id):
        return

    coordinator = await async_obter_coordinator(hass, entry.entry_id)
    async_add_entities([CgeEstadoAlertaSensor(coordinator, estacao_id)])


def _remover_proximidade_antiga(
    hass: HomeAssistant, entry: ConfigEntry, acompanhadas: list[str]
) -> None:
    """Quem saiu das opções não deve ficar como entidade órfã no registro."""
    registro = er.async_get(hass)
    validos = {f"{PREFIXO_PROXIMIDADE}{entidade}" for entidade in acompanhadas}
    for registrada in er.async_entries_for_config_entry(registro, entry.entry_id):
        if (
            registrada.domain == "sensor"
            and registrada.unique_id.startswith(PREFIXO_PROXIMIDADE)
            and registrada.unique_id not in validos
        ):
            registro.async_remove(registrada.entity_id)


# --------------------------------------------------------------------------- #
# Estações
# --------------------------------------------------------------------------- #


class CgeEstadoAlertaSensor(CgeEstacaoAlertaEntity, SensorEntity):
    """Observação, Atenção, Iminência de transbordamento ou Alerta."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ESTADOS_ALERTA
    _attr_translation_key = "estado_alerta"
    _attr_icon = "mdi:alert-outline"

    def __init__(self, coordinator: CgeAlertasCoordinator, estacao_id: int) -> None:
        super().__init__(coordinator, estacao_id)
        self._attr_unique_id = f"cge_{estacao_id}_estado_alerta"
        self._attr_name = f"{self.nome_estacao} Estado de alerta"
        self.entity_id = f"sensor.cgesp_{slugify(self.nome_estacao)}_estado_alerta"

    @property
    def native_value(self) -> str | None:
        return self.estado


# --------------------------------------------------------------------------- #
# Contadores
# --------------------------------------------------------------------------- #


class _CgeAlagamentosEntity(CgeAlertasEntity):
    @property
    def available(self) -> bool:
        return super().available and self.dados.alagamentos_disponiveis


class CgeAlagamentosAtivosSensor(_CgeAlagamentosEntity, SensorEntity):
    """Pontos de alagamento ativos na cidade (zona None) ou numa zona."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UNIDADE_PONTOS
    _attr_icon = "mdi:home-flood"

    def __init__(self, coordinator: CgeAlertasCoordinator, zona: str | None) -> None:
        super().__init__(coordinator)
        self.zona = zona
        if zona is None:
            self._attr_unique_id = "cgesp_alagamentos_ativos"
            self._attr_name = "Alagamentos ativos"
            self.entity_id = "sensor.cgesp_alagamentos_ativos"
        else:
            self._attr_unique_id = f"cgesp_alagamentos_ativos_{zona}"
            self._attr_name = f"Alagamentos ativos {ZONAS[zona]}"
            self.entity_id = f"sensor.cgesp_alagamentos_ativos_{slugify(ZONAS[zona])}"

    @property
    def native_value(self) -> int:
        if self.zona is None:
            return len(self.dados.pontos_ativos())
        return sum(1 for p in self.dados.pontos_da_zona(self.zona) if p.ativo)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.zona is not None:
            return None
        return {
            "data_referencia": self.dados.data_referencia,
            "por_zona": {
                nome: sum(1 for p in self.dados.pontos_da_zona(zona) if p.ativo)
                for zona, nome in ZONAS.items()
            },
        }


class CgeAlagamentosHojeSensor(_CgeAlagamentosEntity, SensorEntity):
    """Pontos registrados no dia (ativos e encerrados). Zera à meia-noite."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UNIDADE_PONTOS
    _attr_icon = "mdi:calendar-today"
    _attr_unique_id = "cgesp_alagamentos_hoje"
    _attr_name = "Alagamentos hoje"

    def __init__(self, coordinator: CgeAlertasCoordinator) -> None:
        super().__init__(coordinator)
        self.entity_id = "sensor.cgesp_alagamentos_hoje"

    @property
    def native_value(self) -> int:
        return sum(len(self.dados.pontos_da_zona(zona)) for zona in ZONAS)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        ativos = len(self.dados.pontos_ativos())
        return {
            "data_referencia": self.dados.data_referencia,
            "ativos": ativos,
            "encerrados": self.native_value - ativos,
        }


# --------------------------------------------------------------------------- #
# Boletim
# --------------------------------------------------------------------------- #


class CgeBoletimSensor(CgeAlertasEntity, SensorEntity):
    """Título do boletim mais recente do CGE; o texto fica no atributo."""

    _attr_icon = "mdi:newspaper-variant-outline"
    _attr_unique_id = "cgesp_boletim"
    _attr_name = "Boletim"

    def __init__(self, coordinator: CgeAlertasCoordinator) -> None:
        super().__init__(coordinator)
        self.entity_id = "sensor.cgesp_boletim"

    @property
    def available(self) -> bool:
        return super().available and self.dados.boletim is not None

    @property
    def native_value(self) -> str:
        return self.dados.boletim.titulo[:255]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        boletim = self.dados.boletim
        publicado_em = None
        if boletim.publicado_em is not None:
            publicado_em = boletim.publicado_em.replace(
                tzinfo=dt_util.get_time_zone(FUSO_SAO_PAULO)
            )
        return {
            "titulo": boletim.titulo,
            "texto": boletim.texto,
            "publicado_em": publicado_em,
            "link": boletim.link,
        }


# --------------------------------------------------------------------------- #
# Proximidade
# --------------------------------------------------------------------------- #


class CgeProximidadeSensor(_CgeAlagamentosEntity, SensorEntity):
    """Quantos alagamentos ativos estão a até `raio_km` de uma pessoa,
    rastreador ou zona. Recalcula quando a entidade se move."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UNIDADE_PONTOS
    _attr_icon = "mdi:map-marker-radius"

    def __init__(
        self,
        coordinator: CgeAlertasCoordinator,
        entidade: str,
        raio_km: float,
        geocodificar: bool,
    ) -> None:
        super().__init__(coordinator)
        self.entidade = entidade
        self.raio_km = raio_km
        self.geocodificar = geocodificar
        dominio, objeto = entidade.split(".", 1)
        self._attr_unique_id = f"{PREFIXO_PROXIMIDADE}{entidade}"
        sufixo = objeto if dominio == "person" else f"{dominio}_{objeto}"
        self.entity_id = f"sensor.cgesp_alagamentos_perto_{slugify(sufixo)}"
        self._objeto = objeto

    def _nome_da_entidade(self) -> str:
        estado = self.hass.states.get(self.entidade) if self.hass else None
        if estado is not None and estado.attributes.get(ATTR_FRIENDLY_NAME):
            return estado.attributes[ATTR_FRIENDLY_NAME]
        return self._objeto

    @property
    def name(self) -> str:
        return f"Alagamentos perto de {self._nome_da_entidade()}"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_track_state_change_event(
                self.hass, [self.entidade], self._entidade_mudou
            )
        )

    @callback
    def _entidade_mudou(self, _evento: Event) -> None:
        self.async_write_ha_state()

    def _posicao(self) -> tuple[float, float] | None:
        estado = self.hass.states.get(self.entidade)
        if estado is None:
            return None
        lat = estado.attributes.get(ATTR_LATITUDE)
        lon = estado.attributes.get(ATTR_LONGITUDE)
        try:
            return float(lat), float(lon)
        except (TypeError, ValueError):
            return None

    def _calcular(self) -> tuple[list[tuple[PontoAlagamento, float]] | None, str | None]:
        """(pontos próximos, motivo) — pontos None quando não dá para calcular."""
        if not self.geocodificar:
            return None, "a opção de mostrar os pontos no mapa está desligada"
        posicao = self._posicao()
        if posicao is None:
            return None, f"{self.entidade} não tem localização (latitude/longitude)"
        return pontos_proximos(*posicao, self.dados.pontos_ativos(), self.raio_km), None

    @property
    def native_value(self) -> int | None:
        proximos, _ = self._calcular()
        return None if proximos is None else len(proximos)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        proximos, motivo = self._calcular()
        atributos: dict[str, Any] = {"entidade": self.entidade, "raio_km": self.raio_km}
        if proximos is None:
            atributos["motivo"] = motivo
            return atributos
        nao_localizados = sum(1 for p in self.dados.pontos_ativos() if not p.localizado)
        atributos.update(
            {
                "mais_proximo_km": round(proximos[0][1], 1) if proximos else None,
                "ruas": [f"{p.local} ({km:.1f} km)" for p, km in proximos],
                "pontos": [
                    {
                        "zona": ZONAS.get(p.zona, p.zona),
                        **p.como_atributo(),
                        "distancia_km": round(km, 2),
                    }
                    for p, km in proximos
                ],
                # Pontos ainda sem coordenada não entram na conta.
                "pontos_sem_localizacao": nao_localizados,
            }
        )
        return atributos
