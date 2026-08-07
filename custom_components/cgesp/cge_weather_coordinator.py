from datetime import timedelta
from random import randrange
from .cge_data import CgeData
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
import logging

from .cge_scrape import CgeScrape, CgeScrapeError
from .const import CONF_ESTACAO_ID, DOMAIN

_LOGGER = logging.getLogger(__name__)


class CgeWeatherCoordinator(DataUpdateCoordinator["CgeData"]):
    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        self.scraper = CgeScrape(
            hass=hass, estacao_id=config_entry.data[CONF_ESTACAO_ID]
        )
        update_interval = timedelta(minutes=randrange(61, 75))
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=update_interval)

    async def _async_update_data(self) -> CgeData:
        try:
            return await self.scraper.get()
        except CgeScrapeError as err:
            raise UpdateFailed(str(err)) from err
