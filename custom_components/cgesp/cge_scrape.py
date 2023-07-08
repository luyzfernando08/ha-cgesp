from __future__ import annotations
from ast import List

import requests
from bs4 import BeautifulSoup
import re
import logging
from datetime import datetime
from .cge_data import CgeData
from .cge_data_forecast import CgeForecastData

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


def __texto_para_numero__(texto: str) -> int:
    valor = re.search(r"\d+\.\d+", texto)
    if valor is None:
        valor = re.search(r"\d+", texto)

    return float(valor.group())


def __pega_informacao__(soup: BeautifulSoup, indexColuna: int, linha: int = 1):
    return __texto_para_numero__(
        soup.select_one("table")
        .select("table")[indexColuna]
        .select_one(f"tr:nth-child({linha})")
        .text
    )


def __pega_periodo_dia__() -> str:
    agora = datetime.now()
    if agora.hour >= 0 and agora.hour < 6:
        return ".prev-madrug"
    elif agora.hour >= 6 and agora.hour < 12:
        return ".prev-manha"
    elif agora.hour >= 12 and agora.hour < 18:
        return ".prev-tarde"
    elif agora.hour >= 18 and agora.hour <= 23:
        return ".prev-noite"


def __de_para_ceu__(ceu: str):
    if ceu == "Céu claro":
        return "sunny"
    elif ceu == "Poucas nuvens":
        return "partlycloudy"
    elif ceu == "Chuvisco":
        return "pouring"
    elif ceu == "Nublado com chuva":
        return "rainy"


class CgeScrape:
    def __init__(self, hass: HomeAssistant, estacaoId: int) -> None:
        self.hass = hass
        self.estacaoId = estacaoId

    async def get(self) -> CgeData:
        def get():
            _LOGGER.warning(f"Pesquisando estação {self.estacaoId}")
            url = f"https://www.cgesp.org/v3/estacao.jsp?POSTO={self.estacaoId}"

            response = requests.get(url, timeout=60000)

            soup = BeautifulSoup(response.text, "html.parser")

            estacao = CgeData()

            estacao.temperatura = __pega_informacao__(soup, 1)
            estacao.umidade = __pega_informacao__(soup, 2)
            estacao.vento = __pega_informacao__(soup, 3, 2)
            estacao.pressaoDoAr = __pega_informacao__(soup, 4)

            url = "https://www.cgesp.org/v3/previsao_estendida.jsp"
            response = requests.get(url, timeout=60000)

            soup = BeautifulSoup(response.text, "html.parser")

            forecasts = []
            for index, tabela in enumerate(soup.select(".col-previsao-simples")):
                # forecastDia = forecast[f"dia{index+1}"]
                forecast = CgeForecastData()
                for coluna in tabela.select(".data-prev"):
                    dia = coluna.text.replace("\n", "").strip()
                    dia = dia[:5] + "/" + dia[5:]
                    forecast.datetime = datetime.strptime(dia, "%d/%m/%Y")

                forecast.temperaturaMaxima = __texto_para_numero__(
                    tabela.select_one(".temp-max").text
                )

                forecast.temperaturaMinima = __texto_para_numero__(
                    tabela.select_one(".temp-min").text
                )
                forecast.umidade = __texto_para_numero__(
                    tabela.select_one(".umid-min").text
                )

                # forecastDia["temperaturaMaxima"] = __texto_para_numero__(
                #     tabela.select_one(".temp-max").text
                # )
                # forecastDia["umidadeMinima"] = __texto_para_numero__(
                #     tabela.select_one(".umid-min").text
                # )
                # forecastDia["umidadeMaxima"] = __texto_para_numero__(
                #     tabela.select_one(".umid-max").text
                # )

                forecast.condicaoTempo = __de_para_ceu__(
                    tabela.select_one(__pega_periodo_dia__())
                    .select_one(".cond-tempo")
                    .find("h2")
                    .text.strip()
                )

                forecasts.append(forecast)

            estacao.forecast = forecasts
            estacao.condicaoTempo = forecasts[0].condicaoTempo
            return estacao

        response = await self.hass.async_add_executor_job(get)

        _LOGGER.warning(f"Estação {self.estacaoId} => {response}")

        return response
