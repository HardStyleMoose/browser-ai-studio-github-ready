from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from automation.dom_analysis import DomAnalyzer
from automation.dom_live_policy_store import DomLivePolicyStore
from automation.n8n_sidecar import N8nSidecarManager
from automation.task_evidence_store import TaskEvidenceStore
from distributed.cluster_worker_runtime import ClusterWorkerConfig, ClusterWorkerRuntime


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


class TaskEvidenceAggregateTests(unittest.TestCase):
    def test_aggregate_exposes_preferred_targets_and_confirmation_heuristics(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = TaskEvidenceStore(temp_dir)
            store.record(
                {
                    "game": "legends_of_mushroom",
                    "profile": "Legends of Mushroom",
                    "screen_state": "reward_panel",
                    "task_key": "claim_rewards",
                    "runtime": "browser",
                    "confirmed_outcome": "advanced",
                    "chosen_candidate": {"label": "Claim", "kind": "dom", "keyword": "claim"},
                    "intended_action": {"label": "Claim", "target_type": "claim", "keyword": "claim", "point": [205, 520]},
                }
            )
            store.record(
                {
                    "game": "legends_of_mushroom",
                    "profile": "Legends of Mushroom",
                    "screen_state": "reward_panel",
                    "task_key": "claim_rewards",
                    "runtime": "browser",
                    "confirmed_outcome": "wrong_target",
                    "chosen_candidate": {"label": "Reward Panel", "kind": "panel", "keyword": "reward"},
                    "intended_action": {"label": "Claim", "target_type": "claim", "keyword": "claim", "point": [205, 520]},
                }
            )
            aggregate = store.aggregate(game="legends_of_mushroom", runtime="browser")
            self.assertIn("screen_state_preferred_targets", aggregate)
            self.assertIn("preferred_targets_by_state", aggregate)
            self.assertIn("confirmation_heuristics", aggregate)
            self.assertTrue(any(row["screen_state"] == "reward_panel" for row in aggregate["screen_state_preferred_targets"]))
            self.assertEqual(1, aggregate["confirmation_heuristics"]["overall"]["advanced"])
            self.assertEqual(1, aggregate["confirmation_heuristics"]["overall"]["wrong_target"])


class DomLiveRuntimeTests(unittest.TestCase):
    def test_dom_live_candidates_use_evidence_priority(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = ClusterWorkerConfig(
                worker_id="worker-test",
                mode="browser",
                browser_url="https://lom.joynetgame.com",
                desktop_exe="",
                desktop_window_title="",
                capture_region={"left": 0, "top": 0, "width": 405, "height": 720},
                behavior_graph={},
                model_name="ppo_model",
                memory_limit_gb=2.0,
                cpu_limit_percent=200,
                target_fps=20,
                gpu_acceleration_enabled=False,
                mouse_enabled=True,
                keyboard_enabled=True,
                antiban_config={},
                quick_mode=False,
                watch_reward_ads=False,
                auto_learning_enabled=False,
                learning_store_dir=temp_dir,
                browser_dom_drive_mode="dom_live_experimental",
                dom_confirmation_required=True,
                dom_live_cooldown_ms=850,
                dom_live_max_repeat_attempts=3,
                dom_evidence_weight=1.3,
                browser_prewarm_enabled=True,
                preview_target_fps=10,
                control_preview_target_fps=15,
            )
            runtime = ClusterWorkerRuntime(config)
            runtime.evidence_store = TaskEvidenceStore(temp_dir)
            runtime.dom_live_store = DomLivePolicyStore(Path(temp_dir) / "domlive", runtime._game_label(), runtime.game_profile.name, config.worker_id)
            runtime._page = object()
            runtime._browser_capture_bounds = {"x": 0, "y": 0, "width": 405, "height": 720}
            runtime._dom_analyzer = DomAnalyzer(_project_root())
            runtime._combined_visible_state_text = lambda: "claim reward continue"
            snapshot = {
                "url": "https://lom.joynetgame.com",
                "title": "Legends",
                "viewport": {"width": 405, "height": 720},
                "raw_text_summary": "claim reward continue",
                "actionable_count": 2,
                "actionables": [
                    {
                        "text": "Reward Panel",
                        "role": "button",
                        "selector_hint": "#panel",
                        "visible": True,
                        "enabled": True,
                        "confidence": 0.70,
                        "bounds": {"x": 28, "y": 90, "width": 340, "height": 360},
                        "center": [198, 270],
                        "token": "panel-token",
                    },
                    {
                        "text": "Claim",
                        "role": "button",
                        "selector_hint": "#claim",
                        "visible": True,
                        "enabled": True,
                        "confidence": 0.72,
                        "bounds": {"x": 156, "y": 520, "width": 90, "height": 36},
                        "center": [201, 538],
                        "token": "claim-token",
                    },
                ],
                "screenshot_hash": "abc123",
            }
            runtime.capture_dom_snapshot = lambda: dict(snapshot)
            runtime._latest_dom_snapshot = dict(snapshot)
            runtime.evidence_store.record(
                {
                    "game": runtime._game_label(),
                    "profile": runtime.game_profile.name,
                    "screen_state": "reward_panel",
                    "task_key": "claim_rewards",
                    "runtime": "browser",
                    "confirmed_outcome": "advanced",
                    "chosen_candidate": {"label": "Claim", "kind": "dom", "keyword": "claim"},
                    "intended_action": {"label": "Claim", "target_type": "claim", "keyword": "claim", "point": [201, 538]},
                }
            )
            candidates = runtime._dom_live_action_candidates({"screen_state": "reward_panel", "matched_keywords": ["claim", "reward"]})
            self.assertGreaterEqual(len(candidates), 2)
            self.assertEqual("Claim", candidates[0]["label"])
            self.assertEqual("reward_panel", candidates[0]["screen_state"])


class N8nSidecarTests(unittest.TestCase):
    def test_template_export_import_and_node_unavailable_status(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = N8nSidecarManager(temp_dir)
            templates = manager.load_templates()
            self.assertTrue(any(row["key"] == "provider_summary" for row in templates))
            export_path = Path(temp_dir) / "provider_summary.json"
            manager.export_template("provider_summary", export_path)
            self.assertTrue(export_path.exists())
            imported = manager.import_template(export_path)
            self.assertEqual("provider_summary", imported["key"])
            with patch.object(manager, "_find_node_path", return_value=""):
                status = manager.process_status()
            self.assertFalse(status["node_available"])

    def test_install_status_detects_local_runtime(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = N8nSidecarManager(temp_dir)
            install_dir = Path(temp_dir) / "data" / "n8n_runtime" / "node_runtime"
            package_dir = install_dir / "node_modules" / "n8n"
            package_dir.mkdir(parents=True, exist_ok=True)
            with open(package_dir / "package.json", "w", encoding="utf-8") as handle:
                json.dump({"name": "n8n", "version": "1.0.0"}, handle)
            entrypoint = package_dir / "bin" / "n8n"
            entrypoint.parent.mkdir(parents=True, exist_ok=True)
            entrypoint.write_text("console.log('n8n');", encoding="utf-8")
            status = manager.install_status()
            self.assertTrue(status["installed"])
            self.assertEqual("1.0.0", status["installed_version"])

    def test_legacy_docker_mode_migrates_to_node_managed_local(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = N8nSidecarManager(temp_dir)
            manager.apply_settings(
                {
                    "mode": "docker_sidecar",
                    "data_dir": "data/n8n_sidecar",
                    "open_editor_externally": True,
                }
            )
            state = manager.collect_state()
            self.assertEqual("node_managed_local", state["mode"])
            self.assertEqual("external", state["editor_mode"])
            self.assertIn("n8n_runtime", state["data_dir"])

    def test_n8n_widget_state_roundtrip(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        from ui.n8n_hub_widget import N8nHubWidget

        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as temp_dir:
            widget = N8nHubWidget(temp_dir)
            widget.set_saved_state(
                {
                    "mode": "node_managed_local",
                    "port": 5678,
                    "editor_url": "http://localhost:5678",
                    "install_dir": str(Path(temp_dir) / "n8n_runtime"),
                    "data_dir": str(Path(temp_dir) / "n8n_data"),
                    "auto_start": False,
                    "editor_mode": "external",
                    "open_editor_externally": True,
                    "last_template": "provider_summary",
                    "api_key_env_var": "N8N_API_KEY",
                }
            )
            state = widget.collect_state()
            self.assertEqual(5678, state["port"])
            self.assertEqual("node_managed_local", state["mode"])
            self.assertEqual("external", state["editor_mode"])
            self.assertEqual("provider_summary", state["last_template"])
            widget.deleteLater()
            app.processEvents()


if __name__ == "__main__":
    unittest.main()
