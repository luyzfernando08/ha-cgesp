class CgeForecastData:
    def __init__(self) -> None:
        self._temperaturaMinima = None
        self._temperaturaMaxima = None
        self._umidade = None
        self._datetime = None
        self._condicaoTempo = None

    @property
    def temperaturaMinima(self):
        return self._temperaturaMinima

    @temperaturaMinima.setter
    def temperaturaMinima(self, valor):
        self._temperaturaMinima = valor

    @property
    def temperaturaMaxima(self):
        return self._temperaturaMaxima

    @temperaturaMaxima.setter
    def temperaturaMaxima(self, valor):
        self._temperaturaMaxima = valor

    @property
    def umidade(self):
        return self._umidade

    @umidade.setter
    def umidade(self, valor):
        self._umidade = valor

    @property
    def datetime(self):
        return self._datetime

    @datetime.setter
    def datetime(self, valor):
        self._datetime = valor

    @property
    def condicaoTempo(self):
        return self._condicaoTempo

    @condicaoTempo.setter
    def condicaoTempo(self, valor):
        self._condicaoTempo = valor
