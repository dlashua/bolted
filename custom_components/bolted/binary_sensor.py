"""Bolted Binary Sensor Entity"""
from typing import Optional

from homeassistant.components.binary_sensor import BinarySensorEntity

from .entity_manager import BoltedEntity, EntityManager

PLATFORM = "binary_sensor"


async def async_setup_platform(
    hass, config, async_add_entities, discovery_info=None
):
    """Initialize Pyscript Binary Sensor Platform"""
    EntityManager.register_platform(
        PLATFORM, async_add_entities, BoltedBinarySensor
    )


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Initialize Pyscript Binary Sensor Config"""
    return await async_setup_platform(
        hass, config_entry.data, async_add_entities, discovery_info=None
    )


class BoltedBinarySensor(BoltedEntity, BinarySensorEntity):
    """A Bolted Binary Sensor Entity"""

    _attr_is_on: Optional[bool] = None
    _attr_extra_state_attributes: dict = {}
    _attr_device_class: Optional[str] = None
    _restorable_attributes = [
        "_attr_is_on",
        "_attr_extra_state_attributes",
        "_attr_device_class",
    ]

    # USED IN BOLTED APPS
    ######################################

    def set(self, is_on: bool, attributes: Optional[dict] = None) -> None:
        self._attr_is_on = is_on
        if attributes is not None:
            self._attr_extra_state_attributes = attributes
        self.async_update()

    def set_attributes(self, attributes: dict = {}) -> None:
        self._attr_extra_state_attributes = attributes
        self.async_update()

    def set_attribute(self, key: str, value: any) -> None:
        self._attr_extra_state_attributes[key] = value
        self.async_update()

    def set_device_class(self, device_class: str) -> None:
        self._attr_device_class = device_class
