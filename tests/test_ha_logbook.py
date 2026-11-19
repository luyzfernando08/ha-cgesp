"""Descrição dos eventos de alagamento no Diário de bordo."""
from homeassistant.core import Event, HomeAssistant
from homeassistant.loader import async_get_integration
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cgesp.const import (
    CONF_TIPO,
    DOMAIN,
    EVENTO_ALAGAMENTO_ENCERRADO,
    EVENTO_ALAGAMENTO_NOVO,
    TIPO_ALERTAS_CIDADE,
    UNIQUE_ID_ALERTAS_CIDADE,
)

DADOS = {
    "zona": "Zona Leste",
    "zona_id": "leste",
    "bairro": "Itaim Paulista",
    "local": "Avenida Marechal Tito",
    "referencia": "altura do número 7557",
    "inicio": "17:48",
    "sentido": None,
    "transitavel": False,
    "fim": None,
}


async def _descritores(hass: HomeAssistant) -> dict:
    """Carrega o logbook.py como o HA faz e devolve {(domínio, evento): função}."""
    integracao = await async_get_integration(hass, DOMAIN)
    plataforma = await integracao.async_get_platform("logbook")
    descritores = {}
    plataforma.async_describe_events(
        hass, lambda dominio, evento, funcao: descritores.update({(dominio, evento): funcao})
    )
    return descritores


async def test_registra_os_dois_eventos(hass: HomeAssistant) -> None:
    descritores = await _descritores(hass)

    assert set(descritores) == {
        (DOMAIN, EVENTO_ALAGAMENTO_NOVO),
        (DOMAIN, EVENTO_ALAGAMENTO_ENCERRADO),
    }


async def test_alagamento_novo(hass: HomeAssistant) -> None:
    descrever = (await _descritores(hass))[(DOMAIN, EVENTO_ALAGAMENTO_NOVO)]

    descricao = descrever(Event(EVENTO_ALAGAMENTO_NOVO, DADOS))

    assert descricao["name"] == "CGE - SP"
    assert descricao["message"] == (
        "novo alagamento: Avenida Marechal Tito, altura do número 7557 "
        "(Itaim Paulista, Zona Leste), intransitável"
    )
    # Sem a entrada de alertas, o sensor da zona não existe: não liga a nada.
    assert "entity_id" not in descricao


async def test_alagamento_encerrado_sem_referencia(hass: HomeAssistant) -> None:
    descrever = (await _descritores(hass))[(DOMAIN, EVENTO_ALAGAMENTO_ENCERRADO)]
    dados = {**DADOS, "referencia": None, "bairro": "", "fim": "19:10"}

    descricao = descrever(Event(EVENTO_ALAGAMENTO_ENCERRADO, dados))

    assert descricao["message"] == "alagamento encerrado: Avenida Marechal Tito (Zona Leste)"


async def test_liga_ao_sensor_da_zona(hass: HomeAssistant, site_cge) -> None:
    entrada = MockConfigEntry(
        domain=DOMAIN,
        unique_id=UNIQUE_ID_ALERTAS_CIDADE,
        data={CONF_TIPO: TIPO_ALERTAS_CIDADE},
    )
    entrada.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entrada.entry_id)
    await hass.async_block_till_done()
    descrever = (await _descritores(hass))[(DOMAIN, EVENTO_ALAGAMENTO_NOVO)]

    descricao = descrever(Event(EVENTO_ALAGAMENTO_NOVO, DADOS))

    # O entity_id vem do registro, então segue valendo se o usuário renomear.
    assert descricao["entity_id"] == "binary_sensor.cgesp_alagamento_zona_leste"


async def test_logbook_do_ha_encontra_a_plataforma(
    recorder_mock, hass: HomeAssistant, site_cge
) -> None:
    """Com o Diário de bordo de verdade (precisa do recorder), os eventos da
    integração ficam registrados com a nossa descrição."""
    from homeassistant.setup import async_setup_component

    entrada = MockConfigEntry(
        domain=DOMAIN,
        unique_id=UNIQUE_ID_ALERTAS_CIDADE,
        data={CONF_TIPO: TIPO_ALERTAS_CIDADE},
    )
    entrada.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entrada.entry_id)
    # O logbook depende do frontend (pacote grande, irrelevante aqui).
    hass.config.components.add("frontend")
    assert await async_setup_component(hass, "logbook", {})
    await hass.async_block_till_done()

    externos = hass.data["logbook"].external_events
    for evento in (EVENTO_ALAGAMENTO_NOVO, EVENTO_ALAGAMENTO_ENCERRADO):
        dominio, descrever = externos[evento]
        assert dominio == DOMAIN
    assert descrever(Event(EVENTO_ALAGAMENTO_ENCERRADO, DADOS))["message"].startswith(
        "alagamento encerrado: Avenida Marechal Tito"
    )
