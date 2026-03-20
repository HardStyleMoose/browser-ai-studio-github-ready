from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from automation.click_diagnostics import ClickDiagnosticsEngine, browser_to_capture_point, capture_to_browser_point
from automation.guide_coach import GuideCoachEngine


class StubResourceReader:
    def __init__(self):
        self.available = False

    def read_text(self, _image, config: str = "--psm 6"):
        return ""

    def read_text_boxes(self, _image, keywords=(), min_confidence: float = 20.0, config: str = "--psm 11"):
        return []


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _make_reward_frame() -> np.ndarray:
    frame = np.zeros((720, 405, 3), dtype=np.uint8)
    frame[:] = (12, 18, 18)
    cv2.rectangle(frame, (48, 210), (356, 610), (190, 196, 220), -1)
    cv2.rectangle(frame, (120, 480), (286, 540), (80, 200, 80), -1)
    cv2.rectangle(frame, (74, 560), (118, 594), (40, 220, 255), -1)
    cv2.circle(frame, (95, 577), 12, (25, 210, 245), -1)
    return frame


class ClickDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.reader = StubResourceReader()
        self.guide_engine = GuideCoachEngine(_project_root(), resource_reader=self.reader)
        self.engine = ClickDiagnosticsEngine(self.guide_engine)

    def test_coordinate_roundtrip(self):
        profile = self.engine.default_calibration_profile()
        profile["capture_scale_x"] = 0.91
        profile["capture_scale_y"] = 0.88
        profile["offset_x"] = 14.0
        profile["offset_y"] = -7.0
        original = (117, 533)
        browser_point = capture_to_browser_point(original, profile)
        remapped = browser_to_capture_point(browser_point, profile)
        self.assertEqual(original, remapped)

    def test_diagnostics_flags_small_lower_target(self):
        frame = _make_reward_frame()
        guide_analysis = {
            "screen_state": "reward_panel",
            "screen_label": "Reward Panel",
            "recommendations": ["Claim the lower reward action first."],
            "matched_keywords": ["claim", "reward"],
            "ocr_text": "claim reward",
            "ocr_boxes": [],
        }
        diagnostics = self.engine.analyze_frame(frame, guide_analysis=guide_analysis)
        keywords = {str(candidate.get("keyword") or "") for candidate in diagnostics.get("candidates", [])}
        self.assertIn("claim", keywords)
        self.assertIn("small_target_overwhelmed", diagnostics.get("loop_risk", {}).get("flags", []))

    def test_loop_risk_flags_repeated_choice(self):
        frame = _make_reward_frame()
        guide_analysis = {
            "screen_state": "reward_panel",
            "screen_label": "Reward Panel",
            "recommendations": [],
            "matched_keywords": ["claim", "reward"],
            "ocr_text": "claim reward",
            "ocr_boxes": [],
        }
        first = self.engine.analyze_frame(frame, guide_analysis=guide_analysis)
        second = self.engine.analyze_frame(frame, guide_analysis=guide_analysis, recent_trace=[first])
        self.assertIn("stale_loop", second.get("loop_risk", {}).get("flags", []))

    def test_focus_mask_assessment_reward_panel(self):
        frame = _make_reward_frame()
        inside = self.engine.assess_focus_masks(
            "reward_panel",
            frame.shape,
            chosen={"x": 203, "y": 510},
            intended_point=(203, 520),
        )
        outside = self.engine.assess_focus_masks(
            "reward_panel",
            frame.shape,
            chosen={"x": 94, "y": 248},
            intended_point=None,
        )
        self.assertTrue(inside["chosen_hit"])
        self.assertEqual("Bottom Action Button", inside["chosen_zone"])
        self.assertTrue(inside["intended_hit"])
        self.assertTrue(outside["outside_focus"])
        self.assertGreater(float(outside["distance_to_primary"] or 0.0), 0.0)

    def test_label_roundtrip_and_comparison_report(self):
        frame = _make_reward_frame()
        guide_analysis = {
            "screen_state": "reward_panel",
            "screen_label": "Reward Panel",
            "recommendations": ["Claim the lower reward action first."],
            "matched_keywords": ["claim", "reward"],
            "ocr_text": "claim reward",
            "ocr_boxes": [],
        }
        diagnostics = self.engine.analyze_frame(frame, guide_analysis=guide_analysis)
        review = {
            "media_path": "example.png",
            "kind": "image",
            "frame_reviews": [
                self.engine._frame_review_entry(
                    guide_analysis,
                    diagnostics,
                    frame_index=0,
                    timestamp_seconds=0.0,
                    advance_score=0.0,
                    advanced=False,
                    reasons=["Still image review"],
                )
            ],
        }
        review["frame_reviews"][0] = self.engine.attach_label_to_frame_review(
            review["frame_reviews"][0],
            {
                "point": [203, 510],
                "target_type": "claim",
                "outcome": "advanced",
                "note": "Bottom claim button",
            },
        )
        normalized = self.engine.normalize_review(review)
        frame_review = normalized["frame_reviews"][0]
        self.assertEqual([203, 510], frame_review["label"]["point"])
        self.assertEqual("claim", frame_review["label"]["target_type"])
        self.assertTrue(frame_review["focus_mask_assessment"]["intended_hit"])
        self.assertIn("comparison_report", normalized)
        self.assertIn("issue_counts", normalized["comparison_report"])
        self.assertIn("summary_lines", normalized["comparison_report"])


class GuideCoachWidgetSmokeTests(unittest.TestCase):
    def test_widget_state_roundtrip(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        from ui.guide_coach_widget import GuideCoachWidget

        app = QApplication.instance() or QApplication([])
        widget = GuideCoachWidget(_project_root(), resource_reader=StubResourceReader())
        widget.set_saved_state(
            {
                "sample_interval_seconds": 2.0,
                "last_replay_path": "example.mp4",
                "checklist_progress": {"lamp_tutorial": True},
                "calibration_host": "lom.joynetgame.com",
                "calibration_runtime": "chromium",
                "active_calibration_profile_key": "lom.joynetgame.com|browser|chromium",
                "calibration_profiles": {
                    "lom.joynetgame.com|browser|chromium": {
                        "capture_scale_x": 0.95,
                        "capture_scale_y": 0.96,
                        "offset_x": 6,
                        "offset_y": -4,
                        "preview_scale": 1.25,
                        "click_radius": 6,
                        "max_panel_box_ratio": 0.12,
                    }
                },
                "show_focus_masks": True,
                "last_label_target_type": "claim",
                "last_label_outcome": "missed",
            }
        )
        state = widget.collect_state()
        self.assertEqual(state["last_replay_path"], "example.mp4")
        self.assertIn("lom.joynetgame.com|browser|chromium", state["calibration_profiles"])
        self.assertTrue(state["show_focus_masks"])
        self.assertEqual("claim", state["last_label_target_type"])
        self.assertEqual("missed", state["last_label_outcome"])
        widget.deleteLater()
        app.processEvents()

    def test_widget_replay_label_flow(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        from ui.guide_coach_widget import GuideCoachWidget

        app = QApplication.instance() or QApplication([])
        widget = GuideCoachWidget(_project_root(), resource_reader=StubResourceReader())
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "reward.png"
            cv2.imwrite(str(image_path), _make_reward_frame())
            widget.replay_path_input.setText(str(image_path))
            widget.review_selected_media()
            widget.replay_timeline_table.selectRow(0)
            widget._on_replay_selection_changed()
            widget._on_replay_preview_clicked(203, 510)
            widget.label_target_type_combo.setCurrentText("Claim")
            widget.label_outcome_combo.setCurrentText("Advanced")
            widget._save_current_replay_label()
            saved_label = widget.current_replay_entry.get("label", {})
            self.assertEqual([203, 510], saved_label.get("point"))
            self.assertEqual("claim", saved_label.get("target_type"))
            self.assertEqual("advanced", saved_label.get("outcome"))
            self.assertIn("comparison_report", widget.last_review)
            self.assertGreaterEqual(widget.replay_comparison_table.rowCount(), 0)
            if widget.replay_comparison_table.rowCount() > 0:
                widget.replay_comparison_table.selectRow(0)
                widget._on_comparison_selection_changed()
                self.assertGreaterEqual(widget.replay_timeline_table.currentRow(), 0)
        widget.deleteLater()
        app.processEvents()


if __name__ == "__main__":
    unittest.main()
