"""Local founder grants for PRIVATE registered workspace roots.

These grants are owner-runtime state. They are not Workshop Work, not shared
graph content, and not a replacement for the signed workspace-root registry.
"""
from __future__ import annotations

from pathlib import Path
from contextlib import contextmanager
import hashlib
import json
import os
import threading
import time
import uuid

from .cell_secret_keys import SigningKeyProvider
from .universal_cell import InvalidCell


SCHEMA = "archhub.private-root-grants/v1"
DEFAULT_OPERATIONS = ("edit_file", "apply_patch", "write_file", "create")
SUPPORTED_OPERATIONS = frozenset(DEFAULT_OPERATIONS)
_RUNTIMES = {"claude", "codex", "cursor", "gemini", "antigravity", "opencode", "windsurf", "zed", "aider"}
_KEY_ID = "archhub.local.private-root-grants"


def canonical(value: object) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                          allow_nan=False).encode("ascii")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise InvalidCell("private-root grant document is invalid") from exc


def default_grant_path() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) / "ArchHub" if base else Path.home() / ".archhub"
    return root / "governance" / "private-root-grants.json"


def _text(value: object, field: str, *, maximum: int = 512) -> str:
    if type(value) is not str:
        raise InvalidCell("private-root grant %s is invalid" % field)
    cleaned = value.strip()
    if not cleaned or len(cleaned.encode("utf-8")) > maximum:
        raise InvalidCell("private-root grant %s is invalid" % field)
    return cleaned


def _digest(value: object, field: str) -> str:
    text = _text(value, field, maximum=64)
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise InvalidCell("private-root grant %s is invalid" % field)
    return text


def _operations(values: object) -> tuple[str, ...]:
    if values is None:
        return DEFAULT_OPERATIONS
    if type(values) not in (list, tuple) or not values:
        raise InvalidCell("private-root grant operations are invalid")
    operations = tuple(_text(value, "operation", maximum=128) for value in values)
    if len(operations) != len(set(operations)):
        raise InvalidCell("private-root grant operations are invalid")
    if any(operation not in SUPPORTED_OPERATIONS for operation in operations):
        raise InvalidCell("private-root grant operations are invalid")
    return operations


class PrivateRootGrantStore:
    """Signed local grant file bound to one owner authority key."""

    def __init__(self, path: str | Path | None = None, *, provider: SigningKeyProvider,
                 key_id: str = _KEY_ID) -> None:
        self.path = Path(path) if path is not None else default_grant_path()
        self.provider = provider
        self.key_id = key_id
        self._mutation_lock = threading.RLock()

    @contextmanager
    def _locked_mutation(self):
        with self._mutation_lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            lock_path = self.path.with_name(".%s.lock" % self.path.name)
            with lock_path.open("a+b") as handle:
                handle.seek(0)
                handle.write(b"\0")
                handle.flush()
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                    try:
                        yield
                    finally:
                        handle.seek(0)
                        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                    try:
                        yield
                    finally:
                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _header(self) -> dict[str, object]:
        ref = self.provider.current_reference(self.key_id)
        return {
            "schema": SCHEMA,
            "key_id": ref.key_id,
            "key_version": ref.version,
            "key_fingerprint": self.provider.key_fingerprint(ref.key_id, ref.version),
        }

    def _empty(self) -> dict[str, object]:
        return {**self._header(), "grants": []}

    def _signed(self, body: dict[str, object]) -> dict[str, object]:
        payload = canonical(body)
        return {**body, "signature": self.provider.sign(
            str(body["key_id"]), int(body["key_version"]), payload)}

    def _read(self) -> dict[str, object]:
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return self._empty()
        except (OSError, ValueError) as exc:
            raise InvalidCell("private-root grant document is unreadable") from exc
        if type(document) is not dict or type(document.get("signature")) is not str:
            raise InvalidCell("private-root grant document is unsigned")
        body = {key: value for key, value in document.items() if key != "signature"}
        if (body.get("schema") != SCHEMA
                or body.get("key_id") != self.key_id
                or type(body.get("key_version")) is not int
                or type(body.get("key_fingerprint")) is not str
                or type(body.get("grants")) is not list):
            raise InvalidCell("private-root grant document is malformed")
        if self.provider.key_fingerprint(self.key_id, int(body["key_version"])) != body["key_fingerprint"]:
            raise InvalidCell("private-root grant signing key is not pinned")
        if not self.provider.verify(self.key_id, int(body["key_version"]),
                                    canonical(body), str(document["signature"])):
            raise InvalidCell("private-root grant document does not verify")
        for grant in body["grants"]:
            self._validate_grant(grant)
        return body

    def _write(self, body: dict[str, object]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(".%s.%s.tmp" % (self.path.name, os.getpid()))
        try:
            temporary.write_text(json.dumps(self._signed(body), sort_keys=True,
                                            separators=(",", ":")) + "\n", encoding="utf-8")
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _validate_grant(grant: object) -> None:
        if type(grant) is not dict or set(grant) != {
            "grant_id", "root_id", "runtime", "session_id", "root_digest",
            "operations", "issued_at", "expires_at", "issued_by_founder", "revoked",
        }:
            raise InvalidCell("private-root grant is malformed")
        _text(grant["grant_id"], "identity", maximum=128)
        _text(grant["root_id"], "root id", maximum=64)
        runtime = _text(grant["runtime"], "runtime", maximum=64)
        if runtime not in _RUNTIMES:
            raise InvalidCell("private-root grant runtime is invalid")
        _text(grant["session_id"], "session identity", maximum=512)
        _digest(grant["root_digest"], "root digest")
        _operations(grant["operations"])
        if type(grant["issued_at"]) not in (int, float) or type(grant["expires_at"]) not in (int, float):
            raise InvalidCell("private-root grant time is invalid")
        if grant["expires_at"] <= grant["issued_at"]:
            raise InvalidCell("private-root grant expiry is invalid")
        if grant["issued_by_founder"] is not True or type(grant["revoked"]) is not bool:
            raise InvalidCell("private-root grant marker is invalid")

    def grant(self, *, root_id: str, runtime: str, session_id: str, root_digest: str,
              operations: object = None, expires_at: float | None = None,
              now: float | None = None) -> dict[str, object]:
        issued_at = time.time() if now is None else float(now)
        expiry = issued_at + 30 * 24 * 60 * 60 if expires_at is None else float(expires_at)
        grant = {
            "grant_id": "private-root-grant:%s" % uuid.uuid4().hex,
            "root_id": _text(root_id, "root id", maximum=64),
            "runtime": _text(runtime, "runtime", maximum=64).lower(),
            "session_id": _text(session_id, "session identity", maximum=512),
            "root_digest": _digest(root_digest, "root digest"),
            "operations": list(_operations(operations)),
            "issued_at": issued_at,
            "expires_at": expiry,
            "issued_by_founder": True,
            "revoked": False,
        }
        self._validate_grant(grant)
        with self._locked_mutation():
            body = self._read()
            grants = [
                {**item, "revoked": True}
                if item["root_id"] == grant["root_id"] and item["runtime"] == grant["runtime"]
                and item["session_id"] == grant["session_id"] else item
                for item in body["grants"]
            ]
            grants.append(grant)
            self._write({**self._header(), "grants": grants})
        return grant

    def revoke(self, *, root_id: str, runtime: str | None = None, session_id: str | None = None) -> int:
        with self._locked_mutation():
            body = self._read()
            count = 0
            grants = []
            for grant in body["grants"]:
                matched = grant["root_id"] == root_id
                matched = matched and (runtime is None or grant["runtime"] == runtime)
                matched = matched and (session_id is None or grant["session_id"] == session_id)
                if matched and not grant["revoked"]:
                    count += 1
                    grant = {**grant, "revoked": True}
                grants.append(grant)
            self._write({**self._header(), "grants": grants})
        return count

    def status(self, *, root_id: str, runtime: str, session_id: str, operation: str,
               root_digest: str, now: float | None = None,
               include_grant: bool = False) -> dict[str, object]:
        try:
            body = self._read()
        except InvalidCell as exc:
            return {"granted": False, "reason": "grant store invalid: %s" % exc}
        moment = time.time() if now is None else float(now)
        candidates = [
            grant for grant in body["grants"]
            if grant["root_id"] == root_id and grant["runtime"] == runtime
            and grant["session_id"] == session_id and grant["root_digest"] == root_digest
            and operation in grant["operations"]
        ]
        if not candidates:
            return {"granted": False, "reason": "no grant: ask the founder in Settings > Workspaces"}
        grant = sorted(candidates, key=lambda item: item["issued_at"])[-1]
        if grant["revoked"]:
            return {"granted": False, "reason": "grant revoked"}
        if moment >= float(grant["expires_at"]):
            return {"granted": False, "reason": "grant expired"}
        result = {"granted": True, "until": grant["expires_at"]}
        if include_grant:
            result["grant"] = grant
        return result

    def list(self) -> list[dict[str, object]]:
        try:
            return list(self._read()["grants"])
        except InvalidCell:
            return []


def grant_fingerprint(grant: dict[str, object]) -> str:
    return hashlib.sha256(canonical({"schema": SCHEMA + ".grant-fingerprint", "grant": grant})).hexdigest()
