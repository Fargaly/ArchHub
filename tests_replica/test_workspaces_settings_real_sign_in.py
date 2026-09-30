"""Settings -> Workspaces through the REAL browser sign-in, exactly as the Studio
page does it: POST /api/universal/session with the page's canvas key, then the
workspace-roots route with the token and CSRF that sign-in returned. Founder
report 2026-09-30 (fb28e88): "browser CSRF digest drifted" on read and Add."""
import json

import pytest
import sys
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_workspace_roots_owner_route import ROUTE, runtime  # noqa: E402,F401


def _call(server, path, payload, headers):
    request = Request(server.url + path, data=json.dumps(payload).encode("utf-8"),
                      headers={"Content-Type": "application/json", **headers}, method="POST")
    try:
        with urlopen(request, timeout=60) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8"))


def _sign_in(server):
    status, session = _call(server, "/api/universal/session", {},
                            {"X-ArchHub-Sign-In": "1", "X-ArchHub-Canvas-Key": server.clean_canvas_key})
    assert status == 200, session
    return session


def _roots(server, session, payload):
    return _call(server, ROUTE, payload,
                 {"X-ArchHub-Session": session["token"], "X-ArchHub-CSRF": session["csrf"]})


def test_a_signed_in_page_reads_and_adds_workspaces(runtime, tmp_path):
    server, _built, _home, _tmp = runtime
    session = _sign_in(server)
    status, listed = _roots(server, session, {"action": "list"})
    assert status == 200, listed
    folder = tmp_path / "E-01.PERSONAL"
    folder.mkdir()
    status, added = _roots(server, session, {"action": "register", "id": "personal",
                                             "path": str(folder), "privacy": "private",
                                             "profile": "client", "writers": ["claude"]})
    assert status == 200, added
    # The same page, after the graph moved: the held session still reads.
    status, listed = _roots(server, session, {"action": "list"})
    assert status == 200, listed
    # A second page signs in and is handed the live session: both pairs answer.
    again = _sign_in(server)
    for held in (session, again):
        status, listed = _roots(server, held, {"action": "list"})
        assert status == 200, (held == again, listed)


def test_browse_returns_the_folder_the_owner_picked_and_changes_nothing(runtime, monkeypatch, tmp_path):
    """Browse answers with the dialog's folder only; nothing is registered and the
    graph does not move. The dialog itself is replaced here (no window in a court)."""
    from nodelang import workspace_roots_catalogue as roots
    server, built, _home, _tmp = runtime
    session = _sign_in(server)
    picked = tmp_path / "Clients" / "BBC4"
    picked.mkdir(parents=True)
    monkeypatch.setattr(roots, "pick_workspace_folder", lambda: str(picked))
    revision = built.location.authority.store.revision
    status, answer = _roots(server, session, {"action": "browse"})
    assert status == 200 and answer["path"] == str(picked), answer
    assert built.location.authority.store.revision == revision
    monkeypatch.setattr(roots, "pick_workspace_folder", lambda: "")  # cancelled
    status, answer = _roots(server, session, {"action": "browse"})
    assert status == 200 and answer["path"] == "", answer
    status, answer = _roots(server, session, {"action": "browse", "path": "C:/x"})
    assert status != 200, answer
    status, answer = _call(server, ROUTE, {"action": "browse"},
                           {"X-ArchHub-Session": session["token"], "X-ArchHub-CSRF": "wrong"})
    assert status == 403, answer


def test_the_picker_accepts_only_a_local_folder(monkeypatch):
    import subprocess
    from nodelang import workspace_roots_catalogue as roots

    class Done:
        def __init__(self, out, code=0):
            self.stdout, self.returncode = out, code

    for out, expected in ((b"E:/01.PERSONAL", "E:\\01.PERSONAL"),
                          ("E:/Clients/ملف".encode("utf-8"), "E:\\Clients\\ملف"), (b"", "")):
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: Done(out))
        assert roots.pick_workspace_folder() == expected
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Done(b"\\\\server\\share"))
    with pytest.raises(roots.WorkspaceRootRefused):
        roots.pick_workspace_folder()
