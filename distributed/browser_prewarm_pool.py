from __future__ import annotations

import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Callable

from distributed.cluster_worker_runtime import ClusterWorkerConfig, ClusterWorkerRuntime, browser_prewarm_signature


class BrowserPrewarmPool:
    def __init__(self, project_root: str | Path, log_callback: Callable[[str], None] | None = None):
        self.project_root = Path(project_root)
        self.log_callback = log_callback
        self._lock = threading.Lock()
        self._runtime: ClusterWorkerRuntime | None = None
        self._desired_signature: tuple | None = None
        self._status = "disabled"
        self._detail = "Background standby browser prewarm is disabled."
        self._last_error = ""
        self._claimed_by = ""
        self._ready_at = 0.0

    def _log(self, message: str):
        if callable(self.log_callback):
            self.log_callback(str(message))

    def arm(self, config: ClusterWorkerConfig) -> bool:
        signature = browser_prewarm_signature(config)
        with self._lock:
            self._desired_signature = signature
            runtime = self._runtime
            if runtime is not None:
                snapshot = runtime.snapshot()
                if not snapshot.get("alive"):
                    self._runtime = None
                    runtime = None
                elif str(snapshot.get("status") or "").strip().lower() in {"error", "stopped"}:
                    self._stop_runtime_locked(runtime)
                    self._runtime = None
                    runtime = None
                elif runtime.standby_signature() != signature:
                    self._status = "rebuilding"
                    self._detail = "Incompatible standby session detected. Rebuilding hidden browser prewarm."
                    self._stop_runtime_locked(runtime)
                    self._runtime = None
                    runtime = None
            if runtime is not None:
                self._refresh_from_runtime_locked(runtime)
                return False
            standby_config = replace(
                config,
                worker_id="standby-slot-1",
                standby_pool_slot=True,
                standby_slot_id="browser-standby-1",
            )
            runtime = ClusterWorkerRuntime(
                standby_config,
                log_callback=lambda message: self._log(message),
            )
            self._runtime = runtime
            self._status = "warming"
            self._detail = "Warming hidden browser session in the background."
            runtime.start()
            return True

    def disarm(self, reason: str = "Disabled"):
        with self._lock:
            runtime = self._runtime
            self._runtime = None
            self._desired_signature = None
            self._claimed_by = ""
            self._ready_at = 0.0
            self._status = "disabled"
            self._detail = str(reason or "Background standby browser prewarm is disabled.")
            if runtime is not None:
                self._stop_runtime_locked(runtime)

    def claim(self, config: ClusterWorkerConfig, log_callback: Callable[[str], None] | None = None) -> ClusterWorkerRuntime | None:
        with self._lock:
            runtime = self._runtime
            if runtime is None:
                self._status = "cold"
                self._detail = "No standby browser session is ready. Falling back to cold launch."
                return None
            if not runtime.can_claim_standby(config):
                self._refresh_from_runtime_locked(runtime)
                snapshot = runtime.snapshot()
                if runtime.standby_signature() != browser_prewarm_signature(config):
                    self._status = "rebuilding"
                    self._detail = "Standby browser session is incompatible with the current browser settings."
                elif str(snapshot.get("status") or "").strip().lower() != "standby_ready":
                    self._status = "warming"
                    self._detail = "Standby browser session is still warming."
                return None
            claimed = runtime.claim_standby(config, log_callback=log_callback)
            if not claimed:
                self._refresh_from_runtime_locked(runtime)
                return None
            self._runtime = None
            self._claimed_by = str(config.worker_id or "").strip()
            self._status = "claimed"
            self._detail = f"Standby browser claimed by {self._claimed_by or 'worker'}."
            self._ready_at = 0.0
            return runtime

    def snapshot(self) -> dict:
        with self._lock:
            runtime = self._runtime
            if runtime is not None:
                self._refresh_from_runtime_locked(runtime)
            return {
                "status": self._status,
                "detail": self._detail,
                "claimed_by": self._claimed_by,
                "ready_at": self._ready_at,
                "last_error": self._last_error,
                "has_runtime": runtime is not None,
            }

    def _refresh_from_runtime_locked(self, runtime: ClusterWorkerRuntime):
        snapshot = runtime.snapshot()
        raw_status = str(snapshot.get("status") or "").strip().lower()
        self._last_error = str(snapshot.get("last_error") or "").strip()
        if not snapshot.get("alive"):
            self._runtime = None
            if self._last_error:
                self._status = "error"
                self._detail = self._last_error
            else:
                self._status = "disabled"
                self._detail = "Standby browser session is not running."
            return
        if raw_status == "standby_ready":
            self._status = "ready"
            self._detail = "Standby browser session is ready to be claimed."
            if self._ready_at <= 0.0:
                self._ready_at = time.time()
        elif raw_status == "standby_claimed":
            self._status = "claimed"
            self._detail = str(snapshot.get("task") or "Standby browser session was claimed.")
        elif raw_status in {"standby_prewarming", "loading_game", "warming_capture", "prewarming"}:
            self._status = "warming"
            self._detail = str(snapshot.get("progress") or snapshot.get("task") or "Warming hidden browser session.")
        elif raw_status == "error":
            self._status = "error"
            self._detail = self._last_error or str(snapshot.get("task") or "Standby browser session hit an error.")
        elif raw_status == "stopped":
            self._status = "disabled"
            self._detail = str(snapshot.get("progress") or "Standby browser session stopped.")
        else:
            self._status = raw_status or "warming"
            self._detail = str(snapshot.get("progress") or snapshot.get("task") or "Standby browser session warming.")

    def _stop_runtime_locked(self, runtime: ClusterWorkerRuntime):
        try:
            persist_now = getattr(runtime, "persist_now", None)
            if callable(persist_now):
                persist_now()
        except Exception:
            pass
        runtime.stop()
        if runtime.ident is not None:
            runtime.join(timeout=4.0)
