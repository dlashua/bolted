"""Bolted Sensor Entity"""
from .entity_manager import EntityManager, BoltedEntity
from homeassistant.components.sensor import SensorEntity
from typing import Optional

PLATFORM = "sensor"


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Initialize Bolted Sensor Platform"""
    EntityManager.register_platform(PLATFORM, async_add_entities, BoltedSensor)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Initialize Bolted Sensor Config"""
    return await async_setup_platform(hass, config_entry.data, async_add_entities, discovery_info=None)


class BoltedSensor(BoltedEntity, SensorEntity):
    """A Bolted Sensor Entity"""
    
    _attr_native_value: Optional[str] = None
    _attr_extra_state_attributes: dict = {}
    _attr_native_unit_of_measurement: Optional[str] = None

    # USED IN BOLTED APPS
    ######################################

    def set(self, state: Optional[str], attributes: Optional[dict] = None) -> None:
        self._attr_native_value = state
        if attributes is not None:
            self._attr_extra_state_attributes = attributes
        self.async_update()

    def set_attributes(self, attributes: dict = {}) -> None:
        self._attr_extra_state_attributes = attributes
        self.async_update()

    def set_attribute(self, key: str, value: any) -> None:
        self._attr_extra_state_attributes[key] = value
        self.async_update()

    def set_unit_of_measurement(self, unit: str) -> None:
        self._attr_native_unit_of_measurement = unit

    def set_device_class(self, device_class: str) -> None:
        self._attr_device_class = device_class

