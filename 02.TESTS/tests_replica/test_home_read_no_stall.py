"""Behavioral court for Home reads (readHomeLayout + listSessionModel) under real HTTP/1.1 keep-alive load.

Verifies on a running NoGraphServer over a 6-connection HTTP/1.1 keep-alive pool (matching Chromium's
per-origin socket cap):
1. Navigating Home -> Canvas -> Home while Canvas autosaves, head/catalogue polls, dock layout writes,
   Workshop SQLite BEGIN IMMEDIATE write transactions, and DesktopAccess(bind_resume=True) run concurrently
   completes within the bounded home_load_ms budget with zero HTTP errors and zero dropped task/recentTask rows.
2. Large (> 1 MiB) .archhub session files in Sessions do not cause repeated full-graph re-parse stalls on
   Home session listing or head/catalogue polls, while fresh edits immediately appear in listSessionModel.
3. Half-open idle TCP connections do not starve Home reads or hang server.close().
4. home_load_ms defaults to the measured 5000 ms budget (within _APPLICATION_SETTING_SPECS bounds, not 290000 ms)
   and propagates user/node edits via setApplicationSetting into both /studio/studio.html ARCHHUB_BOOT and
   /api/universal/canvas runtime_parameters.
"""
from __future__ import annotations

import http.client
import json
import os
import queue
import re
import socket
import sqlite3
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import pytest


class _KeepAlivePool:
    """Chromium-equivalent 6-socket HTTP/1.1 keep-alive connection pool to one origin."""

    def __init__(self, host: str, port: int, size: int = 6, timeout: float = 10.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._pool: queue.Queue[http.client.HTTPConnection] = queue.Queue()
        self._conns: list[http.client.HTTPConnection] = []
        for _ in range(size):
            conn = http.client.HTTPConnection(host, port, timeout=timeout)
            self._pool.put(conn)
            self._conns.append(conn)

    def request_json(self, method: str, path: str, headers: dict, body: dict | None = None):
        raw = json.dumps(body).encode("utf-8") if body is not None else b""
        req_headers = {
            **headers,
            "Connection": "keep-alive",
        }
        if body is not None:
            req_headers["Content-Type"] = "application/json"
            req_headers["Content-Length"] = str(len(raw))
        t0 = time.perf_counter()
        conn = self._pool.get()
        try:
            try:
                conn.request(method, path, body=raw if body is not None else None, headers=req_headers)
                resp = conn.getresponse()
                payload = resp.read()
                status = resp.status
            except (http.client.HTTPException, OSError):
                conn.close()
                conn = http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)
                conn.request(method, path, body=raw if body is not None else None, headers=req_headers)
                resp = conn.getresponse()
                payload = resp.read()
                status = resp.status
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            parsed = json.loads(payload.decode("utf-8")) if payload else {}
            return status, parsed, elapsed_ms
        finally:
            self._pool.put(conn)

    def close(self):
        for conn in self._conns:
            try:
                conn.close()
            except OSError:
                pass


@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    for name in ("USERPROFILE", "HOME", "LOCALAPPDATA", "APPDATA", "TEMP", "TMP"):
        folder = tmp_path / name
        folder.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv(name, str(folder))
    state = tmp_path / "state"
    transport = tmp_path / "transport"
    state.mkdir(parents=True, exist_ok=True)
    transport.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("ARCHHUB_TEST_STATE_DIR", str(state))
    monkeypatch.setenv("WORKSHOP_STATE_DIR", str(transport))
    return tmp_path, state


def _percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * quantile))))
    return ordered[idx]


def test_home_reads_stay_bounded_and_keep_tasks_under_canvas_save_and_sqlite_write_lock(isolated_env, monkeypatch):
    tmp_path, state_dir = isolated_env
    from nodelang import cloud_session, cloud_signin, session_files, workshop_tasks
    from nodelang.library_engines import LIBRARY_ITEM_ENGINES
    from nodelang.nograph_server import JsonFile, NoGraphServer
    from nodelang.workshop_mailbox import ROOM, application_history, profile_database

    record = tmp_path / "cloud" / "cloud.json"
    token = "ah_" + ("t" * 40)
    cloud_signin.write_cloud_session(record, {
        "token": token,
        "email": "qa@example.com",
        "user_id": "u-home",
        "cloud_base_url": "https://api.archhub.io",
        "expires_at": 4102444800,
    })
    cloud_signin.desktop_resume_key(record)

    fetch_calls = []

    def fake_fetch(_url, bearer):
        fetch_calls.append(bearer)
        return (200, {"user_id": "u-home", "email": "qa@example.com", "plan": "studio"}) if bearer == token else (401, {})

    gate = cloud_session.DesktopAccess(record, fetch=fake_fetch, fresh_for=60.0)
    auth = gate.check(bind_resume=True)
    assert auth["admitted"] and auth["subject"] == "u-home"

    tower = tmp_path / "Work" / "Tower"
    tower.mkdir(parents=True, exist_ok=True)
    JsonFile(state_dir / "settings" / "workspaces.json", {}).write({
        "roots": [{"root_id": "tower", "label": "Tower", "path": str(tower)}]
    })

    seeded_tasks = []
    with application_history() as history:
        history.ensure_conversation(ROOM)
        for idx in range(12):
            created = workshop_tasks.create_session(
                history,
                f"Home coordination {idx:02d}",
                select=(idx == 0),
                workspace="tower" if idx % 2 == 0 else "",
            )
            tid = created["taskId"]
            tpath = Path(created["path"])
            doc = session_files.read_document(tpath)
            doc["nodes"].append({
                "id": f"num-{idx}",
                "item": "n_number",
                "type": "data.constant",
                "title": "Number",
                "params": {"value": idx},
                "position": {"x": 140, "y": 90},
            })
            session_files.write_document(tpath, doc)
            workshop_tasks.claim(history, tid, f"builder-{idx % 3}", f"Builder {idx % 3}")
            if idx < 2:
                workshop_tasks.record_step(
                    history, tid, f"builder-{idx % 3}", f"Builder {idx % 3}", f"Step {idx}", "running"
                )
            seeded_tasks.append((tid, str(tpath), session_files.read_document(tpath)))

    # Seed standalone workflows including a > 1.5 MiB canvas (verifying large-canvas caching)
    big_doc = session_files.new_document("Large site coordination")
    big_chunk = "X" * 16000
    for idx in range(110):
        big_doc["nodes"].append({
            "id": f"big-{idx}",
            "item": "n_text",
            "type": "data.constant",
            "title": f"Sheet {idx}",
            "params": {"value": big_chunk},
            "position": {"x": (idx % 10) * 180, "y": (idx // 10) * 120},
        })
    big_path = session_files.document_path(session_files.sessions_directory(), big_doc)
    session_files.write_document(big_path, big_doc)
    assert Path(big_path).stat().st_size > (1 << 20)

    for idx in range(12):
        doc = session_files.new_document(f"Workflow {idx:02d}")
        p = session_files.document_path(session_files.sessions_directory(), doc)
        session_files.write_document(p, doc)

    past = time.time() - 5.0
    for item in session_files.sessions_directory().glob("*.archhub"):
        os.utime(item, (past, past))

    active_tid, active_path, active_doc = seeded_tasks[0]
    files_owner = session_files.SessionFiles(sign_resume_pointer=auth["_sign_resume_pointer"])
    files_owner.dispatch({"action": "open", "path": active_path})

    monkeypatch.setattr(NoGraphServer, "_start_admitted_services", lambda _self: None)
    monkeypatch.setattr(NoGraphServer, "ensure_cloud_relay", lambda _self: None)
    server = NoGraphServer(state_dir, desktop_access=gate).start()
    port = urlparse(server.public_url).port
    headers = {
        "Origin": server.public_url,
        "X-ArchHub-Session": server.browser_session_token,
        "X-ArchHub-CSRF": server.browser_csrf_token,
        "X-ArchHub-Desktop-Subject": "u-home",
    }
    pool = _KeepAlivePool("127.0.0.1", port, size=6, timeout=10.0)
    half_open = None
    try:
        budget_ms = LIBRARY_ITEM_ENGINES["tool_workshop"]["params"]["home_load_ms"]
        assert budget_ms == 5000

        # Warm the session summary cache once, then hold an active SQLite BEGIN IMMEDIATE write transaction
        st0, res0, _ = pool.request_json("POST", "/api/session-model", headers, {"action": "list"})
        assert st0 == 200 and res0["count"] == 25 and res0["recentTask"] == active_tid

        # Hold an unclosed half-open client TCP socket alongside the 6-socket pool
        half_open = socket.create_connection(("127.0.0.1", port), timeout=5.0)

        # Verify an active Workshop SQLite writer transaction never stalls listSessionModel or drops task rows
        db_path = profile_database()
        held_writer = sqlite3.connect(db_path, isolation_level=None, timeout=5.0)
        held_writer.execute("BEGIN IMMEDIATE")
        held_writer.execute("UPDATE workshop_tasks SET purpose = 'saving-canvas' WHERE id = ?", (active_tid,))
        try:
            st_locked, res_locked, locked_ms = pool.request_json("POST", "/api/session-model", headers, {"action": "list"})
            assert st_locked == 200 and res_locked["ok"] is True
            locked_sessions = [s for g in res_locked["groups"] for s in g["sessions"]]
            assert sum(1 for s in locked_sessions if s.get("task")) == 12
            assert res_locked["recentTask"] == active_tid
            assert locked_ms < budget_ms
            # Also verify head poll on a step-bearing task does not block on the active SQLite write lock
            st_head, res_head, head_ms = pool.request_json(
                "POST", "/api/session-files", headers, {"action": "head", "path": active_path, "id": active_doc["id"]}
            )
            assert st_head == 200 and res_head["ok"] is True and head_ms < budget_ms
        finally:
            held_writer.execute("ROLLBACK")
            held_writer.close()

        # Run concurrent Canvas -> Home bursts over the shared 6-connection HTTP/1.1 keep-alive pool
        stop_bg = threading.Event()
        bg_failures = []

        def canvas_writer():
            cur = session_files.read_document(active_path)
            n = 0
            while not stop_bg.is_set():
                try:
                    n += 1
                    cur = {**cur, "viewport": {"x": n % 120, "y": n % 80, "zoom": 1.0}}
                    st_save, res_save, _ = pool.request_json("POST", "/api/session-files", headers, {
                        "action": "autosave", "path": active_path, "document": cur, "base": cur,
                    })
                    if st_save != 200 or not res_save.get("ok"):
                        bg_failures.append(("autosave", st_save, res_save))
                    else:
                        cur = res_save["document"]
                    pool.request_json("POST", "/api/session-files", headers, {"action": "head", "path": "", "id": "unsaved"})
                    pool.request_json("POST", "/api/session-files", headers, {"action": "catalogue"})
                    pool.request_json("POST", "/api/universal/settings-action", headers, {
                        "function": "setDockLayout",
                        "args": [{"left": {"w": 268, "c": bool(n % 2), "st": [{"p": ["workshop"], "a": "workshop", "h": 1, "c": False}]},
                                  "right": {"c": True, "st": [{"p": ["insp"], "a": "insp", "h": 1, "c": False}]}}],
                    })
                except Exception as exc:  # noqa: BLE001
                    bg_failures.append(("canvas_writer", repr(exc)))

        def sqlite_writer():
            n = 0
            while not stop_bg.is_set():
                try:
                    n += 1
                    wconn = sqlite3.connect(db_path, isolation_level=None, timeout=5.0)
                    try:
                        wconn.execute("BEGIN IMMEDIATE")
                        wconn.execute("UPDATE workshop_tasks SET purpose = ? WHERE id = ?", (f"turn-{n}", active_tid))
                        time.sleep(0.015)
                        wconn.execute("COMMIT")
                    finally:
                        wconn.close()
                    time.sleep(0.010)
                except Exception as exc:  # noqa: BLE001
                    bg_failures.append(("sqlite_writer", repr(exc)))

        def live_poller():
            while not stop_bg.is_set():
                try:
                    pool.request_json("POST", "/api/universal/workshop", headers, {"function": "listTasks", "args": []})
                    pool.request_json("POST", "/api/universal/agents-canvas", headers, {})
                except Exception as exc:  # noqa: BLE001
                    bg_failures.append(("live_poller", repr(exc)))

        threads = [
            threading.Thread(target=canvas_writer, daemon=True),
            threading.Thread(target=sqlite_writer, daemon=True),
            threading.Thread(target=live_poller, daemon=True),
        ]
        for thread in threads:
            thread.start()

        home_latencies = []
        list_latencies = []
        try:
            for _ in range(20):
                pair = {}

                def read_layout():
                    pair["layout"] = pool.request_json(
                        "POST", "/api/universal/settings-action", headers, {"function": "readHomeLayout", "args": []}
                    )

                def read_sessions():
                    pair["sessions"] = pool.request_json(
                        "POST", "/api/session-model", headers, {"action": "list"}
                    )

                t1 = threading.Thread(target=read_layout)
                t2 = threading.Thread(target=read_sessions)
                t1.start()
                t2.start()
                t1.join(timeout=10.0)
                t2.join(timeout=10.0)
                assert not t1.is_alive() and not t2.is_alive(), "Home read stalled on keep-alive connection"

                st_l, res_l, ms_l = pair["layout"]
                st_s, res_s, ms_s = pair["sessions"]
                assert st_l == 200 and res_l.get("ok") is True
                assert "homeLayout" in res_l["result"] and "homeMap" in res_l["result"]
                assert st_s == 200 and res_s.get("ok") is True
                flat = [s for g in res_s["groups"] for s in g["sessions"]]
                assert len(flat) == 25
                assert sum(1 for s in flat if s.get("task")) == 12
                assert res_s["recentTask"] == active_tid
                home_latencies.append(ms_l)
                list_latencies.append(ms_s)
        finally:
            stop_bg.set()
            for thread in threads:
                thread.join(timeout=5.0)

        assert not bg_failures, bg_failures
        assert _percentile(home_latencies, 0.95) < budget_ms
        assert _percentile(list_latencies, 0.95) < budget_ms
        assert len(fetch_calls) == 1, "Verified desktop session must stay cached across burst requests"

        # Fresh edit on the > 1 MiB session must appear immediately on the very next listSessionModel read
        st_edit, res_edit, _ = pool.request_json("POST", "/api/session-model", headers, {
            "action": "set", "path": str(big_path), "values": {"pinned": True, "project": "tower"},
        })
        assert st_edit == 200 and res_edit["session"]["pinned"] is True
        st_after, res_after, _ = pool.request_json("POST", "/api/session-model", headers, {"action": "list"})
        assert st_after == 200
        tower_group = next(g for g in res_after["groups"] if g["project"]["id"] == "tower")
        big_row = next(s for s in tower_group["sessions"] if s["path"] == str(big_path))
        assert big_row["pinned"] is True
    finally:
        if half_open is not None:
            half_open.close()
        pool.close()
        t_close = time.perf_counter()
        server.close()
        assert (time.perf_counter() - t_close) < 5.0


def test_home_load_ms_budget_default_and_live_propagation(isolated_env, monkeypatch):
    _tmp_path, state_dir = isolated_env
    from nodelang.library_engines import LIBRARY_ITEM_ENGINES
    from nodelang.nograph_server import NoGraphServer
    from nodelang.settings_owner import _APPLICATION_SETTING_SPECS

    spec_kind, spec_bounds = _APPLICATION_SETTING_SPECS["home_load_ms"]
    default_ms = LIBRARY_ITEM_ENGINES["tool_workshop"]["params"]["home_load_ms"]
    assert spec_kind == "number"
    assert default_ms == 5000
    assert spec_bounds["min"] <= default_ms <= spec_bounds["max"]
    assert default_ms % spec_bounds["step"] == 0

    monkeypatch.setattr(NoGraphServer, "_start_admitted_services", lambda _self: None)
    monkeypatch.setattr(NoGraphServer, "ensure_cloud_relay", lambda _self: None)
    server = NoGraphServer(state_dir).start()
    port = urlparse(server.public_url).port
    pool = _KeepAlivePool("127.0.0.1", port, size=2, timeout=10.0)
    try:
        # 1. Boot HTML carries default home_load_ms = 5000
        boot_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10.0)
        try:
            boot_conn.request(
                "GET",
                f"/studio/studio.html?bootstrap={server.browser_bootstrap_token}",
                headers={"Host": f"127.0.0.1:{port}"},
            )
            boot_resp = boot_conn.getresponse()
            html = boot_resp.read().decode("utf-8")
            assert boot_resp.status == 200
            cookie_header = boot_resp.getheader("Set-Cookie") or ""
            cookie_pair = cookie_header.split(";", 1)[0]
        finally:
            boot_conn.close()

        boot_match = re.search(r"window\.ARCHHUB_BOOT\s*=\s*(\{.*?\});", html)
        assert boot_match is not None
        boot_json = json.loads(boot_match.group(1))
        assert boot_json["home_load_ms"] == 5000

        headers = {
            "Origin": server.public_url,
            "Cookie": cookie_pair,
            "X-ArchHub-Session": server.browser_session_token,
            "X-ArchHub-CSRF": server.browser_csrf_token,
        }

        # 2. /api/universal/canvas exposes runtime_parameters.home_load_ms = 5000
        st_c0, canvas0, _ = pool.request_json("GET", "/api/universal/canvas", headers)
        assert st_c0 == 200
        assert canvas0["runtime_parameters"]["home_load_ms"] == 5000

        # 3. Updating home_load_ms via setApplicationSetting propagates to both r_canvas and studio.html boot JSON
        st_set, res_set, _ = pool.request_json("POST", "/api/universal/settings-action", headers, {
            "function": "setApplicationSetting",
            "args": ["home_load_ms", 8000],
        })
        assert st_set == 200 and res_set["result"]["home_load_ms"] == 8000

        st_c1, canvas1, _ = pool.request_json("GET", "/api/universal/canvas", headers)
        assert st_c1 == 200
        assert canvas1["runtime_parameters"]["home_load_ms"] == 8000

        reload_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10.0)
        try:
            reload_conn.request(
                "GET",
                "/studio/studio.html",
                headers={"Host": f"127.0.0.1:{port}", "Cookie": cookie_pair},
            )
            reload_resp = reload_conn.getresponse()
            reload_html = reload_resp.read().decode("utf-8")
            assert reload_resp.status == 200
        finally:
            reload_conn.close()
        reload_boot = json.loads(re.search(r"window\.ARCHHUB_BOOT\s*=\s*(\{.*?\});", reload_html).group(1))
        assert reload_boot["home_load_ms"] == 8000
    finally:
        pool.close()
        server.close()


def test_canvas_list_open_and_read_never_fail_under_held_editor_lock_on_large_archhub(isolated_env, monkeypatch):
    """MCP canvas.list_open and canvas.read (plus listSessionModel) never take canvas_documents.locked
    and never fail 'Another editor holds this file; retry.' while another editor holds the > 1 MiB .archhub
    edit lock (and metadata locks)."""
    import asyncio
    import subprocess
    import sys

    tmp_path, state_dir = isolated_env
    from nodelang import canvas_documents, cloud_session, cloud_signin, session_files
    from nodelang.native_agent_mcp import build_server
    from nodelang.nograph_server import JsonFile, NoGraphServer

    record = tmp_path / "cloud" / "cloud.json"
    token = "ah_" + ("r" * 40)
    cloud_signin.write_cloud_session(record, {
        "token": token,
        "email": "qa@example.com",
        "user_id": "u-lock",
        "cloud_base_url": "https://api.archhub.io",
        "expires_at": 4102444800,
    })
    cloud_signin.desktop_resume_key(record)
    gate = cloud_session.DesktopAccess(
        record,
        fetch=lambda _url, bearer: (200, {"user_id": "u-lock", "email": "qa@example.com", "plan": "studio"})
        if bearer == token else (401, {}),
        fresh_for=60.0,
    )
    auth = gate.check(bind_resume=True)
    assert auth["admitted"]

    # Create two > 1.5 MiB .archhub sessions (one open in app, one recent)
    big_chunk = "Y" * 16000
    large_open_doc = session_files.new_document("Large structural coordination")
    for idx in range(110):
        large_open_doc["nodes"].append({
            "id": f"struct-{idx}",
            "item": "n_text",
            "type": "data.constant",
            "title": f"Package {idx}",
            "params": {"value": big_chunk},
            "position": {"x": (idx % 10) * 180, "y": (idx // 10) * 120},
        })
    large_recent_doc = session_files.new_document("Large facade study")
    for idx in range(105):
        large_recent_doc["nodes"].append({
            "id": f"facade-{idx}",
            "item": "n_text",
            "type": "data.constant",
            "title": f"Elevation {idx}",
            "params": {"value": big_chunk},
            "position": {"x": (idx % 10) * 180, "y": (idx // 10) * 120},
        })

    sessions_dir = session_files.sessions_directory()
    large_open_path = session_files.document_path(sessions_dir, large_open_doc)
    large_recent_path = session_files.document_path(sessions_dir, large_recent_doc)
    session_files.write_document(large_open_path, large_open_doc)
    session_files.write_document(large_recent_path, large_recent_doc)
    assert Path(large_open_path).stat().st_size > (1 << 20)
    assert Path(large_recent_path).stat().st_size > (1 << 20)

    files_owner = session_files.SessionFiles(sign_resume_pointer=auth["_sign_resume_pointer"])
    files_owner.dispatch({"action": "open", "path": str(large_recent_path)})
    files_owner.dispatch({"action": "open", "path": str(large_open_path)})

    past = time.time() - 5.0
    for candidate in (large_open_path, large_recent_path):
        os.utime(candidate, (past, past))
    # Warm the stamped document cache once for the open file, leave the second large file uncached in _SESSION_FIELDS_CACHE
    session_files.read_document(large_open_path, shared=True)

    # Also stage an active file-move.json journal whose locks are held by a live editor process
    move_journal = JsonFile(state_dir / "data" / "sessions" / "file-move.json", {})
    move_journal.write({
        "old": str(large_open_path),
        "new": str(Path(large_open_path).with_name("Large structural coordination (renaming).archhub")),
        "id": large_open_doc["id"],
        "duplicate": False,
    })

    app_src = str(Path(__file__).resolve().parents[2] / "01.APP")
    holder_script = (
        "import os, sys, time\n"
        "from contextlib import ExitStack\n"
        "sys.path.insert(0, sys.argv[1])\n"
        "from nodelang import canvas_documents\n"
        "with ExitStack() as stack:\n"
        "    for target in sys.argv[2:]:\n"
        "        stack.enter_context(canvas_documents.locked(target, timeout=5.0))\n"
        "    sys.stdout.write('LOCKED\\n')\n"
        "    sys.stdout.flush()\n"
        "    sys.stdin.readline()\n"
    )
    lock_targets = [
        str(large_open_path),
        str(large_recent_path),
        str(files_owner.metadata / "recent.json"),
        str(files_owner.metadata / "current.json"),
        str(move_journal.path),
    ]
    holder = subprocess.Popen(
        [sys.executable, "-c", holder_script, app_src, *lock_targets],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=dict(os.environ),
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    mcp_server = build_server(desktop_access=gate)
    monkeypatch.setattr(NoGraphServer, "_start_admitted_services", lambda _self: None)
    monkeypatch.setattr(NoGraphServer, "ensure_cloud_relay", lambda _self: None)
    http_server = NoGraphServer(state_dir, desktop_access=gate).start()
    port = urlparse(http_server.public_url).port
    pool = _KeepAlivePool("127.0.0.1", port, size=2, timeout=5.0)
    try:
        ready_line = holder.stdout.readline().strip()
        assert ready_line == "LOCKED", holder.stderr.read()

        # Confirm the cross-process editor lock IS genuinely held (a writer attempt times out immediately)
        with pytest.raises(TimeoutError, match="Another editor holds this file; retry."):
            with canvas_documents.locked(large_open_path, timeout=0.05):
                pass

        def call_mcp(tool_name, **kwargs):
            t0 = time.perf_counter()
            raw = asyncio.run(mcp_server.call_tool(tool_name, kwargs))
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            content = raw[1] if isinstance(raw, tuple) else None
            payload = content.get("result", content) if isinstance(content, dict) else json.loads(raw[0].text)
            return payload, elapsed_ms

        # 1. MCP canvas.list_open returns immediately (< 200 ms) while all editor/metadata locks are held
        listed, list_ms = call_mcp("canvas.list_open")
        assert list_ms < 200.0, f"canvas.list_open took {list_ms:.1f} ms under held lock"
        assert [row["path"] for row in listed["files"]] == [str(large_open_path), str(large_recent_path)]
        assert listed["files"][0]["open_in_app"] is True
        assert listed["files"][0]["title"] == "Large structural coordination"
        assert listed["files"][1]["open_in_app"] is False
        assert listed["files"][1]["title"] == "Large facade study"

        # 2. MCP canvas.read and canvas.open also succeed without taking the edit lock
        summary_open, read_ms = call_mcp("canvas.read", path=str(large_open_path))
        assert read_ms < 200.0, f"canvas.read took {read_ms:.1f} ms on cached >1 MiB canvas"
        assert summary_open["title"] == "Large structural coordination"
        assert len(summary_open["nodes"]) == 110

        summary_recent, _ = call_mcp("canvas.open", path=str(large_recent_path))
        assert summary_recent["title"] == "Large facade study"
        assert len(summary_recent["nodes"]) == 105

        # 3. HTTP listSessionModel also succeeds without blocking on the held editor/metadata locks
        headers = {
            "Origin": http_server.public_url,
            "X-ArchHub-Session": http_server.browser_session_token,
            "X-ArchHub-CSRF": http_server.browser_csrf_token,
            "X-ArchHub-Desktop-Subject": "u-lock",
        }
        st_list, res_list, http_ms = pool.request_json("POST", "/api/session-model", headers, {"action": "list"})
        assert st_list == 200 and res_list["ok"] is True
        assert http_ms < 500.0
        listed_paths = {s["path"] for g in res_list["groups"] for s in g["sessions"]}
        assert {str(large_open_path), str(large_recent_path)} <= listed_paths
    finally:
        mcp_server._mailbox_stop()
        pool.close()
        http_server.close()
        try:
            if holder.stdin:
                holder.stdin.write("\n")
                holder.stdin.flush()
            holder.wait(timeout=5.0)
        except Exception:  # noqa: BLE001
            holder.kill()
            holder.wait(timeout=5.0)
        move_journal.path.unlink(missing_ok=True)
