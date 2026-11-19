"""Coordinator compartilhado dos alertas da cidade (alagamentos e estado das áreas)."""
from __future__ import annotations

import asyncio
import inspect
import logging
from datetime import datetime, timedelta
from typing import Any

import requests

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .cge_alertas import (
    PARTE_ALAGAMENTOS,
    PARTE_MAPA,
    PARTES,
    URL_ALAGAMENTOS,
    URL_MAPA_AREAS,
    CgeAlertas,
    CgeAlertasData,
    CgeAlertasError,
    PontoAlagamento,
    _buscar,
    _decodificar_texto,
)
from .cge_extras import (
    INTERVALO_COM_CHUVA,
    URL_BOLETIM,
    URL_PREVISAO,
    Boletim,
    PeriodoPrevisao,
    diferenca_pontos,
    escolher_intervalo,
    parse_boletim,
    parse_periodos,
)
from .cge_geocodificacao import Geocodificador
from .const import (
    ALERTAS_UPDATE_INTERVAL,
    DATA_ALERTAS_COORDINATOR,
    DATA_ALERTAS_USUARIOS,
    DOMAIN,
    EVENTO_ALAGAMENTO_ENCERRADO,
    EVENTO_ALAGAMENTO_NOVO,
    ZONAS,
)

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY_GEO = f"{DOMAIN}.geocodificacao"
STORAGE_VERSION_GEO = 1

URL_ISSUES = "https://github.com/luyzfernando08/ha-cgesp/issues"
ISSUE_IDS_LAYOUT = {
    PARTE_ALAGAMENTOS: "layout_alagamentos",
    PARTE_MAPA: "layout_mapa_alertas",
}
URLS_POR_PARTE = {
    PARTE_ALAGAMENTOS: URL_ALAGAMENTOS,
    PARTE_MAPA: URL_MAPA_AREAS,
}

FUSO_SAO_PAULO = "America/Sao_Paulo"
VALIDADE_PREVISAO = timedelta(hours=1)


def _ler_previsao() -> list[PeriodoPrevisao]:
    return parse_periodos(_decodificar_texto(_buscar(URL_PREVISAO).content))


def _ler_boletim() -> Boletim:
    return parse_boletim(_buscar(URL_BOLETIM).content)


def kwargs_config_entry(entry: ConfigEntry | None) -> dict[str, Any]:
    """`config_entry=` para o DataUpdateCoordinator, quando o HA aceita.

    O HA associa o coordinator a uma entrada e o desliga quando ela é
    descarregada. As versões novas pedem a entrada explicitamente; as antigas
    não têm o parâmetro e usam a entrada que estava sendo configurada.
    """
    if "config_entry" in inspect.signature(DataUpdateCoordinator.__init__).parameters:
        return {"config_entry": entry}
    return {}


def dados_evento(ponto: PontoAlagamento) -> dict[str, Any]:
    return {
        "zona": ZONAS.get(ponto.zona, ponto.zona),
        "zona_id": ponto.zona,
        **ponto.como_atributo(),
        "fim": ponto.fim,
    }


class CgeAlertasCoordinator(DataUpdateCoordinator[CgeAlertasData]):
    def __init__(self, hass: HomeAssistant) -> None:
        self.alertas = CgeAlertas(hass=hass)
        self.geocodificador: Geocodificador | None = None
        self._store_geo: Store | None = None
        self._tarefa_geo: asyncio.Task | None = None
        # Intervalo adaptativo (opção de "Alertas da cidade"; ligado por padrão).
        self.intervalo_adaptativo = True
        # O boletim só tem sensor em "Alertas da cidade"; sem ela, não é baixado.
        self.buscar_boletim = False
        self.motivo_intervalo: str | None = None
        self._periodos: list[PeriodoPrevisao] | None = None
        self._previsao_lida_em: datetime | None = None
        self._boletim: Boletim | None = None
        self.erros_extras: dict[str, str] = {}
        # Pontos ativos da leitura anterior (None até a primeira leitura).
        self._pontos_anteriores: dict[str, PontoAlagamento] | None = None
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_alertas",
            update_interval=ALERTAS_UPDATE_INTERVAL,
            # Compartilhado por todas as entradas: não pertence a nenhuma
            # (ver async_obter_coordinator).
            **kwargs_config_entry(None),
        )

    async def _async_update_data(self) -> CgeAlertasData:
        try:
            dados, _ = await asyncio.gather(self.alertas.get(), self._atualizar_extras())
        except CgeAlertasError as err:
            self._definir_intervalo(None)
            raise UpdateFailed(str(err)) from err
        finally:
            sincronizar_reparos(self.hass, self.alertas.layout_quebrado)
        dados.boletim = self._boletim
        dados.periodos_previsao = self._periodos
        self._localizar(dados)
        self._disparar_eventos(dados)
        self._definir_intervalo(dados)
        return dados

    # ------------------------------------------------ previsão e boletim

    def _agora_local(self) -> datetime:
        fuso = dt_util.get_time_zone(FUSO_SAO_PAULO)
        return dt_util.now(fuso).replace(tzinfo=None)

    async def _tentar_extra(self, nome: str, funcao):
        try:
            valor = await self.hass.async_add_executor_job(funcao)
        except (
            requests.exceptions.RequestException,
            CgeAlertasError,
            AttributeError,
            IndexError,
            KeyError,
            TypeError,
            ValueError,
        ) as err:
            if nome not in self.erros_extras:
                _LOGGER.info("CGE: não foi possível ler %s: %s", nome, err)
            self.erros_extras[nome] = str(err)
            return None
        if nome in self.erros_extras:
            self.erros_extras.pop(nome)
            _LOGGER.info("CGE: %s voltou a funcionar", nome)
        return valor

    async def _atualizar_extras(self) -> None:
        """Previsão (no máximo 1x por hora) e último boletim. Falhas aqui
        nunca derrubam os alertas: a previsão só ajusta o intervalo."""
        agora = self._agora_local()
        previsao_vencida = (
            self._previsao_lida_em is None
            or agora - self._previsao_lida_em >= VALIDADE_PREVISAO
        )

        async def _nada() -> None:
            return None

        boletim, periodos = await asyncio.gather(
            self._tentar_extra("boletim", _ler_boletim) if self.buscar_boletim else _nada(),
            self._tentar_extra("previsão", _ler_previsao) if previsao_vencida else _nada(),
        )
        if boletim is not None:
            self._boletim = boletim
        if periodos is not None:
            self._periodos = periodos
            self._previsao_lida_em = agora

    def definir_intervalo_adaptativo(self, ativo: bool) -> None:
        """Aplica a opção já, sem esperar a próxima leitura (que, com o
        intervalo antigo, poderia demorar até 30 minutos)."""
        self.intervalo_adaptativo = ativo
        self._definir_intervalo(self.data if self.last_update_success else None)

    def _definir_intervalo(self, dados: CgeAlertasData | None) -> None:
        if not self.intervalo_adaptativo:
            intervalo, motivo = ALERTAS_UPDATE_INTERVAL, "intervalo fixo (opção desligada)"
        elif dados is None:
            intervalo, motivo = INTERVALO_COM_CHUVA, "falha ao ler o CGE"
        else:
            intervalo, motivo = escolher_intervalo(dados, self._periodos, self._agora_local())
        if intervalo != self.update_interval:
            _LOGGER.debug("CGE: atualizando a cada %s (%s)", intervalo, motivo)
        self.update_interval = intervalo
        self.motivo_intervalo = motivo

    # ------------------------------------------------ eventos

    def _disparar_eventos(self, dados: CgeAlertasData) -> None:
        """cgesp_alagamento_novo / cgesp_alagamento_encerrado.

        A primeira leitura só serve de base (não dispara um evento para cada
        ponto já ativo quando o HA inicia). Com os alagamentos indisponíveis,
        nada muda: site fora do ar não encerra alagamento.
        """
        if not dados.alagamentos_disponiveis:
            return
        atuais = {p.chave: p for p in dados.pontos_ativos()}
        anteriores = self._pontos_anteriores
        self._pontos_anteriores = atuais
        if anteriores is None:
            return
        novos, encerrados = diferenca_pontos(anteriores, atuais)
        for ponto in novos:
            self.hass.bus.async_fire(EVENTO_ALAGAMENTO_NOVO, dados_evento(ponto))
        for ponto in encerrados:
            self.hass.bus.async_fire(EVENTO_ALAGAMENTO_ENCERRADO, dados_evento(ponto))

    # ------------------------------------------------ geocodificação (opcional)

    async def async_definir_geocodificacao(self, ativa: bool) -> None:
        """Liga/desliga a localização dos pontos (opção de "Alertas da cidade")."""
        if not ativa:
            self.geocodificador = None
            if self._tarefa_geo is not None and not self._tarefa_geo.done():
                self._tarefa_geo.cancel()
            return
        if self.geocodificador is not None:
            return

        self._store_geo = Store(self.hass, STORAGE_VERSION_GEO, STORAGE_KEY_GEO)
        geocodificador = Geocodificador(self.hass.async_add_executor_job)
        geocodificador.importar(await self._store_geo.async_load() or {})
        self.geocodificador = geocodificador
        if self.data is not None:
            self._localizar(self.data)
            self.async_update_listeners()

    def _localizar(self, dados: CgeAlertasData) -> None:
        """Aplica o cache já; pontos novos são localizados em segundo plano
        para não atrasar os sensores (o Nominatim aceita 1 consulta/s)."""
        if self.geocodificador is None:
            return
        pendentes = self.geocodificador.aplicar_cache(dados.pontos_ativos())
        if not pendentes:
            return
        if self._tarefa_geo is not None and not self._tarefa_geo.done():
            return  # a rodada em andamento cuida; o resto fica para a próxima
        self._tarefa_geo = self.hass.async_create_background_task(
            self._localizar_pendentes(self.geocodificador, pendentes),
            name=f"{DOMAIN}_geocodificacao",
        )

    async def _localizar_pendentes(
        self, geocodificador: Geocodificador, pendentes: list[PontoAlagamento]
    ) -> None:
        try:
            novidade = await geocodificador.localizar(pendentes)
        except Exception:  # noqa: BLE001 - localização nunca deve derrubar os alertas
            _LOGGER.exception("Erro inesperado ao localizar pontos de alagamento")
            return
        if not novidade or geocodificador is not self.geocodificador:
            return
        if self._store_geo is not None:
            self._store_geo.async_delay_save(geocodificador.exportar, 30)
        if self.data is not None:
            geocodificador.aplicar_cache(self.data.pontos_ativos())
            self.async_update_listeners()


def _issue_id(parte: str) -> str:
    return ISSUE_IDS_LAYOUT[parte]


def sincronizar_reparos(hass: HomeAssistant, layout_quebrado: dict[str, str]) -> None:
    """Abre um aviso em Configurações > Reparos para cada parte com layout
    não reconhecido e fecha os avisos das partes que voltaram a funcionar."""
    for parte in PARTES:
        erro = layout_quebrado.get(parte)
        if erro is None:
            ir.async_delete_issue(hass, DOMAIN, _issue_id(parte))
            continue
        ir.async_create_issue(
            hass,
            DOMAIN,
            _issue_id(parte),
            is_fixable=False,
            is_persistent=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="layout_alterado",
            translation_placeholders={
                "parte": parte,
                "url": URLS_POR_PARTE[parte],
                "erro": erro,
            },
            learn_more_url=URL_ISSUES,
        )


def remover_reparos(hass: HomeAssistant) -> None:
    for parte in PARTES:
        ir.async_delete_issue(hass, DOMAIN, _issue_id(parte))


async def async_obter_coordinator(
    hass: HomeAssistant, entry_id: str, alertas_cidade: bool = False
) -> CgeAlertasCoordinator:
    """Retorna o coordinator único da integração, criando-o no primeiro uso.

    Todas as entradas (estações e "Alertas da cidade") compartilham a mesma
    consulta ao site, feita a cada 10 minutos.
    """
    dados = hass.data.setdefault(DOMAIN, {})
    usuarios: set[str] = dados.setdefault(DATA_ALERTAS_USUARIOS, set())
    usuarios.add(entry_id)

    coordinator: CgeAlertasCoordinator | None = dados.get(DATA_ALERTAS_COORDINATOR)
    if coordinator is None:
        # Sem isso, o HA associaria o coordinator à entrada que está sendo
        # configurada agora e o desligaria quando ela fosse removida ou
        # recarregada (ex.: ao mudar as opções), parando as outras entradas.
        contexto = config_entries.current_entry.set(None)
        try:
            coordinator = CgeAlertasCoordinator(hass)
        finally:
            config_entries.current_entry.reset(contexto)
        coordinator.buscar_boletim = alertas_cidade
        dados[DATA_ALERTAS_COORDINATOR] = coordinator
        await coordinator.async_refresh()
    elif alertas_cidade and not coordinator.buscar_boletim:
        # Já existia por causa das estações: lê o boletim agora, sem esperar o ciclo.
        coordinator.buscar_boletim = True
        await coordinator.async_refresh()
    return coordinator


def obter_coordinator_existente(hass: HomeAssistant) -> CgeAlertasCoordinator | None:
    return hass.data.get(DOMAIN, {}).get(DATA_ALERTAS_COORDINATOR)


def liberar_coordinator(hass: HomeAssistant, entry_id: str) -> None:
    """Remove a entrada dos usuários; descarta o coordinator quando ninguém mais usa."""
    dados = hass.data.get(DOMAIN, {})
    usuarios: set[str] = dados.get(DATA_ALERTAS_USUARIOS, set())
    usuarios.discard(entry_id)
    if not usuarios:
        # Sem entidades ouvindo, o coordinator já parou de agendar atualizações.
        dados.pop(DATA_ALERTAS_COORDINATOR, None)
        # Ninguém mais consulta os alertas: avisos de layout não fazem sentido.
        remover_reparos(hass)
