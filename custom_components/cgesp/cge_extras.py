"""Partes complementares dos alertas, sem dependência do Home Assistant.

- Previsão por período (madrugada, manhã, tarde, noite) para decidir o
  intervalo de atualização: 10 min quando pode chover, 30 min quando não.
- Último boletim do CGE (feed RSS de notícias).
- Distância entre coordenadas e pontos de alagamento próximos.
- Diferença entre duas leituras (pontos novos e encerrados), para os eventos.
"""
from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from bs4 import BeautifulSoup

from .cge_alertas import (
    CgeAlertasData,
    CgeAlertasError,
    PontoAlagamento,
    _decodificar_texto,
    normalizar,
)

URL_PREVISAO = "https://www.cgesp.org/v3/previsao_estendida.jsp"
URL_BOLETIM = "https://www.cgesp.org/v3/feed_rss.jsp"
URL_NOTICIAS = "https://www.cgesp.org/v3/"

INTERVALO_COM_CHUVA = timedelta(minutes=10)
INTERVALO_SEM_CHUVA = timedelta(minutes=30)
JANELA_PREVISAO = timedelta(hours=12)

# --------------------------------------------------------------------------- #
# Previsão por período
# --------------------------------------------------------------------------- #

# Classe do bloco no site -> (nome, hora de início, hora de fim)
_PERIODOS = {
    "prev-madrug": ("madrugada", 0, 6),
    "prev-manha": ("manha", 6, 12),
    "prev-tarde": ("tarde", 12, 18),
    "prev-noite": ("noite", 18, 24),
}
_PALAVRAS_CHUVA = ("chuv", "garoa", "pancada", "temporal", "tempestade", "trovoada")
# "PT" no site: potencial para temporais.
_POTENCIAL_RELEVANTE = ("moderado", "alto", "muito alto", "elevado")


@dataclass
class PeriodoPrevisao:
    inicio: datetime
    fim: datetime
    periodo: str
    condicao: str
    potencial_temporais: str | None

    @property
    def pode_chover(self) -> bool:
        condicao = normalizar(self.condicao)
        if any(palavra in condicao for palavra in _PALAVRAS_CHUVA):
            return True
        return normalizar(self.potencial_temporais or "") in _POTENCIAL_RELEVANTE

    def como_atributo(self) -> dict:
        return {
            "inicio": self.inicio.isoformat(),
            "periodo": self.periodo,
            "condicao": self.condicao,
            "potencial_temporais": self.potencial_temporais,
        }


def _dia_da_coluna(coluna) -> date:
    texto = re.sub(r"\s+", "", coluna.select_one(".data-prev").get_text())
    encontrado = re.search(r"(\d{2})/(\d{2})/?(\d{4})", texto)
    if encontrado is None:
        raise CgeAlertasError(f"Data da previsão não reconhecida: {texto!r}")
    dia, mes, ano = (int(g) for g in encontrado.groups())
    return date(ano, mes, dia)


def parse_periodos(html: str) -> list[PeriodoPrevisao]:
    soup = BeautifulSoup(html, "html.parser")
    periodos: list[PeriodoPrevisao] = []
    for coluna in soup.select(".col-previsao-simples"):
        dia = _dia_da_coluna(coluna)
        for classe, (nome, hora_inicio, hora_fim) in _PERIODOS.items():
            bloco = coluna.select_one(f".{classe} .cond-tempo")
            if bloco is None:
                continue
            textos = [h2.get_text(" ", strip=True) for h2 in bloco.find_all("h2")]
            condicao = textos[0] if textos else ""
            potencial = None
            for texto in textos[1:]:
                if normalizar(texto).startswith("pt"):
                    potencial = texto.split(":", 1)[-1].strip() or None
            inicio = datetime.combine(dia, datetime.min.time()) + timedelta(hours=hora_inicio)
            periodos.append(
                PeriodoPrevisao(
                    inicio=inicio,
                    fim=inicio + timedelta(hours=hora_fim - hora_inicio),
                    periodo=nome,
                    condicao=condicao,
                    potencial_temporais=potencial,
                )
            )
    if not periodos:
        raise CgeAlertasError("Nenhum período encontrado na previsão do CGE")
    return periodos


def periodos_na_janela(
    periodos: list[PeriodoPrevisao], agora: datetime, janela: timedelta = JANELA_PREVISAO
) -> list[PeriodoPrevisao]:
    """Períodos que se sobrepõem a [agora, agora + janela] (horário local, sem fuso)."""
    limite = agora + janela
    return [p for p in periodos if p.fim > agora and p.inicio < limite]


def chuva_prevista(
    periodos: list[PeriodoPrevisao] | None, agora: datetime
) -> bool | None:
    """True/False pela previsão das próximas horas; None se não há previsão
    para o horário (site fora do ar ou previsão desatualizada)."""
    if not periodos:
        return None
    proximos = periodos_na_janela(periodos, agora)
    if not proximos:
        return None
    return any(p.pode_chover for p in proximos)


def escolher_intervalo(
    dados: CgeAlertasData | None,
    periodos: list[PeriodoPrevisao] | None,
    agora: datetime,
) -> tuple[timedelta, str]:
    """Intervalo da próxima atualização e o motivo (vai para os diagnósticos).

    Na dúvida (falta de dados), fica no intervalo curto.
    """
    if dados is None:
        return INTERVALO_COM_CHUVA, "sem dados do CGE"
    if dados.pontos_ativos():
        return INTERVALO_COM_CHUVA, "há alagamentos ativos"
    if any(estado != "observacao" for estado in (dados.estados_areas or {}).values()):
        return INTERVALO_COM_CHUVA, "há região em atenção ou alerta"
    if not dados.alagamentos_disponiveis or not dados.mapa_disponivel:
        return INTERVALO_COM_CHUVA, "parte do site indisponível"
    prevista = chuva_prevista(periodos, agora)
    if prevista is None:
        return INTERVALO_COM_CHUVA, "previsão indisponível"
    if prevista:
        return INTERVALO_COM_CHUVA, "chuva prevista nas próximas horas"
    return INTERVALO_SEM_CHUVA, "sem chuva prevista nas próximas horas"


# --------------------------------------------------------------------------- #
# Boletim (RSS de notícias)
# --------------------------------------------------------------------------- #

_MESES = {
    "jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6,
    "jul": 7, "ago": 8, "set": 9, "out": 10, "nov": 11, "dez": 12,
}
_DATA_RSS = re.compile(r"(\d{1,2})\s+([a-zç]{3})[a-z]*\s+(\d{4})\s+(\d{1,2}):(\d{2})(?::(\d{2}))?")


@dataclass
class Boletim:
    id: str | None
    titulo: str
    texto: str
    publicado_em: datetime | None  # horário local de São Paulo, sem fuso
    link: str | None


def _data_rss(texto: str | None) -> datetime | None:
    """'Qua, 18 nov 2026 23:58:21 GMT' -> datetime(2026, 11, 18, 23, 58, 21).

    Apesar do "GMT", o horário publicado é o de São Paulo (os boletins
    "de madrugada" saem perto da meia-noite).
    """
    encontrado = _DATA_RSS.search(normalizar(texto or ""))
    if encontrado is None:
        return None
    dia, mes, ano, hora, minuto, segundo = encontrado.groups()
    numero_mes = _MESES.get(mes[:3])
    if numero_mes is None:
        return None
    try:
        return datetime(int(ano), numero_mes, int(dia), int(hora), int(minuto), int(segundo or 0))
    except ValueError:
        return None


def _texto_simples(html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    paragrafos = [
        re.sub(r"\s+", " ", p.get_text(" ")).strip() for p in soup.find_all("p")
    ] or [re.sub(r"\s+", " ", soup.get_text(" ")).strip()]
    return "\n\n".join(p for p in paragrafos if p)


def parse_boletim(conteudo: bytes) -> Boletim:
    """Primeira notícia do feed (a mais recente)."""
    try:
        raiz = ET.fromstring(_decodificar_texto(conteudo).lstrip("﻿").strip())
    except ET.ParseError as err:
        raise CgeAlertasError(f"Feed de notícias do CGE inválido: {err}") from err
    item = raiz.find("./channel/item")
    if item is None:
        raise CgeAlertasError("Nenhuma notícia no feed do CGE")
    titulo = (item.findtext("title") or "").strip()
    if not titulo:
        raise CgeAlertasError("Notícia do CGE sem título")
    link = (item.findtext("link") or "").strip() or None
    if link and not link.startswith("http"):
        link = URL_NOTICIAS + link.lstrip("/")
    return Boletim(
        id=(item.findtext("guid") or "").strip() or None,
        titulo=titulo,
        texto=_texto_simples(item.findtext("description") or ""),
        publicado_em=_data_rss(item.findtext("pubDate")),
        link=link,
    )


# --------------------------------------------------------------------------- #
# Distância
# --------------------------------------------------------------------------- #

_RAIO_TERRA_KM = 6371.0088


def distancia_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distância em linha reta (haversine)."""
    f1, f2 = math.radians(lat1), math.radians(lat2)
    df = f2 - f1
    dl = math.radians(lon2 - lon1)
    a = math.sin(df / 2) ** 2 + math.cos(f1) * math.cos(f2) * math.sin(dl / 2) ** 2
    return 2 * _RAIO_TERRA_KM * math.asin(math.sqrt(a))


def pontos_proximos(
    latitude: float, longitude: float, pontos: list[PontoAlagamento], raio_km: float
) -> list[tuple[PontoAlagamento, float]]:
    """Pontos localizados dentro do raio, do mais perto ao mais longe."""
    proximos = []
    for ponto in pontos:
        if not ponto.localizado:
            continue
        km = distancia_km(latitude, longitude, ponto.latitude, ponto.longitude)  # type: ignore[arg-type]
        if km <= raio_km:
            proximos.append((ponto, km))
    return sorted(proximos, key=lambda item: item[1])


# --------------------------------------------------------------------------- #
# Eventos
# --------------------------------------------------------------------------- #


def diferenca_pontos(
    anteriores: dict[str, PontoAlagamento], atuais: dict[str, PontoAlagamento]
) -> tuple[list[PontoAlagamento], list[PontoAlagamento]]:
    """(novos, encerrados) entre duas leituras dos pontos ativos."""
    novos = [p for chave, p in atuais.items() if chave not in anteriores]
    encerrados = [p for chave, p in anteriores.items() if chave not in atuais]
    return novos, encerrados
