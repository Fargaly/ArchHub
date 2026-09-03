"""Persisted Windows CNG signing provider for graph-held authority.

The public provider surface can describe, sign, and verify only. Private-key
export, arbitrary provider selection, overwrite, import, and deletion are not
capabilities of this adapter.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import hashlib
import hmac
import os
import re
import threading
from urllib.parse import quote, unquote

from .cell_signing_authority import (
    ProviderKeyMetadata,
    ProviderSignRequest,
    ProviderSignResponse,
    SigningAuthorityDenied,
)


WINDOWS_CNG_PROVIDER_PROTOCOL = (
    "https://archhub.local/provider/windows-cng/v1"
)
SOFTWARE_PROVIDER_ID = "windows-cng-software"
PLATFORM_PROVIDER_ID = "windows-cng-platform"

_PROVIDERS = {
    SOFTWARE_PROVIDER_ID: (
        "Microsoft Software Key Storage Provider",
        "windows-cng-software-user",
    ),
    PLATFORM_PROVIDER_ID: (
        "Microsoft Platform Crypto Provider",
        "windows-tpm-user",
    ),
}
_KEY_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,191}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_NTE_BAD_KEYSET = 0x80090016
_NTE_EXISTS = 0x8009000F
_NCRYPT_SILENT_FLAG = 0x00000040
_ECDSA_P256 = "ECDSA_P256"
_PUBLIC_BLOB = "ECCPUBLICBLOB"


class _Ncrypt:
    def __init__(self) -> None:
        if os.name != "nt":
            raise SigningAuthorityDenied("Windows CNG is unavailable")
        library = ctypes.WinDLL("ncrypt.dll")
        handle = ctypes.c_void_p
        dword = wintypes.DWORD
        status = ctypes.c_long

        library.NCryptOpenStorageProvider.argtypes = (
            ctypes.POINTER(handle), wintypes.LPCWSTR, dword
        )
        library.NCryptOpenStorageProvider.restype = status
        library.NCryptCreatePersistedKey.argtypes = (
            handle,
            ctypes.POINTER(handle),
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            dword,
            dword,
        )
        library.NCryptCreatePersistedKey.restype = status
        library.NCryptOpenKey.argtypes = (
            handle, ctypes.POINTER(handle), wintypes.LPCWSTR, dword, dword
        )
        library.NCryptOpenKey.restype = status
        library.NCryptSetProperty.argtypes = (
            handle, wintypes.LPCWSTR, ctypes.c_void_p, dword, dword
        )
        library.NCryptSetProperty.restype = status
        library.NCryptFinalizeKey.argtypes = (handle, dword)
        library.NCryptFinalizeKey.restype = status
        library.NCryptExportKey.argtypes = (
            handle,
            handle,
            wintypes.LPCWSTR,
            ctypes.c_void_p,
            ctypes.c_void_p,
            dword,
            ctypes.POINTER(dword),
            dword,
        )
        library.NCryptExportKey.restype = status
        library.NCryptSignHash.argtypes = (
            handle,
            ctypes.c_void_p,
            ctypes.c_void_p,
            dword,
            ctypes.c_void_p,
            dword,
            ctypes.POINTER(dword),
            dword,
        )
        library.NCryptSignHash.restype = status
        library.NCryptVerifySignature.argtypes = (
            handle,
            ctypes.c_void_p,
            ctypes.c_void_p,
            dword,
            ctypes.c_void_p,
            dword,
            dword,
        )
        library.NCryptVerifySignature.restype = status
        library.NCryptDeleteKey.argtypes = (handle, dword)
        library.NCryptDeleteKey.restype = status
        library.NCryptFreeObject.argtypes = (handle,)
        library.NCryptFreeObject.restype = status

        self.library = library
        self.handle_type = handle
        self.dword_type = dword

    @staticmethod
    def code(value: int) -> int:
        return ctypes.c_uint32(value).value

    def require(self, operation: str, value: int) -> None:
        code = self.code(value)
        if code:
            raise SigningAuthorityDenied(
                "%s failed with Windows CNG status 0x%08x" % (operation, code)
            )

    def open_provider(self, provider_name: str):
        handle = self.handle_type()
        self.require(
            "open key storage provider",
            self.library.NCryptOpenStorageProvider(
                ctypes.byref(handle), provider_name, 0
            ),
        )
        return handle

    def free(self, handle) -> None:
        if handle is not None and handle.value:
            self.require("release CNG handle", self.library.NCryptFreeObject(handle))


_API: _Ncrypt | None = None
_API_LOCK = threading.Lock()


def _api() -> _Ncrypt:
    global _API
    with _API_LOCK:
        if _API is None:
            _API = _Ncrypt()
        return _API


def _checked_key_name(value: str) -> str:
    name = str(value)
    if not _KEY_NAME.fullmatch(name):
        raise ValueError("Windows CNG key name is invalid")
    return name


def _resource(provider_id: str, key_name: str, public_digest: str) -> str:
    return "cng://%s/user/%s/sha256/%s" % (
        provider_id,
        quote(key_name, safe="._-"),
        public_digest,
    )


def _parse_resource(resource_version: str) -> tuple[str, str, str]:
    text = str(resource_version)
    prefix = "cng://"
    if not text.startswith(prefix):
        raise SigningAuthorityDenied("Windows CNG resource is invalid")
    parts = text[len(prefix):].split("/")
    if (
        len(parts) != 5
        or parts[1] != "user"
        or parts[3] != "sha256"
        or parts[0] not in _PROVIDERS
        or not _DIGEST.fullmatch(parts[4])
    ):
        raise SigningAuthorityDenied("Windows CNG resource is invalid")
    key_name = _checked_key_name(unquote(parts[2]))
    if quote(key_name, safe="._-") != parts[2]:
        raise SigningAuthorityDenied("Windows CNG resource is non-canonical")
    return parts[0], key_name, parts[4]


class WindowsCngSigningAuthorityProvider:
    """Current-user ECDSA P-256 key held by one admitted Windows KSP."""

    def __init__(
        self,
        *,
        provider_id: str,
        key_name: str,
        create: bool = False,
    ) -> None:
        if provider_id not in _PROVIDERS:
            raise ValueError("Windows CNG provider is not admitted")
        self.provider_id = provider_id
        self.provider_name, self.protection_level = _PROVIDERS[provider_id]
        self.key_name = _checked_key_name(key_name)
        self._lock = threading.RLock()
        self._current_resource = self._ensure_resource(create=create)

    def __reduce_ex__(self, protocol):
        raise TypeError("Windows CNG signing providers cannot be serialized")

    @property
    def current_resource(self) -> str:
        return self._current_resource

    def _open_key(self, provider, key_name: str):
        api = _api()
        key = api.handle_type()
        status = api.library.NCryptOpenKey(
            provider,
            ctypes.byref(key),
            key_name,
            0,
            _NCRYPT_SILENT_FLAG,
        )
        return status, key

    def _create_key(self, provider):
        api = _api()
        key = api.handle_type()
        api.require(
            "create persisted signing key",
            api.library.NCryptCreatePersistedKey(
                provider,
                ctypes.byref(key),
                _ECDSA_P256,
                self.key_name,
                0,
                0,
            ),
        )
        try:
            export_policy = api.dword_type(0)
            api.require(
                "set non-exportable key policy",
                api.library.NCryptSetProperty(
                    key,
                    "Export Policy",
                    ctypes.byref(export_policy),
                    ctypes.sizeof(export_policy),
                    0,
                ),
            )
            api.require(
                "finalize persisted signing key",
                api.library.NCryptFinalizeKey(key, _NCRYPT_SILENT_FLAG),
            )
            return key
        except Exception:
            api.free(key)
            raise

    def _export_public(self, key) -> bytes:
        api = _api()
        size = api.dword_type()
        api.require(
            "size public signing key",
            api.library.NCryptExportKey(
                key,
                api.handle_type(),
                _PUBLIC_BLOB,
                None,
                None,
                0,
                ctypes.byref(size),
                _NCRYPT_SILENT_FLAG,
            ),
        )
        if size.value < 16 or size.value > 4096:
            raise SigningAuthorityDenied("Windows CNG public key size is invalid")
        output = (ctypes.c_ubyte * size.value)()
        api.require(
            "export public signing key",
            api.library.NCryptExportKey(
                key,
                api.handle_type(),
                _PUBLIC_BLOB,
                None,
                output,
                size.value,
                ctypes.byref(size),
                _NCRYPT_SILENT_FLAG,
            ),
        )
        return bytes(output[:size.value])

    def _ensure_resource(self, *, create: bool) -> str:
        api = _api()
        provider = api.open_provider(self.provider_name)
        key = None
        try:
            status, candidate = self._open_key(provider, self.key_name)
            code = api.code(status)
            if code == _NTE_BAD_KEYSET:
                if not create:
                    raise SigningAuthorityDenied(
                        "Windows CNG signing key is unavailable"
                    )
                try:
                    key = self._create_key(provider)
                except SigningAuthorityDenied as exc:
                    if "0x%08x" % _NTE_EXISTS not in str(exc):
                        raise
                    status, key = self._open_key(provider, self.key_name)
                    api.require("open concurrent signing key", status)
            else:
                api.require("open persisted signing key", status)
                key = candidate
            public = self._export_public(key)
            digest = hashlib.sha256(public).hexdigest()
            return _resource(self.provider_id, self.key_name, digest)
        finally:
            if key is not None:
                api.free(key)
            api.free(provider)

    def _open_exact(self, resource_version: str):
        provider_id, key_name, expected_digest = _parse_resource(resource_version)
        if provider_id != self.provider_id or key_name != self.key_name:
            raise SigningAuthorityDenied("Windows CNG resource mismatched")
        api = _api()
        provider = api.open_provider(self.provider_name)
        key = None
        try:
            status, key = self._open_key(provider, key_name)
            api.require("open exact persisted signing key", status)
            public = self._export_public(key)
            actual_digest = hashlib.sha256(public).hexdigest()
            if not hmac.compare_digest(expected_digest, actual_digest):
                raise SigningAuthorityDenied(
                    "Windows CNG public key digest mismatched"
                )
            return provider, key, public
        except Exception:
            if key is not None:
                api.free(key)
            api.free(provider)
            raise

    def describe(self, resource_version: str) -> ProviderKeyMetadata:
        with self._lock:
            provider, key, public = self._open_exact(resource_version)
            try:
                return ProviderKeyMetadata(
                    WINDOWS_CNG_PROVIDER_PROTOCOL,
                    self.provider_id,
                    resource_version,
                    "sign-verify",
                    "ecdsa-p256-sha256-p1363",
                    "message",
                    "sha256",
                    "base64",
                    "cng-eccpublicblob",
                    public,
                    self.protection_level,
                    "none",
                    "active",
                )
            finally:
                api = _api()
                api.free(key)
                api.free(provider)

    @staticmethod
    def _digest_payload(payload: bytes):
        digest = hashlib.sha256(bytes(payload)).digest()
        return (ctypes.c_ubyte * len(digest)).from_buffer_copy(digest)

    def sign(self, request: ProviderSignRequest) -> ProviderSignResponse:
        if (
            request.resource_version != self.current_resource
            or request.signature_algorithm != "ecdsa-p256-sha256-p1363"
            or request.payload_mode != "message"
            or request.digest_algorithm != "sha256"
            or not request.payload
        ):
            raise SigningAuthorityDenied("Windows CNG signing request mismatched")
        with self._lock:
            provider, key, _public = self._open_exact(request.resource_version)
            try:
                api = _api()
                digest = self._digest_payload(request.payload)
                size = api.dword_type()
                api.require(
                    "size Windows CNG signature",
                    api.library.NCryptSignHash(
                        key,
                        None,
                        digest,
                        len(digest),
                        None,
                        0,
                        ctypes.byref(size),
                        _NCRYPT_SILENT_FLAG,
                    ),
                )
                if size.value != 64:
                    raise SigningAuthorityDenied(
                        "Windows CNG ECDSA signature size is invalid"
                    )
                output = (ctypes.c_ubyte * size.value)()
                api.require(
                    "create Windows CNG signature",
                    api.library.NCryptSignHash(
                        key,
                        None,
                        digest,
                        len(digest),
                        output,
                        size.value,
                        ctypes.byref(size),
                        _NCRYPT_SILENT_FLAG,
                    ),
                )
                signature = bytes(output[:size.value])
                integrity = "windows-cng-call-sha256:" + hashlib.sha256(
                    request.request_id.encode("ascii")
                    + request.resource_version.encode("ascii")
                    + signature
                ).hexdigest()
                return ProviderSignResponse(
                    request.request_id,
                    WINDOWS_CNG_PROVIDER_PROTOCOL,
                    self.provider_id,
                    request.resource_version,
                    "ecdsa-p256-sha256-p1363",
                    "base64",
                    self.protection_level,
                    integrity,
                    signature,
                )
            finally:
                api = _api()
                api.free(key)
                api.free(provider)

    def verify(
        self, resource_version: str, payload: bytes, signature: bytes
    ) -> bool:
        if len(signature) != 64 or not payload:
            return False
        with self._lock:
            try:
                provider, key, _public = self._open_exact(resource_version)
            except SigningAuthorityDenied:
                return False
            try:
                api = _api()
                digest = self._digest_payload(payload)
                encoded = (ctypes.c_ubyte * len(signature)).from_buffer_copy(
                    signature
                )
                status = api.library.NCryptVerifySignature(
                    key,
                    None,
                    digest,
                    len(digest),
                    encoded,
                    len(encoded),
                    _NCRYPT_SILENT_FLAG,
                )
                return api.code(status) == 0
            finally:
                api = _api()
                api.free(key)
                api.free(provider)


__all__ = [
    "PLATFORM_PROVIDER_ID",
    "SOFTWARE_PROVIDER_ID",
    "WINDOWS_CNG_PROVIDER_PROTOCOL",
    "WindowsCngSigningAuthorityProvider",
]
