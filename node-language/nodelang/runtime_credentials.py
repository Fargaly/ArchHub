"""Current-user custody for browser capabilities that survive worker handoff."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import secrets
import threading

from .cell_secret_keys import (
    SigningKeyError,
    protect_current_user_data,
    unprotect_current_user_data,
)


@dataclass(frozen=True, slots=True)
class BrowserSessionCredentials:
    token: str
    csrf_token: str
    custody_id: str


class BrowserCredentialVault:
    """Atomic DPAPI custody; the file contains ciphertext only."""

    FORMAT = "archhub.browser-session-custody"
    VERSION = 1

    def __init__(self, path: str | os.PathLike[str]) -> None:
        if os.name != "nt":
            raise SigningKeyError("browser credential custody requires Windows")
        self.path = Path(path).expanduser().resolve()
        self._lock = threading.RLock()

    @staticmethod
    def default_path() -> Path:
        local = os.environ.get("LOCALAPPDATA")
        if not local:
            raise SigningKeyError("LOCALAPPDATA is unavailable")
        return Path(local) / "ArchHub" / "runtime" / "browser-session-v1.dpapi"

    def _purpose(self) -> str:
        identity = hashlib.sha256(str(self.path).encode("utf-8")).hexdigest()
        return "browser-session-custody/" + identity

    @staticmethod
    def _validate(payload: object) -> BrowserSessionCredentials:
        if type(payload) is not dict or set(payload) != {
            "format", "version", "token", "csrf_token", "custody_id"
        }:
            raise SigningKeyError("browser credential vault shape is invalid")
        if (
            payload["format"] != BrowserCredentialVault.FORMAT
            or payload["version"] != BrowserCredentialVault.VERSION
            or any(
                type(payload[name]) is not str
                or len(payload[name]) < 32
                or len(payload[name]) > 256
                for name in ("token", "csrf_token", "custody_id")
            )
        ):
            raise SigningKeyError("browser credential vault content is invalid")
        return BrowserSessionCredentials(
            payload["token"], payload["csrf_token"], payload["custody_id"]
        )

    def load_or_create(self) -> BrowserSessionCredentials:
        with self._lock:
            if self.path.exists():
                try:
                    plaintext = unprotect_current_user_data(
                        self.path.read_bytes(), purpose=self._purpose()
                    )
                    return self._validate(json.loads(plaintext.decode("utf-8")))
                except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                    raise SigningKeyError(
                        "browser credential vault is unreadable"
                    ) from exc
            credentials = BrowserSessionCredentials(
                secrets.token_urlsafe(48),
                secrets.token_urlsafe(48),
                secrets.token_hex(32),
            )
            payload = {
                "format": self.FORMAT,
                "version": self.VERSION,
                "token": credentials.token,
                "csrf_token": credentials.csrf_token,
                "custody_id": credentials.custody_id,
            }
            plaintext = json.dumps(
                payload, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            ciphertext = protect_current_user_data(
                plaintext, purpose=self._purpose()
            )
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_name(
                ".%s.%s.tmp" % (self.path.name, secrets.token_hex(8))
            )
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
                0o600,
            )
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(ciphertext)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.path)
            finally:
                try:
                    temporary.unlink()
                except FileNotFoundError:
                    pass
            return credentials


__all__ = ["BrowserCredentialVault", "BrowserSessionCredentials"]
