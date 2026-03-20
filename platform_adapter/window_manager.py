"""Helpers for managing application windows."""

import time


class WindowManager:
    """Cross-platform window helpers."""

    def __init__(self, title: str):
        self.title = title

    def find_window(self):
        """Return window handle or None."""
        return None

    def focus_window(self):
        """Bring the window to the foreground."""
        pass

    def wait_for_window(self, timeout: float = 10.0):
        start = time.time()
        while time.time() - start < timeout:
            if self.find_window():
                return True
            time.sleep(0.1)
        return False
