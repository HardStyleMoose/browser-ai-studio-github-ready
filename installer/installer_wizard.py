from __future__ import annotations

import sys
import time
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtGui import QFont, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWizard,
    QWizardPage,
)

from core.browser_runtime import ensure_playwright_chromium
from core.legal_docs import legal_doc_text, legal_doc_version
from installer.install_utils import (
    APP_NAME,
    create_windows_shortcut,
    default_install_dir,
    desktop_dir,
    disk_free_bytes,
    extract_payload,
    format_bytes,
    installed_app_icon,
    launch_installed_app,
    load_release_manifest,
    payload_size_bytes,
    resolve_payload_path,
    resource_root,
    start_menu_programs_dir,
    verify_release_payload,
    write_install_manifest,
)

INSTALLER_OPERATIONAL_NOTICE_TEXT = """BrowerAI Studio Labs Installation Notice

Please read this notice carefully before installing or using this software.

This setup wizard installs BrowerAI Studio Labs and, depending on the options you choose, may copy a packaged desktop application to your selected install directory, create desktop and Start menu shortcuts, and provision a browser runtime component used by browser-based automation and analysis workflows. The installer may also write a small installation manifest so the application can identify where it was installed and what setup choices were selected during installation.

BrowerAI Studio Labs is provided as a configurable desktop application environment for workflow design, training, browser and desktop capture, plugin loading, perception tooling, and related runtime features. Because the software can be configured in many different ways and may interact with third-party applications, browser content, local files, input devices, and machine-learning components, you are responsible for reviewing your chosen configuration and using the software in a manner that is lawful, authorized, safe, and appropriate for your own system and use case.

By continuing with this installation, you acknowledge that third-party services, websites, games, tools, and local applications may each have their own terms of service, acceptable use requirements, account policies, system requirements, and operational limitations. Installing BrowerAI Studio Labs does not grant rights to access, automate, modify, monitor, or interact with any third-party software or service beyond what you are independently authorized to do. It is your responsibility to ensure that your use of the installed application complies with all applicable rules, licenses, and restrictions.

This installer may download or prepare supporting runtime components, including Chromium for Playwright-based browser sessions, in order to make browser features available after setup. Those components may consume additional disk space and may be updated or replaced over time by their upstream providers. Network access may be required the first time these components are provisioned. If your environment has security, proxy, enterprise policy, or endpoint protection controls, those controls may affect runtime provisioning or later application behavior.

You should also understand that the application may store configuration values, logs, datasets, cached files, and other generated content in or alongside the chosen installation path and in user-profile locations used by Windows, Python, Playwright, or supporting libraries. Depending on the features you enable, the software may capture screenshots, inspect on-screen text, load plugins, process media files, or save output artifacts. You are responsible for protecting any sensitive content that may be processed or stored through those workflows.

Although this installer is designed to provide a reliable first-run setup experience, the software is distributed on an as-is basis without any promise that it will be uninterrupted, error-free, compatible with every environment, or suitable for every operational purpose. No installation routine can fully eliminate the possibility of conflicts with local permissions, antivirus controls, missing dependencies, graphics drivers, unsupported hardware, or future upstream changes in third-party libraries and browser runtimes.

As a best practice, review the installation location before continuing, close unnecessary applications during setup, and keep appropriate backups of important files and settings. If you are installing over an existing version, you should verify any custom configuration, plugin, or dataset content you wish to preserve. Where required by your environment, obtain administrator approval or organizational authorization before deployment.

If you do not agree with these installation conditions, or if you are not authorized to install and use this software on this machine, do not continue with setup."""


INSTALLER_DISCLAIMER_TEXT = (
    f"{legal_doc_text('eula', 'EULA document is unavailable in this installer build.')}\n\n"
    "Additional Legal And Security References\n\n"
    f"- NOTICE.md Version: {legal_doc_version('notice')}\n"
    f"- SECURITY.md Version: {legal_doc_version('security')}\n\n"
    "The installer-specific operational notice below supplements the EULA above and does not replace it.\n\n"
    f"{INSTALLER_OPERATIONAL_NOTICE_TEXT}"
)


class InstallWorker(QObject):
    progress_changed = Signal(int)
    log_message = Signal(str)
    finished = Signal(dict)
    failed = Signal(str)

    def __init__(
        self,
        install_dir: str,
        create_desktop_shortcut: bool,
        create_start_menu_shortcut: bool,
        install_chromium: bool,
        launch_after_install: bool,
    ):
        super().__init__()
        self.install_dir = Path(install_dir)
        self.create_desktop_shortcut = create_desktop_shortcut
        self.create_start_menu_shortcut = create_start_menu_shortcut
        self.install_chromium = install_chromium
        self.launch_after_install = launch_after_install

    @Slot()
    def run(self):
        try:
            payload_path = resolve_payload_path()
            payload_manifest = load_release_manifest()
            payload_sha256 = verify_release_payload(payload_path, payload_manifest)
            self.progress_changed.emit(2)
            self.log_message.emit(f"Preparing installation to {self.install_dir}")
            self.log_message.emit(f"Verified installer payload integrity ({payload_sha256[:12]}...).")
            if self.install_dir.exists() and any(self.install_dir.iterdir()):
                self.log_message.emit("Existing installation detected. Files will be updated in place.")
            else:
                self.log_message.emit("Creating installation directory.")
            self.progress_changed.emit(5)
            extract_payload(payload_path, self.install_dir, progress_callback=self.progress_changed.emit, log_callback=self.log_message.emit)
            app_executable = self.install_dir / payload_manifest["entry_executable"]
            if not app_executable.exists():
                raise FileNotFoundError(f"Installed application executable was not found: {app_executable}")

            created_shortcuts = []
            icon_path = installed_app_icon(self.install_dir) or app_executable

            if self.create_desktop_shortcut:
                shortcut_path = desktop_dir() / f"{APP_NAME}.lnk"
                create_windows_shortcut(
                    shortcut_path,
                    app_executable,
                    app_executable.parent,
                    f"Launch {APP_NAME}",
                    icon_path=icon_path,
                )
                created_shortcuts.append(str(shortcut_path))
                self.log_message.emit("Desktop shortcut created.")

            if self.create_start_menu_shortcut:
                shortcut_path = start_menu_programs_dir() / f"{APP_NAME}.lnk"
                create_windows_shortcut(
                    shortcut_path,
                    app_executable,
                    app_executable.parent,
                    f"Launch {APP_NAME}",
                    icon_path=icon_path,
                )
                created_shortcuts.append(str(shortcut_path))
                self.log_message.emit("Start menu shortcut created.")

            self.progress_changed.emit(78)
            chromium_status = {"available": True, "message": "Skipped Chromium setup.", "attempted_install": False}
            if self.install_chromium:
                self.log_message.emit("Checking bundled browser runtime...")
                chromium_status = ensure_playwright_chromium(install_if_missing=True)
                self.log_message.emit(chromium_status["message"])
                if not chromium_status["available"]:
                    raise RuntimeError(chromium_status["message"])

            accepted_at = time.strftime("%Y-%m-%d %H:%M:%S")
            manifest_path = write_install_manifest(
                self.install_dir,
                payload_manifest,
                app_executable,
                created_shortcuts,
                legal_acceptance={
                    "accepted_at": accepted_at,
                    "accepted_in_installer": True,
                    "eula_version": str(payload_manifest.get("eula_version") or ""),
                    "eula_sha256": str(payload_manifest.get("eula_sha256") or ""),
                    "notice_sha256": str(payload_manifest.get("notice_sha256") or ""),
                    "payload_sha256": str(payload_sha256 or ""),
                },
            )
            self.progress_changed.emit(95)
            self.log_message.emit(f"Installation manifest written to {manifest_path.name}")
            self.progress_changed.emit(100)
            self.finished.emit(
                {
                    "install_dir": str(self.install_dir),
                    "app_executable": str(app_executable),
                    "created_shortcuts": created_shortcuts,
                    "chromium_status": chromium_status,
                    "launch_after_install": self.launch_after_install,
                }
            )
        except Exception as exc:
            self.failed.emit(str(exc))


class WelcomePage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("Welcome")
        self.setSubTitle("Install BrowerAI Studio Labs with a guided desktop setup.")

        layout = QVBoxLayout(self)
        hero = QFrame()
        hero.setObjectName("hero")
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(18, 18, 18, 18)
        hero_layout.setSpacing(16)

        logo_label = QLabel()
        logo_path = resource_root() / "app" / "icon.png"
        if logo_path.exists():
            pixmap = QPixmap(str(logo_path))
            logo_label.setPixmap(pixmap.scaled(72, 72, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        logo_label.setFixedSize(80, 80)
        logo_label.setAlignment(Qt.AlignCenter)
        hero_layout.addWidget(logo_label)

        text_layout = QVBoxLayout()
        title = QLabel(APP_NAME)
        title.setObjectName("heroTitle")
        body = QLabel(
            "This setup wizard installs the full desktop application, prepares browser runtime support, "
            "and can place shortcuts where you want them."
        )
        body.setWordWrap(True)
        body.setObjectName("mutedText")
        text_layout.addWidget(title)
        text_layout.addWidget(body)
        hero_layout.addLayout(text_layout, 1)
        layout.addWidget(hero)

        bullets = QLabel(
            "What this installer will do:\n"
            "- copy the packaged application to your chosen install folder\n"
            "- optionally provision Chromium for browser workers\n"
            "- optionally create desktop and Start menu shortcuts\n"
            "- optionally launch the app after setup completes"
        )
        bullets.setWordWrap(True)
        layout.addWidget(bullets)
        layout.addStretch()


class DisclaimerPage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("License Agreement")
        self.setSubTitle("Review the EULA, notice, and security references before continuing.")

        layout = QVBoxLayout(self)
        disclaimer_box = QPlainTextEdit()
        disclaimer_box.setReadOnly(True)
        disclaimer_box.setPlainText(INSTALLER_DISCLAIMER_TEXT)
        disclaimer_box.setMinimumHeight(320)
        self.accept_checkbox = QCheckBox("I have read and accept the EULA and installation terms above.")
        self.accept_checkbox.toggled.connect(self.completeChanged.emit)

        layout.addWidget(disclaimer_box, 1)
        layout.addWidget(self.accept_checkbox)

        self.registerField("disclaimerAccepted*", self.accept_checkbox)

    def isComplete(self) -> bool:
        return self.accept_checkbox.isChecked()

    def validatePage(self) -> bool:
        if not self.accept_checkbox.isChecked():
            QMessageBox.warning(self, APP_NAME, "You must accept the EULA and installation terms before continuing.")
            return False
        return True


class DestinationPage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("Choose Install Location")
        self.setSubTitle("Pick where BrowerAI Studio Labs should be installed.")

        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        self.install_dir_edit = QLineEdit(str(default_install_dir()))
        browse_button = QPushButton("Browse")
        browse_button.clicked.connect(self._browse_for_dir)
        row.addWidget(self.install_dir_edit, 1)
        row.addWidget(browse_button)
        layout.addLayout(row)

        self.stats_label = QLabel()
        self.stats_label.setWordWrap(True)
        layout.addWidget(self.stats_label)
        self.notice_label = QLabel()
        self.notice_label.setWordWrap(True)
        self.notice_label.setObjectName("mutedText")
        layout.addWidget(self.notice_label)
        layout.addStretch()

        self.install_dir_edit.textChanged.connect(self._refresh_stats)
        self.registerField("installDir*", self.install_dir_edit)
        self._refresh_stats()

    def initializePage(self):
        self._refresh_stats()

    def validatePage(self) -> bool:
        install_dir = Path(self.install_dir_edit.text().strip())
        if not self.install_dir_edit.text().strip():
            QMessageBox.warning(self, APP_NAME, "Choose an installation folder first.")
            return False
        try:
            free_bytes = disk_free_bytes(install_dir)
        except Exception as exc:
            QMessageBox.warning(self, APP_NAME, f"Unable to validate the install location: {exc}")
            return False
        required = int(payload_size_bytes() * 1.25)
        if free_bytes < required:
            QMessageBox.warning(
                self,
                APP_NAME,
                f"Not enough free space.\n\nRequired: {format_bytes(required)}\nAvailable: {format_bytes(free_bytes)}",
            )
            return False
        return True

    def _browse_for_dir(self):
        chosen = QFileDialog.getExistingDirectory(self, "Select Install Folder", self.install_dir_edit.text().strip())
        if chosen:
            self.install_dir_edit.setText(chosen)

    def _refresh_stats(self):
        install_dir = Path(self.install_dir_edit.text().strip() or str(default_install_dir()))
        payload_size = payload_size_bytes()
        free_bytes = disk_free_bytes(install_dir)
        self.stats_label.setText(
            f"Package size: {format_bytes(payload_size)}\n"
            f"Free space at destination: {format_bytes(free_bytes)}"
        )
        if install_dir.exists() and any(install_dir.iterdir()):
            self.notice_label.setText("An existing installation was detected here. Setup will update it in place.")
        else:
            self.notice_label.setText("A new per-user installation will be created here.")


class OptionsPage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("Choose Setup Options")
        self.setSubTitle("Select shortcuts and runtime components.")

        layout = QVBoxLayout(self)
        self.desktop_shortcut_checkbox = QCheckBox("Create a desktop shortcut")
        self.desktop_shortcut_checkbox.setChecked(True)
        self.start_menu_shortcut_checkbox = QCheckBox("Create a Start menu shortcut")
        self.start_menu_shortcut_checkbox.setChecked(True)
        self.chromium_checkbox = QCheckBox("Install Chromium runtime for browser workers")
        self.chromium_checkbox.setChecked(True)
        self.launch_checkbox = QCheckBox("Launch BrowerAI Studio Labs when setup finishes")
        self.launch_checkbox.setChecked(True)

        for checkbox in [
            self.desktop_shortcut_checkbox,
            self.start_menu_shortcut_checkbox,
            self.chromium_checkbox,
            self.launch_checkbox,
        ]:
            layout.addWidget(checkbox)

        notes = QLabel(
            "Chromium setup is recommended so browser workers can run immediately after install without manual fixes."
        )
        notes.setWordWrap(True)
        notes.setObjectName("mutedText")
        layout.addWidget(notes)
        layout.addStretch()

        self.registerField("desktopShortcut", self.desktop_shortcut_checkbox)
        self.registerField("startMenuShortcut", self.start_menu_shortcut_checkbox)
        self.registerField("installChromium", self.chromium_checkbox)
        self.registerField("launchAfterInstall", self.launch_checkbox)


class SummaryPage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("Ready To Install")
        self.setSubTitle("Review the setup plan before installation begins.")
        layout = QVBoxLayout(self)
        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)
        layout.addStretch()

    def initializePage(self):
        wizard = self.wizard()
        install_dir = wizard.field("installDir")
        selected_options = []
        if wizard.field("desktopShortcut"):
            selected_options.append("Desktop shortcut")
        if wizard.field("startMenuShortcut"):
            selected_options.append("Start menu shortcut")
        if wizard.field("installChromium"):
            selected_options.append("Chromium runtime")
        if wizard.field("launchAfterInstall"):
            selected_options.append("Launch when complete")
        options_text = ", ".join(selected_options) if selected_options else "No optional components selected"
        self.summary_label.setText(
            f"Application: {APP_NAME}\n"
            f"Install folder: {install_dir}\n"
            f"Package size: {format_bytes(payload_size_bytes())}\n"
            f"Options: {options_text}\n\n"
            "Click Install to begin."
        )

    def nextId(self) -> int:
        return InstallerWizard.PAGE_INSTALL


class InstallPage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("Installing")
        self.setSubTitle("Setup is copying files, creating shortcuts, and preparing runtime dependencies.")
        self._started = False
        self._complete = False
        self._failed = False
        self.result = None
        self.thread = None
        self.worker = None

        layout = QVBoxLayout(self)
        self.status_label = QLabel("Waiting to start installation...")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        layout.addWidget(self.status_label)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.log_output, 1)

    def initializePage(self):
        if self._started:
            return
        self._started = True
        wizard = self.wizard()
        self.thread = QThread(self)
        self.worker = InstallWorker(
            install_dir=str(wizard.field("installDir")),
            create_desktop_shortcut=bool(wizard.field("desktopShortcut")),
            create_start_menu_shortcut=bool(wizard.field("startMenuShortcut")),
            install_chromium=bool(wizard.field("installChromium")),
            launch_after_install=bool(wizard.field("launchAfterInstall")),
        )
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress_changed.connect(self._on_progress_changed)
        self.worker.log_message.connect(self._on_log_message)
        self.worker.finished.connect(self._on_finished)
        self.worker.failed.connect(self._on_failed)
        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.thread.start()

    def isComplete(self) -> bool:
        return self._complete

    def nextId(self) -> int:
        return InstallerWizard.PAGE_FINISH

    def cleanupPage(self):
        if self.thread is not None and self.thread.isRunning():
            self.thread.quit()
            self.thread.wait(1000)

    @Slot(int)
    def _on_progress_changed(self, value: int):
        self.progress_bar.setValue(value)

    @Slot(str)
    def _on_log_message(self, message: str):
        self.status_label.setText(message)
        self.log_output.appendPlainText(message)

    @Slot(dict)
    def _on_finished(self, result: dict):
        self.result = result
        self._complete = True
        self.status_label.setText("Installation completed successfully.")
        self.progress_bar.setValue(100)
        self.wizard().install_result = result
        self.completeChanged.emit()

    @Slot(str)
    def _on_failed(self, message: str):
        self._failed = True
        self.status_label.setText("Installation failed.")
        self.log_output.appendPlainText(f"ERROR: {message}")
        QMessageBox.critical(self, APP_NAME, f"Installation failed:\n\n{message}")
        self._complete = False
        self.completeChanged.emit()


class FinishPage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("Setup Complete")
        self.setSubTitle("BrowerAI Studio Labs is ready to use.")
        layout = QVBoxLayout(self)
        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)
        layout.addStretch()

    def initializePage(self):
        result = getattr(self.wizard(), "install_result", None) or {}
        install_dir = result.get("install_dir", "Unknown")
        shortcuts = result.get("created_shortcuts", [])
        chromium = result.get("chromium_status", {}).get("message", "Runtime status unavailable.")
        shortcut_text = "\n".join(f"- {path}" for path in shortcuts) if shortcuts else "- No shortcuts created"
        self.summary_label.setText(
            f"Installed to:\n{install_dir}\n\n"
            f"Shortcuts:\n{shortcut_text}\n\n"
            f"Browser runtime:\n{chromium}"
        )

    def isFinalPage(self) -> bool:
        return True


class InstallerWizard(QWizard):
    PAGE_WELCOME = 0
    PAGE_DISCLAIMER = 1
    PAGE_DESTINATION = 2
    PAGE_OPTIONS = 3
    PAGE_SUMMARY = 4
    PAGE_INSTALL = 5
    PAGE_FINISH = 6

    def __init__(self):
        super().__init__()
        self.install_result = None
        self.setWindowTitle(f"{APP_NAME} Setup")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setOption(QWizard.WizardOption.NoBackButtonOnStartPage, True)
        self.setOption(QWizard.WizardOption.NoBackButtonOnLastPage, True)
        self.resize(760, 560)

        icon_path = resource_root() / "app" / "icon.ico"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self.setPage(self.PAGE_WELCOME, WelcomePage())
        self.setPage(self.PAGE_DISCLAIMER, DisclaimerPage())
        self.setPage(self.PAGE_DESTINATION, DestinationPage())
        self.setPage(self.PAGE_OPTIONS, OptionsPage())
        self.setPage(self.PAGE_SUMMARY, SummaryPage())
        self.setPage(self.PAGE_INSTALL, InstallPage())
        self.setPage(self.PAGE_FINISH, FinishPage())

        self.setButtonText(QWizard.WizardButton.NextButton, "Next")
        self.setButtonText(QWizard.WizardButton.BackButton, "Back")
        self.setButtonText(QWizard.WizardButton.FinishButton, "Finish")
        self.setButtonText(QWizard.WizardButton.CancelButton, "Cancel")
        self._apply_styles()

    def accept(self):
        result = self.install_result or {}
        if result.get("launch_after_install") and result.get("app_executable"):
            try:
                launch_installed_app(Path(result["app_executable"]))
            except Exception as exc:
                QMessageBox.warning(self, APP_NAME, f"Installed successfully, but the app could not be launched:\n\n{exc}")
        super().accept()

    def _apply_styles(self):
        self.setStyleSheet(
            """
            QWizard {
                background: #0c1208;
                color: #d8ff6b;
            }
            QFrame#hero {
                border: 1px solid #69ff18;
                border-radius: 12px;
                background: #10190a;
            }
            QLabel#heroTitle {
                font-size: 24px;
                font-weight: 700;
            }
            QLabel#mutedText {
                color: #b6d78a;
            }
            QLineEdit, QPlainTextEdit {
                border: 1px solid #5fd417;
                border-radius: 8px;
                padding: 8px;
                background: #081004;
                color: #ebffb0;
            }
            QPushButton {
                border: 1px solid #7cff16;
                border-radius: 8px;
                background: #2f8d12;
                color: #f3ffd8;
                padding: 8px 14px;
            }
            QPushButton:hover {
                background: #38a815;
            }
            QProgressBar {
                border: 1px solid #5fd417;
                border-radius: 8px;
                text-align: center;
                background: #081004;
                color: #ebffb0;
                min-height: 24px;
            }
            QProgressBar::chunk {
                background: #5fd417;
                border-radius: 7px;
            }
            QCheckBox {
                spacing: 10px;
            }
            """
        )


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(f"{APP_NAME} Setup")
    app.setApplicationDisplayName(f"{APP_NAME} Setup")
    app.setFont(QFont("Segoe UI", 10))
    wizard = InstallerWizard()
    wizard.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
