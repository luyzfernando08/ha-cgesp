from __future__ import annotations
from ast import List
from .cge_data_forecast import CgeForecastData


class CgeData:
    def __init__(self) -> None:
        self._temperatura = None
        self._umidade = None
        self._vento = None
        self._pressaoDoAr = None
        self._condicaoTempo = None
        self.forecast = None

    @property
    def temperatura(self):
        return self._temperatura

    @temperatura.setter
    def temperatura(self, valor):
        self._temperatura = valor

    @property
    def umidade(self):
        return self._umidade

    @umidade.setter
    def umidade(self, valor):
        self._umidade = valor

    @property
    def vento(self):
        return self._vento

    @vento.setter
    def vento(self, valor):
        self._vento = valor

    @property
    def pressaoDoAr(self):
        return self._pressaoDoAr

    @pressaoDoAr.setter
    def pressaoDoAr(self, valor):
        self._pressaoDoAr = valor

    @property
    def condicaoTempo(self):
        return self._condicaoTempo

    @condicaoTempo.setter
    def condicaoTempo(self, valor):
        self._condicaoTempo = valor

    @property
    def forecast(self) -> list[CgeForecastData]:
        return self._forecast

    @forecast.setter
    def forecast(self, valor: list[CgeForecastData]):
        self._forecast = valor
