from PySide6.QtCore import QPropertyAnimation, QRectF
from PySide6.QtWidgets import QGraphicsRectItem

class AnimatedBlock(QGraphicsRectItem):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.animation = QPropertyAnimation(self, b"geometry")
        self.animation.setDuration(300)

    def animate_to(self, rect: QRectF):
        self.animation.setStartValue(self.rect())
        self.animation.setEndValue(rect)
        self.animation.start()
