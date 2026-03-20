from __future__ import annotations

import json
import os
import shutil
import time
from datetime import datetime

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QApplication, QFileDialog, QListWidget, QMessageBox, QVBoxLayout, QWidget, QDialog, QLabel, QPushButton

from ui.click_overlay import ClickOverlay
from ui.node_editor import NodeEditor


class BehaviorEditor(QWidget):
    def __init__(self, click_overlay=None):
        super().__init__()
        self.click_overlay = click_overlay or ClickOverlay()
        self.node_editor = NodeEditor(click_overlay=self.click_overlay)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.node_editor)

        self._sim_paused = False
        self._sim_step = False
        self.simulate_mode = False

        self.node_editor.set_action_handler("apply", self.apply_behavior_to_ai)
        self.node_editor.set_action_handler("save", self.save_behavior)
        self.node_editor.set_action_handler("load", self.load_behavior)
        self.node_editor.set_action_handler("history", self.show_history_dialog)
        self.node_editor.set_action_handler("simulate", self.toggle_simulate_mode)
        self.node_editor.set_action_handler("step", self._step_sim)
        self.node_editor.set_action_handler("pause", self._pause_sim)
        self.node_editor.set_action_handler("resume", self._resume_sim)
        self.set_theme("terminal")

    def _step_sim(self):
        self._sim_step = True
        self._sim_paused = False
        self.log("Simulation stepped.")

    def _pause_sim(self):
        self._sim_paused = True
        self.log("Simulation paused.")

    def _resume_sim(self):
        self._sim_paused = False
        self.log("Simulation resumed.")

    def log(self, message: str):
        self.node_editor.append_log(message)

    def apply_behavior_to_ai(self, _=None):
        self.log("Behavior applied to AI.")

    def get_behavior_graph(self):
        return self.node_editor.to_legacy_graph()

    def highlight_block(self, block_id, active=True):
        self.node_editor.highlight_node(block_id, active)

    def simulate_behavior_blocks(self, behavior_blocks, game_state=None):
        self.node_editor.clear_log()
        self.node_editor.append_log("Simulation started...")

        for block_id, block in behavior_blocks.items():
            self.highlight_block(block_id, active=True)
            self.log(f"Executing block: {block_id} ({block.get('type', 'unknown')})")
            if block.get("type") == "action":
                target = block.get("target")
                if isinstance(target, (tuple, list)) and len(target) == 2:
                    self.click_overlay.show_circle(target[0], target[1], duration=700)
                    self.log(f"Action target: {target[0]}, {target[1]}")
            elif block.get("type") == "state":
                self.log(f"Condition: {block.get('condition', 'True')}")

            while self._sim_paused and not self._sim_step:
                QApplication.processEvents()
                time.sleep(0.1)
            self._sim_step = False
            QApplication.processEvents()
            time.sleep(0.3)
            self.highlight_block(block_id, active=False)
            QApplication.processEvents()

        self.node_editor.append_log("Simulation finished.")

    def save_behavior(self, _=None):
        filename, _ = QFileDialog.getSaveFileName(self, "Save Behavior", "", "JSON Files (*.json)")
        if not filename:
            return

        if os.path.exists(filename):
            versions_dir = os.path.join(os.path.dirname(filename), ".versions")
            os.makedirs(versions_dir, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            version_name = f"{os.path.basename(filename)}.{timestamp}.json"
            shutil.copy2(filename, os.path.join(versions_dir, version_name))

        self.node_editor.save_to_file(filename)
        self.log(f"Saved behavior to {filename}")

    def load_behavior_from_file(self, filename: str):
        with open(filename, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        self.node_editor.set_graph(payload)
        self.log(f"Loaded behavior from {filename}")

    def load_behavior(self, _=None):
        filename, _ = QFileDialog.getOpenFileName(self, "Load Behavior", "", "JSON Files (*.json)")
        if filename:
            self.load_behavior_from_file(filename)

    def show_history_dialog(self, _=None):
        filename, _ = QFileDialog.getOpenFileName(self, "Select Behavior File For History", "", "JSON Files (*.json)")
        if not filename:
            return

        versions_dir = os.path.join(os.path.dirname(filename), ".versions")
        base = os.path.basename(filename)
        versions = []
        if os.path.isdir(versions_dir):
            for item in os.listdir(versions_dir):
                if item.startswith(base + ".") and item.endswith(".json"):
                    versions.append(item)
        versions.sort(reverse=True)

        dialog = QDialog(self)
        dialog.setWindowTitle("Version History")
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(f"History for: {base}"))
        list_widget = QListWidget()
        for version in versions:
            list_widget.addItem(version)
        layout.addWidget(list_widget)
        restore_btn = QPushButton("Restore Selected Version")
        layout.addWidget(restore_btn)

        def restore():
            selected = list_widget.currentItem()
            if selected is None:
                QMessageBox.warning(dialog, "No Selection", "Select a version to restore.")
                return
            version_path = os.path.join(versions_dir, selected.text())
            shutil.copy2(version_path, filename)
            self.load_behavior_from_file(filename)
            dialog.accept()

        restore_btn.clicked.connect(restore)
        dialog.exec()

    def copy_selected(self):
        self.node_editor.copy_selected()

    def paste_blocks(self):
        self.node_editor.paste_copied()

    def toggle_simulate_mode(self, _=None):
        self.simulate_mode = not self.simulate_mode
        self.node_editor.set_simulate_mode(self.simulate_mode)
        self.log(f"Simulate mode {'enabled' if self.simulate_mode else 'disabled'}.")
        if self.simulate_mode:
            self.simulate_behavior_blocks(self.get_behavior_graph())

    def set_theme(self, theme_name: str):
        self.node_editor.apply_theme(theme_name)

    def minimumSizeHint(self):
        return QSize(540, 420)

    def sizeHint(self):
        return QSize(1120, 720)
