import json
from PySide6.QtWidgets import QFileDialog

class ExportImportManager:
    @staticmethod
    def export_graph(graph_data, parent):
        file_path, _ = QFileDialog.getSaveFileName(parent, "Export Workflow", "", "JSON Files (*.json)")
        if file_path:
            with open(file_path, 'w') as f:
                json.dump(graph_data, f, indent=2)

    @staticmethod
    def import_graph(parent):
        file_path, _ = QFileDialog.getOpenFileName(parent, "Import Workflow", "", "JSON Files (*.json)")
        if file_path:
            with open(file_path, 'r') as f:
                return json.load(f)
        return None
