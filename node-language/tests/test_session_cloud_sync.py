"""Cross-device sync of node-graph SESSIONS — the half cloud_sync was
missing.

What this pins
--------------
Node-graph sessions already save/load locally (`app/session_io.py`,
proven by test_session_save_contract.py). cloud_sync.py already syncs
Skills to a private GitHub-backed cache repo, but its docstring claimed
"Skills + Sessions storage" while only skills were ever wired — sessions
never left the machine. This test is the executable contract for the
sessions half:

  1. cloud_sync exposes `sessions_dir()` (mirrors `skills_dir()`) +
     `sync_sessions()` + a `status()` the bridge slot can call.
  2. A small graph session written into the live SESSIONS_DIR survives a
     full round-trip — mirror into the cache, clear the live dir, mirror
     back — with its graph {nodes, wires} byte-identical. This is the
     cross-device behaviour ("edit on device A → appears on device B").
  3. A session file larger than the size cap is SKIPPED (not pushed into
     the gh-backed repo) and the skip is reported with a reason — no
     silent truncation. Some real sessions are >40MB because they inline
     base64 image _attachments; those must not bloat the sync repo.

RED before sessions_dir()/sync wiring exists (AttributeError /
NameError), GREEN after.

These tests never touch the network: they exercise the local mirror +
gate logic only, with the git push/pull layer monkeypatched out. The
push/pull plumbing is already covered by test_cloud.py.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_ROOT))

SESSION_EXT = ".archhub-session.json"


def _small_graph_session() -> dict:
    """A realistic small node-graph session payload — the v1.4 graph-first
    schema written by session_io.save_session (id + name + saved_at +
    graph{nodes, wires})."""
    return {
        "id": "sess_roundtrip_001",
        "name": "Rhino envelope study",
        "saved_at": "2026-06-18T12:00:00",
        "parameters": [],
        "chain": [],
        "graph": {
            "nodes": [
                {"id": "h_rhino_a1", "cat": "host", "title": "Rhino",
                 "x": 40, "y": 60},
                {"id": "c_chat_b2", "cat": "ai", "title": "Conversation",
                 "x": 320, "y": 60,
                 "messages": [{"role": "user", "text": "list layers"}]},
                {"id": "f_filter_c3", "cat": "filter", "title": "Filter",
                 "x": 600, "y": 60},
            ],
            "wires": [
                {"id": "w1", "from": "h_rhino_a1", "to": "c_chat_b2"},
                {"id": "w2", "from": "c_chat_b2", "to": "f_filter_c3"},
            ],
        },
    }


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Isolate cloud_sync's cache + session_io's live SESSIONS_DIR into
    tmp dirs, and stub the network (git push/pull + initialised check) so
    the mirror logic runs without a real repo."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    import cloud_sync
    import session_io

    cache = tmp_path / "ArchHub" / "data_repo"
    cache.mkdir(parents=True, exist_ok=True)
    live_sessions = tmp_path / "ArchHub" / "sessions"
    live_sessions.mkdir(parents=True, exist_ok=True)

    # cloud_sync froze _CACHE_DIR / _CACHE_ROOT at import time off the
    # original LOCALAPPDATA — re-stamp them onto tmp_path.
    monkeypatch.setattr(cloud_sync, "_CACHE_ROOT", tmp_path / "ArchHub")
    monkeypatch.setattr(cloud_sync, "_CACHE_DIR", cache)
    # session_io froze SESSIONS_DIR the same way.
    monkeypatch.setattr(session_io, "SESSIONS_DIR", live_sessions)

    # Pretend the cache repo is cloned + the network is a no-op so
    # sync_sessions() exercises the mirror + gate, not git.
    monkeypatch.setattr(cloud_sync, "is_initialised", lambda: True)
    monkeypatch.setattr(
        cloud_sync, "pull",
        lambda: cloud_sync.SyncResult(True, "pull stub"))
    monkeypatch.setattr(
        cloud_sync, "push",
        lambda msg="": cloud_sync.SyncResult(True, "push stub"))

    return {
        "cloud_sync": cloud_sync,
        "session_io": session_io,
        "cache": cache,
        "live": live_sessions,
        "tmp": tmp_path,
    }


# ---------------------------------------------------------------------------
class TestSessionsApiExists:
    """The new entrypoints must exist + mirror the skills API shape.
    These are the RED-first assertions — sessions_dir / sync_sessions
    don't exist before the wiring lands."""

    def test_sessions_dir_exists_and_is_under_cache(self, env):
        cs = env["cloud_sync"]
        assert hasattr(cs, "sessions_dir"), \
            "cloud_sync must expose sessions_dir() (mirror of skills_dir())"
        sd = cs.sessions_dir()
        assert isinstance(sd, Path)
        # Lives inside the cache repo, alongside skills/.
        assert cs.cache_dir() in sd.parents

    def test_sessions_dir_distinct_from_skills_dir(self, env):
        cs = env["cloud_sync"]
        assert cs.sessions_dir() != cs.skills_dir()

    def test_sync_sessions_entrypoint_exists(self, env):
        cs = env["cloud_sync"]
        assert hasattr(cs, "sync_sessions"), \
            "cloud_sync must expose sync_sessions() (push+pull)"
        res = cs.sync_sessions()
        # Returns a SyncResult-like object the bridge can render.
        assert hasattr(res, "success")
        assert hasattr(res, "message")

    def test_status_reports_session_count(self, env):
        """status() must surface a session count so the bridge slot /
        UI can show 'N sessions synced'."""
        cs = env["cloud_sync"]
        st = cs.status()
        assert hasattr(st, "sessions"), \
            "SyncStatus must carry a `sessions` count for the UI"


# ---------------------------------------------------------------------------
class TestRoundTrip:
    """The core cross-device contract: a small graph session pushed up
    comes back byte-identical after the live dir is wiped."""

    def test_graph_session_round_trips_identical(self, env):
        cs = env["cloud_sync"]
        live = env["live"]
        cache = env["cache"]

        payload = _small_graph_session()
        original = json.dumps(payload, indent=2, sort_keys=True)
        sess_file = live / f"rhino-envelope-study{SESSION_EXT}"
        sess_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        # PUSH side: mirror live -> cache (+ stubbed git push).
        res = cs.sync_sessions()
        assert res.success, f"sync_sessions failed: {res.message}"

        # The file must now be in the cache sessions/ subdir.
        cached = cs.sessions_dir() / sess_file.name
        assert cached.exists(), \
            "session was not mirrored into the cloud cache"

        # Simulate device B / a fresh machine: wipe the live dir, keep
        # only the cache (what a `git pull` would have produced).
        sess_file.unlink()
        assert not sess_file.exists()
        assert list(live.glob(f"*{SESSION_EXT}")) == []

        # PULL side: mirror cache -> live (+ stubbed git pull).
        res2 = cs.sync_sessions()
        assert res2.success, f"second sync failed: {res2.message}"

        restored = live / sess_file.name
        assert restored.exists(), \
            "session did not come back from the cloud cache"

        # The graph {nodes, wires} must be IDENTICAL.
        got = json.loads(restored.read_text(encoding="utf-8"))
        assert json.dumps(got, indent=2, sort_keys=True) == original
        assert got["graph"]["nodes"] == payload["graph"]["nodes"]
        assert got["graph"]["wires"] == payload["graph"]["wires"]

    def test_round_trip_loads_via_session_io(self, env):
        """End-to-end: the restored file must load back through the real
        session_io.load_session as a Session with the graph intact —
        proving sync produced a genuinely usable session, not just bytes."""
        cs = env["cloud_sync"]
        sio = env["session_io"]
        live = env["live"]

        payload = _small_graph_session()
        sess_file = live / f"rhino-envelope-study{SESSION_EXT}"
        sess_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        cs.sync_sessions()                 # push: live -> cache
        sess_file.unlink()                 # device B starts empty
        cs.sync_sessions()                 # pull: cache -> live

        restored = live / sess_file.name
        session, name = sio.load_session(restored)
        assert name == "Rhino envelope study"
        assert session.graph is not None
        assert len(session.graph["nodes"]) == 3
        assert len(session.graph["wires"]) == 2


# ---------------------------------------------------------------------------
class TestSizeCapGate:
    """Large blobs (>cap) must be skipped with a logged reason so the
    gh-backed repo never bloats on a 40MB inline-attachment session."""

    def test_oversize_session_is_skipped_with_reason(self, env, caplog):
        cs = env["cloud_sync"]
        live = env["live"]

        # Small session: should sync.
        small = _small_graph_session()
        small_file = live / f"small{SESSION_EXT}"
        small_file.write_text(json.dumps(small), encoding="utf-8")

        # Oversize session: pad with a fake inline base64 attachment so
        # the file blows past the cap.
        big = _small_graph_session()
        big["id"] = "sess_big_002"
        big["_attachments"] = {"img": "A" * (cs.SESSION_SIZE_CAP_BYTES + 1024)}
        big_file = live / f"big{SESSION_EXT}"
        big_file.write_text(json.dumps(big), encoding="utf-8")
        assert big_file.stat().st_size > cs.SESSION_SIZE_CAP_BYTES

        import logging
        with caplog.at_level(logging.WARNING):
            res = cs.sync_sessions()

        assert res.success

        # Small one made it; big one did NOT.
        assert (cs.sessions_dir() / small_file.name).exists()
        assert not (cs.sessions_dir() / big_file.name).exists(), \
            "oversize session must be skipped, not pushed into the repo"

        # The skip must be reported — in the result detail AND the log —
        # naming the file + the reason (no silent truncation).
        blob = (res.detail + " " + caplog.text).lower()
        assert "big" in blob, "skip report must name the skipped file"
        assert ("skip" in blob or "too large" in blob
                or "cap" in blob or "over" in blob), \
            "skip report must give a reason"

    def test_cap_is_a_sane_default(self, env):
        cs = env["cloud_sync"]
        # The cap exists and is a few MB — big enough for real graph
        # sessions, small enough to stop 40MB attachment blobs.
        assert hasattr(cs, "SESSION_SIZE_CAP_BYTES")
        assert 1_000_000 <= cs.SESSION_SIZE_CAP_BYTES <= 20_000_000

    def test_skipped_count_surfaced_in_status(self, env):
        """A skipped oversize file should not silently vanish — the
        result must let the caller know N were skipped."""
        cs = env["cloud_sync"]
        live = env["live"]
        big = _small_graph_session()
        big["_attachments"] = {"img": "A" * (cs.SESSION_SIZE_CAP_BYTES + 2048)}
        (live / f"huge{SESSION_EXT}").write_text(
            json.dumps(big), encoding="utf-8")

        res = cs.sync_sessions()
        assert res.success
        # Detail mentions the skip so the UI can show it.
        assert "huge" in res.detail.lower()
