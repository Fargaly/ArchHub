"""Settings -> Workspaces Add: the owner approves in the window he is looking at.

The graph's owner runs as a hidden scheduled task, so a key prompt it raised was
never seen and Add could not complete. Now the desktop process (visible window)
signs with the window handle set on the key store and key, and the owner only
verifies: the protected, pinned key's signature over exactly the snapshot it
derives from the graph now, or nothing commits.

Founder 2026-10-01 (Add failed live): a protected key cannot be opened silently
(NCryptOpenKey + NCRYPT_SILENT_FLAG answers NTE_SILENT_CONTEXT, 0x80090022), so the
owner, which read the key's public half itself, could never approve. Now the
WINDOW opens the key, checks its protection and offers the public half; the owner
pins it on the first registration only with a KEY_CHECK signature under it, and
afterwards accepts only the pinned blob. The owner never opens the key: every
court here fails if it does.

No court touches the owner's real key or shows a prompt: CNG courts use
throwaway protect=False keys (deleted); graph courts use an in-memory P-256 key.
"""
from __future__ import annotations

import ctypes
import hashlib
import threading
import uuid

import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.utils import (
    decode_dss_signature,
    encode_dss_signature,
)

from nodelang import workspace_roots_catalogue as roots
from nodelang import workspace_roots_signing as signing
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.unified_authority import create_unified_authority
from nodelang.universal_cell import CellStore

FOUNDER_PRIVATE = Ed25519PrivateKey.from_private_bytes(bytes(range(11, 43)))
FOUNDER_PUBLIC = FOUNDER_PRIVATE.public_key().public_bytes(
    serialization.Encoding.Raw, serialization.PublicFormat.Raw)


# --- the signing call carries the window (real CNG, throwaway key, no prompt) ---

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


class _Recording:
    """The real ncrypt, with every property set and signature recorded in order."""

    def __init__(self, ncrypt, calls):
        self._ncrypt, self._calls = ncrypt, calls

    def __getattr__(self, name):
        real = getattr(self._ncrypt, name)
        if name == "NCryptSetProperty":
            def set_property(handle, prop, value, size, flags):
                shown = getattr(getattr(value, "_obj", None), "value", None)
                self._calls.append(("set", prop, shown))
                return real(handle, prop, value, size, flags)
            return set_property
        if name == "NCryptSignHash":
            def sign_hash(*args):
                self._calls.append(("sign",))
                return real(*args)
            return sign_hash
        return real


def test_the_owner_signature_is_made_with_the_window_handle_set(monkeypatch):
    hwnd = ctypes.windll.user32.GetDesktopWindow()
    assert hwnd
    name = "ArchHub-court-" + uuid.uuid4().hex
    calls = []
    real = signing._libraries
    monkeypatch.setattr(signing, "_libraries",
                        lambda: (lambda n, b: (_Recording(n, calls), b))(*real()))
    try:
        signature = signing.CngSigner(name, protect=False, window_handle=hwnd).sign(b"snapshot")
        windows = [i for i, call in enumerate(calls)
                   if call[:2] == ("set", signing.WINDOW_HANDLE_PROPERTY)]
        signs = [i for i, call in enumerate(calls) if call == ("sign",)]
        # On the store (the creation prompt) and on the key (the signature prompt),
        # always before the key signs.
        assert len(windows) >= 2 and signs and max(windows) < min(signs), calls
        assert all(calls[i][2] == hwnd for i in windows)
        monkeypatch.setattr(signing, "_libraries", real)
        assert signing.CngVerifier(name).verify("cng:" + name, 1, b"snapshot", signature)
    finally:
        monkeypatch.setattr(signing, "_libraries", real)
        _delete_key(name)


def test_without_a_window_the_signer_sets_no_window_property(monkeypatch):
    name = "ArchHub-court-" + uuid.uuid4().hex
    calls = []
    real = signing._libraries
    monkeypatch.setattr(signing, "_libraries",
                        lambda: (lambda n, b: (_Recording(n, calls), b))(*real()))
    try:
        signing.CngSigner(name, protect=False).sign(b"x")
        assert not [c for c in calls if c[:2] == ("set", signing.WINDOW_HANDLE_PROPERTY)]
    finally:
        monkeypatch.setattr(signing, "_libraries", real)
        _delete_key(name)


def test_the_window_offers_only_a_protected_key():
    """Window side (real CNG, unprotected throwaway key, no prompt): the public half is
    offered only of a non-exportable, owner-protected key."""
    name = "ArchHub-court-" + uuid.uuid4().hex
    try:
        signing.CngSigner(name, protect=False).sign(b"x")  # non-exportable, NOT owner-protected
        with pytest.raises(signing.SigningUnavailable, match="not owner-protected"):
            signing.CngSigner(name, protect=True).public_blob()
        blob = signing.CngSigner(name, protect=False).public_blob()
        assert blob == signing.CngVerifier(name).public_blob() and len(blob) == 72
    finally:
        _delete_key(name)
    assert signing.CngSigner(name, protect=True).public_blob() is None


def test_the_window_never_offers_an_exportable_key():
    name = "ArchHub-court-" + uuid.uuid4().hex
    store = signing._Store()
    try:
        key = signing._HANDLE()
        assert store.ncrypt.NCryptCreatePersistedKey(store.provider, ctypes.byref(key),
                                                     signing.ALGORITHM, name, 0, 0) == 0
        export = ctypes.c_ulong(0x1 | 0x2)  # NCRYPT_ALLOW_EXPORT | NCRYPT_ALLOW_PLAINTEXT_EXPORT
        assert store.ncrypt.NCryptSetProperty(key, "Export Policy", ctypes.byref(export), 4, 0) == 0
        assert store.ncrypt.NCryptFinalizeKey(key, 0) == 0
        store.ncrypt.NCryptFreeObject(key)
        with pytest.raises(signing.SigningUnavailable, match="exportable"):
            signing.CngSigner(name, protect=False).public_blob()
    finally:
        store.close()
        _delete_key(name)


# --- the owner verifies; the desktop window signs (throwaway graph) ---

class _Caller:
    def __init__(self, authority):
        self.actor_root = authority.manifest.principal_root
        self.session_root = authority.manifest.bootstrap_session_root
        self.public_key = FOUNDER_PUBLIC

    def sign(self, payload: bytes) -> bytes:
        return FOUNDER_PRIVATE.sign(payload)


class _Key:
    """An ECDSA P-256 key with the CNG wire format; stands in for the store's key."""

    def __init__(self, protected=True):
        self._private = ec.generate_private_key(ec.SECP256R1())
        self.protected, self.exists = protected, True

    def public_blob(self) -> bytes:
        numbers = self._private.public_key().public_numbers()
        return (b"ECS1" + (32).to_bytes(4, "little")
                + numbers.x.to_bytes(32, "big") + numbers.y.to_bytes(32, "big"))

    def fingerprint(self) -> str:
        return hashlib.sha256(self.public_blob()).hexdigest()

    def window_blob(self):
        """What the window's CngSigner.public_blob answers for this key."""
        if not self.exists:
            return None
        if not self.protected:
            raise signing.SigningUnavailable("the existing signing key is not owner-protected; refused")
        return self.public_blob()

    def protected_public_blob(self, *_args, **_kwargs):
        raise AssertionError("the graph's owner opened the key")

    def sign(self, payload: bytes) -> str:
        r, s = decode_dss_signature(self._private.sign(payload, ec.ECDSA(hashes.SHA256())))
        return (r.to_bytes(32, "big") + s.to_bytes(32, "big")).hex()

    def verify_blob(self, blob, key_id, version, payload, signature) -> bool:
        if blob != self.public_blob() or key_id != roots.KEY_ID or version != 1:
            return False
        try:
            raw = bytes.fromhex(signature)
            self._private.public_key().verify(
                encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")),
                payload, ec.ECDSA(hashes.SHA256()))
            return True
        except (InvalidSignature, ValueError):
            return False

    def verify(self, key_id, version, payload, signature) -> bool:
        return self.verify_blob(self.public_blob(), key_id, version, payload, signature)


def _never(*_args):
    raise AssertionError("the graph's owner must not sign: it has no window")


class _OwnerOpenedTheKey(AssertionError):
    pass


@pytest.fixture(autouse=True)
def _the_key_store_is_never_opened_by_a_graph_court(monkeypatch, request):
    """Zero NCrypt opens: the graph courts below never reach the key store at all
    (the window is a court signer, the owner verifies with blobs)."""
    if not ({"world", "old_schema_world"} & set(request.fixturenames)):
        return

    def refuse(*_args, **_kwargs):
        raise _OwnerOpenedTheKey("the key store was opened")
    monkeypatch.setattr(signing, "_Store", refuse)
    monkeypatch.setattr(signing.CngVerifier, "public_blob", refuse)


def _make_world(tmp_path, *, old_schema=False):
    authority = create_unified_authority(
        CellStore(tmp_path / "roots.sqlite3"), MemorySigningKeyProvider("roots-court", b"w" * 32),
        key_id="roots-court", application_label="ArchHub", principal_label="Founder",
        bootstrap_session_label="Window approval court", bootstrap_session_public_key=FOUNDER_PUBLIC,
        composition_labels=("Governance", "Projects"))
    caller = _Caller(authority)
    if old_schema:
        # A GENUINE pre-attestation graph: the key definition published before the
        # enrollment record existed declares only key_id + fingerprint. _publish is
        # idempotent on the name, so the install below retains THIS definition and
        # never adds the new fields -- exactly the founder's live graph.
        roots._publish(
            authority, roots.KEY_DEFINITION,
            {"key_id": roots.KEY_ID, "fingerprint": ""},
            parameters={"key_id": {"type": "text"}, "fingerprint": {"type": "text"}},
            rules={}, panels=["Key", "History"],
            operation_id=str(uuid.uuid4()), label="key", caller=caller)
    catalogue = roots.install_workspace_root_catalogue(
        authority, operation_id=str(uuid.uuid4()), caller=caller)
    key = _Key()
    key.exists = False  # created by the desktop window's first approval
    files = {"snapshot_path": tmp_path / "home" / "workspace-roots.json",
             "pin_path": tmp_path / "home" / "workspace-roots.pin"}
    lock = threading.RLock()

    settings_principal = "archhub/workspace-roots-settings"
    _no_admission = object()

    def owner(body, *, verifier=None, admission=_no_admission):
        """The hidden graph owner: answers the forwarded request, never signs. The
        verified SETTINGS admission is threaded by the authenticated transport; here
        it is simulated (owner_direct simulates a direct call that bypassed it)."""
        if admission is _no_admission:
            admission = {"principal": settings_principal}
        body = dict(body)
        operation = body.pop("command_id", None) or str(uuid.uuid4())
        return roots.owner_change(authority, catalogue, body, caller=caller, operation_id=operation,
                                  lock=lock, signer_factory=_never, fingerprint_of=_never,
                                  verifier=verifier or key, admission=admission, **files)

    def owner_direct(body, *, verifier=None):
        """A direct-to-owner call that skipped the authenticated window admission."""
        return owner(body, verifier=verifier, admission=None)

    class Window:
        """The desktop's key prompt: counts approvals; signs with the store key."""

        def __init__(self, approve=True):
            self.approve, self.asked = approve, []

        def factory(self, pinned):
            window = self

            class Signer:
                def public_blob(self):
                    return key.window_blob()

                def sign(self, payload):
                    window.asked.append((pinned, payload))
                    if not window.approve:
                        raise signing.SigningUnavailable("signature refused: 0x800704c7")
                    if payload == roots.KEY_CHECK:
                        key.exists = True
                    assert pinned is None or pinned == key.fingerprint()
                    return key.sign(payload)
            return Signer()

    tmp = tmp_path
    return {"authority": authority, "catalogue": catalogue, "caller": caller, "key": key,
            "owner": owner, "owner_direct": owner_direct, "settings_principal": settings_principal,
            "Window": Window, "files": files, "tmp": tmp}


@pytest.fixture()
def world(tmp_path):
    return _make_world(tmp_path)


@pytest.fixture()
def old_schema_world(tmp_path):
    """A graph whose key definition predates the enrollment attestation."""
    return _make_world(tmp_path, old_schema=True)


def _register(world, name, *, window=None, forward=None, handle=0x1234):
    folder = world["tmp"] / name
    folder.mkdir(exist_ok=True)
    window = window or world["Window"]()
    return roots.approve_in_this_window(
        {"action": "register", "id": name, "path": str(folder), "privacy": "private",
         "profile": "client", "writers": ["claude"], "command_id": str(uuid.uuid4())},
        window_handle=handle, forward=forward or world["owner"], signer_factory=window.factory)


def _active(world):
    _rev, current, pin = roots.read_state(world["authority"], world["catalogue"], caller=world["caller"])
    return sorted(r["root_id"] for r in current if r.get("state") == "registered"), pin


def test_add_is_approved_in_the_window_and_the_owner_commits_it(world):
    window = world["Window"]()
    view = _register(world, "alpha", window=window)
    assert [r["root_id"] for r in view["roots"] if r["state"] == "registered"] == ["alpha"]
    assert view["projection"] == "match"
    # First registration: the window created the key (its prompt), then approved the snapshot.
    assert window.asked[0] == (None, roots.KEY_CHECK)
    assert window.asked[1][0] == world["key"].fingerprint()
    assert _active(world) == (["alpha"], world["key"].fingerprint())
    second = world["Window"]()
    _register(world, "beta", window=second)
    assert [pinned for pinned, _ in second.asked] == [world["key"].fingerprint()]  # no key check again
    assert _active(world)[0] == ["alpha", "beta"]


def test_no_window_means_no_signature_and_nothing_changes(world):
    asked = []
    with pytest.raises(roots.WorkspaceRootRefused, match="Open the ArchHub window to approve"):
        roots.approve_in_this_window({"action": "register", "id": "x", "path": "C:\\x"},
                                     window_handle=None, forward=lambda b: asked.append(b))
    assert asked == []
    # Reading needs no approval and passes straight to the owner.
    assert roots.approve_in_this_window({"action": "list"}, window_handle=None,
                                        forward=lambda b: {"seen": b}) == {"seen": {"action": "list"}}


def test_a_declined_prompt_changes_nothing(world):
    _register(world, "alpha")
    with pytest.raises(roots.WorkspaceRootRefused, match="the owner did not approve"):
        _register(world, "beta", window=world["Window"](approve=False))
    assert _active(world)[0] == ["alpha"]


def _offer(key, *, check=False):
    offer = {"public_blob": key.public_blob().hex()}
    if check:
        offer["key_check"] = key.sign(roots.KEY_CHECK)
    return offer


def _change(world, name):
    folder = world["tmp"] / name
    folder.mkdir(exist_ok=True)
    return {"action": "register", "id": name, "path": str(folder), "privacy": "private",
            "profile": "client", "writers": ["claude"]}


def test_the_owner_rejects_a_wrong_signature(world):
    _register(world, "alpha")
    change = _change(world, "beta")
    for forged in ("00" * 64, world["key"].sign(b"some other snapshot")):
        with pytest.raises(roots.WorkspaceRootRefused, match="approval does not match"):
            world["owner"]({**change, "signature": forged, **_offer(world["key"])})
    assert _active(world)[0] == ["alpha"]


def test_the_owner_rejects_a_key_that_is_not_the_pinned_one(world):
    _register(world, "alpha")
    pin = world["key"].fingerprint()
    substitute = _Key()  # same name in the store, another public half
    change = _change(world, "beta")
    body = roots.snapshot_body((), substitute.fingerprint())  # refused before any verify
    with pytest.raises(roots.WorkspaceRootRefused, match="not the pinned key"):
        world["owner"]({**change, "signature": substitute.sign(roots.canonical(body)),
                        **_offer(substitute, check=True)}, verifier=substitute)
    with pytest.raises(roots.WorkspaceRootRefused, match="not the pinned key"):
        world["owner"]({"action": "prepare", "change": change, **_offer(substitute, check=True)},
                       verifier=substitute)
    assert _active(world) == (["alpha"], pin)


def test_an_unprotected_key_is_refused_in_the_window_before_anything_is_asked(world):
    world["key"].protected = False
    world["key"].exists = True  # an existing, unprotected key under the name
    asked = []

    def owner(body):
        asked.append(body)
        return world["owner"](body)
    window = world["Window"]()
    with pytest.raises(roots.WorkspaceRootRefused, match="not owner-protected"):
        _register(world, "alpha", window=window, forward=owner)
    assert asked == [] and window.asked == [] and _active(world) == ([], None)


def test_a_forged_first_key_without_a_valid_key_check_is_never_pinned(world):
    """Before any pin, the owner accepts an offered public half only with a KEY_CHECK
    signature that verifies under it: missing, garbage, or made by another key."""
    rogue, other = _Key(), _Key()
    change = _change(world, "alpha")
    prepared = world["owner"]({"action": "prepare", "change": change, **_offer(rogue)}, verifier=rogue)
    assert prepared == {"prepared": {"needs_key_check": True}}
    proper = world["owner"]({"action": "prepare", "change": change, **_offer(rogue, check=True)},
                            verifier=rogue)["prepared"]
    signature = rogue.sign(roots.canonical(proper["body"]))
    cases = {"missing": _offer(rogue),
             "garbage": {**_offer(rogue), "key_check": "00" * 64},
             "another key": {**_offer(rogue), "key_check": other.sign(roots.KEY_CHECK)},
             "another message": {**_offer(rogue), "key_check": rogue.sign(b"not the key check")}}
    for name, offer in cases.items():
        with pytest.raises(roots.WorkspaceRootRefused, match="key check"):
            world["owner"]({**change, "signature": signature, **offer}, verifier=rogue)
    with pytest.raises(roots.WorkspaceRootRefused, match="not an ECDSA P-256 public key"):
        world["owner"]({**change, "signature": signature, "public_blob": "ab" * 72,
                        "key_check": "00" * 64}, verifier=rogue)
    assert _active(world) == ([], None)
    assert not world["files"]["pin_path"].exists()


def test_a_blob_that_is_not_the_pin_is_refused_even_with_its_own_key_check(world):
    _register(world, "alpha")
    other = _Key()
    change = _change(world, "beta")
    with pytest.raises(roots.WorkspaceRootRefused, match="not the pinned key"):
        world["owner"]({"action": "prepare", "change": change, **_offer(other, check=True)},
                       verifier=other)
    assert _active(world)[0] == ["alpha"]


def test_concurrent_first_registrations_pin_one_key_and_refuse_the_other(world):
    """Two windows, two keys, no pin yet: both prepare, both sign; the first commit
    pins its key, the second is refused and nothing of it commits."""
    first, second = world["key"], _Key()
    first.exists = True
    a, b = _change(world, "alpha"), _change(world, "beta")
    pa = world["owner"]({"action": "prepare", "change": a, **_offer(first, check=True)})["prepared"]
    pb = world["owner"]({"action": "prepare", "change": b, **_offer(second, check=True)},
                        verifier=second)["prepared"]
    commit_a = {**a, "signature": first.sign(roots.canonical(pa["body"])), **_offer(first, check=True),
                "admission_ticket": pa["admission_ticket"]}
    commit_b = {**b, "signature": second.sign(roots.canonical(pb["body"])), **_offer(second, check=True),
                "admission_ticket": pb["admission_ticket"]}
    barrier, results = threading.Barrier(2), {}

    class Waiting:
        """Holds both approvals between the owner's two reads of the graph."""

        def __init__(self, inner):
            self.inner = inner

        def verify_blob(self, blob, key_id, version, payload, signature):
            ok = self.inner.verify_blob(blob, key_id, version, payload, signature)
            if payload != roots.KEY_CHECK:
                try:
                    barrier.wait(timeout=10)
                except threading.BrokenBarrierError:
                    pass
            return ok

    def run(name, body, key):
        try:
            results[name] = world["owner"](body, verifier=Waiting(key))
        except roots.WorkspaceRootRefused as exc:
            results[name] = exc
    threads = [threading.Thread(target=run, args=("a", commit_a, first)),
               threading.Thread(target=run, args=("b", commit_b, second))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    refused = [name for name, result in results.items() if isinstance(result, Exception)]
    assert len(results) == 2 and len(refused) == 1, results
    winner = "a" if refused == ["b"] else "b"
    assert "nothing was changed" in str(results[refused[0]])
    pinned = (first if winner == "a" else second).fingerprint()
    assert _active(world) == ([{"a": "alpha", "b": "beta"}[winner]], pinned)
    assert roots.read_pin(world["files"]["pin_path"])[0] == pinned


def test_an_approval_for_a_graph_that_moved_is_refused(world):
    _register(world, "alpha")
    folder = world["tmp"] / "gamma"
    folder.mkdir()
    change = {"action": "register", "id": "gamma", "path": str(folder), "privacy": "private",
              "profile": "client", "writers": ["claude"]}
    prepared = world["owner"]({"action": "prepare", "change": change,
                               **_offer(world["key"])})["prepared"]
    approval = world["key"].sign(roots.canonical(prepared["body"]))
    _register(world, "beta")  # the graph moves after the approval was made
    with pytest.raises(roots.WorkspaceRootRefused, match="approval does not match"):
        world["owner"]({**change, "signature": approval, **_offer(world["key"])})
    assert _active(world)[0] == ["alpha", "beta"]


def test_the_window_refuses_to_sign_a_snapshot_that_is_not_its_request(world):
    _register(world, "alpha")
    window = world["Window"]()

    def lying_owner(body):
        if body.get("action") == "prepare":
            other = dict(body["change"], path=str(world["tmp"] / "elsewhere"))
            offer = {k: v for k, v in body.items() if k in ("public_blob", "key_check")}
            answer = world["owner"]({"action": "prepare", "change": {**other, "id": "elsewhere"},
                                     **offer})
            (world["tmp"] / "elsewhere").mkdir(exist_ok=True)
            return answer
        return world["owner"](body)

    (world["tmp"] / "elsewhere").mkdir(exist_ok=True)
    with pytest.raises(roots.WorkspaceRootRefused, match="prepared a different change"):
        _register(world, "beta", window=window, forward=lying_owner)
    assert window.asked == [] and _active(world)[0] == ["alpha"]


def test_prepare_never_commits(world):
    folder = world["tmp"] / "alpha"
    folder.mkdir()
    change = {"action": "register", "id": "alpha", "path": str(folder), "privacy": "private",
              "profile": "client", "writers": ["claude"]}
    with pytest.raises(roots.WorkspaceRootRefused, match="unexpected workspace-roots fields"):
        world["owner"]({"action": "prepare", "change": change})  # no key offered
    assert world["owner"]({"action": "prepare", "change": change, **_offer(world["key"])}) == {
        "prepared": {"needs_key_check": True}}
    prepared = world["owner"]({"action": "prepare", "change": change,
                               **_offer(world["key"], check=True)})["prepared"]
    assert prepared["pin"] == world["key"].fingerprint()
    assert [r["id"] for r in prepared["body"]["roots"]] == ["alpha"]
    assert _active(world) == ([], None)
    assert not world["files"]["snapshot_path"].exists()
    with pytest.raises(roots.WorkspaceRootRefused, match="only a change can be prepared"):
        world["owner"]({"action": "prepare", "change": {"action": "list"}, **_offer(world["key"])})


def test_the_pin_carries_the_public_half_and_the_owner_reads_only_files(world):
    _register(world, "alpha")
    fingerprint, blob = roots.read_pin(world["files"]["pin_path"])
    assert blob == world["key"].public_blob() and fingerprint == world["key"].fingerprint()
    assert roots.verify_projection(roots.snapshot_body(
        roots.read_state(world["authority"], world["catalogue"], caller=world["caller"])[1],
        fingerprint), world["key"], **world["files"]) == "match"


def test_the_production_owner_path_never_opens_the_key(world, monkeypatch):
    """The default verifier (CngVerifier) is used for verify_blob only: with the key
    store refusing every open, a full first registration and a second one commit."""
    def owner_default(body):
        body = dict(body)
        operation = body.pop("command_id", None) or str(uuid.uuid4())
        return roots.owner_change(world["authority"], world["catalogue"], body,
                                  caller=world["caller"], operation_id=operation,
                                  lock=threading.RLock(),
                                  admission={"principal": world["settings_principal"]},
                                  **world["files"])
    view = _register(world, "alpha", forward=owner_default)
    assert view["projection"] == "match"
    _register(world, "beta", forward=owner_default)
    assert _active(world) == (["alpha", "beta"], world["key"].fingerprint())
