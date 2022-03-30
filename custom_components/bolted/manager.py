"""
Manager for Bolted
"""
import copy
import datetime
import importlib
import importlib.util
import logging
import os
import sys
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

from .const import APP_DIR, CONFIG_DIR, DOMAIN, MODULE_DIR
from .helpers import time_it
from .types import BoltedApp

_LOGGER: logging.Logger = logging.getLogger(__package__)


class StrictBaseModel(BaseModel):
    class Config:
        extra = "forbid"
        validate_assignment = True
        arbitrary_types_allowed = True


class BoltedManifest(StrictBaseModel):
    requirements: Optional[List[str]] = None
    options: Optional[Dict] = None
    deps: List[str] = []


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
    deps: List[str] = []
    config: Dict = {}


class Manager:
    def __init__(self, hass: HomeAssistant):
        self.hass: HomeAssistant = hass
        self.modules: Dict[str, BoltInfo] = dict()
        self.apps: Dict[str, BoltInfo] = dict()
        self.app_instances: Dict[str, AppInstance] = dict()
        self.manifest_cache: Dict[str, BoltedManifest] = dict()

    def shutdown(self, event=None):
        _LOGGER.info("Shutting Down")
        _LOGGER.info("Stopping All Apps")
        self.stop_all()
        self._observer.stop()

    def stop_all(self):
        _LOGGER.debug("Stopping All Objects")
        apps_to_stop = []
        for app_instance_name in self.app_instances:
            apps_to_stop.append(app_instance_name)

        for app_instance_name in apps_to_stop:
            self.stop_app(app_instance_name)

    def stop_app(self, app_instance_name):
        try:
            this_app = self.app_instances.pop(app_instance_name)
        except KeyError:
            _LOGGER.debug(
                "Tried to Kill Bolt App %s but it was not loaded",
                app_instance_name,
            )
        else:
            _LOGGER.info("Killing Bolt App %s", app_instance_name)
            this_app.instance.shutdown()
            del this_app

    def get_manifest(self, filename):
        if filename in self.manifest_cache:
            return self.manifest_cache[filename]

        try:
            with open(filename, "r") as stream:
                data_loaded = yaml.safe_load(stream)
        except FileNotFoundError:
            data_loaded = {}
        if data_loaded is None:
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

        self.manifest_cache.clear()
        module_prefix = MODULE_DIR.replace("/", ".")
        app_prefix = APP_DIR.replace("/", ".")

        available_modules = self.get_available_bolts(MODULE_DIR)
        changed_modules = self.get_missing_changed(
            available_modules, self.modules
        )

        available_apps = self.get_available_bolts(APP_DIR)
        changed_apps = self.get_missing_changed(available_apps, self.apps)

        changed_app_instances = set()
        for app_instance_name, app_instance in self.app_instances.items():
            if app_instance.bolt.name in changed_apps:
                changed_app_instances.add(app_instance_name)
                continue

            for dep in app_instance.deps + app_instance.bolt.manifest.deps:
                if dep.startswith(app_prefix):
                    if dep[(len(app_prefix) + 1) :] in changed_apps:
                        changed_app_instances.add(app_instance_name)
                        changed_apps.add(app_instance.bolt.name)
                        continue

                if dep.startswith(module_prefix):
                    if dep[(len(module_prefix) + 1) :] in changed_modules:
                        changed_app_instances.add(app_instance_name)
                        changed_apps.add(app_instance.bolt.name)
                        continue

        for name in changed_modules:
            _LOGGER.warning("Module Changed: %s", name)
            full_name = f"{module_prefix}.{name}"
            if full_name in sys.modules:
                _LOGGER.warning("Refreshing Module: %s", full_name)
                try:
                    importlib.reload(sys.modules[full_name])
                except:
                    _LOGGER.warning("Could not reload %s", full_name)
                del sys.modules[full_name]
            if name in self.modules:
                del self.modules[name]

        for name, info in available_modules.items():
            if name not in self.modules:
                self.modules[name] = info

        for name in changed_apps:
            _LOGGER.warning("App Changed: %s", name)
            full_name = f"{app_prefix}.{name}"
            if full_name in sys.modules:
                _LOGGER.warning("Refreshing Module: %s", full_name)
                try:
                    importlib.reload(sys.modules[full_name])
                except:
                    _LOGGER.warning("Could not reload %s", full_name)
                del sys.modules[full_name]
            if name in self.apps:
                del self.apps[name]

        for name, info in available_apps.items():
            if name not in self.apps:
                self.apps[name] = info

        bolted = await self.get_component_config()
        try:
            apps_config = bolted.get("apps", [])
        except AttributeError:
            apps_config = []

        if apps_config is None:
            apps_config = []

        apps_to_load = []
        seen = set()
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

            seen.add(app_instance_name)

            if app_instance_name in changed_app_instances:
                apps_to_load.append(app_config)
                continue

            if app_instance_name not in self.app_instances:
                apps_to_load.append(app_config)
                continue

            if app_config != self.app_instances[app_instance_name].config:
                changed_app_instances.add(app_instance_name)
                apps_to_load.append(app_config)
                continue

        for app_instance_name in self.app_instances:
            if app_instance_name not in seen:
                changed_app_instances.add(app_instance_name)

        for app_instance_name in changed_app_instances:
            self.stop_app(app_instance_name)

        for app_config in apps_to_load:
            await self.start_app(app_config)

    def get_missing_changed(
        self, avail: Dict[str, BoltInfo], curr: Dict[str, BoltInfo]
    ):
        remove = set()
        for name, bolt in curr.items():
            if name not in avail:
                remove.add(name)
                continue

            if bolt.mtime != avail[name].mtime:
                remove.add(name)
                continue

            if bolt.manifest != avail[name].manifest:
                remove.add(name)
                continue

        return remove

    def get_available_bolts(self, dir):
        available_bolts: Dict[str, BoltInfo] = dict()
        bolt_path = self.hass.config.path(dir)
        for (dirpath, dirnames, filenames) in os.walk(bolt_path):
            _LOGGER.debug("walking %s", dirpath)
            if "__init__.py" in filenames:
                this_bolt = self.get_bolt_info(
                    dirpath, "__init__.py", bolt_path
                )
                available_bolts[this_bolt.name] = this_bolt
                dirnames.clear()
                continue

            for this_file in filenames:
                if this_file[0] == "#":
                    continue
                if this_file[-3:] == ".py":
                    this_bolt = self.get_bolt_info(
                        dirpath, this_file, bolt_path
                    )
                    available_bolts[this_bolt.name] = this_bolt

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
                py_event_handler,
                self.hass.config.path(APP_DIR),
                recursive=True,
            )
        else:
            _LOGGER.warn("Apps Directory does not exist: %s", APP_DIR)

        if os.path.exists(MODULE_DIR):
            self._observer.schedule(
                py_event_handler,
                self.hass.config.path(MODULE_DIR),
                recursive=True,
            )
        else:
            _LOGGER.warn("Modules Directory does not exist: %s", MODULE_DIR)

        if os.path.exists(CONFIG_DIR):
            self._observer.schedule(
                yaml_event_handler,
                self.hass.config.path(CONFIG_DIR),
                recursive=False,
            )
        else:
            _LOGGER.warn("Config Directory does not exist: %s", CONFIG_DIR)

        self._observer.start()
        return True

    async def start_app(self, app_config):
        if "app" not in app_config:
            return None

        app_instance_name = app_config["name"]
        app_name = app_config["app"]

        if app_name not in self.apps:
            _LOGGER.error('app "%s" is not valid', app_name)
            return None

        if app_instance_name in self.app_instances:
            _LOGGER.error(
                "attempting to start and already started app: %s",
                app_instance_name,
            )
            return None

        this_app = self.apps[app_name]

        if this_app.module is None:
            if this_app.manifest.requirements is not None:
                _LOGGER.info(
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
                f"bolted.apps.{app_name}", this_app.path
            )

            loading_module = importlib.util.module_from_spec(this_module_spec)
            try:
                this_module_spec.loader.exec_module(loading_module)
            except Exception as e:
                _LOGGER.error("Exception loading %s", app_name)
                _LOGGER.exception(e)
                return None
            this_app.module = loading_module
            _LOGGER.info("Loaded Module %s", app_name)
            _LOGGER.debug("MANIFEST %s %s", app_name, this_app.manifest)

        options = {}
        if this_app.manifest.options is not None:
            options = this_app.manifest.options
        app_config_copy = copy.deepcopy(app_config)
        app_config_copy.pop("app")
        app_config_copy.pop("name")
        try:
            this_obj_class = this_app.module.App
        except AttributeError:
            _LOGGER.error("%s doesn't have an 'App' class", app_name)
            return False

        try:
            deps = getattr(this_obj_class, "DEPS")
        except AttributeError:
            deps = []

        try:
            reqs = getattr(this_obj_class, "REQS")
        except AttributeError:
            reqs = None

        if reqs is not None:
            _LOGGER.info(
                "Installing Class Requirements for %s: %s",
                app_name,
                reqs,
            )
            _time_requirements = time_it()
            try:
                await async_process_requirements(
                    self.hass,
                    f"{DOMAIN}.{app_name}",
                    reqs,
                )
            except Exception as e:
                _LOGGER.error(
                    "Exception loading requirements for %s", app_name
                )
                _LOGGER.exception(e)
                return None
            _LOGGER.debug("Requirements took %s", _time_requirements())

        try:
            this_obj = this_obj_class(
                self.hass, app_instance_name, app_config_copy, **options
            )
        except AttributeError:
            _LOGGER.error(
                "Unable to Instantiate App %s %s", app_name, app_instance_name
            )
            return False
        else:
            self.app_instances[app_instance_name] = AppInstance(
                name=app_instance_name,
                bolt=this_app,
                instance=this_obj,
                config=app_config,
                deps=deps,
            )
            _LOGGER.info(
                "Created Bolt App Instance %s",
                self.app_instances[app_instance_name],
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
