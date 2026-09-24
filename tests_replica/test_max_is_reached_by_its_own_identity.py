"""Court (fix 4): 3ds Max is reached only through a listener that answers as MaxMCP.

Founder report 2026-09-23: 3ds Max was hard-coded to 127.0.0.1:48886, the port AutoCAD's
broker listens on, so MAXScript went to AutoCAD. MaxMCP binds the first free port from
48886 to 48899 and answers /max-mcp/ping with service "max-mcp"
(bridges/sources/max_mcp/max_mcp_startup.py). Sockets and HTTP answers are fixtures:
the signed exec call (_bridge_call) is faked too, so no court reaches a live 3ds Max
or the credential store the signing secret lives in.
"""
import importlib
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import app.secrets_store as _secrets
from nodelang import host_brokers as hosts

ROOT = Path(__file__).resolve().parents[1]
# The real store functions, taken at import, before any court fixture runs.
# The store courts below compare identities only; none of them calls these.
_STORE_NAMES = ("load_api_key", "save_api_key", "delete_api_key", "list_keys")
_REAL_STORE = tuple(getattr(_secrets, name) for name in _STORE_NAMES)

ACAD, MAX = 48886, 48887


def _fake(monkeypatch, listening):
    sent = []

    def port_open(port, timeout=0.15):
        return port in listening

    def http(url, body=None, headers=None, timeout=20.0):
        sent.append((url, body))
        if ":%d/" % ACAD in url:
            return {"status": "error", "error": "Unknown route: /max-mcp/ping"}
        if url.endswith("/max-mcp/ping"):
            return {"status": "ok", "service": "max-mcp", "version": "0.2.0"}
        return {"status": "ok", "result": "ran"}

    def bridge_call(url, body=None, timeout=20.0):
        return http(url, body, timeout=timeout)
    monkeypatch.setattr(hosts, "_port_open", port_open)
    monkeypatch.setattr(hosts, "_http", http)
    monkeypatch.setattr(hosts, "_bridge_call", bridge_call)
    monkeypatch.setattr(hosts, "_running", lambda names: False, raising=False)
    monkeypatch.setattr(hosts, "_installed", lambda paths: False, raising=False)
    return sent


def test_maxscript_goes_to_the_listener_that_answers_as_maxmcp_never_to_autocad(monkeypatch):
    sent = _fake(monkeypatch, {ACAD, MAX})
    out, said = hosts.max_exec({"code": "box()"}, {})
    assert said == "ran in 3ds Max", (said, sent)
    executed = [(url, body) for url, body in sent if body is not None]
    assert executed == [("http://127.0.0.1:%d/max-mcp/exec_maxscript" % MAX, {"script": "box()"})], sent
    assert not any(":%d/" % ACAD in url and body is not None for url, body in sent), "nothing is sent to AutoCAD"


def test_autocad_alone_is_not_3ds_max(monkeypatch):
    sent = _fake(monkeypatch, {ACAD})
    out, said = hosts.max_exec({"code": "box()"}, {})
    assert out["ok"] is False and "max-mcp" in said, said
    assert all(body is None for _url, body in sent), "no MAXScript was sent anywhere: %r" % sent
    row = next(row for row in hosts.probe_host_rows() if row["id"] == "max")
    assert row["state"] != "connected", row


def test_a_court_signs_with_a_secret_held_in_memory_never_the_credential_store():
    """conftest.no_real_credential_store: ensure_secret never reaches app.secrets_store in a court."""
    from nodelang import host_bridge_auth as auth
    store = auth._store()
    assert type(store).__name__ == "_CourtCredentialStore", store
    secret = auth.ensure_secret()
    assert store.saved == {auth.PROVIDER: secret}


def _reaches_real_store(store) -> bool:
    return any(getattr(store, name, None) is real for name, real in zip(_STORE_NAMES, _REAL_STORE))


def test_host_bridge_auth_loaded_by_path_never_reaches_the_real_store():
    spec = importlib.util.spec_from_file_location("_court_host_bridge_auth",
                                                  ROOT / "nodelang" / "host_bridge_auth.py")
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    assert not _reaches_real_store(loaded._store()), loaded._store()


def test_host_bridge_auth_reloaded_never_reaches_the_real_store():
    from nodelang import host_bridge_auth as auth
    importlib.reload(auth)
    assert not _reaches_real_store(auth._store()), auth._store()


def test_a_by_path_copy_of_the_secrets_store_refuses_the_os_store():
    """model_router loads app/secrets_store.py by path; that copy is not the patched module."""
    spec = importlib.util.spec_from_file_location("_court_secrets_store", ROOT / "app" / "secrets_store.py")
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    assert getattr(loaded, "os_store_refused", lambda: False)(), "the copy would use keyring"


def test_a_child_process_refuses_the_os_store():
    probe = ("from app import secrets_store as s; "
             "print(getattr(s, 'os_store_refused', lambda: False)())")
    ran = subprocess.run([sys.executable, "-c", probe], cwd=ROOT, capture_output=True, text=True,
                         timeout=60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert ran.stdout.strip() == "True", (ran.stdout, ran.stderr[-500:])


def test_the_memory_store_outside_a_court_is_refused_not_obeyed():
    """The variable alone, with no pytest running, must not switch a real install to memory keys."""
    probe = ("from app import secrets_store as s\n"
             "try:\n    s.os_store_refused()\n"
             "except RuntimeError as refused:\n    print('refused:', refused)\n"
             "else:\n    print('obeyed')\n")
    env = {k: v for k, v in os.environ.items() if k != "PYTEST_VERSION"}
    env["ARCHHUB_TEST_SECRET_STORE"] = "memory"
    ran = subprocess.run([sys.executable, "-c", probe], cwd=ROOT, env=env, capture_output=True, text=True,
                         timeout=60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert ran.stdout.strip() == ("refused: ARCHHUB_TEST_SECRET_STORE=memory is for courts only; unset it"), (
        ran.stdout, ran.stderr[-500:])


def test_the_max_row_names_the_port_maxmcp_answers_on(monkeypatch):
    _fake(monkeypatch, {ACAD, MAX})
    row = next(row for row in hosts.probe_host_rows() if row["id"] == "max")
    assert row["state"] == "connected" and ":%d" % MAX in row["detail"], row
