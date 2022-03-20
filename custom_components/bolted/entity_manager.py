"""Bolted Entity Manager"""
import logging
from typing import Optional, Any
from collections.abc import Mapping, MutableMapping
from homeassistant.helpers.restore_state import RestoreEntity
from .helpers import ObservableVariable
from homeassistant.helpers.restore_state import ExtraStoredData, RestoredExtraData
import homeassistant.helpers.entity_registry as hass_entity_registry
import homeassistant.helpers.device_registry as hass_device_registry

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
        cls.entity_registry = hass_entity_registry.async_get(hass)
        cls.device_registry = hass_device_registry.async_get(hass)


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
    async def get(cls, bolted, platform, name, restore=False):
        """Get an Entity from Bolted"""
        unique_id = f'{bolted.__class__.__module__}::{bolted.name}::{name}'
        await cls.wait_platform_registered(platform)
        if platform not in cls.registered_entities or unique_id not in cls.registered_entities[platform]:
            await cls.create(bolted, platform, name, restore=restore)
        
        return cls.registered_entities[platform][unique_id]

    @classmethod
    async def create(cls, bolted, platform, name, restore=False):
        """Create entity from Bolted."""
        unique_id = f'{bolted.__class__.__module__}::{bolted.name}::{name}'
        await cls.wait_platform_registered(platform)
        _LOGGER.debug('Created New Entity %s %s', platform, unique_id)
        new_entity = cls.platform_classes[platform](cls.hass, bolted, unique_id, restore=restore)
        new_entity.entity_id = f'{platform}.{bolted.name}'
        cls.platform_adders[platform]([new_entity])
        await new_entity.wait_for_added()
        cls.registered_entities[platform][unique_id] = new_entity

    @classmethod
    def remove(cls, entity):
        entity.set(None, {})
        # entity IDs don't stick with this. commenting for now.
        # entity_id = entity.entity_id
        # unique_id = entity.unique_id
        # entity_platform, _ = entity_id.split('.', 1)
        # _LOGGER.debug('Removing Entity %s', entity_id)
        # cls.entity_registry.async_remove(entity_id)
        # del cls.registered_entities[entity_platform][unique_id]

    @classmethod
    async def wait_platform_registered(cls, platform):
        """Wait for platform registration."""
        if platform not in cls.platform_classes:
            raise KeyError(f'Platform {platform} not registered.')

        return True

    @classmethod
    def get_by_entity_id(cls, entity_id):
        return cls.entity_registry.async_get(entity_id)

    @classmethod
    def get_device_id(cls, entity_id):
        this_entity = cls.get_by_entity_id(entity_id)
        if this_entity is None:
            return None
        return this_entity.device_id

    @classmethod
    def get_device_by_entity_id(cls, entity_id):
        device_id = cls.get_device_id(entity_id)
        if device_id is None:
            return None
        return cls.device_registry.async_get(device_id)


class BoltedEntity(RestoreEntity):
    """Base Class for all Bolted Entities"""

    _attr_unique_id: Optional[str] = None
    _attr_should_poll = False
    _attr_extra_state_attributes: MutableMapping[str, Any]
    _attr_bolted_state_attributes: MutableMapping[str, Any]
    _restorable_attributes = None

    def __init__(self, hass, bolted, unique_id, restore=False):
        self.hass = hass
        self.bolted = bolted
        self._added = ObservableVariable(False)
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

    @property
    def extra_restore_state_data(self) -> Optional[ExtraStoredData]:
        """Return entity specific state data to be restored.
        Implemented by platform classes.
        """
        if self._restorable_attributes is None:
            return None

        restore = dict()
        for key in self._restorable_attributes:
            restore[key] = getattr(self, key)
        return RestoredExtraData(restore)

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




