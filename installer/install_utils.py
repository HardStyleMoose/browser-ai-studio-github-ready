from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

from core.security_utils import sha256_file


APP_NAME = "BrowerAI Studio Labs"
INSTALL_MANIFEST_NAME = "browserai_install_manifest.json"


def resource_root() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.parent


def resolve_payload_path() -> Path:
    candidates = [
        resource_root() / "installer_payload" / "app_payload.zip",
        resource_root() / "installer" / "build" / "app_payload.zip",
        resource_root() / "build" / "installer_payload" / "app_payload.zip",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError("Installer payload archive was not found.")


def resolve_release_manifest_path() -> Path:
    candidates = [
        resource_root() / "installer_payload" / "release_manifest.json",
        resource_root() / "installer" / "build" / "release_manifest.json",
        resource_root() / "build" / "installer_payload" / "release_manifest.json",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError("Installer release manifest was not found.")


def load_release_manifest() -> dict:
    path = resolve_release_manifest_path()
    return json.loads(path.read_text(encoding="utf-8"))


def verify_release_payload(payload_zip: Path, payload_manifest: dict):
    expected_sha256 = str((payload_manifest or {}).get("payload_sha256") or "").strip().lower()
    if not expected_sha256:
        raise RuntimeError("Release manifest is missing payload_sha256.")
    actual_sha256 = sha256_file(payload_zip).lower()
    if actual_sha256 != expected_sha256:
        raise RuntimeError(
            "Installer payload integrity check failed. The payload hash does not match the release manifest."
        )
    return actual_sha256


def default_install_dir() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "Programs" / APP_NAME
    return Path.home() / "AppData" / "Local" / "Programs" / APP_NAME


def desktop_dir() -> Path:
    return Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop"


def start_menu_programs_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / APP_NAME
    return Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / APP_NAME


def payload_size_bytes() -> int:
    return resolve_payload_path().stat().st_size


def disk_free_bytes(target_dir: Path) -> int:
    probe = target_dir if target_dir.exists() else target_dir.parent
    probe.mkdir(parents=True, exist_ok=True)
    return shutil.disk_usage(probe).free


def format_bytes(value: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(max(0, value))
    for unit in units:
        if size < 1024.0 or unit == units[-1]:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{value} B"


def extract_payload(payload_zip: Path, install_dir: Path, progress_callback=None, log_callback=None):
    install_dir = Path(install_dir)
    install_dir.mkdir(parents=True, exist_ok=True)
    install_root = install_dir.resolve()
    with zipfile.ZipFile(payload_zip, "r") as archive:
        entries = [entry for entry in archive.infolist() if not entry.is_dir()]
        total = max(1, len(entries))
        for index, entry in enumerate(entries, start=1):
            destination = install_dir / entry.filename
            destination_resolved = destination.resolve()
            if not str(destination_resolved).startswith(str(install_root)):
                raise RuntimeError(f"Blocked unsafe payload entry: {entry.filename}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(entry, "r") as source, open(destination, "wb") as target:
                shutil.copyfileobj(source, target)
            if log_callback is not None:
                log_callback(f"Installed {entry.filename}")
            if progress_callback is not None:
                progress_callback(10 + int((index / total) * 60))


def create_windows_shortcut(
    shortcut_path: Path,
    target_path: Path,
    working_directory: Path,
    description: str,
    icon_path: Path | None = None,
):
    shortcut_path = Path(shortcut_path)
    shortcut_path.parent.mkdir(parents=True, exist_ok=True)
    icon_value = str(icon_path or target_path)
    command = (
        "$WshShell = New-Object -ComObject WScript.Shell; "
        f"$Shortcut = $WshShell.CreateShortcut('{str(shortcut_path)}'); "
        f"$Shortcut.TargetPath = '{str(target_path)}'; "
        f"$Shortcut.WorkingDirectory = '{str(working_directory)}'; "
        f"$Shortcut.Description = '{description}'; "
        f"$Shortcut.IconLocation = '{icon_value}'; "
        "$Shortcut.Save()"
    )
    subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            command,
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def write_install_manifest(
    install_dir: Path,
    payload_manifest: dict,
    app_executable: Path,
    created_shortcuts: list[str],
    legal_acceptance: dict | None = None,
) -> Path:
    manifest = {
        "app_name": APP_NAME,
        "install_dir": str(install_dir),
        "app_executable": str(app_executable),
        "installed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "payload_manifest": payload_manifest,
        "created_shortcuts": created_shortcuts,
        "legal_acceptance": dict(legal_acceptance or {}),
    }
    manifest_path = Path(install_dir) / INSTALL_MANIFEST_NAME
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest_path


def installed_app_icon(install_dir: Path) -> Path | None:
    candidates = [
        Path(install_dir) / "app" / "icon.ico",
        Path(install_dir) / "icon.ico",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def launch_installed_app(app_executable: Path):
    subprocess.Popen([str(app_executable)], cwd=str(app_executable.parent))
