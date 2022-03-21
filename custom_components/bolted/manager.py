"""
Manager for Bolted
"""
import logging
from homeassistant.core import HomeAssistant
from homeassistant import config as conf_util
from homeassistant.exceptions import HomeAssistantError
from homeassistant.loader import async_get_integration
import os
import importlib.util
from watchdog.events import PatternMatchingEventHandler
from watchdog.observers import Observer
import yaml
from homeassistant.requirements import async_process_requirements
import copy
from pydantic import BaseModel, Field, validator, ValidationError
import datetime
from typing import Optional, Dict, List
from types import ModuleType
from .types import HassApp

from .const import (
    DOMAIN,
    APP_DIR,
)

_LOGGER: logging.Logger = logging.getLogger(__package__)

class StrictBaseModel(BaseModel):
    class Config:
        extra = 'forbid'
        validate_assignment = True
        arbitrary_types_allowed = True

class AppManifest(StrictBaseModel):
    requirements: Optional[List[str]] = None
    options: Optional[Dict] = None

class App(StrictBaseModel):
    name: str
    path: str
    mtime: datetime.datetime
    manifest: AppManifest
    module: Optional[ModuleType] = None

class AppInstance(StrictBaseModel):
    name: str
    app: App
    instance: HassApp
    config: Dict = {}


class Manager():

    def __init__(self, hass: HomeAssistant):
        self.hass: HomeAssistant = hass
        self.apps: Dict[str, App] = dict()
        self.app_instances: Dict[str, AppInstance] = dict()
        
    async def stop_all(self):
        _LOGGER.debug('Stopping All Objects')
        apps_to_stop = []
        for app_instance_name in self.app_instances:
            apps_to_stop.append(app_instance_name)

        for app_instance_name in apps_to_stop:
            await self.stop_app(app_instance_name)

    async def stop_app(self, app_instance_name):
        try:
            this_app = self.app_instances.pop(app_instance_name)
        except KeyError:
            _LOGGER.debug('Tried to Kill %s but it was not loaded', app_instance_name)
        else:
            _LOGGER.debug('Killing %s', app_instance_name)
            this_app.instance.shutdown()
            del this_app

    async def reload(self):
        _LOGGER.debug("@reload")
        reloaded_apps = await self.refresh_available_apps()
        bolted = await self.get_component_config()
        try:
            apps_config = bolted.get('apps', None)
        except AttributeError:
            apps_config = []

        apps_to_load = {}
        seen = []
        for app_config in apps_config:
            try:
                app_name = app_config['app']
                app_instance_name = app_config['name']
            except:
                _LOGGER.warn("Required Keys (app, name) not present in config %s", app_config)
                continue

            if app_instance_name in seen:
                _LOGGER.warn("Multiple Apps share the same name: %s", app_instance_name)
                continue

            seen.append(app_instance_name)

            if app_name in reloaded_apps:
                await self.stop_app(app_instance_name)

            if app_instance_name in self.app_instances:
                if app_config != self.app_instances[app_instance_name].config:
                    await self.stop_app(app_instance_name)
                else:
                    continue

            apps_to_load[app_instance_name] = app_config

        app_instances_to_remove = []
        for app_instance_name in self.app_instances:
            if app_instance_name not in seen:
                app_instances_to_remove.append(app_instance_name)

        for app_instance_name in app_instances_to_remove:
                await self.stop_app(app_instance_name)

        for app_instance_name in apps_to_load:
            app_config = apps_to_load[app_instance_name]
            await self.start_app(app_instance_name, app_config)

    async def refresh_available_apps(self):
        available_apps: Dict[str, App] = dict()
        modules_path = self.hass.config.path(APP_DIR)
        for (dirpath, dirnames, filenames) in os.walk(modules_path):
            _LOGGER.debug("walking %s", dirpath)
            if "__init__.py" in filenames:
                module_path = dirpath[len(modules_path)+1:]
                app_path = dirpath + '/' + '__init__.py'
                app_name = module_path
                app_name = app_name.replace('/', '.')
                _LOGGER.debug('Found App Module app_name: %s, app_path: %s', app_name, app_path)
                app_manifest = {}
                if "manifest.yaml" in filenames:
                    with open(dirpath + "/manifest.yaml", 'r') as stream:
                        data_loaded = yaml.safe_load(stream)
                    app_manifest = data_loaded
                available_apps[app_name] = App(
                    name=app_name,
                    path=app_path,
                    mtime=os.path.getmtime(app_path),
                    manifest=app_manifest,
                )
                dirnames = []
                continue

            for this_file in filenames:
                if this_file[0] == "#":
                    continue
                if this_file[-3:] == '.py':
                    module_path = dirpath[len(modules_path)+1:]
                    app_path = dirpath + '/' + this_file
                    app_name = this_file[0:-3]
                    if len(module_path) != 0:
                        app_name = module_path + '/' + app_name
                    app_name = app_name.replace('/','.')
                    _LOGGER.debug('Found App app_name: %s, app_path: %s', app_name, app_path)
                    available_apps[app_name] = App(
                        name=app_name,
                        path=app_path,
                        mtime=os.path.getmtime(app_path),
                        manifest={}
                    )

            dirs_to_remove = []
            bad_dirs = [
                '__pycache__'
            ]
            for dir in dirnames:
                if dir in bad_dirs:
                    dirs_to_remove.append(dir)
                    continue
                if dir[0] == "#":
                    dirs_to_remove.append(dir)
                    continue

            for dir in dirs_to_remove:
                dirnames.remove(dir)

        apps_to_remove = []
        for app in self.apps:
            if app not in available_apps:
                _LOGGER.debug('App No Longer Available: %s', app)
                apps_to_remove.append(app)
                continue

            if self.apps[app].mtime != available_apps[app].mtime:
                _LOGGER.debug('App Has Changed: %s', app)
                apps_to_remove.append(app)
                continue

        for app in apps_to_remove:
            del self.apps[app]

        for app in available_apps:
            self.apps[app] = available_apps[app]

        _LOGGER.debug('Available Apps %s', self.apps)

        return apps_to_remove

    async def start(self) -> bool:
        _LOGGER.debug("@start")

        await self.reload()

        def reload_action():
            self.hass.add_job(self.reload)

        event_handler = EventHandler(['*.py', '*.yaml'], reload_action)
        self._observer = Observer()
        self._observer.schedule(event_handler, self.hass.config.path(APP_DIR), recursive=True)
        self._observer.start()
        return True


    async def start_app(self, app_instance_name, app_config):
        if 'app' not in app_config:
            return None

        app_name = app_config['app']

        if app_name not in self.apps:
            _LOGGER.error('app "%s" is not valid', app_name)
            return None

        this_app = self.apps[app_name]

        if this_app.module is None:
            if this_app.manifest.requirements is not None:
                _LOGGER.debug('Installing Requirements for %s: %s', app_name, this_app.manifest.requirements)
                await async_process_requirements(self.hass, f"{DOMAIN}.{app_name}", this_app.manifest.requirements)
            
            this_module_spec = importlib.util.spec_from_file_location(
                app_name,
                this_app.path
            )

            loading_module = importlib.util.module_from_spec(this_module_spec)
            try:
                this_module_spec.loader.exec_module(loading_module)
            except Exception as e:
                _LOGGER.error("Exception loading %s", app_name)
                _LOGGER.exception(e)
                return None
            this_app.module = loading_module
            _LOGGER.debug('Loaded Module %s', app_name)
            _LOGGER.debug('MANIFEST %s %s', app_name, this_app.manifest)

        options = {}
        if this_app.manifest.options is not None:
            options = this_app.manifest.options
        app_config_copy = copy.deepcopy(app_config)
        app_config_copy.pop('app')
        app_config_copy.pop('name')
        try:
            this_obj = this_app.module.App(self.hass, app_instance_name, app_config_copy, **options)
        except AttributeError:
            _LOGGER.error("%s doesn't have an 'App' class", app_name)
        else:
            _LOGGER.debug('Created App Instance %s: %s', app_instance_name, this_obj)
            self.app_instances[app_instance_name] = AppInstance(
                name=app_instance_name,
                app=this_app,
                instance=this_obj,
                config=app_config,
            )

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