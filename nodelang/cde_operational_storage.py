"""Indexed CDE write-permit and receipt operational storage in the primary instance SQLite database.

SPEC 3.2 and 3.3:
Permission policies, capability scopes, agent identity, executable workflows and
their relationships remain graph authority. Individual tool checks, per-write
permits/receipts and audit history use bounded indexed operational records in the
SAME primary instance database, without creating a new graph composition or
layout node per event.
"""
from __future__ import annotations

import copy
import json
import math
import os
from pathlib import Path
import sqlite3
import threading
from typing import Any

from .universal_cell import InvalidCell


class CdeOperationalDenied(PermissionError):
    """Operational storage constraint denied the operation."""


class CdeOperationalStorage:
    """Instance-owned operational storage for CDE write permits and receipts."""

    def __init__(self, database_path: str | os.PathLike[str] | None = None) -> None:
        self._lock = threading.RLock()
        self._closed = False
        self._database_path: str | None = (
            str(Path(database_path).expanduser().resolve())
            if database_path is not None
            else None
        )
        self._connection: sqlite3.Connection | None = None
        self._memory_permits: dict[str, dict[str, Any]] = {}
        self._memory_receipts: dict[str, dict[str, Any]] = {}
        self._memory_receipts_by_permit: dict[str, dict[str, Any]] = {}
        self._memory_nonces: dict[str, str] = {}
        self._memory_requests: dict[str, str] = {}

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
                "CREATE TABLE IF NOT EXISTS cde_write_permits ("
                "permit_root TEXT PRIMARY KEY, "
                "runtime TEXT NOT NULL, "
                "agent_session_root TEXT NOT NULL, "
                "work_root TEXT NOT NULL, "
                "container_root TEXT NOT NULL, "
                "container_id TEXT NOT NULL, "
                "container_digest TEXT NOT NULL, "
                "operation TEXT NOT NULL, "
                "path TEXT NOT NULL, "
                "content_digest TEXT NOT NULL, "
                "request_id TEXT NOT NULL, "
                "nonce TEXT NOT NULL, "
                "authority_revision INTEGER NOT NULL, "
                "issued_at REAL NOT NULL, "
                "expires_at REAL NOT NULL, "
                "authorization_evidence TEXT NOT NULL, "
                "signature_envelope_root TEXT NOT NULL, "
                "state TEXT NOT NULL, "
                "envelope_data TEXT NOT NULL, "
                "revocation_reason TEXT"
                ")"
            )
            self._connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_cde_permits_request "
                "ON cde_write_permits(request_id)"
            )
            self._connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_cde_permits_nonce "
                "ON cde_write_permits(nonce)"
            )
            self._connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_cde_permits_expires "
                "ON cde_write_permits(expires_at)"
            )
            self._connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_cde_permits_session "
                "ON cde_write_permits(agent_session_root)"
            )
            self._connection.execute(
                "CREATE TABLE IF NOT EXISTS cde_write_receipts ("
                "receipt_root TEXT PRIMARY KEY, "
                "permit_root TEXT NOT NULL UNIQUE, "
                "kind TEXT NOT NULL, "
                "digest TEXT NOT NULL, "
                "evidence_digest TEXT NOT NULL, "
                "recorded_at REAL NOT NULL, "
                "authority_revision INTEGER NOT NULL"
                ")"
            )
            self._connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_cde_receipts_permit "
                "ON cde_write_receipts(permit_root)"
            )
            self._connection.execute("COMMIT")
        except Exception:
            self._connection.execute("ROLLBACK")
            raise

    @property
    def database_path(self) -> str | None:
        return self._database_path

    @property
    def is_closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            if self._connection is not None:
                self._connection.close()
                self._connection = None
            self._closed = True

    def record_permit(self, permit_data: dict[str, Any]) -> dict[str, Any]:
        permit_root = permit_data["permit_root"]
        request_id = permit_data["request_id"]
        nonce = permit_data["nonce"]

        with self._lock:
            if self._closed:
                raise InvalidCell("CdeOperationalStorage is closed")
            if self._connection is not None:
                in_tx = False
                try:
                    self._connection.execute("BEGIN IMMEDIATE")
                    in_tx = True
                    head = self._connection.execute("SELECT MAX(revision) FROM revisions").fetchone()[0]
                    if head != permit_data["authority_revision"]:
                        raise CdeOperationalDenied("CDE write permit authority revision is stale")
                    cur = self._connection.execute(
                        "SELECT permit_root, runtime, agent_session_root, work_root, container_root, "
                        "container_id, container_digest, operation, path, content_digest, "
                        "request_id, nonce, authority_revision, issued_at, expires_at, "
                        "authorization_evidence, signature_envelope_root, state, envelope_data, revocation_reason "
                        "FROM cde_write_permits WHERE permit_root = ?",
                        (permit_root,),
                    )
                    row = cur.fetchone()
                    if row is not None:
                        if row[10] != request_id:
                            self._connection.execute("ROLLBACK")
                            raise CdeOperationalDenied("CDE write permit request was replayed")
                        if row[11] != nonce:
                            self._connection.execute("ROLLBACK")
                            raise CdeOperationalDenied("CDE write permit nonce was replayed")
                        self._connection.execute("COMMIT")
                        return self._row_to_permit_dict(row)

                    cur = self._connection.execute(
                        "SELECT permit_root, request_id, nonce FROM cde_write_permits WHERE request_id = ? OR nonce = ?",
                        (request_id, nonce),
                    )
                    clash = cur.fetchone()
                    if clash is not None:
                        self._connection.execute("ROLLBACK")
                        if clash[2] == nonce:
                            raise CdeOperationalDenied("CDE write permit nonce was replayed")
                        raise CdeOperationalDenied("CDE write permit request was replayed")

                    self._connection.execute(
                        "INSERT INTO cde_write_permits ("
                        "permit_root, runtime, agent_session_root, work_root, container_root, "
                        "container_id, container_digest, operation, path, content_digest, "
                        "request_id, nonce, authority_revision, issued_at, expires_at, "
                        "authorization_evidence, signature_envelope_root, state, envelope_data, revocation_reason"
                        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)",
                        (
                            permit_root,
                            permit_data["runtime"],
                            permit_data["agent_session_root"],
                            permit_data["work_root"],
                            permit_data["container_root"],
                            permit_data["container_id"],
                            permit_data["container_digest"],
                            permit_data["operation"],
                            permit_data["path"],
                            permit_data["content_digest"],
                            request_id,
                            nonce,
                            permit_data["authority_revision"],
                            permit_data["issued_at"],
                            permit_data["expires_at"],
                            permit_data["authorization_evidence"],
                            permit_data["signature_envelope_root"],
                            permit_data.get("state", "active"),
                            permit_data["envelope_data"]
                            if isinstance(permit_data["envelope_data"], str)
                            else json.dumps(permit_data["envelope_data"]),
                        ),
                    )
                    self._connection.execute("COMMIT")
                    return permit_data
                except Exception:
                    if in_tx:
                        try:
                            self._connection.execute("ROLLBACK")
                        except Exception:
                            pass
                    raise
            else:
                existing = self._memory_permits.get(permit_root)
                if existing is not None:
                    if existing["request_id"] != request_id:
                        raise CdeOperationalDenied("CDE write permit request was replayed")
                    if existing["nonce"] != nonce:
                        raise CdeOperationalDenied("CDE write permit nonce was replayed")
                    return copy.deepcopy(existing)

                if nonce in self._memory_nonces:
                    raise CdeOperationalDenied("CDE write permit nonce was replayed")
                if request_id in self._memory_requests:
                    raise CdeOperationalDenied("CDE write permit request was replayed")

                stored = copy.deepcopy(permit_data)
                if "state" not in stored:
                    stored["state"] = "active"
                if not isinstance(stored["envelope_data"], str):
                    stored["envelope_data"] = json.dumps(stored["envelope_data"])
                self._memory_permits[permit_root] = stored
                self._memory_nonces[nonce] = permit_root
                self._memory_requests[request_id] = permit_root
                return copy.deepcopy(stored)

    def get_permit(self, permit_root: str) -> dict[str, Any] | None:
        with self._lock:
            if self._closed:
                raise InvalidCell("CdeOperationalStorage is closed")
            if self._connection is not None:
                cur = self._connection.execute(
                    "SELECT permit_root, runtime, agent_session_root, work_root, container_root, "
                    "container_id, container_digest, operation, path, content_digest, "
                    "request_id, nonce, authority_revision, issued_at, expires_at, "
                    "authorization_evidence, signature_envelope_root, state, envelope_data, revocation_reason "
                    "FROM cde_write_permits WHERE permit_root = ?",
                    (permit_root,),
                )
                row = cur.fetchone()
                return self._row_to_permit_dict(row) if row is not None else None
            else:
                p = self._memory_permits.get(permit_root)
                return dict(p) if p is not None else None

    def get_permit_by_nonce(self, nonce: str) -> dict[str, Any] | None:
        with self._lock:
            if self._closed:
                raise InvalidCell("CdeOperationalStorage is closed")
            if self._connection is not None:
                cur = self._connection.execute(
                    "SELECT permit_root, runtime, agent_session_root, work_root, container_root, "
                    "container_id, container_digest, operation, path, content_digest, "
                    "request_id, nonce, authority_revision, issued_at, expires_at, "
                    "authorization_evidence, signature_envelope_root, state, envelope_data, revocation_reason "
                    "FROM cde_write_permits WHERE nonce = ?",
                    (nonce,),
                )
                row = cur.fetchone()
                return self._row_to_permit_dict(row) if row is not None else None
            else:
                root = self._memory_nonces.get(nonce)
                return dict(self._memory_permits[root]) if root is not None else None

    def get_permit_by_request(self, request_id: str) -> dict[str, Any] | None:
        with self._lock:
            if self._closed:
                raise InvalidCell("CdeOperationalStorage is closed")
            if self._connection is not None:
                cur = self._connection.execute(
                    "SELECT permit_root, runtime, agent_session_root, work_root, container_root, "
                    "container_id, container_digest, operation, path, content_digest, "
                    "request_id, nonce, authority_revision, issued_at, expires_at, "
                    "authorization_evidence, signature_envelope_root, state, envelope_data, revocation_reason "
                    "FROM cde_write_permits WHERE request_id = ?",
                    (request_id,),
                )
                row = cur.fetchone()
                return self._row_to_permit_dict(row) if row is not None else None
            else:
                root = self._memory_requests.get(request_id)
                return dict(self._memory_permits[root]) if root is not None else None

    def consume_permit(
        self,
        permit_root: str,
        receipt_data: dict[str, Any],
        *,
        expected_content_digest: str,
        now: float,
    ) -> dict[str, Any]:
        with self._lock:
            if self._closed:
                raise InvalidCell("CdeOperationalStorage is closed")
            if self._connection is not None:
                in_tx = False
                try:
                    self._connection.execute("BEGIN IMMEDIATE")
                    in_tx = True
                    head = self._connection.execute("SELECT MAX(revision) FROM revisions").fetchone()[0]
                    if head != receipt_data["authority_revision"]:
                        raise CdeOperationalDenied("CDE write permit authority revision is stale")
                    cur = self._connection.execute(
                        "SELECT state, content_digest, issued_at, expires_at "
                        "FROM cde_write_permits WHERE permit_root = ?",
                        (permit_root,),
                    )
                    row = cur.fetchone()
                    if row is None:
                        self._connection.execute("ROLLBACK")
                        raise InvalidCell("CDE write permit is missing")
                    state, content_digest, issued_at, expires_at = row

                    if state == "consumed":
                        cur = self._connection.execute(
                            "SELECT receipt_root, permit_root, kind, digest, evidence_digest, recorded_at, authority_revision "
                            "FROM cde_write_receipts WHERE permit_root = ?",
                            (permit_root,),
                        )
                        receipt_row = cur.fetchone()
                        if receipt_row is not None and receipt_row[4] == receipt_data["evidence_digest"]:
                            self._connection.execute("COMMIT")
                            return self._row_to_receipt_dict(receipt_row)
                        self._connection.execute("ROLLBACK")
                        raise CdeOperationalDenied("CDE write permit was already consumed")

                    if state == "revoked":
                        self._connection.execute("ROLLBACK")
                        raise CdeOperationalDenied("CDE write permit was revoked")

                    if now < issued_at or now >= expires_at:
                        self._connection.execute("ROLLBACK")
                        raise CdeOperationalDenied("CDE write permit expired or is not yet valid")

                    if content_digest != expected_content_digest:
                        self._connection.execute("ROLLBACK")
                        raise CdeOperationalDenied("CDE write permit content digest mismatched")

                    cur = self._connection.execute(
                        "UPDATE cde_write_permits SET state = 'consumed' WHERE permit_root = ? AND state = 'active'",
                        (permit_root,),
                    )
                    if cur.rowcount != 1:
                        self._connection.execute("ROLLBACK")
                        raise CdeOperationalDenied("CDE write permit was already consumed")

                    self._connection.execute(
                        "INSERT INTO cde_write_receipts ("
                        "receipt_root, permit_root, kind, digest, evidence_digest, recorded_at, authority_revision"
                        ") VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (
                            receipt_data["receipt_root"],
                            permit_root,
                            receipt_data["kind"],
                            receipt_data["digest"],
                            receipt_data["evidence_digest"],
                            receipt_data["recorded_at"],
                            receipt_data["authority_revision"],
                        ),
                    )
                    self._connection.execute("COMMIT")
                    return receipt_data
                except Exception:
                    if in_tx:
                        try:
                            self._connection.execute("ROLLBACK")
                        except Exception:
                            pass
                    raise
            else:
                permit = self._memory_permits.get(permit_root)
                if permit is None:
                    raise InvalidCell("CDE write permit is missing")
                state = permit["state"]
                if state == "consumed":
                    existing = self._memory_receipts_by_permit.get(permit_root)
                    if existing is not None and existing["evidence_digest"] == receipt_data["evidence_digest"]:
                        return copy.deepcopy(existing)
                    raise CdeOperationalDenied("CDE write permit was already consumed")
                if state == "revoked":
                    raise CdeOperationalDenied("CDE write permit was revoked")
                if now < permit["issued_at"] or now >= permit["expires_at"]:
                    raise CdeOperationalDenied("CDE write permit expired or is not yet valid")
                if permit["content_digest"] != expected_content_digest:
                    raise CdeOperationalDenied("CDE write permit content digest mismatched")

                permit["state"] = "consumed"
                self._memory_receipts[receipt_data["receipt_root"]] = copy.deepcopy(receipt_data)
                self._memory_receipts_by_permit[permit_root] = copy.deepcopy(receipt_data)
                return copy.deepcopy(receipt_data)

    def revoke_permit(
        self,
        permit_root: str,
        receipt_data: dict[str, Any],
        *,
        reason: str,
        now: float,
    ) -> dict[str, Any]:
        with self._lock:
            if self._closed:
                raise InvalidCell("CdeOperationalStorage is closed")
            if self._connection is not None:
                in_tx = False
                try:
                    self._connection.execute("BEGIN IMMEDIATE")
                    in_tx = True
                    head = self._connection.execute("SELECT MAX(revision) FROM revisions").fetchone()[0]
                    if head != receipt_data["authority_revision"]:
                        raise CdeOperationalDenied("CDE write permit authority revision is stale")
                    cur = self._connection.execute(
                        "SELECT state FROM cde_write_permits WHERE permit_root = ?",
                        (permit_root,),
                    )
                    row = cur.fetchone()
                    if row is None:
                        self._connection.execute("ROLLBACK")
                        raise InvalidCell("CDE write permit is missing")
                    state = row[0]
                    if state == "consumed":
                        self._connection.execute("ROLLBACK")
                        raise CdeOperationalDenied("consumed CDE write permit cannot be revoked")
                    if state == "revoked":
                        self._connection.execute("ROLLBACK")
                        raise CdeOperationalDenied("CDE write permit was already revoked")

                    cur = self._connection.execute(
                        "UPDATE cde_write_permits SET state = 'revoked', revocation_reason = ? "
                        "WHERE permit_root = ? AND state = 'active'",
                        (reason, permit_root),
                    )
                    if cur.rowcount != 1:
                        self._connection.execute("ROLLBACK")
                        raise CdeOperationalDenied("CDE write permit was already consumed or revoked")

                    self._connection.execute(
                        "INSERT INTO cde_write_receipts ("
                        "receipt_root, permit_root, kind, digest, evidence_digest, recorded_at, authority_revision"
                        ") VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (
                            receipt_data["receipt_root"],
                            permit_root,
                            receipt_data["kind"],
                            receipt_data["digest"],
                            receipt_data["evidence_digest"],
                            receipt_data["recorded_at"],
                            receipt_data["authority_revision"],
                        ),
                    )
                    self._connection.execute("COMMIT")
                    return receipt_data
                except Exception:
                    if in_tx:
                        try:
                            self._connection.execute("ROLLBACK")
                        except Exception:
                            pass
                    raise
            else:
                permit = self._memory_permits.get(permit_root)
                if permit is None:
                    raise InvalidCell("CDE write permit is missing")
                state = permit["state"]
                if state == "consumed":
                    raise CdeOperationalDenied("consumed CDE write permit cannot be revoked")
                if state == "revoked":
                    raise CdeOperationalDenied("CDE write permit was already revoked")
                permit["state"] = "revoked"
                permit["revocation_reason"] = reason
                self._memory_receipts[receipt_data["receipt_root"]] = copy.deepcopy(receipt_data)
                self._memory_receipts_by_permit[permit_root] = copy.deepcopy(receipt_data)
                return copy.deepcopy(receipt_data)

    def get_receipt(self, receipt_root: str) -> dict[str, Any] | None:
        with self._lock:
            if self._closed:
                raise InvalidCell("CdeOperationalStorage is closed")
            if self._connection is not None:
                cur = self._connection.execute(
                    "SELECT receipt_root, permit_root, kind, digest, evidence_digest, recorded_at, authority_revision "
                    "FROM cde_write_receipts WHERE receipt_root = ?",
                    (receipt_root,),
                )
                row = cur.fetchone()
                return self._row_to_receipt_dict(row) if row is not None else None
            else:
                r = self._memory_receipts.get(receipt_root)
                return dict(r) if r is not None else None

    def get_receipt_for_permit(self, permit_root: str) -> dict[str, Any] | None:
        with self._lock:
            if self._closed:
                raise InvalidCell("CdeOperationalStorage is closed")
            if self._connection is not None:
                cur = self._connection.execute(
                    "SELECT receipt_root, permit_root, kind, digest, evidence_digest, recorded_at, authority_revision "
                    "FROM cde_write_receipts WHERE permit_root = ?",
                    (permit_root,),
                )
                row = cur.fetchone()
                return self._row_to_receipt_dict(row) if row is not None else None
            else:
                r = self._memory_receipts_by_permit.get(permit_root)
                return dict(r) if r is not None else None

    @staticmethod
    def _row_to_permit_dict(row: tuple[Any, ...]) -> dict[str, Any]:
        envelope_data = row[18]
        if isinstance(envelope_data, str):
            try:
                envelope_data = json.loads(envelope_data)
            except Exception:
                pass
        return {
            "permit_root": row[0],
            "runtime": row[1],
            "agent_session_root": row[2],
            "work_root": row[3],
            "container_root": row[4],
            "container_id": row[5],
            "container_digest": row[6],
            "operation": row[7],
            "path": row[8],
            "content_digest": row[9],
            "request_id": row[10],
            "nonce": row[11],
            "authority_revision": row[12],
            "issued_at": row[13],
            "expires_at": row[14],
            "authorization_evidence": row[15],
            "signature_envelope_root": row[16],
            "state": row[17],
            "envelope_data": envelope_data,
            "revocation_reason": row[19],
        }

    @staticmethod
    def _row_to_receipt_dict(row: tuple[Any, ...]) -> dict[str, Any]:
        return {
            "receipt_root": row[0],
            "permit_root": row[1],
            "kind": row[2],
            "digest": row[3],
            "evidence_digest": row[4],
            "recorded_at": row[5],
            "authority_revision": row[6],
        }


__all__ = [
    "CdeOperationalDenied",
    "CdeOperationalStorage",
]
