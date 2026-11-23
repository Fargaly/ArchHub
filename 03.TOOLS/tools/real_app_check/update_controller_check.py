"""Installed-only check of the shipped ApplicationUpdate controller (e988 eb8390bd).

Runs the installed nodelang against a disposable state folder with inert Setup bytes; nothing is
installed, restarted or signed in. A ready offer for the installed build that is confirmed on disk
must answer, and keep answering, "up to date" with no busy guard and no restart; a truly newer staged
build must still be refused while work is busy.
"""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile


def stage(state, build_id, phase, built_at=None):
    updates = state / "updates"
    updates.mkdir(parents=True, exist_ok=True)
    setup = updates / "ArchHub-Setup-0.exe"
    setup.write_bytes(b"inert installer bytes for the controller check")
    marker = {"build_id": build_id, "sha256": hashlib.sha256(setup.read_bytes()).hexdigest(), "phase": phase}
    if built_at:
        marker["built_at"] = built_at
    (updates / "staged.json").write_text(json.dumps(marker), encoding="utf-8")


def controller(state, app, busy):
    from nodelang.application_update import ApplicationUpdate
    calls = {"guard": 0, "restart": 0}

    def guard():
        calls["guard"] += 1
        return busy

    def restart():
        calls["restart"] += 1

    update = ApplicationUpdate(state, app, request_restart=restart, restart_refusal=guard,
                               policy=lambda: {"auto_apply_on_quit": False, "channel": "stable"})
    return update, calls


def main():
    app = Path(os.environ["LOCALAPPDATA"]) / "ArchHub"
    sys.path.insert(0, str(app))
    from nodelang.application_update import UpdateRestartRefused
    from nodelang.quiet_update import installed_build_id
    installed = installed_build_id(app)
    if not installed:
        raise SystemExit("No installed BUILD_ID to check against.")
    with tempfile.TemporaryDirectory() as folder:
        state = Path(folder) / "same"
        stage(state, installed, "confirmed")
        update, calls = controller(state, app, busy="2 calls in flight")
        with update._lock:   # a ready offer for the installed build, as the founder's screen showed
            update._state, update._available = "ready", installed
            update._detail, update._restart_reason = "Build %s is downloaded and verified. Restart to update." % installed, "busy"
        try:
            clicked = update.reload()
        except UpdateRestartRefused as refusal:
            raise SystemExit("Same build %s: Update showed a refusal instead of up to date: %s" % (installed, refusal))
        after = update.status()
        for name, value in (("click", clicked), ("next status", after)):
            if value["state"] != "idle" or value.get("available_build") or "up to date" not in value["detail"]:
                raise SystemExit("Same build %s: %s still offers an update: %r" % (installed, name, value))
        if calls != {"guard": 0, "restart": 0}:
            raise SystemExit("Same build consulted the busy guard or restarted: %r" % calls)

        state = Path(folder) / "newer"
        stage(state, "20991231-2359-update-check", "staged", built_at="2099-12-31T23:59:59Z")
        update, calls = controller(state, app, busy="2 calls in flight")
        try:
            update.reload()
        except UpdateRestartRefused as refusal:
            if "calls in flight" not in str(refusal):
                raise SystemExit("Newer build refused for the wrong reason: %s" % refusal)
        else:
            raise SystemExit("A newer staged build restarted over busy work.")
        if calls != {"guard": 1, "restart": 0}:
            raise SystemExit("Newer busy build: expected one guard call and no restart, got %r" % calls)
    print(json.dumps({"result": "PASS", "installed": installed, "same_build": "up to date, no guard, no restart",
                      "newer_busy": "refused, no restart"}))


if __name__ == "__main__":
    main()
