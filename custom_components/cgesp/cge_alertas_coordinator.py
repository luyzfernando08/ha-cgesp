"""Coordinator compartilhado dos alertas da cidade (alagamentos e estado das áreas)."""
from __future__ import annotations

import asyncio
import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

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
)
from .cge_geocodificacao import Geocodificador
from .const import (
    ALERTAS_UPDATE_INTERVAL,
    DATA_ALERTAS_COORDINATOR,
    DATA_ALERTAS_USUARIOS,
    DOMAIN,
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


class CgeAlertasCoordinator(DataUpdateCoordinator[CgeAlertasData]):
    def __init__(self, hass: HomeAssistant) -> None:
        self.alertas = CgeAlertas(hass=hass)
        self.geocodificador: Geocodificador | None = None
        self._store_geo: Store | None = None
        self._tarefa_geo: asyncio.Task | None = None
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_alertas",
            update_interval=ALERTAS_UPDATE_INTERVAL,
        )

    async def _async_update_data(self) -> CgeAlertasData:
        try:
            dados = await self.alertas.get()
        except CgeAlertasError as err:
            raise UpdateFailed(str(err)) from err
        finally:
            sincronizar_reparos(self.hass, self.alertas.layout_quebrado)
        self._localizar(dados)
        return dados

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


async def async_obter_coordinator(hass: HomeAssistant, entry_id: str) -> CgeAlertasCoordinator:
    """Retorna o coordinator único da integração, criando-o no primeiro uso.

    Todas as entradas (estações e "Alertas da cidade") compartilham a mesma
    consulta ao site, feita a cada 10 minutos.
    """
    dados = hass.data.setdefault(DOMAIN, {})
    usuarios: set[str] = dados.setdefault(DATA_ALERTAS_USUARIOS, set())
    usuarios.add(entry_id)

    coordinator: CgeAlertasCoordinator | None = dados.get(DATA_ALERTAS_COORDINATOR)
    if coordinator is None:
        coordinator = CgeAlertasCoordinator(hass)
        dados[DATA_ALERTAS_COORDINATOR] = coordinator
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
