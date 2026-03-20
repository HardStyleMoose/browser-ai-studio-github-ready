from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QCheckBox,
    QStackedLayout,
)

from automation.n8n_sidecar import N8nSidecarManager
from core.security_utils import normalize_env_var_name

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
except Exception:  # pragma: no cover
    QWebEngineView = None


class N8nHubWidget(QWidget):
    def __init__(self, project_root, status_callback=None, parent=None):
        super().__init__(parent)
        self.project_root = Path(project_root)
        self.status_callback = status_callback
        self.manager = N8nSidecarManager(self.project_root)
        self._editor_view = None
        self._build_ui()
        self.refresh_status()
        self._reload_templates()

    def _safe_port(self) -> int:
        try:
            return max(1024, min(65535, int(self.port_input.text().strip() or 5678)))
        except Exception:
            return 5678

    def _default_install_dir(self) -> str:
        return str(self.project_root / "data" / "n8n_runtime" / "node_runtime")

    def _default_data_dir(self) -> str:
        return str(self.project_root / "data" / "n8n_runtime" / "user_data")

    def _normalized_editor_url(self, port: int | None = None) -> str:
        safe_port = self._safe_port() if port is None else max(1024, min(65535, int(port)))
        return f"http://localhost:{safe_port}"

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        overview_row = QHBoxLayout()
        overview_row.setSpacing(12)

        status_box, status_layout = self._make_group("Runtime Status")
        self.status_summary_label = QLabel("Checking local n8n runtime status...")
        self.status_summary_label.setWordWrap(True)
        status_layout.addWidget(self.status_summary_label)
        self.health_label = QLabel("Health: unknown")
        self.health_label.setWordWrap(True)
        status_layout.addWidget(self.health_label)
        self.editor_label = QLabel("Editor: http://localhost:5678")
        self.editor_label.setWordWrap(True)
        self.editor_label.setObjectName("mutedLabel")
        status_layout.addWidget(self.editor_label)
        self.install_label = QLabel("Install: not checked")
        self.install_label.setWordWrap(True)
        self.install_label.setObjectName("mutedLabel")
        status_layout.addWidget(self.install_label)
        overview_row.addWidget(status_box, 2)

        notes_box, notes_layout = self._make_group("Operational Notes")
        self.notes_text = QTextEdit()
        self.notes_text.setReadOnly(True)
        self.notes_text.setMinimumHeight(120)
        self.notes_text.setPlainText(
            "n8n runs as a local Node-managed runtime. The editor can be embedded with Qt WebEngine or opened in your system browser."
        )
        notes_layout.addWidget(self.notes_text)
        overview_row.addWidget(notes_box, 3)
        root.addLayout(overview_row)

        config_box, config_layout = self._make_group("Runtime Configuration")
        config_grid = QGridLayout()
        config_grid.setHorizontalSpacing(10)
        config_grid.setVerticalSpacing(8)
        config_grid.addWidget(QLabel("Mode"), 0, 0)
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Node Managed Local", "node_managed_local")
        config_grid.addWidget(self.mode_combo, 0, 1)
        config_grid.addWidget(QLabel("Editor Mode"), 1, 0)
        self.editor_mode_combo = QComboBox()
        self.editor_mode_combo.addItem("Embedded", "embedded")
        self.editor_mode_combo.addItem("External Browser", "external")
        self.editor_mode_combo.currentIndexChanged.connect(self._sync_editor_mode)
        config_grid.addWidget(self.editor_mode_combo, 1, 1)
        config_grid.addWidget(QLabel("Port"), 2, 0)
        self.port_input = QLineEdit("5678")
        config_grid.addWidget(self.port_input, 2, 1)
        config_grid.addWidget(QLabel("Editor URL"), 3, 0)
        self.editor_input = QLineEdit("http://localhost:5678")
        config_grid.addWidget(self.editor_input, 3, 1)
        config_grid.addWidget(QLabel("Install Directory"), 4, 0)
        self.install_dir_input = QLineEdit(self._default_install_dir())
        config_grid.addWidget(self.install_dir_input, 4, 1)
        config_grid.addWidget(QLabel("Data Directory"), 5, 0)
        self.data_dir_input = QLineEdit(self._default_data_dir())
        config_grid.addWidget(self.data_dir_input, 5, 1)
        config_grid.addWidget(QLabel("API Key Env Var"), 6, 0)
        self.api_key_env_input = QLineEdit("N8N_API_KEY")
        config_grid.addWidget(self.api_key_env_input, 6, 1)
        self.auto_start_checkbox = QCheckBox("Auto-start with the app")
        config_grid.addWidget(self.auto_start_checkbox, 7, 1)
        config_layout.addLayout(config_grid)

        config_buttons = QHBoxLayout()
        apply_button = QPushButton("Apply Config")
        apply_button.clicked.connect(self.apply_config)
        refresh_button = QPushButton("Refresh Status")
        refresh_button.clicked.connect(self.refresh_status)
        install_button = QPushButton("Install n8n")
        install_button.clicked.connect(self.install_runtime)
        update_button = QPushButton("Update n8n")
        update_button.clicked.connect(self.update_runtime)
        start_button = QPushButton("Start Runtime")
        start_button.clicked.connect(self.start_runtime)
        stop_button = QPushButton("Stop Runtime")
        stop_button.clicked.connect(self.stop_runtime)
        restart_button = QPushButton("Restart Runtime")
        restart_button.clicked.connect(self.restart_runtime)
        for button in [apply_button, refresh_button, install_button, update_button, start_button, stop_button, restart_button]:
            config_buttons.addWidget(button)
        config_buttons.addStretch()
        config_layout.addLayout(config_buttons)
        root.addWidget(config_box)

        editor_box, editor_layout = self._make_group("n8n Editor")
        editor_controls = QHBoxLayout()
        open_button = QPushButton("Open Editor")
        open_button.clicked.connect(self.open_editor)
        open_browser_button = QPushButton("Open In Browser")
        open_browser_button.clicked.connect(self.open_in_browser)
        reload_button = QPushButton("Reload Embedded")
        reload_button.clicked.connect(self.reload_embedded_editor)
        editor_controls.addWidget(open_button)
        editor_controls.addWidget(open_browser_button)
        editor_controls.addWidget(reload_button)
        editor_controls.addStretch()
        editor_layout.addLayout(editor_controls)

        self.editor_stack_host = QWidget()
        self.editor_stack = QStackedLayout(self.editor_stack_host)
        self.editor_placeholder = QTextEdit()
        self.editor_placeholder.setReadOnly(True)
        self.editor_placeholder.setMinimumHeight(260)
        self.editor_placeholder.setPlainText("The embedded n8n editor will appear here when the runtime is running.")
        self.editor_stack.addWidget(self.editor_placeholder)
        self.editor_stack.setCurrentWidget(self.editor_placeholder)
        editor_layout.addWidget(self.editor_stack_host, stretch=1)
        root.addWidget(editor_box, stretch=1)

        lower_split = QSplitter(Qt.Horizontal)

        template_box, template_layout = self._make_group("Workflow Templates")
        self.template_list = QListWidget()
        self.template_list.currentRowChanged.connect(self._update_template_detail)
        template_layout.addWidget(self.template_list)
        template_buttons = QHBoxLayout()
        self.export_template_button = QPushButton("Export Template")
        self.export_template_button.clicked.connect(self.export_selected_template)
        self.import_template_button = QPushButton("Import Template")
        self.import_template_button.clicked.connect(self.import_template_file)
        template_buttons.addWidget(self.export_template_button)
        template_buttons.addWidget(self.import_template_button)
        template_buttons.addStretch()
        template_layout.addLayout(template_buttons)
        self.template_detail_text = QTextEdit()
        self.template_detail_text.setReadOnly(True)
        self.template_detail_text.setMinimumHeight(140)
        self.template_detail_text.setPlainText("Select a workflow template to inspect it.")
        template_layout.addWidget(self.template_detail_text)
        lower_split.addWidget(template_box)

        runs_box, runs_layout = self._make_group("Execution History")
        self.runs_text = QTextEdit()
        self.runs_text.setReadOnly(True)
        self.runs_text.setMinimumHeight(220)
        self.runs_text.setPlainText("Recent n8n workflow runs will appear here when the runtime is healthy and an API key is configured.")
        runs_layout.addWidget(self.runs_text)
        refresh_runs_button = QPushButton("Refresh Runs")
        refresh_runs_button.clicked.connect(self.refresh_runs)
        runs_layout.addWidget(refresh_runs_button)
        lower_split.addWidget(runs_box)

        lower_split.setStretchFactor(0, 3)
        lower_split.setStretchFactor(1, 2)
        root.addWidget(lower_split)

    def _make_group(self, title: str):
        box = QGroupBox(title)
        layout = QVBoxLayout(box)
        layout.setContentsMargins(12, 16, 12, 12)
        layout.setSpacing(8)
        return box, layout

    def _sync_editor_mode(self):
        mode = self.editor_mode_combo.currentData()
        if mode == "embedded" and QWebEngineView is None:
            self.editor_placeholder.setPlainText(
                "Qt WebEngine is unavailable in this runtime, so embedded mode cannot be used. Switch to External Browser."
            )
            self.editor_stack.setCurrentWidget(self.editor_placeholder)
            return
        if mode == "external":
            self.editor_placeholder.setPlainText(
                "External editor mode is active. Use Open Editor or Open In Browser to work with n8n."
            )
            self.editor_stack.setCurrentWidget(self.editor_placeholder)
            return
        if self._ensure_embedded_view():
            self.editor_stack.setCurrentWidget(self._editor_view)

    def _ensure_embedded_view(self):
        if QWebEngineView is None:
            return False
        if self._editor_view is not None:
            return True
        try:
            self._editor_view = QWebEngineView()
            self._editor_view.setMinimumHeight(260)
            self.editor_stack.addWidget(self._editor_view)
            return True
        except Exception as exc:
            self._editor_view = None
            self.editor_placeholder.setPlainText(f"Unable to create embedded n8n editor: {exc}")
            self.editor_stack.setCurrentWidget(self.editor_placeholder)
            return False

    def _load_embedded_editor(self, force: bool = False):
        if self.editor_mode_combo.currentData() != "embedded":
            return
        if not self._ensure_embedded_view():
            return
        editor_url = self._normalized_editor_url()
        if force or self._editor_view.url().toString() != editor_url:
            self._editor_view.setUrl(QUrl(editor_url))
        self.editor_stack.setCurrentWidget(self._editor_view)

    def set_saved_state(self, payload: dict | None):
        payload = dict(payload or {})
        mode_value = str(payload.get("mode", "node_managed_local")).lower()
        if mode_value == "docker_sidecar":
            mode_value = "node_managed_local"
        self.mode_combo.setCurrentIndex(max(0, self.mode_combo.findData(mode_value)))
        port = int(payload.get("port", 5678) or 5678)
        self.port_input.setText(str(port))
        self.editor_input.setText(self._normalized_editor_url(port))
        self.install_dir_input.setText(str(payload.get("install_dir", self._default_install_dir())))
        data_dir = payload.get("data_dir", self._default_data_dir())
        if str(data_dir).replace("\\", "/").endswith("n8n_sidecar"):
            data_dir = self._default_data_dir()
        self.data_dir_input.setText(str(data_dir))
        editor_mode = str(payload.get("editor_mode") or "").strip().lower()
        if editor_mode not in {"embedded", "external"}:
            editor_mode = "external" if bool(payload.get("open_editor_externally", False)) else "embedded"
        self.editor_mode_combo.setCurrentIndex(max(0, self.editor_mode_combo.findData(editor_mode)))
        self.api_key_env_input.setText(normalize_env_var_name(str(payload.get("api_key_env_var", "N8N_API_KEY"))) or "N8N_API_KEY")
        self.auto_start_checkbox.setChecked(bool(payload.get("auto_start", False)))
        self.apply_config()
        self.refresh_status()

    def collect_state(self) -> dict:
        port = self._safe_port()
        editor_mode = str(self.editor_mode_combo.currentData() or "embedded")
        return {
            "mode": self.mode_combo.currentData(),
            "port": port,
            "editor_url": self._normalized_editor_url(port),
            "install_dir": self.install_dir_input.text().strip() or self._default_install_dir(),
            "data_dir": self.data_dir_input.text().strip() or self._default_data_dir(),
            "auto_start": self.auto_start_checkbox.isChecked(),
            "editor_mode": editor_mode,
            "open_editor_externally": editor_mode == "external",
            "last_template": self._selected_template_key(),
            "api_key_env_var": normalize_env_var_name(self.api_key_env_input.text().strip()) or "N8N_API_KEY",
            "last_installed_version": self.manager.installed_version(),
        }

    def apply_config(self):
        self.manager.apply_settings(self.collect_state())
        self._sync_editor_mode()
        self._set_status("n8n Hub config applied")
        self.refresh_status()

    def refresh_status(self):
        self.manager.apply_settings(self.collect_state())
        install_info = self.manager.install_status()
        status = self.manager.health_check()
        self.status_summary_label.setText(
            f"Node: {'available' if install_info.get('node_available') else 'unavailable'} | "
            f"Runtime: {'running' if status.get('process_running') else 'stopped'} | "
            f"{status.get('message', install_info.get('node_message', ''))}"
        )
        self.health_label.setText(
            f"Health: {status.get('health', 'unknown')} | "
            f"{status.get('health_message', status.get('message', 'No health details'))}"
        )
        self.editor_label.setText(
            f"Editor: {status.get('editor_url', self.editor_input.text().strip())} | mode={self.editor_mode_combo.currentText()}"
        )
        version = install_info.get("installed_version", "")
        install_text = (
            f"Installed: {version} | runtime={install_info.get('install_dir', '')}"
            if install_info.get("installed")
            else f"Installed: no | runtime={install_info.get('install_dir', '')}"
        )
        self.install_label.setText(install_text)
        self.refresh_runs()
        if status.get("process_running") and self.editor_mode_combo.currentData() == "embedded":
            self._load_embedded_editor(force=False)
        else:
            self._sync_editor_mode()

    def install_runtime(self):
        self.manager.apply_settings(self.collect_state())
        result = self.manager.install(update=False)
        self._set_status(result.get("message", "n8n install attempted"))
        self.refresh_status()

    def update_runtime(self):
        self.manager.apply_settings(self.collect_state())
        result = self.manager.update()
        self._set_status(result.get("message", "n8n update attempted"))
        self.refresh_status()

    def start_runtime(self):
        self.manager.apply_settings(self.collect_state())
        status = self.manager.start(install_if_missing=True)
        self._set_status(status.get("message", "n8n runtime start attempted"))
        self.refresh_status()

    def stop_runtime(self):
        self.manager.apply_settings(self.collect_state())
        status = self.manager.stop()
        self._set_status(status.get("message", "n8n runtime stop attempted"))
        self.refresh_status()

    def restart_runtime(self):
        self.manager.apply_settings(self.collect_state())
        status = self.manager.restart()
        self._set_status(status.get("message", "n8n runtime restart attempted"))
        self.refresh_status()

    def open_editor(self):
        self.manager.apply_settings(self.collect_state())
        if self.editor_mode_combo.currentData() == "embedded":
            self._load_embedded_editor(force=True)
            self._set_status("Embedded n8n editor loaded")
            return
        self.open_in_browser()

    def open_in_browser(self):
        self.manager.apply_settings(self.collect_state())
        result = self.manager.open_editor()
        self._set_status(result.get("message", "Open editor attempted"))

    def reload_embedded_editor(self):
        if self.editor_mode_combo.currentData() != "embedded":
            QMessageBox.information(self, "n8n Hub", "Switch the editor mode to Embedded first.")
            return
        self._load_embedded_editor(force=True)
        self._set_status("Embedded n8n editor reloaded")

    def _reload_templates(self):
        self.template_list.clear()
        templates = self.manager.load_templates()
        for row in templates:
            item = QListWidgetItem(str(row.get("name", "Workflow Template")))
            item.setData(Qt.UserRole, dict(row))
            self.template_list.addItem(item)
        if templates:
            self.template_list.setCurrentRow(0)
        else:
            self.template_detail_text.setPlainText("No n8n templates are available.")

    def _selected_template_key(self) -> str:
        item = self.template_list.currentItem()
        payload = dict(item.data(Qt.UserRole) or {}) if item is not None else {}
        return str(payload.get("key") or "").strip()

    def _update_template_detail(self):
        item = self.template_list.currentItem()
        payload = dict(item.data(Qt.UserRole) or {}) if item is not None else {}
        if not payload:
            self.template_detail_text.setPlainText("Select a workflow template to inspect it.")
            return
        self.template_detail_text.setPlainText(
            "\n".join(
                [
                    str(payload.get("name", "Workflow Template")),
                    "",
                    str(payload.get("description", "")).strip(),
                    "",
                    "Key:",
                    str(payload.get("key", "")).strip(),
                    "",
                    "Payload Preview:",
                    os.linesep.join([line.rstrip() for line in str(payload.get("payload", {})).splitlines()]) or str(payload.get("payload", {})),
                ]
            ).strip()
        )

    def export_selected_template(self):
        template_key = self._selected_template_key()
        if not template_key:
            QMessageBox.information(self, "n8n Hub", "Select a workflow template first.")
            return
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Export n8n Template",
            f"{template_key}.json",
            "JSON Files (*.json)",
        )
        if not filename:
            return
        self.manager.export_template(template_key, filename)
        self._set_status(f"Exported n8n template: {Path(filename).name}")

    def import_template_file(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Import n8n Template", "", "JSON Files (*.json)")
        if not filename:
            return
        self.manager.import_template(filename)
        self._reload_templates()
        self._set_status(f"Imported n8n template: {Path(filename).name}")

    def refresh_runs(self):
        self.manager.apply_settings(self.collect_state())
        runs = self.manager.execution_summaries(limit=8)
        if not runs:
            self.runs_text.setPlainText(
                "Recent n8n runs are unavailable. Start the runtime and configure the API key environment variable if you want execution summaries."
            )
            return
        lines = []
        for row in runs:
            lines.append(
                f"{row.get('workflow_name', 'Workflow')} | {row.get('status', 'unknown')} | "
                f"started={row.get('started_at', '')} | duration={float(row.get('duration_ms', 0.0) or 0.0):.0f} ms"
            )
        self.runs_text.setPlainText("\n".join(lines))

    def _set_status(self, message: str):
        if callable(self.status_callback):
            try:
                self.status_callback(str(message or "").strip())
            except Exception:
                pass
