"""Diário de bordo: os eventos de alagamento viram frases legíveis.

Sem isto, `cgesp_alagamento_novo` e `cgesp_alagamento_encerrado` aparecem
crus no Diário de bordo. Cada entrada também é ligada ao sensor de alagamento
da zona, então aparece no histórico dele.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.components.logbook import (
    LOGBOOK_ENTRY_ENTITY_ID,
    LOGBOOK_ENTRY_MESSAGE,
    LOGBOOK_ENTRY_NAME,
)
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN, EVENTO_ALAGAMENTO_ENCERRADO, EVENTO_ALAGAMENTO_NOVO

NOME = "CGE - SP"


def descrever_ponto(dados: dict[str, Any]) -> str:
    """'Avenida X, altura do número 10 (Itaim Paulista, Zona Leste)'."""
    local = dados.get("local") or "local não informado"
    referencia = dados.get("referencia")
    if referencia:
        local = f"{local}, {referencia}"
    regiao = ", ".join(p for p in (dados.get("bairro"), dados.get("zona")) if p)
    return f"{local} ({regiao})" if regiao else local


def mensagem(tipo_evento: str, dados: dict[str, Any]) -> str:
    ponto = descrever_ponto(dados)
    if tipo_evento == EVENTO_ALAGAMENTO_ENCERRADO:
        return f"alagamento encerrado: {ponto}"
    situacao = "transitável" if dados.get("transitavel") else "intransitável"
    return f"novo alagamento: {ponto}, {situacao}"


@callback
def async_describe_events(
    hass: HomeAssistant,
    async_describe_event: Callable[[str, str, Callable[[Event], dict[str, str]]], None],
) -> None:
    @callback
    def descrever(evento: Event) -> dict[str, str]:
        descricao = {
            LOGBOOK_ENTRY_NAME: NOME,
            LOGBOOK_ENTRY_MESSAGE: mensagem(evento.event_type, evento.data),
        }
        zona = evento.data.get("zona_id")
        if zona:
            entity_id = er.async_get(hass).async_get_entity_id(
                "binary_sensor", DOMAIN, f"cgesp_alagamento_{zona}"
            )
            if entity_id:
                descricao[LOGBOOK_ENTRY_ENTITY_ID] = entity_id
        return descricao

    async_describe_event(DOMAIN, EVENTO_ALAGAMENTO_NOVO, descrever)
    async_describe_event(DOMAIN, EVENTO_ALAGAMENTO_ENCERRADO, descrever)
