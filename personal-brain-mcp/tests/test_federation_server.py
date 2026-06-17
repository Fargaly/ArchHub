"""BRV-11 — federation HTTP outbox + reputations must survive a restart.

Root cause (origin/main): `federation_server.create_app` built a *process-local*
`Outbox` ("in-memory for now; persist via store in V2") and a `reputations: dict`
that lived only in the closure. The sibling runtime `publish_worker.py` already
persists its outbox to the `fragments` table — so the federation HTTP server had
a DIVERGENT, volatile second outbox. Restart the daemon → both were lost.

These tests pin the V2 behaviour: the server's outbox + reputation registry are
backed by the SAME brain store (no parallel store, ONE-SYSTEM), so an app-factory
re-create over the same store re-loads them.

Persistence is what we assert, NOT the HTTP transport — so the tests drive the
route *handlers* directly through `create_app(...).state` helpers, which makes
them run without `httpx`/`TestClient` (kept dependency-light, matching the rest
of the suite). The same handlers are what FastAPI mounts.
"""
from __future__ import annotations

import pytest

from personal_brain.storage import BrainStore

fastapi = pytest.importorskip("fastapi")  # server module needs FastAPI present

from personal_brain.federation_server import create_app  # noqa: E402
from personal_brain.federation import ContributorReputation  # noqa: E402


def _store(tmp_path):
    # File-backed (NOT ':memory:') so a second BrainStore.open over the same
    # path sees the first store's committed rows — this is the "restart" the
    # leaf requires (':memory:' is per-connection and would hide the bug).
    return BrainStore.open(tmp_path / "brain.db")


def test_outbox_activity_survives_app_factory_recreate(tmp_path):
    """An activity published into the outbox of one app instance must be
    present in the outbox of a fresh app built over the same store."""
    db = tmp_path / "brain.db"
    store_a = BrainStore.open(db)
    app_a = create_app(store_a, firm_id="archhub-inc",
                        base_url="http://x", actor_url="http://x/actor")

    # Publish a pattern into app_a's outbox via the persistence helper the
    # /publish route uses (real path, no HTTP server needed).
    pid = app_a.state.federation_persist_demo_pattern("survivor-pattern")
    assert pid, "publish helper should return the pattern id"
    assert any(a.object.get("pattern_id") == pid
               for a in app_a.state.federation_outbox.activities)
    store_a.close()

    # ── restart: brand-new store handle + brand-new app over the same DB ──
    store_b = BrainStore.open(db)
    app_b = create_app(store_b, firm_id="archhub-inc",
                        base_url="http://x", actor_url="http://x/actor")
    reloaded = [a.object.get("pattern_id")
                for a in app_b.state.federation_outbox.activities]
    assert pid in reloaded, (
        "outbox activity was lost on app-factory re-create — the federation "
        "outbox is still in-memory-only (BRV-11 not fixed)"
    )
    store_b.close()


def test_reputation_row_survives_app_factory_recreate(tmp_path):
    """A contributor reputation recorded by one app instance must be present
    in a fresh app built over the same store."""
    db = tmp_path / "brain.db"
    store_a = BrainStore.open(db)
    app_a = create_app(store_a, firm_id="archhub-inc",
                       base_url="http://x", actor_url="http://x/actor")

    rep = ContributorReputation(contributor_id="peer-firm-hash",
                                accepted_count=7, rejected_count=1)
    app_a.state.federation_save_reputation(rep)
    assert "peer-firm-hash" in app_a.state.federation_reputations
    store_a.close()

    store_b = BrainStore.open(db)
    app_b = create_app(store_b, firm_id="archhub-inc",
                       base_url="http://x", actor_url="http://x/actor")
    reloaded = app_b.state.federation_reputations.get("peer-firm-hash")
    assert reloaded is not None, (
        "reputation row was lost on app-factory re-create — the reputation "
        "registry is still an in-memory dict (BRV-11 not fixed)"
    )
    assert reloaded.accepted_count == 7
    assert reloaded.rejected_count == 1
    store_b.close()
