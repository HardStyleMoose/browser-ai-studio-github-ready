from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

try:
    from playwright import __main__ as playwright_main
    from playwright.sync_api import sync_playwright
except Exception:  # pragma: no cover - optional runtime dependency
    playwright_main = None
    sync_playwright = None


_INSTALL_LOCK = threading.Lock()
_STATUS_CACHE = None
_STATUS_CACHE_AT = 0.0
_STATUS_CACHE_TTL_S = 45.0


def chromium_runtime_status() -> dict:
    global _STATUS_CACHE, _STATUS_CACHE_AT
    now = time.time()
    if _STATUS_CACHE is not None and (now - _STATUS_CACHE_AT) < _STATUS_CACHE_TTL_S:
        return dict(_STATUS_CACHE)
    if sync_playwright is None:
        status = {
            "available": False,
            "message": "Playwright is not installed.",
            "attempted_install": False,
        }
        _STATUS_CACHE = dict(status)
        _STATUS_CACHE_AT = now
        return status
    try:
        playwright = sync_playwright().start()
        try:
            executable_path = Path(playwright.chromium.executable_path)
            available = executable_path.exists()
        finally:
            playwright.stop()
    except Exception as exc:
        status = {
            "available": False,
            "message": str(exc),
            "attempted_install": False,
        }
        _STATUS_CACHE = dict(status)
        _STATUS_CACHE_AT = now
        return status
    status = {
        "available": bool(available),
        "message": "Playwright Chromium is ready." if available else "Playwright Chromium is not installed.",
        "attempted_install": False,
    }
    _STATUS_CACHE = dict(status)
    _STATUS_CACHE_AT = now
    return status


def ensure_playwright_chromium(install_if_missing: bool = True) -> dict:
    global _STATUS_CACHE, _STATUS_CACHE_AT
    status = chromium_runtime_status()
    if status["available"] or not install_if_missing:
        return status

    with _INSTALL_LOCK:
        status = chromium_runtime_status()
        if status["available"] or not install_if_missing:
            return status
        install_error = None
        try:
            _run_playwright_install()
        except Exception as exc:  # pragma: no cover - depends on network/runtime
            install_error = str(exc)
        _STATUS_CACHE = None
        _STATUS_CACHE_AT = 0.0
        final_status = chromium_runtime_status()
        final_status["attempted_install"] = True
        if final_status["available"]:
            final_status["message"] = "Playwright Chromium installed and ready."
            return final_status
        if install_error:
            final_status["message"] = f"Chromium install failed: {install_error}"
        return final_status


def _run_playwright_install():
    if playwright_main is None:
        raise RuntimeError("Playwright installer entrypoint is unavailable.")
    original_argv = list(sys.argv)
    try:
        sys.argv = ["playwright", "install", "chromium"]
        try:
            playwright_main.main()
        except SystemExit as exc:
            exit_code = exc.code if isinstance(exc.code, int) else (0 if exc.code in (None, False) else 1)
            if exit_code != 0:
                raise RuntimeError(f"'playwright install chromium' exited with code {exit_code}.")
    finally:
        sys.argv = original_argv
