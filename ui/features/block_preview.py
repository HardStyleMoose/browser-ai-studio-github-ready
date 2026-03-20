from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout
from PySide6.QtCore import Qt

class BlockPreview(QWidget):
    def __init__(self, block_config, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setFixedSize(220, 120)
        layout = QVBoxLayout(self)
        self.label = QLabel(f"Preview: {block_config}")
        layout.addWidget(self.label)
        self.setStyleSheet("background: #22304a; color: #f8fafc; border-radius: 8px;")

    def update_preview(self, block_config):
        self.label.setText(f"Preview: {block_config}")
