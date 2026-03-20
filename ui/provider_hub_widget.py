from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
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
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from automation.provider_hub import (
    CATALOG_CATEGORIES,
    ProviderCatalogService,
    ProviderClient,
    validate_endpoint_profile_config,
)


class ProviderHubWidget(QWidget):
    def __init__(self, project_root, status_callback=None, parent=None):
        super().__init__(parent)
        self.project_root = Path(project_root)
        self.status_callback = status_callback
        self.catalog_service = ProviderCatalogService(self.project_root)
        self.provider_client = ProviderClient()
        self.catalog_payload = self.catalog_service.load_cache()
        self.endpoint_profiles = self.catalog_service.load_endpoint_profiles()
        self.auto_refresh_catalog = False
        self.last_category = "all"
        self.last_search = ""
        self.last_selected_profile = ""
        self._build_ui()
        self._reload_catalog_table()
        self._reload_profile_list()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        overview_row = QHBoxLayout()
        overview_row.setSpacing(12)
        catalog_box, catalog_layout = self._make_group("Catalog Summary")
        self.catalog_summary_label = QLabel("Catalog not loaded yet.")
        self.catalog_summary_label.setWordWrap(True)
        catalog_layout.addWidget(self.catalog_summary_label)
        self.catalog_source_label = QLabel("Sources: none")
        self.catalog_source_label.setWordWrap(True)
        self.catalog_source_label.setObjectName("mutedLabel")
        catalog_layout.addWidget(self.catalog_source_label)
        overview_row.addWidget(catalog_box, 2)

        provider_box, provider_layout = self._make_group("Endpoint Summary")
        self.endpoint_summary_label = QLabel("Configured endpoints: 0")
        self.endpoint_summary_label.setWordWrap(True)
        provider_layout.addWidget(self.endpoint_summary_label)
        self.endpoint_warning_label = QLabel(
            "Only explicitly configured documented API endpoints can be used. Catalog rows stay informational by default."
        )
        self.endpoint_warning_label.setWordWrap(True)
        self.endpoint_warning_label.setObjectName("mutedLabel")
        provider_layout.addWidget(self.endpoint_warning_label)
        overview_row.addWidget(provider_box, 2)
        root.addLayout(overview_row)

        catalog_group, catalog_layout = self._make_group("Catalog")
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Category"))
        self.catalog_category_combo = QComboBox()
        self.catalog_category_combo.addItem("All", "all")
        for category in CATALOG_CATEGORIES:
            self.catalog_category_combo.addItem(category.title(), category)
        self.catalog_category_combo.currentIndexChanged.connect(self._on_catalog_filters_changed)
        filter_row.addWidget(self.catalog_category_combo)
        filter_row.addWidget(QLabel("Search"))
        self.catalog_search_input = QLineEdit()
        self.catalog_search_input.setPlaceholderText("Search provider, note, link, or models")
        self.catalog_search_input.textChanged.connect(self._on_catalog_filters_changed)
        filter_row.addWidget(self.catalog_search_input, 1)
        self.catalog_auto_refresh_checkbox = QCheckBox("Refresh Catalog On Open")
        self.catalog_auto_refresh_checkbox.toggled.connect(self._on_auto_refresh_toggled)
        filter_row.addWidget(self.catalog_auto_refresh_checkbox)
        refresh_button = QPushButton("Refresh Catalog")
        refresh_button.clicked.connect(self.refresh_catalog)
        filter_row.addWidget(refresh_button)
        catalog_layout.addLayout(filter_row)

        self.catalog_table = QTableWidget(0, 8)
        self.catalog_table.setHorizontalHeaderLabels(
            ["Name", "Category", "Signup", "Limit Note", "API", "Style", "Models", "Link"]
        )
        self.catalog_table.verticalHeader().setVisible(False)
        self.catalog_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.catalog_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.catalog_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.catalog_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.catalog_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.catalog_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.catalog_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.catalog_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.catalog_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.catalog_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.Stretch)
        self.catalog_table.horizontalHeader().setSectionResizeMode(7, QHeaderView.Stretch)
        self.catalog_table.itemSelectionChanged.connect(self._update_catalog_detail)
        catalog_layout.addWidget(self.catalog_table)
        self.catalog_detail_text = QTextEdit()
        self.catalog_detail_text.setReadOnly(True)
        self.catalog_detail_text.setMinimumHeight(120)
        self.catalog_detail_text.setPlainText("Select a catalog entry to inspect its notes, limits, and API hints.")
        catalog_layout.addWidget(self.catalog_detail_text)
        root.addWidget(catalog_group)

        lower_row = QHBoxLayout()
        lower_row.setSpacing(12)

        profile_group, profile_layout = self._make_group("Compatible APIs")
        profile_split = QHBoxLayout()
        profile_split.setSpacing(12)
        self.profile_list = QListWidget()
        self.profile_list.currentRowChanged.connect(self._on_profile_selected)
        profile_split.addWidget(self.profile_list, 1)
        profile_form = QGridLayout()
        profile_form.setHorizontalSpacing(10)
        profile_form.setVerticalSpacing(8)
        profile_form.addWidget(QLabel("Label"), 0, 0)
        self.profile_label_input = QLineEdit()
        profile_form.addWidget(self.profile_label_input, 0, 1)
        profile_form.addWidget(QLabel("Base URL"), 1, 0)
        self.profile_base_url_input = QLineEdit()
        self.profile_base_url_input.setPlaceholderText("https://provider.example.com")
        profile_form.addWidget(self.profile_base_url_input, 1, 1)
        profile_form.addWidget(QLabel("API Key Env Var"), 2, 0)
        self.profile_api_env_input = QLineEdit()
        self.profile_api_env_input.setPlaceholderText("OPTIONAL_ENV_VAR")
        profile_form.addWidget(self.profile_api_env_input, 2, 1)
        profile_form.addWidget(QLabel("API Style"), 3, 0)
        self.profile_api_style_combo = QComboBox()
        self.profile_api_style_combo.addItem("OpenAI Chat", "openai_chat")
        self.profile_api_style_combo.addItem("OpenAI Responses", "openai_responses")
        self.profile_api_style_combo.addItem("Ollama Chat", "ollama_chat")
        self.profile_api_style_combo.addItem("Documented JSON API", "documented_api")
        profile_form.addWidget(self.profile_api_style_combo, 3, 1)
        profile_form.addWidget(QLabel("Models (comma-separated)"), 4, 0)
        self.profile_models_input = QLineEdit()
        profile_form.addWidget(self.profile_models_input, 4, 1)
        profile_form.addWidget(QLabel("Notes"), 5, 0)
        self.profile_notes_input = QTextEdit()
        self.profile_notes_input.setMinimumHeight(96)
        profile_form.addWidget(self.profile_notes_input, 5, 1)
        self.profile_enabled_checkbox = QCheckBox("Enable This Endpoint")
        profile_form.addWidget(self.profile_enabled_checkbox, 6, 1)
        profile_buttons = QHBoxLayout()
        save_profile_button = QPushButton("Save Profile")
        save_profile_button.clicked.connect(self.save_profile)
        delete_profile_button = QPushButton("Delete Profile")
        delete_profile_button.clicked.connect(self.delete_profile)
        health_button = QPushButton("Check Health")
        health_button.clicked.connect(self.check_selected_profile)
        profile_buttons.addWidget(save_profile_button)
        profile_buttons.addWidget(delete_profile_button)
        profile_buttons.addWidget(health_button)
        profile_buttons.addStretch()
        profile_wrapper = QVBoxLayout()
        profile_wrapper.addLayout(profile_form)
        profile_wrapper.addLayout(profile_buttons)
        profile_split.addLayout(profile_wrapper, 2)
        profile_layout.addLayout(profile_split)
        lower_row.addWidget(profile_group, 3)

        prompt_group, prompt_layout = self._make_group("Prompt Lab")
        prompt_layout.addWidget(QLabel("Provider Profile"))
        self.prompt_profile_combo = QComboBox()
        prompt_layout.addWidget(self.prompt_profile_combo)
        prompt_layout.addWidget(QLabel("Prompt"))
        self.prompt_input = QTextEdit()
        self.prompt_input.setMinimumHeight(120)
        self.prompt_input.setPlaceholderText(
            "Use configured providers for offline analysis, labeling, or OCR/DOM summarization prompts."
        )
        prompt_layout.addWidget(self.prompt_input)
        prompt_buttons = QHBoxLayout()
        run_prompt_button = QPushButton("Run Prompt")
        run_prompt_button.clicked.connect(self.run_prompt)
        prompt_buttons.addWidget(run_prompt_button)
        prompt_buttons.addStretch()
        prompt_layout.addLayout(prompt_buttons)
        self.prompt_output = QTextEdit()
        self.prompt_output.setReadOnly(True)
        self.prompt_output.setMinimumHeight(160)
        self.prompt_output.setPlainText("Prompt responses will appear here.")
        prompt_layout.addWidget(self.prompt_output)
        lower_row.addWidget(prompt_group, 2)
        root.addLayout(lower_row)

        notes_group, notes_layout = self._make_group("Health & Notes")
        self.health_notes_text = QTextEdit()
        self.health_notes_text.setReadOnly(True)
        self.health_notes_text.setMinimumHeight(140)
        self.health_notes_text.setPlainText("Health checks, refresh warnings, and operational notes will appear here.")
        notes_layout.addWidget(self.health_notes_text)
        root.addWidget(notes_group)

    def _make_group(self, title: str):
        box = QGroupBox(title)
        layout = QVBoxLayout(box)
        layout.setContentsMargins(12, 16, 12, 12)
        layout.setSpacing(8)
        return box, layout

    def set_saved_state(self, payload: dict | None):
        payload = dict(payload or {})
        self.auto_refresh_catalog = bool(payload.get("auto_refresh_catalog", False))
        self.last_category = str(payload.get("last_category", "all") or "all").strip().lower() or "all"
        self.last_search = str(payload.get("last_search", "") or "").strip()
        self.last_selected_profile = str(payload.get("last_selected_profile", "") or "").strip()
        self.catalog_auto_refresh_checkbox.setChecked(self.auto_refresh_catalog)
        index = self.catalog_category_combo.findData(self.last_category)
        if index >= 0:
            self.catalog_category_combo.setCurrentIndex(index)
        self.catalog_search_input.setText(self.last_search)
        if self.auto_refresh_catalog:
            self.refresh_catalog()
        else:
            self._reload_catalog_table()
        self._reload_profile_list(select_token=self.last_selected_profile)

    def collect_state(self) -> dict:
        return {
            "auto_refresh_catalog": self.catalog_auto_refresh_checkbox.isChecked(),
            "last_category": self.catalog_category_combo.currentData(),
            "last_search": self.catalog_search_input.text().strip(),
            "last_selected_profile": self._selected_profile_token(),
        }

    def refresh_catalog(self):
        try:
            self.catalog_payload = self.catalog_service.refresh()
        except Exception as exc:
            QMessageBox.warning(self, "Provider Hub", f"Catalog refresh failed: {exc}")
            return
        self._reload_catalog_table()
        self._set_status("Provider Hub catalog refreshed")

    def _reload_catalog_table(self):
        entries = list(self.catalog_payload.get("entries", []) or [])
        category = str(self.catalog_category_combo.currentData() or "all").strip().lower()
        needle = self.catalog_search_input.text().strip().lower()
        filtered = []
        for entry in entries:
            if category != "all" and str(entry.get("category", "")).strip().lower() != category:
                continue
            haystack = " | ".join(
                [
                    str(entry.get("name", "")),
                    str(entry.get("link", "")),
                    str(entry.get("limit_note", "")),
                    str(entry.get("notes", "")),
                    ", ".join(entry.get("models", [])),
                ]
            ).lower()
            if needle and needle not in haystack:
                continue
            filtered.append(entry)

        self.catalog_table.setRowCount(len(filtered))
        for row, entry in enumerate(filtered):
            values = [
                entry.get("name", ""),
                entry.get("category", "").title(),
                "Yes" if entry.get("signup_required") else "No",
                entry.get("limit_note", "") or "Not stated",
                "Yes" if entry.get("supports_api") else "No",
                entry.get("api_style", "") or "N/A",
                ", ".join(entry.get("models", [])) or "N/A",
                entry.get("link", ""),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                if column == 0:
                    item.setData(Qt.UserRole, dict(entry))
                self.catalog_table.setItem(row, column, item)
        self.catalog_table.resizeRowsToContents()

        api_count = sum(1 for entry in entries if entry.get("supports_api"))
        warning_count = len(list(self.catalog_payload.get("warnings", []) or []))
        self.catalog_summary_label.setText(
            f"Entries: {len(entries)} | API-capable: {api_count} | Filtered: {len(filtered)} | Warnings: {warning_count}"
        )
        sources = [str(source.get("label", "")) for source in list(self.catalog_payload.get("sources", []) or []) if source]
        self.catalog_source_label.setText("Sources: " + (", ".join(sources) if sources else "none loaded"))
        warnings = "\n".join(str(line) for line in list(self.catalog_payload.get("warnings", []) or []) if str(line).strip())
        if warnings:
            self.health_notes_text.setPlainText(warnings)
        if filtered:
            self.catalog_table.selectRow(0)
            self._update_catalog_detail()
        else:
            self.catalog_detail_text.setPlainText("No catalog entries match the current filter.")

    def _update_catalog_detail(self):
        row = self.catalog_table.currentRow()
        if row < 0:
            return
        item = self.catalog_table.item(row, 0)
        entry = dict(item.data(Qt.UserRole) or {}) if item is not None else {}
        lines = [
            entry.get("name", "Provider"),
            "",
            f"Category: {entry.get('category', '').title()}",
            f"Signup Required: {'Yes' if entry.get('signup_required') else 'No'}",
            f"Supports API: {'Yes' if entry.get('supports_api') else 'No'}",
            f"API Style: {entry.get('api_style', 'N/A') or 'N/A'}",
            f"Models: {', '.join(entry.get('models', [])) or 'N/A'}",
            f"Link: {entry.get('link', '') or 'N/A'}",
            "",
            f"Limit Note: {entry.get('limit_note', '') or 'Not stated'}",
            "",
            str(entry.get("notes", "") or "No extra notes."),
        ]
        self.catalog_detail_text.setPlainText("\n".join(lines).strip())

    def _reload_profile_list(self, select_token: str = ""):
        self.profile_list.clear()
        profiles = list(self.endpoint_profiles)
        for entry in profiles:
            label = str(entry.get("label", "Provider")).strip()
            suffix = " [enabled]" if entry.get("enabled") else ""
            item = QListWidgetItem(f"{label}{suffix}")
            item.setData(Qt.UserRole, dict(entry))
            self.profile_list.addItem(item)
        self.endpoint_summary_label.setText(
            f"Configured endpoints: {len(profiles)} | Enabled: {sum(1 for entry in profiles if entry.get('enabled'))}"
        )
        self._reload_prompt_profiles()
        if profiles:
            index = 0
            if select_token:
                for row in range(self.profile_list.count()):
                    item = self.profile_list.item(row)
                    entry = dict(item.data(Qt.UserRole) or {})
                    if str(entry.get("token", "")) == select_token:
                        index = row
                        break
            self.profile_list.setCurrentRow(index)
            self._on_profile_selected(index)
        else:
            self._clear_profile_form()

    def _reload_prompt_profiles(self):
        current_token = self._selected_prompt_profile_token()
        self.prompt_profile_combo.blockSignals(True)
        self.prompt_profile_combo.clear()
        for entry in self.endpoint_profiles:
            self.prompt_profile_combo.addItem(str(entry.get("label", "Provider")), dict(entry))
        self.prompt_profile_combo.blockSignals(False)
        if current_token:
            for index in range(self.prompt_profile_combo.count()):
                payload = dict(self.prompt_profile_combo.itemData(index) or {})
                if str(payload.get("token", "")) == current_token:
                    self.prompt_profile_combo.setCurrentIndex(index)
                    break

    def _clear_profile_form(self):
        self.profile_label_input.setText("")
        self.profile_base_url_input.setText("")
        self.profile_api_env_input.setText("")
        self.profile_models_input.setText("")
        self.profile_notes_input.setPlainText("")
        self.profile_enabled_checkbox.setChecked(False)
        self.profile_api_style_combo.setCurrentIndex(0)

    def _on_profile_selected(self, row: int):
        if row < 0 or row >= self.profile_list.count():
            self._clear_profile_form()
            return
        item = self.profile_list.item(row)
        payload = dict(item.data(Qt.UserRole) or {})
        self.profile_label_input.setText(str(payload.get("label", "")))
        self.profile_base_url_input.setText(str(payload.get("base_url", "")))
        self.profile_api_env_input.setText(str(payload.get("api_key_env_var", "")))
        self.profile_models_input.setText(", ".join(payload.get("models", [])))
        self.profile_notes_input.setPlainText(str(payload.get("notes", "")))
        self.profile_enabled_checkbox.setChecked(bool(payload.get("enabled")))
        index = self.profile_api_style_combo.findData(str(payload.get("api_style", "openai_chat")))
        self.profile_api_style_combo.setCurrentIndex(max(0, index))
        self.last_selected_profile = str(payload.get("token", ""))

    def save_profile(self):
        label = self.profile_label_input.text().strip()
        base_url = self.profile_base_url_input.text().strip()
        if not label or not base_url:
            QMessageBox.information(self, "Provider Hub", "Profile label and base URL are required.")
            return
        validation = validate_endpoint_profile_config(
            {
                "base_url": base_url,
                "api_key_env_var": self.profile_api_env_input.text().strip(),
            }
        )
        if not validation.get("ok"):
            QMessageBox.warning(self, "Provider Hub", str(validation.get("error") or "Provider profile is invalid."))
            return
        payload = {
            "label": label,
            "base_url": str(validation.get("normalized_base_url") or base_url),
            "api_key_env_var": str(validation.get("normalized_api_key_env_var") or ""),
            "api_style": self.profile_api_style_combo.currentData(),
            "models": [value.strip() for value in self.profile_models_input.text().split(",") if value.strip()],
            "enabled": self.profile_enabled_checkbox.isChecked(),
            "notes": self.profile_notes_input.toPlainText().strip(),
        }
        normalized = self.catalog_service._normalize_profile(payload)
        token = normalized["token"]
        replaced = False
        for index, entry in enumerate(list(self.endpoint_profiles)):
            if str(entry.get("token", "")) == token:
                self.endpoint_profiles[index] = normalized
                replaced = True
                break
        if not replaced:
            self.endpoint_profiles.append(normalized)
        self.endpoint_profiles.sort(key=lambda item: str(item.get("label", "")).lower())
        self.catalog_service.save_endpoint_profiles(self.endpoint_profiles)
        self._reload_profile_list(select_token=token)
        self._set_status(f"Saved provider profile: {label}")

    def delete_profile(self):
        token = self._selected_profile_token()
        if not token:
            QMessageBox.information(self, "Provider Hub", "Select a profile to delete.")
            return
        self.endpoint_profiles = [entry for entry in self.endpoint_profiles if str(entry.get("token", "")) != token]
        self.catalog_service.save_endpoint_profiles(self.endpoint_profiles)
        self._reload_profile_list()
        self._set_status("Provider profile deleted")

    def check_selected_profile(self):
        profile = self._selected_profile()
        if not profile:
            QMessageBox.information(self, "Provider Hub", "Select a provider profile first.")
            return
        result = self.provider_client.check_health(profile)
        token = str(profile.get("token", ""))
        for entry in self.endpoint_profiles:
            if str(entry.get("token", "")) == token:
                entry["last_status"] = str(result.get("status", ""))
                entry["last_latency_ms"] = float(result.get("latency_ms", 0.0) or 0.0)
                break
        self.catalog_service.save_endpoint_profiles(self.endpoint_profiles)
        self._reload_profile_list(select_token=token)
        self.health_notes_text.setPlainText(
            f"Health Check: {'OK' if result.get('ok') else 'Failed'}\n"
            f"Status: {result.get('status', 'Unknown')}\n"
            f"Latency: {float(result.get('latency_ms', 0.0) or 0.0):.1f} ms"
        )
        self._set_status(f"Provider health checked: {profile.get('label', 'Provider')}")

    def run_prompt(self):
        profile = self._selected_prompt_profile()
        if not profile:
            QMessageBox.information(self, "Provider Hub", "Select a configured provider profile first.")
            return
        prompt = self.prompt_input.toPlainText().strip()
        if not prompt:
            QMessageBox.information(self, "Provider Hub", "Enter a prompt first.")
            return
        result = self.provider_client.run_prompt(profile, prompt)
        token = str(profile.get("token", ""))
        for entry in self.endpoint_profiles:
            if str(entry.get("token", "")) == token:
                entry["last_status"] = "Prompt OK" if result.get("ok") else f"Prompt failed: {result.get('error', 'Unknown')}"
                entry["last_latency_ms"] = float(result.get("latency_ms", 0.0) or 0.0)
                break
        self.catalog_service.save_endpoint_profiles(self.endpoint_profiles)
        self._reload_profile_list(select_token=token)
        if result.get("ok"):
            self.prompt_output.setPlainText(str(result.get("output_text", "") or "").strip() or "No output text.")
            self.health_notes_text.setPlainText(
                f"Prompt completed via {profile.get('label', 'Provider')} in {float(result.get('latency_ms', 0.0)):.1f} ms."
            )
            self._set_status(f"Prompt completed: {profile.get('label', 'Provider')}")
            return
        self.prompt_output.setPlainText(str(result.get("error", "Prompt failed.")))
        self.health_notes_text.setPlainText(str(result.get("error", "Prompt failed.")))
        self._set_status(f"Prompt failed: {profile.get('label', 'Provider')}")

    def _selected_profile(self) -> dict:
        row = self.profile_list.currentRow()
        if row < 0 or row >= self.profile_list.count():
            return {}
        item = self.profile_list.item(row)
        return dict(item.data(Qt.UserRole) or {})

    def _selected_profile_token(self) -> str:
        return str(self._selected_profile().get("token", ""))

    def _selected_prompt_profile(self) -> dict:
        return dict(self.prompt_profile_combo.currentData() or {})

    def _selected_prompt_profile_token(self) -> str:
        return str(self._selected_prompt_profile().get("token", ""))

    def _on_catalog_filters_changed(self, *_args):
        self._reload_catalog_table()

    def _on_auto_refresh_toggled(self, checked: bool):
        self.auto_refresh_catalog = bool(checked)

    def _set_status(self, message: str):
        if callable(self.status_callback):
            try:
                self.status_callback(message)
                return
            except Exception:
                pass
