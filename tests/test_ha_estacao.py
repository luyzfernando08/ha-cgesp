"""Estação meteorológica num Home Assistant de verdade.

Pinheiros fica na área "Pinheiros" do mapa de alertas (Zona Oeste). No
mapa_alertas.png ela está em observação; no mapa_alertas_atencao_2020.png,
em atenção.
"""
import pytest
from homeassistant.components.weather import DOMAIN as WEATHER_DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cgesp.const import (
    CONF_ESTACAO_ID,
    CONF_TIPO,
    DATA_ALERTAS_COORDINATOR,
    DOMAIN,
    TIPO_ALERTAS_CIDADE,
    TIPO_ESTACAO,
    UNIQUE_ID_ALERTAS_CIDADE,
)

from .conftest import URL_MAPA_PNG

PINHEIROS = 1000635
MAUA = 1000876  # fora da capital: sem área no mapa de alertas
# No HA atual o nome do dispositivo ("CGE - SP") entra no entity_id.
CLIMA = "weather.cge_sp_pinheiros"


async def _estacao(hass: HomeAssistant, estacao_id: int = PINHEIROS) -> MockConfigEntry:
    entrada = MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"cge_{estacao_id}",
        data={CONF_TIPO: TIPO_ESTACAO, CONF_ESTACAO_ID: estacao_id},
    )
    entrada.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entrada.entry_id)
    await hass.async_block_till_done()
    return entrada


async def test_clima_da_estacao(hass: HomeAssistant, site_cge) -> None:
    await _estacao(hass)

    clima = hass.states.get(CLIMA)
    assert clima is not None
    assert clima.state == "rainy"
    assert clima.attributes["temperature"] == 23.3
    assert clima.attributes["humidity"] == 60  # o HA arredonda (59,6 no site)
    assert clima.attributes["pressure"] == 913.6
    assert clima.attributes["wind_speed"] == 20.3


async def test_previsao_diaria(hass: HomeAssistant, site_cge) -> None:
    await _estacao(hass)

    resposta = await hass.services.async_call(
        WEATHER_DOMAIN,
        "get_forecasts",
        {"entity_id": CLIMA, "type": "daily"},
        blocking=True,
        return_response=True,
    )

    previsao = resposta[CLIMA]["forecast"]
    assert len(previsao) >= 2
    assert previsao[0]["temperature"] == 24.0
    assert previsao[0]["templow"] == 18.0
    assert previsao[0]["condition"] == "rainy"


async def test_estado_de_alerta_da_estacao(hass: HomeAssistant, site_cge) -> None:
    await _estacao(hass)

    sensor = hass.states.get("sensor.cgesp_pinheiros_estado_alerta")
    assert sensor.state == "observacao"
    assert sensor.attributes["area_monitorada"] == "Pinheiros"
    assert sensor.attributes["zona"] == "Zona Oeste"
    assert hass.states.get("binary_sensor.cgesp_pinheiros_atencao").state == STATE_OFF


async def test_estacao_em_atencao(hass: HomeAssistant, site_cge) -> None:
    site_cge.paginas[URL_MAPA_PNG] = site_cge.fixture("mapa_alertas_atencao_2020.png")
    await _estacao(hass)

    assert hass.states.get("sensor.cgesp_pinheiros_estado_alerta").state == "atencao"
    assert hass.states.get("binary_sensor.cgesp_pinheiros_atencao").state == STATE_ON


async def test_estacao_fora_da_capital(hass: HomeAssistant, site_cge) -> None:
    await _estacao(hass, MAUA)

    # Só o clima; sem área no mapa, não há sensores de alerta.
    assert hass.states.async_entity_ids("weather") == ["weather.cge_sp_maua_paco_municipal"]
    assert hass.states.async_entity_ids("sensor") == []
    assert hass.states.async_entity_ids("binary_sensor") == []


async def test_estacao_nao_baixa_o_boletim(hass: HomeAssistant, site_cge) -> None:
    await _estacao(hass)

    assert not any("feed_rss" in url for url in site_cge.consultas)


@pytest.mark.parametrize("remover_primeiro", ["estacao", "alertas"])
async def test_coordinator_compartilhado(
    hass: HomeAssistant, site_cge, remover_primeiro
) -> None:
    """Estação e alertas da cidade usam a mesma leitura do site; remover uma
    entrada não pode desligar a outra."""
    estacao = await _estacao(hass)
    alertas = MockConfigEntry(
        domain=DOMAIN,
        unique_id=UNIQUE_ID_ALERTAS_CIDADE,
        data={CONF_TIPO: TIPO_ALERTAS_CIDADE},
    )
    alertas.add_to_hass(hass)
    assert await hass.config_entries.async_setup(alertas.entry_id)
    await hass.async_block_till_done()

    coordinator = hass.data[DOMAIN][DATA_ALERTAS_COORDINATOR]
    # A estação veio antes; a entrada de alertas passou a buscar o boletim.
    assert coordinator.buscar_boletim is True
    assert hass.states.get("sensor.cgesp_boletim").state != STATE_UNAVAILABLE

    sai, fica = (estacao, alertas) if remover_primeiro == "estacao" else (alertas, estacao)
    assert await hass.config_entries.async_unload(sai.entry_id)
    await hass.async_block_till_done()

    assert fica.state is ConfigEntryState.LOADED
    assert hass.data[DOMAIN][DATA_ALERTAS_COORDINATOR] is coordinator
    if fica is estacao:
        assert coordinator.buscar_boletim is False
        entidade = "sensor.cgesp_pinheiros_estado_alerta"
    else:
        entidade = "sensor.cgesp_alagamentos_ativos"

    # O coordinator continua atualizando para quem ficou.
    site_cge.paginas[URL_MAPA_PNG] = site_cge.fixture("mapa_alertas_atencao_2020.png")
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert coordinator.last_update_success
    assert hass.states.get(entidade).state not in (STATE_UNAVAILABLE, None)
    if fica is estacao:
        assert hass.states.get(entidade).state == "atencao"


async def test_mudar_opcoes_dos_alertas_nao_para_a_estacao(
    hass: HomeAssistant, site_cge
) -> None:
    """Os alertas criam o coordinator; mudar as opções recarrega essa entrada,
    e a estação precisa continuar recebendo atualizações."""
    alertas = MockConfigEntry(
        domain=DOMAIN,
        unique_id=UNIQUE_ID_ALERTAS_CIDADE,
        data={CONF_TIPO: TIPO_ALERTAS_CIDADE},
    )
    alertas.add_to_hass(hass)
    assert await hass.config_entries.async_setup(alertas.entry_id)
    await hass.async_block_till_done()
    await _estacao(hass)
    coordinator = hass.data[DOMAIN][DATA_ALERTAS_COORDINATOR]

    hass.config_entries.async_update_entry(alertas, options={"raio_km": 3.0})
    await hass.async_block_till_done()

    assert alertas.state is ConfigEntryState.LOADED
    assert hass.data[DOMAIN][DATA_ALERTAS_COORDINATOR] is coordinator
    site_cge.paginas[URL_MAPA_PNG] = site_cge.fixture("mapa_alertas_atencao_2020.png")
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("sensor.cgesp_pinheiros_estado_alerta").state == "atencao"
    # Ainda agendado: o coordinator não foi desligado junto com a entrada.
    assert coordinator._unsub_refresh is not None
