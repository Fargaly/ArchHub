"""DPAPI custody for host-only Ed25519 caller capabilities."""

from __future__ import annotations

import base64
from contextlib import contextmanager
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import threading
import uuid

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)

from .cell_secret_keys import protect_current_user_data, unprotect_current_user_data
from .unified_authority import UnifiedAuthority
from .universal_cell import InvalidCell


_KEY_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


@dataclass(frozen=True, slots=True)
class Ed25519CallerCapability:
    actor_root: str
    session_root: str
    public_key: bytes
    _private_key: Ed25519PrivateKey

    def sign(self, payload: bytes) -> bytes:
        return self._private_key.sign(bytes(payload))


class WindowsDpapiCallerKeyStore:
    """Small encrypted key vault; it contains no graph or session state."""

    FORMAT = "archhub.caller-key-ring"
    FORMAT_VERSION = 1

    def __init__(self, path: str | os.PathLike[str]) -> None:
        if os.name != "nt":
            raise InvalidCell("DPAPI caller-key custody requires Windows")
        self.path = Path(path).expanduser().resolve()
        self._lock = threading.RLock()

    @staticmethod
    def default_path() -> Path:
        local = os.environ.get("LOCALAPPDATA")
        if not local:
            raise InvalidCell("LOCALAPPDATA is unavailable")
        return Path(local) / "ArchHub" / "keys" / "caller-signing-v1.dpapi.json"

    @staticmethod
    def _purpose(key_id: str) -> str:
        return "unified-caller/%s/v1" % key_id

    @staticmethod
    def _validate_key_id(key_id: str) -> str:
        if type(key_id) is not str or _KEY_ID.fullmatch(key_id) is None:
            raise InvalidCell("caller key identity is invalid")
        return key_id

    def _empty(self) -> dict[str, object]:
        return {
            "format": self.FORMAT,
            "format_version": self.FORMAT_VERSION,
            "keys": {},
        }

    def _load(self) -> dict[str, object]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return self._empty()
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise InvalidCell("caller key ring is unreadable") from exc
        if (
            type(payload) is not dict
            or payload.get("format") != self.FORMAT
            or payload.get("format_version") != self.FORMAT_VERSION
            or type(payload.get("keys")) is not dict
        ):
            raise InvalidCell("caller key ring format is invalid")
        return payload

    def _save(self, payload: dict[str, object]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(
            ".%s.%s.tmp" % (self.path.name, uuid.uuid4().hex)
        )
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
            0o600,
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(payload, stream, sort_keys=True, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    @contextmanager
    def _exclusive_update(self):
        """Serialize key creation across local agent adapter processes."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_name(self.path.name + ".lock")
        with self._lock, open(lock_path, "a+b", buffering=0) as stream:
            stream.seek(0, os.SEEK_END)
            if stream.tell() == 0:
                stream.write(b"\0")
            stream.seek(0)
            import msvcrt

            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)

    def ensure(self, key_id: str) -> bytes:
        key_id = self._validate_key_id(key_id)
        with self._exclusive_update():
            payload = self._load()
            keys = payload["keys"]
            if not isinstance(keys, dict):
                raise InvalidCell("caller key ring entries are invalid")
            if key_id not in keys:
                private_key = Ed25519PrivateKey.generate()
                private_bytes = private_key.private_bytes(
                    serialization.Encoding.Raw,
                    serialization.PrivateFormat.Raw,
                    serialization.NoEncryption(),
                )
                public_key = private_key.public_key().public_bytes(
                    serialization.Encoding.Raw,
                    serialization.PublicFormat.Raw,
                )
                protected = protect_current_user_data(
                    private_bytes,
                    purpose=self._purpose(key_id),
                )
                keys[key_id] = {
                    "algorithm": "ed25519",
                    "private": base64.b64encode(protected).decode("ascii"),
                    "public": base64.b64encode(public_key).decode("ascii"),
                }
                self._save(payload)
                return public_key
            return self._public_key_from_payload(payload, key_id)

    def _public_key_from_payload(
        self,
        payload: dict[str, object],
        key_id: str,
    ) -> bytes:
        try:
            record = payload["keys"][key_id]  # type: ignore[index]
            if record["algorithm"] != "ed25519":
                raise KeyError(key_id)
            expected = base64.b64decode(record["public"], validate=True)
            private_key = Ed25519PrivateKey.from_private_bytes(
                unprotect_current_user_data(
                    base64.b64decode(record["private"], validate=True),
                    purpose=self._purpose(key_id),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidCell("caller key record is invalid") from exc
        actual = private_key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
        if len(expected) != 32 or actual != expected:
            raise InvalidCell("caller public and private keys do not match")
        return actual

    def _private_key(self, key_id: str) -> Ed25519PrivateKey:
        key_id = self._validate_key_id(key_id)
        payload = self._load()
        try:
            record = payload["keys"][key_id]  # type: ignore[index]
            if record["algorithm"] != "ed25519":
                raise KeyError(key_id)
            protected = base64.b64decode(record["private"], validate=True)
            expected_public = base64.b64decode(record["public"], validate=True)
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidCell("caller key record is invalid") from exc
        try:
            private_bytes = unprotect_current_user_data(
                protected,
                purpose=self._purpose(key_id),
            )
            private_key = Ed25519PrivateKey.from_private_bytes(private_bytes)
        except (ValueError, TypeError) as exc:
            raise InvalidCell("caller private key cannot be recovered") from exc
        actual_public = private_key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
        if actual_public != expected_public:
            raise InvalidCell("caller public and private keys do not match")
        return private_key

    def public_key(self, key_id: str) -> bytes:
        private_key = self._private_key(key_id)
        return private_key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )

    def sign(self, key_id: str, payload: bytes) -> bytes:
        return self._private_key(key_id).sign(bytes(payload))

    def bind_bootstrap(
        self,
        authority: UnifiedAuthority,
        key_id: str,
    ) -> Ed25519CallerCapability:
        private_key = self._private_key(key_id)
        public_key = private_key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
        return Ed25519CallerCapability(
            authority.manifest.principal_root,
            authority.manifest.bootstrap_session_root,
            public_key,
            private_key,
        )

    def bind_session(
        self,
        authority: UnifiedAuthority,
        key_id: str,
        session_root: str,
    ) -> Ed25519CallerCapability:
        if type(session_root) is not str or not session_root:
            raise InvalidCell("caller session identity is invalid")
        private_key = self._private_key(key_id)
        public_key = private_key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
        return Ed25519CallerCapability(
            authority.manifest.principal_root,
            session_root,
            public_key,
            private_key,
        )


__all__ = ["Ed25519CallerCapability", "WindowsDpapiCallerKeyStore"]
