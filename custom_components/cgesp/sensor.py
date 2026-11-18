"""Sensor do estado de alerta da área monitorada de cada estação."""
from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import slugify

from .cge_alertas_coordinator import CgeAlertasCoordinator, async_obter_coordinator
from .const import CONF_ESTACAO_ID, ESTACOES_REGIAO, ESTADOS_ALERTA
from .entity import CgeEstacaoAlertaEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    estacao_id: int = entry.data[CONF_ESTACAO_ID]
    if not ESTACOES_REGIAO.get(estacao_id):
        return

    coordinator = await async_obter_coordinator(hass, entry.entry_id)
    async_add_entities([CgeEstadoAlertaSensor(coordinator, estacao_id)])


class CgeEstadoAlertaSensor(CgeEstacaoAlertaEntity, SensorEntity):
    """Observação, Atenção, Iminência de transbordamento ou Alerta."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ESTADOS_ALERTA
    _attr_translation_key = "estado_alerta"
    _attr_icon = "mdi:alert-outline"

    def __init__(self, coordinator: CgeAlertasCoordinator, estacao_id: int) -> None:
        super().__init__(coordinator, estacao_id)
        self._attr_unique_id = f"cge_{estacao_id}_estado_alerta"
        self._attr_name = f"{self.nome_estacao} Estado de alerta"
        self.entity_id = f"sensor.cgesp_{slugify(self.nome_estacao)}_estado_alerta"

    @property
    def native_value(self) -> str | None:
        return self.estado
