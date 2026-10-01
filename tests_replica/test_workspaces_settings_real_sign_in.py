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


def test_browse_on_the_graph_owner_is_refused_visibly_and_changes_nothing(runtime, monkeypatch):
    """The graph's owner has no visible window: a folder dialog it opened would never
    be seen. Browse is the desktop window's own dialog; here it is refused, in words."""
    import subprocess
    server, built, _home, _tmp = runtime
    session = _sign_in(server)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("no dialog process may start"))
    revision = built.location.authority.store.revision
    status, answer = _roots(server, session, {"action": "browse"})
    assert status != 200 and "Open the ArchHub window to choose a folder" in answer["error"], answer
    assert built.location.authority.store.revision == revision
    status, answer = _roots(server, session, {"action": "browse", "path": "C:/x"})
    assert status != 200, answer
    status, answer = _call(server, ROUTE, {"action": "browse"},
                           {"X-ArchHub-Session": session["token"], "X-ArchHub-CSRF": "wrong"})
    assert status == 403, answer


def test_the_picker_accepts_only_a_local_folder():
    from nodelang import workspace_roots_catalogue as roots

    for chosen, expected in (("E:/01.PERSONAL", r"E:\01.PERSONAL"),
                             ("E:/Clients/ملف", r"E:\Clients\ملف"), ("", "")):
        assert roots.normalized_picked_folder(chosen) == expected
    with pytest.raises(roots.WorkspaceRootRefused):
        roots.normalized_picked_folder(r"\\server\share")
