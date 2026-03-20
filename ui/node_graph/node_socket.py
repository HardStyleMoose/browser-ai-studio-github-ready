from __future__ import annotations

from PySide6.QtCore import QRectF
from PySide6.QtGui import QBrush, QColor, QPen
from PySide6.QtWidgets import QGraphicsEllipseItem


class NodeSocket(QGraphicsEllipseItem):
    def __init__(self, parent, socket_role: str, index: int):
        super().__init__(-6, -6, 12, 12, parent)
        self.socket_role = socket_role
        self.index = index
        self.connections = []

        fill = QColor("#58c4dd") if socket_role == "input" else QColor("#f4b860")
        self.setBrush(QBrush(fill))
        self.setPen(QPen(QColor("#1f2937"), 1.5))

    def center_in_scene(self):
        return self.mapToScene(QRectF(self.rect()).center())

    def add_connection(self, connection):
        if connection not in self.connections:
            self.connections.append(connection)

    def remove_connection(self, connection):
        if connection in self.connections:
            self.connections.remove(connection)
