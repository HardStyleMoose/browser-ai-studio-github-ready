from __future__ import annotations

import base64
import importlib.util
import json
import os
import threading
import time
from pathlib import Path
from queue import Empty, SimpleQueue
from urllib.parse import urlparse

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QGuiApplication, QIcon, QImage, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QCheckBox,
    QSpinBox,
    QDoubleSpinBox,
)

from automation.game_profiles import format_game_display_name, resolve_game_profile
from core.legal_docs import legal_doc_label, legal_doc_path, legal_doc_text, legal_doc_version
from ui.click_overlay import ClickOverlay
from ui.theme_presets import THEMES, build_app_stylesheet


_CV2_MODULE = None
_NUMPY_MODULE = None


def _cv2():
    global _CV2_MODULE
    if _CV2_MODULE is None:
        import cv2 as cv2_module

        _CV2_MODULE = cv2_module
    return _CV2_MODULE


def _np():
    global _NUMPY_MODULE
    if _NUMPY_MODULE is None:
        import numpy as numpy_module

        _NUMPY_MODULE = numpy_module
    return _NUMPY_MODULE


def _chart_types():
    from PySide6.QtCharts import QChart, QChartView, QLineSeries, QValueAxis

    return QChart, QChartView, QLineSeries, QValueAxis


def _behavior_editor_type():
    from ui.behavior_editor import BehaviorEditor

    return BehaviorEditor


def _guide_coach_widget_type():
    from ui.guide_coach_widget import GuideCoachWidget

    return GuideCoachWidget


def _provider_hub_widget_type():
    from ui.provider_hub_widget import ProviderHubWidget

    return ProviderHubWidget


def _n8n_hub_widget_type():
    from ui.n8n_hub_widget import N8nHubWidget

    return N8nHubWidget


def _get_window_region(title: str):
    from automation.game_launcher import get_window_region

    return get_window_region(title)


def _list_open_windows():
    from automation.game_launcher import list_open_windows

    return list_open_windows()


def _default_bundle_name(profile_key: str, game_key: str, worker_id: str):
    from automation.worker_bundle_io import default_bundle_name

    return default_bundle_name(profile_key, game_key, worker_id)


def _export_worker_bundle(*args, **kwargs):
    from automation.worker_bundle_io import export_worker_bundle

    return export_worker_bundle(*args, **kwargs)


def _import_worker_bundle(*args, **kwargs):
    from automation.worker_bundle_io import import_worker_bundle

    return import_worker_bundle(*args, **kwargs)


def _get_host_gpu_info():
    from core.gpu_telemetry import get_host_gpu_info

    return get_host_gpu_info()


def _debug_overlay_window_type():
    from ui.debug_overlay import DebugOverlayWindow

    return DebugOverlayWindow


def _region_selector_overlay_type():
    from ui.region_selector_overlay import RegionSelectorOverlay

    return RegionSelectorOverlay


class ScrollGuardComboBox(QComboBox):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def wheelEvent(self, event):
        if self.hasFocus():
            super().wheelEvent(event)
            return
        event.ignore()


class ScrollGuardSpinBox(QSpinBox):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def wheelEvent(self, event):
        if self.hasFocus():
            super().wheelEvent(event)
            return
        event.ignore()


class ScrollGuardDoubleSpinBox(QDoubleSpinBox):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def wheelEvent(self, event):
        if self.hasFocus():
            super().wheelEvent(event)
            return
        event.ignore()


class InteractiveWorkerFrameLabel(QLabel):
    def __init__(self, on_click=None, on_key=None, parent=None):
        super().__init__(parent)
        self.on_click = on_click
        self.on_key = on_key
        self._frame_shape = None
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def set_frame_shape(self, frame):
        if frame is None:
            self._frame_shape = None
            return
        if hasattr(frame, "shape"):
            self._frame_shape = tuple(frame.shape[:2])
            return
        if isinstance(frame, dict):
            width = int(frame.get("width", 0) or 0)
            height = int(frame.get("height", 0) or 0)
        elif isinstance(frame, (tuple, list)) and len(frame) >= 2:
            if len(frame) >= 2 and frame[0] and frame[1]:
                first = int(frame[0] or 0)
                second = int(frame[1] or 0)
                width, height = second, first
            else:
                width = 0
                height = 0
        else:
            width = 0
            height = 0
        self._frame_shape = (height, width) if width > 0 and height > 0 else None

    def _map_position_to_frame(self, position):
        if not self._frame_shape:
            return None
        frame_height, frame_width = self._frame_shape[:2]
        label_width = max(1, self.width())
        label_height = max(1, self.height())
        scale = min(label_width / max(1, frame_width), label_height / max(1, frame_height))
        drawn_width = frame_width * scale
        drawn_height = frame_height * scale
        offset_x = (label_width - drawn_width) / 2.0
        offset_y = (label_height - drawn_height) / 2.0
        x = float(position.x()) - offset_x
        y = float(position.y()) - offset_y
        if x < 0 or y < 0 or x > drawn_width or y > drawn_height:
            return None
        frame_x = int(max(0, min(frame_width - 1, x / max(0.001, scale))))
        frame_y = int(max(0, min(frame_height - 1, y / max(0.001, scale))))
        return frame_x, frame_y

    def _translate_key(self, event) -> str:
        key = int(event.key())
        key_map = {
            int(Qt.Key.Key_Up): "ArrowUp",
            int(Qt.Key.Key_Down): "ArrowDown",
            int(Qt.Key.Key_Left): "ArrowLeft",
            int(Qt.Key.Key_Right): "ArrowRight",
            int(Qt.Key.Key_Space): "Space",
            int(Qt.Key.Key_Return): "Enter",
            int(Qt.Key.Key_Enter): "Enter",
            int(Qt.Key.Key_Escape): "Escape",
            int(Qt.Key.Key_Tab): "Tab",
            int(Qt.Key.Key_Backspace): "Backspace",
            int(Qt.Key.Key_Delete): "Delete",
        }
        if key in key_map:
            return key_map[key]
        text = str(event.text() or "").strip()
        return text

    def mousePressEvent(self, event):
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        mapped = self._map_position_to_frame(event.position())
        if mapped is not None and callable(self.on_click):
            button = "right" if event.button() == Qt.MouseButton.RightButton else "left"
            if event.button() in {Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton}:
                self.on_click(mapped[0], mapped[1], button)
                event.accept()
                return
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        key_text = self._translate_key(event)
        if key_text and callable(self.on_key):
            self.on_key(key_text)
            event.accept()
            return
        super().keyPressEvent(event)


class WorkerPreviewWindow(QDialog):
    def __init__(self, worker_id: str, icon: QIcon | None = None, on_close=None, parent=None):
        super().__init__(parent)
        self.worker_id = worker_id
        self.on_close = on_close
        self.preview_tier = "preview"
        self._current_pixmap = None
        self._current_scaled_pixmap = None
        self._last_capture_token = None
        self._auto_resizing = False
        self._user_resized = False
        self._auto_sized_shape = None
        self._source_frame_shape = None
        self._logical_frame_size = None

        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setModal(False)
        self.setWindowTitle(f"{worker_id} Live Preview")
        if icon is not None and not icon.isNull():
            self.setWindowIcon(icon)
        self.setSizeGripEnabled(True)
        self.resize(720, 520)
        self.setMinimumSize(420, 300)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        hero = QFrame()
        hero.setObjectName("heroCard")
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(14, 14, 14, 14)
        hero_layout.setSpacing(8)

        self.title_label = QLabel(f"{worker_id} Live Preview")
        self.title_label.setObjectName("sectionTitle")
        self.subtitle_label = QLabel("Waiting for the worker to capture its first frame.")
        self.subtitle_label.setObjectName("mutedLabel")
        self.subtitle_label.setWordWrap(True)
        hero_layout.addWidget(self.title_label)
        hero_layout.addWidget(self.subtitle_label)

        controls_row = QHBoxLayout()
        controls_row.setSpacing(8)
        self.show_fps_checkbox = QCheckBox("Show FPS")
        self.show_fps_checkbox.setChecked(True)
        self.show_fps_checkbox.toggled.connect(self._sync_fps_visibility)
        controls_row.addWidget(self.show_fps_checkbox)
        self.fps_value_label = QLabel("0.0 FPS")
        self.fps_value_label.setObjectName("statusHeader")
        controls_row.addWidget(self.fps_value_label)
        controls_row.addStretch()
        hero_layout.addLayout(controls_row)
        root.addWidget(hero)

        self.preview_label = QLabel("Live preview will appear here.")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumSize(320, 200)
        self.preview_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.preview_label.setObjectName("mutedLabel")
        root.addWidget(self.preview_label, stretch=1)

        info_card = QFrame()
        info_card.setObjectName("heroCard")
        info_layout = QVBoxLayout(info_card)
        info_layout.setContentsMargins(14, 12, 14, 12)
        info_layout.setSpacing(6)
        self.status_line = QLabel("Status: waiting")
        self.status_line.setWordWrap(True)
        self.detail_line = QLabel("Details: no worker snapshot yet.")
        self.detail_line.setObjectName("mutedLabel")
        self.detail_line.setWordWrap(True)
        self.capture_line = QLabel("Capture: unavailable")
        self.capture_line.setObjectName("mutedLabel")
        self.capture_line.setWordWrap(True)
        info_layout.addWidget(self.status_line)
        info_layout.addWidget(self.detail_line)
        info_layout.addWidget(self.capture_line)
        root.addWidget(info_card)
        self._sync_fps_visibility()

    def _sync_fps_visibility(self):
        self.fps_value_label.setVisible(self.show_fps_checkbox.isChecked())

    def current_capture_token(self):
        return self._last_capture_token

    def preview_timer_interval_ms(self) -> int:
        return 100

    def update_preview(self, payload: dict | None, worker_record: dict | None = None):
        payload = payload or {}
        snapshot = dict(payload.get("snapshot") or {})
        worker_record = worker_record or {}

        status = snapshot.get("status") or worker_record.get("status") or "offline"
        task = snapshot.get("task") or worker_record.get("task") or "Waiting For Frames"
        game = snapshot.get("game") or worker_record.get("game") or "Unknown Game"
        profile = snapshot.get("profile") or worker_record.get("profile") or "Unknown Profile"
        strategy = snapshot.get("strategy") or worker_record.get("strategy") or "No strategy details yet"
        mode = snapshot.get("mode") or worker_record.get("mode") or "Unknown Mode"
        ads = snapshot.get("ads") or worker_record.get("ads") or "Skip Reward Ads"
        learning = snapshot.get("learning") or worker_record.get("learning") or "enabled"
        progress = snapshot.get("progress") or worker_record.get("progress") or "No progress yet"
        capture = snapshot.get("capture") or worker_record.get("capture") or "Capture unavailable"
        cpu = snapshot.get("cpu") or worker_record.get("cpu") or "N/A"
        last_error = snapshot.get("last_error") or ""
        fps_value = float(payload.get("fps") or 0.0)

        self.subtitle_label.setText(f"{game} | {profile} | {mode} | {str(status).title()}")
        self.status_line.setText(f"Task: {task} | {progress}")
        if last_error:
            self.detail_line.setText(f"Last Error: {last_error}")
        else:
            self.detail_line.setText(f"Strategy: {strategy} | CPU: {cpu} | Ads: {ads} | Learning: {learning}")
        self.capture_line.setText(f"Capture: {capture}")
        self.fps_value_label.setText(f"{fps_value:.1f} FPS")

        frame = payload.get("frame")
        capture_token = payload.get("captured_at")
        source_size = self._coerce_size_payload(payload.get("source_size"))
        logical_size = self._coerce_size_payload(payload.get("logical_size")) or source_size
        if frame is not None and capture_token != self._last_capture_token:
            self._last_capture_token = capture_token
            self._source_frame_shape = source_size or self._coerce_size_payload(frame)
            self._logical_frame_size = logical_size or self._source_frame_shape
            self._update_cached_pixmap(frame)
            self._auto_fit_to_surface(self._logical_frame_size)
            self._render_cached_pixmap()
        elif frame is None and self._current_pixmap is None:
            self.preview_label.setText("Worker is online, but no preview frame is available yet.")

    def _coerce_size_payload(self, payload):
        if payload is None:
            return None
        if isinstance(payload, dict):
            width = int(payload.get("width", 0) or 0)
            height = int(payload.get("height", 0) or 0)
            return (width, height) if width > 0 and height > 0 else None
        if hasattr(payload, "shape"):
            height, width = payload.shape[:2]
            return (int(width), int(height))
        if isinstance(payload, (tuple, list)) and len(payload) >= 2:
            first = int(payload[0] or 0)
            second = int(payload[1] or 0)
            if first > 0 and second > 0:
                return (second, first)
        return None

    def _auto_fit_to_surface(self, surface_size):
        if surface_size is None:
            return
        frame_width, frame_height = surface_size
        shape = (frame_width, frame_height)
        if self._user_resized and self._auto_sized_shape == shape:
            return
        if self._user_resized and self._auto_sized_shape is not None:
            return
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            return
        geometry = screen.availableGeometry()
        preview_w = max(1, self.preview_label.width())
        preview_h = max(1, self.preview_label.height())
        chrome_w = max(150, self.width() - preview_w)
        chrome_h = max(180, self.height() - preview_h)
        max_width = max(self.minimumWidth(), int(geometry.width() * 0.82))
        max_height = max(self.minimumHeight(), int(geometry.height() * 0.84))
        scale = min(
            1.0,
            max(0.2, (max_width - chrome_w) / max(1, frame_width)),
            max(0.2, (max_height - chrome_h) / max(1, frame_height)),
        )
        target_width = max(self.minimumWidth(), int(frame_width * scale) + chrome_w)
        target_height = max(self.minimumHeight(), int(frame_height * scale) + chrome_h)
        if abs(target_width - self.width()) < 18 and abs(target_height - self.height()) < 18:
            self._auto_sized_shape = shape
            return
        self._auto_resizing = True
        try:
            self.resize(target_width, target_height)
            self._auto_sized_shape = shape
        finally:
            self._auto_resizing = False

    def _update_cached_pixmap(self, frame):
        if frame is None:
            return
        cv2 = _cv2()
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        height, width, channels = rgb.shape
        image = QImage(rgb.data, width, height, channels * width, QImage.Format_RGB888).copy()
        self._current_pixmap = QPixmap.fromImage(image)
        self._current_scaled_pixmap = None
        self.preview_label.setText("")
        if hasattr(self.preview_label, "set_frame_shape"):
            self.preview_label.set_frame_shape(
                {
                    "width": int((self._source_frame_shape or self._coerce_size_payload(frame) or (0, 0))[0]),
                    "height": int((self._source_frame_shape or self._coerce_size_payload(frame) or (0, 0))[1]),
                }
            )

    def _render_cached_pixmap(self):
        if self._current_pixmap is None:
            return
        scaled = self._current_pixmap.scaled(
            self.preview_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )
        self._current_scaled_pixmap = scaled
        self.preview_label.setPixmap(scaled)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._current_pixmap is not None and self._auto_sized_shape is not None and not self._auto_resizing:
            self._user_resized = True
        if self._current_pixmap is not None:
            self._render_cached_pixmap()

    def closeEvent(self, event):
        if callable(self.on_close):
            self.on_close(self.worker_id)
        super().closeEvent(event)


class WorkerControlWindow(WorkerPreviewWindow):
    def __init__(
        self,
        worker_id: str,
        icon: QIcon | None = None,
        on_close=None,
        on_click=None,
        on_key=None,
        on_capture_dom=None,
        on_save_evidence=None,
        parent=None,
    ):
        super().__init__(worker_id, icon=icon, on_close=on_close, parent=parent)
        self.preview_tier = "control"
        self.setWindowTitle(f"{worker_id} Interactive Control")
        self.title_label.setText(f"{worker_id} Interactive Control")
        self.subtitle_label.setText("Autoplay pauses while this window is open. Click inside the frame or use the keyboard to control the worker.")
        self.on_capture_dom = on_capture_dom
        self.on_save_evidence = on_save_evidence

        interactive_label = InteractiveWorkerFrameLabel(on_click=on_click, on_key=on_key, parent=self)
        interactive_label.setAlignment(self.preview_label.alignment())
        interactive_label.setMinimumSize(self.preview_label.minimumSize())
        interactive_label.setSizePolicy(self.preview_label.sizePolicy())
        interactive_label.setObjectName(self.preview_label.objectName())
        interactive_label.setText("Interactive control will appear here.")
        layout = self.layout()
        layout.replaceWidget(self.preview_label, interactive_label)
        self.preview_label.deleteLater()
        self.preview_label = interactive_label

        self.control_hint_label = QLabel("Autoplay is paused. Left click inside the frame to play, right click for alternate input, and press keys while the frame is focused.")
        self.control_hint_label.setObjectName("mutedLabel")
        self.control_hint_label.setWordWrap(True)
        layout.insertWidget(1, self.control_hint_label)
        controls_row = QHBoxLayout()
        snapshot_button = QPushButton("Snapshot DOM")
        snapshot_button.clicked.connect(self._capture_dom_snapshot)
        advanced_button = QPushButton("Save Advanced")
        advanced_button.clicked.connect(lambda: self._save_evidence("advanced"))
        neutral_button = QPushButton("Save Neutral")
        neutral_button.clicked.connect(lambda: self._save_evidence("neutral"))
        wrong_button = QPushButton("Save Wrong Target")
        wrong_button.clicked.connect(lambda: self._save_evidence("wrong_target"))
        for widget in [snapshot_button, advanced_button, neutral_button, wrong_button]:
            controls_row.addWidget(widget)
        controls_row.addStretch()
        layout.insertLayout(2, controls_row)
        self.manual_status_label = QLabel("Manual control pauses autoplay. DOM snapshots and evidence capture stay safe while the worker waits for your input.")
        self.manual_status_label.setObjectName("mutedLabel")
        self.manual_status_label.setWordWrap(True)
        layout.insertWidget(3, self.manual_status_label)

    def update_preview(self, payload: dict | None, worker_record: dict | None = None):
        super().update_preview(payload, worker_record)
        snapshot = dict((payload or {}).get("snapshot") or {})
        last_error = str(snapshot.get("last_error") or "").strip()
        if not last_error:
            self.detail_line.setText("Autoplay paused while this window is open. You can click and type directly into the worker session.")

    def preview_timer_interval_ms(self) -> int:
        return 66

    def set_manual_status(self, message: str):
        self.manual_status_label.setText(str(message or "").strip() or "Manual control pauses autoplay. DOM snapshots and evidence capture stay safe while the worker waits for your input.")

    def _capture_dom_snapshot(self):
        if callable(self.on_capture_dom):
            self.on_capture_dom(self.worker_id)

    def _save_evidence(self, outcome: str):
        if callable(self.on_save_evidence):
            self.on_save_evidence(self.worker_id, outcome)


class MainWindow(QMainWindow):
    PAGE_ORDER = ["Training", "Model Dashboard", "Behavior Editor", "Cluster", "Vision Lab", "Guide Coach", "Provider Hub", "n8n Hub", "Plugins", "Settings"]
    THEME_DEFINITIONS = THEMES
    APP_NAME = "BrowerAI Studio Labs"
    AUTHOR_NAME = "RicketyWrecked"
    MAX_CLUSTER_WORKERS = 10

    def __init__(self, input_manager=None, ppo_trainer=None, plugin_manager=None, event_bus=None, pipeline_controller=None, config=None, parent=None):
        super().__init__(parent)
        self.input_manager = input_manager
        self.ppo_trainer = ppo_trainer
        self.plugin_manager = plugin_manager
        self.event_bus = event_bus
        self.pipeline_controller = pipeline_controller
        self.config = config

        self.project_root = Path(__file__).resolve().parent.parent
        self.avatar_path = self.project_root / "agent_avatar.png"
        self.logo_path = self.project_root / "app" / "icon.png"
        self.icon_path = self.project_root / "app" / "icon.ico"
        if not self.icon_path.exists():
            self.icon_path = self.logo_path
        self.region_file = self.project_root / "game_region.json"
        self.default_cluster_workers = 1
        self.cluster_worker_memory_gb = 2.0
        self.cluster_worker_cpu_limit_percent = 200.0
        self.cluster_worker_target_fps = 30
        self.cluster_browser_prewarm_enabled = True
        self.cluster_preview_target_fps = 10
        self.cluster_control_preview_target_fps = 15
        self.cluster_gpu_acceleration_enabled = True
        self.cluster_watch_ads = False
        self.cluster_auto_learning_enabled = True
        self.cluster_browser_dom_drive_mode = "legacy"
        self.cluster_dom_confirmation_required = True
        self.cluster_dom_live_cooldown_ms = 850
        self.cluster_dom_live_max_repeat_attempts = 3
        self.cluster_dom_evidence_weight = 1.3
        self.host_gpu_info = {"available": False, "name": "Detecting GPU...", "memory_gb": 0.0}
        self.cluster_worker_runtimes = {}
        self.cluster_worker_startup_overrides = {}
        self._browser_prewarm_pool_instance = None
        self.worker_preview_windows = {}
        self.worker_control_windows = {}
        self.worker_dom_snapshot_cache = {}
        self.desktop_window_titles = []
        self._task_evidence_store_instance = None
        self._dom_analyzer_instance = None
        self._n8n_manager_instance = None

        self.ai_running = False
        self.ppo_training = False
        self.current_state = {"xp": 0, "gold": 0, "reward": 0.0, "action": "idle"}
        self.episode_count = 0
        self.total_reward = 0.0
        self.exploration_rate = 1.0
        self.worker_data = []
        self.cluster_connected = False
        self.cluster_connected_at = None
        self.cluster_last_event = "No cluster events yet."
        self.cluster_last_event_at = None
        self.cluster_event_count = 0
        self._next_worker_index = 1
        self._training_steps_completed = 0
        self._action_value_map = {}
        self._ppo_status_text = "Idle"
        self._pipeline_event_counts = {"frames": 0, "perceptions": 0, "decisions": 0, "executions": 0}
        self._pipeline_last_signal = "No runtime signals yet."
        self._pipeline_last_signal_at = None
        self._pending_logs = SimpleQueue()
        self._pending_rewards = SimpleQueue()
        self._pending_metric_points = SimpleQueue()
        self.current_theme = "terminal"
        self._sidebar_user_visible = True
        self._current_page_name = "Training"
        self.vision_live_preview_enabled = False
        self.vision_last_frame = None
        self.vision_last_analysis = {}
        self.vision_last_dom_snapshot = {}
        self.vision_last_screen_action_map = {}
        self.vision_last_inference_ms = 0.0
        self.vision_last_capture_size = "N/A"
        self.vision_preview_frames = 0
        self.vision_target_limit = 5
        self.vision_source_mode = "region"
        self.vision_media_path = ""
        self.vision_media_kind = None
        self.vision_media_capture = None
        self.vision_media_image = None
        self.vision_media_total_frames = 0
        self.vision_obs_client = None
        self.vision_obs_status = "OBS capture unavailable"
        self.vision_heatmap = None
        self.vision_heatmap_shape = None
        self.vision_last_heatmap_peak = 0.0
        self.vision_session_history = []
        self.vision_session_limit = 30
        self.vision_builtin_presets = self._default_vision_presets()
        self.vision_custom_presets = {}
        self.vision_preset_profiles = dict(self.vision_builtin_presets)
        self.vision_selected_preset = "Balanced"

        self.click_overlay = ClickOverlay()
        self.debug_overlay = None

        self.setWindowTitle(self.APP_NAME)
        if self.icon_path.exists():
            self.setWindowIcon(QIcon(str(self.icon_path)))
        self.setMinimumSize(900, 620)
        self._apply_initial_window_geometry()
        self.vision_preview_timer = QTimer(self)
        self.vision_preview_timer.setInterval(700)
        self.vision_preview_timer.timeout.connect(self.update_vision_lab_preview)

        self._build_shell()
        self._build_menu_bar()
        self._build_pages()
        self._build_status_bar()
        self._load_settings_from_config()
        QTimer.singleShot(0, self.refresh_desktop_window_list)
        self._attach_event_bus()
        self._ui_refresh_timer = QTimer(self)
        self._ui_refresh_timer.setInterval(180)
        self._ui_refresh_timer.timeout.connect(self._refresh_runtime_ui)
        self._ui_refresh_timer.start()
        self._worker_preview_timer = QTimer(self)
        self._worker_preview_timer.setInterval(max(33, int(round(1000.0 / max(1, self.cluster_preview_target_fps)))))
        self._worker_preview_timer.timeout.connect(self._update_worker_preview_windows)
        self._worker_control_timer = QTimer(self)
        self._worker_control_timer.setInterval(
            max(33, int(round(1000.0 / max(1, self.cluster_control_preview_target_fps))))
        )
        self._worker_control_timer.timeout.connect(self._update_worker_control_windows)
        default_page = self._config_value("general", "default_page", "Training")
        self.navigate_to(default_page if default_page in self.PAGE_ORDER else "Training")

    def attach_runtime_services(
        self,
        input_manager=None,
        ppo_trainer=None,
        plugin_manager=None,
        event_bus=None,
        pipeline_controller=None,
        config=None,
    ):
        if config is not None:
            self.config = config
        if event_bus is not None and event_bus is not self.event_bus:
            self.event_bus = event_bus
            self._attach_event_bus()
        self.input_manager = input_manager
        self.ppo_trainer = ppo_trainer
        self.plugin_manager = plugin_manager
        self.pipeline_controller = pipeline_controller
        self._apply_runtime_settings_from_ui()
        self.refresh_ocr_status()
        self.refresh_plugins()
        self._sync_training_ui_state()
        self._sync_model_dashboard_state()
        self._sync_plugin_ui_state()
        self._sync_cluster_ui_state()
        self._sync_vision_lab_state()

    def refresh_host_gpu_info(self):
        self.host_gpu_info = _get_host_gpu_info()
        if hasattr(self, "cluster_gpu_detected_label"):
            if self._cluster_gpu_enabled():
                self.cluster_gpu_detected_label.setText(f"Detected GPU: {self._host_gpu_summary()}")
            else:
                self.cluster_gpu_detected_label.setText("GPU acceleration disabled. Workers will stay in legacy browser mode.")
        if hasattr(self, "cluster_gpu_label"):
            self.cluster_gpu_label.setText(f"Avg GPU: 0% / 100% | 0% worker average | Host: {self._host_gpu_summary()}")

    def _build_shell(self):
        root = QWidget()
        self.setCentralWidget(root)
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(12)

        sidebar_shell = QFrame()
        self.sidebar_shell = sidebar_shell
        sidebar_layout = QVBoxLayout(sidebar_shell)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(10)

        brand = QFrame()
        brand.setObjectName("heroCard")
        brand_layout = QHBoxLayout(brand)
        brand_layout.setContentsMargins(14, 14, 14, 14)
        brand_layout.setSpacing(12)
        self.brand_logo_label = QLabel()
        self.brand_logo_label.setObjectName("brandLogo")
        self.brand_logo_label.setFixedSize(64, 64)
        self.brand_logo_label.setAlignment(Qt.AlignCenter)
        if self.logo_path.exists():
            brand_logo = QPixmap(str(self.logo_path))
            if not brand_logo.isNull():
                self.brand_logo_label.setPixmap(brand_logo.scaled(46, 46, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        brand_layout.addWidget(self.brand_logo_label)
        brand_text = QWidget()
        brand_text.setMinimumWidth(0)
        brand_text.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        brand_text_layout = QVBoxLayout(brand_text)
        brand_text_layout.setContentsMargins(0, 0, 0, 0)
        brand_text_layout.setSpacing(3)
        brand_title = QLabel(self.APP_NAME)
        brand_title.setObjectName("brandWordmark")
        brand_title.setWordWrap(True)
        brand_title.setMinimumWidth(0)
        brand_title.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.brand_subtitle_label = QLabel("Graphs, training, clusters, plugins.")
        self.brand_subtitle_label.setWordWrap(True)
        self.brand_subtitle_label.setObjectName("mutedLabel")
        brand_text_layout.addWidget(brand_title)
        brand_text_layout.addWidget(self.brand_subtitle_label)
        brand_layout.addWidget(brand_text, stretch=1)
        sidebar_layout.addWidget(brand)

        self.sidebar = QListWidget()
        self.sidebar.setObjectName("navSidebar")
        self.sidebar.currentRowChanged.connect(self._on_nav_changed)
        sidebar_layout.addWidget(self.sidebar, stretch=1)

        self.footer_label = QLabel("F12 stops live training.\nTerminal is the default theme. Use Settings to switch themes.")
        self.footer_label.setObjectName("mutedLabel")
        self.footer_label.setWordWrap(True)
        sidebar_layout.addWidget(self.footer_label)

        self._sidebar_default_width = 276
        sidebar_shell.setFixedWidth(self._sidebar_default_width)
        root_layout.addWidget(sidebar_shell)

        content_shell = QFrame()
        content_shell.setObjectName("contentShell")
        content_layout = QVBoxLayout(content_shell)
        content_layout.setContentsMargins(14, 14, 14, 14)
        content_layout.setSpacing(12)

        self.page_header = QWidget()
        page_header_layout = QVBoxLayout(self.page_header)
        page_header_layout.setContentsMargins(0, 0, 0, 0)
        page_header_layout.setSpacing(2)
        self.page_title = QLabel("Training")
        self.page_title.setObjectName("pageTitle")
        self.page_title.setWordWrap(True)
        self.page_subtitle = QLabel("Configure runtime controls, capture, and training state.")
        self.page_subtitle.setObjectName("mutedLabel")
        self.page_subtitle.setWordWrap(True)
        page_header_layout.addWidget(self.page_title)
        page_header_layout.addWidget(self.page_subtitle)
        content_layout.addWidget(self.page_header)

        self.page_stack = QStackedWidget()
        self.page_stack.setMinimumSize(0, 0)
        self.page_stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        content_layout.addWidget(self.page_stack, stretch=1)
        root_layout.addWidget(content_shell, stretch=1)

    def is_sidebar_visible(self) -> bool:
        return bool(getattr(self, "_sidebar_user_visible", True))

    def set_sidebar_visible(self, visible: bool) -> bool:
        if getattr(self, "sidebar_shell", None) is None:
            return False
        self._sidebar_user_visible = bool(visible)
        self.sidebar_shell.setVisible(self._sidebar_user_visible)
        return self._sidebar_user_visible

    def toggle_sidebar_visibility(self) -> bool:
        visible = not self.is_sidebar_visible()
        self.set_sidebar_visible(visible)
        return visible

    def _build_menu_bar(self):
        menu_bar = self.menuBar()

        file_menu = menu_bar.addMenu("&File")
        save_region_action = QAction("Save Region", self)
        save_region_action.triggered.connect(self.save_game_region)
        load_region_action = QAction("Load Region", self)
        load_region_action.triggered.connect(self.load_game_region)
        file_menu.addAction(save_region_action)
        file_menu.addAction(load_region_action)
        file_menu.addSeparator()
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        view_menu = menu_bar.addMenu("&View")
        self.theme_actions = {}
        toggle_overlay_action = QAction("Toggle Debug Overlay", self)
        toggle_overlay_action.triggered.connect(self.toggle_debug_overlay)
        view_menu.addAction(toggle_overlay_action)

        tools_menu = menu_bar.addMenu("&Tools")
        preview_action = QAction("Preview Region", self)
        preview_action.triggered.connect(self.preview_game_region)
        tools_menu.addAction(preview_action)
        refresh_plugins_action = QAction("Refresh Plugins", self)
        refresh_plugins_action.triggered.connect(self.refresh_plugins)
        tools_menu.addAction(refresh_plugins_action)

        help_menu = menu_bar.addMenu("&Help")
        about_action = QAction(f"About {self.APP_NAME}", self)
        about_action.triggered.connect(self.show_about_dialog)
        help_menu.addAction(about_action)
        help_menu.addSeparator()
        for doc_key in ["license", "eula", "notice", "third_party_notices", "security"]:
            action = QAction(legal_doc_label(doc_key), self)
            action.triggered.connect(lambda _checked=False, key=doc_key: self._show_legal_document(key))
            help_menu.addAction(action)

    def _build_status_bar(self):
        status_bar = QStatusBar()
        self.setStatusBar(status_bar)
        self.status_label = QLabel("Ready")
        status_bar.addWidget(self.status_label, 1)
        self.author_label = QLabel(f"By {self.AUTHOR_NAME}")
        self.author_label.setObjectName("authorLabel")
        status_bar.addPermanentWidget(self.author_label)
        self.set_status("Ready")

    def _create_page_host(self):
        host = QWidget()
        host.setMinimumSize(0, 0)
        host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        return host, layout

    def _post_build_page_sync(self, page_name: str):
        if page_name in {"Vision Lab", "Guide Coach", "Provider Hub", "n8n Hub", "Settings"} and getattr(self, "_settings_payload_cache", None) is not None:
            self._apply_settings_payload_to_ui(self._settings_payload_cache)
        if page_name == "Behavior Editor" and hasattr(self, "behavior_editor"):
            self.behavior_editor.set_theme(self.current_theme)
        if page_name == "Model Dashboard":
            self._sync_model_dashboard_state()
        elif page_name == "Cluster":
            self._sync_cluster_ui_state()
        elif page_name == "Plugins":
            self.refresh_plugins()
            self._sync_plugin_ui_state()
        elif page_name == "Vision Lab":
            self._sync_vision_lab_state()
        elif page_name == "Guide Coach":
            self._sync_guide_coach_state()
        elif page_name == "Provider Hub":
            self._sync_provider_hub_state()
        elif page_name == "n8n Hub":
            self._sync_n8n_hub_state()
        elif page_name == "Training":
            self._sync_training_ui_state()
        elif page_name == "Settings":
            if self.isVisible():
                self.refresh_ocr_status()
        self._sync_model_dashboard_state()

    def _ensure_page_built(self, page_name: str):
        if page_name not in self.PAGE_ORDER:
            return
        if self._page_content.get(page_name) is not None:
            return
        builder = self._page_builders[page_name]
        widget = builder()
        widget.setMinimumSize(0, 0)
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._page_host_layouts[page_name].addWidget(widget)
        self._page_content[page_name] = widget
        self._post_build_page_sync(page_name)

    def _build_pages(self):
        self.sidebar.clear()
        for page_name in self.PAGE_ORDER:
            self.sidebar.addItem(QListWidgetItem(page_name))

        self._page_builders = {
            "Training": self.create_training_page,
            "Model Dashboard": self.create_model_dashboard_page,
            "Behavior Editor": self.create_behavior_editor_page,
            "Cluster": self.create_training_cluster_page,
            "Vision Lab": self.create_vision_lab_page,
            "Guide Coach": self.create_guide_coach_page,
            "Provider Hub": self.create_provider_hub_page,
            "n8n Hub": self.create_n8n_hub_page,
            "Plugins": self.create_plugins_page,
            "Settings": self.create_settings_page,
        }
        self._page_host_layouts = {}
        self._page_content = {}
        self.pages = {}
        for name in self.PAGE_ORDER:
            host, layout = self._create_page_host()
            self.pages[name] = host
            self._page_host_layouts[name] = layout
            self._page_content[name] = None
            self.page_stack.addWidget(host)
        self._ensure_page_built("Training")

    def _attach_event_bus(self):
        if self.event_bus is None:
            return
        self.event_bus.subscribe("plugin_log", self._queue_log)
        self.event_bus.subscribe("plugin_loaded", lambda _data: self.refresh_plugins())
        self.event_bus.subscribe("plugin_unloaded", lambda _data: self.refresh_plugins())
        self.event_bus.subscribe("frame_captured", lambda _data: self._record_pipeline_event("frames", "Frame captured"))
        self.event_bus.subscribe("perception_ready", lambda _data: self._record_pipeline_event("perceptions", "Perception ready"))
        self.event_bus.subscribe("action_decided", self._handle_action_decided)
        self.event_bus.subscribe("action_executed", self._handle_action_executed)

    def _queue_log(self, message):
        if message is None:
            return
        self._pending_logs.put(str(message))

    def _queue_reward_entry(self, message: str):
        if message is None:
            return
        self._pending_rewards.put(str(message))

    def _queue_metric_point(self, step: int, xp: float, gold: float, reward: float, action: str):
        self._pending_metric_points.put(
            {
                "step": float(step),
                "xp": float(xp),
                "gold": float(gold),
                "reward": float(reward),
                "action": str(action or "idle"),
            }
        )

    def _record_pipeline_event(self, key: str, message: str):
        if key in self._pipeline_event_counts:
            self._pipeline_event_counts[key] += 1
        self._pipeline_last_signal = message
        self._pipeline_last_signal_at = time.time()

    def _handle_action_decided(self, data):
        self._record_pipeline_event("decisions", f"Action decided: {data}")
        self._queue_log(f"Action decided: {data}")

    def _handle_action_executed(self, data):
        self._record_pipeline_event("executions", f"Action executed: {data}")
        self._queue_log(f"Action executed: {data}")

    def _refresh_runtime_ui(self):
        while True:
            try:
                message = self._pending_logs.get_nowait()
            except Empty:
                break
            self._append_log(message)

        while True:
            try:
                entry = self._pending_rewards.get_nowait()
            except Empty:
                break
            self._append_reward_history(entry)

        while True:
            try:
                point = self._pending_metric_points.get_nowait()
            except Empty:
                break
            self._append_metric_point(point)

        if hasattr(self, "xp_label"):
            self.xp_label.setText(f"XP: {self.current_state.get('xp', 0)}")
            self.gold_label.setText(f"Gold: {self.current_state.get('gold', 0)}")
            self.reward_label.setText(f"Reward: {float(self.current_state.get('reward', 0.0)):.2f}")
            self.action_label.setText(f"Last Action: {self.current_state.get('action', 'idle')}")
        if hasattr(self, "training_status_value"):
            self.training_status_value.setText("Running" if self.ai_running else "Idle")
        if hasattr(self, "training_mode_value") and hasattr(self, "browser_radio"):
            self.training_mode_value.setText("Browser" if self.browser_radio.isChecked() else "Desktop")
        if hasattr(self, "training_region_value"):
            self.training_region_value.setText(self._training_region_summary())

        if hasattr(self, "progress_bar") and hasattr(self, "max_steps_spin"):
            max_steps = max(1, self.max_steps_spin.value())
            completed = min(self._training_steps_completed, max_steps)
            self.progress_bar.setRange(0, max_steps)
            self.progress_bar.setValue(completed)
            self.progress_bar.setFormat(f"Training Progress: {completed}/{max_steps}")

        if hasattr(self, "episode_count_label"):
            average_reward = self.total_reward / max(1, self.episode_count)
            self.episode_count_label.setText(f"Episodes: {self.episode_count}")
            self.total_reward_label.setText(f"Total Reward: {self.total_reward:.2f}")
            self.average_reward_label.setText(f"Average Reward: {average_reward:.2f}")
            self.exploration_rate_label.setText(f"Exploration Rate: {self.exploration_rate:.3f}")
            self.ppo_status_label.setText(f"PPO Status: {self._ppo_status_text}")

        self._sync_training_ui_state()
        self._sync_model_dashboard_state()
        self._sync_cluster_ui_state()
        self._sync_vision_lab_state()
        self._sync_plugin_ui_state()

    def _append_reward_history(self, entry: str):
        if not hasattr(self, "reward_history"):
            return
        if self.reward_history.count() == 1 and self.reward_history.item(0).text() == "No rewards recorded yet.":
            self.reward_history.clear()
        self.reward_history.insertItem(0, entry)
        while self.reward_history.count() > 80:
            self.reward_history.takeItem(self.reward_history.count() - 1)

    def _append_metric_point(self, point: dict):
        if not hasattr(self, "reward_series"):
            return
        step = point["step"]
        for series, value in [
            (self.xp_series, point["xp"]),
            (self.gold_series, point["gold"]),
            (self.reward_series, point["reward"]),
            (self.action_series, self._action_value(point["action"])),
        ]:
            series.append(step, value)
            chart = series.chart()
            if chart is None:
                continue
            x_axes = chart.axes(Qt.Horizontal)
            y_axes = chart.axes(Qt.Vertical)
            if x_axes:
                x_axes[0].setRange(0, max(10.0, step))
            if y_axes:
                y_axes[0].setRange(min(y_axes[0].min(), 0.0, value), max(y_axes[0].max(), value + 1.0))

    def _action_value(self, action_name: str) -> int:
        action_name = action_name or "idle"
        if action_name not in self._action_value_map:
            self._action_value_map[action_name] = len(self._action_value_map) + 1
        return self._action_value_map[action_name]

    def _sync_training_ui_state(self):
        if not hasattr(self, "start_btn"):
            return
        self.start_btn.setEnabled(not self.ai_running)
        self.stop_btn.setEnabled(self.ai_running)
        if hasattr(self, "train_ppo_btn") and hasattr(self, "stop_ppo_btn"):
            self.train_ppo_btn.setEnabled(not self.ppo_training and self.ppo_trainer is not None)
            self.stop_ppo_btn.setEnabled(self.ppo_training)

    def _sync_model_dashboard_state(self):
        if not hasattr(self, "model_trainer_value"):
            return
        trainer_ready = self.ppo_trainer is not None
        pipeline_ready = self.pipeline_controller is not None
        plugin_count = len(self.plugin_manager.get_plugin_summaries()) if self.plugin_manager is not None else 0
        save_path = self._model_save_path()
        checkpoint_path = Path(save_path + ".zip")
        trainer_summary = self.ppo_trainer.short_backend_label() if trainer_ready and hasattr(self.ppo_trainer, "short_backend_label") else ("Ready" if trainer_ready else "Unavailable")
        checkpoint_summary = self.ppo_trainer.checkpoint_summary() if trainer_ready and hasattr(self.ppo_trainer, "checkpoint_summary") else ("Present" if checkpoint_path.exists() else "Missing")
        self.model_trainer_value.setText(trainer_summary if trainer_ready else "Unavailable")
        self.model_checkpoint_value.setText(checkpoint_summary)
        self.model_pipeline_value.setText("Attached" if pipeline_ready else "Offline")
        self.model_plugins_value.setText(str(plugin_count))
        self.model_save_path_label.setText(f"Model Path: {save_path}")
        if hasattr(self, "model_backend_label"):
            backend_text = self.ppo_trainer.summary() if trainer_ready and hasattr(self.ppo_trainer, "summary") else "Trainer unavailable"
            self.model_backend_label.setText(f"Backend: {backend_text}")
        if hasattr(self, "model_checkpoint_detail_label"):
            eval_reward = getattr(self.ppo_trainer, "last_eval_reward", None) if trainer_ready else None
            eval_text = "n/a" if eval_reward is None else f"{float(eval_reward):.2f}"
            self.model_checkpoint_detail_label.setText(
                f"Checkpoint Details: {checkpoint_summary} | Eval Reward: {eval_text}"
            )
        self.model_runtime_label.setText(
            "Runtime: "
            f"training={'live' if self.ai_running else 'idle'}, "
            f"ppo={'training' if self.ppo_training else getattr(self, '_ppo_status_text', 'idle').lower()}, "
            f"theme={self.THEME_DEFINITIONS.get(self.current_theme, {}).get('label', self.current_theme)}"
        )
        self.model_ocr_label.setText(f"OCR: {self._ocr_status_summary()}")
        self.model_cluster_label.setText(
            f"Cluster: {'connected' if self.cluster_connected else 'offline'} with {len(self.worker_data)} worker(s)"
        )
        trainer_caps = (
            self.ppo_trainer.capabilities_summary()
            if trainer_ready and hasattr(self.ppo_trainer, "capabilities_summary")
            else "PPO trainer unavailable."
        )
        self.model_capabilities_label.setText(
            "Capabilities: browser and desktop capture, behavior graphs, PPO training, OCR + YOLO perception, "
            f"plugin loading, multi-worker cluster control, and RL backends: {trainer_caps}"
        )

    def _sync_plugin_ui_state(self):
        if not hasattr(self, "plugin_count_value"):
            return
        summaries = self.plugin_manager.get_plugin_summaries() if self.plugin_manager is not None else []
        self.plugin_count_value.setText(str(len(summaries)))
        self.plugin_runtime_value.setText("Ready" if self.plugin_manager is not None else "Unavailable")
        self.plugin_reload_value.setText("Available" if self.plugin_manager is not None else "Disabled")
        self.plugin_event_value.setText("Attached" if self.event_bus is not None else "Offline")
        if not summaries:
            self.plugin_detail_name_label.setText("Name: No plugins loaded")
            self.plugin_detail_id_label.setText("ID: N/A")
            self.plugin_detail_version_label.setText("Version: N/A")
            self.plugin_detail_description_label.setText("Description: Load or reload plugins to inspect them here.")

    def _sync_vision_lab_state(self):
        if not hasattr(self, "vision_preview_value"):
            return
        analysis = self.vision_last_analysis or {}
        detections = analysis.get("detections", [])
        dataset_count = self._vision_dataset_sample_count()
        session_count = len(self.vision_session_history)
        heatmap_peak = self.vision_last_heatmap_peak
        source_mode = self.vision_source_selector.currentText() if hasattr(self, "vision_source_selector") else "Screen Region"
        acceleration = self.vision_acceleration_selector.currentText() if hasattr(self, "vision_acceleration_selector") else "Auto"
        self.vision_preview_value.setText("Live" if self.vision_live_preview_enabled else "Stopped")
        self.vision_detector_value.setText(analysis.get("detector_label", self._vision_detector_name()))
        self.vision_targets_value.setText(str(len(detections)))
        self.vision_dataset_value.setText(str(dataset_count))
        if hasattr(self, "vision_history_value"):
            self.vision_history_value.setText(str(session_count))
        if hasattr(self, "vision_heatmap_value"):
            self.vision_heatmap_value.setText(f"{heatmap_peak:.1f}")
        self.vision_runtime_label.setText(
            "Runtime: "
            f"{source_mode} | "
            f"{self.vision_backend_selector.currentText()} | "
            f"{acceleration} | "
            f"Interval: {self.vision_interval_spin.value()} ms | "
            f"Target Limit: {self.vision_target_limit_spin.value()}"
        )
        self.vision_capture_label.setText(
            f"Capture: {self.vision_last_capture_size} | Region: {self._training_region_summary()}"
        )
        self.vision_status_label.setText(
            f"Last Analysis: {analysis.get('summary', 'No analysis yet.')}"
        )
        self.vision_ocr_state_label.setText(f"OCR: {self._ocr_status_summary()}")
        self.vision_benchmark_label.setText(f"Inference: {self.vision_last_inference_ms:.1f} ms")
        self.vision_model_label.setText(
            "Detector Source: "
            f"{analysis.get('detector_label', self._vision_detector_name())} | "
            f"Samples: {dataset_count}"
        )
        if hasattr(self, "vision_heatmap_summary_label"):
            self.vision_heatmap_summary_label.setText(
                f"Peak intensity {heatmap_peak:.1f} across {session_count} session event(s)."
                if heatmap_peak > 0
                else "No hotspots yet. Run live preview or analyze a frame to build the map."
            )
        if hasattr(self, "vision_preset_summary_label"):
            preset_text = self.vision_preset_selector.currentText() if hasattr(self, "vision_preset_selector") else self.vision_selected_preset
            self.vision_preset_summary_label.setText(
                f"Active preset: {preset_text} | History limit: {self.vision_session_limit} | Heatmap radius: "
                f"{self.vision_heatmap_radius_spin.value() if hasattr(self, 'vision_heatmap_radius_spin') else 42}"
            )
        if hasattr(self, "vision_capture_source_label"):
            media_text = Path(self.vision_media_path).name if self.vision_media_path else "none"
            self.vision_capture_source_label.setText(
                f"Source Mode: {source_mode} | Media: {media_text}"
            )
        if hasattr(self, "vision_media_path_label"):
            if self.vision_media_path:
                suffix = f" | frames={self.vision_media_total_frames}" if self.vision_media_kind == "video" else ""
                self.vision_media_path_label.setText(f"Media: {self.vision_media_path}{suffix}")
            else:
                self.vision_media_path_label.setText("Media: none loaded")
        if hasattr(self, "vision_obs_status_label"):
            self.vision_obs_status_label.setText(f"OBS: {self.vision_obs_status}")
        if hasattr(self, "vision_backend_status_label"):
            capabilities = self._vision_backend_capabilities()
            self.vision_backend_status_label.setText(
                "Backends: "
                f"YOLO={'yes' if capabilities['yolo'] else 'no'}, "
                f"ONNX={'yes' if capabilities['onnx'] else 'no'}, "
                f"TensorRT={'yes' if capabilities['tensorrt'] else 'no'}, "
                f"OBS={'yes' if capabilities['obs'] else 'no'}"
            )
        if hasattr(self, "vision_media_frame_spin"):
            is_video = self.vision_media_kind == "video" and self.vision_media_total_frames > 0
            self.vision_media_frame_spin.setEnabled(is_video)
        if hasattr(self, "vision_prev_frame_btn"):
            frame_controls_enabled = self.vision_media_kind in {"image", "video"}
            self.vision_prev_frame_btn.setEnabled(frame_controls_enabled)
            self.vision_next_frame_btn.setEnabled(frame_controls_enabled and self.vision_media_kind == "video")
        if hasattr(self, "vision_history_list") and self.vision_history_list.count() != session_count:
            self._refresh_vision_history_widgets()

    def _guide_coach_latest_frame(self):
        if self.vision_last_frame is not None:
            return self.vision_last_frame.copy()
        if self.vision_media_kind in {"image", "video"}:
            frame = self._load_vision_media_frame(0)
            if frame is not None:
                return frame.copy()
        return None

    def _capture_guide_coach_frame(self):
        try:
            frame = self._capture_vision_frame()
        except Exception:
            frame = None
        if frame is not None:
            return frame.copy()
        try:
            from vision.screen_capture import capture_screen

            region = self._validated_game_region()
            if region is None:
                return None
            return capture_screen(region)
        except Exception:
            return None

    def _current_vision_media_path(self) -> str:
        return str(self.vision_media_path or "")

    def _task_evidence_store(self):
        if self._task_evidence_store_instance is None:
            from automation.task_evidence_store import TaskEvidenceStore

            self._task_evidence_store_instance = TaskEvidenceStore(self.project_root)
        return self._task_evidence_store_instance

    def _dom_analyzer(self):
        if self._dom_analyzer_instance is None:
            from automation.dom_analysis import DomAnalyzer

            self._dom_analyzer_instance = DomAnalyzer(self.project_root)
        return self._dom_analyzer_instance

    def _n8n_manager(self):
        if self._n8n_manager_instance is None:
            from automation.n8n_sidecar import N8nSidecarManager

            self._n8n_manager_instance = N8nSidecarManager(self.project_root)
        return self._n8n_manager_instance

    def _guide_coach_engine(self):
        widget_engine = getattr(getattr(self, "guide_coach_widget", None), "engine", None)
        if widget_engine is not None:
            return widget_engine
        cached = getattr(self, "_guide_coach_engine_instance", None)
        if cached is None:
            from automation.guide_coach import GuideCoachEngine

            cached = GuideCoachEngine(
                self.project_root,
                profile_key=getattr(self._current_game_profile(), "key", "legends_of_mushroom"),
            )
            self._guide_coach_engine_instance = cached
        return cached

    def _guide_analysis_for_frame(self, frame, source_label: str = "Current Capture") -> dict:
        if frame is None:
            return {}
        engine = self._guide_coach_engine()
        checklist_progress = {}
        if hasattr(self, "guide_coach_widget"):
            checklist_progress = dict(getattr(self.guide_coach_widget, "checklist_progress", {}) or {})
        try:
            return engine.analyze_frame(frame, checklist_progress=checklist_progress, source_label=source_label)
        except Exception as exc:
            self._queue_log(f"Guide analysis error: {exc}")
            return {}

    def _dom_snapshot_summary_payload(self, snapshot: dict | None) -> dict:
        snapshot = dict(snapshot or {})
        top_actionables = []
        for entry in list(snapshot.get("actionables", []) or [])[:8]:
            bounds = dict(entry.get("bounds") or {})
            top_actionables.append(
                {
                    "label": str(entry.get("text") or entry.get("selector_hint") or entry.get("role") or "").strip(),
                    "kind": str(entry.get("role") or "dom").strip(),
                    "keyword": "",
                    "token": str(entry.get("token") or "").strip(),
                    "score": float(entry.get("confidence", 0.0) or 0.0),
                    "bounds": {
                        "x": int(bounds.get("x", 0) or 0),
                        "y": int(bounds.get("y", 0) or 0),
                        "width": int(bounds.get("width", 0) or 0),
                        "height": int(bounds.get("height", 0) or 0),
                    },
                }
            )
        return {
            "url": str(snapshot.get("url") or "").strip(),
            "title": str(snapshot.get("title") or "").strip(),
            "viewport": dict(snapshot.get("viewport") or {}),
            "raw_text_summary": str(snapshot.get("raw_text_summary") or "").strip()[:1500],
            "actionable_count": int(snapshot.get("actionable_count", len(snapshot.get("actionables", []) or [])) or 0),
            "top_actionables": top_actionables,
            "screenshot_hash": str(snapshot.get("screenshot_hash") or "").strip(),
        }

    def _build_screen_action_map(self, dom_snapshot: dict | None, frame, guide_analysis: dict | None = None) -> dict:
        guide_analysis = dict(guide_analysis or {})
        screen_state = str(guide_analysis.get("screen_state") or "unknown").strip().lower() or "unknown"
        profile_name = getattr(self._current_game_profile(), "name", "Legends of Mushroom")
        evidence_summary = self._task_evidence_store().aggregate(
            game=getattr(self._current_game_profile(), "key", "legends_of_mushroom"),
            profile=profile_name,
            screen_state=screen_state,
            runtime="browser",
        )
        return self._dom_analyzer().build_screen_action_map(
            dom_snapshot,
            ocr_boxes=list(guide_analysis.get("ocr_boxes", []) or []),
            screen_state=screen_state,
            guide_analysis=guide_analysis,
            evidence_summary=evidence_summary,
        )

    def _selected_browser_worker_runtime(self):
        worker = self._selected_worker_record()
        if worker is None:
            worker = next(
                (
                    item
                    for item in self.worker_data
                    if str((item or {}).get("mode", "")).strip().lower() == "browser"
                    and str((item or {}).get("status", "")).strip().lower() not in {"offline", "idle", "stopped"}
                ),
                None,
            )
        if worker is None:
            return None, None
        worker_id = str(worker.get("id") or "")
        runtime = self.cluster_worker_runtimes.get(worker_id)
        return worker, runtime

    def _capture_worker_dom_snapshot(self, worker_id: str) -> tuple[dict, object | None, dict | None]:
        worker = self._worker_record_by_id(worker_id)
        runtime = self.cluster_worker_runtimes.get(worker_id)
        if worker is None or runtime is None:
            return {}, None, worker
        capture = getattr(runtime, "capture_dom_snapshot", None)
        if not callable(capture):
            return {}, runtime, worker
        snapshot = dict(capture() or {})
        if snapshot:
            self.worker_dom_snapshot_cache[str(worker.get("id") or "")] = dict(snapshot)
        return snapshot, runtime, worker

    def _capture_selected_worker_dom_snapshot(self):
        worker, runtime = self._selected_browser_worker_runtime()
        if worker is None or runtime is None:
            return {}
        snapshot, _runtime, _worker = self._capture_worker_dom_snapshot(str(worker.get("id") or ""))
        return snapshot

    def _guide_coach_dom_snapshot(self):
        snapshot = self._capture_selected_worker_dom_snapshot()
        if snapshot:
            return snapshot
        worker, _runtime = self._selected_browser_worker_runtime()
        if worker is None:
            return {}
        return dict(self.worker_dom_snapshot_cache.get(str(worker.get("id") or ""), {}) or {})

    def _guide_coach_manual_context(self):
        worker, _runtime = self._selected_browser_worker_runtime()
        if worker is None:
            return {"game": getattr(self._current_game_profile(), "key", "legends_of_mushroom"), "profile": getattr(self._current_game_profile(), "name", "Legends of Mushroom"), "runtime": "browser"}
        return {
            "worker_id": str(worker.get("id") or ""),
            "game": getattr(self._current_game_profile(), "key", "legends_of_mushroom"),
            "profile": str(worker.get("profile") or getattr(self._current_game_profile(), "name", "Legends of Mushroom")),
            "runtime": "browser",
            "session_id": str(worker.get("id") or ""),
        }

    def _capture_worker_control_dom_snapshot(self, worker_id: str):
        window = self.worker_control_windows.get(worker_id)
        snapshot, runtime, worker = self._capture_worker_dom_snapshot(worker_id)
        if worker is None or runtime is None:
            if window is not None:
                window.set_manual_status("Worker runtime is unavailable, so no DOM snapshot could be captured.")
            self.set_status(f"{worker_id} DOM snapshot unavailable")
            return {}
        preview_payload = getattr(runtime, "preview_payload", None)
        preview = preview_payload() if callable(preview_payload) else {}
        frame = preview.get("frame")
        guide_analysis = self._guide_analysis_for_frame(frame, source_label=f"{worker_id} Manual Session") if frame is not None else {}
        action_map = self._build_screen_action_map(snapshot, frame, guide_analysis=guide_analysis) if snapshot or guide_analysis else {}
        if hasattr(self, "guide_coach_widget"):
            if frame is not None:
                self.guide_coach_widget.analyze_frame_silently(frame, f"{worker_id} Manual Session")
            if snapshot:
                self.guide_coach_widget.ingest_dom_snapshot(snapshot, source_label=f"{worker_id} Manual Session", frame=frame)
        if window is not None:
            if snapshot:
                top_label = str((((action_map or {}).get("merged_actions") or [{}])[0] or {}).get("label") or "No ranked actions").strip()
                window.set_manual_status(
                    f"Captured DOM snapshot with {int(snapshot.get('actionable_count', 0) or 0)} actionables. Top merged action: {top_label}."
                )
            else:
                window.set_manual_status("DOM snapshot capture returned no actionable elements.")
        self.set_status(f"Captured DOM snapshot for {worker_id}")
        return snapshot

    def _save_worker_control_evidence(self, worker_id: str, outcome: str):
        window = self.worker_control_windows.get(worker_id)
        snapshot, runtime, worker = self._capture_worker_dom_snapshot(worker_id)
        if worker is None or runtime is None:
            if window is not None:
                window.set_manual_status("Evidence save skipped because the worker runtime is unavailable.")
            return
        preview_payload = getattr(runtime, "preview_payload", None)
        preview = preview_payload() if callable(preview_payload) else {}
        frame = preview.get("frame")
        guide_analysis = self._guide_analysis_for_frame(frame, source_label=f"{worker_id} Manual Session") if frame is not None else {}
        action_map = self._build_screen_action_map(snapshot, frame, guide_analysis=guide_analysis) if snapshot or guide_analysis else {}
        top_action = dict(((action_map or {}).get("merged_actions") or [{}])[0] or {})
        frame_hash_value = ""
        if frame is not None:
            try:
                from automation.dom_analysis import frame_hash

                frame_hash_value = frame_hash(frame)
            except Exception:
                frame_hash_value = ""
        chosen_candidate = {
            "label": str(top_action.get("label") or "").strip(),
            "kind": str(top_action.get("source") or top_action.get("role") or "dom").strip(),
            "keyword": str(top_action.get("keyword") or "").strip(),
            "token": str(top_action.get("token") or "").strip(),
            "score": float(top_action.get("score", 0.0) or 0.0),
            "bounds": dict(top_action.get("bounds") or {}),
        }
        intended_action = {
            "label": str(top_action.get("label") or guide_analysis.get("screen_label") or "Observed Action").strip(),
            "target_type": str(top_action.get("keyword") or "other").strip().lower() or "other",
            "keyword": str(top_action.get("keyword") or "").strip().lower(),
            "point": list(top_action.get("center") or [])[:2] if top_action.get("center") else None,
            "browser_point": None,
            "note": f"Saved from {worker_id} interactive control",
        }
        record = self._task_evidence_store().record(
            {
                "game": getattr(self._current_game_profile(), "key", "legends_of_mushroom"),
                "profile": str(worker.get("profile") or getattr(self._current_game_profile(), "name", "Legends of Mushroom")),
                "screen_state": str(guide_analysis.get("screen_state") or "unknown").strip().lower() or "unknown",
                "task_key": str(top_action.get("keyword") or guide_analysis.get("screen_state") or "manual_action").strip().lower() or "manual_action",
                "runtime": "browser",
                "worker_id": worker_id,
                "session_id": worker_id,
                "source": "manual_control",
                "dom_snapshot_summary": self._dom_snapshot_summary_payload(snapshot),
                "ocr_excerpt": str(guide_analysis.get("ocr_excerpt") or guide_analysis.get("ocr_text") or "").strip(),
                "chosen_candidate": chosen_candidate,
                "intended_action": intended_action,
                "confirmed_outcome": str(outcome or "neutral").strip().lower() or "neutral",
                "visible_transition": str(outcome or "").strip().lower() == "advanced",
                "frame_hash": frame_hash_value,
                "screenshot_hash": str(snapshot.get("screenshot_hash") or "").strip(),
                "note": f"Interactive control evidence from {worker_id}",
            }
        )
        if hasattr(self, "guide_coach_widget"):
            if frame is not None:
                self.guide_coach_widget.analyze_frame_silently(frame, f"{worker_id} Manual Session")
            if snapshot:
                self.guide_coach_widget.ingest_dom_snapshot(snapshot, source_label=f"{worker_id} Manual Session", frame=frame)
        if window is not None:
            top_label = str(top_action.get("label") or "Observed Action").strip()
            window.set_manual_status(
                f"Saved {str(outcome).replace('_', ' ')} evidence for {worker_id}. Top action: {top_label}. Record: {Path(str(record.get('storage_path') or '')).name}"
            )
        self.set_status(f"Saved {str(outcome).replace('_', ' ')} evidence for {worker_id}")

    def _sync_guide_coach_state(self):
        if not hasattr(self, "guide_coach_widget"):
            return
        latest_frame = self._guide_coach_latest_frame()
        if latest_frame is not None:
            source_label = Path(self.vision_media_path).name if self.vision_media_path else "Latest Vision Frame"
            self.guide_coach_widget.analyze_frame_silently(latest_frame, source_label)
        self.guide_coach_widget.set_action_evidence_state((self._settings_payload_cache or {}).get("action_evidence", {}))

    def _sync_provider_hub_state(self):
        if not hasattr(self, "provider_hub_widget"):
            return
        self.provider_hub_widget.set_saved_state((self._settings_payload_cache or {}).get("provider_hub", {}))

    def _sync_n8n_hub_state(self):
        if not hasattr(self, "n8n_hub_widget"):
            return
        self.n8n_hub_widget.set_saved_state((self._settings_payload_cache or {}).get("n8n", {}))

    def _schedule_n8n_autostart(self, payload: dict | None = None):
        config = dict(payload or (self._settings_payload_cache or {}).get("n8n", {}))
        if not bool(config.get("auto_start", False)):
            return

        def start_runtime():
            try:
                manager = self._n8n_manager()
                manager.apply_settings(config)
                status = manager.start(install_if_missing=True)
                self.set_status(str(status.get("message") or "n8n runtime auto-start attempted"))
            except Exception as exc:
                self.set_status(f"n8n auto-start failed: {exc}")

        QTimer.singleShot(1500, start_runtime)

    def _optional_module_available(self, module_name: str) -> bool:
        return importlib.util.find_spec(module_name) is not None

    def _vision_backend_capabilities(self) -> dict:
        return {
            "yolo": self._optional_module_available("ultralytics"),
            "onnx": self._optional_module_available("onnxruntime"),
            "tensorrt": self._optional_module_available("tensorrt"),
            "obs": any(self._optional_module_available(name) for name in ("obsws_python", "simpleobsws", "obswebsocket")),
        }

    def _current_vision_profile(self) -> dict:
        return self._sanitize_vision_profile(
            {
                "source_mode": self.vision_source_selector.currentData() if hasattr(self, "vision_source_selector") else "region",
                "backend": self.vision_backend_selector.currentData() if hasattr(self, "vision_backend_selector") else "auto",
                "acceleration": self.vision_acceleration_selector.currentData() if hasattr(self, "vision_acceleration_selector") else "auto",
                "confidence": self.vision_confidence_spin.value() if hasattr(self, "vision_confidence_spin") else 0.50,
                "interval_ms": self.vision_interval_spin.value() if hasattr(self, "vision_interval_spin") else 700,
                "target_limit": self.vision_target_limit_spin.value() if hasattr(self, "vision_target_limit_spin") else 5,
                "benchmark_runs": self.vision_benchmark_frames_spin.value() if hasattr(self, "vision_benchmark_frames_spin") else 20,
                "overlay_boxes": self.vision_overlay_boxes_checkbox.isChecked() if hasattr(self, "vision_overlay_boxes_checkbox") else True,
                "overlay_labels": self.vision_overlay_labels_checkbox.isChecked() if hasattr(self, "vision_overlay_labels_checkbox") else True,
                "overlay_ocr": self.vision_overlay_ocr_checkbox.isChecked() if hasattr(self, "vision_overlay_ocr_checkbox") else False,
                "heatmap_decay": self.vision_heatmap_decay_spin.value() if hasattr(self, "vision_heatmap_decay_spin") else 0.92,
                "heatmap_radius": self.vision_heatmap_radius_spin.value() if hasattr(self, "vision_heatmap_radius_spin") else 42,
                "history_limit": self.vision_history_limit_spin.value() if hasattr(self, "vision_history_limit_spin") else self.vision_session_limit,
            }
        )

    def _apply_vision_profile(self, profile: dict):
        sanitized = self._sanitize_vision_profile(profile)
        if hasattr(self, "vision_source_selector"):
            index = self.vision_source_selector.findData(sanitized["source_mode"])
            if index >= 0:
                self.vision_source_selector.setCurrentIndex(index)
        if hasattr(self, "vision_backend_selector"):
            index = self.vision_backend_selector.findData(sanitized["backend"])
            if index >= 0:
                self.vision_backend_selector.setCurrentIndex(index)
        if hasattr(self, "vision_acceleration_selector"):
            index = self.vision_acceleration_selector.findData(sanitized["acceleration"])
            if index >= 0:
                self.vision_acceleration_selector.setCurrentIndex(index)
        if hasattr(self, "vision_confidence_spin"):
            self.vision_confidence_spin.setValue(sanitized["confidence"])
        if hasattr(self, "vision_interval_spin"):
            self.vision_interval_spin.setValue(sanitized["interval_ms"])
        if hasattr(self, "vision_target_limit_spin"):
            self.vision_target_limit_spin.setValue(sanitized["target_limit"])
        if hasattr(self, "vision_benchmark_frames_spin"):
            self.vision_benchmark_frames_spin.setValue(sanitized["benchmark_runs"])
        if hasattr(self, "vision_overlay_boxes_checkbox"):
            self.vision_overlay_boxes_checkbox.setChecked(sanitized["overlay_boxes"])
        if hasattr(self, "vision_overlay_labels_checkbox"):
            self.vision_overlay_labels_checkbox.setChecked(sanitized["overlay_labels"])
        if hasattr(self, "vision_overlay_ocr_checkbox"):
            self.vision_overlay_ocr_checkbox.setChecked(sanitized["overlay_ocr"])
        if hasattr(self, "vision_heatmap_decay_spin"):
            self.vision_heatmap_decay_spin.setValue(sanitized["heatmap_decay"])
        if hasattr(self, "vision_heatmap_radius_spin"):
            self.vision_heatmap_radius_spin.setValue(sanitized["heatmap_radius"])
        if hasattr(self, "vision_history_limit_spin"):
            self.vision_history_limit_spin.setValue(sanitized["history_limit"])
        self.vision_session_limit = sanitized["history_limit"]
        self._apply_runtime_settings_from_ui()

    def _reset_vision_heatmap_buffer(self, shape=None):
        if shape is None:
            self.vision_heatmap = None
            self.vision_heatmap_shape = None
            self.vision_last_heatmap_peak = 0.0
            return
        height, width = shape[:2]
        np = _np()
        self.vision_heatmap = np.zeros((height, width), dtype=np.float32)
        self.vision_heatmap_shape = (height, width)
        self.vision_last_heatmap_peak = 0.0

    def reset_vision_heatmap(self):
        shape = self.vision_last_frame.shape if self.vision_last_frame is not None else None
        self._reset_vision_heatmap_buffer(shape)
        self._set_vision_heatmap_preview(None)
        if hasattr(self, "vision_heatmap_summary_label"):
            self.vision_heatmap_summary_label.setText("Heatmap reset. Analyze or preview frames to build hotspots again.")
        self._sync_vision_lab_state()
        self.set_status("Vision heatmap reset")

    def _update_vision_heatmap(self, detections, frame_shape):
        if frame_shape is None or len(frame_shape) < 2:
            return
        height, width = frame_shape[:2]
        if self.vision_heatmap is None or self.vision_heatmap_shape != (height, width):
            self._reset_vision_heatmap_buffer(frame_shape)
        cv2 = _cv2()
        np = _np()
        decay = self.vision_heatmap_decay_spin.value() if hasattr(self, "vision_heatmap_decay_spin") else 0.92
        radius = self.vision_heatmap_radius_spin.value() if hasattr(self, "vision_heatmap_radius_spin") else 42
        self.vision_heatmap *= float(decay)
        for detection in detections:
            center = detection.get("center", [width // 2, height // 2])
            confidence = float(detection.get("confidence", 0.5))
            cx = int(max(0, min(width - 1, center[0])))
            cy = int(max(0, min(height - 1, center[1])))
            intensity = max(0.20, min(2.00, 0.40 + confidence))
            cv2.circle(self.vision_heatmap, (cx, cy), radius, intensity, thickness=-1)
        self.vision_last_heatmap_peak = float(np.max(self.vision_heatmap)) if self.vision_heatmap is not None else 0.0

    def _render_vision_heatmap(self):
        if self.vision_heatmap is None or self.vision_heatmap.size == 0:
            return None
        cv2 = _cv2()
        np = _np()
        peak = float(np.max(self.vision_heatmap))
        if peak <= 0:
            return None
        normalized = np.clip(self.vision_heatmap / peak, 0.0, 1.0)
        heatmap_gray = np.uint8(normalized * 255.0)
        heatmap_color = cv2.applyColorMap(heatmap_gray, cv2.COLORMAP_TURBO)
        if self.vision_last_frame is not None and self.vision_last_frame.shape[:2] == heatmap_color.shape[:2]:
            return cv2.addWeighted(self.vision_last_frame, 0.30, heatmap_color, 0.70, 0.0)
        return heatmap_color

    def _set_scaled_preview_label(self, label: QLabel, frame, empty_text: str):
        if frame is None:
            label.setText(empty_text)
            label.setPixmap(QPixmap())
            return
        cv2 = _cv2()
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        height, width, channels = rgb.shape
        image = QImage(rgb.data, width, height, channels * width, QImage.Format_RGB888)
        pixmap = QPixmap.fromImage(image)
        target = label.size()
        scaled = pixmap.scaled(max(1, target.width()), max(1, target.height()), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        label.setText("")
        label.setPixmap(scaled)

    def _set_vision_heatmap_preview(self, frame):
        if hasattr(self, "vision_heatmap_label"):
            self._set_scaled_preview_label(self.vision_heatmap_label, frame, "Heatmap will appear after analysis")

    def _refresh_vision_history_widgets(self):
        if not hasattr(self, "vision_history_list"):
            return
        current_row = self.vision_history_list.currentRow()
        self.vision_history_list.blockSignals(True)
        self.vision_history_list.clear()
        for entry in self.vision_session_history:
            self.vision_history_list.addItem(
                f"{entry['timestamp']} | {entry['detections']} target(s) | {entry['backend']}"
            )
        self.vision_history_list.blockSignals(False)
        if self.vision_session_history:
            target_row = 0 if current_row < 0 else min(current_row, len(self.vision_session_history) - 1)
            self.vision_history_list.setCurrentRow(target_row)
            self.update_vision_session_detail(target_row)
        else:
            self.update_vision_session_detail(-1)

    def _record_vision_session_entry(self, analysis: dict):
        entry = {
            "timestamp": time.strftime("%H:%M:%S"),
            "summary": analysis.get("summary", "No analysis"),
            "backend": analysis.get("detector_label", self._vision_detector_name()),
            "capture_size": analysis.get("capture_size", "N/A"),
            "detections": len(analysis.get("detections", [])),
            "ocr_found": bool(analysis.get("ocr_text", "").strip()),
            "inference_ms": round(float(analysis.get("inference_ms", 0.0)), 2),
            "source_mode": self.vision_source_selector.currentData() if hasattr(self, "vision_source_selector") else "region",
        }
        self.vision_session_history.insert(0, entry)
        limit = self.vision_history_limit_spin.value() if hasattr(self, "vision_history_limit_spin") else self.vision_session_limit
        self.vision_session_limit = limit
        del self.vision_session_history[limit:]
        self._refresh_vision_history_widgets()

    def update_vision_session_detail(self, row: int):
        if not hasattr(self, "vision_history_detail_label"):
            return
        if row < 0 or row >= len(self.vision_session_history):
            self.vision_history_detail_label.setText("No session history yet.")
            return
        entry = self.vision_session_history[row]
        self.vision_history_detail_label.setText(
            f"{entry['timestamp']} | {entry['summary']} | size={entry['capture_size']} | "
            f"detections={entry['detections']} | ocr={'yes' if entry['ocr_found'] else 'no'} | "
            f"inference={entry['inference_ms']:.1f} ms"
        )

    def clear_vision_session_history(self):
        self.vision_session_history.clear()
        self._refresh_vision_history_widgets()
        self._sync_vision_lab_state()
        self.set_status("Vision session history cleared")

    def export_vision_session_history(self):
        filename, _ = QFileDialog.getSaveFileName(self, "Export Vision Session History", "vision_session_history.json", "JSON Files (*.json)")
        if not filename:
            return
        with open(filename, "w", encoding="utf-8") as handle:
            json.dump(self.vision_session_history, handle, indent=2)
        self.set_status(f"Vision session history exported: {os.path.basename(filename)}")

    def export_vision_heatmap(self):
        frame = self._render_vision_heatmap()
        if frame is None:
            QMessageBox.information(self, "Vision Lab", "No heatmap data is available yet.")
            return
        filename, _ = QFileDialog.getSaveFileName(self, "Export Vision Heatmap", "vision_heatmap.png", "PNG Files (*.png)")
        if not filename:
            return
        cv2 = _cv2()
        cv2.imwrite(filename, frame)
        self.set_status(f"Vision heatmap exported: {os.path.basename(filename)}")

    def apply_vision_preset(self):
        if not hasattr(self, "vision_preset_selector"):
            return
        preset_name = self.vision_preset_selector.currentText()
        profile = self.vision_preset_profiles.get(preset_name)
        if profile is None:
            return
        self.vision_selected_preset = preset_name
        self._apply_vision_profile(profile)
        self.set_status(f"Vision preset applied: {preset_name}")

    def save_vision_preset(self):
        preset_name, accepted = QInputDialog.getText(self, "Save Vision Preset", "Preset name:")
        preset_name = preset_name.strip()
        if not accepted or not preset_name:
            return
        self.vision_custom_presets[preset_name] = self._current_vision_profile()
        self.vision_selected_preset = preset_name
        self._rebuild_vision_preset_profiles(preset_name)
        self.set_status(f"Vision preset saved: {preset_name}")

    def delete_vision_preset(self):
        if not hasattr(self, "vision_preset_selector"):
            return
        preset_name = self.vision_preset_selector.currentText()
        if preset_name in self.vision_builtin_presets:
            QMessageBox.information(self, "Vision Lab", "Built-in presets cannot be deleted.")
            return
        if preset_name not in self.vision_custom_presets:
            return
        del self.vision_custom_presets[preset_name]
        self._rebuild_vision_preset_profiles("Balanced")
        self.set_status(f"Vision preset deleted: {preset_name}")

    def _vision_obs_client_factory(self):
        if self._optional_module_available("obsws_python"):
            import obsws_python

            return ("obsws_python", obsws_python.ReqClient)
        return (None, None)

    def _vision_region_preset(self, width: int, height: int):
        self.region_w.setText(str(width))
        self.region_h.setText(str(height))
        self.vision_last_capture_size = f"{width} x {height}"
        self._sync_vision_lab_state()

    def _release_vision_media(self):
        if self.vision_media_capture is not None:
            try:
                self.vision_media_capture.release()
            except Exception:
                pass
        self.vision_media_capture = None
        self.vision_media_image = None
        self.vision_media_kind = None
        self.vision_media_path = ""
        self.vision_media_total_frames = 0
        if hasattr(self, "vision_media_frame_spin"):
            self.vision_media_frame_spin.blockSignals(True)
            self.vision_media_frame_spin.setRange(0, 0)
            self.vision_media_frame_spin.setValue(0)
            self.vision_media_frame_spin.blockSignals(False)

    def _load_vision_media_frame(self, frame_index: int | None = None):
        if self.vision_media_kind == "image" and self.vision_media_image is not None:
            return self.vision_media_image.copy()
        if self.vision_media_kind != "video" or self.vision_media_capture is None:
            return None
        cv2 = _cv2()
        target_index = frame_index if frame_index is not None else 0
        target_index = max(0, min(target_index, max(0, self.vision_media_total_frames - 1)))
        self.vision_media_capture.set(cv2.CAP_PROP_POS_FRAMES, target_index)
        ok, frame = self.vision_media_capture.read()
        if not ok:
            return None
        return frame

    def _set_vision_media_frame(self, frame_index: int):
        frame = self._load_vision_media_frame(frame_index)
        if frame is None:
            return
        self.vision_last_frame = frame.copy()
        self._set_vision_preview_frame(frame)
        self.set_status(f"Loaded media frame {frame_index}")

    def open_vision_media_file(self):
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Open Vision Media",
            "",
            "Media Files (*.png *.jpg *.jpeg *.bmp *.mp4 *.avi *.mov *.mkv);;Images (*.png *.jpg *.jpeg *.bmp);;Videos (*.mp4 *.avi *.mov *.mkv)",
        )
        if not filename:
            return
        cv2 = _cv2()
        self._release_vision_media()
        suffix = Path(filename).suffix.lower()
        self.vision_media_path = filename
        if suffix in {".png", ".jpg", ".jpeg", ".bmp"}:
            image = cv2.imread(filename)
            if image is None:
                QMessageBox.warning(self, "Vision Lab", "Unable to load the selected image.")
                self._release_vision_media()
                return
            self.vision_media_image = image
            self.vision_media_kind = "image"
        else:
            capture = cv2.VideoCapture(filename)
            if not capture.isOpened():
                QMessageBox.warning(self, "Vision Lab", "Unable to load the selected video.")
                self._release_vision_media()
                return
            self.vision_media_capture = capture
            self.vision_media_kind = "video"
            self.vision_media_total_frames = max(1, int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 1))
            if hasattr(self, "vision_media_frame_spin"):
                self.vision_media_frame_spin.blockSignals(True)
                self.vision_media_frame_spin.setRange(0, max(0, self.vision_media_total_frames - 1))
                self.vision_media_frame_spin.setValue(0)
                self.vision_media_frame_spin.blockSignals(False)
        if hasattr(self, "vision_source_selector"):
            index = self.vision_source_selector.findData("file")
            if index >= 0:
                self.vision_source_selector.setCurrentIndex(index)
        self.vision_source_mode = "file"
        first_frame = self._load_vision_media_frame(0)
        if first_frame is not None:
            self._run_vision_analysis(first_frame, update_preview=True)
        self._sync_vision_lab_state()
        self.set_status(f"Vision media loaded: {Path(filename).name}")

    def clear_vision_media_file(self):
        self._release_vision_media()
        self.vision_last_frame = None
        self.vision_last_analysis = {}
        self.vision_last_dom_snapshot = {}
        self.vision_last_screen_action_map = {}
        self.vision_session_history.clear()
        self._reset_vision_heatmap_buffer(None)
        if hasattr(self, "vision_dom_summary_label"):
            self._update_vision_dom_widgets({}, {}, source_label="")
        if hasattr(self, "vision_source_selector"):
            index = self.vision_source_selector.findData("region")
            if index >= 0:
                self.vision_source_selector.setCurrentIndex(index)
        self.vision_source_mode = "region"
        self._set_vision_preview_frame(None)
        self._set_vision_heatmap_preview(None)
        if hasattr(self, "vision_report_text"):
            self.vision_report_text.setPlainText("Vision Lab Report\n\nNo analysis yet.")
        if hasattr(self, "vision_ocr_text"):
            self.vision_ocr_text.setPlainText("No OCR text detected.")
        self._update_vision_target_table([])
        self._refresh_vision_history_widgets()
        self._sync_vision_lab_state()
        self.set_status("Vision media cleared")

    def step_vision_media(self, delta: int):
        if self.vision_media_kind != "video" or not hasattr(self, "vision_media_frame_spin"):
            return
        next_value = max(0, min(self.vision_media_frame_spin.maximum(), self.vision_media_frame_spin.value() + delta))
        self.vision_media_frame_spin.setValue(next_value)

    def on_vision_media_frame_changed(self, frame_index: int):
        if self.vision_media_kind != "video":
            return
        frame = self._load_vision_media_frame(frame_index)
        if frame is None:
            return
        self.vision_last_frame = frame.copy()
        self._set_vision_preview_frame(frame)
        self._sync_vision_lab_state()

    def test_obs_connection(self):
        factory_name, factory = self._vision_obs_client_factory()
        if factory is None:
            self.vision_obs_status = "obsws_python not installed"
            self._sync_vision_lab_state()
            self.set_status("OBS capture backend is unavailable")
            return
        try:
            host = self.vision_obs_host_input.text().strip() if hasattr(self, "vision_obs_host_input") else "localhost"
            port = self.vision_obs_port_spin.value() if hasattr(self, "vision_obs_port_spin") else 4455
            password = self.vision_obs_password_input.text() if hasattr(self, "vision_obs_password_input") else ""
            client = factory(host=host, port=port, password=password, timeout=3)
            version = client.get_version()
            platform = getattr(version, "obs_version", "connected")
            self.vision_obs_client = client
            self.vision_obs_status = f"{factory_name} connected to OBS {platform}"
        except Exception as exc:
            self.vision_obs_client = None
            self.vision_obs_status = f"Connection failed: {exc}"
        self._sync_vision_lab_state()
        self.set_status(self.vision_obs_status)

    def _capture_obs_frame(self):
        if self.vision_obs_client is None:
            self.test_obs_connection()
        if self.vision_obs_client is None:
            raise RuntimeError(self.vision_obs_status)
        source_name = self.vision_obs_source_input.text().strip() if hasattr(self, "vision_obs_source_input") else ""
        if not source_name:
            raise RuntimeError("Enter an OBS source name first.")
        response = self.vision_obs_client.get_source_screenshot(source_name, "png", 1280, 720, 100)
        image_data = getattr(response, "image_data", "")
        if not image_data or "," not in image_data:
            raise RuntimeError("OBS did not return a screenshot.")
        encoded = image_data.split(",", 1)[1]
        raw = base64.b64decode(encoded)
        cv2 = _cv2()
        np = _np()
        buffer = np.frombuffer(raw, dtype=np.uint8)
        frame = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
        if frame is None:
            raise RuntimeError("Failed to decode OBS screenshot.")
        self.vision_obs_status = "Live OBS capture active"
        return frame

    def _vision_capture_region(self):
        try:
            region = self.get_game_region()
        except Exception:
            return None
        if region.get("width", 0) <= 0 or region.get("height", 0) <= 0:
            return None
        return region

    def _vision_dataset_dir(self) -> Path:
        default_dir = self.project_root / "datasets" / "vision_lab"
        if not hasattr(self, "vision_dataset_dir_input"):
            return default_dir
        value = self.vision_dataset_dir_input.text().strip()
        if not value:
            return default_dir
        path = Path(value)
        if not path.is_absolute():
            path = self.project_root / path
        return path

    def _vision_dataset_sample_count(self) -> int:
        dataset_dir = self._vision_dataset_dir()
        images_dir = dataset_dir / "images"
        if not images_dir.exists():
            return 0
        return sum(1 for path in images_dir.iterdir() if path.suffix.lower() in {".png", ".jpg", ".jpeg"})

    def _vision_detector_source(self):
        if self.pipeline_controller is not None:
            try:
                return self.pipeline_controller.vision_worker.perception_engine.detector
            except Exception:
                pass
        if self.input_manager is not None:
            game_state = getattr(self.input_manager, "game_state", None)
            if game_state is not None and hasattr(game_state, "detector"):
                return game_state.detector
        return None

    def _vision_ui_detector_source(self):
        if self.pipeline_controller is not None:
            try:
                return self.pipeline_controller.vision_worker.perception_engine.ui_detector
            except Exception:
                pass
        return None

    def _vision_ocr_reader_source(self):
        if self.pipeline_controller is not None:
            try:
                return self.pipeline_controller.vision_worker.perception_engine.ocr
            except Exception:
                pass
        if self.input_manager is not None:
            game_state = getattr(self.input_manager, "game_state", None)
            if game_state is not None and hasattr(game_state, "reader"):
                return game_state.reader
        try:
            from vision.resource_reader import ResourceReader

            return ResourceReader()
        except Exception:
            return None

    def _vision_detector_name(self) -> str:
        detector = self._vision_detector_source()
        if detector is None:
            return "UI/OCR Fallback"
        return detector.__class__.__name__

    def _extract_yolo_detections(self, results, confidence_threshold: float):
        detections = []
        if results is None:
            return detections
        boxes = getattr(results, "boxes", None)
        names = getattr(results, "names", {}) or {}
        if boxes is None:
            return detections
        for box in boxes:
            try:
                coords = box.xyxy[0].tolist()
                x1, y1, x2, y2 = [int(max(0, value)) for value in coords]
                w = max(0, x2 - x1)
                h = max(0, y2 - y1)
                confidence = float(box.conf[0]) if hasattr(box, "conf") and len(box.conf) else 0.0
                if confidence < confidence_threshold:
                    continue
                class_id = int(float(box.cls[0])) if hasattr(box, "cls") and len(box.cls) else 0
                label = names.get(class_id, f"class_{class_id}") if isinstance(names, dict) else f"class_{class_id}"
                detections.append(
                    {
                        "label": label,
                        "confidence": confidence,
                        "bbox": [x1, y1, w, h],
                        "center": [x1 + (w // 2), y1 + (h // 2)],
                        "source": "yolo",
                    }
                )
            except Exception:
                continue
        return detections

    def _ui_buttons_to_detections(self, buttons):
        detections = []
        for x, y, w, h in buttons or []:
            detections.append(
                {
                    "label": "ui_button",
                    "confidence": 0.50,
                    "bbox": [int(x), int(y), int(w), int(h)],
                    "center": [int(x + (w / 2)), int(y + (h / 2))],
                    "source": "ui",
                }
            )
        return detections

    def _rank_vision_targets(self, detections, frame_shape):
        if frame_shape is None or len(frame_shape) < 2:
            return detections
        frame_h, frame_w = frame_shape[:2]
        max_distance = max(1.0, (frame_w ** 2 + frame_h ** 2) ** 0.5)
        ranked = []
        for detection in detections:
            x, y, w, h = detection["bbox"]
            cx, cy = detection["center"]
            area_ratio = (w * h) / max(1.0, frame_w * frame_h)
            distance = ((cx - (frame_w / 2)) ** 2 + (cy - (frame_h / 2)) ** 2) ** 0.5
            center_score = max(0.0, 1.0 - (distance / max_distance))
            score = (float(detection.get("confidence", 0.0)) * 100.0) + (area_ratio * 1500.0) + (center_score * 25.0)
            enriched = dict(detection)
            enriched["rank_score"] = round(score, 2)
            ranked.append(enriched)
        ranked.sort(key=lambda item: item.get("rank_score", 0.0), reverse=True)
        limit = self.vision_target_limit_spin.value() if hasattr(self, "vision_target_limit_spin") else self.vision_target_limit
        for index, detection in enumerate(ranked[:limit], start=1):
            detection["rank"] = index
        return ranked[:limit]

    def _draw_vision_overlays(self, frame, detections, ocr_text):
        annotated = frame.copy()
        cv2 = _cv2()
        if hasattr(self, "vision_overlay_boxes_checkbox") and self.vision_overlay_boxes_checkbox.isChecked():
            for detection in detections:
                x, y, w, h = detection["bbox"]
                color = (78, 201, 176) if detection.get("source") == "ui" else (114, 255, 47)
                cv2.rectangle(annotated, (x, y), (x + w, y + h), color, 2)
                if hasattr(self, "vision_overlay_labels_checkbox") and self.vision_overlay_labels_checkbox.isChecked():
                    label = f"{detection['label']} {detection.get('confidence', 0.0):.2f}"
                    cv2.putText(annotated, label, (x, max(18, y - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)
        if hasattr(self, "vision_overlay_ocr_checkbox") and self.vision_overlay_ocr_checkbox.isChecked() and ocr_text.strip():
            for index, line in enumerate([line.strip() for line in ocr_text.splitlines() if line.strip()][:3]):
                cv2.putText(
                    annotated,
                    line[:80],
                    (12, 24 + (index * 22)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.55,
                    (217, 255, 176),
                    1,
                    cv2.LINE_AA,
                )
        return annotated

    def _set_vision_preview_frame(self, frame):
        if not hasattr(self, "vision_preview_label"):
            return
        self._set_scaled_preview_label(self.vision_preview_label, frame, "No preview yet")

    def _update_vision_target_table(self, detections):
        if not hasattr(self, "vision_target_table"):
            return
        self.vision_target_table.setRowCount(len(detections))
        for row, detection in enumerate(detections):
            x, y, w, h = detection["bbox"]
            center_x, center_y = detection["center"]
            self.vision_target_table.setItem(row, 0, QTableWidgetItem(str(detection.get("rank", row + 1))))
            self.vision_target_table.setItem(row, 1, QTableWidgetItem(detection.get("label", "target")))
            self.vision_target_table.setItem(row, 2, QTableWidgetItem(f"{float(detection.get('confidence', 0.0)):.2f}"))
            self.vision_target_table.setItem(row, 3, QTableWidgetItem(f"{center_x}, {center_y}"))
            self.vision_target_table.setItem(row, 4, QTableWidgetItem(f"{w} x {h}"))

    def _update_vision_dom_widgets(self, snapshot: dict | None, action_map: dict | None, source_label: str = ""):
        if not hasattr(self, "vision_dom_summary_label"):
            return
        snapshot = dict(snapshot or {})
        action_map = dict(action_map or {})
        self.vision_last_dom_snapshot = snapshot
        self.vision_last_screen_action_map = action_map
        merged_actions = list(action_map.get("merged_actions", []) or [])
        source_text = str(source_label or snapshot.get("url") or "DOM Snapshot").strip()
        if not snapshot and not merged_actions:
            self.vision_dom_summary_label.setText("No DOM snapshot captured yet.")
            self.vision_dom_text.setPlainText("Merged DOM and OCR action evidence will appear here.")
            self.vision_dom_action_table.setRowCount(0)
            return
        url_text = str(snapshot.get("url") or "N/A").strip()
        title_text = str(snapshot.get("title") or "Untitled").strip()
        actionable_count = int(snapshot.get("actionable_count", len(snapshot.get("actionables", []) or [])) or 0)
        screen_state = str(action_map.get("screen_state") or "unknown").strip().lower() or "unknown"
        self.vision_dom_summary_label.setText(
            f"{source_text} | state={screen_state} | DOM actionables={actionable_count} | merged actions={len(merged_actions)}"
        )
        text_lines = [
            f"Source: {source_text}",
            f"URL: {url_text}",
            f"Title: {title_text}",
            f"Viewport: {dict(snapshot.get('viewport') or {})}",
            f"Screenshot Hash: {str(snapshot.get('screenshot_hash') or '').strip() or 'N/A'}",
            "",
        ]
        text_lines.extend(str(line) for line in list(action_map.get("summary_lines", []) or []))
        raw_summary = str(snapshot.get("raw_text_summary") or "").strip()
        if raw_summary:
            text_lines.extend(["", "DOM Text Summary:", raw_summary])
        self.vision_dom_text.setPlainText("\n".join(text_lines).strip())
        self.vision_dom_action_table.setRowCount(len(merged_actions))
        for row, entry in enumerate(merged_actions):
            bounds = dict(entry.get("bounds") or {})
            self.vision_dom_action_table.setItem(row, 0, QTableWidgetItem(str(entry.get("source", "")).upper()))
            self.vision_dom_action_table.setItem(row, 1, QTableWidgetItem(str(entry.get("label", "") or "Action")))
            self.vision_dom_action_table.setItem(row, 2, QTableWidgetItem(f"{float(entry.get('score', 0.0) or 0.0):.2f}"))
            self.vision_dom_action_table.setItem(row, 3, QTableWidgetItem(str(entry.get("keyword", "") or "-")))
            self.vision_dom_action_table.setItem(
                row,
                4,
                QTableWidgetItem(
                    f"{int(bounds.get('x', 0) or 0)},{int(bounds.get('y', 0) or 0)} "
                    f"{int(bounds.get('width', 0) or 0)}x{int(bounds.get('height', 0) or 0)}"
                ),
            )
        self.vision_dom_action_table.resizeRowsToContents()

    def _format_vision_report(self, analysis):
        detections = analysis.get("detections", [])
        lines = [
            "Vision Lab Report",
            "",
            f"Preset: {self.vision_preset_selector.currentText() if hasattr(self, 'vision_preset_selector') else self.vision_selected_preset}",
            f"Detector: {analysis.get('detector_label', 'N/A')}",
            f"Capture Size: {analysis.get('capture_size', 'N/A')}",
            f"Detection Count: {len(detections)}",
            f"Inference: {analysis.get('inference_ms', 0.0):.1f} ms",
            f"Session Events: {len(self.vision_session_history)}",
            f"Heatmap Peak: {self.vision_last_heatmap_peak:.1f}",
            f"OCR Summary: {'text found' if analysis.get('ocr_text', '').strip() else 'no text detected'}",
            f"DOM Actionables: {int((analysis.get('dom_snapshot') or {}).get('actionable_count', 0) or 0)}",
            f"Merged Actions: {len(list((analysis.get('screen_action_map') or {}).get('merged_actions', []) or []))}",
            "",
            "Top Targets:",
        ]
        if detections:
            for detection in detections:
                lines.append(
                    f"- #{detection.get('rank', 0)} {detection.get('label', 'target')} "
                    f"conf={float(detection.get('confidence', 0.0)):.2f} "
                    f"center={detection.get('center')} score={detection.get('rank_score', 0.0)}"
                )
        else:
            lines.append("- No ranked targets")
        action_map = dict(analysis.get("screen_action_map") or {})
        if action_map:
            lines.extend(["", "DOM + OCR Summary:"])
            lines.extend(str(line) for line in list(action_map.get("summary_lines", []) or [])[:8])
        return "\n".join(lines)

    def _serializable_vision_analysis(self):
        analysis = dict(self.vision_last_analysis or {})
        analysis.pop("annotated_frame", None)
        analysis["heatmap_peak"] = self.vision_last_heatmap_peak
        analysis["session_events"] = len(self.vision_session_history)
        if self.vision_last_dom_snapshot:
            analysis["dom_snapshot"] = self._dom_snapshot_summary_payload(self.vision_last_dom_snapshot)
        if self.vision_last_screen_action_map:
            action_map = dict(self.vision_last_screen_action_map or {})
            action_map["dom_snapshot"] = self._dom_snapshot_summary_payload(action_map.get("dom_snapshot"))
            analysis["screen_action_map"] = action_map
        return analysis

    def _analyze_frame_for_vision_lab(self, frame, draw_preview: bool = True):
        if frame is None:
            return {
                "detections": [],
                "ocr_text": "",
                "detector_label": self._vision_detector_name(),
                "inference_ms": 0.0,
                "capture_size": "N/A",
                "summary": "No frame captured.",
            }

        start_time = time.perf_counter()
        backend = self.vision_backend_selector.currentData() if hasattr(self, "vision_backend_selector") else "auto"
        confidence_threshold = self.vision_confidence_spin.value() if hasattr(self, "vision_confidence_spin") else 0.5
        detector_label = "OCR Only"
        detections = []

        if backend in {"auto", "yolo"}:
            detector = self._vision_detector_source()
            if detector is not None:
                try:
                    detections = self._extract_yolo_detections(detector.detect(frame), confidence_threshold)
                    detector_label = detector.__class__.__name__
                except Exception as exc:
                    self._queue_log(f"Vision detector error: {exc}")
        if not detections and backend in {"auto", "ui"}:
            ui_detector = self._vision_ui_detector_source()
            if ui_detector is not None:
                try:
                    detections = self._ui_buttons_to_detections(ui_detector.detect_buttons(frame))
                    detector_label = "UI Contour Detector"
                except Exception as exc:
                    self._queue_log(f"Vision UI detector error: {exc}")

        ocr_text = ""
        if backend in {"auto", "yolo", "ui", "ocr"}:
            reader = self._vision_ocr_reader_source()
            if reader is not None:
                for method_name in ("read_text", "read"):
                    method = getattr(reader, method_name, None)
                    if callable(method):
                        try:
                            ocr_text = method(frame) or ""
                        except Exception as exc:
                            self._queue_log(f"Vision OCR error: {exc}")
                        break

        ranked = self._rank_vision_targets(detections, frame.shape)
        inference_ms = (time.perf_counter() - start_time) * 1000.0
        capture_size = f"{frame.shape[1]} x {frame.shape[0]}"
        summary = f"{len(ranked)} ranked target(s) using {detector_label}"
        annotated = self._draw_vision_overlays(frame, ranked, ocr_text) if draw_preview else frame
        return {
            "detections": ranked,
            "ocr_text": ocr_text,
            "detector_label": detector_label,
            "inference_ms": inference_ms,
            "capture_size": capture_size,
            "annotated_frame": annotated,
            "summary": summary,
        }

    def _run_vision_analysis(self, frame, update_preview: bool = True):
        analysis = self._analyze_frame_for_vision_lab(frame, draw_preview=update_preview)
        self.vision_last_frame = frame.copy() if frame is not None else None
        self.vision_last_analysis = analysis
        self.vision_last_inference_ms = analysis.get("inference_ms", 0.0)
        self.vision_last_capture_size = analysis.get("capture_size", "N/A")
        self._update_vision_heatmap(analysis.get("detections", []), frame.shape if frame is not None else None)
        self._record_vision_session_entry(analysis)
        if update_preview:
            self._set_vision_preview_frame(analysis.get("annotated_frame"))
        self._set_vision_heatmap_preview(self._render_vision_heatmap())
        if hasattr(self, "vision_report_text"):
            self.vision_report_text.setPlainText(self._format_vision_report(analysis))
        if hasattr(self, "vision_ocr_text"):
            text = analysis.get("ocr_text", "").strip()
            self.vision_ocr_text.setPlainText(text if text else "No OCR text detected.")
        self._update_vision_target_table(analysis.get("detections", []))
        self._sync_vision_lab_state()
        return analysis

    def _capture_vision_frame(self):
        from vision.screen_capture import capture_screen
        source_mode = self.vision_source_selector.currentData() if hasattr(self, "vision_source_selector") else "region"
        self.vision_source_mode = source_mode
        if source_mode == "file":
            frame_index = self.vision_media_frame_spin.value() if hasattr(self, "vision_media_frame_spin") else 0
            frame = self._load_vision_media_frame(frame_index)
            if frame is None:
                raise RuntimeError("No media file is loaded.")
            return frame
        if source_mode == "obs":
            return self._capture_obs_frame()
        return capture_screen(self._vision_capture_region())

    def start_vision_preview(self):
        if hasattr(self, "vision_interval_spin"):
            self.vision_preview_timer.setInterval(self.vision_interval_spin.value())
        self.vision_live_preview_enabled = True
        self.vision_preview_timer.start()
        self.update_vision_lab_preview()
        self.set_status("Vision Lab live preview started")

    def stop_vision_preview(self):
        self.vision_live_preview_enabled = False
        self.vision_preview_timer.stop()
        self._sync_vision_lab_state()
        self.set_status("Vision Lab live preview stopped")

    def update_vision_lab_preview(self):
        if not self.vision_live_preview_enabled:
            return
        try:
            frame = self._capture_vision_frame()
        except Exception as exc:
            self._queue_log(f"Vision capture error: {exc}")
            self.stop_vision_preview()
            return
        self.vision_preview_frames += 1
        self._run_vision_analysis(frame, update_preview=True)
        if self.vision_source_selector.currentData() == "file" and self.vision_media_kind == "video" and hasattr(self, "vision_media_frame_spin"):
            next_frame = self.vision_media_frame_spin.value() + 1
            if next_frame > self.vision_media_frame_spin.maximum():
                next_frame = 0
            self.vision_media_frame_spin.blockSignals(True)
            self.vision_media_frame_spin.setValue(next_frame)
            self.vision_media_frame_spin.blockSignals(False)

    def analyze_vision_frame(self):
        try:
            frame = self._capture_vision_frame()
        except Exception as exc:
            QMessageBox.warning(self, "Vision Lab", f"Capture failed: {exc}")
            return
        analysis = self._run_vision_analysis(frame, update_preview=True)
        self.set_status(analysis.get("summary", "Vision frame analyzed"))

    def extract_vision_actionables(self):
        try:
            frame = self.vision_last_frame if self.vision_last_frame is not None else self._capture_vision_frame()
        except Exception as exc:
            QMessageBox.warning(self, "Vision Lab", f"Actionable extraction failed: {exc}")
            return
        if frame is None:
            QMessageBox.information(self, "Vision Lab", "Analyze or capture a frame before extracting actionables.")
            return
        snapshot = self._capture_selected_worker_dom_snapshot()
        guide_analysis = self._guide_analysis_for_frame(frame, source_label="Vision Lab DOM + OCR")
        action_map = self._build_screen_action_map(snapshot, frame, guide_analysis=guide_analysis)
        serializable = self._serializable_vision_analysis()
        serializable.update(
            {
                "screen_state": str(guide_analysis.get("screen_state") or "unknown").strip().lower() or "unknown",
                "screen_label": str(guide_analysis.get("screen_label") or "Unknown").strip() or "Unknown",
                "ocr_boxes": list(guide_analysis.get("ocr_boxes", []) or []),
                "dom_snapshot": self._dom_snapshot_summary_payload(snapshot),
                "screen_action_map": action_map,
            }
        )
        self.vision_last_analysis = serializable
        self._update_vision_dom_widgets(snapshot, action_map, source_label="Vision Lab DOM + OCR")
        if hasattr(self, "vision_report_text"):
            self.vision_report_text.setPlainText(self._format_vision_report(self.vision_last_analysis))
        self._sync_vision_lab_state()
        top_label = str((((action_map or {}).get("merged_actions") or [{}])[0] or {}).get("label") or "No merged actions").strip()
        self.set_status(f"Vision actionables extracted: {top_label}")

    def capture_vision_snapshot(self):
        try:
            frame = self.vision_last_frame if self.vision_last_frame is not None else self._capture_vision_frame()
        except Exception as exc:
            QMessageBox.warning(self, "Vision Lab", f"Snapshot capture failed: {exc}")
            return
        cv2 = _cv2()
        snapshot_dir = self.project_root / "datasets" / "vision_snapshots"
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        image_path = snapshot_dir / f"vision_snapshot_{timestamp}.png"
        cv2.imwrite(str(image_path), frame)
        if self.vision_last_analysis:
            report_path = snapshot_dir / f"vision_snapshot_{timestamp}.json"
            with open(report_path, "w", encoding="utf-8") as handle:
                json.dump(self._serializable_vision_analysis(), handle, indent=2, default=str)
        self.set_status(f"Vision snapshot saved: {image_path.name}")

    def collect_vision_dataset_sample(self):
        try:
            frame = self.vision_last_frame if self.vision_last_frame is not None else self._capture_vision_frame()
        except Exception as exc:
            QMessageBox.warning(self, "Vision Lab", f"Dataset capture failed: {exc}")
            return
        analysis = self.vision_last_analysis or self._run_vision_analysis(frame, update_preview=True)
        cv2 = _cv2()
        dataset_dir = self._vision_dataset_dir()
        images_dir = dataset_dir / "images"
        labels_dir = dataset_dir / "labels"
        images_dir.mkdir(parents=True, exist_ok=True)
        labels_dir.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        image_path = images_dir / f"sample_{timestamp}.png"
        label_path = labels_dir / f"sample_{timestamp}.json"
        cv2.imwrite(str(image_path), frame)
        with open(label_path, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "capture_size": analysis.get("capture_size"),
                    "detector": analysis.get("detector_label"),
                    "detections": analysis.get("detections", []),
                    "ocr_text": analysis.get("ocr_text", ""),
                },
                handle,
                indent=2,
            )
        self._sync_vision_lab_state()
        self.set_status(f"Dataset sample saved: {image_path.name}")

    def benchmark_vision_pipeline(self):
        try:
            frame = self.vision_last_frame if self.vision_last_frame is not None else self._capture_vision_frame()
        except Exception as exc:
            QMessageBox.warning(self, "Vision Lab", f"Capture failed: {exc}")
            return
        acceleration = self.vision_acceleration_selector.currentData() if hasattr(self, "vision_acceleration_selector") else "auto"
        capabilities = self._vision_backend_capabilities()
        if acceleration == "onnx" and not capabilities["onnx"]:
            QMessageBox.information(self, "Vision Lab", "ONNX Runtime is not installed in this environment yet.")
            return
        if acceleration == "tensorrt" and not capabilities["tensorrt"]:
            QMessageBox.information(self, "Vision Lab", "TensorRT is not installed in this environment yet.")
            return
        runs = self.vision_benchmark_frames_spin.value() if hasattr(self, "vision_benchmark_frames_spin") else 10
        timings = []
        for _ in range(runs):
            analysis = self._analyze_frame_for_vision_lab(frame, draw_preview=False)
            timings.append(analysis.get("inference_ms", 0.0))
        average_ms = sum(timings) / max(1, len(timings))
        max_fps = 1000.0 / average_ms if average_ms > 0 else 0.0
        if hasattr(self, "vision_report_text"):
            existing = self.vision_report_text.toPlainText().strip()
            benchmark_text = (
                f"Benchmark: {runs} runs | profile={self.vision_acceleration_selector.currentText()} | "
                f"avg={average_ms:.1f} ms | est_fps={max_fps:.1f}"
            )
            self.vision_report_text.setPlainText(f"{existing}\n\n{benchmark_text}".strip())
        self.vision_last_inference_ms = average_ms
        self._sync_vision_lab_state()
        self.set_status(f"Vision benchmark complete: {average_ms:.1f} ms average")

    def export_vision_report(self):
        filename, _ = QFileDialog.getSaveFileName(self, "Export Vision Report", "vision_report.json", "JSON Files (*.json)")
        if not filename:
            return
        payload = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "settings": {
                "source": self.vision_source_selector.currentData() if hasattr(self, "vision_source_selector") else "region",
                "backend": self.vision_backend_selector.currentData() if hasattr(self, "vision_backend_selector") else "auto",
                "acceleration": self.vision_acceleration_selector.currentData() if hasattr(self, "vision_acceleration_selector") else "auto",
                "confidence": self.vision_confidence_spin.value() if hasattr(self, "vision_confidence_spin") else 0.5,
                "interval_ms": self.vision_interval_spin.value() if hasattr(self, "vision_interval_spin") else 700,
                "target_limit": self.vision_target_limit_spin.value() if hasattr(self, "vision_target_limit_spin") else 5,
                "preset": self.vision_preset_selector.currentText() if hasattr(self, "vision_preset_selector") else self.vision_selected_preset,
            },
            "analysis": self._serializable_vision_analysis(),
            "session_history": self.vision_session_history,
        }
        with open(filename, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, default=str)
        self.set_status(f"Vision report exported: {os.path.basename(filename)}")

    def _sync_cluster_ui_state(self):
        if not hasattr(self, "connect_cluster_btn"):
            return
        standby_snapshot = self._reconcile_browser_prewarm_pool()
        self._sync_cluster_runtime_snapshots()
        for index, worker in enumerate(self.worker_data):
            runtime = self.cluster_worker_runtimes.get(worker["id"])
            if runtime is None:
                worker["task"] = worker.get("task") or self._cluster_task_for_status(worker.get("status", "idle"))
                worker["game"] = worker.get("game") or self._current_game_label()
                worker["profile"] = worker.get("profile") or self._current_game_profile().name
                worker["strategy"] = worker.get("strategy") or self._current_game_profile().strategy
                worker["mode"] = worker.get("mode") or self._current_game_mode_label()
                worker["watch_reward_ads_enabled"] = bool(
                    worker.get("watch_reward_ads_enabled", getattr(self, "cluster_watch_ads", False))
                )
                worker["ads"] = worker.get("ads") or (
                    "Watch Reward Ads" if worker["watch_reward_ads_enabled"] else "Skip Reward Ads"
                )
                worker["learning"] = worker.get("learning") or ("enabled" if getattr(self, "cluster_auto_learning_enabled", True) else "disabled")
                worker["capture"] = worker.get("capture") or self._cluster_capture_summary()
                worker["model"] = worker.get("model") or self._cluster_model_summary()
                worker["progress"] = worker.get("progress") or self._cluster_progress_summary()
                worker["dom_drive_mode"] = worker.get("dom_drive_mode") or self._cluster_dom_drive_mode()
                worker["dom_last_action"] = worker.get("dom_last_action") or ""
                worker["dom_last_confirmation"] = worker.get("dom_last_confirmation") or ""
                worker["dom_fallback_reason"] = worker.get("dom_fallback_reason") or ""
                worker["dom_top_candidates"] = list(worker.get("dom_top_candidates") or [])
                worker["memory_limit_gb"] = max(0.5, float(worker.get("memory_limit_gb", self._cluster_worker_limit_gb())))
                worker["cpu_limit_percent"] = max(25.0, float(worker.get("cpu_limit_percent", self._cluster_worker_cpu_limit_percent())))
                cpu, mem, cpu_detail = self._cluster_usage_profile(
                    worker.get("status", "idle"),
                    worker["memory_limit_gb"],
                    worker["cpu_limit_percent"],
                )
                gpu, gpu_detail = self._cluster_gpu_usage_profile(worker.get("status", "idle"))
                worker["cpu"] = worker.get("cpu") or cpu
                worker["gpu"] = worker.get("gpu") or gpu
                worker["cpu_detail"] = worker.get("cpu_detail") or cpu_detail
                worker["gpu_detail"] = worker.get("gpu_detail") or gpu_detail
                worker["mem"] = worker.get("mem") or mem
            else:
                worker["memory_limit_gb"] = self._cluster_worker_limit_gb()
                worker["cpu_limit_percent"] = self._cluster_worker_cpu_limit_percent()
            if hasattr(self, "worker_table") and index < self.worker_table.rowCount():
                values = [
                    worker["id"],
                    worker["status"],
                    worker["task"],
                    worker["game"],
                    worker["mode"],
                    worker["cpu"],
                    worker["gpu"],
                    worker["mem"],
                ]
                for column, value in enumerate(values):
                    item = self.worker_table.item(index, column)
                    if item is None:
                        item = QTableWidgetItem()
                        self.worker_table.setItem(index, column, item)
                    item.setText(str(value))
        has_workers = bool(self.worker_data)
        selected_worker_record = self._selected_worker_record()
        selected_worker = selected_worker_record["id"] if selected_worker_record is not None else "None"
        active_workers = sum(1 for worker in self.worker_data if worker["status"] not in {"idle", "offline", "stopped"})
        avg_cpu = self._average_usage(self.worker_data, "cpu")
        avg_cpu_used = self._average_usage_used(self.worker_data, "cpu")
        avg_gpu = self._average_usage(self.worker_data, "gpu")
        avg_gpu_used = self._average_usage_used(self.worker_data, "gpu")
        avg_memory = self._average_usage(self.worker_data, "mem")
        estimated_core_share = self._total_cpu_core_share(self.worker_data)
        host_logical_cores = max(1, int(os.cpu_count() or 1))
        cpu_cap_percent = self._cluster_worker_cpu_limit_percent()
        cpu_cap_cores = cpu_cap_percent / 100.0
        target_fps = self._cluster_worker_target_fps()
        status_text = "Connected" if self.cluster_connected else "Disconnected"
        standby_status = str((standby_snapshot or {}).get("status") or "disabled").strip().lower()
        standby_detail = str((standby_snapshot or {}).get("detail") or "Background standby browser prewarm is disabled.")
        standby_label_map = {
            "disabled": "Disabled",
            "warming": "Warming hidden browser",
            "ready": "Standby ready",
            "claimed": f"Claimed by {str((standby_snapshot or {}).get('claimed_by') or 'worker').strip()}" if str((standby_snapshot or {}).get("claimed_by") or "").strip() else "Claimed",
            "rebuilding": "Incompatible, rebuilding",
            "cold": "Cold launch fallback",
            "error": "Error",
        }
        standby_card_text = standby_label_map.get(standby_status, standby_status.replace("_", " ").title() or "Disabled")
        if hasattr(self, "cluster_status_label"):
            self.cluster_status_label.setText(f"Status: {status_text}")
        self.connect_cluster_btn.setText("Disconnect Cluster" if self.cluster_connected else "Connect To Cluster")
        resumable_row, resumable_worker = self._selected_or_first_worker(self._worker_is_resumable)
        stoppable_row, stoppable_worker = self._selected_or_first_worker(self._worker_is_stoppable)
        self.start_worker_btn.setEnabled(self.cluster_connected and (resumable_worker is not None or len(self.worker_data) < self.MAX_CLUSTER_WORKERS))
        self.start_worker_btn.setText("Resume Worker" if resumable_worker is not None else "Start Worker")
        self.stop_worker_btn.setEnabled(self.cluster_connected and stoppable_worker is not None)
        self.stop_worker_btn.setText("Stop Worker")
        self.scale_up_btn.setEnabled(self.cluster_connected)
        self.scale_down_btn.setEnabled(self.cluster_connected and has_workers)
        if hasattr(self, "toggle_worker_ads_btn"):
            toggle_enabled = selected_worker_record is not None and str(
                (selected_worker_record or {}).get("mode", self._current_game_mode_label())
            ).strip().lower() == "browser"
            self.toggle_worker_ads_btn.setEnabled(toggle_enabled)
            if toggle_enabled:
                toggle_ads_enabled = bool(selected_worker_record.get("watch_reward_ads_enabled"))
                self.toggle_worker_ads_btn.setText(
                    "Disable Reward Ads" if toggle_ads_enabled else "Enable Reward Ads"
                )
            else:
                self.toggle_worker_ads_btn.setText("Toggle Reward Ads")
        if hasattr(self, "import_worker_bundle_btn"):
            self.import_worker_bundle_btn.setEnabled(True)
        if hasattr(self, "export_worker_bundle_btn"):
            self.export_worker_bundle_btn.setEnabled(self._selected_worker_record() is not None)
        if hasattr(self, "cluster_summary_label"):
            self.cluster_summary_label.setText(
                f"{status_text}. Workers: {len(self.worker_data)} / {self.MAX_CLUSTER_WORKERS}. "
                f"Busy: {active_workers}. Selected: {selected_worker}. "
                f"Budget: {self._cluster_worker_limit_gb():.1f} GB each. CPU cap: {cpu_cap_percent:.0f}% ({cpu_cap_cores:.2f} shared cores). "
                f"Target FPS: {target_fps}. Auto: {'on' if self.cluster_auto_learning_enabled else 'off'} | "
                f"Ads: {'on' if self.cluster_watch_ads else 'off'} | DOM: {self._cluster_dom_drive_mode()} | "
                f"Standby: {standby_card_text}."
            )
        if hasattr(self, "cluster_connection_value"):
            self.cluster_connection_value.setText("Connected" if self.cluster_connected else "Offline")
            self.cluster_workers_value.setText(str(len(self.worker_data)))
            self.cluster_active_value.setText(str(active_workers))
            self.cluster_standby_value.setText(standby_card_text)
            self.cluster_load_value.setText(f"{avg_cpu_used:.0f}% / {cpu_cap_percent:.0f}%")
            self.cluster_gpu_value.setText(f"{avg_gpu_used:.0f}% / 100%")
        if hasattr(self, "cluster_uptime_label"):
            self.cluster_uptime_label.setText(f"Uptime: {self._format_elapsed(self.cluster_connected_at)}")
            self.cluster_last_event_label.setText(
                f"Last Event: {self.cluster_last_event} ({self._format_elapsed(self.cluster_last_event_at)})"
            )
            self.cluster_event_count_label.setText(f"Cluster Events: {self.cluster_event_count}")
            self.cluster_worker_profile_label.setText(
                f"Worker Profile: default={self.default_cluster_workers}, max={self.MAX_CLUSTER_WORKERS}, "
                f"budget={self._cluster_worker_limit_gb():.1f} GB each | cpu cap={cpu_cap_percent:.0f}% ({cpu_cap_cores:.2f} shared cores) | "
                f"target={target_fps} fps | game={self._current_game_profile().name} | "
                f"ads={'on' if self.cluster_watch_ads else 'off'} | learning={'on' if self.cluster_auto_learning_enabled else 'off'} | "
                f"dom={self._cluster_dom_drive_mode()}"
            )
            self.cluster_standby_status_label.setText(f"Standby Browser: {standby_detail}")
            self.cluster_cpu_label.setText(
                f"Avg CPU: {avg_cpu_used:.0f}% / {cpu_cap_percent:.0f}% cap ({cpu_cap_cores:.2f} shared cores) | "
                f"{avg_cpu:.0f}% of cap | Est Share: {estimated_core_share:.1f} logical cores | "
                f"Host: {host_logical_cores} logical cores"
            )
            self.cluster_gpu_label.setText(
                f"Avg GPU: {avg_gpu_used:.0f}% / 100% | {avg_gpu:.0f}% worker average | Host: {self._host_gpu_summary()}"
            )
            self.cluster_memory_label.setText(f"Avg Memory: {avg_memory:.0f}% | Budget: {self._cluster_worker_limit_gb():.1f} GB")
            self.cluster_pipeline_events_label.setText(
                "Runtime Signals: "
                f"frames={self._pipeline_event_counts['frames']}, "
                f"vision={self._pipeline_event_counts['perceptions']}, "
                f"decisions={self._pipeline_event_counts['decisions']}, "
                f"actions={self._pipeline_event_counts['executions']}"
            )
            self.cluster_pipeline_status_label.setText(f"Pipeline: {self._pipeline_status_summary()}")
            self.cluster_ocr_status_label.setText(f"OCR: {self._ocr_status_summary()}")
            self.cluster_runtime_signal_label.setText(
                f"Last Runtime Signal: {self._pipeline_last_signal} ({self._format_elapsed(self._pipeline_last_signal_at)})"
            )
        if hasattr(self, "cluster_selected_id_label"):
            if selected_worker_record is None:
                self.cluster_selected_id_label.setText("Selected Worker: None")
                self.cluster_selected_status_label.setText("Status: N/A")
                self.cluster_selected_task_label.setText("Task: N/A")
                self.cluster_selected_game_label.setText("Game: N/A")
                self.cluster_selected_profile_label.setText("Profile: N/A")
                self.cluster_selected_mode_label.setText("Mode: N/A")
                self.cluster_selected_ads_label.setText("Ads: N/A")
                self.cluster_selected_learning_label.setText("Learning: N/A")
                self.cluster_selected_progress_label.setText("Progress: N/A")
                self.cluster_selected_strategy_label.setText("Strategy: N/A")
                self.cluster_selected_capture_label.setText("Capture: N/A")
                self.cluster_selected_model_label.setText("Model: N/A")
                self.cluster_selected_dom_mode_label.setText("DOM Drive: N/A")
                self.cluster_selected_dom_action_label.setText("DOM Last Action: N/A")
                self.cluster_selected_dom_confirmation_label.setText("DOM Confirmation: N/A")
                self.cluster_selected_dom_fallback_label.setText("DOM Fallback: N/A")
                self.cluster_selected_cpu_label.setText("CPU: N/A")
                self.cluster_selected_cpu_detail_label.setText("CPU Detail: N/A")
                self.cluster_selected_gpu_label.setText("GPU: N/A")
                self.cluster_selected_gpu_detail_label.setText("GPU Detail: N/A")
                self.cluster_selected_mem_label.setText("Memory: N/A")
            else:
                cpu_used, cpu_limit = self._parse_usage_values(selected_worker_record["cpu"])
                cpu_ratio = self._parse_usage_ratio(selected_worker_record["cpu"]) * 100.0
                mem_ratio = self._parse_usage_ratio(selected_worker_record["mem"]) * 100.0
                cpu_limit_cores = cpu_limit / 100.0
                cpu_used_cores = cpu_used / 100.0
                self.cluster_selected_id_label.setText(f"Selected Worker: {selected_worker_record['id']}")
                self.cluster_selected_status_label.setText(f"Status: {selected_worker_record['status']}")
                self.cluster_selected_task_label.setText(f"Task: {selected_worker_record.get('task', 'N/A')}")
                self.cluster_selected_game_label.setText(f"Game: {selected_worker_record.get('game', 'N/A')}")
                self.cluster_selected_profile_label.setText(f"Profile: {selected_worker_record.get('profile', 'N/A')}")
                self.cluster_selected_mode_label.setText(f"Mode: {selected_worker_record.get('mode', 'N/A')}")
                self.cluster_selected_ads_label.setText(f"Ads: {selected_worker_record.get('ads', 'N/A')}")
                self.cluster_selected_learning_label.setText(f"Learning: {selected_worker_record.get('learning', 'N/A')}")
                self.cluster_selected_progress_label.setText(f"Progress: {selected_worker_record.get('progress', 'N/A')}")
                self.cluster_selected_strategy_label.setText(f"Strategy: {selected_worker_record.get('strategy', 'N/A')}")
                self.cluster_selected_capture_label.setText(f"Capture: {selected_worker_record.get('capture', 'N/A')}")
                self.cluster_selected_model_label.setText(f"Model: {selected_worker_record.get('model', 'N/A')}")
                dom_candidates = list(selected_worker_record.get("dom_top_candidates", []) or [])
                top_dom = ", ".join(
                    str(item.get("label", "")).strip()
                    for item in dom_candidates[:3]
                    if str(item.get("label", "")).strip()
                )
                self.cluster_selected_dom_mode_label.setText(f"DOM Drive: {selected_worker_record.get('dom_drive_mode', 'legacy')}")
                self.cluster_selected_dom_action_label.setText(
                    f"DOM Last Action: {selected_worker_record.get('dom_last_action', 'N/A') or 'N/A'}"
                )
                self.cluster_selected_dom_confirmation_label.setText(
                    f"DOM Confirmation: {selected_worker_record.get('dom_last_confirmation', 'N/A') or 'N/A'}"
                )
                self.cluster_selected_dom_fallback_label.setText(
                    f"DOM Fallback: {selected_worker_record.get('dom_fallback_reason', '') or top_dom or 'N/A'}"
                )
                self.cluster_selected_cpu_label.setText(
                    f"CPU: {cpu_used:.0f}% / {cpu_limit:.0f}% cap ({cpu_used_cores:.2f}/{cpu_limit_cores:.2f} shared cores, {cpu_ratio:.0f}% of cap)"
                )
                self.cluster_selected_cpu_detail_label.setText(
                    f"CPU Detail: {selected_worker_record.get('cpu_detail', 'No CPU telemetry yet.')}"
                )
                self.cluster_selected_gpu_label.setText(
                    f"GPU: {selected_worker_record.get('gpu', '0/100%')}"
                )
                self.cluster_selected_gpu_detail_label.setText(
                    f"GPU Detail: {selected_worker_record.get('gpu_detail', 'No GPU telemetry yet.')}"
                )
                self.cluster_selected_mem_label.setText(
                    f"Memory: {selected_worker_record['mem']} ({mem_ratio:.0f}%) | Limit: "
                    f"{float(selected_worker_record.get('memory_limit_gb', self._cluster_worker_limit_gb())):.1f} GB"
                )

    def _selected_worker_row(self) -> int:
        if not hasattr(self, "worker_table"):
            return -1
        selected_ranges = self.worker_table.selectedRanges()
        if not selected_ranges:
            return -1
        return selected_ranges[0].topRow()

    def _selected_worker_record(self):
        selected_row = self._selected_worker_row()
        if 0 <= selected_row < len(self.worker_data):
            return self.worker_data[selected_row]
        return None

    def _worker_is_resumable(self, worker: dict | None) -> bool:
        status_text = str((worker or {}).get("status", "idle") or "idle").strip().lower()
        return status_text in {"idle", "offline", "stopped", "error"}

    def _worker_is_stoppable(self, worker: dict | None) -> bool:
        status_text = str((worker or {}).get("status", "idle") or "idle").strip().lower()
        return status_text in {"running", "starting", "queued", "busy", "evaluating", "prewarming", "loading_game", "warming_capture"}

    def _selected_or_first_worker(self, predicate) -> tuple[int, dict | None]:
        selected_row = self._selected_worker_row()
        if 0 <= selected_row < len(self.worker_data):
            selected_worker = self.worker_data[selected_row]
            if predicate(selected_worker):
                return selected_row, selected_worker
        for index, worker in enumerate(self.worker_data):
            if predicate(worker):
                return index, worker
        return -1, None

    def _worker_record_by_id(self, worker_id: str):
        for worker in self.worker_data:
            if worker.get("id") == worker_id:
                return worker
        return None

    def _set_worker_reward_ads(self, worker_id: str, enabled: bool):
        worker = self._worker_record_by_id(worker_id)
        if worker is None:
            return
        enabled = bool(enabled)
        worker["watch_reward_ads_enabled"] = enabled
        worker["ads"] = "Watch Reward Ads" if enabled else "Skip Reward Ads"
        runtime = self.cluster_worker_runtimes.get(worker_id)
        should_restart = (
            runtime is not None
            and self.cluster_connected
            and str(worker.get("mode", self._current_game_mode_label())).strip().lower() == "browser"
            and str(worker.get("status", "")).strip().lower() not in {"offline", "idle", "stopped", "queued"}
        )
        if should_restart:
            self._stop_cluster_worker_runtime(worker_id)
            worker["status"] = "starting"
            worker["task"] = "Updating Reward Ad Policy"
            worker["progress"] = "Restarting worker with the new reward-ad setting"
        self.update_cluster_ui(self.worker_data, connected=self.cluster_connected)
        if should_restart:
            self._start_cluster_worker_runtime(worker_id)
        self.log_cluster_event(
            f"{worker_id} reward ads {'enabled' if enabled else 'disabled'}."
        )

    def toggle_selected_worker_ads(self):
        worker = self._selected_worker_record()
        if worker is None:
            self.log_cluster_event("Select a worker row before toggling reward ads.")
            return
        if str(worker.get("mode", self._current_game_mode_label())).strip().lower() != "browser":
            self.log_cluster_event("Reward-ad toggles only apply to browser workers.")
            return
        self._set_worker_reward_ads(
            worker["id"],
            not bool(worker.get("watch_reward_ads_enabled")),
        )

    def _remove_worker_preview_window(self, worker_id: str):
        self.worker_preview_windows.pop(worker_id, None)
        self._sync_worker_preview_timer()

    def _remove_worker_control_window(self, worker_id: str):
        self.worker_control_windows.pop(worker_id, None)
        self._set_worker_manual_control(worker_id, False)
        self._sync_worker_preview_timer()

    def _sync_worker_preview_timer(self):
        if not hasattr(self, "_worker_preview_timer"):
            return
        if self.worker_preview_windows:
            if not self._worker_preview_timer.isActive():
                self._worker_preview_timer.start()
        else:
            self._worker_preview_timer.stop()
        if hasattr(self, "_worker_control_timer"):
            if self.worker_control_windows:
                if not self._worker_control_timer.isActive():
                    self._worker_control_timer.start()
            else:
                self._worker_control_timer.stop()

    def _set_worker_manual_control(self, worker_id: str, active: bool):
        runtime = self.cluster_worker_runtimes.get(worker_id)
        if runtime is None:
            return
        setter = getattr(runtime, "set_manual_control_active", None)
        if callable(setter):
            try:
                setter(active)
            except Exception:
                pass

    def _send_worker_manual_click(self, worker_id: str, x: int, y: int, button: str = "left"):
        runtime = self.cluster_worker_runtimes.get(worker_id)
        if runtime is None:
            self.set_status(f"{worker_id} is not running yet.")
            return
        sender = getattr(runtime, "enqueue_manual_click", None)
        if not callable(sender) or not sender(x, y, button):
            self.set_status(f"Manual click is unavailable for {worker_id}.")

    def _send_worker_manual_key(self, worker_id: str, key: str):
        runtime = self.cluster_worker_runtimes.get(worker_id)
        if runtime is None:
            self.set_status(f"{worker_id} is not running yet.")
            return
        sender = getattr(runtime, "enqueue_manual_key", None)
        if not callable(sender) or not sender(key):
            self.set_status(f"Manual keyboard input is unavailable for {worker_id}.")

    def open_worker_preview(self, worker_id: str | None = None):
        worker_record = self._worker_record_by_id(worker_id) if worker_id else self._selected_worker_record()
        if worker_record is None:
            self.log_cluster_event("Select a worker row before opening live preview.")
            return
        worker_id = worker_record["id"]
        window = self.worker_preview_windows.get(worker_id)
        if window is None:
            icon = self.windowIcon() if not self.windowIcon().isNull() else None
            window = WorkerPreviewWindow(worker_id, icon=icon, on_close=self._remove_worker_preview_window, parent=self)
            self.worker_preview_windows[worker_id] = window
        self._sync_worker_preview_timer()
        self._update_single_worker_preview(worker_id)
        window.show()
        window.raise_()
        window.activateWindow()
        self.set_status(f"Opened live preview for {worker_id}")

    def open_worker_control(self, worker_id: str | None = None):
        worker_record = self._worker_record_by_id(worker_id) if worker_id else self._selected_worker_record()
        if worker_record is None:
            self.log_cluster_event("Select a browser worker row before opening interactive control.")
            return
        worker_id = worker_record["id"]
        if str(worker_record.get("mode", self._current_game_mode_label())).strip().lower() != "browser":
            self.log_cluster_event("Interactive control is only available for browser workers.")
            return
        window = self.worker_control_windows.get(worker_id)
        if window is None:
            icon = self.windowIcon() if not self.windowIcon().isNull() else None
            window = WorkerControlWindow(
                worker_id,
                icon=icon,
                on_close=self._remove_worker_control_window,
                on_click=lambda x, y, button, wid=worker_id: self._send_worker_manual_click(wid, x, y, button),
                on_key=lambda key, wid=worker_id: self._send_worker_manual_key(wid, key),
                on_capture_dom=lambda wid=worker_id: self._capture_worker_control_dom_snapshot(wid),
                on_save_evidence=lambda wid, outcome: self._save_worker_control_evidence(wid, outcome),
                parent=self,
            )
            self.worker_control_windows[worker_id] = window
        self._set_worker_manual_control(worker_id, True)
        self._sync_worker_preview_timer()
        self._update_single_worker_control(worker_id)
        window.show()
        window.raise_()
        window.activateWindow()
        if hasattr(window.preview_label, "setFocus"):
            window.preview_label.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
        self.set_status(f"Opened interactive control for {worker_id}")

    def close_worker_preview(self, worker_id: str):
        window = self.worker_preview_windows.pop(worker_id, None)
        if window is not None:
            window.on_close = None
            window.close()
        self._sync_worker_preview_timer()

    def close_worker_control(self, worker_id: str):
        window = self.worker_control_windows.pop(worker_id, None)
        self._set_worker_manual_control(worker_id, False)
        if window is not None:
            window.on_close = None
            window.close()
        self._sync_worker_preview_timer()

    def _close_all_worker_previews(self):
        for worker_id in list(self.worker_preview_windows.keys()):
            self.close_worker_preview(worker_id)

    def _close_all_worker_controls(self):
        for worker_id in list(self.worker_control_windows.keys()):
            self.close_worker_control(worker_id)

    def _preview_payload_for_worker(self, worker_id: str, worker_record: dict, window, tier: str = "preview"):
        worker_record = self._worker_record_by_id(worker_id)
        if worker_record is None:
            return None
        runtime = self.cluster_worker_runtimes.get(worker_id)
        last_capture_token = window.current_capture_token() if hasattr(window, "current_capture_token") else None
        return runtime.preview_payload(last_capture_token, tier=tier) if runtime is not None else {
            "frame": None,
            "snapshot": {
                "status": worker_record.get("status", "offline"),
                "task": worker_record.get("task", "Waiting For Work"),
                "progress": worker_record.get("progress", "No progress yet"),
                "capture": worker_record.get("capture", "Capture unavailable"),
                "game": worker_record.get("game", self._current_game_label()),
                "profile": worker_record.get("profile", self._current_game_profile().name),
                "strategy": worker_record.get("strategy", self._current_game_profile().strategy),
                "mode": worker_record.get("mode", self._current_game_mode_label()),
                "ads": worker_record.get("ads", "Skip Reward Ads"),
                "learning": worker_record.get("learning", "enabled"),
                "gpu": worker_record.get("gpu", "0/100%"),
                "gpu_detail": worker_record.get("gpu_detail", "No GPU telemetry yet."),
                "last_error": "",
            },
            "captured_at": None,
            "fps": 0.0,
            "source_size": None,
            "logical_size": None,
            "preview_tier": tier,
        }

    def _update_single_worker_preview(self, worker_id: str):
        window = self.worker_preview_windows.get(worker_id)
        if window is None:
            return
        worker_record = self._worker_record_by_id(worker_id)
        if worker_record is None:
            self.close_worker_preview(worker_id)
            return
        payload = self._preview_payload_for_worker(worker_id, worker_record, window, tier="preview")
        if payload is not None:
            window.update_preview(payload, worker_record)

    def _update_single_worker_control(self, worker_id: str):
        window = self.worker_control_windows.get(worker_id)
        if window is None:
            return
        worker_record = self._worker_record_by_id(worker_id)
        if worker_record is None:
            self.close_worker_control(worker_id)
            return
        payload = self._preview_payload_for_worker(worker_id, worker_record, window, tier="control")
        if payload is not None:
            window.update_preview(payload, worker_record)

    def _update_worker_preview_windows(self):
        if not self.worker_preview_windows and not self.worker_control_windows:
            self._sync_worker_preview_timer()
            return
        active_ids = {worker.get("id") for worker in self.worker_data}
        for worker_id in [wid for wid in self.worker_preview_windows.keys() if wid not in active_ids]:
            self.close_worker_preview(worker_id)
        for worker_id in list(self.worker_preview_windows.keys()):
            self._update_single_worker_preview(worker_id)

    def _update_worker_control_windows(self):
        if not self.worker_control_windows and not self.worker_preview_windows:
            self._sync_worker_preview_timer()
            return
        active_ids = {worker.get("id") for worker in self.worker_data}
        for worker_id in list(self.worker_control_windows.keys()):
            if worker_id not in active_ids:
                self.close_worker_control(worker_id)
                continue
            self._update_single_worker_control(worker_id)

    def _create_worker_record(
        self,
        worker_id: str | None = None,
        status: str = "idle",
        cpu: str | None = None,
        gpu: str | None = None,
        mem: str | None = None,
        task: str | None = None,
        game: str | None = None,
        mode: str | None = None,
        capture: str | None = None,
        model: str | None = None,
        progress: str | None = None,
        profile: str | None = None,
        strategy: str | None = None,
        ads: str | None = None,
        learning: str | None = None,
        memory_limit_gb: float | None = None,
        cpu_limit_percent: float | None = None,
        cpu_detail: str | None = None,
        gpu_detail: str | None = None,
        watch_reward_ads_enabled: bool | None = None,
        dom_drive_mode: str | None = None,
        dom_last_action: str | None = None,
        dom_last_confirmation: str | None = None,
        dom_fallback_reason: str | None = None,
        dom_top_candidates: list | None = None,
    ):
        if not worker_id:
            worker_id = f"worker-{self._next_worker_index}"
            self._next_worker_index += 1
        elif worker_id.startswith("worker-"):
            suffix = worker_id.split("-", 1)[1]
            if suffix.isdigit():
                self._next_worker_index = max(self._next_worker_index, int(suffix) + 1)
        limit_gb = max(0.5, float(memory_limit_gb if memory_limit_gb is not None else self._cluster_worker_limit_gb()))
        cpu_limit = max(25.0, float(cpu_limit_percent if cpu_limit_percent is not None else self._cluster_worker_cpu_limit_percent()))
        suggested_cpu, suggested_mem, suggested_cpu_detail = self._cluster_usage_profile(status, limit_gb, cpu_limit)
        suggested_gpu, suggested_gpu_detail = self._cluster_gpu_usage_profile(status)
        if cpu is None:
            cpu = suggested_cpu
        if gpu is None:
            gpu = suggested_gpu
        if mem is None:
            mem = suggested_mem
        if cpu_detail is None:
            cpu_detail = suggested_cpu_detail
        if gpu_detail is None:
            gpu_detail = suggested_gpu_detail
        current_profile = self._current_game_profile()
        watch_reward_ads_enabled = bool(
            getattr(self, "cluster_watch_ads", False)
            if watch_reward_ads_enabled is None
            else watch_reward_ads_enabled
        )
        return {
            "id": worker_id,
            "status": status,
            "task": task or self._cluster_task_for_status(status),
            "game": game or self._current_game_label(),
            "profile": profile or current_profile.name,
            "strategy": strategy or current_profile.strategy,
            "mode": mode or self._current_game_mode_label(),
            "watch_reward_ads_enabled": watch_reward_ads_enabled,
            "ads": ads or ("Watch Reward Ads" if watch_reward_ads_enabled else "Skip Reward Ads"),
            "learning": learning or ("enabled" if getattr(self, "cluster_auto_learning_enabled", True) else "disabled"),
            "capture": capture or self._cluster_capture_summary(),
            "model": model or self._cluster_model_summary(),
            "progress": progress or self._cluster_progress_summary(),
            "dom_drive_mode": dom_drive_mode or self._cluster_dom_drive_mode(),
            "dom_last_action": dom_last_action or "",
            "dom_last_confirmation": dom_last_confirmation or "",
            "dom_fallback_reason": dom_fallback_reason or "",
            "dom_top_candidates": list(dom_top_candidates or []),
            "memory_limit_gb": limit_gb,
            "cpu_limit_percent": cpu_limit,
            "cpu": cpu,
            "gpu": gpu,
            "cpu_detail": cpu_detail,
            "gpu_detail": gpu_detail,
            "mem": mem,
        }

    def _parse_usage_values(self, value: str) -> tuple[float, float]:
        text = (value or "").replace("GB", "").replace("%", "").strip()
        if "/" not in text:
            return 0.0, 0.0
        used_text, total_text = [part.strip() for part in text.split("/", 1)]
        try:
            used_value = float(used_text)
            total_value = float(total_text)
        except ValueError:
            return 0.0, 0.0
        return used_value, total_value

    def _parse_usage_ratio(self, value: str) -> float:
        used_value, total_value = self._parse_usage_values(value)
        if total_value <= 0:
            return 0.0
        return max(0.0, min(1.0, used_value / total_value))

    def _average_usage(self, workers, field: str) -> float:
        if not workers:
            return 0.0
        return sum(self._parse_usage_ratio(worker.get(field, "")) for worker in workers) / len(workers) * 100.0

    def _average_usage_used(self, workers, field: str) -> float:
        if not workers:
            return 0.0
        return sum(self._parse_usage_values(worker.get(field, ""))[0] for worker in workers) / len(workers)

    def _total_cpu_core_share(self, workers) -> float:
        if not workers:
            return 0.0
        return sum(max(0.0, min(1.0, self._parse_usage_values(worker.get("cpu", ""))[0] / 100.0)) for worker in workers)

    def _format_elapsed(self, since):
        if since is None:
            return "N/A"
        elapsed = max(0, int(time.time() - since))
        minutes, seconds = divmod(elapsed, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours}h {minutes}m {seconds}s"
        if minutes:
            return f"{minutes}m {seconds}s"
        return f"{seconds}s"

    def _pipeline_status_summary(self):
        controller = self.pipeline_controller
        workers = getattr(controller, "workers", None) if controller is not None else None
        if not workers:
            return "No runtime pipeline attached"
        parts = []
        for worker in workers:
            status = "running" if worker.is_alive() else "idle"
            parts.append(f"{worker.__class__.__name__}:{status}")
        return ", ".join(parts)

    def _ocr_status_summary(self):
        sources = []
        if self.pipeline_controller is not None:
            try:
                sources.append(self.pipeline_controller.vision_worker.perception_engine.ocr)
            except Exception:
                pass
        if self.input_manager is not None:
            game_state = getattr(self.input_manager, "game_state", None)
            if game_state is not None and hasattr(game_state, "reader"):
                sources.append(game_state.reader)
        for source in sources:
            get_status = getattr(source, "get_status", None)
            if callable(get_status):
                status = get_status()
                return status.get("message", "OCR status unavailable")
        try:
            from vision.resource_reader import ResourceReader

            return ResourceReader().get_status().get("message", "OCR status unavailable")
        except Exception:
            pass
        return "OCR status unavailable"

    def _apply_initial_window_geometry(self):
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            self.resize(1280, 820)
            return
        available = screen.availableGeometry()
        max_width = max(720, available.width() - 24)
        max_height = max(480, available.height() - 32)
        width = min(max_width, min(1380, int(available.width() * 0.90)))
        height = min(max_height, min(860, int(available.height() * 0.86)))
        self.resize(width, height)

    def _config_section(self, section_name: str) -> dict:
        if self.config is None:
            return {}
        section = self.config.get(section_name, {})
        return section if isinstance(section, dict) else {}

    def _config_value(self, section_name: str, key: str, default=None):
        return self._config_section(section_name).get(key, default)

    def _normalize_theme_key(self, theme_value) -> str:
        text = str(theme_value or "").strip().lower()
        if text in self.THEME_DEFINITIONS:
            return text
        for key, theme in self.THEME_DEFINITIONS.items():
            if theme["label"].strip().lower() == text:
                return key
        aliases = {
            "dark": "terminal",
            "light": "native",
            "cyberpunk": "terminal",
        }
        return aliases.get(text, "terminal")

    def _cluster_worker_limit_gb(self) -> float:
        if hasattr(self, "cluster_worker_memory_spin"):
            return max(0.5, float(self.cluster_worker_memory_spin.value()))
        return max(0.5, float(getattr(self, "cluster_worker_memory_gb", 2.0)))

    def _cluster_worker_cpu_limit_percent(self) -> float:
        if hasattr(self, "cluster_worker_cpu_spin"):
            return max(25.0, min(400.0, float(self.cluster_worker_cpu_spin.value())))
        return max(25.0, min(400.0, float(getattr(self, "cluster_worker_cpu_limit_percent", 200.0))))

    def _cluster_worker_target_fps(self) -> int:
        if hasattr(self, "cluster_worker_target_fps_spin"):
            return max(10, min(60, int(self.cluster_worker_target_fps_spin.value())))
        return max(10, min(60, int(getattr(self, "cluster_worker_target_fps", 30))))

    def _cluster_browser_prewarm_enabled(self) -> bool:
        if hasattr(self, "cluster_browser_prewarm_checkbox"):
            return bool(self.cluster_browser_prewarm_checkbox.isChecked())
        return bool(getattr(self, "cluster_browser_prewarm_enabled", True))

    def _cluster_preview_target_fps(self) -> int:
        if hasattr(self, "cluster_preview_target_fps_spin"):
            return max(1, min(30, int(self.cluster_preview_target_fps_spin.value())))
        return max(1, min(30, int(getattr(self, "cluster_preview_target_fps", 10))))

    def _cluster_control_preview_target_fps(self) -> int:
        if hasattr(self, "cluster_control_preview_target_fps_spin"):
            return max(1, min(30, int(self.cluster_control_preview_target_fps_spin.value())))
        return max(1, min(30, int(getattr(self, "cluster_control_preview_target_fps", 15))))

    def _worker_fps_probe_path(self) -> Path:
        return Path(self.project_root) / "data" / "benchmarks" / "worker_fps_probe.json"

    def _worker_fps_probe_summary(self) -> str:
        path = self._worker_fps_probe_path()
        if not path.exists():
            return "No live worker FPS probe has been recorded yet."
        try:
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception:
            return "Worker FPS probe data exists but could not be read."
        avg_fps = float(payload.get("average_fps") or 0.0)
        preview_fps = float(payload.get("average_preview_fps") or 0.0)
        p5_fps = float(payload.get("p5_fps") or 0.0)
        startup_seconds = float(payload.get("startup_seconds") or 0.0)
        preview_target = int(payload.get("preview_target_fps") or self._cluster_preview_target_fps())
        recommended = int(payload.get("recommended_default_fps") or self._cluster_worker_target_fps())
        target = int(payload.get("target_fps") or self._cluster_worker_target_fps())
        return (
            f"Last live probe: target={target} fps | worker avg={avg_fps:.1f} | "
            f"worker p5={p5_fps:.1f} | preview avg={preview_fps:.1f}/{preview_target} | "
            f"ready={startup_seconds:.1f}s | recommended default={recommended}."
        )

    def _refresh_worker_fps_probe_hint(self):
        if hasattr(self, "cluster_fps_probe_label"):
            self.cluster_fps_probe_label.setText(self._worker_fps_probe_summary())

    def _cluster_gpu_enabled(self) -> bool:
        if hasattr(self, "cluster_gpu_checkbox"):
            return bool(self.cluster_gpu_checkbox.isChecked())
        return bool(getattr(self, "cluster_gpu_acceleration_enabled", False))

    def _cluster_dom_drive_mode(self) -> str:
        if hasattr(self, "cluster_dom_drive_mode_selector"):
            value = str(self.cluster_dom_drive_mode_selector.currentData() or "legacy").strip().lower()
        elif hasattr(self, "cluster_dom_mode_quick_selector"):
            value = str(self.cluster_dom_mode_quick_selector.currentData() or "legacy").strip().lower()
        else:
            value = str(getattr(self, "cluster_browser_dom_drive_mode", "legacy") or "legacy").strip().lower()
        if value not in {"legacy", "assist", "dom_live_experimental"}:
            value = "legacy"
        return value

    def _on_cluster_dom_mode_quick_changed(self):
        sender = self.sender()
        if sender is getattr(self, "cluster_dom_mode_quick_selector", None):
            value = str(self.cluster_dom_mode_quick_selector.currentData() or "legacy").strip().lower()
        elif sender is getattr(self, "cluster_dom_drive_mode_selector", None):
            value = str(self.cluster_dom_drive_mode_selector.currentData() or "legacy").strip().lower()
        else:
            value = self._cluster_dom_drive_mode()
        if value not in {"legacy", "assist", "dom_live_experimental"}:
            value = "legacy"
        if hasattr(self, "cluster_dom_drive_mode_selector") and sender is not getattr(self, "cluster_dom_drive_mode_selector", None):
            index = self.cluster_dom_drive_mode_selector.findData(value)
            if index >= 0 and self.cluster_dom_drive_mode_selector.currentIndex() != index:
                self.cluster_dom_drive_mode_selector.setCurrentIndex(index)
        if hasattr(self, "cluster_dom_mode_quick_selector") and sender is not getattr(self, "cluster_dom_mode_quick_selector", None):
            index = self.cluster_dom_mode_quick_selector.findData(value)
            if index >= 0 and self.cluster_dom_mode_quick_selector.currentIndex() != index:
                self.cluster_dom_mode_quick_selector.setCurrentIndex(index)
        self.cluster_browser_dom_drive_mode = value

    def _host_gpu_summary(self) -> str:
        info = dict(self.host_gpu_info or {})
        if not info.get("available"):
            return "GPU unavailable"
        name = str(info.get("name") or "Unknown GPU").strip()
        memory_gb = float(info.get("memory_gb") or 0.0)
        if memory_gb > 0:
            return f"{name} ({memory_gb:.1f} GB VRAM)"
        return name

    def _desired_cluster_worker_count(self) -> int:
        if hasattr(self, "cluster_default_workers_spin"):
            return min(self.MAX_CLUSTER_WORKERS, max(1, int(self.cluster_default_workers_spin.value())))
        return min(self.MAX_CLUSTER_WORKERS, max(1, int(getattr(self, "default_cluster_workers", 1))))

    def _current_game_mode_label(self) -> str:
        if hasattr(self, "browser_radio") and hasattr(self, "desktop_radio"):
            return "Browser" if self.browser_radio.isChecked() else "Desktop"
        if hasattr(self, "default_mode_selector"):
            return self.default_mode_selector.currentText() or "Browser"
        return "Browser"

    def _current_desktop_window_title(self) -> str:
        if hasattr(self, "desktop_window_input"):
            title = self.desktop_window_input.text().strip()
            if title:
                return title
        if hasattr(self, "settings_desktop_window_input"):
            return self.settings_desktop_window_input.text().strip()
        return ""

    def _current_browser_url(self) -> str:
        raw_url = self.url_input.text().strip() if hasattr(self, "url_input") else ""
        if not raw_url and hasattr(self, "settings_url_input"):
            raw_url = self.settings_url_input.text().strip()
        raw_url = raw_url or "https://lom.joynetgame.com"
        try:
            parsed = urlparse(raw_url)
            if not parsed.scheme:
                raw_url = f"https://{raw_url}"
        except Exception:
            pass
        return raw_url

    def _current_game_profile(self):
        desktop_exe = self.exe_input.text().strip() if hasattr(self, "exe_input") else ""
        if not desktop_exe and hasattr(self, "settings_exe_input"):
            desktop_exe = self.settings_exe_input.text().strip()
        return resolve_game_profile(
            self._current_game_mode_label().lower(),
            browser_url=self._current_browser_url(),
            desktop_window_title=self._current_desktop_window_title(),
            desktop_exe=desktop_exe,
        )

    def _browser_prewarm_pool(self):
        if self._browser_prewarm_pool_instance is None:
            from distributed.browser_prewarm_pool import BrowserPrewarmPool

            self._browser_prewarm_pool_instance = BrowserPrewarmPool(
                self.project_root,
                log_callback=lambda message: self._queue_log(message),
            )
        return self._browser_prewarm_pool_instance

    def _cluster_page_visible(self) -> bool:
        return str(getattr(self, "_current_page_name", "") or "").strip() == "Cluster"

    def _browser_prewarm_should_be_active(self) -> bool:
        return (
            self._cluster_page_visible()
            and self._current_game_mode_label().lower() == "browser"
            and self._cluster_browser_prewarm_enabled()
        )

    def _browser_prewarm_config(self):
        config = self._cluster_worker_config("standby-slot-1")
        config.worker_id = "standby-slot-1"
        config.standby_pool_slot = True
        config.standby_slot_id = "browser-standby-1"
        config.standby_idle_timeout_s = 90.0
        return config

    def _reconcile_browser_prewarm_pool(self):
        pool = self._browser_prewarm_pool()
        if self._browser_prewarm_should_be_active():
            pool.arm(self._browser_prewarm_config())
        else:
            pool.disarm("Background standby browser prewarm is disabled.")
        return pool.snapshot()

    def refresh_desktop_window_list(self):
        try:
            titles = _list_open_windows()
        except Exception as exc:
            self._queue_log(f"Desktop window list error: {exc}")
            titles = []
        unique_titles = []
        for title in titles:
            clean = str(title or "").strip()
            if clean and clean not in unique_titles:
                unique_titles.append(clean)
        self.desktop_window_titles = unique_titles
        selectors = [getattr(self, "desktop_window_selector", None), getattr(self, "settings_desktop_window_selector", None)]
        current_title = self._current_desktop_window_title()
        for selector in selectors:
            if selector is None:
                continue
            selector.blockSignals(True)
            selector.clear()
            selector.addItem("Select Desktop Window", "")
            for title in self.desktop_window_titles:
                selector.addItem(title, title)
            index = selector.findData(current_title)
            selector.setCurrentIndex(index if index >= 0 else 0)
            selector.blockSignals(False)
        self.set_status(f"Desktop windows refreshed: {len(self.desktop_window_titles)} found")

    def _set_desktop_window_title(self, title: str):
        clean_title = str(title or "").strip()
        if hasattr(self, "desktop_window_input"):
            self.desktop_window_input.setText(clean_title)
        if hasattr(self, "settings_desktop_window_input"):
            self.settings_desktop_window_input.setText(clean_title)
        for selector in [getattr(self, "desktop_window_selector", None), getattr(self, "settings_desktop_window_selector", None)]:
            if selector is None:
                continue
            index = selector.findData(clean_title)
            if index >= 0 and selector.currentIndex() != index:
                selector.blockSignals(True)
                selector.setCurrentIndex(index)
                selector.blockSignals(False)

    def _on_desktop_window_selected(self, *_args):
        selector = self.sender()
        if selector is None:
            return
        title = selector.currentData() or selector.currentText()
        if title and title != "Select Desktop Window":
            self._set_desktop_window_title(title)
            self.set_status(f"Desktop window selected: {title}")

    def use_selected_desktop_window_region(self):
        title = self._current_desktop_window_title()
        if not title:
            self.set_status("Select a desktop window first")
            return
        region = _get_window_region(title)
        if not region:
            QMessageBox.warning(self, "Desktop Window", "Unable to read the selected desktop window bounds.")
            return
        self.set_region_preset(region["left"], region["top"], region["width"], region["height"])
        self.set_status(f"Loaded region from desktop window: {title}")

    def _current_game_label(self) -> str:
        desktop_exe = self.exe_input.text().strip() if hasattr(self, "exe_input") else ""
        if not desktop_exe and hasattr(self, "settings_exe_input"):
            desktop_exe = self.settings_exe_input.text().strip()
        return format_game_display_name(
            self._current_game_mode_label().lower(),
            browser_url=self._current_browser_url(),
            desktop_window_title=self._current_desktop_window_title(),
            desktop_exe=desktop_exe,
        )

    def _cluster_browser_start_status(self) -> str:
        return "prewarming"

    def _cluster_capture_summary(self) -> str:
        if self._current_game_mode_label().lower() == "desktop":
            window_title = self._current_desktop_window_title()
            if window_title:
                return f"Window: {window_title}"
        return self._training_region_summary() if hasattr(self, "region_w") else "1280 x 720"

    def _cluster_progress_summary(self) -> str:
        max_steps = self.max_steps_spin.value() if hasattr(self, "max_steps_spin") else 5000
        completed = min(getattr(self, "_training_steps_completed", 0), max_steps)
        return f"{completed}/{max_steps}"

    def _cluster_progress_text_for_status(self, status: str) -> str:
        status_text = str(status or "idle").strip().lower()
        if status_text == "standby_prewarming":
            return "Warming a hidden browser session in the background"
        if status_text == "standby_ready":
            return "Hidden browser session is ready to be claimed"
        if status_text == "standby_claimed":
            return "Activating the prewarmed browser session for this worker"
        if status_text == "prewarming":
            return "Launching browser and reserving the hidden session"
        if status_text == "loading_game":
            return "Waiting for the game page to finish loading"
        if status_text == "warming_capture":
            return "Priming the streamed capture path before autoplay"
        if status_text == "queued":
            return "Waiting for shared desktop control"
        return self._cluster_progress_summary()

    def _cluster_model_summary(self) -> str:
        model_path = self._model_save_path()
        return Path(model_path).name or model_path

    def _cluster_task_for_status(self, status: str) -> str:
        status_text = str(status or "idle").lower()
        if status_text == "running":
            profile = self._current_game_profile()
            return "Running Idle Click Loop" if getattr(profile, "idle_clicker", False) else "Training Behavior Graph"
        if status_text == "standby_prewarming":
            return "Warming Hidden Browser Session"
        if status_text == "standby_ready":
            return "Standby Browser Session Ready"
        if status_text == "standby_claimed":
            return "Claiming Prewarmed Browser Session"
        if status_text == "prewarming":
            return "Prewarming Browser Worker"
        if status_text == "loading_game":
            return "Loading Browser Game"
        if status_text == "warming_capture":
            return "Warming Capture Stream"
        if status_text in {"busy", "evaluating"}:
            return "Evaluating Runtime"
        if status_text == "queued":
            return "Queued For Shared Desktop Window"
        if status_text == "error":
            return "Worker Runtime Error"
        if status_text == "offline":
            return "Offline"
        if status_text == "stopped":
            return "Stopped"
        return "Waiting For Work"

    def _cluster_usage_profile(self, status: str, memory_limit_gb: float, cpu_limit_percent: float | None = None):
        status_text = str(status or "idle").lower()
        cpu_limit = max(25.0, float(cpu_limit_percent if cpu_limit_percent is not None else self._cluster_worker_cpu_limit_percent()))
        if status_text == "running":
            cpu_ratio = 0.62
            mem_ratio = 0.58
            cpu_note = "Active gameplay loop"
        elif status_text == "prewarming":
            cpu_ratio = 0.34
            mem_ratio = 0.34
            cpu_note = "Launching isolated browser session"
        elif status_text == "standby_prewarming":
            cpu_ratio = 0.24
            mem_ratio = 0.28
            cpu_note = "Warming hidden standby browser session"
        elif status_text == "standby_ready":
            cpu_ratio = 0.10
            mem_ratio = 0.24
            cpu_note = "Prewarmed standby browser is idle"
        elif status_text == "standby_claimed":
            cpu_ratio = 0.20
            mem_ratio = 0.28
            cpu_note = "Activating claimed standby browser session"
        elif status_text == "loading_game":
            cpu_ratio = 0.30
            mem_ratio = 0.33
            cpu_note = "Waiting for game-ready markers"
        elif status_text == "warming_capture":
            cpu_ratio = 0.26
            mem_ratio = 0.31
            cpu_note = "Priming streamed capture before autoplay"
        elif status_text in {"busy", "evaluating"}:
            cpu_ratio = 0.46
            mem_ratio = 0.46
            cpu_note = "Vision or reward evaluation"
        elif status_text == "queued":
            cpu_ratio = 0.08
            mem_ratio = 0.12
            cpu_note = "Queued behind shared desktop control"
        elif status_text == "error":
            cpu_ratio = 0.05
            mem_ratio = 0.18
            cpu_note = "Recovery / error hold"
        elif status_text == "offline":
            cpu_ratio = 0.0
            mem_ratio = 0.0
            cpu_note = "Offline"
        elif status_text == "stopped":
            cpu_ratio = 0.0
            mem_ratio = 0.0
            cpu_note = "Stopped"
        else:
            cpu_ratio = 0.12
            mem_ratio = 0.22
            cpu_note = "Idle standby"
        cpu_used = min(cpu_limit, cpu_limit * cpu_ratio)
        memory_used = min(memory_limit_gb, round(memory_limit_gb * mem_ratio, 1))
        host_logical_cores = max(1, int(os.cpu_count() or 1))
        cpu_detail = (
            f"{cpu_note} | Est {cpu_used / 100.0:.2f} logical core | "
            f"Host {host_logical_cores} logical cores"
        )
        return f"{cpu_used:.0f}/{cpu_limit:.0f}%", f"{memory_used:.1f}/{memory_limit_gb:.1f} GB", cpu_detail

    def _cluster_gpu_usage_profile(self, status: str, gpu_enabled: bool | None = None):
        if self._current_game_mode_label().lower() != "browser":
            return "0/100%", "Shared desktop mode"
        enabled = self._cluster_gpu_enabled() if gpu_enabled is None else bool(gpu_enabled)
        status_text = str(status or "idle").strip().lower()
        if status_text in {"prewarming", "loading_game", "warming_capture"}:
            if enabled:
                return "0/100%", f"Preparing browser acceleration | Host GPU: {self._host_gpu_summary()}"
            return "0/100%", "Legacy browser warmup"
        if enabled:
            return "0/100%", f"Hardware acceleration armed | Host GPU: {self._host_gpu_summary()}"
        return "0/100%", "Legacy browser mode"

    def _build_cluster_worker(
        self,
        worker_id: str | None = None,
        status: str = "idle",
        task: str | None = None,
        watch_reward_ads_enabled: bool | None = None,
    ):
        limit_gb = self._cluster_worker_limit_gb()
        cpu_limit = self._cluster_worker_cpu_limit_percent()
        cpu, mem, cpu_detail = self._cluster_usage_profile(status, limit_gb, cpu_limit)
        gpu, gpu_detail = self._cluster_gpu_usage_profile(status)
        return self._create_worker_record(
            worker_id=worker_id,
            status=status,
            cpu=cpu,
            gpu=gpu,
            mem=mem,
            task=task or self._cluster_task_for_status(status),
            game=self._current_game_label(),
            mode=self._current_game_mode_label(),
            capture=self._cluster_capture_summary(),
            model=self._cluster_model_summary(),
            progress=self._cluster_progress_text_for_status(status),
            memory_limit_gb=limit_gb,
            cpu_limit_percent=cpu_limit,
            cpu_detail=cpu_detail,
            gpu_detail=gpu_detail,
            watch_reward_ads_enabled=watch_reward_ads_enabled,
        )

    def _rebalance_cluster_workers(self):
        target_count = self._desired_cluster_worker_count()
        existing = list(self.worker_data)
        workers = []
        for index in range(target_count):
            existing_worker = existing[index] if index < len(existing) else {}
            status = existing_worker.get("status", "idle")
            if not self.cluster_connected:
                status = "offline"
            workers.append(
                self._build_cluster_worker(
                    worker_id=existing_worker.get("id"),
                    status=status,
                    watch_reward_ads_enabled=existing_worker.get("watch_reward_ads_enabled"),
                )
            )
        self.update_cluster_ui(workers, connected=self.cluster_connected)

    def _default_vision_presets(self) -> dict:
        return {
            "Balanced": {
                "source_mode": "region",
                "backend": "auto",
                "acceleration": "auto",
                "confidence": 0.50,
                "interval_ms": 700,
                "target_limit": 5,
                "benchmark_runs": 20,
                "overlay_boxes": True,
                "overlay_labels": True,
                "overlay_ocr": False,
                "heatmap_decay": 0.92,
                "heatmap_radius": 42,
                "history_limit": 30,
            },
            "OCR Review": {
                "source_mode": "region",
                "backend": "ocr",
                "acceleration": "auto",
                "confidence": 0.30,
                "interval_ms": 900,
                "target_limit": 3,
                "benchmark_runs": 12,
                "overlay_boxes": False,
                "overlay_labels": False,
                "overlay_ocr": True,
                "heatmap_decay": 0.96,
                "heatmap_radius": 30,
                "history_limit": 20,
            },
            "Dataset Capture": {
                "source_mode": "region",
                "backend": "auto",
                "acceleration": "pytorch",
                "confidence": 0.40,
                "interval_ms": 500,
                "target_limit": 8,
                "benchmark_runs": 10,
                "overlay_boxes": True,
                "overlay_labels": True,
                "overlay_ocr": True,
                "heatmap_decay": 0.95,
                "heatmap_radius": 50,
                "history_limit": 40,
            },
            "Benchmark": {
                "source_mode": "region",
                "backend": "yolo",
                "acceleration": "auto",
                "confidence": 0.55,
                "interval_ms": 250,
                "target_limit": 10,
                "benchmark_runs": 50,
                "overlay_boxes": True,
                "overlay_labels": False,
                "overlay_ocr": False,
                "heatmap_decay": 0.88,
                "heatmap_radius": 58,
                "history_limit": 15,
            },
        }

    def _sanitize_vision_profile(self, profile: dict | None) -> dict:
        default_profile = self._default_vision_presets()["Balanced"]
        merged = dict(default_profile)
        if isinstance(profile, dict):
            merged.update(profile)
        merged["source_mode"] = str(merged.get("source_mode", "region")).lower()
        merged["backend"] = str(merged.get("backend", "auto")).lower()
        merged["acceleration"] = str(merged.get("acceleration", "auto")).lower()
        if merged["source_mode"] not in {"region", "obs", "file"}:
            merged["source_mode"] = "region"
        if merged["backend"] not in {"auto", "yolo", "ui", "ocr"}:
            merged["backend"] = "auto"
        if merged["acceleration"] not in {"auto", "pytorch", "onnx", "tensorrt"}:
            merged["acceleration"] = "auto"
        merged["confidence"] = max(0.05, min(1.0, float(merged.get("confidence", 0.50))))
        merged["interval_ms"] = max(100, min(5000, int(merged.get("interval_ms", 700))))
        merged["target_limit"] = max(1, min(20, int(merged.get("target_limit", 5))))
        merged["benchmark_runs"] = max(1, min(200, int(merged.get("benchmark_runs", 20))))
        merged["overlay_boxes"] = bool(merged.get("overlay_boxes", True))
        merged["overlay_labels"] = bool(merged.get("overlay_labels", True))
        merged["overlay_ocr"] = bool(merged.get("overlay_ocr", False))
        merged["heatmap_decay"] = max(0.50, min(0.995, float(merged.get("heatmap_decay", 0.92))))
        merged["heatmap_radius"] = max(8, min(180, int(merged.get("heatmap_radius", 42))))
        merged["history_limit"] = max(5, min(200, int(merged.get("history_limit", 30))))
        return merged

    def _rebuild_vision_preset_profiles(self, selected_name: str | None = None):
        self.vision_preset_profiles = dict(self.vision_builtin_presets)
        self.vision_preset_profiles.update(self.vision_custom_presets)
        if selected_name and selected_name in self.vision_preset_profiles:
            self.vision_selected_preset = selected_name
        elif self.vision_selected_preset not in self.vision_preset_profiles:
            self.vision_selected_preset = "Balanced"
        if hasattr(self, "vision_preset_selector"):
            self.vision_preset_selector.blockSignals(True)
            self.vision_preset_selector.clear()
            for preset_name in self.vision_preset_profiles:
                self.vision_preset_selector.addItem(preset_name)
            index = self.vision_preset_selector.findText(self.vision_selected_preset)
            if index >= 0:
                self.vision_preset_selector.setCurrentIndex(index)
            self.vision_preset_selector.blockSignals(False)

    def _default_settings_payload(self) -> dict:
        return {
            "general": {
                "start_on_launch": True,
                "default_page": "Training",
            },
            "training": {
                "game_mode": "browser",
                "browser_url": "https://lom.joynetgame.com",
                "desktop_exe": "C:/Games/YourGame/game.exe",
                "desktop_window_title": "",
                "region": {"x": 0, "y": 0, "width": 1280, "height": 720},
                "max_steps": 5000,
                "exploration_rate": 0.2,
            },
            "vision": {
                "detection_confidence": 0.8,
            },
            "vision_lab": {
                "source_mode": "region",
                "backend": "auto",
                "acceleration": "auto",
                "interval_ms": 700,
                "target_limit": 5,
                "dataset_dir": "datasets/vision_lab",
                "overlay_boxes": True,
                "overlay_labels": True,
                "overlay_ocr": False,
                "benchmark_runs": 20,
                "heatmap_decay": 0.92,
                "heatmap_radius": 42,
                "session_history_limit": 30,
                "selected_preset": "Balanced",
                "custom_presets": {},
                "obs_host": "localhost",
                "obs_port": 4455,
                "obs_source": "",
            },
            "guide_coach": {
                "sample_interval_seconds": 1.5,
                "last_replay_path": "",
                "checklist_progress": {},
                "calibration_host": "lom.joynetgame.com",
                "calibration_runtime": "chromium",
                "active_calibration_profile_key": "lom.joynetgame.com|browser|chromium",
                "calibration_profiles": {},
                "show_focus_masks": True,
                "last_label_target_type": "claim",
                "last_label_outcome": "missed",
            },
            "provider_hub": {
                "auto_refresh_catalog": False,
                "last_category": "all",
                "last_search": "",
                "last_selected_profile": "",
            },
            "n8n": {
                "mode": "node_managed_local",
                "port": 5678,
                "editor_url": "http://localhost:5678",
                "install_dir": "data/n8n_runtime/node_runtime",
                "data_dir": "data/n8n_runtime/user_data",
                "auto_start": False,
                "editor_mode": "embedded",
                "open_editor_externally": False,
                "last_template": "provider_summary",
                "last_installed_version": "",
                "api_key_env_var": "N8N_API_KEY",
            },
            "action_evidence": {
                "default_confirmation": "advanced",
                "export_include_dom": True,
            },
            "human_behavior": {
                "enable_random_delays": True,
                "enable_breaks": True,
                "human_mouse": True,
                "human_keyboard": True,
                "break_interval_seconds": 60,
                "break_duration_seconds": 2,
            },
            "appearance": {
                "theme": "terminal",
            },
            "cluster": {
                "default_workers": 1,
                "worker_memory_gb": 2.0,
                "worker_cpu_limit_percent": 200,
                "worker_target_fps": 30,
                "browser_prewarm_enabled": True,
                "preview_target_fps": 10,
                "control_preview_target_fps": 15,
                "gpu_acceleration_enabled": True,
                "watch_reward_ads": False,
                "auto_learning": True,
                "browser_dom_drive_mode": "legacy",
                "dom_confirmation_required": True,
                "dom_live_cooldown_ms": 850,
                "dom_live_max_repeat_attempts": 3,
                "dom_evidence_weight": 1.3,
            },
            "model": {
                "save_path": "models/ppo_model",
                "algorithm": "auto",
                "policy": "auto",
                "use_action_masking": True,
                "evaluation_episodes": 5,
            },
        }

    def _load_settings_from_config(self):
        payload = self._default_settings_payload()
        for section_name in payload:
            configured = self._config_section(section_name)
            if configured:
                payload[section_name].update(configured)
        self._settings_payload_cache = payload
        self._apply_settings_payload_to_ui(payload)
        self._schedule_n8n_autostart(payload.get("n8n", {}))

    def _apply_settings_payload_to_ui(self, payload: dict):
        general = payload.get("general", {})
        training = payload.get("training", {})
        human_behavior = payload.get("human_behavior", {})
        vision = payload.get("vision", {})
        vision_lab = payload.get("vision_lab", {})
        guide_coach = payload.get("guide_coach", {})
        provider_hub = payload.get("provider_hub", {})
        n8n = payload.get("n8n", {})
        action_evidence = payload.get("action_evidence", {})
        appearance = payload.get("appearance", {})
        cluster = payload.get("cluster", {})
        model = payload.get("model", {})
        region = training.get("region", {})

        theme_key = self._normalize_theme_key(appearance.get("theme", "terminal"))
        self.select_theme(theme_key)

        if hasattr(self, "start_on_launch_checkbox"):
            self.start_on_launch_checkbox.setChecked(bool(general.get("start_on_launch", True)))
        if hasattr(self, "default_page_selector"):
            page_name = general.get("default_page", "Training")
            index = self.default_page_selector.findText(page_name)
            if index >= 0:
                self.default_page_selector.setCurrentIndex(index)
        if hasattr(self, "default_mode_selector"):
            mode_index = self.default_mode_selector.findData(str(training.get("game_mode", "browser")).lower())
            if mode_index >= 0:
                self.default_mode_selector.setCurrentIndex(mode_index)
        if hasattr(self, "settings_url_input"):
            self.settings_url_input.setText(training.get("browser_url", "https://lom.joynetgame.com"))
        if hasattr(self, "settings_exe_input"):
            self.settings_exe_input.setText(training.get("desktop_exe", "C:/Games/YourGame/game.exe"))
        if hasattr(self, "settings_desktop_window_input"):
            self.settings_desktop_window_input.setText(training.get("desktop_window_title", ""))
        if hasattr(self, "model_path_input"):
            self.model_path_input.setText(model.get("save_path", "models/ppo_model"))
        if hasattr(self, "trainer_backend_selector"):
            index = self.trainer_backend_selector.findData(str(model.get("algorithm", "auto")).lower())
            if index >= 0:
                self.trainer_backend_selector.setCurrentIndex(index)
        if hasattr(self, "trainer_policy_selector"):
            index = self.trainer_policy_selector.findData(str(model.get("policy", "auto")).lower())
            if index >= 0:
                self.trainer_policy_selector.setCurrentIndex(index)
        if hasattr(self, "trainer_action_masking_checkbox"):
            self.trainer_action_masking_checkbox.setChecked(bool(model.get("use_action_masking", True)))
        if hasattr(self, "trainer_eval_episodes_spin"):
            self.trainer_eval_episodes_spin.setValue(max(1, int(model.get("evaluation_episodes", 5))))
        if hasattr(self, "cluster_default_workers_spin"):
            self.cluster_default_workers_spin.setValue(min(self.MAX_CLUSTER_WORKERS, max(1, int(cluster.get("default_workers", 1)))))
        if hasattr(self, "cluster_worker_memory_spin"):
            self.cluster_worker_memory_spin.setValue(max(0.5, float(cluster.get("worker_memory_gb", 2.0))))
            if hasattr(self, "cluster_worker_cpu_spin"):
                self.cluster_worker_cpu_spin.setValue(max(25, min(400, int(cluster.get("worker_cpu_limit_percent", 200)))))
            if hasattr(self, "cluster_worker_target_fps_spin"):
                self.cluster_worker_target_fps_spin.setValue(max(10, min(60, int(cluster.get("worker_target_fps", 30)))))
            if hasattr(self, "cluster_browser_prewarm_checkbox"):
                self.cluster_browser_prewarm_checkbox.setChecked(bool(cluster.get("browser_prewarm_enabled", True)))
            if hasattr(self, "cluster_preview_target_fps_spin"):
                self.cluster_preview_target_fps_spin.setValue(max(1, min(30, int(cluster.get("preview_target_fps", 10)))))
            if hasattr(self, "cluster_control_preview_target_fps_spin"):
                self.cluster_control_preview_target_fps_spin.setValue(max(1, min(30, int(cluster.get("control_preview_target_fps", 15)))))
            if hasattr(self, "cluster_gpu_checkbox"):
                self.cluster_gpu_checkbox.setChecked(bool(cluster.get("gpu_acceleration_enabled", True)))
            if hasattr(self, "cluster_watch_ads_checkbox"):
                self.cluster_watch_ads_checkbox.setChecked(bool(cluster.get("watch_reward_ads", False)))
            if hasattr(self, "cluster_dom_drive_mode_selector"):
                index = self.cluster_dom_drive_mode_selector.findData(str(cluster.get("browser_dom_drive_mode", "legacy")).lower())
                if index >= 0:
                    self.cluster_dom_drive_mode_selector.setCurrentIndex(index)
            if hasattr(self, "cluster_dom_mode_quick_selector"):
                index = self.cluster_dom_mode_quick_selector.findData(str(cluster.get("browser_dom_drive_mode", "legacy")).lower())
                if index >= 0:
                    self.cluster_dom_mode_quick_selector.setCurrentIndex(index)
            if hasattr(self, "cluster_dom_confirmation_checkbox"):
                self.cluster_dom_confirmation_checkbox.setChecked(bool(cluster.get("dom_confirmation_required", True)))
            if hasattr(self, "cluster_dom_cooldown_spin"):
                self.cluster_dom_cooldown_spin.setValue(max(150, min(5000, int(cluster.get("dom_live_cooldown_ms", 850)))))
            if hasattr(self, "cluster_dom_repeat_spin"):
                self.cluster_dom_repeat_spin.setValue(max(1, min(12, int(cluster.get("dom_live_max_repeat_attempts", 3)))))
            if hasattr(self, "cluster_dom_evidence_weight_spin"):
                self.cluster_dom_evidence_weight_spin.setValue(float(cluster.get("dom_evidence_weight", 1.3)))
        if hasattr(self, "cluster_auto_learning_checkbox"):
            self.cluster_auto_learning_checkbox.setChecked(bool(cluster.get("auto_learning", True)))
        if hasattr(self, "detection_confidence_spin"):
            self.detection_confidence_spin.setValue(float(vision.get("detection_confidence", 0.8)))
        if hasattr(self, "break_interval_spin"):
            self.break_interval_spin.setValue(max(5, int(human_behavior.get("break_interval_seconds", 60))))
        if hasattr(self, "break_duration_spin"):
            self.break_duration_spin.setValue(max(1, int(human_behavior.get("break_duration_seconds", 2))))
        if hasattr(self, "settings_max_steps_spin"):
            self.settings_max_steps_spin.setValue(max(1, int(training.get("max_steps", 5000))))
        if hasattr(self, "settings_exploration_spin"):
            self.settings_exploration_spin.setValue(float(training.get("exploration_rate", 0.2)))
        if hasattr(self, "vision_backend_selector"):
            index = self.vision_backend_selector.findData(str(vision_lab.get("backend", "auto")).lower())
            if index >= 0:
                self.vision_backend_selector.setCurrentIndex(index)
        if hasattr(self, "vision_source_selector"):
            index = self.vision_source_selector.findData(str(vision_lab.get("source_mode", "region")).lower())
            if index >= 0:
                self.vision_source_selector.setCurrentIndex(index)
        if hasattr(self, "vision_acceleration_selector"):
            index = self.vision_acceleration_selector.findData(str(vision_lab.get("acceleration", "auto")).lower())
            if index >= 0:
                self.vision_acceleration_selector.setCurrentIndex(index)
        if hasattr(self, "vision_interval_spin"):
            self.vision_interval_spin.setValue(max(100, int(vision_lab.get("interval_ms", 700))))
        if hasattr(self, "vision_target_limit_spin"):
            self.vision_target_limit_spin.setValue(max(1, int(vision_lab.get("target_limit", 5))))
        if hasattr(self, "vision_dataset_dir_input"):
            self.vision_dataset_dir_input.setText(vision_lab.get("dataset_dir", "datasets/vision_lab"))
        if hasattr(self, "vision_obs_host_input"):
            self.vision_obs_host_input.setText(vision_lab.get("obs_host", "localhost"))
        if hasattr(self, "vision_obs_port_spin"):
            self.vision_obs_port_spin.setValue(max(1, int(vision_lab.get("obs_port", 4455))))
        if hasattr(self, "vision_obs_source_input"):
            self.vision_obs_source_input.setText(vision_lab.get("obs_source", ""))
        if hasattr(self, "vision_overlay_boxes_checkbox"):
            self.vision_overlay_boxes_checkbox.setChecked(bool(vision_lab.get("overlay_boxes", True)))
        if hasattr(self, "vision_overlay_labels_checkbox"):
            self.vision_overlay_labels_checkbox.setChecked(bool(vision_lab.get("overlay_labels", True)))
        if hasattr(self, "vision_overlay_ocr_checkbox"):
            self.vision_overlay_ocr_checkbox.setChecked(bool(vision_lab.get("overlay_ocr", False)))
        if hasattr(self, "guide_coach_widget"):
            self.guide_coach_widget.set_saved_state(guide_coach)
        if hasattr(self, "vision_benchmark_frames_spin"):
            self.vision_benchmark_frames_spin.setValue(max(1, int(vision_lab.get("benchmark_runs", 20))))
        if hasattr(self, "vision_heatmap_decay_spin"):
            self.vision_heatmap_decay_spin.setValue(float(vision_lab.get("heatmap_decay", 0.92)))
        if hasattr(self, "vision_heatmap_radius_spin"):
            self.vision_heatmap_radius_spin.setValue(max(8, int(vision_lab.get("heatmap_radius", 42))))
        if hasattr(self, "vision_history_limit_spin"):
            self.vision_history_limit_spin.setValue(max(5, int(vision_lab.get("session_history_limit", 30))))
        custom_presets = vision_lab.get("custom_presets", {})
        self.vision_custom_presets = {
            name: self._sanitize_vision_profile(profile)
            for name, profile in (custom_presets.items() if isinstance(custom_presets, dict) else [])
        }
        self._rebuild_vision_preset_profiles(str(vision_lab.get("selected_preset", "Balanced")))

        if hasattr(self, "random_delay_checkbox"):
            self.random_delay_checkbox.setChecked(bool(human_behavior.get("enable_random_delays", True)))
        if hasattr(self, "breaks_checkbox"):
            self.breaks_checkbox.setChecked(bool(human_behavior.get("enable_breaks", True)))
        if hasattr(self, "human_mouse_checkbox2"):
            self.human_mouse_checkbox2.setChecked(bool(human_behavior.get("human_mouse", True)))
        if hasattr(self, "human_keyboard_checkbox2"):
            self.human_keyboard_checkbox2.setChecked(bool(human_behavior.get("human_keyboard", True)))
        if hasattr(self, "human_mouse_checkbox"):
            self.human_mouse_checkbox.setChecked(bool(human_behavior.get("human_mouse", True)))
        if hasattr(self, "human_keyboard_checkbox"):
            self.human_keyboard_checkbox.setChecked(bool(human_behavior.get("human_keyboard", True)))
        if hasattr(self, "url_input"):
            self.url_input.setText(training.get("browser_url", "https://lom.joynetgame.com"))
        if hasattr(self, "exe_input"):
            self.exe_input.setText(training.get("desktop_exe", "C:/Games/YourGame/game.exe"))
        if hasattr(self, "desktop_window_input"):
            self.desktop_window_input.setText(training.get("desktop_window_title", ""))
        if hasattr(self, "max_steps_spin"):
            self.max_steps_spin.setValue(max(1, int(training.get("max_steps", 5000))))
        if hasattr(self, "exploration_spin"):
            self.exploration_spin.setValue(float(training.get("exploration_rate", 0.2)))
        if hasattr(self, "browser_radio") and hasattr(self, "desktop_radio"):
            game_mode = str(training.get("game_mode", "browser")).lower()
            self.browser_radio.setChecked(game_mode != "desktop")
            self.desktop_radio.setChecked(game_mode == "desktop")
            self._update_mode_label()
        if hasattr(self, "region_x"):
            self.region_x.setText(str(region.get("x", 0)))
            self.region_y.setText(str(region.get("y", 0)))
            self.region_w.setText(str(region.get("width", 1280)))
            self.region_h.setText(str(region.get("height", 720)))

        self.default_cluster_workers = min(self.MAX_CLUSTER_WORKERS, max(1, int(cluster.get("default_workers", 1))))
        self.cluster_worker_memory_gb = max(0.5, float(cluster.get("worker_memory_gb", 2.0)))
        self.cluster_worker_cpu_limit_percent = max(25.0, min(400.0, float(cluster.get("worker_cpu_limit_percent", 200))))
        self.cluster_worker_target_fps = max(10, min(60, int(cluster.get("worker_target_fps", 30))))
        self.cluster_browser_prewarm_enabled = bool(cluster.get("browser_prewarm_enabled", True))
        self.cluster_preview_target_fps = max(1, min(30, int(cluster.get("preview_target_fps", 10))))
        self.cluster_control_preview_target_fps = max(1, min(30, int(cluster.get("control_preview_target_fps", 15))))
        self.cluster_gpu_acceleration_enabled = bool(cluster.get("gpu_acceleration_enabled", True))
        self.cluster_watch_ads = bool(cluster.get("watch_reward_ads", False))
        self.cluster_auto_learning_enabled = bool(cluster.get("auto_learning", True))
        self._apply_runtime_settings_from_ui()
        if hasattr(self, "guide_coach_widget"):
            self.guide_coach_widget.set_saved_state(guide_coach)
            self.guide_coach_widget.set_action_evidence_state(action_evidence)
        if hasattr(self, "provider_hub_widget"):
            self.provider_hub_widget.set_saved_state(provider_hub)
        if hasattr(self, "n8n_hub_widget"):
            self.n8n_hub_widget.set_saved_state(n8n)
        self._refresh_worker_fps_probe_hint()
        if self.isVisible():
            self.refresh_ocr_status()

    def _collect_settings_payload(self) -> dict:
        training_region = {
            "x": int(self.region_x.text()) if hasattr(self, "region_x") and self.region_x.text().lstrip("-").isdigit() else 0,
            "y": int(self.region_y.text()) if hasattr(self, "region_y") and self.region_y.text().lstrip("-").isdigit() else 0,
            "width": int(self.region_w.text()) if hasattr(self, "region_w") and self.region_w.text().lstrip("-").isdigit() else 1280,
            "height": int(self.region_h.text()) if hasattr(self, "region_h") and self.region_h.text().lstrip("-").isdigit() else 720,
        }
        return {
            "general": {
                "start_on_launch": self.start_on_launch_checkbox.isChecked() if hasattr(self, "start_on_launch_checkbox") else True,
                "default_page": self.default_page_selector.currentText() if hasattr(self, "default_page_selector") else "Training",
            },
            "training": {
                "game_mode": self.default_mode_selector.currentData() if hasattr(self, "default_mode_selector") else "browser",
                "browser_url": self.settings_url_input.text().strip() if hasattr(self, "settings_url_input") else "",
                "desktop_exe": self.settings_exe_input.text().strip() if hasattr(self, "settings_exe_input") else "",
                "desktop_window_title": (
                    self.settings_desktop_window_input.text().strip()
                    if hasattr(self, "settings_desktop_window_input")
                    else ""
                ),
                "region": training_region,
                "max_steps": self.settings_max_steps_spin.value() if hasattr(self, "settings_max_steps_spin") else 5000,
                "exploration_rate": self.settings_exploration_spin.value() if hasattr(self, "settings_exploration_spin") else 0.2,
            },
            "vision": {
                "detection_confidence": self.detection_confidence_spin.value() if hasattr(self, "detection_confidence_spin") else 0.8,
            },
            "vision_lab": {
                "source_mode": self.vision_source_selector.currentData() if hasattr(self, "vision_source_selector") else "region",
                "backend": self.vision_backend_selector.currentData() if hasattr(self, "vision_backend_selector") else "auto",
                "acceleration": self.vision_acceleration_selector.currentData() if hasattr(self, "vision_acceleration_selector") else "auto",
                "interval_ms": self.vision_interval_spin.value() if hasattr(self, "vision_interval_spin") else 700,
                "target_limit": self.vision_target_limit_spin.value() if hasattr(self, "vision_target_limit_spin") else 5,
                "dataset_dir": self.vision_dataset_dir_input.text().strip() if hasattr(self, "vision_dataset_dir_input") else "datasets/vision_lab",
                "overlay_boxes": self.vision_overlay_boxes_checkbox.isChecked() if hasattr(self, "vision_overlay_boxes_checkbox") else True,
                "overlay_labels": self.vision_overlay_labels_checkbox.isChecked() if hasattr(self, "vision_overlay_labels_checkbox") else True,
                "overlay_ocr": self.vision_overlay_ocr_checkbox.isChecked() if hasattr(self, "vision_overlay_ocr_checkbox") else False,
                "benchmark_runs": self.vision_benchmark_frames_spin.value() if hasattr(self, "vision_benchmark_frames_spin") else 20,
                "heatmap_decay": self.vision_heatmap_decay_spin.value() if hasattr(self, "vision_heatmap_decay_spin") else 0.92,
                "heatmap_radius": self.vision_heatmap_radius_spin.value() if hasattr(self, "vision_heatmap_radius_spin") else 42,
                "session_history_limit": self.vision_history_limit_spin.value() if hasattr(self, "vision_history_limit_spin") else 30,
                "selected_preset": self.vision_preset_selector.currentText() if hasattr(self, "vision_preset_selector") else self.vision_selected_preset,
                "custom_presets": self.vision_custom_presets,
                "obs_host": self.vision_obs_host_input.text().strip() if hasattr(self, "vision_obs_host_input") else "localhost",
                "obs_port": self.vision_obs_port_spin.value() if hasattr(self, "vision_obs_port_spin") else 4455,
                "obs_source": self.vision_obs_source_input.text().strip() if hasattr(self, "vision_obs_source_input") else "",
            },
            "guide_coach": (
                self.guide_coach_widget.collect_state()
                if hasattr(self, "guide_coach_widget")
                else dict((self._settings_payload_cache or {}).get("guide_coach", {}))
            ),
            "provider_hub": (
                self.provider_hub_widget.collect_state()
                if hasattr(self, "provider_hub_widget")
                else dict((self._settings_payload_cache or {}).get("provider_hub", {}))
            ),
            "n8n": (
                self.n8n_hub_widget.collect_state()
                if hasattr(self, "n8n_hub_widget")
                else dict((self._settings_payload_cache or {}).get("n8n", {}))
            ),
            "action_evidence": (
                self.guide_coach_widget.collect_action_evidence_state()
                if hasattr(self, "guide_coach_widget")
                else dict((self._settings_payload_cache or {}).get("action_evidence", {}))
            ),
            "human_behavior": {
                "enable_random_delays": self.random_delay_checkbox.isChecked() if hasattr(self, "random_delay_checkbox") else True,
                "enable_breaks": self.breaks_checkbox.isChecked() if hasattr(self, "breaks_checkbox") else True,
                "human_mouse": self.human_mouse_checkbox2.isChecked() if hasattr(self, "human_mouse_checkbox2") else True,
                "human_keyboard": self.human_keyboard_checkbox2.isChecked() if hasattr(self, "human_keyboard_checkbox2") else True,
                "break_interval_seconds": self.break_interval_spin.value() if hasattr(self, "break_interval_spin") else 60,
                "break_duration_seconds": self.break_duration_spin.value() if hasattr(self, "break_duration_spin") else 2,
            },
            "appearance": {
                "theme": self.current_theme,
            },
            "cluster": {
                "default_workers": min(self.MAX_CLUSTER_WORKERS, self.cluster_default_workers_spin.value()) if hasattr(self, "cluster_default_workers_spin") else 1,
                "worker_memory_gb": self.cluster_worker_memory_spin.value() if hasattr(self, "cluster_worker_memory_spin") else 2.0,
                "worker_cpu_limit_percent": self.cluster_worker_cpu_spin.value() if hasattr(self, "cluster_worker_cpu_spin") else 200,
                "worker_target_fps": self.cluster_worker_target_fps_spin.value() if hasattr(self, "cluster_worker_target_fps_spin") else 30,
                "browser_prewarm_enabled": self._cluster_browser_prewarm_enabled(),
                "preview_target_fps": self._cluster_preview_target_fps(),
                "control_preview_target_fps": self._cluster_control_preview_target_fps(),
                "gpu_acceleration_enabled": self._cluster_gpu_enabled(),
                "watch_reward_ads": self.cluster_watch_ads_checkbox.isChecked() if hasattr(self, "cluster_watch_ads_checkbox") else False,
                "auto_learning": self.cluster_auto_learning_checkbox.isChecked() if hasattr(self, "cluster_auto_learning_checkbox") else True,
                "browser_dom_drive_mode": self._cluster_dom_drive_mode(),
                "dom_confirmation_required": (
                    self.cluster_dom_confirmation_checkbox.isChecked() if hasattr(self, "cluster_dom_confirmation_checkbox") else True
                ),
                "dom_live_cooldown_ms": self.cluster_dom_cooldown_spin.value() if hasattr(self, "cluster_dom_cooldown_spin") else 850,
                "dom_live_max_repeat_attempts": self.cluster_dom_repeat_spin.value() if hasattr(self, "cluster_dom_repeat_spin") else 3,
                "dom_evidence_weight": self.cluster_dom_evidence_weight_spin.value() if hasattr(self, "cluster_dom_evidence_weight_spin") else 1.3,
            },
            "model": {
                "save_path": self.model_path_input.text().strip() if hasattr(self, "model_path_input") else "models/ppo_model",
                "algorithm": self.trainer_backend_selector.currentData() if hasattr(self, "trainer_backend_selector") else "auto",
                "policy": self.trainer_policy_selector.currentData() if hasattr(self, "trainer_policy_selector") else "auto",
                "use_action_masking": (
                    self.trainer_action_masking_checkbox.isChecked()
                    if hasattr(self, "trainer_action_masking_checkbox")
                    else True
                ),
                "evaluation_episodes": (
                    self.trainer_eval_episodes_spin.value()
                    if hasattr(self, "trainer_eval_episodes_spin")
                    else 5
                ),
            },
        }

    def _apply_detection_confidence(self, confidence: float):
        targets = []
        if self.pipeline_controller is not None:
            try:
                targets.append(self.pipeline_controller.vision_worker.perception_engine.detector)
            except Exception:
                pass
        if self.input_manager is not None:
            game_state = getattr(self.input_manager, "game_state", None)
            if game_state is not None and hasattr(game_state, "detector"):
                targets.append(game_state.detector)
        for detector in targets:
            model = getattr(detector, "model", None)
            overrides = getattr(model, "overrides", None)
            if isinstance(overrides, dict):
                overrides["conf"] = confidence

    def _apply_runtime_settings_from_ui(self):
        if hasattr(self, "settings_url_input") and hasattr(self, "url_input"):
            self.url_input.setText(self.settings_url_input.text())
        if hasattr(self, "settings_exe_input") and hasattr(self, "exe_input"):
            self.exe_input.setText(self.settings_exe_input.text())
        if hasattr(self, "settings_desktop_window_input") and hasattr(self, "desktop_window_input"):
            self.desktop_window_input.setText(self.settings_desktop_window_input.text())
        if hasattr(self, "settings_max_steps_spin") and hasattr(self, "max_steps_spin"):
            self.max_steps_spin.setValue(self.settings_max_steps_spin.value())
        if hasattr(self, "settings_exploration_spin") and hasattr(self, "exploration_spin"):
            self.exploration_spin.setValue(self.settings_exploration_spin.value())
            self.exploration_rate = self.settings_exploration_spin.value()
        if hasattr(self, "default_mode_selector") and hasattr(self, "browser_radio") and hasattr(self, "desktop_radio"):
            game_mode = self.default_mode_selector.currentData()
            self.browser_radio.setChecked(game_mode != "desktop")
            self.desktop_radio.setChecked(game_mode == "desktop")
            self._update_mode_label()
        self.default_cluster_workers = (
            min(self.MAX_CLUSTER_WORKERS, self.cluster_default_workers_spin.value())
            if hasattr(self, "cluster_default_workers_spin")
            else 1
        )
        self.cluster_worker_memory_gb = self._cluster_worker_limit_gb()
        self.cluster_worker_cpu_limit_percent = self._cluster_worker_cpu_limit_percent()
        self.cluster_worker_target_fps = self._cluster_worker_target_fps()
        self.cluster_browser_prewarm_enabled = self._cluster_browser_prewarm_enabled()
        self.cluster_preview_target_fps = self._cluster_preview_target_fps()
        self.cluster_control_preview_target_fps = self._cluster_control_preview_target_fps()
        self.cluster_gpu_acceleration_enabled = self._cluster_gpu_enabled()
        self.cluster_watch_ads = self.cluster_watch_ads_checkbox.isChecked() if hasattr(self, "cluster_watch_ads_checkbox") else False
        self.cluster_auto_learning_enabled = (
            self.cluster_auto_learning_checkbox.isChecked() if hasattr(self, "cluster_auto_learning_checkbox") else True
        )
        self.cluster_browser_dom_drive_mode = self._cluster_dom_drive_mode()
        self.cluster_dom_confirmation_required = (
            self.cluster_dom_confirmation_checkbox.isChecked() if hasattr(self, "cluster_dom_confirmation_checkbox") else True
        )
        self.cluster_dom_live_cooldown_ms = (
            self.cluster_dom_cooldown_spin.value() if hasattr(self, "cluster_dom_cooldown_spin") else 850
        )
        self.cluster_dom_live_max_repeat_attempts = (
            self.cluster_dom_repeat_spin.value() if hasattr(self, "cluster_dom_repeat_spin") else 3
        )
        self.cluster_dom_evidence_weight = (
            self.cluster_dom_evidence_weight_spin.value() if hasattr(self, "cluster_dom_evidence_weight_spin") else 1.3
        )
        if self.isVisible():
            self.refresh_host_gpu_info()
        elif hasattr(self, "cluster_gpu_detected_label"):
            if self._cluster_gpu_enabled():
                self.cluster_gpu_detected_label.setText("Detected GPU: probing after launch...")
            else:
                self.cluster_gpu_detected_label.setText("GPU acceleration disabled. Workers will stay in legacy browser mode.")
        for runtime in self.cluster_worker_runtimes.values():
            update_limits = getattr(runtime, "update_resource_limits", None)
            if callable(update_limits):
                update_limits(
                    memory_limit_gb=self.cluster_worker_memory_gb,
                    cpu_limit_percent=self.cluster_worker_cpu_limit_percent,
                    target_fps=self.cluster_worker_target_fps,
                )
            update_preview_settings = getattr(runtime, "update_preview_settings", None)
            if callable(update_preview_settings):
                update_preview_settings(
                    browser_prewarm_enabled=self.cluster_browser_prewarm_enabled,
                    preview_target_fps=self.cluster_preview_target_fps,
                    control_preview_target_fps=self.cluster_control_preview_target_fps,
                )
        if hasattr(self, "_worker_preview_timer"):
            self._worker_preview_timer.setInterval(max(33, int(round(1000.0 / max(1, self.cluster_preview_target_fps)))))
        if hasattr(self, "_worker_control_timer"):
            self._worker_control_timer.setInterval(
                max(33, int(round(1000.0 / max(1, self.cluster_control_preview_target_fps))))
            )
        if getattr(self, "worker_data", None) and not self.cluster_connected:
            self._rebalance_cluster_workers()
        elif getattr(self, "worker_data", None):
            self.update_cluster_ui(self.worker_data, connected=self.cluster_connected)
        if self.input_manager is not None:
            self.input_manager.break_interval = float(self.break_interval_spin.value()) if hasattr(self, "break_interval_spin") else 60.0
            self.input_manager.break_duration = float(self.break_duration_spin.value()) if hasattr(self, "break_duration_spin") else 2.0
        self._sync_antiban_settings()
        if self.ppo_trainer is not None and hasattr(self, "model_path_input"):
            model_path = self.model_path_input.text().strip() or "models/ppo_model"
            self.ppo_trainer.configure(
                save_path=model_path,
                algorithm=self.trainer_backend_selector.currentData() if hasattr(self, "trainer_backend_selector") else "auto",
                policy=self.trainer_policy_selector.currentData() if hasattr(self, "trainer_policy_selector") else "auto",
                use_action_masking=(
                    self.trainer_action_masking_checkbox.isChecked()
                    if hasattr(self, "trainer_action_masking_checkbox")
                    else True
                ),
            )
        if hasattr(self, "detection_confidence_spin"):
            self._apply_detection_confidence(float(self.detection_confidence_spin.value()))
        if hasattr(self, "vision_interval_spin"):
            self.vision_preview_timer.setInterval(self.vision_interval_spin.value())
        if hasattr(self, "vision_source_selector"):
            self.vision_source_mode = self.vision_source_selector.currentData()
        if hasattr(self, "vision_history_limit_spin"):
            self.vision_session_limit = self.vision_history_limit_spin.value()
        if hasattr(self, "vision_preset_selector"):
            self.vision_selected_preset = self.vision_preset_selector.currentText() or self.vision_selected_preset
        self._reconcile_browser_prewarm_pool()
        if self.isVisible():
            self._sync_model_dashboard_state()
            self._sync_vision_lab_state()

    def _model_save_path(self) -> str:
        if hasattr(self, "model_path_input"):
            value = self.model_path_input.text().strip()
            if value:
                return value
        if self.ppo_trainer is not None and getattr(self.ppo_trainer, "save_path", None):
            return self.ppo_trainer.save_path
        return "models/ppo_model"

    def refresh_ocr_status(self):
        status_text = self._ocr_status_summary()
        if hasattr(self, "settings_ocr_status_label"):
            self.settings_ocr_status_label.setText(f"OCR: {status_text}")
        path_text = "not detected"
        try:
            from vision.resource_reader import ResourceReader

            status = ResourceReader().get_status()
            path_text = status.get("path") or "not detected"
        except Exception:
            pass
        if hasattr(self, "settings_ocr_path_label"):
            self.settings_ocr_path_label.setText(f"OCR Path: {path_text}")
        self._sync_vision_lab_state()

    def save_application_settings(self):
        payload = self._collect_settings_payload()
        self._apply_runtime_settings_from_ui()
        if self.config is not None:
            for key, value in payload.items():
                self.config.set(key, value)
            self.config.save()
        self.set_status("Application settings saved")

    def reload_application_settings(self):
        if self.config is not None:
            self.config.load()
        self._load_settings_from_config()
        self.set_status("Application settings reloaded")

    def reset_application_settings(self):
        self._apply_settings_payload_to_ui(self._default_settings_payload())
        self.set_status("Settings reset to defaults")

    def export_runtime_snapshot(self):
        filename, _ = QFileDialog.getSaveFileName(self, "Export Runtime Snapshot", "runtime_snapshot.json", "JSON Files (*.json)")
        if not filename:
            return
        payload = self._collect_settings_payload()
        payload["runtime"] = {
            "theme": self.current_theme,
            "training_running": self.ai_running,
            "ppo_training": self.ppo_training,
            "cluster_connected": self.cluster_connected,
            "cluster_workers": self.worker_data,
            "cluster_events": self.cluster_event_count,
            "ocr_status": self._ocr_status_summary(),
            "pipeline_status": self._pipeline_status_summary(),
            "plugins": self.plugin_manager.get_plugin_summaries() if self.plugin_manager is not None else [],
        }
        with open(filename, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        self.set_status(f"Runtime snapshot exported: {os.path.basename(filename)}")

    def _selected_worker_bundle_context(self):
        worker_record = self._selected_worker_record()
        if worker_record is None:
            return None
        worker_id = str(worker_record.get("id") or "").strip()
        runtime = self.cluster_worker_runtimes.get(worker_id)
        if runtime is not None:
            persist_now = getattr(runtime, "persist_now", None)
            if callable(persist_now):
                try:
                    persist_now()
                except Exception:
                    pass
        profile_key = getattr(getattr(runtime, "game_profile", None), "key", self._current_game_profile().key)
        game_key = str(worker_record.get("game") or self._current_game_label()).strip() or self._current_game_label()
        model_path = self._model_save_path()
        return {
            "worker_id": worker_id,
            "profile_key": profile_key,
            "game_key": game_key,
            "model_path": model_path,
        }

    def export_selected_worker_bundle(self):
        context = self._selected_worker_bundle_context()
        if context is None:
            self.log_cluster_event("Select a worker row before exporting a worker bundle.")
            return
        suggested_name = _default_bundle_name(context["profile_key"], context["game_key"], context["worker_id"])
        filename, _ = QFileDialog.getSaveFileName(self, "Export Worker Bundle", suggested_name, "Worker Bundle (*.zip)")
        if not filename:
            return
        if not filename.lower().endswith(".zip"):
            filename = f"{filename}.zip"
        try:
            result = _export_worker_bundle(
                self.project_root,
                context["worker_id"],
                context["profile_key"],
                context["game_key"],
                filename,
                model_path=context["model_path"],
            )
        except Exception as exc:
            self.log_cluster_event(f"Failed to export worker bundle: {exc}")
            self.set_status("Worker bundle export failed")
            return
        self.log_cluster_event(
            f"Exported worker bundle for {context['worker_id']} -> {os.path.basename(result['bundle_path'])}."
        )
        self.set_status(f"Worker bundle exported: {os.path.basename(result['bundle_path'])}")

    def import_worker_bundle_file(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Import Worker Bundle", "", "Worker Bundle (*.zip)")
        if not filename:
            return
        worker_id_override, accepted = QInputDialog.getText(
            self,
            "Import Worker Bundle",
            "Worker ID override (leave blank to use the bundle worker ID):",
        )
        if not accepted:
            return
        try:
            result = _import_worker_bundle(
                self.project_root,
                filename,
                worker_id_override=worker_id_override.strip() or None,
            )
        except Exception as exc:
            self.log_cluster_event(f"Failed to import worker bundle: {exc}")
            self.set_status("Worker bundle import failed")
            return

        worker_id = result["worker_id"]
        existing = self._worker_record_by_id(worker_id)
        browser_mode = self._current_game_mode_label().lower() == "browser"
        active_desktop_runtime = any(runtime.is_alive() for runtime in self.cluster_worker_runtimes.values()) if not browser_mode else False
        status = "running" if self.cluster_connected and (browser_mode or not active_desktop_runtime) else ("queued" if self.cluster_connected else "idle")
        task = "Imported Worker Bundle" if status != "queued" else "Queued For Shared Desktop Window"

        if existing is None:
            imported_worker = self._build_cluster_worker(worker_id=worker_id, status=status, task=task)
            imported_worker["profile"] = str(result.get("profile_key", imported_worker.get("profile", ""))).replace("_", " ").title()
            if result.get("model_path"):
                imported_worker["model"] = Path(str(result["model_path"])).name
            self.worker_data.append(imported_worker)
            self.update_cluster_ui(self.worker_data, connected=self.cluster_connected)
            if self.cluster_connected and status == "running":
                self._start_cluster_worker_runtime(worker_id)
        else:
            was_running = worker_id in self.cluster_worker_runtimes
            if was_running:
                self._stop_cluster_worker_runtime(worker_id)
            existing["learning"] = "imported bundle"
            if result.get("model_path"):
                existing["model"] = Path(str(result["model_path"])).name
            self.update_cluster_ui(self.worker_data, connected=self.cluster_connected)
            if self.cluster_connected and (existing.get("status") == "running" or was_running):
                self._start_cluster_worker_runtime(worker_id)

        if result.get("model_path") and hasattr(self, "model_path_input"):
            imported_model_path = str(result["model_path"])
            if not Path(self._model_save_path()).exists():
                self.model_path_input.setText(imported_model_path)

        self.log_cluster_event(
            f"Imported worker bundle {os.path.basename(filename)} as {worker_id} for {result.get('profile_key', 'worker')}."
        )
        self.set_status(f"Worker bundle imported: {worker_id}")

    def load_saved_model(self):
        if self.ppo_trainer is None:
            self.set_status("PPO trainer is unavailable")
            return
        self._apply_runtime_settings_from_ui()
        try:
            loaded = self.ppo_trainer.load()
        except Exception as exc:
            self._queue_log(f"PPO load error: {exc}")
            self.set_status("Failed to load saved PPO model")
            return
        self.set_status("Saved PPO model loaded" if loaded else "No saved PPO model found")
        self._sync_model_dashboard_state()

    def save_model_checkpoint(self):
        if self.ppo_trainer is None or getattr(self.ppo_trainer, "model", None) is None:
            self.set_status("No PPO model is currently loaded")
            return
        self._apply_runtime_settings_from_ui()
        save_path = self._model_save_path()
        try:
            Path(save_path).parent.mkdir(parents=True, exist_ok=True)
            self.ppo_trainer.save_checkpoint(save_path)
        except Exception as exc:
            self._queue_log(f"PPO save error: {exc}")
            self.set_status("Failed to save PPO checkpoint")
            return
        self.set_status(f"PPO checkpoint saved: {os.path.basename(save_path)}")
        self._sync_model_dashboard_state()

    def evaluate_model_checkpoint(self):
        if self.ppo_trainer is None:
            self.set_status("PPO trainer is unavailable")
            return
        self._apply_runtime_settings_from_ui()
        episodes = self.trainer_eval_episodes_spin.value() if hasattr(self, "trainer_eval_episodes_spin") else 5
        self._ppo_status_text = "Evaluating"
        self._sync_model_dashboard_state()
        self.set_status(f"Evaluating PPO checkpoint over {episodes} episode(s)")

        def runner():
            try:
                score = self.ppo_trainer.evaluate_current_model(episodes=episodes)
            except Exception as exc:
                self._queue_log(f"PPO evaluation error: {exc}")
                self._ppo_status_text = "Idle"
                self.set_status("Failed to evaluate PPO checkpoint")
            else:
                self._queue_log(f"PPO evaluation reward: {score:.2f} over {episodes} episode(s)")
                self._ppo_status_text = "Idle"
                self.set_status(f"PPO evaluation finished: {score:.2f}")
            finally:
                self._sync_model_dashboard_state()

        threading.Thread(target=runner, daemon=True).start()

    def show_runtime_details(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Runtime Details")
        dialog.resize(840, 520)
        layout = QVBoxLayout(dialog)
        details = QTextEdit()
        details.setReadOnly(True)
        plugin_lines = []
        for plugin in (self.plugin_manager.get_plugin_summaries() if self.plugin_manager is not None else []):
            plugin_lines.append(
                f"- {plugin['name']} ({plugin['version']}) [{plugin['id']}]"
            )
        if not plugin_lines:
            plugin_lines.append("- No plugins loaded")
        details.setPlainText(
            "\n".join([
                f"{self.APP_NAME}",
                "",
                f"Theme: {self.THEME_DEFINITIONS.get(self.current_theme, {}).get('label', self.current_theme)}",
                f"Training: {'running' if self.ai_running else 'idle'}",
                f"PPO: {'training' if self.ppo_training else self._ppo_status_text.lower()}",
                f"Trainer Backend: {self.ppo_trainer.summary() if self.ppo_trainer is not None and hasattr(self.ppo_trainer, 'summary') else 'Unavailable'}",
                f"Trainer Capabilities: {self.ppo_trainer.capabilities_summary() if self.ppo_trainer is not None and hasattr(self.ppo_trainer, 'capabilities_summary') else 'Unavailable'}",
                f"Pipeline: {self._pipeline_status_summary()}",
                f"OCR: {self._ocr_status_summary()}",
                f"Cluster: {'connected' if self.cluster_connected else 'offline'} / workers={len(self.worker_data)} / events={self.cluster_event_count}",
                f"Model Path: {self._model_save_path()}",
                "",
                "Project Capabilities:",
                "- Browser and desktop automation",
                "- Drag-and-drop behavior graph editing",
                "- OCR and YOLO-backed perception",
                "- PPO training and saved model checkpoints",
                "- Plugin loading and reload support",
                "- Cluster worker control and runtime diagnostics",
                "",
                "Loaded Plugins:",
                *plugin_lines,
            ])
        )
        layout.addWidget(details)
        close_button = QPushButton("Close")
        close_button.clicked.connect(dialog.accept)
        layout.addWidget(close_button)
        dialog.exec()

    def update_plugin_details(self, current, _previous=None):
        payload = current.data(Qt.UserRole) if current is not None else None
        if not isinstance(payload, dict):
            return
        self.plugin_detail_name_label.setText(f"Name: {payload.get('name', 'Unknown')}")
        self.plugin_detail_id_label.setText(f"ID: {payload.get('id', 'N/A')}")
        self.plugin_detail_version_label.setText(f"Version: {payload.get('version', 'N/A')}")
        self.plugin_detail_description_label.setText(f"Description: {payload.get('description', 'No description provided.')}")

    def _apply_training_settings(self):
        if self.input_manager is None:
            return
        self.input_manager.mouse_enabled = self.mouse_checkbox.isChecked()
        self.input_manager.keyboard_enabled = self.keyboard_checkbox.isChecked()
        self.input_manager.game_mode = "browser" if self.browser_radio.isChecked() else "desktop"
        self._sync_antiban_settings()

    def _validated_game_region(self):
        region = self.get_game_region()
        if region["width"] <= 0 or region["height"] <= 0:
            QMessageBox.warning(self, "Region Error", "Region width and height must be greater than zero.")
            return None
        return region

    def _training_region_summary(self) -> str:
        values = []
        for widget in [getattr(self, "region_w", None), getattr(self, "region_h", None)]:
            if widget is None:
                return "1280 x 720"
            text = widget.text().strip()
            if not text.lstrip("-").isdigit():
                return "Invalid Region"
            values.append(int(text))
        return f"{values[0]} x {values[1]}"

    def _wrap_scrollable_page(self, content: QWidget):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(content)
        return scroll

    def _make_group(self, title: str):
        group = QGroupBox(title)
        layout = QVBoxLayout(group)
        layout.setContentsMargins(12, 16, 12, 12)
        layout.setSpacing(8)
        return group, layout

    def _make_section_title(self, title: str, subtitle: str):
        wrapper = QFrame()
        wrapper.setObjectName("heroCard")
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(14, 14, 14, 14)
        title_label = QLabel(title)
        title_label.setObjectName("sectionTitle")
        subtitle_label = QLabel(subtitle)
        subtitle_label.setWordWrap(True)
        subtitle_label.setObjectName("mutedLabel")
        layout.addWidget(title_label)
        layout.addWidget(subtitle_label)
        return wrapper

    def _make_stat_card(self, label_text: str, value_text: str, accent: str):
        card = QFrame()
        card.setObjectName("statCard")
        card.setStyleSheet(f"QFrame#statCard {{ border-left: 4px solid {accent}; }}")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 10)
        label = QLabel(label_text)
        label.setObjectName("mutedLabel")
        value = QLabel(value_text)
        value.setObjectName("statValue")
        layout.addWidget(label)
        layout.addWidget(value)
        return card, value

    def _build_button_grid(self, button_specs, columns: int = 3):
        widget = QWidget()
        layout = QGridLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(10)
        for index, (label, handler) in enumerate(button_specs):
            row = index // columns
            column = index % columns
            button = QPushButton(label)
            button.clicked.connect(handler)
            layout.addWidget(button, row, column)
        for column in range(columns):
            layout.setColumnStretch(column, 1)
        return widget

    def _on_nav_changed(self, row: int):
        if 0 <= row < len(self.PAGE_ORDER):
            self.navigate_to(self.PAGE_ORDER[row])

    def show_page(self, page_name: str):
        self.navigate_to(page_name)

    def navigate_to(self, page_name: str):
        if page_name not in self.PAGE_ORDER:
            return
        self._current_page_name = page_name
        if page_name != "Vision Lab" and self.vision_live_preview_enabled:
            self.stop_vision_preview()
        self._ensure_page_built(page_name)
        index = self.PAGE_ORDER.index(page_name)
        if self.sidebar.currentRow() != index:
            self.sidebar.blockSignals(True)
            self.sidebar.setCurrentRow(index)
            self.sidebar.blockSignals(False)
        self.page_stack.setCurrentIndex(index)
        self.page_title.setText(page_name)
        subtitles = {
            "Training": "Configure runtime controls, capture, and training state.",
            "Model Dashboard": "Charts, metrics, and PPO controls.",
            "Behavior Editor": "Graph editing and behavior file actions.",
            "Cluster": "Worker controls and cluster events.",
            "Vision Lab": "Live capture, inference analysis, and dataset tooling.",
            "Guide Coach": "Safe guide coaching, screen labeling, and replay review.",
            "Provider Hub": "Catalog providers, compatible APIs, prompt tools, and endpoint health notes.",
            "n8n Hub": "Manage the local Node-powered n8n runtime, workflows, and orchestration status.",
            "Plugins": "Loaded plugin inventory and refresh tools.",
            "Settings": "Theme, anti-ban settings, and application logs.",
        }
        self.page_subtitle.setText(subtitles.get(page_name, ""))
        self.page_header.setVisible(page_name not in {"Model Dashboard", "Behavior Editor", "Cluster", "Vision Lab", "Guide Coach", "Provider Hub", "n8n Hub", "Plugins"})
        self._reconcile_browser_prewarm_pool()

    def set_status(self, message: str):
        if hasattr(self, "status_label"):
            self.status_label.setText(message)
        status_bar = self.statusBar()
        if status_bar is not None:
            status_bar.showMessage(message, 4000)

    def create_training_page(self):
        content = QWidget()
        root = QVBoxLayout(content)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        root.addWidget(self._make_section_title("Training Control Center", "Start, stop, capture, and notes now live in one stable layout."))

        stats_row = QHBoxLayout()
        stats_row.setSpacing(10)
        status_card, self.training_status_value = self._make_stat_card("Status", "Idle", "#0ea5e9")
        mode_card, self.training_mode_value = self._make_stat_card("Mode", "Browser", "#22c55e")
        region_card, self.training_region_value = self._make_stat_card("Region", "1280 x 720", "#f59e0b")
        stats_row.addWidget(status_card)
        stats_row.addWidget(mode_card)
        stats_row.addWidget(region_card)
        root.addLayout(stats_row)

        columns = QHBoxLayout()
        columns.setSpacing(12)
        left_column = QVBoxLayout()
        right_column = QVBoxLayout()
        left_column.setSpacing(12)
        right_column.setSpacing(12)
        left_column.setAlignment(Qt.AlignTop)
        right_column.setAlignment(Qt.AlignTop)

        controls_box, controls_layout = self._make_group("Session Controls")
        controls_box.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        control_row = QHBoxLayout()
        control_row.setSpacing(10)
        self.start_btn = QPushButton("Start AI")
        self.start_btn.clicked.connect(self.start_ai)
        self.stop_btn = QPushButton("Stop AI")
        self.stop_btn.clicked.connect(self.stop_ai)
        self.stop_btn.setEnabled(False)
        self.debug_overlay_btn = QPushButton("Show Debug Overlay")
        self.debug_overlay_btn.clicked.connect(self.toggle_debug_overlay)
        for button in [self.start_btn, self.stop_btn, self.debug_overlay_btn]:
            control_row.addWidget(button)
        controls_layout.addLayout(control_row)
        training_hint = QLabel("Start runs the current behavior graph against the selected capture region.")
        training_hint.setWordWrap(True)
        training_hint.setObjectName("mutedLabel")
        training_hint.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        controls_layout.addWidget(training_hint)
        left_column.addWidget(controls_box)

        source_box, source_layout = self._make_group("Game Source")
        source_box.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self.browser_radio = QRadioButton("Browser Game")
        self.desktop_radio = QRadioButton("Desktop Game")
        self.browser_radio.setChecked(True)
        self.browser_radio.toggled.connect(self._update_mode_label)
        self.game_mode_group = QButtonGroup(self)
        self.game_mode_group.addButton(self.browser_radio)
        self.game_mode_group.addButton(self.desktop_radio)
        source_layout.addWidget(self.browser_radio)
        source_layout.addWidget(self.desktop_radio)
        source_layout.addWidget(QLabel("Browser URL"))
        self.url_input = QLineEdit("https://lom.joynetgame.com")
        source_layout.addWidget(self.url_input)
        source_layout.addWidget(QLabel("Desktop EXE"))
        self.exe_input = QLineEdit("C:/Games/YourGame/game.exe")
        source_layout.addWidget(self.exe_input)
        source_layout.addWidget(QLabel("Desktop Window"))
        self.desktop_window_input = QLineEdit()
        self.desktop_window_input.setPlaceholderText("Window title for desktop mode")
        source_layout.addWidget(self.desktop_window_input)
        desktop_window_row = QHBoxLayout()
        self.desktop_window_selector = ScrollGuardComboBox()
        self.desktop_window_selector.currentIndexChanged.connect(self._on_desktop_window_selected)
        refresh_windows_btn = QPushButton("Refresh Windows")
        refresh_windows_btn.clicked.connect(self.refresh_desktop_window_list)
        use_window_region_btn = QPushButton("Use Window Region")
        use_window_region_btn.clicked.connect(self.use_selected_desktop_window_region)
        desktop_window_row.addWidget(self.desktop_window_selector, 1)
        desktop_window_row.addWidget(refresh_windows_btn)
        desktop_window_row.addWidget(use_window_region_btn)
        source_layout.addLayout(desktop_window_row)
        self._update_mode_label()
        left_column.addWidget(source_box)

        region_box, region_layout = self._make_group("Game Window Region")
        region_box.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        grid = QGridLayout()
        self.region_x = QLineEdit("0")
        self.region_y = QLineEdit("0")
        self.region_w = QLineEdit("1280")
        self.region_h = QLineEdit("720")
        for widget, width in [(self.region_x, 88), (self.region_y, 88), (self.region_w, 108), (self.region_h, 108)]:
            widget.setMinimumWidth(width)
        for column, (label_text, widget) in enumerate([("X", self.region_x), ("Y", self.region_y), ("Width", self.region_w), ("Height", self.region_h)]):
            grid.addWidget(QLabel(label_text), 0, column)
            grid.addWidget(widget, 1, column)
        grid.setColumnStretch(4, 1)
        region_layout.addLayout(grid)
        preset_row = QHBoxLayout()
        preset_720 = QPushButton("Use 1280 x 720")
        preset_720.clicked.connect(lambda: self.set_region_preset(0, 0, 1280, 720))
        preset_1080 = QPushButton("Use 1920 x 1080")
        preset_1080.clicked.connect(lambda: self.set_region_preset(0, 0, 1920, 1080))
        preset_row.addWidget(preset_720)
        preset_row.addWidget(preset_1080)
        region_layout.addLayout(preset_row)
        region_layout.addWidget(self._build_button_grid([
            ("Drag to Capture", self.capture_region_drag),
            ("Preview Region", self.preview_game_region),
            ("Save Region", self.save_game_region),
            ("Load Region", self.load_game_region),
            ("Apply Region", self.apply_game_region),
        ], columns=3))
        left_column.addWidget(region_box)

        input_box, input_layout = self._make_group("Input Settings")
        input_box.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self.mouse_checkbox = QCheckBox("Enable Mouse")
        self.mouse_checkbox.setChecked(True)
        self.mouse_checkbox.stateChanged.connect(self.toggle_mouse)
        self.keyboard_checkbox = QCheckBox("Enable Keyboard")
        self.keyboard_checkbox.setChecked(True)
        self.keyboard_checkbox.stateChanged.connect(self.toggle_keyboard)
        self.human_mouse_checkbox = QCheckBox("Human-like Mouse Timing")
        self.human_mouse_checkbox.setChecked(True)
        self.human_mouse_checkbox.stateChanged.connect(self._sync_antiban_settings)
        self.human_keyboard_checkbox = QCheckBox("Human-like Keyboard Timing")
        self.human_keyboard_checkbox.setChecked(True)
        self.human_keyboard_checkbox.stateChanged.connect(self._sync_antiban_settings)
        for widget in [self.mouse_checkbox, self.keyboard_checkbox, self.human_mouse_checkbox, self.human_keyboard_checkbox]:
            input_layout.addWidget(widget)
        right_column.addWidget(input_box)

        stats_box, stats_layout = self._make_group("Agent Stats")
        stats_box.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self.xp_label = QLabel("XP: 0")
        self.gold_label = QLabel("Gold: 0")
        self.reward_label = QLabel("Reward: 0.00")
        self.action_label = QLabel("Last Action: idle")
        for widget in [self.xp_label, self.gold_label, self.reward_label, self.action_label]:
            stats_layout.addWidget(widget)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, self.max_steps_spin.value() if hasattr(self, "max_steps_spin") else 5000)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("Training Progress: 0/5000")
        stats_layout.addWidget(self.progress_bar)
        right_column.addWidget(stats_box)

        quick_box, quick_layout = self._make_group("Quick Settings")
        quick_box.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self.quick_checkbox = QCheckBox("Fast Training Mode")
        quick_layout.addWidget(self.quick_checkbox)
        quick_layout.addWidget(QLabel("Max Steps"))
        self.max_steps_spin = QSpinBox()
        self.max_steps_spin.setRange(1, 1_000_000)
        self.max_steps_spin.setValue(5000)
        quick_layout.addWidget(self.max_steps_spin)
        quick_layout.addWidget(QLabel("Exploration Rate"))
        self.exploration_spin = QDoubleSpinBox()
        self.exploration_spin.setRange(0.0, 1.0)
        self.exploration_spin.setSingleStep(0.05)
        self.exploration_spin.setValue(0.2)
        quick_layout.addWidget(self.exploration_spin)
        right_column.addWidget(quick_box)

        avatar_box, avatar_layout = self._make_group("Agent Avatar")
        avatar_box.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self.avatar_label = QLabel()
        self.avatar_label.setAlignment(Qt.AlignCenter)
        avatar_pixmap = QPixmap(str(self.avatar_path))
        if avatar_pixmap.isNull():
            self.avatar_label.setText("No Avatar")
        else:
            self.avatar_label.setPixmap(avatar_pixmap.scaled(96, 96, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        avatar_layout.addWidget(self.avatar_label)
        right_column.addWidget(avatar_box)

        left_column.addStretch(1)
        right_column.addStretch(1)

        columns.addLayout(left_column, stretch=3)
        columns.addLayout(right_column, stretch=2)
        root.addLayout(columns)

        lower_row = QHBoxLayout()
        lower_row.setSpacing(12)
        logs_box, logs_layout = self._make_group("Agent Log Output")
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        logs_layout.addWidget(self.log_output)
        lower_row.addWidget(logs_box, stretch=3)

        notes_box, notes_layout = self._make_group("Notes And History")
        self.notes_edit = QTextEdit()
        self.notes_edit.setPlaceholderText("Write notes about experiments, problems, or promising behavior.")
        self.reward_history = QListWidget()
        self.reward_history.addItem("No rewards recorded yet.")
        notes_layout.addWidget(self.notes_edit)
        notes_layout.addWidget(QLabel("Recent Reward History"))
        notes_layout.addWidget(self.reward_history)
        lower_row.addWidget(notes_box, stretch=2)
        root.addLayout(lower_row)
        root.addStretch()

        return self._wrap_scrollable_page(content)

    def create_model_dashboard_page(self):
        _QChart, QChartView, QLineSeries, _QValueAxis = _chart_types()
        content = QWidget()
        root = QVBoxLayout(content)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)
        root.addWidget(self._make_section_title("Model Dashboard", "Charts and metrics are grouped in a dashboard grid now."))

        overview_row = QWidget()
        overview_layout = QGridLayout(overview_row)
        overview_layout.setContentsMargins(0, 0, 0, 0)
        overview_layout.setHorizontalSpacing(12)
        overview_layout.setVerticalSpacing(12)
        trainer_card, self.model_trainer_value = self._make_stat_card("Trainer", "Unavailable", "#0ea5e9")
        checkpoint_card, self.model_checkpoint_value = self._make_stat_card("Saved Model", "Missing", "#22c55e")
        pipeline_card, self.model_pipeline_value = self._make_stat_card("Pipeline", "Offline", "#f59e0b")
        plugins_card, self.model_plugins_value = self._make_stat_card("Plugins", "0", "#84cc16")
        for column, card in enumerate([trainer_card, checkpoint_card, pipeline_card, plugins_card]):
            overview_layout.addWidget(card, 0, column)
            overview_layout.setColumnStretch(column, 1)
        root.addWidget(overview_row)

        self.xp_series = QLineSeries()
        self.gold_series = QLineSeries()
        self.action_series = QLineSeries()
        self.reward_series = QLineSeries()
        self.loss_series = QLineSeries()

        chart_grid = QGridLayout()
        for title, series, y_title, row, column in [
            ("XP Over Time", self.xp_series, "XP", 0, 0),
            ("Gold Over Time", self.gold_series, "Gold", 0, 1),
            ("Actions Over Time", self.action_series, "Action", 1, 0),
            ("Reward Over Time", self.reward_series, "Reward", 1, 1),
        ]:
            view = QChartView(self._create_chart(title, series, "Step", y_title))
            view.setMinimumHeight(210)
            chart_grid.addWidget(view, row, column)
        chart_grid.setColumnStretch(0, 1)
        chart_grid.setColumnStretch(1, 1)
        root.addLayout(chart_grid)

        stats_box, stats_layout = self._make_group("Training Statistics")
        self.episode_count_label = QLabel("Episodes: 0")
        self.total_reward_label = QLabel("Total Reward: 0.00")
        self.average_reward_label = QLabel("Average Reward: 0.00")
        self.exploration_rate_label = QLabel("Exploration Rate: 1.000")
        self.ppo_status_label = QLabel("PPO Status: Idle")
        for widget in [self.episode_count_label, self.total_reward_label, self.average_reward_label, self.exploration_rate_label, self.ppo_status_label]:
            stats_layout.addWidget(widget)
        root.addWidget(stats_box)

        details_box, details_layout = self._make_group("Model And Runtime Details")
        self.model_save_path_label = QLabel("Model Path: models/ppo_model")
        self.model_backend_label = QLabel("Backend: auto")
        self.model_checkpoint_detail_label = QLabel("Checkpoint Details: no checkpoint metadata yet")
        self.model_runtime_label = QLabel("Runtime: training=idle, ppo=idle, theme=Terminal")
        self.model_ocr_label = QLabel("OCR: OCR status unavailable")
        self.model_cluster_label = QLabel("Cluster: offline with 0 worker(s)")
        self.model_capabilities_label = QLabel(
            "Capabilities: browser and desktop capture, behavior graphs, PPO training, OCR + YOLO perception, plugin loading, and multi-worker cluster control."
        )
        for widget in [
            self.model_save_path_label,
            self.model_backend_label,
            self.model_checkpoint_detail_label,
            self.model_runtime_label,
            self.model_ocr_label,
            self.model_cluster_label,
            self.model_capabilities_label,
        ]:
            widget.setWordWrap(True)
            details_layout.addWidget(widget)
        root.addWidget(details_box)

        controls = QGridLayout()
        controls.setHorizontalSpacing(10)
        controls.setVerticalSpacing(10)
        reset_button = QPushButton("Reset Charts")
        reset_button.clicked.connect(self.reset_charts)
        export_button = QPushButton("Export Metrics")
        export_button.clicked.connect(self.export_metrics)
        self.train_ppo_btn = QPushButton("Train PPO")
        self.train_ppo_btn.clicked.connect(self.start_ppo_training)
        self.stop_ppo_btn = QPushButton("Stop PPO")
        self.stop_ppo_btn.clicked.connect(self.stop_ppo_training)
        self.stop_ppo_btn.setEnabled(False)
        load_model_button = QPushButton("Load Saved PPO")
        load_model_button.clicked.connect(self.load_saved_model)
        save_model_button = QPushButton("Save PPO Checkpoint")
        save_model_button.clicked.connect(self.save_model_checkpoint)
        evaluate_model_button = QPushButton("Evaluate PPO")
        evaluate_model_button.clicked.connect(self.evaluate_model_checkpoint)
        details_button = QPushButton("View Runtime Details")
        details_button.clicked.connect(self.show_runtime_details)
        export_snapshot_button = QPushButton("Export Runtime Snapshot")
        export_snapshot_button.clicked.connect(self.export_runtime_snapshot)
        for index, widget in enumerate([
            reset_button,
            export_button,
            self.train_ppo_btn,
            self.stop_ppo_btn,
            load_model_button,
            save_model_button,
            evaluate_model_button,
            details_button,
            export_snapshot_button,
        ]):
            controls.addWidget(widget, index // 4, index % 4)
            controls.setColumnStretch(index % 4, 1)
        root.addLayout(controls)
        root.addStretch()
        return self._wrap_scrollable_page(content)

    def _create_chart(self, title: str, series: QLineSeries, x_title: str, y_title: str):
        QChart, _QChartView, _QLineSeries, QValueAxis = _chart_types()
        chart = QChart()
        chart.setTitle(title)
        chart.addSeries(series)
        axis_x = QValueAxis()
        axis_y = QValueAxis()
        axis_x.setTitleText(x_title)
        axis_y.setTitleText(y_title)
        axis_x.setRange(0, 10)
        axis_y.setRange(0, 10)
        chart.addAxis(axis_x, Qt.AlignmentFlag.AlignBottom)
        chart.addAxis(axis_y, Qt.AlignmentFlag.AlignLeft)
        series.attachAxis(axis_x)
        series.attachAxis(axis_y)
        return chart

    def create_behavior_editor_page(self):
        BehaviorEditor = _behavior_editor_type()
        page = QWidget()
        page.setMinimumSize(0, 0)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.addWidget(self._make_section_title("Behavior Graph Editor", "Graph tools and tab actions now live in one coherent editor layout."))
        self.behavior_editor = BehaviorEditor(click_overlay=self.click_overlay)
        self.behavior_editor.setMinimumSize(0, 0)
        self.behavior_editor.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.behavior_editor, stretch=1)
        return page

    def create_training_cluster_page(self):
        page = QWidget()
        page.setMinimumSize(0, 0)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.addWidget(self._make_section_title("Cluster Management", "Worker controls, table menus, and event logs are grouped together."))

        self.cluster_status_label = QLabel("Status: Disconnected")
        self.cluster_status_label.setObjectName("statusHeader")
        layout.addWidget(self.cluster_status_label)
        self.cluster_summary_label = QLabel("Disconnected. Workers: 0. Selected: None.")
        self.cluster_summary_label.setObjectName("mutedLabel")
        self.cluster_summary_label.setWordWrap(True)
        layout.addWidget(self.cluster_summary_label)

        overview_row = QWidget()
        overview_layout = QGridLayout(overview_row)
        overview_layout.setContentsMargins(0, 0, 0, 0)
        overview_layout.setHorizontalSpacing(12)
        overview_layout.setVerticalSpacing(12)
        connection_card, self.cluster_connection_value = self._make_stat_card("Connection", "Offline", "#0ea5e9")
        workers_card, self.cluster_workers_value = self._make_stat_card("Workers", "0", "#22c55e")
        active_card, self.cluster_active_value = self._make_stat_card("Busy Workers", "0", "#f59e0b")
        standby_card, self.cluster_standby_value = self._make_stat_card("Standby", "Disabled", "#38bdf8")
        load_card, self.cluster_load_value = self._make_stat_card("Avg CPU", "0% / 200%", "#84cc16")
        gpu_card, self.cluster_gpu_value = self._make_stat_card("Avg GPU", "0% / 100%", "#22d3ee")
        for index, card in enumerate([connection_card, workers_card, active_card, standby_card, load_card, gpu_card]):
            overview_layout.addWidget(card, index // 3, index % 3)
            overview_layout.setColumnStretch(index % 3, 1)
        layout.addWidget(overview_row)

        details_row = QHBoxLayout()
        details_row.setSpacing(12)

        runtime_box, runtime_layout = self._make_group("Runtime Diagnostics")
        self.cluster_uptime_label = QLabel("Uptime: N/A")
        self.cluster_last_event_label = QLabel("Last Event: No cluster events yet. (N/A)")
        self.cluster_event_count_label = QLabel("Cluster Events: 0")
        self.cluster_worker_profile_label = QLabel(
            f"Worker Profile: {self.default_cluster_workers} worker(s) @ {self._cluster_worker_limit_gb():.1f} GB each | "
            f"target={self._cluster_worker_target_fps()} fps"
        )
        self.cluster_standby_status_label = QLabel("Standby Browser: Disabled")
        self.cluster_cpu_label = QLabel("Avg CPU: 0% / 200% cap (2.00 shared cores) | Est Share: 0.0 logical cores")
        self.cluster_gpu_label = QLabel("Avg GPU: Disabled")
        self.cluster_memory_label = QLabel("Avg Memory: 0%")
        self.cluster_pipeline_events_label = QLabel("Runtime Signals: frames=0, vision=0, decisions=0, actions=0")
        self.cluster_pipeline_status_label = QLabel("Pipeline: No runtime pipeline attached")
        self.cluster_ocr_status_label = QLabel("OCR: OCR status unavailable")
        self.cluster_runtime_signal_label = QLabel("Last Runtime Signal: No runtime signals yet. (N/A)")
        for widget in [
            self.cluster_uptime_label,
            self.cluster_last_event_label,
            self.cluster_event_count_label,
            self.cluster_worker_profile_label,
            self.cluster_standby_status_label,
            self.cluster_cpu_label,
            self.cluster_memory_label,
            self.cluster_pipeline_events_label,
            self.cluster_pipeline_status_label,
            self.cluster_ocr_status_label,
            self.cluster_runtime_signal_label,
        ]:
            widget.setWordWrap(True)
            runtime_layout.addWidget(widget)
        details_row.addWidget(runtime_box, 2)

        selected_box, selected_layout = self._make_group("Selected Worker")
        self.cluster_selected_id_label = QLabel("Selected Worker: None")
        self.cluster_selected_status_label = QLabel("Status: N/A")
        self.cluster_selected_task_label = QLabel("Task: N/A")
        self.cluster_selected_game_label = QLabel("Game: N/A")
        self.cluster_selected_profile_label = QLabel("Profile: N/A")
        self.cluster_selected_mode_label = QLabel("Mode: N/A")
        self.cluster_selected_ads_label = QLabel("Ads: N/A")
        self.cluster_selected_learning_label = QLabel("Learning: N/A")
        self.cluster_selected_progress_label = QLabel("Progress: N/A")
        self.cluster_selected_strategy_label = QLabel("Strategy: N/A")
        self.cluster_selected_capture_label = QLabel("Capture: N/A")
        self.cluster_selected_model_label = QLabel("Model: N/A")
        self.cluster_selected_dom_mode_label = QLabel("DOM Drive: N/A")
        self.cluster_selected_dom_action_label = QLabel("DOM Last Action: N/A")
        self.cluster_selected_dom_confirmation_label = QLabel("DOM Confirmation: N/A")
        self.cluster_selected_dom_fallback_label = QLabel("DOM Fallback: N/A")
        self.cluster_selected_cpu_label = QLabel("CPU: N/A")
        self.cluster_selected_cpu_detail_label = QLabel("CPU Detail: N/A")
        self.cluster_selected_gpu_label = QLabel("GPU: Disabled")
        self.cluster_selected_gpu_detail_label = QLabel("GPU Detail: Legacy browser mode")
        self.cluster_selected_mem_label = QLabel("Memory: N/A")
        selected_hint = QLabel("Pick a worker row to inspect its current runtime load.")
        selected_hint.setObjectName("mutedLabel")
        selected_hint.setWordWrap(True)
        for widget in [
            self.cluster_selected_id_label,
            self.cluster_selected_status_label,
            self.cluster_selected_task_label,
            self.cluster_selected_game_label,
            self.cluster_selected_profile_label,
            self.cluster_selected_mode_label,
            self.cluster_selected_ads_label,
            self.cluster_selected_learning_label,
            self.cluster_selected_progress_label,
            self.cluster_selected_strategy_label,
            self.cluster_selected_capture_label,
            self.cluster_selected_model_label,
            self.cluster_selected_dom_mode_label,
            self.cluster_selected_dom_action_label,
            self.cluster_selected_dom_confirmation_label,
            self.cluster_selected_dom_fallback_label,
            self.cluster_selected_cpu_label,
            self.cluster_selected_cpu_detail_label,
            self.cluster_selected_gpu_label,
            self.cluster_selected_gpu_detail_label,
            self.cluster_selected_mem_label,
            selected_hint,
        ]:
            widget.setWordWrap(True)
            selected_layout.addWidget(widget)
        details_row.addWidget(selected_box, 1)
        layout.addLayout(details_row)

        workers_box, workers_layout = self._make_group("Connected Workers")
        self.worker_table = QTableWidget(0, 8)
        self.worker_table.setHorizontalHeaderLabels(["Worker ID", "Status", "Task", "Game", "Mode", "CPU", "GPU", "Memory"])
        self.worker_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.worker_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.worker_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.worker_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.worker_table.customContextMenuRequested.connect(self.show_worker_context_menu)
        self.worker_table.itemSelectionChanged.connect(self._sync_cluster_ui_state)
        self.worker_table.setMinimumHeight(280)
        self.worker_table.setAlternatingRowColors(True)
        self.worker_table.setColumnHidden(6, True)
        workers_layout.addWidget(self.worker_table)
        layout.addWidget(workers_box, stretch=1)

        controls = QGridLayout()
        controls.setHorizontalSpacing(10)
        controls.setVerticalSpacing(10)
        self.connect_cluster_btn = QPushButton("Connect To Cluster")
        self.connect_cluster_btn.clicked.connect(self.connect_to_cluster)
        self.start_worker_btn = QPushButton("Start Worker")
        self.start_worker_btn.clicked.connect(self.start_worker)
        self.stop_worker_btn = QPushButton("Stop Worker")
        self.stop_worker_btn.clicked.connect(self.stop_worker)
        self.scale_up_btn = QPushButton("Scale Up")
        self.scale_up_btn.clicked.connect(self.scale_up)
        self.scale_down_btn = QPushButton("Scale Down")
        self.scale_down_btn.clicked.connect(self.scale_down)
        self.toggle_worker_ads_btn = QPushButton("Toggle Reward Ads")
        self.toggle_worker_ads_btn.clicked.connect(self.toggle_selected_worker_ads)
        self.import_worker_bundle_btn = QPushButton("Import Worker Bundle")
        self.import_worker_bundle_btn.clicked.connect(self.import_worker_bundle_file)
        self.export_worker_bundle_btn = QPushButton("Export Worker Bundle")
        self.export_worker_bundle_btn.clicked.connect(self.export_selected_worker_bundle)
        cluster_controls = [
            self.connect_cluster_btn,
            self.start_worker_btn,
            self.stop_worker_btn,
            self.scale_up_btn,
            self.scale_down_btn,
            self.toggle_worker_ads_btn,
            self.import_worker_bundle_btn,
            self.export_worker_bundle_btn,
        ]
        for index, button in enumerate(cluster_controls):
            controls.addWidget(button, index // 4, index % 4)
            controls.setColumnStretch(index % 4, 1)
        layout.addLayout(controls)

        dom_mode_row = QHBoxLayout()
        dom_mode_row.addWidget(QLabel("DOM Drive Mode"))
        self.cluster_dom_mode_quick_selector = ScrollGuardComboBox()
        self.cluster_dom_mode_quick_selector.addItem("Legacy", "legacy")
        self.cluster_dom_mode_quick_selector.addItem("Assist", "assist")
        self.cluster_dom_mode_quick_selector.addItem("DOM Live Experimental", "dom_live_experimental")
        self.cluster_dom_mode_quick_selector.currentIndexChanged.connect(self._on_cluster_dom_mode_quick_changed)
        dom_mode_row.addWidget(self.cluster_dom_mode_quick_selector)
        dom_mode_hint = QLabel("Quick cluster toggle for browser workers. Detailed DOM confirmation settings stay in Settings.")
        dom_mode_hint.setWordWrap(True)
        dom_mode_hint.setObjectName("mutedLabel")
        dom_mode_row.addWidget(dom_mode_hint, 1)
        layout.addLayout(dom_mode_row)

        logs_box, logs_layout = self._make_group("Cluster Event Log")
        self.cluster_log = QTextEdit()
        self.cluster_log.setReadOnly(True)
        self.cluster_log.setMinimumHeight(180)
        logs_layout.addWidget(self.cluster_log)
        layout.addWidget(logs_box)

        self.update_cluster_ui([], connected=False)
        return self._wrap_scrollable_page(page)

    def create_vision_lab_page(self):
        content = QWidget()
        content.setMinimumSize(0, 0)
        root = QVBoxLayout(content)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        root.addWidget(self._make_section_title("Vision Lab", "Safe live capture analysis, OCR review, target ranking, and dataset tooling."))

        overview_row = QWidget()
        overview_layout = QGridLayout(overview_row)
        overview_layout.setContentsMargins(0, 0, 0, 0)
        overview_layout.setHorizontalSpacing(12)
        overview_layout.setVerticalSpacing(12)
        overview_cards = [
            self._make_stat_card("Preview", "Stopped", "#0ea5e9"),
            self._make_stat_card("Detector", "Auto", "#22c55e"),
            self._make_stat_card("Ranked Targets", "0", "#f59e0b"),
            self._make_stat_card("Dataset Samples", "0", "#84cc16"),
            self._make_stat_card("Session Events", "0", "#22d3ee"),
            self._make_stat_card("Heatmap Peak", "0.0", "#eab308"),
        ]
        (
            (preview_card, self.vision_preview_value),
            (detector_card, self.vision_detector_value),
            (targets_card, self.vision_targets_value),
            (dataset_card, self.vision_dataset_value),
            (history_card, self.vision_history_value),
            (heatmap_card, self.vision_heatmap_value),
        ) = overview_cards
        for index, (card, _value) in enumerate(overview_cards):
            overview_layout.addWidget(card, index // 3, index % 3)
            overview_layout.setColumnStretch(index % 3, 1)
        root.addWidget(overview_row)

        upper_row = QHBoxLayout()
        upper_row.setSpacing(12)

        preview_box, preview_layout = self._make_group("Live Capture Preview")
        self.vision_preview_label = QLabel("No preview yet")
        self.vision_preview_label.setAlignment(Qt.AlignCenter)
        self.vision_preview_label.setMinimumHeight(340)
        self.vision_preview_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.vision_preview_label.setObjectName("mutedLabel")
        preview_layout.addWidget(self.vision_preview_label)
        preview_buttons = QGridLayout()
        preview_buttons.setHorizontalSpacing(10)
        preview_buttons.setVerticalSpacing(10)
        vision_actions = [
            ("Start Live Preview", self.start_vision_preview),
            ("Stop Preview", self.stop_vision_preview),
            ("Analyze Frame", self.analyze_vision_frame),
            ("Extract Actionables", self.extract_vision_actionables),
            ("Save Snapshot", self.capture_vision_snapshot),
            ("Collect Dataset Sample", self.collect_vision_dataset_sample),
            ("Benchmark Inference", self.benchmark_vision_pipeline),
            ("Export Vision Report", self.export_vision_report),
            ("Refresh Status", self.refresh_ocr_status),
        ]
        for index, (label, handler) in enumerate(vision_actions):
            button = QPushButton(label)
            button.clicked.connect(handler)
            preview_buttons.addWidget(button, index // 4, index % 4)
            preview_buttons.setColumnStretch(index % 4, 1)
        preview_layout.addLayout(preview_buttons)
        preview_hint = QLabel(
            "Vision Lab analyzes the current capture region only. It does not move the mouse, aim, fire, or control the game."
        )
        preview_hint.setWordWrap(True)
        preview_hint.setObjectName("mutedLabel")
        preview_layout.addWidget(preview_hint)
        upper_row.addWidget(preview_box, 3)

        controls_column = QVBoxLayout()
        controls_column.setSpacing(12)

        source_box, source_layout = self._make_group("Capture Sources")
        source_layout.addWidget(QLabel("Source Mode"))
        self.vision_source_selector = ScrollGuardComboBox()
        self.vision_source_selector.addItem("Screen Region", "region")
        self.vision_source_selector.addItem("OBS WebSocket", "obs")
        self.vision_source_selector.addItem("Image / Video File", "file")
        self.vision_source_selector.currentIndexChanged.connect(lambda *_args: self._sync_vision_lab_state())
        source_layout.addWidget(self.vision_source_selector)
        source_layout.addWidget(QLabel("Acceleration Profile"))
        self.vision_acceleration_selector = ScrollGuardComboBox()
        self.vision_acceleration_selector.addItem("Auto Profile", "auto")
        self.vision_acceleration_selector.addItem("PyTorch / YOLO", "pytorch")
        self.vision_acceleration_selector.addItem("ONNX Runtime", "onnx")
        self.vision_acceleration_selector.addItem("TensorRT", "tensorrt")
        self.vision_acceleration_selector.currentIndexChanged.connect(lambda *_args: self._sync_vision_lab_state())
        source_layout.addWidget(self.vision_acceleration_selector)
        preset_grid = QGridLayout()
        preset_grid.setHorizontalSpacing(10)
        preset_grid.setVerticalSpacing(10)
        for index, (label, width, height) in enumerate([
            ("Use 640 x 640", 640, 640),
            ("Use 960 x 540", 960, 540),
            ("Use 1280 x 720", 1280, 720),
            ("Use 1600 x 900", 1600, 900),
        ]):
            button = QPushButton(label)
            button.clicked.connect(lambda _checked=False, w=width, h=height: self._vision_region_preset(w, h))
            preset_grid.addWidget(button, index // 2, index % 2)
            preset_grid.setColumnStretch(index % 2, 1)
        source_layout.addLayout(preset_grid)
        source_buttons = QGridLayout()
        source_buttons.setHorizontalSpacing(10)
        source_buttons.setVerticalSpacing(10)
        open_media_btn = QPushButton("Open Media")
        open_media_btn.clicked.connect(self.open_vision_media_file)
        clear_media_btn = QPushButton("Clear Media")
        clear_media_btn.clicked.connect(self.clear_vision_media_file)
        test_obs_btn = QPushButton("Test OBS")
        test_obs_btn.clicked.connect(self.test_obs_connection)
        source_buttons.addWidget(open_media_btn, 0, 0)
        source_buttons.addWidget(clear_media_btn, 0, 1)
        source_buttons.addWidget(test_obs_btn, 1, 0, 1, 2)
        source_layout.addLayout(source_buttons)
        controls_column.addWidget(source_box)

        controls_box, controls_layout = self._make_group("Analysis Controls")
        controls_layout.addWidget(QLabel("Analysis Backend"))
        self.vision_backend_selector = ScrollGuardComboBox()
        self.vision_backend_selector.addItem("Auto (YOLO + UI + OCR)", "auto")
        self.vision_backend_selector.addItem("YOLO Only", "yolo")
        self.vision_backend_selector.addItem("UI Contours Only", "ui")
        self.vision_backend_selector.addItem("OCR Only", "ocr")
        self.vision_backend_selector.currentIndexChanged.connect(lambda *_args: self._sync_vision_lab_state())
        controls_layout.addWidget(self.vision_backend_selector)
        controls_layout.addWidget(QLabel("Detection Confidence"))
        self.vision_confidence_spin = ScrollGuardDoubleSpinBox()
        self.vision_confidence_spin.setRange(0.05, 1.0)
        self.vision_confidence_spin.setSingleStep(0.05)
        self.vision_confidence_spin.setValue(0.5)
        self.vision_confidence_spin.valueChanged.connect(lambda *_args: self._sync_vision_lab_state())
        controls_layout.addWidget(self.vision_confidence_spin)
        controls_layout.addWidget(QLabel("Preview Interval (ms)"))
        self.vision_interval_spin = ScrollGuardSpinBox()
        self.vision_interval_spin.setRange(100, 5000)
        self.vision_interval_spin.setValue(700)
        self.vision_interval_spin.valueChanged.connect(self.vision_preview_timer.setInterval)
        controls_layout.addWidget(self.vision_interval_spin)
        controls_layout.addWidget(QLabel("Target Rank Limit"))
        self.vision_target_limit_spin = ScrollGuardSpinBox()
        self.vision_target_limit_spin.setRange(1, 20)
        self.vision_target_limit_spin.setValue(5)
        self.vision_target_limit_spin.valueChanged.connect(lambda *_args: self._sync_vision_lab_state())
        controls_layout.addWidget(self.vision_target_limit_spin)
        controls_layout.addWidget(QLabel("Benchmark Runs"))
        self.vision_benchmark_frames_spin = ScrollGuardSpinBox()
        self.vision_benchmark_frames_spin.setRange(1, 200)
        self.vision_benchmark_frames_spin.setValue(20)
        self.vision_benchmark_frames_spin.valueChanged.connect(lambda *_args: self._sync_vision_lab_state())
        controls_layout.addWidget(self.vision_benchmark_frames_spin)
        controls_layout.addWidget(QLabel("Heatmap Decay"))
        self.vision_heatmap_decay_spin = ScrollGuardDoubleSpinBox()
        self.vision_heatmap_decay_spin.setRange(0.50, 0.995)
        self.vision_heatmap_decay_spin.setSingleStep(0.01)
        self.vision_heatmap_decay_spin.setValue(0.92)
        self.vision_heatmap_decay_spin.valueChanged.connect(lambda *_args: self._sync_vision_lab_state())
        controls_layout.addWidget(self.vision_heatmap_decay_spin)
        controls_layout.addWidget(QLabel("Heatmap Radius"))
        self.vision_heatmap_radius_spin = ScrollGuardSpinBox()
        self.vision_heatmap_radius_spin.setRange(8, 180)
        self.vision_heatmap_radius_spin.setValue(42)
        self.vision_heatmap_radius_spin.valueChanged.connect(lambda *_args: self._sync_vision_lab_state())
        controls_layout.addWidget(self.vision_heatmap_radius_spin)
        controls_layout.addWidget(QLabel("Session History Limit"))
        self.vision_history_limit_spin = ScrollGuardSpinBox()
        self.vision_history_limit_spin.setRange(5, 200)
        self.vision_history_limit_spin.setValue(30)
        self.vision_history_limit_spin.valueChanged.connect(lambda value: setattr(self, "vision_session_limit", value))
        self.vision_history_limit_spin.valueChanged.connect(lambda *_args: self._sync_vision_lab_state())
        controls_layout.addWidget(self.vision_history_limit_spin)
        self.vision_overlay_boxes_checkbox = QCheckBox("Draw Detection Boxes")
        self.vision_overlay_boxes_checkbox.setChecked(True)
        self.vision_overlay_labels_checkbox = QCheckBox("Draw Labels")
        self.vision_overlay_labels_checkbox.setChecked(True)
        self.vision_overlay_ocr_checkbox = QCheckBox("Overlay OCR Text")
        self.vision_overlay_ocr_checkbox.setChecked(False)
        for widget in [
            self.vision_overlay_boxes_checkbox,
            self.vision_overlay_labels_checkbox,
            self.vision_overlay_ocr_checkbox,
        ]:
            controls_layout.addWidget(widget)
        controls_column.addWidget(controls_box)

        runtime_box, runtime_layout = self._make_group("Runtime Details")
        self.vision_capture_source_label = QLabel("Source Mode: Screen Region | Media: none")
        self.vision_obs_status_label = QLabel("OBS: OBS capture unavailable")
        self.vision_backend_status_label = QLabel("Backends: YOLO=yes, ONNX=no, TensorRT=no, OBS=no")
        self.vision_runtime_label = QLabel("Backend: Auto | Interval: 700 ms | Target Limit: 5")
        self.vision_capture_label = QLabel("Capture: N/A | Region: 1280 x 720")
        self.vision_status_label = QLabel("Last Analysis: No analysis yet.")
        self.vision_ocr_state_label = QLabel("OCR: checking...")
        self.vision_benchmark_label = QLabel("Inference: 0.0 ms")
        self.vision_model_label = QLabel("Detector Source: Auto")
        for widget in [
            self.vision_capture_source_label,
            self.vision_obs_status_label,
            self.vision_backend_status_label,
            self.vision_runtime_label,
            self.vision_capture_label,
            self.vision_status_label,
            self.vision_ocr_state_label,
            self.vision_benchmark_label,
            self.vision_model_label,
        ]:
            widget.setWordWrap(True)
            runtime_layout.addWidget(widget)
        controls_column.addWidget(runtime_box)
        controls_column.addStretch(1)
        upper_row.addLayout(controls_column, 2)
        root.addLayout(upper_row)

        analysis_row = QHBoxLayout()
        analysis_row.setSpacing(12)

        targets_box, targets_layout = self._make_group("Ranked Targets")
        self.vision_target_table = QTableWidget(0, 5)
        self.vision_target_table.setHorizontalHeaderLabels(["Rank", "Label", "Confidence", "Center", "Size"])
        self.vision_target_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.vision_target_table.setMinimumHeight(260)
        self.vision_target_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        targets_layout.addWidget(self.vision_target_table)
        analysis_row.addWidget(targets_box, 3)

        report_column = QVBoxLayout()
        report_column.setSpacing(12)

        ocr_box, ocr_layout = self._make_group("OCR Extract")
        self.vision_ocr_text = QTextEdit()
        self.vision_ocr_text.setReadOnly(True)
        self.vision_ocr_text.setMinimumHeight(120)
        ocr_layout.addWidget(self.vision_ocr_text)
        report_column.addWidget(ocr_box)

        report_box, report_layout = self._make_group("Analysis Report")
        self.vision_report_text = QTextEdit()
        self.vision_report_text.setReadOnly(True)
        self.vision_report_text.setMinimumHeight(180)
        report_layout.addWidget(self.vision_report_text)
        report_column.addWidget(report_box)

        dom_box, dom_layout = self._make_group("DOM + OCR Actions")
        self.vision_dom_summary_label = QLabel("No DOM snapshot captured yet.")
        self.vision_dom_summary_label.setWordWrap(True)
        self.vision_dom_summary_label.setObjectName("mutedLabel")
        dom_layout.addWidget(self.vision_dom_summary_label)
        self.vision_dom_action_table = QTableWidget(0, 5)
        self.vision_dom_action_table.setHorizontalHeaderLabels(["Source", "Label", "Score", "Keyword", "Bounds"])
        self.vision_dom_action_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.vision_dom_action_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.vision_dom_action_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.vision_dom_action_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.vision_dom_action_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.vision_dom_action_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.vision_dom_action_table.setMinimumHeight(150)
        dom_layout.addWidget(self.vision_dom_action_table)
        self.vision_dom_text = QTextEdit()
        self.vision_dom_text.setReadOnly(True)
        self.vision_dom_text.setMinimumHeight(130)
        self.vision_dom_text.setPlainText("Merged DOM and OCR action evidence will appear here.")
        dom_layout.addWidget(self.vision_dom_text)
        report_column.addWidget(dom_box)
        analysis_row.addLayout(report_column, 2)
        root.addLayout(analysis_row)

        insights_row = QHBoxLayout()
        insights_row.setSpacing(12)

        heatmap_box, heatmap_layout = self._make_group("Target Heatmap")
        self.vision_heatmap_label = QLabel("Heatmap will appear after analysis")
        self.vision_heatmap_label.setAlignment(Qt.AlignCenter)
        self.vision_heatmap_label.setMinimumHeight(240)
        self.vision_heatmap_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.vision_heatmap_label.setObjectName("mutedLabel")
        heatmap_layout.addWidget(self.vision_heatmap_label)
        heatmap_actions = QHBoxLayout()
        reset_heatmap_btn = QPushButton("Reset Heatmap")
        reset_heatmap_btn.clicked.connect(self.reset_vision_heatmap)
        export_heatmap_btn = QPushButton("Export Heatmap")
        export_heatmap_btn.clicked.connect(self.export_vision_heatmap)
        heatmap_actions.addWidget(reset_heatmap_btn)
        heatmap_actions.addWidget(export_heatmap_btn)
        heatmap_actions.addStretch()
        heatmap_layout.addLayout(heatmap_actions)
        self.vision_heatmap_summary_label = QLabel("No heatmap data yet.")
        self.vision_heatmap_summary_label.setWordWrap(True)
        self.vision_heatmap_summary_label.setObjectName("mutedLabel")
        heatmap_layout.addWidget(self.vision_heatmap_summary_label)
        insights_row.addWidget(heatmap_box, 2)

        history_column = QVBoxLayout()
        history_column.setSpacing(12)

        preset_box, preset_layout = self._make_group("Preset Profiles")
        preset_layout.addWidget(QLabel("Active Preset"))
        self.vision_preset_selector = ScrollGuardComboBox()
        self.vision_preset_selector.currentIndexChanged.connect(
            lambda *_args: setattr(self, "vision_selected_preset", self.vision_preset_selector.currentText())
        )
        preset_layout.addWidget(self.vision_preset_selector)
        preset_buttons = QGridLayout()
        preset_buttons.setHorizontalSpacing(10)
        preset_buttons.setVerticalSpacing(10)
        apply_preset_btn = QPushButton("Apply Preset")
        apply_preset_btn.clicked.connect(self.apply_vision_preset)
        save_preset_btn = QPushButton("Save Current As")
        save_preset_btn.clicked.connect(self.save_vision_preset)
        delete_preset_btn = QPushButton("Delete Preset")
        delete_preset_btn.clicked.connect(self.delete_vision_preset)
        preset_buttons.addWidget(apply_preset_btn, 0, 0)
        preset_buttons.addWidget(save_preset_btn, 0, 1)
        preset_buttons.addWidget(delete_preset_btn, 1, 0, 1, 2)
        preset_layout.addLayout(preset_buttons)
        self.vision_preset_summary_label = QLabel("Active preset: Balanced")
        self.vision_preset_summary_label.setWordWrap(True)
        self.vision_preset_summary_label.setObjectName("mutedLabel")
        preset_layout.addWidget(self.vision_preset_summary_label)
        history_column.addWidget(preset_box)

        history_box, history_layout = self._make_group("Session History")
        self.vision_history_list = QListWidget()
        self.vision_history_list.setMinimumHeight(180)
        self.vision_history_list.currentRowChanged.connect(self.update_vision_session_detail)
        history_layout.addWidget(self.vision_history_list)
        self.vision_history_detail_label = QLabel("No session history yet.")
        self.vision_history_detail_label.setWordWrap(True)
        self.vision_history_detail_label.setObjectName("mutedLabel")
        history_layout.addWidget(self.vision_history_detail_label)
        history_actions = QHBoxLayout()
        clear_history_btn = QPushButton("Clear History")
        clear_history_btn.clicked.connect(self.clear_vision_session_history)
        export_history_btn = QPushButton("Export History")
        export_history_btn.clicked.connect(self.export_vision_session_history)
        history_actions.addWidget(clear_history_btn)
        history_actions.addWidget(export_history_btn)
        history_actions.addStretch()
        history_layout.addLayout(history_actions)
        history_column.addWidget(history_box)
        insights_row.addLayout(history_column, 2)
        root.addLayout(insights_row)

        tools_row = QHBoxLayout()
        tools_row.setSpacing(12)

        dataset_box, dataset_layout = self._make_group("Dataset Tools")
        dataset_layout.addWidget(QLabel("Dataset Directory"))
        self.vision_dataset_dir_input = QLineEdit("datasets/vision_lab")
        dataset_layout.addWidget(self.vision_dataset_dir_input)
        dataset_layout.addWidget(QLabel("OBS Host"))
        self.vision_obs_host_input = QLineEdit("localhost")
        dataset_layout.addWidget(self.vision_obs_host_input)
        dataset_layout.addWidget(QLabel("OBS Port"))
        self.vision_obs_port_spin = ScrollGuardSpinBox()
        self.vision_obs_port_spin.setRange(1, 65535)
        self.vision_obs_port_spin.setValue(4455)
        dataset_layout.addWidget(self.vision_obs_port_spin)
        dataset_layout.addWidget(QLabel("OBS Password"))
        self.vision_obs_password_input = QLineEdit()
        self.vision_obs_password_input.setEchoMode(QLineEdit.EchoMode.Password)
        dataset_layout.addWidget(self.vision_obs_password_input)
        dataset_layout.addWidget(QLabel("OBS Source Name"))
        self.vision_obs_source_input = QLineEdit()
        dataset_layout.addWidget(self.vision_obs_source_input)
        dataset_note = QLabel(
            "Dataset samples save the current frame plus a JSON report of OCR text, ranked detections, and the active safe analysis profile."
        )
        dataset_note.setWordWrap(True)
        dataset_note.setObjectName("mutedLabel")
        dataset_layout.addWidget(dataset_note)
        tools_row.addWidget(dataset_box, 1)

        media_box, media_layout = self._make_group("Recorded Review")
        self.vision_media_path_label = QLabel("Media: none loaded")
        self.vision_media_path_label.setWordWrap(True)
        media_layout.addWidget(self.vision_media_path_label)
        media_layout.addWidget(QLabel("Video Frame"))
        self.vision_media_frame_spin = ScrollGuardSpinBox()
        self.vision_media_frame_spin.setRange(0, 0)
        self.vision_media_frame_spin.valueChanged.connect(self.on_vision_media_frame_changed)
        media_layout.addWidget(self.vision_media_frame_spin)
        media_buttons = QGridLayout()
        media_buttons.setHorizontalSpacing(10)
        media_buttons.setVerticalSpacing(10)
        self.vision_prev_frame_btn = QPushButton("Previous Frame")
        self.vision_prev_frame_btn.clicked.connect(lambda: self.step_vision_media(-1))
        self.vision_next_frame_btn = QPushButton("Next Frame")
        self.vision_next_frame_btn.clicked.connect(lambda: self.step_vision_media(1))
        analyze_media_btn = QPushButton("Analyze Current Media Frame")
        analyze_media_btn.clicked.connect(self.analyze_vision_frame)
        media_buttons.addWidget(self.vision_prev_frame_btn, 0, 0)
        media_buttons.addWidget(self.vision_next_frame_btn, 0, 1)
        media_buttons.addWidget(analyze_media_btn, 1, 0, 1, 2)
        media_layout.addLayout(media_buttons)
        media_note = QLabel("Use recorded footage to inspect safe detection behavior frame-by-frame without sending any input to a game.")
        media_note.setWordWrap(True)
        media_note.setObjectName("mutedLabel")
        media_layout.addWidget(media_note)
        tools_row.addWidget(media_box, 1)
        root.addLayout(tools_row)

        root.addStretch()

        self._rebuild_vision_preset_profiles(self.vision_selected_preset)
        self._refresh_vision_history_widgets()
        self.refresh_ocr_status()
        self._sync_vision_lab_state()
        return self._wrap_scrollable_page(content)

    def create_guide_coach_page(self):
        GuideCoachWidget = _guide_coach_widget_type()
        content = QWidget()
        content.setMinimumSize(0, 0)
        root = QVBoxLayout(content)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        root.addWidget(
            self._make_section_title(
                "Guide Coach",
                "Detected screen guidance, F2P checklist tracking, and offline replay review live together here.",
            )
        )
        self.guide_coach_widget = GuideCoachWidget(
            project_root=self.project_root,
            latest_frame_provider=self._guide_coach_latest_frame,
            capture_frame_provider=self._capture_guide_coach_frame,
            current_media_path_provider=self._current_vision_media_path,
            dom_snapshot_provider=self._guide_coach_dom_snapshot,
            manual_context_provider=self._guide_coach_manual_context,
            status_callback=self.set_status,
            profile_key=getattr(self._current_game_profile(), "key", "legends_of_mushroom"),
            evidence_store=self._task_evidence_store(),
        )
        root.addWidget(self.guide_coach_widget, stretch=1)
        self._sync_guide_coach_state()
        return self._wrap_scrollable_page(content)

    def create_provider_hub_page(self):
        ProviderHubWidget = _provider_hub_widget_type()
        content = QWidget()
        content.setMinimumSize(0, 0)
        root = QVBoxLayout(content)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        root.addWidget(
            self._make_section_title(
                "Provider Hub",
                "Catalog external AI services, manage compatible API profiles, and use prompt tools for offline analysis support.",
            )
        )
        self.provider_hub_widget = ProviderHubWidget(
            project_root=self.project_root,
            status_callback=self.set_status,
        )
        root.addWidget(self.provider_hub_widget, stretch=1)
        self._sync_provider_hub_state()
        return self._wrap_scrollable_page(content)

    def create_n8n_hub_page(self):
        N8nHubWidget = _n8n_hub_widget_type()
        content = QWidget()
        content.setMinimumSize(0, 0)
        root = QVBoxLayout(content)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        root.addWidget(
            self._make_section_title(
                "n8n Hub",
                "Manage the local Node-powered n8n runtime, workflow templates, and editor mode from one place.",
            )
        )
        self.n8n_hub_widget = N8nHubWidget(
            project_root=self.project_root,
            status_callback=self.set_status,
        )
        root.addWidget(self.n8n_hub_widget, stretch=1)
        self._sync_n8n_hub_state()
        return self._wrap_scrollable_page(content)

    def create_plugins_page(self):
        page = QWidget()
        page.setMinimumSize(0, 0)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.addWidget(self._make_section_title("Plugin Manager", "Loaded plugins and refresh controls now have a dedicated tab layout."))

        summary_row = QWidget()
        summary_layout = QGridLayout(summary_row)
        summary_layout.setContentsMargins(0, 0, 0, 0)
        summary_layout.setHorizontalSpacing(12)
        summary_layout.setVerticalSpacing(12)
        plugin_count_card, self.plugin_count_value = self._make_stat_card("Loaded", "0", "#22c55e")
        plugin_runtime_card, self.plugin_runtime_value = self._make_stat_card("Runtime", "Unavailable", "#0ea5e9")
        plugin_reload_card, self.plugin_reload_value = self._make_stat_card("Hot Reload", "Disabled", "#f59e0b")
        plugin_event_card, self.plugin_event_value = self._make_stat_card("Event Bus", "Offline", "#84cc16")
        for column, card in enumerate([plugin_count_card, plugin_runtime_card, plugin_reload_card, plugin_event_card]):
            summary_layout.addWidget(card, 0, column)
            summary_layout.setColumnStretch(column, 1)
        layout.addWidget(summary_row)

        row = QHBoxLayout()
        reload_button = QPushButton("Reload Plugins")
        reload_button.clicked.connect(self.reload_plugins)
        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self.refresh_plugins)
        row.addWidget(reload_button)
        row.addWidget(refresh_button)
        row.addStretch()
        layout.addLayout(row)

        detail_box, detail_layout = self._make_group("Selected Plugin")
        self.plugin_detail_name_label = QLabel("Name: No plugins loaded")
        self.plugin_detail_id_label = QLabel("ID: N/A")
        self.plugin_detail_version_label = QLabel("Version: N/A")
        self.plugin_detail_description_label = QLabel("Description: Load or reload plugins to inspect them here.")
        for widget in [
            self.plugin_detail_name_label,
            self.plugin_detail_id_label,
            self.plugin_detail_version_label,
            self.plugin_detail_description_label,
        ]:
            widget.setWordWrap(True)
            detail_layout.addWidget(widget)
        layout.addWidget(detail_box)

        self.plugin_list = QListWidget()
        self.plugin_list.setMinimumHeight(260)
        self.plugin_list.currentItemChanged.connect(self.update_plugin_details)
        layout.addWidget(self.plugin_list)
        layout.addStretch()
        self.refresh_plugins()
        return self._wrap_scrollable_page(page)

    def create_settings_page(self):
        content = QWidget()
        root = QVBoxLayout(content)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)
        root.addWidget(self._make_section_title("Application Settings", "Theme controls, anti-ban options, and logs now match the rest of the app."))

        theme_box, theme_layout = self._make_group("UI Theme")
        self.theme_selector = ScrollGuardComboBox()
        for key, theme in self.THEME_DEFINITIONS.items():
            self.theme_selector.addItem(theme["label"], key)
        self.theme_selector.currentIndexChanged.connect(self.change_theme)
        theme_layout.addWidget(QLabel("Theme Preset"))
        theme_layout.addWidget(self.theme_selector)
        self.theme_description_label = QLabel()
        self.theme_description_label.setObjectName("mutedLabel")
        self.theme_description_label.setWordWrap(True)
        theme_layout.addWidget(self.theme_description_label)
        default_theme_label = self.THEME_DEFINITIONS["terminal"]["label"]
        default_hint = QLabel(f"{default_theme_label} loads by default when the app starts.")
        default_hint.setObjectName("mutedLabel")
        default_hint.setWordWrap(True)
        theme_layout.addWidget(default_hint)
        root.addWidget(theme_box)

        runtime_box, runtime_layout = self._make_group("Runtime Defaults")
        self.start_on_launch_checkbox = QCheckBox("Load preferred defaults on startup")
        runtime_layout.addWidget(self.start_on_launch_checkbox)
        runtime_layout.addWidget(QLabel("Default Page"))
        self.default_page_selector = ScrollGuardComboBox()
        for page_name in self.PAGE_ORDER:
            self.default_page_selector.addItem(page_name)
        runtime_layout.addWidget(self.default_page_selector)
        runtime_layout.addWidget(QLabel("Default Game Mode"))
        self.default_mode_selector = ScrollGuardComboBox()
        self.default_mode_selector.addItem("Browser", "browser")
        self.default_mode_selector.addItem("Desktop", "desktop")
        runtime_layout.addWidget(self.default_mode_selector)
        runtime_layout.addWidget(QLabel("Browser URL"))
        self.settings_url_input = QLineEdit("https://lom.joynetgame.com")
        runtime_layout.addWidget(self.settings_url_input)
        runtime_layout.addWidget(QLabel("Desktop EXE"))
        self.settings_exe_input = QLineEdit("C:/Games/YourGame/game.exe")
        runtime_layout.addWidget(self.settings_exe_input)
        runtime_layout.addWidget(QLabel("Desktop Window Title"))
        self.settings_desktop_window_input = QLineEdit()
        self.settings_desktop_window_input.setPlaceholderText("Window title for desktop mode")
        runtime_layout.addWidget(self.settings_desktop_window_input)
        settings_window_row = QHBoxLayout()
        self.settings_desktop_window_selector = ScrollGuardComboBox()
        self.settings_desktop_window_selector.currentIndexChanged.connect(self._on_desktop_window_selected)
        settings_refresh_windows_btn = QPushButton("Refresh Windows")
        settings_refresh_windows_btn.clicked.connect(self.refresh_desktop_window_list)
        settings_window_row.addWidget(self.settings_desktop_window_selector, 1)
        settings_window_row.addWidget(settings_refresh_windows_btn)
        runtime_layout.addLayout(settings_window_row)
        root.addWidget(runtime_box)

        advanced_box, advanced_layout = self._make_group("Advanced Controls")
        advanced_layout.addWidget(QLabel("PPO Model Save Path"))
        self.model_path_input = QLineEdit("models/ppo_model")
        advanced_layout.addWidget(self.model_path_input)
        advanced_layout.addWidget(QLabel("Trainer Backend"))
        self.trainer_backend_selector = ScrollGuardComboBox()
        self.trainer_backend_selector.addItem("Auto", "auto")
        self.trainer_backend_selector.addItem("PPO", "ppo")
        self.trainer_backend_selector.addItem("Maskable PPO", "maskable_ppo")
        self.trainer_backend_selector.addItem("Recurrent PPO", "recurrent_ppo")
        advanced_layout.addWidget(self.trainer_backend_selector)
        advanced_layout.addWidget(QLabel("Policy Layout"))
        self.trainer_policy_selector = ScrollGuardComboBox()
        self.trainer_policy_selector.addItem("Auto", "auto")
        self.trainer_policy_selector.addItem("MLP", "mlp")
        self.trainer_policy_selector.addItem("Recurrent", "recurrent")
        advanced_layout.addWidget(self.trainer_policy_selector)
        self.trainer_action_masking_checkbox = QCheckBox("Use Action Masking When The Environment Supports It")
        self.trainer_action_masking_checkbox.setChecked(True)
        advanced_layout.addWidget(self.trainer_action_masking_checkbox)
        advanced_layout.addWidget(QLabel("Evaluation Episodes"))
        self.trainer_eval_episodes_spin = ScrollGuardSpinBox()
        self.trainer_eval_episodes_spin.setRange(1, 100)
        self.trainer_eval_episodes_spin.setValue(5)
        advanced_layout.addWidget(self.trainer_eval_episodes_spin)
        advanced_layout.addWidget(QLabel("Cluster Default Workers"))
        self.cluster_default_workers_spin = ScrollGuardSpinBox()
        self.cluster_default_workers_spin.setRange(1, self.MAX_CLUSTER_WORKERS)
        self.cluster_default_workers_spin.setValue(1)
        advanced_layout.addWidget(self.cluster_default_workers_spin)
        advanced_layout.addWidget(QLabel("Worker Memory Budget (GB each)"))
        self.cluster_worker_memory_spin = ScrollGuardDoubleSpinBox()
        self.cluster_worker_memory_spin.setRange(0.5, 16.0)
        self.cluster_worker_memory_spin.setSingleStep(0.5)
        self.cluster_worker_memory_spin.setValue(2.0)
        advanced_layout.addWidget(self.cluster_worker_memory_spin)
        advanced_layout.addWidget(QLabel("Worker CPU Budget (% each, 100 = 1 core)"))
        self.cluster_worker_cpu_spin = ScrollGuardSpinBox()
        self.cluster_worker_cpu_spin.setRange(25, 400)
        self.cluster_worker_cpu_spin.setSingleStep(25)
        self.cluster_worker_cpu_spin.setValue(200)
        advanced_layout.addWidget(self.cluster_worker_cpu_spin)
        advanced_layout.addWidget(QLabel("Worker Target FPS"))
        self.cluster_worker_target_fps_spin = ScrollGuardSpinBox()
        self.cluster_worker_target_fps_spin.setRange(10, 60)
        self.cluster_worker_target_fps_spin.setValue(30)
        advanced_layout.addWidget(self.cluster_worker_target_fps_spin)
        self.cluster_browser_prewarm_checkbox = QCheckBox("Prewarm Browser Workers Before Autoplay")
        self.cluster_browser_prewarm_checkbox.setChecked(True)
        advanced_layout.addWidget(self.cluster_browser_prewarm_checkbox)
        advanced_layout.addWidget(QLabel("Passive Preview Target FPS"))
        self.cluster_preview_target_fps_spin = ScrollGuardSpinBox()
        self.cluster_preview_target_fps_spin.setRange(1, 30)
        self.cluster_preview_target_fps_spin.setValue(10)
        advanced_layout.addWidget(self.cluster_preview_target_fps_spin)
        advanced_layout.addWidget(QLabel("Interactive Control Preview FPS"))
        self.cluster_control_preview_target_fps_spin = ScrollGuardSpinBox()
        self.cluster_control_preview_target_fps_spin.setRange(1, 30)
        self.cluster_control_preview_target_fps_spin.setValue(15)
        advanced_layout.addWidget(self.cluster_control_preview_target_fps_spin)
        self.cluster_gpu_checkbox = QCheckBox("Use GPU Acceleration For Browser Workers")
        self.cluster_gpu_checkbox.setChecked(True)
        advanced_layout.addWidget(self.cluster_gpu_checkbox)
        self.cluster_gpu_detected_label = QLabel(f"Detected GPU: {self._host_gpu_summary()}")
        self.cluster_gpu_detected_label.setObjectName("mutedLabel")
        self.cluster_gpu_detected_label.setWordWrap(True)
        advanced_layout.addWidget(self.cluster_gpu_detected_label)
        self.cluster_auto_learning_checkbox = QCheckBox("Save Worker Learning And Reuse It")
        self.cluster_auto_learning_checkbox.setChecked(True)
        advanced_layout.addWidget(self.cluster_auto_learning_checkbox)
        self.cluster_watch_ads_checkbox = QCheckBox("Allow Workers To Watch Reward Ads")
        self.cluster_watch_ads_checkbox.setChecked(False)
        advanced_layout.addWidget(self.cluster_watch_ads_checkbox)
        advanced_layout.addWidget(QLabel("Browser DOM Drive Mode"))
        self.cluster_dom_drive_mode_selector = ScrollGuardComboBox()
        self.cluster_dom_drive_mode_selector.addItem("Legacy", "legacy")
        self.cluster_dom_drive_mode_selector.addItem("Assist", "assist")
        self.cluster_dom_drive_mode_selector.addItem("DOM Live Experimental", "dom_live_experimental")
        self.cluster_dom_drive_mode_selector.currentIndexChanged.connect(self._on_cluster_dom_mode_quick_changed)
        advanced_layout.addWidget(self.cluster_dom_drive_mode_selector)
        self.cluster_dom_confirmation_checkbox = QCheckBox("Require DOM Confirmation Before Advancing Tasks")
        self.cluster_dom_confirmation_checkbox.setChecked(True)
        advanced_layout.addWidget(self.cluster_dom_confirmation_checkbox)
        advanced_layout.addWidget(QLabel("DOM Live Cooldown (ms)"))
        self.cluster_dom_cooldown_spin = ScrollGuardSpinBox()
        self.cluster_dom_cooldown_spin.setRange(150, 5000)
        self.cluster_dom_cooldown_spin.setSingleStep(50)
        self.cluster_dom_cooldown_spin.setValue(850)
        advanced_layout.addWidget(self.cluster_dom_cooldown_spin)
        advanced_layout.addWidget(QLabel("DOM Max Repeat Attempts"))
        self.cluster_dom_repeat_spin = ScrollGuardSpinBox()
        self.cluster_dom_repeat_spin.setRange(1, 12)
        self.cluster_dom_repeat_spin.setValue(3)
        advanced_layout.addWidget(self.cluster_dom_repeat_spin)
        advanced_layout.addWidget(QLabel("DOM Evidence Weight"))
        self.cluster_dom_evidence_weight_spin = ScrollGuardDoubleSpinBox()
        self.cluster_dom_evidence_weight_spin.setRange(0.1, 3.5)
        self.cluster_dom_evidence_weight_spin.setSingleStep(0.1)
        self.cluster_dom_evidence_weight_spin.setValue(1.3)
        advanced_layout.addWidget(self.cluster_dom_evidence_weight_spin)
        worker_logic_hint = QLabel(
            "Cluster workers use automatic game logic and saved learning. CPU budget uses 100% = 1 shared logical core, so 200% equals a 2-core share. Target FPS uses the configured default above with a 10 FPS floor. DOM live mode is opt-in and browser-only. The graph editor remains for manual workflows."
        )
        worker_logic_hint.setObjectName("mutedLabel")
        worker_logic_hint.setWordWrap(True)
        advanced_layout.addWidget(worker_logic_hint)
        self.cluster_fps_probe_label = QLabel("No live worker FPS probe has been recorded yet.")
        self.cluster_fps_probe_label.setObjectName("mutedLabel")
        self.cluster_fps_probe_label.setWordWrap(True)
        advanced_layout.addWidget(self.cluster_fps_probe_label)
        advanced_layout.addWidget(QLabel("Detection Confidence"))
        self.detection_confidence_spin = ScrollGuardDoubleSpinBox()
        self.detection_confidence_spin.setRange(0.05, 1.0)
        self.detection_confidence_spin.setSingleStep(0.05)
        self.detection_confidence_spin.setValue(0.8)
        advanced_layout.addWidget(self.detection_confidence_spin)
        advanced_layout.addWidget(QLabel("Break Interval (seconds)"))
        self.break_interval_spin = ScrollGuardSpinBox()
        self.break_interval_spin.setRange(5, 3600)
        self.break_interval_spin.setValue(60)
        advanced_layout.addWidget(self.break_interval_spin)
        advanced_layout.addWidget(QLabel("Break Duration (seconds)"))
        self.break_duration_spin = ScrollGuardSpinBox()
        self.break_duration_spin.setRange(1, 600)
        self.break_duration_spin.setValue(2)
        advanced_layout.addWidget(self.break_duration_spin)
        advanced_layout.addWidget(QLabel("Default Max Steps"))
        self.settings_max_steps_spin = ScrollGuardSpinBox()
        self.settings_max_steps_spin.setRange(1, 1_000_000)
        self.settings_max_steps_spin.setValue(5000)
        advanced_layout.addWidget(self.settings_max_steps_spin)
        advanced_layout.addWidget(QLabel("Default Exploration Rate"))
        self.settings_exploration_spin = ScrollGuardDoubleSpinBox()
        self.settings_exploration_spin.setRange(0.0, 1.0)
        self.settings_exploration_spin.setSingleStep(0.05)
        self.settings_exploration_spin.setValue(0.2)
        advanced_layout.addWidget(self.settings_exploration_spin)
        root.addWidget(advanced_box)

        vision_box, vision_layout = self._make_group("Vision And OCR")
        self.settings_ocr_status_label = QLabel("OCR: checking...")
        self.settings_ocr_status_label.setWordWrap(True)
        self.settings_ocr_path_label = QLabel("OCR Path: not detected")
        self.settings_ocr_path_label.setWordWrap(True)
        refresh_ocr_button = QPushButton("Refresh OCR Status")
        refresh_ocr_button.clicked.connect(self.refresh_ocr_status)
        vision_layout.addWidget(self.settings_ocr_status_label)
        vision_layout.addWidget(self.settings_ocr_path_label)
        vision_layout.addWidget(refresh_ocr_button)
        root.addWidget(vision_box)

        antiban_box, antiban_layout = self._make_group("Anti-Ban Behavior")
        self.random_delay_checkbox = QCheckBox("Enable Random Delays")
        self.random_delay_checkbox.setChecked(True)
        self.breaks_checkbox = QCheckBox("Enable Random Breaks")
        self.breaks_checkbox.setChecked(True)
        self.human_mouse_checkbox2 = QCheckBox("Human-like Mouse Movement")
        self.human_mouse_checkbox2.setChecked(True)
        self.human_keyboard_checkbox2 = QCheckBox("Human-like Keyboard Timing")
        self.human_keyboard_checkbox2.setChecked(True)
        for widget in [self.random_delay_checkbox, self.breaks_checkbox, self.human_mouse_checkbox2, self.human_keyboard_checkbox2]:
            widget.stateChanged.connect(self._sync_antiban_settings)
            antiban_layout.addWidget(widget)
        root.addWidget(antiban_box)

        actions_box, actions_layout = self._make_group("Settings Actions")
        action_grid = QGridLayout()
        save_settings_button = QPushButton("Save Settings")
        save_settings_button.clicked.connect(self.save_application_settings)
        reload_settings_button = QPushButton("Reload Settings")
        reload_settings_button.clicked.connect(self.reload_application_settings)
        reset_defaults_button = QPushButton("Reset Defaults")
        reset_defaults_button.clicked.connect(self.reset_application_settings)
        export_snapshot_button = QPushButton("Export Runtime Snapshot")
        export_snapshot_button.clicked.connect(self.export_runtime_snapshot)
        load_model_button = QPushButton("Load Saved PPO")
        load_model_button.clicked.connect(self.load_saved_model)
        save_model_button = QPushButton("Save PPO Checkpoint")
        save_model_button.clicked.connect(self.save_model_checkpoint)
        evaluate_model_button = QPushButton("Evaluate PPO")
        evaluate_model_button.clicked.connect(self.evaluate_model_checkpoint)
        for index, widget in enumerate([
            save_settings_button,
            reload_settings_button,
            reset_defaults_button,
            export_snapshot_button,
            load_model_button,
            save_model_button,
            evaluate_model_button,
        ]):
            action_grid.addWidget(widget, index // 3, index % 3)
            action_grid.setColumnStretch(index % 3, 1)
        actions_layout.addLayout(action_grid)
        root.addWidget(actions_box)

        logs_box, logs_layout = self._make_group("Application Logs")
        self.logs_text = QTextEdit()
        self.logs_text.setReadOnly(True)
        logs_layout.addWidget(self.logs_text)
        root.addWidget(logs_box)
        root.addStretch()
        self._refresh_worker_fps_probe_hint()
        return self._wrap_scrollable_page(content)

    def select_theme(self, theme_key: str):
        if theme_key not in self.THEME_DEFINITIONS:
            theme_key = "terminal"
        self.current_theme = theme_key
        theme = self.THEME_DEFINITIONS[theme_key]
        self.setStyleSheet(build_app_stylesheet(theme_key))

        for key, action in self.theme_actions.items():
            action.setChecked(key == theme_key)

        if hasattr(self, "theme_selector"):
            index = self.theme_selector.findData(theme_key)
            if index >= 0 and self.theme_selector.currentIndex() != index:
                self.theme_selector.blockSignals(True)
                self.theme_selector.setCurrentIndex(index)
                self.theme_selector.blockSignals(False)

        if hasattr(self, "theme_description_label"):
            self.theme_description_label.setText(theme["description"])

        if hasattr(self, "behavior_editor"):
            self.behavior_editor.set_theme(theme_key)

        self._sync_model_dashboard_state()
        self.set_status(f"{theme['label']} theme applied")

    def change_theme(self, *_args):
        if not hasattr(self, "theme_selector"):
            return
        self.select_theme(self.theme_selector.currentData())

    def _append_log(self, message):
        if message is None:
            return
        text = str(message)
        if hasattr(self, "logs_text"):
            self.logs_text.append(text)
        if hasattr(self, "log_output"):
            self.log_output.append(text)

    def _update_mode_label(self):
        browser_mode = self.browser_radio.isChecked()
        if hasattr(self, "url_input"):
            self.url_input.setEnabled(browser_mode)
        if hasattr(self, "exe_input"):
            self.exe_input.setEnabled(not browser_mode)
        if self.input_manager is not None:
            self.input_manager.game_mode = "browser" if browser_mode else "desktop"
        self.set_status("Browser mode selected" if browser_mode else "Desktop mode selected")

    def _sync_antiban_settings(self):
        if self.input_manager is None or not hasattr(self.input_manager, "antiban"):
            return
        self.input_manager.antiban["random_delay"] = self.random_delay_checkbox.isChecked() if hasattr(self, "random_delay_checkbox") else True
        self.input_manager.antiban["random_breaks"] = self.breaks_checkbox.isChecked() if hasattr(self, "breaks_checkbox") else True
        self.input_manager.antiban["human_mouse"] = (
            self.human_mouse_checkbox2.isChecked() if hasattr(self, "human_mouse_checkbox2") else self.human_mouse_checkbox.isChecked()
        )
        self.input_manager.antiban["human_keyboard"] = (
            self.human_keyboard_checkbox2.isChecked() if hasattr(self, "human_keyboard_checkbox2") else self.human_keyboard_checkbox.isChecked()
        )

    def set_region_preset(self, x: int, y: int, w: int, h: int):
        self.region_x.setText(str(x))
        self.region_y.setText(str(y))
        self.region_w.setText(str(w))
        self.region_h.setText(str(h))
        self.apply_game_region()

    def _select_region_interactively(self):
        overlay = _region_selector_overlay_type()()
        self.showMinimized()
        overlay.show()
        from PySide6.QtWidgets import QApplication
        while overlay.isVisible():
            QApplication.processEvents()
            time.sleep(0.01)
        self.showNormal()
        self.raise_()
        self.activateWindow()
        return overlay.get_selected_region()

    def capture_region_drag(self):
        try:
            region = self._select_region_interactively()
        except Exception as exc:
            QMessageBox.warning(self, "Capture Error", f"Region capture failed: {exc}")
            return
        if not region:
            self.set_status("Region capture cancelled")
            return
        x, y, w, h = region
        if w <= 0 or h <= 0:
            QMessageBox.warning(self, "Capture Error", "Selected region must have a positive width and height.")
            return
        self.set_region_preset(x, y, w, h)
        self.set_status(f"Captured region {w} x {h}")

    def preview_game_region(self):
        region = self._validated_game_region()
        if region is None:
            return
        try:
            from vision.screen_capture import capture_screen
            frame = capture_screen(region)
        except Exception as exc:
            QMessageBox.warning(self, "Preview Error", f"Unable to capture the selected region: {exc}")
            return
        rgb_frame = frame[:, :, ::-1].copy()
        height, width, _channels = rgb_frame.shape
        qimage = QImage(rgb_frame.data, width, height, width * 3, QImage.Format.Format_RGB888).copy()
        pixmap = QPixmap.fromImage(qimage)
        dialog = QDialog(self)
        dialog.setWindowTitle("Region Preview")
        dialog.resize(900, 600)
        layout = QVBoxLayout(dialog)
        label = QLabel()
        label.setAlignment(Qt.AlignCenter)
        label.setPixmap(pixmap.scaled(860, 560, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        layout.addWidget(label)
        dialog.exec()

    def save_game_region(self):
        region = self._validated_game_region()
        if region is None:
            return
        self.region_file.write_text(json.dumps(region, indent=2), encoding="utf-8")
        self.set_status(f"Saved region to {self.region_file.name}")

    def load_game_region(self):
        if not self.region_file.exists():
            self.set_status("No saved region file found")
            return
        region = json.loads(self.region_file.read_text(encoding="utf-8"))
        self.set_region_preset(region["left"], region["top"], region["width"], region["height"])
        self.set_status(f"Loaded region from {self.region_file.name}")

    def get_game_region(self):
        try:
            return {"left": int(self.region_x.text()), "top": int(self.region_y.text()), "width": int(self.region_w.text()), "height": int(self.region_h.text())}
        except ValueError:
            QMessageBox.warning(self, "Region Error", "Region values must be valid integers.")
            return {"left": 0, "top": 0, "width": 1280, "height": 720}

    def apply_game_region(self):
        region = self._validated_game_region()
        if region is None:
            return False
        self.set_status(
            f"Region applied: left={region['left']}, top={region['top']}, size={region['width']} x {region['height']}"
        )
        return True

    def start_ai(self):
        if self.ai_running:
            return
        if self.input_manager is None or not hasattr(self.input_manager, "execute_behavior_blocks"):
            self._queue_log("Input manager is unavailable. Runtime execution is disabled.")
            self.set_status("Input manager is unavailable")
            return
        region = self._validated_game_region()
        if region is None:
            return
        if hasattr(self, "desktop_radio") and self.desktop_radio.isChecked():
            window_title = self._current_desktop_window_title()
            if window_title:
                window_region = _get_window_region(window_title)
                if window_region:
                    region = window_region
                    self.set_region_preset(
                        window_region["left"],
                        window_region["top"],
                        window_region["width"],
                        window_region["height"],
                    )
        self._apply_training_settings()
        self.apply_behavior()
        behavior_graph = self.behavior_editor.get_behavior_graph() if hasattr(self, "behavior_editor") else {}
        if not behavior_graph:
            self._queue_log("Behavior graph is empty. Training will only capture state until nodes are added.")

        self.ai_running = True
        self._training_steps_completed = 0
        self.current_state["reward"] = 0.0
        self.current_state["action"] = "running"
        self._sync_training_ui_state()
        self._queue_log("AI training started.")
        self.set_status("AI training started")

        def runner():
            try:
                from vision.screen_capture import capture_screen
            except Exception as exc:
                self._queue_log(f"Training startup error: {exc}")
                self.ai_running = False
                self.current_state["action"] = "idle"
                return

            while self.ai_running:
                try:
                    graph = behavior_graph
                    frame = capture_screen(region)
                    game_state, reward = self.input_manager.update_game_state(frame)
                    if not isinstance(game_state, dict):
                        game_state = {}
                    reward_value = float(reward or 0.0)
                    action_name = game_state.get("action", "running")
                    self.current_state["xp"] = game_state.get("xp", self.current_state.get("xp", 0))
                    self.current_state["gold"] = game_state.get("gold", self.current_state.get("gold", 0))
                    self.current_state["reward"] = reward_value
                    self.current_state["action"] = action_name
                    self._training_steps_completed += 1
                    self.episode_count = self._training_steps_completed
                    self.total_reward += reward_value
                    self.exploration_rate = float(self.exploration_spin.value())
                    self._queue_metric_point(
                        self._training_steps_completed,
                        self.current_state["xp"],
                        self.current_state["gold"],
                        reward_value,
                        action_name,
                    )
                    self._queue_reward_entry(f"Step {self._training_steps_completed}: reward {reward_value:.2f}")
                    if graph:
                        self.input_manager.execute_behavior_blocks(graph, game_state, editor=None)
                    time.sleep(0.15 if self.quick_checkbox.isChecked() else 0.5)
                except Exception as exc:
                    self._queue_log(f"Training loop error: {exc}")
                    break
            self.ai_running = False
            self.current_state["action"] = "idle"

        threading.Thread(target=runner, daemon=True).start()

    def stop_ai(self):
        self.ai_running = False
        self.current_state["action"] = "idle"
        self._sync_training_ui_state()
        self._queue_log("AI training stopped.")
        self.set_status("AI training stopped")

    def toggle_mouse(self):
        if self.input_manager is not None:
            self.input_manager.mouse_enabled = self.mouse_checkbox.isChecked()
        self.set_status("Mouse input enabled" if self.mouse_checkbox.isChecked() else "Mouse input disabled")

    def toggle_keyboard(self):
        if self.input_manager is not None:
            self.input_manager.keyboard_enabled = self.keyboard_checkbox.isChecked()
        self.set_status("Keyboard input enabled" if self.keyboard_checkbox.isChecked() else "Keyboard input disabled")

    def apply_behavior(self):
        if not hasattr(self, "behavior_editor"):
            return
        graph = self.behavior_editor.get_behavior_graph()
        agent = getattr(self.input_manager, "agent", None) if self.input_manager is not None else None
        if agent is not None and hasattr(agent, "set_behavior_graph"):
            agent.set_behavior_graph(graph)
        self.set_status("Behavior applied to AI")

    def toggle_debug_overlay(self):
        if self.debug_overlay is None or not self.debug_overlay.isVisible():
            self.debug_overlay = _debug_overlay_window_type()(self.get_game_region(), self, self)
            self.debug_overlay.show()
            self.debug_overlay_btn.setText("Hide Debug Overlay")
            self.set_status("Debug overlay shown")
        else:
            self.debug_overlay.close()
            self.debug_overlay = None
            self.debug_overlay_btn.setText("Show Debug Overlay")
            self.set_status("Debug overlay hidden")

    def start_ppo_training(self):
        if self.ppo_trainer is None:
            self.set_status("PPO trainer is unavailable")
            return
        if self.ppo_training:
            return
        self.ppo_training = True
        self._ppo_status_text = "Training"
        self._sync_training_ui_state()
        self.set_status("PPO training started")

        def runner():
            try:
                self.ppo_trainer.train(timesteps=self.max_steps_spin.value())
            except Exception as exc:
                self._queue_log(f"PPO error: {exc}")
            finally:
                self.ppo_training = False
                self._ppo_status_text = "Idle"

        threading.Thread(target=runner, daemon=True).start()

    def stop_ppo_training(self):
        if self.ppo_trainer is not None and hasattr(self.ppo_trainer, "stop"):
            self.ppo_trainer.stop()
        self.ppo_training = False
        self._ppo_status_text = "Stopped"
        self._sync_training_ui_state()
        self.set_status("PPO training stopped")

    def reset_charts(self):
        for series in [self.xp_series, self.gold_series, self.action_series, self.reward_series, self.loss_series]:
            series.clear()
        self.episode_count = 0
        self.total_reward = 0.0
        self.exploration_rate = 1.0
        self._training_steps_completed = 0
        self._action_value_map.clear()
        self.progress_bar.setRange(0, self.max_steps_spin.value())
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat(f"Training Progress: 0/{self.max_steps_spin.value()}")
        self.episode_count_label.setText("Episodes: 0")
        self.total_reward_label.setText("Total Reward: 0.00")
        self.average_reward_label.setText("Average Reward: 0.00")
        self.exploration_rate_label.setText("Exploration Rate: 1.000")
        self.set_status("Charts reset")

    def export_metrics(self):
        filename, _ = QFileDialog.getSaveFileName(self, "Export Metrics", "metrics.json", "JSON Files (*.json)")
        if not filename:
            return
        payload = {
            "episodes": self.episode_count,
            "total_reward": self.total_reward,
            "average_reward": self.total_reward / max(1, self.episode_count),
            "reward_points": [(point.x(), point.y()) for point in self.reward_series.points()],
            "loss_points": [(point.x(), point.y()) for point in self.loss_series.points()],
        }
        with open(filename, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        self.set_status(f"Metrics exported: {os.path.basename(filename)}")

    def _current_behavior_graph_payload(self):
        if not hasattr(self, "behavior_editor"):
            return {}
        try:
            graph = self.behavior_editor.get_behavior_graph()
        except Exception:
            return {}
        return graph if isinstance(graph, dict) else {}

    def _cluster_worker_config(self, worker_id: str) -> ClusterWorkerConfig:
        from distributed.cluster_worker_runtime import ClusterWorkerConfig

        region = self.get_game_region() if hasattr(self, "get_game_region") else {"left": 0, "top": 0, "width": 1280, "height": 720}
        browser_url = self._current_browser_url()
        desktop_exe = self.exe_input.text().strip() if hasattr(self, "exe_input") else ""
        desktop_window_title = self._current_desktop_window_title()
        worker_record = self._worker_record_by_id(worker_id)
        startup_override = self.cluster_worker_startup_overrides.get(worker_id) if hasattr(self, "cluster_worker_startup_overrides") else None
        force_legacy_launch = bool((startup_override or {}).get("force_legacy_launch", False))
        watch_reward_ads = (
            bool(worker_record.get("watch_reward_ads_enabled"))
            if worker_record is not None
            else (self.cluster_watch_ads_checkbox.isChecked() if hasattr(self, "cluster_watch_ads_checkbox") else False)
        )
        return ClusterWorkerConfig(
            worker_id=worker_id,
            mode=self._current_game_mode_label().lower(),
            browser_url=browser_url,
            desktop_exe=desktop_exe,
            desktop_window_title=desktop_window_title,
            capture_region=region,
            behavior_graph={},
            model_name=self._cluster_model_summary(),
            memory_limit_gb=self._cluster_worker_limit_gb(),
            cpu_limit_percent=self._cluster_worker_cpu_limit_percent(),
            target_fps=self._cluster_worker_target_fps(),
            gpu_acceleration_enabled=self._cluster_gpu_enabled() and not force_legacy_launch,
            mouse_enabled=self.mouse_checkbox.isChecked() if hasattr(self, "mouse_checkbox") else True,
            keyboard_enabled=self.keyboard_checkbox.isChecked() if hasattr(self, "keyboard_checkbox") else True,
            antiban_config=dict(getattr(self.input_manager, "antiban", {})) if self.input_manager is not None else {},
            quick_mode=self.quick_checkbox.isChecked() if hasattr(self, "quick_checkbox") else False,
            watch_reward_ads=watch_reward_ads,
            auto_learning_enabled=(
                self.cluster_auto_learning_checkbox.isChecked() if hasattr(self, "cluster_auto_learning_checkbox") else True
            ),
            learning_store_dir=str(self.project_root / "data" / "worker_learning"),
            browser_dom_drive_mode=self._cluster_dom_drive_mode(),
            dom_confirmation_required=(
                self.cluster_dom_confirmation_checkbox.isChecked() if hasattr(self, "cluster_dom_confirmation_checkbox") else True
            ),
            dom_live_cooldown_ms=self.cluster_dom_cooldown_spin.value() if hasattr(self, "cluster_dom_cooldown_spin") else 850,
            dom_live_max_repeat_attempts=self.cluster_dom_repeat_spin.value() if hasattr(self, "cluster_dom_repeat_spin") else 3,
            dom_evidence_weight=(
                self.cluster_dom_evidence_weight_spin.value() if hasattr(self, "cluster_dom_evidence_weight_spin") else 1.3
            ),
            browser_prewarm_enabled=self._cluster_browser_prewarm_enabled(),
            preview_target_fps=self._cluster_preview_target_fps(),
            control_preview_target_fps=self._cluster_control_preview_target_fps(),
        )

    def _start_cluster_worker_runtime(self, worker_id: str):
        from distributed.cluster_worker_runtime import ClusterWorkerRuntime

        self._stop_cluster_worker_runtime(worker_id)
        config = self._cluster_worker_config(worker_id)
        runtime = None
        claimed_standby = False
        if config.mode.lower() == "browser":
            runtime = self._browser_prewarm_pool().claim(
                config,
                log_callback=lambda message: self._queue_log(message),
            )
            claimed_standby = runtime is not None
        if runtime is None:
            runtime = ClusterWorkerRuntime(
                config,
                log_callback=lambda message: self._queue_log(message),
            )
        self.cluster_worker_runtimes[worker_id] = runtime
        if claimed_standby:
            self.log_cluster_event(f"{worker_id} claimed a prewarmed browser session.")
        else:
            if config.mode.lower() == "browser":
                self._queue_log(f"{worker_id}: no compatible standby browser session was ready, starting cold launch.")
            runtime.start()
        if worker_id in self.worker_control_windows:
            self._set_worker_manual_control(worker_id, True)
        if claimed_standby:
            self._reconcile_browser_prewarm_pool()

    def _stop_cluster_worker_runtime(self, worker_id: str):
        runtime = self.cluster_worker_runtimes.pop(worker_id, None)
        if runtime is None:
            return
        persist_now = getattr(runtime, "persist_now", None)
        if callable(persist_now):
            try:
                persist_now()
            except Exception:
                pass
        runtime.stop()
        if runtime.ident is not None:
            runtime.join(timeout=2.0)

    def _cluster_startup_retry_state(self, worker_id: str) -> dict:
        state = self.cluster_worker_startup_overrides.get(worker_id)
        if not isinstance(state, dict):
            state = {"restart_attempts": 0, "restart_pending": False, "force_legacy_launch": False}
            self.cluster_worker_startup_overrides[worker_id] = state
        state.setdefault("restart_attempts", 0)
        state.setdefault("restart_pending", False)
        state.setdefault("force_legacy_launch", False)
        return state

    def _clear_cluster_startup_overrides(self):
        self.cluster_worker_startup_overrides.clear()

    def _is_worker_startup_bootstrap_error(self, snapshot: dict) -> bool:
        status = str(snapshot.get("status") or "").strip().lower()
        if status != "error":
            return False
        last_error = str(snapshot.get("last_error") or "").strip().lower()
        progress = str(snapshot.get("progress") or "").strip().lower()
        if "failed after 0 steps" not in progress:
            return False
        failure_markers = (
            "playwright worker startup failed",
            "connection closed while reading from the driver",
            "browser worker page is not initialized",
            "target page, context or browser has been closed",
            "browser has been closed",
            "playwright is not initialized for browser launch",
        )
        return any(marker in last_error for marker in failure_markers)

    def _queue_cluster_worker_safe_restart(self, worker_id: str):
        state = self._cluster_startup_retry_state(worker_id)
        if bool(state.get("restart_pending", False)):
            return False
        next_attempt = int(state.get("restart_attempts", 0)) + 1
        max_attempts = 3
        if next_attempt > max_attempts:
            return False
        state["restart_attempts"] = next_attempt
        state["restart_pending"] = True
        state["force_legacy_launch"] = True
        self._stop_cluster_worker_runtime(worker_id)
        retry_delay_ms = 900 * next_attempt
        self._queue_log(
            f"{worker_id}: browser startup was unstable, retrying in legacy browser mode "
            f"(attempt {next_attempt}/{max_attempts}) after {retry_delay_ms} ms."
        )
        self.set_status(f"Retrying {worker_id} in legacy browser mode ({next_attempt}/{max_attempts})")

        def restart_worker():
            latest_state = self._cluster_startup_retry_state(worker_id)
            latest_state["restart_pending"] = False
            if not self.cluster_connected:
                return
            if not any(worker.get("id") == worker_id for worker in self.worker_data):
                return
            self._start_cluster_worker_runtime(worker_id)

        QTimer.singleShot(retry_delay_ms, restart_worker)
        return True

    def _stop_all_cluster_runtimes(self):
        for worker_id in list(self.cluster_worker_runtimes.keys()):
            self._stop_cluster_worker_runtime(worker_id)

    def _sync_cluster_runtime_snapshots(self):
        stale_worker_ids = []
        pending_safe_restarts = []
        for worker in self.worker_data:
            runtime = self.cluster_worker_runtimes.get(worker["id"])
            if runtime is None:
                continue
            snapshot = runtime.snapshot()
            worker["status"] = snapshot.get("status", worker.get("status", "idle"))
            worker["task"] = snapshot.get("task", worker.get("task", "Waiting For Work"))
            worker["game"] = snapshot.get("game", worker.get("game", self._current_game_label()))
            worker["profile"] = snapshot.get("profile", worker.get("profile", self._current_game_profile().name))
            worker["strategy"] = snapshot.get("strategy", worker.get("strategy", self._current_game_profile().strategy))
            worker["mode"] = snapshot.get("mode", worker.get("mode", self._current_game_mode_label()))
            worker["ads"] = snapshot.get("ads", worker.get("ads", "Skip Reward Ads"))
            worker["learning"] = snapshot.get("learning", worker.get("learning", "enabled"))
            worker["capture"] = snapshot.get("capture", worker.get("capture", self._cluster_capture_summary()))
            worker["model"] = snapshot.get("model", worker.get("model", self._cluster_model_summary()))
            worker["progress"] = snapshot.get("progress", worker.get("progress", self._cluster_progress_summary()))
            worker["dom_drive_mode"] = snapshot.get("dom_drive_mode", worker.get("dom_drive_mode", self._cluster_dom_drive_mode()))
            worker["dom_last_action"] = snapshot.get("dom_last_action", worker.get("dom_last_action", ""))
            worker["dom_last_confirmation"] = snapshot.get("dom_last_confirmation", worker.get("dom_last_confirmation", ""))
            worker["dom_fallback_reason"] = snapshot.get("dom_fallback_reason", worker.get("dom_fallback_reason", ""))
            worker["dom_top_candidates"] = list(snapshot.get("dom_top_candidates", worker.get("dom_top_candidates", [])) or [])
            worker["cpu"] = snapshot.get("cpu", worker.get("cpu", f"0/{self._cluster_worker_cpu_limit_percent():.0f}%"))
            worker["cpu_detail"] = snapshot.get("cpu_detail", worker.get("cpu_detail", "No CPU telemetry yet."))
            worker["gpu"] = snapshot.get("gpu", worker.get("gpu", "0/100%"))
            worker["gpu_detail"] = snapshot.get("gpu_detail", worker.get("gpu_detail", "No GPU telemetry yet."))
            worker["cpu_limit_percent"] = float(snapshot.get("cpu_limit_percent", worker.get("cpu_limit_percent", self._cluster_worker_cpu_limit_percent())))
            worker["mem"] = snapshot.get("mem", worker.get("mem", f"0.0/{self._cluster_worker_limit_gb():.1f} GB"))
            worker["memory_limit_gb"] = float(snapshot.get("memory_limit_gb", self._cluster_worker_limit_gb()))
            if snapshot.get("last_error"):
                worker["capture"] = f"{worker['capture']} | Error: {snapshot['last_error']}"
            if (
                self.cluster_connected
                and worker.get("mode", "").strip().lower() == "browser"
                and self._is_worker_startup_bootstrap_error(snapshot)
            ):
                startup_state = self._cluster_startup_retry_state(worker["id"])
                max_attempts = 3
                if int(startup_state.get("restart_attempts", 0)) < max_attempts:
                    worker["status"] = "starting"
                    worker["task"] = "Retrying Browser Startup"
                    current_attempt = int(startup_state.get("restart_attempts", 0)) + (
                        0 if bool(startup_state.get("restart_pending", False)) else 1
                    )
                    worker["progress"] = (
                        f"Legacy browser retry after Playwright startup error "
                        f"({min(current_attempt, max_attempts)}/{max_attempts})"
                    )
                    worker["gpu"] = "0/100%"
                    worker["gpu_detail"] = "Queued legacy browser retry."
                    if not bool(startup_state.get("restart_pending", False)):
                        pending_safe_restarts.append(worker["id"])
            if not snapshot.get("alive") and snapshot.get("status") in {"stopped", "error"}:
                stale_worker_ids.append(worker["id"])
        for worker_id in stale_worker_ids:
            self.cluster_worker_runtimes.pop(worker_id, None)
        for worker_id in pending_safe_restarts:
            self._queue_cluster_worker_safe_restart(worker_id)

    def show_worker_context_menu(self, pos):
        row = self.worker_table.rowAt(pos.y())
        if row >= 0:
            self.worker_table.selectRow(row)
        menu = QMenu(self.worker_table)
        add_action = menu.addAction("Add Worker")
        import_bundle_action = menu.addAction("Import Worker Bundle")
        menu.addSeparator()
        open_preview_action = menu.addAction("Open Live Preview")
        close_preview_action = menu.addAction("Close Live Preview")
        open_control_action = menu.addAction("Open Interactive Control")
        close_control_action = menu.addAction("Close Interactive Control")
        selected_worker = self.worker_data[self.worker_table.currentRow()] if 0 <= self.worker_table.currentRow() < len(self.worker_data) else None
        toggle_ads_action = menu.addAction(
            "Disable Reward Ads" if selected_worker and bool(selected_worker.get("watch_reward_ads_enabled")) else "Enable Reward Ads"
        )
        menu.addSeparator()
        export_bundle_action = menu.addAction("Export Worker Bundle")
        menu.addSeparator()
        rename_action = menu.addAction("Rename Worker")
        delete_action = menu.addAction("Delete Worker")
        has_selection = self.worker_table.currentRow() >= 0
        browser_selection = has_selection and selected_worker is not None and str(
            selected_worker.get("mode", self._current_game_mode_label())
        ).strip().lower() == "browser"
        open_preview_action.setEnabled(has_selection)
        close_preview_action.setEnabled(
            has_selection
            and self.worker_table.currentRow() < len(self.worker_data)
            and self.worker_data[self.worker_table.currentRow()]["id"] in self.worker_preview_windows
        )
        open_control_action.setEnabled(browser_selection)
        close_control_action.setEnabled(
            browser_selection
            and self.worker_table.currentRow() < len(self.worker_data)
            and self.worker_data[self.worker_table.currentRow()]["id"] in self.worker_control_windows
        )
        toggle_ads_action.setEnabled(browser_selection)
        export_bundle_action.setEnabled(has_selection)
        rename_action.setEnabled(has_selection)
        delete_action.setEnabled(has_selection)
        action = menu.exec(self.worker_table.viewport().mapToGlobal(pos))
        current_row = self.worker_table.currentRow()
        connected = self.cluster_connected
        if action == add_action:
            if len(self.worker_data) >= self.MAX_CLUSTER_WORKERS:
                self.log_cluster_event(f"Worker limit reached ({self.MAX_CLUSTER_WORKERS}).")
                return
            worker_id, ok = QInputDialog.getText(self, "Add Worker", "Worker ID:")
            if ok and worker_id:
                browser_mode = self._current_game_mode_label().lower() == "browser"
                active_desktop_runtime = any(runtime.is_alive() for runtime in self.cluster_worker_runtimes.values()) if not browser_mode else False
                status = (
                    self._cluster_browser_start_status()
                    if connected and browser_mode
                    else ("running" if connected and not active_desktop_runtime else ("queued" if connected else "idle"))
                )
                task = None if status != "queued" else "Queued For Shared Desktop Window"
                self.worker_data.append(self._build_cluster_worker(worker_id=worker_id, status=status, task=task))
                self.update_cluster_ui(self.worker_data, connected=connected)
                if connected and status in {"running", "prewarming"}:
                    self._start_cluster_worker_runtime(worker_id)
        elif action == import_bundle_action:
            self.import_worker_bundle_file()
        elif action == open_preview_action and current_row >= 0:
            self.open_worker_preview(self.worker_data[current_row]["id"])
        elif action == close_preview_action and current_row >= 0:
            self.close_worker_preview(self.worker_data[current_row]["id"])
        elif action == open_control_action and current_row >= 0:
            self.open_worker_control(self.worker_data[current_row]["id"])
        elif action == close_control_action and current_row >= 0:
            self.close_worker_control(self.worker_data[current_row]["id"])
        elif action == toggle_ads_action and current_row >= 0:
            worker = self.worker_data[current_row]
            self._set_worker_reward_ads(worker["id"], not bool(worker.get("watch_reward_ads_enabled")))
        elif action == export_bundle_action and current_row >= 0:
            self.export_selected_worker_bundle()
        elif action == rename_action and current_row >= 0:
            current_id = self.worker_table.item(current_row, 0).text()
            worker_id, ok = QInputDialog.getText(self, "Rename Worker", "Worker ID:", text=current_id)
            if ok and worker_id:
                self._stop_cluster_worker_runtime(current_id)
                self.close_worker_preview(current_id)
                self.close_worker_control(current_id)
                self.worker_data[current_row]["id"] = worker_id
                self.update_cluster_ui(self.worker_data, connected=connected)
        elif action == delete_action and current_row >= 0:
            self._stop_cluster_worker_runtime(self.worker_data[current_row]["id"])
            self.close_worker_preview(self.worker_data[current_row]["id"])
            self.close_worker_control(self.worker_data[current_row]["id"])
            self.worker_data.pop(current_row)
            self.update_cluster_ui(self.worker_data, connected=connected)

    def update_cluster_ui(self, workers, connected: bool):
        previous_row = self._selected_worker_row()
        self.cluster_connected = connected
        self.worker_data = [
            self._create_worker_record(
                worker_id=worker.get("id"),
                status=worker.get("status", "idle"),
                cpu=worker.get("cpu"),
                gpu=worker.get("gpu"),
                mem=worker.get("mem"),
                task=worker.get("task"),
                game=worker.get("game"),
                profile=worker.get("profile"),
                strategy=worker.get("strategy"),
                mode=worker.get("mode"),
                ads=worker.get("ads"),
                watch_reward_ads_enabled=worker.get("watch_reward_ads_enabled"),
                learning=worker.get("learning"),
                capture=worker.get("capture"),
                model=worker.get("model"),
                progress=worker.get("progress"),
                memory_limit_gb=worker.get("memory_limit_gb"),
                cpu_limit_percent=worker.get("cpu_limit_percent"),
                cpu_detail=worker.get("cpu_detail"),
                gpu_detail=worker.get("gpu_detail"),
            )
            for worker in workers
        ]
        active_worker_ids = {worker["id"] for worker in self.worker_data}
        for worker_id in [key for key in self.cluster_worker_runtimes.keys() if key not in active_worker_ids]:
            self._stop_cluster_worker_runtime(worker_id)
        for worker_id in [key for key in self.worker_preview_windows.keys() if key not in active_worker_ids]:
            self.close_worker_preview(worker_id)
        for worker_id in [key for key in self.worker_control_windows.keys() if key not in active_worker_ids]:
            self.close_worker_control(worker_id)
        status_text = "Connected" if connected else "Disconnected"
        self.cluster_status_label.setText(f"Status: {status_text}")
        self.worker_table.setRowCount(len(self.worker_data))
        for row, worker in enumerate(self.worker_data):
            self.worker_table.setItem(row, 0, QTableWidgetItem(worker["id"]))
            self.worker_table.setItem(row, 1, QTableWidgetItem(worker["status"]))
            self.worker_table.setItem(row, 2, QTableWidgetItem(worker["task"]))
            self.worker_table.setItem(row, 3, QTableWidgetItem(worker["game"]))
            self.worker_table.setItem(row, 4, QTableWidgetItem(worker["mode"]))
            self.worker_table.setItem(row, 5, QTableWidgetItem(worker["cpu"]))
            self.worker_table.setItem(row, 6, QTableWidgetItem(worker["gpu"]))
            self.worker_table.setItem(row, 7, QTableWidgetItem(worker["mem"]))
        if self.worker_data:
            target_row = min(max(previous_row, 0), len(self.worker_data) - 1)
            self.worker_table.selectRow(target_row)
        else:
            self.worker_table.clearSelection()
        self._sync_cluster_ui_state()

    def log_cluster_event(self, message: str):
        timestamp = time.strftime("%H:%M:%S")
        self.cluster_last_event = message
        self.cluster_last_event_at = time.time()
        self.cluster_event_count += 1
        self.cluster_log.append(f"[{timestamp}] {message}")
        self._sync_cluster_ui_state()
        self.set_status(message)

    def connect_to_cluster(self):
        if self.cluster_connected:
            self.cluster_connected_at = None
            self._clear_cluster_startup_overrides()
            self._close_all_worker_previews()
            self._close_all_worker_controls()
            self._stop_all_cluster_runtimes()
            disconnected_workers = [
                self._build_cluster_worker(
                    worker["id"],
                    status="offline",
                    task="Offline",
                    watch_reward_ads_enabled=worker.get("watch_reward_ads_enabled"),
                )
                for worker in self.worker_data
            ]
            self.update_cluster_ui(disconnected_workers, connected=False)
            self._reconcile_browser_prewarm_pool()
            self.log_cluster_event("Disconnected from cluster.")
            return

        self.cluster_connected_at = time.time()
        self.cluster_event_count = 0
        self._clear_cluster_startup_overrides()
        browser_mode = self._current_game_mode_label().lower() == "browser"
        if self.worker_data:
            workers = []
            for index, worker in enumerate(self.worker_data[: self.MAX_CLUSTER_WORKERS]):
                if browser_mode:
                    status = self._cluster_browser_start_status()
                else:
                    status = "running" if index == 0 else "queued"
                workers.append(
                    self._build_cluster_worker(
                        worker["id"],
                        status=status,
                        watch_reward_ads_enabled=worker.get("watch_reward_ads_enabled"),
                    )
                )
        else:
            worker_count = self._desired_cluster_worker_count()
            workers = []
            for index in range(worker_count):
                if browser_mode:
                    status = self._cluster_browser_start_status()
                else:
                    status = "running" if index == 0 else "queued"
                workers.append(self._build_cluster_worker(status=status))
        self.update_cluster_ui(workers, connected=True)
        active_workers = 0
        for worker in self.worker_data:
            if browser_mode or active_workers == 0:
                self._start_cluster_worker_runtime(worker["id"])
                active_workers += 1
        self._reconcile_browser_prewarm_pool()
        message = (
            f"Connected to cluster for {self._current_game_label()} ({self._current_game_mode_label()}) "
            f"with {len(workers)} worker(s) @ {self._cluster_worker_limit_gb():.1f} GB."
        )
        if browser_mode:
            message += (
                f" Browser workers launch isolated headless browser sessions, prewarm capture before autoplay, and then begin self-play. "
                f"Reward ads are {'enabled' if self.cluster_watch_ads else 'disabled'}."
            )
        if not browser_mode and len(workers) > 1:
            message += " Desktop mode uses one active controller and queues the rest on the shared window."
        self.log_cluster_event(message)

    def start_worker(self):
        if not self.cluster_connected:
            self.log_cluster_event("Connect to the cluster before starting workers.")
            return
        browser_mode = self._current_game_mode_label().lower() == "browser"
        active_desktop_runtime = any(runtime.is_alive() for runtime in self.cluster_worker_runtimes.values()) if not browser_mode else False
        resume_index, resume_worker = self._selected_or_first_worker(self._worker_is_resumable)
        if resume_worker is not None:
            worker_id = str(resume_worker["id"])
            status = self._cluster_browser_start_status() if browser_mode else ("running" if not active_desktop_runtime else "queued")
            task = None if status == "running" else "Queued For Shared Desktop Window"
            self.worker_data[resume_index] = self._build_cluster_worker(
                worker_id=worker_id,
                status=status,
                task=task,
                watch_reward_ads_enabled=resume_worker.get("watch_reward_ads_enabled"),
            )
            self.update_cluster_ui(self.worker_data, connected=True)
            if status in {"running", "prewarming"}:
                self._start_cluster_worker_runtime(worker_id)
            self.log_cluster_event(f"Resumed {worker_id}.")
            return
        if len(self.worker_data) >= self.MAX_CLUSTER_WORKERS:
            self.log_cluster_event(f"Worker limit reached ({self.MAX_CLUSTER_WORKERS}).")
            return
        worker_id = f"worker-{self._next_worker_index}"
        status = self._cluster_browser_start_status() if browser_mode else ("running" if not active_desktop_runtime else "queued")
        task = None if status == "running" else "Queued For Shared Desktop Window"
        self.worker_data.append(self._build_cluster_worker(worker_id=worker_id, status=status, task=task))
        self.update_cluster_ui(self.worker_data, connected=True)
        if status in {"running", "prewarming"}:
            self._start_cluster_worker_runtime(worker_id)
        suffix = " using headless Chromium." if browser_mode else "."
        self.log_cluster_event(
            f"Started {worker_id} for {self._current_game_label()} with {self._cluster_worker_limit_gb():.1f} GB budget{suffix} "
            f"Auto-learning is {'enabled' if self.cluster_auto_learning_enabled else 'disabled'}."
        )

    def stop_worker(self):
        if not self.cluster_connected:
            self.log_cluster_event("Connect to the cluster before stopping workers.")
            return
        if not self.worker_data:
            self.log_cluster_event("No workers to stop.")
            return
        target_index, worker = self._selected_or_first_worker(self._worker_is_stoppable)
        if worker is None:
            self.log_cluster_event("No running or queued worker is available to stop.")
            return
        worker_id = str(worker["id"])
        self._stop_cluster_worker_runtime(worker_id)
        self.worker_data[target_index] = self._build_cluster_worker(
            worker_id=worker_id,
            status="stopped",
            task="Stopped (ready to resume)",
            watch_reward_ads_enabled=worker.get("watch_reward_ads_enabled"),
        )
        self.update_cluster_ui(self.worker_data, connected=True)
        if self._current_game_mode_label().lower() == "desktop" and self.worker_data and not self.cluster_worker_runtimes:
            queued_index, queued_worker = self._selected_or_first_worker(
                lambda item: str((item or {}).get("status", "")).strip().lower() == "queued"
            )
            if queued_worker is not None:
                queued_id = str(queued_worker["id"])
                self.worker_data[queued_index] = self._build_cluster_worker(
                    worker_id=queued_id,
                    status="running",
                    watch_reward_ads_enabled=queued_worker.get("watch_reward_ads_enabled"),
                )
                self.update_cluster_ui(self.worker_data, connected=True)
                self._start_cluster_worker_runtime(queued_id)
        self.log_cluster_event(f"Stopped {worker_id} and kept it ready to resume.")

    def scale_up(self):
        if not self.cluster_connected:
            self.log_cluster_event("Connect to the cluster before adding workers.")
            return
        if len(self.worker_data) >= self.MAX_CLUSTER_WORKERS:
            self.log_cluster_event(f"Worker limit reached ({self.MAX_CLUSTER_WORKERS}).")
            return
        worker_id = f"worker-{self._next_worker_index}"
        browser_mode = self._current_game_mode_label().lower() == "browser"
        active_desktop_runtime = any(runtime.is_alive() for runtime in self.cluster_worker_runtimes.values()) if not browser_mode else False
        status = self._cluster_browser_start_status() if browser_mode else ("running" if not active_desktop_runtime else "queued")
        task = None if status == "running" else "Queued For Shared Desktop Window"
        self.worker_data.append(self._build_cluster_worker(worker_id=worker_id, status=status, task=task))
        self.update_cluster_ui(self.worker_data, connected=True)
        if status in {"running", "prewarming"}:
            self._start_cluster_worker_runtime(worker_id)
        self.log_cluster_event(f"Added {worker_id} to the cluster.")

    def scale_down(self):
        if not self.cluster_connected:
            self.log_cluster_event("Connect to the cluster before removing workers.")
            return
        if not self.worker_data:
            self.log_cluster_event("No workers to remove.")
            return
        current_row = self._selected_worker_row()
        remove_index = current_row if 0 <= current_row < len(self.worker_data) else len(self.worker_data) - 1
        worker = self.worker_data.pop(remove_index)
        self._stop_cluster_worker_runtime(worker["id"])
        self.close_worker_preview(worker["id"])
        self.close_worker_control(worker["id"])
        self.update_cluster_ui(self.worker_data, connected=True)
        if self._current_game_mode_label().lower() == "desktop" and self.worker_data and not self.cluster_worker_runtimes:
            queued_index, queued_worker = self._selected_or_first_worker(
                lambda item: str((item or {}).get("status", "")).strip().lower() == "queued"
            )
            if queued_worker is not None:
                queued_id = str(queued_worker["id"])
                self.worker_data[queued_index] = self._build_cluster_worker(
                    worker_id=queued_id,
                    status="running",
                    watch_reward_ads_enabled=queued_worker.get("watch_reward_ads_enabled"),
                )
                self.update_cluster_ui(self.worker_data, connected=True)
                self._start_cluster_worker_runtime(queued_id)
        self.log_cluster_event(f"Removed {worker['id']} from the cluster.")

    def refresh_plugins(self):
        if not hasattr(self, "plugin_list"):
            self._sync_plugin_ui_state()
            return
        self.plugin_list.clear()
        if self.plugin_manager is None:
            self.plugin_list.addItem("No plugin manager configured")
            self._sync_plugin_ui_state()
            return
        summaries = self.plugin_manager.get_plugin_summaries()
        if not summaries:
            self.plugin_list.addItem("No plugins loaded")
            self._sync_plugin_ui_state()
            return
        for plugin in summaries:
            item = QListWidgetItem(f"{plugin['name']} ({plugin['version']})")
            item.setData(Qt.UserRole, plugin)
            self.plugin_list.addItem(item)
        if self.plugin_list.count() > 0:
            self.plugin_list.setCurrentRow(0)
        self._sync_plugin_ui_state()

    def reload_plugins(self):
        if self.plugin_manager is None:
            self.set_status("No plugin manager configured")
            return
        self.plugin_manager.reload_all()
        self.refresh_plugins()
        self.set_status("Plugins reloaded")

    def show_about_dialog(self):
        QMessageBox.information(
            self,
            f"About {self.APP_NAME}",
            f"{self.APP_NAME} now uses a repaired main menu, a visible branded logo, and cleaner working page controls.\n\nBuilt by {self.AUTHOR_NAME}.",
        )

    def _show_legal_document(self, key: str):
        label = legal_doc_label(key)
        text = legal_doc_text(key, fallback=f"{label} is unavailable in this build.")
        path = legal_doc_path(key)
        version = legal_doc_version(key)

        dialog = QDialog(self)
        dialog.setModal(False)
        dialog.setWindowTitle(f"{self.APP_NAME} - {label}")
        if self.windowIcon() is not None and not self.windowIcon().isNull():
            dialog.setWindowIcon(self.windowIcon())
        dialog.resize(820, 680)

        layout = QVBoxLayout(dialog)
        summary = QLabel(
            f"{label} | Version: {version}"
            + (f"\nSource: {path}" if path is not None else "\nSource: bundled fallback")
        )
        summary.setWordWrap(True)
        summary.setObjectName("mutedLabel")
        layout.addWidget(summary)

        viewer = QTextEdit(dialog)
        viewer.setReadOnly(True)
        viewer.setMarkdown(text)
        layout.addWidget(viewer, 1)

        close_button = QPushButton("Close", dialog)
        close_button.clicked.connect(dialog.accept)
        layout.addWidget(close_button, alignment=Qt.AlignmentFlag.AlignRight)
        dialog.exec()

    def closeEvent(self, event):
        self.ai_running = False
        self.vision_preview_timer.stop()
        if hasattr(self, "_worker_preview_timer"):
            self._worker_preview_timer.stop()
        if hasattr(self, "_worker_control_timer"):
            self._worker_control_timer.stop()
        self._release_vision_media()
        self._close_all_worker_previews()
        self._close_all_worker_controls()
        self._stop_all_cluster_runtimes()
        if self._browser_prewarm_pool_instance is not None:
            try:
                self._browser_prewarm_pool_instance.disarm("Application closing.")
            except Exception:
                pass
        if self.debug_overlay is not None:
            self.debug_overlay.close()
        super().closeEvent(event)
