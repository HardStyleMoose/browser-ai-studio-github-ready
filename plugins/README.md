# Plugin Development Guide for BrowserAI Studio

## How Plugins Work
- Plugins extend the AI Lab with new block types, actions, UI panels, or integrations.
- Each plugin implements the `PluginInterface` and is auto-discovered from the `plugins/` folder.

## Creating a Plugin
1. Create a new Python file in `plugins/` (e.g., `my_plugin.py`).
2. Inherit from `PluginInterface` and implement the `register(self, app_context)` method.
3. Use `app_context` to access the node registry, event bus, or UI hooks.

### Example
```python
from core.plugin_interface import PluginInterface

class MyPlugin(PluginInterface):
    name = "My Custom Plugin"
    description = "Adds a new block type."

    def register(self, app_context):
        node_registry = app_context.get("node_registry")
        if node_registry:
            node_registry.register({
                "my_block": {
                    "title": "My Block",
                    "category": "Plugin",
                    "color": "#06b6d4",
                    "inputs": 1,
                    "outputs": 1,
                    "config": {"action": "my_action"},
                }
            })
```

## Plugin API
- `register(self, app_context)`: Called on load. Use `app_context` to register blocks, subscribe to events, or add UI.
- `app_context` keys: `node_registry`, `event_bus`, `logger`, `config`, etc.

## Hot Reloading
- Use the Plugins tab in the UI to reload plugins at runtime.

## Troubleshooting Plugins
- Ensure your plugin file is named uniquely and placed in the `plugins/` folder.
- If your plugin does not appear, check for syntax errors or missing dependencies.
- Use the Plugins tab to reload plugins after making changes.
- Plugins must inherit from `PluginInterface` and implement `register(self, app_context)`.
- If you need extra dependencies, list them in a `requirements.txt` in your plugin folder.

## Plugin Loading Notes
- Plugins are auto-discovered at startup and when reloading via the UI.
- Only Python files in `plugins/` are loaded; subfolders are not scanned by default.
- The `app_context` provides access to core services and UI hooks.

## Example Plugin (Updated)
```python
from core.plugin_interface import PluginInterface

class MyPlugin(PluginInterface):
    name = "My Custom Plugin"
    description = "Adds a new block type."

    def register(self, app_context):
        node_registry = app_context.get("node_registry")
        if node_registry:
            node_registry.register({
                "my_block": {
                    "title": "My Block",
                    "category": "Plugin",
                    "color": "#06b6d4",
                    "inputs": 1,
                    "outputs": 1,
                    "config": {"action": "my_action"},
                }
            })
        logger = app_context.get("logger")
        if logger:
            logger.info("MyPlugin loaded successfully.")
```

---

See `plugins/example_plugin.py` for a working example.
