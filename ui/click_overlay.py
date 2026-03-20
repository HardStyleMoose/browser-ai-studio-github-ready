from PySide6.QtWidgets import QWidget
from PySide6.QtGui import QGuiApplication, QPainter, QColor
from PySide6.QtCore import Qt, QTimer

class ClickOverlay(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.circle_pos = None
        self.circle_visible = False
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.hide_circle)
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            self.setGeometry(screen.geometry())
        else:
            self.resize(1920, 1080)

    def show_circle(self, x, y, duration=500):
        self.circle_pos = (x, y)
        self.circle_visible = True
        self.show()
        self.raise_()
        self.repaint()
        self.timer.start(duration)

    def hide_circle(self):
        self.circle_visible = False
        self.circle_pos = None
        self.repaint()
        self.timer.stop()
        self.hide()

    def paintEvent(self, event):
        if self.circle_visible and self.circle_pos:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing)
            color = QColor(0, 0, 0, 128)  # Semi-transparent black
            painter.setBrush(color)
            painter.setPen(Qt.NoPen)
            x, y = self.circle_pos
            radius = 40
            painter.drawEllipse(x - radius, y - radius, radius * 2, radius * 2)
