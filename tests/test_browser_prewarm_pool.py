from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from distributed.browser_prewarm_pool import BrowserPrewarmPool
from distributed.cluster_worker_runtime import (
    ClusterWorkerConfig,
    ClusterWorkerRuntime,
    browser_prewarm_signature,
)


def _make_config(
    temp_dir: str,
    worker_id: str = "worker-1",
    standby_pool_slot: bool = False,
    mode: str = "browser",
    browser_url: str = "https://lom.joynetgame.com",
) -> ClusterWorkerConfig:
    return ClusterWorkerConfig(
        worker_id=worker_id,
        mode=mode,
        browser_url=browser_url,
        desktop_exe="",
        desktop_window_title="",
        capture_region={"left": 0, "top": 0, "width": 405, "height": 720},
        behavior_graph={},
        model_name="ppo_model",
        memory_limit_gb=2.0,
        cpu_limit_percent=200,
        target_fps=30,
        gpu_acceleration_enabled=False,
        mouse_enabled=True,
        keyboard_enabled=True,
        antiban_config={},
        quick_mode=False,
        watch_reward_ads=False,
        auto_learning_enabled=False,
        learning_store_dir=temp_dir,
        browser_dom_drive_mode="legacy",
        dom_confirmation_required=True,
        dom_live_cooldown_ms=850,
        dom_live_max_repeat_attempts=3,
        dom_evidence_weight=1.3,
        browser_prewarm_enabled=True,
        preview_target_fps=10,
        control_preview_target_fps=15,
        standby_pool_slot=standby_pool_slot,
        standby_slot_id="browser-standby-1" if standby_pool_slot else "",
        standby_idle_timeout_s=90.0,
    )


def _wait_for(predicate, timeout_s: float = 5.0, interval_s: float = 0.05):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval_s)
    return False


def _fake_start_browser_session(self):
    frame = np.full((720, 405, 3), 180, dtype=np.uint8)
    self._browser_capture_bounds = {"x": 0, "y": 0, "width": 405, "height": 720}
    self._browser_viewport_size = {"width": 405, "height": 720}
    self._last_frame_shape = frame.shape
    self._record_captured_frame(frame)
    self._update_snapshot(
        status="warming_capture",
        task="Warming Capture Stream",
        progress="Priming the first streamed game frame before autoplay starts",
        capture=self._capture_summary(),
    )


def _fake_capture_frame(self):
    frame = np.full((720, 405, 3), 160, dtype=np.uint8)
    self._last_frame_shape = frame.shape
    return frame


class BrowserStandbyRuntimeTests(unittest.TestCase):
    def test_standby_runtime_reaches_ready_and_can_be_claimed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            standby_config = _make_config(temp_dir, worker_id="standby-slot-1", standby_pool_slot=True)
            runtime = ClusterWorkerRuntime(standby_config)
            with patch.object(ClusterWorkerRuntime, "_start_browser_session", _fake_start_browser_session), \
                 patch.object(ClusterWorkerRuntime, "_close_browser_session", lambda self: None), \
                 patch.object(ClusterWorkerRuntime, "_capture_frame", _fake_capture_frame), \
                 patch.object(ClusterWorkerRuntime, "_frame_loading_marker", lambda self, frame, force=False: ""), \
                 patch.object(ClusterWorkerRuntime, "_resolve_game_state", lambda self, frame: ({}, 0.0)), \
                 patch.object(ClusterWorkerRuntime, "_execute_profile_actions", lambda self, state: None), \
                 patch.object(ClusterWorkerRuntime, "_execute_behavior_graph", lambda self, state: None), \
                 patch.object(ClusterWorkerRuntime, "_apply_cpu_budget", lambda self, work_elapsed, base_delay: 0.0):
                runtime.start()
                self.assertTrue(_wait_for(lambda: runtime.snapshot().get("status") == "standby_ready"))
                live_config = _make_config(temp_dir, worker_id="worker-live")
                self.assertTrue(runtime.can_claim_standby(live_config))
                self.assertTrue(runtime.claim_standby(live_config))
                self.assertTrue(_wait_for(lambda: runtime.snapshot().get("status") == "running"))
                self.assertEqual("ClusterWorker-worker-live", runtime.name)
                runtime.stop()
                runtime.join(timeout=4.0)

    def test_standby_claim_rejects_incompatible_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            standby_config = _make_config(temp_dir, worker_id="standby-slot-1", standby_pool_slot=True)
            runtime = ClusterWorkerRuntime(standby_config)
            with patch.object(ClusterWorkerRuntime, "_start_browser_session", _fake_start_browser_session), \
                 patch.object(ClusterWorkerRuntime, "_close_browser_session", lambda self: None):
                runtime.start()
                self.assertTrue(_wait_for(lambda: runtime.snapshot().get("status") == "standby_ready"))
                incompatible = _make_config(temp_dir, worker_id="worker-live", browser_url="https://example.com")
                self.assertFalse(runtime.can_claim_standby(incompatible))
                self.assertFalse(runtime.claim_standby(incompatible))
                runtime.stop()
                runtime.join(timeout=4.0)


class FakeRuntime:
    instances = []

    def __init__(self, config, log_callback=None):
        self.config = config
        self.log_callback = log_callback
        self._alive = False
        self._status = "standby_prewarming"
        self.ident = 1
        self.__class__.instances.append(self)

    def start(self):
        self._alive = True
        self._status = "standby_ready"

    def stop(self):
        self._alive = False
        self._status = "stopped"

    def join(self, timeout=None):
        return None

    def persist_now(self):
        return None

    def snapshot(self):
        return {
            "alive": self._alive,
            "status": self._status,
            "task": self._status,
            "progress": self._status,
            "last_error": "",
        }

    def standby_signature(self):
        return browser_prewarm_signature(self.config)

    def can_claim_standby(self, config):
        return self._alive and self._status == "standby_ready" and browser_prewarm_signature(config) == self.standby_signature()

    def claim_standby(self, config, log_callback=None):
        if not self.can_claim_standby(config):
            return False
        self.config = config
        self.log_callback = log_callback
        self._status = "standby_claimed"
        return True


class BrowserPrewarmPoolTests(unittest.TestCase):
    def test_pool_refills_after_claim(self):
        FakeRuntime.instances = []
        with tempfile.TemporaryDirectory() as temp_dir:
            config = _make_config(temp_dir)
            with patch("distributed.browser_prewarm_pool.ClusterWorkerRuntime", FakeRuntime):
                pool = BrowserPrewarmPool(temp_dir)
                self.assertTrue(pool.arm(config))
                self.assertEqual(1, len(FakeRuntime.instances))
                claimed = pool.claim(config)
                self.assertIsNotNone(claimed)
                self.assertEqual(1, len(FakeRuntime.instances))
                self.assertTrue(pool.arm(config))
                self.assertEqual(2, len(FakeRuntime.instances))

    def test_pool_rebuilds_incompatible_slot(self):
        FakeRuntime.instances = []
        with tempfile.TemporaryDirectory() as temp_dir:
            config = _make_config(temp_dir)
            incompatible = _make_config(temp_dir, browser_url="https://example.com")
            with patch("distributed.browser_prewarm_pool.ClusterWorkerRuntime", FakeRuntime):
                pool = BrowserPrewarmPool(temp_dir)
                pool.arm(config)
                self.assertEqual(1, len(FakeRuntime.instances))
                pool.arm(incompatible)
                self.assertEqual(2, len(FakeRuntime.instances))


@unittest.skip("Covered by the offscreen UI smoke pass outside unittest.")
class BrowserPrewarmPoolUiTests(unittest.TestCase):
    def test_cluster_page_arms_pool_in_browser_mode_only(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        from ui.main_window_fixed import MainWindow

        class FakePool:
            def __init__(self):
                self.arm_calls = []
                self.disarm_calls = []
                self._snapshot = {
                    "status": "disabled",
                    "detail": "Background standby browser prewarm is disabled.",
                    "claimed_by": "",
                }

            def arm(self, config):
                self.arm_calls.append(config)
                self._snapshot = {"status": "ready", "detail": "Standby browser session is ready to be claimed.", "claimed_by": ""}
                return True

            def disarm(self, reason=""):
                self.disarm_calls.append(reason)
                self._snapshot = {"status": "disabled", "detail": reason or "disabled", "claimed_by": ""}

            def snapshot(self):
                return dict(self._snapshot)

        app = QApplication.instance() or QApplication([])
        fake_pool = FakePool()
        with patch.object(MainWindow, "_browser_prewarm_pool", return_value=fake_pool):
            window = MainWindow()
            try:
                window.navigate_to("Cluster")
                app.processEvents()
                self.assertTrue(fake_pool.arm_calls)
                self.assertEqual("Standby ready", window.cluster_standby_value.text())

                if hasattr(window, "default_mode_selector"):
                    index = window.default_mode_selector.findData("desktop")
                    if index >= 0:
                        window.default_mode_selector.setCurrentIndex(index)
                window._apply_runtime_settings_from_ui()
                window.navigate_to("Cluster")
                app.processEvents()
                self.assertTrue(fake_pool.disarm_calls)
            finally:
                window.close()
                window.deleteLater()
                app.processEvents()


if __name__ == "__main__":
    unittest.main()
