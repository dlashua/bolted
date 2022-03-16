"""Bolted Entity Manager"""
from homeassistant.helpers.entity import Entity
import logging
from typing import Optional, Any
from collections.abc import Awaitable, Iterable, Mapping, MutableMapping

_LOGGER: logging.Logger = logging.getLogger(__package__)


class EntityManager:
    """Entity Manager."""
    hass = None

    platform_adders = {}
    platform_classes = {}
    registered_entities = {}

    @classmethod
    def init(cls, hass):
        """Initialize Class Variables"""
        cls.hass = hass

    @classmethod
    def register_platform(cls, platform, adder, entity_class):
        """Register platform from Home Assistant"""
        _LOGGER.debug(
            "Platform %s Registered",
            platform,
        )
        cls.platform_adders[platform] = adder
        cls.platform_classes[platform] = entity_class
        cls.registered_entities[platform] = {}

    @classmethod
    def get(cls, bolted, platform, name):
        unique_id = f'{bolted.__class__.__module__}::{bolted.name}::{name}'
        """Get an Entity from Bolted"""
        cls.wait_platform_registered(platform)
        if platform not in cls.registered_entities or unique_id not in cls.registered_entities[platform]:
            cls.create(bolted, platform, unique_id)

        return cls.registered_entities[platform][unique_id]

    @classmethod
    def create(cls, bolted, platform, unique_id):
        """Create entity from Bolted."""
        cls.wait_platform_registered(platform)
        new_entity = cls.platform_classes[platform](cls.hass, bolted, unique_id)
        cls.platform_adders[platform]([new_entity])
        cls.registered_entities[platform][unique_id] = new_entity

    @classmethod
    def wait_platform_registered(cls, platform):
        """Wait for platform registration."""
        if platform not in cls.platform_classes:
            raise KeyError(f"Platform {platform} not registered.")

        return True


class BoltedEntity(Entity):
    """Base Class for all Bolted Entities"""
    _added = False

    _attr_unique_id: Optional[str] = None
    _attr_should_poll = False
    _attr_extra_state_attributes: MutableMapping[str, Any]
    _attr_bolted_state_attributes: MutableMapping[str, Any]

    def __init__(self, hass, bolted, unique_id):
        self.hass = hass
        self.bolted = bolted

        self._attr_unique_id = unique_id

        self._attr_bolted_state_attributes = {
            "bolted_app": self.bolted.__class__.__module__,
            "bolted_app_name": self.bolted.name,
        }

        _LOGGER.debug(
            "Entity Initialized %s",
            self.unique_id,
        )

    @property
    def extra_state_attributes(self) -> Optional[Mapping[str, Any]]:
        """Return entity specific state attributes.
        Implemented by platform classes. Convention for attribute names
        is lowercase snake_case.
        """
        attrs = {}
        if hasattr(self, "_attr_extra_state_attributes"):
            attrs.update(self._attr_extra_state_attributes)
        if hasattr(self, "_attr_bolted_state_attributes"):
            attrs.update(self._attr_bolted_state_attributes)
        return attrs

    async def async_added_to_hass(self):
        """Called when Home Assistant adds the entity to the registry""" 
        self._added = True   
        self.async_update()
        _LOGGER.debug(
            "Entity %s Added to Hass as %s",
            self.unique_id,
            self.entity_id,
        )

    # USED INTERNALLY
    #####################################

    def async_update(self):
        """Request an entity update from Home Assistant"""
        if self._added:
            self.async_write_ha_state()




