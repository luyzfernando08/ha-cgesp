"""Diagnóstico para anexar em issues (Configurações > Integrações > CGE - SP >
⋮ > Baixar diagnóstico).

Traz o que a integração leu do site na última atualização, para entender
problemas de layout sem precisar reproduzir. A posição de pessoas e zonas
não é incluída, só os nomes das entidades acompanhadas.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .cge_alertas_coordinator import obter_coordinator_existente
from .const import CONF_ESTACAO_ID, ESTACOES, ESTACOES_REGIAO
from .entity import obter_radar


def _resumo_radar(hass: HomeAssistant) -> dict[str, Any] | None:
    radar = obter_radar(hass)
    if radar is None:
        return None
    leitura = radar.data
    return {
        "ultima_atualizacao_ok": radar.last_update_success,
        "ultimo_erro": str(radar.last_exception) if radar.last_exception else None,
        "intervalo_atual": str(radar.update_interval),
        "motivo_intervalo": radar.motivo_intervalo,
        "erro_layout": radar.erro_layout,
        "falhas_seguidas": radar.falhas_seguidas,
        "falhando_desde": radar.falhando_desde.isoformat() if radar.falhando_desde else None,
        "ultima_falha": radar.ultima_falha,
        "imagem_de": leitura.obtida_em.isoformat() if leitura else None,
        "imagem_bytes": len(leitura.imagem) if leitura else None,
        "celulas_com_chuva": sum(1 for n in leitura.celulas if n) if leitura else None,
        "quadros_animacao": len(radar.animacao),
        "horario_do_radar": leitura.horario.isoformat() if leitura and leitura.horario else None,
        "movimento": (
            {
                "vx_celulas_min": round(leitura.movimento.vx, 3),
                "vy_celulas_min": round(leitura.movimento.vy, 3),
                "velocidade_kmh": round(leitura.movimento.velocidade_kmh, 1),
                "indo_para": leitura.movimento.indo_para,
                "confianca": leitura.movimento.confianca,
                "intervalo_min": leitura.movimento.minutos,
            }
            if leitura and leitura.movimento
            else None
        ),
    }


def _resumo_alertas(hass: HomeAssistant) -> dict[str, Any] | None:
    coordinator = obter_coordinator_existente(hass)
    if coordinator is None:
        return None
    dados = coordinator.data
    geocodificador = coordinator.geocodificador
    resumo: dict[str, Any] = {
        "ultima_atualizacao_ok": coordinator.last_update_success,
        "ultimo_erro": str(coordinator.last_exception) if coordinator.last_exception else None,
        "intervalo_atual": str(coordinator.update_interval),
        "motivo_intervalo": coordinator.motivo_intervalo,
        "intervalo_adaptativo": coordinator.intervalo_adaptativo,
        "layout_quebrado": dict(coordinator.alertas.layout_quebrado),
        "erros_previsao_boletim": dict(coordinator.erros_extras),
        "localizacao_no_mapa": geocodificador is not None,
        "cache_localizacao": len(geocodificador.exportar()) if geocodificador else None,
    }
    if dados is None:
        return resumo
    resumo["dados"] = {
        "data_referencia": dados.data_referencia,
        "alagamentos": (
            {zona: [asdict(p) for p in pontos] for zona, pontos in dados.alagamentos.items()}
            if dados.alagamentos is not None
            else None
        ),
        "estados_areas": dados.estados_areas,
        "mapa_atualizado_em": (
            dados.mapa_atualizado_em.isoformat() if dados.mapa_atualizado_em else None
        ),
        "mapa_png_bytes": len(dados.mapa_png) if dados.mapa_png else None,
        "boletim": (
            {
                "titulo": dados.boletim.titulo,
                "publicado_em": (
                    dados.boletim.publicado_em.isoformat()
                    if dados.boletim.publicado_em
                    else None
                ),
                "link": dados.boletim.link,
            }
            if dados.boletim
            else None
        ),
        "previsao": (
            [p.como_atributo() for p in dados.periodos_previsao]
            if dados.periodos_previsao
            else None
        ),
    }
    return resumo


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    diagnostico: dict[str, Any] = {
        "entrada": {"data": dict(entry.data), "options": dict(entry.options)},
    }
    estacao_id = entry.data.get(CONF_ESTACAO_ID)
    if estacao_id is not None:
        diagnostico["estacao"] = {
            "id": estacao_id,
            "nome": ESTACOES.get(estacao_id),
            "regiao": ESTACOES_REGIAO.get(estacao_id),
        }
    diagnostico["alertas"] = _resumo_alertas(hass)
    if entry.data.get(CONF_ESTACAO_ID) is None:
        diagnostico["radar"] = _resumo_radar(hass)
    return diagnostico
