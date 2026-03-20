from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path


def _slugify(value: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "_", str(value or "").strip().lower()).strip("_")
    return text or "item"


def _atomic_write(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=True)
    os.replace(temp_path, path)


class DomLivePolicyStore:
    def __init__(self, root_dir: str | Path, game: str, profile: str, worker_id: str):
        self.root_dir = Path(root_dir)
        self.game = str(game or "unknown_game").strip() or "unknown_game"
        self.profile = str(profile or "default").strip() or "default"
        self.worker_id = str(worker_id or "worker").strip() or "worker"
        self.path = (
            self.root_dir
            / _slugify(self.game)
            / _slugify(self.profile)
            / f"{_slugify(self.worker_id)}.json"
        )
        self.state = self.load()

    def default_state(self) -> dict:
        return {
            "saved_at": "",
            "game": self.game,
            "profile": self.profile,
            "worker_id": self.worker_id,
            "actions": {},
        }

    def load(self) -> dict:
        if not self.path.exists():
            return self.default_state()
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception:
            return self.default_state()
        if not isinstance(payload, dict):
            return self.default_state()
        payload.setdefault("actions", {})
        return payload

    def save(self):
        self.state["saved_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        _atomic_write(self.path, self.state)

    def _entry(self, screen_state: str, token: str) -> dict:
        actions = self.state.setdefault("actions", {})
        state_key = str(screen_state or "unknown").strip().lower() or "unknown"
        token_key = str(token or "").strip() or "unknown"
        state_bucket = actions.setdefault(state_key, {})
        return state_bucket.setdefault(
            token_key,
            {
                "screen_state": state_key,
                "token": token_key,
                "keyword": "",
                "label": "",
                "task_key": "",
                "attempts": 0,
                "successes": 0,
                "failures": 0,
                "neutrals": 0,
                "confirmation_rate": 0.0,
                "last_confirmation": "",
                "last_reason": "",
                "updated_at": 0.0,
            },
        )

    def record(
        self,
        screen_state: str,
        candidate: dict | None,
        outcome: str,
        reason: str = "",
        task_key: str = "",
    ) -> dict:
        candidate = dict(candidate or {})
        token = str(candidate.get("token") or candidate.get("selector_hint") or candidate.get("label") or "unknown").strip()
        entry = self._entry(screen_state, token)
        entry["attempts"] = int(entry.get("attempts", 0) or 0) + 1
        entry["keyword"] = str(candidate.get("keyword") or entry.get("keyword") or "").strip().lower()
        entry["label"] = str(candidate.get("label") or entry.get("label") or "").strip()
        entry["task_key"] = str(task_key or candidate.get("task_key") or entry.get("task_key") or "").strip().lower()
        normalized = str(outcome or "").strip().lower()
        if normalized == "success":
            entry["successes"] = int(entry.get("successes", 0) or 0) + 1
        elif normalized == "failure":
            entry["failures"] = int(entry.get("failures", 0) or 0) + 1
        else:
            entry["neutrals"] = int(entry.get("neutrals", 0) or 0) + 1
            normalized = "neutral"
        decisive = int(entry.get("successes", 0) or 0) + int(entry.get("failures", 0) or 0)
        entry["confirmation_rate"] = (
            round(float(entry.get("successes", 0) or 0) / max(1, decisive), 4) if decisive > 0 else 0.0
        )
        entry["last_confirmation"] = normalized
        entry["last_reason"] = str(reason or "").strip()
        entry["updated_at"] = time.time()
        return entry

    def score_adjustment(self, screen_state: str, candidate: dict | None) -> float:
        candidate = dict(candidate or {})
        token = str(candidate.get("token") or candidate.get("selector_hint") or candidate.get("label") or "unknown").strip()
        entry = (
            self.state.get("actions", {})
            .get(str(screen_state or "unknown").strip().lower() or "unknown", {})
            .get(token)
        )
        if not isinstance(entry, dict):
            return 0.0
        successes = int(entry.get("successes", 0) or 0)
        failures = int(entry.get("failures", 0) or 0)
        neutrals = int(entry.get("neutrals", 0) or 0)
        return max(-2.0, min(2.5, (successes * 0.45) - (failures * 0.55) + (neutrals * 0.05)))

    def summary_for_state(self, screen_state: str) -> dict:
        state_key = str(screen_state or "unknown").strip().lower() or "unknown"
        bucket = dict(self.state.get("actions", {}).get(state_key, {}) or {})
        rows = sorted(
            bucket.values(),
            key=lambda item: (
                -float(item.get("confirmation_rate", 0.0) or 0.0),
                -int(item.get("successes", 0) or 0),
                str(item.get("label") or ""),
            ),
        )
        return {
            "screen_state": state_key,
            "preferred_actions": rows[:8],
            "summary_lines": [
                f"Stored DOM-live actions: {len(rows)}",
                (
                    "Top stored action: "
                    + f"{rows[0].get('label', 'unknown')} "
                    + f"(success {int(rows[0].get('successes', 0) or 0)}, "
                    + f"rate {float(rows[0].get('confirmation_rate', 0.0) or 0.0):.2f})"
                    if rows
                    else "Top stored action: none"
                ),
            ],
        }
