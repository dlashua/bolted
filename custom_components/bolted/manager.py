"""
Manager for Bolted
"""
import logging
from homeassistant.core import HomeAssistant
from homeassistant import config as conf_util
from homeassistant.exceptions import HomeAssistantError
from homeassistant.loader import async_get_integration
import os
import sys
import importlib.util
from typing import Optional
from importlib import reload
from watchdog.events import PatternMatchingEventHandler
from watchdog.observers import Observer

from .const import (
    DOMAIN,
    FOLDER,
)

_LOGGER: logging.Logger = logging.getLogger(__package__)

class Manager():

    def __init__(self, hass: HomeAssistant):
        self.hass = hass
        self.available_apps: dict = {}
        self.available_apps_mtime: dict = {}
        self.loaded_app_modules: dict = {}
        self.loaded_app_instances: dict = {}
        
    async def stop_all(self):
        _LOGGER.debug('Stopping All Objects')
        apps_to_stop = []
        for app_instance_name in self.loaded_app_instances:
            apps_to_stop.append(app_instance_name)

        for app_instance_name in apps_to_stop:
            await self.stop_app(app_instance_name)

    async def stop_app(self, app_instance_name):
        this_app = self.loaded_app_instances.pop(app_instance_name)
        _LOGGER.debug('Killing %s', this_app)
        this_app['obj'].shutdown()
        del this_app

    async def reload(self):
        _LOGGER.debug("@reload")
        reloaded_apps = await self.refresh_available_apps()
        bolted = await self.get_component_config()
        apps_config = bolted.get('apps', {})

        apps_to_load = {}
        for app_instance_name in apps_config:
            app_config = apps_config[app_instance_name]
            if app_instance_name not in self.loaded_app_instances:
                apps_to_load[app_instance_name] = app_config
                continue

            if app_config != self.loaded_app_instances[app_instance_name]['config']:
                await self.stop_app(app_instance_name)
                apps_to_load[app_instance_name] = app_config
                continue

            if app_config['app'] in reloaded_apps:
                await self.stop_app(app_instance_name)
                apps_to_load[app_instance_name] = app_config
                continue                   

        for app_instance_name in apps_to_load:
            app_config = apps_to_load[app_instance_name]
            self.start_app(app_instance_name, app_config)

    async def refresh_available_apps(self):
        available_apps = {}
        available_apps_mtime = {}
        modules_path = self.hass.config.path(FOLDER)
        for (dirpath, dirnames, filenames) in os.walk(modules_path):
            _LOGGER.debug("walking %s", dirpath)
            for this_file in filenames:
                if this_file[-3:] == '.py':
                    app_name = this_file[0:-3]
                    app_name = app_name.replace('/','.')
                    app_path = dirpath + '/' + this_file
                    available_apps[app_name] = app_path
                    available_apps_mtime[app_name] = os.path.getmtime(app_path)

        apps_to_remove = []
        for app in self.available_apps:
            if app not in available_apps:
                _LOGGER.debug('App No Longer Available: %s', app)
                apps_to_remove.append(app)
                continue

            if self.available_apps_mtime[app] != available_apps_mtime[app]:
                _LOGGER.debug('App Has Changed: %s', app)
                apps_to_remove.append(app)
                continue

        for app in apps_to_remove:
            del self.available_apps[app]
            if app in self.loaded_app_modules:
                del self.loaded_app_modules[app]

        for app in available_apps:
            self.available_apps[app] = available_apps[app]
            self.available_apps_mtime[app] = available_apps_mtime[app]

        _LOGGER.debug('Available Apps %s', self.available_apps)

        return apps_to_remove

    async def start(self) -> bool:
        _LOGGER.debug("@start")

        await self.refresh_available_apps()

        bolted = await self.get_component_config()
        apps_config = bolted.get('apps', {})

        for app_instance_name in apps_config:
            app_config = apps_config[app_instance_name]
            self.start_app(app_instance_name, app_config)

        def reload_action():
            self.hass.add_job(self.reload)

        event_handler = EventHandler(['*.py'], reload_action)
        self._observer = Observer()
        self._observer.schedule(event_handler, self.hass.config.path(FOLDER), recursive=True)
        self._observer.start()
        return True


    def start_app(self, app_instance_name, app_config):
        if 'app' not in app_config:
            return None

        app_name = app_config['app']

        if app_name not in self.available_apps:
            _LOGGER.error('app "%s" is not valid', app_name)
            return None

        if app_name not in self.loaded_app_modules:
            this_module_spec = importlib.util.spec_from_file_location(
                app_name,
                self.available_apps[app_name]
            )

            self.loaded_app_modules[app_name] = importlib.util.module_from_spec(this_module_spec)
            this_module_spec.loader.exec_module(self.loaded_app_modules[app_name])
            _LOGGER.debug('Loaded Module %s', app_name)

        this_obj = self.loaded_app_modules[app_name].Module(self.hass, app_instance_name, app_config)
        _LOGGER.debug('Created App Instance %s: %s', app_instance_name, this_obj)
        self.loaded_app_instances[app_instance_name] = {
            "config": app_config,
            "module": app_name,
            "obj": this_obj
        }

        return True

    async def get_component_config(self) -> dict:
        _LOGGER.debug("@get_component_config")

        try: 
            hass_config_raw = await conf_util.async_hass_config_yaml(self.hass)
        except HomeAssistantError as err:
            _LOGGER.error(err)
            return {}

        # I have no idea what this does
        hass_config = await conf_util.async_process_component_config(
            self.hass, hass_config_raw, await async_get_integration(self.hass, DOMAIN)
        )

        bolted = hass_config[DOMAIN]

        return bolted

class EventHandler(PatternMatchingEventHandler):
    """Class for handling Watcher events."""

    def __init__(self, patterns, cb):
        """Initialise the EventHandler."""
        super().__init__(patterns, ignore_directories=True)
        self.cb = cb

    def process(self, event):
        """On Watcher event, fire callback"""
        _LOGGER.debug("process(%s)", event)
        self.cb()

    def on_modified(self, event):
        """File modified."""
        self.process(event)

    def on_moved(self, event):
        """File moved."""
        self.process(event)

    def on_created(self, event):
        """File created."""
        self.process(event)

    def on_deleted(self, event):
        """File deleted."""
        self.process(event)