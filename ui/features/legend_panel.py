from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout

class LegendPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        legend = QLabel(
            "<b>Legend:</b> "
            "<span style='color:#22c55e;'>Green</span>=True branch, "
            "<span style='color:#ef4444;'>Red</span>=False branch, "
            "<span style='color:#f59e42;'>Orange dashed</span>=Loop, "
            "\u27f3=Loop node"
        )
        legend.setStyleSheet("color:#f8fafc;background:#0f172a;padding:4px;")
        layout.addWidget(legend)
        self.setStyleSheet("background: #22304a; border-radius: 8px;")
