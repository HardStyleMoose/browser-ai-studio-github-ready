import subprocess
import pygetwindow as gw

try:
    from playwright.sync_api import sync_playwright
except Exception:  # pragma: no cover - optional runtime dependency
    sync_playwright = None


def launch_browser_game(url):
    """Launch a browser game using Playwright."""
    if sync_playwright is None:
        raise RuntimeError("Playwright is not installed.")
    playwright = sync_playwright().start()
    browser = playwright.chromium.launch(headless=False)
    page = browser.new_page()
    page.goto(url)
    return page, browser, playwright


def launch_desktop_game(exe_path):
    """Launch a desktop game using subprocess."""
    proc = subprocess.Popen(exe_path)
    return proc


def list_open_windows():
    """Return visible window titles for desktop selection."""
    try:
        return [title for title in gw.getAllTitles() if str(title or "").strip()]
    except Exception:
        return []


def focus_window(title):
    """Focus a window by title."""
    try:
        win = gw.getWindowsWithTitle(title)[0]
        win.activate()
    except IndexError:
        print(f"Window with title '{title}' not found.")


def get_window_region(title):
    """Get the region of a window by title."""
    try:
        win = gw.getWindowsWithTitle(title)[0]
        return {'left': win.left, 'top': win.top, 'width': win.width, 'height': win.height}
    except IndexError:
        return None
