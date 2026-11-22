"""Radar de chuva do CGE, sem dependência do Home Assistant.

A imagem publicada pelo CGE (radar do SAISP) é um mapa com latitude e
longitude nos eixos, e a chuva aparece em quatro cores chapadas (fraca,
moderada, forte e muito forte). Daqui saem:

- a intensidade da chuva num ponto (casa, pessoa, zona);
- a chuva mais próxima de um ponto (distância, intensidade e direção);
- a animação da última hora (GIF).

A posição dos eixos foi medida na imagem. Se o layout mudar, `ler_radar`
levanta `RadarLayoutError` em vez de devolver valores errados.
"""
from __future__ import annotations

import io
import math
import threading
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import cached_property

from PIL import Image

URL_RADAR = "https://www.saisp.br/cgesp/radarIntens.jpg"

NIVEIS = ("sem_chuva", "fraca", "moderada", "forte", "muito_forte")
SEM_CHUVA, FRACA, MODERADA, FORTE, MUITO_FORTE = range(5)

# Cores da legenda da imagem (medidas no próprio JPEG).
_CORES = {
    FRACA: (57, 234, 55),
    MODERADA: (252, 212, 63),
    FORTE: (251, 54, 20),
    MUITO_FORTE: (182, 39, 245),
}
# Distância máxima (RGB) para um pixel contar como chuva. O JPEG borra um pouco
# as cores; o fundo de satélite fica bem mais longe delas.
_DISTANCIA_COR = 70

# ---- Calibração (imagem de 700 x 1000) -------------------------------------
TAMANHO = (700, 1000)
# x = _X0 + (longitude - _LON0) * _PX_LON ; y = _Y0 + (_LAT0 - latitude) * _PX_LAT
_LON0, _X0, _PX_LON = -46.8, 118.58, 1176.5
_LAT0, _Y0, _PX_LAT = -23.4, 139.31, 1284.5
# Interior da moldura (x0, y0, x1, y1), sem as bordas pretas.
_AREA = (47, 51, 673, 953)
# Caixa da legenda, no canto inferior direito: não é radar.
_LEGENDA = (497, 822, 673, 953)
# Marcas dos eixos que precisam continuar no lugar: (x, y).
_MARCAS = [(236, 958), (354, 958), (589, 958), (41, 139), (41, 396), (41, 910)]

# A chuva é agrupada em células de 4 x 4 pixels (~350 m).
CELULA = 4
_MINIMO_PIXELS = 3  # pixels de chuva numa célula para ela contar

KM_POR_GRAU = 111.32
_DIRECOES = ("norte", "nordeste", "leste", "sudeste", "sul", "sudoeste", "oeste", "noroeste")

# Animação.
JANELA_ANIMACAO = timedelta(hours=1)
MAXIMO_QUADROS = 15
TAMANHO_ANIMACAO = (350, 500)
DURACAO_QUADRO_MS = 400
DURACAO_ULTIMO_MS = 1800


class RadarLayoutError(Exception):
    """A imagem do radar não tem mais o layout esperado."""


class RadarImagemInvalida(Exception):
    """O servidor mandou algo que não é uma imagem inteira (página de erro,
    arquivo cortado no meio da transferência). Costuma ser passageiro."""


@dataclass
class ChuvaProxima:
    distancia_km: float
    nivel: int
    direcao: str | None  # None quando está chovendo no próprio ponto

    @property
    def intensidade(self) -> str:
        return NIVEIS[self.nivel]


@dataclass
class LeituraRadar:
    imagem: bytes  # JPEG original, servido pela câmera
    obtida_em: datetime
    # Nível de cada célula (linha a linha), só da área do mapa.
    celulas: bytes
    colunas: int
    linhas: int
    quadro: Image.Image | None = field(default=None, repr=False)  # para a animação

    # ------------------------------------------------ consultas

    def _celula(self, latitude: float, longitude: float) -> tuple[int, int] | None:
        x = _X0 + (longitude - _LON0) * _PX_LON
        y = _Y0 + (_LAT0 - latitude) * _PX_LAT
        x0, y0, x1, y1 = _AREA
        if not (x0 <= x < x1 and y0 <= y < y1) or _na_legenda(x, y):
            return None
        return int((x - x0) // CELULA), int((y - y0) // CELULA)

    def coberto(self, latitude: float, longitude: float) -> bool:
        return self._celula(latitude, longitude) is not None

    def nivel_em(self, latitude: float, longitude: float) -> int | None:
        """Intensidade no ponto; None fora da área do radar."""
        celula = self._celula(latitude, longitude)
        if celula is None:
            return None
        coluna, linha = celula
        return self.celulas[linha * self.colunas + coluna]

    def _centro(self, coluna: int, linha: int) -> tuple[float, float]:
        x = _AREA[0] + (coluna + 0.5) * CELULA
        y = _AREA[1] + (linha + 0.5) * CELULA
        return _LAT0 - (y - _Y0) / _PX_LAT, _LON0 + (x - _X0) / _PX_LON

    def chuva_mais_proxima(
        self, latitude: float, longitude: float, nivel_minimo: int = FRACA
    ) -> ChuvaProxima | None:
        """A célula com chuva (de `nivel_minimo` para cima) mais perto do
        ponto; None se não há chuva assim em nenhum lugar da imagem."""
        nivel_aqui = self.nivel_em(latitude, longitude)
        if nivel_aqui is not None and nivel_aqui >= nivel_minimo:
            return ChuvaProxima(0.0, nivel_aqui, None)
        melhor: tuple[float, int, float, float] | None = None
        cos_lat = math.cos(math.radians(latitude))
        for indice in self._indices_com_chuva:
            nivel = self.celulas[indice]
            if nivel < nivel_minimo:
                continue
            lat, lon = self._centro(indice % self.colunas, indice // self.colunas)
            dy = (lat - latitude) * KM_POR_GRAU
            dx = (lon - longitude) * KM_POR_GRAU * cos_lat
            km = math.hypot(dx, dy)
            if melhor is None or km < melhor[0]:
                melhor = (km, nivel, dx, dy)
        if melhor is None:
            return None
        km, nivel, dx, dy = melhor
        return ChuvaProxima(km, nivel, _direcao(dx, dy))

    @cached_property
    def _indices_com_chuva(self) -> list[int]:
        return [indice for indice, nivel in enumerate(self.celulas) if nivel]

    def area_com_chuva(self) -> float:
        """Fração das células do mapa com chuva (0 a 1)."""
        return len(self._indices_com_chuva) / len(self.celulas) if self.celulas else 0.0

    @property
    def tem_chuva(self) -> bool:
        return bool(self._indices_com_chuva)


def _na_legenda(x: float, y: float) -> bool:
    x0, y0, x1, y1 = _LEGENDA
    return x0 <= x <= x1 and y0 <= y <= y1


def _direcao(dx: float, dy: float) -> str:
    """Direção (de onde o ponto está para onde a chuva está)."""
    angulo = math.degrees(math.atan2(dx, dy)) % 360  # 0 = norte, 90 = leste
    return _DIRECOES[int((angulo + 22.5) // 45) % 8]


# --------------------------------------------------------------------------- #
# Leitura da imagem
# --------------------------------------------------------------------------- #


def _escuro(rgb: tuple[int, int, int]) -> bool:
    return sum(rgb) < 3 * 90


def _verificar_layout(imagem: Image.Image) -> None:
    if imagem.size != TAMANHO:
        raise RadarLayoutError(f"tamanho {imagem.size}, esperado {TAMANHO}")
    pixels = imagem.load()
    x0, y0, x1, y1 = _AREA
    # A legenda cobre a moldura no canto inferior direito.
    bordas = {
        "esquerda": [(x0 - 1, y) for y in range(y0, y1, 10)],
        "direita": [(x1, y) for y in range(y0, _LEGENDA[1], 10)],
        "topo": [(x, y0 - 1) for x in range(x0, x1, 10)],
        "base": [(x, y1) for x in range(x0, _LEGENDA[0], 10)],
    }
    for nome, pontos in bordas.items():
        escuros = sum(1 for p in pontos if _escuro(pixels[p]))
        if escuros < 0.9 * len(pontos):
            raise RadarLayoutError(f"moldura do mapa fora do lugar ({nome})")
    for marca in _MARCAS:
        if not _escuro(pixels[marca]):
            raise RadarLayoutError(f"marca do eixo fora do lugar em {marca}")


def _classificar(rgb: tuple[int, int, int]) -> int:
    r, g, b = rgb
    # Corte rápido: as cores de chuva são bem saturadas e claras.
    if max(r, g, b) < 180 or max(r, g, b) - min(r, g, b) < 120:
        return SEM_CHUVA
    limite = _DISTANCIA_COR * _DISTANCIA_COR
    for nivel, (cr, cg, cb) in _CORES.items():
        if (r - cr) ** 2 + (g - cg) ** 2 + (b - cb) ** 2 <= limite:
            return nivel
    return SEM_CHUVA


def _celulas(imagem: Image.Image) -> tuple[bytes, int, int]:
    x0, y0, x1, y1 = _AREA
    area = imagem.crop(_AREA)
    largura, altura = area.size
    colunas, linhas = math.ceil(largura / CELULA), math.ceil(altura / CELULA)
    contagem: dict[int, Counter] = {}
    # get_flattened_data substitui getdata no Pillow 12.1+.
    dados = (
        area.get_flattened_data()
        if hasattr(area, "get_flattened_data")
        else area.getdata()
    )
    for indice, rgb in enumerate(dados):
        nivel = _classificar(rgb)
        if nivel == SEM_CHUVA:
            continue
        x, y = indice % largura, indice // largura
        if _na_legenda(x + x0, y + y0):
            continue
        celula = (y // CELULA) * colunas + x // CELULA
        contagem.setdefault(celula, Counter())[nivel] += 1
    celulas = bytearray(colunas * linhas)
    for celula, niveis in contagem.items():
        if sum(niveis.values()) >= _MINIMO_PIXELS:
            celulas[celula] = niveis.most_common(1)[0][0]
    return bytes(celulas), colunas, linhas


def ler_radar(conteudo: bytes, obtida_em: datetime) -> LeituraRadar:
    """Lê a imagem do radar. Levanta RadarImagemInvalida se o conteúdo não é
    uma imagem inteira, e RadarLayoutError se o layout mudou."""
    try:
        imagem = Image.open(io.BytesIO(conteudo))
        imagem.load()
    except (OSError, ValueError) as err:
        raise RadarImagemInvalida(
            f"{len(conteudo)} bytes que não formam uma imagem ({type(err).__name__})"
        ) from err
    imagem = imagem.convert("RGB")
    _verificar_layout(imagem)
    celulas, colunas, linhas = _celulas(imagem)
    quadro = imagem.resize(TAMANHO_ANIMACAO, Image.Resampling.LANCZOS)
    return LeituraRadar(conteudo, obtida_em, celulas, colunas, linhas, quadro)


# --------------------------------------------------------------------------- #
# Animação
# --------------------------------------------------------------------------- #


class AnimacaoRadar:
    """Guarda os quadros da última hora e monta um GIF.

    Todos os quadros usam a mesma paleta: como o fundo não muda, o GIF só
    grava o que mudou de um quadro para o outro e fica pequeno.
    """

    def __init__(
        self, janela: timedelta = JANELA_ANIMACAO, maximo: int = MAXIMO_QUADROS
    ) -> None:
        self.janela = janela
        self.maximo = maximo
        self._quadros: list[tuple[datetime, bytes, Image.Image]] = []
        self._paleta: Image.Image | None = None
        self._gif: bytes | None = None
        self._trava = threading.Lock()

    def __len__(self) -> int:
        return len(self._quadros)

    def _criar_paleta(self, quadro: Image.Image) -> Image.Image:
        base = quadro.quantize(colors=240, method=Image.Quantize.MEDIANCUT)
        cores = list(base.getpalette()[: 240 * 3])
        cores += [c for rgb in _CORES.values() for c in rgb]
        cores += [0, 0, 0, 255, 255, 255]
        paleta = Image.new("P", (1, 1))
        paleta.putpalette(cores + [0] * (768 - len(cores)))
        return paleta

    def adicionar(self, leitura: LeituraRadar) -> None:
        if leitura.quadro is None:
            return
        with self._trava:
            if self._paleta is None:
                self._paleta = self._criar_paleta(leitura.quadro)
            quadro = leitura.quadro.quantize(
                palette=self._paleta, dither=Image.Dither.NONE
            )
            if self._quadros and self._quadros[-1][1] == leitura.celulas:
                # Mesma chuva: troca o último quadro (fica o horário mais novo).
                self._quadros[-1] = (leitura.obtida_em, leitura.celulas, quadro)
            elif self._quadros and leitura.obtida_em <= self._quadros[-1][0]:
                return  # leitura repetida ou fora de ordem
            else:
                self._quadros.append((leitura.obtida_em, leitura.celulas, quadro))
            limite = leitura.obtida_em - self.janela
            self._quadros = [q for q in self._quadros if q[0] >= limite][-self.maximo :]
            self._gif = None

    @property
    def horarios(self) -> list[datetime]:
        return [q[0] for q in self._quadros]

    def gif(self) -> bytes | None:
        with self._trava:
            if self._gif is not None or not self._quadros:
                return self._gif
            quadros = [q[2] for q in self._quadros]
            duracoes = [DURACAO_QUADRO_MS] * (len(quadros) - 1) + [DURACAO_ULTIMO_MS]
            saida = io.BytesIO()
            quadros[0].save(
                saida,
                format="GIF",
                save_all=True,
                append_images=quadros[1:],
                duration=duracoes,
                loop=0,
                optimize=False,
                disposal=1,
            )
            self._gif = saida.getvalue()
            return self._gif
