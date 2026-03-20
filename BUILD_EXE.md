## Packaging BrowerAI Studio Labs as a Standalone App + Installer

### 1. Install PyInstaller

```
pip install pyinstaller
```

### 2. Build the App and Installer

From the browser-ai-studio directory:

```
python build_exe.py
```

Or double-click:

- `Build BrowerAI Studio Labs Installer.vbs`

This build flow now does all of the following:

- provisions Playwright Chromium for browser workers
- builds the application dist into `dist/BrowserAI_Lab/`
- creates an installer payload archive in `installer/build/`
- builds a commercial-style setup wizard executable in `dist/BrowerAI Studio Labs Setup.exe`
- bundles `LICENSE.md`, `EULA.md`, `NOTICE.md`, `THIRD_PARTY_NOTICES.md`, and `SECURITY.md` into the packaged output
- writes release-manifest integrity fields including `payload_sha256`, `eula_sha256`, and `notice_sha256`

### 3. Notes
- Ensure all assets, models, and plugins are present in the output folder.
- The app and installer both use `app/icon.ico`.
- For troubleshooting, use `--console` in the EXE section of the spec file for debug output.
- The app now auto-checks Playwright Chromium on startup and will try to install it on first run if it is missing.
- If you want to pre-provision it during packaging, run `python -m playwright install chromium` before building the EXE.
- The installer wizard can install the app for a user without opening a terminal and can create desktop/Start menu shortcuts.
- The installer wizard verifies the payload hash before extraction and records accepted legal metadata in the install manifest.

### 4. Troubleshooting
- If the EXE fails to launch, run it from the command line to view errors.
- Missing DLLs: Add them to the `dist/BrowserAI_Lab/` folder or specify in the spec file.
- PySide6/Qt errors: Ensure all Qt plugins and assets are included.
- Use `--console` for debug output, or `--windowed` to hide the console.
- For large projects, increase the recursion limit in your main script (`import sys; sys.setrecursionlimit(2000)`).
- If the installer cannot be built, verify that `installer/build/app_payload.zip` and `installer/build/release_manifest.json` were created during the app build step.

### 5. Advanced Customization
- Edit `pyinstaller.spec` to control the app bundle and `installer_wizard.spec` to control the setup executable.
- To bundle additional folders (models, plugins, assets), use the `datas` argument in the spec file:
  ```python
  datas=[('assets/*', 'assets'), ('models/*', 'models'), ('plugins/*', 'plugins')]
  ```
- To change the app or setup EXE name, edit the `name` argument in the relevant spec file.

---
