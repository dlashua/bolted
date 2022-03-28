import abc
import asyncio
from collections import OrderedDict
import datetime
from functools import wraps
import inspect
import io
import logging
from typing import Callable, Dict

import pendulum
import yaml

from homeassistant.components.device_automation.trigger import (
    async_attach_trigger as async_attach_device_automation_trigger,
)
from homeassistant.const import EVENT_HOMEASSISTANT_START
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import (
    TrackTemplate,
    TrackTemplateResult,
    async_track_state_change_event,
    async_track_template_result,
)
from homeassistant.helpers.service import async_set_service_schema
from homeassistant.helpers.template import Template, is_template_string

from .const import DOMAIN
from .entity_manager import EntityManager

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


# def match_sig(func):
#     func_params = []
#     func_signature = inspect.signature(func)

#     @wraps(func)
#     def inner_match_sig(**kwargs):
#         bound_arguments = func_signature.bind(**kwargs)

#         return func(*bound_arguments.args, **bound_arguments.kwargs)

#     return inner_match_sig


def match_sig(func):
    func_params = []
    func_signature = inspect.signature(func)
    for param in func_signature.parameters:
        func_params.append(param)

    @wraps(func)
    def inner_match_sig(**kwargs):
        if "kwargs" in func_params:
            kwargs_to_send = kwargs
        else:
            kwargs_to_send = {}
            for key in func_params:
                if key in kwargs:
                    kwargs_to_send[key] = kwargs.pop(key)
                else:
                    _LOGGER.warn("unknown argument %s in %s", key, func)
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


class BoltedBase(metaclass=abc.ABCMeta):
    def __init__(
        self, hass: HomeAssistant, name, config, automation_switch=False
    ):
        self.hass = hass
        self.name = name
        self.config = config
        self._logging_name = (
            f"{__package__}"
            f".{self._get_logger_name()}"
            f".{self.__module__}.{self.name}"
        )

        if "log_level" in self.config:
            self.call_service(
                "logger",
                "set_level",
                **{self._logging_name: self.config.pop("log_level")},
            )

        self.logger = logging.getLogger(self._logging_name)
        self.listeners = []
        self._registered_services = set()
        self._registered_entities = []
        self._automation_switch = automation_switch
        self.automation_switch = None

        if self.hass.is_running:
            self.hass.add_job(self._startup)
        else:
            self.hass.bus.async_listen_once(
                EVENT_HOMEASSISTANT_START, self._startup
            )

    async def get_entity(self, platform, name, **kwargs):
        this_entity = await EntityManager.get(self, platform, name, **kwargs)
        if this_entity not in self._registered_entities:
            self._registered_entities.append(this_entity)
        return this_entity

    def get_entity_by_id(self, entity_id):
        return EntityManager.get_by_entity_id(entity_id)

    def get_device_id(self, entity_id):
        return EntityManager.get_device_id(entity_id)

    def get_device_by_entity_id(self, entity_id):
        return EntityManager.get_device_by_entity_id(entity_id)

    def is_template(self, template):
        return is_template_string(template)

    @staticmethod
    def debounce(seconds: float):
        def deco_debounce(func: Callable):
            handles: Dict[BoltedBase, Callable] = {}

            @wraps(func)
            def inner_debounce(self: BoltedBase, *args, **kwargs):
                nonlocal handles

                def remove_handle_and_run():
                    nonlocal handles
                    nonlocal self
                    if self in handles:
                        del handles[self]

                    func(self, *args, **kwargs)

                if self in handles:
                    self.logger.debug("cancelling %s", handles[self])
                    handles[self]()

                handles[self] = self.run_in(seconds, remove_handle_and_run)

            return inner_debounce

        return deco_debounce

    async def _startup(self, _=None):
        if self._automation_switch is True:
            self.automation_switch = await self.get_entity(
                "switch", "automation", restore=True
            )
            self.logger.debug("Automation Switch Entity Created %s", self.name)

            async def turn_on(*args, **kwargs):
                await call_or_await(self.startup)
                self.automation_switch.set(True)

            async def turn_off(*args, **kwargs):
                self.shutdown()
                self.automation_switch.set(False)

            self.automation_switch.on_turn_on(turn_on)
            self.automation_switch.on_turn_off(turn_off)

            self.logger.debug(
                "Automation Switch for %s is %s",
                self.name,
                self.automation_switch.is_on,
            )
            self.logger.debug(
                "Automation Switch State for %s is %s",
                self.name,
                self.automation_switch.state,
            )
            if self.automation_switch.is_on is not False:
                await turn_on()
            else:
                await turn_off()

            return

        await call_or_await(self.startup)

    def state_get(self, entity_id):
        return self.hass.states.get(entity_id)

    def service_register(self, service, cb, schema=None):
        self.hass.services.async_register(DOMAIN, service, cb)
        this_schema = None
        desc = cb.__doc__
        if schema is not None:
            this_schema = schema
        elif desc is not None and desc.startswith("yaml"):
            try:
                desc = desc[4:].lstrip(" \n\r")
                file_desc = io.StringIO(desc)
                this_schema = (
                    yaml.load(file_desc, Loader=yaml.BaseLoader)
                    or OrderedDict()
                )
                file_desc.close()
            except Exception as exc:
                self.logger.error(
                    "Unable to decode yaml doc_string for %s(): %s",
                    self.name,
                    str(exc),
                )
                raise exc
        elif desc is not None and len(desc) > 0:
            this_schema = {
                "name": service,
                "description": desc,
            }
        else:
            this_schema = {"name": service, "description": "Bolted Service"}

        async_set_service_schema(self.hass, DOMAIN, service, this_schema)
        self._registered_services.add(service)

    async def listen_device_automation(self, config, automation_info, cb):
        """Not Tested. Difficult to use. Doesn't clean up."""
        if "domain" not in config:
            raise Exception("domain must be present in config")

        if "device_id" not in config:
            raise Exception("device_id must be present in config")

        x = await async_attach_device_automation_trigger(
            self.hass, config, cb, automation_info
        )
        return x

    def render_template(self, template):
        template = Template(template, self.hass)
        return template.async_render()

    def listen_template(
        self, value_template, cb, trigger_now=False, **listen_kwargs
    ):
        matched_cb = match_sig(cb)

        @callback
        @wraps(cb)
        def inner_cb(event, template_result):
            _LOGGER.debug(
                "listen_template template=%s, event=%s, template_result=%s",
                value_template,
                event,
                template_result,
            )
            if isinstance(template_result[0], TrackTemplateResult):
                result = template_result[0].result
                last_result = template_result[0].last_result
            else:
                result = template_result[0]
                last_result = None

            kwargs = listen_kwargs.copy()
            kwargs.update(
                dict(event=event, result=result, last_result=last_result)
            )

            matched_cb(**kwargs)

        template = Template(value_template, self.hass)
        info = async_track_template_result(
            self.hass,
            [TrackTemplate(template, None)],
            inner_cb,
        )

        self.listeners.append(info.async_remove)

        if trigger_now is True:
            inner_cb(event=None, template_result=[template.async_render()])

        return info.async_remove

    listen_template_func = make_cb_decorator(listen_template)

    def listen_state(self, entity_id, cb, trigger_now=False, **listen_kwargs):
        matched_cb = match_sig(cb)

        @callback
        @wraps(cb)
        def inner_cb(event):
            self.logger.debug("listen_state event: %s", event)
            kwargs = listen_kwargs.copy()
            kwargs.update(
                dict(
                    entity_id=event.data["entity_id"],
                    new_state=event.data["new_state"],
                    old_state=event.data["old_state"],
                )
            )

            matched_cb(**kwargs)

        handle = async_track_state_change_event(self.hass, entity_id, inner_cb)
        self.listeners.append(handle)

        if trigger_now is True:
            state = self.state_get(entity_id)
            kwargs = listen_kwargs.copy()
            kwargs.update(
                dict(
                    entity_id=entity_id,
                    new_state=state,
                    old_state=None,
                )
            )
            matched_cb(**kwargs)

        return handle

    listen_state_func = make_cb_decorator(listen_state)

    def listen_event(self, event_type, cb, filter={}, **kwargs):
        matched_cb = match_sig(cb)

        @callback
        @wraps(cb)
        def inner_cb(event):
            self.logger.debug("listen_event event: %s", event)
            if not recursive_match(filter, event.data):
                return
            kwargs.update(
                dict(
                    event_type=event.event_type,
                    event_data=event.data,
                )
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
            self.logger.debug("Killing %s", this_listener)
            this_listener()

        while self._registered_services:
            this_service = self._registered_services.pop()
            self.hass.services.async_remove(DOMAIN, this_service)

        while self._registered_entities:
            this_entity = self._registered_entities.pop()
            EntityManager.remove(this_entity)

    def __del__(self):
        return self.shutdown()

    # TO OVERRIDE
    @abc.abstractmethod
    def startup(self):
        pass

    @abc.abstractmethod
    def _get_logger_name(self):
        pass


class BoltedApp(BoltedBase):
    def _get_logger_name(self):
        return "app"


class BoltedScript(BoltedBase):
    def _get_logger_name(self):
        return "script"
