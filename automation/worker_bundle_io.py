from __future__ import annotations

import json
import re
import time
import zipfile
from pathlib import Path


def _slugify(value: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "_", str(value or "").strip().lower()).strip("_")
    return text or "default"


def _atomic_write_json(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temp_path.replace(path)


def _guide_manifest_path(project_root: Path, profile_key: str) -> Path:
    return project_root / "data" / "guides" / f"{_slugify(profile_key)}.json"


def _learning_paths(project_root: Path, profile_key: str, game_key: str, worker_id: str) -> tuple[Path, Path]:
    root = project_root / "data" / "worker_learning"
    profile_slug = _slugify(profile_key)
    game_slug = _slugify(game_key)
    worker_slug = _slugify(worker_id)
    return (
        root / f"{profile_slug}__{game_slug}__{worker_slug}.json",
        root / f"{profile_slug}__{game_slug}.json",
    )


def _session_path(project_root: Path, game_key: str, worker_id: str) -> Path:
    return project_root / "data" / "worker_sessions" / _slugify(game_key) / f"{_slugify(worker_id)}.json"


def default_bundle_name(profile_key: str, game_key: str, worker_id: str) -> str:
    return f"{_slugify(profile_key)}__{_slugify(game_key)}__{_slugify(worker_id)}_bundle.zip"


def export_worker_bundle(
    project_root: str | Path,
    worker_id: str,
    profile_key: str,
    game_key: str,
    bundle_path: str | Path,
    model_path: str | Path | None = None,
) -> dict:
    root = Path(project_root)
    worker_slug = _slugify(worker_id)
    learning_path, legacy_learning_path = _learning_paths(root, profile_key, game_key, worker_id)
    if not learning_path.exists() and legacy_learning_path.exists():
        learning_path = legacy_learning_path
    session_path = _session_path(root, game_key, worker_id)
    guide_path = _guide_manifest_path(root, profile_key)
    bundle_file = Path(bundle_path)
    bundle_file.parent.mkdir(parents=True, exist_ok=True)

    model_entries: list[tuple[Path, str]] = []
    resolved_model_path = Path(model_path) if model_path else None
    if resolved_model_path is not None and not resolved_model_path.is_absolute():
        resolved_model_path = root / resolved_model_path
    if resolved_model_path and resolved_model_path.exists():
        if resolved_model_path.is_dir():
            for file_path in resolved_model_path.rglob("*"):
                if file_path.is_file():
                    model_entries.append((file_path, str(Path("model") / file_path.relative_to(resolved_model_path))))
        else:
            model_entries.append((resolved_model_path, str(Path("model") / resolved_model_path.name)))

    manifest = {
        "version": 1,
        "exported_at": time.time(),
        "worker": {
            "worker_id": worker_slug,
            "profile_key": _slugify(profile_key),
            "game_key": _slugify(game_key),
        },
        "files": {
            "learning": "worker_learning.json" if learning_path.exists() else "",
            "session": "worker_session.json" if session_path.exists() else "",
            "guide": "guide_manifest.json" if guide_path.exists() else "",
            "model": [arcname for _path, arcname in model_entries],
        },
    }

    with zipfile.ZipFile(bundle_file, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        bundle.writestr("manifest.json", json.dumps(manifest, indent=2))
        if learning_path.exists():
            bundle.write(learning_path, "worker_learning.json")
        if session_path.exists():
            bundle.write(session_path, "worker_session.json")
        if guide_path.exists():
            bundle.write(guide_path, "guide_manifest.json")
        for source_path, arcname in model_entries:
            bundle.write(source_path, arcname)

    return {
        "bundle_path": str(bundle_file),
        "worker_id": worker_slug,
        "profile_key": _slugify(profile_key),
        "game_key": _slugify(game_key),
        "included_model_files": len(model_entries),
        "included_learning": learning_path.exists(),
        "included_session": session_path.exists(),
    }


def import_worker_bundle(
    project_root: str | Path,
    bundle_path: str | Path,
    worker_id_override: str | None = None,
) -> dict:
    root = Path(project_root)
    bundle_file = Path(bundle_path)
    with zipfile.ZipFile(bundle_file, "r") as bundle:
        manifest = json.loads(bundle.read("manifest.json").decode("utf-8"))
        worker = dict(manifest.get("worker") or {})
        profile_key = str(worker.get("profile_key") or "default")
        game_key = str(worker.get("game_key") or "default")
        worker_id = _slugify(worker_id_override or worker.get("worker_id") or "worker-imported")

        learning_target, _legacy = _learning_paths(root, profile_key, game_key, worker_id)
        if "worker_learning.json" in bundle.namelist():
            learning_payload = json.loads(bundle.read("worker_learning.json").decode("utf-8"))
            if isinstance(learning_payload, dict):
                learning_payload["worker_id"] = worker_id
                learning_payload["profile"] = _slugify(profile_key)
                learning_payload["game"] = _slugify(game_key)
                _atomic_write_json(learning_target, learning_payload)

        session_target = _session_path(root, game_key, worker_id)
        if "worker_session.json" in bundle.namelist():
            session_payload = json.loads(bundle.read("worker_session.json").decode("utf-8"))
            if isinstance(session_payload, dict):
                session_payload["worker_id"] = worker_id
                session_payload["game"] = _slugify(game_key)
                _atomic_write_json(session_target, session_payload)

        guide_target = _guide_manifest_path(root, profile_key)
        if "guide_manifest.json" in bundle.namelist() and not guide_target.exists():
            guide_payload = json.loads(bundle.read("guide_manifest.json").decode("utf-8"))
            if isinstance(guide_payload, dict):
                _atomic_write_json(guide_target, guide_payload)

        imported_model_path = ""
        for name in bundle.namelist():
            if not name.startswith("model/") or name.endswith("/"):
                continue
            relative = Path(name).relative_to("model")
            destination = root / "models" / "imported_workers" / worker_id / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(bundle.read(name))
            if not imported_model_path:
                imported_model_path = str(destination)

    return {
        "bundle_path": str(bundle_file),
        "worker_id": worker_id,
        "profile_key": _slugify(profile_key),
        "game_key": _slugify(game_key),
        "model_path": imported_model_path,
        "learning_path": str(learning_target),
        "session_path": str(session_target),
    }
