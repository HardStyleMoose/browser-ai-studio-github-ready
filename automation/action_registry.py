"""Registry for automation actions."""

from typing import Callable, Dict


class ActionRegistry:
    actions: Dict[str, Callable] = {}

    @classmethod
    def register(cls, name: str, func: Callable) -> None:
        cls.actions[name] = func

    @classmethod
    def execute(cls, name: str, *args, **kwargs):
        if name not in cls.actions:
            raise KeyError(f"Action not found: {name}")
        return cls.actions[name](*args, **kwargs)
