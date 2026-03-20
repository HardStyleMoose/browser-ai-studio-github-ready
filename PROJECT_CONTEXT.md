# BrowserAI Studio Context

This file is a future-reference context summary for the current BrowserAI Studio project.

It is based on:
- `README.md`
- `distributed/README.md`
- `plugins/README.md`
- `requirements.txt`
- current active UI/runtime code in `app/`, `ui/`, `core/`, and `plugins/`

## Project Identity

- App name: `BrowerAI Studio Labs`
- Author label: `RicketyWrecked`
- Primary purpose: a desktop application for game automation research and visual workflow design
- Core focus areas:
  - browser and desktop game capture
  - drag-and-drop behavior graphs
  - PPO/RL training workflows
  - OCR and object/UI detection
  - plugin-driven extensibility
  - cluster-style multi-worker control
  - safe vision analysis via Vision Lab

## Current Top-Level App Sections

- `Training`
  - game mode, URL/EXE, capture region, AI start/stop, input settings, quick settings, logs, notes
- `Model Dashboard`
  - charts, metrics, PPO controls, runtime details
- `Behavior Editor`
  - node graph editor, logs/minimap panel, graph background tools, behavior save/load/history/simulate
- `Cluster`
  - worker table, runtime diagnostics, selected worker detail, scale/start/stop/connect controls
- `Vision Lab`
  - safe capture analysis, OCR review, backend profiles, dataset tools, recorded media review, heatmaps, presets, session history
- `Plugins`
  - plugin inventory, reload/refresh, selected plugin detail
- `Settings`
  - theme, runtime defaults, cluster defaults, OCR status, anti-ban settings, save/reload/reset actions

## What The Project Offers

- Visual behavior creation without hand-writing automation logic
- Human-like mouse/keyboard timing controls
- Browser and desktop training modes
- OCR support through Tesseract
- Vision pipelines using screen capture plus UI/OCR/object detection
- PPO model training/load/save flows
- Cluster-style worker management for parallel runtime/testing concepts
- Plugin support for registering new blocks and future integrations
- Persistent settings through `config/settings.yaml`

## Architecture Snapshot

The project is organized around these layers:

- `UI Layer`
  - PySide6 main shell, multi-page layout, graph editor, stats panels, settings
- `Automation Layer`
  - input manager, action execution, anti-ban style timing, behavior application
- `Vision Layer`
  - screen capture, OCR/resource reading, UI detection, YOLO-style detection, dataset capture
- `AI Layer`
  - PPO trainer and environment-building support
- `Integration Layer`
  - config, event bus, plugin manager, pipeline controller, runtime wiring

## Important Runtime Notes

- Default theme: `Terminal`
- Main window brand/title: `BrowerAI Studio Labs`
- OCR is expected to work best when Tesseract is installed
- The active app window is created by `app/main.py` and `app/main.pyw`
- `ui/main_window.py` is only a thin export of `ui/main_window_fixed.py`
- The active graph editor implementation is `ui/node_editor_fixed.py`

## Cluster Defaults And Limits

Current cluster behavior in the app:

- default worker count: `2`
- maximum worker count: `10`
- default memory budget per worker: `2.0 GB`
- worker detail now includes:
  - worker id
  - status
  - task
  - game
  - mode
  - CPU usage
  - memory usage
  - capture region
  - model/checkpoint summary
  - training progress summary

The cluster UI is currently a control/monitoring surface, not a full distributed scheduler.

## Vision Lab Context

Vision Lab is a safe advanced analysis module. It is intended for:

- screen-region analysis
- OCR inspection
- UI/object detection review
- target ranking for analysis only
- dataset collection
- backend/preset benchmarking
- heatmap generation
- session history export
- recorded image/video review

It is not intended to drive game input from the analysis page.

## Plugin System Context

The plugin README describes a `PluginInterface`/`register()` style, but the current runtime code uses:

- `core/plugin_interface.py`
  - `BasePlugin`
  - `activate(context)`
  - optional `deactivate(context)`

Current plugin loading behavior:

- only Python files in `plugins/` are discovered
- plugins are loaded by `core/plugin_manager.py`
- plugin summaries shown in the UI currently include:
  - id
  - name
  - version
  - description

## Key Files

- `app/main.py`
  - main startup path
- `app/main.pyw`
  - no-console entrypoint
- `ui/main_window_fixed.py`
  - active main window and page construction
- `ui/behavior_editor.py`
  - behavior editor wrapper
- `ui/node_editor_fixed.py`
  - active graph editor implementation
- `vision/resource_reader.py`
  - OCR/Tesseract status logic
- `vision/screen_capture.py`
  - screen capture utilities
- `core/config_manager.py`
  - settings persistence
- `core/plugin_manager.py`
  - plugin discovery/load/unload
- `config/settings.yaml`
  - persisted defaults

## Main Run Commands

From `D:\IDLE RPG`:

```powershell
.\env\Scripts\python.exe "AI Agents\browser-ai-studio\app\main.py"
```

No-console path:

```powershell
.\env\Scripts\pythonw.exe "AI Agents\browser-ai-studio\app\main.pyw"
```

## Primary Dependencies

From `requirements.txt`:

- `pyside6`
- `opencv-python`
- `torch`
- `ultralytics`
- `numpy`
- `pyautogui`
- `playwright`
- `pytesseract`
- `mss`
- `pynput`
- `stable-baselines3`
- `gymnasium`

## Known Documentation Gaps

- Root README mentions older tab counts and some older naming
- Plugin README describes an interface shape that does not exactly match the current runtime API
- This file should be preferred as a current-state orientation document when those sources disagree

