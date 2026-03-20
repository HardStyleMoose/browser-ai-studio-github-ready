from __future__ import annotations

from core.plugin_interface import BasePlugin


from core.plugin_interface import EventSubscriptionPlugin

class Plugin(EventSubscriptionPlugin):
    plugin_id = "logging_plugin"
    name = "Activity Logger"
    version = "1.0.0"
    description = "Mirrors key runtime events onto the shared event bus log stream."

    def activate(self, context: dict) -> None:
        event_bus = context["event_bus"]
        self.subscribe(event_bus, "plugin_loaded", lambda data: event_bus.emit("plugin_log", f"Plugin loaded: {data['name']}"))
        self.subscribe(event_bus, "action_decided", lambda data: event_bus.emit("plugin_log", f"Action decided: {data}"))
        self.subscribe(event_bus, "action_executed", lambda data: event_bus.emit("plugin_log", f"Action executed: {data}"))
