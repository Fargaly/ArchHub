"""Option 1 signing-layer court: the window opens the owner-protected key EXACTLY ONCE
and WITHOUT the silent flag (so Windows shows its protection prompt -- the owner's
consent), and the owner/verify path opens the key not at all (verify_blob only, so no
NTE_SILENT_CONTEXT path is ever taken). Driven through an injected fake _Store that
records every NCryptOpenKey flag; the real key store is never touched.
"""
from nodelang import workspace_roots_catalogue as roots
from nodelang import workspace_roots_signing as signing

_CANNED_BLOB = bytes(72)  # an ECCPUBLICBLOB-sized stub


class _FakeNcrypt:
    def NCryptFreeObject(self, *_args):
        return 0


def _install_fake_store(monkeypatch, opens):
    def init(self):
        self.ncrypt = _FakeNcrypt()
        self.provider = object()

    def open_(self, name, flags=signing.NCRYPT_SILENT_FLAG):
        opens.append((name, flags))
        return object(), 0  # a non-None key handle, rc 0

    monkeypatch.setattr(signing._Store, "__init__", init)
    monkeypatch.setattr(signing._Store, "open", open_)
    monkeypatch.setattr(signing._Store, "close", lambda self: None)
    monkeypatch.setattr(signing._Store, "public_blob",
                        lambda self, key, flags=signing.NCRYPT_SILENT_FLAG: _CANNED_BLOB)


def test_the_window_opens_the_key_once_and_without_the_silent_flag(monkeypatch):
    opens = []
    _install_fake_store(monkeypatch, opens)
    # the protection + window-attach checks are not what this court measures
    monkeypatch.setattr(signing.CngSigner, "_check_existing", lambda self, store, key, flags=0: None)
    monkeypatch.setattr(signing.CngSigner, "_attach_window", lambda self, store, key: None)
    blob = signing.CngSigner(roots.KEY_NAME, protect=True, window_handle=0x1234).public_blob()
    assert blob == _CANNED_BLOB
    assert len(opens) == 1, "the window must open the key exactly once"
    assert opens[0][1] == 0, "the window open must NOT pass the silent flag"
    assert opens[0][1] != signing.NCRYPT_SILENT_FLAG


def test_the_owner_verify_path_opens_the_key_not_at_all(monkeypatch):
    opens = []
    _install_fake_store(monkeypatch, opens)
    verifier = signing.CngVerifier(roots.KEY_NAME)
    # verify_blob checks a signature against a supplied public blob; it must never open
    # the store, so the hidden owner never hits a silent open (NTE_SILENT_CONTEXT).
    ok = verifier.verify_blob(_CANNED_BLOB, roots.KEY_ID, 1, b"payload", "00" * 64)
    assert ok is False          # a stub blob/signature does not verify
    assert opens == [], "the owner verify path must not open the key store at all"
