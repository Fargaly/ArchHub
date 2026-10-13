import time
import threading
from types import SimpleNamespace

from nodelang.native_contact import (
    RUNTIME_RETIRE_KIND,
    project_native_agent_rows,
    retire_stale_native_runtimes,
)
from nodelang.runtime_presence_lease_storage import RuntimePresenceLeaseStorage
from nodelang.universal_cell import CellStore


def _owner(storage):
    return SimpleNamespace(
        universal_registry=SimpleNamespace(application_root="app-root"),
        universal_store=SimpleNamespace(revision=0),
        native_recipient_relay=SimpleNamespace(
            _channel_lock=threading.Lock(),
            _pending_jobs={},
        ),
        _ownership_record_storage=lambda: storage,
    )


def test_native_sessions_collapse_to_one_named_row_per_agent_app():
    rows = []
    for index in range(30):
        app = ("claude", "codex", "opencode", "antigravity")[index % 4]
        rows.append({"app": app, "id": f"{app}-{index}", "title": f"Runtime-{index:08x}", "cwd": "work"})

    projected = project_native_agent_rows(rows)

    assert [row["title"] for row in projected] == ["Antigravity", "Claude", "Codex", "OpenCode"]
    assert sum(row["session_count"] for row in projected) == 30
    assert all("Runtime-" not in row["title"] for row in projected)


def test_stale_runtime_retirement_is_reversible_and_live_safe(tmp_path):
    path = tmp_path / "runtime.sqlite3"
    CellStore(path).close()
    storage = RuntimePresenceLeaseStorage(path)
    owner = _owner(storage)
    now = time.time()
    stale = {"app": "claude", "id": "stale-a", "connected": False, "last_seen_at": now - 90000}
    live = {"app": "claude", "id": "live-a", "connected": True, "last_seen_at": now - 90000}

    retired = retire_stale_native_runtimes(owner, [stale, live], hours=24, now=now)

    assert len(retired) == 1
    assert storage.list_records(RUNTIME_RETIRE_KIND, states=("retired",))[0]["payload"]["session_id"] == "stale-a"
    storage.put_record(RUNTIME_RETIRE_KIND, retired[0], owner_root="app-root", state="restored",
        payload={"kind": "native-runtime-retirement", "version": 1, "restored": True},
        authority_revision=0, updated_at=now + 1, event="restore")
    reopened = RuntimePresenceLeaseStorage(path)
    try:
        assert reopened.list_records(RUNTIME_RETIRE_KIND, states=("retired",)) == []
        assert reopened.list_records(RUNTIME_RETIRE_KIND, states=("restored",))[0]["record_root"] == retired[0]
    finally:
        storage.close()
        reopened.close()
