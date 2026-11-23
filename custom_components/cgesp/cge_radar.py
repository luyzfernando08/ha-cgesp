"""Radar de chuva do CGE, sem dependência do Home Assistant.

A imagem publicada pelo CGE (radar do SAISP) é um mapa com latitude e
longitude nos eixos, e a chuva aparece em quatro cores chapadas (fraca,
moderada, forte e muito forte). Daqui saem:

- a intensidade da chuva num ponto (casa, pessoa, zona);
- a chuva mais próxima de um ponto (distância, intensidade e direção);
- o movimento da chuva entre duas imagens e, com ele, quando a chuva deve
  chegar a um ponto;
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
from datetime import datetime, timedelta, timezone
from functools import cached_property
from zoneinfo import ZoneInfo

from PIL import Image, ImageChops, ImageFilter, ImageStat

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
# Tamanho de uma célula em km (no centro da imagem, latitude -23,6).
KM_CELULA_X = CELULA / _PX_LON * KM_POR_GRAU * math.cos(math.radians(23.6))
KM_CELULA_Y = CELULA / _PX_LAT * KM_POR_GRAU
_DIRECOES = ("norte", "nordeste", "leste", "sudeste", "sul", "sudoeste", "oeste", "noroeste")

# ---- Horário da imagem -----------------------------------------------------
# O título diz a hora do radar ("Atualizado em: 22-11-2026 17:20 Local"). O
# servidor publica cada imagem de 7 a 12 minutos depois, com atraso variável,
# então o Last-Modified não serve para medir a velocidade da chuva.
FUSO_SP = ZoneInfo("America/Sao_Paulo")
_TITULO = (300, 5, 700, 40)
# Assinatura de cada dígito do título: o glifo reduzido a 8 x 12 pixels, 1 bit
# por pixel (escuro = 1), linha a linha. Medidas nas imagens do servidor.
_DIGITOS: dict[int, int] = {
    0: 0x3C7EE7C3C3C3C3C3C3E77E3C,
    1: 0x070FFFFF0F0F0F0F0F0F0F0F,
    2: 0x3C7FE7C303070E3C70F0FFFF,
    3: 0x3CFEE7C7061E1F07C3E7FF3C,
    4: 0x0E1E1E3E266646FEFF0E0606,
    5: 0x7F7F60C0FEFF070303E7FE3C,
    6: 0x3C7FE3C0FEFFE3C3C3E77E3C,
    7: 0xFFFF06060C0C181818303030,
    8: 0x3C7E6666663E7EE7C3667E3C,
    9: 0x1C7E6763E3637F3F03677E3C,
}
_DISTANCIA_DIGITO = 6  # bits diferentes tolerados

# ---- Movimento e previsão ----------------------------------------------------
# A velocidade é medida entre duas imagens com 5 a 20 minutos de diferença
# (de preferência 10, que dá mais precisão que 5).
INTERVALO_MOVIMENTO = (timedelta(minutes=5), timedelta(minutes=20))
INTERVALO_MOVIMENTO_IDEAL = timedelta(minutes=10)
_VELOCIDADE_MAXIMA_KMH = 100
_FATOR_GROSSO = 3  # a busca começa numa grade 3x mais grossa
HORIZONTE_PREVISAO = 60  # minutos
# Minutos seguidos sem chuva para a chuva contar como parada.
SECO_MINIMO = 10
_CONFIANCA_MINIMA = 0.5

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


@dataclass(frozen=True)
class Movimento:
    """Velocidade da chuva, em células por minuto (vx para leste, vy para o
    sul, como as linhas da imagem)."""

    vx: float
    vy: float
    confianca: float  # correlação entre as duas imagens (0 a 1)
    minutos: float  # intervalo entre as imagens usadas

    @property
    def velocidade_kmh(self) -> float:
        return math.hypot(self.vx * KM_CELULA_X, self.vy * KM_CELULA_Y) * 60

    @property
    def indo_para(self) -> str | None:
        """Direção para onde a chuva vai; None se está quase parada."""
        if self.velocidade_kmh < 3:
            return None
        return _direcao(self.vx * KM_CELULA_X, -self.vy * KM_CELULA_Y)

    @property
    def vindo_de(self) -> str | None:
        if self.velocidade_kmh < 3:
            return None
        return _direcao(-self.vx * KM_CELULA_X, self.vy * KM_CELULA_Y)


@dataclass(frozen=True)
class ChegadaChuva:
    minutos: int  # a partir de agora; 0 = já deve estar chovendo no ponto
    nivel_maximo: int  # a mais forte prevista no ponto dentro do horizonte
    movimento: Movimento
    chega_as: datetime

    @property
    def intensidade_maxima(self) -> str:
        return NIVEIS[self.nivel_maximo]


@dataclass(frozen=True)
class FimChuva:
    # A partir de agora; 0 = já deve ter parado. None: não para dentro do
    # horizonte, ou a chuva que vem depois está fora da imagem.
    minutos: int | None
    nivel_maximo: int  # a mais forte prevista no ponto até parar
    movimento: Movimento
    para_as: datetime | None
    chuva_de_fora: bool = False

    @property
    def intensidade_maxima(self) -> str:
        return NIVEIS[self.nivel_maximo]


@dataclass
class LeituraRadar:
    imagem: bytes  # JPEG original, servido pela câmera
    obtida_em: datetime
    # Nível de cada célula (linha a linha), só da área do mapa.
    celulas: bytes
    colunas: int
    linhas: int
    quadro: Image.Image | None = field(default=None, repr=False)  # para a animação
    # Hora do radar (lida no título); None se não deu para ler.
    horario: datetime | None = None
    # Deslocamento da chuva medido contra uma imagem anterior.
    movimento: Movimento | None = None

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

    def chegada_da_chuva(
        self,
        latitude: float,
        longitude: float,
        agora: datetime | None = None,
        horizonte: int = HORIZONTE_PREVISAO,
    ) -> ChegadaChuva | None:
        """Em quantos minutos a partir de `agora` a chuva deve chegar ao ponto,
        empurrando a chuva da imagem com a velocidade medida. A imagem é de
        `horario`, uns 10 minutos antes de `agora` (o servidor demora para
        publicar), então a conta começa nesse atraso. None sem movimento
        medido, fora da imagem ou se nenhuma chuva chega dentro do horizonte."""
        celula = self._celula(latitude, longitude)
        movimento = self.movimento
        if celula is None or movimento is None or self.horario is None:
            return None
        atraso = 0
        if agora is not None:
            atraso = max(0, round((agora - self.horario).total_seconds() / 60))
        coluna, linha = celula
        chegada: int | None = None
        maximo = SEM_CHUVA
        for minuto in range(atraso, atraso + horizonte + 1):
            # A chuva que estará no ponto `minuto` minutos depois da imagem é
            # a que está nela em ponto - velocidade * minuto.
            nivel = self._nivel_celula(
                round(coluna - movimento.vx * minuto), round(linha - movimento.vy * minuto)
            )
            if nivel is None:
                break  # veio de fora da imagem: não dá para saber
            if nivel:
                if chegada is None:
                    chegada = minuto
                maximo = max(maximo, nivel)
        if chegada is None:
            return None
        return ChegadaChuva(
            chegada - atraso, maximo, movimento, self.horario + timedelta(minutes=chegada)
        )

    def fim_da_chuva(
        self,
        latitude: float,
        longitude: float,
        agora: datetime | None = None,
        horizonte: int = HORIZONTE_PREVISAO,
    ) -> FimChuva | None:
        """Em quantos minutos a partir de `agora` a chuva deve parar no ponto,
        com a mesma conta de `chegada_da_chuva`: o fim é o primeiro minuto
        seco seguido de pelo menos `SECO_MINIMO` minutos sem chuva (um vão
        entre duas manchas não conta). None sem movimento medido ou fora da
        imagem."""
        celula = self._celula(latitude, longitude)
        movimento = self.movimento
        if celula is None or movimento is None or self.horario is None:
            return None
        atraso = 0
        if agora is not None:
            atraso = max(0, round((agora - self.horario).total_seconds() / 60))
        coluna, linha = celula
        maximo = SEM_CHUVA
        seco_desde: int | None = None
        for minuto in range(atraso, atraso + horizonte + SECO_MINIMO + 1):
            nivel = self._nivel_celula(
                round(coluna - movimento.vx * minuto), round(linha - movimento.vy * minuto)
            )
            if nivel is None:
                # A chuva que vem depois ainda está fora da imagem.
                if seco_desde is not None:
                    break  # já tinha parado; o resto é incerto, mas ficou seco
                return FimChuva(None, maximo, movimento, None, chuva_de_fora=True)
            if nivel:
                seco_desde = None
                if minuto - atraso <= horizonte:
                    maximo = max(maximo, nivel)
                continue
            if seco_desde is None:
                if minuto - atraso > horizonte:
                    break  # ainda chovendo no fim do horizonte
                seco_desde = minuto
            if minuto - seco_desde >= SECO_MINIMO:
                break
        if seco_desde is None:
            return FimChuva(None, maximo, movimento, None)
        return FimChuva(
            seco_desde - atraso, maximo, movimento, self.horario + timedelta(minutes=seco_desde)
        )

    def _nivel_celula(self, coluna: int, linha: int) -> int | None:
        if not (0 <= coluna < self.colunas and 0 <= linha < self.linhas):
            return None
        x = _AREA[0] + (coluna + 0.5) * CELULA
        y = _AREA[1] + (linha + 0.5) * CELULA
        if _na_legenda(x, y):
            return None
        return self.celulas[linha * self.colunas + coluna]

    @cached_property
    def _indices_com_chuva(self) -> list[int]:
        return [indice for indice, nivel in enumerate(self.celulas) if nivel]

    def area_com_chuva(self) -> float:
        """Fração das células do mapa com chuva (0 a 1)."""
        return len(self._indices_com_chuva) / len(self.celulas) if self.celulas else 0.0

    @property
    def tem_chuva(self) -> bool:
        return bool(self._indices_com_chuva)

    def bloco_do_mapa(self, zoom: int, x: int, y: int) -> bytes:
        """Bloco de mapa (PNG de 256 x 256, no esquema {z}/{x}/{y} dos mapas
        web) só com a chuva, nas cores da legenda, e o resto transparente."""
        escala = TAMANHO_BLOCO * 2**zoom
        x0, y0, x1, y1 = _AREA
        lx0, ly0, lx1, ly1 = _LEGENDA

        # Longitude só depende da coluna do bloco, e latitude só da linha:
        # basta achar a célula de cada coluna e de cada linha uma vez.
        colunas: list[int] = []
        na_legenda_x: list[bool] = []
        for i in range(TAMANHO_BLOCO):
            longitude = (x * TAMANHO_BLOCO + i + 0.5) / escala * 360 - 180
            px = _X0 + (longitude - _LON0) * _PX_LON
            colunas.append(int((px - x0) // CELULA) if x0 <= px < x1 else -1)
            na_legenda_x.append(lx0 <= px <= lx1)
        if max(colunas) < 0:
            return BLOCO_VAZIO

        dados = bytearray(TAMANHO_BLOCO * TAMANHO_BLOCO)
        algo = False
        linhas_prontas: dict[tuple[int, bool], bytes] = {}
        for j in range(TAMANHO_BLOCO):
            n = math.pi * (1 - 2 * (y * TAMANHO_BLOCO + j + 0.5) / escala)
            latitude = math.degrees(math.atan(math.sinh(n)))
            py = _Y0 + (_LAT0 - latitude) * _PX_LAT
            if not y0 <= py < y1:
                continue
            linha = int((py - y0) // CELULA)
            legenda = ly0 <= py <= ly1
            pronta = linhas_prontas.get((linha, legenda))
            if pronta is None:
                inicio = linha * self.colunas
                celulas = self.celulas[inicio : inicio + self.colunas]
                pronta = bytes(
                    celulas[c] if c >= 0 and not (legenda and na_legenda_x[i]) else 0
                    for i, c in enumerate(colunas)
                )
                linhas_prontas[(linha, legenda)] = pronta
            if any(pronta):
                algo = True
                dados[j * TAMANHO_BLOCO : (j + 1) * TAMANHO_BLOCO] = pronta
        if not algo:
            return BLOCO_VAZIO
        return _png_do_bloco(bytes(dados))


# ---- Blocos de mapa ---------------------------------------------------------
TAMANHO_BLOCO = 256


def _png_do_bloco(dados: bytes) -> bytes:
    """PNG com paleta: índice = nível da chuva; 0 (sem chuva) é transparente."""
    imagem = Image.frombytes("P", (TAMANHO_BLOCO, TAMANHO_BLOCO), dados)
    paleta = [0, 0, 0]
    for nivel in (FRACA, MODERADA, FORTE, MUITO_FORTE):
        paleta += list(_CORES[nivel])
    imagem.putpalette(paleta)
    saida = io.BytesIO()
    imagem.save(saida, "PNG", transparency=0, optimize=True)
    return saida.getvalue()


BLOCO_VAZIO = _png_do_bloco(bytes(TAMANHO_BLOCO * TAMANHO_BLOCO))


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


def _glifos_do_titulo(imagem: Image.Image) -> list[Image.Image]:
    """Os caracteres do fim do título, recortados (separados por colunas sem
    pixel escuro)."""
    titulo = imagem.convert("L").crop(_TITULO)
    largura, altura = titulo.size
    pixels = titulo.load()
    escura = [any(pixels[x, y] < 140 for y in range(altura)) for x in range(largura)]
    glifos = []
    x = 0
    while x < largura:
        if not escura[x]:
            x += 1
            continue
        inicio = x
        while x < largura and escura[x]:
            x += 1
        caixa = titulo.crop((inicio, 0, x, altura))
        cp = caixa.load()
        linhas = [y for y in range(altura) if any(cp[i, y] < 140 for i in range(x - inicio))]
        glifos.append(caixa.crop((0, linhas[0], x - inicio, linhas[-1] + 1)))
    return glifos


def _assinatura(glifo: Image.Image) -> int:
    pixels = glifo.resize((8, 12), Image.Resampling.BILINEAR).load()
    bits = 0
    for y in range(12):
        for x in range(8):
            bits = bits << 1 | (pixels[x, y] < 128)
    return bits


def _digito(glifo: Image.Image) -> int | None:
    assinatura = _assinatura(glifo)
    distancia, digito = min(
        (bin(assinatura ^ modelo).count("1"), digito) for digito, modelo in _DIGITOS.items()
    )
    return digito if distancia <= _DISTANCIA_DIGITO else None


def ler_hora_do_titulo(imagem: Image.Image) -> tuple[int, int] | None:
    """(hora, minuto) do título "... HH:MM Local"; None se não deu para ler."""
    glifos = _glifos_do_titulo(imagem)
    # Do fim: "Local" (5 glifos), M2, M1, ":", H2, H1.
    if len(glifos) < 10:
        return None
    digitos = [_digito(glifos[i]) for i in (-10, -9, -7, -6)]
    if None in digitos:
        return None
    h1, h2, m1, m2 = digitos
    hora, minuto = h1 * 10 + h2, m1 * 10 + m2  # type: ignore[operator]
    if hora > 23 or minuto > 59:
        return None
    return hora, minuto


def horario_do_radar(
    hora_minuto: tuple[int, int] | None, publicada_em: datetime
) -> datetime | None:
    """A hora do título vira data e hora completas: o último HH:MM em São
    Paulo antes da publicação (o título não diz o fuso)."""
    if hora_minuto is None:
        return None
    if publicada_em.tzinfo is None:
        publicada_em = publicada_em.replace(tzinfo=timezone.utc)
    publicada = publicada_em.astimezone(FUSO_SP)
    horario = publicada.replace(
        hour=hora_minuto[0], minute=hora_minuto[1], second=0, microsecond=0
    )
    if horario > publicada + timedelta(minutes=5):
        horario -= timedelta(days=1)
    if publicada - horario > timedelta(hours=3):
        return None  # atrasada demais: melhor não confiar
    return horario.astimezone(timezone.utc)


def ler_radar(conteudo: bytes, obtida_em: datetime) -> LeituraRadar:
    """Lê a imagem do radar. Levanta RadarImagemInvalida se o conteúdo não é
    uma imagem inteira, e RadarLayoutError se o layout mudou.

    `obtida_em` é a hora de publicação (Last-Modified); a hora do radar, lida
    no título, fica em `horario`."""
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
    try:
        hora_minuto = ler_hora_do_titulo(imagem)
    except (IndexError, ValueError):
        hora_minuto = None
    horario = horario_do_radar(hora_minuto, obtida_em)
    return LeituraRadar(conteudo, obtida_em, celulas, colunas, linhas, quadro, horario)


# --------------------------------------------------------------------------- #
# Movimento
# --------------------------------------------------------------------------- #


def _grade(leitura: LeituraRadar) -> Image.Image:
    """As células como imagem em tons de cinza (mais forte = mais claro), um
    pouco borrada para a correlação variar suavemente."""
    valores = bytes(nivel * 60 for nivel in leitura.celulas)
    grade = Image.frombytes("L", (leitura.colunas, leitura.linhas), valores)
    return grade.filter(ImageFilter.BoxBlur(2))


def _correlacao_maxima(
    anterior: Image.Image,
    atual: Image.Image,
    janela: tuple[int, int, int, int],
    candidatos: list[tuple[int, int]],
) -> tuple[float, int, int] | None:
    """O deslocamento (dx, dy) que mais aproxima `anterior` de `atual` na
    janela, por correlação normalizada."""
    x0, y0, x1, y1 = janela
    alvo = atual.crop(janela)
    energia_alvo = ImageStat.Stat(ImageChops.multiply(alvo, alvo)).sum[0]
    if energia_alvo == 0:
        return None
    melhor: tuple[float, int, int] | None = None
    for dx, dy in candidatos:
        origem = anterior.crop((x0 - dx, y0 - dy, x1 - dx, y1 - dy))
        energia = ImageStat.Stat(ImageChops.multiply(origem, origem)).sum[0]
        if energia == 0:
            continue
        produto = ImageStat.Stat(ImageChops.multiply(origem, alvo)).sum[0]
        correlacao = produto / math.sqrt(energia * energia_alvo)
        if melhor is None or correlacao > melhor[0]:
            melhor = (correlacao, dx, dy)
    return melhor


def medir_movimento(anterior: LeituraRadar, atual: LeituraRadar) -> Movimento | None:
    """Velocidade da chuva entre duas leituras (com `horario`). None sem
    chuva, com intervalo fora de INTERVALO_MOVIMENTO ou correlação fraca."""
    if anterior.horario is None or atual.horario is None:
        return None
    intervalo = atual.horario - anterior.horario
    if not INTERVALO_MOVIMENTO[0] <= intervalo <= INTERVALO_MOVIMENTO[1]:
        return None
    if not (anterior.tem_chuva and atual.tem_chuva):
        return None
    minutos = intervalo.total_seconds() / 60
    alcance = math.ceil(
        _VELOCIDADE_MAXIMA_KMH / 60 * minutos / min(KM_CELULA_X, KM_CELULA_Y)
    )
    a, b = _grade(anterior), _grade(atual)
    margem = 10
    janela = (margem, margem, atual.colunas - margem, atual.linhas - margem)

    # Primeiro numa grade 3x mais grossa, depois refina em volta.
    f = _FATOR_GROSSO
    grossa_a = a.resize((a.width // f, a.height // f), Image.Resampling.BOX)
    grossa_b = b.resize((b.width // f, b.height // f), Image.Resampling.BOX)
    r = alcance // f + 1
    grosso = _correlacao_maxima(
        grossa_a,
        grossa_b,
        (janela[0] // f, janela[1] // f, janela[2] // f, janela[3] // f),
        [(dx, dy) for dy in range(-r, r + 1) for dx in range(-r, r + 1)],
    )
    if grosso is None:
        return None
    cx, cy = grosso[1] * f, grosso[2] * f
    fino = _correlacao_maxima(
        a, b, janela, [(cx + dx, cy + dy) for dy in range(-f, f + 1) for dx in range(-f, f + 1)]
    )
    if fino is None or fino[0] < _CONFIANCA_MINIMA:
        return None
    correlacao, dx, dy = fino
    return Movimento(dx / minutos, dy / minutos, round(correlacao, 3), minutos)


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
