import logging
from types import coroutine
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.core import callback
from homeassistant.const import (
    EVENT_HOMEASSISTANT_START,
)
import abc
from homeassistant.core import HomeAssistant
import inspect
from homeassistant.helpers.event import (
    TrackTemplate,
    async_track_template_result,
)
from homeassistant.helpers.template import Template
from functools import wraps
from .entity_manager import EntityManager
import asyncio
import pendulum
import datetime


_LOGGER: logging.Logger = logging.getLogger(__package__)

def recursive_match(search, source):
    if isinstance(search, dict):
        if not isinstance(source, dict):
            return False
        
        for key in search:
            if key not in source:
                return False
            if not recursive_match(search[key], source[key]):
                return False

    else:
        if search != source:
            return False

    return True    
    

def match_sig(func):
    func_params = []
    func_signature = inspect.signature(func)
    for param in func_signature.parameters:
        func_params.append(param)

    @wraps(func)
    def inner_match_sig(**kwargs):
        kwargs_to_send = {}
        for key in func_params:
            if key in kwargs:
                kwargs_to_send[key] = kwargs[key]
            else:
                _LOGGER.warn('unknown argument %s in %s', key, func)
                kwargs_to_send[key] = None

        return func(**kwargs_to_send)

    return inner_match_sig
    
def make_cb_decorator(orig_func):
    def inner_cb_decorator(*args, **kwargs):
        @wraps(orig_func)
        def inner_cb_decorator_func(func):
            return orig_func(cb=func, *args, **kwargs)
        return inner_cb_decorator_func
    return inner_cb_decorator

async def call_or_await(cb, *args, **kwargs):
    if asyncio.iscoroutinefunction(cb):
        await cb(*args, **kwargs)
    else:
        cb(*args, **kwargs)

class HassModuleTypeBase(metaclass=abc.ABCMeta):

    def __init__(self, hass: HomeAssistant, name, config):
        self.hass = hass
        self.name = name
        self.config = config
        self._logging_name = f'{__package__}.{self._get_logger_name()}.{self.__module__}.{self.name}'
        self.logger = logging.getLogger(self._logging_name)
        self.listeners = []
        self.automation_switch = None
        
        if self.hass.is_running:
            self.hass.add_job(self._startup)
        else:
            self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_START, self._startup)

    async def get_entity(self, platform, name, **kwargs):
        return await EntityManager.get(self, platform, name, **kwargs)

    async def _startup(self, _ = None):
        self.automation_switch = await self.get_entity('switch', 'automation', restore=True)
        self.logger.debug('Automation Switch Entity Created %s', self.name)
        async def turn_on(*args, **kwargs):
            await call_or_await(self.startup)
            self.automation_switch.set(True)
        async def turn_off(*args, **kwargs):
            self.shutdown()
            self.automation_switch.set(False)

        self.automation_switch.on_turn_on(turn_on)
        self.automation_switch.on_turn_off(turn_off)

        self.logger.debug('Automation Switch for %s is %s', self.name, self.automation_switch.is_on)
        self.logger.debug('Automation Switch State for %s is %s', self.name, self.automation_switch.state)
        if self.automation_switch.is_on is not False:
            await turn_on()
        else:
            await turn_off()


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

    def listen_event(self, event_type, cb, filter={}):
        matched_cb = match_sig(cb)

        @callback
        @wraps(cb)
        def inner_cb(event):
            self.logger.debug('listen_event event: %s', event)
            if not recursive_match(filter, event.data):
                return
            kwargs = dict(
                event_type=event.event_type,
                event_data=event.data,
            )

            matched_cb(**kwargs)
    
        handle = self.hass.bus.async_listen(event_type, inner_cb)
        self.listeners.append(handle)

        return handle

    listen_event_func = make_cb_decorator(listen_event)

    def fire_event(self, event_type, data={}):
        self.hass.bus.fire(event_type, data)

    def run_in(self, seconds, cb, *args, **kwargs):
        async def inner_run_in():
            await asyncio.sleep(seconds)
            await call_or_await(cb, *args, **kwargs)

        return self.add_job(inner_run_in())

    def run_at(self, time, cb, *args, **kwargs):
        now = pendulum.now()
        if isinstance(time, str):
            fut = pendulum.parse(time, tz=now.tz)
        elif isinstance(time, datetime.time):
            fut = pendulum.parse(str(time), tz=now.tz)
        
        seconds = (fut - now).in_seconds()

        if seconds <= 0:
            fut = fut.add(hours=24)
            seconds = (fut - now).in_seconds()

        return self.run_in(seconds, cb, *args, **kwargs)

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

        return cancel_add_job

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
