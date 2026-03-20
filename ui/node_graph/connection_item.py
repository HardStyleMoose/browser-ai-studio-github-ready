from __future__ import annotations

import math

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsPathItem


class ConnectionItem(QGraphicsPathItem):
    def __init__(self, start_socket, end_socket):
        super().__init__()
        self.start_socket = start_socket
        self.end_socket = end_socket
        self.branch_type = self._infer_branch_type()
        self.arrow_points = []

        self.setZValue(-1)
        self.setFlag(self.GraphicsItemFlag.ItemIsSelectable, True)
        self.setAcceptHoverEvents(True)
        self.setPen(self._make_pen())

        self.start_socket.add_connection(self)
        self.end_socket.add_connection(self)
        self.update_path()

    def _infer_branch_type(self):
        parent = self.start_socket.parentItem()
        if parent is None or not hasattr(parent, "node_type"):
            return None
        if parent.node_type == "condition":
            if self.start_socket.index == 0:
                return "true"
            if self.start_socket.index == 1:
                return "false"
        if parent.node_type == "loop":
            return "loop"
        return None

    def _make_pen(self):
        if self.branch_type == "true":
            return QPen(QColor("#22c55e"), 2.6)
        if self.branch_type == "false":
            return QPen(QColor("#ef4444"), 2.6)
        if self.branch_type == "loop":
            pen = QPen(QColor("#f59e42"), 2.2)
            pen.setStyle(Qt.DashLine)
            return pen
        return QPen(QColor("#94a3b8"), 2.2)

    def hoverEnterEvent(self, event):
        self.setPen(QPen(QColor("#f8fafc"), 3))
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.setPen(self._make_pen())
        super().hoverLeaveEvent(event)

    def mouseDoubleClickEvent(self, event):
        self.disconnect()
        if self.scene() is not None:
            self.scene().removeItem(self)
        super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event):
        from ui.node_graph.node_item import NodeItem

        scene_pos = event.scenePos()
        nearest_socket = None
        min_distance = float("inf")
        for item in self.scene().items():
            if isinstance(item, NodeItem):
                for socket in item.input_sockets:
                    distance = (socket.center_in_scene() - scene_pos).manhattanLength()
                    if distance < 32 and distance < min_distance:
                        min_distance = distance
                        nearest_socket = socket
        if nearest_socket and nearest_socket != self.end_socket:
            self.end_socket.remove_connection(self)
            self.end_socket = nearest_socket
            self.end_socket.add_connection(self)
            self.update_path()
        super().mouseMoveEvent(event)

    def update_path(self):
        start = self.start_socket.center_in_scene()
        end = self.end_socket.center_in_scene()
        dx = max(60.0, abs(end.x() - start.x()) * 0.5)

        path = QPainterPath(start)
        path.cubicTo(
            QPointF(start.x() + dx, start.y()),
            QPointF(end.x() - dx, end.y()),
            end,
        )
        self.setPath(path)

        self.arrow_points = []
        if start != end:
            angle = math.atan2(end.y() - start.y(), end.x() - start.x())
            arrow_size = 14
            p1 = end
            p2 = QPointF(
                end.x() - arrow_size * math.cos(angle - math.pi / 7),
                end.y() - arrow_size * math.sin(angle - math.pi / 7),
            )
            p3 = QPointF(
                end.x() - arrow_size * math.cos(angle + math.pi / 7),
                end.y() - arrow_size * math.sin(angle + math.pi / 7),
            )
            self.arrow_points = [p1, p2, p3]

    def paint(self, painter, option, widget=None):
        super().paint(painter, option, widget)
        if not self.arrow_points:
            return

        if self.branch_type == "true":
            color = QColor("#22c55e")
        elif self.branch_type == "false":
            color = QColor("#ef4444")
        elif self.branch_type == "loop":
            color = QColor("#f59e42")
        else:
            color = QColor("#94a3b8")

        painter.setBrush(color)
        painter.setPen(QPen(color, 1.5))
        painter.drawPolygon(self.arrow_points)

    def disconnect(self):
        self.start_socket.remove_connection(self)
        self.end_socket.remove_connection(self)
