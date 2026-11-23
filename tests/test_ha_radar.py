"""Radar de chuva num Home Assistant de verdade: chuva no local de pessoas e
zonas, chuva mais próxima, câmeras e intervalo.

O site simulado começa com radar_sem_chuva.jpg (ver test_cge_radar.py).
"""
import io
from datetime import UTC, datetime, timedelta

import pytest
from homeassistant.components.camera import async_get_image
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from PIL import Image
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)

from custom_components.cgesp.const import (
    CONF_ENTIDADES_PROXIMIDADE,
    CONF_INTERVALO_ADAPTATIVO,
    CONF_TIPO,
    DATA_RADAR_COORDINATOR,
    DOMAIN,
    TIPO_ALERTAS_CIDADE,
    UNIQUE_ID_ALERTAS_CIDADE,
)

from .conftest import URL_ALAGAMENTOS, URL_PREVISAO, URL_RADAR

PAULISTA = (-23.5614, -46.6559)  # chuva moderada em radar_chuva.jpg
CONSOLACAO = (-23.5500, -46.6300)  # ~2 km a nordeste dela
CAMPINAS = (-22.9056, -47.0608)  # fora da imagem

CHUVA_CASA = "sensor.cgesp_chuva_zone_home"
CHOVENDO_CASA = "binary_sensor.cgesp_chovendo_zone_home"
PROXIMA_CASA = "sensor.cgesp_chuva_mais_proxima_zone_home"


@pytest.fixture(autouse=True)
def _radar_de_agora(site_cge) -> None:
    """A imagem inicial do radar é de 19/11 às 18:00 UTC (as seguintes vêm
    minutos depois e ficam na mesma hora da animação)."""
    site_cge.modificado[URL_RADAR] = "Thu, 19 Nov 2026 18:00:00 GMT"


def _casa(hass: HomeAssistant, posicao: tuple[float, float]) -> None:
    hass.states.async_set(
        "zone.home", "0", {"friendly_name": "Casa", "latitude": posicao[0], "longitude": posicao[1]}
    )


async def _configurar(hass: HomeAssistant, **opcoes) -> MockConfigEntry:
    opcoes.setdefault(CONF_ENTIDADES_PROXIMIDADE, ["zone.home"])
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


def _radar(hass: HomeAssistant):
    return hass.data[DOMAIN][DATA_RADAR_COORDINATOR]


async def _nova_imagem(hass: HomeAssistant, site_cge, nome: str | None, minuto: int) -> None:
    """O servidor publica uma imagem nova (outro Last-Modified) e o radar lê."""
    conteudo = site_cge.fixture(nome) if nome else site_cge.paginas[URL_RADAR]
    site_cge.trocar(URL_RADAR, conteudo, f"Thu, 19 Nov 2026 18:{minuto:02d}:00 GMT")
    await _radar(hass).async_refresh()
    await hass.async_block_till_done()


async def _nova_imagem_bruta(hass: HomeAssistant, site_cge, conteudo, minuto: int) -> None:
    """Como _nova_imagem, mas com qualquer resposta (bytes ou código de erro)."""
    site_cge.trocar(URL_RADAR, conteudo, f"Thu, 19 Nov 2026 18:{minuto:02d}:00 GMT")
    await _radar(hass).async_refresh()
    await hass.async_block_till_done()


# ------------------------------------------------------------------ chuva no local


async def test_sem_chuva(hass: HomeAssistant, site_cge) -> None:
    _casa(hass, PAULISTA)
    await _configurar(hass)

    chuva = hass.states.get(CHUVA_CASA)
    assert chuva.state == "sem_chuva"
    assert chuva.attributes["friendly_name"].endswith("Chuva em Casa")
    assert chuva.attributes["options"] == [
        "sem_chuva", "fraca", "moderada", "forte", "muito_forte"
    ]
    # Horário da imagem: o Last-Modified do servidor.
    assert chuva.attributes["radar_atualizado_em"] == datetime(2026, 11, 19, 18, 0, tzinfo=UTC)
    assert hass.states.get(CHOVENDO_CASA).state == STATE_OFF

    # Sem chuva em lugar nenhum: a distância fica desconhecida, com o motivo.
    proxima = hass.states.get(PROXIMA_CASA)
    assert proxima.state == STATE_UNKNOWN
    assert proxima.attributes["motivo"] == "sem chuva na imagem do radar"


async def test_chovendo_em_casa(hass: HomeAssistant, site_cge) -> None:
    _casa(hass, PAULISTA)
    site_cge.paginas[URL_RADAR] = site_cge.fixture("radar_chuva.jpg")
    await _configurar(hass)

    assert hass.states.get(CHUVA_CASA).state == "moderada"
    chovendo = hass.states.get(CHOVENDO_CASA)
    assert chovendo.state == STATE_ON
    assert chovendo.attributes["intensidade"] == "moderada"
    assert chovendo.attributes["device_class"] == "moisture"

    proxima = hass.states.get(PROXIMA_CASA)
    assert float(proxima.state) == 0
    assert proxima.attributes["unit_of_measurement"] == "km"
    assert proxima.attributes["intensidade"] == "moderada"
    assert proxima.attributes["direcao"] is None
    # A forte mais perto é a muito forte do Campo Limpo, a ~13 km.
    assert proxima.attributes["chuva_forte_km"] == pytest.approx(13, abs=1)


async def test_chuva_por_perto(hass: HomeAssistant, site_cge) -> None:
    _casa(hass, CONSOLACAO)
    site_cge.paginas[URL_RADAR] = site_cge.fixture("radar_chuva.jpg")
    await _configurar(hass)

    assert hass.states.get(CHUVA_CASA).state == "sem_chuva"
    assert hass.states.get(CHOVENDO_CASA).state == STATE_OFF
    proxima = hass.states.get(PROXIMA_CASA)
    assert float(proxima.state) == pytest.approx(2.0, abs=0.4)
    assert proxima.attributes["direcao"] == "sudoeste"
    assert proxima.attributes["intensidade"] == "moderada"


async def test_chuva_chega_e_vai_embora(hass: HomeAssistant, site_cge) -> None:
    _casa(hass, PAULISTA)
    await _configurar(hass)
    assert hass.states.get(CHOVENDO_CASA).state == STATE_OFF

    await _nova_imagem(hass, site_cge, "radar_chuva.jpg", 5)
    assert hass.states.get(CHOVENDO_CASA).state == STATE_ON

    await _nova_imagem(hass, site_cge, "radar_sem_chuva.jpg", 10)
    assert hass.states.get(CHOVENDO_CASA).state == STATE_OFF


async def test_pessoa_se_movendo(hass: HomeAssistant, site_cge) -> None:
    hass.states.async_set(
        "person.joao", "not_home",
        {"friendly_name": "João", "latitude": CONSOLACAO[0], "longitude": CONSOLACAO[1]},
    )
    site_cge.paginas[URL_RADAR] = site_cge.fixture("radar_chuva.jpg")
    await _configurar(hass, **{CONF_ENTIDADES_PROXIMIDADE: ["person.joao"]})
    assert hass.states.get("binary_sensor.cgesp_chovendo_joao").state == STATE_OFF

    hass.states.async_set(
        "person.joao", "not_home",
        {"friendly_name": "João", "latitude": PAULISTA[0], "longitude": PAULISTA[1]},
    )
    await hass.async_block_till_done()

    assert hass.states.get("binary_sensor.cgesp_chovendo_joao").state == STATE_ON
    assert hass.states.get("sensor.cgesp_chuva_joao").state == "moderada"
    assert float(hass.states.get("sensor.cgesp_chuva_mais_proxima_joao").state) == 0


async def test_sem_localizacao_ou_fora_da_imagem(hass: HomeAssistant, site_cge) -> None:
    hass.states.async_set("device_tracker.celular", "not_home", {})
    hass.states.async_set(
        "zone.campinas", "0", {"latitude": CAMPINAS[0], "longitude": CAMPINAS[1]}
    )
    await _configurar(
        hass, **{CONF_ENTIDADES_PROXIMIDADE: ["device_tracker.celular", "zone.campinas"]}
    )

    celular = hass.states.get("sensor.cgesp_chuva_device_tracker_celular")
    assert celular.state == STATE_UNKNOWN
    assert "não tem localização" in celular.attributes["motivo"]
    assert hass.states.get("binary_sensor.cgesp_chovendo_device_tracker_celular").state == STATE_UNKNOWN

    campinas = hass.states.get("sensor.cgesp_chuva_zone_campinas")
    assert campinas.state == STATE_UNKNOWN
    assert campinas.attributes["motivo"] == "fora da área coberta pela imagem do radar"


async def test_sem_mapa_nao_cria_alagamentos_perto(hass: HomeAssistant, site_cge) -> None:
    _casa(hass, PAULISTA)
    await _configurar(hass)

    assert hass.states.get(CHUVA_CASA) is not None
    assert hass.states.get("sensor.cgesp_alagamentos_perto_zone_home") is None


async def test_tirar_das_opcoes_apaga_os_sensores(hass: HomeAssistant, site_cge) -> None:
    _casa(hass, PAULISTA)
    entrada = await _configurar(hass)
    registro = er.async_get(hass)
    removidas = [CHUVA_CASA, CHOVENDO_CASA, PROXIMA_CASA]
    assert all(registro.async_get(e) for e in removidas)

    hass.config_entries.async_update_entry(entrada, options={CONF_ENTIDADES_PROXIMIDADE: []})
    await hass.async_block_till_done()

    for entity_id in removidas:
        assert registro.async_get(entity_id) is None, entity_id
        assert hass.states.get(entity_id) is None, entity_id


# ------------------------------------------------------------------ chuva chegando

GRAJAU = (-23.78, -46.67)  # chuva moderada chegando em ~22 min em radar_movimento
CHEGA_CASA = "sensor.cgesp_chuva_chega_em_zone_home"


async def _chuva_de_22_11(hass: HomeAssistant, site_cge, nome: str, publicada: str) -> None:
    """Imagens reais de 22/11: chuva forte no extremo sul indo para leste a
    ~32 km/h. Títulos de 17:20 e 17:30 (hora de Brasília)."""
    site_cge.trocar(URL_RADAR, site_cge.fixture(nome), publicada)
    await _radar(hass).async_refresh()
    await hass.async_block_till_done()


async def test_chuva_chegando(hass: HomeAssistant, site_cge, freezer) -> None:
    freezer.move_to("2026-11-22T20:32:00+00:00")
    _casa(hass, GRAJAU)
    site_cge.paginas[URL_RADAR] = site_cge.fixture("radar_movimento_1720.jpg")
    site_cge.modificado[URL_RADAR] = "Sun, 22 Nov 2026 20:31:47 GMT"
    await _configurar(hass)

    # Uma imagem só: ainda não dá para saber para onde a chuva vai.
    chega = hass.states.get(CHEGA_CASA)
    assert chega.state == STATE_UNKNOWN
    assert "ainda não medido" in chega.attributes["motivo"]

    # Dez minutos depois (pelo título; o servidor publicou só 6 depois).
    freezer.move_to("2026-11-22T20:38:00+00:00")
    await _chuva_de_22_11(hass, site_cge, "radar_movimento_1730.jpg", "Sun, 22 Nov 2026 20:37:19 GMT")

    # Pela imagem das 20:30 UTC, a chuva chega ~22 min depois dela; a
    # imagem já tem 8 minutos, então faltam ~14.
    chega = hass.states.get(CHEGA_CASA)
    assert float(chega.state) == pytest.approx(14, abs=3)
    assert chega.attributes["chega_as"] == pytest.approx(
        datetime(2026, 11, 22, 20, 52, tzinfo=UTC), abs=timedelta(minutes=3)
    )
    assert chega.attributes["unit_of_measurement"] == "min"
    assert chega.attributes["device_class"] == "duration"
    assert chega.attributes["intensidade_maxima"] == "moderada"
    assert chega.attributes["vindo_de"] == "oeste"
    assert chega.attributes["velocidade_kmh"] == pytest.approx(32, abs=4)
    assert "motivo" not in chega.attributes

    radar = hass.states.get("camera.cgesp_radar")
    assert radar.attributes["chuva_indo_para"] == "leste"
    assert radar.attributes["horario_do_radar"] == datetime(2026, 11, 22, 20, 30, tzinfo=UTC)


async def test_chuva_que_nao_vem(hass: HomeAssistant, site_cge, freezer) -> None:
    freezer.move_to("2026-11-22T20:38:00+00:00")
    _casa(hass, PAULISTA)
    site_cge.paginas[URL_RADAR] = site_cge.fixture("radar_movimento_1720.jpg")
    site_cge.modificado[URL_RADAR] = "Sun, 22 Nov 2026 20:31:47 GMT"
    await _configurar(hass)
    await _chuva_de_22_11(hass, site_cge, "radar_movimento_1730.jpg", "Sun, 22 Nov 2026 20:37:19 GMT")

    # A chuva passa bem ao sul da Paulista.
    chega = hass.states.get(CHEGA_CASA)
    assert chega.state == STATE_UNKNOWN
    assert chega.attributes["motivo"] == "nenhuma chuva chegando nos próximos 60 minutos"
    assert chega.attributes["vindo_de"] == "oeste"


async def test_imagem_republicada_mantem_o_movimento(
    hass: HomeAssistant, site_cge, freezer
) -> None:
    freezer.move_to("2026-11-22T20:38:00+00:00")
    _casa(hass, GRAJAU)
    site_cge.paginas[URL_RADAR] = site_cge.fixture("radar_movimento_1720.jpg")
    site_cge.modificado[URL_RADAR] = "Sun, 22 Nov 2026 20:31:47 GMT"
    await _configurar(hass)
    await _chuva_de_22_11(hass, site_cge, "radar_movimento_1730.jpg", "Sun, 22 Nov 2026 20:37:19 GMT")

    # O servidor publica a mesma imagem de novo, com outro Last-Modified.
    await _chuva_de_22_11(hass, site_cge, "radar_movimento_1730.jpg", "Sun, 22 Nov 2026 20:39:16 GMT")

    assert float(hass.states.get(CHEGA_CASA).state) == pytest.approx(14, abs=3)


# ------------------------------------------------------------------ câmeras


async def test_camera_radar(hass: HomeAssistant, site_cge) -> None:
    site_cge.paginas[URL_RADAR] = site_cge.fixture("radar_fraca.jpg")
    await _configurar(hass)

    imagem = await async_get_image(hass, "camera.cgesp_radar")

    assert imagem.content_type == "image/jpeg"
    assert imagem.content == site_cge.fixture("radar_fraca.jpg")
    camera = hass.states.get("camera.cgesp_radar")
    assert 0 < camera.attributes["area_com_chuva_pct"] < 0.2


async def test_camera_animacao(hass: HomeAssistant, site_cge) -> None:
    await _configurar(hass)
    await _nova_imagem(hass, site_cge, "radar_fraca.jpg", 5)
    await _nova_imagem(hass, site_cge, "radar_chuva.jpg", 10)

    imagem = await async_get_image(hass, "camera.cgesp_radar_animacao")

    assert imagem.content_type == "image/gif"
    assert Image.open(io.BytesIO(imagem.content)).n_frames == 3
    animacao = hass.states.get("camera.cgesp_radar_animacao")
    assert animacao.attributes["quadros"] == 3
    assert animacao.attributes["inicio"] == datetime(2026, 11, 19, 18, 0, tzinfo=UTC)
    assert animacao.attributes["fim"] == datetime(2026, 11, 19, 18, 10, tzinfo=UTC)


async def test_imagem_que_nao_mudou_nao_e_baixada_de_novo(hass: HomeAssistant, site_cge) -> None:
    await _configurar(hass)
    radar = _radar(hass)
    leitura = radar.data

    await radar.async_refresh()

    # O servidor respondeu 304: mesma leitura, sem quadro novo.
    assert radar.last_update_success
    assert radar.data is leitura
    assert len(radar.animacao) == 1


async def test_radar_fora_do_ar_nao_afeta_alertas(hass: HomeAssistant, site_cge) -> None:
    site_cge.paginas[URL_RADAR] = None
    await _configurar(hass)

    assert hass.states.get("camera.cgesp_radar").state == STATE_UNAVAILABLE
    assert hass.states.get(CHUVA_CASA).state == STATE_UNAVAILABLE
    assert hass.states.get("sensor.cgesp_alagamentos_ativos").state == "1"


async def test_falha_passageira_mantem_a_ultima_leitura(
    hass: HomeAssistant, site_cge, caplog
) -> None:
    _casa(hass, PAULISTA)
    site_cge.paginas[URL_RADAR] = site_cge.fixture("radar_chuva.jpg")
    await _configurar(hass)
    radar = _radar(hass)
    leitura = radar.data

    # 502, 504 e imagem cortada: os sensores continuam com a imagem anterior,
    # sem erro no log nem aviso em Reparos, e a próxima tentativa é logo.
    inteira = site_cge.fixture("radar_chuva.jpg")
    for minuto, conteudo in [(5, 502), (6, 504), (7, inteira[: len(inteira) // 2])]:
        await _nova_imagem_bruta(hass, site_cge, conteudo, minuto)
        assert radar.last_update_success
        assert radar.data is leitura
        assert hass.states.get(CHUVA_CASA).state == "moderada"
        assert radar.update_interval == timedelta(minutes=1)
    assert radar.falhas_seguidas == 3
    assert not [
        r for r in caplog.records
        if r.name.startswith("custom_components") and r.levelname in ("ERROR", "WARNING")
    ]
    assert ir.async_get(hass).async_get_issue(DOMAIN, "layout_radar") is None

    # O servidor volta: leitura nova e intervalo normal.
    await _nova_imagem(hass, site_cge, "radar_sem_chuva.jpg", 8)
    assert hass.states.get(CHUVA_CASA).state == "sem_chuva"
    assert radar.falhas_seguidas == 0
    assert radar.update_interval == timedelta(minutes=5)


async def test_falha_longa_deixa_os_sensores_indisponiveis(
    hass: HomeAssistant, site_cge, freezer
) -> None:
    freezer.move_to("2026-11-19T18:00:00+00:00")
    _casa(hass, PAULISTA)
    await _configurar(hass)
    radar = _radar(hass)

    site_cge.paginas[URL_RADAR] = 502
    await radar.async_refresh()
    assert hass.states.get(CHUVA_CASA).state == "sem_chuva"

    # Depois de 20 minutos falhando, a imagem antiga já não vale.
    freezer.tick(timedelta(minutes=21))
    await radar.async_refresh()
    await hass.async_block_till_done()

    assert not radar.last_update_success
    assert hass.states.get(CHUVA_CASA).state == STATE_UNAVAILABLE
    assert radar.update_interval == timedelta(minutes=5)


async def test_layout_do_radar_mudou(hass: HomeAssistant, site_cge) -> None:
    _casa(hass, PAULISTA)
    await _configurar(hass)
    saida = io.BytesIO()
    Image.new("RGB", (900, 700), "white").save(saida, format="JPEG")

    site_cge.trocar(URL_RADAR, saida.getvalue(), "Thu, 19 Nov 2026 18:05:00 GMT")
    await _radar(hass).async_refresh()
    await hass.async_block_till_done()

    # Melhor indisponível do que "sem chuva" errado.
    assert hass.states.get(CHUVA_CASA).state == STATE_UNAVAILABLE
    aviso = ir.async_get(hass).async_get_issue(DOMAIN, "layout_radar")
    assert aviso is not None
    assert aviso.translation_placeholders["parte"] == "radar de chuva"

    await _nova_imagem(hass, site_cge, "radar_sem_chuva.jpg", 10)
    assert hass.states.get(CHUVA_CASA).state == "sem_chuva"
    assert ir.async_get(hass).async_get_issue(DOMAIN, "layout_radar") is None


# ------------------------------------------------------------------ intervalo


async def test_intervalo_seco(hass: HomeAssistant, site_cge, freezer) -> None:
    # 19h em São Paulo, sem alagamento e sem chuva prevista: alertas a cada 30 min.
    freezer.move_to("2026-11-19T22:00:00+00:00")
    site_cge.paginas[URL_ALAGAMENTOS] = site_cge.fixture("alagamentos_vazio.html")
    site_cge.paginas[URL_PREVISAO] = site_cge.fixture("previsao_pancadas.html")
    await _configurar(hass)
    radar = _radar(hass)
    assert radar.update_interval == timedelta(minutes=15)

    await _nova_imagem(hass, site_cge, "radar_fraca.jpg", 5)

    assert radar.update_interval == timedelta(minutes=5)
    assert radar.motivo_intervalo == "chuva no radar"


async def test_intervalo_com_previsao_de_chuva(hass: HomeAssistant, site_cge, freezer) -> None:
    # 8h em São Paulo: pancadas previstas para a tarde.
    freezer.move_to("2026-11-19T11:00:00+00:00")
    site_cge.paginas[URL_ALAGAMENTOS] = site_cge.fixture("alagamentos_vazio.html")
    site_cge.paginas[URL_PREVISAO] = site_cge.fixture("previsao_pancadas.html")
    await _configurar(hass)

    assert _radar(hass).update_interval == timedelta(minutes=5)


async def test_intervalo_fixo(hass: HomeAssistant, site_cge, freezer) -> None:
    freezer.move_to("2026-11-19T22:00:00+00:00")
    site_cge.paginas[URL_ALAGAMENTOS] = site_cge.fixture("alagamentos_vazio.html")
    site_cge.paginas[URL_PREVISAO] = site_cge.fixture("previsao_pancadas.html")
    await _configurar(hass, **{CONF_INTERVALO_ADAPTATIVO: False})

    assert _radar(hass).update_interval == timedelta(minutes=5)


# ------------------------------------------------------------------ remover e diagnóstico


async def test_remover(hass: HomeAssistant, site_cge) -> None:
    entrada = await _configurar(hass)

    assert await hass.config_entries.async_unload(entrada.entry_id)
    await hass.async_block_till_done()

    assert DATA_RADAR_COORDINATOR not in hass.data[DOMAIN]
    assert hass.states.get("camera.cgesp_radar").state == STATE_UNAVAILABLE


async def test_diagnostico(hass: HomeAssistant, site_cge, hass_client) -> None:
    entrada = await _configurar(hass)
    await _nova_imagem(hass, site_cge, "radar_chuva.jpg", 5)

    diagnostico = await get_diagnostics_for_config_entry(hass, hass_client, entrada)

    radar = diagnostico["radar"]
    assert radar["ultima_atualizacao_ok"] is True
    assert radar["erro_layout"] is None
    assert radar["celulas_com_chuva"] > 0
    assert radar["quadros_animacao"] == 2


# ------------------------------------------------------------------ camada do mapa


async def test_camada_de_chuva_no_mapa(hass: HomeAssistant, site_cge, hass_client_no_auth) -> None:
    from .test_cge_radar import bloco_e_pixel

    site_cge.paginas[URL_RADAR] = site_cge.fixture("radar_chuva.jpg")
    await _configurar(hass)
    # Sem login: o card de mapa pede os blocos direto ao servidor.
    cliente = await hass_client_no_auth()

    x, y, px, py = bloco_e_pixel(*PAULISTA, zoom=13)
    resposta = await cliente.get(f"/api/cgesp/radar/qualquer/13/{x}/{y}.png")
    assert resposta.status == 200
    assert resposta.content_type == "image/png"
    assert "max-age" in resposta.headers["Cache-Control"]
    imagem = Image.open(io.BytesIO(await resposta.read())).convert("RGBA")
    assert imagem.getpixel((px, py)) == (252, 212, 63, 255)  # moderada

    # De novo: vem do cache, igual.
    segunda = await cliente.get(f"/api/cgesp/radar/outra/13/{x}/{y}.png")
    assert await segunda.read() == await resposta.read()

    # Fora da imagem: bloco transparente.
    x, y, px, py = bloco_e_pixel(*CAMPINAS, zoom=13)
    vazio = await cliente.get(f"/api/cgesp/radar/qualquer/13/{x}/{y}.png")
    assert Image.open(io.BytesIO(await vazio.read())).convert("RGBA").getpixel((px, py))[3] == 0

    # Endereços inválidos.
    assert (await cliente.get("/api/cgesp/radar/v/13/99999/1.png")).status == 404
    assert (await cliente.get("/api/cgesp/radar/v/25/1/1.png")).status == 404
    assert (await cliente.get("/api/cgesp/radar/v/a/1/1.png")).status == 404


async def test_horario_do_radar(hass: HomeAssistant, site_cge) -> None:
    await _configurar(hass)

    horario = hass.states.get("sensor.cgesp_radar_horario")
    assert horario.attributes["device_class"] == "timestamp"
    # A hora do título (14:45 em São Paulo), não a de publicação.
    assert horario.state == "2026-11-19T17:45:00+00:00"
    assert horario.attributes["publicado_em"] == datetime(2026, 11, 19, 18, 0, tzinfo=UTC)
