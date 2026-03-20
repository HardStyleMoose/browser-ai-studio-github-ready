from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

import numpy as np

from automation.dom_analysis import DomAnalyzer
from automation.provider_hub import ProviderCatalogService
from automation.task_evidence_store import TaskEvidenceStore


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _guide_frame() -> np.ndarray:
    frame = np.zeros((720, 405, 3), dtype=np.uint8)
    frame[:] = (18, 22, 22)
    return frame


class ProviderCatalogTests(unittest.TestCase):
    def test_parse_markdown_catalog_extracts_flags(self):
        service = ProviderCatalogService(_project_root())
        markdown = """
# Chat
- [FreeChat](https://freechat.example.com) OpenAI-compatible API, no rate limit. Signup required. Models: `gpt-4.1-mini`

# Media
- [Painter](https://painter.example.com) Free 100 daily credits.
"""
        entries = service.parse_markdown_catalog(markdown, source="sample")
        self.assertGreaterEqual(len(entries), 2)
        free_chat = next(entry for entry in entries if entry["name"] == "FreeChat")
        painter = next(entry for entry in entries if entry["name"] == "Painter")
        self.assertEqual("chat", free_chat["category"])
        self.assertTrue(free_chat["signup_required"])
        self.assertTrue(free_chat["supports_api"])
        self.assertIn("openai", free_chat["api_style"])
        self.assertIn("gpt-4.1-mini", free_chat["models"])
        self.assertTrue("limit" in free_chat["limit_note"].lower() or "rate" in free_chat["limit_note"].lower())
        self.assertEqual("media", painter["category"])

    def test_parse_site_html_extracts_entries(self):
        service = ProviderCatalogService(_project_root())
        html = """
<section>
  <h2>Voice</h2>
  <div>Speech API with daily free requests</div>
  <a href="https://voice.example.com">VoiceBox</a>
</section>
"""
        entries = service.parse_site_html(html, source="site")
        self.assertEqual(1, len(entries))
        self.assertEqual("VoiceBox", entries[0]["name"])
        self.assertEqual("voice", entries[0]["category"])


class DomAnalyzerTests(unittest.TestCase):
    def test_build_screen_action_map_prefers_small_reward_action(self):
        analyzer = DomAnalyzer(_project_root())
        snapshot = analyzer.normalize_snapshot(
            {
                "url": "https://lom.joynetgame.com",
                "title": "Legends",
                "viewport": {"width": 405, "height": 720},
                "raw_text_summary": "claim reward continue",
                "actionables": [
                    {
                        "text": "Reward Panel",
                        "role": "button",
                        "selector_hint": "#panel",
                        "visible": True,
                        "enabled": True,
                        "confidence": 0.72,
                        "bounds": {"x": 20, "y": 60, "width": 360, "height": 420},
                    },
                    {
                        "text": "Claim",
                        "role": "button",
                        "selector_hint": "#claim",
                        "visible": True,
                        "enabled": True,
                        "confidence": 0.70,
                        "bounds": {"x": 150, "y": 520, "width": 92, "height": 38},
                    },
                ],
            }
        )
        action_map = analyzer.build_screen_action_map(
            snapshot,
            ocr_boxes=[{"text": "Claim", "keyword": "claim", "confidence": 75.0, "x": 152, "y": 522, "width": 80, "height": 30}],
            screen_state="reward_panel",
            guide_analysis={"screen_state": "reward_panel", "matched_keywords": ["claim", "reward"]},
            evidence_summary={"summary_lines": [], "task_hints": [], "avoid_patterns": []},
        )
        merged = action_map["merged_actions"]
        self.assertGreaterEqual(len(merged), 2)
        self.assertEqual("Claim", merged[0]["label"])
        self.assertIn(merged[0]["source"], {"dom", "ocr"})


class TaskEvidenceStoreTests(unittest.TestCase):
    def test_record_aggregate_and_export_import_roundtrip(self):
        with tempfile.TemporaryDirectory() as temp_dir, tempfile.TemporaryDirectory() as import_dir:
            store = TaskEvidenceStore(temp_dir)
            advanced = store.record(
                {
                    "game": "legends_of_mushroom",
                    "profile": "Legends of Mushroom",
                    "screen_state": "reward_panel",
                    "task_key": "claim_rewards",
                    "runtime": "browser",
                    "confirmed_outcome": "advanced",
                    "chosen_candidate": {"label": "Claim", "kind": "dom", "keyword": "claim"},
                    "intended_action": {"label": "Claim", "target_type": "claim", "keyword": "claim", "point": [200, 520]},
                }
            )
            wrong = store.record(
                {
                    "game": "legends_of_mushroom",
                    "profile": "Legends of Mushroom",
                    "screen_state": "reward_panel",
                    "task_key": "claim_rewards",
                    "runtime": "browser",
                    "confirmed_outcome": "wrong_target",
                    "chosen_candidate": {"label": "Panel", "kind": "panel", "keyword": "reward"},
                    "intended_action": {"label": "Claim", "target_type": "claim", "keyword": "claim", "point": [200, 520]},
                }
            )
            self.assertTrue(Path(advanced["storage_path"]).exists())
            self.assertTrue(Path(wrong["storage_path"]).exists())
            aggregate = store.aggregate(game="legends_of_mushroom", screen_state="reward_panel", runtime="browser")
            self.assertGreaterEqual(aggregate["record_count"], 2)
            self.assertTrue(any(item["task_key"] == "claim_rewards" for item in aggregate["task_hints"]))
            self.assertTrue(any(item["kind"] == "panel" for item in aggregate["avoid_patterns"]))

            export_path = Path(temp_dir) / "evidence_export.json"
            payload = store.export_records(export_path, game="legends_of_mushroom")
            self.assertTrue(export_path.exists())
            self.assertEqual(2, len(payload["records"]))

            imported_store = TaskEvidenceStore(import_dir)
            imported = imported_store.import_records(export_path)
            self.assertEqual(2, imported["imported_count"])
            self.assertEqual(2, len(imported_store.query(game="legends_of_mushroom")))


class ProviderHubAndGuideCoachWidgetSmokeTests(unittest.TestCase):
    def test_provider_hub_widget_loads_cached_catalog_and_profiles(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        from ui.provider_hub_widget import ProviderHubWidget

        with tempfile.TemporaryDirectory() as temp_dir:
            service = ProviderCatalogService(temp_dir)
            service.save_cache(
                {
                    "updated_at": "2026-03-20T00:00:00Z",
                    "entries": [
                        {
                            "name": "FreeChat",
                            "category": "chat",
                            "link": "https://freechat.example.com",
                            "signup_required": True,
                            "limit_note": "No rate limit stated.",
                            "supports_api": True,
                            "api_style": "openai_chat",
                            "models": ["gpt-4.1-mini"],
                            "source": "test",
                            "notes": "OpenAI-compatible API",
                        }
                    ],
                    "sources": [{"label": "test", "url": "https://example.com", "kind": "test"}],
                    "warnings": [],
                }
            )
            service.save_endpoint_profiles(
                [
                    {
                        "label": "Local Provider",
                        "base_url": "https://provider.example.com",
                        "api_key_env_var": "LOCAL_PROVIDER_KEY",
                        "api_style": "openai_chat",
                        "models": ["gpt-4.1-mini"],
                        "enabled": True,
                    }
                ]
            )
            app = QApplication.instance() or QApplication([])
            widget = ProviderHubWidget(temp_dir)
            widget.set_saved_state(
                {
                    "auto_refresh_catalog": False,
                    "last_category": "chat",
                    "last_search": "free",
                }
            )
            self.assertEqual(1, widget.catalog_table.rowCount())
            self.assertEqual(1, widget.profile_list.count())
            self.assertEqual("chat", widget.collect_state()["last_category"])
            widget.deleteLater()
            app.processEvents()

    def test_guide_coach_dom_snapshot_panel_updates(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        from ui.guide_coach_widget import GuideCoachWidget

        app = QApplication.instance() or QApplication([])
        widget = GuideCoachWidget(_project_root())
        frame = _guide_frame()
        widget.analyze_frame_silently(frame, "Guide Coach Test")
        widget.ingest_dom_snapshot(
            {
                "url": "https://lom.joynetgame.com",
                "title": "Legends",
                "viewport": {"width": 405, "height": 720},
                "raw_text_summary": "claim reward",
                "actionable_count": 1,
                "actionables": [
                    {
                        "text": "Claim",
                        "role": "button",
                        "selector_hint": "#claim",
                        "visible": True,
                        "enabled": True,
                        "confidence": 0.9,
                        "bounds": {"x": 150, "y": 520, "width": 92, "height": 38},
                        "center": [196, 539],
                        "token": "claim-token",
                    }
                ],
                "screenshot_hash": "abc123",
            },
            source_label="Test Snapshot",
            frame=frame,
        )
        self.assertGreaterEqual(widget.dom_action_table.rowCount(), 1)
        self.assertIn("Test Snapshot", widget.dom_snapshot_summary_label.text())
        self.assertIn("claim", widget.dom_snapshot_text.toPlainText().lower())
        widget.deleteLater()
        app.processEvents()


if __name__ == "__main__":
    unittest.main()
