"""Current-user custody for browser capabilities that survive worker handoff."""
from __future__ import annotations

from .user_paths import state_directory

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import secrets
import threading



class SigningKeyError(RuntimeError):
    """A signing key is unavailable, corrupt, or outside its custody policy."""

class _DataBlob(ctypes.Structure):
    _fields_ = (
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    )

def _input_blob(data: bytes) -> tuple[_DataBlob, object]:
    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    return _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))), buffer

def _windows_dpapi(data: bytes, entropy: bytes, *, protect: bool) -> bytes:
    if os.name != "nt":
        raise SigningKeyError("Windows DPAPI is available only on Windows")
    crypt32 = ctypes.WinDLL("Crypt32.dll", use_last_error=True)
    kernel32 = ctypes.WinDLL("Kernel32.dll", use_last_error=True)
    function = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    function.argtypes = (
        ctypes.POINTER(_DataBlob),
        wintypes.LPCWSTR if protect else ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(_DataBlob),
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    )
    function.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = (wintypes.HLOCAL,)
    kernel32.LocalFree.restype = wintypes.HLOCAL
    source, source_buffer = _input_blob(data)
    entropy_blob, entropy_buffer = _input_blob(entropy)
    output = _DataBlob()
    description = None if protect else wintypes.LPWSTR()
    description_arg = "ArchHub signing key" if protect else ctypes.byref(description)
    result = function(
        ctypes.byref(source),
        description_arg,
        ctypes.byref(entropy_blob),
        None,
        None,
        0x1,  # CRYPTPROTECT_UI_FORBIDDEN
        ctypes.byref(output),
    )
    del source_buffer, entropy_buffer
    if not result:
        error = ctypes.get_last_error()
        raise SigningKeyError("Windows DPAPI operation failed: %s" % error)
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(output.pbData, wintypes.HLOCAL))
        if not protect and description.value:
            kernel32.LocalFree(ctypes.cast(description, wintypes.HLOCAL))

def protect_current_user_data(data: bytes, *, purpose: str) -> bytes:
    """Protect opaque bytes for this Windows user with purpose separation."""
    raw = bytes(data)
    label = str(purpose).strip()
    if not raw or not label or len(label.encode("utf-8")) > 512:
        raise ValueError("DPAPI data and bounded purpose are required")
    entropy = hashlib.sha256(
        ("ArchHub/current-user-data/v1/" + label).encode("utf-8")
    ).digest()
    return _windows_dpapi(raw, entropy, protect=True)

def unprotect_current_user_data(data: bytes, *, purpose: str) -> bytes:
    """Recover bytes protected for this Windows user and exact purpose."""
    raw = bytes(data)
    label = str(purpose).strip()
    if not raw or not label or len(label.encode("utf-8")) > 512:
        raise ValueError("DPAPI data and bounded purpose are required")
    entropy = hashlib.sha256(
        ("ArchHub/current-user-data/v1/" + label).encode("utf-8")
    ).digest()
    return _windows_dpapi(raw, entropy, protect=False)


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
        if not local and not os.environ.get("ARCHHUB_TEST_STATE_DIR"):
            raise SigningKeyError("LOCALAPPDATA is unavailable")
        return state_directory() / "runtime" / "browser-session-v1.dpapi"

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


import re

_LOOKS_LIKE_A_SECRET = re.compile(
    r"(?i)(?:^(?:sk|pk|ghp|xox[abps]|ah_live|AKIA)[-_A-Za-z0-9]{8,}$"
    r"|^bearer\s+\S+$"
    r"|\b(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|password|secret)"
    r"\s*[:=]\s*\S+)"
)

_HIGH_ENTROPY = re.compile(r"^[A-Za-z0-9+/=_-]{40,}$")

def assert_not_a_secret(value: str, label: str) -> None:
    """Refuse anything that reads like the secret itself."""
    if _LOOKS_LIKE_A_SECRET.search(value) or _HIGH_ENTROPY.match(value):
        raise ValueError("%s looks like a credential, not a reference" % label)
