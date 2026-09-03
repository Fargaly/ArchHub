"""Silent Ollama install + model pull for zero-barrier onboarding.

For the architect who has never installed any AI tooling, this module
does the entire install in one shot:

  1. Download Ollama's official Windows installer (.exe, ~180 MB)
     from https://ollama.com/download/OllamaSetup.exe to %TEMP%.
  2. Run it silently (Ollama's installer supports /SILENT).
  3. Poll localhost:11434 until the service answers.
  4. Pull a small model (qwen2.5:3b, ~1.9 GB) via `ollama pull`.
  5. Verify generation works with a one-token completion.

Total time: ~4-8 minutes on a decent home connection. RAM needed:
~4 GB free at runtime (model loaded on demand).

The flow runs on a worker thread; the caller binds to four signals:
    progress(stage: str, percent: int, detail: str)
    failed(stage: str, error: str)
    finished(model: str)

Stages: "download" · "install" · "service_wait" · "model_pull" ·
         "verify" · "done"

When the user's network is air-gapped or the download fails, the
caller falls back to the "I'll set this up later" path. We never
block the app on this — the architect can use ArchHub with a
provider key instead.

Public API
----------
    OllamaInstaller(model: str = "qwen2.5:3b")
        start() -> None
        cancel() -> None
        signals: progress, failed, finished

    detect()       -> "running" | "installed_not_running" | "absent"
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QObject, QThread, pyqtSignal


OLLAMA_DOWNLOAD_URL = "https://ollama.com/download/OllamaSetup.exe"
OLLAMA_PORT = 11434

# Default model — small enough to run on a 8 GB laptop, large enough
# to feel responsive at ~3-4 tokens/sec on CPU and follow tool-use
# instructions reasonably well.
DEFAULT_MODEL = "qwen2.5:3b"

# Polling caps.
SERVICE_WAIT_TIMEOUT_S = 60
PULL_TIMEOUT_S = 30 * 60   # 30 min ceiling for slow connections


# ---------------------------------------------------------------------------
def _is_running() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", OLLAMA_PORT), timeout=0.4):
            return True
    except OSError:
        return False


def _is_installed_not_running() -> bool:
    """Ollama installed but service not yet up — `ollama.exe` is on PATH
    or in the standard install location."""
    if shutil.which("ollama"):
        return True
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe",
        Path(os.environ.get("PROGRAMFILES", "")) / "Ollama" / "ollama.exe",
    ]
    return any(p.exists() for p in candidates if p)


def detect() -> str:
    """Three-state probe: running / installed_not_running / absent."""
    if _is_running():
        return "running"
    if _is_installed_not_running():
        return "installed_not_running"
    return "absent"


def _ollama_exe() -> Optional[Path]:
    """Resolve a reachable ollama.exe path. Returns None if absent."""
    p = shutil.which("ollama")
    if p:
        return Path(p)
    for cand in (
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe",
        Path(os.environ.get("PROGRAMFILES", "")) / "Ollama" / "ollama.exe",
    ):
        if cand.exists():
            return cand
    return None


# ---------------------------------------------------------------------------
class OllamaInstaller(QObject):
    progress = pyqtSignal(str, int, str)  # stage, percent, detail
    failed   = pyqtSignal(str, str)        # stage, error
    finished = pyqtSignal(str)             # model name

    def __init__(self, model: str = DEFAULT_MODEL, parent=None):
        super().__init__(parent)
        self.model = model
        self._cancel = False
        self._thread: Optional[QThread] = None

    # ---- lifecycle -------------------------------------------------------
    def start(self) -> None:
        if self._thread is not None and self._thread.isRunning():
            return
        self._cancel = False
        self._thread = QThread()
        self.moveToThread(self._thread)
        self._thread.started.connect(self._run)
        self.finished.connect(self._thread.quit)
        self.failed.connect(lambda *_: self._thread.quit())
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def cancel(self) -> None:
        self._cancel = True

    def _check_cancel(self) -> bool:
        return bool(self._cancel)

    # ---- worker ---------------------------------------------------------
    def _run(self) -> None:
        state = detect()

        # If already running, jump to model pull.
        if state == "running":
            if not self._do_pull():
                return
            self.finished.emit(self.model)
            return

        # If installed but not running, try to start the service.
        if state == "installed_not_running":
            self.progress.emit("service_wait", 0, "Starting AI service…")
            self._spawn_ollama_serve()
            if not self._wait_for_service():
                return
            if not self._do_pull():
                return
            self.finished.emit(self.model)
            return

        # Absent — download installer then run it.
        installer_path = self._download_installer()
        if installer_path is None:
            return
        if not self._run_installer(installer_path):
            return
        # After install, the Ollama service usually auto-starts. Wait
        # a few seconds to be sure.
        self.progress.emit("service_wait", 0, "Starting AI service…")
        if not self._wait_for_service():
            return
        if not self._do_pull():
            return
        self.finished.emit(self.model)

    # ---- step: download ------------------------------------------------
    def _download_installer(self) -> Optional[Path]:
        try:
            tmp_dir = Path(tempfile.gettempdir()) / "ArchHub-onboarding"
            tmp_dir.mkdir(parents=True, exist_ok=True)
            dest = tmp_dir / "OllamaSetup.exe"
            req = urllib.request.Request(
                OLLAMA_DOWNLOAD_URL,
                headers={"User-Agent": "ArchHub-onboarding/1.0"},
            )
            self.progress.emit("download", 0, "Downloading AI engine…")
            with urllib.request.urlopen(req, timeout=30) as resp, \
                 open(dest, "wb") as out:
                total = int(resp.headers.get("Content-Length") or 0)
                read = 0
                chunk = 1024 * 64
                while True:
                    if self._check_cancel():
                        self.failed.emit("download", "Cancelled.")
                        return None
                    buf = resp.read(chunk)
                    if not buf:
                        break
                    out.write(buf)
                    read += len(buf)
                    if total > 0:
                        pct = int(read * 100 / total)
                        self.progress.emit(
                            "download", pct,
                            f"Downloading AI engine… {read//(1024*1024)} / "
                            f"{total//(1024*1024)} MB",
                        )
            self.progress.emit("download", 100, "Download complete.")
            return dest
        except urllib.error.URLError as e:
            self.failed.emit("download",
                              f"Couldn't reach ollama.com — {e.reason}. "
                              "Check your internet connection and retry.")
            return None
        except Exception as e:
            self.failed.emit("download",
                              f"Download failed: {type(e).__name__}: {e}")
            return None

    # ---- step: install -------------------------------------------------
    def _run_installer(self, installer_path: Path) -> bool:
        self.progress.emit("install", 0,
                            "Installing AI engine (no clicks needed)…")
        try:
            # Ollama installer is built with Inno Setup → /VERYSILENT
            # /SUPPRESSMSGBOXES /NORESTART runs it without any UI.
            cflags = 0
            if hasattr(subprocess, "CREATE_NO_WINDOW"):
                cflags = subprocess.CREATE_NO_WINDOW
            result = subprocess.run(
                [str(installer_path), "/VERYSILENT",
                 "/SUPPRESSMSGBOXES", "/NORESTART"],
                creationflags=cflags,
                timeout=600,
            )
            if result.returncode != 0:
                self.failed.emit(
                    "install",
                    f"Installer exited with code {result.returncode}. "
                    "Try running it manually from "
                    f"{installer_path}",
                )
                return False
        except subprocess.TimeoutExpired:
            self.failed.emit("install",
                              "Installer ran too long (over 10 minutes).")
            return False
        except Exception as e:
            self.failed.emit("install",
                              f"Install failed: {type(e).__name__}: {e}")
            return False
        self.progress.emit("install", 100, "AI engine installed.")
        return True

    # ---- step: spawn service ------------------------------------------
    def _spawn_ollama_serve(self) -> None:
        exe = _ollama_exe()
        if exe is None:
            return
        try:
            cflags = 0
            if hasattr(subprocess, "CREATE_NO_WINDOW"):
                cflags = subprocess.CREATE_NO_WINDOW
            subprocess.Popen(
                [str(exe), "serve"],
                creationflags=cflags,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass

    def _wait_for_service(self) -> bool:
        t0 = time.time()
        while time.time() - t0 < SERVICE_WAIT_TIMEOUT_S:
            if self._check_cancel():
                self.failed.emit("service_wait", "Cancelled.")
                return False
            if _is_running():
                self.progress.emit("service_wait", 100, "AI service live.")
                return True
            time.sleep(0.5)
        self.failed.emit(
            "service_wait",
            "AI service didn't start within a minute. "
            "Try restarting your computer + relaunching ArchHub.",
        )
        return False

    # ---- step: pull model ---------------------------------------------
    def _do_pull(self) -> bool:
        """Use Ollama's HTTP API (/api/pull) so we get streaming
        progress instead of parsing CLI output."""
        url = f"http://127.0.0.1:{OLLAMA_PORT}/api/pull"
        self.progress.emit("model_pull", 0,
                            f"Downloading AI model ({self.model})…")
        payload = json.dumps({"name": self.model, "stream": True}).encode()
        req = urllib.request.Request(url, data=payload, method="POST",
                                       headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=PULL_TIMEOUT_S) as resp:
                for raw_line in resp:
                    if self._check_cancel():
                        self.failed.emit("model_pull", "Cancelled.")
                        return False
                    try:
                        d = json.loads(raw_line.decode("utf-8").strip())
                    except Exception:
                        continue
                    status = d.get("status", "")
                    total = d.get("total")
                    completed = d.get("completed")
                    pct = 0
                    detail = status
                    if total and completed and total > 0:
                        pct = int(completed * 100 / total)
                        detail = (f"{status} — {completed//(1024*1024)} / "
                                   f"{total//(1024*1024)} MB")
                    self.progress.emit("model_pull", pct, detail)
                    if status == "success":
                        break
        except Exception as e:
            self.failed.emit(
                "model_pull",
                f"Couldn't download the AI model: {type(e).__name__}: {e}",
            )
            return False
        self.progress.emit("model_pull", 100, "AI model ready.")
        # Verify with a one-token completion.
        try:
            ver = json.dumps({"model": self.model,
                               "prompt": "hi", "stream": False,
                               "options": {"num_predict": 1}}).encode()
            req2 = urllib.request.Request(
                f"http://127.0.0.1:{OLLAMA_PORT}/api/generate",
                data=ver, method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req2, timeout=60) as r:
                r.read()
            self.progress.emit("verify", 100, "AI brain ready.")
        except Exception as e:
            self.failed.emit(
                "verify",
                f"Model installed but didn't respond: {type(e).__name__}",
            )
            return False
        return True
