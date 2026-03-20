from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPen
from PySide6.QtWidgets import QGraphicsItem, QGraphicsRectItem, QGraphicsSimpleTextItem, QInputDialog, QMenu

from ui.node_graph.node_socket import NodeSocket


class NodeItem(QGraphicsRectItem):
    WIDTH = 180
    HEADER_HEIGHT = 32
    BODY_HEIGHT = 92

    def __init__(self, node_id: str, node_type: str, title: str, color: str, config=None, inputs: int = 1, outputs: int = 1):
        super().__init__(0, 0, self.WIDTH, self.HEADER_HEIGHT + self.BODY_HEIGHT)
        self.node_id = node_id
        self.node_type = node_type
        self.title = title
        self.config = config or {}
        self.header_color = QColor(color)

        self._resizing = False
        self._resize_start = None
        self._resize_rect_start = None

        self._apply_type_style()
        self.setAcceptHoverEvents(True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)

        self.header = QGraphicsRectItem(0, 0, self.WIDTH, self.HEADER_HEIGHT, self)
        self.header.setBrush(QBrush(self.header_color))
        self.header.setPen(QPen(Qt.PenStyle.NoPen))

        self.title_item = QGraphicsSimpleTextItem(title, self)
        title_font = QFont()
        title_font.setPointSize(12)
        title_font.setBold(True)
        self.title_item.setFont(title_font)
        self.title_item.setBrush(QBrush(QColor("#f8fafc")))
        self.title_item.setPos(10, 7)

        self.subtitle_item = QGraphicsSimpleTextItem(node_type.upper(), self)
        subtitle_font = QFont()
        subtitle_font.setPointSize(10)
        self.subtitle_item.setFont(subtitle_font)
        self.subtitle_item.setBrush(QBrush(QColor("#94a3b8")))
        self.subtitle_item.setPos(10, 44)

        self.summary_item = QGraphicsSimpleTextItem(self._summarize_config(), self)
        summary_font = QFont()
        summary_font.setPointSize(9)
        self.summary_item.setFont(summary_font)
        self.summary_item.setBrush(QBrush(QColor("#cbd5e1")))
        self.summary_item.setPos(10, 68)

        self.input_sockets = self._build_sockets("input", inputs)
        self.output_sockets = self._build_sockets("output", outputs)

    def _apply_type_style(self):
        if self.node_type == "action":
            self.setBrush(QBrush(QColor("#1e293b")))
            self.setPen(QPen(QColor("#2563eb"), 2.2))
        elif self.node_type == "condition":
            self.setBrush(QBrush(QColor("#052e16")))
            self.setPen(QPen(QColor("#059669"), 2.2))
        elif self.node_type == "wait":
            self.setBrush(QBrush(QColor("#2e1065")))
            self.setPen(QPen(QColor("#7c3aed"), 2.2))
        elif self.node_type == "loop":
            self.setBrush(QBrush(QColor("#431407")))
            self.setPen(QPen(QColor("#ea580c"), 2.2))
            self.loop_label = QGraphicsSimpleTextItem("↻", self)
            self.loop_label.setBrush(QBrush(QColor("#f59e42")))
            self.loop_label.setPos(self.WIDTH - 28, 8)
        elif self.node_type in ("sequence", "selector"):
            self.setBrush(QBrush(QColor("#431407")))
            self.setPen(QPen(QColor("#ea580c"), 2.2))
        else:
            self.setBrush(QBrush(QColor("#111827")))
            self.setPen(QPen(QColor("#334155"), 1.2))

    def contextMenuEvent(self, event):
        menu = QMenu()
        rename_action = menu.addAction("Rename Block")
        action = menu.exec(event.screenPos())
        if action == rename_action:
            new_title, ok = QInputDialog.getText(None, "Rename Block", "New block name:", text=self.title)
            if ok and new_title:
                self.title = new_title
                self.title_item.setText(new_title)

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            event.ignore()
            return
        margin = 8
        rect = self.rect()
        if abs(event.pos().x() - rect.right()) < margin or abs(event.pos().y() - rect.bottom()) < margin:
            self._resizing = True
            self._resize_start = event.pos()
            self._resize_rect_start = rect
        else:
            self._resizing = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._resizing:
            dx = event.pos().x() - self._resize_start.x()
            dy = event.pos().y() - self._resize_start.y()
            new_width = max(self.WIDTH, self._resize_rect_start.width() + dx)
            new_height = max(self.HEADER_HEIGHT + self.BODY_HEIGHT, self._resize_rect_start.height() + dy)
            self.setRect(0, 0, new_width, new_height)
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._resizing = False
        super().mouseReleaseEvent(event)

    def paint(self, painter, option, widget=None):
        rect = self.rect()

        painter.save()
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 60))
        painter.drawRoundedRect(rect.translated(4, 4), 18, 18)
        painter.restore()

        painter.setBrush(self.brush())
        painter.setPen(self.pen())
        if self.node_type == "condition":
            painter.drawEllipse(rect)
        else:
            painter.drawRoundedRect(rect, 16, 16)

        if self.isSelected():
            painter.setPen(QPen(QColor("#f59e42"), 3, Qt.DashLine))
            painter.drawRoundedRect(rect, 16, 16)

    def _build_sockets(self, socket_role: str, count: int):
        sockets = []
        if count <= 0:
            return sockets

        spacing = self.BODY_HEIGHT / (count + 1)
        x_pos = 0 if socket_role == "input" else self.WIDTH
        for index in range(count):
            socket = NodeSocket(self, socket_role, index)
            socket.setPos(x_pos, self.HEADER_HEIGHT + spacing * (index + 1))
            sockets.append(socket)
        return sockets

    def _summarize_config(self):
        if not self.config:
            return "No parameters"
        key, value = next(iter(self.config.items()))
        return f"{key}: {value}"

    def set_active(self, active: bool):
        border = QColor("#f59e0b") if active else QColor("#334155")
        width = 2.4 if active else 1.2
        self.setPen(QPen(border, width))

    def update_config(self, config):
        self.config = config or {}
        self.summary_item.setText(self._summarize_config())

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            for socket in self.input_sockets + self.output_sockets:
                for connection in list(socket.connections):
                    connection.update_path()
        return super().itemChange(change, value)
