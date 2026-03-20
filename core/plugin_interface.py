from __future__ import annotations

from abc import ABC, abstractmethod

class BasePlugin(ABC):
    plugin_id = "base_plugin"
    name = "Base Plugin"
    version = "1.0.0"
    description = ""

    @abstractmethod
    def activate(self, context: dict) -> None:
        raise NotImplementedError

    def deactivate(self, context: dict) -> None:
        return None

class EventSubscriptionPlugin(BasePlugin):
    def __init__(self):
        self._subscriptions = []

    def subscribe(self, event_bus, event_name, callback):
        event_bus.subscribe(event_name, callback)
        self._subscriptions.append((event_name, callback))

    def deactivate(self, context: dict) -> None:
        event_bus = context.get("event_bus")
        for event_name, callback in self._subscriptions:
            event_bus.unsubscribe(event_name, callback)
        self._subscriptions.clear()
