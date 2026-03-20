"""Central configuration loader."""

import json
import os
from pathlib import Path

try:
    import yaml  # type: ignore
except ImportError:
    yaml = None


class ConfigManager:
    def __init__(self, path: str = "config/settings.yaml"):
        resolved_path = Path(path)
        if not resolved_path.is_absolute():
            project_root = Path(__file__).resolve().parent.parent
            resolved_path = project_root / resolved_path
        self.path = str(resolved_path)
        self.config = {}
        self.load()

    def load(self) -> None:
        if not os.path.exists(self.path):
            self.config = {}
            return

        with open(self.path, "r", encoding="utf-8") as f:
            if self.path.lower().endswith(".yaml") or self.path.lower().endswith(".yml"):
                if yaml:
                    self.config = yaml.safe_load(f) or {}
                else:
                    # Fallback: parse as JSON if YAML is not installed.
                    self.config = json.load(f)
            else:
                self.config = json.load(f)

    def get(self, key, default=None):
        return self.config.get(key, default)

    def set(self, key, value):
        self.config[key] = value

    def save(self, path: str | None = None) -> None:
        target = path or self.path
        resolved_target = Path(target)
        if not resolved_target.is_absolute():
            project_root = Path(__file__).resolve().parent.parent
            resolved_target = project_root / resolved_target
        os.makedirs(resolved_target.parent, exist_ok=True)
        with open(resolved_target, "w", encoding="utf-8") as f:
            if str(resolved_target).lower().endswith(".yaml") and yaml:
                yaml.safe_dump(self.config, f)
            else:
                json.dump(self.config, f, indent=2)
