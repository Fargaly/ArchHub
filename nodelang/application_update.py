"""Desktop release download state shared by the existing Studio and tray."""
import os
from pathlib import Path
import re
import tempfile
import threading

from .universal_cell import InvalidCell

# quiet_update's refusal for a release that is not strictly newer than the
# installed build. The decision court runs the real refusal through this match.
_NOT_NEWER = "The offered build is not newer than the installed build; no update staged."
# The build the owner last acknowledged. A different BUILD_ID at boot is an
# update, however it was installed, and the Studio confirms it once.
SEEN_BUILD = "last-seen-build"


def update_decision(result, installed_build):
    """Name what one finished check decided: newer, same, older or failed.

    quiet_update owns ordering and staging. Only a verified staged release is
    offered; the same or an older release is up to date, never available.
    """
    result = result if type(result) is dict else {}
    build = str(result.get("build_id") or "")
    installed = str(installed_build or "") or "unversioned build"
    reason = " ".join(str(result.get("reason") or "Update check finished.").split())[:512]
    status = result.get("status")
    if result.get("staged") is True and status == "staged" and build:
        return {"decision": "newer", "state": "ready", "available_build": build,
            "detail": "Build %s is downloaded and verified. Restart to update." % build,
            "log": "check: newer release %s staged and ready (installed %s)" % (build, installed)}
    if result.get("staged") is True and status == "awaiting_boot" and build == installed:
        # quiet_update returns the held marker without reading any release.
        return {"decision": "same", "state": "idle", "available_build": "",
            "detail": "Up to date. Build %s was just installed." % installed,
            "log": "check: installed build %s is awaiting boot confirmation; nothing offered" % installed}
    if reason == "up to date":
        return {"decision": "same", "state": "idle", "available_build": "",
            "detail": "Up to date. Build %s is the latest release." % installed,
            "log": "check: up to date (installed %s is the latest release)" % installed}
    if status == "not_ready" and reason == _NOT_NEWER and build:
        return {"decision": "older", "state": "idle", "available_build": "",
            "detail": "Up to date. The latest release %s is not newer than the installed build %s." % (build, installed),
            "log": "check: latest release %s is not newer than installed %s; nothing offered" % (build, installed)}
    return {"decision": "failed", "state": "failed", "available_build": "", "detail": reason,
        "log": "check: failed -- " + reason}


def _seen_build(state_dir):
    try:
        with (Path(state_dir) / "updates" / SEEN_BUILD).open(encoding="ascii") as stream:
            value = stream.read(258).strip()
    except (OSError, UnicodeError):
        return ""
    return value if re.fullmatch(r"[A-Za-z0-9._-]{1,256}", value) else ""


def _record_seen_build(state_dir, build):
    from .quiet_update import _plain
    updates = Path(state_dir) / "updates"
    _plain(updates)
    updates.mkdir(parents=True, exist_ok=True)
    target = updates / SEEN_BUILD
    _plain(target)
    fd, name = tempfile.mkstemp(prefix=".seen-", suffix=".tmp", dir=updates)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="ascii", newline="") as stream:
            stream.write(build)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


class ApplicationUpdate:
    def __init__(self, state_dir, app_dir, *, request_restart, initial_stage=None, report=None, on_ready=None,
                 first_boot=False):
        from .quiet_update import installed_build_id
        self.state_dir, self.app_dir = Path(state_dir), Path(app_dir)
        self._request_restart = request_restart
        self._report, self._on_ready = report, on_ready
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
        self._updated = None
        installed, seen = installed_build_id(self.app_dir), _seen_build(self.state_dir)
        if installed and seen != installed:
            if seen or not first_boot:
                # A release restart and a local install both land here.
                self._updated = (seen, installed)
            else:
                try:
                    _record_seen_build(self.state_dir, installed)
                except (OSError, ValueError):
                    pass

    def status(self):
        from .quiet_update import installed_build_id
        with self._lock:
            return {"ok": True, "current_build": installed_build_id(self.app_dir) or "Unversioned build",
                "state": self._state, "available_build": self._available or None,
                "detail": self._detail,
                "restart_supported": callable(self._request_restart) and not self._closed,
                "updated_from": (self._updated[0] or None) if self._updated else None,
                "updated_to": self._updated[1] if self._updated else None}

    def acknowledge(self):
        """Record the running build as seen; its update confirmation is not shown again."""
        with self._lock:
            if self._updated:
                try:
                    _record_seen_build(self.state_dir, self._updated[1])
                except (OSError, ValueError) as error:
                    raise InvalidCell("The update confirmation could not be saved (" + type(error).__name__
                        + "). Dismiss again to retry.") from None
                self._updated = None
            return self.status()

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
                return self.status()
            except Exception as error:
                self._worker = None
                self._state, self._detail = "failed", "Update check could not start (" + type(error).__name__ + "). Check again to retry."
                status = self.status()
        self._say("check: failed -- " + status["detail"])
        return status

    def _say(self, line):
        # One launcher line per finished check. A log sink never changes the decision.
        if callable(self._report):
            try:
                self._report(line)
            except Exception:
                pass

    def _download(self):
        from .quiet_update import installed_build_id, stage_if_newer
        try:
            result = stage_if_newer(self.state_dir, self.app_dir, cancellation_event=self._stop)
        except Exception as error:
            result = {"staged": False, "build_id": "", "status": "unavailable",
                "reason": "Update download failed (" + type(error).__name__ + "). Check again to retry."}
        decision = update_decision(result, installed_build_id(self.app_dir))
        with self._lock:
            self._state, self._detail = decision["state"], decision["detail"]
            self._available = decision["available_build"]
        self._say(decision["log"])
        if decision["state"] == "ready" and callable(self._on_ready):
            # The desktop page reads the ready status now; the Studio holds no update poll.
            try:
                self._on_ready()
            except Exception:
                pass

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
            "restart_supported": False, "updated_from": None, "updated_to": None}
    return update.status()


def application_update_action(owner, body):
    if type(body) is not dict or set(body) != {"action"} or body["action"] not in ("check", "reload", "acknowledge"):
        raise InvalidCell("Application update action is invalid")
    update = getattr(owner, "application_update", None)
    if update is None:
        raise InvalidCell("Application updates require the installed desktop lifecycle")
    if body["action"] == "acknowledge":
        return update.acknowledge()
    return update.check() if body["action"] == "check" else update.reload()
