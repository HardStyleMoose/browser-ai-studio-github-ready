# BrowerAI Studio Labs Third-Party Notices

Version: 2026-03-20

This file is a convenience summary of major third-party components that are used, bundled, or provisioned by BrowerAI Studio Labs. It is not a complete substitute for the original third-party license files or notices distributed by their upstream authors.

Before shipping commercial or public builds, review the exact versions you distribute and the original license files for those versions.

## Core Python/Desktop Stack

- Python runtime: Python Software Foundation License
- PySide6 / Qt for Python: LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only
- PyInstaller: GPLv2-or-later with PyInstaller bootloader exception
- NumPy: BSD-3-Clause
- OpenCV (`opencv-python`): Apache License 2.0

## Automation And Browser Stack

- Playwright: upstream license applies; review the bundled Playwright driver notices when distributing
- Chromium / browser runtime components: upstream Chromium and bundled browser notices apply
- `n8n` local managed runtime: see the `n8n` package license and bundled notices in the managed runtime

## AI / ML / Training Stack

- PyTorch: BSD-3-Clause
- Torchvision: BSD
- Stable-Baselines3: MIT
- SB3-Contrib: MIT
- Gymnasium: upstream license applies
- Pytesseract: Apache License 2.0
- Tesseract OCR: upstream license applies when installed or redistributed separately

## Additional Project Dependencies

- `requests`, `mss`, `pynput`, `pyautogui`, `pyqtgraph`, `yt-dlp`, and other dependencies remain subject to their own upstream licenses
- Optional or generated runtimes such as FFmpeg, Node.js, Playwright browser assets, and `n8n` dependencies must be reviewed separately when bundled

## Important Licensing Review Note

This project currently references `ultralytics` in `requirements.txt`, and the installed package metadata reports the license as `AGPL-3.0`.

If you distribute builds that include or depend on that component, you should complete a separate compatibility and compliance review before distribution. This notice does not resolve or waive any obligations imposed by that third-party license.

## Distribution Guidance

- Keep upstream license texts and notices when a bundled dependency requires them
- Do not remove attribution or third-party notice files from packaged outputs when they are required by an upstream license
- Re-check notices whenever dependency versions change
