"""Bolted Entity Manager"""
import logging
from typing import Optional, Any
from collections.abc import Mapping, MutableMapping
from homeassistant.helpers.restore_state import RestoreEntity
from .helpers import ObservableVariable

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
    async def get(cls, bolted, platform, name, **kwargs):
        unique_id = f'{bolted.__class__.__module__}::{bolted.name}::{name}'
        """Get an Entity from Bolted"""
        await cls.wait_platform_registered(platform)
        if platform not in cls.registered_entities or unique_id not in cls.registered_entities[platform]:
            await cls.create(bolted, platform, unique_id, **kwargs)
        
        return cls.registered_entities[platform][unique_id]

    @classmethod
    async def create(cls, bolted, platform, unique_id, **kwargs):
        """Create entity from Bolted."""
        await cls.wait_platform_registered(platform)
        _LOGGER.debug('Created New Entity %s %s', platform, unique_id)
        new_entity = cls.platform_classes[platform](cls.hass, bolted, unique_id, **kwargs)
        cls.platform_adders[platform]([new_entity])
        await new_entity.wait_for_added()
        cls.registered_entities[platform][unique_id] = new_entity

    @classmethod
    async def wait_platform_registered(cls, platform):
        """Wait for platform registration."""
        if platform not in cls.platform_classes:
            raise KeyError(f'Platform {platform} not registered.')

        return True


class BoltedEntity(RestoreEntity):
    """Base Class for all Bolted Entities"""

    _attr_unique_id: Optional[str] = None
    _attr_should_poll = False
    _attr_extra_state_attributes: MutableMapping[str, Any]
    _attr_bolted_state_attributes: MutableMapping[str, Any]

    def __init__(self, hass, bolted, unique_id, restore=False):
        self.hass = hass
        self.bolted = bolted
        self._added = ObservableVariable(False)
        self._ready_handler = None
        self._should_restore = restore

        self._attr_unique_id = unique_id

        self._attr_bolted_state_attributes = {
            "bolted_app": self.bolted.__class__.__module__,
            "bolted_app_name": self.bolted.name,
        }

        _LOGGER.debug(
            "Entity Initialized %s",
            self.unique_id,
        )

    async def wait_for_added(self):
        while self._added.value is not True:
            _LOGGER.debug('Waiting for Entity to be added %s', self.unique_id)
            await self._added.wait()
        
    @property
    def extra_state_attributes(self) -> Optional[Mapping[str, Any]]:
        """Return entity specific state attributes."""
        attrs = {}
        if hasattr(self, "_attr_extra_state_attributes"):
            attrs.update(self._attr_extra_state_attributes)
        if hasattr(self, "_attr_bolted_state_attributes"):
            attrs.update(self._attr_bolted_state_attributes)
        return attrs

    async def async_added_to_hass(self):
        """Called when Home Assistant adds the entity to the registry""" 
        await super().async_added_to_hass()

        if self._should_restore:
            last_data = await self.async_get_last_extra_data()
            self.bolted.logger.debug("Last Data %s: %s", self.unique_id, last_data)
            if last_data is not None:
                for key, value in last_data.as_dict().items():
                    self.bolted.logger.debug('Restore %s = %s value', key, value)
                    setattr(self, key, value)

        self._added.value = True   
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
        if self._added.value is True:
            self.async_write_ha_state()




