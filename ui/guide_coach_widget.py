from __future__ import annotations

import json
from pathlib import Path

import cv2
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QDoubleSpinBox,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from automation.click_diagnostics import ClickDiagnosticsEngine, FRAME_LABEL_TARGET_TYPES, calibration_storage_key
from automation.dom_analysis import DomAnalyzer, frame_hash
from automation.guide_coach import GuideCoachEngine
from automation.task_evidence_store import TaskEvidenceStore


class GuideClickFrameLabel(QLabel):
    def __init__(self, on_click=None, parent=None):
        super().__init__(parent)
        self.on_click = on_click
        self._frame_shape = None
        self._preview_scale = 1.0
        self.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def set_frame_shape(self, frame_shape, preview_scale: float = 1.0):
        self._frame_shape = tuple(frame_shape[:2]) if frame_shape else None
        self._preview_scale = max(0.25, float(preview_scale or 1.0))

    def mousePressEvent(self, event):  # pragma: no cover - UI behavior
        if not self._frame_shape or not callable(self.on_click):
            super().mousePressEvent(event)
            return
        frame_height, frame_width = self._frame_shape[:2]
        scale = max(0.25, float(self._preview_scale or 1.0))
        x = int(max(0, min(frame_width - 1, event.position().x() / scale)))
        y = int(max(0, min(frame_height - 1, event.position().y() / scale)))
        self.on_click(x, y)
        event.accept()


class GuideCoachWidget(QWidget):
    def __init__(
        self,
        project_root,
        latest_frame_provider=None,
        capture_frame_provider=None,
        current_media_path_provider=None,
        dom_snapshot_provider=None,
        manual_context_provider=None,
        status_callback=None,
        resource_reader=None,
        profile_key: str = "legends_of_mushroom",
        evidence_store=None,
        parent=None,
    ):
        super().__init__(parent)
        self.project_root = Path(project_root)
        self.latest_frame_provider = latest_frame_provider
        self.capture_frame_provider = capture_frame_provider
        self.current_media_path_provider = current_media_path_provider
        self.dom_snapshot_provider = dom_snapshot_provider
        self.manual_context_provider = manual_context_provider
        self.status_callback = status_callback
        self.engine = GuideCoachEngine(
            project_root=self.project_root,
            profile_key=profile_key,
            resource_reader=resource_reader,
        )
        self.diagnostics_engine = ClickDiagnosticsEngine(
            self.engine,
            browser_url="https://lom.joynetgame.com",
            mode="browser",
            runtime_profile="chromium",
        )
        self.profile_key = str(profile_key or "legends_of_mushroom")
        self.dom_analyzer = DomAnalyzer(self.project_root)
        self.evidence_store = evidence_store or TaskEvidenceStore(self.project_root)
        self.checklist_progress = self.engine.default_progress_state()
        self.last_analysis = {}
        self.last_review = {}
        self.last_frame = None
        self.last_diagnostics = {}
        self.last_dom_snapshot = {}
        self.last_screen_action_map = {}
        self.last_dom_source_label = ""
        self.current_preview_frame = None
        self.current_replay_preview_frame = None
        self.current_replay_source_frame = None
        self.current_replay_entry = {}
        self.calibration_profiles = {}
        self.active_calibration_profile_key = calibration_storage_key("lom.joynetgame.com", "browser", "chromium")
        self.calibration_click_point = None
        self.calibration_candidate = None
        self.calibration_source_frame = None
        self.calibration_source_diagnostics = None
        self.pending_replay_label_point = None
        self.pending_replay_label_candidate = None
        self.show_focus_masks = True
        self.last_label_target_type = "claim"
        self.last_label_outcome = "missed"
        self.replay_comparison_rows = []
        self.evidence_default_outcome = "advanced"
        self.evidence_export_include_dom = True
        self._populating_checklist = False
        self._build_ui()
        self._load_active_calibration_profile_to_controls()
        self._load_guide_overview()
        self._refresh_checklist()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        overview_row = QHBoxLayout()
        overview_row.setSpacing(12)

        state_box, state_layout = self._make_group("Detected Screen")
        self.screen_state_label = QLabel("State: Waiting for analysis")
        self.screen_confidence_label = QLabel("Confidence: 0.00")
        self.screen_source_label = QLabel("Source: none")
        self.screen_signals_label = QLabel("Signals: none")
        for label in [
            self.screen_state_label,
            self.screen_confidence_label,
            self.screen_source_label,
            self.screen_signals_label,
        ]:
            label.setWordWrap(True)
            state_layout.addWidget(label)
        overview_row.addWidget(state_box, 1)

        priority_box, priority_layout = self._make_group("Recommended Priorities")
        self.recommendation_list = QListWidget()
        self.recommendation_list.setMinimumHeight(140)
        priority_layout.addWidget(self.recommendation_list)
        self.tip_label = QLabel("Guide notes will appear here after analysis.")
        self.tip_label.setWordWrap(True)
        self.tip_label.setObjectName("mutedLabel")
        priority_layout.addWidget(self.tip_label)
        overview_row.addWidget(priority_box, 2)

        guide_box, guide_layout = self._make_group("Guide Context")
        self.guide_summary_label = QLabel("No guide loaded.")
        self.guide_summary_label.setWordWrap(True)
        self.guide_summary_label.setObjectName("mutedLabel")
        self.guide_sources_label = QLabel("")
        self.guide_sources_label.setWordWrap(True)
        self.guide_sources_label.setObjectName("mutedLabel")
        guide_layout.addWidget(self.guide_summary_label)
        guide_layout.addWidget(self.guide_sources_label)
        overview_row.addWidget(guide_box, 2)

        root.addLayout(overview_row)

        center_row = QHBoxLayout()
        center_row.setSpacing(12)

        preview_box, preview_layout = self._make_group("Current Screen Review")
        self.preview_label = QLabel("Analyze the latest frame or current capture to review the screen.")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumHeight(320)
        self.preview_label.setObjectName("previewSurface")
        self.preview_label.setWordWrap(True)
        preview_layout.addWidget(self.preview_label)
        preview_actions = QGridLayout()
        preview_actions.setHorizontalSpacing(10)
        preview_actions.setVerticalSpacing(10)
        analyze_latest_button = QPushButton("Analyze Latest Vision Frame")
        analyze_latest_button.clicked.connect(self.analyze_latest_frame)
        analyze_capture_button = QPushButton("Capture Current Region")
        analyze_capture_button.clicked.connect(self.analyze_current_capture)
        review_media_button = QPushButton("Review Vision Media")
        review_media_button.clicked.connect(self.review_current_media)
        preview_actions.addWidget(analyze_latest_button, 0, 0)
        preview_actions.addWidget(analyze_capture_button, 0, 1)
        preview_actions.addWidget(review_media_button, 1, 0, 1, 2)
        preview_layout.addLayout(preview_actions)
        self.analysis_excerpt_label = QLabel("No OCR excerpt yet.")
        self.analysis_excerpt_label.setWordWrap(True)
        self.analysis_excerpt_label.setObjectName("mutedLabel")
        preview_layout.addWidget(self.analysis_excerpt_label)
        self.current_target_label = QLabel("Top target: waiting")
        self.current_target_label.setWordWrap(True)
        self.current_target_label.setObjectName("mutedLabel")
        preview_layout.addWidget(self.current_target_label)
        self.current_loop_label = QLabel("Loop risk: none")
        self.current_loop_label.setWordWrap(True)
        self.current_loop_label.setObjectName("mutedLabel")
        preview_layout.addWidget(self.current_loop_label)
        center_row.addWidget(preview_box, 3)

        checklist_box, checklist_layout = self._make_group("Progression Checklist")
        self.checklist_summary_label = QLabel("Completed: 0 / 0")
        self.checklist_summary_label.setObjectName("mutedLabel")
        checklist_layout.addWidget(self.checklist_summary_label)
        self.checklist_table = QTableWidget(0, 5)
        self.checklist_table.setHorizontalHeaderLabels(["Done", "Priority", "F2P", "Checklist Item", "Status"])
        self.checklist_table.verticalHeader().setVisible(False)
        self.checklist_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.checklist_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.checklist_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.checklist_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.checklist_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.checklist_table.itemChanged.connect(self._on_checklist_item_changed)
        checklist_layout.addWidget(self.checklist_table)
        checklist_buttons = QHBoxLayout()
        reset_checklist_button = QPushButton("Reset Checklist")
        reset_checklist_button.clicked.connect(self.reset_checklist_progress)
        checklist_buttons.addWidget(reset_checklist_button)
        checklist_buttons.addStretch()
        checklist_layout.addLayout(checklist_buttons)
        center_row.addWidget(checklist_box, 4)

        root.addLayout(center_row)

        replay_box, replay_layout = self._make_group("Replay Diagnostics")
        path_row = QHBoxLayout()
        self.replay_path_input = QLineEdit()
        self.replay_path_input.setPlaceholderText("Select an image or video replay to review")
        browse_button = QPushButton("Browse")
        browse_button.clicked.connect(self.browse_replay_file)
        analyze_button = QPushButton("Analyze Replay")
        analyze_button.clicked.connect(self.review_selected_media)
        export_button = QPushButton("Export Review")
        export_button.clicked.connect(self.export_replay_review)
        import_button = QPushButton("Import Review")
        import_button.clicked.connect(self.import_replay_review)
        path_row.addWidget(self.replay_path_input, 1)
        path_row.addWidget(browse_button)
        path_row.addWidget(analyze_button)
        path_row.addWidget(export_button)
        path_row.addWidget(import_button)
        replay_layout.addLayout(path_row)

        settings_row = QHBoxLayout()
        settings_row.addWidget(QLabel("Sample Interval (seconds)"))
        self.replay_sample_spin = QDoubleSpinBox()
        self.replay_sample_spin.setRange(0.25, 10.0)
        self.replay_sample_spin.setDecimals(2)
        self.replay_sample_spin.setSingleStep(0.25)
        self.replay_sample_spin.setValue(1.50)
        settings_row.addWidget(self.replay_sample_spin)
        self.show_focus_masks_checkbox = QCheckBox("Show Focus Masks")
        self.show_focus_masks_checkbox.setChecked(True)
        self.show_focus_masks_checkbox.toggled.connect(self._on_focus_masks_toggled)
        settings_row.addWidget(self.show_focus_masks_checkbox)
        settings_row.addStretch()
        replay_layout.addLayout(settings_row)

        replay_split = QHBoxLayout()
        replay_split.setSpacing(12)
        replay_left = QVBoxLayout()
        replay_left.setSpacing(8)
        self.replay_preview_label = GuideClickFrameLabel(on_click=self._on_replay_preview_clicked)
        self.replay_preview_label.setText("Run a replay review to inspect selected frames with overlays.")
        self.replay_preview_label.setAlignment(Qt.AlignCenter)
        self.replay_preview_label.setMinimumHeight(260)
        self.replay_preview_label.setObjectName("previewSurface")
        self.replay_preview_label.setWordWrap(True)
        replay_left.addWidget(self.replay_preview_label)
        self.replay_frame_summary_label = QLabel("No replay frame selected.")
        self.replay_frame_summary_label.setWordWrap(True)
        self.replay_frame_summary_label.setObjectName("mutedLabel")
        replay_left.addWidget(self.replay_frame_summary_label)
        self.replay_candidate_table = QTableWidget(0, 5)
        self.replay_candidate_table.setHorizontalHeaderLabels(["#", "Target", "Kind", "Score", "Browser Point"])
        self.replay_candidate_table.verticalHeader().setVisible(False)
        self.replay_candidate_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.replay_candidate_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.replay_candidate_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.replay_candidate_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.replay_candidate_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        replay_left.addWidget(self.replay_candidate_table)
        self.replay_miss_text = QTextEdit()
        self.replay_miss_text.setReadOnly(True)
        self.replay_miss_text.setMinimumHeight(120)
        self.replay_miss_text.setPlainText("Miss diagnostics and suggested fixes will appear here.")
        replay_left.addWidget(self.replay_miss_text)
        label_box, label_layout = self._make_group("Label Intended Target")
        label_controls = QGridLayout()
        label_controls.setHorizontalSpacing(10)
        label_controls.setVerticalSpacing(8)
        label_controls.addWidget(QLabel("Target Type"), 0, 0)
        self.label_target_type_combo = QComboBox()
        self.label_target_type_combo.addItems([value.replace("_", " ").title() for value in FRAME_LABEL_TARGET_TYPES])
        self.label_target_type_combo.setCurrentText("Claim")
        self.label_target_type_combo.currentTextChanged.connect(self._on_label_controls_changed)
        label_controls.addWidget(self.label_target_type_combo, 0, 1)
        label_controls.addWidget(QLabel("Outcome"), 0, 2)
        self.label_outcome_combo = QComboBox()
        self.label_outcome_combo.addItems(["Advanced", "Neutral", "Missed"])
        self.label_outcome_combo.setCurrentText("Missed")
        self.label_outcome_combo.currentTextChanged.connect(self._on_label_controls_changed)
        label_controls.addWidget(self.label_outcome_combo, 0, 3)
        label_controls.addWidget(QLabel("Note"), 1, 0)
        self.label_note_input = QLineEdit()
        self.label_note_input.setPlaceholderText("Optional note about why this was the intended target")
        self.label_note_input.textChanged.connect(self._on_label_controls_changed)
        label_controls.addWidget(self.label_note_input, 1, 1, 1, 3)
        label_layout.addLayout(label_controls)
        label_buttons = QHBoxLayout()
        use_top_candidate_button = QPushButton("Use Top Candidate")
        use_top_candidate_button.clicked.connect(self._use_top_candidate_for_label)
        save_label_button = QPushButton("Save Label")
        save_label_button.clicked.connect(self._save_current_replay_label)
        clear_label_button = QPushButton("Clear Label")
        clear_label_button.clicked.connect(self._clear_current_replay_label)
        label_buttons.addWidget(use_top_candidate_button)
        label_buttons.addWidget(save_label_button)
        label_buttons.addWidget(clear_label_button)
        label_buttons.addStretch()
        label_layout.addLayout(label_buttons)
        self.label_summary_label = QLabel("Click the selected replay frame to mark the intended target.")
        self.label_summary_label.setWordWrap(True)
        self.label_summary_label.setObjectName("mutedLabel")
        label_layout.addWidget(self.label_summary_label)
        replay_left.addWidget(label_box)
        replay_split.addLayout(replay_left, 3)

        replay_right = QVBoxLayout()
        replay_right.setSpacing(8)
        self.replay_timeline_table = QTableWidget(0, 6)
        self.replay_timeline_table.setHorizontalHeaderLabels(["Time", "State", "Advanced", "Score", "Chosen", "Guide"])
        self.replay_timeline_table.verticalHeader().setVisible(False)
        self.replay_timeline_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.replay_timeline_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.replay_timeline_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.replay_timeline_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.replay_timeline_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.replay_timeline_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.replay_timeline_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.replay_timeline_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self.replay_timeline_table.itemSelectionChanged.connect(self._on_replay_selection_changed)
        replay_right.addWidget(self.replay_timeline_table)
        self.replay_report_text = QTextEdit()
        self.replay_report_text.setReadOnly(True)
        self.replay_report_text.setMinimumHeight(220)
        self.replay_report_text.setPlainText("Replay review results will appear here.")
        replay_right.addWidget(self.replay_report_text)
        replay_split.addLayout(replay_right, 3)
        replay_layout.addLayout(replay_split)
        comparison_box, comparison_layout = self._make_group("Replay Comparison Report")
        self.replay_comparison_summary = QTextEdit()
        self.replay_comparison_summary.setReadOnly(True)
        self.replay_comparison_summary.setMinimumHeight(110)
        self.replay_comparison_summary.setPlainText("Comparison insights will appear here after replay analysis.")
        comparison_layout.addWidget(self.replay_comparison_summary)
        self.replay_comparison_table = QTableWidget(0, 5)
        self.replay_comparison_table.setHorizontalHeaderLabels(["Issue", "Time", "Screen", "Chosen", "Alternative"])
        self.replay_comparison_table.verticalHeader().setVisible(False)
        self.replay_comparison_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.replay_comparison_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.replay_comparison_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.replay_comparison_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.replay_comparison_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.replay_comparison_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.replay_comparison_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.replay_comparison_table.itemSelectionChanged.connect(self._on_comparison_selection_changed)
        comparison_layout.addWidget(self.replay_comparison_table)
        replay_layout.addWidget(comparison_box)

        root.addWidget(replay_box)

        dom_box, dom_layout = self._make_group("DOM Snapshot + Evidence")
        dom_button_row = QHBoxLayout()
        capture_dom_button = QPushButton("Capture DOM Snapshot")
        capture_dom_button.clicked.connect(self.capture_dom_snapshot)
        analyze_dom_button = QPushButton("Analyze DOM + OCR")
        analyze_dom_button.clicked.connect(self.analyze_dom_and_ocr)
        save_advanced_button = QPushButton("Save Advanced Evidence")
        save_advanced_button.clicked.connect(lambda: self.save_current_evidence("advanced"))
        save_neutral_button = QPushButton("Save Neutral Evidence")
        save_neutral_button.clicked.connect(lambda: self.save_current_evidence("neutral"))
        save_wrong_button = QPushButton("Save Wrong Target Evidence")
        save_wrong_button.clicked.connect(lambda: self.save_current_evidence("wrong_target"))
        for widget in [
            capture_dom_button,
            analyze_dom_button,
            save_advanced_button,
            save_neutral_button,
            save_wrong_button,
        ]:
            dom_button_row.addWidget(widget)
        dom_button_row.addStretch()
        dom_layout.addLayout(dom_button_row)

        dom_pref_row = QHBoxLayout()
        dom_pref_row.addWidget(QLabel("Default Confirmation"))
        self.evidence_default_outcome_combo = QComboBox()
        self.evidence_default_outcome_combo.addItem("Advanced", "advanced")
        self.evidence_default_outcome_combo.addItem("Neutral", "neutral")
        self.evidence_default_outcome_combo.addItem("Wrong Target", "wrong_target")
        self.evidence_default_outcome_combo.currentIndexChanged.connect(self._on_evidence_preferences_changed)
        dom_pref_row.addWidget(self.evidence_default_outcome_combo)
        self.evidence_export_include_dom_checkbox = QCheckBox("Include DOM Summary In Review Exports")
        self.evidence_export_include_dom_checkbox.setChecked(True)
        self.evidence_export_include_dom_checkbox.toggled.connect(self._on_evidence_preferences_changed)
        dom_pref_row.addWidget(self.evidence_export_include_dom_checkbox)
        dom_pref_row.addStretch()
        dom_layout.addLayout(dom_pref_row)

        self.dom_snapshot_summary_label = QLabel("No DOM snapshot captured yet.")
        self.dom_snapshot_summary_label.setWordWrap(True)
        self.dom_snapshot_summary_label.setObjectName("mutedLabel")
        dom_layout.addWidget(self.dom_snapshot_summary_label)

        dom_split = QHBoxLayout()
        dom_split.setSpacing(12)
        self.dom_action_table = QTableWidget(0, 5)
        self.dom_action_table.setHorizontalHeaderLabels(["Source", "Label", "Score", "Kind", "Selector"])
        self.dom_action_table.verticalHeader().setVisible(False)
        self.dom_action_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.dom_action_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.dom_action_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.dom_action_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.dom_action_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.dom_action_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        dom_split.addWidget(self.dom_action_table, 3)

        dom_right = QVBoxLayout()
        dom_right.setSpacing(8)
        self.dom_snapshot_text = QTextEdit()
        self.dom_snapshot_text.setReadOnly(True)
        self.dom_snapshot_text.setMinimumHeight(120)
        self.dom_snapshot_text.setPlainText("DOM snapshot details will appear here.")
        dom_right.addWidget(self.dom_snapshot_text)
        self.evidence_summary_text = QTextEdit()
        self.evidence_summary_text.setReadOnly(True)
        self.evidence_summary_text.setMinimumHeight(120)
        self.evidence_summary_text.setPlainText("Saved evidence summaries and hints will appear here.")
        dom_right.addWidget(self.evidence_summary_text)
        dom_split.addLayout(dom_right, 2)
        dom_layout.addLayout(dom_split)
        root.addWidget(dom_box)

        calibration_box, calibration_layout = self._make_group("Click Calibration")
        calibration_header = QGridLayout()
        calibration_header.setHorizontalSpacing(10)
        calibration_header.setVerticalSpacing(8)
        calibration_header.addWidget(QLabel("Game Host"), 0, 0)
        self.calibration_host_input = QLineEdit("lom.joynetgame.com")
        calibration_header.addWidget(self.calibration_host_input, 0, 1)
        calibration_header.addWidget(QLabel("Runtime"), 0, 2)
        self.calibration_runtime_input = QLineEdit("chromium")
        calibration_header.addWidget(self.calibration_runtime_input, 0, 3)
        use_current_button = QPushButton("Use Current Analysis")
        use_current_button.clicked.connect(self.use_current_analysis_for_calibration)
        use_replay_button = QPushButton("Use Replay Selection")
        use_replay_button.clicked.connect(self.use_replay_selection_for_calibration)
        calibration_header.addWidget(use_current_button, 1, 0, 1, 2)
        calibration_header.addWidget(use_replay_button, 1, 2, 1, 2)
        calibration_layout.addLayout(calibration_header)

        calibration_split = QHBoxLayout()
        calibration_split.setSpacing(12)
        preview_column = QVBoxLayout()
        preview_column.setSpacing(8)
        self.calibration_scroll = QScrollArea()
        self.calibration_scroll.setWidgetResizable(True)
        self.calibration_preview_label = GuideClickFrameLabel(on_click=self._on_calibration_preview_clicked)
        self.calibration_preview_label.setText("Choose a current frame or replay frame, then click the intended target.")
        self.calibration_preview_label.setMinimumSize(320, 200)
        self.calibration_preview_label.setObjectName("previewSurface")
        self.calibration_scroll.setWidget(self.calibration_preview_label)
        preview_column.addWidget(self.calibration_scroll, 1)
        self.calibration_summary_label = QLabel("No calibration source selected.")
        self.calibration_summary_label.setWordWrap(True)
        self.calibration_summary_label.setObjectName("mutedLabel")
        preview_column.addWidget(self.calibration_summary_label)
        calibration_split.addLayout(preview_column, 3)

        controls_column = QVBoxLayout()
        controls_column.setSpacing(8)
        calibration_grid = QGridLayout()
        calibration_grid.setHorizontalSpacing(10)
        calibration_grid.setVerticalSpacing(8)
        calibration_grid.addWidget(QLabel("Capture Scale X"), 0, 0)
        self.capture_scale_x_spin = QDoubleSpinBox()
        self.capture_scale_x_spin.setRange(0.25, 4.0)
        self.capture_scale_x_spin.setDecimals(3)
        self.capture_scale_x_spin.setSingleStep(0.05)
        calibration_grid.addWidget(self.capture_scale_x_spin, 0, 1)
        calibration_grid.addWidget(QLabel("Capture Scale Y"), 0, 2)
        self.capture_scale_y_spin = QDoubleSpinBox()
        self.capture_scale_y_spin.setRange(0.25, 4.0)
        self.capture_scale_y_spin.setDecimals(3)
        self.capture_scale_y_spin.setSingleStep(0.05)
        calibration_grid.addWidget(self.capture_scale_y_spin, 0, 3)
        calibration_grid.addWidget(QLabel("Offset X"), 1, 0)
        self.offset_x_spin = QDoubleSpinBox()
        self.offset_x_spin.setRange(-5000.0, 5000.0)
        self.offset_x_spin.setDecimals(2)
        calibration_grid.addWidget(self.offset_x_spin, 1, 1)
        calibration_grid.addWidget(QLabel("Offset Y"), 1, 2)
        self.offset_y_spin = QDoubleSpinBox()
        self.offset_y_spin.setRange(-5000.0, 5000.0)
        self.offset_y_spin.setDecimals(2)
        calibration_grid.addWidget(self.offset_y_spin, 1, 3)
        calibration_grid.addWidget(QLabel("Preview Scale"), 2, 0)
        self.preview_scale_spin = QDoubleSpinBox()
        self.preview_scale_spin.setRange(0.25, 4.0)
        self.preview_scale_spin.setDecimals(2)
        self.preview_scale_spin.setSingleStep(0.10)
        calibration_grid.addWidget(self.preview_scale_spin, 2, 1)
        calibration_grid.addWidget(QLabel("Click Radius"), 2, 2)
        self.click_radius_spin = QSpinBox()
        self.click_radius_spin.setRange(2, 64)
        calibration_grid.addWidget(self.click_radius_spin, 2, 3)
        calibration_grid.addWidget(QLabel("Max Panel Ratio"), 3, 0)
        self.max_panel_ratio_spin = QDoubleSpinBox()
        self.max_panel_ratio_spin.setRange(0.04, 0.90)
        self.max_panel_ratio_spin.setDecimals(3)
        self.max_panel_ratio_spin.setSingleStep(0.01)
        calibration_grid.addWidget(self.max_panel_ratio_spin, 3, 1)
        controls_column.addLayout(calibration_grid)
        calibration_buttons = QHBoxLayout()
        apply_click_button = QPushButton("Apply From Last Click")
        apply_click_button.clicked.connect(self.apply_last_calibration_click)
        reset_profile_button = QPushButton("Reset Active Profile")
        reset_profile_button.clicked.connect(self.reset_active_calibration_profile)
        calibration_buttons.addWidget(apply_click_button)
        calibration_buttons.addWidget(reset_profile_button)
        calibration_buttons.addStretch()
        controls_column.addLayout(calibration_buttons)
        self.calibration_details_text = QTextEdit()
        self.calibration_details_text.setReadOnly(True)
        self.calibration_details_text.setMinimumHeight(180)
        self.calibration_details_text.setPlainText("Calibration details and suggested corrections will appear here.")
        controls_column.addWidget(self.calibration_details_text)
        calibration_split.addLayout(controls_column, 2)
        calibration_layout.addLayout(calibration_split)

        for widget in [
            self.capture_scale_x_spin,
            self.capture_scale_y_spin,
            self.offset_x_spin,
            self.offset_y_spin,
            self.preview_scale_spin,
            self.click_radius_spin,
            self.max_panel_ratio_spin,
            self.calibration_host_input,
            self.calibration_runtime_input,
        ]:
            if hasattr(widget, "valueChanged"):
                widget.valueChanged.connect(self._on_calibration_controls_changed)
            elif hasattr(widget, "textChanged"):
                widget.textChanged.connect(self._on_calibration_identity_changed)

        root.addWidget(calibration_box)

    def _make_group(self, title: str):
        box = QGroupBox(title)
        layout = QVBoxLayout(box)
        layout.setContentsMargins(12, 16, 12, 12)
        layout.setSpacing(8)
        return box, layout

    def _load_guide_overview(self):
        guide = self.engine.guide or {}
        self.guide_summary_label.setText(str(guide.get("summary", "No guide summary available.")))
        source_lines = []
        for source in guide.get("sources", []):
            title = str(source.get("title", "Guide source")).strip()
            role = str(source.get("role", "")).strip()
            uploader = str(source.get("uploader", "")).strip()
            source_lines.append(f"- {title} | {role or 'reference'} | {uploader or 'unknown'}")
        self.guide_sources_label.setText("\n".join(source_lines) if source_lines else "No linked guide sources yet.")

    def set_saved_state(self, payload: dict | None):
        payload = payload if isinstance(payload, dict) else {}
        progress = payload.get("checklist_progress", {})
        if isinstance(progress, dict):
            self.checklist_progress = {
                **self.engine.default_progress_state(),
                **{str(key): bool(value) for key, value in progress.items()},
            }
        if hasattr(self, "replay_sample_spin"):
            self.replay_sample_spin.setValue(max(0.25, float(payload.get("sample_interval_seconds", 1.5))))
        if hasattr(self, "replay_path_input"):
            self.replay_path_input.setText(str(payload.get("last_replay_path", "")).strip())
        self.calibration_profiles = dict(payload.get("calibration_profiles", {})) if isinstance(payload.get("calibration_profiles", {}), dict) else {}
        self.show_focus_masks = bool(payload.get("show_focus_masks", True))
        self.last_label_target_type = str(payload.get("last_label_target_type", "claim") or "claim").strip().lower() or "claim"
        self.last_label_outcome = str(payload.get("last_label_outcome", "missed") or "missed").strip().lower() or "missed"
        host = str(payload.get("calibration_host", "lom.joynetgame.com")).strip() or "lom.joynetgame.com"
        runtime = str(payload.get("calibration_runtime", "chromium")).strip() or "chromium"
        self.active_calibration_profile_key = str(
            payload.get("active_calibration_profile_key", calibration_storage_key(host, "browser", runtime))
        ).strip() or calibration_storage_key(host, "browser", runtime)
        if hasattr(self, "calibration_host_input"):
            self.calibration_host_input.setText(host)
        if hasattr(self, "calibration_runtime_input"):
            self.calibration_runtime_input.setText(runtime)
        if hasattr(self, "show_focus_masks_checkbox"):
            self.show_focus_masks_checkbox.setChecked(self.show_focus_masks)
        if hasattr(self, "label_target_type_combo"):
            self.label_target_type_combo.setCurrentText(self.last_label_target_type.replace("_", " ").title())
        if hasattr(self, "label_outcome_combo"):
            self.label_outcome_combo.setCurrentText(self.last_label_outcome.title())
        if hasattr(self, "evidence_default_outcome_combo"):
            index = self.evidence_default_outcome_combo.findData(str(payload.get("evidence_default_outcome", "advanced") or "advanced"))
            self.evidence_default_outcome_combo.setCurrentIndex(max(0, index))
        if hasattr(self, "evidence_export_include_dom_checkbox"):
            self.evidence_export_include_dom_checkbox.setChecked(bool(payload.get("evidence_export_include_dom", True)))
        self._load_active_calibration_profile_to_controls()
        self._refresh_checklist(self.last_analysis or None)
        self._refresh_evidence_summary()

    def collect_state(self) -> dict:
        return {
            "sample_interval_seconds": self.replay_sample_spin.value() if hasattr(self, "replay_sample_spin") else 1.5,
            "last_replay_path": self.replay_path_input.text().strip() if hasattr(self, "replay_path_input") else "",
            "checklist_progress": dict(self.checklist_progress),
            "calibration_host": self.calibration_host_input.text().strip() if hasattr(self, "calibration_host_input") else "lom.joynetgame.com",
            "calibration_runtime": self.calibration_runtime_input.text().strip() if hasattr(self, "calibration_runtime_input") else "chromium",
            "active_calibration_profile_key": self.active_calibration_profile_key,
            "calibration_profiles": dict(self.calibration_profiles),
            "show_focus_masks": self.show_focus_masks_checkbox.isChecked() if hasattr(self, "show_focus_masks_checkbox") else True,
            "last_label_target_type": self._label_target_type_value(),
            "last_label_outcome": self._label_outcome_value(),
            "evidence_default_outcome": self.evidence_default_outcome_combo.currentData() if hasattr(self, "evidence_default_outcome_combo") else "advanced",
            "evidence_export_include_dom": self.evidence_export_include_dom_checkbox.isChecked() if hasattr(self, "evidence_export_include_dom_checkbox") else True,
        }

    def set_action_evidence_state(self, payload: dict | None):
        payload = dict(payload or {})
        if hasattr(self, "evidence_default_outcome_combo"):
            index = self.evidence_default_outcome_combo.findData(str(payload.get("default_confirmation", "advanced") or "advanced"))
            self.evidence_default_outcome_combo.setCurrentIndex(max(0, index))
        if hasattr(self, "evidence_export_include_dom_checkbox"):
            self.evidence_export_include_dom_checkbox.setChecked(bool(payload.get("export_include_dom", True)))
        self._refresh_evidence_summary(screen_state=(self.last_analysis or {}).get("screen_state", "unknown"))

    def collect_action_evidence_state(self) -> dict:
        return {
            "default_confirmation": self.evidence_default_outcome_combo.currentData() if hasattr(self, "evidence_default_outcome_combo") else "advanced",
            "export_include_dom": self.evidence_export_include_dom_checkbox.isChecked() if hasattr(self, "evidence_export_include_dom_checkbox") else True,
        }

    def reset_checklist_progress(self):
        self.checklist_progress = self.engine.default_progress_state()
        self._refresh_checklist(self.last_analysis or None)
        self._set_status("Guide Coach checklist reset")

    def analyze_latest_frame(self):
        frame = self._resolve_frame(self.latest_frame_provider)
        if frame is None:
            QMessageBox.information(self, "Guide Coach", "No live or Vision Lab frame is available yet.")
            return
        self._analyze_frame(frame, "Latest Vision Frame")

    def analyze_current_capture(self):
        frame = self._resolve_frame(self.capture_frame_provider)
        if frame is None:
            QMessageBox.information(self, "Guide Coach", "Unable to capture the current region right now.")
            return
        self._analyze_frame(frame, "Current Capture Region")

    def analyze_frame_silently(self, frame, source_label: str = "Current Frame"):
        if frame is None:
            return
        self._analyze_frame(frame, source_label, update_status=False)

    def review_current_media(self):
        media_path = ""
        if callable(self.current_media_path_provider):
            try:
                media_path = str(self.current_media_path_provider() or "").strip()
            except Exception:
                media_path = ""
        if not media_path:
            QMessageBox.information(self, "Guide Coach", "No Vision Lab media file is loaded right now.")
            return
        self.replay_path_input.setText(media_path)
        self.review_selected_media()

    def browse_replay_file(self):
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Open Replay Or Screenshot",
            self.replay_path_input.text().strip(),
            "Media Files (*.png *.jpg *.jpeg *.bmp *.mp4 *.avi *.mov *.mkv);;Images (*.png *.jpg *.jpeg *.bmp);;Videos (*.mp4 *.avi *.mov *.mkv)",
        )
        if filename:
            self.replay_path_input.setText(filename)

    def review_selected_media(self):
        filename = self.replay_path_input.text().strip()
        if not filename:
            QMessageBox.information(self, "Guide Coach", "Choose a replay or screenshot first.")
            return
        try:
            review = self.diagnostics_engine.review_media(
                filename,
                checklist_progress=self.checklist_progress,
                sample_interval_seconds=self.replay_sample_spin.value(),
                calibration_profile=self._active_calibration_profile(),
            )
        except Exception as exc:
            QMessageBox.warning(self, "Guide Coach", f"Replay review failed: {exc}")
            return
        self.last_review = review
        preview_frame = self.diagnostics_engine.load_frame_from_media(filename)
        if review.get("kind") == "image" and review.get("analysis"):
            diagnostics = ((review.get("frame_reviews") or [{}])[0] or {}).get("diagnostics", {})
            self._apply_analysis(review["analysis"], preview_frame, diagnostics=diagnostics)
        elif preview_frame is not None:
            self.last_frame = preview_frame.copy() if hasattr(preview_frame, "copy") else preview_frame
        self._update_replay_review_ui(review)
        self._set_status(f"Guide Coach replay review complete: {Path(filename).name}")

    def export_replay_review(self):
        if not self.last_review:
            QMessageBox.information(self, "Guide Coach", "Run a replay review before exporting a report.")
            return
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Export Guide Coach Review",
            "guide_coach_review.json",
            "JSON Files (*.json)",
        )
        if not filename:
            return
        export_payload = dict(self.last_review)
        if hasattr(self, "evidence_export_include_dom_checkbox") and self.evidence_export_include_dom_checkbox.isChecked():
            export_payload["last_dom_snapshot"] = self._dom_snapshot_summary(self.last_dom_snapshot)
            export_payload["last_screen_action_map"] = dict(self.last_screen_action_map or {})
        review_dir = Path(filename).with_suffix("")
        review_dir.mkdir(parents=True, exist_ok=True)
        frame_reviews = []
        for entry in list(self.last_review.get("frame_reviews", [])):
            exported_entry = dict(entry)
            frame = self.diagnostics_engine.load_frame_from_media(
                self.last_review.get("media_path", ""),
                int(entry.get("frame_index", 0) or 0),
            )
            annotated_path = ""
            if frame is not None:
                label_payload = self.diagnostics_engine.normalize_frame_label(entry.get("label"), calibration_profile=self._active_calibration_profile())
                intended_point = tuple(label_payload["point"]) if label_payload.get("point") is not None else None
                annotated = self.diagnostics_engine.render_overlay(
                    frame,
                    entry.get("diagnostics", {}),
                    calibration_profile=self._active_calibration_profile(),
                    intended_point=intended_point,
                    selected_token=label_payload.get("matched_candidate_token", ""),
                    show_focus_masks=self.show_focus_masks_checkbox.isChecked() if hasattr(self, "show_focus_masks_checkbox") else True,
                )
                annotated_path = str(review_dir / f"frame_{int(entry.get('frame_index', 0) or 0):05d}.png")
                cv2.imwrite(annotated_path, annotated)
            exported_entry["annotated_image"] = annotated_path
            frame_reviews.append(exported_entry)
        export_payload["frame_reviews"] = frame_reviews
        export_payload["timeline"] = list(export_payload.get("timeline", []))
        with open(filename, "w", encoding="utf-8") as handle:
            json.dump(export_payload, handle, indent=2)
        self._set_status(f"Guide Coach review exported: {Path(filename).name}")

    def import_replay_review(self):
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Import Guide Coach Review",
            self.replay_path_input.text().strip(),
            "JSON Files (*.json)",
        )
        if not filename:
            return
        try:
            with open(filename, "r", encoding="utf-8") as handle:
                review = json.load(handle)
        except Exception as exc:
            QMessageBox.warning(self, "Guide Coach", f"Unable to import review: {exc}")
            return
        if not isinstance(review, dict):
            QMessageBox.warning(self, "Guide Coach", "Imported review is not a valid diagnostics payload.")
            return
        self.last_review = self.diagnostics_engine.normalize_review(review, calibration_profile=self._active_calibration_profile())
        self.last_dom_snapshot = dict(review.get("last_dom_snapshot") or {})
        self.last_screen_action_map = dict(review.get("last_screen_action_map") or {})
        self.replay_path_input.setText(str(review.get("media_path", self.replay_path_input.text().strip())))
        self._update_replay_review_ui(self.last_review)
        if self.last_dom_snapshot:
            self._update_dom_snapshot_ui(self.last_dom_snapshot, self.last_screen_action_map, source_label="Imported Review DOM")
        self._set_status(f"Guide Coach review imported: {Path(filename).name}")

    def capture_dom_snapshot(self):
        if not callable(self.dom_snapshot_provider):
            QMessageBox.information(self, "Guide Coach", "A live browser DOM snapshot provider is not connected right now.")
            return
        try:
            snapshot = dict(self.dom_snapshot_provider() or {})
        except Exception as exc:
            QMessageBox.warning(self, "Guide Coach", f"DOM snapshot capture failed: {exc}")
            return
        if not snapshot:
            QMessageBox.information(self, "Guide Coach", "No DOM snapshot is available right now.")
            return
        frame = self.last_frame if self.last_frame is not None else self._resolve_frame(self.latest_frame_provider)
        self.ingest_dom_snapshot(snapshot, source_label="Live Browser Session", frame=frame)
        self._set_status("Guide Coach captured a live DOM snapshot")

    def analyze_dom_and_ocr(self):
        frame = self.last_frame if self.last_frame is not None else self._resolve_frame(self.capture_frame_provider)
        if frame is None:
            QMessageBox.information(self, "Guide Coach", "Analyze a frame or capture the current region first.")
            return
        if not self.last_analysis:
            self._analyze_frame(frame, "DOM + OCR Capture", update_status=False)
        snapshot = dict(self.last_dom_snapshot or {})
        if not snapshot and callable(self.dom_snapshot_provider):
            try:
                snapshot = dict(self.dom_snapshot_provider() or {})
            except Exception:
                snapshot = {}
        if not snapshot:
            QMessageBox.information(self, "Guide Coach", "Capture a DOM snapshot first or open a live browser worker.")
            return
        action_map = self._build_dom_action_map(snapshot, self.last_analysis or {}, frame)
        self.last_dom_snapshot = snapshot
        self.last_screen_action_map = action_map
        self._update_dom_snapshot_ui(snapshot, action_map, source_label=self.last_dom_source_label or "DOM + OCR")
        self._set_status("Guide Coach merged DOM and OCR action evidence")

    def ingest_dom_snapshot(self, snapshot: dict | None, source_label: str = "", frame=None):
        self.last_dom_snapshot = dict(snapshot or {})
        self.last_dom_source_label = str(source_label or self.last_dom_snapshot.get("url") or "DOM Snapshot").strip()
        if frame is None:
            frame = self.last_frame if self.last_frame is not None else None
        action_map = self._build_dom_action_map(self.last_dom_snapshot, self.last_analysis or {}, frame)
        self.last_screen_action_map = action_map
        self._update_dom_snapshot_ui(self.last_dom_snapshot, action_map, source_label=self.last_dom_source_label)
        self._refresh_evidence_summary(screen_state=(self.last_analysis or {}).get("screen_state", "unknown"))

    def save_current_evidence(self, outcome: str | None = None):
        outcome_value = str(outcome or self.evidence_default_outcome_combo.currentData() or "advanced").strip().lower() or "advanced"
        if outcome_value not in {"advanced", "neutral", "wrong_target"}:
            outcome_value = "neutral"
        context = self._manual_context()
        screen_state = ""
        source = "guide_coach"
        chosen_candidate = {}
        intended_action = {}
        ocr_excerpt = ""
        note = ""
        if self.current_replay_entry:
            source = "replay"
            screen_state = str(self.current_replay_entry.get("screen_state") or "unknown").strip().lower()
            diagnostics = dict(self.current_replay_entry.get("diagnostics") or {})
            chosen_candidate = dict(diagnostics.get("chosen_candidate") or {})
            label = self._build_label_payload() if self.pending_replay_label_point is not None else self._current_replay_label()
            intended_action = {
                "label": label.get("target_type", "other").replace("_", " ").title(),
                "target_type": label.get("target_type", "other"),
                "keyword": str((self.pending_replay_label_candidate or {}).get("keyword") or label.get("target_type", "")).strip().lower(),
                "point": label.get("point"),
                "browser_point": label.get("browser_point"),
                "note": label.get("note", ""),
            }
            ocr_excerpt = str(self.current_replay_entry.get("guide_excerpt") or "")
            note = str(label.get("note", "") or "")
        elif self.last_analysis:
            source = "current_capture"
            screen_state = str(self.last_analysis.get("screen_state") or "unknown").strip().lower()
            chosen_candidate = dict((self.last_diagnostics or {}).get("chosen_candidate") or {})
            top_action = dict(((self.last_screen_action_map or {}).get("merged_actions") or [{}])[0] or {})
            intended_action = {
                "label": str(top_action.get("label") or chosen_candidate.get("label") or "Observed Action"),
                "target_type": str(top_action.get("keyword") or chosen_candidate.get("keyword") or "other").strip().lower() or "other",
                "keyword": str(top_action.get("keyword") or chosen_candidate.get("keyword") or "").strip().lower(),
                "point": list(top_action.get("center") or [])[:2] if top_action.get("center") else None,
                "note": f"Saved from {self.last_dom_source_label or 'current analysis'}",
            }
            ocr_excerpt = str(self.last_analysis.get("ocr_excerpt") or "")
            note = str(intended_action.get("note") or "")
        else:
            QMessageBox.information(self, "Guide Coach", "Analyze a frame or select a replay row before saving evidence.")
            return

        game_key = str(context.get("game") or self.profile_key).strip() or self.profile_key
        profile_key = str(context.get("profile") or self.profile_key).strip() or self.profile_key
        runtime = str(context.get("runtime") or "browser").strip() or "browser"
        task_key = (
            str(intended_action.get("target_type") or "").strip().lower()
            or str(chosen_candidate.get("keyword") or "").strip().lower()
            or str(screen_state or "unknown")
        )
        dom_summary = self._dom_snapshot_summary(self.last_dom_snapshot)
        record = self.evidence_store.record(
            {
                "game": game_key,
                "profile": profile_key,
                "screen_state": screen_state or "unknown",
                "task_key": task_key,
                "runtime": runtime,
                "worker_id": context.get("worker_id", ""),
                "session_id": context.get("session_id", ""),
                "source": source,
                "dom_snapshot_summary": dom_summary,
                "ocr_excerpt": ocr_excerpt,
                "chosen_candidate": chosen_candidate,
                "intended_action": intended_action,
                "confirmed_outcome": outcome_value,
                "visible_transition": outcome_value == "advanced",
                "frame_hash": frame_hash(self.current_replay_source_frame if source == "replay" else self.last_frame),
                "screenshot_hash": str((self.last_dom_snapshot or {}).get("screenshot_hash", "") or ""),
                "note": note,
            }
        )
        self._refresh_evidence_summary(screen_state=screen_state or "unknown")
        if self.last_dom_snapshot:
            action_map = self._build_dom_action_map(self.last_dom_snapshot, self.last_analysis or {}, self.last_frame)
            self.last_screen_action_map = action_map
            self._update_dom_snapshot_ui(self.last_dom_snapshot, action_map, source_label=self.last_dom_source_label or "DOM Snapshot")
        self._set_status(f"Saved {outcome_value.replace('_', ' ')} evidence for {record['task_key']}")

    def _analyze_frame(self, frame, source_label: str, update_status: bool = True):
        analysis = self.engine.analyze_frame(frame, checklist_progress=self.checklist_progress, source_label=source_label)
        diagnostics = self.diagnostics_engine.analyze_frame(
            frame,
            guide_analysis=analysis,
            calibration_profile=self._active_calibration_profile(),
            source_label=source_label,
        )
        self._apply_analysis(analysis, frame, diagnostics=diagnostics)
        if update_status:
            self._set_status(f"Guide Coach analyzed {source_label.lower()}")

    def _apply_analysis(self, analysis: dict, frame, diagnostics: dict | None = None):
        self.last_analysis = analysis
        self.last_diagnostics = diagnostics or {}
        self.last_frame = frame.copy() if frame is not None and hasattr(frame, "copy") else frame
        self.screen_state_label.setText(f"State: {analysis.get('screen_label', 'Unknown')}")
        self.screen_confidence_label.setText(f"Confidence: {float(analysis.get('confidence', 0.0)):.2f}")
        self.screen_source_label.setText(f"Source: {analysis.get('source_label', 'Unknown')}")
        signals = analysis.get("signals", {})
        active_signals = [label.replace("_", " ") for label, enabled in signals.items() if enabled]
        self.screen_signals_label.setText(
            "Signals: " + (", ".join(active_signals) if active_signals else "none detected")
        )
        evidence_summary = self._evidence_summary_for_state(analysis.get("screen_state", "unknown"))
        self.recommendation_list.clear()
        for recommendation in analysis.get("recommendations", []):
            self.recommendation_list.addItem(QListWidgetItem(recommendation))
        for hint in list(evidence_summary.get("task_hints", []))[:3]:
            self.recommendation_list.addItem(
                QListWidgetItem(
                    f"Evidence Hint: {hint.get('task_key', 'task')} -> {hint.get('target_type', 'target')} ({int(hint.get('count', 0) or 0)} confirmations)"
                )
            )
        tips = analysis.get("tips", [])
        evidence_lines = list(evidence_summary.get("summary_lines", []))[:3]
        all_tips = list(tips)
        if evidence_lines:
            all_tips.append("")
            all_tips.extend(evidence_lines)
        self.tip_label.setText("\n".join(all_tips).strip() if all_tips else "No extra guide note matched this screen yet.")
        self.analysis_excerpt_label.setText(f"OCR excerpt: {analysis.get('ocr_excerpt', 'No OCR text detected.')}")
        chosen = (self.last_diagnostics or {}).get("chosen_candidate") or {}
        loop_flags = ", ".join((self.last_diagnostics or {}).get("loop_risk", {}).get("flags", []))
        self.current_target_label.setText(f"Top target: {chosen.get('label', 'none')} | Focus: {(self.last_diagnostics or {}).get('focus_region', 'n/a')}")
        self.current_loop_label.setText(f"Loop risk: {loop_flags if loop_flags else 'none detected'}")
        annotated = self.diagnostics_engine.render_overlay(
            self.last_frame,
            self.last_diagnostics,
            calibration_profile=self._active_calibration_profile(),
            show_focus_masks=self.show_focus_masks_checkbox.isChecked() if hasattr(self, "show_focus_masks_checkbox") else True,
        )
        self.current_preview_frame = annotated if annotated is not None else self.last_frame
        self._set_preview_frame(self.current_preview_frame)
        self._refresh_checklist(analysis)
        if self.last_dom_snapshot:
            self.last_screen_action_map = self._build_dom_action_map(self.last_dom_snapshot, analysis, frame)
            self._update_dom_snapshot_ui(self.last_dom_snapshot, self.last_screen_action_map, source_label=self.last_dom_source_label or "DOM Snapshot")
        else:
            self._refresh_evidence_summary(screen_state=analysis.get("screen_state", "unknown"))
        self.use_current_analysis_for_calibration()

    def _manual_context(self) -> dict:
        if callable(self.manual_context_provider):
            try:
                payload = self.manual_context_provider() or {}
                if isinstance(payload, dict):
                    return dict(payload)
            except Exception:
                return {}
        return {}

    def _evidence_summary_for_state(self, screen_state: str) -> dict:
        context = self._manual_context()
        return self.evidence_store.aggregate(
            game=str(context.get("game") or self.profile_key).strip() or self.profile_key,
            profile=str(context.get("profile") or self.profile_key).strip() or self.profile_key,
            screen_state=str(screen_state or "unknown").strip().lower() or "unknown",
            runtime=str(context.get("runtime") or "browser").strip() or "browser",
        )

    def _build_dom_action_map(self, snapshot: dict, analysis: dict, frame) -> dict:
        evidence_summary = self._evidence_summary_for_state((analysis or {}).get("screen_state", "unknown"))
        action_map = self.dom_analyzer.build_screen_action_map(
            snapshot,
            ocr_boxes=list((analysis or {}).get("ocr_boxes", []) or []),
            screen_state=(analysis or {}).get("screen_state", "unknown"),
            guide_analysis=analysis,
            evidence_summary=evidence_summary,
        )
        if frame is not None and not action_map.get("dom_snapshot", {}).get("screenshot_hash"):
            action_map["dom_snapshot"]["screenshot_hash"] = frame_hash(frame)
        return action_map

    def _dom_snapshot_summary(self, snapshot: dict | None) -> dict:
        snapshot = dict(snapshot or {})
        actionables = list(snapshot.get("actionables", []) or [])
        return {
            "url": str(snapshot.get("url", "") or ""),
            "title": str(snapshot.get("title", "") or ""),
            "viewport": dict(snapshot.get("viewport") or {}),
            "raw_text_summary": str(snapshot.get("raw_text_summary", "") or ""),
            "actionable_count": int(snapshot.get("actionable_count", len(actionables)) or 0),
            "top_actionables": list(actionables[:8]),
            "screenshot_hash": str(snapshot.get("screenshot_hash", "") or ""),
        }

    def _update_dom_snapshot_ui(self, snapshot: dict | None, action_map: dict | None, source_label: str = ""):
        snapshot = dict(snapshot or {})
        action_map = dict(action_map or {})
        self.last_dom_snapshot = snapshot
        self.last_screen_action_map = action_map
        source_text = str(source_label or snapshot.get("url") or "DOM Snapshot").strip()
        if not snapshot:
            self.dom_snapshot_summary_label.setText("No DOM snapshot captured yet.")
            self.dom_snapshot_text.setPlainText("DOM snapshot details will appear here.")
            self.dom_action_table.setRowCount(0)
            self._refresh_evidence_summary(screen_state=(self.last_analysis or {}).get("screen_state", "unknown"))
            return
        self.dom_snapshot_summary_label.setText(
            f"Source: {source_text} | URL: {snapshot.get('url', 'n/a')} | "
            f"Viewport: {snapshot.get('viewport', {}).get('width', 0)} x {snapshot.get('viewport', {}).get('height', 0)} | "
            f"Actionables: {snapshot.get('actionable_count', 0)}"
        )
        lines = [
            f"Title: {snapshot.get('title', '') or 'N/A'}",
            f"Screenshot Hash: {snapshot.get('screenshot_hash', '') or 'n/a'}",
            "",
            str(snapshot.get("raw_text_summary", "") or "No DOM text summary captured."),
        ]
        self.dom_snapshot_text.setPlainText("\n".join(lines).strip())
        self._populate_dom_action_table(list(action_map.get("merged_actions", []) or []))
        self._refresh_evidence_summary(screen_state=(action_map or {}).get("screen_state", (self.last_analysis or {}).get("screen_state", "unknown")))

    def _populate_dom_action_table(self, actions: list[dict]):
        self.dom_action_table.setRowCount(len(actions[:10]))
        for row, action in enumerate(actions[:10]):
            values = [
                str(action.get("source", "")).upper(),
                action.get("label", ""),
                f"{float(action.get('score', 0.0) or 0.0):.2f}",
                action.get("keyword", "") or action.get("kind", "") or action.get("role", ""),
                action.get("selector_hint", ""),
            ]
            for column, value in enumerate(values):
                cell = QTableWidgetItem(str(value))
                cell.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                if column == 1:
                    cell.setToolTip(str(action.get("reason", "") or ""))
                self.dom_action_table.setItem(row, column, cell)
        self.dom_action_table.resizeRowsToContents()

    def _refresh_evidence_summary(self, screen_state: str = "unknown"):
        summary = self._evidence_summary_for_state(screen_state)
        lines = list(summary.get("summary_lines", []) or [])
        hints = list(summary.get("task_hints", []) or [])
        if hints:
            lines.append("")
            lines.append("Task Hints:")
            for row in hints[:5]:
                lines.append(
                    f"- {row.get('task_key', 'task')} -> {row.get('target_type', 'target')} ({int(row.get('count', 0) or 0)})"
                )
        avoids = list(summary.get("avoid_patterns", []) or [])
        if avoids:
            lines.append("")
            lines.append("Avoid Patterns:")
            for row in avoids[:5]:
                lines.append(
                    f"- {row.get('kind', 'unknown')} / {row.get('keyword', 'unknown')} ({int(row.get('count', 0) or 0)})"
                )
        self.evidence_summary_text.setPlainText(
            "\n".join(lines).strip() if lines else "Saved evidence summaries and hints will appear here."
        )

    def _refresh_checklist(self, analysis: dict | None = None):
        checklist = self.engine.build_checklist(self.checklist_progress, analysis)
        self._populating_checklist = True
        self.checklist_table.blockSignals(True)
        self.checklist_table.setRowCount(len(checklist))
        for row, entry in enumerate(checklist):
            done_item = QTableWidgetItem("")
            done_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            done_item.setCheckState(Qt.Checked if entry["completed"] else Qt.Unchecked)
            done_item.setData(Qt.ItemDataRole.UserRole, entry["id"])
            self.checklist_table.setItem(row, 0, done_item)

            priority_item = QTableWidgetItem(entry["priority"])
            priority_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.checklist_table.setItem(row, 1, priority_item)

            f2p_item = QTableWidgetItem("Yes" if entry["f2p"] else "No")
            f2p_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.checklist_table.setItem(row, 2, f2p_item)

            title_item = QTableWidgetItem(entry["title"])
            title_item.setToolTip(entry["summary"])
            title_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.checklist_table.setItem(row, 3, title_item)

            status_text = "Detected in current screen" if entry["observed"] else entry["summary"]
            status_item = QTableWidgetItem(status_text)
            status_item.setToolTip(entry["summary"])
            status_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.checklist_table.setItem(row, 4, status_item)
        self.checklist_table.blockSignals(False)
        self._populating_checklist = False

        completed = sum(1 for item in checklist if item["completed"])
        f2p_count = sum(1 for item in checklist if item["f2p"])
        observed_count = sum(1 for item in checklist if item["observed"])
        self.checklist_summary_label.setText(
            f"Completed: {completed} / {len(checklist)} | F2P items: {f2p_count} | Detected now: {observed_count}"
        )

    def _on_checklist_item_changed(self, item: QTableWidgetItem):
        if self._populating_checklist or item.column() != 0:
            return
        item_id = str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
        if not item_id:
            return
        self.checklist_progress[item_id] = item.checkState() == Qt.Checked
        self._refresh_checklist(self.last_analysis or None)

    def _update_replay_review_ui(self, review: dict):
        summary_lines = list(review.get("summary", []))
        state_counts = review.get("state_counts", {})
        issue_counts = review.get("issue_counts", {})
        comparison_report = dict(review.get("comparison_report") or {})
        if state_counts:
            summary_lines.append("")
            summary_lines.append("Screen States Seen:")
            for state, count in sorted(state_counts.items(), key=lambda item: (-item[1], item[0])):
                summary_lines.append(f"- {state.replace('_', ' ').title()}: {count}")
        if issue_counts:
            summary_lines.append("")
            summary_lines.append("Diagnostics Flags:")
            for flag, count in sorted(issue_counts.items(), key=lambda item: (-item[1], item[0])):
                summary_lines.append(f"- {flag.replace('_', ' ').title()}: {count}")
        self.replay_report_text.setPlainText("\n".join(summary_lines).strip())
        comparison_lines = list(comparison_report.get("summary_lines", []))
        top_losing_targets = list(comparison_report.get("top_losing_targets", []))
        if top_losing_targets:
            comparison_lines.append("")
            comparison_lines.append("Top Losing Small Targets:")
            for row in top_losing_targets:
                comparison_lines.append(
                    f"- {str(row.get('kind', 'unknown')).title()} / {str(row.get('keyword', 'unknown')).replace('_', ' ').title()}: {int(row.get('count', 0) or 0)}"
                )
        self.replay_comparison_summary.setPlainText(
            "\n".join(comparison_lines).strip() if comparison_lines else "Comparison insights will appear here after replay analysis."
        )
        self._populate_comparison_examples(comparison_report)

        timeline = review.get("timeline", [])
        self.replay_timeline_table.setRowCount(len(timeline))
        for row, entry in enumerate(timeline):
            values = [
                entry.get("timestamp", ""),
                entry.get("screen_label", entry.get("screen_state", "Unknown")),
                "Yes" if entry.get("advanced") else "No",
                f"{float(entry.get('advance_score', 0.0)):.2f}",
                entry.get("chosen_label", ""),
                entry.get("top_recommendation", ""),
            ]
            for column, value in enumerate(values):
                cell = QTableWidgetItem(str(value))
                cell.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                if column >= 4:
                    reasons = entry.get("reasons", [])
                    if reasons:
                        cell.setToolTip("\n".join(str(reason) for reason in reasons))
                self.replay_timeline_table.setItem(row, column, cell)
        self.replay_timeline_table.resizeRowsToContents()
        if timeline:
            self.replay_timeline_table.selectRow(0)
            self._on_replay_selection_changed()
        else:
            self.current_replay_entry = {}
            self.current_replay_source_frame = None
            self.replay_preview_label.setText("Run a replay review to inspect selected frames with overlays.")
            self.replay_preview_label.setPixmap(QPixmap())
            self.replay_candidate_table.setRowCount(0)
            self.replay_miss_text.setPlainText("Miss diagnostics and suggested fixes will appear here.")
            self.label_summary_label.setText("Click the selected replay frame to mark the intended target.")

    def _set_preview_frame(self, frame):
        if frame is None:
            self.preview_label.setText("No preview available for the current analysis.")
            self.preview_label.setPixmap(QPixmap())
            return
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        height, width, channels = rgb.shape
        image = QImage(rgb.data, width, height, channels * width, QImage.Format.Format_RGB888)
        pixmap = QPixmap.fromImage(image)
        scaled = pixmap.scaled(
            max(1, self.preview_label.width()),
            max(1, self.preview_label.height()),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self.preview_label.setText("")
        self.preview_label.setPixmap(scaled)

    def resizeEvent(self, event):  # pragma: no cover - UI behavior
        super().resizeEvent(event)
        if self.current_preview_frame is not None:
            self._set_preview_frame(self.current_preview_frame)
        if self.current_replay_preview_frame is not None:
            self._set_replay_preview_frame(self.current_replay_preview_frame)
        self._refresh_calibration_preview()

    def _resolve_frame(self, provider):
        if not callable(provider):
            return None
        try:
            frame = provider()
        except Exception as exc:
            QMessageBox.warning(self, "Guide Coach", f"Frame capture failed: {exc}")
            return None
        if frame is None:
            return None
        return frame.copy() if hasattr(frame, "copy") else frame

    def _load_preview_frame_from_media(self, filename: str):
        path = Path(filename)
        suffix = path.suffix.lower()
        if suffix in {".png", ".jpg", ".jpeg", ".bmp"}:
            frame = cv2.imread(str(path))
            return frame if frame is not None else None
        capture = cv2.VideoCapture(str(path))
        if not capture.isOpened():
            return None
        ok, frame = capture.read()
        capture.release()
        if not ok:
            return None
        return frame

    def _on_replay_selection_changed(self):
        row = self.replay_timeline_table.currentRow() if hasattr(self, "replay_timeline_table") else -1
        frame_reviews = list((self.last_review or {}).get("frame_reviews", []))
        if row < 0 or row >= len(frame_reviews):
            return
        entry = dict(frame_reviews[row] or {})
        self.current_replay_entry = entry
        frame = None
        annotated_path = str(entry.get("annotated_image", "")).strip()
        media_path = (self.last_review or {}).get("media_path", "")
        if media_path:
            frame = self.diagnostics_engine.load_frame_from_media(media_path, int(entry.get("frame_index", 0) or 0))
        if frame is None and annotated_path and Path(annotated_path).exists():
            frame = cv2.imread(annotated_path)
        self.current_replay_source_frame = frame.copy() if frame is not None and hasattr(frame, "copy") else frame
        self._refresh_replay_preview()
        diagnostics = dict(entry.get("diagnostics") or {})
        chosen = diagnostics.get("chosen_candidate") or {}
        flags = ", ".join((diagnostics.get("loop_risk") or {}).get("flags", []))
        focus_summary = self._format_focus_assessment(entry.get("focus_mask_assessment") or diagnostics.get("focus_mask_assessment") or {})
        self.replay_frame_summary_label.setText(
            f"{entry.get('timestamp', '--')} | {entry.get('screen_label', 'Unknown')} | "
            f"Chosen: {chosen.get('label', 'none')} | Flags: {flags or 'none'} | Focus: {focus_summary}"
        )
        self._populate_replay_candidates(diagnostics.get("candidates", []))
        miss_lines = list(diagnostics.get("miss_diagnosis", [])) + [""] + list(diagnostics.get("improvement_suggestions", []))
        self.replay_miss_text.setPlainText("\n".join(line for line in miss_lines if line is not None).strip())
        self.pending_replay_label_point = tuple(entry.get("label", {}).get("point")) if isinstance(entry.get("label", {}).get("point"), (list, tuple)) else None
        self.pending_replay_label_candidate = self.diagnostics_engine.find_candidate_at_point(diagnostics, self.pending_replay_label_point)
        self._load_current_label_into_controls()
        self._refresh_label_summary()
        self._refresh_evidence_summary(screen_state=entry.get("screen_state", "unknown"))
        if frame is not None:
            self.calibration_source_frame = frame.copy() if hasattr(frame, "copy") else frame
            self.calibration_source_diagnostics = diagnostics
            self.calibration_summary_label.setText(
                f"Calibration source: replay frame {entry.get('timestamp', '--')} | Focus: {focus_summary}"
            )
            self._refresh_calibration_preview()

    def _populate_replay_candidates(self, candidates: list[dict]):
        self.replay_candidate_table.setRowCount(len(candidates[:8]))
        for row, candidate in enumerate(candidates[:8]):
            browser_point = candidate.get("browser_point")
            values = [
                int(candidate.get("rank", row + 1) or (row + 1)),
                candidate.get("label", candidate.get("keyword", "target")),
                candidate.get("kind", ""),
                f"{float(candidate.get('total_score', 0.0) or 0.0):.1f}",
                f"{browser_point[0]}, {browser_point[1]}" if browser_point else "--",
            ]
            for column, value in enumerate(values):
                cell = QTableWidgetItem(str(value))
                cell.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                if column == 1:
                    breakdown = candidate.get("score_breakdown", {})
                    tooltip = [
                        f"Detector: {breakdown.get('detector_score', 0.0):.1f}",
                        f"Kind Bonus: {breakdown.get('kind_bonus', 0.0):.1f}",
                        f"Keyword Bonus: {breakdown.get('keyword_bonus', 0.0):.1f}",
                        f"Vertical Bonus: {breakdown.get('vertical_bonus', 0.0):.1f}",
                        f"Vertical Penalty: {breakdown.get('vertical_penalty', 0.0):.1f}",
                        f"Panel Penalty: {breakdown.get('oversized_panel_penalty', 0.0):.1f}",
                    ]
                    cell.setToolTip("\n".join(tooltip))
                self.replay_candidate_table.setItem(row, column, cell)
        self.replay_candidate_table.resizeRowsToContents()

    def _set_replay_preview_frame(self, frame):
        if frame is None:
            self.replay_preview_label.setText("Replay preview unavailable for the selected entry.")
            self.replay_preview_label.setPixmap(QPixmap())
            return
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        height, width, channels = rgb.shape
        image = QImage(rgb.data, width, height, channels * width, QImage.Format.Format_RGB888)
        pixmap = QPixmap.fromImage(image)
        scaled = pixmap.scaled(
            max(1, self.replay_preview_label.width()),
            max(1, self.replay_preview_label.height()),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self.replay_preview_label.setText("")
        self.replay_preview_label.setPixmap(scaled)
        self.replay_preview_label.set_frame_shape(frame.shape, preview_scale=float(scaled.width()) / max(1.0, float(width)))

    def _refresh_replay_preview(self):
        if self.current_replay_source_frame is None:
            self.current_replay_preview_frame = None
            self._set_replay_preview_frame(None)
            return
        diagnostics = dict((self.current_replay_entry or {}).get("diagnostics") or {})
        label_payload = self._current_replay_label()
        intended_point = tuple(label_payload["point"]) if label_payload.get("point") is not None else self.pending_replay_label_point
        selected_token = str(label_payload.get("matched_candidate_token", "") or "")
        if not selected_token and self.pending_replay_label_candidate:
            selected_token = str(self.pending_replay_label_candidate.get("token", "") or "")
        frame = self.diagnostics_engine.render_overlay(
            self.current_replay_source_frame,
            diagnostics,
            calibration_profile=self._active_calibration_profile(),
            intended_point=intended_point,
            selected_token=selected_token,
            show_focus_masks=self.show_focus_masks_checkbox.isChecked() if hasattr(self, "show_focus_masks_checkbox") else True,
        )
        self.current_replay_preview_frame = frame
        self._set_replay_preview_frame(frame)

    def _populate_comparison_examples(self, comparison_report: dict):
        examples = list(comparison_report.get("broad_vs_small_examples", [])) + list(comparison_report.get("focus_miss_examples", []))
        self.replay_comparison_rows = examples
        self.replay_comparison_table.setRowCount(len(examples))
        for row, entry in enumerate(examples):
            values = [
                entry.get("issue", ""),
                entry.get("timestamp", ""),
                entry.get("screen_label", ""),
                entry.get("chosen_label", ""),
                entry.get("alternative_label", ""),
            ]
            for column, value in enumerate(values):
                cell = QTableWidgetItem(str(value))
                cell.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                self.replay_comparison_table.setItem(row, column, cell)
        self.replay_comparison_table.resizeRowsToContents()

    def _on_comparison_selection_changed(self):
        row = self.replay_comparison_table.currentRow() if hasattr(self, "replay_comparison_table") else -1
        if row < 0 or row >= len(self.replay_comparison_rows):
            return
        frame_index = int(self.replay_comparison_rows[row].get("frame_index", -1) or -1)
        for timeline_row, entry in enumerate(list((self.last_review or {}).get("timeline", []))):
            if int(entry.get("frame_index", -2) or -2) == frame_index:
                self.replay_timeline_table.selectRow(timeline_row)
                break

    def _current_replay_label(self) -> dict:
        return self.diagnostics_engine.normalize_frame_label((self.current_replay_entry or {}).get("label"), calibration_profile=self._active_calibration_profile())

    def _label_target_type_value(self) -> str:
        text = self.label_target_type_combo.currentText().strip().lower() if hasattr(self, "label_target_type_combo") else "other"
        return text.replace(" ", "_")

    def _label_outcome_value(self) -> str:
        return self.label_outcome_combo.currentText().strip().lower() if hasattr(self, "label_outcome_combo") else "neutral"

    def _load_current_label_into_controls(self):
        label = self._current_replay_label()
        target_text = str(label.get("target_type", self.last_label_target_type) or self.last_label_target_type).replace("_", " ").title()
        outcome_text = str(label.get("outcome", self.last_label_outcome) or self.last_label_outcome).title()
        self.label_target_type_combo.blockSignals(True)
        self.label_outcome_combo.blockSignals(True)
        self.label_note_input.blockSignals(True)
        self.label_target_type_combo.setCurrentText(target_text)
        self.label_outcome_combo.setCurrentText(outcome_text)
        self.label_note_input.setText(str(label.get("note", "") or ""))
        self.label_target_type_combo.blockSignals(False)
        self.label_outcome_combo.blockSignals(False)
        self.label_note_input.blockSignals(False)

    def _build_label_payload(self) -> dict:
        point = None
        if self.pending_replay_label_point is not None:
            point = [int(self.pending_replay_label_point[0]), int(self.pending_replay_label_point[1])]
        candidate = self.pending_replay_label_candidate
        matched_token = ""
        if candidate is not None:
            matched_token = str(candidate.get("token", "") or "")
        return self.diagnostics_engine.normalize_frame_label(
            {
                "point": point,
                "target_type": self._label_target_type_value(),
                "outcome": self._label_outcome_value(),
                "note": self.label_note_input.text().strip() if hasattr(self, "label_note_input") else "",
                "matched_candidate_token": matched_token,
            },
            calibration_profile=self._active_calibration_profile(),
        )

    def _refresh_label_summary(self):
        label = self._build_label_payload() if self.pending_replay_label_point is not None else self._current_replay_label()
        if label.get("point") is None:
            self.label_summary_label.setText("Click the selected replay frame to mark the intended target.")
            return
        chosen = dict((self.current_replay_entry or {}).get("diagnostics", {}).get("chosen_candidate") or {})
        delta_text = "n/a"
        if chosen:
            delta_x = int(label["point"][0]) - int(chosen.get("x", 0) or 0)
            delta_y = int(label["point"][1]) - int(chosen.get("y", 0) or 0)
            delta_text = f"{delta_x:+d}, {delta_y:+d}"
        candidate_label = self.diagnostics_engine._candidate_label(self.pending_replay_label_candidate) if self.pending_replay_label_candidate else "none"
        matched = "yes" if str(label.get("matched_candidate_token", "") or "") == str(chosen.get("token", "") or "") and chosen else "no"
        self.label_summary_label.setText(
            f"Intended: {label['target_type'].replace('_', ' ').title()} @ {label['point'][0]}, {label['point'][1]} | "
            f"Nearest target: {candidate_label} | Delta vs chosen: {delta_text} | Matched chosen: {matched}"
        )

    def _on_replay_preview_clicked(self, x: int, y: int):
        if not self.current_replay_entry:
            return
        self.pending_replay_label_point = (x, y)
        diagnostics = dict((self.current_replay_entry or {}).get("diagnostics") or {})
        self.pending_replay_label_candidate = self.diagnostics_engine.find_candidate_at_point(diagnostics, self.pending_replay_label_point)
        self._refresh_label_summary()
        self._refresh_replay_preview()

    def _on_label_controls_changed(self, *_args):
        self.last_label_target_type = self._label_target_type_value()
        self.last_label_outcome = self._label_outcome_value()
        if self.pending_replay_label_point is not None or self._current_replay_label().get("point") is not None:
            self._refresh_label_summary()

    def _use_top_candidate_for_label(self):
        diagnostics = dict((self.current_replay_entry or {}).get("diagnostics") or {})
        chosen = diagnostics.get("chosen_candidate") or {}
        if not chosen:
            QMessageBox.information(self, "Guide Coach", "No ranked target is available for this replay frame.")
            return
        self.pending_replay_label_point = (int(chosen.get("x", 0) or 0), int(chosen.get("y", 0) or 0))
        self.pending_replay_label_candidate = dict(chosen)
        self._refresh_label_summary()
        self._refresh_replay_preview()

    def _save_current_replay_label(self):
        if not self.current_replay_entry:
            QMessageBox.information(self, "Guide Coach", "Select a replay frame first.")
            return
        if self.pending_replay_label_point is None:
            QMessageBox.information(self, "Guide Coach", "Click the replay preview to mark the intended target first.")
            return
        row = self.replay_timeline_table.currentRow()
        frame_reviews = list((self.last_review or {}).get("frame_reviews", []))
        if row < 0 or row >= len(frame_reviews):
            return
        updated_entry = self.diagnostics_engine.attach_label_to_frame_review(
            frame_reviews[row],
            self._build_label_payload(),
            calibration_profile=self._active_calibration_profile(),
        )
        frame_reviews[row] = updated_entry
        review = dict(self.last_review or {})
        review["frame_reviews"] = frame_reviews
        self.last_review = self.diagnostics_engine.normalize_review(review, calibration_profile=self._active_calibration_profile())
        self.current_replay_entry = dict(self.last_review["frame_reviews"][row])
        self.pending_replay_label_point = tuple(self.current_replay_entry.get("label", {}).get("point")) if self.current_replay_entry.get("label", {}).get("point") is not None else None
        self.pending_replay_label_candidate = self.diagnostics_engine.find_candidate_at_point(
            self.current_replay_entry.get("diagnostics"),
            self.pending_replay_label_point,
        )
        self._update_replay_review_ui(self.last_review)
        self.replay_timeline_table.selectRow(row)
        self._set_status("Guide Coach intended-target label saved")

    def _clear_current_replay_label(self):
        if not self.current_replay_entry:
            return
        row = self.replay_timeline_table.currentRow()
        frame_reviews = list((self.last_review or {}).get("frame_reviews", []))
        if row < 0 or row >= len(frame_reviews):
            return
        updated_entry = self.diagnostics_engine.attach_label_to_frame_review(
            frame_reviews[row],
            None,
            calibration_profile=self._active_calibration_profile(),
        )
        frame_reviews[row] = updated_entry
        review = dict(self.last_review or {})
        review["frame_reviews"] = frame_reviews
        self.last_review = self.diagnostics_engine.normalize_review(review, calibration_profile=self._active_calibration_profile())
        self.pending_replay_label_point = None
        self.pending_replay_label_candidate = None
        self._update_replay_review_ui(self.last_review)
        self.replay_timeline_table.selectRow(row)
        self._set_status("Guide Coach intended-target label cleared")

    def _format_focus_assessment(self, assessment: dict | None) -> str:
        assessment = dict(assessment or {})
        if not assessment.get("state_has_masks"):
            return "no masks"
        if assessment.get("outside_focus"):
            distance = assessment.get("distance_to_primary")
            if distance is None:
                return "outside focus"
            return f"outside focus ({float(distance):.1f}px)"
        zone = str(assessment.get("chosen_zone") or "")
        return zone or "inside focus"

    def _on_focus_masks_toggled(self, checked: bool):
        self.show_focus_masks = bool(checked)
        if self.last_frame is not None and self.last_diagnostics:
            self._apply_analysis(self.last_analysis, self.last_frame, diagnostics=self.last_diagnostics)
        if self.current_replay_entry:
            self._refresh_replay_preview()
        self._refresh_calibration_preview()

    def _on_evidence_preferences_changed(self, *_args):
        self.evidence_default_outcome = (
            self.evidence_default_outcome_combo.currentData() if hasattr(self, "evidence_default_outcome_combo") else "advanced"
        )
        self.evidence_export_include_dom = (
            self.evidence_export_include_dom_checkbox.isChecked()
            if hasattr(self, "evidence_export_include_dom_checkbox")
            else True
        )
        self._refresh_evidence_summary(screen_state=(self.last_analysis or {}).get("screen_state", "unknown"))

    def _active_calibration_profile(self) -> dict:
        host = self.calibration_host_input.text().strip() if hasattr(self, "calibration_host_input") else "lom.joynetgame.com"
        runtime = self.calibration_runtime_input.text().strip() if hasattr(self, "calibration_runtime_input") else "chromium"
        key = calibration_storage_key(host, "browser", runtime)
        self.active_calibration_profile_key = key
        return self.diagnostics_engine.normalize_calibration_profile(self.calibration_profiles.get(key, {}), host=host, mode="browser", runtime=runtime)

    def _load_active_calibration_profile_to_controls(self):
        profile = self._active_calibration_profile()
        self.capture_scale_x_spin.blockSignals(True)
        self.capture_scale_y_spin.blockSignals(True)
        self.offset_x_spin.blockSignals(True)
        self.offset_y_spin.blockSignals(True)
        self.preview_scale_spin.blockSignals(True)
        self.click_radius_spin.blockSignals(True)
        self.max_panel_ratio_spin.blockSignals(True)
        self.capture_scale_x_spin.setValue(float(profile.get("capture_scale_x", 1.0) or 1.0))
        self.capture_scale_y_spin.setValue(float(profile.get("capture_scale_y", 1.0) or 1.0))
        self.offset_x_spin.setValue(float(profile.get("offset_x", 0.0) or 0.0))
        self.offset_y_spin.setValue(float(profile.get("offset_y", 0.0) or 0.0))
        self.preview_scale_spin.setValue(float(profile.get("preview_scale", 1.0) or 1.0))
        self.click_radius_spin.setValue(int(profile.get("click_radius", 8) or 8))
        self.max_panel_ratio_spin.setValue(float(profile.get("max_panel_box_ratio", 0.18) or 0.18))
        self.capture_scale_x_spin.blockSignals(False)
        self.capture_scale_y_spin.blockSignals(False)
        self.offset_x_spin.blockSignals(False)
        self.offset_y_spin.blockSignals(False)
        self.preview_scale_spin.blockSignals(False)
        self.click_radius_spin.blockSignals(False)
        self.max_panel_ratio_spin.blockSignals(False)
        self._refresh_calibration_preview()

    def _save_active_calibration_profile_from_controls(self):
        if not hasattr(self, "capture_scale_x_spin"):
            return
        host = self.calibration_host_input.text().strip() if hasattr(self, "calibration_host_input") else "lom.joynetgame.com"
        runtime = self.calibration_runtime_input.text().strip() if hasattr(self, "calibration_runtime_input") else "chromium"
        key = calibration_storage_key(host, "browser", runtime)
        self.active_calibration_profile_key = key
        self.calibration_profiles[key] = self.diagnostics_engine.normalize_calibration_profile(
            {
                "capture_scale_x": self.capture_scale_x_spin.value(),
                "capture_scale_y": self.capture_scale_y_spin.value(),
                "offset_x": self.offset_x_spin.value(),
                "offset_y": self.offset_y_spin.value(),
                "preview_scale": self.preview_scale_spin.value(),
                "click_radius": self.click_radius_spin.value(),
                "max_panel_box_ratio": self.max_panel_ratio_spin.value(),
            },
            host=host,
            mode="browser",
            runtime=runtime,
        )

    def _on_calibration_controls_changed(self, *_args):
        self._save_active_calibration_profile_from_controls()
        self._refresh_calibration_preview()

    def _on_calibration_identity_changed(self, *_args):
        self._load_active_calibration_profile_to_controls()

    def use_current_analysis_for_calibration(self):
        if self.last_frame is None or not self.last_diagnostics:
            return
        self.calibration_source_frame = self.last_frame.copy() if hasattr(self.last_frame, "copy") else self.last_frame
        self.calibration_source_diagnostics = dict(self.last_diagnostics)
        focus_summary = self._format_focus_assessment((self.last_diagnostics or {}).get("focus_mask_assessment") or {})
        self.calibration_summary_label.setText(f"Calibration source: current Guide Coach analysis | Focus: {focus_summary}")
        self._refresh_calibration_preview()

    def use_replay_selection_for_calibration(self):
        if not self.current_replay_entry:
            QMessageBox.information(self, "Guide Coach", "Select a replay row first.")
            return
        frame = self.diagnostics_engine.load_frame_from_media(
            (self.last_review or {}).get("media_path", ""),
            int(self.current_replay_entry.get("frame_index", 0) or 0),
        )
        if frame is None:
            QMessageBox.information(self, "Guide Coach", "Unable to load the selected replay frame.")
            return
        self.calibration_source_frame = frame
        self.calibration_source_diagnostics = dict(self.current_replay_entry.get("diagnostics") or {})
        focus_summary = self._format_focus_assessment(self.current_replay_entry.get("focus_mask_assessment") or self.calibration_source_diagnostics.get("focus_mask_assessment") or {})
        self.calibration_summary_label.setText(
            f"Calibration source: replay frame {self.current_replay_entry.get('timestamp', '--')} | Focus: {focus_summary}"
        )
        self._refresh_calibration_preview()

    def _on_calibration_preview_clicked(self, x: int, y: int):
        self.calibration_click_point = (x, y)
        self.calibration_candidate = self.diagnostics_engine.find_candidate_at_point(self.calibration_source_diagnostics, self.calibration_click_point)
        calibration = self.diagnostics_engine.calibration_from_manual_point(
            self.calibration_source_diagnostics,
            self.calibration_click_point,
            self._active_calibration_profile(),
        )
        lines = [calibration.get("summary", "")]
        intended = calibration.get("intended_candidate")
        if intended:
            lines.append(f"Nearest target: {intended.get('label', 'target')}")
        focus_summary = self._format_focus_assessment(
            self.diagnostics_engine.assess_focus_masks(
                (self.calibration_source_diagnostics or {}).get("screen_state", "unknown"),
                getattr(self.calibration_source_frame, "shape", (720, 405)),
                chosen=(self.calibration_source_diagnostics or {}).get("chosen_candidate"),
                intended_point=self.calibration_click_point,
            )
        )
        lines.append(f"Focus assessment: {focus_summary}")
        self.calibration_details_text.setPlainText("\n".join(line for line in lines if line).strip())
        self._refresh_calibration_preview()

    def apply_last_calibration_click(self):
        if self.calibration_click_point is None:
            QMessageBox.information(self, "Guide Coach", "Click the intended target in the calibration preview first.")
            return
        calibration = self.diagnostics_engine.calibration_from_manual_point(
            self.calibration_source_diagnostics,
            self.calibration_click_point,
            self._active_calibration_profile(),
        )
        profile = calibration.get("profile", self._active_calibration_profile())
        self.calibration_profiles[self.active_calibration_profile_key] = dict(profile)
        self._load_active_calibration_profile_to_controls()
        self.calibration_details_text.setPlainText(calibration.get("summary", "Calibration applied."))
        self._set_status("Guide Coach calibration updated")

    def reset_active_calibration_profile(self):
        profile = self.diagnostics_engine.default_calibration_profile(
            host=self.calibration_host_input.text().strip(),
            mode="browser",
            runtime=self.calibration_runtime_input.text().strip(),
        )
        self.calibration_profiles[self.active_calibration_profile_key] = dict(profile)
        self.calibration_click_point = None
        self._load_active_calibration_profile_to_controls()
        self.calibration_details_text.setPlainText("Active calibration profile reset to defaults.")

    def _refresh_calibration_preview(self):
        if self.calibration_source_frame is None:
            self.calibration_preview_label.setText("Choose a current frame or replay frame, then click the intended target.")
            self.calibration_preview_label.setPixmap(QPixmap())
            return
        profile = self._active_calibration_profile()
        annotated = self.diagnostics_engine.render_overlay(
            self.calibration_source_frame,
            self.calibration_source_diagnostics,
            calibration_profile=profile,
            intended_point=self.calibration_click_point,
            show_focus_masks=self.show_focus_masks_checkbox.isChecked() if hasattr(self, "show_focus_masks_checkbox") else True,
        )
        if annotated is None:
            return
        rgb = cv2.cvtColor(annotated, cv2.COLOR_BGR2RGB)
        height, width, channels = rgb.shape
        image = QImage(rgb.data, width, height, channels * width, QImage.Format.Format_RGB888)
        pixmap = QPixmap.fromImage(image)
        scale = max(0.25, float(profile.get("preview_scale", 1.0) or 1.0))
        scaled = pixmap.scaled(int(width * scale), int(height * scale), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.calibration_preview_label.setText("")
        self.calibration_preview_label.setPixmap(scaled)
        self.calibration_preview_label.resize(scaled.size())
        self.calibration_preview_label.set_frame_shape(annotated.shape, preview_scale=scale)

    def _set_status(self, message: str):
        if callable(self.status_callback):
            try:
                self.status_callback(message)
                return
            except Exception:
                pass
