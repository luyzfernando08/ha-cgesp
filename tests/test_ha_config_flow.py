"""Fluxo de configuração e opções, num Home Assistant de verdade."""
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cgesp.const import (
    CONF_ENTIDADES_PROXIMIDADE,
    CONF_ESTACAO_ID,
    CONF_GEOCODIFICAR,
    CONF_INTERVALO_ADAPTATIVO,
    CONF_RAIO_KM,
    CONF_TIPO,
    DOMAIN,
    ENTRADA_ESTACAO_METEOROLOGICA,
    TIPO_ALERTAS_CIDADE,
    TIPO_ESTACAO,
    UNIQUE_ID_ALERTAS_CIDADE,
)

PINHEIROS = 1000635


async def _iniciar(hass: HomeAssistant, passo: str):
    resultado = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert resultado["type"] is FlowResultType.MENU
    assert resultado["menu_options"] == [TIPO_ESTACAO, TIPO_ALERTAS_CIDADE]
    return await hass.config_entries.flow.async_configure(
        resultado["flow_id"], {"next_step_id": passo}
    )


async def test_adiciona_estacao(hass: HomeAssistant, site_cge) -> None:
    resultado = await _iniciar(hass, TIPO_ESTACAO)
    assert resultado["type"] is FlowResultType.FORM

    resultado = await hass.config_entries.flow.async_configure(
        resultado["flow_id"], {ENTRADA_ESTACAO_METEOROLOGICA: PINHEIROS}
    )
    await hass.async_block_till_done()

    assert resultado["type"] is FlowResultType.CREATE_ENTRY
    assert resultado["title"] == "Pinheiros"
    assert resultado["data"] == {CONF_TIPO: TIPO_ESTACAO, CONF_ESTACAO_ID: PINHEIROS}
    assert resultado["result"].unique_id == f"cge_{PINHEIROS}"


async def test_estacao_com_site_fora_do_ar(hass: HomeAssistant, site_cge) -> None:
    site_cge.fora_do_ar()
    resultado = await _iniciar(hass, TIPO_ESTACAO)
    resultado = await hass.config_entries.flow.async_configure(
        resultado["flow_id"], {ENTRADA_ESTACAO_METEOROLOGICA: PINHEIROS}
    )

    assert resultado["type"] is FlowResultType.FORM
    assert resultado["errors"] == {"base": "cannot_connect"}


async def test_estacao_repetida(hass: HomeAssistant, site_cge) -> None:
    MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"cge_{PINHEIROS}",
        data={CONF_TIPO: TIPO_ESTACAO, CONF_ESTACAO_ID: PINHEIROS},
    ).add_to_hass(hass)

    resultado = await _iniciar(hass, TIPO_ESTACAO)
    resultado = await hass.config_entries.flow.async_configure(
        resultado["flow_id"], {ENTRADA_ESTACAO_METEOROLOGICA: PINHEIROS}
    )

    assert resultado["type"] is FlowResultType.ABORT
    assert resultado["reason"] == "already_configured"


async def test_adiciona_alertas_da_cidade(hass: HomeAssistant, site_cge) -> None:
    resultado = await _iniciar(hass, TIPO_ALERTAS_CIDADE)
    assert resultado["type"] is FlowResultType.FORM

    resultado = await hass.config_entries.flow.async_configure(
        resultado["flow_id"],
        {CONF_GEOCODIFICAR: False, CONF_INTERVALO_ADAPTATIVO: False},
    )
    await hass.async_block_till_done()

    assert resultado["type"] is FlowResultType.CREATE_ENTRY
    assert resultado["data"] == {CONF_TIPO: TIPO_ALERTAS_CIDADE}
    assert resultado["options"] == {
        CONF_GEOCODIFICAR: False,
        CONF_INTERVALO_ADAPTATIVO: False,
    }
    assert resultado["result"].unique_id == UNIQUE_ID_ALERTAS_CIDADE


async def test_alertas_com_site_fora_do_ar(hass: HomeAssistant, site_cge) -> None:
    site_cge.fora_do_ar()
    resultado = await _iniciar(hass, TIPO_ALERTAS_CIDADE)
    resultado = await hass.config_entries.flow.async_configure(
        resultado["flow_id"], {}
    )

    assert resultado["type"] is FlowResultType.FORM
    assert resultado["errors"] == {"base": "cannot_connect"}


async def test_alertas_so_uma_vez(hass: HomeAssistant, site_cge) -> None:
    MockConfigEntry(
        domain=DOMAIN,
        unique_id=UNIQUE_ID_ALERTAS_CIDADE,
        data={CONF_TIPO: TIPO_ALERTAS_CIDADE},
    ).add_to_hass(hass)

    resultado = await _iniciar(hass, TIPO_ALERTAS_CIDADE)

    assert resultado["type"] is FlowResultType.ABORT
    assert resultado["reason"] == "already_configured"


async def _entrada_alertas(hass: HomeAssistant, **opcoes) -> MockConfigEntry:
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


async def test_opcoes_salvam(hass: HomeAssistant, site_cge) -> None:
    entrada = await _entrada_alertas(hass)

    resultado = await hass.config_entries.options.async_init(entrada.entry_id)
    assert resultado["type"] is FlowResultType.FORM
    resultado = await hass.config_entries.options.async_configure(
        resultado["flow_id"],
        {
            CONF_GEOCODIFICAR: True,
            CONF_ENTIDADES_PROXIMIDADE: ["person.joao"],
            CONF_RAIO_KM: 3.5,
            CONF_INTERVALO_ADAPTATIVO: True,
        },
    )
    await hass.async_block_till_done()

    assert resultado["type"] is FlowResultType.CREATE_ENTRY
    assert entrada.options[CONF_ENTIDADES_PROXIMIDADE] == ["person.joao"]
    assert entrada.options[CONF_RAIO_KM] == 3.5


async def test_opcoes_pessoas_sem_o_mapa(hass: HomeAssistant, site_cge) -> None:
    """Sem os pontos no mapa, a pessoa ganha só os sensores de chuva do radar
    (os alagamentos por perto precisam das coordenadas dos pontos)."""
    hass.states.async_set("person.joao", "home", {"latitude": -23.56, "longitude": -46.65})
    entrada = await _entrada_alertas(hass)

    resultado = await hass.config_entries.options.async_init(entrada.entry_id)
    resultado = await hass.config_entries.options.async_configure(
        resultado["flow_id"],
        {CONF_GEOCODIFICAR: False, CONF_ENTIDADES_PROXIMIDADE: ["person.joao"]},
    )
    await hass.async_block_till_done()

    assert resultado["type"] is FlowResultType.CREATE_ENTRY
    assert entrada.options[CONF_ENTIDADES_PROXIMIDADE] == ["person.joao"]
    assert hass.states.get("sensor.cgesp_chuva_joao") is not None
    assert hass.states.get("sensor.cgesp_alagamentos_perto_joao") is None


async def test_estacao_nao_tem_opcoes(hass: HomeAssistant, site_cge) -> None:
    entrada = MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"cge_{PINHEIROS}",
        data={CONF_TIPO: TIPO_ESTACAO, CONF_ESTACAO_ID: PINHEIROS},
    )
    entrada.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entrada.entry_id)
    await hass.async_block_till_done()

    assert entrada.supports_options is False
