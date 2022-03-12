from ast import Add
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

LISTEN_STATE_DEC = {}
_LOGGER: logging.Logger = logging.getLogger(__package__)

class AddDecorators(abc.ABCMeta):
    insta_id = 0

    @classmethod
    def __prepare__(metaclass, basename, extends, *args, **kwargs):
        my_id = metaclass.insta_id
        metaclass.insta_id = metaclass.insta_id + 1

        super().__prepare__(basename, extends, *args, **kwargs)
        _LOGGER.debug('PREPARE bn: %s, e: %s, %s %s', basename, extends, args, kwargs)
        def d_listen_state(entity_id):
            def inner(f):
                if my_id not in LISTEN_STATE_DEC:
                    LISTEN_STATE_DEC[my_id] = []
                LISTEN_STATE_DEC[my_id].append({
                    'entity_id': entity_id,
                    'func': f
                })
                return f

            return inner

        return {"d_listen_state": d_listen_state, "_LISTEN_ID": my_id}

    # def __new__(mcs, name, bases, attrs, **kwargs):
    #     x = ('  Meta.__new__(mcs=%s, name=%r, bases=%s, attrs=[%s], **%s)' % (
    #         mcs, name, bases, ', '.join(attrs), kwargs
    #     ))
    #     _LOGGER.debug(x)
    #     def d_listen_state(entity_id):
    #         def inner(f):
    #             _LOGGER.debug('here')
    #             return f

    #         return inner


    #     obj = super().__new__(mcs, name, bases, attrs)
    #     setattr(obj, "d_listen_state", d_listen_state)
    #     _LOGGER.debug('obj %s', obj)
    #     return obj

    


class HassModuleTypeBase(metaclass=abc.ABCMeta):

    def __init__(self, hass: HomeAssistant, name, config):
        self.hass = hass
        self.name = name
        self.config = config
        self._logging_name = f'{__package__}.{self._get_logger_name()}.{self.__module__}.{self.name}'
        self.logger = logging.getLogger(self._logging_name)
        self.listeners = []

        if self.hass.is_running:
            self.hass.add_job(self._startup)
        else:
            self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_START, self._startup)

        # self.setattr(self, 'listen_state', self.listen_state)

    async def _startup(self, _ = None):
        self.startup()

    def listen_state(self, entity_id, cb=None):
        def inner_listen_state(cb):
            cb_params = []
            cb_signature = inspect.signature(cb)
            for param in cb_signature.parameters:
                cb_params.append(param)

            @callback
            def inner_cb(event):
                self.logger.debug('listen_state event: %s', event)
                avail_kwargs = dict(
                    entity_id=event.data['entity_id'],
                    new_state=event.data['new_state'],
                    old_state=event.data['old_state']
                )

                kwargs = {}
                for key in cb_params:
                    kwargs[key] = avail_kwargs[key]

                cb(**kwargs)

            handle = async_track_state_change_event(self.hass, entity_id, inner_cb)
            self.listeners.append(handle)
        
        if cb is None:
            return inner_listen_state
        
        return inner_listen_state(cb)

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
