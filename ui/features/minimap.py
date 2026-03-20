from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget


class MiniMap(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap = QPixmap()
        self._scene_rect = QRectF()
        self._viewport_rect = QRectF()
        self._colors = {
            "background": QColor("#07101f"),
            "border": QColor("#334155"),
            "accent": QColor("#38bdf8"),
            "empty": QColor("#94a3b8"),
        }
        self.setMinimumHeight(220)

    def apply_theme(self, colors: dict):
        self._colors = {
            "background": QColor(colors["field"]),
            "border": QColor(colors["field_border"]),
            "accent": QColor(colors["accent"]),
            "empty": QColor(colors["button_fg"]),
        }
        self.update()

    def set_snapshot(self, pixmap: QPixmap, scene_rect: QRectF, viewport_rect: QRectF):
        self._pixmap = pixmap
        self._scene_rect = QRectF(scene_rect)
        self._viewport_rect = QRectF(viewport_rect)
        self.update()

    def clear_snapshot(self):
        self._pixmap = QPixmap()
        self._scene_rect = QRectF()
        self._viewport_rect = QRectF()
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), self._colors["background"])

        content_rect = self.rect().adjusted(10, 10, -10, -10)
        painter.setPen(QPen(self._colors["border"], 1.5))
        painter.drawRoundedRect(content_rect, 10, 10)

        if self._pixmap.isNull():
            painter.setPen(self._colors["empty"])
            painter.drawText(content_rect, Qt.AlignCenter, "Minimap Preview")
            return

        scaled = self._pixmap.scaled(
            content_rect.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        draw_rect = QRectF(0, 0, scaled.width(), scaled.height())
        draw_rect.moveCenter(content_rect.center())
        painter.drawPixmap(draw_rect.topLeft().toPoint(), scaled)

        if self._scene_rect.width() <= 0 or self._scene_rect.height() <= 0:
            return
        if self._viewport_rect.width() <= 0 or self._viewport_rect.height() <= 0:
            return

        scale_x = draw_rect.width() / self._scene_rect.width()
        scale_y = draw_rect.height() / self._scene_rect.height()
        viewport = QRectF(
            draw_rect.left() + (self._viewport_rect.left() - self._scene_rect.left()) * scale_x,
            draw_rect.top() + (self._viewport_rect.top() - self._scene_rect.top()) * scale_y,
            self._viewport_rect.width() * scale_x,
            self._viewport_rect.height() * scale_y,
        )
        painter.setPen(QPen(self._colors["accent"], 2))
        painter.drawRoundedRect(viewport, 6, 6)
