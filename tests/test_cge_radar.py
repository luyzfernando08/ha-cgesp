"""Leitura da imagem do radar de chuva.

Fixtures (imagem real do CGE de 19/11/2026, 14:45):
- radar_fraca.jpg: como publicada, com chuva fraca perto de Parelheiros;
- radar_sem_chuva.jpg: a mesma, sem a mancha de chuva;
- radar_chuva.jpg: sem chuva, com blocos pintados nas cores da legenda:
  moderada na Av. Paulista, forte em Itaim Paulista e muito forte no Campo Limpo.
"""
import io
import math
from datetime import UTC, datetime, timedelta

import pytest
from PIL import Image

from custom_components.cgesp.cge_radar import (
    BLOCO_VAZIO,
    FORTE,
    FRACA,
    MODERADA,
    MUITO_FORTE,
    SEM_CHUVA,
    AnimacaoRadar,
    LeituraRadar,
    RadarImagemInvalida,
    RadarLayoutError,
    horario_do_radar,
    ler_hora_do_titulo,
    ler_radar,
    medir_movimento,
)

from .conftest import SiteCge

HORARIO = datetime(2026, 11, 19, 17, 45)

PAULISTA = (-23.5614, -46.6559)
ITAIM_PAULISTA = (-23.4935, -46.4140)
CAMPO_LIMPO = (-23.6500, -46.7500)
PARELHEIROS_CHUVA = (-23.8093, -46.6517)  # dentro da mancha de radar_fraca.jpg
CONSOLACAO = (-23.5500, -46.6300)  # ~2,7 km a nordeste da Paulista
CAMPINAS = (-22.9056, -47.0608)  # fora da imagem


def _ler(nome: str, quando: datetime = HORARIO) -> LeituraRadar:
    return ler_radar(SiteCge.fixture(nome), quando)


@pytest.fixture(scope="module")
def chuva() -> LeituraRadar:
    return _ler("radar_chuva.jpg")


# ------------------------------------------------------------------ chuva num ponto


def test_sem_chuva() -> None:
    leitura = _ler("radar_sem_chuva.jpg")

    assert not leitura.tem_chuva
    assert leitura.area_com_chuva() == 0
    assert leitura.nivel_em(*PAULISTA) == SEM_CHUVA
    assert leitura.chuva_mais_proxima(*PAULISTA) is None


def test_chuva_fraca_da_imagem_real() -> None:
    leitura = _ler("radar_fraca.jpg")

    assert leitura.tem_chuva
    assert leitura.nivel_em(*PARELHEIROS_CHUVA) == FRACA
    assert leitura.nivel_em(*PAULISTA) == SEM_CHUVA
    # Só a mancha de Parelheiros: nada do fundo de satélite vira chuva.
    assert 0 < leitura.area_com_chuva() < 0.002


@pytest.mark.parametrize(
    ("ponto", "nivel"),
    [(PAULISTA, MODERADA), (ITAIM_PAULISTA, FORTE), (CAMPO_LIMPO, MUITO_FORTE)],
)
def test_intensidade(chuva: LeituraRadar, ponto, nivel) -> None:
    assert chuva.nivel_em(*ponto) == nivel


def test_fora_da_imagem(chuva: LeituraRadar) -> None:
    assert chuva.nivel_em(*CAMPINAS) is None
    assert not chuva.coberto(*CAMPINAS)


def test_canto_da_legenda_nao_e_radar(chuva: LeituraRadar) -> None:
    # As cores da legenda ficam no canto inferior direito da imagem.
    assert chuva.nivel_em(-23.97, -46.40) is None


# ------------------------------------------------------------------ chuva mais próxima


def test_chovendo_no_ponto(chuva: LeituraRadar) -> None:
    proxima = chuva.chuva_mais_proxima(*PAULISTA)

    assert proxima.distancia_km == 0
    assert proxima.intensidade == "moderada"
    assert proxima.direcao is None


def test_chuva_mais_proxima(chuva: LeituraRadar) -> None:
    proxima = chuva.chuva_mais_proxima(*CONSOLACAO)

    # O bloco da Paulista tem ~1,2 km de lado: a borda fica a ~2 km.
    assert proxima.distancia_km == pytest.approx(2.0, abs=0.4)
    assert proxima.intensidade == "moderada"
    assert proxima.direcao == "sudoeste"


def test_chuva_forte_mais_proxima(chuva: LeituraRadar) -> None:
    forte = chuva.chuva_mais_proxima(*CONSOLACAO, nivel_minimo=FORTE)

    # Ignora a moderada da Paulista; a mais perto, forte ou pior, é a do Campo Limpo.
    assert forte.intensidade == "muito_forte"
    assert forte.distancia_km == pytest.approx(15.5, abs=1)
    assert forte.direcao == "sudoeste"


def test_direcoes(chuva: LeituraRadar) -> None:
    # Itaim Paulista fica a leste da Paulista.
    assert chuva.chuva_mais_proxima(ITAIM_PAULISTA[0], -46.60, FORTE).direcao == "leste"
    # Ao sul do bloco da Paulista, a chuva está ao norte.
    assert chuva.chuva_mais_proxima(-23.60, -46.6559).direcao == "norte"


# ------------------------------------------------------------------ layout


def _jpeg(imagem: Image.Image) -> bytes:
    saida = io.BytesIO()
    imagem.save(saida, format="JPEG", quality=95)
    return saida.getvalue()


def test_tamanho_diferente() -> None:
    with pytest.raises(RadarLayoutError, match="tamanho"):
        ler_radar(_jpeg(Image.new("RGB", (800, 1000), "white")), HORARIO)


def test_sem_moldura() -> None:
    with pytest.raises(RadarLayoutError, match="moldura"):
        ler_radar(_jpeg(Image.new("RGB", (700, 1000), "white")), HORARIO)


def test_mapa_deslocado() -> None:
    """Mesmo tamanho, mas o mapa andou alguns pixels: os eixos não batem."""
    original = Image.open(io.BytesIO(SiteCge.fixture("radar_chuva.jpg"))).convert("RGB")
    deslocada = Image.new("RGB", original.size, "white")
    deslocada.paste(original, (12, 0))

    with pytest.raises(RadarLayoutError):
        ler_radar(_jpeg(deslocada), HORARIO)


def test_nao_e_imagem() -> None:
    # Página de erro no lugar da imagem: falha passageira, não layout novo.
    with pytest.raises(RadarImagemInvalida, match="17 bytes"):
        ler_radar(b"<html>erro</html>", HORARIO)


def test_imagem_cortada() -> None:
    # Transferência interrompida no meio do arquivo.
    inteira = SiteCge.fixture("radar_chuva.jpg")
    with pytest.raises(RadarImagemInvalida):
        ler_radar(inteira[: len(inteira) // 2], HORARIO)


# ------------------------------------------------------------------ animação


def _quadros_do_gif(conteudo: bytes) -> int:
    return Image.open(io.BytesIO(conteudo)).n_frames


def test_animacao() -> None:
    animacao = AnimacaoRadar()
    for minuto, nome in enumerate(["radar_sem_chuva.jpg", "radar_fraca.jpg", "radar_chuva.jpg"]):
        animacao.adicionar(_ler(nome, HORARIO + timedelta(minutes=5 * minuto)))

    gif = animacao.gif()

    assert gif[:6] == b"GIF89a"
    assert _quadros_do_gif(gif) == 3
    assert animacao.horarios[-1] == HORARIO + timedelta(minutes=10)
    # Mesma paleta em todos os quadros: o GIF fica pequeno.
    assert len(gif) < 400_000
    assert animacao.gif() is gif  # cache até chegar um quadro novo


def test_animacao_mesma_chuva_troca_o_ultimo_quadro() -> None:
    animacao = AnimacaoRadar()
    animacao.adicionar(_ler("radar_chuva.jpg", HORARIO))
    animacao.adicionar(_ler("radar_chuva.jpg", HORARIO + timedelta(minutes=5)))

    assert len(animacao) == 1
    assert animacao.horarios == [HORARIO + timedelta(minutes=5)]


def test_animacao_guarda_so_a_ultima_hora() -> None:
    animacao = AnimacaoRadar()
    nomes = ["radar_sem_chuva.jpg", "radar_fraca.jpg", "radar_chuva.jpg"]
    for i in range(20):
        animacao.adicionar(_ler(nomes[i % 3], HORARIO + timedelta(minutes=5 * i)))

    ultimo = HORARIO + timedelta(minutes=5 * 19)
    assert animacao.horarios[-1] == ultimo
    assert animacao.horarios[0] == ultimo - timedelta(hours=1)
    assert len(animacao) == 13


def test_animacao_ignora_leitura_antiga() -> None:
    animacao = AnimacaoRadar()
    animacao.adicionar(_ler("radar_chuva.jpg", HORARIO))
    animacao.adicionar(_ler("radar_fraca.jpg", HORARIO - timedelta(minutes=5)))

    assert animacao.horarios == [HORARIO]


# ------------------------------------------------------------------ hora do radar


def _imagem(nome: str) -> Image.Image:
    return Image.open(io.BytesIO(SiteCge.fixture(nome)))


def test_hora_do_titulo() -> None:
    # "Atualizado em: 19-11-2026 14:45 Local"
    assert ler_hora_do_titulo(_imagem("radar_sem_chuva.jpg")) == (14, 45)


def test_titulo_ilegivel() -> None:
    imagem = _imagem("radar_sem_chuva.jpg").convert("RGB")
    imagem.paste((255, 255, 255), (0, 0, 700, 45))
    assert ler_hora_do_titulo(imagem) is None


def test_horario_do_radar() -> None:
    publicada = datetime(2026, 11, 19, 18, 0, tzinfo=UTC)  # 15:00 em São Paulo
    assert horario_do_radar((14, 45), publicada) == datetime(2026, 11, 19, 17, 45, tzinfo=UTC)
    # Publicada logo depois da meia-noite com o título da véspera.
    meia_noite = datetime(2026, 11, 20, 3, 5, tzinfo=UTC)  # 00:05 em São Paulo
    assert horario_do_radar((23, 55), meia_noite) == datetime(2026, 11, 20, 2, 55, tzinfo=UTC)
    # Título de horas antes da publicação: não dá para confiar.
    assert horario_do_radar((9, 0), publicada) is None
    assert horario_do_radar(None, publicada) is None


def test_leitura_tem_a_hora_do_radar() -> None:
    leitura = _ler("radar_chuva.jpg", datetime(2026, 11, 19, 18, 0, tzinfo=UTC))
    assert leitura.horario == datetime(2026, 11, 19, 17, 45, tzinfo=UTC)


# ------------------------------------------------------------------ movimento

INICIO = datetime(2026, 11, 19, 17, 45, tzinfo=UTC)
BLOCO = (-23.62, -46.70)  # chuva moderada pintada aqui, em 48 x 48 pixels
ANDOU_PX = 24  # 6 células para leste em 10 minutos


def _pixel(latitude: float, longitude: float) -> tuple[int, int]:
    return round(118.58 + (longitude + 46.8) * 1176.5), round(139.31 + (-23.4 - latitude) * 1284.5)


def _com_bloco(deslocamento_px: int, horario: datetime) -> LeituraRadar:
    imagem = _imagem("radar_sem_chuva.jpg").convert("RGB")
    x, y = _pixel(*BLOCO)
    x += deslocamento_px
    imagem.paste((252, 212, 63), (x - 24, y - 24, x + 24, y + 24))
    leitura = ler_radar(_jpeg(imagem), horario)
    leitura.horario = horario
    return leitura


@pytest.fixture(scope="module")
def bloco_andando() -> LeituraRadar:
    antes = _com_bloco(0, INICIO)
    depois = _com_bloco(ANDOU_PX, INICIO + timedelta(minutes=10))
    depois.movimento = medir_movimento(antes, depois)
    return depois


def test_movimento(bloco_andando: LeituraRadar) -> None:
    movimento = bloco_andando.movimento

    assert movimento.vx == pytest.approx(0.6, abs=0.05)  # células por minuto
    assert movimento.vy == pytest.approx(0, abs=0.05)
    assert movimento.velocidade_kmh == pytest.approx(12.5, abs=1)
    assert movimento.indo_para == "leste"
    assert movimento.vindo_de == "oeste"
    assert movimento.confianca > 0.9
    assert movimento.minutos == 10


def _a_leste_do_bloco(px_da_borda: int) -> tuple[float, float]:
    """Ponto `px_da_borda` pixels a leste da borda do bloco (já deslocado)."""
    x, y = _pixel(*BLOCO)
    x += ANDOU_PX + 24 + px_da_borda
    return -23.4 - (y - 139.31) / 1284.5, -46.8 + (x - 118.58) / 1176.5


def test_chuva_chegando(bloco_andando: LeituraRadar) -> None:
    # 40 pixels = 10 células a 0,6 célula por minuto: uns 17 minutos.
    chegada = bloco_andando.chegada_da_chuva(*_a_leste_do_bloco(40))

    assert chegada.minutos == pytest.approx(17, abs=2)
    assert chegada.intensidade_maxima == "moderada"
    assert chegada.movimento.vindo_de == "oeste"


def test_chegada_conta_a_partir_de_agora(bloco_andando: LeituraRadar) -> None:
    # A imagem é de 10 minutos atrás (o servidor demora para publicar): a
    # chuva que chegaria 17 minutos depois da imagem chega em 7 a partir de agora.
    ponto = _a_leste_do_bloco(40)
    pela_imagem = bloco_andando.chegada_da_chuva(*ponto)
    agora = bloco_andando.horario + timedelta(minutes=10)

    chegada = bloco_andando.chegada_da_chuva(*ponto, agora=agora)

    assert chegada.minutos == pela_imagem.minutos - 10
    assert chegada.chega_as == pela_imagem.chega_as == bloco_andando.horario + timedelta(
        minutes=pela_imagem.minutos
    )
    # Passou da hora prevista: pela previsão, já está chovendo lá.
    passou = bloco_andando.chegada_da_chuva(*ponto, agora=agora + timedelta(minutes=8))
    assert passou.minutos == 0


def test_chuva_no_ponto_chega_em_zero(bloco_andando: LeituraRadar) -> None:
    assert bloco_andando.chegada_da_chuva(BLOCO[0], BLOCO[1] + ANDOU_PX / 1176.5).minutos == 0


def test_chuva_indo_embora_ou_longe_demais(bloco_andando: LeituraRadar) -> None:
    # A oeste do bloco: a chuva está se afastando.
    assert bloco_andando.chegada_da_chuva(BLOCO[0], BLOCO[1] - 0.05) is None
    # A leste, mas longe demais para chegar em 60 minutos (a 12,5 km/h).
    assert bloco_andando.chegada_da_chuva(*_a_leste_do_bloco(400)) is None
    # Ao norte: a chuva passa ao lado.
    assert bloco_andando.chegada_da_chuva(BLOCO[0] + 0.05, BLOCO[1] + 0.05) is None


def test_sem_movimento_medido() -> None:
    leitura = _com_bloco(0, INICIO)
    assert leitura.movimento is None
    assert leitura.chegada_da_chuva(*_a_leste_do_bloco(40)) is None


def test_movimento_precisa_de_intervalo_valido() -> None:
    antes = _com_bloco(0, INICIO)
    # Mesma hora (imagem republicada) ou muito tempo depois: não mede.
    assert medir_movimento(antes, _com_bloco(ANDOU_PX, INICIO)) is None
    assert medir_movimento(antes, _com_bloco(ANDOU_PX, INICIO + timedelta(minutes=40))) is None
    # Sem a hora do título: não mede.
    sem_hora = _com_bloco(ANDOU_PX, INICIO + timedelta(minutes=10))
    sem_hora.horario = None
    assert medir_movimento(antes, sem_hora) is None


def test_sem_chuva_nao_mede() -> None:
    seco = _ler("radar_sem_chuva.jpg", INICIO)
    seco.horario = INICIO
    depois = _com_bloco(0, INICIO + timedelta(minutes=10))
    assert medir_movimento(seco, depois) is None


# ------------------------------------------------------------------ blocos do mapa


def bloco_e_pixel(latitude: float, longitude: float, zoom: int) -> tuple[int, int, int, int]:
    """Bloco {x}/{y} dos mapas web que contém o ponto, e o pixel dentro dele."""
    escala = 256 * 2**zoom
    gx = (longitude + 180) / 360 * escala
    seno = math.sin(math.radians(latitude))
    gy = (0.5 - math.log((1 + seno) / (1 - seno)) / (4 * math.pi)) * escala
    return int(gx // 256), int(gy // 256), int(gx % 256), int(gy % 256)


def _cor(png: bytes, px: int, py: int) -> tuple[int, int, int, int]:
    return Image.open(io.BytesIO(png)).convert("RGBA").getpixel((px, py))


@pytest.mark.parametrize(
    ("ponto", "cor"),
    [
        (PAULISTA, (252, 212, 63)),  # moderada
        (ITAIM_PAULISTA, (251, 54, 20)),  # forte
        (CAMPO_LIMPO, (182, 39, 245)),  # muito forte
    ],
)
def test_bloco_com_chuva(chuva: LeituraRadar, ponto, cor) -> None:
    x, y, px, py = bloco_e_pixel(*ponto, zoom=13)
    png = chuva.bloco_do_mapa(13, x, y)

    assert Image.open(io.BytesIO(png)).format == "PNG"
    assert Image.open(io.BytesIO(png)).size == (256, 256)
    assert _cor(png, px, py) == (*cor, 255)


def test_bloco_transparente_fora_da_chuva(chuva: LeituraRadar) -> None:
    # Consolação: no mesmo bloco da Paulista, mas sem chuva.
    x, y, _, _ = bloco_e_pixel(*PAULISTA, zoom=13)
    _, _, px, py = bloco_e_pixel(*CONSOLACAO, zoom=13)
    assert bloco_e_pixel(*CONSOLACAO, zoom=13)[:2] == (x, y)
    assert _cor(chuva.bloco_do_mapa(13, x, y), px, py)[3] == 0


def test_bloco_vazio(chuva: LeituraRadar) -> None:
    # Fora da imagem do radar, e dentro dela sem chuva.
    assert chuva.bloco_do_mapa(13, *bloco_e_pixel(*CAMPINAS, zoom=13)[:2]) == BLOCO_VAZIO
    seco = _ler("radar_sem_chuva.jpg")
    assert seco.bloco_do_mapa(13, *bloco_e_pixel(*PAULISTA, zoom=13)[:2]) == BLOCO_VAZIO
    assert _cor(BLOCO_VAZIO, 128, 128)[3] == 0


def test_bloco_de_zoom_baixo_tem_a_cidade_toda(chuva: LeituraRadar) -> None:
    # Zoom 8: a imagem inteira cabe em um bloco; a chuva continua no lugar.
    for ponto, nivel in ((PAULISTA, MODERADA), (ITAIM_PAULISTA, FORTE)):
        x, y, px, py = bloco_e_pixel(*ponto, zoom=8)
        assert _cor(chuva.bloco_do_mapa(8, x, y), px, py)[3] == 255, nivel


def test_legenda_nao_vira_chuva() -> None:
    # A legenda (canto sudeste) tem as cores da chuva, mas não é radar.
    leitura = _ler("radar_sem_chuva.jpg")
    legenda = (-23.99, -46.40)
    x, y, _, _ = bloco_e_pixel(*legenda, zoom=10)
    assert leitura.bloco_do_mapa(10, x, y) == BLOCO_VAZIO
