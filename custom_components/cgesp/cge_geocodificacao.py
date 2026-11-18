"""Localização aproximada (latitude/longitude) dos pontos de alagamento.

O CGE não publica coordenadas, só o nome da via (abreviado) e uma referência.
Aqui o endereço é expandido e consultado no Nominatim (OpenStreetMap).
O resultado só é aceito se estiver na cidade de São Paulo, e a precisão é
informada para quem usar a coordenada:

- ``numero``: rua e número encontrados ("altura do número 7557");
- ``rua``: a rua certa, mas em algum ponto dela (vias longas podem ficar longe);
- ``referencia``: a rua não foi achada, usou-se a via da referência;
- ``aproximado``: o serviço devolveu uma via com outro nome, provavelmente vizinha.

Política de uso do Nominatim: no máximo 1 consulta por segundo, cache dos
resultados e User-Agent identificando a aplicação.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import requests

from .cge_alertas import PontoAlagamento, normalizar

_LOGGER = logging.getLogger(__name__)

URL_NOMINATIM = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "ha-cgesp (Home Assistant custom integration)"
REQUEST_TIMEOUT = 20

INTERVALO_ENTRE_CONSULTAS = 1.1  # segundos (limite do Nominatim: 1/s)
MAX_CONSULTAS_POR_RODADA = 30
TTL_NAO_ENCONTRADO = 24 * 60 * 60  # tenta de novo um endereço não achado após 1 dia
MAX_ENTRADAS_CACHE = 2000

PRECISAO_NUMERO = "numero"
PRECISAO_RUA = "rua"
PRECISAO_REFERENCIA = "referencia"
PRECISAO_APROXIMADO = "aproximado"

_ABREVIACOES = {
    "r": "Rua",
    "av": "Avenida",
    "al": "Alameda",
    "ac": "Acesso",
    "pte": "Ponte",
    "vd": "Viaduto",
    "tv": "Travessa",
    "pc": "Praça",
    "pca": "Praça",
    "est": "Estrada",
    "rod": "Rodovia",
    "lgo": "Largo",
    "tun": "Túnel",
    "pq": "Parque",
    "jd": "Jardim",
    "vl": "Vila",
    "sto": "Santo",
    "sta": "Santa",
    "s": "São",
    "dr": "Doutor",
    "prof": "Professor",
    "eng": "Engenheiro",
    "pres": "Presidente",
    "gov": "Governador",
    "mal": "Marechal",
    "gal": "General",
    "cel": "Coronel",
    "brig": "Brigadeiro",
    "cap": "Capitão",
    "dep": "Deputado",
    "sen": "Senador",
    "ver": "Vereador",
    "jorn": "Jornalista",
}

# Palavras que não ajudam a dizer se duas vias são a mesma.
_PALAVRAS_IGNORADAS = {
    "rua", "avenida", "alameda", "acesso", "ponte", "viaduto", "travessa",
    "praca", "estrada", "rodovia", "largo", "tunel", "marginal",
    "de", "da", "do", "das", "dos", "e",
}

_NUMERO = re.compile(r"(?:n[uú]mero|n[º°o]\.?)\s*(\d{1,5})", re.IGNORECASE)


@dataclass
class Localizacao:
    latitude: float
    longitude: float
    precisao: str


@dataclass
class _EntradaCache:
    localizacao: Localizacao | None
    quando: float


def expandir_abreviacoes(via: str) -> str:
    """'R STO ARCADIO (JD PAULISTA)' -> 'Rua Santo ARCADIO'."""
    sem_parenteses = re.sub(r"\(.*?\)", " ", via)
    palavras = []
    for palavra in re.split(r"[\s\-]+", sem_parenteses):
        chave = palavra.strip(".,").lower()
        if not chave:
            continue
        palavras.append(_ABREVIACOES.get(chave, palavra.strip(",")))
    return " ".join(palavras)


def extrair_numero(referencia: str | None) -> str | None:
    """'altura do número 7557' -> '7557'."""
    if not referencia:
        return None
    encontrado = _NUMERO.search(referencia)
    return encontrado.group(1) if encontrado else None


def _palavras_relevantes(texto: str) -> set[str]:
    return {
        palavra
        for palavra in re.split(r"[^a-z0-9]+", normalizar(texto))
        if len(palavra) >= 3 and palavra not in _PALAVRAS_IGNORADAS
    }


def nomes_combinam(procurado: str, encontrado: str | None) -> bool:
    """A via devolvida pelo serviço é a que foi pedida?

    Compara as palavras relevantes (sem tipo da via e preposições); aceita
    quando ao menos 60% das palavras procuradas aparecem no nome encontrado.
    Ex.: 'MARGINAL TIETE ASCB EXPRESSA' combina com 'Marginal Tietê (Expressa)'.
    """
    if not encontrado:
        return False
    # No nome do CGE, parênteses trazem o bairro ("(JD PAULISTA)"); no do
    # OpenStreetMap fazem parte do nome ("Marginal Tietê (Expressa)").
    procuradas = _palavras_relevantes(expandir_abreviacoes(procurado))
    if not procuradas:
        return False
    achadas = _palavras_relevantes(encontrado)
    return len(procuradas & achadas) / len(procuradas) >= 0.6


def _referencia_e_via(referencia: str | None) -> bool:
    if not referencia or extrair_numero(referencia):
        return False
    return not normalizar(referencia).startswith(("altura", "proximo", "em frente", "esquina"))


def _resultado_valido(resultado: dict[str, Any]) -> bool:
    endereco = resultado.get("address") or {}
    cidade = endereco.get("city") or endereco.get("town") or endereco.get("municipality")
    return normalizar(cidade or "") == "sao paulo"


def _nome_da_via(resultado: dict[str, Any]) -> str | None:
    endereco = resultado.get("address") or {}
    return endereco.get("road") or resultado.get("name")


def chave_ponto(ponto: PontoAlagamento) -> str:
    return f"{normalizar(ponto.local)}|{normalizar(ponto.referencia or '')}"


def buscar_nominatim(rua: str) -> list[dict[str, Any]]:
    """Consulta síncrona (rodar no executor)."""
    resposta = requests.get(
        URL_NOMINATIM,
        params={
            "street": rua,
            "city": "São Paulo",
            "state": "São Paulo",
            "country": "Brasil",
            "format": "jsonv2",
            "addressdetails": 1,
            "limit": 1,
        },
        headers={"User-Agent": USER_AGENT, "Accept-Language": "pt-BR"},
        timeout=REQUEST_TIMEOUT,
    )
    resposta.raise_for_status()
    return resposta.json()


class Geocodificador:
    """Localiza pontos de alagamento com cache e limite de consultas.

    `executar` roda uma função síncrona fora do loop (no HA,
    `hass.async_add_executor_job`); `buscar` e `dormir` podem ser trocados
    nos testes.
    """

    def __init__(
        self,
        executar: Callable[..., Awaitable[Any]],
        buscar: Callable[[str], list[dict[str, Any]]] = buscar_nominatim,
        dormir: Callable[[float], Awaitable[None]] = asyncio.sleep,
        relogio: Callable[[], float] = time.time,
    ) -> None:
        self._executar = executar
        self._buscar = buscar
        self._dormir = dormir
        self._relogio = relogio
        self._cache: dict[str, _EntradaCache] = {}
        self._ultima_consulta: float | None = None
        self._trava = asyncio.Lock()

    # ----------------------------------------------------------- cache

    def importar(self, dados: dict[str, Any]) -> None:
        for chave, valor in (dados or {}).items():
            try:
                loc = valor.get("localizacao")
                self._cache[chave] = _EntradaCache(
                    Localizacao(**loc) if loc else None, float(valor["quando"])
                )
            except (AttributeError, KeyError, TypeError, ValueError):
                continue

    def exportar(self) -> dict[str, Any]:
        return {
            chave: {
                "localizacao": vars(entrada.localizacao) if entrada.localizacao else None,
                "quando": entrada.quando,
            }
            for chave, entrada in self._cache.items()
        }

    def _do_cache(self, chave: str) -> tuple[bool, Localizacao | None]:
        entrada = self._cache.get(chave)
        if entrada is None:
            return False, None
        if entrada.localizacao is None and self._relogio() - entrada.quando > TTL_NAO_ENCONTRADO:
            return False, None
        return True, entrada.localizacao

    def _guardar(self, chave: str, localizacao: Localizacao | None) -> None:
        self._cache[chave] = _EntradaCache(localizacao, self._relogio())
        if len(self._cache) > MAX_ENTRADAS_CACHE:
            mais_antiga = min(self._cache, key=lambda c: self._cache[c].quando)
            self._cache.pop(mais_antiga)

    # ----------------------------------------------------------- uso

    def aplicar_cache(self, pontos: list[PontoAlagamento]) -> list[PontoAlagamento]:
        """Preenche os pontos que já estão no cache; devolve os que faltam."""
        pendentes = []
        for ponto in pontos:
            encontrado, localizacao = self._do_cache(chave_ponto(ponto))
            if not encontrado:
                pendentes.append(ponto)
            elif localizacao is not None:
                _preencher(ponto, localizacao)
        return pendentes

    async def localizar(self, pontos: list[PontoAlagamento]) -> bool:
        """Consulta os pontos fora do cache (até o limite por rodada).

        Retorna True se algo novo entrou no cache. Erros de rede não são
        cacheados: o ponto é tentado de novo na próxima rodada.
        """
        async with self._trava:
            novidade = False
            consultados: set[str] = set()
            for ponto in self.aplicar_cache(pontos):
                chave = chave_ponto(ponto)
                if chave in consultados:
                    continue
                if len(consultados) >= MAX_CONSULTAS_POR_RODADA:
                    break
                consultados.add(chave)
                try:
                    localizacao = await self._localizar_ponto(ponto)
                except (requests.exceptions.RequestException, ValueError) as err:
                    _LOGGER.debug("Falha ao localizar %s: %s", ponto.local, err)
                    continue
                self._guardar(chave, localizacao)
                novidade = True
            if novidade:
                self.aplicar_cache(pontos)
            return novidade

    async def _consultar(self, rua: str) -> dict[str, Any] | None:
        if self._ultima_consulta is not None:
            espera = INTERVALO_ENTRE_CONSULTAS - (self._relogio() - self._ultima_consulta)
            if espera > 0:
                await self._dormir(espera)
        try:
            resultados = await self._executar(self._buscar, rua)
        finally:
            self._ultima_consulta = self._relogio()
        for resultado in resultados or []:
            if _resultado_valido(resultado):
                return resultado
        return None

    async def _localizar_ponto(self, ponto: PontoAlagamento) -> Localizacao | None:
        rua = expandir_abreviacoes(ponto.local)
        numero = extrair_numero(ponto.referencia)
        aproximado: dict[str, Any] | None = None

        resultado = await self._consultar(f"{numero} {rua}" if numero else rua)
        if resultado is not None:
            if nomes_combinam(ponto.local, _nome_da_via(resultado)):
                achou_numero = bool((resultado.get("address") or {}).get("house_number"))
                return _localizacao(
                    resultado, PRECISAO_NUMERO if numero and achou_numero else PRECISAO_RUA
                )
            aproximado = resultado

        if _referencia_e_via(ponto.referencia):
            resultado = await self._consultar(expandir_abreviacoes(ponto.referencia or ""))
            if resultado is not None and nomes_combinam(
                ponto.referencia or "", _nome_da_via(resultado)
            ):
                return _localizacao(resultado, PRECISAO_REFERENCIA)

        if aproximado is not None:
            return _localizacao(aproximado, PRECISAO_APROXIMADO)
        return None


def _localizacao(resultado: dict[str, Any], precisao: str) -> Localizacao:
    return Localizacao(float(resultado["lat"]), float(resultado["lon"]), precisao)


def _preencher(ponto: PontoAlagamento, localizacao: Localizacao) -> None:
    ponto.latitude = localizacao.latitude
    ponto.longitude = localizacao.longitude
    ponto.precisao_localizacao = localizacao.precisao
