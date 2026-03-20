from PySide6.QtWidgets import QWidget, QApplication
from PySide6.QtCore import Qt, QRect, QPoint
from PySide6.QtGui import QPainter, QPen, QColor

class RegionSelectorOverlay(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.start_point = None
        self.end_point = None
        self.selected_rect = None
        self.setCursor(Qt.CrossCursor)
        self.showFullScreen()
        self.setFocusPolicy(Qt.StrongFocus)
    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.selected_rect = None
            self.close()
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.start_point = event.pos()
            self.end_point = event.pos()
            self.update()

    def mouseMoveEvent(self, event):
        if self.start_point:
            self.end_point = event.pos()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.start_point:
            self.end_point = event.pos()
            self.selected_rect = QRect(self.start_point, self.end_point).normalized()
            self.close()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 80))
        if self.start_point and self.end_point:
            rect = QRect(self.start_point, self.end_point).normalized()
            pen = QPen(QColor(0, 255, 0), 2)
            painter.setPen(pen)
            painter.drawRect(rect)

    def get_selected_region(self):
        if self.selected_rect:
            return (self.selected_rect.x(), self.selected_rect.y(), self.selected_rect.width(), self.selected_rect.height())
        return None
