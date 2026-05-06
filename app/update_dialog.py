"""Update dialog — one-click "Check for updates" + "Apply + restart".

The architect clicks **↻ Update** in the header, sees a small dialog with
the current version, the available version (if any), and a single primary
button. No terminal involved.

States the dialog shows:
  - Checking…              (spinner while git fetch runs)
  - Up to date             (HEAD matches remote)
  - <N> updates available  (HEAD is behind; show subject of newest)
  - Cannot update          (network error, dirty tree, ahead of remote)

Background work runs in a QThread so the UI never freezes.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, QObject, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
    QMessageBox,
)

import updater


# ---------------------------------------------------------------------------
class _CheckWorker(QObject):
    """Runs updater.check_for_updates() off the UI thread."""
    finished = pyqtSignal(object)        # UpdateStatus

    def run(self) -> None:
        status = updater.check_for_updates()
        self.finished.emit(status)


class _ApplyWorker(QObject):
    """Runs updater.apply_update() off the UI thread."""
    finished = pyqtSignal(bool, str)     # (success, message)

    def run(self) -> None:
        ok, msg = updater.apply_update()
        self.finished.emit(ok, msg)


# ---------------------------------------------------------------------------
class UpdateDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("ArchHub — Update")
        self.setObjectName("panel")
        self.setMinimumWidth(440)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_header())

        body = QFrame()
        bv = QVBoxLayout(body)
        bv.setContentsMargins(24, 18, 24, 8)
        bv.setSpacing(10)

        self.status_line = QLabel("Checking for updates…")
        self.status_line.setObjectName("updateStatus")
        self.status_line.setWordWrap(True)
        bv.addWidget(self.status_line)

        self.detail_line = QLabel("")
        self.detail_line.setObjectName("updateDetail")
        self.detail_line.setWordWrap(True)
        bv.addWidget(self.detail_line)

        outer.addWidget(body, 1)
        outer.addWidget(self._build_footer())

        self._worker_thread: QThread | None = None
        self._worker = None

        # Kick off the initial check immediately.
        self._start_check()

    # ---- UI scaffolding ---------------------------------------------------

    def _build_header(self) -> QWidget:
        hf = QFrame(); hf.setObjectName("panelHeader")
        v = QVBoxLayout(hf); v.setContentsMargins(24, 22, 24, 14); v.setSpacing(4)
        t = QLabel("Update"); t.setObjectName("panelTitle")
        s = QLabel("Check for the latest ArchHub version and apply it in one click.")
        s.setObjectName("panelSubtitle"); s.setWordWrap(True)
        v.addWidget(t); v.addWidget(s)
        return hf

    def _build_footer(self) -> QWidget:
        f = QFrame(); f.setObjectName("panelFooter")
        h = QHBoxLayout(f); h.setContentsMargins(20, 12, 20, 14); h.setSpacing(8)

        self.recheck_btn = QPushButton("↻ Re-check")
        self.recheck_btn.setObjectName("ghostButton")
        self.recheck_btn.clicked.connect(self._start_check)
        h.addWidget(self.recheck_btn)

        h.addStretch(1)

        self.close_btn = QPushButton("Close")
        self.close_btn.setObjectName("ghostButton")
        self.close_btn.clicked.connect(self.reject)
        h.addWidget(self.close_btn)

        self.action_btn = QPushButton("Update")
        self.action_btn.setObjectName("primaryButton")
        self.action_btn.setEnabled(False)
        self.action_btn.clicked.connect(self._start_apply)
        h.addWidget(self.action_btn)

        return f

    # ---- check ------------------------------------------------------------

    def _start_check(self) -> None:
        self.status_line.setText("Checking for updates…")
        self.detail_line.setText("")
        self.action_btn.setEnabled(False)
        self.recheck_btn.setEnabled(False)

        self._worker = _CheckWorker()
        self._worker_thread = QThread(self)
        self._worker.moveToThread(self._worker_thread)
        self._worker_thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_check_done)
        self._worker.finished.connect(self._worker_thread.quit)
        self._worker_thread.finished.connect(self._worker.deleteLater)
        self._worker_thread.finished.connect(self._worker_thread.deleteLater)
        self._worker_thread.start()

    def _on_check_done(self, status) -> None:
        self.recheck_btn.setEnabled(True)
        self._render_status(status)

    def _render_status(self, status) -> None:
        if status.error:
            self.status_line.setText(f"⚠️ {status.error}")
            self.detail_line.setText("")
            self.action_btn.setEnabled(False)
            return

        version_line = (
            f"Installed: <b>{status.local_commit or 'unknown'}</b> "
            f"on branch <b>{status.branch or '?'}</b>"
        )
        if status.local_subject:
            version_line += f"<br><i>{status.local_subject}</i>"

        if status.has_updates:
            head = (
                f"✨ {status.behind} update"
                f"{'s' if status.behind != 1 else ''} available."
            )
            self.status_line.setText(head)
            extra = ""
            if status.has_uncommitted:
                extra = (
                    "<br><br>⚠️ Local changes detected. The updater will not "
                    "overwrite them. Discard or commit them first."
                )
                self.action_btn.setEnabled(False)
                self.action_btn.setText("Cannot update")
            elif status.ahead > 0:
                extra = (
                    f"<br><br>⚠️ This checkout is also {status.ahead} commit"
                    f"{'s' if status.ahead != 1 else ''} ahead of the remote. "
                    f"Push or stash them, then try again."
                )
                self.action_btn.setEnabled(False)
                self.action_btn.setText("Cannot update")
            else:
                self.action_btn.setEnabled(True)
                self.action_btn.setText("Update + Restart")
            self.detail_line.setText(version_line + extra)
        else:
            self.status_line.setText("✓ ArchHub is up to date.")
            self.detail_line.setText(version_line)
            self.action_btn.setEnabled(False)
            self.action_btn.setText("Update")

    # ---- apply ------------------------------------------------------------

    def _start_apply(self) -> None:
        if QMessageBox.question(
            self, "Apply update?",
            "ArchHub will pull the latest changes and restart itself. "
            "Any unsaved chat will be lost. Continue?",
        ) != QMessageBox.StandardButton.Yes:
            return

        self.action_btn.setEnabled(False)
        self.recheck_btn.setEnabled(False)
        self.status_line.setText("Applying update…")
        self.detail_line.setText("")

        self._worker = _ApplyWorker()
        self._worker_thread = QThread(self)
        self._worker.moveToThread(self._worker_thread)
        self._worker_thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_apply_done)
        self._worker.finished.connect(self._worker_thread.quit)
        self._worker_thread.finished.connect(self._worker.deleteLater)
        self._worker_thread.finished.connect(self._worker_thread.deleteLater)
        self._worker_thread.start()

    def _on_apply_done(self, ok: bool, message: str) -> None:
        if not ok:
            self.status_line.setText("⚠️ Update failed.")
            # Wrap multiline git output in a fixed-width style for readability.
            safe_msg = (message or "")
            self.detail_line.setText(
                f"<pre style='white-space:pre-wrap;font-size:11px;color:#c9c4bc;'>"
                f"{safe_msg}</pre>"
                f"<br><i>Tip: double-click <b>Update.bat</b> in the repo folder "
                f"for a verbose log if this keeps happening.</i>"
            )
            self.recheck_btn.setEnabled(True)
            self.action_btn.setEnabled(False)
            return
        self.status_line.setText("✓ Updated. Restarting…")
        self.detail_line.setText(message)
        # Brief pause so the user sees the success line, then relaunch.
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(700, self._restart_app)

    def _restart_app(self) -> None:
        # Close the parent window cleanly so its resources release before
        # we exec the new process.
        parent = self.parent()
        try:
            if parent is not None and hasattr(parent, "close"):
                parent.close()
        except Exception:
            pass
        updater.restart()
