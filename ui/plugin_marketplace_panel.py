from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton, QListWidget, QHBoxLayout, QTextEdit, QLineEdit, QFileDialog, QMessageBox
import os
import json

class PluginMarketplacePanel(QWidget):
    def __init__(self, plugins_dir="plugins/"):
        super().__init__()
        self.plugins_dir = plugins_dir
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Plugin Marketplace"))
        self.plugin_list = QListWidget()
        layout.addWidget(self.plugin_list)
        btns = QHBoxLayout()
        self.install_btn = QPushButton("Install Plugin")
        self.remove_btn = QPushButton("Remove Plugin")
        self.import_btn = QPushButton("Import Plugin File")
        self.export_btn = QPushButton("Export Plugin File")
        btns.addWidget(self.install_btn)
        btns.addWidget(self.remove_btn)
        btns.addWidget(self.import_btn)
        btns.addWidget(self.export_btn)
        layout.addLayout(btns)
        self.install_btn.clicked.connect(self.install_plugin)
        self.remove_btn.clicked.connect(self.remove_plugin)
        self.import_btn.clicked.connect(self.import_plugin)
        self.export_btn.clicked.connect(self.export_plugin)
        self.plugin_list.currentTextChanged.connect(self.display_plugin_info)
        self.info_box = QTextEdit()
        self.info_box.setReadOnly(True)
        layout.addWidget(self.info_box)
        self.refresh_plugins()

        # Real-time refresh timer for plugin list/info
        from PySide6.QtCore import QTimer
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(1000)  # 1 second
        self.refresh_timer.timeout.connect(self._refresh_plugins_info)
        self.refresh_timer.start()

    def _refresh_plugins_info(self):
        self.refresh_plugins()
        # Optionally refresh info box for currently selected plugin
        plugin_file = self.plugin_list.currentItem().text() if self.plugin_list.currentItem() else None
        if plugin_file:
            self.display_plugin_info(plugin_file)

    def refresh_plugins(self):
        self.plugin_list.clear()
        if os.path.exists(self.plugins_dir):
            for f in os.listdir(self.plugins_dir):
                if f.endswith(".py") and f != "__init__.py":
                    self.plugin_list.addItem(f)

    def display_plugin_info(self, plugin_file):
        if not plugin_file:
            self.info_box.clear()
            return
        path = os.path.join(self.plugins_dir, plugin_file)
        try:
            with open(path, "r", encoding="utf-8") as f:
                code = f.read()
            # Try to extract plugin metadata
            name = self._extract_metadata(code, "name")
            desc = self._extract_metadata(code, "description")
            version = self._extract_metadata(code, "version")
            info = f"Name: {name}\nVersion: {version}\nDescription: {desc}\n\n---\n{code[:500]}..."
            self.info_box.setPlainText(info)
        except Exception as e:
            self.info_box.setPlainText(f"Error reading plugin: {e}")

    def _extract_metadata(self, code, key):
        import re
        match = re.search(rf"{key}\s*=\s*['\"]([^'\"]+)['\"]", code)
        return match.group(1) if match else "Unknown"

    def install_plugin(self):
        plugin_file = self.plugin_list.currentItem().text() if self.plugin_list.currentItem() else None
        if not plugin_file:
            return
        QMessageBox.information(self, "Install Plugin", f"Plugin '{plugin_file}' is already installed.")

    def remove_plugin(self):
        plugin_file = self.plugin_list.currentItem().text() if self.plugin_list.currentItem() else None
        if not plugin_file:
            return
        path = os.path.join(self.plugins_dir, plugin_file)
        try:
            os.remove(path)
            self.refresh_plugins()
            QMessageBox.information(self, "Remove Plugin", f"Plugin '{plugin_file}' removed.")
        except Exception as e:
            QMessageBox.warning(self, "Remove Plugin", f"Failed to remove: {e}")

    def import_plugin(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Import Plugin File", "", "Python Files (*.py)")
        if filename:
            dest = os.path.join(self.plugins_dir, os.path.basename(filename))
            try:
                with open(filename, "r", encoding="utf-8") as src, open(dest, "w", encoding="utf-8") as dst:
                    dst.write(src.read())
                self.refresh_plugins()
                QMessageBox.information(self, "Import Plugin", f"Plugin imported: {os.path.basename(filename)}")
            except Exception as e:
                QMessageBox.warning(self, "Import Plugin", f"Failed to import: {e}")

    def export_plugin(self):
        plugin_file = self.plugin_list.currentItem().text() if self.plugin_list.currentItem() else None
        if not plugin_file:
            return
        filename, _ = QFileDialog.getSaveFileName(self, "Export Plugin File", plugin_file, "Python Files (*.py)")
        if filename:
            src = os.path.join(self.plugins_dir, plugin_file)
            try:
                with open(src, "r", encoding="utf-8") as s, open(filename, "w", encoding="utf-8") as d:
                    d.write(s.read())
                QMessageBox.information(self, "Export Plugin", f"Plugin exported: {os.path.basename(filename)}")
            except Exception as e:
                QMessageBox.warning(self, "Export Plugin", f"Failed to export: {e}")
