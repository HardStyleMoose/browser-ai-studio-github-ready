from PySide6.QtWidgets import QGraphicsLineItem
from PySide6.QtGui import QPen, QColor

class AlignmentGuide(QGraphicsLineItem):
    def __init__(self, x1, y1, x2, y2):
        super().__init__(x1, y1, x2, y2)
        self.setPen(QPen(QColor("#38bdf8"), 2, ))
        self.setZValue(100)

class AlignmentGuidesManager:
    def __init__(self, scene):
        self.scene = scene
        self.guides = []

    def show_guides(self, positions):
        self.clear_guides()
        for (x1, y1, x2, y2) in positions:
            guide = AlignmentGuide(x1, y1, x2, y2)
            self.scene.addItem(guide)
            self.guides.append(guide)

    def clear_guides(self):
        for guide in self.guides:
            self.scene.removeItem(guide)
        self.guides.clear()
