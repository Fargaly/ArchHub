"""Signing for the workspace-roots snapshot with an app-held, non-exportable key.

The key is ECDSA P-256 in the current user's Windows key store (Microsoft Software Key
Storage Provider), created with export forbidden and NCRYPT_UI_FORCE_HIGH_PROTECTION,
so Windows itself asks the owner before it is created and before every signature: no
process, not even a shell running as the same user, can sign silently (a silent
attempt fails with NTE_SILENT_CONTEXT). Such a key cannot be OPENED silently either
(NCryptOpenKey with NCRYPT_SILENT_FLAG answers NTE_SILENT_CONTEXT, 0x80090022): only
the visible desktop window opens it (CngSigner.public_blob), checks its protection
and hands its public half on. The graph's owner and the governance hooks never open
the key: they verify with the public blob carried in the pin (verify_blob, BCrypt only).

An existing key under the name is adopted only when it is non-exportable, carries the
owner-prompt protection (when protect=True) and, once the graph pins its public-key
fingerprint, has exactly that public half; anything else is refused, never adopted.

Named limits: the courts prove that creating a protected key silently is refused; they do
not (and cannot, without showing a prompt) prove that each signature of an EXISTING key
prompts; that rests on the checked UI-policy property. A same-user process can delete the
key and create its own under the same name; with the fingerprint pinned, the signer
refuses it and the application reports the mismatch.
"""
from __future__ import annotations

import ctypes
import hashlib
from ctypes import wintypes

PROVIDER_NAME = "Microsoft Software Key Storage Provider"
ALGORITHM = "ECDSA_P256"
NCRYPT_SILENT_FLAG = 0x40
FORCE_HIGH_PROTECTION = 0x2
NTE_BAD_KEYSET = 0x80090016
NTE_NOT_FOUND = 0x80090011
# NCRYPT_WINDOW_HANDLE_PROPERTY: the window the owner prompt belongs to. Without it a
# prompt raised by a process with no visible window never reaches the owner.
WINDOW_HANDLE_PROPERTY = "HWND Handle"
_HANDLE = ctypes.c_size_t


class _UiPolicy(ctypes.Structure):
    _fields_ = [("dwVersion", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("pszCreationTitle", wintypes.LPCWSTR), ("pszFriendlyName", wintypes.LPCWSTR),
                ("pszDescription", wintypes.LPCWSTR)]


class SigningUnavailable(RuntimeError):
    """The key store refused, or the owner declined the Windows prompt."""


def _libraries():
    ncrypt, bcrypt = ctypes.WinDLL("ncrypt"), ctypes.WinDLL("bcrypt")
    for name in ("NCryptOpenStorageProvider", "NCryptOpenKey", "NCryptCreatePersistedKey", "NCryptSetProperty",
                 "NCryptGetProperty", "NCryptFinalizeKey", "NCryptExportKey", "NCryptSignHash", "NCryptFreeObject"):
        getattr(ncrypt, name).restype = ctypes.c_long
    ncrypt.NCryptOpenStorageProvider.argtypes = (ctypes.POINTER(_HANDLE), wintypes.LPCWSTR, wintypes.DWORD)
    ncrypt.NCryptOpenKey.argtypes = (_HANDLE, ctypes.POINTER(_HANDLE), wintypes.LPCWSTR, wintypes.DWORD,
                                     wintypes.DWORD)
    ncrypt.NCryptCreatePersistedKey.argtypes = (_HANDLE, ctypes.POINTER(_HANDLE), wintypes.LPCWSTR,
                                                wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD)
    ncrypt.NCryptSetProperty.argtypes = (_HANDLE, wintypes.LPCWSTR, ctypes.c_void_p, wintypes.DWORD,
                                         wintypes.DWORD)
    ncrypt.NCryptGetProperty.argtypes = (_HANDLE, wintypes.LPCWSTR, ctypes.c_void_p, wintypes.DWORD,
                                         ctypes.POINTER(wintypes.DWORD), wintypes.DWORD)
    ncrypt.NCryptFinalizeKey.argtypes = (_HANDLE, wintypes.DWORD)
    ncrypt.NCryptExportKey.argtypes = (_HANDLE, _HANDLE, wintypes.LPCWSTR, ctypes.c_void_p, ctypes.c_void_p,
                                       wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.DWORD)
    ncrypt.NCryptSignHash.argtypes = (_HANDLE, ctypes.c_void_p, ctypes.c_char_p, wintypes.DWORD,
                                      ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
                                      wintypes.DWORD)
    ncrypt.NCryptFreeObject.argtypes = (_HANDLE,)
    for name in ("BCryptOpenAlgorithmProvider", "BCryptImportKeyPair", "BCryptVerifySignature",
                 "BCryptDestroyKey", "BCryptCloseAlgorithmProvider"):
        getattr(bcrypt, name).restype = ctypes.c_long
    bcrypt.BCryptOpenAlgorithmProvider.argtypes = (ctypes.POINTER(_HANDLE), wintypes.LPCWSTR,
                                                   wintypes.LPCWSTR, wintypes.ULONG)
    bcrypt.BCryptImportKeyPair.argtypes = (_HANDLE, _HANDLE, wintypes.LPCWSTR, ctypes.POINTER(_HANDLE),
                                           ctypes.c_char_p, wintypes.ULONG, wintypes.ULONG)
    bcrypt.BCryptVerifySignature.argtypes = (_HANDLE, ctypes.c_void_p, ctypes.c_char_p, wintypes.ULONG,
                                             ctypes.c_char_p, wintypes.ULONG, wintypes.ULONG)
    bcrypt.BCryptDestroyKey.argtypes = (_HANDLE,)
    bcrypt.BCryptCloseAlgorithmProvider.argtypes = (_HANDLE, wintypes.ULONG)
    return ncrypt, bcrypt


def _status(value):
    return value & 0xFFFFFFFF


class _Store:
    def __init__(self):
        self.ncrypt, self.bcrypt = _libraries()
        self.provider = _HANDLE()
        rc = self.ncrypt.NCryptOpenStorageProvider(ctypes.byref(self.provider), PROVIDER_NAME, 0)
        if rc:
            raise SigningUnavailable("key store unavailable: %#x" % _status(rc))

    def close(self):
        self.ncrypt.NCryptFreeObject(self.provider)

    def open(self, name, flags=NCRYPT_SILENT_FLAG):
        key = _HANDLE()
        rc = self.ncrypt.NCryptOpenKey(self.provider, ctypes.byref(key), name, 0, flags)
        return (key if rc == 0 else None), _status(rc)

    def public_blob(self, key, flags=NCRYPT_SILENT_FLAG):
        size = wintypes.DWORD()
        rc = self.ncrypt.NCryptExportKey(key, 0, "ECCPUBLICBLOB", None, None, 0, ctypes.byref(size),
                                         flags)
        if rc:
            raise SigningUnavailable("public key unavailable: %#x" % _status(rc))
        buffer = (ctypes.c_ubyte * size.value)()
        rc = self.ncrypt.NCryptExportKey(key, 0, "ECCPUBLICBLOB", None, buffer, size, ctypes.byref(size),
                                         flags)
        if rc:
            raise SigningUnavailable("public key unavailable: %#x" % _status(rc))
        return bytes(buffer[:size.value])


class CngSigner:
    """Signs with the owner's protected key, creating it on first use (Windows prompts)."""

    def __init__(self, key_name: str, *, description: str = "ArchHub workspace registrations",
                 protect: bool = True, pinned_fingerprint: str | None = None,
                 window_handle: int | None = None):
        self.key_name = key_name
        self.description = description
        self.protect = protect  # courts only: False creates an unprompted key they delete
        # The public-key fingerprint the graph pinned at the first registration; a key
        # under the same name with any other public half is a substitute and refused.
        self.pinned_fingerprint = pinned_fingerprint
        # The visible window the owner prompt is shown in front of (the desktop's).
        self.window_handle = window_handle

    def _attach_window(self, store, handle):
        """Bind the owner prompt to the window; a prompt that cannot be shown is refused."""
        if not self.window_handle:
            return
        hwnd = ctypes.c_void_p(int(self.window_handle))
        rc = store.ncrypt.NCryptSetProperty(handle, WINDOW_HANDLE_PROPERTY, ctypes.byref(hwnd),
                                            ctypes.sizeof(hwnd), 0)
        if rc:
            raise SigningUnavailable("the owner prompt cannot be attached to the ArchHub window: %#x"
                                     % _status(rc))

    def _dword_property(self, store, key, name, flags=NCRYPT_SILENT_FLAG):
        value, size = wintypes.DWORD(), wintypes.DWORD()
        rc = store.ncrypt.NCryptGetProperty(key, name, ctypes.byref(value), 4, ctypes.byref(size),
                                            flags)
        if rc:
            raise SigningUnavailable("signing key %s unreadable: %#x" % (name, _status(rc)))
        return value.value

    def _ui_flags(self, store, key, flags=NCRYPT_SILENT_FLAG):
        buffer, size = (ctypes.c_ubyte * 1024)(), wintypes.DWORD()
        rc = store.ncrypt.NCryptGetProperty(key, "UI Policy", buffer, 1024, ctypes.byref(size), flags)
        if _status(rc) == NTE_NOT_FOUND:
            return 0
        if rc or size.value < 8:
            raise SigningUnavailable("signing key UI policy unreadable: %#x" % _status(rc))
        return ctypes.cast(buffer, ctypes.POINTER(_UiPolicy)).contents.dwFlags

    def _check_existing(self, store, key, flags=NCRYPT_SILENT_FLAG):
        """An existing key is adopted only when its protection and identity are exactly ours."""
        if self._dword_property(store, key, "Export Policy", flags) != 0:
            raise SigningUnavailable("the existing signing key is exportable; refused")
        if self.protect and not self._ui_flags(store, key, flags) & FORCE_HIGH_PROTECTION:
            raise SigningUnavailable("the existing signing key is not owner-protected; refused")
        if self.pinned_fingerprint is not None:
            if hashlib.sha256(store.public_blob(key, flags)).hexdigest() != self.pinned_fingerprint:
                raise SigningUnavailable("the existing signing key is not the pinned key; refused")

    def _key(self, store):
        key, rc = store.open(self.key_name, flags=0)
        if key is not None:
            try:
                # This is the window's process: no read here is silent (a protected
                # key refuses silent reads), and any prompt belongs to the window.
                self._attach_window(store, key)
                self._check_existing(store, key, 0)
            except BaseException:
                store.ncrypt.NCryptFreeObject(key)
                raise
            return key
        if rc != NTE_BAD_KEYSET:
            raise SigningUnavailable("signing key unavailable: %#x" % rc)
        if self.pinned_fingerprint is not None:
            raise SigningUnavailable("the pinned signing key is missing; refusing to create a new one")
        key = _HANDLE()
        rc = store.ncrypt.NCryptCreatePersistedKey(store.provider, ctypes.byref(key), ALGORITHM,
                                                   self.key_name, 0, 0)
        if rc:
            raise SigningUnavailable("signing key not created: %#x" % _status(rc))
        try:
            # The creation prompt (shown at finalize) belongs to the window too; the
            # key store refuses the property on its provider handle (NTE_NOT_SUPPORTED).
            self._attach_window(store, key)
            export = wintypes.DWORD(0)
            ui = _UiPolicy(1, FORCE_HIGH_PROTECTION, None, "ArchHub workspaces", self.description)
            policies = [("Export Policy", ctypes.byref(export), 4)]
            if self.protect:
                policies.append(("UI Policy", ctypes.byref(ui), ctypes.sizeof(ui)))
            for name, value, size in policies:
                rc = store.ncrypt.NCryptSetProperty(key, name, value, size, 0)
                if rc:
                    raise SigningUnavailable("signing key policy refused: %#x" % _status(rc))
            rc = store.ncrypt.NCryptFinalizeKey(key, 0)  # Windows asks the owner here
            if rc:
                raise SigningUnavailable("signing key not confirmed by the owner: %#x" % _status(rc))
        except BaseException:
            store.ncrypt.NCryptFreeObject(key)
            raise
        return key

    def sign(self, payload: bytes) -> str:
        store = _Store()
        try:
            key = self._key(store)
            try:
                self._attach_window(store, key)  # the per-signature prompt
                digest = hashlib.sha256(payload).digest()
                size = wintypes.DWORD()
                rc = store.ncrypt.NCryptSignHash(key, None, digest, len(digest), None, 0, ctypes.byref(size), 0)
                if rc:
                    raise SigningUnavailable("signature refused: %#x" % _status(rc))
                buffer = (ctypes.c_ubyte * size.value)()
                rc = store.ncrypt.NCryptSignHash(key, None, digest, len(digest), buffer, size,
                                                 ctypes.byref(size), 0)
                if rc:
                    raise SigningUnavailable("signature refused: %#x" % _status(rc))
                return bytes(buffer[:size.value]).hex()
            finally:
                store.ncrypt.NCryptFreeObject(key)
        finally:
            store.close()

    def public_blob(self) -> bytes | None:
        """The key's public half, read in the visible window process (never silently:
        a protected key refuses a silent open), and only of a key whose protection and
        identity are exactly ours; None when no key exists yet. This blob is what the
        graph's owner pins and verifies with; the owner itself never opens the key."""
        store = _Store()
        try:
            key, rc = store.open(self.key_name, flags=0)
            if key is None:
                if rc == NTE_BAD_KEYSET:
                    return None
                raise SigningUnavailable("signing key unavailable: %#x" % rc)
            try:
                self._attach_window(store, key)
                self._check_existing(store, key, 0)
                return store.public_blob(key, 0)
            finally:
                store.ncrypt.NCryptFreeObject(key)
        finally:
            store.close()


class CngVerifier:
    """Verifies with the public key the store exports silently; holds no secret."""

    def __init__(self, key_name: str):
        self.key_name = key_name

    def public_blob(self) -> bytes | None:
        store = _Store()
        try:
            key, rc = store.open(self.key_name)
            if key is None:
                if rc == NTE_BAD_KEYSET:
                    return None  # positively absent
                raise SigningUnavailable("signing key unavailable: %#x" % rc)
            try:
                return store.public_blob(key)
            finally:
                store.ncrypt.NCryptFreeObject(key)
        finally:
            store.close()

    def public_fingerprint(self) -> str | None:
        blob = self.public_blob()
        return hashlib.sha256(blob).hexdigest() if blob else None

    def verify(self, key_id: str, version: int, payload: bytes, signature: str) -> bool:
        """Verify with the key the store holds now. A caller that checked a pin uses
        verify_blob with the exact blob it checked instead."""
        try:
            blob = self.public_blob()
        except Exception:  # noqa: BLE001 - any doubt is a refused signature
            return False
        return self.verify_blob(blob, key_id, version, payload, signature)

    def verify_blob(self, blob, key_id: str, version: int, payload: bytes,
                    signature: str) -> bool:
        """Verify with exactly `blob` (an ECCPUBLICBLOB); the key store is not opened."""
        try:
            if key_id != "cng:" + self.key_name or version != 1:
                return False
            blob = bytes(blob) if blob else None
            raw = bytes.fromhex(signature)
            if not blob or len(raw) != 64:
                return False
            _ncrypt, bcrypt = _libraries()
            algorithm, key = _HANDLE(), _HANDLE()
            if bcrypt.BCryptOpenAlgorithmProvider(ctypes.byref(algorithm), ALGORITHM, None, 0):
                return False
            try:
                if bcrypt.BCryptImportKeyPair(algorithm, 0, "ECCPUBLICBLOB", ctypes.byref(key), blob, len(blob), 0):
                    return False
                digest = hashlib.sha256(payload).digest()
                return bcrypt.BCryptVerifySignature(key, None, digest, len(digest), raw, len(raw), 0) == 0
            finally:
                if key.value:
                    bcrypt.BCryptDestroyKey(key)
                bcrypt.BCryptCloseAlgorithmProvider(algorithm, 0)
        except Exception:  # noqa: BLE001 - any doubt is a refused signature
            return False
