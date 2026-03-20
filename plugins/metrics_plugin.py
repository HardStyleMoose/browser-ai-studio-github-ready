from __future__ import annotations

from core.plugin_interface import BasePlugin


class Plugin(BasePlugin):
    plugin_id = "metrics_plugin"
    name = "Session Metrics"
    version = "1.0.0"
    description = "Tracks frame, decision, and execution counts for the current session."

    def __init__(self):
        self._subscriptions = []
        self._metrics = {"frames": 0, "decisions": 0, "executions": 0}

    def activate(self, context: dict) -> None:
        event_bus = context["event_bus"]
        self._subscribe(event_bus, "frame_captured", self._on_frame)
        self._subscribe(event_bus, "action_decided", self._on_decision)
        self._subscribe(event_bus, "action_executed", self._on_execution)

    def deactivate(self, context: dict) -> None:
        event_bus = context["event_bus"]
        for event_name, callback in self._subscriptions:
            event_bus.unsubscribe(event_name, callback)
        self._subscriptions.clear()

    def _subscribe(self, event_bus, event_name, callback):
        event_bus.subscribe(event_name, callback)
        self._subscriptions.append((event_name, callback))

    def _publish(self, callback_name, data=None):
        callback_name(data)

    def _on_frame(self, _data):
        self._metrics["frames"] += 1

    def _on_decision(self, _data):
        self._metrics["decisions"] += 1

    def _on_execution(self, _data):
        self._metrics["executions"] += 1
