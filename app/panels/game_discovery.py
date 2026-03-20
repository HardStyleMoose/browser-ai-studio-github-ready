from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout


class GameDiscoveryPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Game Discovery Panel"))
