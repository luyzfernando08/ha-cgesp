"""Sensores.

Estações: estado de alerta da área monitorada.
Alertas da cidade: contadores de alagamentos, último boletim do CGE e, para
cada pessoa, rastreador ou zona escolhida, alagamentos por perto e a chuva no
local pelo radar (intensidade, distância até a chuva mais próxima e em quantos
minutos a chuva deve chegar ou parar). Também a hora da última imagem do radar.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfLength, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util
from homeassistant.util import slugify

from .cge_alertas import PontoAlagamento
from .cge_alertas_coordinator import (
    FUSO_SAO_PAULO,
    CgeAlertasCoordinator,
    async_obter_coordinator,
)
from .cge_extras import pontos_proximos
from .cge_radar import FORTE, HORIZONTE_PREVISAO, NIVEIS, SEM_CHUVA, ChegadaChuva, FimChuva
from .cge_radar_coordinator import CgeRadarCoordinator
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
from .entity import (
    CgeAlertasEntity,
    CgeEstacaoAlertaEntity,
    CgeRadarEntity,
    EntidadeAcompanhada,
    obter_radar,
    remover_orfas,
)

UNIDADE_PONTOS = "pontos"
PREFIXO_PROXIMIDADE = "cgesp_proximidade_"
PREFIXO_CHUVA = "cgesp_chuva_"
PREFIXO_CHUVA_PROXIMA = "cgesp_chuva_mais_proxima_"
PREFIXO_CHUVA_CHEGA = "cgesp_chuva_chega_em_"
PREFIXO_CHUVA_PARA = "cgesp_chuva_para_em_"
ATRIBUTO_GEOJSON_INTRANSITAVEIS = "geojson_intransitaveis"
ATRIBUTO_GEOJSON_TRANSITAVEIS = "geojson_transitaveis"


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
        radar = obter_radar(hass)
        if radar is not None:
            entidades.append(CgeRadarHorarioSensor(radar))
        por_entidade: list[SensorEntity] = []
        for entidade in acompanhadas:
            # Alagamentos perto só com os pontos no mapa (precisa das coordenadas).
            if geocodificar:
                por_entidade.append(CgeProximidadeSensor(coordinator, entidade, raio))
            if radar is not None:
                por_entidade.append(CgeChuvaSensor(radar, entidade))
                por_entidade.append(CgeChuvaProximaSensor(radar, entidade))
                por_entidade.append(CgeChuvaChegaSensor(radar, entidade))
                por_entidade.append(CgeChuvaParaSensor(radar, entidade))
        remover_orfas(
            hass,
            entry,
            "sensor",
            (
                PREFIXO_PROXIMIDADE,
                PREFIXO_CHUVA,
                PREFIXO_CHUVA_PROXIMA,
                PREFIXO_CHUVA_CHEGA,
                PREFIXO_CHUVA_PARA,
            ),
            {e.unique_id for e in por_entidade if e.unique_id},
        )
        async_add_entities([*entidades, *por_entidade])
        return

    estacao_id: int = entry.data[CONF_ESTACAO_ID]
    if not ESTACOES_REGIAO.get(estacao_id):
        return

    coordinator = await async_obter_coordinator(hass, entry.entry_id)
    async_add_entities([CgeEstadoAlertaSensor(coordinator, estacao_id)])


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
    # Os pontos no mapa mudam a cada atualização: não vão para o histórico.
    _unrecorded_attributes = frozenset(
        {ATRIBUTO_GEOJSON_INTRANSITAVEIS, ATRIBUTO_GEOJSON_TRANSITAVEIS}
    )

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
            # Pontos localizados, para cards de mapa que leem GeoJSON (como o
            # ha-map-card), separados para cada tipo ter a sua cor.
            ATRIBUTO_GEOJSON_INTRANSITAVEIS: self._geojson(transitavel=False),
            ATRIBUTO_GEOJSON_TRANSITAVEIS: self._geojson(transitavel=True),
        }

    def _geojson(self, transitavel: bool) -> dict[str, Any]:
        return {
            "type": "FeatureCollection",
            "features": [
                _ponto_geojson(ponto)
                for ponto in self.dados.pontos_ativos()
                if ponto.localizado and ponto.transitavel == transitavel
            ],
        }


def _ponto_geojson(ponto: PontoAlagamento) -> dict[str, Any]:
    # O ha-map-card mostra as 5 primeiras propriedades ao passar o mouse.
    propriedades = {
        "Local": ponto.local,
        "Bairro": f"{ponto.bairro} ({ZONAS.get(ponto.zona, ponto.zona)})",
        "Desde": ponto.inicio,
        "Passagem": "transitável" if ponto.transitavel else "intransitável",
        "Referência": ponto.referencia,
    }
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [ponto.longitude, ponto.latitude]},
        "properties": {chave: valor for chave, valor in propriedades.items() if valor},
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


class CgeProximidadeSensor(EntidadeAcompanhada, _CgeAlagamentosEntity, SensorEntity):
    """Quantos alagamentos ativos estão a até `raio_km` de uma pessoa,
    rastreador ou zona. Recalcula quando a entidade se move."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UNIDADE_PONTOS
    _attr_icon = "mdi:map-marker-radius"

    def __init__(
        self, coordinator: CgeAlertasCoordinator, entidade: str, raio_km: float
    ) -> None:
        super().__init__(coordinator)
        self._acompanhar(entidade)
        self.raio_km = raio_km
        self._attr_unique_id = f"{PREFIXO_PROXIMIDADE}{entidade}"
        self.entity_id = f"sensor.cgesp_alagamentos_perto_{self.sufixo}"

    @property
    def name(self) -> str:
        return f"Alagamentos perto de {self._nome_da_entidade()}"

    def _proximos(self) -> list[tuple[PontoAlagamento, float]] | None:
        posicao = self._posicao()
        if posicao is None:
            return None
        return pontos_proximos(*posicao, self.dados.pontos_ativos(), self.raio_km)

    @property
    def native_value(self) -> int | None:
        proximos = self._proximos()
        return None if proximos is None else len(proximos)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        proximos = self._proximos()
        atributos: dict[str, Any] = {"entidade": self.entidade, "raio_km": self.raio_km}
        if proximos is None:
            atributos["motivo"] = self._sem_posicao()
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


# --------------------------------------------------------------------------- #
# Radar de chuva
# --------------------------------------------------------------------------- #


def _atualizado_em(leitura) -> Any:
    return dt_util.as_local(leitura.obtida_em)


class CgeRadarHorarioSensor(CgeRadarEntity, SensorEntity):
    """Hora da imagem do radar (a do título; a de publicação se não der para
    ler). Muda a cada imagem nova: serve para cards recarregarem a camada de
    chuva do mapa."""

    _attr_name = "Horário do radar"
    _attr_unique_id = "cgesp_radar_horario"
    _attr_icon = "mdi:radar"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: CgeRadarCoordinator) -> None:
        super().__init__(coordinator)
        self.entity_id = "sensor.cgesp_radar_horario"

    @property
    def native_value(self) -> datetime:
        return self.leitura.horario or self.leitura.obtida_em

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"publicado_em": _atualizado_em(self.leitura)}


class CgeChuvaSensor(EntidadeAcompanhada, CgeRadarEntity, SensorEntity):
    """Intensidade da chuva agora no local da pessoa, rastreador ou zona."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = list(NIVEIS)
    _attr_translation_key = "chuva"
    _attr_icon = "mdi:weather-rainy"

    def __init__(self, coordinator: CgeRadarCoordinator, entidade: str) -> None:
        super().__init__(coordinator)
        self._acompanhar(entidade)
        self._attr_unique_id = f"{PREFIXO_CHUVA}{entidade}"
        self.entity_id = f"sensor.cgesp_chuva_{self.sufixo}"

    @property
    def name(self) -> str:
        return f"Chuva em {self._nome_da_entidade()}"

    def _nivel(self) -> tuple[int | None, str | None]:
        posicao = self._posicao()
        if posicao is None:
            return None, self._sem_posicao()
        nivel = self.leitura.nivel_em(*posicao)
        if nivel is None:
            return None, "fora da área coberta pela imagem do radar"
        return nivel, None

    @property
    def native_value(self) -> str | None:
        nivel, _ = self._nivel()
        return None if nivel is None else NIVEIS[nivel]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        _, motivo = self._nivel()
        atributos: dict[str, Any] = {
            "entidade": self.entidade,
            "radar_atualizado_em": _atualizado_em(self.leitura),
        }
        if motivo:
            atributos["motivo"] = motivo
        return atributos


class CgeChuvaProximaSensor(EntidadeAcompanhada, CgeRadarEntity, SensorEntity):
    """Distância da pessoa, rastreador ou zona até a chuva mais próxima
    (0 quando está chovendo no local)."""

    _attr_device_class = SensorDeviceClass.DISTANCE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfLength.KILOMETERS
    _attr_suggested_display_precision = 1
    _attr_icon = "mdi:map-marker-distance"

    def __init__(self, coordinator: CgeRadarCoordinator, entidade: str) -> None:
        super().__init__(coordinator)
        self._acompanhar(entidade)
        self._attr_unique_id = f"{PREFIXO_CHUVA_PROXIMA}{entidade}"
        self.entity_id = f"sensor.cgesp_chuva_mais_proxima_{self.sufixo}"

    @property
    def name(self) -> str:
        return f"Chuva mais próxima de {self._nome_da_entidade()}"

    @property
    def native_value(self) -> float | None:
        posicao = self._posicao()
        if posicao is None:
            return None
        chuva = self.leitura.chuva_mais_proxima(*posicao)
        return None if chuva is None else round(chuva.distancia_km, 2)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        atributos: dict[str, Any] = {
            "entidade": self.entidade,
            "radar_atualizado_em": _atualizado_em(self.leitura),
        }
        posicao = self._posicao()
        if posicao is None:
            atributos["motivo"] = self._sem_posicao()
            return atributos
        chuva = self.leitura.chuva_mais_proxima(*posicao)
        forte = self.leitura.chuva_mais_proxima(*posicao, nivel_minimo=FORTE)
        if chuva is None:
            atributos["motivo"] = "sem chuva na imagem do radar"
        atributos.update(
            {
                "intensidade": chuva.intensidade if chuva else None,
                "direcao": chuva.direcao if chuva else None,
                "chuva_forte_km": round(forte.distancia_km, 2) if forte else None,
                "chuva_forte_direcao": forte.direcao if forte else None,
            }
        )
        return atributos


class CgeChuvaChegaSensor(EntidadeAcompanhada, CgeRadarEntity, SensorEntity):
    """Em quantos minutos a chuva deve chegar à pessoa, rastreador ou zona,
    pelo movimento da chuva entre as últimas imagens do radar (0 quando já
    está chovendo no local)."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_suggested_display_precision = 0
    _attr_icon = "mdi:weather-pouring"

    def __init__(self, coordinator: CgeRadarCoordinator, entidade: str) -> None:
        super().__init__(coordinator)
        self._acompanhar(entidade)
        self._attr_unique_id = f"{PREFIXO_CHUVA_CHEGA}{entidade}"
        self.entity_id = f"sensor.cgesp_chuva_chega_em_{self.sufixo}"

    @property
    def name(self) -> str:
        return f"Chuva chega em {self._nome_da_entidade()}"

    def _chegada(self) -> tuple[ChegadaChuva | None, str | None]:
        posicao = self._posicao()
        if posicao is None:
            return None, self._sem_posicao()
        leitura = self.leitura
        if not leitura.coberto(*posicao):
            return None, "fora da área coberta pela imagem do radar"
        if not leitura.tem_chuva:
            return None, "sem chuva na imagem do radar"
        if leitura.movimento is None:
            return None, "movimento da chuva ainda não medido (precisa de duas imagens com chuva)"
        chegada = leitura.chegada_da_chuva(*posicao, agora=dt_util.utcnow())
        if chegada is None:
            return None, f"nenhuma chuva chegando nos próximos {HORIZONTE_PREVISAO} minutos"
        return chegada, None

    @property
    def native_value(self) -> int | None:
        chegada, _ = self._chegada()
        return None if chegada is None else chegada.minutos

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        chegada, motivo = self._chegada()
        movimento = self.leitura.movimento
        atributos: dict[str, Any] = {
            "entidade": self.entidade,
            "radar_atualizado_em": _atualizado_em(self.leitura),
            "chega_as": dt_util.as_local(chegada.chega_as) if chegada else None,
            "intensidade_maxima": chegada.intensidade_maxima if chegada else None,
            "vindo_de": movimento.vindo_de if movimento else None,
            "velocidade_kmh": round(movimento.velocidade_kmh) if movimento else None,
        }
        if motivo:
            atributos["motivo"] = motivo
        return atributos


class CgeChuvaParaSensor(EntidadeAcompanhada, CgeRadarEntity, SensorEntity):
    """Em quantos minutos a chuva deve parar na pessoa, rastreador ou zona,
    enquanto está chovendo lá, pelo movimento da chuva entre as últimas
    imagens do radar."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_suggested_display_precision = 0
    _attr_icon = "mdi:weather-partly-rainy"

    def __init__(self, coordinator: CgeRadarCoordinator, entidade: str) -> None:
        super().__init__(coordinator)
        self._acompanhar(entidade)
        self._attr_unique_id = f"{PREFIXO_CHUVA_PARA}{entidade}"
        self.entity_id = f"sensor.cgesp_chuva_para_em_{self.sufixo}"

    @property
    def name(self) -> str:
        return f"Chuva para em {self._nome_da_entidade()}"

    def _fim(self) -> tuple[FimChuva | None, str | None]:
        posicao = self._posicao()
        if posicao is None:
            return None, self._sem_posicao()
        leitura = self.leitura
        nivel = leitura.nivel_em(*posicao)
        if nivel is None:
            return None, "fora da área coberta pela imagem do radar"
        if nivel == SEM_CHUVA:
            return None, "não está chovendo no local"
        if leitura.movimento is None:
            return None, "movimento da chuva ainda não medido (precisa de duas imagens com chuva)"
        fim = leitura.fim_da_chuva(*posicao, agora=dt_util.utcnow())
        if fim is None:
            return None, "não deu para calcular"
        if fim.chuva_de_fora:
            return fim, "a chuva que vem depois ainda está fora da área do radar"
        if fim.minutos is None:
            return fim, f"a chuva deve continuar por mais de {HORIZONTE_PREVISAO} minutos"
        return fim, None

    @property
    def native_value(self) -> int | None:
        fim, _ = self._fim()
        return None if fim is None else fim.minutos

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        fim, motivo = self._fim()
        movimento = self.leitura.movimento
        atributos: dict[str, Any] = {
            "entidade": self.entidade,
            "radar_atualizado_em": _atualizado_em(self.leitura),
            "para_as": dt_util.as_local(fim.para_as) if fim and fim.para_as else None,
            "intensidade_maxima": (
                fim.intensidade_maxima if fim and fim.nivel_maximo != SEM_CHUVA else None
            ),
            "vindo_de": movimento.vindo_de if movimento else None,
            "velocidade_kmh": round(movimento.velocidade_kmh) if movimento else None,
        }
        if motivo:
            atributos["motivo"] = motivo
        return atributos
