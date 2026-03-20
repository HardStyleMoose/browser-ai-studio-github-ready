"""A simple event bus for decoupled communication."""

from typing import Any, Callable, Dict, List


class EventBus:
    def __init__(self):
        self.listeners: Dict[str, List[Callable[[Any], None]]] = {}

    def subscribe(self, event: str, callback: Callable[[Any], None]) -> None:
        """Subscribe to an event."""
        self.listeners.setdefault(event, []).append(callback)

    def unsubscribe(self, event: str, callback: Callable[[Any], None]) -> None:
        """Unsubscribe a callback from an event."""
        callbacks = self.listeners.get(event)
        if not callbacks:
            return
        try:
            callbacks.remove(callback)
        except ValueError:
            return
        if not callbacks:
            self.listeners.pop(event, None)

    def emit(self, event: str, data: Any = None) -> None:
        """Emit an event to all listeners."""
        for callback in list(self.listeners.get(event, [])):
            try:
                callback(data)
            except Exception:
                # Avoid breaking the event loop due to a single handler
                pass
