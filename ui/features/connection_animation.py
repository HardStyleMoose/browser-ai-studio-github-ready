from PySide6.QtCore import QPropertyAnimation
from PySide6.QtGui import QPen, QColor
from PySide6.QtWidgets import QGraphicsPathItem

class AnimatedConnection(QGraphicsPathItem):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.animation = QPropertyAnimation(self, b"opacity")
        self.animation.setDuration(400)
        self.setPen(QPen(QColor("#38bdf8"), 2.6))

    def animate(self):
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)
        self.animation.start()
