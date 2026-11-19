"""Alertas da cidade num Home Assistant de verdade, com o site do CGE simulado
pelas fixtures (tests/fixtures).

Na fixture alagamentos.html (15/11/2026) há 6 pontos no dia e só 1 ativo:
Avenida Marechal Tito, Zona Leste, intransitável. No mapa_alertas.png todas
as áreas estão em observação.
"""
from datetime import timedelta

import pytest
from homeassistant.components.camera import async_get_image
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)

from custom_components.cgesp.cge_extras import URL_RADAR
from custom_components.cgesp.const import (
    CONF_INTERVALO_ADAPTATIVO,
    CONF_TIPO,
    DATA_ALERTAS_COORDINATOR,
    DOMAIN,
    EVENTO_ALAGAMENTO_ENCERRADO,
    EVENTO_ALAGAMENTO_NOVO,
    TIPO_ALERTAS_CIDADE,
    UNIQUE_ID_ALERTAS_CIDADE,
)

from .conftest import URL_ALAGAMENTOS, URL_MAPA_PNG, URL_PREVISAO

ZONAS_ENTIDADES = ["zona_norte", "zona_sul", "zona_leste", "zona_oeste", "centro"]


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


def _coordinator(hass: HomeAssistant):
    return hass.data[DOMAIN][DATA_ALERTAS_COORDINATOR]


async def _atualizar(hass: HomeAssistant) -> None:
    await _coordinator(hass).async_refresh()
    await hass.async_block_till_done()


# ------------------------------------------------------------------ entidades


async def test_cria_as_entidades(hass: HomeAssistant, site_cge) -> None:
    entrada = await _configurar(hass)
    assert entrada.state is ConfigEntryState.LOADED

    esperadas = [
        *(f"binary_sensor.cgesp_alagamento_{z}" for z in ZONAS_ENTIDADES),
        "sensor.cgesp_alagamentos_ativos",
        *(f"sensor.cgesp_alagamentos_ativos_{z}" for z in ZONAS_ENTIDADES),
        "sensor.cgesp_alagamentos_hoje",
        "sensor.cgesp_boletim",
        "camera.cgesp_radar",
        "camera.cgesp_mapa_alertas",
    ]
    for entity_id in esperadas:
        estado = hass.states.get(entity_id)
        assert estado is not None, entity_id
        assert estado.state != STATE_UNAVAILABLE, entity_id

    # Sem a opção do mapa, nenhum ponto vira geo_location.
    assert hass.states.async_entity_ids("geo_location") == []


async def test_alagamento_por_zona(hass: HomeAssistant, site_cge) -> None:
    await _configurar(hass)

    leste = hass.states.get("binary_sensor.cgesp_alagamento_zona_leste")
    assert leste.state == STATE_ON
    assert leste.attributes["pontos_ativos"] == 1
    assert leste.attributes["pontos_intransitaveis"] == 1
    assert leste.attributes["ruas"] == ["Avenida Marechal Tito"]
    assert leste.attributes["data_referencia"] == "15/11/2026"

    norte = hass.states.get("binary_sensor.cgesp_alagamento_zona_norte")
    assert norte.state == STATE_OFF
    assert norte.attributes["pontos_encerrados_hoje"] == 2


async def test_contadores(hass: HomeAssistant, site_cge) -> None:
    await _configurar(hass)

    cidade = hass.states.get("sensor.cgesp_alagamentos_ativos")
    assert cidade.state == "1"
    assert cidade.attributes["unit_of_measurement"] == "pontos"
    assert cidade.attributes["state_class"] == "measurement"
    assert cidade.attributes["por_zona"] == {
        "Zona Norte": 0,
        "Zona Sul": 0,
        "Zona Leste": 1,
        "Zona Oeste": 0,
        "Centro": 0,
    }
    assert hass.states.get("sensor.cgesp_alagamentos_ativos_zona_leste").state == "1"
    assert hass.states.get("sensor.cgesp_alagamentos_ativos_zona_sul").state == "0"

    hoje = hass.states.get("sensor.cgesp_alagamentos_hoje")
    assert hoje.state == "6"
    assert hoje.attributes["ativos"] == 1
    assert hoje.attributes["encerrados"] == 5


async def test_boletim(hass: HomeAssistant, site_cge) -> None:
    await _configurar(hass)

    boletim = hass.states.get("sensor.cgesp_boletim")
    assert boletim.state.startswith("Início de madrugada com céu encoberto")
    assert boletim.attributes["link"] == "https://www.cgesp.org/v3/noticias.jsp?id=56475"
    assert boletim.attributes["texto"]
    # Publicado às 23:58 no horário de São Paulo (o RSS diz "GMT", mas não é).
    assert boletim.attributes["publicado_em"].isoformat() == "2026-11-18T23:58:21-03:00"


async def test_camera_mapa_de_alertas(hass: HomeAssistant, site_cge) -> None:
    await _configurar(hass)

    imagem = await async_get_image(hass, "camera.cgesp_mapa_alertas")

    assert imagem.content_type == "image/png"
    assert imagem.content == site_cge.fixture("mapa_alertas.png")


async def test_camera_radar_com_cache(hass: HomeAssistant, site_cge, aioclient_mock) -> None:
    aioclient_mock.get(URL_RADAR, content=b"jpeg-do-radar")
    await _configurar(hass)

    primeira = await async_get_image(hass, "camera.cgesp_radar")
    segunda = await async_get_image(hass, "camera.cgesp_radar")

    assert primeira.content == segunda.content == b"jpeg-do-radar"
    assert primeira.content_type == "image/jpeg"
    # A segunda veio do cache: o servidor do radar só foi consultado uma vez.
    assert aioclient_mock.call_count == 1


async def test_camera_radar_mantem_ultima_imagem(
    hass: HomeAssistant, site_cge, aioclient_mock, freezer
) -> None:
    aioclient_mock.get(URL_RADAR, content=b"jpeg-antigo")
    await _configurar(hass)
    assert (await async_get_image(hass, "camera.cgesp_radar")).content == b"jpeg-antigo"

    aioclient_mock.clear_requests()
    aioclient_mock.get(URL_RADAR, status=500)
    camera = hass.data["camera"].get_entity("camera.cgesp_radar")
    camera._baixada_em -= 10 * 60  # cache vencido

    imagem = await camera.async_camera_image()

    assert aioclient_mock.call_count == 1
    assert imagem == b"jpeg-antigo"


# ------------------------------------------------------------------ site fora do ar


async def test_site_fora_do_ar_e_volta(hass: HomeAssistant, site_cge) -> None:
    paginas = dict(site_cge.paginas)
    site_cge.fora_do_ar()
    entrada = await _configurar(hass)

    # A entrada carrega mesmo assim; as entidades ficam indisponíveis.
    assert entrada.state is ConfigEntryState.LOADED
    assert hass.states.get("sensor.cgesp_alagamentos_ativos").state == STATE_UNAVAILABLE
    assert (
        hass.states.get("binary_sensor.cgesp_alagamento_zona_leste").state
        == STATE_UNAVAILABLE
    )

    site_cge.paginas.update(paginas)
    await _atualizar(hass)

    assert hass.states.get("sensor.cgesp_alagamentos_ativos").state == "1"


async def test_so_o_mapa_fora_do_ar(hass: HomeAssistant, site_cge) -> None:
    site_cge.paginas[URL_MAPA_PNG] = None
    await _configurar(hass)

    # Alagamentos seguem funcionando; só o mapa fica indisponível.
    assert hass.states.get("sensor.cgesp_alagamentos_ativos").state == "1"
    assert hass.states.get("camera.cgesp_mapa_alertas").state == STATE_UNAVAILABLE


async def test_atualiza_sozinho_pelo_intervalo(hass: HomeAssistant, site_cge, freezer) -> None:
    await _configurar(hass)
    site_cge.paginas[URL_ALAGAMENTOS] = site_cge.fixture("alagamentos_vazio.html")

    freezer.tick(timedelta(minutes=11))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert hass.states.get("sensor.cgesp_alagamentos_ativos").state == "0"


# ------------------------------------------------------------------ reparos


async def test_reparo_quando_o_layout_muda(hass: HomeAssistant, site_cge) -> None:
    original = site_cge.paginas[URL_ALAGAMENTOS]
    site_cge.paginas[URL_ALAGAMENTOS] = original.replace(b"tit-bairros", b"titulo-zona")
    await _configurar(hass)
    registro = ir.async_get(hass)

    aviso = registro.async_get_issue(DOMAIN, "layout_alagamentos")
    assert aviso is not None
    assert aviso.translation_key == "layout_alterado"
    assert aviso.translation_placeholders["parte"] == "alagamentos"
    assert hass.states.get("sensor.cgesp_alagamentos_ativos").state == STATE_UNAVAILABLE
    # O mapa continua lido normalmente.
    assert registro.async_get_issue(DOMAIN, "layout_mapa_alertas") is None

    site_cge.paginas[URL_ALAGAMENTOS] = original
    await _atualizar(hass)

    assert registro.async_get_issue(DOMAIN, "layout_alagamentos") is None
    assert hass.states.get("sensor.cgesp_alagamentos_ativos").state == "1"


async def test_conexao_caida_nao_abre_reparo(hass: HomeAssistant, site_cge) -> None:
    site_cge.paginas[URL_ALAGAMENTOS] = None
    await _configurar(hass)

    assert ir.async_get(hass).async_get_issue(DOMAIN, "layout_alagamentos") is None


# ------------------------------------------------------------------ eventos


async def test_eventos_de_alagamento(hass: HomeAssistant, site_cge) -> None:
    novos = async_capture_events(hass, EVENTO_ALAGAMENTO_NOVO)
    encerrados = async_capture_events(hass, EVENTO_ALAGAMENTO_ENCERRADO)
    await _configurar(hass)

    # A primeira leitura é só a base: nada de evento para o que já estava ativo.
    assert novos == [] and encerrados == []

    site_cge.paginas[URL_ALAGAMENTOS] = site_cge.fixture("alagamentos_vazio.html")
    await _atualizar(hass)
    assert len(encerrados) == 1
    assert encerrados[0].data["local"] == "Avenida Marechal Tito"
    assert encerrados[0].data["zona"] == "Zona Leste"
    assert encerrados[0].data["zona_id"] == "leste"

    # Site fora do ar não abre nem encerra alagamento.
    site_cge.paginas[URL_ALAGAMENTOS] = None
    await _atualizar(hass)
    assert len(novos) == 0 and len(encerrados) == 1

    site_cge.paginas[URL_ALAGAMENTOS] = site_cge.fixture("alagamentos.html")
    await _atualizar(hass)
    assert len(novos) == 1
    assert novos[0].data["local"] == "Avenida Marechal Tito"
    assert novos[0].data["transitavel"] is False


# ------------------------------------------------------------------ intervalo


@pytest.mark.parametrize(
    ("horario_utc", "esperado"),
    [
        # 19h em São Paulo: noite e madrugada nubladas, manhã com poucas nuvens.
        ("2026-11-19T22:00:00+00:00", timedelta(minutes=30)),
        # 8h em São Paulo: pancadas previstas para a tarde.
        ("2026-11-19T11:00:00+00:00", timedelta(minutes=10)),
    ],
)
async def test_intervalo_segue_a_previsao(
    hass: HomeAssistant, site_cge, freezer, horario_utc, esperado
) -> None:
    freezer.move_to(horario_utc)
    site_cge.paginas[URL_ALAGAMENTOS] = site_cge.fixture("alagamentos_vazio.html")
    site_cge.paginas[URL_PREVISAO] = site_cge.fixture("previsao_pancadas.html")
    await _configurar(hass)

    assert _coordinator(hass).update_interval == esperado


async def test_intervalo_curto_com_alagamento_ativo(hass: HomeAssistant, site_cge, freezer) -> None:
    freezer.move_to("2026-11-19T22:00:00+00:00")
    site_cge.paginas[URL_PREVISAO] = site_cge.fixture("previsao_pancadas.html")
    await _configurar(hass)

    coordinator = _coordinator(hass)
    assert coordinator.update_interval == timedelta(minutes=10)
    assert coordinator.motivo_intervalo == "há alagamentos ativos"


async def test_intervalo_fixo_com_a_opcao_desligada(hass: HomeAssistant, site_cge, freezer) -> None:
    freezer.move_to("2026-11-19T22:00:00+00:00")
    site_cge.paginas[URL_ALAGAMENTOS] = site_cge.fixture("alagamentos_vazio.html")
    site_cge.paginas[URL_PREVISAO] = site_cge.fixture("previsao_pancadas.html")
    await _configurar(hass, **{CONF_INTERVALO_ADAPTATIVO: False})

    assert _coordinator(hass).update_interval == timedelta(minutes=10)


async def test_previsao_lida_no_maximo_uma_vez_por_hora(hass: HomeAssistant, site_cge) -> None:
    await _configurar(hass)
    await _atualizar(hass)
    await _atualizar(hass)

    assert site_cge.consultas.count(URL_PREVISAO) == 1


# ------------------------------------------------------------------ remover


async def test_remover_descarrega_tudo(hass: HomeAssistant, site_cge) -> None:
    entrada = await _configurar(hass)
    site_cge.paginas[URL_ALAGAMENTOS] = site_cge.paginas[URL_ALAGAMENTOS].replace(
        b"tit-bairros", b"titulo-zona"
    )
    await _atualizar(hass)
    assert ir.async_get(hass).async_get_issue(DOMAIN, "layout_alagamentos") is not None

    assert await hass.config_entries.async_unload(entrada.entry_id)
    await hass.async_block_till_done()

    assert entrada.state is ConfigEntryState.NOT_LOADED
    assert DATA_ALERTAS_COORDINATOR not in hass.data[DOMAIN]
    # Ninguém mais lê o site: o aviso de layout sai de Reparos.
    assert ir.async_get(hass).async_get_issue(DOMAIN, "layout_alagamentos") is None
    assert hass.states.get("sensor.cgesp_alagamentos_ativos").state == STATE_UNAVAILABLE


# ------------------------------------------------------------------ diagnóstico


async def test_diagnostico(hass: HomeAssistant, site_cge, hass_client) -> None:
    entrada = await _configurar(hass)

    diagnostico = await get_diagnostics_for_config_entry(hass, hass_client, entrada)

    alertas = diagnostico["alertas"]
    assert alertas["ultima_atualizacao_ok"] is True
    assert alertas["layout_quebrado"] == {}
    assert alertas["dados"]["data_referencia"] == "15/11/2026"
    assert len(alertas["dados"]["alagamentos"]["leste"]) == 1
    assert alertas["dados"]["boletim"]["link"].endswith("id=56475")
    assert alertas["dados"]["mapa_png_bytes"] > 0
