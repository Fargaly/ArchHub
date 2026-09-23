"""Indexed runtime presence lease storage in the primary instance SQLite database.

Preserves the invariant that stable identity and authorization bindings (session,
device custody, runtime) remain Cells in the Universal Cell graph, while volatile
high-frequency lease timestamps (refreshed_at, expires_at) are maintained in an
indexed auxiliary table in the SAME primary instance SQLite database without
generating graph revisions or cell version bloat.

Explicit instance ownership: each application server or store instance explicitly
owns its lease storage without process globals, path inference, or cached handle leaks.
"""
from __future__ import annotations

import json
import math
from itertools import islice
import os
from pathlib import Path
import sqlite3
import threading
from typing import Any

from .universal_cell import InvalidCell


# SPEC 3.3: operational instances live in bounded indexed records in the same
# primary database, referenced by their graph-held capability. The closed set
# below is the only vocabulary a record may use; each kind is bounded.
OPERATIONAL_RECORD_KINDS = frozenset({
    "runtime-ownership",
    "browser-session",
    "runtime-presence",
    "steward-signal",
    "authorization-receipt",
    "compliance-event",
})
_OPERATIONAL_RECORD_LIMIT = 10_000
_OPERATIONAL_EVENT_LIMIT = 4_096


class RuntimePresenceLeaseStorage:
    """Explicit instance-owned lease storage backed by SQLite or an in-memory fallback."""

    def __init__(self, database_path: str | os.PathLike[str] | None = None) -> None:
        self._lock = threading.RLock()
        self._closed = False
        self._database_path: str | None = (
            str(Path(database_path).expanduser().resolve())
            if database_path is not None
            else None
        )
        self._connection: sqlite3.Connection | None = None
        self._memory_leases: dict[str, dict[str, Any]] = {}
        self._memory_tombstones: set[str] = set()
        self._memory_migrated: bool = False
        self._memory_activities: dict[str, dict[str, Any]] = {}
        self._memory_records: dict[tuple[str, str], dict[str, Any]] = {}
        self._memory_events: list[dict[str, Any]] = []
        self._memory_event_sequence = 0

        if self._database_path is not None:
            self._connection = sqlite3.connect(
                self._database_path,
                timeout=30.0,
                isolation_level=None,
                check_same_thread=False,
            )
            self._connection.execute("PRAGMA busy_timeout = 30000")
            self._ensure_schema()

    def _ensure_schema(self) -> None:
        if self._connection is None:
            return
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            self._connection.execute(
                "CREATE TABLE IF NOT EXISTS runtime_presence_leases ("
                "presence_root TEXT PRIMARY KEY, "
                "owner_token TEXT NOT NULL, "
                "refreshed_at REAL NOT NULL, "
                "expires_at REAL NOT NULL, "
                "generation INTEGER NOT NULL DEFAULT 1"
                ")"
            )
            self._connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_runtime_presence_leases_expires "
                "ON runtime_presence_leases(expires_at)"
            )
            self._connection.execute(
                "CREATE TABLE IF NOT EXISTS runtime_presence_tombstones ("
                "presence_root TEXT PRIMARY KEY, "
                "revoked_at REAL NOT NULL"
                ")"
            )
            self._connection.execute(
                "CREATE TABLE IF NOT EXISTS runtime_presence_migration ("
                "cutover_completed INTEGER PRIMARY KEY"
                ")"
            )
            self._connection.execute(
                "CREATE TABLE IF NOT EXISTS baboom_activities ("
                "activity_root TEXT PRIMARY KEY, "
                "agent_session_root TEXT NOT NULL, "
                "device_custody_root TEXT NOT NULL, "
                "app TEXT NOT NULL, "
                "observed_at REAL NOT NULL, "
                "expires_at REAL NOT NULL"
                ")"
            )
            self._connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_baboom_activities_expires "
                "ON baboom_activities(expires_at)"
            )
            self._connection.execute(
                "CREATE TABLE IF NOT EXISTS operational_records ("
                "kind TEXT NOT NULL, "
                "record_root TEXT NOT NULL, "
                "owner_root TEXT NOT NULL, "
                "state TEXT NOT NULL, "
                "generation INTEGER NOT NULL, "
                "authority_revision INTEGER NOT NULL, "
                "updated_at REAL NOT NULL, "
                "payload TEXT NOT NULL, "
                "PRIMARY KEY (kind, record_root))"
            )
            self._connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_operational_records_owner "
                "ON operational_records(kind, owner_root, state)"
            )
            self._connection.execute(
                "CREATE TABLE IF NOT EXISTS operational_events ("
                "sequence INTEGER PRIMARY KEY AUTOINCREMENT, "
                "kind TEXT NOT NULL, "
                "record_root TEXT NOT NULL, "
                "event TEXT NOT NULL, "
                "authority_revision INTEGER NOT NULL, "
                "recorded_at REAL NOT NULL, "
                "payload TEXT NOT NULL)"
            )
            self._connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_operational_events_record "
                "ON operational_events(kind, record_root, sequence)"
            )
            self._connection.execute("COMMIT")
        except Exception:
            self._connection.execute("ROLLBACK")
            raise

    @property
    def database_path(self) -> str | None:
        return self._database_path

    def create_initial_lease(
        self,
        presence_root: str,
        owner_token: str,
        refreshed_at: float,
        expires_at: float,
    ) -> int:
        if not isinstance(presence_root, str) or not presence_root:
            raise InvalidCell("presence_root must be a non-empty string")
        if not isinstance(owner_token, str) or not owner_token:
            raise InvalidCell("owner_token must be a non-empty string")
        if not (math.isfinite(refreshed_at) and math.isfinite(expires_at)):
            raise InvalidCell("refreshed_at and expires_at must be finite numbers")
        if not refreshed_at < expires_at:
            raise InvalidCell("refreshed_at must be less than expires_at")

        with self._lock:
            if self._closed:
                raise InvalidCell("RuntimePresenceLeaseStorage is closed")
            if self._connection is not None:
                in_tx = False
                try:
                    self._connection.execute("BEGIN IMMEDIATE")
                    in_tx = True
                    cur = self._connection.execute(
                        "SELECT 1 FROM runtime_presence_tombstones WHERE presence_root = ?",
                        (presence_root,),
                    )
                    if cur.fetchone() is not None:
                        self._connection.execute("ROLLBACK")
                        raise InvalidCell("runtime presence lease is revoked: fail closed")
                    try:
                        self._connection.execute(
                            "INSERT INTO runtime_presence_leases "
                            "(presence_root, owner_token, refreshed_at, expires_at, generation) "
                            "VALUES (?, ?, ?, ?, 1)",
                            (presence_root, owner_token, refreshed_at, expires_at),
                        )
                        self._connection.execute("COMMIT")
                        return 1
                    except sqlite3.IntegrityError as exc:
                        self._connection.execute("ROLLBACK")
                        raise InvalidCell(
                            "runtime presence lease already exists"
                        ) from exc
                except Exception:
                    if in_tx:
                        try:
                            self._connection.execute("ROLLBACK")
                        except Exception:
                            pass
                    raise
            else:
                if presence_root in self._memory_tombstones:
                    raise InvalidCell("runtime presence lease is revoked: fail closed")
                if presence_root in self._memory_leases:
                    raise InvalidCell("runtime presence lease already exists")
                self._memory_leases[presence_root] = {
                    "owner_token": owner_token,
                    "refreshed_at": refreshed_at,
                    "expires_at": expires_at,
                    "generation": 1,
                }
                return 1

    def renew_lease(
        self,
        presence_root: str,
        owner_token: str,
        refreshed_at: float,
        expires_at: float,
        *,
        expected_generation: int | None = None,
    ) -> int:
        if not isinstance(presence_root, str) or not presence_root:
            raise InvalidCell("presence_root must be a non-empty string")
        if not isinstance(owner_token, str) or not owner_token:
            raise InvalidCell("owner_token must be a non-empty string")
        if not (math.isfinite(refreshed_at) and math.isfinite(expires_at)):
            raise InvalidCell("refreshed_at and expires_at must be finite numbers")
        if not refreshed_at < expires_at:
            raise InvalidCell("refreshed_at must be less than expires_at")

        with self._lock:
            if self._closed:
                raise InvalidCell("RuntimePresenceLeaseStorage is closed")
            if self._connection is not None:
                in_tx = False
                try:
                    self._connection.execute("BEGIN IMMEDIATE")
                    in_tx = True
                    cur = self._connection.execute(
                        "SELECT 1 FROM runtime_presence_tombstones WHERE presence_root = ?",
                        (presence_root,),
                    )
                    if cur.fetchone() is not None:
                        self._connection.execute("ROLLBACK")
                        raise InvalidCell("runtime presence lease is revoked: fail closed")

                    cursor = self._connection.execute(
                        "SELECT owner_token, refreshed_at, expires_at, generation "
                        "FROM runtime_presence_leases WHERE presence_root = ?",
                        (presence_root,),
                    )
                    row = cursor.fetchone()
                    if row is None:
                        self._connection.execute("ROLLBACK")
                        raise InvalidCell("runtime presence lease not found")
                    curr_owner, curr_refreshed, curr_expires, curr_gen = row
                    if curr_owner != owner_token:
                        self._connection.execute("ROLLBACK")
                        raise InvalidCell(
                            "runtime presence lease owner mismatch: expected %s, got %s"
                            % (curr_owner, owner_token)
                        )
                    if refreshed_at <= curr_refreshed:
                        self._connection.execute("ROLLBACK")
                        raise InvalidCell(
                            "runtime presence renewal time must be strictly monotonic "
                            "(%.6f <= %.6f)" % (refreshed_at, curr_refreshed)
                        )
                    if (
                        expected_generation is not None
                        and curr_gen != expected_generation
                    ):
                        self._connection.execute("ROLLBACK")
                        raise InvalidCell(
                            "stale runtime presence lease writer: generation mismatch "
                            "(expected %d, found %d)" % (expected_generation, curr_gen)
                        )

                    gen_clause = "AND generation = ?" if expected_generation is not None else ""
                    params = [refreshed_at, expires_at, presence_root, owner_token, refreshed_at]
                    if expected_generation is not None:
                        params.append(expected_generation)

                    update_cur = self._connection.execute(
                        "UPDATE runtime_presence_leases "
                        "SET refreshed_at = ?, expires_at = ?, generation = generation + 1 "
                        f"WHERE presence_root = ? AND owner_token = ? AND refreshed_at < ? {gen_clause} "
                        "RETURNING generation",
                        tuple(params),
                    )
                    res = update_cur.fetchone()
                    if res is None:
                        self._connection.execute("ROLLBACK")
                        raise InvalidCell(
                            "concurrent runtime presence lease mutation conflict"
                        )
                    self._connection.execute("COMMIT")
                    return res[0]
                except Exception:
                    if in_tx:
                        try:
                            self._connection.execute("ROLLBACK")
                        except Exception:
                            pass
                    raise
            else:
                if presence_root in self._memory_tombstones:
                    raise InvalidCell("runtime presence lease is revoked: fail closed")
                entry = self._memory_leases.get(presence_root)
                if entry is None:
                    raise InvalidCell("runtime presence lease not found")
                if entry["owner_token"] != owner_token:
                    raise InvalidCell(
                        "runtime presence lease owner mismatch: expected %s, got %s"
                        % (entry["owner_token"], owner_token)
                    )
                if refreshed_at <= entry["refreshed_at"]:
                    raise InvalidCell(
                        "runtime presence renewal time must be strictly monotonic "
                        "(%.6f <= %.6f)" % (refreshed_at, entry["refreshed_at"])
                    )
                if (
                    expected_generation is not None
                    and entry["generation"] != expected_generation
                ):
                    raise InvalidCell(
                        "stale runtime presence lease writer: generation mismatch "
                        "(expected %d, found %d)" % (expected_generation, entry["generation"])
                    )
                entry["generation"] += 1
                entry["refreshed_at"] = refreshed_at
                entry["expires_at"] = expires_at
                return entry["generation"]

    def get_lease(
        self, presence_root: str
    ) -> tuple[float, float, int, str] | None:
        with self._lock:
            if self._closed:
                raise InvalidCell("RuntimePresenceLeaseStorage is closed")
            if self._connection is not None:
                cur = self._connection.execute(
                    "SELECT 1 FROM runtime_presence_tombstones WHERE presence_root = ?",
                    (presence_root,),
                )
                if cur.fetchone() is not None:
                    return None
                cursor = self._connection.execute(
                    "SELECT refreshed_at, expires_at, generation, owner_token "
                    "FROM runtime_presence_leases WHERE presence_root = ?",
                    (presence_root,),
                )
                row = cursor.fetchone()
                return (row[0], row[1], row[2], row[3]) if row is not None else None
            else:
                if presence_root in self._memory_tombstones:
                    return None
                entry = self._memory_leases.get(presence_root)
                if entry is None:
                    return None
                return (
                    entry["refreshed_at"],
                    entry["expires_at"],
                    entry["generation"],
                    entry["owner_token"],
                )

    def get_active_leases(
        self, now: float
    ) -> dict[str, tuple[float, float, int, str]]:
        current_time = float(now)
        with self._lock:
            if self._closed:
                raise InvalidCell("RuntimePresenceLeaseStorage is closed")
            if self._connection is not None:
                cursor = self._connection.execute(
                    "SELECT presence_root, refreshed_at, expires_at, generation, owner_token "
                    "FROM runtime_presence_leases "
                    "WHERE expires_at > ? AND presence_root NOT IN (SELECT presence_root FROM runtime_presence_tombstones)",
                    (current_time,),
                )
                return {
                    row[0]: (row[1], row[2], row[3], row[4])
                    for row in cursor.fetchall()
                }
            else:
                return {
                    root: (
                        entry["refreshed_at"],
                        entry["expires_at"],
                        entry["generation"],
                        entry["owner_token"],
                    )
                    for root, entry in self._memory_leases.items()
                    if current_time < entry["expires_at"] and root not in self._memory_tombstones
                }

    def delete_lease(
        self, presence_root: str, owner_token: str | None = None, *, now: float | None = None
    ) -> bool:
        t = float(now) if now is not None else 0.0
        with self._lock:
            if self._closed:
                raise InvalidCell("RuntimePresenceLeaseStorage is closed")
            if self._connection is not None:
                in_tx = False
                try:
                    self._connection.execute("BEGIN IMMEDIATE")
                    in_tx = True
                    cur = self._connection.execute(
                        "SELECT owner_token FROM runtime_presence_leases WHERE presence_root = ?",
                        (presence_root,),
                    )
                    row = cur.fetchone()
                    if row is None:
                        self._connection.execute("ROLLBACK")
                        return False
                    existing_owner = row[0]
                    if owner_token is not None and existing_owner != owner_token:
                        self._connection.execute("ROLLBACK")
                        return False
                    self._connection.execute(
                        "DELETE FROM runtime_presence_leases WHERE presence_root = ?",
                        (presence_root,),
                    )
                    self._connection.execute(
                        "INSERT OR REPLACE INTO runtime_presence_tombstones (presence_root, revoked_at) "
                        "VALUES (?, ?)",
                        (presence_root, t),
                    )
                    self._connection.execute("COMMIT")
                    return True
                except Exception:
                    if in_tx:
                        try:
                            self._connection.execute("ROLLBACK")
                        except Exception:
                            pass
                    raise
            else:
                entry = self._memory_leases.get(presence_root)
                if entry is None:
                    return False
                if owner_token is not None and entry["owner_token"] != owner_token:
                    return False
                self._memory_tombstones.add(presence_root)
                del self._memory_leases[presence_root]
                return True

    def migrate_legacy_leases(
        self, snapshot: Any, protocol: Any, *, now: float
    ) -> int:
        """Bounded atomic one-time migration of unexpired legacy graph leases to this storage."""
        with self._lock:
            if self._closed:
                raise InvalidCell("RuntimePresenceLeaseStorage is closed")
            if self._connection is not None:
                in_tx = False
                try:
                    self._connection.execute("BEGIN IMMEDIATE")
                    in_tx = True
                    cur = self._connection.execute(
                        "SELECT 1 FROM runtime_presence_migration WHERE cutover_completed = 1"
                    )
                    if cur.fetchone() is not None:
                        self._connection.execute("ROLLBACK")
                        return 0

                    from .cell_protocols import read_relation
                    roots = tuple(
                        member.participant_id
                        for member in read_relation(snapshot, protocol.root_id, budget=100_000)
                        if member.role_id == protocol.role("presence-member")
                    )
                    migrated_count = 0
                    for root in roots:
                        cur_lease = self._connection.execute(
                            "SELECT 1 FROM runtime_presence_leases WHERE presence_root = ?",
                            (root,),
                        ).fetchone()
                        if cur_lease is not None:
                            continue

                        cur_tomb = self._connection.execute(
                            "SELECT 1 FROM runtime_presence_tombstones WHERE presence_root = ?",
                            (root,),
                        ).fetchone()
                        if cur_tomb is not None:
                            continue

                        members = read_relation(snapshot, root, budget=128)
                        session_candidates = [
                            m.participant_id for m in members
                            if m.role_id == protocol.role("presence-agent-session")
                        ]
                        expires_candidates = [
                            m.participant_id for m in members
                            if m.role_id == protocol.role("presence-expires-at")
                        ]
                        refreshed_candidates = [
                            m.participant_id for m in members
                            if m.role_id == protocol.role("presence-refreshed-at")
                        ]
                        if not (session_candidates and expires_candidates and refreshed_candidates):
                            continue
                        session = session_candidates[0]
                        try:
                            graph_expires = float(snapshot.cells[expires_candidates[0]].atom.decode("utf-8"))
                            graph_refreshed = float(snapshot.cells[refreshed_candidates[0]].atom.decode("utf-8"))
                        except (KeyError, ValueError, UnicodeDecodeError):
                            continue
                        if now < graph_expires and graph_refreshed < graph_expires:
                            self._connection.execute(
                                "INSERT INTO runtime_presence_leases "
                                "(presence_root, owner_token, refreshed_at, expires_at, generation) "
                                "VALUES (?, ?, ?, ?, 1)",
                                (root, session, graph_refreshed, graph_expires),
                            )
                            migrated_count += 1

                    self._connection.execute(
                        "INSERT OR IGNORE INTO runtime_presence_migration (cutover_completed) VALUES (1)"
                    )
                    self._connection.execute("COMMIT")
                    return migrated_count
                except Exception:
                    if in_tx:
                        try:
                            self._connection.execute("ROLLBACK")
                        except Exception:
                            pass
                    raise
            else:
                if self._memory_migrated:
                    return 0
                from .cell_protocols import read_relation
                roots = tuple(
                    member.participant_id
                    for member in read_relation(snapshot, protocol.root_id, budget=100_000)
                    if member.role_id == protocol.role("presence-member")
                )
                migrated_count = 0
                for root in roots:
                    if root in self._memory_leases or root in self._memory_tombstones:
                        continue
                    members = read_relation(snapshot, root, budget=128)
                    session_candidates = [
                        m.participant_id for m in members
                        if m.role_id == protocol.role("presence-agent-session")
                    ]
                    expires_candidates = [
                        m.participant_id for m in members
                        if m.role_id == protocol.role("presence-expires-at")
                    ]
                    refreshed_candidates = [
                        m.participant_id for m in members
                        if m.role_id == protocol.role("presence-refreshed-at")
                    ]
                    if not (session_candidates and expires_candidates and refreshed_candidates):
                        continue
                    session = session_candidates[0]
                    try:
                        graph_expires = float(snapshot.cells[expires_candidates[0]].atom.decode("utf-8"))
                        graph_refreshed = float(snapshot.cells[refreshed_candidates[0]].atom.decode("utf-8"))
                    except (KeyError, ValueError, UnicodeDecodeError):
                        continue
                    if now < graph_expires and graph_refreshed < graph_expires:
                        self._memory_leases[root] = {
                            "owner_token": session,
                            "refreshed_at": graph_refreshed,
                            "expires_at": graph_expires,
                            "generation": 1,
                        }
                        migrated_count += 1
                self._memory_migrated = True
                return migrated_count

    @staticmethod
    def _row_to_activity_dict(row: tuple[Any, ...]) -> dict[str, Any]:
        return {
            "activity_root": row[0],
            "agent_session_root": row[1],
            "device_custody_root": row[2],
            "app": row[3],
            "observed_at": row[4],
            "expires_at": row[5],
        }

    def record_baboom_activity(self, activity_data: dict[str, Any]) -> dict[str, Any]:
        root = activity_data["activity_root"]
        with self._lock:
            if self._closed:
                raise InvalidCell("RuntimePresenceLeaseStorage is closed")
            if self._connection is not None:
                in_tx = False
                try:
                    self._connection.execute("BEGIN IMMEDIATE")
                    in_tx = True
                    head_row = self._connection.execute(
                        "SELECT MAX(revision) FROM revisions"
                    ).fetchone()
                    head = head_row[0] if head_row and head_row[0] is not None else 0
                    if head != activity_data["authority_revision"]:
                        self._connection.execute("ROLLBACK")
                        raise InvalidCell("BABOOM activity authority revision is stale")
                    cur = self._connection.execute(
                        "SELECT agent_session_root, device_custody_root, observed_at, expires_at "
                        "FROM baboom_activities WHERE activity_root = ?",
                        (root,),
                    )
                    row = cur.fetchone()
                    if row is not None:
                        if (
                            row[0] != activity_data["agent_session_root"]
                            or row[1] != activity_data["device_custody_root"]
                        ):
                            self._connection.execute("ROLLBACK")
                            raise InvalidCell("BABOOM activity binding drifted")
                        if activity_data["observed_at"] < row[2]:
                            self._connection.execute("ROLLBACK")
                            raise InvalidCell("BABOOM activity observation is stale")
                        self._connection.execute(
                            "UPDATE baboom_activities SET app = ?, observed_at = ?, expires_at = ? WHERE activity_root = ?",
                            (
                                activity_data["app"],
                                activity_data["observed_at"],
                                activity_data["expires_at"],
                                root,
                            ),
                        )
                    else:
                        self._connection.execute(
                            "INSERT INTO baboom_activities "
                            "(activity_root, agent_session_root, device_custody_root, app, observed_at, expires_at) "
                            "VALUES (?, ?, ?, ?, ?, ?)",
                            (
                                root,
                                activity_data["agent_session_root"],
                                activity_data["device_custody_root"],
                                activity_data["app"],
                                activity_data["observed_at"],
                                activity_data["expires_at"],
                            ),
                        )
                    self._connection.execute("COMMIT")
                    return {
                        "activity_root": root,
                        "agent_session_root": activity_data["agent_session_root"],
                        "device_custody_root": activity_data["device_custody_root"],
                        "app": activity_data["app"],
                        "observed_at": activity_data["observed_at"],
                        "expires_at": activity_data["expires_at"],
                    }
                except Exception:
                    if in_tx:
                        try:
                            self._connection.execute("ROLLBACK")
                        except Exception:
                            pass
                    raise
            else:
                existing = self._memory_activities.get(root)
                if existing is not None:
                    if (
                        existing["agent_session_root"] != activity_data["agent_session_root"]
                        or existing["device_custody_root"] != activity_data["device_custody_root"]
                    ):
                        raise InvalidCell("BABOOM activity binding drifted")
                    if activity_data["observed_at"] < existing["observed_at"]:
                        raise InvalidCell("BABOOM activity observation is stale")
                stored = {
                    "activity_root": root,
                    "agent_session_root": activity_data["agent_session_root"],
                    "device_custody_root": activity_data["device_custody_root"],
                    "app": activity_data["app"],
                    "observed_at": activity_data["observed_at"],
                    "expires_at": activity_data["expires_at"],
                }
                self._memory_activities[root] = stored
                return dict(stored)

    def read_baboom_activity_row(self, activity_root: str) -> dict[str, Any] | None:
        with self._lock:
            if self._closed:
                raise InvalidCell("RuntimePresenceLeaseStorage is closed")
            if self._connection is not None:
                cur = self._connection.execute(
                    "SELECT activity_root, agent_session_root, device_custody_root, app, observed_at, expires_at "
                    "FROM baboom_activities WHERE activity_root = ?",
                    (activity_root,),
                )
                row = cur.fetchone()
                return self._row_to_activity_dict(row) if row is not None else None
            stored = self._memory_activities.get(activity_root)
            return dict(stored) if stored is not None else None

    def list_baboom_activity_rows(self, limit: int = 1000) -> list[dict[str, Any]]:
        if type(limit) is not int or not 1 <= limit <= 10001:
            raise InvalidCell("BABOOM activity limit must be between 1 and 10001")
        with self._lock:
            if self._closed:
                raise InvalidCell("RuntimePresenceLeaseStorage is closed")
            if self._connection is not None:
                cur = self._connection.execute(
                    "SELECT activity_root, agent_session_root, device_custody_root, app, observed_at, expires_at "
                    "FROM baboom_activities ORDER BY activity_root LIMIT ?",
                    (limit,),
                )
                return [self._row_to_activity_dict(row) for row in cur.fetchall()]
            return [dict(stored) for stored in islice(self._memory_activities.values(), limit)]

    def list_active_baboom_activity_rows(self, now: float, limit: int = 1000) -> list[dict[str, Any]]:
        if type(limit) is not int or not 1 <= limit <= 10001:
            raise InvalidCell("BABOOM activity limit must be between 1 and 10001")
        if isinstance(now, bool) or not isinstance(now, (float, int)) or not math.isfinite(now):
            raise InvalidCell("BABOOM activity current time must be finite")
        with self._lock:
            if self._closed:
                raise InvalidCell("RuntimePresenceLeaseStorage is closed")
            if self._connection is not None:
                cur = self._connection.execute(
                    "SELECT activity_root, agent_session_root, device_custody_root, app, observed_at, expires_at "
                    "FROM baboom_activities WHERE expires_at > ? ORDER BY expires_at, activity_root LIMIT ?",
                    (now, limit),
                )
                return [self._row_to_activity_dict(row) for row in cur.fetchall()]
            return [dict(stored) for stored in islice(
                (row for row in self._memory_activities.values() if row["expires_at"] > now), limit
            )]

    # -- Bounded operational records (SPEC 3.3) ---------------------------

    @staticmethod
    def _record_kind(kind: str) -> str:
        if kind not in OPERATIONAL_RECORD_KINDS:
            raise InvalidCell("operational record kind is not admitted")
        return kind

    @staticmethod
    def _record_text(value: object, label: str) -> str:
        if type(value) is not str or not value or len(value.encode("utf-8")) > 1024:
            raise InvalidCell("operational record %s is invalid" % label)
        return value

    @staticmethod
    def _record_payload(payload: object) -> str:
        if not isinstance(payload, dict):
            raise InvalidCell("operational record payload must be an object")
        try:
            text = json.dumps(
                payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise InvalidCell("operational record payload is not canonical JSON") from exc
        if len(text) > 256 * 1024:
            raise InvalidCell("operational record payload exceeds its bound")
        return text

    @staticmethod
    def _record_row(row: tuple[Any, ...]) -> dict[str, Any]:
        return {
            "kind": row[0],
            "record_root": row[1],
            "owner_root": row[2],
            "state": row[3],
            "generation": int(row[4]),
            "authority_revision": int(row[5]),
            "updated_at": float(row[6]),
            "payload": json.loads(row[7]),
        }

    def put_record(
        self,
        kind: str,
        record_root: str,
        *,
        owner_root: str,
        state: str,
        payload: dict[str, Any],
        authority_revision: int,
        updated_at: float,
        expected_generation: int | None = None,
        create_only: bool = False,
        event: str | None = None,
        retire_states: frozenset[str] | tuple[str, ...] = (),
    ) -> dict[str, Any]:
        """Create or advance one record atomically against a graph revision.

        ``authority_revision`` is the graph revision whose policy admitted this
        write; a file-backed record refuses when the graph head has moved.
        ``expected_generation`` fences concurrent writers. A new record beyond
        the per-kind bound first retires the oldest terminal records.
        """
        kind = self._record_kind(kind)
        record_root = self._record_text(record_root, "root")
        owner_root = self._record_text(owner_root, "owner")
        state = self._record_text(state, "state")
        text = self._record_payload(payload)
        if event is not None:
            event = self._record_text(event, "event")
        if type(authority_revision) is not int or authority_revision < 0:
            raise InvalidCell("operational record authority revision is invalid")
        if isinstance(updated_at, bool) or not isinstance(updated_at, (int, float)) or not math.isfinite(updated_at):
            raise InvalidCell("operational record time must be finite")
        if expected_generation is not None and (
            type(expected_generation) is not int or expected_generation < 1
        ):
            raise InvalidCell("operational record generation must be a positive integer")
        retire = tuple(retire_states)
        with self._lock:
            if self._closed:
                raise InvalidCell("RuntimePresenceLeaseStorage is closed")
            if self._connection is None:
                return self._put_memory_record(
                    kind, record_root, owner_root, state, text, authority_revision,
                    float(updated_at), expected_generation, create_only, event, retire,
                )
            in_tx = False
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                in_tx = True
                head_row = self._connection.execute(
                    "SELECT MAX(revision) FROM revisions"
                ).fetchone()
                head = head_row[0] if head_row and head_row[0] is not None else 0
                if head != authority_revision:
                    raise InvalidCell("operational record authority revision is stale")
                row = self._connection.execute(
                    "SELECT generation, owner_root FROM operational_records "
                    "WHERE kind = ? AND record_root = ?",
                    (kind, record_root),
                ).fetchone()
                if row is None:
                    if expected_generation is not None:
                        raise InvalidCell("operational record generation mismatch")
                    count = self._connection.execute(
                        "SELECT COUNT(*) FROM operational_records WHERE kind = ?",
                        (kind,),
                    ).fetchone()[0]
                    if count >= _OPERATIONAL_RECORD_LIMIT and retire:
                        marks = ",".join("?" for _ in retire)
                        self._connection.execute(
                            "DELETE FROM operational_records WHERE rowid IN ("
                            "SELECT rowid FROM operational_records WHERE kind = ? "
                            "AND state IN (%s) ORDER BY updated_at LIMIT ?)" % marks,
                            (kind, *retire, count - _OPERATIONAL_RECORD_LIMIT + 1),
                        )
                        count = self._connection.execute(
                            "SELECT COUNT(*) FROM operational_records WHERE kind = ?",
                            (kind,),
                        ).fetchone()[0]
                    if count >= _OPERATIONAL_RECORD_LIMIT:
                        raise InvalidCell("operational record kind reached its bound")
                    generation = 1
                    self._connection.execute(
                        "INSERT INTO operational_records (kind, record_root, owner_root, "
                        "state, generation, authority_revision, updated_at, payload) "
                        "VALUES (?, ?, ?, ?, 1, ?, ?, ?)",
                        (kind, record_root, owner_root, state, authority_revision,
                         float(updated_at), text),
                    )
                else:
                    if create_only:
                        raise InvalidCell("operational record already exists")
                    if row[1] != owner_root:
                        raise InvalidCell("operational record owner drifted")
                    if expected_generation is not None and row[0] != expected_generation:
                        raise InvalidCell("operational record generation mismatch")
                    generation = int(row[0]) + 1
                    self._connection.execute(
                        "UPDATE operational_records SET state = ?, generation = ?, "
                        "authority_revision = ?, updated_at = ?, payload = ? "
                        "WHERE kind = ? AND record_root = ?",
                        (state, generation, authority_revision, float(updated_at),
                         text, kind, record_root),
                    )
                if event is not None:
                    self._connection.execute(
                        "INSERT INTO operational_events (kind, record_root, event, "
                        "authority_revision, recorded_at, payload) VALUES (?, ?, ?, ?, ?, ?)",
                        (kind, record_root, event, authority_revision, float(updated_at), text),
                    )
                    self._connection.execute(
                        "DELETE FROM operational_events WHERE kind = ? AND sequence <= ("
                        "SELECT sequence FROM operational_events WHERE kind = ? "
                        "ORDER BY sequence DESC LIMIT 1 OFFSET ?)",
                        (kind, kind, _OPERATIONAL_EVENT_LIMIT),
                    )
                self._connection.execute("COMMIT")
                in_tx = False
            except Exception:
                if in_tx:
                    try:
                        self._connection.execute("ROLLBACK")
                    except Exception:
                        pass
                raise
            return {
                "kind": kind, "record_root": record_root, "owner_root": owner_root,
                "state": state, "generation": generation,
                "authority_revision": authority_revision,
                "updated_at": float(updated_at), "payload": json.loads(text),
            }

    def _put_memory_record(
        self, kind, record_root, owner_root, state, text, authority_revision,
        updated_at, expected_generation, create_only, event, retire,
    ) -> dict[str, Any]:
        key = (kind, record_root)
        existing = self._memory_records.get(key)
        if existing is None:
            if expected_generation is not None:
                raise InvalidCell("operational record generation mismatch")
            same_kind = sorted(
                (stored["updated_at"], stored_key)
                for stored_key, stored in self._memory_records.items()
                if stored_key[0] == kind
            )
            if len(same_kind) >= _OPERATIONAL_RECORD_LIMIT and retire:
                excess = len(same_kind) - _OPERATIONAL_RECORD_LIMIT + 1
                for _, stored_key in same_kind:
                    if excess <= 0:
                        break
                    if self._memory_records[stored_key]["state"] in retire:
                        self._memory_records.pop(stored_key)
                        excess -= 1
                same_kind = [
                    item for item in same_kind if item[1] in self._memory_records
                ]
            if len(same_kind) >= _OPERATIONAL_RECORD_LIMIT:
                raise InvalidCell("operational record kind reached its bound")
            generation = 1
        else:
            if create_only:
                raise InvalidCell("operational record already exists")
            if existing["owner_root"] != owner_root:
                raise InvalidCell("operational record owner drifted")
            if expected_generation is not None and existing["generation"] != expected_generation:
                raise InvalidCell("operational record generation mismatch")
            generation = existing["generation"] + 1
        stored = {
            "kind": kind, "record_root": record_root, "owner_root": owner_root,
            "state": state, "generation": generation,
            "authority_revision": authority_revision, "updated_at": updated_at,
            "payload": text,
        }
        self._memory_records[key] = stored
        if event is not None:
            self._memory_event_sequence += 1
            self._memory_events.append({
                "sequence": self._memory_event_sequence, "kind": kind,
                "record_root": record_root, "event": event,
                "authority_revision": authority_revision, "recorded_at": updated_at,
                "payload": text,
            })
            same = [item for item in self._memory_events if item["kind"] == kind]
            if len(same) > _OPERATIONAL_EVENT_LIMIT:
                dropped = {id(item) for item in same[:len(same) - _OPERATIONAL_EVENT_LIMIT]}
                self._memory_events = [
                    item for item in self._memory_events if id(item) not in dropped
                ]
        return {**stored, "payload": json.loads(text)}

    def get_record(self, kind: str, record_root: str) -> dict[str, Any] | None:
        kind = self._record_kind(kind)
        record_root = self._record_text(record_root, "root")
        with self._lock:
            if self._closed:
                raise InvalidCell("RuntimePresenceLeaseStorage is closed")
            if self._connection is None:
                stored = self._memory_records.get((kind, record_root))
                return None if stored is None else {
                    **stored, "payload": json.loads(stored["payload"])
                }
            row = self._connection.execute(
                "SELECT kind, record_root, owner_root, state, generation, "
                "authority_revision, updated_at, payload FROM operational_records "
                "WHERE kind = ? AND record_root = ?",
                (kind, record_root),
            ).fetchone()
            return None if row is None else self._record_row(row)

    def list_records(
        self,
        kind: str,
        *,
        owner_root: str | None = None,
        states: tuple[str, ...] | frozenset[str] | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        kind = self._record_kind(kind)
        if type(limit) is not int or not 1 <= limit <= _OPERATIONAL_RECORD_LIMIT:
            raise InvalidCell("operational record limit is invalid")
        wanted = None if states is None else tuple(states)
        with self._lock:
            if self._closed:
                raise InvalidCell("RuntimePresenceLeaseStorage is closed")
            if self._connection is None:
                rows = [
                    {**stored, "payload": json.loads(stored["payload"])}
                    for (stored_kind, _), stored in sorted(self._memory_records.items())
                    if stored_kind == kind
                    and (owner_root is None or stored["owner_root"] == owner_root)
                    and (wanted is None or stored["state"] in wanted)
                ]
                return rows[:limit]
            query = (
                "SELECT kind, record_root, owner_root, state, generation, "
                "authority_revision, updated_at, payload FROM operational_records "
                "WHERE kind = ?"
            )
            arguments: list[Any] = [kind]
            if owner_root is not None:
                query += " AND owner_root = ?"
                arguments.append(owner_root)
            if wanted is not None:
                if not wanted:
                    return []
                query += " AND state IN (%s)" % ",".join("?" for _ in wanted)
                arguments.extend(wanted)
            query += " ORDER BY record_root LIMIT ?"
            arguments.append(limit)
            return [
                self._record_row(row)
                for row in self._connection.execute(query, arguments).fetchall()
            ]

    def list_events(
        self, kind: str, record_root: str | None = None, *, limit: int = 256
    ) -> list[dict[str, Any]]:
        kind = self._record_kind(kind)
        if type(limit) is not int or not 1 <= limit <= _OPERATIONAL_EVENT_LIMIT:
            raise InvalidCell("operational event limit is invalid")
        with self._lock:
            if self._closed:
                raise InvalidCell("RuntimePresenceLeaseStorage is closed")
            if self._connection is None:
                rows = [
                    {**item, "payload": json.loads(item["payload"])}
                    for item in self._memory_events
                    if item["kind"] == kind
                    and (record_root is None or item["record_root"] == record_root)
                ]
                return rows[-limit:]
            query = (
                "SELECT sequence, kind, record_root, event, authority_revision, "
                "recorded_at, payload FROM operational_events WHERE kind = ?"
            )
            arguments: list[Any] = [kind]
            if record_root is not None:
                query += " AND record_root = ?"
                arguments.append(record_root)
            query += " ORDER BY sequence DESC LIMIT ?"
            arguments.append(limit)
            rows = self._connection.execute(query, arguments).fetchall()
            return [
                {
                    "sequence": row[0], "kind": row[1], "record_root": row[2],
                    "event": row[3], "authority_revision": row[4],
                    "recorded_at": row[5], "payload": json.loads(row[6]),
                }
                for row in reversed(rows)
            ]

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            if self._connection is not None:
                self._connection.close()
                self._connection = None
            self._closed = True


__all__ = [
    "OPERATIONAL_RECORD_KINDS",
    "RuntimePresenceLeaseStorage",
]
