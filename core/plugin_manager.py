from __future__ import annotations

import importlib.util
from pathlib import Path

from core.plugin_interface import BasePlugin


class PluginManager:
    def __init__(self, plugins_dir: str, event_bus, app_context=None):
        self.plugins_dir = Path(plugins_dir)
        self.event_bus = event_bus
        self.app_context = app_context or {}
        self.plugins = {}
        self.modules = {}

    def discover_plugin_files(self):
        if not self.plugins_dir.exists():
            return []
        return sorted(
            path for path in self.plugins_dir.glob("*.py")
            if path.name not in {"__init__.py"}
        )

    def load_all(self):
        loaded = []
        for plugin_file in self.discover_plugin_files():
            plugin = self.load_plugin(plugin_file)
            if plugin is not None:
                loaded.append(plugin)
        return loaded

    def reload_all(self):
        self.unload_all()
        return self.load_all()

    def load_plugin(self, plugin_file):
        plugin_path = Path(plugin_file)
        module_name = f"browser_ai_plugin_{plugin_path.stem}"
        spec = importlib.util.spec_from_file_location(module_name, plugin_path)
        if spec is None or spec.loader is None:
            return None

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        plugin_class = getattr(module, "Plugin", None)
        if plugin_class is None or not issubclass(plugin_class, BasePlugin):
            return None

        plugin = plugin_class()
        context = dict(self.app_context)
        context["event_bus"] = self.event_bus
        context["plugin_manager"] = self
        plugin.activate(context)

        self.plugins[plugin.plugin_id] = plugin
        self.modules[plugin.plugin_id] = module
        self.event_bus.emit("plugin_loaded", self.describe_plugin(plugin))
        return plugin

    def unload_all(self):
        context = dict(self.app_context)
        context["event_bus"] = self.event_bus
        context["plugin_manager"] = self
        for plugin_id, plugin in list(self.plugins.items()):
            try:
                plugin.deactivate(context)
            finally:
                self.event_bus.emit("plugin_unloaded", self.describe_plugin(plugin))
        self.plugins.clear()
        self.modules.clear()

    def describe_plugin(self, plugin):
        return {
            "id": plugin.plugin_id,
            "name": plugin.name,
            "version": plugin.version,
            "description": plugin.description,
        }

    def get_plugin_summaries(self):
        return [self.describe_plugin(plugin) for plugin in self.plugins.values()]
