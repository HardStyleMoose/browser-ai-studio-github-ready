from PySide6.QtGui import QKeySequence
from PySide6.QtGui import QShortcut

class KeyboardShortcutsManager:
    def __init__(self, parent):
        self.parent = parent
        self.shortcuts = []

    def add_shortcut(self, key, callback):
        shortcut = QShortcut(QKeySequence(key), self.parent)
        shortcut.activated.connect(callback)
        self.shortcuts.append(shortcut)

    def clear_shortcuts(self):
        for shortcut in self.shortcuts:
            shortcut.activated.disconnect()
        self.shortcuts.clear()
