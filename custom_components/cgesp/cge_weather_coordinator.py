from datetime import timedelta
from random import randrange
from homeassistant.components.cge.cge_data import CgeData
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
import logging

from .cge_scrape import CgeScrape
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class CgeWeatherCoordinator(DataUpdateCoordinator["CgeData"]):
    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        self.scraper = CgeScrape(
            hass=hass, estacaoId=config_entry.data.get("ESTACAO_ID")
        )
        update_interval = timedelta(minutes=randrange(61, 75))
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=update_interval)

    async def _async_update_data(self) -> CgeData:
        return await self.scraper.get()
