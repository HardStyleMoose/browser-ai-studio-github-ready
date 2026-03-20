from __future__ import annotations

import asyncio
import base64
import inspect
import os
import random
import shutil
import threading
import time
import traceback
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path
from queue import Empty, SimpleQueue
from typing import Callable
from urllib.parse import urlparse

import cv2
import numpy as np

from ai.level_detector import LevelDetector
from ai.progress_tracker import ProgressTracker
from ai.reward_engine import RewardEngine
from ai.state_extractor import StateExtractor
from ai.state_utils import build_state_vector
from automation.game_profiles import format_game_display_name, resolve_game_profile
from automation.game_launcher import get_window_region
from automation.guide_learning import load_game_guide
from automation.input_manager import InputManager
from automation.task_evidence_store import TaskEvidenceStore
from automation.dom_live_policy_store import DomLivePolicyStore
from automation.worker_learning import WorkerLearningMemory
from automation.worker_session_store import WorkerSessionStore
from core.browser_runtime import ensure_playwright_chromium
from core.gpu_telemetry import get_host_gpu_info, sample_gpu_usage
from vision.resource_reader import ResourceReader
from vision.screen_capture import capture_screen

try:
    from playwright.sync_api import sync_playwright
except Exception:  # pragma: no cover - optional at runtime
    sync_playwright = None

try:
    from playwright.async_api import async_playwright
except Exception:  # pragma: no cover - optional at runtime
    async_playwright = None

try:
    import psutil
except Exception:  # pragma: no cover - optional runtime dependency
    psutil = None


def _normalized_browser_key(key: str) -> str:
    mapping = {
        "space": "Space",
        "enter": "Enter",
        "return": "Enter",
        "shift": "Shift",
        "ctrl": "Control",
        "control": "Control",
        "alt": "Alt",
        "esc": "Escape",
        "escape": "Escape",
        "tab": "Tab",
        "up": "ArrowUp",
        "down": "ArrowDown",
        "left": "ArrowLeft",
        "right": "ArrowRight",
    }
    text = str(key or "").strip()
    return mapping.get(text.lower(), text)


def _normalized_browser_url(url: str) -> str:
    text = str(url or "").strip()
    if not text:
        return "https://lom.joynetgame.com"
    parsed = urlparse(text)
    if not parsed.scheme:
        text = f"https://{text}"
        parsed = urlparse(text)
    if not parsed.netloc and parsed.path:
        text = f"https://{parsed.path.lstrip('/')}"
    return text


def _browser_host_label(url: str) -> str:
    try:
        parsed = urlparse(_normalized_browser_url(url))
        if parsed.netloc:
            return parsed.netloc.replace("www.", "")
    except Exception:
        pass
    return _normalized_browser_url(url)


def browser_prewarm_signature(config) -> tuple:
    region = dict(getattr(config, "capture_region", {}) or {})
    mode = str(getattr(config, "mode", "browser") or "browser").strip().lower()
    browser_url = _normalized_browser_url(getattr(config, "browser_url", "https://lom.joynetgame.com"))
    dom_mode = str(getattr(config, "browser_dom_drive_mode", "legacy") or "legacy").strip().lower()
    if dom_mode not in {"legacy", "assist", "dom_live_experimental"}:
        dom_mode = "legacy"
    return (
        mode,
        browser_url,
        bool(getattr(config, "gpu_acceleration_enabled", False)),
        max(320, int(region.get("width", 1280) or 1280)),
        max(240, int(region.get("height", 720) or 720)),
        dom_mode,
    )


class WorkerInputManager(InputManager):
    def __init__(self, mode: str, antiban_config=None):
        super().__init__(enable_game_state=False, antiban_config=antiban_config)
        self.mode = str(mode or "desktop").lower()
        self.page = None
        self.browser_offset = (0, 0)
        self.browser_capture_scale = (1.0, 1.0)
        self.browser_runner = None
        self.last_action = "idle"
        self.fast_browser_input = bool(self.antiban.get("browser_fast_input", self.mode == "browser"))

    def bind_browser_page(self, page, offset=(0, 0), runner=None, capture_scale=(1.0, 1.0)):
        self.page = page
        self.browser_runner = runner
        self.browser_offset = (
            max(0, int((offset or (0, 0))[0])),
            max(0, int((offset or (0, 0))[1])),
        )
        try:
            scale_x = float((capture_scale or (1.0, 1.0))[0] or 1.0)
            scale_y = float((capture_scale or (1.0, 1.0))[1] or 1.0)
        except Exception:
            scale_x = 1.0
            scale_y = 1.0
        self.browser_capture_scale = (
            max(0.10, scale_x),
            max(0.10, scale_y),
        )

    def _resolve_browser_result(self, result):
        if callable(self.browser_runner):
            return self.browser_runner(result)
        return result

    def click(self, x, y):
        x = int(x)
        y = int(y)
        self.last_action = f"click({x}, {y})"
        if self.mode == "browser" and self.page is not None:
            offset_x, offset_y = self.browser_offset
            scale_x, scale_y = self.browser_capture_scale
            page_x = int(round((x / scale_x) + offset_x))
            page_y = int(round((y / scale_y) + offset_y))
            if self.fast_browser_input:
                self._resolve_browser_result(self.page.mouse.click(page_x, page_y, delay=0))
                return
            if self.antiban.get("random_delay", True):
                time.sleep(0.03 + random.uniform(0.01, 0.08))
            steps = 8 if self.antiban.get("human_mouse", True) else 1
            self._resolve_browser_result(self.page.mouse.move(page_x, page_y, steps=steps))
            self._resolve_browser_result(
                self.page.mouse.click(page_x, page_y, delay=50 if self.antiban.get("human_mouse", True) else 0)
            )
            return
        super().click(x, y)

    def click_many(self, points):
        point_list = [(int(px), int(py)) for px, py in list(points or []) if px is not None and py is not None]
        if not point_list:
            return
        if self.mode == "browser" and self.page is not None and self.fast_browser_input:
            offset_x, offset_y = self.browser_offset
            scale_x, scale_y = self.browser_capture_scale
            for point_x, point_y in point_list:
                page_x = int(round((point_x / scale_x) + offset_x))
                page_y = int(round((point_y / scale_y) + offset_y))
                self._resolve_browser_result(self.page.mouse.click(page_x, page_y, delay=0))
            self.last_action = f"clicks:{len(point_list)}"
            return
        for point_x, point_y in point_list:
            self.click(point_x, point_y)

    def press_key(self, key):
        self.last_action = f"key:{key}"
        if self.mode == "browser" and self.page is not None:
            if not self.fast_browser_input and self.antiban.get("random_delay", True):
                time.sleep(0.03 + random.uniform(0.01, 0.08))
            self._resolve_browser_result(self.page.keyboard.press(_normalized_browser_key(str(key))))
            return
        super().press_key(key)


class WorkerStateTracker:
    def __init__(self, profile=None):
        self.profile = profile
        self.reader = ResourceReader()
        self.extractor = StateExtractor()
        self.progress = ProgressTracker()
        self.level_detector = LevelDetector()
        self.reward_engine = RewardEngine()
        self.last_state = {"gold": 0, "xp": 0, "level": 0, "health": 0, "damage": 0}
        self.last_reward = 0.0
        self.last_text = ""
        self.last_resources = []
        self._cached_ocr_text = ""
        self._last_ocr_at = 0.0

    def update(self, frame, preferred_text: str = "", allow_ocr: bool = True, ocr_cooldown_s: float = 1.5):
        now = time.time()
        text = str(preferred_text or "").strip()
        should_run_ocr = bool(allow_ocr) and (
            not text or (now - self._last_ocr_at) >= max(0.2, float(ocr_cooldown_s or 0.2))
        )
        if should_run_ocr:
            try:
                ocr_text = (self.reader.read_text(frame, config="--psm 6") or "").strip()
            except Exception:
                ocr_text = ""
            if ocr_text:
                self._cached_ocr_text = ocr_text
                self._last_ocr_at = now
                if text:
                    text = f"{text}\n{ocr_text}"
                else:
                    text = ocr_text
        elif not text:
            text = self._cached_ocr_text or ""
        resources = self.extractor.extract(text) or []
        levelup = self.level_detector.check_level_up(text)
        state_vector = build_state_vector(resources, damage=0, levelup=levelup)
        xp_gain = self.progress.compute_reward(state_vector)
        reward = self.reward_engine.compute(xp_gain, damage=0, levelup=levelup)
        self.last_text = text
        self.last_resources = list(resources)
        self.last_state = {
            "gold": state_vector[0] if len(state_vector) > 0 else 0,
            "xp": state_vector[1] if len(state_vector) > 1 else 0,
            "level": state_vector[2] if len(state_vector) > 2 else 0,
            "health": state_vector[3] if len(state_vector) > 3 else 0,
            "damage": state_vector[4] if len(state_vector) > 4 else 0,
        }
        self.last_reward = reward
        return dict(self.last_state), float(reward)


@dataclass
class ClusterWorkerConfig:
    worker_id: str
    mode: str
    browser_url: str
    desktop_exe: str
    desktop_window_title: str
    capture_region: dict
    behavior_graph: dict
    model_name: str
    memory_limit_gb: float
    cpu_limit_percent: float
    target_fps: float
    gpu_acceleration_enabled: bool
    mouse_enabled: bool
    keyboard_enabled: bool
    antiban_config: dict
    quick_mode: bool
    watch_reward_ads: bool
    auto_learning_enabled: bool
    learning_store_dir: str
    browser_dom_drive_mode: str
    dom_confirmation_required: bool
    dom_live_cooldown_ms: int
    dom_live_max_repeat_attempts: int
    dom_evidence_weight: float
    browser_prewarm_enabled: bool
    preview_target_fps: int
    control_preview_target_fps: int
    standby_pool_slot: bool = False
    standby_slot_id: str = ""
    standby_idle_timeout_s: float = 90.0


class ClusterWorkerRuntime(threading.Thread):
    def __init__(self, config: ClusterWorkerConfig, log_callback: Callable[[str], None] | None = None):
        super().__init__(daemon=True, name=f"ClusterWorker-{config.worker_id}")
        self.config = config
        self.log_callback = log_callback
        self.stop_event = threading.Event()
        self.state_lock = threading.Lock()
        self.project_root = Path(__file__).resolve().parent.parent
        self._standby_pool_slot = bool(getattr(config, "standby_pool_slot", False))
        self._standby_slot_id = str(getattr(config, "standby_slot_id", "") or config.worker_id or "standby-slot")
        self._standby_claim_lock = threading.Lock()
        self._standby_claim_event = threading.Event()
        self._standby_claim_config = None
        self._standby_claimed_by = ""
        self._standby_ready_at = 0.0
        self._standby_claimed_at = 0.0
        self._standby_wait_started_at = 0.0
        self._standby_last_reason = ""
        self.game_profile = resolve_game_profile(
            config.mode,
            browser_url=config.browser_url,
            desktop_window_title=config.desktop_window_title,
            desktop_exe=config.desktop_exe,
        )
        self.input_manager = WorkerInputManager(config.mode, antiban_config=config.antiban_config)
        self.input_manager.mouse_enabled = bool(config.mouse_enabled)
        self.input_manager.keyboard_enabled = bool(config.keyboard_enabled)
        self.state_tracker = WorkerStateTracker(profile=self.game_profile)
        self.ocr_reader = ResourceReader()

        self._playwright = None
        self._playwright_manager = None
        self._playwright_async_mode = False
        self._browser_async_loop = None
        self._browser = None
        self._browser_context = None
        self._browser_cdp_session = None
        self._page = None
        self._browser_capture_bounds = None
        self._browser_capture_scale = self._preferred_browser_capture_scale()
        self._browser_viewport_size = None
        self._browser_streaming_enabled = self.config.mode.lower() == "browser"
        self._browser_stream_active = False
        self._browser_stream_handler_registered = False
        self._browser_stream_lock = threading.Lock()
        self._browser_stream_payload = None
        self._browser_stream_payload_at = 0.0
        self._browser_stream_latest_frame = None
        self._browser_stream_latest_frame_at = 0.0
        self._browser_stream_last_consumed_at = 0.0
        self._browser_stream_last_signature = None
        self._browser_stream_last_reused_at = 0.0
        self._browser_stream_failures = 0
        self._fit_surface_checkpoints_done = set()
        self._browser_prefers_canvas_capture = self.config.mode.lower() == "browser"
        self._profile_last_state = None
        self._profile_action_label = "warming up"
        self._last_learning_action = None
        self._ad_policy_label = "Ads Off"
        self.guide_context = load_game_guide(self.project_root, self.game_profile.key)
        self.evidence_store = TaskEvidenceStore(self.project_root)
        self.learning_memory = None
        self.session_store = None
        self.dom_live_store = None
        self.session_state = {}
        self._session_last_saved_steps = 0
        self._last_persist_at = 0.0
        self._steps = 0
        self._total_reward = 0.0
        self._started_at = None
        self._last_frame_shape = None
        self._last_error = ""
        self._latest_frame = None
        self._latest_frame_at = None
        self._frame_times = deque(maxlen=24)
        self._preview_tier_cache = {
            "preview": {"frame": None, "token": None, "source_token": None, "emitted_at": 0.0},
            "control": {"frame": None, "token": None, "source_token": None, "emitted_at": 0.0},
        }
        self._cpu_usage_samples = deque(maxlen=24)
        self._gpu_usage_samples = deque(maxlen=24)
        self._last_loop_work_s = 0.0
        self._last_loop_sleep_s = 0.0
        self._logical_cores = max(1, int(os.cpu_count() or 1))
        self._host_gpu_info = {"available": False, "name": "Disabled", "memory_gb": 0.0}
        self._browser_process_ids = []
        self._browser_engine_label = "Chromium"
        self._browser_gpu_percent = 0.0
        self._host_gpu_percent = 0.0
        self._browser_gpu_vendor = "Disabled"
        self._browser_gpu_renderer = "Disabled"
        self._effective_gpu_enabled = False
        self._gpu_launch_note = "Legacy browser mode"
        self._last_gpu_poll_at = 0.0
        self._gpu_executor = None
        self._gpu_future = None
        self._browser_request_lock = threading.Lock()
        self._pending_browser_requests = 0
        self._last_browser_request_at = 0.0
        self._last_loading_marker = ""
        self._last_loading_frame_probe_at = 0.0
        self._last_loading_frame_marker = ""
        self._last_state_refresh_at = 0.0
        self._manual_control_active = False
        self._manual_command_queue = SimpleQueue()
        self._cached_game_state = dict(self.state_tracker.last_state)
        self._cached_reward_value = 0.0
        self._latest_state_text = ""
        self._latest_dom_snapshot = {}
        self._cached_visual_targets = []
        self._cached_ocr_visual_targets = []
        self._last_ocr_visual_targets_at = 0.0
        self._cached_dom_state_text = ""
        self._last_dom_state_text_at = 0.0
        self._keyword_candidate_cache = {}
        self._dom_live_rank_cache = {}
        self._dom_live_candidate_attempts = {}
        self._dom_live_evidence_summary = {}
        self._dom_live_screen_state = "unknown"
        self._dom_live_last_summary = []
        self._dom_live_last_action = ""
        self._dom_live_last_confirmation = ""
        self._dom_live_last_fallback_reason = ""
        self._visual_click_history = {}
        self._visual_click_streaks = {}
        self._task_cycle_index = 0
        self._task_stats = {}
        self._task_last_attempt_at = {}
        self._task_last_success_at = {}
        self._pending_task_context = None
        self._analysis_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"{config.worker_id}-analysis")
        self._analysis_future = None
        self._analysis_submitted_at = 0.0
        self._analysis_available_at = 0.0
        self._analysis_consumed_at = 0.0
        self._next_action_due_at = 0.0
        self._dom_analyzer = None
        self._snapshot = {
            "status": "starting",
            "task": "Starting Worker Runtime",
            "progress": "0 steps",
            "capture": self._default_capture_summary(),
            "model": config.model_name,
            "last_action": "idle",
            "last_error": "",
            "uptime": "0s",
            "game": self._game_label(),
            "profile": self.game_profile.name,
            "strategy": self._strategy_label(),
            "mode": config.mode.title(),
            "cpu": self._cpu_usage_label(),
            "cpu_detail": self._cpu_detail_label(),
            "cpu_limit_percent": self._cpu_limit_percent(),
            "gpu": self._gpu_usage_label(),
            "gpu_detail": self._gpu_detail_label(),
            "mem": f"0.0/{config.memory_limit_gb:.1f} GB",
            "memory_limit_gb": max(0.5, float(config.memory_limit_gb)),
            "fps": "0.0",
            "ads": self._ad_policy_summary(),
            "learning": self._learning_summary(),
            "manual_control": False,
            "dom_drive_enabled": self._dom_drive_enabled(),
            "dom_drive_mode": self._dom_drive_mode(),
            "dom_top_candidates": [],
            "dom_last_action": "",
            "dom_last_confirmation": "",
            "dom_fallback_reason": "",
            "standby_slot": self._standby_pool_slot,
        }
        self._last_runtime_snapshot_at = 0.0
        self._last_runtime_snapshot_status = str(self._snapshot.get("status") or "starting").strip().lower() or "starting"
        self._bind_worker_identity(config)

    def stop(self):
        self.stop_event.set()
        self._standby_claim_event.set()

    def standby_signature(self) -> tuple:
        return browser_prewarm_signature(self.config)

    def standby_ready(self) -> bool:
        snapshot = self.snapshot()
        return bool(snapshot.get("alive")) and str(snapshot.get("status") or "").strip().lower() == "standby_ready"

    def can_claim_standby(self, config: ClusterWorkerConfig) -> bool:
        if not self._standby_pool_slot or self.stop_event.is_set():
            return False
        if browser_prewarm_signature(config) != self.standby_signature():
            return False
        snapshot = self.snapshot()
        return str(snapshot.get("status") or "").strip().lower() == "standby_ready"

    def claim_standby(self, config: ClusterWorkerConfig, log_callback: Callable[[str], None] | None = None) -> bool:
        if not self.can_claim_standby(config):
            return False
        with self._standby_claim_lock:
            if self.stop_event.is_set() or self._standby_claim_event.is_set():
                return False
            if browser_prewarm_signature(config) != self.standby_signature():
                return False
            self._standby_claim_config = replace(
                config,
                standby_pool_slot=False,
                standby_slot_id="",
            )
            self._standby_claimed_by = str(config.worker_id or "").strip()
            if log_callback is not None:
                self.log_callback = log_callback
            self._standby_last_reason = f"Claimed by {self._standby_claimed_by or 'worker'}"
            self._standby_claim_event.set()
            return True

    def _bind_worker_identity(self, config: ClusterWorkerConfig):
        self.config = config
        self.name = f"ClusterWorker-{self.config.worker_id}"
        self._standby_pool_slot = bool(getattr(config, "standby_pool_slot", False))
        self._standby_slot_id = str(getattr(config, "standby_slot_id", "") or self._standby_slot_id or config.worker_id)
        self.game_profile = resolve_game_profile(
            self.config.mode,
            browser_url=self.config.browser_url,
            desktop_window_title=self.config.desktop_window_title,
            desktop_exe=self.config.desktop_exe,
        )
        self.state_tracker.profile = self.game_profile
        self.input_manager.mode = str(self.config.mode or "desktop").lower()
        self.input_manager.antiban = dict(self.config.antiban_config or {})
        self.input_manager.mouse_enabled = bool(self.config.mouse_enabled)
        self.input_manager.keyboard_enabled = bool(self.config.keyboard_enabled)
        self.input_manager.fast_browser_input = bool(
            self.input_manager.antiban.get("browser_fast_input", self.input_manager.mode == "browser")
        )
        self.guide_context = load_game_guide(self.project_root, self.game_profile.key)
        learning_root = Path(self.config.learning_store_dir or (self.project_root / "data" / "worker_learning"))
        self.learning_memory = (
            WorkerLearningMemory(learning_root, self.game_profile.key, self._game_label(), self.config.worker_id)
            if bool(self.config.auto_learning_enabled)
            else None
        )
        self.session_store = WorkerSessionStore(
            self.project_root / "data" / "worker_sessions",
            self._game_label(),
            self.config.worker_id,
        )
        self.dom_live_store = DomLivePolicyStore(
            self.project_root / "data" / "dom_live_learning",
            self._game_label(),
            self.game_profile.name,
            self.config.worker_id,
        )
        self.session_state = self.session_store.load()
        self._dom_live_evidence_summary = {}
        self._task_stats = {}
        self._task_last_attempt_at = {}
        self._task_last_success_at = {}
        self._task_cycle_index = 0
        self._session_last_saved_steps = 0
        self._last_persist_at = 0.0
        self._steps = 0
        self._total_reward = 0.0
        self._dom_live_last_action = ""
        self._dom_live_last_confirmation = ""
        self._dom_live_last_fallback_reason = ""
        self._restore_session_state()
        self._update_snapshot(
            model=self.config.model_name,
            game=self._game_label(),
            profile=self.game_profile.name,
            strategy=self._strategy_label(),
            mode=self.config.mode.title(),
            ads=self._ad_policy_summary(),
            learning=self._learning_summary(),
            cpu=self._cpu_usage_label(),
            cpu_detail=self._cpu_detail_label(),
            cpu_limit_percent=self._cpu_limit_percent(),
            gpu=self._gpu_usage_label(),
            gpu_detail=self._gpu_detail_label(),
            mem=self._memory_usage_label(),
            memory_limit_gb=max(0.5, float(self.config.memory_limit_gb)),
            standby_slot=self._standby_pool_slot,
        )

    def _enter_standby_until_claimed(self) -> bool:
        self._standby_ready_at = time.time()
        self._standby_wait_started_at = self._standby_ready_at
        idle_timeout = max(10.0, float(getattr(self.config, "standby_idle_timeout_s", 90.0) or 90.0))
        self._update_snapshot(
            status="standby_ready",
            task="Standby Browser Session Ready",
            progress="Waiting for a browser worker to claim this hidden prewarmed session.",
            capture=self._capture_summary(),
            standby_slot=True,
        )
        while not self.stop_event.is_set():
            if self._standby_claim_event.wait(timeout=0.20):
                claimed_config = self._standby_claim_config
                if claimed_config is None:
                    return False
                self._standby_claimed_at = time.time()
                self._standby_last_reason = f"Claimed by {self._standby_claimed_by or claimed_config.worker_id}"
                self._update_snapshot(
                    status="standby_claimed",
                    task=f"Claimed By {claimed_config.worker_id}",
                    progress="Activating prewarmed browser session for autoplay.",
                    capture=self._capture_summary(),
                    standby_slot=False,
                )
                self._bind_worker_identity(claimed_config)
                self._standby_pool_slot = False
                return True
            if (time.time() - self._standby_wait_started_at) >= idle_timeout:
                self._standby_last_reason = "Standby idle timeout reached."
                self._update_snapshot(
                    status="stopped",
                    task="Standby Timeout",
                    progress="Unused standby browser session timed out and was released.",
                    capture=self._capture_summary(),
                    standby_slot=True,
                )
                return False
            if self._browser_stream_active:
                self._pump_browser_stream()
                frame = self._consume_browser_stream_frame()
                if frame is not None:
                    self._record_captured_frame(frame)
                    self._last_frame_shape = frame.shape
            self._refresh_runtime_snapshot_if_due(
                "standby_ready",
                task="Standby Browser Session Ready",
                progress="Waiting for a browser worker to claim this hidden prewarmed session.",
                capture=self._capture_summary(),
                fps=f"{self._fps_value():.1f}",
                uptime=self._uptime_label(),
                standby_slot=True,
            )
        return False

    def _resolve_browser_result(self, result):
        if inspect.isawaitable(result):
            if self._browser_async_loop is None:
                raise RuntimeError("Async Playwright loop is not initialized.")
            return self._browser_async_loop.run_until_complete(result)
        return result

    def update_resource_limits(
        self,
        memory_limit_gb: float | None = None,
        cpu_limit_percent: float | None = None,
        target_fps: float | None = None,
    ):
        with self.state_lock:
            if memory_limit_gb is not None:
                self.config.memory_limit_gb = max(0.5, float(memory_limit_gb))
            if cpu_limit_percent is not None:
                self.config.cpu_limit_percent = self._normalize_cpu_limit(cpu_limit_percent)
            if target_fps is not None:
                self.config.target_fps = self._normalize_target_fps(target_fps)
            self._snapshot["cpu"] = self._cpu_usage_label()
            self._snapshot["cpu_detail"] = self._cpu_detail_label()
            self._snapshot["cpu_limit_percent"] = self._cpu_limit_percent()
            self._snapshot["gpu"] = self._gpu_usage_label()
            self._snapshot["gpu_detail"] = self._gpu_detail_label()
            self._snapshot["mem"] = self._memory_usage_label()
            self._snapshot["memory_limit_gb"] = max(0.5, float(self.config.memory_limit_gb))

    def persist_now(self):
        if self._standby_pool_slot and not self._standby_claimed_by:
            return
        if self.learning_memory is not None:
            self.learning_memory.save(force=True)
        if self.dom_live_store is not None:
            self.dom_live_store.save()
        self._persist_session_state(force=True)

    def _clear_manual_command_queue(self):
        while True:
            try:
                self._manual_command_queue.get_nowait()
            except Empty:
                break

    def set_manual_control_active(self, active: bool):
        self._manual_control_active = bool(active)
        self._pending_task_context = None
        if not self._manual_control_active:
            self._clear_manual_command_queue()
        self._update_snapshot(manual_control=self._manual_control_active)

    def manual_control_active(self) -> bool:
        return bool(self._manual_control_active)

    def enqueue_manual_click(self, x: int, y: int, button: str = "left") -> bool:
        if self.config.mode.lower() != "browser":
            return False
        self._manual_command_queue.put(
            {
                "type": "click",
                "x": int(x),
                "y": int(y),
                "button": str(button or "left").strip().lower() or "left",
            }
        )
        return True

    def enqueue_manual_key(self, key: str) -> bool:
        if self.config.mode.lower() != "browser":
            return False
        key_text = str(key or "").strip()
        if not key_text:
            return False
        self._manual_command_queue.put({"type": "key", "key": key_text})
        return True

    def snapshot(self) -> dict:
        with self.state_lock:
            snapshot = dict(self._snapshot)
        snapshot["alive"] = self.is_alive()
        return snapshot

    def preview_payload(self, last_captured_at=None, tier: str = "preview") -> dict:
        tier_key = self._normalized_preview_tier(tier)
        source_frame = None
        source_token = None
        frame = None
        captured_at = None
        source_size = None
        logical_size = None
        now = time.time()
        with self.state_lock:
            snapshot = dict(self._snapshot)
            fps_value = self._fps_value_locked()
            source_token = self._latest_frame_at
            source_size = self._source_frame_size_locked()
            logical_size = self._logical_frame_size_locked(source_size)
            if self._preview_suppressed_locked(snapshot):
                snapshot["alive"] = self.is_alive()
                return {
                    "frame": None,
                    "snapshot": snapshot,
                    "captured_at": None,
                    "fps": fps_value,
                    "source_size": source_size,
                    "logical_size": logical_size,
                    "preview_tier": tier_key,
                }
            cache_entry = self._preview_tier_cache.setdefault(
                tier_key,
                {"frame": None, "token": None, "source_token": None, "emitted_at": 0.0},
            )
            interval_s = self._preview_tier_interval(tier_key)
            build_needed = (
                source_token is not None
                and self._latest_frame is not None
                and (
                    cache_entry.get("frame") is None
                    or cache_entry.get("token") is None
                    or cache_entry.get("source_token") != source_token
                )
                and (
                    cache_entry.get("token") is None
                    or (now - float(cache_entry.get("emitted_at") or 0.0)) >= interval_s
                )
            )
            if build_needed:
                source_frame = self._latest_frame.copy()
            cached_token = cache_entry.get("token")
            if source_frame is None and cached_token is not None and cached_token != last_captured_at:
                cached_frame = cache_entry.get("frame")
                if cached_frame is not None:
                    frame = cached_frame.copy()
                    captured_at = cached_token
        if source_frame is not None and source_token is not None:
            preview_frame = self._build_preview_frame(source_frame, tier_key)
            emitted_at = time.time()
            with self.state_lock:
                snapshot = dict(self._snapshot)
                fps_value = self._fps_value_locked()
                latest_source_token = self._latest_frame_at
                source_size = self._source_frame_size_locked()
                logical_size = self._logical_frame_size_locked(source_size)
                cache_entry = self._preview_tier_cache.setdefault(
                    tier_key,
                    {"frame": None, "token": None, "source_token": None, "emitted_at": 0.0},
                )
                if latest_source_token == source_token:
                    cache_entry["frame"] = preview_frame
                    cache_entry["token"] = source_token
                    cache_entry["source_token"] = source_token
                    cache_entry["emitted_at"] = emitted_at
                captured_at = cache_entry.get("token")
                if captured_at is not None and captured_at != last_captured_at:
                    cached_frame = cache_entry.get("frame")
                    if cached_frame is not None:
                        frame = cached_frame.copy()
        snapshot["alive"] = self.is_alive()
        return {
            "frame": frame,
            "snapshot": snapshot,
            "captured_at": captured_at,
            "fps": fps_value,
            "source_size": source_size,
            "logical_size": logical_size,
            "preview_tier": tier_key,
        }

    def latest_dom_snapshot(self) -> dict:
        with self.state_lock:
            return dict(self._latest_dom_snapshot or {})

    def capture_dom_snapshot(self) -> dict:
        if self.config.mode.lower() != "browser" or self._page is None:
            return {}
        if self._dom_analyzer is None:
            from automation.dom_analysis import DomAnalyzer

            self._dom_analyzer = DomAnalyzer(self.project_root)
        frame = None
        with self.state_lock:
            if self._latest_frame is not None:
                frame = self._latest_frame.copy()
        try:
            from automation.dom_analysis import frame_hash

            snapshot = self._dom_analyzer.capture_snapshot(
                self._page,
                resolve_result=self._resolve_browser_result,
                screenshot_hash=frame_hash(frame),
            )
        except Exception as exc:
            if self.log_callback is not None:
                self.log_callback(f"{self.config.worker_id}: DOM snapshot capture failed: {exc}")
            return self.latest_dom_snapshot()
        with self.state_lock:
            self._latest_dom_snapshot = dict(snapshot or {})
        return dict(snapshot or {})

    def _dom_drive_mode(self) -> str:
        mode = str(getattr(self.config, "browser_dom_drive_mode", "legacy") or "legacy").strip().lower()
        if mode not in {"legacy", "assist", "dom_live_experimental"}:
            mode = "legacy"
        if self.config.mode.lower() != "browser":
            return "legacy"
        return mode

    def update_preview_settings(
        self,
        browser_prewarm_enabled: bool | None = None,
        preview_target_fps: int | None = None,
        control_preview_target_fps: int | None = None,
    ):
        with self.state_lock:
            if browser_prewarm_enabled is not None:
                self.config.browser_prewarm_enabled = bool(browser_prewarm_enabled)
            if preview_target_fps is not None:
                self.config.preview_target_fps = max(1, min(30, int(preview_target_fps)))
            if control_preview_target_fps is not None:
                self.config.control_preview_target_fps = max(1, min(30, int(control_preview_target_fps)))
            for cache_entry in self._preview_tier_cache.values():
                cache_entry["emitted_at"] = 0.0

    def _normalized_preview_tier(self, tier: str) -> str:
        tier_key = str(tier or "preview").strip().lower()
        return "control" if tier_key == "control" else "preview"

    def _preview_tier_target_fps(self, tier: str) -> int:
        tier_key = self._normalized_preview_tier(tier)
        if tier_key == "control":
            return max(1, min(30, int(getattr(self.config, "control_preview_target_fps", 15) or 15)))
        return max(1, min(30, int(getattr(self.config, "preview_target_fps", 10) or 10)))

    def _preview_tier_interval(self, tier: str) -> float:
        return 1.0 / max(1.0, float(self._preview_tier_target_fps(tier)))

    def _preview_tier_max_edge(self, tier: str) -> int:
        return 720 if self._normalized_preview_tier(tier) == "control" else 540

    def _preview_suppressed_locked(self, snapshot: dict | None = None) -> bool:
        if self.config.mode.lower() != "browser":
            return False
        status_text = str((snapshot or self._snapshot).get("status", "") or "").strip().lower()
        return status_text in {"prewarming", "loading_game", "warming_capture", "standby_prewarming", "standby_ready", "standby_claimed"}

    def _source_frame_size_locked(self):
        if self._latest_frame is not None:
            height, width = self._latest_frame.shape[:2]
            return {"width": int(width), "height": int(height)}
        if self._last_frame_shape is not None:
            height, width = self._last_frame_shape[:2]
            return {"width": int(width), "height": int(height)}
        return None

    def _logical_frame_size_locked(self, source_size=None):
        if self.config.mode.lower() == "browser" and self._browser_capture_bounds is not None:
            return {
                "width": int(max(1, self._browser_capture_bounds.get("width", 1) or 1)),
                "height": int(max(1, self._browser_capture_bounds.get("height", 1) or 1)),
            }
        if isinstance(source_size, dict):
            return {
                "width": int(max(1, source_size.get("width", 1) or 1)),
                "height": int(max(1, source_size.get("height", 1) or 1)),
            }
        return None

    def _build_preview_frame(self, frame, tier: str):
        if frame is None:
            return None
        max_edge = self._preview_tier_max_edge(tier)
        height, width = frame.shape[:2]
        longest_edge = max(height, width)
        if longest_edge <= max_edge:
            return frame.copy()
        scale = float(max_edge) / float(max(1, longest_edge))
        resized = cv2.resize(
            frame,
            (max(1, int(width * scale)), max(1, int(height * scale))),
            interpolation=cv2.INTER_AREA,
        )
        return resized

    def _dom_drive_enabled(self) -> bool:
        return self.config.mode.lower() == "browser" and self._dom_drive_mode() != "legacy"

    def _screen_state_analysis(self, visible_text: str = "", dom_snapshot: dict | None = None) -> dict:
        from automation.guide_coach import SCREEN_STATE_DEFINITIONS

        combined_text = " | ".join(
            [
                str(visible_text or "").strip().lower(),
                str((dom_snapshot or {}).get("raw_text_summary") or "").strip().lower(),
            ]
        ).strip()
        matched_keywords = []
        state_scores = {}
        for state_key, definition in SCREEN_STATE_DEFINITIONS.items():
            score = 0.0
            state_matches = []
            for keyword in list(definition.get("keywords", []) or []):
                token = str(keyword or "").strip().lower()
                if token and token in combined_text:
                    score += 1.0 + (0.25 if len(token) > 6 else 0.0)
                    state_matches.append(token)
            if score > 0.0:
                state_scores[state_key] = score
                matched_keywords.extend(state_matches)
        if state_scores:
            state_key = max(state_scores, key=state_scores.get)
            confidence = round(min(0.98, max(0.15, float(state_scores[state_key]) / 4.5)), 2)
        else:
            state_key = "unknown"
            confidence = 0.05
        return {
            "screen_state": state_key,
            "screen_label": str(state_key or "unknown").replace("_", " ").title(),
            "confidence": confidence,
            "matched_keywords": list(dict.fromkeys(matched_keywords))[:12],
        }

    def _dom_live_summary_for_state(self, screen_state: str) -> dict:
        state_key = str(screen_state or "unknown").strip().lower() or "unknown"
        cached = self._dom_live_evidence_summary.get(state_key)
        if cached is not None:
            return dict(cached)
        summary = self.evidence_store.aggregate(
            game=self._game_label(),
            profile=self.game_profile.name,
            screen_state=state_key,
            runtime="browser",
        )
        store_summary = self.dom_live_store.summary_for_state(state_key)
        summary["dom_live_store"] = store_summary
        self._dom_live_evidence_summary[state_key] = dict(summary)
        return dict(summary)

    def _dom_candidate_capture_center(self, candidate: dict | None) -> tuple[int, int] | None:
        candidate = dict(candidate or {})
        center = list(candidate.get("center") or [])
        bounds = dict(self._browser_capture_bounds or {})
        if len(center) < 2:
            bounds_data = dict(candidate.get("bounds") or {})
            if bounds_data:
                center = [
                    int(bounds_data.get("x", 0) or 0) + int(bounds_data.get("width", 0) or 0) // 2,
                    int(bounds_data.get("y", 0) or 0) + int(bounds_data.get("height", 0) or 0) // 2,
                ]
        if len(center) < 2:
            return None
        page_x = int(center[0])
        page_y = int(center[1])
        offset_x = int(bounds.get("x", 0) or 0)
        offset_y = int(bounds.get("y", 0) or 0)
        scale_x, scale_y = getattr(self.input_manager, "browser_capture_scale", (1.0, 1.0))
        capture_x = int(round((page_x - offset_x) * max(0.10, float(scale_x))))
        capture_y = int(round((page_y - offset_y) * max(0.10, float(scale_y))))
        if capture_x < 0 or capture_y < 0:
            return None
        return capture_x, capture_y

    def _dom_candidate_signature(self, candidate: dict | None) -> str:
        candidate = dict(candidate or {})
        label = str(candidate.get("label") or "").strip().lower()
        keyword = str(candidate.get("keyword") or "").strip().lower()
        selector_hint = str(candidate.get("selector_hint") or "").strip().lower()
        token = str(candidate.get("token") or "").strip().lower()
        if token:
            return token
        return f"{selector_hint}|{label}|{keyword}"

    def _dom_candidate_on_cooldown(self, candidate: dict | None) -> bool:
        token = self._dom_candidate_signature(candidate)
        if not token:
            return False
        entry = dict(self._dom_live_candidate_attempts.get(token) or {})
        last_attempt_at = float(entry.get("last_attempt_at", 0.0) or 0.0)
        repeats = int(entry.get("repeats", 0) or 0)
        if last_attempt_at <= 0.0:
            return False
        cooldown = max(0.10, int(getattr(self.config, "dom_live_cooldown_ms", 850) or 850) / 1000.0)
        cooldown *= 1.0 + min(3.0, repeats * 0.35)
        return (time.time() - last_attempt_at) < cooldown

    def _note_dom_candidate_attempt(self, candidate: dict | None, success: bool | None = None):
        token = self._dom_candidate_signature(candidate)
        if not token:
            return
        entry = dict(self._dom_live_candidate_attempts.get(token) or {})
        previous_repeats = int(entry.get("repeats", 0) or 0)
        if success is True:
            repeats = 0
        elif success is False:
            repeats = min(max(1, int(getattr(self.config, "dom_live_max_repeat_attempts", 3) or 3)) + 2, previous_repeats + 1)
        else:
            repeats = previous_repeats
        self._dom_live_candidate_attempts[token] = {
            "last_attempt_at": time.time(),
            "repeats": repeats,
            "last_success": bool(success) if success is not None else entry.get("last_success"),
        }

    def _dom_live_action_candidates(self, guide_analysis: dict | None = None) -> list[dict]:
        if self.config.mode.lower() != "browser" or self._page is None:
            return []
        snapshot = self.capture_dom_snapshot()
        visible_text = self._combined_visible_state_text()
        guide_analysis = dict(guide_analysis or self._screen_state_analysis(visible_text, snapshot))
        screen_state = str(guide_analysis.get("screen_state") or "unknown").strip().lower() or "unknown"
        self._dom_live_screen_state = screen_state
        evidence_summary = self._dom_live_summary_for_state(screen_state)
        action_map = self._dom_analyzer.build_screen_action_map(
            snapshot,
            ocr_boxes=[],
            screen_state=screen_state,
            guide_analysis=guide_analysis,
            evidence_summary=evidence_summary,
        )
        preferred_rows = list((evidence_summary.get("preferred_targets_by_state") or {}).get(screen_state, []) or [])
        avoid_rows = list(evidence_summary.get("avoid_patterns", []) or [])
        store_rows = list(((evidence_summary.get("dom_live_store") or {}).get("preferred_actions") or []) or [])
        dom_weight = max(0.0, min(3.5, float(getattr(self.config, "dom_evidence_weight", 1.3) or 1.3)))
        ranked = []
        for entry in list(action_map.get("merged_actions", []) or [])[:18]:
            candidate = dict(entry)
            keyword = str(candidate.get("keyword") or "").strip().lower()
            label = str(candidate.get("label") or "").strip().lower()
            reason_parts = [str(candidate.get("reason") or candidate.get("source") or "dom")]
            adjustment = 0.0
            for row in preferred_rows:
                row_keyword = str(row.get("keyword") or "").strip().lower()
                row_label = str(row.get("label") or "").strip().lower()
                if row_keyword and row_keyword in label:
                    adjustment += min(2.4, float(row.get("count", 0) or 0) * 0.22 * dom_weight)
                    reason_parts.append(f"evidence+{row_keyword}")
                    break
                if row_label and row_label in label:
                    adjustment += min(1.8, float(row.get("count", 0) or 0) * 0.18 * dom_weight)
                    reason_parts.append("evidence+label")
                    break
            for row in avoid_rows:
                row_keyword = str(row.get("keyword") or "").strip().lower()
                row_kind = str(row.get("kind") or "").strip().lower()
                if row_keyword and row_keyword in label:
                    adjustment -= min(2.6, float(row.get("count", 0) or 0) * 0.28 * dom_weight)
                    reason_parts.append(f"avoid-{row_keyword}")
                    break
                if row_kind and row_kind == str(candidate.get("source") or "").strip().lower():
                    adjustment -= min(1.4, float(row.get("count", 0) or 0) * 0.12 * dom_weight)
            for row in store_rows:
                row_token = str(row.get("token") or "").strip()
                row_keyword = str(row.get("keyword") or "").strip().lower()
                if row_token and row_token == self._dom_candidate_signature(candidate):
                    adjustment += min(2.8, float(row.get("successes", 0) or 0) * 0.20)
                    reason_parts.append("worker-memory")
                    break
                if row_keyword and row_keyword and row_keyword in label:
                    adjustment += min(1.4, float(row.get("successes", 0) or 0) * 0.12)
                    reason_parts.append("worker-memory-keyword")
                    break
            adjustment += self.dom_live_store.score_adjustment(screen_state, candidate)
            candidate["score"] = round(float(candidate.get("score", 0.0) or 0.0) + adjustment, 3)
            candidate["runtime_reason"] = " | ".join(reason_parts)
            candidate["screen_state"] = screen_state
            capture_center = self._dom_candidate_capture_center(candidate)
            if capture_center is None:
                continue
            candidate["capture_center"] = [int(capture_center[0]), int(capture_center[1])]
            ranked.append(candidate)
        ranked.sort(key=lambda item: (-float(item.get("score", 0.0) or 0.0), str(item.get("label") or "").lower()))
        self._dom_live_last_summary = [
            f"{str(item.get('label') or 'action')[:28]} [{str(item.get('source') or '').upper()}] {float(item.get('score', 0.0) or 0.0):.2f}"
            for item in ranked[:4]
        ]
        return ranked

    def _confirm_dom_live_action(self, candidate: dict, before_text: str, before_screen_state: str) -> tuple[bool, str, dict]:
        wait_seconds = 0.18 if not bool(getattr(self.config, "dom_confirmation_required", True)) else 0.24
        time.sleep(wait_seconds)
        post_snapshot = self.capture_dom_snapshot()
        post_text = self._combined_visible_state_text()
        post_analysis = self._screen_state_analysis(post_text, post_snapshot)
        post_state = str(post_analysis.get("screen_state") or "unknown").strip().lower() or "unknown"
        before_blob = str(before_text or "").strip().lower()
        after_blob = str(post_text or "").strip().lower()
        before_count = int((self._latest_dom_snapshot or {}).get("actionable_count", 0) or 0)
        after_count = int(post_snapshot.get("actionable_count", 0) or 0)
        text_changed = bool(before_blob and after_blob and before_blob != after_blob)
        screen_changed = before_screen_state and post_state and before_screen_state != post_state
        keyword = str(candidate.get("keyword") or "").strip().lower()
        label = str(candidate.get("label") or "").strip().lower()
        candidate_disappeared = bool(
            keyword and keyword not in after_blob and keyword in before_blob
        ) or bool(
            label and label not in after_blob and label in before_blob
        )
        dom_changed = abs(after_count - before_count) >= 1
        if screen_changed:
            return True, f"screen_state_changed:{before_screen_state}->{post_state}", post_snapshot
        if text_changed and candidate_disappeared:
            return True, "text_changed_and_target_cleared", post_snapshot
        if text_changed and dom_changed:
            return True, "dom_and_text_changed", post_snapshot
        if not bool(getattr(self.config, "dom_confirmation_required", True)):
            return True, "confirmation_relaxed", post_snapshot
        return False, "no_visible_transition", post_snapshot

    def _record_dom_live_evidence(self, candidate: dict, screen_state: str, outcome: str, confirmation_reason: str):
        visible_text = self._combined_visible_state_text()
        snapshot = self.latest_dom_snapshot()
        confirmed_outcome = "advanced" if outcome == "success" else "wrong_target" if outcome == "failure" else "neutral"
        self.evidence_store.record(
            {
                "game": self._game_label(),
                "profile": self.game_profile.name,
                "screen_state": screen_state,
                "task_key": str(candidate.get("task_key") or "dom_live").strip().lower() or "dom_live",
                "runtime": "browser",
                "worker_id": self.config.worker_id,
                "source": "dom_live",
                "dom_snapshot_summary": {
                    "url": snapshot.get("url", ""),
                    "title": snapshot.get("title", ""),
                    "viewport": snapshot.get("viewport", {}),
                    "raw_text_summary": snapshot.get("raw_text_summary", ""),
                    "actionable_count": snapshot.get("actionable_count", 0),
                    "top_actionables": list(snapshot.get("actionables", [])[:8]),
                    "screenshot_hash": snapshot.get("screenshot_hash", ""),
                },
                "ocr_excerpt": visible_text[:1500],
                "chosen_candidate": candidate,
                "intended_action": {
                    "label": candidate.get("label", ""),
                    "target_type": candidate.get("source", "dom"),
                    "keyword": candidate.get("keyword", ""),
                    "point": list(candidate.get("capture_center") or []),
                },
                "confirmed_outcome": confirmed_outcome,
                "visible_transition": outcome == "success",
                "frame_hash": snapshot.get("screenshot_hash", ""),
                "screenshot_hash": snapshot.get("screenshot_hash", ""),
                "note": confirmation_reason,
            }
        )
        self._dom_live_evidence_summary.pop(screen_state, None)

    def _execute_dom_live_policy(self, game_state: dict | None) -> str | None:
        if not self._dom_drive_enabled():
            return None
        candidates = self._dom_live_action_candidates()
        if not candidates:
            self._dom_live_last_fallback_reason = "No DOM candidates were available"
            return None
        top_candidates = []
        for row in candidates[:6]:
            top_candidates.append(
                {
                    "label": row.get("label", ""),
                    "source": row.get("source", ""),
                    "score": round(float(row.get("score", 0.0) or 0.0), 3),
                    "keyword": row.get("keyword", ""),
                    "reason": row.get("runtime_reason", ""),
                }
            )
        self._update_snapshot(dom_top_candidates=top_candidates)
        max_repeat_attempts = max(1, int(getattr(self.config, "dom_live_max_repeat_attempts", 3) or 3))
        before_text = self._combined_visible_state_text()
        before_state = self._screen_state_analysis(before_text, self.latest_dom_snapshot())
        screen_state = str(before_state.get("screen_state") or "unknown").strip().lower() or "unknown"
        for candidate in candidates:
            token = self._dom_candidate_signature(candidate)
            repeats = int((self._dom_live_candidate_attempts.get(token) or {}).get("repeats", 0) or 0)
            if repeats >= max_repeat_attempts or self._dom_candidate_on_cooldown(candidate):
                continue
            capture_center = list(candidate.get("capture_center") or [])
            if len(capture_center) < 2:
                continue
            self.input_manager.click(int(capture_center[0]), int(capture_center[1]))
            self._remember_action_key(f"dom:{token}")
            self._profile_action_label = f"DOM Live -> {candidate.get('label', 'action')}"
            self._dom_live_last_action = self._profile_action_label
            confirmed, reason, _post_snapshot = self._confirm_dom_live_action(candidate, before_text, screen_state)
            if confirmed:
                self._note_dom_candidate_attempt(candidate, success=True)
                self.dom_live_store.record(screen_state, candidate, "success", reason, task_key="dom_live")
                self.dom_live_store.save()
                self._record_dom_live_evidence(candidate, screen_state, "success", reason)
                self._dom_live_last_confirmation = f"confirmed:{reason}"
                self._dom_live_last_fallback_reason = ""
                candidate["task_key"] = "dom_live"
                self._mark_task_attempt("dom_live", self._profile_action_label, game_state)
                self._update_snapshot(
                    dom_last_action=self._dom_live_last_action,
                    dom_last_confirmation=self._dom_live_last_confirmation,
                    dom_fallback_reason=self._dom_live_last_fallback_reason,
                    dom_drive_enabled=True,
                    dom_drive_mode=self._dom_drive_mode(),
                )
                return self._profile_action_label
            self._note_dom_candidate_attempt(candidate, success=False)
            self.dom_live_store.record(screen_state, candidate, "failure", reason, task_key="dom_live")
            self.dom_live_store.save()
            self._record_dom_live_evidence(candidate, screen_state, "failure", reason)
            self._dom_live_last_confirmation = f"miss:{reason}"
        self._dom_live_last_fallback_reason = "DOM candidates did not confirm, falling back to profile logic"
        self._update_snapshot(
            dom_last_action=self._dom_live_last_action,
            dom_last_confirmation=self._dom_live_last_confirmation,
            dom_fallback_reason=self._dom_live_last_fallback_reason,
            dom_drive_enabled=True,
            dom_drive_mode=self._dom_drive_mode(),
        )
        return None

    def _browser_page_coordinates(self, x: int, y: int) -> tuple[int, int]:
        offset_x, offset_y = getattr(self.input_manager, "browser_offset", (0, 0))
        scale_x, scale_y = getattr(self.input_manager, "browser_capture_scale", (1.0, 1.0))
        page_x = int(round((int(x) / max(0.10, float(scale_x))) + offset_x))
        page_y = int(round((int(y) / max(0.10, float(scale_y))) + offset_y))
        return page_x, page_y

    def _process_manual_commands(self, max_commands: int = 6) -> int:
        if self.config.mode.lower() != "browser" or self._page is None:
            self._clear_manual_command_queue()
            return 0
        processed = 0
        while processed < max(1, int(max_commands)):
            try:
                command = self._manual_command_queue.get_nowait()
            except Empty:
                break
            command_type = str((command or {}).get("type") or "").strip().lower()
            if command_type == "click":
                page_x, page_y = self._browser_page_coordinates(command.get("x", 0), command.get("y", 0))
                button = str(command.get("button") or "left").strip().lower() or "left"
                try:
                    self._resolve_browser_result(self._page.mouse.click(page_x, page_y, button=button, delay=0))
                    self.input_manager.last_action = f"manual:{button}_click({page_x},{page_y})"
                    self._profile_action_label = f"Manual {button.title()} Click"
                except Exception:
                    pass
            elif command_type == "key":
                key_text = str(command.get("key") or "").strip()
                if key_text:
                    try:
                        self._resolve_browser_result(self._page.keyboard.press(_normalized_browser_key(key_text)))
                        self.input_manager.last_action = f"manual:key:{key_text}"
                        self._profile_action_label = f"Manual Key {key_text}"
                    except Exception:
                        pass
            processed += 1
        return processed

    def run(self):
        self._started_at = time.time()
        try:
            if self.config.mode.lower() == "browser":
                self._update_snapshot(
                    status="standby_prewarming" if self._standby_pool_slot else "prewarming",
                    task="Warming Hidden Browser Session" if self._standby_pool_slot else "Launching Headless Chromium",
                    progress=f"Opening {_browser_host_label(self.config.browser_url)}",
                    capture=self._default_capture_summary(),
                    standby_slot=self._standby_pool_slot,
                )
                self._start_browser_session()
                if self._standby_pool_slot:
                    if not self._enter_standby_until_claimed():
                        return
            self._update_snapshot(
                status="running",
                task=self._task_label_for_profile("Profile Warmup"),
                capture=self._capture_summary(),
                game=self._game_label(),
                profile=self.game_profile.name,
                strategy=self._strategy_label(),
                ads=self._ad_policy_summary(),
                learning=self._learning_summary(),
                mode=self.config.mode.title(),
                model=self.config.model_name,
                standby_slot=False,
            )
            if self.log_callback is not None:
                self.log_callback(
                    f"{self.config.worker_id}: runtime started in {self.config.mode.title()} mode for {self._game_label()}."
                )
            while not self.stop_event.is_set():
                loop_started_at = time.perf_counter()
                frame = self._capture_frame()
                self._record_captured_frame(frame)
                self._last_frame_shape = frame.shape
                self._poll_gpu_usage()
                loading_marker = self._frame_loading_marker(frame)
                if loading_marker:
                    previous_loading_marker = str(self._last_loading_marker or "")
                    self._last_loading_marker = loading_marker
                    work_elapsed = max(0.0, time.perf_counter() - loop_started_at)
                    sleep_time = self._apply_cpu_budget(work_elapsed, 1.0 / self._target_fps())
                    self._refresh_runtime_snapshot_if_due(
                        "loading_game",
                        force=loading_marker != previous_loading_marker,
                        task="Waiting For Game To Finish Loading",
                        progress=f"Detected loading screen: {loading_marker}",
                        capture=self._capture_summary(),
                        last_action="idle",
                        cpu=self._cpu_usage_label(),
                        cpu_detail=self._cpu_detail_label(),
                        cpu_limit_percent=self._cpu_limit_percent(),
                        gpu=self._gpu_usage_label(),
                        gpu_detail=self._gpu_detail_label(),
                        mem=self._memory_usage_label(),
                        memory_limit_gb=max(0.5, float(self.config.memory_limit_gb)),
                        uptime=self._uptime_label(),
                        fps=f"{self._fps_value():.1f}",
                    )
                    time.sleep(sleep_time)
                    continue
                game_state, reward = self._resolve_game_state(frame)
                reward_value = float(reward or 0.0) + self._profile_reward_bonus(game_state)
                self._total_reward += max(-1.5, min(2.5, reward_value))
                self._record_learning_outcome(game_state, reward_value)
                if self._manual_control_active:
                    processed_commands = self._process_manual_commands()
                    work_elapsed = max(0.0, time.perf_counter() - loop_started_at)
                    base_delay = self._loop_delay()
                    sleep_time = self._apply_cpu_budget(work_elapsed, base_delay)
                    self._refresh_runtime_snapshot_if_due(
                        "running",
                        force=processed_commands > 0,
                        task="Manual Control Active",
                        progress=f"Autoplay paused | Steps {self._steps} | Reward {self._total_reward:.2f} | {self._profile_action_label or 'Awaiting user input'}",
                        capture=self._capture_summary(),
                        last_action=self.input_manager.last_action,
                        profile=self.game_profile.name,
                        strategy=self._strategy_label(),
                        ads=self._ad_policy_summary(),
                        learning=self._learning_summary(),
                        cpu=self._cpu_usage_label(),
                        cpu_detail=self._cpu_detail_label(),
                        cpu_limit_percent=self._cpu_limit_percent(),
                        gpu=self._gpu_usage_label(),
                        gpu_detail=self._gpu_detail_label(),
                        mem=self._memory_usage_label(),
                        memory_limit_gb=max(0.5, float(self.config.memory_limit_gb)),
                        uptime=self._uptime_label(),
                        fps=f"{self._fps_value():.1f}",
                        manual_control=True,
                        dom_drive_enabled=self._dom_drive_enabled(),
                        dom_drive_mode=self._dom_drive_mode(),
                        dom_last_action=self._dom_live_last_action,
                        dom_last_confirmation=self._dom_live_last_confirmation,
                        dom_fallback_reason="Manual control override active",
                    )
                    time.sleep(sleep_time)
                    continue
                profile_action = None
                graph_action = None
                effective_action = self.input_manager.last_action
                if time.perf_counter() >= self._next_action_due_at:
                    if self._dom_drive_enabled():
                        profile_action = self._execute_dom_live_policy(game_state)
                    if profile_action is None:
                        profile_action = self._execute_profile_actions(game_state)
                    graph_action = self._execute_behavior_graph(game_state)
                    effective_action = profile_action or graph_action or self.input_manager.last_action
                    self._steps += 1
                    self._next_action_due_at = time.perf_counter() + self._action_interval_s()
                    self._persist_session_state()
                work_elapsed = max(0.0, time.perf_counter() - loop_started_at)
                base_delay = self._loop_delay()
                sleep_time = self._apply_cpu_budget(work_elapsed, base_delay)
                self._refresh_runtime_snapshot_if_due(
                    "running",
                    force=bool(profile_action or graph_action),
                    task=self._task_label_for_profile(profile_action or graph_action),
                    progress=f"Steps {self._steps} | Reward {self._total_reward:.2f} | {self._profile_action_label}",
                    capture=self._capture_summary(),
                    last_action=effective_action,
                    profile=self.game_profile.name,
                    strategy=self._strategy_label(),
                    ads=self._ad_policy_summary(),
                    learning=self._learning_summary(),
                    cpu=self._cpu_usage_label(),
                    cpu_detail=self._cpu_detail_label(),
                    cpu_limit_percent=self._cpu_limit_percent(),
                    gpu=self._gpu_usage_label(),
                    gpu_detail=self._gpu_detail_label(),
                    mem=self._memory_usage_label(),
                    memory_limit_gb=max(0.5, float(self.config.memory_limit_gb)),
                    uptime=self._uptime_label(),
                    fps=f"{self._fps_value():.1f}",
                    manual_control=False,
                    dom_drive_enabled=self._dom_drive_enabled(),
                    dom_drive_mode=self._dom_drive_mode(),
                    dom_last_action=self._dom_live_last_action,
                    dom_last_confirmation=self._dom_live_last_confirmation,
                    dom_fallback_reason=self._dom_live_last_fallback_reason,
                )
                time.sleep(sleep_time)
        except Exception as exc:
            self._last_error = str(exc)
            self._update_snapshot(
                status="error",
                task="Worker Runtime Error",
                last_error=self._last_error,
                progress=f"Failed after {self._steps} steps",
                uptime=self._uptime_label(),
            )
            if self.log_callback is not None:
                self.log_callback(f"{self.config.worker_id}: runtime error: {exc}")
                self.log_callback(traceback.format_exc().strip())
        finally:
            self._close_browser_session()
            if self._analysis_future is not None:
                try:
                    self._analysis_future.cancel()
                except Exception:
                    pass
            if self._analysis_executor is not None:
                try:
                    self._analysis_executor.shutdown(wait=False, cancel_futures=True)
                except Exception:
                    pass
            if self._gpu_future is not None:
                try:
                    self._gpu_future.cancel()
                except Exception:
                    pass
            if self._gpu_executor is not None:
                try:
                    self._gpu_executor.shutdown(wait=False, cancel_futures=True)
                except Exception:
                    pass
            if not (self._standby_pool_slot and not self._standby_claimed_by):
                if self.learning_memory is not None:
                    self.learning_memory.save(force=True)
                if self.dom_live_store is not None:
                    self.dom_live_store.save()
                self._persist_session_state(force=True)
            if self.snapshot().get("status") != "error":
                self._update_snapshot(
                    status="stopped",
                    task="Stopped",
                    progress=f"Completed {self._steps} steps",
                    uptime=self._uptime_label(),
                )
            if self.log_callback is not None:
                self.log_callback(f"{self.config.worker_id}: runtime stopped.")

    def _start_browser_session(self):
        if sync_playwright is None and async_playwright is None:
            raise RuntimeError("Playwright is not available for browser workers.")
        launch_entries = self._browser_launch_entries()
        preferred_launch_label = str((launch_entries[0].get("label") if launch_entries else "Chromium") or "Chromium")
        local_fallback_label = self._preferred_local_browser_label() if self._has_local_browser_target() else ""
        if preferred_launch_label == "Chromium":
            browser_status = ensure_playwright_chromium(install_if_missing=True)
            if self.log_callback is not None:
                if browser_status.get("attempted_install"):
                    self.log_callback(f"{self.config.worker_id}: {browser_status['message']}")
                elif local_fallback_label:
                    self.log_callback(
                        f"{self.config.worker_id}: Chromium preferred; local fallback available: {local_fallback_label}."
                    )
        elif self._has_local_browser_target():
            browser_status = {
                "available": True,
                "message": f"Using local browser target: {local_fallback_label or preferred_launch_label}",
                "attempted_install": False,
            }
            if self.log_callback is not None:
                self.log_callback(f"{self.config.worker_id}: {browser_status['message']}")
        else:
            browser_status = ensure_playwright_chromium(install_if_missing=True)
            if self.log_callback is not None and browser_status.get("attempted_install"):
                self.log_callback(f"{self.config.worker_id}: {browser_status['message']}")
        target_url = _normalized_browser_url(self.config.browser_url)
        self.config.browser_url = target_url
        known_browser_pids = self._browser_child_pids()
        viewport = {
            "width": max(320, int(self.config.capture_region.get("width", 1280))),
            "height": max(240, int(self.config.capture_region.get("height", 720))),
        }
        last_error = None
        sync_allowed = sync_playwright is not None
        startup_succeeded = False
        launch_modes = [bool(self._gpu_requested_enabled())]
        if launch_modes[0]:
            launch_modes.append(False)
        for use_gpu in launch_modes:
            launch_label = "hardware-accelerated" if use_gpu else "legacy"
            if use_gpu and self.log_callback is not None:
                self.log_callback(
                    f"{self.config.worker_id}: trying Chromium hardware acceleration for faster browser workers."
                )
            if sync_allowed:
                attempts = 2
                for attempt in range(1, attempts + 1):
                    try:
                        self._open_sync_browser_context(viewport, use_gpu)
                        last_error = None
                        startup_succeeded = True
                        break
                    except Exception as exc:
                        last_error = exc
                        self._close_browser_session()
                        if self.log_callback is not None:
                            self.log_callback(
                                f"{self.config.worker_id}: Playwright sync startup attempt {attempt}/{attempts} "
                                f"failed in {launch_label} mode: {exc}"
                            )
                        if attempt < attempts:
                            time.sleep(0.75)
            if startup_succeeded:
                break
            if async_playwright is not None:
                if self.log_callback is not None:
                    self.log_callback(
                        f"{self.config.worker_id}: falling back to async Playwright worker bootstrap "
                        f"in {launch_label} mode."
                    )
                for attempt in range(1, 3):
                    try:
                        self._open_async_browser_context(viewport, use_gpu)
                        last_error = None
                        startup_succeeded = True
                        break
                    except Exception as async_exc:
                        last_error = async_exc
                        self._close_browser_session()
                        if self.log_callback is not None:
                            self.log_callback(
                                f"{self.config.worker_id}: Playwright async startup attempt {attempt}/2 failed "
                                f"in {launch_label} mode: {async_exc}"
                            )
                        if attempt < 2:
                            time.sleep(0.75)
            if startup_succeeded:
                break
            if use_gpu and self.log_callback is not None:
                self.log_callback(
                    f"{self.config.worker_id}: hardware acceleration was unstable, retrying browser launch in legacy mode."
                )
        if not startup_succeeded and last_error is not None:
            raise RuntimeError(f"Playwright worker startup failed after retries: {last_error}") from last_error
        self._bind_browser_network_observers()
        self.input_manager.bind_browser_page(self._page, offset=(0, 0), runner=self._resolve_browser_result)
        self._capture_browser_process_ids(known_browser_pids)
        self._detect_browser_gpu_details()
        if self.log_callback is not None:
            self.log_callback(
                f"{self.config.worker_id}: headless {self._browser_engine_label} launched for {target_url}."
            )
        self._update_snapshot(
            status="loading_game",
            task="Loading Browser Game",
            progress=f"Navigating to {_browser_host_label(target_url)}",
            capture=self._default_capture_summary(),
        )
        self._resolve_browser_result(self._page.goto(target_url, wait_until="domcontentloaded", timeout=45000))
        self._wait_for_game_ready(timeout_s=70.0)
        self._update_snapshot(
            status="warming_capture",
            task="Fitting Game Surface",
            progress="Sizing the browser session to the live game surface",
            capture=self._default_capture_summary(),
        )
        self._fit_browser_to_game_surface()
        self._update_snapshot(
            status="warming_capture",
            task="Warming Capture Stream",
            progress="Priming the first streamed game frame before autoplay starts",
            capture=self._capture_summary(),
        )
        self._start_browser_streaming_capture()
        if bool(getattr(self.config, "browser_prewarm_enabled", True)):
            self._warm_browser_capture()
        self._capture_browser_process_ids(known_browser_pids)
        self._update_snapshot(gpu=self._gpu_usage_label(), gpu_detail=self._gpu_detail_label())
        if self.log_callback is not None:
            self.log_callback(
                f"{self.config.worker_id}: game page loaded in {self._browser_engine_label} for {_browser_host_label(target_url)}."
            )

    def _open_sync_browser_context(self, viewport: dict, use_gpu: bool):
        self._playwright_async_mode = False
        self._effective_gpu_enabled = bool(use_gpu)
        self._playwright_manager = sync_playwright()
        started_playwright = self._playwright_manager.start()
        self._playwright = started_playwright if hasattr(started_playwright, "chromium") else None
        if self._playwright is None:
            raise RuntimeError("Playwright runtime failed to initialize Chromium access.")
        self._browser = self._launch_browser(gpu_enabled=bool(use_gpu))
        self._browser_context = self._browser.new_context(
            viewport=viewport,
            ignore_https_errors=True,
            device_scale_factor=1,
            service_workers="block",
        )
        self._browser_viewport_size = dict(viewport or {})
        self._page = self._browser_context.new_page()
        self._open_browser_cdp_session()
        self._configure_browser_page_runtime()

    def _open_async_browser_context(self, viewport: dict, use_gpu: bool):
        self._playwright_async_mode = True
        self._effective_gpu_enabled = bool(use_gpu)
        self._browser_async_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._browser_async_loop)
        self._playwright = self._browser_async_loop.run_until_complete(async_playwright().start())
        self._browser = self._launch_browser(gpu_enabled=bool(use_gpu))
        self._browser_context = self._resolve_browser_result(
            self._browser.new_context(
                viewport=viewport,
                ignore_https_errors=True,
                device_scale_factor=1,
                service_workers="block",
            )
        )
        self._browser_viewport_size = dict(viewport or {})
        self._page = self._resolve_browser_result(self._browser_context.new_page())
        self._open_browser_cdp_session()
        self._configure_browser_page_runtime()

    def _open_browser_cdp_session(self):
        if self._browser_context is None or self._page is None:
            self._browser_cdp_session = None
            self._browser_stream_handler_registered = False
            return
        try:
            self._browser_cdp_session = self._resolve_browser_result(self._browser_context.new_cdp_session(self._page))
            self._browser_stream_handler_registered = False
        except Exception:
            self._browser_cdp_session = None
            self._browser_stream_handler_registered = False

    def _stop_browser_streaming_capture(self):
        if self._browser_cdp_session is not None and self._browser_stream_active:
            try:
                self._resolve_browser_result(self._browser_cdp_session.send("Page.stopScreencast"))
            except Exception:
                pass
        self._browser_stream_active = False
        with self._browser_stream_lock:
            self._browser_stream_payload = None
            self._browser_stream_payload_at = 0.0
            self._browser_stream_latest_frame = None
            self._browser_stream_latest_frame_at = 0.0
            self._browser_stream_last_consumed_at = 0.0
            self._browser_stream_last_signature = None
            self._browser_stream_last_reused_at = 0.0

    def _start_browser_streaming_capture(self):
        if not self._browser_streaming_enabled or self._browser_cdp_session is None:
            return
        self._stop_browser_streaming_capture()
        max_width = None
        max_height = None
        if self._browser_capture_bounds is not None:
            max_width = max(160, int(self._browser_capture_bounds.get("width", 320) * self._browser_capture_scale))
            max_height = max(160, int(self._browser_capture_bounds.get("height", 240) * self._browser_capture_scale))
        elif self._browser_viewport_size:
            max_width = max(160, int(self._browser_viewport_size.get("width", 320) * self._browser_capture_scale))
            max_height = max(160, int(self._browser_viewport_size.get("height", 240) * self._browser_capture_scale))
        if not self._browser_stream_handler_registered:
            try:
                self._browser_cdp_session.on("Page.screencastFrame", self._handle_browser_screencast_frame)
                self._browser_stream_handler_registered = True
            except Exception:
                self._browser_stream_handler_registered = False
        screencast_payload = {
            "format": "jpeg",
            "quality": self._browser_capture_jpeg_quality(),
            "everyNthFrame": 1,
        }
        if max_width is not None and max_height is not None:
            screencast_payload["maxWidth"] = int(max_width)
            screencast_payload["maxHeight"] = int(max_height)
        try:
            self._resolve_browser_result(self._browser_cdp_session.send("Page.startScreencast", screencast_payload))
            self._browser_stream_active = True
            self._browser_stream_failures = 0
        except Exception:
            self._browser_stream_active = False

    def _handle_browser_screencast_frame(self, event):
        if not isinstance(event, dict):
            return
        session_id = event.get("sessionId")
        data = str(event.get("data") or "").strip()
        if self._browser_cdp_session is not None and session_id is not None:
            try:
                self._resolve_browser_result(
                    self._browser_cdp_session.send("Page.screencastFrameAck", {"sessionId": int(session_id)})
                )
            except Exception:
                pass
        if not data:
            return
        with self._browser_stream_lock:
            self._browser_stream_payload = data
            self._browser_stream_payload_at = time.time()

    def _browser_stream_reuse_window_s(self) -> float:
        target_fps = self._target_fps()
        return max(0.08, min(0.18, 3.5 / max(12.0, target_fps)))

    def _latest_browser_stream_frame(self, max_age_s: float | None = None):
        age_limit = self._browser_stream_reuse_window_s() if max_age_s is None else max(0.02, float(max_age_s))
        with self._browser_stream_lock:
            frame = self._browser_stream_latest_frame
            captured_at = float(self._browser_stream_latest_frame_at or 0.0)
        if frame is None or captured_at <= 0.0:
            return None
        if (time.time() - captured_at) > age_limit:
            return None
        return frame.copy()

    def _consume_browser_stream_frame(self):
        if not self._browser_stream_active:
            return None
        with self._browser_stream_lock:
            payload = self._browser_stream_payload
            payload_at = float(self._browser_stream_payload_at or 0.0)
            latest_frame = self._browser_stream_latest_frame
            latest_frame_at = float(self._browser_stream_latest_frame_at or 0.0)
            last_signature = self._browser_stream_last_signature
        if not payload or payload_at <= 0.0:
            return None
        if payload_at <= self._browser_stream_last_consumed_at:
            return None
        signature = (len(payload), payload[:64], payload[-64:])
        if signature == last_signature and latest_frame is not None and latest_frame_at > 0.0:
            self._browser_stream_last_consumed_at = payload_at
            self._browser_stream_last_reused_at = time.time()
            return latest_frame.copy()
        try:
            raw = base64.b64decode(payload)
            frame = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
        except Exception:
            frame = None
        if frame is None:
            self._browser_stream_failures += 1
            return None
        viewport = dict(self._browser_viewport_size or {})
        bounds = dict(self._browser_capture_bounds or {})
        if viewport and bounds:
            viewport_width = max(1, int(viewport.get("width", frame.shape[1]) or frame.shape[1]))
            viewport_height = max(1, int(viewport.get("height", frame.shape[0]) or frame.shape[0]))
            scale_x = float(frame.shape[1]) / float(viewport_width)
            scale_y = float(frame.shape[0]) / float(viewport_height)
            crop_x = max(0, min(frame.shape[1] - 1, int(round(float(bounds.get("x", 0) or 0) * scale_x))))
            crop_y = max(0, min(frame.shape[0] - 1, int(round(float(bounds.get("y", 0) or 0) * scale_y))))
            crop_w = max(1, int(round(float(bounds.get("width", frame.shape[1]) or frame.shape[1]) * scale_x)))
            crop_h = max(1, int(round(float(bounds.get("height", frame.shape[0]) or frame.shape[0]) * scale_y)))
            crop_right = min(frame.shape[1], crop_x + crop_w)
            crop_bottom = min(frame.shape[0], crop_y + crop_h)
            if crop_right > crop_x and crop_bottom > crop_y:
                frame = frame[crop_y:crop_bottom, crop_x:crop_right].copy()
        if frame is None or self._browser_frame_is_blank(frame):
            self._browser_stream_failures += 1
            return None
        self._browser_stream_last_consumed_at = payload_at
        with self._browser_stream_lock:
            self._browser_stream_latest_frame = frame
            self._browser_stream_latest_frame_at = payload_at
            self._browser_stream_last_signature = signature
        return frame

    def _pump_browser_stream(self):
        if not self._browser_stream_active or self._browser_cdp_session is None:
            return
        try:
            self._resolve_browser_result(
                self._browser_cdp_session.send(
                    "Runtime.evaluate",
                    {"expression": "void 0", "returnByValue": True, "awaitPromise": False},
                )
            )
        except Exception:
            self._browser_stream_failures += 1

    def _configure_browser_page_runtime(self):
        if self._page is None:
            return
        init_script = """() => {
            try {
                const install = () => {
                    if (document.documentElement && !document.querySelector('style[data-browserai-perf=\"1\"]')) {
                        const style = document.createElement('style');
                        style.setAttribute('data-browserai-perf', '1');
                        style.textContent = `
                            *, *::before, *::after {
                                animation-duration: 0s !important;
                                animation-delay: 0s !important;
                                transition-duration: 0s !important;
                                transition-delay: 0s !important;
                                scroll-behavior: auto !important;
                            }
                        `;
                        (document.head || document.documentElement).appendChild(style);
                    }
                };
                install();
                document.addEventListener('DOMContentLoaded', install, { once: true });
                try {
                    Object.defineProperty(document, 'hidden', { configurable: true, get: () => false });
                    Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'visible' });
                } catch (_error) {
                }
                try {
                    const mediaProto = window.HTMLMediaElement && window.HTMLMediaElement.prototype;
                    if (mediaProto && !mediaProto.__browseraiMuted) {
                        const originalPlay = mediaProto.play;
                        mediaProto.play = function play() {
                            try {
                                this.muted = true;
                                this.volume = 0;
                                this.playbackRate = 1.0;
                            } catch (_error) {
                            }
                            return originalPlay ? originalPlay.apply(this, arguments) : Promise.resolve();
                        };
                        mediaProto.__browseraiMuted = true;
                    }
                } catch (_error) {
                }
            } catch (_error) {
            }
        }"""
        try:
            self._resolve_browser_result(self._page.add_init_script(init_script))
        except Exception:
            pass
        try:
            self._resolve_browser_result(self._page.emulate_media(reduced_motion="reduce"))
        except Exception:
            pass
        try:
            self._resolve_browser_result(self._page.set_default_timeout(10000))
            self._resolve_browser_result(self._page.set_default_navigation_timeout(45000))
        except Exception:
            pass

    def _bind_browser_network_observers(self):
        if self._page is None:
            return

        def should_track(request) -> bool:
            resource_type = str(getattr(request, "resource_type", "") or "").strip().lower()
            return resource_type not in {"websocket", "eventsource", "manifest", "ping"}

        def mark_request_started(request):
            if not should_track(request):
                return
            with self._browser_request_lock:
                self._pending_browser_requests += 1
                self._last_browser_request_at = time.time()

        def mark_request_finished(request):
            if not should_track(request):
                return
            with self._browser_request_lock:
                self._pending_browser_requests = max(0, self._pending_browser_requests - 1)
                self._last_browser_request_at = time.time()

        self._last_browser_request_at = time.time()
        self._page.on("request", mark_request_started)
        self._page.on("requestfinished", mark_request_finished)
        self._page.on("requestfailed", mark_request_finished)

    def _browser_network_state(self) -> tuple[int, float]:
        with self._browser_request_lock:
            pending = self._pending_browser_requests
            last_activity = self._last_browser_request_at
        idle_for = max(0.0, time.time() - last_activity) if last_activity else 0.0
        return pending, idle_for

    def _browser_loading_keywords(self) -> tuple[str, ...]:
        shared = (
            "loading",
            "connecting",
            "initializing",
            "starting",
            "please wait",
            "logging in",
            "fetching",
            "buffering",
            "entering",
        )
        values = [str(keyword).strip().lower() for keyword in (*self.game_profile.loading_keywords, *shared) if str(keyword).strip()]
        return tuple(dict.fromkeys(values))

    def _browser_ready_keywords(self) -> tuple[str, ...]:
        values = [str(keyword).strip().lower() for keyword in self.game_profile.ready_keywords if str(keyword).strip()]
        return tuple(dict.fromkeys(values))

    def _probe_browser_loading_state(self) -> dict:
        if self._page is None:
            return {}
        try:
            return self._resolve_browser_result(
                self._page.evaluate(
                """(payload) => {
                    const visible = (element) => {
                        if (!element) return false;
                        const style = window.getComputedStyle(element);
                        if (!style || style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity || 1) <= 0.02) {
                            return false;
                        }
                        const rect = element.getBoundingClientRect();
                        return rect.width >= 4 && rect.height >= 4;
                    };
                    const bodyText = ((document.body && document.body.innerText) || '')
                        .replace(/\\s+/g, ' ')
                        .trim()
                        .toLowerCase()
                        .slice(0, 6000);
                    const loadingMatch = (payload.loadingKeywords || []).find((keyword) => keyword && bodyText.includes(keyword)) || '';
                    const readyMatch = (payload.readyKeywords || []).find((keyword) => keyword && bodyText.includes(keyword)) || '';
                    const busySelectors = [
                        '[aria-busy=\"true\"]',
                        '[role=\"progressbar\"]',
                        '[class*=\"loading\"]',
                        '[id*=\"loading\"]',
                        '[class*=\"spinner\"]',
                        '[id*=\"spinner\"]',
                        '[class*=\"progress\"]',
                        '[id*=\"progress\"]',
                        '[class*=\"connect\"]',
                        '[id*=\"connect\"]',
                    ];
                    let busyCount = 0;
                    for (const selector of busySelectors) {
                        const elements = Array.from(document.querySelectorAll(selector)).filter(visible);
                        busyCount += elements.length;
                    }
                    return {
                        readyState: document.readyState || 'loading',
                        online: navigator.onLine !== false,
                        fontsReady: !document.fonts || document.fonts.status !== 'loading',
                        loadingMatch,
                        readyMatch,
                        busyCount,
                        title: (document.title || '').trim(),
                    };
                }""",
                {
                    "loadingKeywords": list(self._browser_loading_keywords()),
                    "readyKeywords": list(self._browser_ready_keywords()),
                },
                )
            )
        except Exception:
            return {}

    def _wait_for_game_ready(self, timeout_s: float = 60.0):
        started_at = time.time()
        last_bounds = None
        stable_surface_cycles = 0
        stable_ready_cycles = 0
        fitted_surface = False
        while not self.stop_event.is_set() and (time.time() - started_at) < max(5.0, float(timeout_s)):
            probe = self._probe_browser_loading_state()
            pending_requests, idle_for = self._browser_network_state()
            bounds = self._detect_browser_game_bounds()
            has_surface = bool(bounds and bounds.get("width", 0) >= 320 and bounds.get("height", 0) >= 180)
            if has_surface:
                if (
                    last_bounds is not None
                    and abs(int(bounds["width"]) - int(last_bounds["width"])) <= 12
                    and abs(int(bounds["height"]) - int(last_bounds["height"])) <= 12
                ):
                    stable_surface_cycles += 1
                else:
                    stable_surface_cycles = 1
                last_bounds = dict(bounds)
                if stable_surface_cycles >= 2 and not fitted_surface:
                    self._fit_browser_to_game_surface()
                    fitted_surface = True
            else:
                stable_surface_cycles = 0

            loading_match = str(probe.get("loadingMatch") or "").strip()
            ready_match = str(probe.get("readyMatch") or "").strip()
            ready_state = str(probe.get("readyState") or "loading").lower()
            online = bool(probe.get("online", True))
            fonts_ready = bool(probe.get("fontsReady", True))
            busy_count = int(probe.get("busyCount") or 0)
            elapsed = time.time() - started_at
            strict_network_ready = pending_requests <= 0 and idle_for >= 1.2
            relaxed_network_ready = (
                pending_requests <= 24
                and idle_for >= 0.15
                and has_surface
                and stable_surface_cycles >= 2
                and elapsed >= 8.5
            )
            network_ready = strict_network_ready or relaxed_network_ready
            ready_keyword_seen = bool(ready_match)
            loading_frame_marker = self._browser_loading_frame_marker(last_bounds if has_surface else None)
            soft_surface_ready = (
                online
                and ready_state == "complete"
                and fonts_ready
                and not loading_match
                and not loading_frame_marker
                and has_surface
                and stable_surface_cycles >= 2
                and pending_requests <= 8
                and busy_count <= 1
                and elapsed >= 12.0
            )
            ready_now = (
                online
                and ready_state == "complete"
                and fonts_ready
                and not loading_match
                and not loading_frame_marker
                and busy_count == 0
                and has_surface
                and stable_surface_cycles >= 2
                and network_ready
                and (ready_keyword_seen or elapsed >= 4.0)
            )
            ready_now = ready_now or soft_surface_ready
            self._last_loading_marker = loading_frame_marker or loading_match
            if ready_now:
                stable_ready_cycles += 1
            else:
                stable_ready_cycles = 0

            progress_parts = []
            if loading_match:
                progress_parts.append(f"loading text: {loading_match}")
            if loading_frame_marker:
                progress_parts.append(f"screen text: {loading_frame_marker}")
            if busy_count:
                progress_parts.append(f"visible loaders: {busy_count}")
            if not network_ready:
                progress_parts.append(f"network busy: {pending_requests} pending")
            if not has_surface:
                progress_parts.append("game surface not detected yet")
            elif stable_surface_cycles < 2:
                progress_parts.append("stabilizing game surface")
            if ready_state != "complete":
                progress_parts.append(f"document: {ready_state}")
            if not online:
                progress_parts.append("browser offline")
            if not fonts_ready:
                progress_parts.append("fonts still loading")
            if not progress_parts:
                progress_parts.append("stabilizing game state")

            self._update_snapshot(
                status="loading_game",
                task="Waiting For Game To Finish Loading",
                progress=" | ".join(progress_parts[:3]),
                capture=self._default_capture_summary(),
            )
            if stable_ready_cycles >= 2:
                self._update_snapshot(
                    status="loading_game",
                    task="Game Ready",
                    progress=f"{self.game_profile.name} loaded and ready for self-play",
                    capture=self._default_capture_summary(),
                )
                return
            time.sleep(0.35)

        fallback_message = (
            "Proceeding after load timeout"
            if not self._last_loading_marker
            else f"Proceeding after load timeout ({self._last_loading_marker})"
        )
        self._update_snapshot(
            status="loading_game",
            task="Load Timeout Fallback",
            progress=fallback_message,
            capture=self._default_capture_summary(),
        )
        if self.log_callback is not None:
            self.log_callback(f"{self.config.worker_id}: {fallback_message}.")

    def _fit_browser_to_game_surface(self):
        previous_bounds = dict(self._browser_capture_bounds) if self._browser_capture_bounds else None
        bounds = self._detect_browser_game_bounds()
        if bounds is None:
            self._browser_capture_bounds = None
            self.input_manager.bind_browser_page(
                self._page,
                offset=(0, 0),
                runner=self._resolve_browser_result,
                capture_scale=(1.0, 1.0),
            )
            return

        self._scroll_browser_surface_into_view(bounds)
        refreshed = self._detect_browser_game_bounds() or bounds

        target_width = max(320, min(3840, int(refreshed["width"]) + 24))
        target_height = max(240, min(2160, int(refreshed["height"]) + 24))
        try:
            self._resolve_browser_result(self._page.set_viewport_size({"width": target_width, "height": target_height}))
            self._browser_viewport_size = {"width": int(target_width), "height": int(target_height)}
        except Exception:
            pass

        final_bounds = self._detect_browser_game_bounds() or refreshed
        self._browser_capture_bounds = {
            "x": int(max(0, final_bounds["x"])),
            "y": int(max(0, final_bounds["y"])),
            "width": int(max(1, final_bounds["width"])),
            "height": int(max(1, final_bounds["height"])),
        }
        self.input_manager.bind_browser_page(
            self._page,
            offset=(self._browser_capture_bounds["x"], self._browser_capture_bounds["y"]),
            runner=self._resolve_browser_result,
            capture_scale=(self._browser_capture_scale, self._browser_capture_scale),
        )
        changed = previous_bounds != self._browser_capture_bounds
        if changed:
            self._start_browser_streaming_capture()
            self._update_snapshot(
                status="warming_capture",
                capture=self._capture_summary(),
                progress=(
                    f"Game surface {self._browser_capture_bounds['width']} x {self._browser_capture_bounds['height']} "
                    f"ready in Chromium"
                ),
            )
        if changed and self.log_callback is not None:
            self.log_callback(
                f"{self.config.worker_id}: detected game surface "
                f"{self._browser_capture_bounds['width']}x{self._browser_capture_bounds['height']} "
                f"at {self._browser_capture_bounds['x']},{self._browser_capture_bounds['y']}."
            )

    def _scroll_browser_surface_into_view(self, bounds: dict):
        if self._page is None:
            return
        try:
            self._resolve_browser_result(
                self._page.evaluate(
                """(target) => {
                    const left = Math.max(0, Math.floor(target.x) - 12);
                    const top = Math.max(0, Math.floor(target.y) - 12);
                    window.scrollTo({ left, top, behavior: 'instant' });
                }""",
                bounds,
            )
            )
        except Exception:
            pass

    def _detect_browser_game_bounds(self):
        if self._page is None:
            return None
        try:
            result = self._resolve_browser_result(
                self._page.evaluate(
                """() => {
                    const selectors = [
                        { query: 'canvas', weight: 6_000_000 },
                        { query: 'iframe', weight: 4_000_000 },
                        { query: 'embed', weight: 3_000_000 },
                        { query: 'object', weight: 3_000_000 },
                        { query: '[id*="game"]', weight: 2_000_000 },
                        { query: '[class*="game"]', weight: 2_000_000 },
                        { query: '[id*="play"]', weight: 1_500_000 },
                        { query: '[class*="play"]', weight: 1_500_000 },
                        { query: 'main', weight: 1_000_000 },
                    ];
                    const viewportWidth = window.innerWidth || document.documentElement.clientWidth || 1280;
                    const viewportHeight = window.innerHeight || document.documentElement.clientHeight || 720;
                    const centerX = viewportWidth / 2;
                    const centerY = viewportHeight / 2;
                    const candidates = [];
                    const seen = new Set();
                    const visibleRect = (element) => {
                        const rect = element.getBoundingClientRect();
                        const style = window.getComputedStyle(element);
                        if (!style || style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity || '1') <= 0.05) {
                            return null;
                        }
                        if (rect.width < 220 || rect.height < 140) {
                            return null;
                        }
                        if (rect.bottom <= 0 || rect.right <= 0 || rect.top >= viewportHeight || rect.left >= viewportWidth) {
                            return null;
                        }
                        return rect;
                    };
                    for (const entry of selectors) {
                        const nodes = Array.from(document.querySelectorAll(entry.query)).slice(0, 40);
                        for (const element of nodes) {
                            const rect = visibleRect(element);
                            if (!rect) continue;
                            const key = `${Math.round(rect.left)}:${Math.round(rect.top)}:${Math.round(rect.width)}:${Math.round(rect.height)}`;
                            if (seen.has(key)) continue;
                            seen.add(key);
                            const area = rect.width * rect.height;
                            const distance = Math.abs((rect.left + rect.width / 2) - centerX) + Math.abs((rect.top + rect.height / 2) - centerY);
                            candidates.push({
                                x: Math.max(0, Math.round(rect.left)),
                                y: Math.max(0, Math.round(rect.top)),
                                width: Math.max(1, Math.round(rect.width)),
                                height: Math.max(1, Math.round(rect.height)),
                                score: area + entry.weight - (distance * 120),
                            });
                        }
                    }
                    if (!candidates.length) {
                        return {
                            x: 0,
                            y: 0,
                            width: Math.max(320, Math.round(viewportWidth)),
                            height: Math.max(240, Math.round(viewportHeight)),
                            score: 0,
                        };
                    }
                    candidates.sort((a, b) => b.score - a.score);
                    return candidates[0];
                }"""
                )
            )
        except Exception:
            return None
        if not isinstance(result, dict):
            return None
        width = max(1, int(result.get("width", 0) or 0))
        height = max(1, int(result.get("height", 0) or 0))
        if width <= 0 or height <= 0:
            return None
        return {
            "x": max(0, int(result.get("x", 0) or 0)),
            "y": max(0, int(result.get("y", 0) or 0)),
            "width": width,
            "height": height,
        }

    def _launch_browser(self, gpu_enabled: bool | None = None):
        if self._playwright is None or not hasattr(self._playwright, "chromium"):
            raise RuntimeError("Playwright is not initialized for browser launch.")
        gpu_enabled = bool(gpu_enabled)
        launch_args = [
            "--disable-background-timer-throttling",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
            "--disable-background-networking",
            "--disable-breakpad",
            "--disable-component-update",
            "--disable-default-apps",
            "--disable-domain-reliability",
            "--disable-extensions",
            "--disable-features=CalculateNativeWinOcclusion,BackForwardCache,MediaRouter,OptimizationHints,Translate",
            "--metrics-recording-only",
            "--mute-audio",
            "--no-default-browser-check",
            "--no-first-run",
            "--password-store=basic",
            "--use-mock-keychain",
        ]
        if gpu_enabled:
            launch_args.extend(
                [
                    "--enable-gpu-rasterization",
                    "--enable-zero-copy",
                    "--ignore-gpu-blocklist",
                    "--use-angle=d3d11",
                ]
            )
        else:
            launch_args.append("--disable-gpu")
        launch_kwargs = {
            "headless": True,
            "args": launch_args,
        }
        last_error = None
        for launch_entry in self._browser_launch_entries():
            entry_kwargs = dict(launch_kwargs)
            entry_kwargs.update(dict(launch_entry.get("kwargs") or {}))
            try:
                browser = self._resolve_browser_result(self._playwright.chromium.launch(**entry_kwargs))
                self._browser_engine_label = str(launch_entry.get("label") or "Chromium")
                return browser
            except Exception as exc:
                last_error = exc
                if self.log_callback is not None:
                    self.log_callback(
                        f"{self.config.worker_id}: browser launch via {launch_entry.get('label', 'Chromium')} failed: {exc}"
                    )
        if last_error is not None:
            raise last_error
        raise RuntimeError("No browser launch targets were available.")

    def _browser_launch_entries(self):
        entries = []
        seen = set()

        def add_entry(label: str, **kwargs):
            signature = (label, tuple(sorted(kwargs.items())))
            if signature in seen:
                return
            seen.add(signature)
            entries.append({"label": label, "kwargs": kwargs})

        # Prefer bundled Chromium first for the most predictable capture path,
        # then fall back to locally installed browsers if startup fails.
        add_entry("Chromium")

        candidates = self._browser_executable_candidates()
        for executable_path in candidates:
            lower_path = executable_path.lower()
            if lower_path.endswith("msedge.exe"):
                add_entry("Microsoft Edge", channel="msedge")
                add_entry("Microsoft Edge", executable_path=executable_path)
            elif lower_path.endswith("chrome.exe"):
                add_entry("Google Chrome", channel="chrome")
                add_entry("Google Chrome", executable_path=executable_path)
            else:
                add_entry(Path(executable_path).stem or "Local Browser", executable_path=executable_path)

        return entries

    def _has_local_browser_target(self) -> bool:
        return bool(self._browser_executable_candidates())

    def _preferred_local_browser_label(self) -> str:
        for launch_entry in self._browser_launch_entries():
            label = str(launch_entry.get("label") or "")
            if label and label != "Chromium":
                return label
        return "Chromium"

    def _browser_executable_candidates(self):
        env_paths = [
            os.path.join(os.environ.get("PROGRAMFILES", ""), "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(os.environ.get("PROGRAMFILES(X86)", ""), "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(os.environ.get("PROGRAMFILES", ""), "Chromium", "Application", "chrome.exe"),
            os.path.join(os.environ.get("PROGRAMFILES(X86)", ""), "Chromium", "Application", "chrome.exe"),
            os.path.join(os.environ.get("PROGRAMFILES", ""), "Microsoft", "Edge", "Application", "msedge.exe"),
            os.path.join(os.environ.get("PROGRAMFILES(X86)", ""), "Microsoft", "Edge", "Application", "msedge.exe"),
        ]
        which_paths = [shutil.which(name) for name in ("chrome.exe", "chromium.exe", "msedge.exe")]
        candidates = []
        for path in [*env_paths, *which_paths]:
            if path and path not in candidates and os.path.exists(path):
                candidates.append(path)
        return candidates

    def _close_browser_session(self):
        self._stop_browser_streaming_capture()
        for resource in (self._browser_context, self._browser):
            if resource is None:
                continue
            try:
                self._resolve_browser_result(resource.close())
            except Exception:
                pass
        if self._playwright is not None:
            try:
                self._resolve_browser_result(self._playwright.stop())
            except Exception:
                pass
        elif self._playwright_manager is not None:
            exit_method = getattr(self._playwright_manager, "__exit__", None)
            if callable(exit_method):
                try:
                    exit_method(None, None, None)
                except Exception:
                    pass
        self._browser_context = None
        self._browser = None
        self._browser_cdp_session = None
        self._playwright = None
        self._playwright_manager = None
        if self._browser_async_loop is not None:
            try:
                self._browser_async_loop.close()
            except Exception:
                pass
        self._browser_async_loop = None
        self._playwright_async_mode = False
        self._page = None
        self._browser_capture_bounds = None
        self._browser_viewport_size = None
        self._browser_process_ids = []
        self._browser_engine_label = "Chromium"
        self._browser_stream_handler_registered = False
        self._fit_surface_checkpoints_done = set()
        self.input_manager.bind_browser_page(None, offset=(0, 0), runner=None, capture_scale=(1.0, 1.0))

    def _capture_frame(self):
        if self.config.mode.lower() == "browser":
            if self._page is None:
                raise RuntimeError("Browser worker page is not initialized.")
            if self._steps in {0, 4, 10} and self._steps not in self._fit_surface_checkpoints_done:
                try:
                    self._fit_browser_to_game_surface()
                    self._fit_surface_checkpoints_done.add(int(self._steps))
                except Exception:
                    pass
            if self._browser_stream_active:
                self._pump_browser_stream()
                frame = self._consume_browser_stream_frame()
                if frame is not None:
                    self._browser_stream_failures = 0
                    return frame
                cached_stream_frame = self._latest_browser_stream_frame()
                if cached_stream_frame is not None:
                    return cached_stream_frame
                if self._browser_stream_failures >= 6:
                    self._stop_browser_streaming_capture()
            if self._browser_prefers_canvas_capture:
                frame = self._capture_browser_canvas_frame()
                if frame is not None:
                    return frame
            if self._browser_cdp_session is not None and self._browser_capture_bounds:
                frame = self._capture_browser_cdp_frame()
                if frame is not None:
                    return frame
            screenshot_kwargs = {"type": "jpeg", "quality": self._browser_capture_jpeg_quality(), "scale": "css"}
            if self._browser_capture_bounds:
                screenshot_kwargs["clip"] = dict(self._browser_capture_bounds)
            raw = self._resolve_browser_result(self._page.screenshot(**screenshot_kwargs))
            frame = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
            if frame is None:
                raise RuntimeError("Unable to decode browser worker screenshot.")
            return frame
        region = self._desktop_capture_region()
        return capture_screen(region)

    def _capture_browser_cdp_frame(self):
        if self._browser_cdp_session is None or not self._browser_capture_bounds:
            return None
        clip = {
            "x": float(max(0, self._browser_capture_bounds.get("x", 0))),
            "y": float(max(0, self._browser_capture_bounds.get("y", 0))),
            "width": float(max(1, self._browser_capture_bounds.get("width", 1))),
            "height": float(max(1, self._browser_capture_bounds.get("height", 1))),
            "scale": float(max(0.25, min(1.0, self._browser_capture_scale))),
        }
        command_payload = {
            "format": "jpeg",
            "quality": self._browser_capture_jpeg_quality(),
            "clip": clip,
            "fromSurface": True,
            "captureBeyondViewport": False,
            "optimizeForSpeed": True,
        }
        try:
            payload = self._resolve_browser_result(self._browser_cdp_session.send("Page.captureScreenshot", command_payload))
        except Exception:
            try:
                fallback_payload = dict(command_payload)
                fallback_payload.pop("optimizeForSpeed", None)
                payload = self._resolve_browser_result(
                    self._browser_cdp_session.send("Page.captureScreenshot", fallback_payload)
                )
            except Exception:
                self._browser_cdp_session = None
                return None
        if not isinstance(payload, dict):
            return None
        encoded = str(payload.get("data") or "").strip()
        if not encoded:
            return None
        try:
            raw = base64.b64decode(encoded)
            frame = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
        except Exception:
            frame = None
        if frame is None or self._browser_frame_is_blank(frame):
            return None
        return frame

    def _browser_frame_is_blank(self, frame) -> bool:
        if frame is None or getattr(frame, "size", 0) <= 0:
            return True
        try:
            max_value = int(frame.max())
            mean_value = float(frame.mean())
            std_value = float(frame.std())
            dark_ratio = float((frame < 8).mean())
        except Exception:
            return False
        if max_value <= 4:
            return True
        if mean_value <= 1.0 and std_value <= 1.0:
            return True
        if dark_ratio >= 0.995 and std_value <= 2.0:
            return True
        return False

    def _capture_browser_canvas_frame(self):
        if self._page is None:
            return None
        try:
            payload = self._resolve_browser_result(
                self._page.evaluate(
                    """() => {
                        const visible = (element) => {
                            if (!element) return false;
                            const style = window.getComputedStyle(element);
                            if (!style || style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity || '1') <= 0.05) {
                                return false;
                            }
                            const rect = element.getBoundingClientRect();
                            return rect.width >= 120 && rect.height >= 120;
                        };
                        const canvases = Array.from(document.querySelectorAll('canvas')).filter(visible);
                        if (!canvases.length) {
                            return null;
                        }
                        canvases.sort((left, right) => {
                            const leftRect = left.getBoundingClientRect();
                            const rightRect = right.getBoundingClientRect();
                            return (rightRect.width * rightRect.height) - (leftRect.width * leftRect.height);
                        });
                        const canvas = canvases[0];
                        try {
                            return canvas.toDataURL('image/jpeg', 0.72);
                        } catch (_error) {
                            return null;
                        }
                    }"""
                )
            )
        except Exception:
            return None
        if not payload or not isinstance(payload, str) or "," not in payload:
            return None
        try:
            raw = base64.b64decode(payload.split(",", 1)[1])
            frame = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
        except Exception:
            frame = None
        if frame is None:
            return None
        if self._browser_frame_is_blank(frame):
            self._browser_prefers_canvas_capture = False
            if self.log_callback is not None:
                self.log_callback(
                    f"{self.config.worker_id}: browser canvas capture was blank; falling back to page screenshots."
                )
            return None
        self._browser_prefers_canvas_capture = True
        return frame

    def _analysis_frame(self, frame):
        if frame is None:
            return frame
        height, width = frame.shape[:2]
        longest_edge = max(height, width)
        if self.config.mode.lower() == "browser":
            target_fps = self._target_fps()
            if self.game_profile.idle_clicker and target_fps >= 30.0:
                max_edge = 224
            elif target_fps >= 30.0:
                max_edge = 240
            else:
                max_edge = 256
        else:
            max_edge = 720
        if longest_edge <= max_edge:
            return frame
        scale = max_edge / float(longest_edge)
        return cv2.resize(
            frame,
            (max(1, int(width * scale)), max(1, int(height * scale))),
            interpolation=cv2.INTER_AREA,
        )

    def _browser_state_text(self) -> str:
        if self.config.mode.lower() != "browser" or self._page is None:
            return ""
        now = time.time()
        if self._cached_dom_state_text and (now - self._last_dom_state_text_at) < 0.85:
            return self._cached_dom_state_text
        try:
            result = self._resolve_browser_result(
                self._page.evaluate(
                    """() => {
                        const clean = (value) => String(value || '').replace(/\\s+/g, ' ').trim();
                        const pieces = [];
                        const title = clean(document.title || '');
                        if (title) pieces.push(title);
                        const selectors = [
                            'button',
                            '[role="button"]',
                            '[class*="btn"]',
                            '[class*="button"]',
                            '[class*="reward"]',
                            '[class*="claim"]',
                            '[class*="quest"]',
                            '[class*="daily"]'
                        ];
                        const seen = new Set();
                        for (const selector of selectors) {
                            for (const element of Array.from(document.querySelectorAll(selector)).slice(0, 36)) {
                                const text = clean(element.innerText || element.textContent || '');
                                if (!text || seen.has(text)) continue;
                                seen.add(text);
                                pieces.push(text);
                                if (pieces.length >= 24) break;
                            }
                            if (pieces.length >= 24) break;
                        }
                        const bodyText = clean((document.body && document.body.innerText) || '').slice(0, 1200);
                        if (bodyText) pieces.push(bodyText);
                        return clean(pieces.join(' | ').slice(0, 1800));
                    }"""
                )
            )
        except Exception:
            return self._cached_dom_state_text
        self._cached_dom_state_text = str(result or "").strip()
        self._last_dom_state_text_at = now
        return self._cached_dom_state_text

    def _state_refresh_interval_s(self) -> float:
        target_fps = self._target_fps()
        if self.config.mode.lower() == "browser":
            if self.game_profile.idle_clicker:
                return max(0.85, min(1.25, 16.0 / max(1.0, target_fps)))
            return max(0.12, min(0.30, 4.0 / max(1.0, target_fps)))
        return max(0.20, min(0.50, 8.0 / max(1.0, target_fps)))

    def _action_interval_s(self) -> float:
        if self.config.mode.lower() != "browser":
            return 0.12
        target_fps = self._target_fps()
        if self.game_profile.idle_clicker:
            return max(0.16, min(0.26, 4.0 / max(12.0, target_fps)))
        return max(0.12, min(0.20, 4.5 / max(12.0, target_fps)))

    def _run_state_analysis(self, frame, preferred_text: str = ""):
        ocr_cooldown_s = 3.8 if preferred_text else 1.2
        game_state, reward = self.state_tracker.update(
            frame,
            preferred_text=preferred_text,
            allow_ocr=True,
            ocr_cooldown_s=ocr_cooldown_s,
        )
        visual_targets = self._detect_visual_targets(frame)
        return dict(game_state or {}), float(reward or 0.0), str(self.state_tracker.last_text or ""), visual_targets

    def _poll_state_analysis(self):
        future = self._analysis_future
        if future is None or not future.done():
            return
        self._analysis_future = None
        try:
            result = future.result()
        except Exception as exc:
            if self.log_callback is not None:
                self.log_callback(f"{self.config.worker_id}: state analysis error: {exc}")
            return
        if isinstance(result, tuple) and len(result) >= 4:
            game_state, reward, last_text, visual_targets = result[:4]
        else:
            game_state, reward, last_text = result[:3]
            visual_targets = []
        self._cached_game_state = dict(game_state or {})
        self._cached_reward_value = float(reward or 0.0)
        self._latest_state_text = last_text
        self._cached_visual_targets = list(visual_targets or [])
        self._analysis_available_at = self._analysis_submitted_at

    def _schedule_state_analysis(self, frame):
        if self._analysis_executor is None:
            return
        if self._analysis_future is not None:
            return
        now = time.time()
        if self._last_state_refresh_at > 0.0 and (now - self._last_state_refresh_at) < self._state_refresh_interval_s():
            return
        analysis_frame = self._analysis_frame(frame)
        if analysis_frame is None:
            return
        preferred_text = self._browser_state_text() if self.config.mode.lower() == "browser" else ""
        self._last_state_refresh_at = now
        self._analysis_submitted_at = now
        self._analysis_future = self._analysis_executor.submit(self._run_state_analysis, analysis_frame, preferred_text)

    def _resolve_game_state(self, frame):
        self._poll_state_analysis()
        self._schedule_state_analysis(frame)
        reward_value = 0.0
        if self._analysis_available_at > self._analysis_consumed_at:
            self._analysis_consumed_at = self._analysis_available_at
            reward_value = self._cached_reward_value
        return dict(self._cached_game_state), reward_value

    def _preferred_browser_capture_scale(self) -> float:
        if self.config.mode.lower() != "browser":
            return 1.0
        if self.game_profile.idle_clicker:
            return 0.90
        return 1.0

    def _browser_capture_jpeg_quality(self) -> int:
        return 20

    def _gpu_requested_enabled(self) -> bool:
        return self.config.mode.lower() == "browser" and bool(self.config.gpu_acceleration_enabled)

    def _gpu_enabled(self) -> bool:
        return self.config.mode.lower() == "browser" and bool(self._effective_gpu_enabled)

    def _browser_child_pids(self) -> list[int]:
        if psutil is None:
            return []
        try:
            process = psutil.Process(os.getpid())
            children = process.children(recursive=True)
        except Exception:
            return []
        pids = []
        for child in children:
            try:
                name = child.name().lower()
            except Exception:
                continue
            if any(token in name for token in ("chrome", "chromium", "edge", "msedge", "headless")):
                pids.append(int(child.pid))
        return sorted(set(pids))

    def _capture_browser_process_ids(self, known_pids=None):
        current_pids = self._browser_child_pids()
        if not current_pids:
            return
        known = {int(pid) for pid in list(known_pids or []) if pid is not None}
        new_pids = [pid for pid in current_pids if pid not in known]
        self._browser_process_ids = new_pids or current_pids

    def _detect_browser_gpu_details(self):
        if self.config.mode.lower() != "browser":
            self._browser_gpu_vendor = "Shared desktop mode"
            self._browser_gpu_renderer = "Shared desktop mode"
            return
        host_info = get_host_gpu_info()
        if self._gpu_enabled() and host_info.get("available"):
            host_name = str(host_info.get("name") or "Hardware accelerated").strip()
            memory_gb = float(host_info.get("memory_gb") or 0.0)
            self._browser_gpu_vendor = host_name
            self._browser_gpu_renderer = (
                f"{self._browser_engine_label} hardware acceleration"
                f"{f' | {memory_gb:.1f} GB VRAM' if memory_gb > 0 else ''}"
            )
            self._gpu_launch_note = "Hardware acceleration active"
            return
        self._browser_gpu_vendor = "Disabled"
        self._browser_gpu_renderer = "Legacy browser mode"
        self._gpu_launch_note = "Legacy browser mode"

    def _poll_gpu_usage(self, force: bool = False):
        if self.config.mode.lower() != "browser":
            self._browser_gpu_percent = 0.0
            self._host_gpu_percent = 0.0
            return
        if not self._gpu_enabled():
            self._browser_gpu_percent = 0.0
            self._host_gpu_percent = 0.0
            return
        now = time.time()
        if self._gpu_future is not None and self._gpu_future.done():
            try:
                usage = self._gpu_future.result()
            except Exception:
                usage = None
            self._gpu_future = None
            if isinstance(usage, dict):
                self._browser_gpu_percent = max(0.0, float(usage.get("percent") or 0.0))
                self._host_gpu_percent = max(0.0, float(usage.get("overall_percent") or 0.0))
                self._gpu_usage_samples.append(self._browser_gpu_percent)
                if usage.get("host_name"):
                    self._browser_gpu_vendor = str(usage.get("host_name") or self._browser_gpu_vendor).strip()
                    memory_gb = float(usage.get("memory_gb") or 0.0)
                    self._browser_gpu_renderer = (
                        f"{self._browser_engine_label} hardware acceleration"
                        f"{f' | {memory_gb:.1f} GB VRAM' if memory_gb > 0 else ''}"
                    )
        poll_interval_s = 3.0
        if self._gpu_future is not None:
            return
        if not force and (now - self._last_gpu_poll_at) < poll_interval_s:
            return
        if self._gpu_executor is None:
            self._gpu_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"{self.config.worker_id}-gpu")
        self._last_gpu_poll_at = now
        pid_list = list(self._browser_process_ids)
        self._gpu_future = self._gpu_executor.submit(sample_gpu_usage, pid_list, 2.0)

    def _gpu_usage_percent(self) -> float:
        if self.config.mode.lower() != "browser":
            return 0.0
        if self._gpu_enabled():
            return max(self._browser_gpu_percent, self._host_gpu_percent if self._browser_gpu_percent <= 0.0 else 0.0)
        return 0.0

    def _sync_browser_input_capture_scale(self, frame):
        if self.config.mode.lower() != "browser" or frame is None or self._browser_capture_bounds is None:
            return
        logical_width = max(1, int(self._browser_capture_bounds.get("width", 1) or 1))
        logical_height = max(1, int(self._browser_capture_bounds.get("height", 1) or 1))
        frame_height, frame_width = frame.shape[:2]
        scale_x = max(0.10, float(frame_width) / float(logical_width))
        scale_y = max(0.10, float(frame_height) / float(logical_height))
        current_scale = getattr(self.input_manager, "browser_capture_scale", (1.0, 1.0))
        if abs(scale_x - float(current_scale[0])) < 0.01 and abs(scale_y - float(current_scale[1])) < 0.01:
            return
        self.input_manager.bind_browser_page(
            self._page,
            offset=(self._browser_capture_bounds["x"], self._browser_capture_bounds["y"]),
            runner=self._resolve_browser_result,
            capture_scale=(scale_x, scale_y),
        )

    def _gpu_usage_label(self) -> str:
        if self.config.mode.lower() != "browser":
            return "0/100%"
        return f"{self._gpu_usage_percent():.0f}/100%"

    def _gpu_detail_label(self) -> str:
        if self.config.mode.lower() != "browser":
            return "Shared desktop mode"
        if not self._gpu_enabled():
            return self._gpu_launch_note or "Legacy browser mode"
        worker_percent = f"{self._browser_gpu_percent:.0f}%"
        host_percent = f"{self._host_gpu_percent:.0f}%"
        detail = f"Hardware acceleration active | Worker {worker_percent} | Host {host_percent}"
        if self._browser_gpu_vendor and self._browser_gpu_vendor != "Disabled":
            detail = f"{detail} | {self._browser_gpu_vendor}"
        if self._browser_gpu_renderer and self._browser_gpu_renderer not in {"Disabled", "Legacy browser mode"}:
            detail = f"{detail} | {self._browser_gpu_renderer}"
        return detail

    def _desktop_capture_region(self):
        if self.config.desktop_window_title:
            region = get_window_region(self.config.desktop_window_title)
            if region:
                return region
        return self.config.capture_region

    def _record_captured_frame(self, frame):
        timestamp = time.time()
        self._sync_browser_input_capture_scale(frame)
        with self.state_lock:
            self._latest_frame = frame
            self._latest_frame_at = timestamp
            self._frame_times.append(timestamp)

    def _warm_browser_capture(self, timeout_s: float = 6.0) -> bool:
        deadline = time.time() + max(1.0, float(timeout_s or 1.0))
        while time.time() < deadline and not self.stop_event.is_set():
            frame = None
            if self._browser_stream_active:
                self._pump_browser_stream()
                frame = self._consume_browser_stream_frame()
            if frame is None and self._browser_prefers_canvas_capture:
                frame = self._capture_browser_canvas_frame()
            if frame is None and self._browser_cdp_session is not None and self._browser_capture_bounds:
                frame = self._capture_browser_cdp_frame()
            if frame is None and self._page is not None:
                try:
                    screenshot_kwargs = {"type": "jpeg", "quality": self._browser_capture_jpeg_quality(), "scale": "css"}
                    if self._browser_capture_bounds:
                        screenshot_kwargs["clip"] = dict(self._browser_capture_bounds)
                    raw = self._resolve_browser_result(self._page.screenshot(**screenshot_kwargs))
                    frame = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
                except Exception:
                    frame = None
            if frame is not None:
                self._record_captured_frame(frame)
                self._last_frame_shape = frame.shape
                self._update_snapshot(
                    status="warming_capture",
                    task="Capture Warmed",
                    progress="Initial browser frame captured. Autoplay will start next.",
                    capture=self._capture_summary(),
                )
                return True
            time.sleep(0.08)
        self._update_snapshot(
            status="warming_capture",
            task="Capture Warmup Timeout",
            progress="Continuing without a primed preview frame.",
            capture=self._capture_summary(),
        )
        return False

    def _loop_delay(self) -> float:
        target_delay = 1.0 / self._target_fps()
        if self.game_profile.idle_clicker:
            profile_delay = self.game_profile.quick_delay_s if self.config.quick_mode else self.game_profile.normal_delay_s
            if self.config.mode.lower() == "browser" and getattr(self.input_manager, "fast_browser_input", False):
                return min(profile_delay, max(0.001, target_delay * 0.08))
            return min(profile_delay, target_delay)
        profile_delay = 0.12 if self.config.quick_mode else 0.35
        return min(profile_delay, target_delay)

    def _ad_policy_summary(self) -> str:
        return "Watch Reward Ads" if bool(self.config.watch_reward_ads) else "Skip Reward Ads"

    def _learning_summary(self) -> str:
        session_text = self.session_store.summary() if self.session_store is not None else "Session standby"
        if self.learning_memory is None:
            return f"Learning memory disabled | {session_text}"
        return f"{self.learning_memory.summary()} | {session_text}"

    def _restore_session_state(self):
        session = dict((self.session_state or {}).get("last_session") or {})
        cached_state = dict(session.get("game_state") or {})
        if cached_state:
            self._cached_game_state = cached_state
            self._profile_last_state = dict(cached_state)
        try:
            self._total_reward = float(session.get("total_reward", 0.0) or 0.0)
        except Exception:
            self._total_reward = 0.0
        try:
            self._task_cycle_index = max(0, int(session.get("task_cycle_index", 0) or 0))
        except Exception:
            self._task_cycle_index = 0
        task_stats = session.get("task_stats") or {}
        if isinstance(task_stats, dict):
            restored_stats = {}
            for key, value in task_stats.items():
                if not isinstance(value, dict):
                    continue
                task_key = str(key or "").strip().lower()
                if not task_key:
                    continue
                restored_stats[task_key] = {
                    "attempts": max(0, int(value.get("attempts", 0) or 0)),
                    "successes": max(0, int(value.get("successes", 0) or 0)),
                    "neutrals": max(0, int(value.get("neutrals", 0) or 0)),
                    "failures": max(0, int(value.get("failures", 0) or 0)),
                    "recent_failures": max(0, int(value.get("recent_failures", 0) or 0)),
                    "score": float(value.get("score", 0.0) or 0.0),
                    "last_score": float(value.get("last_score", 0.0) or 0.0),
                    "last_result": str(value.get("last_result", "") or ""),
                    "updated_at": float(value.get("updated_at", 0.0) or 0.0),
                }
            self._task_stats = restored_stats
        self._dom_live_last_action = str(session.get("dom_last_action", "") or "").strip()
        self._dom_live_last_confirmation = str(session.get("dom_last_confirmation", "") or "").strip()
        self._dom_live_last_fallback_reason = str(session.get("dom_fallback_reason", "") or "").strip()

    def _persist_session_state(self, force: bool = False):
        if self.session_store is None or (self._standby_pool_slot and not self._standby_claimed_by):
            return
        now = time.time()
        if not force and self._steps - self._session_last_saved_steps < 5 and (now - self._last_persist_at) < 2.0:
            return
        payload = {
            "saved_at": now,
            "steps": int(self._steps),
            "total_reward": float(self._total_reward),
            "last_action": str(self.input_manager.last_action or "idle"),
            "task": str(self._profile_action_label or "idle"),
            "capture": self._capture_summary(),
            "game_state": dict(self._cached_game_state or {}),
            "profile": self.game_profile.name,
            "guide_enabled": bool(self.guide_context),
            "guide_focus": self._guide_focus_summary(),
            "task_cycle_index": int(self._task_cycle_index),
            "task_stats": dict(self._task_stats or {}),
            "dom_drive_mode": self._dom_drive_mode(),
            "dom_last_action": str(self._dom_live_last_action or ""),
            "dom_last_confirmation": str(self._dom_live_last_confirmation or ""),
            "dom_fallback_reason": str(self._dom_live_last_fallback_reason or ""),
        }
        self.session_store.save(payload)
        self._session_last_saved_steps = int(self._steps)
        self._last_persist_at = now

    def _task_stats_entry(self, task_key: str) -> dict:
        normalized = str(task_key or "").strip().lower() or "unknown"
        entry = self._task_stats.setdefault(
            normalized,
            {
                "attempts": 0,
                "successes": 0,
                "neutrals": 0,
                "failures": 0,
                "recent_failures": 0,
                "score": 0.0,
                "last_score": 0.0,
                "last_result": "",
                "updated_at": 0.0,
            },
        )
        return entry

    def _task_memory_score(self, task_key: str) -> float:
        if self.learning_memory is None:
            return 0.0
        return float(self.learning_memory.task_score(task_key) or 0.0)

    def _task_cooldown_s(self, task_key: str, base_cooldown_s: float = 0.9) -> float:
        stats = self._task_stats_entry(task_key)
        recent_failures = max(0, int(stats.get("recent_failures", 0) or 0))
        memory_score = self._task_memory_score(task_key)
        cooldown = float(base_cooldown_s) + min(2.0, recent_failures * 0.35)
        if memory_score > 0.8:
            cooldown *= 0.72
        return max(0.12, cooldown)

    def _task_on_cooldown(self, task_key: str, base_cooldown_s: float = 0.9) -> bool:
        task_name = str(task_key or "").strip().lower()
        if not task_name:
            return False
        last_attempt_at = float(self._task_last_attempt_at.get(task_name, 0.0) or 0.0)
        if last_attempt_at <= 0.0:
            return False
        return (time.time() - last_attempt_at) < self._task_cooldown_s(task_name, base_cooldown_s)

    def _task_success_rate(self, task_key: str) -> float:
        stats = self._task_stats_entry(task_key)
        successes = max(0, int(stats.get("successes", 0) or 0))
        failures = max(0, int(stats.get("failures", 0) or 0))
        decisive = successes + failures
        if decisive <= 0:
            return 0.0
        return float(successes) / float(decisive)

    def _mark_task_attempt(
        self,
        task_key: str,
        action_label: str,
        game_state: dict | None,
        cycle_index: int | None = None,
        cycle_count: int = 0,
    ):
        task_name = str(task_key or "").strip().lower()
        if not task_name:
            return
        if cycle_count > 0 and cycle_index is not None:
            self._task_cycle_index = (int(cycle_index) + 1) % max(1, int(cycle_count))
        self._task_last_attempt_at[task_name] = time.time()
        self._pending_task_context = {
            "task_key": task_name,
            "action_key": str(self._last_learning_action or "").strip() or None,
            "label": str(action_label or self._profile_action_label or task_name),
            "before_state": dict(game_state or self._cached_game_state or {}),
            "before_text": self._combined_visible_state_text(),
            "step": int(self._steps),
            "started_at": time.time(),
            "observe_until": time.time() + 1.25,
        }

    def _contains_any_keyword(self, text: str, keywords) -> bool:
        blob = str(text or "").strip().lower()
        if not blob:
            return False
        return any(str(keyword or "").strip().lower() in blob for keyword in list(keywords or []) if str(keyword or "").strip())

    def _state_progress_signal(self, before_state: dict | None, current_state: dict | None) -> float:
        previous = dict(before_state or {})
        current = dict(current_state or {})
        gold_gain = max(0, int(current.get("gold", 0) or 0) - int(previous.get("gold", 0) or 0))
        xp_gain = max(0, int(current.get("xp", 0) or 0) - int(previous.get("xp", 0) or 0))
        level_gain = max(0, int(current.get("level", 0) or 0) - int(previous.get("level", 0) or 0))
        signal = (
            gold_gain * max(0.005, float(self.game_profile.gold_reward_scale) * 0.65)
            + xp_gain * max(0.020, float(self.game_profile.xp_reward_scale) * 0.55)
            + level_gain * max(4.0, float(self.game_profile.level_reward_scale) * 0.45)
        )
        return float(min(18.0, signal))

    def _note_task_outcome(self, task_key: str, score: float, outcome: str, result_label: str):
        task_name = str(task_key or "").strip().lower()
        if not task_name:
            return
        stats = self._task_stats_entry(task_name)
        stats["attempts"] = int(stats.get("attempts", 0) or 0) + 1
        normalized_outcome = str(outcome or "").strip().lower()
        if normalized_outcome == "success":
            stats["successes"] = int(stats.get("successes", 0) or 0) + 1
            stats["recent_failures"] = 0
            self._task_last_success_at[task_name] = time.time()
        elif normalized_outcome == "neutral":
            stats["neutrals"] = int(stats.get("neutrals", 0) or 0) + 1
            stats["recent_failures"] = max(0, int(stats.get("recent_failures", 0) or 0) - 1)
        else:
            stats["failures"] = int(stats.get("failures", 0) or 0) + 1
            stats["recent_failures"] = min(6, int(stats.get("recent_failures", 0) or 0) + 1)
        previous_score = float(stats.get("score", 0.0) or 0.0)
        smoothing = 0.22 if normalized_outcome == "success" else 0.10 if normalized_outcome == "neutral" else 0.16
        stats["score"] = round((previous_score * (1.0 - smoothing)) + (float(score) * smoothing), 4)
        stats["last_score"] = float(score)
        stats["last_result"] = str(result_label or normalized_outcome or "no effect")
        stats["updated_at"] = time.time()
        if self.learning_memory is not None:
            self.learning_memory.record_task(task_name, score)

    def _remember_action_key(self, action_key: str | None):
        self._last_learning_action = str(action_key or "").strip() or None

    def _record_learning_outcome(self, game_state: dict | None, reward_value: float):
        pending = dict(self._pending_task_context or {})
        if not pending:
            return
        now = time.time()
        current_state = dict(game_state or self._cached_game_state or {})
        current_text = self._combined_visible_state_text()
        before_state = dict(pending.get("before_state") or {})
        before_text = str(pending.get("before_text") or "")
        task_key = str(pending.get("task_key") or "").strip().lower()
        action_key = str(pending.get("action_key") or "").strip() or None
        label_text = str(pending.get("label") or task_key or "task").strip().lower()
        observe_until = float(pending.get("observe_until", 0.0) or 0.0)

        score = max(-0.8, min(1.8, float(reward_value or 0.0)))
        progress_signal = self._state_progress_signal(before_state, current_state)
        score += progress_signal
        text_changed = bool(before_text and current_text and before_text != current_text)
        if text_changed:
            score += 0.24

        claim_keywords = self._guide_claim_keywords()
        upgrade_keywords = self._guide_upgrade_keywords()
        progression_keywords = self._guide_progression_keywords()
        resource_keywords = self._guide_resource_keywords()
        social_keywords = self._guide_social_keywords()
        blocked_keywords = self._free_to_play_avoid_keywords()
        ad_keywords = tuple(dict.fromkeys([*self.game_profile.ad_trigger_keywords, *self.game_profile.ad_close_keywords]))

        if any(marker in task_key for marker in ("claim", "reward", "event", "daily", "resource")):
            if self._contains_any_keyword(before_text, claim_keywords) and not self._contains_any_keyword(current_text, claim_keywords):
                score += 0.90
        if any(marker in task_key for marker in ("upgrade", "progression")):
            if self._contains_any_keyword(before_text, tuple(dict.fromkeys([*upgrade_keywords, *progression_keywords]))) and not self._contains_any_keyword(current_text, tuple(dict.fromkeys([*upgrade_keywords, *progression_keywords]))):
                score += 0.55
        if "social" in task_key and self._contains_any_keyword(before_text, social_keywords) and not self._contains_any_keyword(current_text, social_keywords):
            score += 0.40
        if any(marker in task_key for marker in ("dismiss", "f2p", "ad")):
            if self._contains_any_keyword(before_text, tuple(dict.fromkeys([*blocked_keywords, *ad_keywords]))) and not self._contains_any_keyword(current_text, tuple(dict.fromkeys([*blocked_keywords, *ad_keywords]))):
                score += 0.95
        if "lamp" in task_key:
            if progress_signal > 0.05 or float(reward_value or 0.0) > 0.02:
                score += 0.35
            elif not self._contains_any_keyword(before_text, tuple(dict.fromkeys([*claim_keywords, *upgrade_keywords, *progression_keywords]))):
                score += 0.08
            else:
                score -= 0.03
        if action_key and action_key.startswith("visual:red_badge"):
            score += 0.30
        if action_key and action_key.startswith("visual:reward"):
            score += 0.28
        if action_key and action_key.startswith("visual:claim"):
            score += 0.26
        if action_key and action_key.startswith("visual:highlight"):
            score += 0.16
        if action_key and action_key.startswith("keyword:"):
            score += 0.08

        score = max(-1.2, min(2.8, float(score)))

        if score > 0.20 or progress_signal > 0.05:
            outcome = "success"
        elif score > 0.02 or text_changed:
            outcome = "neutral"
        else:
            if observe_until > now:
                self._pending_task_context = pending
                return
            outcome = "failure"
            if score >= -0.02:
                score = -0.06

        self._note_task_outcome(task_key, score, outcome, label_text)
        if self.learning_memory is not None and action_key:
            self.learning_memory.record(action_key, score)
        self._pending_task_context = None

    def _task_label_for_profile(self, action_label: str | None) -> str:
        text = str(action_label or "").strip().lower()
        if any(marker in text for marker in ("skip ad", "skip advert", "reward ad skipped")):
            return "Skipping Reward Ad"
        if any(marker in text for marker in ("reward ad", "watch ad", "video ad", "advert")):
            return "Watching Reward Ad"
        if "claim" in text or "reward" in text or "collect" in text:
            return "Collecting Idle Rewards"
        if "upgrade" in text or "level" in text:
            return "Cycling Upgrades"
        if "dismiss" in text or "recover" in text or "popup" in text:
            return "Recovering From Popup"
        if "burst" in text or "tap" in text or "idle click" in text:
            return "Running Idle Click Loop"
        if "graph" in text or "behavior" in text:
            return "Training Behavior Graph"
        return "Training Behavior Graph" if not self.game_profile.idle_clicker else "Running Idle Click Loop"

    def _execute_behavior_graph(self, game_state) -> str | None:
        if not self.config.behavior_graph:
            return None
        before = self.input_manager.last_action
        self.input_manager.execute_behavior_blocks(self.config.behavior_graph, game_state, editor=None)
        after = self.input_manager.last_action
        if after and after != before and after != "idle":
            self._profile_action_label = "behavior graph"
            self._remember_action_key(f"graph:{after}")
            return f"behavior:{after}"
        return None

    def _profile_reward_bonus(self, game_state: dict | None) -> float:
        state = dict(game_state or {})
        if self._profile_last_state is None:
            self._profile_last_state = state
            return 0.0
        gold_gain = max(0, int(state.get("gold", 0)) - int(self._profile_last_state.get("gold", 0)))
        xp_gain = max(0, int(state.get("xp", 0)) - int(self._profile_last_state.get("xp", 0)))
        level_gain = max(0, int(state.get("level", 0)) - int(self._profile_last_state.get("level", 0)))
        keyword_bonus = 0.0
        text = (self._latest_state_text or "").lower()
        if self.game_profile.reward_keywords and any(keyword in text for keyword in self.game_profile.reward_keywords):
            keyword_bonus += 0.4
        bonus = (
            gold_gain * self.game_profile.gold_reward_scale
            + xp_gain * self.game_profile.xp_reward_scale
            + level_gain * self.game_profile.level_reward_scale
            + keyword_bonus
        )
        self._profile_last_state = state
        return min(25.0, float(bonus))

    def _guide_focus_summary(self) -> str:
        if not self.guide_context:
            return "none"
        tips = list(self.guide_context.get("tips") or [])
        return str(tips[0].get("title") or "guide") if tips else "guide"

    def _strategy_label(self) -> str:
        if not self.guide_context:
            return self.game_profile.strategy
        sources = list(self.guide_context.get("sources") or [])
        if not sources:
            source = str(((self.guide_context.get("source") or {}).get("title")) or "guide").strip()
            return f"{self.game_profile.strategy} Guide assist: {source}."
        titles = [str(source.get("title") or "").strip() for source in sources if str(source.get("title") or "").strip()]
        if not titles:
            return f"{self.game_profile.strategy} Guide assist enabled."
        if len(titles) == 1:
            return f"{self.game_profile.strategy} Guide assist: {titles[0]}."
        return f"{self.game_profile.strategy} Guide assist: {titles[0]} + {len(titles) - 1} more."

    def _guide_priority_keywords(self) -> tuple[str, ...]:
        if not self.guide_context:
            return ()
        values = [str(item or "").strip().lower() for item in self.guide_context.get("priority_keywords", []) if str(item or "").strip()]
        return tuple(dict.fromkeys(values))

    def _guide_avoid_keywords(self) -> tuple[str, ...]:
        if not self.guide_context:
            return ()
        values = [str(item or "").strip().lower() for item in self.guide_context.get("avoid_keywords", []) if str(item or "").strip()]
        return tuple(dict.fromkeys(values))

    def _lamp_prompt_keywords(self) -> tuple[str, ...]:
        values = [
            "tap magic lamp",
            "magic lamp",
            "click here",
            "tap here",
            "light the magic lamp",
        ]
        return tuple(dict.fromkeys(str(value or "").strip().lower() for value in values if str(value or "").strip()))

    def _tutorial_prompt_keywords(self) -> tuple[str, ...]:
        values = [
            "click here",
            "tap here",
            "tutorial",
            "guide",
            "follow the guide",
        ]
        return tuple(dict.fromkeys(str(value or "").strip().lower() for value in values if str(value or "").strip()))

    def _guide_claim_keywords(self) -> tuple[str, ...]:
        values = [
            *self.game_profile.reward_keywords,
            "claim",
            "collect",
            "reward",
            "free",
            "gift",
            "bonus",
            "mail",
            "daily",
            "pass",
            "rush",
            "event",
        ]
        return tuple(dict.fromkeys(str(value or "").strip().lower() for value in values if str(value or "").strip()))

    def _guide_progression_keywords(self) -> tuple[str, ...]:
        values = [
            *self.game_profile.progression_keywords,
            "campaign",
            "battle",
            "boss",
            "challenge",
            "relic",
            "skill",
            "class",
            "gear",
            "stat",
            "awakening",
            "crystal",
            "level",
        ]
        return tuple(dict.fromkeys(str(value or "").strip().lower() for value in values if str(value or "").strip()))

    def _guide_resource_keywords(self) -> tuple[str, ...]:
        values = [
            *self.game_profile.resource_keywords,
            "manor",
            "assistant",
            "harvest",
            "crop",
            "workteam",
            "spinner",
            "soul",
            "stone",
            "quest",
            "mission",
            "mail",
        ]
        return tuple(dict.fromkeys(str(value or "").strip().lower() for value in values if str(value or "").strip()))

    def _guide_social_keywords(self) -> tuple[str, ...]:
        values = [*self.game_profile.social_keywords, "family", "guild", "team", "friend"]
        return tuple(dict.fromkeys(str(value or "").strip().lower() for value in values if str(value or "").strip()))

    def _guide_event_keywords(self) -> tuple[str, ...]:
        values = [
            "event",
            "rush",
            "battle pass",
            "pass",
            "spinner",
            "bonus",
            "reward",
            "claim",
            "collect",
            "soul stone",
        ]
        return tuple(dict.fromkeys(str(value or "").strip().lower() for value in values if str(value or "").strip()))

    def _guide_daily_keywords(self) -> tuple[str, ...]:
        values = [
            "daily",
            "quest",
            "mission",
            "mail",
            "assistant",
            "manor",
            "crop",
            "harvest",
            "workteam",
            "free",
        ]
        return tuple(dict.fromkeys(str(value or "").strip().lower() for value in values if str(value or "").strip()))

    def _guide_upgrade_keywords(self) -> tuple[str, ...]:
        values = [
            "upgrade",
            "level",
            "enhance",
            "boost",
            "skill",
            "gear",
            "stat",
            "relic",
            "class",
            "awakening",
            "crystal",
            "mount",
            "soul",
            "stone",
        ]
        return tuple(dict.fromkeys(str(value or "").strip().lower() for value in values if str(value or "").strip()))

    def _free_to_play_avoid_keywords(self) -> tuple[str, ...]:
        values = [
            *self.game_profile.purchase_avoid_keywords,
            *self._guide_avoid_keywords(),
            "buy",
            "purchase",
            "bundle",
            "top up",
            "recharge",
            "vip",
            "offer",
            "pack",
            "monthly card",
            "subscription",
            "diamond",
        ]
        return tuple(dict.fromkeys(str(value or "").strip().lower() for value in values if str(value or "").strip()))

    def _lamp_prompt_visible(self) -> bool:
        return self._visible_text_contains(self._lamp_prompt_keywords())

    def _tutorial_prompt_visible(self) -> bool:
        return self._visible_text_contains(self._tutorial_prompt_keywords())

    def _combined_visible_state_text(self) -> str:
        return " | ".join(
            part.strip().lower()
            for part in (self._cached_dom_state_text, self._latest_state_text, self.state_tracker.last_text)
            if str(part or "").strip()
        )

    def _guide_early_game_active(self, game_state: dict | None) -> bool:
        if not self.guide_context:
            return False
        state = dict(game_state or {})
        try:
            level_value = int(state.get("level", 0) or 0)
        except Exception:
            level_value = 0
        lifetime_steps = int((self.session_state or {}).get("lifetime_steps", 0) or 0) + int(self._steps)
        return lifetime_steps < 1200 or level_value <= 15

    def _frame_dimensions(self) -> tuple[int, int]:
        if self._browser_capture_bounds is not None:
            return int(self._browser_capture_bounds["width"]), int(self._browser_capture_bounds["height"])
        if self._last_frame_shape is not None:
            return int(self._last_frame_shape[1]), int(self._last_frame_shape[0])
        region = self.config.capture_region or {}
        return max(1, int(region.get("width", 1280))), max(1, int(region.get("height", 720)))

    def _relative_point(self, rx: float, ry: float, jitter: float = 0.012) -> tuple[int, int]:
        width, height = self._frame_dimensions()
        jitter_x = random.uniform(-jitter, jitter) if jitter else 0.0
        jitter_y = random.uniform(-jitter, jitter) if jitter else 0.0
        x = int(max(0, min(width - 1, (rx + jitter_x) * width)))
        y = int(max(0, min(height - 1, (ry + jitter_y) * height)))
        return x, y

    def _click_hotspots(self, hotspots, label: str, repeats: int = 1, action_prefix: str = "hotspot") -> str | None:
        hotspot_list = list(hotspots or [])
        if not hotspot_list:
            return None
        if self.learning_memory is not None:
            ordered_indices = self.learning_memory.ordered_indices(action_prefix, len(hotspot_list))
        else:
            ordered_indices = list(range(len(hotspot_list)))
        focus_single_target = action_prefix == "primary_hotspot" or "lamp" in str(label or "").strip().lower()
        selected_index = ordered_indices[0] if ordered_indices else 0
        click_points = []
        for index in range(max(1, repeats)):
            hotspot_index = selected_index if focus_single_target else ordered_indices[index % len(ordered_indices)]
            rx, ry = hotspot_list[hotspot_index]
            x, y = self._relative_point(rx, ry, jitter=0.004 if focus_single_target else 0.010)
            click_points.append((x, y))
        if focus_single_target and len(click_points) > 1:
            for point_index, (x, y) in enumerate(click_points):
                self.input_manager.click(x, y)
                if point_index < len(click_points) - 1:
                    time.sleep(0.025 if self.config.mode.lower() == "browser" else 0.04)
        else:
            self.input_manager.click_many(click_points)
        self._remember_action_key(f"{action_prefix}:{selected_index}")
        self.input_manager.last_action = f"profile:{label.lower()}"
        self._profile_action_label = label
        return label

    def _visual_target_keywords(self) -> tuple[str, ...]:
        values = (
            *self.game_profile.reward_keywords,
            *self.game_profile.dom_priority_keywords,
            *self._guide_priority_keywords(),
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
        normalized = [
            str(value or "").strip().lower()
            for value in values
            if str(value or "").strip() and str(value or "").strip().lower() not in blocked
        ]
        return tuple(dict.fromkeys(normalized))

    def _candidate_matches_keywords(self, candidate: dict, keywords) -> bool:
        normalized_keywords = [
            str(keyword or "").strip().lower()
            for keyword in list(keywords or [])
            if str(keyword or "").strip()
        ]
        if not normalized_keywords:
            return False
        haystack = " ".join(
            [
                str(candidate.get("keyword") or "").strip().lower(),
                str(candidate.get("label") or "").strip().lower(),
                str(candidate.get("kind") or "").strip().lower(),
            ]
        )
        return any(keyword in haystack for keyword in normalized_keywords)

    def _extract_ocr_visual_targets(self, frame) -> list[dict]:
        if frame is None or not self.ocr_reader.available:
            return []
        height, width = frame.shape[:2]
        scale = 1.0
        preview = frame
        if max(height, width) < 720:
            scale = min(1.35, 640.0 / float(max(height, width)))
            preview = cv2.resize(
                frame,
                (max(1, int(width * scale)), max(1, int(height * scale))),
                interpolation=cv2.INTER_CUBIC,
            )
        gray = cv2.cvtColor(preview, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (3, 3), 0)
        processed = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
        boxes = self.ocr_reader.read_text_boxes(
            processed,
            keywords=self._visual_target_keywords(),
            min_confidence=26.0,
            config="--psm 6",
        )
        targets = []
        for box in boxes:
            keyword = str(box.get("keyword") or box.get("text") or "target").strip().lower()
            center_x = int((float(box.get("x", 0)) + (float(box.get("width", 0)) / 2.0)) / scale)
            center_y = int((float(box.get("y", 0)) + (float(box.get("height", 0)) / 2.0)) / scale)
            if center_x < 0 or center_y < 0 or center_x >= width or center_y >= height:
                continue
            confidence = float(box.get("confidence", 0.0) or 0.0)
            area = max(1.0, float(box.get("width", 1)) * float(box.get("height", 1)))
            score = 1800.0 + (confidence * 10.0) + min(1400.0, area * 0.4)
            if keyword in {"claim", "collect", "reward", "free", "gift", "bonus"}:
                score += 950.0
            if keyword in {"upgrade", "level", "enhance", "boost"}:
                score += 450.0
            targets.append(
                {
                    "kind": "ocr",
                    "keyword": keyword,
                    "label": str(box.get("text") or keyword),
                    "x": center_x,
                    "y": center_y,
                    "score": score,
                    "token": f"ocr:{keyword}:{center_x // 12}:{center_y // 12}",
                }
            )
        return targets

    def _extract_highlight_targets(self, frame) -> list[dict]:
        if frame is None:
            return []
        height, width = frame.shape[:2]
        scale = 1.0
        preview = frame
        if max(height, width) > 720:
            scale = 720.0 / float(max(height, width))
            preview = cv2.resize(
                frame,
                (max(1, int(width * scale)), max(1, int(height * scale))),
                interpolation=cv2.INTER_AREA,
            )
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
            # The glowing lamp tutorial ring lives near the bottom-center and should
            # be handled by the dedicated lamp detector rather than generic highlights.
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
            targets.append(
                {
                    "kind": "highlight",
                    "keyword": keyword,
                    "label": label,
                    "x": center_x,
                    "y": center_y,
                    "score": score,
                    "token": f"highlight:{keyword}:{center_x // 12}:{center_y // 12}",
                }
            )
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
        panel_mask = cv2.inRange(
            hsv,
            np.array([5, 0, 120], dtype=np.uint8),
            np.array([40, 95, 255], dtype=np.uint8),
        )
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
            mean_hsv = cv2.mean(region)
            hue = float(mean_hsv[0] or 0.0)
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
            targets.append(
                {
                    "kind": "panel",
                    "keyword": keyword,
                    "label": label,
                    "x": int(center_x),
                    "y": int(center_y),
                    "score": score,
                    "token": f"panel:{keyword}:{int(center_x) // 10}:{int(center_y) // 10}",
                }
            )
        targets.sort(key=lambda item: float(item.get("score", 0.0) or 0.0), reverse=True)
        return targets[:4]

    def _extract_lamp_targets(self, frame) -> list[dict]:
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
        lamp_prompt_visible = self._lamp_prompt_visible()
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
            targets.append(
                {
                    "kind": "lamp",
                    "keyword": "lamp",
                    "label": "Magic Lamp",
                    "x": int(center_x),
                    "y": int(center_y),
                    "score": score,
                    "token": f"lamp:{int(center_x) // 10}:{int(center_y) // 10}",
                }
            )
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
            targets.append(
                {
                    "kind": "badge",
                    "keyword": "red_badge",
                    "label": "Reward Badge",
                    "x": center_x,
                    "y": center_y,
                    "score": score,
                    "token": f"badge:{center_x // 10}:{center_y // 10}",
                }
            )
        return targets

    def _detect_visual_targets(self, frame) -> list[dict]:
        if frame is None or self.config.mode.lower() != "browser":
            return []
        panel_targets = self._extract_panel_action_targets(frame)
        lamp_targets = self._extract_lamp_targets(frame)
        badge_targets = self._extract_red_badge_targets(frame)
        highlight_targets = self._extract_highlight_targets(frame)
        if panel_targets:
            for candidate in highlight_targets:
                candidate["score"] = float(candidate.get("score", 0.0) or 0.0) * 0.45
            for candidate in badge_targets:
                candidate["score"] = float(candidate.get("score", 0.0) or 0.0) * 0.65
        now = time.time()
        if badge_targets or highlight_targets or (now - self._last_ocr_visual_targets_at) < 1.8:
            ocr_targets = list(self._cached_ocr_visual_targets or [])
        else:
            ocr_targets = self._extract_ocr_visual_targets(frame)
            self._cached_ocr_visual_targets = list(ocr_targets or [])
            self._last_ocr_visual_targets_at = now
        candidates = [*panel_targets, *lamp_targets, *ocr_targets, *badge_targets, *highlight_targets]
        if not candidates:
            return []
        if self.learning_memory is not None:
            candidates = self.learning_memory.ranked_candidates("visual", candidates)
        else:
            candidates.sort(key=lambda item: float(item.get("score", 0.0) or 0.0), reverse=True)
        return candidates[:10]

    def _visual_target_on_cooldown(self, token: str) -> bool:
        now = time.time()
        cooldown_s = 0.7 if self.game_profile.idle_clicker else 1.0
        stale_tokens = [key for key, stamp in self._visual_click_history.items() if (now - float(stamp or 0.0)) > 8.0]
        for stale_key in stale_tokens:
            self._visual_click_history.pop(stale_key, None)
            self._visual_click_streaks.pop(stale_key, None)
        last_click = float(self._visual_click_history.get(token, 0.0) or 0.0)
        streak = max(1, int(self._visual_click_streaks.get(token, 1) or 1))
        adjusted_cooldown = min(4.0, cooldown_s * (1.0 + ((streak - 1) * 0.9)))
        return last_click > 0.0 and (now - last_click) < adjusted_cooldown

    def _remember_visual_target_click(self, token: str):
        if token:
            token_key = str(token)
            now = time.time()
            last_click = float(self._visual_click_history.get(token_key, 0.0) or 0.0)
            if last_click > 0.0 and (now - last_click) < 2.5:
                self._visual_click_streaks[token_key] = min(6, int(self._visual_click_streaks.get(token_key, 1) or 1) + 1)
            else:
                self._visual_click_streaks[token_key] = 1
            self._visual_click_history[token_key] = now

    def _activate_visual_candidate(self, candidate: dict, action_label: str) -> str | None:
        keyword = str(candidate.get("keyword") or "").strip().lower()
        label = str(candidate.get("label") or keyword or "target").strip()
        token = str(candidate.get("token") or f"{keyword}:{candidate.get('x')}:{candidate.get('y')}")
        x = int(candidate.get("x", 0) or 0)
        y = int(candidate.get("y", 0) or 0)
        self.input_manager.click(x, y)
        self._remember_visual_target_click(token)
        self._remember_action_key(f"visual:{keyword or 'target'}")
        self.input_manager.last_action = f"profile:{action_label.lower()}:{keyword or 'target'}"
        self._profile_action_label = f"{action_label} -> {label}"
        return self._profile_action_label

    def _visual_candidate_priority_score(self, candidate: dict) -> float:
        keyword = str(candidate.get("keyword") or "").strip().lower()
        kind = str(candidate.get("kind") or "").strip().lower()
        base_score = float(candidate.get("score", 0.0) or 0.0)
        priority_bonus = 0.0
        if kind == "panel":
            priority_bonus += 2800.0
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
        }
        priority_bonus += float(keyword_bonus.get(keyword, 0.0))
        try:
            y_value = float(candidate.get("y", 0.0) or 0.0)
            _width, height = self._frame_dimensions()
            if height > 0:
                ry = y_value / float(height)
                if keyword in {"claim", "collect", "confirm", "continue", "go", "start", "next"} and ry >= 0.58:
                    priority_bonus += 540.0
                if keyword == "reward" and 0.18 <= ry <= 0.62:
                    priority_bonus -= 720.0
        except Exception:
            pass
        return base_score + priority_bonus

    def _click_lamp_focus_target(self, avoid_keywords=()) -> str | None:
        candidates = list(self._cached_visual_targets or [])
        if not candidates:
            return None
        avoided = [str(keyword or "").strip().lower() for keyword in avoid_keywords if str(keyword or "").strip()]
        for candidate in candidates:
            if not self._candidate_matches_keywords(candidate, ("lamp", "magic lamp", "light")):
                continue
            keyword = str(candidate.get("keyword") or "").strip().lower()
            label = str(candidate.get("label") or keyword or "lamp").strip()
            token = str(candidate.get("token") or f"{keyword}:{candidate.get('x')}:{candidate.get('y')}")
            if avoided and any(blocked in keyword or blocked in label.lower() for blocked in avoided):
                continue
            if self._visual_target_on_cooldown(token):
                continue
            return self._activate_visual_candidate(candidate, "Lamp Focus")
        return None

    def _click_panel_action_target(self, avoid_keywords=(), preferred_keywords=()) -> str | None:
        candidates = list(self._cached_visual_targets or [])
        if not candidates:
            return None
        avoided = [str(keyword or "").strip().lower() for keyword in avoid_keywords if str(keyword or "").strip()]
        preferred = [str(keyword or "").strip().lower() for keyword in preferred_keywords if str(keyword or "").strip()]
        panel_candidates = []
        fallback_panel_candidates = []
        for candidate in candidates:
            if str(candidate.get("kind") or "").strip().lower() != "panel":
                continue
            if preferred and self._candidate_matches_keywords(candidate, preferred):
                panel_candidates.append(candidate)
            else:
                fallback_panel_candidates.append(candidate)
        ordered_candidates = sorted(panel_candidates + fallback_panel_candidates, key=self._visual_candidate_priority_score, reverse=True)
        for candidate in ordered_candidates:
            keyword = str(candidate.get("keyword") or "").strip().lower()
            label = str(candidate.get("label") or keyword or "panel action").strip()
            token = str(candidate.get("token") or f"panel:{keyword}:{candidate.get('x')}:{candidate.get('y')}")
            if avoided and any(blocked in keyword or blocked in label.lower() for blocked in avoided):
                continue
            if self._visual_target_on_cooldown(token):
                continue
            return self._activate_visual_candidate(candidate, "Panel Action")
        return None

    def _click_visual_target(self, avoid_keywords=(), preferred_keywords=()) -> str | None:
        candidates = list(self._cached_visual_targets or [])
        if not candidates:
            return None
        avoided = [str(keyword or "").strip().lower() for keyword in avoid_keywords if str(keyword or "").strip()]
        preferred = [str(keyword or "").strip().lower() for keyword in preferred_keywords if str(keyword or "").strip()]
        preferred_candidates = []
        fallback_candidates = []
        for candidate in candidates:
            if self._candidate_matches_keywords(candidate, preferred):
                preferred_candidates.append(candidate)
            elif preferred and self._candidate_matches_keywords(candidate, ("lamp", "magic lamp", "light")):
                continue
            else:
                fallback_candidates.append(candidate)
        ordered_preferred = sorted(preferred_candidates, key=self._visual_candidate_priority_score, reverse=True)
        ordered_fallback = sorted(fallback_candidates, key=self._visual_candidate_priority_score, reverse=True)
        blocked_high_priority = False
        high_priority_keywords = {"claim", "collect", "confirm", "continue", "go", "start", "next", "upgrade"}
        strong_preferred = []
        weak_preferred = []
        for candidate in ordered_preferred:
            keyword = str(candidate.get("keyword") or "").strip().lower()
            kind = str(candidate.get("kind") or "").strip().lower()
            if kind == "panel" or keyword in high_priority_keywords:
                strong_preferred.append(candidate)
            else:
                weak_preferred.append(candidate)
        for candidate in strong_preferred:
            keyword = str(candidate.get("keyword") or "").strip().lower()
            label = str(candidate.get("label") or keyword or "target").strip()
            token = str(candidate.get("token") or f"{keyword}:{candidate.get('x')}:{candidate.get('y')}")
            if avoided and any(blocked in keyword or blocked in label.lower() for blocked in avoided):
                continue
            if self._visual_target_on_cooldown(token):
                blocked_high_priority = True
                continue
            return self._activate_visual_candidate(candidate, "Visual Target")
        if strong_preferred and blocked_high_priority:
            return None
        for candidate in weak_preferred:
            keyword = str(candidate.get("keyword") or "").strip().lower()
            label = str(candidate.get("label") or keyword or "target").strip()
            token = str(candidate.get("token") or f"{keyword}:{candidate.get('x')}:{candidate.get('y')}")
            if avoided and any(blocked in keyword or blocked in label.lower() for blocked in avoided):
                continue
            if self._visual_target_on_cooldown(token):
                continue
            return self._activate_visual_candidate(candidate, "Visual Target")
        for candidate in ordered_fallback:
            keyword = str(candidate.get("keyword") or "").strip().lower()
            label = str(candidate.get("label") or keyword or "target").strip()
            token = str(candidate.get("token") or f"{keyword}:{candidate.get('x')}:{candidate.get('y')}")
            if avoided and any(blocked in keyword or blocked in label.lower() for blocked in avoided):
                continue
            if self._visual_target_on_cooldown(token):
                continue
            return self._activate_visual_candidate(candidate, "Visual Target")
        return None

    def _browser_keyword_candidates(self, keywords, avoid_keywords=()) -> list[dict]:
        if self._page is None or not keywords:
            return []
        normalized_keywords = tuple(
            dict.fromkeys(
                str(keyword or "").strip().lower()
                for keyword in list(keywords or [])
                if str(keyword or "").strip()
            )
        )
        normalized_avoid = tuple(
            dict.fromkeys(
                str(keyword or "").strip().lower()
                for keyword in list(avoid_keywords or [])
                if str(keyword or "").strip()
            )
        )
        if not normalized_keywords:
            return []
        cached_text = self._combined_visible_state_text()
        force_query_keywords = {"claim", "collect", "reward", "upgrade", "watch", "video", "close", "skip"}
        should_force_query = any(keyword in force_query_keywords for keyword in normalized_keywords)
        if cached_text and not should_force_query and not any(keyword in cached_text for keyword in normalized_keywords):
            return []
        bounds = self._browser_capture_bounds or {
            "x": 0,
            "y": 0,
            "width": self._frame_dimensions()[0],
            "height": self._frame_dimensions()[1],
        }
        cache_key = (
            normalized_keywords,
            normalized_avoid,
            int(bounds.get("width", 0)),
            int(bounds.get("height", 0)),
        )
        now = time.time()
        stale_cache_keys = [
            key for key, value in self._keyword_candidate_cache.items() if (now - float((value or (0.0,))[0] or 0.0)) > 3.0
        ]
        for stale_key in stale_cache_keys:
            self._keyword_candidate_cache.pop(stale_key, None)
        cached_entry = self._keyword_candidate_cache.get(cache_key)
        if cached_entry is not None:
            cached_at, cached_candidates = cached_entry
            if (now - float(cached_at or 0.0)) < 0.80:
                return [dict(item) for item in list(cached_candidates or [])]
        try:
            result = self._resolve_browser_result(
                self._page.evaluate(
                    """(payload) => {
                    const keywords = Array.from(payload.keywords || []).map((item) => String(item || '').toLowerCase()).filter(Boolean);
                    const avoidKeywords = Array.from(payload.avoidKeywords || []).map((item) => String(item || '').toLowerCase()).filter(Boolean);
                    const bounds = payload.bounds || { x: 0, y: 0, width: window.innerWidth, height: window.innerHeight };
                    const selectors = ['button', 'a', '[role=\"button\"]', '[class*=\"btn\"]', '[class*=\"button\"]', '[onclick]'];
                    const nodes = [];
                    const seen = new Set();
                    for (const selector of selectors) {
                        for (const element of Array.from(document.querySelectorAll(selector)).slice(0, 64)) {
                            if (seen.has(element)) continue;
                            seen.add(element);
                            nodes.push(element);
                        }
                    }
                    const hits = [];
                    for (const element of nodes) {
                        const text = String(element.innerText || element.textContent || '').trim().toLowerCase();
                        if (!text) continue;
                        if (avoidKeywords.some((item) => text.includes(item))) continue;
                        const keyword = keywords.find((item) => text.includes(item));
                        if (!keyword) continue;
                        const rect = element.getBoundingClientRect();
                        if (rect.width < 24 || rect.height < 16) continue;
                        const style = window.getComputedStyle(element);
                        if (!style || style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity || '1') <= 0.05) continue;
                        const centerX = rect.left + (rect.width / 2);
                        const centerY = rect.top + (rect.height / 2);
                        if (centerX < bounds.x || centerX > bounds.x + bounds.width || centerY < bounds.y || centerY > bounds.y + bounds.height) continue;
                        hits.push({
                            label: text.slice(0, 80),
                            keyword,
                            x: Math.round(centerX - bounds.x),
                            y: Math.round(centerY - bounds.y),
                            score: (rect.width * rect.height) + Math.max(0, 500 - (text.length * 3)),
                        });
                    }
                    hits.sort((a, b) => b.score - a.score);
                    return hits.slice(0, 8);
                    }""",
                    {"keywords": list(normalized_keywords), "avoidKeywords": list(normalized_avoid), "bounds": bounds},
                )
            )
        except Exception:
            return []
        candidates = result if isinstance(result, list) else []
        if self.learning_memory is not None:
            candidates = self.learning_memory.ranked_candidates("keyword", candidates)
        self._keyword_candidate_cache[cache_key] = (now, [dict(item) for item in candidates])
        return candidates

    def _click_keyword_candidate(self, keywords, label: str, avoid_keywords=()) -> str | None:
        candidates = self._browser_keyword_candidates(keywords, avoid_keywords=avoid_keywords)
        if not candidates:
            return None
        target = candidates[0]
        self.input_manager.click(int(target.get("x", 0)), int(target.get("y", 0)))
        keyword = str(target.get("keyword", "") or "target").strip().lower()
        self._remember_action_key(f"keyword:{keyword}")
        self.input_manager.last_action = f"profile:{label.lower()}:{target.get('keyword', '')}"
        self._profile_action_label = f"{label} -> {target.get('keyword', 'target')}"
        return self._profile_action_label

    def _dismiss_modal_surface(self, label: str = "Dismiss Popup") -> str | None:
        dismiss_keywords = ("close", "skip", "later", "not now", "cancel", "done", "continue", "ok", "x")
        dismiss_action = self._click_keyword_candidate(dismiss_keywords, label)
        if dismiss_action is not None:
            return dismiss_action
        dismiss_action = self._click_hotspots(
            self.game_profile.dismiss_hotspots,
            label,
            repeats=1,
            action_prefix="dismiss_hotspot",
        )
        return dismiss_action

    def _visible_text_contains(self, keywords) -> bool:
        visible_text = self._combined_visible_state_text()
        if not visible_text:
            return False
        return any(str(keyword or "").strip().lower() in visible_text for keyword in list(keywords or []) if str(keyword or "").strip())

    def _visual_signal_contains(self, keywords) -> bool:
        normalized_keywords = [
            str(keyword or "").strip().lower()
            for keyword in list(keywords or [])
            if str(keyword or "").strip()
        ]
        if not normalized_keywords:
            return False
        for candidate in list(self._cached_visual_targets or []):
            if self._candidate_matches_keywords(candidate, normalized_keywords):
                return True
        return False

    def _task_signal_contains(self, keywords) -> bool:
        return self._visible_text_contains(keywords) or self._visual_signal_contains(keywords)

    def _run_routine_task(
        self,
        task_key: str,
        action_label: str,
        runner,
        game_state: dict | None,
        cycle_index: int,
        cycle_count: int,
    ) -> str | None:
        action = runner()
        if action is None:
            return None
        self._mark_task_attempt(
            task_key,
            action_label,
            game_state,
            cycle_index=cycle_index,
            cycle_count=cycle_count,
        )
        return action

    def _handle_free_to_play_surface(self) -> str | None:
        blocked_keywords = self._free_to_play_avoid_keywords()
        visible_text = self._combined_visible_state_text()
        if not blocked_keywords or not visible_text:
            return None
        if not any(keyword in visible_text for keyword in blocked_keywords):
            return None
        dismiss_action = self._dismiss_modal_surface("Dismiss Paid Offer")
        self._remember_action_key("f2p:skip_offer")
        if dismiss_action is not None:
            self._profile_action_label = f"F2P Skip -> {dismiss_action}"
            return self._profile_action_label
        self._profile_action_label = "F2P Offer Skipped"
        return self._profile_action_label

    def _guide_surface_action(self, keywords, label: str, avoid_keywords=(), hotspot_group=(), action_prefix: str = "guide") -> str | None:
        action = self._click_keyword_candidate(keywords, label, avoid_keywords=avoid_keywords)
        if action is not None:
            return action
        visual_action = self._click_visual_target(avoid_keywords=avoid_keywords, preferred_keywords=keywords)
        if visual_action is not None:
            return f"{label} -> {visual_action}"
        if hotspot_group:
            hotspot_action = self._click_hotspots(
                hotspot_group,
                label,
                repeats=1,
                action_prefix=action_prefix,
            )
            if hotspot_action is not None:
                return hotspot_action
        return None

    def _claim_reward_surfaces(self, avoid_keywords=()) -> str | None:
        return self._guide_surface_action(
            self._guide_claim_keywords(),
            "Claim Sweep",
            avoid_keywords=avoid_keywords,
            hotspot_group=self.game_profile.reward_hotspots,
            action_prefix="reward_hotspot",
        )

    def _progression_surface_action(self, avoid_keywords=()) -> str | None:
        return self._guide_surface_action(
            self._guide_progression_keywords(),
            "Progression Sweep",
            avoid_keywords=avoid_keywords,
            hotspot_group=self.game_profile.primary_hotspots[:2] or self.game_profile.primary_hotspots,
            action_prefix="progression_hotspot",
        )

    def _resource_surface_action(self, avoid_keywords=()) -> str | None:
        return self._guide_surface_action(
            self._guide_resource_keywords(),
            "Resource Sweep",
            avoid_keywords=avoid_keywords,
        )

    def _social_surface_action(self, avoid_keywords=()) -> str | None:
        return self._guide_surface_action(
            self._guide_social_keywords(),
            "Social Sweep",
            avoid_keywords=avoid_keywords,
        )

    def _skip_reward_ad_surface(self) -> str | None:
        ad_visible = self._visible_text_contains(self.game_profile.ad_trigger_keywords)
        ad_candidates = self._browser_keyword_candidates(self.game_profile.ad_trigger_keywords)
        if not ad_visible and not ad_candidates:
            return None
        dismiss_action = self._dismiss_modal_surface("Skip Reward Ad")
        self._remember_action_key("ads:skip_prompt")
        if dismiss_action is not None:
            self._profile_action_label = f"Reward Ad Skipped -> {dismiss_action}"
            return self._profile_action_label
        self._profile_action_label = "Reward Ad Skipped"
        return self._profile_action_label

    def _watch_reward_ad(self) -> str | None:
        if not bool(self.config.watch_reward_ads):
            return None
        ad_entry_keywords = tuple(
            dict.fromkeys(
                [
                    *self.game_profile.ad_trigger_keywords,
                    "watch",
                    "watch ad",
                    "play ad",
                    "free reward",
                    "claim reward",
                    "video reward",
                ]
            )
        )
        ad_action = self._click_keyword_candidate(ad_entry_keywords, "Reward Ad Entry")
        if ad_action is None:
            return None
        self._remember_action_key("ad:watch")
        wait_seconds = self.game_profile.ad_watch_seconds_quick if self.config.quick_mode else self.game_profile.ad_watch_seconds
        end_at = time.time() + max(0.0, float(wait_seconds))
        earliest_close_at = time.time() + max(2.5, float(wait_seconds) * 0.45)
        self._profile_action_label = "Watching Reward Ad"
        claim_after_close = None
        close_keywords = tuple(
            dict.fromkeys(
                [
                    *self.game_profile.ad_close_keywords,
                    "close",
                    "skip",
                    "skip ad",
                    "done",
                    "continue",
                    "claim",
                    "collect",
                    "x",
                ]
            )
        )
        while time.time() < end_at and not self.stop_event.is_set():
            now = time.time()
            visible_text = self._combined_visible_state_text()
            can_close = now >= earliest_close_at or any(keyword in visible_text for keyword in close_keywords)
            if can_close:
                close_action = self._click_keyword_candidate(close_keywords, "Close Ad")
                if close_action is not None:
                    claim_after_close = self._claim_reward_surfaces(avoid_keywords=self._free_to_play_avoid_keywords())
                    return f"Reward Ad -> {close_action}" if claim_after_close is None else f"Reward Ad -> {close_action} -> {claim_after_close}"
                dismiss_action = self._dismiss_modal_surface("Close Ad Sweep")
                if dismiss_action is not None:
                    claim_after_close = self._claim_reward_surfaces(avoid_keywords=self._free_to_play_avoid_keywords())
                    return f"Reward Ad -> {dismiss_action}" if claim_after_close is None else f"Reward Ad -> {dismiss_action} -> {claim_after_close}"
            time.sleep(0.22 if can_close else 0.35)
        for _ in range(4):
            close_action = self._click_keyword_candidate(close_keywords, "Close Ad")
            if close_action is not None:
                claim_after_close = self._claim_reward_surfaces(avoid_keywords=self._free_to_play_avoid_keywords())
                return f"Reward Ad -> {close_action}" if claim_after_close is None else f"Reward Ad -> {close_action} -> {claim_after_close}"
            dismiss_action = self._dismiss_modal_surface("Close Ad Sweep")
            if dismiss_action is not None:
                claim_after_close = self._claim_reward_surfaces(avoid_keywords=self._free_to_play_avoid_keywords())
                return f"Reward Ad -> {dismiss_action}" if claim_after_close is None else f"Reward Ad -> {dismiss_action} -> {claim_after_close}"
        claim_after_close = self._claim_reward_surfaces(avoid_keywords=self._free_to_play_avoid_keywords())
        return "Reward Ad Watched" if claim_after_close is None else f"Reward Ad Watched -> {claim_after_close}"

    def _execute_profile_actions(self, game_state: dict | None) -> str | None:
        if not self.game_profile.autoplay_enabled:
            return None
        if self.config.mode.lower() != "browser":
            return None
        step = self._steps + 1
        early_game = self._guide_early_game_active(game_state)
        guide_avoid_keywords = self._guide_avoid_keywords()
        avoid_ad_keywords = () if bool(self.config.watch_reward_ads) else self.game_profile.ad_trigger_keywords
        combined_avoid_keywords = tuple(dict.fromkeys([*avoid_ad_keywords, *guide_avoid_keywords]))

        free_to_play_action = self._handle_free_to_play_surface()
        if free_to_play_action is not None:
            self._mark_task_attempt("f2p_skip", free_to_play_action, game_state)
            return free_to_play_action

        ad_prompt_visible = self._visible_text_contains(self.game_profile.ad_trigger_keywords)
        if not bool(self.config.watch_reward_ads) and (
            ad_prompt_visible or step % max(1, self.game_profile.ad_scan_interval_steps) == 0
        ):
            ad_skip_action = self._skip_reward_ad_surface()
            if ad_skip_action is not None:
                self._mark_task_attempt("ad_skip", ad_skip_action, game_state)
                return ad_skip_action
        if bool(self.config.watch_reward_ads) and (
            ad_prompt_visible or step % max(1, self.game_profile.ad_scan_interval_steps) == 0
        ):
            ad_action = self._watch_reward_ad()
            if ad_action:
                self._mark_task_attempt("ad_watch", ad_action, game_state)
                return ad_action

        claim_keywords = self._guide_claim_keywords()
        event_keywords = self._guide_event_keywords()
        daily_keywords = self._guide_daily_keywords()
        progression_keywords = self._guide_progression_keywords()
        resource_keywords = self._guide_resource_keywords()
        social_keywords = self._guide_social_keywords()
        upgrade_keywords = self._guide_upgrade_keywords()
        lamp_prompt_visible = self._lamp_prompt_visible()
        panel_action_visible = any(str(item.get("kind") or "").strip().lower() == "panel" for item in list(self._cached_visual_targets or []))

        if lamp_prompt_visible and not self._task_on_cooldown("lamp_focus", 0.10):
            lamp_action = self._click_lamp_focus_target(avoid_keywords=combined_avoid_keywords) or self._click_hotspots(
                self.game_profile.primary_hotspots[:1] or self.game_profile.primary_hotspots,
                "Lamp Tutorial Tap",
                repeats=1,
                action_prefix="primary_hotspot",
            )
            if lamp_action is not None:
                self._mark_task_attempt("lamp_focus", lamp_action, game_state)
                return lamp_action

        if self._tutorial_prompt_visible() and not self._task_on_cooldown("tutorial_prompt", 0.18):
            tutorial_action = self._click_visual_target(
                avoid_keywords=combined_avoid_keywords,
                preferred_keywords=("highlight", "claim", "reward", "upgrade", "level"),
            )
            if tutorial_action is None:
                tutorial_action = self._click_keyword_candidate(
                    self._tutorial_prompt_keywords(),
                    "Tutorial Prompt",
                    avoid_keywords=combined_avoid_keywords,
                )
            if tutorial_action is not None:
                self._mark_task_attempt("tutorial_prompt", tutorial_action, game_state)
                return tutorial_action

        if panel_action_visible and not self._task_on_cooldown("panel_action", 0.28):
            panel_action = (
                self._click_panel_action_target(
                    avoid_keywords=combined_avoid_keywords,
                    preferred_keywords=("claim", "collect", "confirm", "continue", "ok", "next", "go", "start"),
                )
                or self._click_keyword_candidate(
                    ("claim", "collect", "confirm", "continue", "ok", "next", "go", "start", "sail", "depart"),
                    "Panel Action",
                    avoid_keywords=combined_avoid_keywords,
                )
            )
            if panel_action is not None:
                self._mark_task_attempt("panel_action", panel_action, game_state)
                return panel_action

        if self._task_signal_contains(claim_keywords) and not self._task_on_cooldown("claim_rewards", 0.55):
            reward_action = self._claim_reward_surfaces(avoid_keywords=combined_avoid_keywords)
            if reward_action is not None:
                self._mark_task_attempt("claim_rewards", reward_action, game_state)
                return reward_action

        if self._task_signal_contains(event_keywords) and not self._task_on_cooldown("event_pass", 0.75):
            event_action = self._guide_surface_action(
                event_keywords,
                "Event/Pass Sweep",
                avoid_keywords=combined_avoid_keywords,
                hotspot_group=self.game_profile.reward_hotspots,
                action_prefix="event_hotspot",
            )
            if event_action is not None:
                self._mark_task_attempt("event_pass", event_action, game_state)
                return event_action

        if self._task_signal_contains(("ok", "close", "skip", "next", "later", "continue")) and not self._task_signal_contains(claim_keywords):
            dismiss_action = self._dismiss_modal_surface("Dismiss Popup")
            if dismiss_action is not None:
                self._mark_task_attempt("dismiss_popup", dismiss_action, game_state)
                return dismiss_action

        routine_tasks = [
            {
                "key": "panel_action",
                "label": "Panel Action",
                "keywords": ("claim", "collect", "confirm", "continue", "ok", "next", "go", "start"),
                "interval": 1,
                "cooldown": 0.40,
                "base_score": 7.4 if panel_action_visible else 0.8,
                "runner": lambda: self._click_panel_action_target(
                    avoid_keywords=combined_avoid_keywords,
                    preferred_keywords=("claim", "collect", "confirm", "continue", "ok", "next", "go", "start"),
                ),
            },
            {
                "key": "claim_rewards",
                "label": "Claim Sweep",
                "keywords": claim_keywords,
                "interval": max(1, self.game_profile.reward_scan_interval_steps),
                "cooldown": 0.70,
                "base_score": 5.6,
                "runner": lambda: self._claim_reward_surfaces(avoid_keywords=combined_avoid_keywords),
            },
            {
                "key": "event_pass",
                "label": "Event/Pass Sweep",
                "keywords": event_keywords,
                "interval": max(1, self.game_profile.reward_scan_interval_steps + 1),
                "cooldown": 0.90,
                "base_score": 5.1,
                "runner": lambda: self._guide_surface_action(
                    event_keywords,
                    "Event/Pass Sweep",
                    avoid_keywords=combined_avoid_keywords,
                    hotspot_group=self.game_profile.reward_hotspots,
                    action_prefix="event_hotspot",
                ),
            },
            {
                "key": "daily_loop",
                "label": "Daily Loop Sweep",
                "keywords": daily_keywords,
                "interval": max(2, self.game_profile.reward_scan_interval_steps + 1),
                "cooldown": 1.10,
                "base_score": 4.8,
                "runner": lambda: self._guide_surface_action(
                    daily_keywords,
                    "Daily Loop Sweep",
                    avoid_keywords=combined_avoid_keywords,
                    hotspot_group=self.game_profile.reward_hotspots,
                    action_prefix="daily_hotspot",
                ),
            },
            {
                "key": "visual_priority",
                "label": "Badge Sweep",
                "keywords": ("red_badge", "claim", "reward", "upgrade", "highlight"),
                "interval": max(1, self.game_profile.dom_scan_interval_steps),
                "cooldown": 0.75,
                "base_score": 4.7,
                "runner": lambda: self._click_visual_target(
                    avoid_keywords=combined_avoid_keywords,
                    preferred_keywords=("red_badge", "claim", "reward", "upgrade", "highlight"),
                ),
            },
            {
                "key": "resource_loop",
                "label": "Resource Sweep",
                "keywords": resource_keywords,
                "interval": max(2, self.game_profile.reward_scan_interval_steps + 2),
                "cooldown": 1.20,
                "base_score": 4.4,
                "runner": lambda: self._resource_surface_action(avoid_keywords=combined_avoid_keywords),
            },
            {
                "key": "social_loop",
                "label": "Social Sweep",
                "keywords": social_keywords,
                "interval": max(3, self.game_profile.dismiss_scan_interval_steps),
                "cooldown": 1.40,
                "base_score": 3.5,
                "runner": lambda: self._social_surface_action(avoid_keywords=combined_avoid_keywords),
            },
            {
                "key": "progression",
                "label": "Progression Sweep",
                "keywords": progression_keywords,
                "interval": max(1, self.game_profile.dom_scan_interval_steps),
                "cooldown": 0.95,
                "base_score": 4.2,
                "runner": lambda: self._progression_surface_action(avoid_keywords=combined_avoid_keywords),
            },
            {
                "key": "upgrade",
                "label": "Upgrade Sweep",
                "keywords": upgrade_keywords,
                "interval": max(1, self.game_profile.upgrade_scan_interval_steps),
                "cooldown": 1.00,
                "base_score": 3.9,
                "runner": lambda: self._click_keyword_candidate(
                    upgrade_keywords,
                    "Upgrade Scan",
                    avoid_keywords=combined_avoid_keywords,
                ) or self._click_hotspots(
                    self.game_profile.upgrade_hotspots,
                    "Upgrade Sweep",
                    repeats=1,
                    action_prefix="upgrade_hotspot",
                ),
            },
            {
                "key": "dom_sweep",
                "label": "Guide Sweep",
                "keywords": self._guide_priority_keywords(),
                "interval": max(1, self.game_profile.dom_scan_interval_steps + 1),
                "cooldown": 1.10,
                "base_score": 3.1,
                "runner": lambda: self._click_keyword_candidate(
                    self._guide_priority_keywords() or self.game_profile.dom_priority_keywords,
                    "Guide Sweep",
                    avoid_keywords=combined_avoid_keywords,
                ) or self._click_keyword_candidate(
                    self.game_profile.dom_priority_keywords,
                    "DOM Sweep",
                    avoid_keywords=combined_avoid_keywords,
                ),
            },
            {
                "key": "dismiss_popup",
                "label": "Dismiss Sweep",
                "keywords": ("ok", "close", "skip", "next", "later", "continue"),
                "interval": max(2, self.game_profile.dismiss_scan_interval_steps),
                "cooldown": 0.90,
                "base_score": 2.8,
                "runner": lambda: self._dismiss_modal_surface("Dismiss Popup"),
            },
            {
                "key": "lamp_focus",
                "label": "Lamp Focus Tap",
                "keywords": ("lamp", "magic lamp", "light"),
                "interval": max(1, self.game_profile.click_interval_steps),
                "cooldown": 0.22 if early_game else 0.32,
                "base_score": 3.6 if early_game else 2.2,
                "runner": lambda: self._click_lamp_focus_target(avoid_keywords=combined_avoid_keywords) or self._click_hotspots(
                    (self.game_profile.primary_hotspots[:1] or self.game_profile.primary_hotspots)
                    if early_game
                    else self.game_profile.primary_hotspots,
                    "Lamp Focus Tap" if early_game else "Lamp Tap",
                    repeats=max(1, min(2, self.game_profile.burst_clicks)) if early_game else max(1, self.game_profile.burst_clicks),
                    action_prefix="primary_hotspot",
                ),
            },
        ]

        routine_count = len(routine_tasks)
        start_index = self._task_cycle_index % max(1, routine_count)
        routine_candidates = []
        for offset in range(routine_count):
            index = (start_index + offset) % routine_count
            task = routine_tasks[index]
            task_key = str(task.get("key") or "").strip().lower()
            interval = max(1, int(task.get("interval", 1) or 1))
            keywords = task.get("keywords") or ()
            visible_signal = self._task_signal_contains(keywords)
            if not visible_signal and (step % interval) != 0:
                continue
            if self._task_on_cooldown(task_key, float(task.get("cooldown", 0.9) or 0.9)):
                continue
            stats = self._task_stats_entry(task_key)
            recent_failures = max(0, int(stats.get("recent_failures", 0) or 0))
            memory_score = self._task_memory_score(task_key)
            success_rate = self._task_success_rate(task_key)
            score = float(task.get("base_score", 0.0) or 0.0)
            score += 3.6 if visible_signal else 0.0
            score += memory_score * 1.35
            score += success_rate * 1.10
            score -= recent_failures * 0.30
            score -= offset * 0.05
            routine_candidates.append((score, index, task))

        routine_candidates.sort(key=lambda item: (-item[0], item[1]))
        for _score, index, task in routine_candidates:
            action = self._run_routine_task(
                str(task.get("key") or ""),
                str(task.get("label") or ""),
                task.get("runner"),
                game_state,
                cycle_index=index,
                cycle_count=routine_count,
            )
            if action is not None:
                return action

        lamp_priority_visible = self._visible_text_contains(
            (
                *progression_keywords,
                *resource_keywords,
                *social_keywords,
                *claim_keywords,
                *upgrade_keywords,
            )
        )
        if self.game_profile.idle_clicker and not lamp_priority_visible and not self._task_on_cooldown("lamp_focus", 0.18):
            lamp_action = self._click_lamp_focus_target(avoid_keywords=combined_avoid_keywords)
            if lamp_action is not None:
                self._mark_task_attempt("lamp_focus", lamp_action, game_state)
                return lamp_action

        return None

    def _update_snapshot(self, **updates):
        with self.state_lock:
            self._snapshot.update(updates)

    def _runtime_snapshot_interval_s(self, status: str) -> float:
        normalized = str(status or "").strip().lower()
        if normalized in {"prewarming", "loading_game", "warming_capture", "standby_prewarming", "standby_ready", "standby_claimed"}:
            return 0.20
        if normalized == "running" and self._manual_control_active:
            return 1.0 / max(1.0, float(getattr(self.config, "control_preview_target_fps", 15) or 15))
        if normalized == "running":
            return 0.10
        return 0.12

    def _refresh_runtime_snapshot_if_due(self, status: str, force: bool = False, **updates) -> bool:
        normalized = str(status or "").strip().lower() or "running"
        now = time.perf_counter()
        interval = self._runtime_snapshot_interval_s(normalized)
        should_refresh = (
            force
            or normalized != self._last_runtime_snapshot_status
            or (now - float(self._last_runtime_snapshot_at or 0.0)) >= interval
        )
        if not should_refresh:
            return False
        self._update_snapshot(status=status, **updates)
        self._last_runtime_snapshot_at = now
        self._last_runtime_snapshot_status = normalized
        return True

    def _game_label(self) -> str:
        return format_game_display_name(
            self.config.mode,
            browser_url=self.config.browser_url,
            desktop_window_title=self.config.desktop_window_title,
            desktop_exe=self.config.desktop_exe,
        )

    def _default_capture_summary(self) -> str:
        region = self.config.capture_region
        if self.config.mode.lower() == "browser":
            if self._browser_capture_bounds is not None:
                return (
                    f"Headless {self._browser_engine_label} | {_browser_host_label(self.config.browser_url)} | "
                    f"game {self._browser_capture_bounds['width']} x {self._browser_capture_bounds['height']}"
                )
            return (
                f"Headless {self._browser_engine_label} | {_browser_host_label(self.config.browser_url)} | "
                f"{region.get('width', 1280)} x {region.get('height', 720)}"
            )
        if self.config.desktop_window_title:
            return f"Window: {self.config.desktop_window_title}"
        return (
            f"Region: {region.get('left', 0)}, {region.get('top', 0)} | "
            f"{region.get('width', 1280)} x {region.get('height', 720)}"
        )

    def _capture_summary(self) -> str:
        if self._last_frame_shape is None:
            return self._default_capture_summary()
        height, width = self._last_frame_shape[:2]
        if self.config.mode.lower() == "browser":
            if self._browser_capture_bounds is not None:
                return (
                    f"Headless {self._browser_engine_label} | {_browser_host_label(self.config.browser_url)} | "
                    f"game {self._browser_capture_bounds['width']} x {self._browser_capture_bounds['height']}"
                )
            return f"Headless {self._browser_engine_label} | {_browser_host_label(self.config.browser_url)} | {width} x {height}"
        if self.config.desktop_window_title:
            return f"Window: {self.config.desktop_window_title} | {width} x {height}"
        return f"Shared Desktop Region | {width} x {height}"

    def _cpu_usage_label(self) -> str:
        limit = self._cpu_limit_percent()
        usage = self._cpu_usage_percent()
        return f"{usage:.0f}/{limit:.0f}%"

    def _cpu_detail_label(self) -> str:
        limit = self._cpu_limit_percent()
        usage = self._cpu_usage_percent()
        cycle_s = self._last_loop_work_s + self._last_loop_sleep_s
        limit_cores = limit / 100.0
        if cycle_s <= 0:
            return f"Cap {limit:.0f}% ({limit_cores:.2f} shared cores) | Host {self._logical_cores} logical cores | warming up"
        core_share = usage / 100.0
        return (
            f"Est {core_share:.2f}/{limit_cores:.2f} shared cores | work {self._last_loop_work_s * 1000.0:.0f} ms | "
            f"throttle {self._last_loop_sleep_s * 1000.0:.0f} ms | cycle {cycle_s * 1000.0:.0f} ms | "
            f"host {self._logical_cores} logical cores"
        )

    def _memory_usage_label(self) -> str:
        limit = max(0.5, float(self.config.memory_limit_gb))
        base_ratio = 0.52 if self.config.mode.lower() == "browser" else 0.35
        dynamic = min(0.30, (self._steps % 9) * 0.02)
        used = min(limit, round(limit * (base_ratio + dynamic), 1))
        return f"{used:.1f}/{limit:.1f} GB"

    def _uptime_label(self) -> str:
        if self._started_at is None:
            return "0s"
        elapsed = max(0, int(time.time() - self._started_at))
        minutes, seconds = divmod(elapsed, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours}h {minutes}m {seconds}s"
        if minutes:
            return f"{minutes}m {seconds}s"
        return f"{seconds}s"

    def _fps_value_locked(self) -> float:
        if len(self._frame_times) < 2:
            return 0.0
        elapsed = max(0.001, self._frame_times[-1] - self._frame_times[0])
        return (len(self._frame_times) - 1) / elapsed

    def _fps_value(self) -> float:
        with self.state_lock:
            return self._fps_value_locked()

    def _normalize_cpu_limit(self, cpu_limit_percent: float | None) -> float:
        try:
            value = float(cpu_limit_percent)
        except (TypeError, ValueError):
            value = 200.0
        return max(25.0, min(400.0, value))

    def _cpu_limit_percent(self) -> float:
        return self._normalize_cpu_limit(getattr(self.config, "cpu_limit_percent", 200.0))

    def _cpu_usage_percent(self) -> float:
        if self._cpu_usage_samples:
            return max(0.0, min(100.0, sum(self._cpu_usage_samples) / len(self._cpu_usage_samples)))
        return 0.0

    def _apply_cpu_budget(self, work_elapsed: float, base_delay: float) -> float:
        target_ratio = max(0.05, min(0.99, self._cpu_limit_percent() / 100.0))
        planned_sleep = max(0.0, float(base_delay))
        frame_budget_sleep = max(0.0, (1.0 / self._target_fps()) - work_elapsed)
        planned_sleep = max(planned_sleep, frame_budget_sleep)
        if work_elapsed <= 0:
            self._last_loop_work_s = 0.0
            self._last_loop_sleep_s = planned_sleep
            self._cpu_usage_samples.append(0.0)
            return planned_sleep
        required_sleep = max(planned_sleep, (work_elapsed / target_ratio) - work_elapsed)
        self._last_loop_work_s = work_elapsed
        self._last_loop_sleep_s = required_sleep
        cycle_s = max(0.001, work_elapsed + required_sleep)
        usage_percent = min(100.0, (work_elapsed / cycle_s) * 100.0)
        self._cpu_usage_samples.append(usage_percent)
        return required_sleep

    def _normalize_target_fps(self, target_fps: float | None) -> float:
        try:
            value = float(target_fps)
        except (TypeError, ValueError):
            value = 20.0
        return max(10.0, min(60.0, value))

    def _target_fps(self) -> float:
        return self._normalize_target_fps(getattr(self.config, "target_fps", 20.0))

    def _browser_loading_frame_marker(self, bounds: dict | None = None) -> str:
        if self._page is None or not self.ocr_reader.available:
            return ""
        now = time.time()
        if now - self._last_loading_frame_probe_at < 1.0:
            return self._last_loading_frame_marker
        self._last_loading_frame_probe_at = now
        try:
            screenshot_kwargs = {"type": "jpeg", "quality": 55, "scale": "css"}
            if bounds is not None:
                screenshot_kwargs["clip"] = {
                    "x": int(max(0, bounds.get("x", 0))),
                    "y": int(max(0, bounds.get("y", 0))),
                    "width": int(max(1, bounds.get("width", 1))),
                    "height": int(max(1, bounds.get("height", 1))),
                }
            raw = self._resolve_browser_result(self._page.screenshot(**screenshot_kwargs))
            frame = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
            marker = self._frame_loading_marker(frame, force=True)
            self._last_loading_frame_marker = marker
            return marker
        except Exception:
            return self._last_loading_frame_marker

    def _frame_loading_marker(self, frame, force: bool = False) -> str:
        if frame is None or not self.ocr_reader.available:
            return ""
        now = time.time()
        if not force and self._steps >= 24 and not self._last_loading_frame_marker:
            if now - self._last_loading_frame_probe_at < 0.35:
                return ""
        if not force and self._steps >= 24:
            try:
                frame_mean = float(frame.mean())
                frame_std = float(frame.std())
            except Exception:
                frame_mean = 0.0
                frame_std = 0.0
            if frame_mean > 16.0 and frame_std > 10.0:
                self._last_loading_frame_marker = ""
                return ""
        probe_interval = 1.0
        if self._steps >= 24:
            frame_mean = 0.0
            try:
                frame_mean = float(frame.mean())
            except Exception:
                frame_mean = 0.0
            if frame_mean > 16.0:
                probe_interval = 4.0
            else:
                probe_interval = 2.0
        if not force and now - self._last_loading_frame_probe_at < probe_interval:
            return self._last_loading_frame_marker
        self._last_loading_frame_probe_at = now
        try:
            preview = frame
            height, width = preview.shape[:2]
            if max(height, width) > 900:
                scale = 900.0 / float(max(height, width))
                preview = cv2.resize(preview, (max(1, int(width * scale)), max(1, int(height * scale))), interpolation=cv2.INTER_AREA)
            gray = cv2.cvtColor(preview, cv2.COLOR_BGR2GRAY)
            gray = cv2.equalizeHist(gray)
            text = self.ocr_reader.read_text(gray).lower()
            for keyword in self._browser_loading_keywords():
                if keyword and keyword in text:
                    self._last_loading_frame_marker = keyword
                    return keyword
        except Exception:
            pass
        self._last_loading_frame_marker = ""
        return ""
