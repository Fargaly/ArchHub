"""Non-exporting Windows CNG device proof keys for RFC 9449 DPoP."""
from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import hashlib
import json
import os
import re
import secrets
import struct
import time
from types import MappingProxyType
from typing import Mapping
from urllib.parse import urlsplit, urlunsplit

from .cell_dpop import normalize_dpop_target_uri


PLATFORM_PROVIDER = "Microsoft Platform Crypto Provider"
SOFTWARE_PROVIDER = "Microsoft Software Key Storage Provider"
_KEY_NAME = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_P256_PUBLIC_MAGIC = 0x31534345
_P256_ECDH_PUBLIC_MAGIC = 0x314B4345
_EXPORT_POLICY_PROPERTY = "Export Policy"
_IMPLEMENTATION_TYPE_PROPERTY = "Impl Type"
_IMPLEMENTATION_HARDWARE_FLAG = 0x00000001
_KDF_HASH_ALGORITHM = 0x00000000


class _NCryptBuffer(ctypes.Structure):
    _fields_ = [
        ("cbBuffer", wintypes.DWORD),
        ("BufferType", wintypes.DWORD),
        ("pvBuffer", ctypes.c_void_p),
    ]


class _NCryptBufferDesc(ctypes.Structure):
    _fields_ = [
        ("ulVersion", wintypes.DWORD),
        ("cBuffers", wintypes.DWORD),
        ("pBuffers", ctypes.POINTER(_NCryptBuffer)),
    ]


class DeviceProofKeyError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DeviceProofKeyReference:
    key_name: str
    provider: str
    algorithm: str
    thumbprint: str
    public_jwk: Mapping[str, str]
    hardware_backed: bool


@dataclass(frozen=True, slots=True)
class RecipientKeyReference:
    key_name: str
    provider: str
    algorithm: str
    thumbprint: str
    public_jwk: Mapping[str, str]
    hardware_backed: bool


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _canonical_json(value: Mapping[str, object]) -> bytes:
    return json.dumps(
        dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")


def _status(status: int, operation: str) -> None:
    if status:
        raise DeviceProofKeyError(
            "%s failed with CNG status 0x%08x"
            % (operation, status & 0xFFFFFFFF)
        )


class WindowsCngDeviceProofKey:
    """One persisted non-exporting P-256 signing capability.

    Production creation defaults to the TPM-backed Platform Crypto Provider.
    The software provider is accepted only with an explicit opt-in so callers
    cannot silently downgrade device-key custody.
    """

    def __init__(
        self,
        key_name: str,
        *,
        provider: str = PLATFORM_PROVIDER,
        create_if_missing: bool = False,
        allow_software: bool = False,
    ) -> None:
        if os.name != "nt":
            raise DeviceProofKeyError("Windows CNG is available only on Windows")
        if not _KEY_NAME.fullmatch(str(key_name)):
            raise ValueError("device proof-key name is invalid")
        if provider not in (PLATFORM_PROVIDER, SOFTWARE_PROVIDER):
            raise DeviceProofKeyError("device proof-key provider is not allowed")
        if provider == SOFTWARE_PROVIDER and not allow_software:
            raise DeviceProofKeyError(
                "software device-key custody requires explicit permission"
            )
        self.key_name = str(key_name)
        self.provider = provider
        self._ncrypt = ctypes.WinDLL("ncrypt.dll", use_last_error=True)
        self._provider_handle = ctypes.c_void_p()
        self._key_handle = ctypes.c_void_p()
        self._configure_api()
        try:
            _status(
                self._ncrypt.NCryptOpenStorageProvider(
                    ctypes.byref(self._provider_handle), provider, 0
                ),
                "open CNG provider",
            )
            open_status = self._ncrypt.NCryptOpenKey(
                self._provider_handle,
                ctypes.byref(self._key_handle),
                self.key_name,
                0,
                0,
            )
            if open_status:
                if not create_if_missing:
                    _status(open_status, "open device proof key")
                self._create_key()
            self._public_jwk = MappingProxyType(self._export_public_jwk())
            self._thumbprint = _b64url(
                hashlib.sha256(_canonical_json(self._public_jwk)).digest()
            )
            self._hardware_backed = bool(
                self._dword_property(
                    self._provider_handle, _IMPLEMENTATION_TYPE_PROPERTY
                ) & _IMPLEMENTATION_HARDWARE_FLAG
            )
            if provider == PLATFORM_PROVIDER and not self._hardware_backed:
                raise DeviceProofKeyError(
                    "Platform Crypto Provider did not report hardware custody"
                )
        except Exception:
            self.close()
            raise

    def _configure_api(self) -> None:
        handle = ctypes.c_void_p
        api = self._ncrypt
        api.NCryptOpenStorageProvider.argtypes = (
            ctypes.POINTER(handle), wintypes.LPCWSTR, wintypes.DWORD
        )
        api.NCryptOpenStorageProvider.restype = wintypes.LONG
        api.NCryptOpenKey.argtypes = (
            handle, ctypes.POINTER(handle), wintypes.LPCWSTR,
            wintypes.DWORD, wintypes.DWORD,
        )
        api.NCryptOpenKey.restype = wintypes.LONG
        api.NCryptCreatePersistedKey.argtypes = (
            handle, ctypes.POINTER(handle), wintypes.LPCWSTR,
            wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        )
        api.NCryptCreatePersistedKey.restype = wintypes.LONG
        api.NCryptSetProperty.argtypes = (
            handle, wintypes.LPCWSTR, ctypes.c_void_p,
            wintypes.DWORD, wintypes.DWORD,
        )
        api.NCryptSetProperty.restype = wintypes.LONG
        api.NCryptGetProperty.argtypes = (
            handle, wintypes.LPCWSTR, ctypes.c_void_p,
            wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.DWORD,
        )
        api.NCryptGetProperty.restype = wintypes.LONG
        api.NCryptFinalizeKey.argtypes = (handle, wintypes.DWORD)
        api.NCryptFinalizeKey.restype = wintypes.LONG
        api.NCryptExportKey.argtypes = (
            handle, handle, wintypes.LPCWSTR, ctypes.c_void_p,
            ctypes.c_void_p, wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD), wintypes.DWORD,
        )
        api.NCryptExportKey.restype = wintypes.LONG
        api.NCryptSignHash.argtypes = (
            handle, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
            ctypes.c_void_p, wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD), wintypes.DWORD,
        )
        api.NCryptSignHash.restype = wintypes.LONG
        api.NCryptDeleteKey.argtypes = (handle, wintypes.DWORD)
        api.NCryptDeleteKey.restype = wintypes.LONG
        api.NCryptFreeObject.argtypes = (handle,)
        api.NCryptFreeObject.restype = wintypes.LONG

    def _create_key(self) -> None:
        self._key_handle = ctypes.c_void_p()
        _status(
            self._ncrypt.NCryptCreatePersistedKey(
                self._provider_handle,
                ctypes.byref(self._key_handle),
                "ECDSA_P256",
                self.key_name,
                0,
                0,
            ),
            "create device proof key",
        )
        no_export = wintypes.DWORD(0)
        _status(
            self._ncrypt.NCryptSetProperty(
                self._key_handle,
                _EXPORT_POLICY_PROPERTY,
                ctypes.byref(no_export),
                ctypes.sizeof(no_export),
                0,
            ),
            "set non-exportable device proof-key policy",
        )
        _status(
            self._ncrypt.NCryptFinalizeKey(self._key_handle, 0),
            "finalize device proof key",
        )

    def _dword_property(self, handle, name: str) -> int:
        value = wintypes.DWORD()
        size = wintypes.DWORD()
        _status(
            self._ncrypt.NCryptGetProperty(
                handle,
                name,
                ctypes.byref(value),
                ctypes.sizeof(value),
                ctypes.byref(size),
                0,
            ),
            "read CNG property",
        )
        if size.value != ctypes.sizeof(value):
            raise DeviceProofKeyError("CNG DWORD property has invalid size")
        return int(value.value)

    def _export_public_jwk(self) -> dict[str, str]:
        size = wintypes.DWORD()
        _status(
            self._ncrypt.NCryptExportKey(
                self._key_handle,
                ctypes.c_void_p(),
                "ECCPUBLICBLOB",
                None,
                None,
                0,
                ctypes.byref(size),
                0,
            ),
            "measure device public key",
        )
        output = (ctypes.c_ubyte * size.value)()
        _status(
            self._ncrypt.NCryptExportKey(
                self._key_handle,
                ctypes.c_void_p(),
                "ECCPUBLICBLOB",
                None,
                output,
                size.value,
                ctypes.byref(size),
                0,
            ),
            "export device public key",
        )
        blob = bytes(output[:size.value])
        if len(blob) < 8:
            raise DeviceProofKeyError("CNG public key blob is truncated")
        magic, coordinate_size = struct.unpack("<II", blob[:8])
        if magic != _P256_PUBLIC_MAGIC or coordinate_size != 32:
            raise DeviceProofKeyError("CNG device key is not P-256")
        if len(blob) != 8 + coordinate_size * 2:
            raise DeviceProofKeyError("CNG public key blob has invalid size")
        x = blob[8:8 + coordinate_size]
        y = blob[8 + coordinate_size:]
        return {
            "crv": "P-256",
            "kty": "EC",
            "x": _b64url(x),
            "y": _b64url(y),
        }

    @property
    def reference(self) -> DeviceProofKeyReference:
        return DeviceProofKeyReference(
            self.key_name,
            self.provider,
            "ES256",
            self._thumbprint,
            self._public_jwk,
            self._hardware_backed,
        )

    def sign_digest(self, digest: bytes) -> bytes:
        if not self._key_handle.value:
            raise DeviceProofKeyError("device proof key is closed")
        digest = bytes(digest)
        if len(digest) != 32:
            raise ValueError("ES256 device signature requires one SHA-256 digest")
        source = (ctypes.c_ubyte * len(digest)).from_buffer_copy(digest)
        size = wintypes.DWORD()
        _status(
            self._ncrypt.NCryptSignHash(
                self._key_handle,
                None,
                source,
                len(digest),
                None,
                0,
                ctypes.byref(size),
                0,
            ),
            "measure device signature",
        )
        output = (ctypes.c_ubyte * size.value)()
        _status(
            self._ncrypt.NCryptSignHash(
                self._key_handle,
                None,
                source,
                len(digest),
                output,
                size.value,
                ctypes.byref(size),
                0,
            ),
            "sign device proof",
        )
        signature = bytes(output[:size.value])
        if len(signature) != 64:
            raise DeviceProofKeyError("CNG ES256 signature has invalid size")
        return signature

    def dpop_proof(
        self,
        *,
        http_method: str,
        target_uri: str,
        access_token: str,
        nonce: str,
        issued_at: float | None = None,
        proof_id: str | None = None,
    ) -> bytes:
        if not access_token or not access_token.isascii() or not nonce:
            raise ValueError("DPoP access token and nonce are required")
        method = str(http_method).upper()
        if not method or not method.isascii():
            raise ValueError("DPoP HTTP method is invalid")
        target = normalize_dpop_target_uri(target_uri)
        parsed = urlsplit(target)
        htu = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
        header = {
            "alg": "ES256",
            "jwk": dict(self._public_jwk),
            "typ": "dpop+jwt",
        }
        claims = {
            "ath": _b64url(hashlib.sha256(access_token.encode("ascii")).digest()),
            "htm": method,
            "htu": htu,
            "iat": int(time.time() if issued_at is None else issued_at),
            "jti": proof_id or secrets.token_urlsafe(24),
            "nonce": nonce,
        }
        protected = _b64url(_canonical_json(header))
        payload = _b64url(_canonical_json(claims))
        signing_input = (protected + "." + payload).encode("ascii")
        signature = self.sign_digest(hashlib.sha256(signing_input).digest())
        return (protected + "." + payload + "." + _b64url(signature)).encode(
            "ascii"
        )

    def close(self) -> None:
        if getattr(self, "_key_handle", None) is not None \
                and self._key_handle.value:
            self._ncrypt.NCryptFreeObject(self._key_handle)
            self._key_handle = ctypes.c_void_p()
        if getattr(self, "_provider_handle", None) is not None \
                and self._provider_handle.value:
            self._ncrypt.NCryptFreeObject(self._provider_handle)
            self._provider_handle = ctypes.c_void_p()

    def delete_test_key(self) -> None:
        """Delete only an explicitly named software court key."""
        if (
            self.provider != SOFTWARE_PROVIDER
            or not self.key_name.startswith("ArchHub.Test.")
        ):
            raise DeviceProofKeyError(
                "only isolated ArchHub software test keys may be deleted here"
            )
        if not self._key_handle.value:
            raise DeviceProofKeyError("device proof key is closed")
        _status(
            self._ncrypt.NCryptDeleteKey(self._key_handle, 0),
            "delete isolated device proof test key",
        )
        self._key_handle = ctypes.c_void_p()

    def __enter__(self):
        return self

    def __exit__(self, _type, _value, _traceback):
        self.close()


class WindowsCngRecipientKey:
    """One persisted non-exporting P-256 ECDH recipient capability.

    This key is deliberately distinct from the device signing key. Production
    defaults to TPM-backed custody; a software provider exists only for courts.
    """

    def __init__(
        self,
        key_name: str,
        *,
        provider: str = PLATFORM_PROVIDER,
        create_if_missing: bool = False,
        allow_software: bool = False,
    ) -> None:
        if os.name != "nt":
            raise DeviceProofKeyError("Windows CNG is available only on Windows")
        if not _KEY_NAME.fullmatch(str(key_name)):
            raise ValueError("recipient key name is invalid")
        if provider not in (PLATFORM_PROVIDER, SOFTWARE_PROVIDER):
            raise DeviceProofKeyError("recipient key provider is not allowed")
        if provider == SOFTWARE_PROVIDER and not allow_software:
            raise DeviceProofKeyError(
                "software recipient-key custody requires explicit permission"
            )
        self.key_name = str(key_name)
        self.provider = provider
        self._ncrypt = ctypes.WinDLL("ncrypt.dll", use_last_error=True)
        self._provider_handle = ctypes.c_void_p()
        self._key_handle = ctypes.c_void_p()
        self._configure_api()
        try:
            _status(
                self._ncrypt.NCryptOpenStorageProvider(
                    ctypes.byref(self._provider_handle), provider, 0
                ),
                "open CNG recipient provider",
            )
            open_status = self._ncrypt.NCryptOpenKey(
                self._provider_handle,
                ctypes.byref(self._key_handle),
                self.key_name,
                0,
                0,
            )
            if open_status:
                if not create_if_missing:
                    _status(open_status, "open recipient key")
                self._create_key()
            self._public_jwk = MappingProxyType(self._export_public_jwk())
            self._thumbprint = _b64url(
                hashlib.sha256(_canonical_json(self._public_jwk)).digest()
            )
            self._hardware_backed = bool(
                self._dword_property(
                    self._provider_handle, _IMPLEMENTATION_TYPE_PROPERTY
                ) & _IMPLEMENTATION_HARDWARE_FLAG
            )
            if provider == PLATFORM_PROVIDER and not self._hardware_backed:
                raise DeviceProofKeyError(
                    "Platform Crypto Provider did not report hardware custody"
                )
        except Exception:
            self.close()
            raise

    def _configure_api(self) -> None:
        handle = ctypes.c_void_p
        api = self._ncrypt
        api.NCryptOpenStorageProvider.argtypes = (
            ctypes.POINTER(handle), wintypes.LPCWSTR, wintypes.DWORD
        )
        api.NCryptOpenStorageProvider.restype = wintypes.LONG
        api.NCryptOpenKey.argtypes = (
            handle, ctypes.POINTER(handle), wintypes.LPCWSTR,
            wintypes.DWORD, wintypes.DWORD,
        )
        api.NCryptOpenKey.restype = wintypes.LONG
        api.NCryptCreatePersistedKey.argtypes = (
            handle, ctypes.POINTER(handle), wintypes.LPCWSTR,
            wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        )
        api.NCryptCreatePersistedKey.restype = wintypes.LONG
        api.NCryptSetProperty.argtypes = (
            handle, wintypes.LPCWSTR, ctypes.c_void_p,
            wintypes.DWORD, wintypes.DWORD,
        )
        api.NCryptSetProperty.restype = wintypes.LONG
        api.NCryptGetProperty.argtypes = (
            handle, wintypes.LPCWSTR, ctypes.c_void_p,
            wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.DWORD,
        )
        api.NCryptGetProperty.restype = wintypes.LONG
        api.NCryptFinalizeKey.argtypes = (handle, wintypes.DWORD)
        api.NCryptFinalizeKey.restype = wintypes.LONG
        api.NCryptExportKey.argtypes = (
            handle, handle, wintypes.LPCWSTR, ctypes.c_void_p,
            ctypes.c_void_p, wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD), wintypes.DWORD,
        )
        api.NCryptExportKey.restype = wintypes.LONG
        api.NCryptImportKey.argtypes = (
            handle, handle, wintypes.LPCWSTR, ctypes.c_void_p,
            ctypes.POINTER(handle), ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
        )
        api.NCryptImportKey.restype = wintypes.LONG
        api.NCryptSecretAgreement.argtypes = (
            handle, handle, ctypes.POINTER(handle), wintypes.DWORD
        )
        api.NCryptSecretAgreement.restype = wintypes.LONG
        api.NCryptDeriveKey.argtypes = (
            handle, wintypes.LPCWSTR, ctypes.c_void_p, ctypes.c_void_p,
            wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.DWORD,
        )
        api.NCryptDeriveKey.restype = wintypes.LONG
        api.NCryptDeleteKey.argtypes = (handle, wintypes.DWORD)
        api.NCryptDeleteKey.restype = wintypes.LONG
        api.NCryptFreeObject.argtypes = (handle,)
        api.NCryptFreeObject.restype = wintypes.LONG

    def _create_key(self) -> None:
        self._key_handle = ctypes.c_void_p()
        _status(
            self._ncrypt.NCryptCreatePersistedKey(
                self._provider_handle,
                ctypes.byref(self._key_handle),
                "ECDH_P256",
                self.key_name,
                0,
                0,
            ),
            "create recipient key",
        )
        no_export = wintypes.DWORD(0)
        _status(
            self._ncrypt.NCryptSetProperty(
                self._key_handle,
                _EXPORT_POLICY_PROPERTY,
                ctypes.byref(no_export),
                ctypes.sizeof(no_export),
                0,
            ),
            "set non-exportable recipient-key policy",
        )
        _status(
            self._ncrypt.NCryptFinalizeKey(self._key_handle, 0),
            "finalize recipient key",
        )

    def _dword_property(self, handle, name: str) -> int:
        value = wintypes.DWORD()
        size = wintypes.DWORD()
        _status(
            self._ncrypt.NCryptGetProperty(
                handle,
                name,
                ctypes.byref(value),
                ctypes.sizeof(value),
                ctypes.byref(size),
                0,
            ),
            "read CNG recipient property",
        )
        if size.value != ctypes.sizeof(value):
            raise DeviceProofKeyError("CNG DWORD property has invalid size")
        return int(value.value)

    def _export_public_jwk(self) -> dict[str, str]:
        size = wintypes.DWORD()
        _status(
            self._ncrypt.NCryptExportKey(
                self._key_handle,
                ctypes.c_void_p(),
                "ECCPUBLICBLOB",
                None,
                None,
                0,
                ctypes.byref(size),
                0,
            ),
            "measure recipient public key",
        )
        output = (ctypes.c_ubyte * size.value)()
        _status(
            self._ncrypt.NCryptExportKey(
                self._key_handle,
                ctypes.c_void_p(),
                "ECCPUBLICBLOB",
                None,
                output,
                size.value,
                ctypes.byref(size),
                0,
            ),
            "export recipient public key",
        )
        blob = bytes(output[:size.value])
        if len(blob) < 8:
            raise DeviceProofKeyError("CNG recipient public key blob is truncated")
        magic, coordinate_size = struct.unpack("<II", blob[:8])
        if magic != _P256_ECDH_PUBLIC_MAGIC or coordinate_size != 32:
            raise DeviceProofKeyError("CNG recipient key is not P-256 ECDH")
        if len(blob) != 8 + coordinate_size * 2:
            raise DeviceProofKeyError("CNG recipient public key blob has invalid size")
        x = blob[8:8 + coordinate_size]
        y = blob[8 + coordinate_size:]
        return {
            "crv": "P-256",
            "kty": "EC",
            "x": _b64url(x),
            "y": _b64url(y),
        }

    @property
    def reference(self) -> RecipientKeyReference:
        return RecipientKeyReference(
            self.key_name,
            self.provider,
            "ECDH-ES",
            self._thumbprint,
            self._public_jwk,
            self._hardware_backed,
        )

    def derive_shared_secret(self, peer_public_jwk: Mapping[str, str]) -> bytes:
        """Derive CNG's SHA-256 ECDH key material for an imported public peer."""
        if not self._key_handle.value:
            raise DeviceProofKeyError("recipient key is closed")
        if not isinstance(peer_public_jwk, Mapping) or set(peer_public_jwk) != {
            "crv", "kty", "x", "y"
        }:
            raise ValueError("recipient peer public JWK is invalid")
        if peer_public_jwk.get("kty") != "EC" or peer_public_jwk.get("crv") != "P-256":
            raise ValueError("recipient peer public JWK must be P-256")
        try:
            x = base64.urlsafe_b64decode(str(peer_public_jwk["x"]) + "=" * (-len(str(peer_public_jwk["x"])) % 4))
            y = base64.urlsafe_b64decode(str(peer_public_jwk["y"]) + "=" * (-len(str(peer_public_jwk["y"])) % 4))
        except (KeyError, UnicodeEncodeError, ValueError) as exc:
            raise ValueError("recipient peer public JWK is invalid") from exc
        if len(x) != 32 or len(y) != 32:
            raise ValueError("recipient peer public JWK coordinates are invalid")
        blob = struct.pack("<II", _P256_ECDH_PUBLIC_MAGIC, 32) + x + y
        buffer = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
        peer_handle = ctypes.c_void_p()
        secret_handle = ctypes.c_void_p()
        try:
            _status(
                self._ncrypt.NCryptImportKey(
                    self._provider_handle,
                    ctypes.c_void_p(),
                    "ECCPUBLICBLOB",
                    None,
                    ctypes.byref(peer_handle),
                    buffer,
                    len(blob),
                    0,
                ),
                "import recipient peer public key",
            )
            _status(
                self._ncrypt.NCryptSecretAgreement(
                    self._key_handle, peer_handle, ctypes.byref(secret_handle), 0
                ),
                "derive recipient secret agreement",
            )
            algorithm = ctypes.create_unicode_buffer("SHA256")
            buffers = (_NCryptBuffer * 1)(
                _NCryptBuffer(
                    ctypes.sizeof(algorithm),
                    _KDF_HASH_ALGORITHM,
                    ctypes.cast(algorithm, ctypes.c_void_p),
                )
            )
            descriptor = _NCryptBufferDesc(0, len(buffers), buffers)
            size = wintypes.DWORD()
            _status(
                self._ncrypt.NCryptDeriveKey(
                    secret_handle,
                    "HASH",
                    ctypes.byref(descriptor),
                    None,
                    0,
                    ctypes.byref(size),
                    0,
                ),
                "measure recipient shared secret",
            )
            if size.value != 32:
                raise DeviceProofKeyError("CNG P-256 shared secret has invalid size")
            output = (ctypes.c_ubyte * size.value)()
            _status(
                self._ncrypt.NCryptDeriveKey(
                    secret_handle,
                    "HASH",
                    ctypes.byref(descriptor),
                    output,
                    size.value,
                    ctypes.byref(size),
                    0,
                ),
                "derive recipient shared secret",
            )
            return bytes(output[:size.value])
        finally:
            if secret_handle.value:
                self._ncrypt.NCryptFreeObject(secret_handle)
            if peer_handle.value:
                self._ncrypt.NCryptFreeObject(peer_handle)

    def close(self) -> None:
        if getattr(self, "_key_handle", None) is not None and self._key_handle.value:
            self._ncrypt.NCryptFreeObject(self._key_handle)
            self._key_handle = ctypes.c_void_p()
        if getattr(self, "_provider_handle", None) is not None and self._provider_handle.value:
            self._ncrypt.NCryptFreeObject(self._provider_handle)
            self._provider_handle = ctypes.c_void_p()

    def delete_test_key(self) -> None:
        if (
            self.provider != SOFTWARE_PROVIDER
            or not self.key_name.startswith("ArchHub.Test.")
        ):
            raise DeviceProofKeyError(
                "only isolated ArchHub software test keys may be deleted here"
            )
        if not self._key_handle.value:
            raise DeviceProofKeyError("recipient key is closed")
        _status(
            self._ncrypt.NCryptDeleteKey(self._key_handle, 0),
            "delete isolated recipient test key",
        )
        self._key_handle = ctypes.c_void_p()

    def __enter__(self):
        return self

    def __exit__(self, _type, _value, _traceback):
        self.close()


__all__ = [
    "DeviceProofKeyError",
    "DeviceProofKeyReference",
    "PLATFORM_PROVIDER",
    "RecipientKeyReference",
    "SOFTWARE_PROVIDER",
    "WindowsCngDeviceProofKey",
    "WindowsCngRecipientKey",
]
