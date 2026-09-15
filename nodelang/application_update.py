"""Desktop release download state shared by the existing Studio and tray."""
from pathlib import Path
import threading

from .universal_cell import InvalidCell


class ApplicationUpdate:
    def __init__(self, state_dir, app_dir, *, request_restart, initial_stage=None):
        self.state_dir, self.app_dir = Path(state_dir), Path(app_dir)
        self._request_restart = request_restart
        self._lock = threading.RLock()
        self._worker = None
        self._state, self._detail = "idle", "Check for a new ArchHub release."
        self._available = ""
        self._closed = False
        self._stop = threading.Event()
        # The launcher already verified staging before opening the graph. Reuse
        # that observation; never hash an installer on a UI status poll.
        if initial_stage and initial_stage.get("staged") and initial_stage.get("status") == "staged":
            self._available = str(initial_stage.get("build_id") or "")
            self._state, self._detail = "ready", "The downloaded update is ready to install."

    def status(self):
        from .quiet_update import installed_build_id
        with self._lock:
            return {"ok": True, "current_build": installed_build_id(self.app_dir) or "Unversioned build",
                "state": self._state, "available_build": self._available or None,
                "detail": self._detail,
                "restart_supported": callable(self._request_restart) and not self._closed}

    def check(self):
        with self._lock:
            if self._closed or self._state == "restarting":
                raise InvalidCell("The application is closing for an update")
            if self._worker is not None and self._worker.is_alive():
                return self.status()
            self._state, self._detail = "checking", "Checking and downloading the latest release."
            self._worker = threading.Thread(target=self._download,
                name="archhub-update-download", daemon=True)
            try:
                self._worker.start()
            except Exception as error:
                self._worker = None
                self._state, self._detail = "failed", "Update check could not start (" + type(error).__name__ + "). Check again to retry."
            return self.status()

    def _download(self):
        from .quiet_update import stage_if_newer
        try:
            result = stage_if_newer(self.state_dir, self.app_dir, cancellation_event=self._stop)
            with self._lock:
                self._available = str(result.get("build_id") or "")
                self._state = "ready" if result.get("staged") and result.get("status") == "staged" else (
                    "idle" if result.get("reason") == "up to date" else "failed")
                self._detail = str(result.get("reason") or "Update check finished.")
        except Exception as error:
            with self._lock:
                self._state = "failed"
                self._detail = "Update download failed (" + type(error).__name__ + "). Check again to retry."

    def reload(self):
        from .quiet_update import staged_update
        with self._lock:
            if self._closed or not callable(self._request_restart):
                raise InvalidCell("Update and reload requires the desktop application")
            if self._state == "restarting":
                return self.status()
            if self._worker is not None and self._worker.is_alive():
                raise InvalidCell("Wait for the update download to finish")
            staged = staged_update(self.state_dir, self.app_dir)
            if not staged.get("staged") or staged.get("status") != "staged":
                self._state, self._detail = "failed", str(staged.get("reason") or "No verified update is ready.")
                raise InvalidCell(self._detail)
            self._available = str(staged["build_id"])
            try:
                self._request_restart()
            except Exception as error:
                self._state, self._detail = "failed", "Restart could not be requested (" + type(error).__name__ + "). The downloaded update is retained."
                raise InvalidCell(self._detail) from None
            self._state, self._detail = "restarting", "Saving your data and restarting into the update."
            return self.status()

    def close(self, *, timeout_seconds=6.0):
        """Stop staging and report whether the owned download actually ended.

        Socket/DNS calls may outlast this wait. The launcher must retain its
        recovery state and refuse a successful close while that worker lives.
        """
        with self._lock:
            self._closed = True
            self._stop.set()
            worker = self._worker
        # The worker takes _lock to publish its final result. Never join it
        # while holding that lock.
        if worker is not None:
            worker.join(timeout=timeout_seconds)
        return worker is None or not worker.is_alive()


def application_update_status(owner):
    update = getattr(owner, "application_update", None)
    if update is None:
        return {"ok": True, "current_build": "Unversioned build", "state": "idle", "available_build": None,
            "detail": "Release updates are available in the installed desktop application.",
            "restart_supported": False}
    return update.status()


def application_update_action(owner, body):
    if type(body) is not dict or set(body) != {"action"} or body["action"] not in ("check", "reload"):
        raise InvalidCell("Application update action is invalid")
    update = getattr(owner, "application_update", None)
    if update is None:
        raise InvalidCell("Application updates require the installed desktop lifecycle")
    return update.check() if body["action"] == "check" else update.reload()
