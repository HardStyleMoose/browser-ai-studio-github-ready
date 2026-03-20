from PySide6.QtWidgets import QToolTip
from PySide6.QtCore import QPoint

class TooltipHelper:
    @staticmethod
    def show_tooltip(widget, text, pos=None):
        if pos is None:
            pos = widget.mapToGlobal(widget.rect().center())
        QToolTip.showText(pos, text, widget)

    @staticmethod
    def hide_tooltip():
        QToolTip.hideText()
