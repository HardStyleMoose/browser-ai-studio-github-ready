from __future__ import annotations

import json
import re
from pathlib import Path


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_") or "default"


def guide_manifest_path(project_root: str | Path, profile_key: str) -> Path:
    root = Path(project_root)
    slug = _slugify(profile_key)
    return root / "data" / "guides" / f"{slug}.json"


def load_game_guide(project_root: str | Path, profile_key: str) -> dict:
    path = guide_manifest_path(project_root, profile_key)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}

