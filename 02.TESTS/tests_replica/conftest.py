"""Disposable file-owner fixtures and guards against live profile and host writes."""
from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "03.TOOLS"))
from tools.real_app_check.profile_guard import _real_profile_paths, _deny_profile_write as _guard_profile_write
from functools import partial

_REAL_PROFILE_PATHS = _real_profile_paths()
_PROFILE_WRITE_ATTEMPTS = []
_deny_profile_write = partial(_guard_profile_write, protected=_REAL_PROFILE_PATHS,
                              attempts=_PROFILE_WRITE_ATTEMPTS)

# Install before application imports/collection; caught refusals still fail session teardown.
sys.addaudithook(_deny_profile_write)

# Collection imports must also see only disposable profile paths.
_COLLECTION_PROFILE = tempfile.TemporaryDirectory(prefix="PROFILE-", dir=os.environ.get("TEMP"))
for _name, _suffix in (("USERPROFILE", ""), ("HOME", ""), ("LOCALAPPDATA", "LOCAL"),
                       ("APPDATA", "ROAMING"), ("TEMP", "TMP"), ("TMP", "TMP")):
    _path = Path(_COLLECTION_PROFILE.name) / _suffix
    _path.mkdir(parents=True, exist_ok=True)
    os.environ[_name] = str(_path)

import pytest


@pytest.fixture(scope="session", autouse=True)
def no_live_profile_writes(tmp_path_factory):
    with pytest.MonkeyPatch.context() as patch:
        _isolate_profile(tmp_path_factory.mktemp("PROFILE"), patch)
        yield
    assert not _PROFILE_WRITE_ATTEMPTS, _PROFILE_WRITE_ATTEMPTS


@pytest.fixture(autouse=True)
def isolated_profile(tmp_path, monkeypatch, no_live_profile_writes):
    """Every server fixture starts with its own home, registry and app key path."""
    return _isolate_profile(tmp_path / "PROFILE", monkeypatch)


def _isolate_profile(home, monkeypatch):
    local = home / "LOCAL"
    local.mkdir(parents=True)
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setenv("ARCHHUB_TEST_STATE_DIR", str(local / "ArchHub"))
    monkeypatch.setenv("APPDATA", str(home / "ROAMING"))
    temporary = home / "TMP"
    temporary.mkdir()
    monkeypatch.setenv("TEMP", str(temporary))
    monkeypatch.setenv("TMP", str(temporary))
    return home


def pytest_terminal_summary(terminalreporter):
    terminalreporter.write_line("PROFILE-WRITE-GUARD: protected write attempts=" + str(len(_PROFILE_WRITE_ATTEMPTS)))




# ---------------------------------------------------------------------------
# No court may reach a live host. On 2026-09-06 the founder had Revit 2025
# open with the ArchHub broker on :48884 while the library shape court ran
# the Revit authoring cards with nothing stubbed: the C# went to his model
# (it failed closed only because of a compile error and a nested
# transaction). A court that can write into the founder's model is not a
# court. Every test starts with the hosts unreachable; a test that needs a
# host fakes it with its own monkeypatch, which wins over this one.
import pytest as _pytest


@_pytest.fixture(autouse=True)
def no_live_hosts(monkeypatch):
    import nodelang.clean_revit_adapter as _revit
    import nodelang.host_brokers as _hosts
    import nodelang.library_engines as _library

    def _refuse(*_args, **_kwargs):
        raise AssertionError("a court tried to reach a live host")

    monkeypatch.setattr(_revit, "live_sessions", lambda: [])
    monkeypatch.setattr(_revit, "_call", _refuse)
    monkeypatch.setattr(_hosts, "_com_alive", lambda _prog_id: False)
    monkeypatch.setattr(_hosts, "_port_open", lambda *_a, **_k: False)
    monkeypatch.setattr(_library, "_OUTLOOK", [lambda: None])
    monkeypatch.setattr(_library, "_NOTIFY_SURFACE", [])


class _CourtCredentialStore:
    """The host-bridge signing secret's store for one court, in memory."""

    def __init__(self):
        self.saved = {}

    def load_api_key(self, name):
        return self.saved.get(name)

    def save_api_key(self, name, value):
        self.saved[name] = value

    def delete_api_key(self, name):
        self.saved.pop(name, None)

    def list_keys(self):
        return list(self.saved)


# Children the courts start, and any copy of app/secrets_store.py loaded by
# path (model_router does), refuse the OS store on this variable alone.
import os as _os
_os.environ["ARCHHUB_TEST_SECRET_STORE"] = "memory"


@_pytest.fixture(autouse=True)
def no_real_credential_store(monkeypatch):
    # host_bridge_auth.ensure_secret creates the bridge secret in the app's
    # credential store -- on Windows the person's Credential Locker -- the
    # first time anything signs a bridge call. A court that reached a signed
    # call with nothing stubbed wrote the REAL entry. Every court keeps keys
    # in memory for that test, whichever way it reaches the store: the
    # imported host_bridge_auth, a copy of it loaded by path or reloaded
    # (both import app.secrets_store, whose functions are replaced too), a
    # by-path copy of app/secrets_store.py, or a child process (the
    # variable). A court that needs its own store replaces _store (or
    # ensure_secret) with its own monkeypatch.
    import app.secrets_store as _secrets
    import nodelang.host_bridge_auth as _auth
    store = _CourtCredentialStore()
    monkeypatch.setenv("ARCHHUB_TEST_SECRET_STORE", "memory")
    monkeypatch.setattr(_auth, "_store", lambda: store)
    for name in ("load_api_key", "save_api_key", "delete_api_key", "list_keys"):
        monkeypatch.setattr(_secrets, name, getattr(store, name))
    return store


@_pytest.fixture(autouse=True)
def no_configured_model_default(monkeypatch):
    # Courts never read this machine's real settings default_model: with no pick,
    # the composer's default route (2026-09-23) would otherwise send with it.
    # Courts that need it restore it with a fixture settings store.
    import nodelang.model_router as _router
    monkeypatch.setattr(_router, "default_composer_route", lambda **_kwargs: ("", ""), raising=False)




def _no_live_coordination_service():
    raise AssertionError(
        "a court reached for the live coordination service (:8474); pin "
        "workspace_roots_catalogue.graph_context to a court host instead")


def pytest_configure(config):
    """Before collection and before ANY fixture: no court can reach the live
    graph owner or ensure a key in the live caller ring through the workspace-
    roots current-state check. A court that proves the seam pins its own
    context (test_workspace_roots_graph_current.py)."""
    from nodelang import workspace_roots_catalogue

    workspace_roots_catalogue.graph_context = _no_live_coordination_service
