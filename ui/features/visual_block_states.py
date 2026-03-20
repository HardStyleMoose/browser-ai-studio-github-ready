from PySide6.QtGui import QBrush, QColor, QPen

class VisualBlockStates:
    @staticmethod
    def set_active(block):
        block.setBrush(QBrush(QColor("#38bdf8")))
        block.setPen(QPen(QColor("#f59e0b"), 2.4))

    @staticmethod
    def set_error(block):
        block.setBrush(QBrush(QColor("#ef4444")))
        block.setPen(QPen(QColor("#b91c1c"), 2.4))

    @staticmethod
    def set_disabled(block):
        block.setBrush(QBrush(QColor("#64748b")))
        block.setPen(QPen(QColor("#334155"), 1.2))

    @staticmethod
    def set_normal(block):
        block.setBrush(QBrush(QColor("#1e293b")))
        block.setPen(QPen(QColor("#2563eb"), 2.2))
