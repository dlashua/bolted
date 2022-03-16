import logging
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.core import callback
from homeassistant.const import (
    EVENT_HOMEASSISTANT_START,
)
from .const import (
    DOMAIN
)
import abc
from homeassistant.core import HomeAssistant
from functools import partial
import inspect
from homeassistant.loader import IntegrationNotFound, async_get_integration
import voluptuous as vol
from homeassistant.helpers.event import (
    TrackTemplate,
    async_call_later,
    async_track_template_result,
)
from homeassistant.helpers.template import Template
from functools import wraps
from .entity_manager import EntityManager


_LOGGER: logging.Logger = logging.getLogger(__package__)


def match_sig(func):
    func_params = []
    func_signature = inspect.signature(func)
    for param in func_signature.parameters:
        func_params.append(param)

    @wraps(func)
    def inner_match_sig(**kwargs):
        kwargs_to_send = {}
        for key in func_params:
            kwargs_to_send[key] = kwargs[key]

        return func(**kwargs_to_send)

    return inner_match_sig
    
def make_cb_decorator(orig_func):
    def inner_cb_decorator(*args, **kwargs):
        @wraps(orig_func)
        def inner_cb_decorator_func(func):
            return orig_func(cb=func, *args, **kwargs)
        return inner_cb_decorator_func
    return inner_cb_decorator
class HassModuleTypeBase(metaclass=abc.ABCMeta):

    def __init__(self, hass: HomeAssistant, name, config):
        self.hass = hass
        self.name = name
        self.config = config
        self._logging_name = f'{__package__}.{self._get_logger_name()}.{self.__module__}.{self.name}'
        self.logger = logging.getLogger(self._logging_name)
        self.listeners = []

        # self._template_trigger_platform = None

        if self.hass.is_running:
            self.hass.add_job(self._startup)
        else:
            self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_START, self._startup)

    def get_entity(self, platform, name):
        return EntityManager.get(self, platform, name)

    async def _startup(self, _ = None):
        # try:
        #     integration = await async_get_integration(self.hass, 'template')
        # except IntegrationNotFound:
        #     raise vol.Invalid(f"Invalid platform 'template' specified") from None
        # try:
        #     self._template_trigger_platform = integration.get_platform("trigger")
        # except ImportError:
        #     raise vol.Invalid(
        #         f"Integration 'template' does not provide trigger support"
        #     ) from None

        self.startup()

    def listen_template(self, value_template, cb):
        matched_cb = match_sig(cb)

        @callback
        @wraps(cb)
        def inner_cb(event, template_result):
            _LOGGER.debug('listen_template template=%s, event=%s, template_result=%s', value_template, event, template_result)
            kwargs = dict(
                event=event,
                result=template_result[0].result,
                last_result=template_result[0].last_result
            )

            matched_cb(**kwargs)

        _LOGGER.debug('hass is %s', self.hass)
        info = async_track_template_result(
            self.hass,
            [TrackTemplate(Template(value_template, self.hass), None)],
            inner_cb,
        )

        self.listeners.append(info.async_remove)

        return info.async_remove

    listen_template_func = make_cb_decorator(listen_template)

    def listen_state(self, entity_id, cb):
        matched_cb = match_sig(cb)

        @callback
        @wraps(cb)
        def inner_cb(event):
            self.logger.debug('listen_state event: %s', event)
            kwargs = dict(
                entity_id=event.data['entity_id'],
                new_state=event.data['new_state'],
                old_state=event.data['old_state']
            )

            matched_cb(**kwargs)

        handle = async_track_state_change_event(self.hass, entity_id, inner_cb)
        self.listeners.append(handle)
        
        return handle

    listen_state_func = make_cb_decorator(listen_state)

    def call_service(self, domain, service, **kwargs):
        self.hass.async_create_task(
            self.hass.services.async_call(domain, service, kwargs)
        )

    def add_job(self, target):
        future = self.hass.async_run_job(target)
        def cancel_add_job():
            future.cancel()

        def remove_listener(_):
            try:
                self.listeners.remove(cancel_add_job)
            except ValueError:
                pass

        future.add_done_callback(remove_listener)

        self.listeners.append(cancel_add_job)


    def shutdown(self):
        while self.listeners:
            this_listener = self.listeners.pop()
            self.logger.debug('Killing %s', this_listener)
            this_listener()

    def __del__(self):
        return self.shutdown()

    ###### TO OVERRIDE
    @abc.abstractmethod
    def startup(self):
        pass

    @abc.abstractmethod
    def _get_logger_name(self):
        pass

class HassApp(HassModuleTypeBase):
    def _get_logger_name(self):
        return 'app'

class HassScript(HassModuleTypeBase):
    pass
