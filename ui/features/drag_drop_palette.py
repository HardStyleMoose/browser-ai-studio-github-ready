from PySide6.QtWidgets import QWidget, QVBoxLayout, QPushButton
from PySide6.QtCore import Qt

class DragDropPalette(QWidget):
    def __init__(self, node_types, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setFixedSize(120, 320)
        layout = QVBoxLayout(self)
        for node_type in node_types:
            btn = QPushButton(node_type)
            btn.setStyleSheet("background: #38bdf8; color: #0f172a; border-radius: 6px; margin: 4px;")
            btn.setFixedHeight(32)
            layout.addWidget(btn)
            btn.setDragEnabled = True  # Placeholder for drag logic
        self.setStyleSheet("background: #f8fafc; border-radius: 8px;")
