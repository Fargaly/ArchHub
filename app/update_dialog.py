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
    QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QProgressBar,
    QVBoxLayout, QWidget, QMessageBox,
)

import updater
import release_updater


# ---------------------------------------------------------------------------
class _CheckWorker(QObject):
    """Runs the right update check off the UI thread.

    Two modes coexist:
      - Git-checkout users (developers, source clones): updater.check_for_updates()
        does a `git fetch` and reports ahead/behind counts.
      - Installer users (.exe via Inno Setup): release_updater.has_update_available()
        hits the GitHub Releases API and compares semver tags.
    """
    finished = pyqtSignal(object)        # an UpdateState we render below

    def run(self) -> None:
        if release_updater.in_git_checkout():
            status = updater.check_for_updates()
            self.finished.emit(("git", status))
        else:
            available, info, local = release_updater.has_update_available()
            self.finished.emit(("release", available, info, local))


class _ApplyWorker(QObject):
    """Runs the matching apply path off the UI thread."""
    finished = pyqtSignal(bool, str)     # (success, message)
    progress = pyqtSignal(int, int)      # (downloaded, total) bytes

    def __init__(self, mode: str, release_info=None):
        super().__init__()
        self._mode = mode
        self._release_info = release_info

    def run(self) -> None:
        if self._mode == "git":
            ok, msg = updater.apply_update()
            self.finished.emit(ok, msg)
            return
        # release mode
        try:
            installer_path = release_updater.download_asset(
                self._release_info,
                on_progress=lambda d, t: self.progress.emit(d, t),
            )
            self.finished.emit(True, f"Downloaded {installer_path.name}. Launching installer…")
            # The installer takes over from here; this Python process exits.
            release_updater.run_installer(installer_path, silent=True, relaunch=True)
        except Exception as ex:
            self.finished.emit(False, f"Update failed: {type(ex).__name__}: {ex}")


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

    def _on_check_done(self, payload) -> None:
        self.recheck_btn.setEnabled(True)
        if not payload:
            return
        kind = payload[0]
        if kind == "git":
            self._mode = "git"
            self._render_git_status(payload[1])
        elif kind == "release":
            _, available, info, local = payload
            self._mode = "release"
            self._release_info = info if available else None
            self._render_release_status(available, info, local)

    def _render_git_status(self, status) -> None:
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
                f"{'s' if status.behind != 1 else ''} available (source build)."
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

    def _render_release_status(self, available: bool, info, local: str) -> None:
        if info.error and not info.tag:
            self.status_line.setText(f"⚠️ {info.error}")
            self.detail_line.setText("")
            self.action_btn.setEnabled(False)
            return

        local_v = local or "unknown"
        version_line = (
            f"Installed: <b>{local_v}</b><br>"
            f"Latest release: <b>{info.tag or '—'}</b>"
        )
        if info.published_at:
            version_line += (
                f"<br><span style='color:#a09a90;'>"
                f"Published {info.published_at[:10]}</span>"
            )

        if available:
            self.status_line.setText(
                f"✨ Update available — {info.tag} ({info.asset_size // 1024 // 1024} MB)."
            )
            notes = (info.body or "")[:600].strip()
            if notes:
                version_line += f"<br><br><b>What's new</b><br><pre style='white-space:pre-wrap;font-size:11px;color:#c9c4bc;'>{notes}</pre>"
            self.action_btn.setEnabled(True)
            self.action_btn.setText("Update + Restart")
        else:
            self.status_line.setText("✓ ArchHub is up to date.")
            self.action_btn.setEnabled(False)
            self.action_btn.setText("Update")
        self.detail_line.setText(version_line)

    # ---- apply ------------------------------------------------------------

    def _start_apply(self) -> None:
        if QMessageBox.question(
            self, "Apply update?",
            "ArchHub will download the latest version and restart itself. "
            "Any unsaved chat will be lost. Continue?",
        ) != QMessageBox.StandardButton.Yes:
            return

        self.action_btn.setEnabled(False)
        self.recheck_btn.setEnabled(False)
        self.status_line.setText("Applying update…")
        self.detail_line.setText("")

        mode = getattr(self, "_mode", "git")
        info = getattr(self, "_release_info", None) if mode == "release" else None
        self._worker = _ApplyWorker(mode=mode, release_info=info)
        self._worker_thread = QThread(self)
        self._worker.moveToThread(self._worker_thread)
        self._worker_thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_apply_done)
        self._worker.progress.connect(self._on_apply_progress)
        self._worker.finished.connect(self._worker_thread.quit)
        self._worker_thread.finished.connect(self._worker.deleteLater)
        self._worker_thread.finished.connect(self._worker_thread.deleteLater)
        self._worker_thread.start()

    def _on_apply_progress(self, downloaded: int, total: int) -> None:
        if total <= 0:
            return
        pct = int(100 * downloaded / total)
        mb_d = downloaded / 1024 / 1024
        mb_t = total / 1024 / 1024
        self.status_line.setText(f"Downloading update… {pct}% ({mb_d:.1f} / {mb_t:.1f} MB)")

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
