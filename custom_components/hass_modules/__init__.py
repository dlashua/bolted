"""
Custom integration for HASS Modules

For more details about this integration, please refer to
https://github.com/dlashua/hass-modules
"""
import logging
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration
from .manager import Manager

from .const import (
    DOMAIN,
    SERVICE_RELOAD,
)

_LOGGER: logging.Logger = logging.getLogger(__package__)

SCRIPTS = []

# hass_config is the entire Home Assistant Configuration as an OrderedDict
async def async_setup(hass: HomeAssistant, _hass_config) -> bool:
    _LOGGER.debug("@async_setup")

    manager = Manager(hass)

    async def reload_handler(_) -> None:
        return await manager.reload()

    hass.services.async_register(DOMAIN, SERVICE_RELOAD, reload_handler)

    return await manager.start()

