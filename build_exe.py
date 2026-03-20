from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from installer.build_support import create_release_payload


PROJECT_ROOT = Path(__file__).resolve().parent
DIST_DIR = PROJECT_ROOT / "dist"
INSTALLER_BUILD_DIR = PROJECT_ROOT / "installer" / "build"
APP_SPEC = PROJECT_ROOT / "pyinstaller.spec"
INSTALLER_SPEC = PROJECT_ROOT / "installer_wizard.spec"
APP_DIST_NAME = "BrowserAI_Lab"
PAYLOAD_ZIP = INSTALLER_BUILD_DIR / "app_payload.zip"
RELEASE_MANIFEST = INSTALLER_BUILD_DIR / "release_manifest.json"


def run_step(command: list[str], description: str):
    print(f"[BUILD] {description}")
    subprocess.run(command, cwd=PROJECT_ROOT, check=True)


def main():
    INSTALLER_BUILD_DIR.mkdir(parents=True, exist_ok=True)

    run_step([sys.executable, "-m", "playwright", "install", "chromium"], "Provisioning Playwright Chromium")
    run_step([sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm", str(APP_SPEC)], "Building application dist")

    app_dist_dir = DIST_DIR / APP_DIST_NAME
    manifest = create_release_payload(app_dist_dir, PAYLOAD_ZIP, RELEASE_MANIFEST)
    print(f"[BUILD] Created installer payload: {PAYLOAD_ZIP.name} ({manifest['file_count']} files)")

    run_step([sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm", str(INSTALLER_SPEC)], "Building installer wizard")

    installer_exe = DIST_DIR / "BrowerAI Studio Labs Setup.exe"
    if installer_exe.exists():
        print(f"[BUILD] Installer ready: {installer_exe}")
    else:
        print("[BUILD] Installer build completed. Check the dist folder for the setup executable.")


if __name__ == "__main__":
    main()
