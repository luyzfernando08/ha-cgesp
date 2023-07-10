from __future__ import annotations
from ast import List
from enum import Enum


import requests
from bs4 import BeautifulSoup
import re
import logging
from datetime import datetime
from .cge_data import CgeData
from .cge_data_forecast import CgeForecastData

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

TEMPERATURA:str = "Temperatura"
UMIDADE:str = "Umidade"
VENTO:str = "Vento"
PRESSAO:str = "Pressão"


def __texto_para_numero__(texto: str) -> int:
    valor = re.search(r"\d+\.\d+", texto)
    if valor is None:
        valor = re.search(r"\d+", texto)

    return float(valor.group())


def __pega_informacao__(soup: BeautifulSoup, index_coluna: int, linha: int = 1):
    return __texto_para_numero__(
        soup.select_one("table")
        .select("table")[index_coluna]
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
    elif ceu == "Nublado com chuva" or ceu == "Chuvisco":
        return "rainy"
    elif ceu == "Nublado" or ceu == "Encoberto":
        return "cloudy"

class CgeScrape:
    def __init__(self, hass: HomeAssistant, estacao_id: int) -> None:
        self.hass = hass
        self.estacao_id = estacao_id

    async def get(self) -> CgeData:
        def get():
            url = f"https://www.cgesp.org/v3/estacao.jsp?POSTO={self.estacao_id}"

            response = requests.get(url, timeout=60000)

            soup = BeautifulSoup(response.text, "html.parser")

            colunas = [TEMPERATURA,UMIDADE,VENTO,PRESSAO]

            index_por_coluna = {}
            for index,item in enumerate(soup.select('table tr th')):
                for coluna in colunas:
                    if item.text == coluna:
                        index_por_coluna[coluna] = index

            estacao = CgeData()

            if TEMPERATURA in index_por_coluna:
                estacao.temperatura = __pega_informacao__(soup, index_por_coluna[TEMPERATURA])
            if UMIDADE in index_por_coluna:
                estacao.umidade = __pega_informacao__(soup, index_por_coluna[UMIDADE])
            if VENTO in index_por_coluna:
                estacao.vento = __pega_informacao__(soup, index_por_coluna[VENTO],3)
            if PRESSAO in index_por_coluna:
                estacao.pressaoDoAr = __pega_informacao__(soup, index_por_coluna[PRESSAO])

            url = "https://www.cgesp.org/v3/previsao_estendida.jsp"
            response = requests.get(url, timeout=60000)

            soup = BeautifulSoup(response.text, "html.parser")

            forecasts = []
            for index, tabela in enumerate(soup.select(".col-previsao-simples")):
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

        return response
