"""
Manager for Bolted
"""
import copy
import datetime
import importlib.util
import logging
import os
from types import ModuleType
from typing import Dict, List, Optional

from pydantic import BaseModel
from watchdog.events import PatternMatchingEventHandler
from watchdog.observers import Observer
import yaml

from homeassistant import config as conf_util
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.loader import async_get_integration
from homeassistant.requirements import async_process_requirements

from .const import APP_DIR, DOMAIN, SCRIPT_DIR, CONFIG_DIR
from .helpers import time_it
from .types import BoltedApp, BoltedScript

_LOGGER: logging.Logger = logging.getLogger(__package__)


class StrictBaseModel(BaseModel):
    class Config:
        extra = "forbid"
        validate_assignment = True
        arbitrary_types_allowed = True


class BoltedManifest(StrictBaseModel):
    requirements: Optional[List[str]] = None
    options: Optional[Dict] = None


class BoltInfo(StrictBaseModel):
    name: str
    path: str
    mtime: datetime.datetime
    manifest: BoltedManifest
    module: Optional[ModuleType] = None


class AppInstance(StrictBaseModel):
    name: str
    bolt: BoltInfo
    instance: BoltedApp
    config: Dict = {}


class ScriptInstance(StrictBaseModel):
    name: str
    bolt: BoltInfo
    instance: BoltedScript


class Manager:
    def __init__(self, hass: HomeAssistant):
        self.hass: HomeAssistant = hass
        self.apps: Dict[str, BoltInfo] = dict()
        self.app_instances: Dict[str, AppInstance] = dict()
        self.scripts: Dict[str, BoltInfo] = dict()
        self.script_instances: Dict[str, ScriptInstance] = dict()
        self.manifest_cache: Dict[str, BoltedManifest] = dict()

    async def stop_all(self):
        _LOGGER.debug("Stopping All Objects")
        apps_to_stop = []
        for app_instance_name in self.app_instances:
            apps_to_stop.append(app_instance_name)

        for app_instance_name in apps_to_stop:
            await self.stop_app(app_instance_name)

        scripts_to_stop = []
        for script_instance_name in self.script_instances:
            scripts_to_stop.append(script_instance_name)

        for script_instance_name in scripts_to_stop:
            await self.stop_script(script_instance_name)

    async def stop_app(self, app_instance_name):
        try:
            this_app = self.app_instances.pop(app_instance_name)
        except KeyError:
            _LOGGER.debug(
                "Tried to Kill Bolt App %s but it was not loaded", app_instance_name
            )
        else:
            _LOGGER.debug("Killing Bolt App %s", app_instance_name)
            this_app.instance.shutdown()
            del this_app

    async def stop_script(self, script_instance_name):
        try:
            this_script = self.script_instances.pop(script_instance_name)
        except KeyError:
            _LOGGER.debug(
                "Tried to Kill Bolt Script %s but it was not loaded", script_instance_name
            )
        else:
            _LOGGER.debug("Killing Bolt Script %s", script_instance_name)
            this_script.instance.shutdown()
            del this_script

    def get_manifest(self, filename):
        if filename in self.manifest_cache:
            return self.manifest_cache[filename]

        try:
            with open(filename, "r") as stream:
                data_loaded = yaml.safe_load(stream)
        except FileNotFoundError:
            data_loaded = {}
        app_manifest = BoltedManifest(**data_loaded)
        self.manifest_cache[filename] = app_manifest
        return app_manifest

    def get_bolt_info(self, dirpath: str, filename: str, root_path: str):
        apppath = dirpath + "/" + filename
        appdir = dirpath[len(root_path) + 1 :]
        if filename == "__init__.py":
            appname = appdir
        else:
            appname = filename[0:-3]
            if len(appdir) != 0:
                appname = appdir + "/" + appname
        appname = appname.replace("/", ".")
        _LOGGER.debug(
            "Found Bolt  %s at %s",
            appname,
            apppath,
        )
        return BoltInfo(
            name=appname,
            path=apppath,
            mtime=os.path.getmtime(apppath),
            manifest=self.get_manifest(dirpath + "/manifest.yaml"),
        )

    async def reload(self):
        _LOGGER.debug("@reload")
        bolted = await self.get_component_config()

        await self.reload_apps(bolted)
        await self.reload_scripts()

    async def reload_scripts(self):
        available_scripts = await self.get_available_bolts(SCRIPT_DIR)

        scripts_to_remove = []
        for script in self.scripts:
            if script not in available_scripts:
                _LOGGER.debug("Script No Longer Available: %s", script)
                scripts_to_remove.append(script)
                continue

            if self.scripts[script].mtime != available_scripts[script].mtime:
                _LOGGER.debug("Script Has Changed: %s", script)
                scripts_to_remove.append(script)
                continue

        for script in scripts_to_remove:
            await self.stop_script(script)
            del self.scripts[script]

        for script in available_scripts:
            self.scripts[script] = available_scripts[script]

        for script in self.scripts:
            if script not in self.script_instances:
                await self.start_script(self.scripts[script])


    async def reload_apps(self, bolted):
        try:
            apps_config = bolted.get("apps", [])
        except AttributeError:
            apps_config = []

        if apps_config is None:
            apps_config = []

        available_apps = await self.get_available_bolts(APP_DIR)

        apps_to_remove = []
        for app in self.apps:
            if app not in available_apps:
                _LOGGER.debug("App No Longer Available: %s", app)
                apps_to_remove.append(app)
                continue

            if self.apps[app].mtime != available_apps[app].mtime:
                _LOGGER.debug("App Has Changed: %s", app)
                apps_to_remove.append(app)
                continue

        for app in apps_to_remove:
            del self.apps[app]

        for app in available_apps:
            self.apps[app] = available_apps[app]

        _LOGGER.debug("Available Apps %s", self.apps.keys())

        apps_to_load = {}
        seen = []
        for app_config in apps_config:
            try:
                app_name = app_config["app"]
                app_instance_name = app_config["name"]
            except KeyError:
                _LOGGER.warn(
                    "Required Keys (app, name) not present in config %s",
                    app_config,
                )
                continue

            if app_instance_name in seen:
                _LOGGER.warn(
                    "Multiple Apps share the same name: %s", app_instance_name
                )
                continue

            seen.append(app_instance_name)

            if app_name in apps_to_remove:
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

    async def get_available_bolts(self, dir):
        self.manifest_cache.clear()
        available_bolts: Dict[str, BoltInfo] = dict()
        bolt_path = self.hass.config.path(dir)
        for (dirpath, dirnames, filenames) in os.walk(bolt_path):
            _LOGGER.debug("walking %s", dirpath)
            if "__init__.py" in filenames:
                this_app = self.get_bolt_info(
                    dirpath, "__init__.py", bolt_path
                )
                available_bolts[this_app.name] = this_app
                dirnames.clear()
                continue

            for this_file in filenames:
                if this_file[0] == "#":
                    continue
                if this_file[-3:] == ".py":
                    this_app = self.get_bolt_info(
                        dirpath, this_file, bolt_path
                    )
                    available_bolts[this_app.name] = this_app

            dirs_to_remove = []
            bad_dirs = ["__pycache__"]
            for dir in dirnames:
                if dir in bad_dirs:
                    dirs_to_remove.append(dir)
                    continue
                if dir[0] == "#":
                    dirs_to_remove.append(dir)
                    continue

            for dir in dirs_to_remove:
                dirnames.remove(dir)
        
        return available_bolts


    async def start(self) -> bool:
        _LOGGER.debug("@start")

        await self.reload()

        def reload_action():
            self.hass.add_job(self.reload)

        yaml_event_handler = EventHandler(["*.yaml"], reload_action)
        py_event_handler = EventHandler(["*.py"], reload_action)
        self._observer = Observer()

        if os.path.exists(APP_DIR):
            self._observer.schedule(
                py_event_handler, self.hass.config.path(APP_DIR), recursive=True
            )
        else:
            _LOGGER.warn('Apps Directory does not exist: %s', APP_DIR)
        
        if os.path.exists(SCRIPT_DIR):
            self._observer.schedule(
                py_event_handler, self.hass.config.path(SCRIPT_DIR), recursive=True
            )
        else:
            _LOGGER.warn('Scripts Directory does not exist: %s', SCRIPT_DIR)

        if os.path.exists(CONFIG_DIR):
            self._observer.schedule(
                yaml_event_handler, self.hass.config.path(CONFIG_DIR), recursive=False
            )
        else:
            _LOGGER.warn('Config Directory does not exist: %s', CONFIG_DIR)


        self._observer.start()
        return True

    async def start_script(self, script: BoltInfo):
        if script.name not in self.scripts:
            _LOGGER.error('script "%s" is not valid', script.name)
            return None

        if script.module is None:
            if script.manifest.requirements is not None:
                _LOGGER.debug(
                    "Installing Requirements for %s: %s",
                    script.name,
                    script.manifest.requirements,
                )
                _time_requirements = time_it()
                try:
                    await async_process_requirements(
                        self.hass,
                        f"{DOMAIN}.{script.name}",
                        script.manifest.requirements,
                    )
                except Exception as e:
                    _LOGGER.error(
                        "Exception loading requirements for %s", script.name
                    )
                    _LOGGER.exception(e)
                    return None
                _LOGGER.debug("Requirements took %s", _time_requirements())

            this_module_spec = importlib.util.spec_from_file_location(
                script.name, script.path
            )

            loading_module = importlib.util.module_from_spec(this_module_spec)
            try:
                this_module_spec.loader.exec_module(loading_module)
            except Exception as e:
                _LOGGER.error("Exception loading %s", script.name)
                _LOGGER.exception(e)
                return None
            script.module = loading_module
            _LOGGER.debug("Loaded Module %s", script.name)
            _LOGGER.debug("MANIFEST %s %s", script.name, script.manifest)

        options = {}
        if script.manifest.options is not None:
            options = script.manifest.options

        try:
            this_obj = script.module.Script(
                self.hass, script.name, {}, **options
            )
        except AttributeError:
            _LOGGER.error("%s doesn't have an 'Script' class", script.name)
        else:
            _LOGGER.debug(
                "Created Bolt Script Instance %s: %s", script.name, this_obj
            )
            self.script_instances[script.name] = ScriptInstance(
                name=script.name,
                bolt=script,
                instance=this_obj
            )

        return True


    async def start_app(self, app_instance_name, app_config):
        if "app" not in app_config:
            return None

        app_name = app_config["app"]

        if app_name not in self.apps:
            _LOGGER.error('app "%s" is not valid', app_name)
            return None

        this_app = self.apps[app_name]

        if this_app.module is None:
            if this_app.manifest.requirements is not None:
                _LOGGER.debug(
                    "Installing Requirements for %s: %s",
                    app_name,
                    this_app.manifest.requirements,
                )
                _time_requirements = time_it()
                try:
                    await async_process_requirements(
                        self.hass,
                        f"{DOMAIN}.{app_name}",
                        this_app.manifest.requirements,
                    )
                except Exception as e:
                    _LOGGER.error(
                        "Exception loading requirements for %s", app_name
                    )
                    _LOGGER.exception(e)
                    return None
                _LOGGER.debug("Requirements took %s", _time_requirements())

            this_module_spec = importlib.util.spec_from_file_location(
                app_name, this_app.path
            )

            loading_module = importlib.util.module_from_spec(this_module_spec)
            try:
                this_module_spec.loader.exec_module(loading_module)
            except Exception as e:
                _LOGGER.error("Exception loading %s", app_name)
                _LOGGER.exception(e)
                return None
            this_app.module = loading_module
            _LOGGER.debug("Loaded Module %s", app_name)
            _LOGGER.debug("MANIFEST %s %s", app_name, this_app.manifest)

        options = {}
        if this_app.manifest.options is not None:
            options = this_app.manifest.options
        app_config_copy = copy.deepcopy(app_config)
        app_config_copy.pop("app")
        app_config_copy.pop("name")
        try:
            this_obj = this_app.module.App(
                self.hass, app_instance_name, app_config_copy, **options
            )
        except AttributeError:
            _LOGGER.error("%s doesn't have an 'App' class", app_name)
        else:
            _LOGGER.debug(
                "Created Bolt App Instance %s: %s", app_instance_name, this_obj
            )
            self.app_instances[app_instance_name] = AppInstance(
                name=app_instance_name,
                bolt=this_app,
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
            self.hass,
            hass_config_raw,
            await async_get_integration(self.hass, DOMAIN),
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
