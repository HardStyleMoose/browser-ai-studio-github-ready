from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout


class VisionDebugPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Vision Debug Panel"))
