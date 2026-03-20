from __future__ import annotations

import json
import re
import time
from pathlib import Path


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_") or "default"


class WorkerSessionStore:
    def __init__(self, root_dir: str | Path, game_key: str, worker_id: str):
        self.root_dir = Path(root_dir)
        self.game_key = _slugify(game_key)
        self.worker_id = _slugify(worker_id)
        self.path = self.root_dir / self.game_key / f"{self.worker_id}.json"
        self.data = {
            "version": 1,
            "game": self.game_key,
            "worker_id": self.worker_id,
            "created_at": time.time(),
            "updated_at": time.time(),
            "runs": 0,
            "lifetime_steps": 0,
            "lifetime_reward": 0.0,
            "last_session": {},
        }
        self.load()

    def load(self) -> dict:
        if not self.path.exists():
            return dict(self.data)
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return dict(self.data)
        if isinstance(payload, dict):
            self.data.update(payload)
        return dict(self.data)

    def save(self, session_payload: dict):
        self.root_dir.mkdir(parents=True, exist_ok=True)
        game_dir = self.root_dir / self.game_key
        game_dir.mkdir(parents=True, exist_ok=True)
        last_session = dict(session_payload or {})
        last_steps = int(last_session.get("steps", 0) or 0)
        last_reward = float(last_session.get("total_reward", 0.0) or 0.0)
        previous_steps = int(self.data.get("last_session", {}).get("steps", 0) or 0)
        previous_reward = float(self.data.get("last_session", {}).get("total_reward", 0.0) or 0.0)
        if last_steps < previous_steps:
            self.data["runs"] = int(self.data.get("runs", 0) or 0) + 1
        self.data["lifetime_steps"] = max(int(self.data.get("lifetime_steps", 0) or 0), previous_steps) + max(
            0, last_steps - previous_steps
        )
        self.data["lifetime_reward"] = max(
            float(self.data.get("lifetime_reward", 0.0) or 0.0),
            previous_reward,
        ) + max(0.0, last_reward - previous_reward)
        self.data["updated_at"] = time.time()
        self.data["last_session"] = last_session
        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        temp_path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        temp_path.replace(self.path)

    def summary(self) -> str:
        session = self.data.get("last_session", {})
        return (
            f"saved steps={int(session.get('steps', 0) or 0)} "
            f"reward={float(session.get('total_reward', 0.0) or 0.0):.2f} "
            f"lifetime={int(self.data.get('lifetime_steps', 0) or 0)}"
        )

    def snapshot(self) -> dict:
        return dict(self.data)
