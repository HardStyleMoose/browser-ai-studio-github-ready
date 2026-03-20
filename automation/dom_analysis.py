from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Callable

from automation.guide_coach import SCREEN_STATE_DEFINITIONS


def _clean_text(value: str) -> str:
    return " ".join(str(value or "").replace("\n", " ").replace("\r", " ").split()).strip()


def _normalize_bounds(bounds: dict | None) -> dict:
    payload = dict(bounds or {})
    return {
        "x": max(0, int(payload.get("x", 0) or 0)),
        "y": max(0, int(payload.get("y", 0) or 0)),
        "width": max(0, int(payload.get("width", 0) or 0)),
        "height": max(0, int(payload.get("height", 0) or 0)),
    }


def frame_hash(frame) -> str:
    if frame is None:
        return ""
    try:
        return hashlib.sha1(memoryview(frame).tobytes()).hexdigest()
    except Exception:
        try:
            return hashlib.sha1(bytes(frame)).hexdigest()
        except Exception:
            return ""


class DomAnalyzer:
    SNAPSHOT_SCRIPT = """() => {
        const clean = (value) => String(value || '').replace(/\\s+/g, ' ').trim();
        const visible = (element) => {
            if (!element) return false;
            const style = window.getComputedStyle(element);
            if (!style || style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity || '1') <= 0.02) {
                return false;
            }
            const rect = element.getBoundingClientRect();
            return rect.width >= 4 && rect.height >= 4;
        };
        const selectorHint = (element) => {
            if (!element) return '';
            const id = clean(element.id || '');
            if (id) return `#${id}`;
            const name = clean(element.getAttribute('name') || '');
            if (name) return `[name="${name}"]`;
            const testId = clean(element.getAttribute('data-testid') || element.getAttribute('data-test') || '');
            if (testId) return `[data-testid="${testId}"]`;
            const classes = Array.from(element.classList || []).slice(0, 2).map((item) => clean(item)).filter(Boolean);
            if (classes.length) return `${element.tagName.toLowerCase()}.${classes.join('.')}`;
            return element.tagName.toLowerCase();
        };
        const candidates = new Set([
            'button',
            'a[href]',
            'input',
            'textarea',
            'select',
            '[role="button"]',
            '[role="link"]',
            '[role="tab"]',
            '[role="menuitem"]',
            '[onclick]',
            '[class*="btn"]',
            '[class*="button"]',
            '[class*="claim"]',
            '[class*="reward"]',
            '[class*="event"]',
            '[class*="mail"]',
            '[class*="upgrade"]',
            '[id*="claim"]',
            '[id*="reward"]',
            '[id*="event"]',
            '[id*="mail"]',
            '[id*="upgrade"]'
        ]);
        const actionables = [];
        const seen = new Set();
        for (const selector of candidates) {
            for (const element of Array.from(document.querySelectorAll(selector)).slice(0, 180)) {
                if (!visible(element)) continue;
                const rect = element.getBoundingClientRect();
                const text = clean(element.innerText || element.textContent || element.getAttribute('aria-label') || element.getAttribute('title') || element.getAttribute('value') || '');
                if (!text && rect.width < 14 && rect.height < 14) continue;
                const token = `${selectorHint(element)}|${Math.round(rect.x)}|${Math.round(rect.y)}|${Math.round(rect.width)}|${Math.round(rect.height)}|${text}`;
                if (seen.has(token)) continue;
                seen.add(token);
                const role = clean(element.getAttribute('role') || element.tagName.toLowerCase());
                const disabled = element.hasAttribute('disabled') || element.getAttribute('aria-disabled') === 'true';
                const confidence = Math.min(
                    0.98,
                    0.32
                    + (text ? 0.18 : 0.0)
                    + ((role === 'button' || role === 'a' || role === 'link') ? 0.18 : 0.0)
                    + (!disabled ? 0.12 : -0.10)
                    + ((rect.width >= 36 && rect.height >= 18) ? 0.10 : 0.0)
                );
                actionables.push({
                    text,
                    role,
                    selector_hint: selectorHint(element),
                    visible: true,
                    enabled: !disabled,
                    confidence,
                    bounds: {
                        x: Math.max(0, Math.round(rect.x)),
                        y: Math.max(0, Math.round(rect.y)),
                        width: Math.max(0, Math.round(rect.width)),
                        height: Math.max(0, Math.round(rect.height))
                    }
                });
                if (actionables.length >= 120) break;
            }
            if (actionables.length >= 120) break;
        }
        const rawTextSummary = clean(((document.body && document.body.innerText) || '').slice(0, 5000));
        return {
            url: window.location.href,
            title: clean(document.title || ''),
            viewport: { width: window.innerWidth || 0, height: window.innerHeight || 0 },
            raw_text_summary: rawTextSummary.slice(0, 1800),
            actionables
        };
    }"""

    def __init__(self, project_root: str | Path | None = None):
        self.project_root = Path(project_root) if project_root else None

    def capture_snapshot(
        self,
        page,
        resolve_result: Callable[[object], object] | None = None,
        screenshot_hash: str = "",
    ) -> dict:
        if page is None:
            return self.normalize_snapshot(None, screenshot_hash=screenshot_hash)
        resolver = resolve_result if callable(resolve_result) else (lambda value: value)
        payload = resolver(page.evaluate(self.SNAPSHOT_SCRIPT))
        return self.normalize_snapshot(payload, screenshot_hash=screenshot_hash)

    def normalize_snapshot(self, payload: dict | None, screenshot_hash: str = "") -> dict:
        payload = dict(payload or {})
        actionables = []
        for entry in list(payload.get("actionables", []) or []):
            normalized = {
                "text": _clean_text((entry or {}).get("text", "")),
                "role": _clean_text((entry or {}).get("role", "")),
                "selector_hint": _clean_text((entry or {}).get("selector_hint", "")),
                "visible": bool((entry or {}).get("visible", True)),
                "enabled": bool((entry or {}).get("enabled", True)),
                "confidence": max(0.0, min(1.0, float((entry or {}).get("confidence", 0.5) or 0.5))),
                "bounds": _normalize_bounds((entry or {}).get("bounds")),
            }
            if normalized["bounds"]["width"] <= 0 or normalized["bounds"]["height"] <= 0:
                continue
            center_x = normalized["bounds"]["x"] + normalized["bounds"]["width"] // 2
            center_y = normalized["bounds"]["y"] + normalized["bounds"]["height"] // 2
            normalized["center"] = [center_x, center_y]
            normalized["token"] = hashlib.sha1(
                json.dumps(
                    [
                        normalized["selector_hint"],
                        normalized["text"],
                        normalized["role"],
                        normalized["center"],
                    ],
                    ensure_ascii=True,
                ).encode("utf-8")
            ).hexdigest()[:12]
            actionables.append(normalized)
        viewport = dict(payload.get("viewport") or {})
        snapshot = {
            "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "url": str(payload.get("url") or "").strip(),
            "title": _clean_text(payload.get("title", "")),
            "viewport": {
                "width": max(0, int(viewport.get("width", 0) or 0)),
                "height": max(0, int(viewport.get("height", 0) or 0)),
            },
            "raw_text_summary": _clean_text(payload.get("raw_text_summary", ""))[:1800],
            "actionables": actionables,
            "actionable_count": len(actionables),
            "screenshot_hash": str(screenshot_hash or "").strip(),
        }
        return snapshot

    def build_screen_action_map(
        self,
        dom_snapshot: dict | None,
        ocr_boxes: list[dict] | None = None,
        screen_state: str = "",
        guide_analysis: dict | None = None,
        evidence_summary: dict | None = None,
    ) -> dict:
        screen_state_key = str(screen_state or (guide_analysis or {}).get("screen_state") or "unknown").strip().lower()
        state_definition = SCREEN_STATE_DEFINITIONS.get(screen_state_key, {})
        state_keywords = {str(value).strip().lower() for value in state_definition.get("keywords", []) if str(value).strip()}
        matched_keywords = {
            str(value).strip().lower()
            for value in list((guide_analysis or {}).get("matched_keywords", []) or [])
            if str(value).strip()
        }
        successful_targets = {
            str(row.get("keyword") or row.get("target_type") or "").strip().lower()
            for row in list((evidence_summary or {}).get("task_hints", []) or [])
            if str(row.get("keyword") or row.get("target_type") or "").strip()
        }
        avoid_keywords = {
            str(row.get("keyword") or row.get("kind") or "").strip().lower()
            for row in list((evidence_summary or {}).get("avoid_patterns", []) or [])
            if str(row.get("keyword") or row.get("kind") or "").strip()
        }
        priority_keywords = state_keywords | matched_keywords | successful_targets
        merged = []
        dom_snapshot = dict(dom_snapshot or {})
        for entry in list(dom_snapshot.get("actionables", []) or []):
            text = _clean_text(entry.get("text", ""))
            lowered = text.lower()
            keyword_bonus = 0.0
            matched = ""
            for keyword in sorted(priority_keywords, key=len, reverse=True):
                if keyword and keyword in lowered:
                    keyword_bonus = 1.4
                    matched = keyword
                    break
            for keyword in sorted(avoid_keywords, key=len, reverse=True):
                if keyword and keyword in lowered:
                    keyword_bonus -= 1.2
                    break
            bounds = _normalize_bounds(entry.get("bounds"))
            size_penalty = 0.0
            if bounds["width"] * bounds["height"] > 120000:
                size_penalty -= 0.8
            score = round(
                float(entry.get("confidence", 0.0) or 0.0) * 3.8
                + (0.5 if entry.get("enabled", True) else -0.8)
                + (0.4 if entry.get("visible", True) else -0.8)
                + keyword_bonus
                + size_penalty,
                3,
            )
            merged.append(
                {
                    "source": "dom",
                    "label": text or entry.get("selector_hint") or entry.get("role") or "DOM action",
                    "keyword": matched,
                    "selector_hint": entry.get("selector_hint", ""),
                    "role": entry.get("role", ""),
                    "bounds": bounds,
                    "center": list(entry.get("center") or [bounds["x"] + bounds["width"] // 2, bounds["y"] + bounds["height"] // 2]),
                    "enabled": bool(entry.get("enabled", True)),
                    "score": score,
                    "reason": f"DOM action | keyword bonus {keyword_bonus:+.1f} | size penalty {size_penalty:+.1f}",
                    "token": str(entry.get("token") or ""),
                }
            )
        for entry in list(ocr_boxes or []):
            text = _clean_text(entry.get("text", ""))
            lowered = text.lower()
            keyword_bonus = 0.0
            matched = str(entry.get("keyword") or "").strip().lower()
            if matched and matched in priority_keywords:
                keyword_bonus += 1.2
            elif any(keyword in lowered for keyword in priority_keywords):
                keyword_bonus += 1.0
                matched = next((keyword for keyword in priority_keywords if keyword in lowered), matched)
            if matched in avoid_keywords or any(keyword in lowered for keyword in avoid_keywords):
                keyword_bonus -= 1.0
            bounds = _normalize_bounds(entry)
            confidence = max(0.0, min(100.0, float(entry.get("confidence", 0.0) or 0.0)))
            score = round((confidence / 24.0) + keyword_bonus, 3)
            merged.append(
                {
                    "source": "ocr",
                    "label": text or matched or "OCR action",
                    "keyword": matched,
                    "selector_hint": "",
                    "role": "text",
                    "bounds": bounds,
                    "center": [bounds["x"] + bounds["width"] // 2, bounds["y"] + bounds["height"] // 2],
                    "enabled": True,
                    "score": score,
                    "reason": f"OCR text | confidence {confidence:.1f} | keyword bonus {keyword_bonus:+.1f}",
                    "token": hashlib.sha1(f"ocr|{text}|{bounds}".encode("utf-8")).hexdigest()[:12],
                }
            )
        merged.sort(key=lambda item: (-float(item.get("score", 0.0) or 0.0), item.get("label", "").lower()))
        merged = merged[:24]
        summary_lines = [
            f"Screen State: {screen_state_key or 'unknown'}",
            f"DOM Actionables: {len(dom_snapshot.get('actionables', []) or [])}",
            f"OCR Actionables: {len(list(ocr_boxes or []))}",
        ]
        if merged:
            summary_lines.append("Top Ranked Actions:")
            for row in merged[:5]:
                summary_lines.append(
                    f"- {row['label']} [{row['source'].upper()}] score {float(row.get('score', 0.0)):.2f}"
                )
        hints = list((evidence_summary or {}).get("summary_lines", []) or [])
        if hints:
            summary_lines.append("")
            summary_lines.append("Evidence Hints:")
            summary_lines.extend(str(line) for line in hints[:4])
        return {
            "screen_state": screen_state_key or "unknown",
            "dom_snapshot": dom_snapshot,
            "merged_actions": merged,
            "summary_lines": summary_lines,
            "priority_keywords": sorted(priority_keywords),
            "avoid_keywords": sorted(avoid_keywords),
        }
