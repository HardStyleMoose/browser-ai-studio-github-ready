from __future__ import annotations

import json
import time
import zipfile
from pathlib import Path

from core.legal_docs import LEGAL_DOC_FILENAMES, legal_doc_version_from_text
from core.security_utils import sha256_file


APP_DISPLAY_NAME = "BrowerAI Studio Labs"
DEFAULT_APP_EXECUTABLES = [
    "BrowerAI Studio Labs.exe",
    "BrowerAI_Studio_Labs.exe",
    "BrowserAI_Lab.exe",
]


def find_app_executable(app_dist_dir: Path) -> Path:
    app_dist_dir = Path(app_dist_dir)
    for name in DEFAULT_APP_EXECUTABLES:
        candidate = app_dist_dir / name
        if candidate.exists():
            return candidate
    executables = sorted(app_dist_dir.glob("*.exe"))
    if not executables:
        raise FileNotFoundError(f"No executable found in {app_dist_dir}")
    return executables[0]


def create_release_payload(app_dist_dir: Path, payload_zip_path: Path, manifest_path: Path) -> dict:
    app_dist_dir = Path(app_dist_dir)
    payload_zip_path = Path(payload_zip_path)
    manifest_path = Path(manifest_path)
    if not app_dist_dir.exists():
        raise FileNotFoundError(f"App dist directory not found: {app_dist_dir}")

    entry_executable = find_app_executable(app_dist_dir)
    payload_zip_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(payload_zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(app_dist_dir.rglob("*")):
            if path.is_file():
                archive.write(path, arcname=path.relative_to(app_dist_dir).as_posix())

    legal_docs = {}
    for key, filename in LEGAL_DOC_FILENAMES.items():
        candidate = app_dist_dir / "legal_docs" / filename
        if not candidate.exists():
            continue
        text = candidate.read_text(encoding="utf-8")
        legal_docs[key] = {
            "filename": filename,
            "sha256": sha256_file(candidate),
            "version": legal_doc_version_from_text(text),
        }

    if "eula" not in legal_docs or "notice" not in legal_docs:
        raise FileNotFoundError("Packaged legal docs are missing EULA.md or NOTICE.md from the application dist.")

    manifest = {
        "app_name": APP_DISPLAY_NAME,
        "entry_executable": entry_executable.name,
        "payload_name": payload_zip_path.name,
        "build_timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "payload_size_bytes": payload_zip_path.stat().st_size,
        "payload_sha256": sha256_file(payload_zip_path),
        "file_count": sum(1 for path in app_dist_dir.rglob("*") if path.is_file()),
        "eula_version": legal_docs["eula"]["version"],
        "eula_sha256": legal_docs["eula"]["sha256"],
        "notice_sha256": legal_docs["notice"]["sha256"],
        "legal_docs": legal_docs,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest
