import logging
from .cge_weather_coordinator import CgeWeatherCoordinator
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.components.weather import Forecast, WeatherEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, ESTACOES

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    estacao_id: int = entry.data.get("ESTACAO_ID")
    coordinator: CgeWeatherCoordinator = CgeWeatherCoordinator(
        hass=hass, config_entry=entry
    )
    _LOGGER.debug(f"Estação selecionado: {estacao_id}")

    async_add_entities(
        [CgeWeather(coordinator=coordinator, estacao_id=estacao_id)],
        update_before_add=True,
    )


class CgeWeather(CoordinatorEntity[CgeWeatherCoordinator], WeatherEntity):
    def __init__(self, coordinator: CgeWeatherCoordinator, estacao_id: int) -> None:
        self.estacao_id = estacao_id
        self.coordinator = coordinator
        super().__init__(coordinator)


    @property
    def unique_id(self) -> str | None:
        return f"cge_{self.estacao_id}"

    @property
    def name(self) -> str:
        return ESTACOES[self.estacao_id]

    @property
    def condition(self) -> str | None:
        return self.coordinator.data.condicaoTempo

    @property
    def native_temperature(self) -> float | None:
        return self.coordinator.data.temperatura

    @property
    def humidity(self) -> float | None:
        return self.coordinator.data.umidade

    @property
    def native_pressure(self) -> float | None:
        return self.coordinator.data.pressaoDoAr

    @property
    def native_wind_speed(self) -> float | None:
        return self.coordinator.data.vento

    @property
    def forecast(self) -> list[Forecast] | None:
        forecasts: list[Forecast] = []

        for item in self.coordinator.data.forecast:
            forecast = Forecast()
            forecast["datetime"] = item.datetime
            forecast["humidity"] = item.umidade
            forecast["templow"] = item.temperaturaMinima
            forecast["condition"] = item.condicaoTempo
            forecast["temperature"] = item.temperaturaMaxima
            forecasts.append(forecast)

        return forecasts

    @property
    def device_info(self) -> DeviceInfo:
        """Device info."""
        return DeviceInfo(
            name="CGE - SP",
            entry_type=DeviceEntryType.SERVICE,
            identifiers={(DOMAIN,)},  # type: ignore[arg-type]
            manufacturer="cgesp.org",
            model="CGE",
            configuration_url="https://www.cgesp.org/v3/",
        )
