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

import math
from itertools import islice
import os
from pathlib import Path
import sqlite3
import threading
from typing import Any

from .universal_cell import InvalidCell


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

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            if self._connection is not None:
                self._connection.close()
                self._connection = None
            self._closed = True


__all__ = [
    "RuntimePresenceLeaseStorage",
]
