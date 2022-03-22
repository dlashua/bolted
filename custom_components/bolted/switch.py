"""Bolted Switch Entity"""
from typing import Optional

from homeassistant.helpers.entity import ToggleEntity

from .entity_manager import BoltedEntity, EntityManager
from .types import call_or_await

PLATFORM = "switch"


async def async_setup_platform(
    hass, config, async_add_entities, discovery_info=None
):
    """Initialize Bolted Switch Platform"""
    EntityManager.register_platform(PLATFORM, async_add_entities, BoltedSwitch)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Initialize Pyscript Switch Config"""
    return await async_setup_platform(
        hass, config_entry.data, async_add_entities, discovery_info=None
    )


class BoltedSwitch(BoltedEntity, ToggleEntity):
    """A Bolted Switch Entity"""

    _turn_on_handler = None
    _turn_off_handler = None
    _attr_is_on: Optional[bool] = None
    _attr_extra_state_attributes: dict = {}
    _restorable_attributes = [
        "_attr_is_on",
        "_attr_extra_state_attributes",
    ]

    async def async_turn_on(self, **kwargs):
        """Handle turn_on request."""
        if self._turn_on_handler is None:
            return

        if callable(self._turn_on_handler):
            await call_or_await(self._turn_on_handler, **kwargs)
        else:
            raise RuntimeError(
                (
                    f"Unable to Call turn_on_handler of type"
                    f" {type(self._turn_on_handler)}"
                )
            )

    async def async_turn_off(self, **kwargs):
        """Handle turn_off request."""
        if self._turn_off_handler is None:
            return

        if callable(self._turn_off_handler):
            await call_or_await(self._turn_off_handler, **kwargs)
        else:
            raise RuntimeError(
                (
                    f"Unable to Call turn_off_handler of type"
                    f" {type(self._turn_off_handler)}"
                )
            )

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

    def on_turn_on(self, func):
        """Setup handler for turn_on functionality"""
        self._turn_on_handler = func

    def on_turn_off(self, func):
        """Setup handler for turn_off functionality"""
        self._turn_off_handler = func
