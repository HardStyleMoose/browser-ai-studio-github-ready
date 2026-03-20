from __future__ import annotations

import json
import re
import time
from pathlib import Path


def _slugify(value: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "_", str(value or "").strip().lower()).strip("_")
    return text or "default"


class WorkerLearningMemory:
    def __init__(self, root_dir: str | Path, profile_key: str, game_key: str, worker_id: str | None = None):
        self.root_dir = Path(root_dir)
        self.profile_key = _slugify(profile_key)
        self.game_key = _slugify(game_key)
        self.worker_id = _slugify(worker_id or "default")
        self.legacy_path = self.root_dir / f"{self.profile_key}__{self.game_key}.json"
        self.path = self.root_dir / f"{self.profile_key}__{self.game_key}__{self.worker_id}.json"
        self._last_save = 0.0
        self._dirty = False
        self.data = {
            "version": 1,
            "profile": self.profile_key,
            "game": self.game_key,
            "worker_id": self.worker_id,
            "created_at": time.time(),
            "updated_at": time.time(),
            "steps": 0,
            "positive_steps": 0,
            "actions": {},
        }
        self.load()

    def load(self):
        source_path = self.path
        if not source_path.exists() and self.legacy_path.exists():
            source_path = self.legacy_path
        if not source_path.exists():
            return
        try:
            payload = json.loads(source_path.read_text(encoding="utf-8"))
        except Exception:
            return
        if isinstance(payload, dict):
            self.data.update(payload)
            self.data["worker_id"] = self.worker_id

    def score_for(self, action_key: str) -> float:
        entry = self.data.get("actions", {}).get(str(action_key), {})
        return float(entry.get("score", 0.0) or 0.0)

    def task_score(self, task_key: str) -> float:
        task_name = str(task_key or "").strip().lower()
        if not task_name:
            return 0.0
        return self.score_for(f"task:{task_name}")

    def ordered_indices(self, prefix: str, count: int) -> list[int]:
        scored = []
        for index in range(count):
            score = self.score_for(f"{prefix}:{index}")
            scored.append((index, score))
        scored.sort(key=lambda item: (-item[1], item[0]))
        return [index for index, _score in scored]

    def ranked_candidates(self, prefix: str, candidates: list[dict], key_name: str = "keyword") -> list[dict]:
        ranked = []
        for candidate in candidates:
            action_suffix = str(candidate.get(key_name, "") or "unknown").strip().lower()
            memory_score = self.score_for(f"{prefix}:{action_suffix}")
            enriched = dict(candidate)
            enriched["_memory_score"] = memory_score
            ranked.append(enriched)
        ranked.sort(key=lambda item: (float(item.get("score", 0.0)) + (item.get("_memory_score", 0.0) * 500.0)), reverse=True)
        return ranked

    def record(self, action_key: str, reward: float):
        action_key = str(action_key or "").strip()
        if not action_key:
            return
        actions = self.data.setdefault("actions", {})
        entry = actions.setdefault(
            action_key,
            {"count": 0, "score": 0.0, "avg_reward": 0.0, "last_reward": 0.0},
        )
        entry["count"] = int(entry.get("count", 0)) + 1
        reward_value = max(-3.0, min(5.0, float(reward or 0.0)))
        previous_avg = float(entry.get("avg_reward", 0.0))
        count = max(1, entry["count"])
        entry["avg_reward"] = previous_avg + ((reward_value - previous_avg) / count)
        previous_score = float(entry.get("score", 0.0))
        smoothing = 0.18 if reward_value >= 0 else 0.30
        entry["score"] = round((previous_score * 0.88) + (reward_value * smoothing), 4)
        entry["last_reward"] = reward_value
        self.data["steps"] = int(self.data.get("steps", 0)) + 1
        if reward_value > 0:
            self.data["positive_steps"] = int(self.data.get("positive_steps", 0)) + 1
        self.data["updated_at"] = time.time()
        self._dirty = True
        if self.data["steps"] % 4 == 0:
            self.save()

    def record_task(self, task_key: str, reward: float):
        task_name = str(task_key or "").strip().lower()
        if not task_name:
            return
        self.record(f"task:{task_name}", reward)

    def summary(self) -> str:
        actions = self.data.get("actions", {})
        if not actions:
            return "fresh profile"
        best_key = max(actions, key=lambda key: float(actions[key].get("score", 0.0)))
        best_entry = actions[best_key]
        return (
            f"best={best_key} score={float(best_entry.get('score', 0.0)):.2f} "
            f"steps={int(self.data.get('steps', 0))}"
        )

    def save(self, force: bool = False):
        if not force and not self._dirty:
            return
        self.root_dir.mkdir(parents=True, exist_ok=True)
        payload = dict(self.data)
        payload["updated_at"] = time.time()
        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temp_path.replace(self.path)
        self.data = payload
        self._last_save = time.time()
        self._dirty = False
