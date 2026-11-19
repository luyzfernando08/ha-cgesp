"""Coleta de alertas da cidade no site do CGE: alagamentos por zona e estado das áreas monitoradas."""
from __future__ import annotations

import asyncio
import colorsys
import logging
import re
import struct
import unicodedata
import zlib
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING, Any

import requests
from bs4 import BeautifulSoup

from .const import (
    ESTADO_ALERTA,
    ESTADO_ATENCAO,
    ESTADO_IMINENCIA,
    ESTADO_OBSERVACAO,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

URL_ALAGAMENTOS = "https://www.cgesp.org/v3/alagamentos.jsp"
URL_MAPA_AREAS = "https://www.cgesp.org/v3/mapas.jsp?arq=alertas"
URL_MAPA_PNG = "https://www.cgesp.org/cgesp/mapa_sp_geoserver.png"

REQUEST_TIMEOUT = 60

_PNG_ASSINATURA = b"\x89PNG\r\n\x1a\n"
_STATUS_PONTO = {
    "ativo-transitavel": (True, True),
    "ativo-intransitavel": (True, False),
    "inativo-transitavel": (False, True),
    "inativo-intransitavel": (False, False),
}


class CgeAlertasError(Exception):
    """Raised when the CGE alert pages cannot be reached or parsed."""


@dataclass
class PontoAlagamento:
    zona: str
    bairro: str
    local: str
    inicio: str | None
    fim: str | None
    sentido: str | None
    referencia: str | None
    ativo: bool
    transitavel: bool
    # Preenchidos pela geocodificação (opcional); o CGE não publica coordenadas.
    latitude: float | None = None
    longitude: float | None = None
    precisao_localizacao: str | None = None

    @property
    def chave(self) -> str:
        """Identifica o ponto entre consultas (o CGE não tem id)."""
        return "|".join(
            (self.zona, normalizar(self.bairro), normalizar(self.local), self.inicio or "")
        )

    @property
    def localizado(self) -> bool:
        return self.latitude is not None and self.longitude is not None

    def como_atributo(self) -> dict:
        atributo = {
            "bairro": self.bairro,
            "local": self.local,
            "inicio": self.inicio,
            "sentido": self.sentido,
            "referencia": self.referencia,
            "transitavel": self.transitavel,
        }
        if self.localizado:
            atributo["latitude"] = self.latitude
            atributo["longitude"] = self.longitude
            atributo["precisao_localizacao"] = self.precisao_localizacao
        return atributo


@dataclass
class AreaMapa:
    nome: str
    x: int
    y: int
    raio: int


@dataclass
class ResultadoAlagamentos:
    data_referencia: str | None
    pontos: dict[str, list[PontoAlagamento]]
    avisos: list[str] = field(default_factory=list)


@dataclass
class ResultadoMapa:
    estados: dict[str, str]
    horario: datetime | None
    avisos: list[str] = field(default_factory=list)
    png: bytes | None = None


@dataclass
class CgeAlertasData:
    """Dados de uma consulta. Uma parte que falhou fica None (não "vazia")."""

    data_referencia: str | None = None
    alagamentos: dict[str, list[PontoAlagamento]] | None = None
    estados_areas: dict[str, str] | None = None
    mapa_atualizado_em: datetime | None = None
    # Imagem do mapa de alertas, servida pela câmera "Mapa de alertas".
    mapa_png: bytes | None = None
    # Preenchidos pelo coordinator (cge_extras); None quando indisponíveis.
    boletim: Any = None
    periodos_previsao: list[Any] | None = None

    @property
    def alagamentos_disponiveis(self) -> bool:
        return self.alagamentos is not None

    @property
    def mapa_disponivel(self) -> bool:
        return self.estados_areas is not None

    def pontos_da_zona(self, zona: str) -> list[PontoAlagamento]:
        return (self.alagamentos or {}).get(zona, [])

    def pontos_ativos(self) -> list[PontoAlagamento]:
        return [p for pontos in (self.alagamentos or {}).values() for p in pontos if p.ativo]

    def estado_da_area(self, area: str) -> str | None:
        return (self.estados_areas or {}).get(normalizar(area))


def normalizar(texto: str) -> str:
    """Minúsculas, sem acentos e com espaços simples — para comparar nomes do site."""
    sem_acento = "".join(
        c
        for c in unicodedata.normalize("NFKD", texto)
        if not unicodedata.combining(c)
    )
    return re.sub(r"\s+", " ", sem_acento).strip().lower()


def _decodificar_texto(conteudo: bytes) -> str:
    # O alagamentos.jsp declara UTF-8 mas entrega Latin-1; o mapa entrega UTF-8.
    try:
        return conteudo.decode("utf-8")
    except UnicodeDecodeError:
        return conteudo.decode("latin-1")


# --------------------------------------------------------------------------- #
# Alagamentos
# --------------------------------------------------------------------------- #


def _zona_do_titulo(titulo: str) -> str:
    return normalizar(re.sub(r"(?i)^\s*zona\s+", "", titulo))


def _linhas(tag) -> list[str]:
    if tag is None:
        return []
    return [linha.strip() for linha in tag.get_text("\n").split("\n") if linha.strip()]


def _valor_rotulado(linhas: list[str], rotulo: str) -> str | None:
    for linha in linhas:
        if normalizar(linha).startswith(rotulo):
            valor = linha.split(":", 1)[1].strip() if ":" in linha else ""
            return valor or None
    return None


def _parse_ponto(div, zona: str, bairro: str) -> PontoAlagamento | None:
    """Retorna None quando o status (ativo/inativo) não é reconhecido."""
    status = None
    for li in div.select("li"):
        for classe in li.get("class", []):
            if classe in _STATUS_PONTO:
                status = _STATUS_PONTO[classe]
    if status is None:
        return None

    local_linhas = _linhas(div.select_one("li.col-local"))
    inicio = fim = None
    local = ""
    if local_linhas:
        horario = re.search(
            r"De\s*(\d{1,2}:\d{2})\s*a\s*(\d{1,2}:\d{2})?", local_linhas[0]
        )
        if horario:
            inicio, fim = horario.group(1), horario.group(2)
            local = " ".join(local_linhas[1:])
        else:
            local = " ".join(local_linhas)

    descricao = next(
        (
            li
            for li in div.select("li.arial-descr-alag")
            if "col-local" not in li.get("class", [])
        ),
        None,
    )
    descricao_linhas = _linhas(descricao)

    ativo, transitavel = status
    return PontoAlagamento(
        zona=zona,
        bairro=bairro,
        local=local,
        inicio=inicio,
        fim=fim,
        sentido=_valor_rotulado(descricao_linhas, "sentido"),
        referencia=_valor_rotulado(descricao_linhas, "referencia"),
        ativo=ativo,
        transitavel=transitavel,
    )


_SEM_REGISTROS = "nao ha registros de alagamentos"


def _parse_alagamentos(html: str) -> ResultadoAlagamentos:
    """Lê os pontos de alagamento agrupados por zona.

    Uma página sem zonas só é aceita como "sem alagamentos" se trouxer a
    mensagem do CGE para isso; caso contrário o layout mudou e é erro — assim
    os sensores ficam indisponíveis em vez de indicar, falsamente, que não
    há alagamento.
    """
    soup = BeautifulSoup(html, "html.parser")

    campo_data = soup.select_one("input[name=dataBusca]")
    data_referencia = campo_data.get("value") if campo_data else None

    titulos = soup.select("h1.tit-bairros")
    if not titulos:
        if _SEM_REGISTROS in normalizar(soup.get_text(" ")):
            return ResultadoAlagamentos(data_referencia, {})
        raise CgeAlertasError(
            "Layout da página de alagamentos do CGE não reconhecido: "
            "não há zonas nem a mensagem de 'sem registros'"
        )

    alagamentos: dict[str, list[PontoAlagamento]] = {}
    avisos: list[str] = []
    blocos = 0
    zona: str | None = None
    for elemento in soup.find_all(["h1", "table"]):
        classes = elemento.get("class", [])
        if elemento.name == "h1" and "tit-bairros" in classes:
            zona = _zona_do_titulo(elemento.get_text())
            alagamentos.setdefault(zona, [])
            continue
        if elemento.name != "table" or "tb-pontos-de-alagamentos" not in classes:
            continue
        if zona is None:
            continue

        bairro_td = elemento.select_one("td.bairro")
        bairro = bairro_td.get_text(" ", strip=True) if bairro_td else ""
        for div in elemento.select("div.ponto-de-alagamento"):
            blocos += 1
            ponto = _parse_ponto(div, zona, bairro)
            if ponto is None:
                local = " ".join(_linhas(div.select_one("li.col-local")))
                avisos.append(
                    f"Ponto de alagamento com status não reconhecido ignorado: "
                    f"{zona} / {bairro} / {local}"
                )
                continue
            alagamentos[zona].append(ponto)

    if blocos == 0 or blocos == len(avisos):
        raise CgeAlertasError(
            "Layout da página de alagamentos do CGE não reconhecido: "
            f"{len(titulos)} zona(s) listadas, mas nenhum ponto pôde ser lido"
        )

    return ResultadoAlagamentos(data_referencia, alagamentos, avisos)


# --------------------------------------------------------------------------- #
# Mapa de situação das áreas monitoradas (PNG)
# --------------------------------------------------------------------------- #


def _parse_areas_mapa(html: str) -> list[AreaMapa]:
    soup = BeautifulSoup(html, "html.parser")
    areas = []
    for area in soup.select("map area"):
        titulo = area.get("title")
        coords = [c.strip() for c in (area.get("coords") or "").split(",")]
        if not titulo or len(coords) != 3:
            continue
        x, y, raio = (int(c) for c in coords)
        areas.append(AreaMapa(nome=titulo.strip(), x=x, y=y, raio=raio))
    return areas


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


@dataclass
class _ImagemPng:
    largura: int
    altura: int
    canais: int
    linhas: list[bytes]
    horario: datetime | None

    def rgb(self, x: int, y: int) -> tuple[int, int, int]:
        inicio = x * self.canais
        r, g, b = self.linhas[y][inicio : inicio + 3]
        return r, g, b


def _decodificar_png(conteudo: bytes) -> _ImagemPng:
    """Decodifica PNG RGB/RGBA de 8 bits não entrelaçado (formato usado pelo CGE).

    Feito à mão para não depender do Pillow.
    """
    if not conteudo.startswith(_PNG_ASSINATURA):
        raise ValueError("Conteúdo não é um PNG")

    pos = len(_PNG_ASSINATURA)
    idat = bytearray()
    cabecalho = None
    horario = None
    while pos + 8 <= len(conteudo):
        (tamanho,) = struct.unpack(">I", conteudo[pos : pos + 4])
        tipo = conteudo[pos + 4 : pos + 8]
        dados = conteudo[pos + 8 : pos + 8 + tamanho]
        if tipo == b"IHDR":
            cabecalho = struct.unpack(">IIBBBBB", dados)
        elif tipo == b"IDAT":
            idat.extend(dados)
        elif tipo == b"tIME" and len(dados) == 7:
            ano, mes, dia, hora, minuto, segundo = struct.unpack(">HBBBBB", dados)
            horario = datetime(ano, mes, dia, hora, minuto, segundo, tzinfo=timezone.utc)
        elif tipo == b"IEND":
            break
        pos += 12 + tamanho

    if cabecalho is None:
        raise ValueError("PNG sem cabeçalho IHDR")
    largura, altura, profundidade, tipo_cor, _, _, entrelacado = cabecalho
    canais = {2: 3, 6: 4}.get(tipo_cor)
    if profundidade != 8 or canais is None or entrelacado:
        raise ValueError(
            f"Formato de PNG não suportado (bits={profundidade}, cor={tipo_cor}, entrelaçado={entrelacado})"
        )

    bruto = zlib.decompress(bytes(idat))
    passo = largura * canais
    linhas: list[bytes] = []
    anterior = bytearray(passo)
    p = 0
    for _ in range(altura):
        filtro = bruto[p]
        linha = bytearray(bruto[p + 1 : p + 1 + passo])
        p += 1 + passo
        for i in range(passo):
            a = linha[i - canais] if i >= canais else 0
            b = anterior[i]
            if filtro == 1:
                linha[i] = (linha[i] + a) & 0xFF
            elif filtro == 2:
                linha[i] = (linha[i] + b) & 0xFF
            elif filtro == 3:
                linha[i] = (linha[i] + ((a + b) >> 1)) & 0xFF
            elif filtro == 4:
                c = anterior[i - canais] if i >= canais else 0
                linha[i] = (linha[i] + _paeth(a, b, c)) & 0xFF
            elif filtro != 0:
                raise ValueError(f"Filtro PNG inválido: {filtro}")
        linhas.append(bytes(linha))
        anterior = linha

    return _ImagemPng(largura, altura, canais, linhas, horario)


def _classificar_cor(r: int, g: int, b: int) -> str | None:
    """Converte a cor de preenchimento da área no estado da legenda do mapa.

    Legenda do CGE: cinza = Observação, amarelo = Atenção,
    laranja = Iminência de transbordamento, vermelho = Alerta.

    As áreas são pintadas com transparência sobre o branco (o amarelo puro
    da legenda aparece como (255, 255, 102) no mapa), por isso a cor é
    classificada pelo matiz, que não muda com a transparência.
    Pixels escuros (texto, bordas) e de outras cores retornam None.
    """
    maior, menor = max(r, g, b), min(r, g, b)
    if maior - menor <= 20:
        return ESTADO_OBSERVACAO if menor >= 150 else None
    if maior < 150 or maior - menor < 60:
        return None

    # Matizes medidos em mapas reais: vermelho 0°, laranja 39°, amarelo 60°.
    # Limites nos pontos médios entre eles.
    matiz = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)[0] * 360
    if matiz >= 345 or matiz < 18:
        return ESTADO_ALERTA
    if matiz < 50:
        return ESTADO_IMINENCIA
    if matiz < 75:
        return ESTADO_ATENCAO
    return None


def _estado_na_area(imagem: _ImagemPng, area: AreaMapa) -> str | None:
    contagem: Counter[str] = Counter()
    raio2 = area.raio * area.raio
    for y in range(max(0, area.y - area.raio), min(imagem.altura, area.y + area.raio + 1)):
        for x in range(max(0, area.x - area.raio), min(imagem.largura, area.x + area.raio + 1)):
            if (x - area.x) ** 2 + (y - area.y) ** 2 > raio2:
                continue
            estado = _classificar_cor(*imagem.rgb(x, y))
            if estado is not None:
                contagem[estado] += 1
    if not contagem:
        return None
    return contagem.most_common(1)[0][0]


def _parse_estados_areas(png: bytes, areas: list[AreaMapa]) -> ResultadoMapa:
    imagem = _decodificar_png(png)
    estados: dict[str, str] = {}
    avisos: list[str] = []
    for area in areas:
        estado = _estado_na_area(imagem, area)
        if estado is None:
            avisos.append(
                f"Cor da área {area.nome} não reconhecida no mapa de alertas do CGE"
            )
            continue
        estados[normalizar(area.nome)] = estado

    if areas and not estados:
        raise CgeAlertasError(
            "Nenhuma área do mapa de alertas do CGE tem cor reconhecida; "
            "o mapa provavelmente mudou"
        )
    return ResultadoMapa(estados, imagem.horario, avisos)


# --------------------------------------------------------------------------- #
# Coleta
# --------------------------------------------------------------------------- #


def _horario_do_header(valor: str | None) -> datetime | None:
    if not valor:
        return None
    try:
        return parsedate_to_datetime(valor)
    except (TypeError, ValueError):
        return None


PARTE_ALAGAMENTOS = "alagamentos"
PARTE_MAPA = "mapa de alertas"
PARTES = (PARTE_ALAGAMENTOS, PARTE_MAPA)

_ERROS_DE_LEITURA = (
    AttributeError,
    IndexError,
    KeyError,
    TypeError,
    ValueError,
    zlib.error,
    struct.error,
)


def _buscar(url: str) -> requests.Response:
    response = requests.get(url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response


def _ler_alagamentos(resposta: requests.Response) -> ResultadoAlagamentos:
    return _parse_alagamentos(_decodificar_texto(resposta.content))


def _ler_mapa(
    resposta_areas: requests.Response, resposta_png: requests.Response
) -> ResultadoMapa:
    areas = _parse_areas_mapa(_decodificar_texto(resposta_areas.content))
    if not areas:
        raise CgeAlertasError("Nenhuma área encontrada no mapa de alertas do CGE")
    resultado = _parse_estados_areas(resposta_png.content, areas)
    if resultado.horario is None:
        resultado.horario = _horario_do_header(resposta_png.headers.get("Last-Modified"))
    resultado.png = resposta_png.content
    return resultado


class CgeAlertas:
    """Busca alagamentos e mapa de forma independente.

    Se só uma das partes falhar, a outra continua disponível; só é erro
    quando as duas falham. Falhas parciais e avisos de leitura são logados
    uma vez (e de novo apenas depois de se resolverem e voltarem).
    """

    def __init__(self, hass: "HomeAssistant") -> None:
        self.hass = hass
        self._partes_com_falha: set[str] = set()
        self._avisos_ativos: set[str] = set()
        # Partes cujo layout não pôde ser lido (parte -> erro). Falhas de
        # conexão não mexem aqui: com o site fora do ar não dá para saber se
        # o layout continua quebrado ou não.
        self.layout_quebrado: dict[str, str] = {}

    async def _obter_alagamentos(self) -> ResultadoAlagamentos:
        resposta = await self.hass.async_add_executor_job(_buscar, URL_ALAGAMENTOS)
        return await self.hass.async_add_executor_job(_ler_alagamentos, resposta)

    async def _obter_mapa(self) -> ResultadoMapa:
        resposta_areas, resposta_png = await asyncio.gather(
            self.hass.async_add_executor_job(_buscar, URL_MAPA_AREAS),
            self.hass.async_add_executor_job(_buscar, URL_MAPA_PNG),
        )
        return await self.hass.async_add_executor_job(
            _ler_mapa, resposta_areas, resposta_png
        )

    async def _tentar(self, parte: str, obter) -> tuple[object | None, str | None]:
        try:
            valor = await obter()
        except requests.exceptions.RequestException as err:
            return None, f"{parte}: erro ao conectar ao site do CGE: {err}"
        except CgeAlertasError as err:
            self.layout_quebrado[parte] = str(err)
            return None, f"{parte}: {err}"
        except _ERROS_DE_LEITURA as err:
            erro = f"erro ao interpretar os dados do CGE: {err!r}"
            self.layout_quebrado[parte] = erro
            return None, f"{parte}: {erro}"
        self.layout_quebrado.pop(parte, None)
        return valor, None

    def _registrar_parte(self, parte: str, erro: str | None, logar: bool) -> None:
        if erro is None:
            if parte in self._partes_com_falha:
                self._partes_com_falha.discard(parte)
                _LOGGER.info("CGE: %s voltou a funcionar", parte)
            return
        if logar and parte not in self._partes_com_falha:
            _LOGGER.warning("CGE: falha ao obter %s; sensores dependentes ficarão indisponíveis", erro)
        self._partes_com_falha.add(parte)

    def _registrar_avisos(self, avisos: list[str]) -> None:
        for aviso in avisos:
            if aviso not in self._avisos_ativos:
                _LOGGER.warning("CGE: %s", aviso)
        self._avisos_ativos = set(avisos)

    async def get(self) -> CgeAlertasData:
        (alagamentos, erro_alag), (mapa, erro_mapa) = await asyncio.gather(
            self._tentar(PARTE_ALAGAMENTOS, self._obter_alagamentos),
            self._tentar(PARTE_MAPA, self._obter_mapa),
        )

        if erro_alag and erro_mapa:
            # Falha total: o coordinator loga e marca tudo indisponível.
            self._registrar_parte(PARTE_ALAGAMENTOS, erro_alag, logar=False)
            self._registrar_parte(PARTE_MAPA, erro_mapa, logar=False)
            raise CgeAlertasError(f"{erro_alag} | {erro_mapa}")

        self._registrar_parte(PARTE_ALAGAMENTOS, erro_alag, logar=True)
        self._registrar_parte(PARTE_MAPA, erro_mapa, logar=True)

        avisos: list[str] = []
        dados = CgeAlertasData()
        if isinstance(alagamentos, ResultadoAlagamentos):
            dados.data_referencia = alagamentos.data_referencia
            dados.alagamentos = alagamentos.pontos
            avisos.extend(alagamentos.avisos)
        if isinstance(mapa, ResultadoMapa):
            dados.estados_areas = mapa.estados
            dados.mapa_atualizado_em = mapa.horario
            dados.mapa_png = mapa.png
            avisos.extend(mapa.avisos)
        self._registrar_avisos(avisos)
        return dados
