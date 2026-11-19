"""Pontos no mapa (geo_location) e alagamentos perto de pessoas e zonas.

A posição dos pontos vem do cache salvo do geocodificador (`hass_storage`),
então nenhum teste consulta o OpenStreetMap.
"""
import time

import pytest
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cgesp.cge_alertas import _decodificar_texto, _parse_alagamentos
from custom_components.cgesp.cge_alertas_coordinator import STORAGE_KEY_GEO
from custom_components.cgesp.cge_geocodificacao import chave_ponto
from custom_components.cgesp.const import (
    CONF_ENTIDADES_PROXIMIDADE,
    CONF_GEOCODIFICAR,
    CONF_RAIO_KM,
    CONF_TIPO,
    DOMAIN,
    TIPO_ALERTAS_CIDADE,
    UNIQUE_ID_ALERTAS_CIDADE,
)

from .conftest import URL_ALAGAMENTOS, SiteCge

# O único ponto ativo da fixture alagamentos.html.
MARECHAL_TITO = (-23.4935, -46.4140)
PERTO = (-23.5000, -46.4200)  # ~1 km
LONGE = (-23.5614, -46.6559)  # Av. Paulista, ~26 km


@pytest.fixture
def cache_geo(hass_storage) -> None:
    html = _decodificar_texto(SiteCge.fixture("alagamentos.html"))
    (ponto,) = [p for p in _parse_alagamentos(html).pontos["leste"] if p.ativo]
    hass_storage[STORAGE_KEY_GEO] = {
        "version": 1,
        "minor_version": 1,
        "key": STORAGE_KEY_GEO,
        "data": {
            chave_ponto(ponto): {
                "localizacao": {
                    "latitude": MARECHAL_TITO[0],
                    "longitude": MARECHAL_TITO[1],
                    "precisao": "numero",
                },
                "quando": time.time(),
            }
        },
    }


def _pessoa(hass: HomeAssistant, posicao: tuple[float, float] | None) -> None:
    atributos = {"friendly_name": "João"}
    if posicao is not None:
        atributos.update(latitude=posicao[0], longitude=posicao[1])
    hass.states.async_set("person.joao", "home", atributos)


async def _configurar(hass: HomeAssistant, **opcoes) -> MockConfigEntry:
    entrada = MockConfigEntry(
        domain=DOMAIN,
        unique_id=UNIQUE_ID_ALERTAS_CIDADE,
        data={CONF_TIPO: TIPO_ALERTAS_CIDADE},
        options=opcoes,
    )
    entrada.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entrada.entry_id)
    await hass.async_block_till_done()
    return entrada


async def test_ponto_no_mapa(hass: HomeAssistant, site_cge, cache_geo) -> None:
    await _configurar(hass, **{CONF_GEOCODIFICAR: True})

    pontos = hass.states.async_entity_ids("geo_location")
    assert pontos == ["geo_location.cgesp_avenida_marechal_tito"]
    ponto = hass.states.get(pontos[0])
    assert ponto.attributes["latitude"] == MARECHAL_TITO[0]
    assert ponto.attributes["longitude"] == MARECHAL_TITO[1]
    assert ponto.attributes["source"] == DOMAIN
    assert ponto.attributes["zona"] == "Zona Leste"
    assert ponto.attributes["transitavel"] is False
    # Já estava no cache: o OpenStreetMap não foi consultado.
    assert not any("nominatim" in url for url in site_cge.consultas)


async def test_ponto_sai_do_mapa_quando_encerra(
    hass: HomeAssistant, site_cge, cache_geo
) -> None:
    await _configurar(hass, **{CONF_GEOCODIFICAR: True})
    coordinator = hass.data[DOMAIN]["alertas_coordinator"]

    # Site fora do ar: o ponto continua no mapa.
    site_cge.paginas[URL_ALAGAMENTOS] = None
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert len(hass.states.async_entity_ids("geo_location")) == 1

    site_cge.paginas[URL_ALAGAMENTOS] = site_cge.fixture("alagamentos_vazio.html")
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.async_entity_ids("geo_location") == []


async def test_alagamento_perto_de_pessoa(hass: HomeAssistant, site_cge, cache_geo) -> None:
    _pessoa(hass, PERTO)
    await _configurar(
        hass,
        **{
            CONF_GEOCODIFICAR: True,
            CONF_ENTIDADES_PROXIMIDADE: ["person.joao"],
            CONF_RAIO_KM: 2.0,
        },
    )

    sensor = hass.states.get("sensor.cgesp_alagamentos_perto_joao")
    assert sensor.state == "1"
    # O HA atual põe o nome do dispositivo ("CGE - SP") na frente.
    assert sensor.attributes["friendly_name"].endswith("Alagamentos perto de João")
    assert sensor.attributes["raio_km"] == 2.0
    assert sensor.attributes["mais_proximo_km"] == pytest.approx(0.9, abs=0.2)
    assert sensor.attributes["ruas"][0].startswith("Avenida Marechal Tito (")

    # Recalcula quando a pessoa se move.
    _pessoa(hass, LONGE)
    await hass.async_block_till_done()
    sensor = hass.states.get("sensor.cgesp_alagamentos_perto_joao")
    assert sensor.state == "0"
    assert sensor.attributes["mais_proximo_km"] is None


async def test_proximidade_de_zona_e_rastreador(hass: HomeAssistant, site_cge, cache_geo) -> None:
    hass.states.async_set(
        "zone.trabalho", "0", {"latitude": PERTO[0], "longitude": PERTO[1]}
    )
    hass.states.async_set("device_tracker.celular", "not_home", {})
    await _configurar(
        hass,
        **{
            CONF_GEOCODIFICAR: True,
            CONF_ENTIDADES_PROXIMIDADE: ["zone.trabalho", "device_tracker.celular"],
        },
    )

    assert hass.states.get("sensor.cgesp_alagamentos_perto_zone_trabalho").state == "1"
    # Sem latitude/longitude não dá para calcular: estado desconhecido, com o motivo.
    celular = hass.states.get("sensor.cgesp_alagamentos_perto_device_tracker_celular")
    assert celular.state == "unknown"
    assert "não tem localização" in celular.attributes["motivo"]


async def test_remover_pessoa_das_opcoes_apaga_o_sensor(
    hass: HomeAssistant, site_cge, cache_geo
) -> None:
    _pessoa(hass, PERTO)
    entrada = await _configurar(
        hass,
        **{CONF_GEOCODIFICAR: True, CONF_ENTIDADES_PROXIMIDADE: ["person.joao"]},
    )
    registro = er.async_get(hass)
    assert registro.async_get("sensor.cgesp_alagamentos_perto_joao") is not None

    hass.config_entries.async_update_entry(
        entrada, options={CONF_GEOCODIFICAR: True, CONF_ENTIDADES_PROXIMIDADE: []}
    )
    await hass.async_block_till_done()

    assert registro.async_get("sensor.cgesp_alagamentos_perto_joao") is None
    assert hass.states.get("sensor.cgesp_alagamentos_perto_joao") is None


async def test_desligar_o_mapa_tira_os_pontos(hass: HomeAssistant, site_cge, cache_geo) -> None:
    entrada = await _configurar(hass, **{CONF_GEOCODIFICAR: True})
    assert len(hass.states.async_entity_ids("geo_location")) == 1

    hass.config_entries.async_update_entry(entrada, options={CONF_GEOCODIFICAR: False})
    await hass.async_block_till_done()

    assert hass.states.async_entity_ids("geo_location") == []
    assert hass.states.get("sensor.cgesp_alagamentos_ativos").state == "1"


async def test_localiza_ponto_novo_no_openstreetmap(hass: HomeAssistant, site_cge) -> None:
    """Sem cache: consulta o Nominatim em segundo plano e salva o resultado."""
    site_cge.paginas["https://nominatim.openstreetmap.org/search"] = (
        b'[{"lat": "-23.4935", "lon": "-46.4140", "category": "highway",'
        b' "type": "primary", "address": {"road": "Avenida Marechal Tito",'
        b' "house_number": "7557", "city": "S\u00e3o Paulo"}}]'
    )
    await _configurar(hass, **{CONF_GEOCODIFICAR: True})
    await hass.async_block_till_done(wait_background_tasks=True)

    assert any("nominatim" in url for url in site_cge.consultas)
    ponto = hass.states.get("geo_location.cgesp_avenida_marechal_tito")
    assert ponto is not None
    assert ponto.state != STATE_UNAVAILABLE
    assert ponto.attributes["latitude"] == MARECHAL_TITO[0]
