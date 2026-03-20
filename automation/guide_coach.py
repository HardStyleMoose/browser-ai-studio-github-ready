from __future__ import annotations

from collections import Counter
from pathlib import Path

import cv2

from automation.guide_learning import load_game_guide
from vision.resource_reader import ResourceReader


SCREEN_STATE_DEFINITIONS = {
    "tutorial": {
        "label": "Tutorial",
        "keywords": [
            "tutorial",
            "guide",
            "tap magic lamp",
            "magic lamp",
            "click here",
            "tap",
            "touch nothing",
            "follow",
        ],
    },
    "reward_panel": {
        "label": "Reward Panel",
        "keywords": [
            "claim",
            "collect",
            "reward",
            "free",
            "bonus",
            "receive",
            "continue",
            "redeem",
        ],
    },
    "mail": {
        "label": "Mail",
        "keywords": [
            "mail",
            "inbox",
            "message",
            "system mail",
            "letter",
            "post",
        ],
    },
    "event": {
        "label": "Event",
        "keywords": [
            "event",
            "rush",
            "battle pass",
            "pass",
            "spinner",
            "lucky",
            "shop",
            "carnival",
        ],
    },
    "upgrade": {
        "label": "Upgrade",
        "keywords": [
            "upgrade",
            "level",
            "gear",
            "skill",
            "stat",
            "relic",
            "awakening",
            "soul",
            "crystal",
        ],
    },
    "idle_combat": {
        "label": "Idle Combat",
        "keywords": [
            "challenge",
            "campaign",
            "boss",
            "battle",
            "combat",
            "normal",
            "stage",
            "auto",
        ],
    },
}


CHECKLIST_BLUEPRINT = [
    {
        "id": "lamp_tutorial",
        "title": "Follow the lamp and tutorial prompts first",
        "summary": "Push the onboarding flow and the lamp before wandering into side systems.",
        "f2p": True,
        "priority": "Critical",
        "signals": ["tutorial", "magic lamp", "click here", "lamp"],
    },
    {
        "id": "save_gems",
        "title": "Save gems and skip early premium pulls",
        "summary": "Treat gem spending as a long-term resource and avoid early gacha temptations.",
        "f2p": True,
        "priority": "Critical",
        "signals": ["gems", "summon", "buy pack", "top up", "recharge", "vip"],
    },
    {
        "id": "claim_free_rewards",
        "title": "Claim free rewards, mail, and login bonuses",
        "summary": "Sweep free claim surfaces often because they are your safest beginner progression source.",
        "f2p": True,
        "priority": "High",
        "signals": ["claim", "collect", "reward", "mail", "bonus", "free"],
    },
    {
        "id": "rush_pass_rewards",
        "title": "Check rushes, passes, and right-rail event claims",
        "summary": "Recurring event and pass rails are high-value F2P surfaces when claimable.",
        "f2p": True,
        "priority": "High",
        "signals": ["event", "rush", "battle pass", "pass", "spinner", "shop"],
    },
    {
        "id": "gear_and_skills",
        "title": "Review gear, skill, stat, relic, and awakening upgrades",
        "summary": "Regular upgrade sweeps support stage progression better than random detours.",
        "f2p": True,
        "priority": "High",
        "signals": ["upgrade", "gear", "skill", "stat", "relic", "awakening", "soul"],
    },
    {
        "id": "daily_loops",
        "title": "Cycle manor, workteam, harvest, and other daily loops",
        "summary": "These repeatable systems are steady passive progression and should be checked often.",
        "f2p": True,
        "priority": "Medium",
        "signals": ["daily", "manor", "assistant", "harvest", "crop", "workteam"],
    },
    {
        "id": "family_social",
        "title": "Review family or guild reward surfaces",
        "summary": "Social systems give recurring value and are worth checking when reward markers appear.",
        "f2p": True,
        "priority": "Medium",
        "signals": ["family", "guild", "mail", "reward"],
    },
    {
        "id": "pve_progression",
        "title": "Stay PvE-first and keep stage progression moving",
        "summary": "Use campaign, boss, and stage progression as the main yardstick for early account growth.",
        "f2p": True,
        "priority": "High",
        "signals": ["campaign", "challenge", "boss", "stage", "normal", "battle"],
    },
]


ACTIONABLE_STATES = {"tutorial", "reward_panel", "mail", "event", "upgrade"}


def _normalize_text(value: str) -> str:
    return " ".join(str(value or "").replace("\n", " ").replace("\r", " ").split()).strip().lower()


def _format_timestamp(seconds: float) -> str:
    total_seconds = max(0, int(seconds))
    minutes, seconds_value = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds_value:02d}"
    return f"{minutes:02d}:{seconds_value:02d}"


class GuideCoachEngine:
    def __init__(self, project_root: str | Path, profile_key: str = "legends_of_mushroom", resource_reader=None):
        self.project_root = Path(project_root)
        self.profile_key = str(profile_key or "legends_of_mushroom")
        self.resource_reader = resource_reader or ResourceReader()
        self.guide = load_game_guide(self.project_root, self.profile_key)
        self.priority_keywords = [_normalize_text(keyword) for keyword in self.guide.get("priority_keywords", []) if keyword]
        self.avoid_keywords = [_normalize_text(keyword) for keyword in self.guide.get("avoid_keywords", []) if keyword]
        self.all_keywords = sorted(
            {
                keyword
                for definition in SCREEN_STATE_DEFINITIONS.values()
                for keyword in definition["keywords"]
            }
            | set(self.priority_keywords)
            | set(self.avoid_keywords)
        )

    def default_progress_state(self) -> dict:
        return {item["id"]: False for item in CHECKLIST_BLUEPRINT}

    def build_checklist(self, progress: dict | None = None, analysis: dict | None = None) -> list[dict]:
        progress = progress or {}
        current_state = str((analysis or {}).get("screen_state") or "").strip().lower()
        matched = {str(value).strip().lower() for value in (analysis or {}).get("matched_keywords", [])}
        checklist = []
        for item in CHECKLIST_BLUEPRINT:
            observed = current_state in item["signals"] or any(signal in matched for signal in item["signals"])
            checklist.append(
                {
                    "id": item["id"],
                    "title": item["title"],
                    "summary": item["summary"],
                    "priority": item["priority"],
                    "f2p": bool(item["f2p"]),
                    "completed": bool(progress.get(item["id"], False)),
                    "observed": observed,
                }
            )
        return checklist

    def analyze_frame(self, frame, checklist_progress: dict | None = None, source_label: str = "Current Capture") -> dict:
        if frame is None:
            return {
                "screen_state": "unknown",
                "screen_label": "Unknown",
                "confidence": 0.0,
                "matched_keywords": [],
                "ocr_text": "",
                "ocr_excerpt": "No frame available.",
                "recommendations": ["Capture a screen or load a replay frame to start the guide coach."],
                "tips": [],
                "checklist": self.build_checklist(checklist_progress),
                "source_label": source_label,
                "reasons": ["No frame supplied"],
                "signals": {},
            }

        ocr_text = self.resource_reader.read_text(frame, config="--psm 6")
        normalized_text = _normalize_text(ocr_text)
        text_boxes = self.resource_reader.read_text_boxes(frame, keywords=self.all_keywords, min_confidence=18.0)
        matched_keywords = self._collect_matched_keywords(normalized_text, text_boxes)
        state_scores, reasons = self._score_states(frame, normalized_text, matched_keywords)
        state = max(state_scores, key=state_scores.get) if state_scores else "unknown"
        best_score = float(state_scores.get(state, 0.0))
        if best_score <= 0.25:
            state = "unknown"
        confidence = max(0.05, min(0.98, best_score / 5.0 if best_score else 0.05))
        signals = self._build_signals(frame, matched_keywords)
        recommendations = self._recommendations_for_state(state, matched_keywords, signals)
        tips = self._tips_for_analysis(matched_keywords, state)
        analysis = {
            "screen_state": state,
            "screen_label": SCREEN_STATE_DEFINITIONS.get(state, {}).get("label", "Unknown"),
            "confidence": round(confidence, 2),
            "matched_keywords": matched_keywords,
            "ocr_text": ocr_text.strip(),
            "ocr_excerpt": self._truncate_excerpt(normalized_text),
            "ocr_boxes": text_boxes,
            "recommendations": recommendations,
            "tips": tips,
            "source_label": source_label,
            "reasons": reasons[:4],
            "signals": signals,
        }
        analysis["checklist"] = self.build_checklist(checklist_progress, analysis)
        return analysis

    def review_media(
        self,
        media_path: str | Path,
        checklist_progress: dict | None = None,
        sample_interval_seconds: float = 1.5,
        max_samples: int = 80,
    ) -> dict:
        path = Path(media_path)
        if not path.exists():
            raise FileNotFoundError(f"Media file not found: {path}")

        suffix = path.suffix.lower()
        if suffix in {".png", ".jpg", ".jpeg", ".bmp"}:
            frame = cv2.imread(str(path))
            analysis = self.analyze_frame(frame, checklist_progress=checklist_progress, source_label=path.name)
            return {
                "media_path": str(path),
                "kind": "image",
                "sample_interval_seconds": float(sample_interval_seconds),
                "frames_analyzed": 1,
                "advanced_frames": 0,
                "overall_progress_score": 0.0,
                "state_counts": {analysis["screen_state"]: 1},
                "timeline": [
                    {
                        "timestamp": "00:00",
                        "frame_index": 0,
                        "screen_state": analysis["screen_state"],
                        "screen_label": analysis["screen_label"],
                        "advance_score": 0.0,
                        "advanced": False,
                        "top_recommendation": analysis["recommendations"][0] if analysis["recommendations"] else "",
                    }
                ],
                "analysis": analysis,
                "summary": [
                    f"Loaded still image: {path.name}",
                    f"Detected screen: {analysis['screen_label']} ({analysis['confidence']:.2f})",
                ],
            }

        capture = cv2.VideoCapture(str(path))
        if not capture.isOpened():
            raise RuntimeError(f"Unable to open replay: {path}")

        fps = float(capture.get(cv2.CAP_PROP_FPS) or 30.0)
        total_frames = max(1, int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 1))
        stride = max(1, int(max(0.25, float(sample_interval_seconds)) * max(1.0, fps)))
        sampled_indices = list(range(0, total_frames, stride))[: max(1, int(max_samples))]
        timeline = []
        state_counter = Counter()
        total_score = 0.0
        advanced_frames = 0
        previous_analysis = None
        previous_frame = None

        for frame_index in sampled_indices:
            capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
            ok, frame = capture.read()
            if not ok or frame is None:
                continue
            analysis = self.analyze_frame(
                frame,
                checklist_progress=checklist_progress,
                source_label=f"{path.name} @ {frame_index}",
            )
            state_counter[analysis["screen_state"]] += 1
            progress = self._score_replay_progress(previous_analysis, analysis, previous_frame, frame)
            total_score += progress["score"]
            advanced_frames += 1 if progress["advanced"] else 0
            timeline.append(
                {
                    "timestamp": _format_timestamp(frame_index / max(1.0, fps)),
                    "frame_index": frame_index,
                    "screen_state": analysis["screen_state"],
                    "screen_label": analysis["screen_label"],
                    "advance_score": round(progress["score"], 2),
                    "advanced": progress["advanced"],
                    "reasons": progress["reasons"],
                    "top_recommendation": analysis["recommendations"][0] if analysis["recommendations"] else "",
                }
            )
            previous_analysis = analysis
            previous_frame = frame

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
            summary.append(
                f"Best segment: {max(timeline, key=lambda entry: entry['advance_score'])['timestamp']}"
            )
        return {
            "media_path": str(path),
            "kind": "video",
            "sample_interval_seconds": float(sample_interval_seconds),
            "frames_analyzed": len(timeline),
            "advanced_frames": advanced_frames,
            "overall_progress_score": round(total_score, 2),
            "state_counts": dict(state_counter),
            "timeline": timeline,
            "summary": summary,
        }

    def _collect_matched_keywords(self, normalized_text: str, text_boxes: list[dict]) -> list[str]:
        found = []
        for keyword in self.all_keywords:
            if keyword and keyword in normalized_text:
                found.append(keyword)
        for entry in text_boxes:
            keyword = _normalize_text(entry.get("keyword") or entry.get("text") or "")
            if keyword and keyword not in found:
                found.append(keyword)
        return found

    def _score_states(self, frame, normalized_text: str, matched_keywords: list[str]):
        scores = {state: 0.0 for state in SCREEN_STATE_DEFINITIONS}
        reasons = []
        matched_set = set(matched_keywords)
        for state, definition in SCREEN_STATE_DEFINITIONS.items():
            for keyword in definition["keywords"]:
                normalized_keyword = _normalize_text(keyword)
                if not normalized_keyword:
                    continue
                if normalized_keyword in matched_set:
                    scores[state] += 1.4
                elif normalized_keyword in normalized_text:
                    scores[state] += 0.9
        tutorial_strength = self._detect_tutorial_prompt(frame)
        badge_strength = self._detect_red_badges(frame)
        if tutorial_strength > 0:
            scores["tutorial"] += tutorial_strength
            reasons.append("Glowing tutorial prompt detected")
        if badge_strength > 0:
            scores["reward_panel"] += 0.5 + badge_strength
            scores["event"] += 0.3 + badge_strength / 2.0
            reasons.append("Red notification badge detected")
        if "mail" in matched_set:
            reasons.append("Mail keywords detected")
        if "claim" in matched_set or "collect" in matched_set:
            reasons.append("Claimable reward keywords detected")
        if "upgrade" in matched_set or "gear" in matched_set or "skill" in matched_set:
            reasons.append("Upgrade keywords detected")
        if "campaign" in matched_set or "challenge" in matched_set or "boss" in matched_set:
            reasons.append("Combat progression keywords detected")
        return scores, reasons

    def _build_signals(self, frame, matched_keywords: list[str]) -> dict:
        keywords = set(matched_keywords)
        return {
            "tutorial_prompt": self._detect_tutorial_prompt(frame) > 0.6,
            "red_badges": self._detect_red_badges(frame),
            "claim_surface": any(keyword in keywords for keyword in {"claim", "collect", "reward", "free"}),
            "mail_surface": "mail" in keywords or "inbox" in keywords,
            "event_surface": any(keyword in keywords for keyword in {"event", "rush", "battle pass", "spinner"}),
            "upgrade_surface": any(keyword in keywords for keyword in {"upgrade", "gear", "skill", "stat", "relic"}),
            "daily_surface": any(keyword in keywords for keyword in {"daily", "manor", "harvest", "workteam"}),
        }

    def _recommendations_for_state(self, state: str, matched_keywords: list[str], signals: dict) -> list[str]:
        matched = set(matched_keywords)
        recommendations = {
            "tutorial": [
                "Follow the glowing tutorial prompt and lamp callout before opening side menus.",
                "Use the beginner flow to unlock the main systems first; do not detour into premium surfaces.",
                "If the lamp or a hand pointer is visible, that should be your next manual action.",
            ],
            "reward_panel": [
                "Sweep free claim, collect, continue, and login reward surfaces before returning to combat.",
                "Prioritize right-rail reward dots, battle pass claims, and rush-event claims over idle menu wandering.",
                "Avoid premium buy buttons even if they share the panel with free rewards.",
            ],
            "mail": [
                "Claim safe free mail and inbox rewards, then close the panel cleanly.",
                "Use mail as a quick F2P sweep instead of staying parked in the inbox.",
            ],
            "event": [
                "Check rush, pass, spinner, and event rails for free claims first.",
                "Treat event screens as F2P review surfaces: claim freebies, skip paid bundles, then move on.",
            ],
            "upgrade": [
                "Review gear, skill, stat, relic, and awakening upgrades that improve PvE progression.",
                "Favor efficient progression upgrades instead of opening unrelated side systems.",
            ],
            "idle_combat": [
                "Stay PvE-first: keep combat, stage, and campaign progression moving.",
                "Let reward and upgrade sweeps interrupt combat only when claim markers are visible.",
            ],
            "unknown": [
                "Capture another frame or load a replay segment with clearer text for classification.",
                "Use the checklist and guide notes to decide whether this looks like tutorial, reward, event, or upgrade context.",
            ],
        }.get(state, [])
        if any(keyword in matched for keyword in self.avoid_keywords):
            recommendations.insert(0, "F2P guardrail: skip premium packs, top-ups, and early gacha spending surfaces.")
        if signals.get("daily_surface"):
            recommendations.append("Daily-loop signal detected: review manor, harvest, or workteam surfaces when finished here.")
        if signals.get("mail_surface") and state != "mail":
            recommendations.append("Mail signal is still visible somewhere on screen; do a quick inbox sweep next.")
        return recommendations[:4]

    def _tips_for_analysis(self, matched_keywords: list[str], state: str) -> list[str]:
        matched = set(matched_keywords)
        tips = []
        for entry in self.guide.get("tips", []):
            title = str(entry.get("title", "")).strip()
            summary = str(entry.get("summary", "")).strip()
            normalized_title = _normalize_text(title)
            if state == "tutorial" and "lamp" in normalized_title:
                tips.append(f"{title}: {summary}")
            elif any(keyword in normalized_title or keyword in _normalize_text(summary) for keyword in matched):
                tips.append(f"{title}: {summary}")
        if not tips and self.guide.get("summary"):
            tips.append(str(self.guide.get("summary")))
        return tips[:3]

    def _score_replay_progress(self, previous: dict | None, current: dict, previous_frame, frame) -> dict:
        if previous is None:
            return {"score": 0.0, "advanced": False, "reasons": ["Starting state"]}  # pragma: no cover

        score = 0.0
        reasons = []
        previous_state = str(previous.get("screen_state") or "unknown")
        current_state = str(current.get("screen_state") or "unknown")
        if current_state != previous_state:
            score += 2.0
            reasons.append(f"State changed from {previous_state} to {current_state}")
            if previous_state in ACTIONABLE_STATES:
                score += 1.0
                reasons.append("Actionable panel likely cleared")
        previous_keywords = set(previous.get("matched_keywords", []))
        current_keywords = set(current.get("matched_keywords", []))
        resolved_keywords = {keyword for keyword in previous_keywords - current_keywords if keyword in {"claim", "collect", "continue", "reward"}}
        if resolved_keywords:
            score += 1.2
            reasons.append("Claim-style prompt disappeared")
        new_progress_keywords = {keyword for keyword in current_keywords - previous_keywords if keyword in {"stage", "campaign", "boss", "challenge", "upgrade", "gear"}}
        if new_progress_keywords:
            score += 0.9
            reasons.append("New progression keywords appeared")
        frame_delta = self._frame_delta_ratio(previous_frame, frame)
        if frame_delta > 0.10:
            score += 0.8
            reasons.append(f"Visual transition changed {frame_delta * 100.0:.0f}% of the frame")
        if current_state == previous_state and current_keywords == previous_keywords:
            score -= 0.4
            reasons.append("Screen stayed effectively unchanged")
        return {"score": score, "advanced": score >= 1.5, "reasons": reasons[:3]}

    def _frame_delta_ratio(self, previous_frame, frame) -> float:
        if previous_frame is None or frame is None or previous_frame.shape != frame.shape:
            return 0.0
        previous_gray = cv2.cvtColor(previous_frame, cv2.COLOR_BGR2GRAY)
        current_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        delta = cv2.absdiff(previous_gray, current_gray)
        return float((delta > 18).mean())

    def _detect_red_badges(self, frame) -> float:
        if frame is None:
            return 0.0
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        lower_red_a = cv2.inRange(hsv, (0, 120, 110), (12, 255, 255))
        lower_red_b = cv2.inRange(hsv, (168, 120, 110), (180, 255, 255))
        red_mask = cv2.bitwise_or(lower_red_a, lower_red_b)
        badge_ratio = float(red_mask.mean() / 255.0)
        return min(1.5, badge_ratio * 22.0)

    def _detect_tutorial_prompt(self, frame) -> float:
        if frame is None:
            return 0.0
        height, width = frame.shape[:2]
        x0 = int(width * 0.22)
        x1 = int(width * 0.78)
        y0 = int(height * 0.70)
        y1 = min(height, int(height * 0.98))
        if x1 <= x0 or y1 <= y0:
            return 0.0
        region = frame[y0:y1, x0:x1]
        hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
        glow_mask = cv2.inRange(hsv, (10, 100, 120), (40, 255, 255))
        glow_ratio = float(glow_mask.mean() / 255.0)
        return min(2.0, glow_ratio * 18.0)

    def _truncate_excerpt(self, text: str, limit: int = 180) -> str:
        if not text:
            return "No OCR text detected."
        if len(text) <= limit:
            return text
        return f"{text[:limit - 3]}..."
