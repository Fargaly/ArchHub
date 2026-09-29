"""The workspace-roots signing key: application-held, non-exportable, owner-prompted.

Throwaway keys only, each deleted. The protected key is probed silently and must be
refused (NTE_SILENT_CONTEXT); no Windows prompt is ever shown by these courts.
"""
import ctypes
import uuid

from nodelang import workspace_roots_signing as signing


def _delete_key(name):
    store = signing._Store()
    try:
        key, _rc = store.open(name, flags=0)
        if key is not None:
            store.ncrypt.NCryptDeleteKey.restype = ctypes.c_long
            store.ncrypt.NCryptDeleteKey.argtypes = (signing._HANDLE, ctypes.c_ulong)
            store.ncrypt.NCryptDeleteKey(key, 0)
    finally:
        store.close()


def test_the_key_signs_and_only_its_public_half_verifies():
    name = "ArchHub-court-" + uuid.uuid4().hex
    try:
        signature = signing.CngSigner(name, protect=False).sign(b'{"roots":[]}')
        verifier = signing.CngVerifier(name)
        assert verifier.verify("cng:" + name, 1, b'{"roots":[]}', signature)
        assert not verifier.verify("cng:" + name, 1, b'{"roots":[]} ', signature)
        assert not verifier.verify("cng:other", 1, b'{"roots":[]}', signature)
        assert len(verifier.public_blob()) == 72
    finally:
        _delete_key(name)


def test_the_private_key_is_never_exportable():
    name = "ArchHub-court-" + uuid.uuid4().hex
    try:
        signing.CngSigner(name, protect=False).sign(b"x")
        store = signing._Store()
        try:
            key, _rc = store.open(name)
            size = ctypes.c_ulong()
            refused = store.ncrypt.NCryptExportKey(key, 0, "ECCPRIVATEBLOB", None, None, 0, ctypes.byref(size),
                                                   signing.NCRYPT_SILENT_FLAG) & 0xFFFFFFFF
            store.ncrypt.NCryptFreeObject(key)
        finally:
            store.close()
        assert refused != 0, "the private key was exportable"
    finally:
        _delete_key(name)


def test_the_protected_key_cannot_be_created_or_used_silently():
    name = "ArchHub-court-" + uuid.uuid4().hex
    store = signing._Store()
    key = signing._HANDLE()
    store.ncrypt.NCryptDeleteKey.restype = ctypes.c_long
    store.ncrypt.NCryptDeleteKey.argtypes = (signing._HANDLE, ctypes.c_ulong)
    try:
        assert store.ncrypt.NCryptCreatePersistedKey(store.provider, ctypes.byref(key), signing.ALGORITHM,
                                                      name, 0, 0) == 0
        ui = signing._UiPolicy(1, signing.FORCE_HIGH_PROTECTION, None, "court", "court")
        assert store.ncrypt.NCryptSetProperty(key, "UI Policy", ctypes.byref(ui), ctypes.sizeof(ui), 0) == 0
        refused = store.ncrypt.NCryptFinalizeKey(key, signing.NCRYPT_SILENT_FLAG) & 0xFFFFFFFF
        assert refused == 0x80090022, hex(refused)
    finally:
        store.ncrypt.NCryptDeleteKey(key, 0)
        store.close()
        _delete_key(name)


def test_an_absent_key_has_no_public_half():
    assert signing.CngVerifier("ArchHub-court-absent-" + uuid.uuid4().hex).public_blob() is None


def _create_raw(name, *, export_flags=0):
    store = signing._Store()
    key = signing._HANDLE()
    try:
        assert store.ncrypt.NCryptCreatePersistedKey(store.provider, ctypes.byref(key), signing.ALGORITHM,
                                                      name, 0, 0) == 0
        policy = ctypes.c_ulong(export_flags)
        assert store.ncrypt.NCryptSetProperty(key, "Export Policy", ctypes.byref(policy), 4, 0) == 0
        assert store.ncrypt.NCryptFinalizeKey(key, signing.NCRYPT_SILENT_FLAG) == 0
    finally:
        store.ncrypt.NCryptFreeObject(key)
        store.close()


def test_an_existing_unprotected_same_name_key_is_refused_not_adopted():
    name = "ArchHub-court-" + uuid.uuid4().hex
    try:
        signing.CngSigner(name, protect=False).sign(b"x")  # an unprompted key already under the name
        try:
            signing.CngSigner(name, protect=True).sign(b"x")
        except signing.SigningUnavailable as exc:
            assert "not owner-protected" in str(exc)
        else:
            raise AssertionError("an unprotected key was adopted")
    finally:
        _delete_key(name)


def test_an_existing_exportable_key_is_refused():
    name = "ArchHub-court-" + uuid.uuid4().hex
    try:
        _create_raw(name, export_flags=0x1)  # NCRYPT_ALLOW_EXPORT_FLAG
        try:
            signing.CngSigner(name, protect=False).sign(b"x")
        except signing.SigningUnavailable as exc:
            assert "exportable" in str(exc)
        else:
            raise AssertionError("an exportable key was adopted")
    finally:
        _delete_key(name)


def test_a_substitute_key_under_the_pinned_name_is_refused():
    name = "ArchHub-court-" + uuid.uuid4().hex
    try:
        signing.CngSigner(name, protect=False).sign(b"x")
        pinned = signing.CngVerifier(name).public_fingerprint()
        assert signing.CngSigner(name, protect=False, pinned_fingerprint=pinned).sign(b"x")
        _delete_key(name)
        signing.CngSigner(name, protect=False).sign(b"x")  # same name, a different key
        try:
            signing.CngSigner(name, protect=False, pinned_fingerprint=pinned).sign(b"x")
        except signing.SigningUnavailable as exc:
            assert "not the pinned key" in str(exc)
        else:
            raise AssertionError("a substitute key was adopted")
    finally:
        _delete_key(name)


def test_a_missing_pinned_key_is_never_silently_recreated():
    name = "ArchHub-court-" + uuid.uuid4().hex
    try:
        signing.CngSigner(name, protect=False, pinned_fingerprint="00" * 32).sign(b"x")
    except signing.SigningUnavailable as exc:
        assert "missing" in str(exc)
    else:
        raise AssertionError("a missing pinned key was recreated")
    finally:
        _delete_key(name)
