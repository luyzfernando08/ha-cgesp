"""Camada de chuva para mapas: blocos {z}/{x}/{y} gerados da imagem do radar.

Cards de mapa que aceitam camadas (como o ha-map-card) pedem os blocos
direto ao servidor, sem o login do Home Assistant; por isso o endereço não
exige autenticação. Ele só devolve o que a imagem pública do radar já mostra.
"""
from __future__ import annotations

from collections import OrderedDict

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .cge_radar import BLOCO_VAZIO
from .const import DOMAIN
from .entity import obter_radar

ZOOM_MAXIMO = 20
_MAXIMO_EM_CACHE = 256
_REGISTRADA = "mapa_radar_registrado"


def registrar_mapa_radar(hass: HomeAssistant) -> None:
    """Registra o endereço uma vez só (o HA não deixa remover views)."""
    dados = hass.data.setdefault(DOMAIN, {})
    if not dados.get(_REGISTRADA):
        hass.http.register_view(CgeRadarBlocosView(hass))
        dados[_REGISTRADA] = True


class CgeRadarBlocosView(HomeAssistantView):
    url = "/api/cgesp/radar/{versao}/{z:\\d+}/{x:\\d+}/{y:\\d+}.png"
    name = "api:cgesp:radar_blocos"
    requires_auth = False

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._cache: OrderedDict[tuple, bytes] = OrderedDict()

    async def get(
        self, request: web.Request, versao: str, z: str, x: str, y: str
    ) -> web.Response:
        # `versao` só serve para o card pedir blocos novos a cada imagem do
        # radar; sempre é servida a leitura mais recente.
        zoom, coluna, linha = int(z), int(x), int(y)
        if zoom > ZOOM_MAXIMO or coluna >= 2**zoom or linha >= 2**zoom:
            return web.Response(status=404)
        radar = obter_radar(self.hass)
        leitura = radar.data if radar is not None else None
        if leitura is None:
            return _png(BLOCO_VAZIO, cache=False)
        chave = (leitura.obtida_em, zoom, coluna, linha)
        corpo = self._cache.get(chave)
        if corpo is None:
            corpo = await self.hass.async_add_executor_job(
                leitura.bloco_do_mapa, zoom, coluna, linha
            )
            self._cache[chave] = corpo
            while len(self._cache) > _MAXIMO_EM_CACHE:
                self._cache.popitem(last=False)
        else:
            self._cache.move_to_end(chave)
        return _png(corpo, cache=True)


def _png(corpo: bytes, cache: bool) -> web.Response:
    return web.Response(
        body=corpo,
        content_type="image/png",
        headers={"Cache-Control": "public, max-age=300" if cache else "no-store"},
    )
