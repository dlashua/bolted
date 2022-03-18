import asyncio
import logging

_LOGGER: logging.Logger = logging.getLogger(__package__)

class ObservableVariable():
    def __init__(self, value):
        self._value = value
        self._watchers = set()
        self._callbacks = set()

    @property
    def value(self):
        return self._value

    @value.setter
    def value(self, value):
        self._value = value
        for watcher in self._watchers:
            watcher.set()
        for callback in self._callbacks:
            callback()

    async def wait(self):
        watcher = asyncio.Event()
        self._watchers.add(watcher)

        await watcher.wait()

        self._watchers.remove(watcher)
        return self.value

    def wait_cb(self, cb):
        self._callbacks.add(cb)
        
