"""Coordinator compartilhado dos alertas da cidade (alagamentos e estado das áreas)."""
from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
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
)
from .const import (
    ALERTAS_UPDATE_INTERVAL,
    DATA_ALERTAS_COORDINATOR,
    DATA_ALERTAS_USUARIOS,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

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
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_alertas",
            update_interval=ALERTAS_UPDATE_INTERVAL,
        )

    async def _async_update_data(self) -> CgeAlertasData:
        try:
            return await self.alertas.get()
        except CgeAlertasError as err:
            raise UpdateFailed(str(err)) from err
        finally:
            sincronizar_reparos(self.hass, self.alertas.layout_quebrado)


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
