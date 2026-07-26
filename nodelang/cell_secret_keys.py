"""External signing-key custody for universal-cell authority protocols.

Keys are runtime capabilities, never Cell atoms.  The graph stores only a
stable key reference and version so signatures remain inspectable and old
revisions remain verifiable after rotation.
"""
from __future__ import annotations

from dataclasses import dataclass
import base64
import ctypes
from ctypes import wintypes
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import threading
from types import MappingProxyType
from typing import Mapping, Protocol


_KEY_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_AWS_KMS_KEY_ARN = re.compile(
    r"^arn:(?:aws|aws-us-gov|aws-cn):kms:"
    r"[a-z0-9-]{1,64}:\d{12}:key/[A-Za-z0-9-]{1,128}$"
)


class SigningKeyError(RuntimeError):
    """A signing key is unavailable, corrupt, or outside its custody policy."""


@dataclass(frozen=True, slots=True)
class SigningKeyMaterial:
    key_id: str
    version: int
    secret: bytes

    def __post_init__(self) -> None:
        if not _KEY_ID.fullmatch(self.key_id):
            raise ValueError("signing key reference is invalid")
        if self.version < 1:
            raise ValueError("signing key version must be positive")
        if len(self.secret) < 32:
            raise ValueError("signing key material must contain at least 256 bits")


@dataclass(frozen=True, slots=True)
class SigningKeyReference:
    """Non-secret key identity safe to persist in graph evidence."""

    key_id: str
    version: int

    def __post_init__(self) -> None:
        if not _KEY_ID.fullmatch(self.key_id):
            raise ValueError("signing key reference is invalid")
        if self.version < 1:
            raise ValueError("signing key version must be positive")


class SigningKeyProvider(Protocol):
    """Non-exporting signing capability used by authority protocols."""

    def current_reference(self, key_id: str) -> SigningKeyReference:
        ...

    def sign(self, key_id: str, version: int, payload: bytes) -> str:
        ...

    def verify(
        self, key_id: str, version: int, payload: bytes, signature: str
    ) -> bool:
        ...


class MemorySigningKeyProvider:
    """Deterministic test/process provider; it never serializes key material."""

    def __init__(
        self,
        key_id: str = "process-ephemeral",
        secret: bytes | None = None,
        *,
        version: int = 1,
    ) -> None:
        material = SigningKeyMaterial(
            key_id, version, secret if secret is not None else secrets.token_bytes(32)
        )
        self._keys: dict[str, dict[int, bytes]] = {
            key_id: {version: material.secret}
        }
        self._current: dict[str, int] = {key_id: version}
        self._lock = threading.RLock()

    def add_key(
        self,
        key_id: str,
        secret: bytes | None = None,
        *,
        version: int = 1,
    ) -> SigningKeyMaterial:
        material = SigningKeyMaterial(
            key_id, version, secret if secret is not None else secrets.token_bytes(32)
        )
        with self._lock:
            if key_id in self._keys:
                raise SigningKeyError("signing key reference already exists")
            self._keys[key_id] = {version: material.secret}
            self._current[key_id] = version
        return material

    def current(self, key_id: str) -> SigningKeyMaterial:
        with self._lock:
            version = self._current.get(key_id)
            if version is None:
                raise SigningKeyError("unknown signing key reference")
            return SigningKeyMaterial(key_id, version, self._keys[key_id][version])

    def resolve(self, key_id: str, version: int) -> SigningKeyMaterial:
        with self._lock:
            try:
                secret = self._keys[key_id][version]
            except KeyError as exc:
                raise SigningKeyError("unknown signing key reference or version") from exc
            return SigningKeyMaterial(key_id, version, secret)

    def current_reference(self, key_id: str) -> SigningKeyReference:
        material = self.current(key_id)
        return SigningKeyReference(material.key_id, material.version)

    def sign(self, key_id: str, version: int, payload: bytes) -> str:
        material = self.resolve(key_id, version)
        return hmac.new(material.secret, bytes(payload), hashlib.sha256).hexdigest()

    def verify(
        self, key_id: str, version: int, payload: bytes, signature: str
    ) -> bool:
        try:
            expected = self.sign(key_id, version, payload)
        except SigningKeyError:
            return False
        return hmac.compare_digest(expected, signature)

    def rotate(self, key_id: str, secret: bytes | None = None) -> SigningKeyMaterial:
        with self._lock:
            previous = self._current.get(key_id)
            if previous is None:
                raise SigningKeyError("unknown signing key reference")
            version = previous + 1
            material = SigningKeyMaterial(
                key_id,
                version,
                secret if secret is not None else secrets.token_bytes(32),
            )
            self._keys[key_id][version] = material.secret
            self._current[key_id] = version
            return material

    def versions(self, key_id: str) -> Mapping[int, bytes]:
        with self._lock:
            try:
                return MappingProxyType(dict(self._keys[key_id]))
            except KeyError as exc:
                raise SigningKeyError("unknown signing key reference") from exc


class AwsKmsHmacSigningKeyProvider:
    """Non-exporting HMAC custody through a versioned AWS KMS key map."""

    _ALGORITHM = "HMAC_SHA_256"
    _MESSAGE_DOMAIN = b"ArchHub/aws-kms-hmac-provider/v1\x00"

    def __init__(
        self,
        keys: Mapping[str, Mapping[int, str]],
        *,
        client=None,
    ) -> None:
        if not isinstance(keys, Mapping) or not keys:
            raise SigningKeyError("AWS KMS signing key map is required")
        admitted: dict[str, dict[int, str]] = {}
        for key_id, versions in keys.items():
            if not isinstance(key_id, str) or not _KEY_ID.fullmatch(key_id):
                raise SigningKeyError(
                    "AWS KMS logical signing key reference is invalid"
                )
            if not isinstance(versions, Mapping) or not versions:
                raise SigningKeyError(
                    "AWS KMS signing key versions are required"
                )
            admitted_versions: dict[int, str] = {}
            for version, key_arn in versions.items():
                if (
                    type(version) is not int
                    or version < 1
                    or not isinstance(key_arn, str)
                    or not _AWS_KMS_KEY_ARN.fullmatch(key_arn)
                ):
                    raise SigningKeyError(
                        "AWS KMS signing key version requires an exact key ARN"
                    )
                admitted_versions[version] = key_arn
            admitted[key_id] = admitted_versions
        self._keys = {
            key_id: MappingProxyType(dict(versions))
            for key_id, versions in admitted.items()
        }
        self._current = {
            key_id: max(versions)
            for key_id, versions in admitted.items()
        }
        self._client = client if client is not None else self._build_client()

    @staticmethod
    def _build_client():
        try:
            import boto3
        except ImportError:
            raise SigningKeyError(
                "boto3 is required for AWS KMS signing custody"
            ) from None
        try:
            return boto3.client("kms")
        except Exception as exc:
            raise SigningKeyError(
                "AWS KMS client admission failed (%s)"
                % type(exc).__name__
            ) from None

    @classmethod
    def _message(cls, payload: bytes) -> bytes:
        return cls._MESSAGE_DOMAIN + hashlib.sha256(bytes(payload)).digest()

    def _key_arn(self, key_id: str, version: int) -> str:
        try:
            return self._keys[key_id][version]
        except (KeyError, TypeError):
            raise SigningKeyError(
                "unknown AWS KMS signing key reference or version"
            ) from None

    def current_reference(self, key_id: str) -> SigningKeyReference:
        try:
            version = self._current[key_id]
        except (KeyError, TypeError):
            raise SigningKeyError(
                "unknown AWS KMS signing key reference"
            ) from None
        return SigningKeyReference(key_id, version)

    def sign(self, key_id: str, version: int, payload: bytes) -> str:
        key_arn = self._key_arn(key_id, version)
        try:
            response = self._client.generate_mac(
                KeyId=key_arn,
                Message=self._message(payload),
                MacAlgorithm=self._ALGORITHM,
            )
        except Exception as exc:
            raise SigningKeyError(
                "AWS KMS signing operation failed (%s)"
                % type(exc).__name__
            ) from None
        mac = response.get("Mac") if isinstance(response, Mapping) else None
        if (
            not isinstance(response, Mapping)
            or response.get("KeyId") != key_arn
            or response.get("MacAlgorithm") != self._ALGORITHM
            or not isinstance(mac, (bytes, bytearray))
            or len(mac) != 32
        ):
            raise SigningKeyError("AWS KMS signing response is invalid")
        return bytes(mac).hex()

    def verify(
        self,
        key_id: str,
        version: int,
        payload: bytes,
        signature: str,
    ) -> bool:
        try:
            key_arn = self._key_arn(key_id, version)
            if (
                not isinstance(signature, str)
                or len(signature) != 64
                or any(
                    character not in "0123456789abcdef"
                    for character in signature
                )
            ):
                return False
            response = self._client.verify_mac(
                KeyId=key_arn,
                Message=self._message(payload),
                MacAlgorithm=self._ALGORITHM,
                Mac=bytes.fromhex(signature),
            )
        except (SigningKeyError, ValueError):
            return False
        except Exception:
            return False
        return bool(
            isinstance(response, Mapping)
            and response.get("KeyId") == key_arn
            and response.get("MacAlgorithm") == self._ALGORITHM
            and response.get("MacValid") is True
        )


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


class WindowsDpapiSigningKeyProvider:
    """Persistent current-user key ring protected by Windows DPAPI.

    The JSON file contains ciphertext and non-secret metadata only.  DPAPI binds
    decryption to the current Windows logon and supplies an integrity check.
    """

    FORMAT = "archhub.signing-key-ring"
    FORMAT_VERSION = 1

    def __init__(self, path: str | os.PathLike[str]) -> None:
        if os.name != "nt":
            raise SigningKeyError("Windows DPAPI key custody requires Windows")
        self.path = Path(path).expanduser().resolve()
        self._lock = threading.RLock()
        self._cached_payload: dict[str, object] | None = None
        self._cached_fingerprint: tuple[int, int] | None = None
        self._material_cache: dict[tuple[str, int], SigningKeyMaterial] = {}

    @staticmethod
    def default_path() -> Path:
        local = os.environ.get("LOCALAPPDATA")
        if not local:
            raise SigningKeyError("LOCALAPPDATA is unavailable")
        return Path(local) / "ArchHub" / "keys" / "authority-signing-v1.dpapi.json"

    @staticmethod
    def _validate_key_id(key_id: str) -> None:
        if not _KEY_ID.fullmatch(key_id):
            raise ValueError("signing key reference is invalid")

    @staticmethod
    def _entropy(key_id: str, version: int) -> bytes:
        return ("ArchHub/authority-signing/v1/%s/%s" % (key_id, version)).encode("utf-8")

    def _empty(self) -> dict[str, object]:
        return {
            "format": self.FORMAT,
            "format_version": self.FORMAT_VERSION,
            "keys": {},
        }

    def _load(self) -> dict[str, object]:
        try:
            stat = self.path.stat()
        except FileNotFoundError:
            if self._cached_fingerprint is None and self._cached_payload is not None:
                return self._cached_payload
            payload = self._empty()
            self._cached_payload = payload
            self._cached_fingerprint = None
            self._material_cache.clear()
            return payload
        fingerprint = (int(stat.st_mtime_ns), int(stat.st_size))
        if (
            self._cached_payload is not None
            and self._cached_fingerprint == fingerprint
        ):
            return self._cached_payload
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise SigningKeyError("signing key ring is unreadable") from exc
        if (
            payload.get("format") != self.FORMAT
            or payload.get("format_version") != self.FORMAT_VERSION
            or not isinstance(payload.get("keys"), dict)
        ):
            raise SigningKeyError("signing key ring format is invalid")
        self._cached_payload = payload
        self._cached_fingerprint = fingerprint
        self._material_cache.clear()
        return payload

    def _save(self, payload: Mapping[str, object]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
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
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            stat = self.path.stat()
            self._cached_payload = dict(payload)
            self._cached_fingerprint = (int(stat.st_mtime_ns), int(stat.st_size))
            self._material_cache.clear()
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def _material(self, payload: Mapping[str, object], key_id: str, version: int) -> SigningKeyMaterial:
        cache_key = (key_id, int(version))
        cached = self._material_cache.get(cache_key)
        if cached is not None:
            return cached
        try:
            keys = payload["keys"]
            record = keys[key_id]  # type: ignore[index]
            encoded = record["versions"][str(version)]
            ciphertext = base64.b64decode(encoded, validate=True)
        except (KeyError, TypeError, ValueError) as exc:
            raise SigningKeyError("unknown signing key reference or version") from exc
        secret = _windows_dpapi(
            ciphertext, self._entropy(key_id, version), protect=False
        )
        material = SigningKeyMaterial(key_id, version, secret)
        self._material_cache[cache_key] = material
        return material

    def current(self, key_id: str) -> SigningKeyMaterial:
        self._validate_key_id(key_id)
        with self._lock:
            payload = self._load()
            keys = payload["keys"]
            if key_id not in keys:  # type: ignore[operator]
                version = 1
                secret = secrets.token_bytes(32)
                ciphertext = _windows_dpapi(
                    secret, self._entropy(key_id, version), protect=True
                )
                keys[key_id] = {  # type: ignore[index]
                    "current": version,
                    "versions": {str(version): base64.b64encode(ciphertext).decode("ascii")},
                }
                self._save(payload)
                material = SigningKeyMaterial(key_id, version, secret)
                self._material_cache[(key_id, version)] = material
                return material
            try:
                version = int(keys[key_id]["current"])  # type: ignore[index]
            except (KeyError, TypeError, ValueError) as exc:
                raise SigningKeyError("signing key ring current version is invalid") from exc
            return self._material(payload, key_id, version)

    def resolve(self, key_id: str, version: int) -> SigningKeyMaterial:
        self._validate_key_id(key_id)
        if version < 1:
            raise SigningKeyError("signing key version is invalid")
        with self._lock:
            return self._material(self._load(), key_id, version)

    def current_reference(self, key_id: str) -> SigningKeyReference:
        material = self.current(key_id)
        return SigningKeyReference(material.key_id, material.version)

    def sign(self, key_id: str, version: int, payload: bytes) -> str:
        material = self.resolve(key_id, version)
        return hmac.new(material.secret, bytes(payload), hashlib.sha256).hexdigest()

    def verify(
        self, key_id: str, version: int, payload: bytes, signature: str
    ) -> bool:
        try:
            expected = self.sign(key_id, version, payload)
        except SigningKeyError:
            return False
        return hmac.compare_digest(expected, signature)

    def rotate(self, key_id: str) -> SigningKeyMaterial:
        self._validate_key_id(key_id)
        with self._lock:
            payload = self._load()
            keys = payload["keys"]
            if key_id not in keys:  # type: ignore[operator]
                self.current(key_id)
                payload = self._load()
                keys = payload["keys"]
            record = keys[key_id]  # type: ignore[index]
            try:
                version = int(record["current"]) + 1
            except (KeyError, TypeError, ValueError) as exc:
                raise SigningKeyError("signing key ring current version is invalid") from exc
            secret = secrets.token_bytes(32)
            ciphertext = _windows_dpapi(
                secret, self._entropy(key_id, version), protect=True
            )
            record["versions"][str(version)] = base64.b64encode(ciphertext).decode("ascii")
            record["current"] = version
            self._save(payload)
            return SigningKeyMaterial(key_id, version, secret)


__all__ = [
    "SigningKeyError",
    "SigningKeyMaterial",
    "SigningKeyReference",
    "SigningKeyProvider",
    "MemorySigningKeyProvider",
    "AwsKmsHmacSigningKeyProvider",
    "WindowsDpapiSigningKeyProvider",
    "protect_current_user_data",
    "unprotect_current_user_data",
]
