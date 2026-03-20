from __future__ import annotations

import os
import sys
import threading
import time
import ctypes

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication, QWidget

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.config_manager import ConfigManager
from core.event_bus import EventBus
from core.logger import setup_logger


STOP_EVENT = threading.Event()
APP_NAME = "BrowerAI Studio Labs"
APP_ID = "RicketyWrecked.BrowerAIStudioLabs"
SHOW_CONSOLE = os.environ.get("BROWSERAI_SHOW_CONSOLE") == "1"
_KEYBOARD_MODULE = None
_KEYBOARD_IMPORT_ATTEMPTED = False


def build_detector(logger):
    try:
        from vision.yolo_detector import YOLODetector

        return YOLODetector(model="yolov8n.pt")
    except Exception as exc:
        logger.warning("Falling back to UI-only detection: %s", exc)
        return None


def build_runtime(logger, event_bus, config=None):
    from automation.action_executor import ActionExecutor
    from automation.input_manager import InputManager
    from core.pipeline_controller import PipelineController
    from environment.environment_builder import EnvironmentBuilder
    from vision.perception_engine import PerceptionEngine
    from vision.resource_reader import ResourceReader
    from vision.screen_capture import capture_screen
    from vision.ui_detector import UIDetector

    input_manager = InputManager()
    ui_detector = UIDetector()
    object_detector = build_detector(logger)
    resource_reader = ResourceReader()
    ocr_status = resource_reader.get_status()
    if ocr_status["available"]:
        logger.info("OCR ready: %s", ocr_status["message"])
    else:
        logger.warning("OCR disabled: %s", ocr_status["message"])
    perception_engine = PerceptionEngine(object_detector, resource_reader, ui_detector)
    action_executor = ActionExecutor(input_manager)
    universal_env = EnvironmentBuilder(perception_engine, ui_detector, action_executor).build_environment()

    try:
        from ai.rl.ppo_trainer import PPOTrainer

        model_config = config.get("model", {}) if config is not None else {}
        ppo_trainer = PPOTrainer(
            env=universal_env,
            save_path=str(model_config.get("save_path", "models/ppo_model") or "models/ppo_model"),
            algorithm=str(model_config.get("algorithm", "auto") or "auto"),
            policy=str(model_config.get("policy", "auto") or "auto"),
            use_action_masking=bool(model_config.get("use_action_masking", True)),
        )
    except Exception as exc:
        logger.warning("PPO trainer unavailable: %s", exc)
        ppo_trainer = None

    pipeline_controller = PipelineController(capture_screen, perception_engine, ppo_trainer, action_executor, event_bus)
    return {
        "input_manager": input_manager,
        "ui_detector": ui_detector,
        "perception_engine": perception_engine,
        "action_executor": action_executor,
        "universal_env": universal_env,
        "ppo_trainer": ppo_trainer,
        "pipeline_controller": pipeline_controller,
    }


def _load_keyboard_module():
    global _KEYBOARD_MODULE, _KEYBOARD_IMPORT_ATTEMPTED
    if _KEYBOARD_IMPORT_ATTEMPTED:
        return _KEYBOARD_MODULE
    _KEYBOARD_IMPORT_ATTEMPTED = True
    try:
        from pynput import keyboard as keyboard_module
    except ImportError:  # pragma: no cover
        keyboard_module = None
    _KEYBOARD_MODULE = keyboard_module
    return _KEYBOARD_MODULE


def emergency_stop_listener(window, logger):
    keyboard = _load_keyboard_module()
    if keyboard is None:
        return

    def on_press(key):
        if key == keyboard.Key.f12:
            logger.warning("Emergency stop activated")
            window.ai_running = False
            STOP_EVENT.set()

    with keyboard.Listener(on_press=on_press) as listener:
        listener.join()


def training_loop(window, pipeline_controller, logger):
    pipeline_controller.start()
    logger.info("Training loop started")
    try:
        while window.ai_running and not STOP_EVENT.is_set():
            time.sleep(0.5)
    finally:
        pipeline_controller.stop()
        logger.info("Training loop stopped")


def _hide_console_window():
    if not sys.platform.startswith("win") or SHOW_CONSOLE:
        return
    try:
        kernel32 = ctypes.windll.kernel32
        user32 = ctypes.windll.user32
        hwnd = kernel32.GetConsoleWindow()
        if hwnd:
            user32.ShowWindow(hwnd, 0)
    except Exception:
        pass


def _hide_console_after_window_ready(window, delay_ms: int = 450):
    if not sys.platform.startswith("win") or SHOW_CONSOLE:
        return

    def _attempt_hide():
        if window.isVisible():
            _hide_console_window()
            return
        QTimer.singleShot(150, _attempt_hide)

    QTimer.singleShot(delay_ms, _attempt_hide)


def _warm_browser_runtime_async(logger):
    def _worker():
        from core.browser_runtime import ensure_playwright_chromium

        status = ensure_playwright_chromium(install_if_missing=True)
        if status["available"]:
            logger.info("Browser runtime: %s", status["message"])
        else:
            logger.warning("Browser runtime: %s", status["message"])

    threading.Thread(target=_worker, name="BrowserRuntimeWarmup", daemon=True).start()


def main():
    if sys.platform.startswith("win"):
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except Exception:
            pass
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    logger = setup_logger()
    debug_fonts = os.environ.get("UI_DEBUG_FONTS") == "1"
    config = ConfigManager()
    event_bus = EventBus()
    from ui.main_window import MainWindow

    app.setFont(QFont("Segoe UI", 10))
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    icon_path = os.path.join(CURRENT_DIR, "icon.ico")
    if not os.path.exists(icon_path):
        icon_path = os.path.join(CURRENT_DIR, "icon.png")
    app.setWindowIcon(QIcon(icon_path))

    window = MainWindow(
        input_manager=None,
        ppo_trainer=None,
        plugin_manager=None,
        event_bus=event_bus,
        pipeline_controller=None,
        config=config,
    )
    window.setWindowTitle(APP_NAME)
    window.setWindowIcon(QIcon(icon_path))
    window.set_status("Loading main shell...")

    window.show()
    app.processEvents()
    _hide_console_after_window_ready(window)

    # Diagnostic: Print font size for all widgets after main window is shown
    if debug_fonts:
        print_invalid_fonts(window, max_depth=5)

    def finish_startup():
        try:
            window.set_status("Loading runtime components...")
            runtime = build_runtime(logger, event_bus, config=config)
            from core.plugin_manager import PluginManager

            plugin_manager = PluginManager(
                plugins_dir=os.path.join(PROJECT_ROOT, "plugins"),
                event_bus=event_bus,
                app_context={"config": config, "logger": logger, **runtime},
            )
            window.attach_runtime_services(
                input_manager=runtime["input_manager"],
                ppo_trainer=runtime["ppo_trainer"],
                plugin_manager=plugin_manager,
                event_bus=event_bus,
                pipeline_controller=runtime["pipeline_controller"],
                config=config,
            )
            try:
                plugin_manager.load_all()
            except Exception as exc:
                logger.warning("Plugin load failed: %s", exc)
                window.set_status(f"Plugin load failed: {exc}")
            else:
                window.refresh_plugins()
                window.set_status("Ready")
            _warm_browser_runtime_async(logger)
            if _load_keyboard_module() is not None:
                threading.Thread(target=emergency_stop_listener, args=(window, logger), daemon=True).start()
        except Exception as exc:
            logger.exception("Startup bootstrap failed: %s", exc)
            window.set_status(f"Startup bootstrap failed: {exc}")

    QTimer.singleShot(0, finish_startup)

    exit_code = app.exec()
    if window.plugin_manager is not None:
        window.plugin_manager.unload_all()
    return exit_code


def print_invalid_fonts(widget, depth=0, max_depth=5):
    if depth > max_depth:
        return
    try:
        indent = '  ' * depth
        print(f"[DEBUG]{indent}{widget.__class__.__name__} (depth {depth})")
        font = widget.font()
        if font.pointSize() == 0:
            print(f"[FONT ERROR]{indent}Widget: {widget.__class__.__name__}, Font: {font.family()}, Size: {font.pointSize()}")
        for child in widget.findChildren(QWidget, options=Qt.FindDirectChildrenOnly):
            # Skip any child whose class name contains 'MainWindow' or 'window' (case-insensitive)
            cls_name = child.__class__.__name__.lower()
            if 'mainwindow' in cls_name or 'window' in cls_name:
                print(f"[SKIP]{indent}Skipping {child.__class__.__name__} to avoid global/window recursion")
                continue
            print_invalid_fonts(child, depth=depth+1, max_depth=max_depth)
    except Exception:
        pass


if __name__ == "__main__":
    if QApplication.instance() is None:
        app = QApplication(sys.argv)
    sys.exit(main())
