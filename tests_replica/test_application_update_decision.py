"""A release check decides newer, same or older, and every update is confirmed once.

Founder state read 2026-09-17 through //localhost/c$: installed BUILD_ID
20260916-2130-e733a13 (written 2026-09-16 21:29:58) with BUILD_METADATA
built_at 2026-09-16T17:24:00Z, an updates directory holding only
operation.lock, and releases/latest build-20260916-2105-b914892 with BUILT_AT
2026-09-16T16:47:18Z. His build came by local install, newer than every public
release, so no release check could announce it: "you updated and I got no
notification". launcher.log carries no update line after line 12067 (2026-09-07).
Every release document here is served from memory; no network, installer,
window or graph is touched.
"""
from __future__ import annotations

import ast
from contextlib import redirect_stdout
import functools
import hashlib
import io
import json
import os
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

from nodelang import quiet_update as qu
from nodelang.universal_cell import InvalidCell

ROOT = Path(__file__).resolve().parents[1]
INSTALLED = ("20260916-2130-e733a13", "2026-09-16T17:24:00Z")
LATEST_PUBLIC = ("20260916-2105-b914892", "2026-09-16T16:47:18Z")
NEXT_PUBLIC = ("20260917-0900-0a1b2c3", "2026-09-17T05:00:00Z")
SAME_INSTANT = ("20260916-2131-0f0f0f0", INSTALLED[1])


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _founder_state(tmp_path, *, seen=None):
    app, state = tmp_path / "ArchHub", tmp_path / "ArchHub-Test"
    app.mkdir(parents=True)
    (app / "BUILD_ID").write_text(INSTALLED[0], encoding="utf-8")
    (app / "BUILD_METADATA.json").write_text(json.dumps(
        {"format": 1, "build_id": INSTALLED[0], "built_at": INSTALLED[1]}), encoding="utf-8")
    (state / "updates").mkdir(parents=True)
    (state / "updates" / "operation.lock").write_bytes(b"0")
    if seen is not None:
        (state / "updates" / "last-seen-build").write_text(seen, encoding="ascii")
    return app, state


def _release(build_id, built_at, installer):
    tag = "build-" + build_id
    body = "BUILD_ID: %s\nBUILT_AT: %s\nSHA256 %s: %s\nSOURCE_REVISION: 0\n\nArchHub desktop preview\n" % (
        build_id, built_at, qu.ASSET_NAME, hashlib.sha256(installer).hexdigest())
    return {"tag_name": tag, "draft": False, "prerelease": False, "body": body,
            "assets": [{"name": qu.ASSET_NAME, "size": len(installer),
                        "browser_download_url": "https://github.com/Fargaly/ArchHub/releases/download/%s/%s"
                        % (tag, qu.ASSET_NAME)}]}


def _awaiting_boot(phase):
    # The installed build is the staged one: apply_staged wrote awaiting_boot, or the
    # marker still says staged while BUILD_ID already equals it.
    def stage(app, state):
        installer = b"installed package " + INSTALLED[0].encode("ascii")
        (state / "updates" / qu.ASSET_NAME).write_bytes(installer)
        (state / "updates" / "staged.json").write_text(json.dumps({
            "build_id": INSTALLED[0], "built_at": INSTALLED[1], "sha256": hashlib.sha256(installer).hexdigest(),
            "url": "https://github.com/Fargaly/ArchHub/releases/download/build-%s/%s" % (INSTALLED[0], qu.ASSET_NAME),
            "tag": "build-" + INSTALLED[0], "phase": phase}), encoding="utf-8")
    return stage


def _controller(app, state, **options):
    from nodelang.application_update import ApplicationUpdate
    return ApplicationUpdate(state, app, request_restart=lambda: None, **options)


def _run_checks(tmp_path, monkeypatch, offered, *, count=1, api_error=None, stage=None, **options):
    app, state = _founder_state(tmp_path, seen=INSTALLED[0])
    if stage is not None:
        stage(app, state)
    installer = b"installer for " + offered[0].encode("ascii")
    requests = []

    def opener(request, timeout=0):
        requests.append(request.full_url)
        if request.full_url == qu.RELEASE_API:
            if api_error is not None:
                raise api_error
            return _Response(json.dumps(_release(offered[0], offered[1], installer)).encode("utf-8"))
        return _Response(installer)

    monkeypatch.setattr(qu, "stage_if_newer", functools.partial(qu.stage_if_newer, opener=opener))
    update = _controller(app, state, **options)
    try:
        for _ in range(count):
            update.check()
            update._worker.join(10)
            assert not update._worker.is_alive()
        return {"status": update.status(), "requests": requests, "state": state, "app": app,
                "installer": installer}
    finally:
        assert update.close(timeout_seconds=2)


def _launcher(names, **bindings):
    path = ROOT / "launch_archhub_test.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    selected = [node for node in tree.body if getattr(node, "name", None) in names]
    assert {node.name for node in selected} == set(names), "the launcher defines " + ", ".join(sorted(names))
    namespace = dict(bindings)
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


def test_founder_installed_build_is_not_offered_the_older_public_release(tmp_path, monkeypatch):
    held = _run_checks(tmp_path, monkeypatch, LATEST_PUBLIC)
    status = held["status"]
    assert status["state"] == "idle", status
    assert status["available_build"] is None, "an older release is never shown as available"
    assert status["current_build"] == INSTALLED[0]
    assert status["detail"] == ("Up to date. The latest release %s is not newer than the installed build %s."
                                % (LATEST_PUBLIC[0], INSTALLED[0]))
    assert held["requests"] == [qu.RELEASE_API], "an older release is never downloaded"
    assert not (held["state"] / "updates" / qu.ASSET_NAME).exists()
    assert not (held["state"] / "updates" / "staged.json").exists()
    assert (held["app"] / "BUILD_ID").read_text(encoding="utf-8") == INSTALLED[0]


def test_a_build_awaiting_boot_confirmation_is_up_to_date_not_failed(tmp_path, monkeypatch):
    held = _run_checks(tmp_path, monkeypatch, NEXT_PUBLIC, stage=_awaiting_boot("awaiting_boot"))
    assert held["requests"] == [], "no request reaches the release API while a build awaits boot confirmation"
    assert held["status"]["state"] == "idle", held["status"]
    assert held["status"]["available_build"] is None


@pytest.mark.parametrize("phase", ["awaiting_boot", "staged"])
def test_a_build_awaiting_boot_confirmation_reads_no_release_and_logs_exactly_that(tmp_path, monkeypatch, phase):
    lines, pushed = [], []
    held = _run_checks(tmp_path, monkeypatch, NEXT_PUBLIC, stage=_awaiting_boot(phase),
                       report=lines.append, on_ready=lambda: pushed.append(phase))
    assert held["requests"] == [], "no request reaches the release API while a build awaits boot confirmation"
    status = held["status"]
    assert status["state"] == "idle" and status["available_build"] is None, status
    assert status["detail"] == "Up to date. Build %s was just installed." % INSTALLED[0]
    assert lines == ["check: installed build %s is awaiting boot confirmation; nothing offered" % INSTALLED[0]]
    assert pushed == [], "nothing new is pushed to the Studio"
    marker = json.loads((held["state"] / "updates" / "staged.json").read_text(encoding="utf-8"))
    assert marker["phase"] == phase, "a release check never acknowledges a boot"


@pytest.mark.parametrize("offered, decision", [
    (NEXT_PUBLIC, "newer"),
    (INSTALLED, "same"),
    (LATEST_PUBLIC, "older"),
    (SAME_INSTANT, "older"),
])
def test_each_check_decides_says_so_once_and_pushes_only_a_ready_release(tmp_path, monkeypatch, offered, decision):
    lines, pushed = [], []
    held = _run_checks(tmp_path, monkeypatch, offered, report=lines.append,
                       on_ready=lambda: pushed.append(threading.current_thread().name))
    status, updates = held["status"], held["state"] / "updates"
    if decision == "newer":
        assert status["state"] == "ready" and status["available_build"] == offered[0]
        assert status["detail"] == "Build %s is downloaded and verified. Restart to update." % offered[0]
        download = _release(offered[0], offered[1], held["installer"])["assets"][0]["browser_download_url"]
        assert held["requests"] == [qu.RELEASE_API, download]
        assert (updates / qu.ASSET_NAME).read_bytes() == held["installer"]
        assert lines == ["check: newer release %s staged and ready (installed %s)" % (offered[0], INSTALLED[0])]
        assert pushed == ["archhub-update-download"], "a ready download is pushed once, from the download worker"
    else:
        assert status["state"] == "idle" and status["available_build"] is None
        assert held["requests"] == [qu.RELEASE_API]
        assert not (updates / qu.ASSET_NAME).exists() and not (updates / "staged.json").exists()
        expected = ("check: up to date (installed %s is the latest release)" % INSTALLED[0] if decision == "same" else
                    "check: latest release %s is not newer than installed %s; nothing offered" % (offered[0], INSTALLED[0]))
        assert lines == [expected]
        assert pushed == []
    assert (held["app"] / "BUILD_ID").read_text(encoding="utf-8") == INSTALLED[0], "a check never installs"
    assert all(line.isascii() and "\n" not in line for line in lines)


def test_every_check_writes_its_own_line_and_a_failed_check_names_its_reason(tmp_path, monkeypatch):
    lines = []
    held = _run_checks(tmp_path, monkeypatch, LATEST_PUBLIC, count=2, report=lines.append)
    assert lines == ["check: latest release %s is not newer than installed %s; nothing offered"
                     % (LATEST_PUBLIC[0], INSTALLED[0])] * 2
    assert held["requests"] == [qu.RELEASE_API, qu.RELEASE_API]
    offline, pushed = [], []
    down = _run_checks(tmp_path / "offline", monkeypatch, NEXT_PUBLIC, report=offline.append,
                       on_ready=lambda: pushed.append(1), api_error=OSError("network unreachable"))
    assert down["status"]["state"] == "failed" and down["status"]["available_build"] is None
    assert offline == ["check: failed -- no release information"]
    assert pushed == []


def test_a_log_or_push_failure_never_changes_the_decision(tmp_path, monkeypatch):
    def broken(*args):
        raise OSError("launcher log or window closed")
    held = _run_checks(tmp_path, monkeypatch, NEXT_PUBLIC, report=broken, on_ready=broken)
    assert held["status"]["state"] == "ready" and held["status"]["available_build"] == NEXT_PUBLIC[0]


def test_a_local_install_is_confirmed_once_and_dismiss_acknowledges_it(tmp_path):
    # His case: no record of a previous build, a saved graph, and a new BUILD_ID.
    from nodelang.application_update import application_update_action
    app, state = _founder_state(tmp_path)
    update = _controller(app, state)
    owner = SimpleNamespace(application_update=update)
    try:
        status = update.status()
        assert (status.get("updated_from"), status.get("updated_to")) == (None, INSTALLED[0]), status
        assert status["state"] == "idle" and status["available_build"] is None
        assert update.status().get("updated_to") == INSTALLED[0], "reading status never acknowledges"
        after = application_update_action(owner, {"action": "acknowledge"})
        assert (after["updated_from"], after["updated_to"]) == (None, None)
        assert (state / "updates" / "last-seen-build").read_text(encoding="ascii") == INSTALLED[0]
        assert application_update_action(owner, {"action": "acknowledge"})["updated_to"] is None, "Dismiss twice is harmless"
        for body in ({"action": "install"}, {"action": "acknowledge", "build": INSTALLED[0]}, ["acknowledge"]):
            with pytest.raises(InvalidCell, match="Application update action is invalid"):
                application_update_action(owner, body)
    finally:
        assert update.close(timeout_seconds=1)
    later = _controller(app, state)
    try:
        status = later.status()
        assert "updated_to" in status and status["updated_to"] is None, "the next boot of that build says nothing"
    finally:
        assert later.close(timeout_seconds=1)


def test_a_release_or_local_update_names_both_builds_until_dismissed_across_restarts(tmp_path):
    app, state = _founder_state(tmp_path, seen=LATEST_PUBLIC[0])
    for _ in range(2):
        update = _controller(app, state)
        try:
            status = update.status()
            assert (status.get("updated_from"), status.get("updated_to")) == (LATEST_PUBLIC[0], INSTALLED[0]), status
        finally:
            assert update.close(timeout_seconds=1)
    assert (state / "updates" / "last-seen-build").read_text(encoding="ascii") == LATEST_PUBLIC[0]
    update = _controller(app, state)
    try:
        status = update.acknowledge()
        assert (status["updated_from"], status["updated_to"]) == (None, None)
    finally:
        assert update.close(timeout_seconds=1)
    assert (state / "updates" / "last-seen-build").read_text(encoding="ascii") == INSTALLED[0]


@pytest.mark.parametrize("case", ["new install", "same build", "unversioned build"])
def test_nothing_is_confirmed_without_an_update(tmp_path, case):
    app, state = _founder_state(tmp_path, seen=INSTALLED[0] if case == "same build" else None)
    options = {"first_boot": True} if case == "new install" else {}
    if case == "unversioned build":
        (app / "BUILD_ID").unlink()
    record = state / "updates" / "last-seen-build"
    for boot in (options, {}):
        update = _controller(app, state, **boot)
        try:
            status = update.status()
            assert "updated_to" in status and (status["updated_from"], status["updated_to"]) == (None, None), status
        finally:
            assert update.close(timeout_seconds=1)
        if case == "unversioned build":
            assert not record.exists()
        else:
            assert record.read_text(encoding="ascii") == INSTALLED[0], "a new install records its build silently"


def test_a_dismiss_that_cannot_be_saved_keeps_the_confirmation(tmp_path):
    app, state = _founder_state(tmp_path)
    (state / "updates" / "last-seen-build").mkdir()
    update = _controller(app, state)
    try:
        assert update.status().get("updated_to") == INSTALLED[0]
        with pytest.raises(InvalidCell, match="could not be saved"):
            update.acknowledge()
        assert update.status()["updated_to"] == INSTALLED[0], "the confirmation stays until it is recorded"
    finally:
        assert update.close(timeout_seconds=1)


def test_launcher_prints_each_check_decision_as_one_update_line():
    report = _launcher({"_report_update_check"})["_report_update_check"]
    written = io.StringIO()
    with redirect_stdout(written):
        report("check: x")
    assert written.getvalue() == "  update     : check: x\n"
    # Supplementary: the controller the launcher builds carries that sink, the push and the boot knowledge.
    source = (ROOT / "launch_archhub_test.py").read_text(encoding="utf-8")
    start = source.index("server.application_update = ApplicationUpdate(")
    construction = source[start:source.index("\n\n", start)]
    for fragment in ("report=_report_update_check", "on_ready=_update_push.ready.emit", "first_boot=first_boot"):
        assert fragment in construction, fragment
    assert source.index("first_boot = not _saved_graph_exists(") < start


def test_a_ready_download_is_pushed_to_the_studio_on_the_qt_thread():
    qt_core = pytest.importorskip("PyQt6.QtCore")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    push_class = _launcher({"_UpdatePush"}, __name__="update_push_court", _UpdateObject=qt_core.QObject,
                           _update_signal=qt_core.pyqtSignal, _update_slot=qt_core.pyqtSlot,
                           _UpdateQt=qt_core.Qt)["_UpdatePush"]
    scripts = []
    page = SimpleNamespace(runJavaScript=lambda script: scripts.append(
        (script, qt_core.QThread.currentThread() == app.thread())))
    push = push_class(app, page)
    try:
        worker = threading.Thread(target=push.ready.emit, name="archhub-update-download")
        worker.start()
        worker.join(2)
        assert not worker.is_alive() and scripts == [], "the download worker never touches the page"
        app.processEvents()
        assert len(scripts) == 1 and scripts[0][1] is True, scripts
        assert "window.ARCHHUB_EXISTING_WORKSHOP.refreshApplicationUpdate()" in scripts[0][0]
    finally:
        push.deleteLater()
        app.processEvents()
