"""Coordinator do radar de chuva (só na entrada "Alertas da cidade").

Baixa a imagem do radar a cada 5 minutos e lê a chuva de cada célula. Quando
não há chuva no radar nem na previsão, passa a 15 minutos (com a opção de
intervalo adaptativo ligada). A consulta usa If-Modified-Since: se a imagem
não mudou, o servidor responde sem reenviá-la.

O servidor do radar às vezes responde 502/504 ou manda a imagem cortada. Uma
falha assim não derruba os sensores: a última leitura continua valendo por até
TOLERANCIA_FALHAS e a integração tenta de novo em INTERVALO_NOVA_TENTATIVA.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime

import requests

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .cge_alertas import REQUEST_TIMEOUT
from .cge_alertas_coordinator import URL_ISSUES, CgeAlertasCoordinator, kwargs_config_entry
from .cge_extras import INTERVALO_COM_CHUVA
from .cge_radar import (
    URL_RADAR,
    AnimacaoRadar,
    LeituraRadar,
    RadarImagemInvalida,
    RadarLayoutError,
    ler_radar,
)
from .const import DOMAIN, INTERVALO_RADAR, INTERVALO_RADAR_SEM_CHUVA

_LOGGER = logging.getLogger(__name__)

ISSUE_ID_RADAR = "layout_radar"

# Por quanto tempo a última leitura continua valendo enquanto o servidor falha.
TOLERANCIA_FALHAS = timedelta(minutes=20)
INTERVALO_NOVA_TENTATIVA = timedelta(minutes=1)


def _quando(resposta: requests.Response) -> datetime:
    """Horário da imagem (Last-Modified), ou agora se o servidor não informar."""
    try:
        return dt_util.as_utc(parsedate_to_datetime(resposta.headers["Last-Modified"]))
    except (KeyError, TypeError, ValueError):
        return dt_util.utcnow()


class CgeRadarCoordinator(DataUpdateCoordinator[LeituraRadar]):
    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, alertas: CgeAlertasCoordinator
    ) -> None:
        self.alertas = alertas
        self.animacao = AnimacaoRadar()
        self.intervalo_adaptativo = True
        self.motivo_intervalo: str | None = None
        self.erro_layout: str | None = None
        self._ultima_modificacao: str | None = None
        # Falhas passageiras seguidas (servidor fora, imagem cortada).
        self.falhando_desde: datetime | None = None
        self.falhas_seguidas = 0
        self.ultima_falha: str | None = None
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_radar",
            update_interval=INTERVALO_RADAR,
            **kwargs_config_entry(entry),
        )

    def _baixar(self) -> requests.Response | None:
        """A imagem nova, ou None se não mudou desde a última leitura."""
        cabecalhos = {}
        if self._ultima_modificacao and self.data is not None:
            cabecalhos["If-Modified-Since"] = self._ultima_modificacao
        resposta = requests.get(URL_RADAR, headers=cabecalhos, timeout=REQUEST_TIMEOUT)
        if resposta.status_code == 304:
            return None
        resposta.raise_for_status()
        return resposta

    def _ler(self, conteudo: bytes, obtida_em: datetime) -> LeituraRadar:
        leitura = ler_radar(conteudo, obtida_em)
        self.animacao.adicionar(leitura)
        leitura.quadro = None  # já está na animação; não precisa ficar na memória
        return leitura

    async def _async_update_data(self) -> LeituraRadar:
        try:
            resposta = await self.hass.async_add_executor_job(self._baixar)
        except requests.exceptions.RequestException as err:
            return self._falha_passageira(f"não foi possível baixar o radar: {err}", err)
        if resposta is None:
            self._recuperou()
            self._definir_intervalo(self.data)
            return self.data  # type: ignore[return-value]

        try:
            leitura = await self.hass.async_add_executor_job(
                self._ler, resposta.content, _quando(resposta)
            )
        except RadarImagemInvalida as err:
            return self._falha_passageira(f"o radar mandou uma imagem inválida: {err}", err)
        except RadarLayoutError as err:
            self._recuperou()
            self._sincronizar_reparo(str(err))
            self._definir_intervalo(None)
            raise UpdateFailed(f"imagem do radar não reconhecida: {err}") from err
        self._recuperou()
        self._sincronizar_reparo(None)
        self._ultima_modificacao = resposta.headers.get("Last-Modified")
        self._definir_intervalo(leitura)
        return leitura

    # ------------------------------------------------ falhas passageiras

    def _falha_passageira(self, mensagem: str, erro: Exception) -> LeituraRadar:
        """Mantém a última leitura e tenta de novo logo; só desiste (sensores
        indisponíveis, erro no log) depois de TOLERANCIA_FALHAS."""
        agora = dt_util.utcnow()
        if self.falhando_desde is None:
            self.falhando_desde = agora
        self.falhas_seguidas += 1
        self.ultima_falha = mensagem
        if self.data is not None and agora - self.falhando_desde < TOLERANCIA_FALHAS:
            _LOGGER.debug(
                "CGE: %s (falha %d seguida); mantendo a imagem anterior",
                mensagem,
                self.falhas_seguidas,
            )
            self.update_interval = INTERVALO_NOVA_TENTATIVA
            self.motivo_intervalo = "nova tentativa após falha do servidor"
            return self.data
        self._definir_intervalo(None)
        raise UpdateFailed(mensagem) from erro

    def _recuperou(self) -> None:
        if self.falhas_seguidas:
            _LOGGER.debug(
                "CGE: radar voltou depois de %d falha(s) seguida(s)", self.falhas_seguidas
            )
        self.falhando_desde = None
        self.falhas_seguidas = 0

    # ------------------------------------------------ intervalo

    def definir_intervalo_adaptativo(self, ativo: bool) -> None:
        self.intervalo_adaptativo = ativo
        self._definir_intervalo(self.data)

    def _definir_intervalo(self, leitura: LeituraRadar | None) -> None:
        if not self.intervalo_adaptativo:
            intervalo, motivo = INTERVALO_RADAR, "intervalo fixo (opção desligada)"
        elif leitura is None:
            intervalo, motivo = INTERVALO_RADAR, "sem leitura do radar"
        elif leitura.tem_chuva:
            intervalo, motivo = INTERVALO_RADAR, "chuva no radar"
        elif (self.alertas.update_interval or INTERVALO_COM_CHUVA) <= INTERVALO_COM_CHUVA:
            intervalo, motivo = INTERVALO_RADAR, self.alertas.motivo_intervalo or "previsão de chuva"
        else:
            intervalo, motivo = INTERVALO_RADAR_SEM_CHUVA, "sem chuva no radar nem na previsão"
        self.update_interval = intervalo
        self.motivo_intervalo = motivo

    # ------------------------------------------------ reparo

    def _sincronizar_reparo(self, erro: str | None) -> None:
        if erro == self.erro_layout:
            return
        self.erro_layout = erro
        if erro is None:
            ir.async_delete_issue(self.hass, DOMAIN, ISSUE_ID_RADAR)
            return
        _LOGGER.warning("CGE: a imagem do radar mudou de layout: %s", erro)
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            ISSUE_ID_RADAR,
            is_fixable=False,
            is_persistent=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="layout_alterado",
            translation_placeholders={"parte": "radar de chuva", "url": URL_RADAR, "erro": erro},
            learn_more_url=URL_ISSUES,
        )


def remover_reparo_radar(hass: HomeAssistant) -> None:
    ir.async_delete_issue(hass, DOMAIN, ISSUE_ID_RADAR)
