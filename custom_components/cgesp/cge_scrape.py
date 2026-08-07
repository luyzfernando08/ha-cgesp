from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime
from typing import TYPE_CHECKING

import requests
from bs4 import BeautifulSoup

from .cge_data import CgeData
from .cge_data_forecast import CgeForecastData

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

TEMPERATURA: str = "Temperatura"
UMIDADE: str = "Umidade"
VENTO: str = "Vento"
PRESSAO: str = "Pressão"

REQUEST_TIMEOUT = 60


class CgeScrapeError(Exception):
    """Raised when the CGE website cannot be reached or parsed."""


def _texto_para_numero(texto: str) -> float:
    valor = re.search(r"\d+\.\d+", texto)
    if valor is None:
        valor = re.search(r"\d+", texto)

    return float(valor.group())


def _pega_informacao(soup: BeautifulSoup, index_coluna: int, linha: int = 1):
    return _texto_para_numero(
        soup.select_one("table")
        .select("table")[index_coluna]
        .select_one(f"tr:nth-child({linha})")
        .text
    )


def _pega_periodo_dia(agora: datetime | None = None) -> str:
    agora = agora or datetime.now()
    if 0 <= agora.hour < 6:
        return ".prev-madrug"
    if 6 <= agora.hour < 12:
        return ".prev-manha"
    if 12 <= agora.hour < 18:
        return ".prev-tarde"
    return ".prev-noite"


def _de_para_ceu(ceu: str) -> str | None:
    if ceu == "Céu claro":
        return "sunny"
    if ceu == "Poucas nuvens":
        return "partlycloudy"
    if ceu in (
        "Chuva",
        "Nublado com chuva",
        "Chuvisco",
        "Pancadas isoladas",
        "Pancadas de chuva",
    ):
        return "rainy"
    if ceu in ("Nublado", "Encoberto"):
        return "cloudy"

    _LOGGER.warning("Condição de céu desconhecida recebida do CGE: %s", ceu)
    return None


def _parse_estacao(html: str) -> CgeData:
    soup = BeautifulSoup(html, "html.parser")

    colunas = [TEMPERATURA, UMIDADE, VENTO, PRESSAO]

    index_por_coluna = {}
    for index, item in enumerate(soup.select("table tr th")):
        for coluna in colunas:
            if item.text == coluna:
                index_por_coluna[coluna] = index

    estacao = CgeData()

    if TEMPERATURA in index_por_coluna:
        estacao.temperatura = _pega_informacao(soup, index_por_coluna[TEMPERATURA])
    if UMIDADE in index_por_coluna:
        estacao.umidade = _pega_informacao(soup, index_por_coluna[UMIDADE])
    if VENTO in index_por_coluna:
        estacao.vento = _pega_informacao(soup, index_por_coluna[VENTO], 3)
    if PRESSAO in index_por_coluna:
        estacao.pressaoDoAr = _pega_informacao(soup, index_por_coluna[PRESSAO])

    return estacao


def _parse_previsao(
    html: str, agora: datetime | None = None
) -> list[CgeForecastData]:
    soup = BeautifulSoup(html, "html.parser")
    periodo_dia = _pega_periodo_dia(agora)

    forecasts = []
    for tabela in soup.select(".col-previsao-simples"):
        forecast = CgeForecastData()
        for coluna in tabela.select(".data-prev"):
            dia = coluna.text.replace("\n", "").strip()
            dia = dia[:5] + "/" + dia[5:]
            forecast.datetime = datetime.strptime(dia, "%d/%m/%Y")

        forecast.temperaturaMaxima = _texto_para_numero(
            tabela.select_one(".temp-max").text
        )
        forecast.temperaturaMinima = _texto_para_numero(
            tabela.select_one(".temp-min").text
        )
        forecast.umidade = _texto_para_numero(tabela.select_one(".umid-min").text)
        forecast.condicaoTempo = _de_para_ceu(
            tabela.select_one(periodo_dia).select_one(".cond-tempo").find("h2").text.strip()
        )

        forecasts.append(forecast)

    return forecasts


class CgeScrape:
    def __init__(self, hass: "HomeAssistant", estacao_id: int) -> None:
        self.hass = hass
        self.estacao_id = estacao_id

    def _buscar_estacao_html(self) -> str:
        url = f"https://www.cgesp.org/v3/estacao.jsp?POSTO={self.estacao_id}"
        response = requests.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.text

    def _buscar_previsao_html(self) -> str:
        url = "https://www.cgesp.org/v3/previsao_estendida.jsp"
        response = requests.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.text

    def _parse(self, estacao_html: str, previsao_html: str) -> CgeData:
        estacao = _parse_estacao(estacao_html)
        forecasts = _parse_previsao(previsao_html)

        if not forecasts:
            raise CgeScrapeError(
                "Não foi possível obter a previsão estendida do CGE"
            )

        estacao.forecast = forecasts
        estacao.condicaoTempo = forecasts[0].condicaoTempo
        return estacao

    async def get(self) -> CgeData:
        try:
            estacao_html, previsao_html = await asyncio.gather(
                self.hass.async_add_executor_job(self._buscar_estacao_html),
                self.hass.async_add_executor_job(self._buscar_previsao_html),
            )
            return await self.hass.async_add_executor_job(
                self._parse, estacao_html, previsao_html
            )
        except requests.exceptions.RequestException as err:
            raise CgeScrapeError(f"Erro ao conectar ao site do CGE: {err}") from err
        except (AttributeError, IndexError, TypeError, ValueError) as err:
            raise CgeScrapeError(f"Erro ao interpretar os dados do CGE: {err}") from err
