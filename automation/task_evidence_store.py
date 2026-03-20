from __future__ import annotations

import json
import os
import re
import time
import uuid
from collections import Counter, defaultdict
from pathlib import Path


def _safe_slug(value: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "_", str(value or "").strip().lower()).strip("_")
    return text or "item"


def _atomic_json_write(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=True)
    os.replace(temp_path, path)


class TaskEvidenceStore:
    def __init__(self, project_root: str | Path):
        self.project_root = Path(project_root)
        self.root_dir = self.project_root / "data" / "action_evidence"

    def _normalize_record(self, payload: dict | None) -> dict:
        payload = dict(payload or {})
        timestamp = str(payload.get("timestamp") or "").strip() or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        record = {
            "record_id": str(payload.get("record_id") or uuid.uuid4().hex),
            "timestamp": timestamp,
            "game": str(payload.get("game") or "unknown_game").strip() or "unknown_game",
            "profile": str(payload.get("profile") or "default").strip() or "default",
            "screen_state": str(payload.get("screen_state") or "unknown").strip() or "unknown",
            "task_key": str(payload.get("task_key") or "unspecified").strip() or "unspecified",
            "runtime": str(payload.get("runtime") or "browser").strip() or "browser",
            "worker_id": str(payload.get("worker_id") or "").strip(),
            "session_id": str(payload.get("session_id") or "").strip(),
            "source": str(payload.get("source") or "guide_coach").strip() or "guide_coach",
            "dom_snapshot_summary": self._normalize_dom_summary(payload.get("dom_snapshot_summary")),
            "ocr_excerpt": str(payload.get("ocr_excerpt") or "").strip(),
            "chosen_candidate": self._normalize_candidate(payload.get("chosen_candidate")),
            "intended_action": self._normalize_intended_action(payload.get("intended_action")),
            "confirmed_outcome": str(payload.get("confirmed_outcome") or "neutral").strip().lower() or "neutral",
            "visible_transition": bool(payload.get("visible_transition", False)),
            "frame_hash": str(payload.get("frame_hash") or "").strip(),
            "screenshot_hash": str(payload.get("screenshot_hash") or "").strip(),
            "note": str(payload.get("note") or "").strip(),
        }
        if record["confirmed_outcome"] not in {"advanced", "neutral", "wrong_target"}:
            record["confirmed_outcome"] = "neutral"
        return record

    def _normalize_dom_summary(self, payload: dict | None) -> dict:
        payload = dict(payload or {})
        actionables = list(payload.get("top_actionables", []) or [])
        return {
            "url": str(payload.get("url") or "").strip(),
            "title": str(payload.get("title") or "").strip(),
            "viewport": dict(payload.get("viewport") or {}),
            "raw_text_summary": str(payload.get("raw_text_summary") or "").strip()[:1500],
            "actionable_count": int(payload.get("actionable_count", len(actionables)) or 0),
            "top_actionables": [self._normalize_candidate(entry) for entry in actionables[:8]],
            "screenshot_hash": str(payload.get("screenshot_hash") or "").strip(),
        }

    def _normalize_candidate(self, payload: dict | None) -> dict:
        payload = dict(payload or {})
        bounds = dict(payload.get("bounds") or {})
        return {
            "label": str(payload.get("label") or payload.get("text") or "").strip(),
            "kind": str(payload.get("kind") or payload.get("source") or payload.get("role") or "").strip(),
            "keyword": str(payload.get("keyword") or "").strip(),
            "token": str(payload.get("token") or "").strip(),
            "score": float(payload.get("score", payload.get("total_score", 0.0)) or 0.0),
            "bounds": {
                "x": int(bounds.get("x", payload.get("x", 0)) or 0),
                "y": int(bounds.get("y", payload.get("y", 0)) or 0),
                "width": int(bounds.get("width", payload.get("width", 0)) or 0),
                "height": int(bounds.get("height", payload.get("height", 0)) or 0),
            },
        }

    def _normalize_intended_action(self, payload: dict | None) -> dict:
        payload = dict(payload or {})
        point = payload.get("point")
        if isinstance(point, (list, tuple)) and len(point) >= 2:
            normalized_point = [int(point[0]), int(point[1])]
        else:
            normalized_point = None
        return {
            "label": str(payload.get("label") or "").strip(),
            "target_type": str(payload.get("target_type") or "other").strip().lower() or "other",
            "keyword": str(payload.get("keyword") or "").strip().lower(),
            "point": normalized_point,
            "browser_point": (
                [int(payload["browser_point"][0]), int(payload["browser_point"][1])]
                if isinstance(payload.get("browser_point"), (list, tuple)) and len(payload.get("browser_point")) >= 2
                else None
            ),
            "note": str(payload.get("note") or "").strip(),
        }

    def _record_path(self, record: dict) -> Path:
        parts = [
            self.root_dir,
            _safe_slug(record["game"]),
            _safe_slug(record["profile"]),
            _safe_slug(record["runtime"]),
            _safe_slug(record["screen_state"]),
            _safe_slug(record["task_key"]),
        ]
        directory = Path(*parts)
        filename = f"{time.strftime('%Y%m%d-%H%M%S', time.gmtime())}_{record['record_id']}.json"
        return directory / filename

    def record(self, payload: dict) -> dict:
        record = self._normalize_record(payload)
        path = self._record_path(record)
        record["storage_path"] = str(path)
        _atomic_json_write(path, record)
        return record

    def query(
        self,
        game: str | None = None,
        profile: str | None = None,
        screen_state: str | None = None,
        task_key: str | None = None,
        runtime: str | None = None,
    ) -> list[dict]:
        if not self.root_dir.exists():
            return []
        filters = {
            "game": str(game or "").strip().lower(),
            "profile": str(profile or "").strip().lower(),
            "screen_state": str(screen_state or "").strip().lower(),
            "task_key": str(task_key or "").strip().lower(),
            "runtime": str(runtime or "").strip().lower(),
        }
        results = []
        for path in sorted(self.root_dir.rglob("*.json")):
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    payload = json.load(handle)
            except Exception:
                continue
            record = self._normalize_record(payload)
            if any(filters[key] and str(record.get(key) or "").strip().lower() != filters[key] for key in filters):
                continue
            record["storage_path"] = str(path)
            results.append(record)
        results.sort(key=lambda item: (item.get("timestamp", ""), item.get("record_id", "")), reverse=True)
        return results

    def aggregate(
        self,
        game: str | None = None,
        profile: str | None = None,
        screen_state: str | None = None,
        runtime: str | None = None,
    ) -> dict:
        records = self.query(game=game, profile=profile, screen_state=screen_state, runtime=runtime)
        task_counter = Counter()
        keyword_counter = Counter()
        avoid_counter = Counter()
        preferred_counter = Counter()
        preferred_by_state = defaultdict(Counter)
        confirmation_counter = Counter()
        confirmation_by_state = defaultdict(Counter)
        broad_panel_examples = []
        successful_examples = []
        chosen_area_total = 0.0
        losing_area_total = 0.0
        area_samples = 0

        for record in records:
            intended = dict(record.get("intended_action") or {})
            chosen = dict(record.get("chosen_candidate") or {})
            target_type = str(intended.get("target_type") or "other").strip().lower() or "other"
            keyword = str(intended.get("keyword") or "").strip().lower()
            task_key_value = str(record.get("task_key") or "unspecified").strip().lower()
            state_key = str(record.get("screen_state") or "unknown").strip().lower() or "unknown"
            counter_key = (task_key_value, target_type, keyword or target_type)
            if record.get("confirmed_outcome") == "advanced":
                task_counter[counter_key] += 1
                keyword_counter[(chosen.get("kind") or target_type, keyword or target_type)] += 1
                preferred_key = (
                    state_key,
                    str(chosen.get("kind") or intended.get("target_type") or "unknown").strip().lower() or "unknown",
                    str(chosen.get("keyword") or keyword or intended.get("label") or target_type).strip().lower() or target_type,
                    str(chosen.get("label") or intended.get("label") or keyword or target_type).strip(),
                    task_key_value,
                )
                preferred_counter[preferred_key] += 1
                preferred_by_state[state_key][preferred_key] += 1
                successful_examples.append(record)
            elif record.get("confirmed_outcome") == "wrong_target":
                avoid_key = (
                    str(chosen.get("kind") or "unknown").strip().lower() or "unknown",
                    str(chosen.get("keyword") or chosen.get("label") or "unknown").strip().lower() or "unknown",
                )
                avoid_counter[avoid_key] += 1
                broad_panel_examples.append(record)
            confirmation_counter[str(record.get("confirmed_outcome") or "neutral").strip().lower() or "neutral"] += 1
            confirmation_by_state[state_key][str(record.get("confirmed_outcome") or "neutral").strip().lower() or "neutral"] += 1

            chosen_bounds = dict(chosen.get("bounds") or {})
            chosen_area = max(0, int(chosen_bounds.get("width", 0) or 0)) * max(0, int(chosen_bounds.get("height", 0) or 0))
            if chosen_area > 0:
                chosen_area_total += chosen_area
                area_samples += 1
            point = intended.get("point")
            if isinstance(point, list) and len(point) >= 2:
                losing_area_total += max(1.0, chosen_area / 3.0)

        task_hints = [
            {
                "task_key": task_key,
                "target_type": target_type,
                "keyword": keyword,
                "count": count,
            }
            for (task_key, target_type, keyword), count in task_counter.most_common(8)
        ]
        avoid_patterns = [
            {"kind": kind, "keyword": keyword, "count": count}
            for (kind, keyword), count in avoid_counter.most_common(8)
        ]
        screen_state_preferred_targets = [
            {
                "screen_state": state_key,
                "kind": kind,
                "keyword": keyword,
                "label": label,
                "task_key": task_key,
                "count": count,
            }
            for (state_key, kind, keyword, label, task_key), count in preferred_counter.most_common(12)
        ]
        preferred_targets_by_state = {}
        for state_key, bucket in preferred_by_state.items():
            preferred_targets_by_state[state_key] = [
                {
                    "screen_state": state_key,
                    "kind": kind,
                    "keyword": keyword,
                    "label": label,
                    "task_key": task_key,
                    "count": count,
                }
                for (state_key, kind, keyword, label, task_key), count in bucket.most_common(8)
            ]
        confirmation_heuristics = {
            "overall": {
                "advanced": int(confirmation_counter.get("advanced", 0) or 0),
                "neutral": int(confirmation_counter.get("neutral", 0) or 0),
                "wrong_target": int(confirmation_counter.get("wrong_target", 0) or 0),
            },
            "by_screen_state": {
                state_key: {
                    "advanced": int(bucket.get("advanced", 0) or 0),
                    "neutral": int(bucket.get("neutral", 0) or 0),
                    "wrong_target": int(bucket.get("wrong_target", 0) or 0),
                }
                for state_key, bucket in confirmation_by_state.items()
            },
        }
        summary_lines = [
            f"Evidence Records: {len(records)}",
            f"Successful Task Hints: {sum(item['count'] for item in task_hints)}",
            f"Avoid Patterns: {sum(item['count'] for item in avoid_patterns)}",
        ]
        if task_hints:
            summary_lines.append(
                "Top Hints: "
                + ", ".join(
                    f"{item['task_key']}->{item['target_type']} ({item['count']})"
                    for item in task_hints[:3]
                )
            )
        if avoid_patterns:
            summary_lines.append(
                "Avoid: "
                + ", ".join(f"{item['kind']}:{item['keyword']} ({item['count']})" for item in avoid_patterns[:3])
            )
        return {
            "record_count": len(records),
            "task_hints": task_hints,
            "avoid_patterns": avoid_patterns,
            "screen_state_preferred_targets": screen_state_preferred_targets,
            "preferred_targets_by_state": preferred_targets_by_state,
            "confirmation_heuristics": confirmation_heuristics,
            "summary_lines": summary_lines,
            "successful_examples": successful_examples[:6],
            "broad_panel_examples": broad_panel_examples[:6],
            "average_chosen_target_size": round(chosen_area_total / max(1, area_samples), 1),
            "average_losing_target_size": round(losing_area_total / max(1, area_samples), 1) if area_samples else 0.0,
        }

    def export_records(self, destination: str | Path, **filters) -> dict:
        destination = Path(destination)
        records = self.query(
            game=filters.get("game"),
            profile=filters.get("profile"),
            screen_state=filters.get("screen_state"),
            task_key=filters.get("task_key"),
            runtime=filters.get("runtime"),
        )
        payload = {
            "exported_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "filters": {key: value for key, value in filters.items() if value},
            "records": records,
        }
        _atomic_json_write(destination, payload)
        return payload

    def import_records(self, source: str | Path) -> dict:
        path = Path(source)
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        records = list(payload.get("records", [])) if isinstance(payload, dict) else list(payload or [])
        imported = []
        for entry in records:
            imported.append(self.record(entry))
        return {
            "imported_count": len(imported),
            "records": imported,
        }
