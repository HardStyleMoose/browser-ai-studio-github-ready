from PySide6.QtWidgets import QApplication

class ThemeManager:
    themes = {
        "dark": "background-color: #0f172a; color: #f8fafc;",
        "light": "background-color: #f8fafc; color: #0f172a;"
    }

    @staticmethod
    def apply_theme(theme_name):
        style = ThemeManager.themes.get(theme_name, ThemeManager.themes["dark"])
        QApplication.instance().setStyleSheet(style)

    @staticmethod
    def toggle_theme():
        current = QApplication.instance().styleSheet()
        if current == ThemeManager.themes["dark"]:
            ThemeManager.apply_theme("light")
        else:
            ThemeManager.apply_theme("dark")
