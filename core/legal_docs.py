from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path


LEGAL_DOC_FILENAMES = {
    "license": "LICENSE.md",
    "eula": "EULA.md",
    "notice": "NOTICE.md",
    "third_party_notices": "THIRD_PARTY_NOTICES.md",
    "security": "SECURITY.md",
    "contributing": "CONTRIBUTING.md",
}

LEGAL_DOC_LABELS = {
    "license": "License",
    "eula": "EULA",
    "notice": "Notice",
    "third_party_notices": "Third-Party Notices",
    "security": "Security Policy",
    "contributing": "Contributing",
}

_VERSION_PATTERN = re.compile(r"^Version:\s*(?P<version>.+?)\s*$", flags=re.IGNORECASE | re.MULTILINE)


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _resource_root() -> Path | None:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return None


def legal_doc_candidates(key: str) -> list[Path]:
    filename = LEGAL_DOC_FILENAMES[key]
    candidates = [
        project_root() / filename,
        project_root() / "legal_docs" / filename,
    ]
    resource_root = _resource_root()
    if resource_root is not None:
        candidates.extend(
            [
                resource_root / filename,
                resource_root / "legal_docs" / filename,
            ]
        )
    ordered = []
    seen = set()
    for candidate in candidates:
        normalized = str(candidate.resolve()) if candidate.exists() else str(candidate)
        if normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(candidate)
    return ordered


def legal_doc_path(key: str) -> Path | None:
    for candidate in legal_doc_candidates(key):
        if candidate.exists():
            return candidate
    return None


def legal_doc_text(key: str, fallback: str = "") -> str:
    path = legal_doc_path(key)
    if path is None:
        return fallback
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return fallback


def legal_doc_label(key: str) -> str:
    return LEGAL_DOC_LABELS.get(key, str(key or "").replace("_", " ").title())


def legal_doc_version_from_text(text: str, default: str = "unversioned") -> str:
    match = _VERSION_PATTERN.search(str(text or ""))
    if match:
        version = str(match.group("version") or "").strip()
        if version:
            return version
    return default


def legal_doc_version(key: str, default: str = "unversioned") -> str:
    return legal_doc_version_from_text(legal_doc_text(key, ""), default=default)


def legal_doc_sha256(key: str) -> str:
    path = legal_doc_path(key)
    if path is None:
        return ""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def legal_doc_manifest() -> dict:
    payload = {}
    for key, filename in LEGAL_DOC_FILENAMES.items():
        path = legal_doc_path(key)
        payload[key] = {
            "label": legal_doc_label(key),
            "filename": filename,
            "path": str(path) if path is not None else "",
            "version": legal_doc_version(key),
            "sha256": legal_doc_sha256(key),
            "exists": bool(path is not None and path.exists()),
        }
    return payload
