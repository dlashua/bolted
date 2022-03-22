"""
Custom integration for Bolted

For more details about this integration, please refer to
https://github.com/dlashua/bolted
"""
import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers import discovery

from .const import DOMAIN, SERVICE_RELOAD
from .entity_manager import EntityManager
from .manager import Manager

_LOGGER: logging.Logger = logging.getLogger(__package__)

SCRIPTS = []

PLATFORMS = ["switch", "binary_sensor", "sensor"]


# hass_config is the entire Home Assistant Configuration as an OrderedDict
async def async_setup(hass: HomeAssistant, _hass_config) -> bool:
    _LOGGER.debug("@async_setup")

    manager = Manager(hass)

    async def reload_handler(_) -> None:
        return await manager.reload()

    hass.services.async_register(DOMAIN, SERVICE_RELOAD, reload_handler)

    EntityManager.init(hass)

    for platform_domain in PLATFORMS:
        hass.async_create_task(
            discovery.async_load_platform(
                hass,
                platform_domain,
                DOMAIN,
                {},
                _hass_config,
            )
        )

    return await manager.start()
