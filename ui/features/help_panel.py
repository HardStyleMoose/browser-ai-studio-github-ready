from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout

class HelpPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        help_text = QLabel(
            "<b>Help:</b>\n"
            "- Drag blocks from palette\n"
            "- Right-click to pan\n"
            "- Mouse wheel to zoom\n"
            "- Double-click connection to delete\n"
            "- Hover blocks for preview\n"
            "- Use toolbar for actions\n"
            "- Undo/Redo with Ctrl+Z/Ctrl+Y\n"
            "- Export/Import workflows"
        )
        help_text.setStyleSheet("color:#f8fafc;background:#22304a;padding:4px;")
        layout.addWidget(help_text)
        self.setStyleSheet("background: #22304a; border-radius: 8px;")
