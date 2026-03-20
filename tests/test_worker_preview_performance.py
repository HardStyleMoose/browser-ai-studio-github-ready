from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from distributed.cluster_worker_runtime import ClusterWorkerConfig, ClusterWorkerRuntime


def _make_config(temp_dir: str) -> ClusterWorkerConfig:
    return ClusterWorkerConfig(
        worker_id="worker-preview-test",
        mode="browser",
        browser_url="https://lom.joynetgame.com",
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
    )


class WorkerPreviewRuntimeTests(unittest.TestCase):
    def _make_runtime(self):
        temp_dir = tempfile.TemporaryDirectory()
        runtime = ClusterWorkerRuntime(_make_config(temp_dir.name))
        runtime._temp_dir = temp_dir
        frame = np.full((720, 405, 3), 180, dtype=np.uint8)
        with runtime.state_lock:
            runtime._snapshot["status"] = "running"
            runtime._latest_frame = frame.copy()
            runtime._last_frame_shape = frame.shape
            runtime._latest_frame_at = 1.0
            runtime._browser_capture_bounds = {"x": 0, "y": 0, "width": 405, "height": 720}
        return runtime

    def test_preview_tier_decimates_until_interval(self):
        runtime = self._make_runtime()
        try:
            with patch("distributed.cluster_worker_runtime.time.time", side_effect=[100.0, 100.0]):
                first = runtime.preview_payload(None, tier="preview")
            self.assertIsNotNone(first["frame"])
            self.assertEqual(1.0, first["captured_at"])
            self.assertEqual("preview", first["preview_tier"])
            self.assertEqual(540, first["frame"].shape[0])

            with runtime.state_lock:
                runtime._latest_frame = np.full((720, 405, 3), 220, dtype=np.uint8)
                runtime._last_frame_shape = runtime._latest_frame.shape
                runtime._latest_frame_at = 2.0

            with patch("distributed.cluster_worker_runtime.time.time", side_effect=[100.05]):
                gated = runtime.preview_payload(first["captured_at"], tier="preview")
            self.assertIsNone(gated["frame"])
            self.assertIsNone(gated["captured_at"])

            with patch("distributed.cluster_worker_runtime.time.time", side_effect=[100.11, 100.11]):
                second = runtime.preview_payload(first["captured_at"], tier="preview")
            self.assertIsNotNone(second["frame"])
            self.assertEqual(2.0, second["captured_at"])
        finally:
            runtime._temp_dir.cleanup()

    def test_control_tier_uses_separate_cache_and_cadence(self):
        runtime = self._make_runtime()
        try:
            with patch("distributed.cluster_worker_runtime.time.time", side_effect=[200.0, 200.0]):
                preview_payload = runtime.preview_payload(None, tier="preview")
            self.assertIsNotNone(preview_payload["frame"])

            with runtime.state_lock:
                runtime._latest_frame = np.full((720, 405, 3), 90, dtype=np.uint8)
                runtime._last_frame_shape = runtime._latest_frame.shape
                runtime._latest_frame_at = 2.0

            with patch("distributed.cluster_worker_runtime.time.time", side_effect=[200.07]):
                preview_blocked = runtime.preview_payload(preview_payload["captured_at"], tier="preview")
            self.assertIsNone(preview_blocked["frame"])

            with patch("distributed.cluster_worker_runtime.time.time", side_effect=[200.07, 200.07]):
                control_payload = runtime.preview_payload(None, tier="control")
            self.assertIsNotNone(control_payload["frame"])
            self.assertEqual("control", control_payload["preview_tier"])
            self.assertEqual(2.0, control_payload["captured_at"])
            self.assertLessEqual(max(control_payload["frame"].shape[:2]), 720)
        finally:
            runtime._temp_dir.cleanup()

    def test_preview_is_suppressed_during_browser_prewarm_states(self):
        runtime = self._make_runtime()
        try:
            with runtime.state_lock:
                runtime._snapshot["status"] = "prewarming"
            payload = runtime.preview_payload(None, tier="preview")
            self.assertIsNone(payload["frame"])
            self.assertIsNone(payload["captured_at"])
            self.assertEqual("preview", payload["preview_tier"])
            self.assertEqual({"width": 405, "height": 720}, payload["logical_size"])
        finally:
            runtime._temp_dir.cleanup()

    def test_browser_capture_settings_stay_on_safe_defaults(self):
        runtime = self._make_runtime()
        try:
            self.assertAlmostEqual(0.90, runtime._browser_capture_scale, places=2)
            self.assertEqual(20, runtime._browser_capture_jpeg_quality())
        finally:
            runtime._temp_dir.cleanup()

    def test_runtime_snapshot_refresh_is_rate_limited(self):
        runtime = self._make_runtime()
        try:
            with patch("distributed.cluster_worker_runtime.time.perf_counter", side_effect=[10.0, 10.05, 10.21]):
                first = runtime._refresh_runtime_snapshot_if_due("running", progress="first")
                second = runtime._refresh_runtime_snapshot_if_due("running", progress="second")
                third = runtime._refresh_runtime_snapshot_if_due("running", progress="third")
            self.assertTrue(first)
            self.assertFalse(second)
            self.assertTrue(third)
        finally:
            runtime._temp_dir.cleanup()

    def test_browser_stream_reuses_fresh_cached_frame_when_payload_repeats(self):
        runtime = self._make_runtime()
        try:
            frame = np.full((720, 405, 3), 77, dtype=np.uint8)
            with runtime._browser_stream_lock:
                runtime._browser_stream_active = True
                runtime._browser_stream_payload = "A" * 160
                runtime._browser_stream_payload_at = 5.0
                runtime._browser_stream_latest_frame = frame.copy()
                runtime._browser_stream_latest_frame_at = 4.95
                runtime._browser_stream_last_signature = (160, ("A" * 160)[:64], ("A" * 160)[-64:])
            reused = runtime._consume_browser_stream_frame()
            self.assertIsNotNone(reused)
            self.assertEqual(frame.shape, reused.shape)
            self.assertEqual(5.0, runtime._browser_stream_last_consumed_at)
        finally:
            runtime._temp_dir.cleanup()

    def test_analysis_frame_is_smaller_for_30fps_browser_workers(self):
        runtime = self._make_runtime()
        try:
            frame = np.full((720, 405, 3), 50, dtype=np.uint8)
            analysis_frame = runtime._analysis_frame(frame)
            self.assertLessEqual(max(analysis_frame.shape[:2]), 224)
        finally:
            runtime._temp_dir.cleanup()


class WorkerPreviewWindowTests(unittest.TestCase):
    def test_resize_reuses_cached_pixmap_until_new_frame_arrives(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        from ui.main_window_fixed import WorkerPreviewWindow

        app = QApplication.instance() or QApplication([])
        window = WorkerPreviewWindow("worker-preview-test")
        try:
            frame = np.full((540, 303, 3), 120, dtype=np.uint8)
            payload = {
                "frame": frame,
                "captured_at": 1.0,
                "fps": 10.0,
                "source_size": {"width": 303, "height": 540},
                "logical_size": {"width": 405, "height": 720},
                "snapshot": {
                    "status": "running",
                    "task": "Idle",
                    "game": "Legends of Mushroom",
                    "profile": "Legends of Mushroom",
                    "strategy": "Test strategy",
                    "mode": "Browser",
                    "ads": "Skip Reward Ads",
                    "learning": "enabled",
                    "progress": "Ready",
                    "capture": "Headless Chromium | lom.joynetgame.com | game 405 x 720",
                    "cpu": "10%",
                },
            }
            window.show()
            app.processEvents()
            window.update_preview(payload, {"id": "worker-preview-test"})
            app.processEvents()

            self.assertIsNotNone(window._current_pixmap)
            self.assertIsNotNone(window._current_scaled_pixmap)
            initial_token = window.current_capture_token()

            with patch.object(window, "_update_cached_pixmap", wraps=window._update_cached_pixmap) as mocked_update:
                window.resize(760, 560)
                app.processEvents()
                self.assertEqual(initial_token, window.current_capture_token())
                mocked_update.assert_not_called()

            self.assertIsNotNone(window._current_scaled_pixmap)
            self.assertIsNotNone(window.preview_label.pixmap())
        finally:
            window.close()
            window.deleteLater()
            app.processEvents()


if __name__ == "__main__":
    unittest.main()
