# Example Plugin for BrowserAI Studio

from core.plugin_interface import BasePlugin

class Plugin(BasePlugin):
    plugin_id = "example_plugin"
    name = "Example Plugin"
    version = "1.0.0"
    description = "Adds a custom action and state block to the behavior editor."

    def _logger(self, context):
        logger = context.get("logger") if isinstance(context, dict) else None
        return logger if hasattr(logger, "info") else None

    def activate(self, context):
        # Register a new block type
        node_registry = context.get("node_registry")
        if node_registry:
            node_registry.register({
                "custom_action": {
                    "title": "Custom Action",
                    "category": "Plugin",
                    "color": "#f43f5e",
                    "inputs": 1,
                    "outputs": 1,
                    "config": {"action": "custom", "target": [100, 100]},
                }
            })
        logger = self._logger(context)
        if logger is not None:
            logger.info("Example Plugin activated")

    def deactivate(self, context):
        logger = self._logger(context)
        if logger is not None:
            logger.info("Example Plugin deactivated")
