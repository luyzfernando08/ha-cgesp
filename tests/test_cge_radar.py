"""Leitura da imagem do radar de chuva.

Fixtures (imagem real do CGE de 19/11/2026, 14:45):
- radar_fraca.jpg: como publicada, com chuva fraca perto de Parelheiros;
- radar_sem_chuva.jpg: a mesma, sem a mancha de chuva;
- radar_chuva.jpg: sem chuva, com blocos pintados nas cores da legenda:
  moderada na Av. Paulista, forte em Itaim Paulista e muito forte no Campo Limpo.
"""
import io
from datetime import datetime, timedelta

import pytest
from PIL import Image

from custom_components.cgesp.cge_radar import (
    FORTE,
    FRACA,
    MODERADA,
    MUITO_FORTE,
    SEM_CHUVA,
    AnimacaoRadar,
    LeituraRadar,
    RadarLayoutError,
    ler_radar,
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
    imagem.save(saida, format="JPEG")
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
    with pytest.raises(RadarLayoutError, match="inválida"):
        ler_radar(b"<html>erro</html>", HORARIO)


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
