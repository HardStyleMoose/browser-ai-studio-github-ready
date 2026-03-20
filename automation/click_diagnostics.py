from __future__ import annotations

from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

import cv2
import numpy as np

from automation.game_profiles import resolve_game_profile
from automation.guide_coach import (
    GuideCoachEngine,
    SCREEN_STATE_DEFINITIONS,
    _format_timestamp,
)


FRAME_LABEL_TARGET_TYPES = (
    "claim",
    "continue",
    "confirm",
    "reward",
    "upgrade",
    "lamp",
    "mail",
    "event",
    "close",
    "other",
)


FOCUS_MASK_DEFINITIONS = {
    "tutorial": [
        {"label": "Lower Guided Prompt", "rect": (0.24, 0.70, 0.52, 0.18), "weight": 1.0},
        {"label": "Lamp Prompt", "rect": (0.36, 0.73, 0.28, 0.19), "weight": 0.95},
    ],
    "reward_panel": [
        {"label": "Bottom Action Button", "rect": (0.26, 0.68, 0.48, 0.18), "weight": 1.0},
        {"label": "Right Reward Rail", "rect": (0.80, 0.18, 0.16, 0.52), "weight": 0.72},
    ],
    "idle_combat": [
        {"label": "Combat Lane", "rect": (0.18, 0.20, 0.64, 0.34), "weight": 0.82},
        {"label": "Lamp Progression", "rect": (0.33, 0.68, 0.34, 0.22), "weight": 1.0},
    ],
}


def calibration_storage_key(host: str, mode: str = "browser", runtime: str = "chromium") -> str:
    normalized_host = str(host or "lom.joynetgame.com").strip().lower() or "lom.joynetgame.com"
    normalized_mode = str(mode or "browser").strip().lower() or "browser"
    normalized_runtime = str(runtime or "chromium").strip().lower() or "chromium"
    return f"{normalized_host}|{normalized_mode}|{normalized_runtime}"


def default_calibration_profile(host: str = "lom.joynetgame.com", mode: str = "browser", runtime: str = "chromium") -> dict:
    return {
        "host": str(host or "lom.joynetgame.com").strip().lower() or "lom.joynetgame.com",
        "mode": str(mode or "browser").strip().lower() or "browser",
        "runtime": str(runtime or "chromium").strip().lower() or "chromium",
        "capture_scale_x": 1.0,
        "capture_scale_y": 1.0,
        "offset_x": 0.0,
        "offset_y": 0.0,
        "preview_scale": 1.0,
        "click_radius": 8,
        "max_panel_box_ratio": 0.18,
        "loop_repeat_threshold": 2,
        "oversized_panel_penalty": 1800.0,
    }


def normalize_calibration_profile(
    payload: dict | None,
    host: str = "lom.joynetgame.com",
    mode: str = "browser",
    runtime: str = "chromium",
) -> dict:
    merged = {**default_calibration_profile(host=host, mode=mode, runtime=runtime)}
    if isinstance(payload, dict):
        merged.update(payload)
    merged["host"] = str(merged.get("host") or host or "lom.joynetgame.com").strip().lower() or "lom.joynetgame.com"
    merged["mode"] = str(merged.get("mode") or mode or "browser").strip().lower() or "browser"
    merged["runtime"] = str(merged.get("runtime") or runtime or "chromium").strip().lower() or "chromium"
    for field_name in ("capture_scale_x", "capture_scale_y", "preview_scale"):
        try:
            merged[field_name] = max(0.25, min(4.0, float(merged.get(field_name, 1.0) or 1.0)))
        except Exception:
            merged[field_name] = 1.0
    for field_name in ("offset_x", "offset_y"):
        try:
            merged[field_name] = float(merged.get(field_name, 0.0) or 0.0)
        except Exception:
            merged[field_name] = 0.0
    try:
        merged["click_radius"] = max(2, min(64, int(round(float(merged.get("click_radius", 8) or 8)))))
    except Exception:
        merged["click_radius"] = 8
    try:
        merged["max_panel_box_ratio"] = max(0.04, min(0.90, float(merged.get("max_panel_box_ratio", 0.18) or 0.18)))
    except Exception:
        merged["max_panel_box_ratio"] = 0.18
    try:
        merged["loop_repeat_threshold"] = max(2, min(8, int(merged.get("loop_repeat_threshold", 2) or 2)))
    except Exception:
        merged["loop_repeat_threshold"] = 2
    try:
        merged["oversized_panel_penalty"] = max(0.0, min(8000.0, float(merged.get("oversized_panel_penalty", 1800.0) or 1800.0)))
    except Exception:
        merged["oversized_panel_penalty"] = 1800.0
    merged["profile_key"] = calibration_storage_key(merged["host"], merged["mode"], merged["runtime"])
    return merged


def capture_to_browser_point(point: tuple[int, int] | None, calibration_profile: dict | None) -> tuple[int, int] | None:
    if point is None:
        return None
    profile = normalize_calibration_profile(calibration_profile)
    scale_x = float(profile.get("capture_scale_x", 1.0) or 1.0)
    scale_y = float(profile.get("capture_scale_y", 1.0) or 1.0)
    browser_x = int(round((float(point[0]) / max(0.25, scale_x)) + float(profile.get("offset_x", 0.0) or 0.0)))
    browser_y = int(round((float(point[1]) / max(0.25, scale_y)) + float(profile.get("offset_y", 0.0) or 0.0)))
    return browser_x, browser_y


def browser_to_capture_point(point: tuple[int, int] | None, calibration_profile: dict | None) -> tuple[int, int] | None:
    if point is None:
        return None
    profile = normalize_calibration_profile(calibration_profile)
    scale_x = float(profile.get("capture_scale_x", 1.0) or 1.0)
    scale_y = float(profile.get("capture_scale_y", 1.0) or 1.0)
    capture_x = int(round((float(point[0]) - float(profile.get("offset_x", 0.0) or 0.0)) * scale_x))
    capture_y = int(round((float(point[1]) - float(profile.get("offset_y", 0.0) or 0.0)) * scale_y))
    return capture_x, capture_y


def default_frame_label() -> dict:
    return {
        "point": None,
        "browser_point": None,
        "target_type": "other",
        "outcome": "neutral",
        "note": "",
        "matched_candidate_token": "",
    }


class ClickDiagnosticsEngine:
    def __init__(
        self,
        guide_engine: GuideCoachEngine,
        browser_url: str = "https://lom.joynetgame.com",
        mode: str = "browser",
        runtime_profile: str = "chromium",
    ):
        self.guide_engine = guide_engine
        self.project_root = Path(guide_engine.project_root)
        self.profile_key = str(guide_engine.profile_key or "legends_of_mushroom")
        self.guide = dict(guide_engine.guide or {})
        self.resource_reader = guide_engine.resource_reader
        self.browser_url = str(browser_url or "https://lom.joynetgame.com").strip() or "https://lom.joynetgame.com"
        self.mode = str(mode or "browser").strip().lower() or "browser"
        self.runtime_profile = str(runtime_profile or "chromium").strip().lower() or "chromium"
        self.game_profile = resolve_game_profile(self.mode, browser_url=self.browser_url)

    def calibration_storage_key(self, host: str | None = None, mode: str | None = None, runtime: str | None = None) -> str:
        return calibration_storage_key(
            host or self._normalized_host_label(self.browser_url),
            mode or self.mode,
            runtime or self.runtime_profile,
        )

    def default_calibration_profile(self, host: str | None = None, mode: str | None = None, runtime: str | None = None) -> dict:
        return normalize_calibration_profile(
            None,
            host=host or self._normalized_host_label(self.browser_url),
            mode=mode or self.mode,
            runtime=runtime or self.runtime_profile,
        )

    def normalize_calibration_profile(self, payload: dict | None, host: str | None = None, mode: str | None = None, runtime: str | None = None) -> dict:
        return normalize_calibration_profile(
            payload,
            host=host or self._normalized_host_label(self.browser_url),
            mode=mode or self.mode,
            runtime=runtime or self.runtime_profile,
        )

    def capture_to_browser_point(self, point: tuple[int, int] | None, calibration_profile: dict | None) -> tuple[int, int] | None:
        return capture_to_browser_point(point, calibration_profile)

    def browser_to_capture_point(self, point: tuple[int, int] | None, calibration_profile: dict | None) -> tuple[int, int] | None:
        return browser_to_capture_point(point, calibration_profile)

    def normalize_frame_label(self, payload: dict | None, calibration_profile: dict | None = None) -> dict:
        normalized = dict(default_frame_label())
        if isinstance(payload, dict):
            normalized.update(payload)
        point = normalized.get("point")
        if isinstance(point, (list, tuple)) and len(point) >= 2:
            normalized["point"] = [int(point[0]), int(point[1])]
        else:
            normalized["point"] = None
        browser_point = normalized.get("browser_point")
        if isinstance(browser_point, (list, tuple)) and len(browser_point) >= 2:
            normalized["browser_point"] = [int(browser_point[0]), int(browser_point[1])]
        elif normalized["point"] is not None:
            resolved = self.capture_to_browser_point((int(normalized["point"][0]), int(normalized["point"][1])), calibration_profile)
            normalized["browser_point"] = [int(resolved[0]), int(resolved[1])] if resolved is not None else None
        else:
            normalized["browser_point"] = None
        target_type = str(normalized.get("target_type", "other") or "other").strip().lower()
        normalized["target_type"] = target_type if target_type in FRAME_LABEL_TARGET_TYPES else "other"
        outcome = str(normalized.get("outcome", "neutral") or "neutral").strip().lower()
        normalized["outcome"] = outcome if outcome in {"advanced", "neutral", "missed"} else "neutral"
        normalized["note"] = str(normalized.get("note", "") or "").strip()
        normalized["matched_candidate_token"] = str(normalized.get("matched_candidate_token", "") or "").strip()
        return normalized

    def focus_masks_for_frame(self, state: str, frame_shape) -> list[dict]:
        if frame_shape is None:
            return []
        frame_height, frame_width = frame_shape[:2]
        masks = []
        for definition in FOCUS_MASK_DEFINITIONS.get(str(state or "").strip().lower(), []):
            rx, ry, rw, rh = definition["rect"]
            x = int(round(frame_width * float(rx)))
            y = int(round(frame_height * float(ry)))
            width = max(1, int(round(frame_width * float(rw))))
            height = max(1, int(round(frame_height * float(rh))))
            masks.append(
                {
                    "label": str(definition.get("label") or "Focus Zone"),
                    "weight": float(definition.get("weight", 1.0) or 1.0),
                    "x": x,
                    "y": y,
                    "width": width,
                    "height": height,
                }
            )
        return masks

    def assess_focus_masks(
        self,
        state: str,
        frame_shape,
        chosen: dict | None = None,
        intended_point: tuple[int, int] | None = None,
    ) -> dict:
        state_key = str(state or "").strip().lower()
        masks = self.focus_masks_for_frame(state_key, frame_shape)
        assessment = {
            "state_has_masks": bool(masks),
            "mask_labels": [mask["label"] for mask in masks],
            "chosen_hit": False,
            "intended_hit": None,
            "chosen_zone": "",
            "intended_zone": "",
            "outside_focus": False,
            "distance_to_primary": None,
            "masks": masks,
        }
        if not masks:
            return assessment
        primary = sorted(masks, key=lambda item: float(item.get("weight", 0.0) or 0.0), reverse=True)[0]
        chosen_point = None
        if isinstance(chosen, dict):
            chosen_point = (int(chosen.get("x", 0) or 0), int(chosen.get("y", 0) or 0))
        if chosen_point is not None:
            chosen_mask = self._mask_for_point(chosen_point, masks)
            if chosen_mask is not None:
                assessment["chosen_hit"] = True
                assessment["chosen_zone"] = str(chosen_mask.get("label") or "")
                assessment["distance_to_primary"] = 0.0
            else:
                assessment["outside_focus"] = True
                assessment["distance_to_primary"] = round(self._distance_to_rect(chosen_point, primary), 1)
        if intended_point is not None:
            intended = (int(intended_point[0]), int(intended_point[1]))
            intended_mask = self._mask_for_point(intended, masks)
            assessment["intended_hit"] = intended_mask is not None
            assessment["intended_zone"] = str((intended_mask or {}).get("label") or "")
        return assessment

    def attach_label_to_frame_review(
        self,
        frame_review: dict,
        label_payload: dict | None,
        calibration_profile: dict | None = None,
    ) -> dict:
        review = dict(frame_review or {})
        diagnostics = dict(review.get("diagnostics") or {})
        normalized = self.normalize_frame_label(label_payload, calibration_profile=calibration_profile)
        review["label"] = normalized
        intended_point = None
        if normalized.get("point") is not None:
            intended_point = (int(normalized["point"][0]), int(normalized["point"][1]))
        review["focus_mask_assessment"] = self.assess_focus_masks(
            review.get("screen_state", diagnostics.get("screen_state", "unknown")),
            self._frame_shape_from_diagnostics(diagnostics),
            chosen=diagnostics.get("chosen_candidate"),
            intended_point=intended_point,
        )
        diagnostics["focus_mask_assessment"] = dict(review["focus_mask_assessment"])
        review["diagnostics"] = diagnostics
        return review

    def normalize_review(self, review: dict | None, calibration_profile: dict | None = None) -> dict:
        normalized = dict(review or {})
        frame_reviews = []
        for entry in list(normalized.get("frame_reviews", [])):
            frame_review = dict(entry or {})
            diagnostics = dict(frame_review.get("diagnostics") or {})
            frame_review["label"] = self.normalize_frame_label(frame_review.get("label"), calibration_profile=calibration_profile)
            frame_review["focus_mask_assessment"] = dict(
                frame_review.get("focus_mask_assessment")
                or diagnostics.get("focus_mask_assessment")
                or self.assess_focus_masks(
                    frame_review.get("screen_state", diagnostics.get("screen_state", "unknown")),
                    self._frame_shape_from_diagnostics(diagnostics),
                    chosen=diagnostics.get("chosen_candidate"),
                    intended_point=tuple(frame_review["label"]["point"]) if frame_review["label"].get("point") is not None else None,
                )
            )
            diagnostics["focus_mask_assessment"] = dict(frame_review["focus_mask_assessment"])
            frame_review["diagnostics"] = diagnostics
            frame_reviews.append(frame_review)
        normalized["frame_reviews"] = frame_reviews
        normalized["timeline"] = [self._timeline_entry(entry) for entry in frame_reviews]
        normalized["comparison_report"] = self.build_comparison_report(frame_reviews)
        return normalized

    def analyze_frame(
        self,
        frame,
        guide_analysis: dict | None = None,
        calibration_profile: dict | None = None,
        recent_trace: list[dict] | None = None,
        source_label: str = "",
        frame_index: int | None = None,
        timestamp_seconds: float | None = None,
    ) -> dict:
        if frame is None:
            profile = self.normalize_calibration_profile(calibration_profile)
            return {
                "screen_state": "unknown",
                "screen_label": "Unknown",
                "focus_region": "No frame available",
                "focus_mask_assessment": self.assess_focus_masks("unknown", (720, 405), chosen=None, intended_point=None),
                "candidates": [],
                "chosen_candidate": None,
                "loop_risk": {"score": 0.0, "flags": [], "reasons": []},
                "miss_diagnosis": ["No frame available for diagnostics."],
                "improvement_suggestions": ["Capture a screen or load a replay frame first."],
                "calibration_profile": profile,
                "transform": self._build_transform_summary(profile, None),
                "frame_index": frame_index,
                "timestamp_seconds": timestamp_seconds,
                "timestamp": _format_timestamp(float(timestamp_seconds or 0.0)),
                "source_label": source_label,
            }

        profile = self.normalize_calibration_profile(calibration_profile)
        if guide_analysis is None:
            guide_analysis = self.guide_engine.analyze_frame(frame, source_label=source_label)
        recent_trace = list(recent_trace or [])
        visible_text = self._combined_visible_text(guide_analysis)

        panel_targets = self._extract_panel_action_targets(frame)
        lamp_targets = self._extract_lamp_targets(frame, visible_text)
        badge_targets = self._extract_red_badge_targets(frame)
        highlight_targets = self._extract_highlight_targets(frame)
        if panel_targets:
            for candidate in highlight_targets:
                candidate["score"] = float(candidate.get("score", 0.0) or 0.0) * 0.45
            for candidate in badge_targets:
                candidate["score"] = float(candidate.get("score", 0.0) or 0.0) * 0.65
        ocr_targets = self._extract_ocr_visual_targets(frame, guide_analysis=guide_analysis)

        height, width = frame.shape[:2]
        raw_candidates = [*panel_targets, *lamp_targets, *ocr_targets, *badge_targets, *highlight_targets]
        ranked_candidates = self._rank_candidates(raw_candidates, frame_size=(width, height), calibration_profile=profile)
        chosen = ranked_candidates[0] if ranked_candidates else None
        loop_risk = self._analyze_loop_risk(
            guide_analysis=guide_analysis,
            chosen=chosen,
            candidates=ranked_candidates,
            recent_trace=recent_trace,
            calibration_profile=profile,
            frame_size=(width, height),
        )
        focus_mask_assessment = self.assess_focus_masks(
            str(guide_analysis.get("screen_state") or "unknown"),
            frame.shape,
            chosen=chosen,
            intended_point=None,
        )
        return {
            "screen_state": str(guide_analysis.get("screen_state") or "unknown"),
            "screen_label": str(guide_analysis.get("screen_label") or "Unknown"),
            "focus_region": self._focus_region_for_state(str(guide_analysis.get("screen_state") or "unknown")),
            "focus_mask_assessment": focus_mask_assessment,
            "candidates": ranked_candidates,
            "chosen_candidate": chosen,
            "loop_risk": loop_risk,
            "miss_diagnosis": self._build_miss_diagnosis(guide_analysis, chosen, ranked_candidates, loop_risk, profile),
            "improvement_suggestions": self._build_improvement_suggestions(guide_analysis, chosen, ranked_candidates, loop_risk, profile),
            "calibration_profile": profile,
            "transform": self._build_transform_summary(profile, chosen),
            "frame_index": frame_index,
            "timestamp_seconds": timestamp_seconds,
            "timestamp": _format_timestamp(float(timestamp_seconds or 0.0)),
            "source_label": source_label,
        }

    def review_media(
        self,
        media_path: str | Path,
        checklist_progress: dict | None = None,
        sample_interval_seconds: float = 1.5,
        max_samples: int = 80,
        calibration_profile: dict | None = None,
    ) -> dict:
        path = Path(media_path)
        if not path.exists():
            raise FileNotFoundError(f"Media file not found: {path}")

        calibration = self.normalize_calibration_profile(calibration_profile)
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp"}:
            frame = cv2.imread(str(path))
            guide_analysis = self.guide_engine.analyze_frame(frame, checklist_progress=checklist_progress, source_label=path.name)
            diagnostics = self.analyze_frame(
                frame,
                guide_analysis=guide_analysis,
                calibration_profile=calibration,
                source_label=path.name,
                frame_index=0,
                timestamp_seconds=0.0,
            )
            frame_review = self._frame_review_entry(
                guide_analysis,
                diagnostics,
                frame_index=0,
                timestamp_seconds=0.0,
                advance_score=0.0,
                advanced=False,
                reasons=["Still image review"],
            )
            review = {
                "media_path": str(path),
                "kind": "image",
                "sample_interval_seconds": float(sample_interval_seconds),
                "frames_analyzed": 1,
                "advanced_frames": 0,
                "overall_progress_score": 0.0,
                "state_counts": {guide_analysis["screen_state"]: 1},
                "issue_counts": dict(Counter(diagnostics.get("loop_risk", {}).get("flags", []))),
                "timeline": [self._timeline_entry(frame_review)],
                "frame_reviews": [frame_review],
                "analysis": guide_analysis,
                "summary": [
                    f"Loaded still image: {path.name}",
                    f"Detected screen: {guide_analysis['screen_label']} ({guide_analysis['confidence']:.2f})",
                    f"Top target: {self._candidate_label(diagnostics.get('chosen_candidate'))}",
                ],
                "calibration_profile": calibration,
            }
            return self.normalize_review(review, calibration_profile=calibration)

        capture = cv2.VideoCapture(str(path))
        if not capture.isOpened():
            raise RuntimeError(f"Unable to open replay: {path}")

        fps = float(capture.get(cv2.CAP_PROP_FPS) or 30.0)
        total_frames = max(1, int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 1))
        stride = max(1, int(max(0.25, float(sample_interval_seconds)) * max(1.0, fps)))
        sampled_indices = list(range(0, total_frames, stride))[: max(1, int(max_samples))]
        frame_reviews = []
        timeline = []
        state_counter = Counter()
        issue_counter = Counter()
        total_score = 0.0
        advanced_frames = 0
        previous_analysis = None
        previous_frame = None
        recent_trace = []

        for frame_index in sampled_indices:
            capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
            ok, frame = capture.read()
            if not ok or frame is None:
                continue
            timestamp_seconds = frame_index / max(1.0, fps)
            guide_analysis = self.guide_engine.analyze_frame(
                frame,
                checklist_progress=checklist_progress,
                source_label=f"{path.name} @ {frame_index}",
            )
            diagnostics = self.analyze_frame(
                frame,
                guide_analysis=guide_analysis,
                calibration_profile=calibration,
                recent_trace=recent_trace[-4:],
                source_label=f"{path.name} @ {frame_index}",
                frame_index=frame_index,
                timestamp_seconds=timestamp_seconds,
            )
            progress = self.guide_engine._score_replay_progress(previous_analysis, guide_analysis, previous_frame, frame)
            state_counter[guide_analysis["screen_state"]] += 1
            issue_counter.update(diagnostics.get("loop_risk", {}).get("flags", []))
            total_score += progress["score"]
            advanced_frames += 1 if progress["advanced"] else 0
            frame_review = self._frame_review_entry(
                guide_analysis,
                diagnostics,
                frame_index=frame_index,
                timestamp_seconds=timestamp_seconds,
                advance_score=float(progress["score"] or 0.0),
                advanced=bool(progress["advanced"]),
                reasons=list(progress.get("reasons", [])),
            )
            frame_reviews.append(frame_review)
            timeline.append(self._timeline_entry(frame_review))
            previous_analysis = guide_analysis
            previous_frame = frame
            recent_trace.append(diagnostics)

        capture.release()
        most_common_state = state_counter.most_common(1)[0][0] if state_counter else "unknown"
        summary = [
            f"Replay: {path.name}",
            f"Samples reviewed: {len(timeline)}",
            f"Most common state: {SCREEN_STATE_DEFINITIONS.get(most_common_state, {}).get('label', 'Unknown')}",
            f"Likely advancement moments: {advanced_frames}",
            f"Replay progress score: {total_score:.2f}",
        ]
        if timeline:
            summary.append(f"Best segment: {max(timeline, key=lambda entry: entry['advance_score'])['timestamp']}")
        if issue_counter:
            summary.append("Most common diagnostics flags:")
            for flag, count in issue_counter.most_common(4):
                summary.append(f"- {flag.replace('_', ' ').title()}: {count}")
        review = {
            "media_path": str(path),
            "kind": "video",
            "sample_interval_seconds": float(sample_interval_seconds),
            "frames_analyzed": len(timeline),
            "advanced_frames": advanced_frames,
            "overall_progress_score": round(total_score, 2),
            "state_counts": dict(state_counter),
            "issue_counts": dict(issue_counter),
            "timeline": timeline,
            "frame_reviews": frame_reviews,
            "summary": summary,
            "calibration_profile": calibration,
        }
        return self.normalize_review(review, calibration_profile=calibration)

    def load_frame_from_media(self, media_path: str | Path, frame_index: int | None = None):
        path = Path(media_path)
        if not path.exists():
            return None
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp"}:
            return cv2.imread(str(path))
        capture = cv2.VideoCapture(str(path))
        if not capture.isOpened():
            return None
        if frame_index is not None:
            capture.set(cv2.CAP_PROP_POS_FRAMES, max(0, int(frame_index)))
        ok, frame = capture.read()
        capture.release()
        return frame if ok else None

    def render_overlay(
        self,
        frame,
        diagnostics: dict | None,
        calibration_profile: dict | None = None,
        intended_point: tuple[int, int] | None = None,
        selected_token: str | None = None,
        show_focus_masks: bool = False,
    ):
        if frame is None:
            return None
        output = frame.copy()
        profile = self.normalize_calibration_profile(calibration_profile)
        diagnostics = diagnostics or {}
        chosen = diagnostics.get("chosen_candidate") or {}
        chosen_token = str((selected_token or chosen.get("token") or "")).strip()
        click_radius = int(profile.get("click_radius", 8) or 8)
        if show_focus_masks:
            assessment = self.assess_focus_masks(
                diagnostics.get("screen_state", "unknown"),
                frame.shape,
                chosen=chosen,
                intended_point=intended_point,
            )
            for index, mask in enumerate(assessment.get("masks", [])):
                x = int(mask.get("x", 0) or 0)
                y = int(mask.get("y", 0) or 0)
                width = int(mask.get("width", 0) or 0)
                height = int(mask.get("height", 0) or 0)
                is_primary = index == 0
                color = (92, 210, 255) if is_primary else (90, 170, 110)
                cv2.rectangle(output, (x, y), (x + width, y + height), color, 1)
                cv2.putText(
                    output,
                    str(mask.get("label") or "Focus"),
                    (max(0, x + 4), max(14, y + 14)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.42,
                    color,
                    1,
                    cv2.LINE_AA,
                )
        for candidate in diagnostics.get("candidates", [])[:6]:
            bounds = candidate.get("bounds", {}) if isinstance(candidate, dict) else {}
            x = int(bounds.get("x", candidate.get("x", 0) if isinstance(candidate, dict) else 0) or 0)
            y = int(bounds.get("y", candidate.get("y", 0) if isinstance(candidate, dict) else 0) or 0)
            width = int(bounds.get("width", 0) or 0)
            height = int(bounds.get("height", 0) or 0)
            token = str(candidate.get("token") or "")
            is_selected = token == chosen_token
            color = self._candidate_color(candidate.get("kind"))
            if width > 0 and height > 0:
                cv2.rectangle(output, (x, y), (x + width, y + height), color, 2 if is_selected else 1)
            point_x = int(candidate.get("x", 0) or 0)
            point_y = int(candidate.get("y", 0) or 0)
            cv2.circle(output, (point_x, point_y), max(3, click_radius), color, 2 if is_selected else 1)
            label = f"{int(candidate.get('rank', 0) or 0)} {str(candidate.get('label') or 'target')[:24]}"
            cv2.putText(output, label, (max(0, point_x - 36), max(14, point_y - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.42, color, 1, cv2.LINE_AA)

        if chosen:
            point = (int(chosen.get("x", 0) or 0), int(chosen.get("y", 0) or 0))
            cv2.circle(output, point, max(6, click_radius + 2), (255, 255, 255), 2)
            capture_offset = (
                int(round(float(profile.get("offset_x", 0.0) or 0.0) * float(profile.get("capture_scale_x", 1.0) or 1.0))),
                int(round(float(profile.get("offset_y", 0.0) or 0.0) * float(profile.get("capture_scale_y", 1.0) or 1.0))),
            )
            corrected_point = (point[0] + capture_offset[0], point[1] + capture_offset[1])
            if corrected_point != point:
                cv2.circle(output, corrected_point, max(4, click_radius), (255, 0, 255), 2)
                cv2.line(output, point, corrected_point, (255, 0, 255), 1, cv2.LINE_AA)

        if intended_point is not None:
            ix, iy = int(intended_point[0]), int(intended_point[1])
            cv2.circle(output, (ix, iy), max(5, click_radius + 1), (0, 255, 255), 2)
            cv2.line(output, (ix - 8, iy), (ix + 8, iy), (0, 255, 255), 1, cv2.LINE_AA)
            cv2.line(output, (ix, iy - 8), (ix, iy + 8), (0, 255, 255), 1, cv2.LINE_AA)
            if chosen:
                cx = int(chosen.get("x", 0) or 0)
                cy = int(chosen.get("y", 0) or 0)
                cv2.line(output, (cx, cy), (ix, iy), (0, 255, 255), 1, cv2.LINE_AA)
        return output

    def find_candidate_at_point(self, diagnostics: dict | None, point: tuple[int, int] | None) -> dict | None:
        if diagnostics is None or point is None:
            return None
        px, py = int(point[0]), int(point[1])
        candidates = list(diagnostics.get("candidates", []))
        containing = []
        for candidate in candidates:
            bounds = candidate.get("bounds", {}) if isinstance(candidate, dict) else {}
            x = int(bounds.get("x", candidate.get("x", 0) or 0))
            y = int(bounds.get("y", candidate.get("y", 0) or 0))
            width = int(bounds.get("width", 0) or 0)
            height = int(bounds.get("height", 0) or 0)
            if width > 0 and height > 0 and x <= px <= (x + width) and y <= py <= (y + height):
                containing.append(candidate)
        if containing:
            return sorted(containing, key=lambda item: float(item.get("total_score", 0.0) or 0.0), reverse=True)[0]
        if not candidates:
            return None
        return min(
            candidates,
            key=lambda item: ((float(item.get("x", 0) or 0.0) - px) ** 2) + ((float(item.get("y", 0) or 0.0) - py) ** 2),
        )

    def calibration_from_manual_point(
        self,
        diagnostics: dict | None,
        intended_point: tuple[int, int] | None,
        calibration_profile: dict | None,
    ) -> dict:
        profile = self.normalize_calibration_profile(calibration_profile)
        chosen = (diagnostics or {}).get("chosen_candidate") or {}
        intended_candidate = self.find_candidate_at_point(diagnostics, intended_point)
        if intended_point is None or not chosen:
            return {"profile": profile, "delta": {"x": 0, "y": 0}, "intended_candidate": intended_candidate, "summary": "Pick a frame and click the intended target first."}

        delta_x = int(intended_point[0]) - int(chosen.get("x", 0) or 0)
        delta_y = int(intended_point[1]) - int(chosen.get("y", 0) or 0)
        scale_x = float(profile.get("capture_scale_x", 1.0) or 1.0)
        scale_y = float(profile.get("capture_scale_y", 1.0) or 1.0)
        updated = dict(profile)
        updated["offset_x"] = float(profile.get("offset_x", 0.0) or 0.0) + (delta_x / max(0.25, scale_x))
        updated["offset_y"] = float(profile.get("offset_y", 0.0) or 0.0) + (delta_y / max(0.25, scale_y))
        if intended_candidate:
            bounds = intended_candidate.get("bounds", {})
            small_edge = min(
                int(bounds.get("width", updated.get("click_radius", 8)) or updated.get("click_radius", 8)),
                int(bounds.get("height", updated.get("click_radius", 8)) or updated.get("click_radius", 8)),
            )
            updated["click_radius"] = max(3, min(updated["click_radius"], int(max(4, small_edge * 0.40))))
            if str(chosen.get("kind") or "").strip().lower() == "panel":
                updated["max_panel_box_ratio"] = max(0.04, min(float(updated["max_panel_box_ratio"]), float(bounds.get("area_ratio", 0.18) or 0.18) + 0.04))
        updated = self.normalize_calibration_profile(updated)
        summary_parts = [f"Delta: {delta_x:+d}, {delta_y:+d}"]
        if intended_candidate and str(intended_candidate.get("token") or "") != str(chosen.get("token") or ""):
            summary_parts.append(f"Intended target looks like {self._candidate_label(intended_candidate)}")
        return {
            "profile": updated,
            "delta": {"x": delta_x, "y": delta_y},
            "intended_candidate": intended_candidate,
            "summary": " | ".join(summary_parts),
        }

    def _timeline_entry(self, frame_review: dict) -> dict:
        diagnostics = dict(frame_review.get("diagnostics") or {})
        chosen = diagnostics.get("chosen_candidate") or {}
        label = self.normalize_frame_label(frame_review.get("label"))
        return {
            "timestamp": frame_review.get("timestamp", ""),
            "frame_index": int(frame_review.get("frame_index", 0) or 0),
            "screen_state": frame_review.get("screen_state", "unknown"),
            "screen_label": frame_review.get("screen_label", "Unknown"),
            "advance_score": float(frame_review.get("advance_score", 0.0) or 0.0),
            "advanced": bool(frame_review.get("advanced")),
            "reasons": list(frame_review.get("advance_reasons", [])),
            "top_recommendation": frame_review.get("top_recommendation", ""),
            "chosen_label": self._candidate_label(chosen),
            "diagnostic_flags": list((diagnostics.get("loop_risk") or {}).get("flags", [])),
            "label_target_type": label.get("target_type", "other"),
            "label_outcome": label.get("outcome", "neutral"),
        }

    def _frame_review_entry(
        self,
        guide_analysis: dict,
        diagnostics: dict,
        frame_index: int,
        timestamp_seconds: float,
        advance_score: float,
        advanced: bool,
        reasons: list[str],
    ) -> dict:
        entry = {
            "timestamp": _format_timestamp(timestamp_seconds),
            "timestamp_seconds": float(timestamp_seconds),
            "frame_index": int(frame_index),
            "screen_state": guide_analysis.get("screen_state", "unknown"),
            "screen_label": guide_analysis.get("screen_label", "Unknown"),
            "confidence": float(guide_analysis.get("confidence", 0.0) or 0.0),
            "top_recommendation": (guide_analysis.get("recommendations") or [""])[0],
            "guide_excerpt": guide_analysis.get("ocr_excerpt", ""),
            "matched_keywords": list(guide_analysis.get("matched_keywords", [])),
            "guide_reasons": list(guide_analysis.get("reasons", [])),
            "diagnostics": diagnostics,
            "advance_score": float(advance_score),
            "advanced": bool(advanced),
            "advance_reasons": list(reasons),
        }
        entry["label"] = self.normalize_frame_label(None)
        entry["focus_mask_assessment"] = dict(
            diagnostics.get("focus_mask_assessment")
            or self.assess_focus_masks(
                entry["screen_state"],
                self._frame_shape_from_diagnostics(diagnostics),
                chosen=diagnostics.get("chosen_candidate"),
                intended_point=None,
            )
        )
        return entry
    def _normalized_host_label(self, url: str) -> str:
        text = str(url or "").strip()
        if not text:
            return "lom.joynetgame.com"
        parsed = urlparse(text if "://" in text else f"https://{text}")
        return (parsed.netloc or parsed.path or "lom.joynetgame.com").lower().replace("www.", "")

    def _combined_visible_text(self, guide_analysis: dict | None) -> str:
        guide_analysis = guide_analysis or {}
        parts = [
            str(guide_analysis.get("ocr_text") or "").strip().lower(),
            " ".join(str(keyword or "").strip().lower() for keyword in guide_analysis.get("matched_keywords", [])),
        ]
        return " | ".join(part for part in parts if part)

    def _build_transform_summary(self, profile: dict, chosen: dict | None) -> dict:
        capture_point = None
        browser_point = None
        if chosen:
            capture_point = (int(chosen.get("x", 0) or 0), int(chosen.get("y", 0) or 0))
            browser_point = self.capture_to_browser_point(capture_point, profile)
        return {
            "profile_key": profile.get("profile_key", ""),
            "host": profile.get("host", ""),
            "mode": profile.get("mode", ""),
            "runtime": profile.get("runtime", ""),
            "capture_scale": {"x": float(profile.get("capture_scale_x", 1.0) or 1.0), "y": float(profile.get("capture_scale_y", 1.0) or 1.0)},
            "offset": {"x": float(profile.get("offset_x", 0.0) or 0.0), "y": float(profile.get("offset_y", 0.0) or 0.0)},
            "preview_scale": float(profile.get("preview_scale", 1.0) or 1.0),
            "click_radius": int(profile.get("click_radius", 8) or 8),
            "capture_point": capture_point,
            "browser_point": browser_point,
        }

    def _rank_candidates(self, candidates: list[dict], frame_size: tuple[int, int], calibration_profile: dict) -> list[dict]:
        width, height = frame_size
        ranked = []
        for candidate in candidates:
            breakdown = self._score_breakdown(candidate, frame_height=height, calibration_profile=calibration_profile)
            capture_point = (int(candidate.get("x", 0) or 0), int(candidate.get("y", 0) or 0))
            browser_point = self.capture_to_browser_point(capture_point, calibration_profile)
            bounds = dict(candidate.get("bounds") or {})
            bounds.setdefault("x", max(0, capture_point[0] - 6))
            bounds.setdefault("y", max(0, capture_point[1] - 6))
            bounds.setdefault("width", 12)
            bounds.setdefault("height", 12)
            area_ratio = (float(bounds.get("width", 0) or 0) * float(bounds.get("height", 0) or 0)) / float(max(1, width * height))
            bounds["area_ratio"] = round(area_ratio, 4)
            ranked.append({**candidate, "bounds": bounds, "detector_score": float(candidate.get("score", 0.0) or 0.0), "total_score": round(float(breakdown.get("total", 0.0) or 0.0), 2), "score_breakdown": breakdown, "browser_point": browser_point})
        ranked.sort(key=lambda item: float(item.get("total_score", 0.0) or 0.0), reverse=True)
        for index, candidate in enumerate(ranked, start=1):
            candidate["rank"] = index
        return ranked

    def _score_breakdown(self, candidate: dict, frame_height: int, calibration_profile: dict) -> dict:
        keyword = str(candidate.get("keyword") or "").strip().lower()
        kind = str(candidate.get("kind") or "").strip().lower()
        base_score = float(candidate.get("score", 0.0) or 0.0)
        kind_bonus = 2800.0 if kind == "panel" else 0.0
        keyword_bonus = {
            "claim": 1600.0,
            "collect": 1500.0,
            "confirm": 1300.0,
            "continue": 1250.0,
            "go": 1180.0,
            "start": 1120.0,
            "next": 1080.0,
            "upgrade": 760.0,
            "red_badge": 620.0,
            "reward": 180.0,
            "highlight": 0.0,
        }.get(keyword, 0.0)
        vertical_bonus = 0.0
        vertical_penalty = 0.0
        y_value = float(candidate.get("y", 0.0) or 0.0)
        if frame_height > 0:
            ry = y_value / float(frame_height)
            if keyword in {"claim", "collect", "confirm", "continue", "go", "start", "next"} and ry >= 0.58:
                vertical_bonus += 540.0
            if keyword == "reward" and 0.18 <= ry <= 0.62:
                vertical_penalty -= 720.0
        oversized_penalty = 0.0
        bounds = dict(candidate.get("bounds") or {})
        area_ratio = float(bounds.get("area_ratio", 0.0) or 0.0)
        max_panel_box_ratio = float(calibration_profile.get("max_panel_box_ratio", 0.18) or 0.18)
        if kind == "panel" and area_ratio > max_panel_box_ratio:
            oversized_penalty -= float(calibration_profile.get("oversized_panel_penalty", 1800.0) or 1800.0)
        total = base_score + kind_bonus + keyword_bonus + vertical_bonus + vertical_penalty + oversized_penalty
        return {
            "detector_score": round(base_score, 2),
            "kind_bonus": round(kind_bonus, 2),
            "keyword_bonus": round(float(keyword_bonus), 2),
            "vertical_bonus": round(vertical_bonus, 2),
            "vertical_penalty": round(vertical_penalty, 2),
            "oversized_panel_penalty": round(oversized_penalty, 2),
            "total": round(total, 2),
        }

    def _analyze_loop_risk(self, guide_analysis: dict, chosen: dict | None, candidates: list[dict], recent_trace: list[dict], calibration_profile: dict, frame_size: tuple[int, int]) -> dict:
        flags = []
        reasons = []
        _width, height = frame_size
        if chosen:
            bounds = dict(chosen.get("bounds") or {})
            area_ratio = float(bounds.get("area_ratio", 0.0) or 0.0)
            if str(chosen.get("kind") or "").strip().lower() == "panel" and area_ratio > float(calibration_profile.get("max_panel_box_ratio", 0.18) or 0.18):
                flags.append("oversized_panel_target")
                reasons.append(f"Chosen panel target covers {area_ratio * 100.0:.1f}% of the frame.")
            repeat_count = 1
            for previous in reversed(recent_trace):
                previous_chosen = (previous.get("chosen_candidate") or {}) if isinstance(previous, dict) else {}
                if not previous_chosen:
                    break
                if str(previous_chosen.get("token") or "") != str(chosen.get("token") or ""):
                    break
                if str(previous.get("screen_state") or "") != str(guide_analysis.get("screen_state") or ""):
                    break
                repeat_count += 1
            if repeat_count >= int(calibration_profile.get("loop_repeat_threshold", 2) or 2):
                flags.append("stale_loop")
                reasons.append(f"Same target chosen on {repeat_count} consecutive reviews without a screen-state change.")
            if self.game_profile.quick_delay_s <= 0.02 or self.game_profile.click_interval_steps <= 2:
                flags.append("aggressive_cadence")
                reasons.append(f"Profile cadence is aggressive ({self.game_profile.quick_delay_s:.3f}s quick delay).")
            small_target = self._small_target_overwhelmed(chosen, candidates, height)
            if small_target is not None:
                flags.append("small_target_overwhelmed")
                reasons.append(f"{self._candidate_label(chosen)} outranked smaller target {self._candidate_label(small_target)}.")
            min_edge = min(
                int(bounds.get("width", calibration_profile.get("click_radius", 8)) or calibration_profile.get("click_radius", 8)),
                int(bounds.get("height", calibration_profile.get("click_radius", 8)) or calibration_profile.get("click_radius", 8)),
            )
            if min_edge <= int(calibration_profile.get("click_radius", 8) or 8) * 2:
                flags.append("tiny_target_precision")
                reasons.append("Chosen target is small enough that a large click radius can spill outside the intended control.")
        score = min(1.0, len(flags) * 0.22)
        return {"score": round(score, 2), "flags": list(dict.fromkeys(flags)), "reasons": reasons[:5]}

    def _small_target_overwhelmed(self, chosen: dict, candidates: list[dict], frame_height: int) -> dict | None:
        chosen_kind = str(chosen.get("kind") or "").strip().lower()
        if chosen_kind not in {"panel", "highlight"}:
            return None
        chosen_score = float(chosen.get("total_score", 0.0) or 0.0)
        chosen_area = float((chosen.get("bounds") or {}).get("area_ratio", 0.0) or 0.0)
        for candidate in candidates[1:]:
            keyword = str(candidate.get("keyword") or "").strip().lower()
            if keyword not in {"claim", "collect", "confirm", "continue", "lamp", "upgrade"}:
                continue
            area_ratio = float((candidate.get("bounds") or {}).get("area_ratio", 0.0) or 0.0)
            if area_ratio >= max(0.08, chosen_area):
                continue
            y_value = float(candidate.get("y", 0.0) or 0.0)
            if frame_height > 0 and (y_value / float(frame_height)) < 0.60:
                continue
            score_gap = chosen_score - float(candidate.get("total_score", 0.0) or 0.0)
            if score_gap <= 2200.0:
                return candidate
        return None

    def build_comparison_report(self, frame_reviews: list[dict] | None) -> dict:
        frame_reviews = list(frame_reviews or [])
        issue_counts = Counter()
        broad_vs_small_examples = []
        focus_miss_examples = []
        top_losing_targets = Counter()
        chosen_area_total = 0.0
        chosen_area_count = 0
        losing_area_total = 0.0
        losing_area_count = 0
        for entry in frame_reviews:
            diagnostics = dict(entry.get("diagnostics") or {})
            chosen = diagnostics.get("chosen_candidate") or {}
            candidates = list(diagnostics.get("candidates", []))
            loop_flags = list((diagnostics.get("loop_risk") or {}).get("flags", []))
            issue_counts.update(loop_flags)
            if chosen:
                chosen_area = self._candidate_area_ratio(chosen)
                if chosen_area > 0.0:
                    chosen_area_total += chosen_area
                    chosen_area_count += 1
            losing_small = self._small_target_overwhelmed(chosen, candidates, self._frame_shape_from_candidates(candidates, chosen)[0])
            if losing_small is not None:
                issue_counts["broad_panel_beats_small_target"] += 1
                losing_area = self._candidate_area_ratio(losing_small)
                if losing_area > 0.0:
                    losing_area_total += losing_area
                    losing_area_count += 1
                broad_vs_small_examples.append(
                    {
                        "frame_index": int(entry.get("frame_index", 0) or 0),
                        "timestamp": str(entry.get("timestamp", "")),
                        "issue": "Broad panel beat smaller target",
                        "chosen_label": self._candidate_label(chosen),
                        "alternative_label": self._candidate_label(losing_small),
                        "screen_label": str(entry.get("screen_label", "Unknown")),
                    }
                )
                losing_key = (
                    str(losing_small.get("kind") or "unknown").strip().lower(),
                    str(losing_small.get("keyword") or "unknown").strip().lower(),
                )
                top_losing_targets[losing_key] += 1
            focus_assessment = dict(
                entry.get("focus_mask_assessment")
                or diagnostics.get("focus_mask_assessment")
                or {}
            )
            if focus_assessment.get("state_has_masks") and focus_assessment.get("outside_focus"):
                in_focus_candidate = self._best_in_focus_candidate(
                    entry.get("screen_state", diagnostics.get("screen_state", "unknown")),
                    candidates,
                    self._frame_shape_from_candidates(candidates, chosen),
                )
                if in_focus_candidate is not None:
                    issue_counts["focus_mask_miss"] += 1
                    focus_miss_examples.append(
                        {
                            "frame_index": int(entry.get("frame_index", 0) or 0),
                            "timestamp": str(entry.get("timestamp", "")),
                            "issue": "Chosen target missed focus region",
                            "chosen_label": self._candidate_label(chosen),
                            "alternative_label": self._candidate_label(in_focus_candidate),
                            "screen_label": str(entry.get("screen_label", "Unknown")),
                        }
                    )
            label = self.normalize_frame_label(entry.get("label"))
            if label.get("point") is not None and label.get("matched_candidate_token"):
                matched = next((candidate for candidate in candidates if str(candidate.get("token") or "") == str(label.get("matched_candidate_token") or "")), None)
                if matched is not None:
                    losing_key = (
                        str(matched.get("kind") or "unknown").strip().lower(),
                        str(matched.get("keyword") or "unknown").strip().lower(),
                    )
                    top_losing_targets[losing_key] += 1
        summary_lines = [
            f"Broad panel beat smaller target: {issue_counts.get('broad_panel_beats_small_target', 0)} frame(s)",
            f"Chosen target outside focus masks while another candidate was inside: {issue_counts.get('focus_mask_miss', 0)} frame(s)",
            f"Stale loop frames: {issue_counts.get('stale_loop', 0)}",
            f"Oversized panel target frames: {issue_counts.get('oversized_panel_target', 0)}",
        ]
        if chosen_area_count and losing_area_count:
            summary_lines.append(
                "Average chosen target size vs best-losing target size: "
                f"{(chosen_area_total / max(1, chosen_area_count)) * 100.0:.2f}% vs "
                f"{(losing_area_total / max(1, losing_area_count)) * 100.0:.2f}% of frame"
            )
        top_losing_rows = []
        for (kind, keyword), count in top_losing_targets.most_common(5):
            top_losing_rows.append({"kind": kind, "keyword": keyword, "count": count})
        return {
            "summary_lines": summary_lines,
            "issue_counts": dict(issue_counts),
            "broad_vs_small_examples": broad_vs_small_examples[:3],
            "focus_miss_examples": focus_miss_examples[:3],
            "top_losing_targets": top_losing_rows,
        }

    def _candidate_area_ratio(self, candidate: dict | None) -> float:
        if not isinstance(candidate, dict):
            return 0.0
        return float((candidate.get("bounds") or {}).get("area_ratio", 0.0) or 0.0)

    def _best_in_focus_candidate(self, state: str, candidates: list[dict], frame_shape) -> dict | None:
        masks = self.focus_masks_for_frame(state, frame_shape)
        if not masks:
            return None
        for candidate in candidates[1:]:
            point = (int(candidate.get("x", 0) or 0), int(candidate.get("y", 0) or 0))
            if self._mask_for_point(point, masks) is not None:
                return candidate
        return None

    def _frame_shape_from_diagnostics(self, diagnostics: dict | None) -> tuple[int, int]:
        diagnostics = diagnostics or {}
        return self._frame_shape_from_candidates(diagnostics.get("candidates", []), diagnostics.get("chosen_candidate"))

    def _frame_shape_from_candidates(self, candidates: list[dict] | None, chosen: dict | None = None) -> tuple[int, int]:
        max_x = 405
        max_y = 720
        for candidate in list(candidates or []) + ([chosen] if isinstance(chosen, dict) else []):
            if not isinstance(candidate, dict):
                continue
            bounds = dict(candidate.get("bounds") or {})
            max_x = max(max_x, int(bounds.get("x", candidate.get("x", 0) or 0) or 0) + int(bounds.get("width", 0) or 0) + 12)
            max_y = max(max_y, int(bounds.get("y", candidate.get("y", 0) or 0) or 0) + int(bounds.get("height", 0) or 0) + 12)
            max_x = max(max_x, int(candidate.get("x", 0) or 0) + 12)
            max_y = max(max_y, int(candidate.get("y", 0) or 0) + 12)
        return max(1, int(max_y)), max(1, int(max_x))

    def _mask_for_point(self, point: tuple[int, int], masks: list[dict]) -> dict | None:
        px, py = int(point[0]), int(point[1])
        for mask in masks:
            x = int(mask.get("x", 0) or 0)
            y = int(mask.get("y", 0) or 0)
            width = int(mask.get("width", 0) or 0)
            height = int(mask.get("height", 0) or 0)
            if x <= px <= (x + width) and y <= py <= (y + height):
                return mask
        return None

    def _distance_to_rect(self, point: tuple[int, int], rect: dict) -> float:
        px, py = int(point[0]), int(point[1])
        x = int(rect.get("x", 0) or 0)
        y = int(rect.get("y", 0) or 0)
        width = int(rect.get("width", 0) or 0)
        height = int(rect.get("height", 0) or 0)
        dx = max(x - px, 0, px - (x + width))
        dy = max(y - py, 0, py - (y + height))
        return float((dx * dx + dy * dy) ** 0.5)

    def _build_miss_diagnosis(self, guide_analysis: dict, chosen: dict | None, candidates: list[dict], loop_risk: dict, calibration_profile: dict) -> list[str]:
        messages = []
        state = str(guide_analysis.get("screen_state") or "unknown")
        frame_shape = self._frame_shape_from_candidates(candidates, chosen)
        focus_assessment = self.assess_focus_masks(state, frame_shape, chosen=chosen, intended_point=None)
        if not chosen:
            return ["No visual target stood out strongly enough on this frame."]
        if "oversized_panel_target" in loop_risk.get("flags", []):
            messages.append("Broad panel detection is dominating this frame, which can hide small intended controls.")
        if "small_target_overwhelmed" in loop_risk.get("flags", []):
            messages.append("A smaller lower-screen target exists, but the current ranking still prefers a broader action surface.")
        if focus_assessment.get("state_has_masks") and focus_assessment.get("outside_focus"):
            messages.append("Chosen target is outside the expected focus region for this screen state.")
        if "stale_loop" in loop_risk.get("flags", []):
            messages.append("The same click choice is repeating without enough evidence that the screen changed.")
        if "aggressive_cadence" in loop_risk.get("flags", []):
            messages.append("Cadence is fast enough that the same target can be re-hit before the UI settles.")
        if "tiny_target_precision" in loop_risk.get("flags", []):
            messages.append(f"The active click radius ({int(calibration_profile.get('click_radius', 8) or 8)} px) is large relative to the chosen control.")
        if state == "tutorial":
            messages.append("Tutorial screens usually want the lower-center guided action first, especially lamp or hand-pointer prompts.")
        elif state == "reward_panel":
            messages.append("Reward panels often need the obvious bottom action button rather than a generic upper highlight.")
        elif state == "idle_combat":
            messages.append("Idle combat frames should generally prefer focused combat/lamp interactions over broad menu panels.")
        return messages[:5] or ["No obvious miss signal was detected beyond the current top-ranked target."]

    def _build_improvement_suggestions(self, guide_analysis: dict, chosen: dict | None, candidates: list[dict], loop_risk: dict, calibration_profile: dict) -> list[str]:
        suggestions = []
        flags = set(loop_risk.get("flags", []))
        state = str(guide_analysis.get("screen_state") or "unknown")
        frame_shape = self._frame_shape_from_candidates(candidates, chosen)
        focus_assessment = self.assess_focus_masks(state, frame_shape, chosen=chosen, intended_point=None)
        if "oversized_panel_target" in flags:
            suggestions.append("Lower the maximum panel box ratio so very broad panels stop outranking smaller controls.")
        if "small_target_overwhelmed" in flags:
            suggestions.append("Prefer smaller lower-screen claim/tutorial targets when they are close in score to a broad panel action.")
        if "stale_loop" in flags:
            suggestions.append("Require more state change between repeated clicks on the same target before trying it again.")
        if "aggressive_cadence" in flags:
            suggestions.append("Use a slower click cadence for tiny controls and tutorial prompts.")
        if "tiny_target_precision" in flags:
            suggestions.append("Shrink the click radius for this profile so small controls have less spillover.")
        if focus_assessment.get("state_has_masks") and focus_assessment.get("outside_focus"):
            suggestions.append("Use the expected focus masks to down-rank clicks that land outside the screen’s primary action zone.")
        state_specific = {
            "tutorial": "Keep the focus region on the lower-center guided prompt or lamp instead of broad panel areas.",
            "reward_panel": "Treat the main bottom claim/continue action as the first-class action on reward panels.",
            "mail": "Mail screens should focus on claim/close flows, not generic highlight regions.",
            "event": "Event screens benefit from small rail/button targeting instead of panel-wide clicks.",
            "upgrade": "Upgrade screens should favor compact upgrade controls and bottom buttons over ambient highlights.",
            "idle_combat": "Idle combat should stay centered on lamp/combat progression unless a clear claim surface appears.",
        }.get(state)
        if state_specific:
            suggestions.append(state_specific)
        for recommendation in guide_analysis.get("recommendations", []):
            if recommendation not in suggestions:
                suggestions.append(recommendation)
        return suggestions[:6]

    def _focus_region_for_state(self, state: str) -> str:
        mapping = {
            "tutorial": "Lower-center guided prompt and lamp/tutorial hand area",
            "reward_panel": "Bottom action button plus right-rail reward markers",
            "mail": "Panel action row and close/claim controls",
            "event": "Right-side event rail and centered event action buttons",
            "upgrade": "Lower upgrade rail and focused stat/skill controls",
            "idle_combat": "Center combat lane and lower-center lamp/progression surface",
        }
        return mapping.get(str(state or "unknown"), "Review the strongest visible button or label cluster on screen")

    def _visual_target_keywords(self) -> tuple[str, ...]:
        values = (
            *self.game_profile.reward_keywords,
            *self.game_profile.dom_priority_keywords,
            *[str(item or "").strip().lower() for item in self.guide.get("priority_keywords", []) if str(item or "").strip()],
            "claim",
            "collect",
            "reward",
            "free",
            "gift",
            "bonus",
            "upgrade",
            "level",
            "challenge",
            "boss",
            "quest",
            "daily",
            "mail",
            "click here",
            "tap here",
            "tutorial",
            "guide",
        )
        blocked = {"auto"}
        normalized = [str(value or "").strip().lower() for value in values if str(value or "").strip() and str(value or "").strip().lower() not in blocked]
        return tuple(dict.fromkeys(normalized))

    def _lamp_prompt_keywords(self) -> tuple[str, ...]:
        values = ["tap magic lamp", "magic lamp", "click here", "tap here", "light the magic lamp"]
        return tuple(dict.fromkeys(str(value or "").strip().lower() for value in values if str(value or "").strip()))

    def _visible_text_contains(self, visible_text: str, keywords) -> bool:
        if not visible_text:
            return False
        return any(str(keyword or "").strip().lower() in visible_text for keyword in list(keywords or []) if str(keyword or "").strip())

    def _extract_ocr_visual_targets(self, frame, guide_analysis: dict | None = None) -> list[dict]:
        if frame is None or not self.resource_reader.available:
            return []
        height, width = frame.shape[:2]
        scale = 1.0
        boxes = list((guide_analysis or {}).get("ocr_boxes", []) or [])
        if not boxes:
            preview = frame
            if max(height, width) < 720:
                scale = min(1.35, 640.0 / float(max(height, width)))
                preview = cv2.resize(frame, (max(1, int(width * scale)), max(1, int(height * scale))), interpolation=cv2.INTER_CUBIC)
            gray = cv2.cvtColor(preview, cv2.COLOR_BGR2GRAY)
            gray = cv2.GaussianBlur(gray, (3, 3), 0)
            processed = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
            boxes = self.resource_reader.read_text_boxes(processed, keywords=self._visual_target_keywords(), min_confidence=26.0, config="--psm 6")
        targets = []
        for box in boxes:
            keyword = str(box.get("keyword") or box.get("text") or "target").strip().lower()
            box_x = int(float(box.get("x", 0) or 0) / scale)
            box_y = int(float(box.get("y", 0) or 0) / scale)
            box_w = int(float(box.get("width", 0) or 0) / scale)
            box_h = int(float(box.get("height", 0) or 0) / scale)
            center_x = int(box_x + (box_w / 2.0))
            center_y = int(box_y + (box_h / 2.0))
            if center_x < 0 or center_y < 0 or center_x >= width or center_y >= height:
                continue
            confidence = float(box.get("confidence", 0.0) or 0.0)
            area = max(1.0, float(box_w) * float(box_h))
            score = 1800.0 + (confidence * 10.0) + min(1400.0, area * 0.4)
            if keyword in {"claim", "collect", "reward", "free", "gift", "bonus"}:
                score += 950.0
            if keyword in {"upgrade", "level", "enhance", "boost"}:
                score += 450.0
            targets.append({"kind": "ocr", "keyword": keyword, "label": str(box.get("text") or keyword), "x": center_x, "y": center_y, "score": score, "token": f"ocr:{keyword}:{center_x // 12}:{center_y // 12}", "bounds": {"x": box_x, "y": box_y, "width": box_w, "height": box_h}})
        return targets

    def _extract_highlight_targets(self, frame) -> list[dict]:
        if frame is None:
            return []
        height, width = frame.shape[:2]
        scale = 1.0
        preview = frame
        if max(height, width) > 720:
            scale = 720.0 / float(max(height, width))
            preview = cv2.resize(frame, (max(1, int(width * scale)), max(1, int(height * scale))), interpolation=cv2.INTER_AREA)
        hsv = cv2.cvtColor(preview, cv2.COLOR_BGR2HSV)
        gold_mask = cv2.inRange(hsv, np.array([12, 90, 120], dtype=np.uint8), np.array([42, 255, 255], dtype=np.uint8))
        green_mask = cv2.inRange(hsv, np.array([40, 70, 90], dtype=np.uint8), np.array([88, 255, 255], dtype=np.uint8))
        mask = cv2.bitwise_or(gold_mask, green_mask)
        kernel = np.ones((3, 3), dtype=np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        contours, _hierarchy = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        targets = []
        preview_h, preview_w = preview.shape[:2]
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < 40.0 or area > float(preview_h * preview_w) * 0.09:
                continue
            x, y, box_w, box_h = cv2.boundingRect(contour)
            if box_w < 14 or box_h < 10:
                continue
            aspect_ratio = box_w / float(max(1, box_h))
            if aspect_ratio < 0.7 or aspect_ratio > 6.5:
                continue
            center_x = int((x + (box_w / 2.0)) / scale)
            center_y = int((y + (box_h / 2.0)) / scale)
            rx = center_x / float(max(1, width))
            ry = center_y / float(max(1, height))
            if 0.40 <= rx <= 0.62 and ry >= 0.74:
                continue
            if 0.18 < rx < 0.82 and 0.12 < ry < 0.70:
                continue
            if ry > 0.72 and rx < 0.42:
                keyword = "claim"
                label = "Highlighted Claim"
            elif ry > 0.72:
                keyword = "upgrade"
                label = "Highlighted Upgrade"
            elif rx < 0.20 or rx > 0.80 or ry < 0.18:
                keyword = "reward"
                label = "Highlighted Reward"
            else:
                keyword = "highlight"
                label = "Highlighted Action"
            edge_bonus = 260.0 if (rx < 0.18 or rx > 0.82 or ry < 0.18 or ry > 0.76) else 0.0
            score = 980.0 + min(1800.0, area * 4.0) + edge_bonus
            if keyword == "claim":
                score += 1400.0
            elif keyword == "upgrade":
                score += 620.0
            elif keyword == "reward" and 0.16 <= ry <= 0.60:
                score -= 780.0
            targets.append({"kind": "highlight", "keyword": keyword, "label": label, "x": center_x, "y": center_y, "score": score, "token": f"highlight:{keyword}:{center_x // 12}:{center_y // 12}", "bounds": {"x": int(x / scale), "y": int(y / scale), "width": int(box_w / scale), "height": int(box_h / scale)}})
        return targets

    def _extract_panel_action_targets(self, frame) -> list[dict]:
        if frame is None:
            return []
        height, width = frame.shape[:2]
        search_top = int(height * 0.24)
        search_bottom = int(height * 0.96)
        search_left = int(width * 0.10)
        search_right = int(width * 0.90)
        if search_right <= search_left or search_bottom <= search_top:
            return []
        search = frame[search_top:search_bottom, search_left:search_right]
        if search.size == 0:
            return []
        hsv = cv2.cvtColor(search, cv2.COLOR_BGR2HSV)
        panel_mask = cv2.inRange(hsv, np.array([5, 0, 120], dtype=np.uint8), np.array([40, 95, 255], dtype=np.uint8))
        panel_mask = cv2.morphologyEx(panel_mask, cv2.MORPH_CLOSE, np.ones((7, 7), dtype=np.uint8))
        contours, _hierarchy = cv2.findContours(panel_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        panel_rects = []
        min_panel_area = float((search_bottom - search_top) * (search_right - search_left)) * 0.08
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < min_panel_area:
                continue
            x, y, box_w, box_h = cv2.boundingRect(contour)
            if box_w < int((search_right - search_left) * 0.32) or box_h < int((search_bottom - search_top) * 0.18):
                continue
            aspect_ratio = box_w / float(max(1, box_h))
            if aspect_ratio < 0.75 or aspect_ratio > 3.8:
                continue
            panel_rects.append((x, y, box_w, box_h, area))
        if not panel_rects:
            return []
        panel_rects.sort(key=lambda item: (item[4], item[3] * item[2]), reverse=True)
        panel_x, panel_y, panel_w, panel_h, _panel_area = panel_rects[0]
        panel_roi = search[panel_y:panel_y + panel_h, panel_x:panel_x + panel_w]
        if panel_roi.size == 0:
            return []
        panel_hsv = cv2.cvtColor(panel_roi, cv2.COLOR_BGR2HSV)
        green_mask = cv2.inRange(panel_hsv, np.array([35, 55, 70], dtype=np.uint8), np.array([95, 255, 255], dtype=np.uint8))
        gold_mask = cv2.inRange(panel_hsv, np.array([10, 60, 110], dtype=np.uint8), np.array([38, 255, 255], dtype=np.uint8))
        blue_mask = cv2.inRange(panel_hsv, np.array([88, 45, 70], dtype=np.uint8), np.array([132, 255, 255], dtype=np.uint8))
        action_mask = cv2.bitwise_or(cv2.bitwise_or(green_mask, gold_mask), blue_mask)
        action_mask = cv2.morphologyEx(action_mask, cv2.MORPH_CLOSE, np.ones((5, 5), dtype=np.uint8))
        action_mask = cv2.morphologyEx(action_mask, cv2.MORPH_OPEN, np.ones((3, 3), dtype=np.uint8))
        button_contours, _hierarchy = cv2.findContours(action_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        targets = []
        for contour in button_contours:
            area = cv2.contourArea(contour)
            if area < max(70.0, float(panel_w * panel_h) * 0.012):
                continue
            x, y, box_w, box_h = cv2.boundingRect(contour)
            if box_w < 20 or box_h < 12:
                continue
            aspect_ratio = box_w / float(max(1, box_h))
            if aspect_ratio < 1.1 or aspect_ratio > 6.0:
                continue
            if y < int(panel_h * 0.34):
                continue
            center_x = search_left + panel_x + x + (box_w // 2)
            center_y = search_top + panel_y + y + (box_h // 2)
            region = panel_hsv[y:y + box_h, x:x + box_w]
            if region.size == 0:
                continue
            hue = float(cv2.mean(region)[0] or 0.0)
            if 34.0 <= hue <= 96.0:
                keyword = "claim"
                label = "Panel Claim Action"
                color_bonus = 700.0
            elif 9.0 <= hue <= 40.0:
                keyword = "confirm"
                label = "Panel Confirm Action"
                color_bonus = 520.0
            else:
                keyword = "continue"
                label = "Panel Continue Action"
                color_bonus = 460.0
            central_bonus = 280.0 if 0.26 <= (center_x / float(max(1, width))) <= 0.74 else 0.0
            score = 4300.0 + min(2200.0, area * 3.4) + color_bonus + central_bonus
            targets.append({"kind": "panel", "keyword": keyword, "label": label, "x": int(center_x), "y": int(center_y), "score": score, "token": f"panel:{keyword}:{int(center_x) // 10}:{int(center_y) // 10}", "bounds": {"x": search_left + panel_x + x, "y": search_top + panel_y + y, "width": box_w, "height": box_h}})
        targets.sort(key=lambda item: float(item.get("score", 0.0) or 0.0), reverse=True)
        return targets[:4]

    def _extract_lamp_targets(self, frame, visible_text: str) -> list[dict]:
        if frame is None:
            return []
        height, width = frame.shape[:2]
        left = int(width * 0.28)
        right = int(width * 0.72)
        top = int(height * 0.68)
        bottom = int(height * 0.98)
        if right <= left or bottom <= top:
            return []
        roi = frame[top:bottom, left:right]
        if roi.size == 0:
            return []
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        gold_mask = cv2.inRange(hsv, np.array([8, 80, 110], dtype=np.uint8), np.array([38, 255, 255], dtype=np.uint8))
        orange_mask = cv2.inRange(hsv, np.array([0, 70, 95], dtype=np.uint8), np.array([18, 255, 255], dtype=np.uint8))
        purple_mask = cv2.inRange(hsv, np.array([118, 35, 65], dtype=np.uint8), np.array([170, 255, 255], dtype=np.uint8))
        mask = cv2.bitwise_or(cv2.bitwise_or(gold_mask, orange_mask), purple_mask)
        kernel = np.ones((5, 5), dtype=np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        contours, _hierarchy = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        expected_x = left + ((right - left) * 0.5)
        expected_y = top + ((bottom - top) * 0.62)
        lamp_prompt_visible = self._visible_text_contains(visible_text, self._lamp_prompt_keywords())
        targets = []
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < 90.0 or area > float((right - left) * (bottom - top)) * 0.45:
                continue
            x, y, box_w, box_h = cv2.boundingRect(contour)
            if box_w < 18 or box_h < 18:
                continue
            center_x = left + x + (box_w // 2)
            center_y = top + y + (box_h // 2)
            distance = ((center_x - expected_x) ** 2 + (center_y - expected_y) ** 2) ** 0.5
            score = 2200.0 + min(2400.0, area * 2.8) + max(0.0, 900.0 - (distance * 5.0))
            if lamp_prompt_visible:
                score += 1400.0
            targets.append({"kind": "lamp", "keyword": "lamp", "label": "Magic Lamp", "x": int(center_x), "y": int(center_y), "score": score, "token": f"lamp:{int(center_x) // 10}:{int(center_y) // 10}", "bounds": {"x": left + x, "y": top + y, "width": box_w, "height": box_h}})
        targets.sort(key=lambda item: float(item.get("score", 0.0) or 0.0), reverse=True)
        return targets[:3]

    def _extract_red_badge_targets(self, frame) -> list[dict]:
        if frame is None:
            return []
        height, width = frame.shape[:2]
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        mask_low = cv2.inRange(hsv, np.array([0, 125, 135], dtype=np.uint8), np.array([12, 255, 255], dtype=np.uint8))
        mask_high = cv2.inRange(hsv, np.array([168, 125, 135], dtype=np.uint8), np.array([180, 255, 255], dtype=np.uint8))
        mask = cv2.bitwise_or(mask_low, mask_high)
        kernel = np.ones((3, 3), dtype=np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        contours, _hierarchy = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        targets = []
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < 18.0 or area > 1200.0:
                continue
            perimeter = max(1.0, cv2.arcLength(contour, True))
            circularity = (4.0 * np.pi * area) / (perimeter * perimeter)
            if circularity < 0.35:
                continue
            x, y, box_w, box_h = cv2.boundingRect(contour)
            if box_w < 5 or box_h < 5 or box_w > 40 or box_h > 40:
                continue
            center_x = x + (box_w // 2)
            center_y = y + (box_h // 2)
            rx = center_x / float(max(1, width))
            ry = center_y / float(max(1, height))
            if 0.16 < rx < 0.84 and 0.20 < ry < 0.72:
                continue
            edge_bonus = 320.0 if (rx < 0.18 or rx > 0.82 or ry < 0.18 or ry > 0.80) else 0.0
            score = 1100.0 + min(900.0, area * 2.8) + edge_bonus
            targets.append({"kind": "badge", "keyword": "red_badge", "label": "Reward Badge", "x": center_x, "y": center_y, "score": score, "token": f"badge:{center_x // 10}:{center_y // 10}", "bounds": {"x": x, "y": y, "width": box_w, "height": box_h}})
        return targets

    def _candidate_color(self, kind: str | None) -> tuple[int, int, int]:
        return {
            "panel": (70, 220, 255),
            "lamp": (255, 200, 0),
            "ocr": (255, 120, 120),
            "badge": (80, 80, 255),
            "highlight": (110, 255, 110),
        }.get(str(kind or "").strip().lower(), (220, 220, 220))

    def _candidate_label(self, candidate: dict | None) -> str:
        if not candidate:
            return "No target"
        label = str(candidate.get("label") or candidate.get("keyword") or "target").strip()
        rank = int(candidate.get("rank", 0) or 0)
        return f"#{rank} {label}" if rank else label
