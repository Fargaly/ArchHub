"""Build progress dialog.

Wraps a connector auto-build in a modal dialog with a progress bar, stage
label, and (collapsed by default) live build log. Runs the build on a
QThread so the UI stays responsive.

Usage:
    dlg = BuildProgressDialog(parent, "Setting up Revit 2023",
                              build_fn=lambda cb: build_revit_connector(2023, cb))
    dlg.exec()
    if dlg.result_ok:
        # retry connector activation
"""
from __future__ import annotations

from typing import Callable, Optional

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton,
    QSizePolicy, QTextEdit, QVBoxLayout, QWidget,
)

from auto_build import BuildResult


# ---------------------------------------------------------------------------
class _BuildWorker(QThread):
    """Runs the build_fn on a worker thread, emits progress signals."""
    progress = pyqtSignal(str, int, str)         # stage, percent, line
    finished_ok = pyqtSignal(object)             # BuildResult

    def __init__(self,
                 build_fn: Callable[[Callable[[str, int, str], None]], BuildResult],
                 parent=None):
        super().__init__(parent)
        self.build_fn = build_fn

    def run(self) -> None:
        def on_progress(stage: str, percent: int, line: str = "") -> None:
            self.progress.emit(stage, int(percent), line or "")
        try:
            result = self.build_fn(on_progress)
        except Exception as ex:
            result = BuildResult(False, f"{type(ex).__name__}: {ex}", [])
        self.finished_ok.emit(result)


# ---------------------------------------------------------------------------
class BuildProgressDialog(QDialog):
    def __init__(self, parent, title: str,
                 build_fn: Callable[[Callable[[str, int, str], None]], BuildResult]):
        super().__init__(parent)
        self.setWindowTitle("ArchHub — Setting up connector")
        self.setObjectName("panel")
        self.setModal(True)
        self.resize(560, 280)

        self.result: Optional[BuildResult] = None
        self.result_ok = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ---- header ----
        hf = QFrame(); hf.setObjectName("panelHeader")
        hv = QVBoxLayout(hf); hv.setContentsMargins(24, 22, 24, 18); hv.setSpacing(4)
        self.title_label = QLabel(title); self.title_label.setObjectName("panelTitle")
        self.subtitle_label = QLabel("This is a one-time setup. ArchHub will configure the connector for you.")
        self.subtitle_label.setObjectName("panelSubtitle"); self.subtitle_label.setWordWrap(True)
        hv.addWidget(self.title_label); hv.addWidget(self.subtitle_label)
        outer.addWidget(hf)

        # ---- body ----
        body = QWidget()
        bv = QVBoxLayout(body); bv.setContentsMargins(24, 16, 24, 12); bv.setSpacing(10)

        self.stage_label = QLabel("Starting…"); self.stage_label.setObjectName("connectorStatus")
        bv.addWidget(self.stage_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100); self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False); self.progress_bar.setFixedHeight(6)
        bv.addWidget(self.progress_bar)

        self.show_log_btn = QPushButton("Show details"); self.show_log_btn.setObjectName("ghostButton")
        self.show_log_btn.setCheckable(True); self.show_log_btn.toggled.connect(self._toggle_log)
        log_row = QHBoxLayout(); log_row.addWidget(self.show_log_btn); log_row.addStretch(1)
        bv.addLayout(log_row)

        self.log_view = QTextEdit(); self.log_view.setObjectName("messageText")
        self.log_view.setReadOnly(True); self.log_view.setMaximumHeight(140); self.log_view.hide()
        bv.addWidget(self.log_view)

        outer.addWidget(body, 1)

        # ---- footer ----
        ff = QFrame(); ff.setObjectName("panelFooter")
        fh = QHBoxLayout(ff); fh.setContentsMargins(20, 12, 20, 14); fh.setSpacing(8)
        fh.addStretch(1)
        self.cancel_btn = QPushButton("Cancel"); self.cancel_btn.setObjectName("ghostButton")
        self.cancel_btn.clicked.connect(self.reject)
        self.close_btn = QPushButton("Close"); self.close_btn.setObjectName("primaryButton")
        self.close_btn.clicked.connect(self.accept); self.close_btn.hide()
        fh.addWidget(self.cancel_btn); fh.addWidget(self.close_btn)
        outer.addWidget(ff)

        # ---- worker ----
        self._worker = _BuildWorker(build_fn, self)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_ok.connect(self._on_finished)
        self._worker.start()

    # ---- slots ------------------------------------------------------------

    def _on_progress(self, stage: str, percent: int, line: str) -> None:
        self.stage_label.setText(stage)
        self.progress_bar.setValue(min(max(percent, 0), 100))
        if line:
            self.log_view.append(line)

    def _on_finished(self, result: BuildResult) -> None:
        self.result = result
        self.result_ok = result.success

        if result.success:
            self.title_label.setText("Connector ready")
            self.subtitle_label.setText("Toggle it on and open the application to start using it.")
            self.stage_label.setText("✓ Done")
            self.progress_bar.setValue(100)
        else:
            self.title_label.setText("Setup failed")
            # Friendly messaging for the most common failures
            if result.detail == "no_dotnet_sdk":
                self.subtitle_label.setText(
                    "ArchHub needs the .NET 8 SDK from Microsoft to set up this connector. "
                    "It's a free, one-time install. Click 'Install .NET' below."
                )
                self.stage_label.setText("Missing prerequisite: .NET 8 SDK")
                self._add_install_dotnet_button()
            elif "not found" in result.detail.lower():
                self.subtitle_label.setText(
                    f"{result.detail} — make sure the application is installed in its default location, "
                    f"or open Settings to point ArchHub at a custom path."
                )
                self.stage_label.setText("Application not found")
            else:
                self.subtitle_label.setText(
                    "The build didn't complete. Click 'Show details' to see the error log."
                )
                self.stage_label.setText("Build error")
                # Auto-open the log on failure
                if not self.show_log_btn.isChecked():
                    self.show_log_btn.setChecked(True)

        self.cancel_btn.hide()
        self.close_btn.show()

    def _toggle_log(self, on: bool) -> None:
        self.log_view.setVisible(on)
        self.show_log_btn.setText("Hide details" if on else "Show details")
        self.adjustSize()

    def _add_install_dotnet_button(self) -> None:
        """Show an 'Install .NET' button when SDK is missing."""
        from auto_build import download_dotnet_installer, install_dotnet_sdk
        from pathlib import Path

        btn = QPushButton("Install .NET 8"); btn.setObjectName("primaryButton")

        def on_click() -> None:
            btn.setEnabled(False)
            self.title_label.setText("Installing .NET 8 SDK")
            self.subtitle_label.setText("This may take a couple of minutes. Please wait.")
            self.progress_bar.setValue(0)

            def task(progress_cb):
                from auto_build import BuildResult
                try:
                    progress_cb("Downloading .NET 8 SDK", 0, "")
                    installer = download_dotnet_installer(
                        Path.home() / "AppData" / "Local" / "ArchHub" / "_dotnet",
                        on_progress=progress_cb,
                    )
                    progress_cb("Installing .NET 8 SDK", 90, "Running silent installer…")
                    ok = install_dotnet_sdk(installer, on_progress=progress_cb)
                    if ok:
                        return BuildResult(True, ".NET 8 SDK installed. Restart the connector setup.", [installer])
                    return BuildResult(False, "Installation failed.", [])
                except Exception as ex:
                    return BuildResult(False, f"{type(ex).__name__}: {ex}", [])

            self._worker = _BuildWorker(task, self)
            self._worker.progress.connect(self._on_progress)
            self._worker.finished_ok.connect(self._on_finished)
            self._worker.start()

        btn.clicked.connect(on_click)
        # Insert into footer next to Close
        footer = self.findChildren(QFrame, "panelFooter")
        if footer:
            footer[0].layout().insertWidget(footer[0].layout().count() - 1, btn)
