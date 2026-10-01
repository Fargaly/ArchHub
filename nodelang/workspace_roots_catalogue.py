"""Workspace roots: the owner's registered folders, held in the one graph.

A root is an instance of the published "Workspace root" definition inside the
"Governance" composition, created and revised only through the signed authority
commands (instantiate_definition, revise_instance). Unregistering moves its state
to "unregistered"; no file is ever touched and the history stays in the graph.

The signing key's identity is graph-authoritative: the first registration records
the SHA-256 of the key's public half as the one "Workspace roots signing key"
instance, and every later signature is made only by the key with that fingerprint
(CngSigner(pinned_fingerprint=...)). The governance hooks read a signed snapshot
projected from these records, plus a pin file carrying the same fingerprint; they
activate no root unless the snapshot verifies under the key the pin names.

Owner approval: the owner route can be reached by any local process, so the
browser session alone never proves the owner asked. Every change signs the
snapshot it will produce BEFORE it commits (owner_change); the Windows prompt of
the protected key is the approval, and a declined prompt changes nothing.

Limits (stated, not hidden):
* Before the first registration nothing is pinned: a same-user process could
  replace the named key then. Once pinned, a substitute key is refused.
* An owner who approves a prompt they did not start approves that change.
* The owner prompt is proven for key creation (silent finalize is refused); a
  per-signature prompt for an existing key is checked from its UI policy, not
  exercised.
* Only the state of a root is revised here. Other values are fixed at
  registration because no path in this module or its route revises them; the
  definition itself does not forbid it.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import tempfile
import time
import uuid

from .unified_authority import (
    CallerCommandCapability,
    UnifiedAuthority,
    composition_root,
    declare_definition,
    instantiate_definition,
    promote_definition,
    published_definition_named,
    read_contained_scope,
    revise_instance,
)
from .universal_cell import InvalidCell


ROOT_DEFINITION = "Workspace root"
KEY_DEFINITION = "Workspace roots signing key"
COMPOSITION = "Governance"
PRIVACY = ("private", "public")
PROFILES = ("client",)
RUNTIMES = ("claude", "codex", "opencode", "gemini", "antigravity", "cursor")


def built_in_path() -> str:
    """The built-in governed tree: the same folder the application resolves as
    its workspace root (workspace_root.workspace_root_for_map over the selected
    map). A running application passes its own resolved root as built_in, so
    admission and the view always use that instance's tree; this is only the
    fallback for callers without one. Never a hardcoded machine path."""
    from .map_import import resolve_map_path
    from .workspace_root import workspace_root_for_map
    return str(PureWindowsPath(workspace_root_for_map(resolve_map_path())))


def __getattr__(name):
    if name == "BUILT_IN_PATH":
        return built_in_path()
    raise AttributeError(name)


SNAPSHOT_FORMAT = "archhub.workspace-roots"
SNAPSHOT_VERSION = 3
PIN_FORMAT = "archhub.workspace-roots-pin"
KEY_NAME = "ArchHub-workspace-roots-v1"
KEY_ID = "cng:" + KEY_NAME
MAX_ROOTS = 64
MAX_REMOVED = 256
PROMISE = (
    "Removing a workspace only stops ArchHub from governing it. "
    "Your files are never deleted."
)
PROVENANCE = {
    "archhub-specification": "SPEC.md sections 4.4, 4.5 and 9",
    "windows-cng-key-storage": (
        "https://learn.microsoft.com/windows/win32/seccng/key-storage-and-retrieval"
    ),
}
_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
_FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")
_REPARSE_POINT = 0x400


class WorkspaceRootRefused(InvalidCell):
    """A registration request that cannot be admitted."""


@dataclass(frozen=True, slots=True)
class WorkspaceRootCatalogue:
    root_definition: str
    key_definition: str


def _subcommand(operation_id: str, label: str) -> str:
    try:
        namespace = uuid.UUID(operation_id)
    except (TypeError, ValueError) as exc:
        raise InvalidCell("workspace root operation identity is invalid") from exc
    return str(uuid.uuid5(namespace, label))


def _publish(authority, name, defaults, *, parameters, rules, panels, operation_id,
             label, caller):
    held = published_definition_named(authority, name, caller=caller)
    if held is not None:
        return held
    declared = declare_definition(
        authority,
        name,
        defaults,
        parameters=parameters,
        rules=rules,
        presentation={"label": name, "panels": panels},
        courts={"owner-only": "required", "files-never-deleted": "required"},
        provenance=PROVENANCE,
        caller=caller,
        command_id=_subcommand(operation_id, label + ":declare"),
    )
    shared = promote_definition(
        authority,
        declared.root_id,
        target_lifecycle="shared",
        version="1-shared",
        evidence_roots=(declared.receipt_root,),
        caller=caller,
        command_id=_subcommand(operation_id, label + ":share"),
    )
    published = promote_definition(
        authority,
        declared.root_id,
        target_lifecycle="published",
        version="1",
        evidence_roots=(shared.receipt_root,),
        caller=caller,
        command_id=_subcommand(operation_id, label + ":publish"),
    )
    return published.root_id


def install_workspace_root_catalogue(
    authority: UnifiedAuthority,
    *,
    operation_id: str,
    caller: CallerCommandCapability,
) -> WorkspaceRootCatalogue:
    """Publish the two definitions once; later calls answer from the head."""
    root_definition = _publish(
        authority,
        ROOT_DEFINITION,
        {
            "root_id": "",
            "path": "",
            "privacy": "private",
            "profile": "client",
            "writers": ["claude"],
            "identity": [],
            "state": "registered",
            "registered_at": "",
        },
        parameters={
            "root_id": {"type": "text", "editor": "text"},
            "path": {"type": "text", "editor": "text"},
            "privacy": {"type": "text", "options": list(PRIVACY), "editor": "choice"},
            "profile": {"type": "text", "options": list(PROFILES), "editor": "choice"},
            "writers": {"type": "list"},
            "identity": {"type": "list"},
            "state": {
                "type": "text",
                "options": ["registered", "unregistered"],
                "editor": "choice",
            },
            "registered_at": {"type": "text"},
        },
        rules={
            "state_parameter": "state",
            "transitions": {"unregistered": {"from": ["registered"]}},
        },
        panels=["Workspace", "History"],
        operation_id=operation_id,
        label="root",
        caller=caller,
    )
    key_definition = _publish(
        authority,
        KEY_DEFINITION,
        {"key_id": KEY_ID, "fingerprint": ""},
        parameters={
            "key_id": {"type": "text"},
            "fingerprint": {"type": "text"},
        },
        rules={},
        panels=["Key", "History"],
        operation_id=operation_id,
        label="key",
        caller=caller,
    )
    return WorkspaceRootCatalogue(root_definition, key_definition)


def find_workspace_root_catalogue(authority, *, caller):
    """The published catalogue, or None. Never commits (safe at boot)."""
    root = published_definition_named(authority, ROOT_DEFINITION, caller=caller)
    key = published_definition_named(authority, KEY_DEFINITION, caller=caller)
    if root is None or key is None:
        return None
    return WorkspaceRootCatalogue(root, key)


def _governance(authority, caller):
    return composition_root(authority, COMPOSITION, caller=caller)


def read_state(authority, catalogue, *, caller):
    """(revision, roots, pin): every root instance (any state) and the pinned key."""
    governance = _governance(authority, caller)
    projection = read_contained_scope(
        authority, governance, scope_root=governance, caller=caller
    )
    roots, pins = [], []
    for instance_root, instance in projection.instances.items():
        values = instance.get("values")
        definition = instance.get("definition")
        if definition == catalogue.root_definition:
            roots.append({"instance": instance_root, **dict(values)})
        elif definition == catalogue.key_definition:
            pins.append(dict(values))
    if len(pins) > 1:
        raise InvalidCell("the graph holds more than one workspace-roots signing key")
    pin = None
    if pins:
        pin = pins[0]
        if pin.get("key_id") != KEY_ID or not _FINGERPRINT.match(str(pin.get("fingerprint"))):
            raise InvalidCell("the pinned workspace-roots signing key record is invalid")
        pin = pin["fingerprint"]
    roots.sort(key=lambda root: (str(root.get("root_id")), root["instance"]))
    return projection.revision, tuple(roots), pin


def _active(roots):
    return [root for root in roots if root.get("state") == "registered"]


def folder_identity(path):
    """(volume serial, file index) exactly as the hooks read it."""
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    class Info(ctypes.Structure):
        _fields_ = [("attributes", wintypes.DWORD), ("created", wintypes.FILETIME),
                    ("accessed", wintypes.FILETIME), ("written", wintypes.FILETIME),
                    ("volume_serial", wintypes.DWORD), ("size_high", wintypes.DWORD),
                    ("size_low", wintypes.DWORD), ("links", wintypes.DWORD),
                    ("index_high", wintypes.DWORD), ("index_low", wintypes.DWORD)]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                   wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
                                   wintypes.HANDLE)
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.GetFileInformationByHandle.argtypes = (wintypes.HANDLE, ctypes.POINTER(Info))
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = kernel.CreateFileW(str(path), 0x80, 0x7, None, 3, 0x02000000, None)
    if handle is None or handle == ctypes.c_void_p(-1).value:
        return None
    try:
        info = Info()
        if not kernel.GetFileInformationByHandle(handle, ctypes.byref(info)):
            return None
        return (info.volume_serial, (info.index_high << 32) | info.index_low)
    finally:
        kernel.CloseHandle(handle)


def _local_folder_path(text) -> bool:
    if type(text) is not str or not text or len(text) > 1024 or "\x00" in text:
        return False
    path = PureWindowsPath(text)
    drive = path.drive
    return (len(drive) == 2 and drive[1] == ":" and path.is_absolute()
            and len(path.parts) > 1 and ":" not in path.name
            and not text.startswith(chr(92) * 2)
            and not any(part != part.rstrip(" .") for part in path.parts[1:]))


def _ancestor_identities(path):
    found = []
    for ancestor in (PureWindowsPath(path), *PureWindowsPath(path).parents):
        identity = folder_identity(str(ancestor))
        if identity is not None:
            found.append(identity)
    return found


def _nests(first: str, second: str) -> bool:
    a, b = folder_identity(first), folder_identity(second)
    return a in _ancestor_identities(second) or b in _ancestor_identities(first)


def admit_folder(path, root_id, privacy, profile, writers, roots, *, built_in=None):
    """The registration values, or WorkspaceRootRefused for anything the hooks refuse."""
    if type(root_id) is not str or not _ID.match(root_id) or root_id == "archhub":
        raise WorkspaceRootRefused("workspace root id is invalid")
    if privacy not in PRIVACY or profile not in PROFILES:
        raise WorkspaceRootRefused("workspace root privacy or profile is invalid")
    if (type(writers) not in (list, tuple) or not writers
            or len(set(writers)) != len(writers)
            or not all(writer in RUNTIMES for writer in writers)):
        raise WorkspaceRootRefused("workspace root writers are invalid")
    if not _local_folder_path(path) or not os.path.isdir(path):
        raise WorkspaceRootRefused(
            "a workspace root must be an existing local folder, not a drive root"
        )
    if getattr(os.lstat(path), "st_file_attributes", 0) & _REPARSE_POINT:
        raise WorkspaceRootRefused("a workspace root cannot be a junction or symbolic link")
    identity = folder_identity(path)
    if identity is None:
        raise WorkspaceRootRefused("the folder identity cannot be read")
    active = _active(roots)
    if len(active) >= MAX_ROOTS:
        raise WorkspaceRootRefused("at most %d workspace roots can be registered" % MAX_ROOTS)
    if any(root.get("root_id") == root_id for root in roots):
        raise WorkspaceRootRefused("that workspace root id is already used")
    if _nests(path, built_in or built_in_path()) or any(_nests(path, root["path"]) for root in active):
        raise WorkspaceRootRefused("workspace roots cannot be inside or around another root")
    return {
        "root_id": root_id,
        "path": str(PureWindowsPath(path)),
        "privacy": privacy,
        "profile": profile,
        "writers": list(writers),
        "identity": list(identity),
        "state": "registered",
        "registered_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def pin_signing_key(authority, catalogue, fingerprint, *, caller, operation_id):
    """Record the key's fingerprint once. A different fingerprint is refused."""
    if type(fingerprint) is not str or not _FINGERPRINT.match(fingerprint):
        raise InvalidCell("workspace-roots key fingerprint is invalid")
    _revision, _roots, pin = read_state(authority, catalogue, caller=caller)
    if pin is not None:
        if pin != fingerprint:
            raise InvalidCell("a different workspace-roots signing key is already pinned")
        return pin
    instantiate_definition(
        authority,
        catalogue.key_definition,
        {"key_id": KEY_ID, "fingerprint": fingerprint},
        scope_root=_governance(authority, caller),
        caller=caller,
        command_id=_subcommand(operation_id, "pin"),
    )
    return fingerprint


def register_root(authority, catalogue, values, *, caller, operation_id):
    """One signed instantiation in Governance. `values` come from admit_folder()."""
    _revision, roots, pin = read_state(authority, catalogue, caller=caller)
    if pin is None:
        raise InvalidCell("no workspace-roots signing key is pinned yet")
    if any(root.get("root_id") == values["root_id"] for root in roots):
        raise WorkspaceRootRefused("that workspace root id is already used")
    return instantiate_definition(
        authority,
        catalogue.root_definition,
        values,
        scope_root=_governance(authority, caller),
        caller=caller,
        command_id=_subcommand(operation_id, "register"),
    )


def unregister_root(authority, catalogue, root_id, *, caller, operation_id):
    """Stop governing a root. Only its state changes; its files are never touched."""
    _revision, roots, _pin = read_state(authority, catalogue, caller=caller)
    matches = [root for root in roots if root.get("root_id") == root_id]
    if len(matches) != 1:
        raise WorkspaceRootRefused("no such workspace root")
    if matches[0].get("state") == "unregistered":
        return None
    return revise_instance(
        authority,
        matches[0]["instance"],
        {"state": "unregistered"},
        scope_root=_governance(authority, caller),
        caller=caller,
        command_id=_subcommand(operation_id, "unregister"),
    )


def canonical(payload) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True).encode("utf-8")


def sequence(roots, pin) -> int:
    """A counter every owner change raises by exactly one, known BEFORE the commit:
    one per registration, one more per unregistration, one for the pin. The hooks
    use it as the snapshot's monotonic revision (rollback protection)."""
    return (1 if pin is not None else 0) + sum(
        2 if root.get("state") == "unregistered" else 1 for root in roots)


def removed_folders(roots):
    """The signed tombstones: folders that were registered and then removed, and
    are not registered again (same folder identity or spelling). Agents stay
    blocked there (workspace_root_removed) until the owner registers the folder
    again -- or registers a folder that contains it (founder 2026-09-30: the
    parent E:/01.PERSONAL covers BBC4 inside it). Roots never nest, so a removed
    child inside an active root was removed before that root was registered.
    Ordered by id; one entry per folder."""
    active = _active(roots)
    live_identities = {tuple(root["identity"]) for root in active}
    live_paths = {str(PureWindowsPath(root["path"])).casefold() for root in active}
    covering = tuple(path.rstrip(chr(92)) + chr(92) for path in live_paths)
    removed, seen = [], set()
    for root in sorted(roots, key=lambda item: item["root_id"]):
        if root.get("state") != "unregistered":
            continue
        identity = tuple(root["identity"])
        spelling = str(PureWindowsPath(root["path"])).casefold()
        if (identity in live_identities or spelling in live_paths or identity in seen
                or spelling.startswith(covering)):
            continue
        seen.add(identity)
        removed.append({"id": root["root_id"], "path": root["path"],
                        "identity": list(root["identity"])})
    return removed


def snapshot_body(roots, pin) -> dict:
    """The hooks' view of the graph: registered roots and removed-folder
    tombstones, ordered by id. The order is canonical, so the body signed before
    a commit (from a prediction) equals the body re-derived from the graph after it."""
    entries = [
        {
            "id": root["root_id"],
            "path": root["path"],
            "privacy": root["privacy"],
            "profile": root["profile"],
            "writers": list(root["writers"]),
            "identity": list(root["identity"]),
        }
        for root in sorted(_active(roots), key=lambda root: root["root_id"])
    ]
    return {
        "format": SNAPSHOT_FORMAT,
        "format_version": SNAPSHOT_VERSION,
        "key_id": KEY_ID,
        "key_version": 1,
        "key_fingerprint": pin,
        "graph_revision": sequence(roots, pin),
        "roots": entries,
        "removed": removed_folders(roots),
    }


def registry_dir() -> Path:
    home = os.environ.get("USERPROFILE") or str(Path.home())
    return Path(home) / ".archhub"


def default_snapshot_path() -> Path:
    return registry_dir() / "workspace-roots.json"


def default_pin_path() -> Path:
    return registry_dir() / "workspace-roots.pin"


def _atomic_write(target: Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix="." + target.name + ".", dir=str(target.parent))
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_projection(body: dict, signature: str, *, snapshot_path=None, pin_path=None) -> None:
    """The pin first (the hooks' trusted identity), then the signed snapshot."""
    _atomic_write(Path(pin_path or default_pin_path()),
                  canonical({"format": PIN_FORMAT, "key_id": KEY_ID,
                             "fingerprint": body["key_fingerprint"]}))
    _atomic_write(Path(snapshot_path or default_snapshot_path()),
                  canonical({**body, "signature": signature}))


def verify_projection(body: dict, verifier, *, snapshot_path=None, pin_path=None) -> str:
    """"match", "missing", "unsigned", "unpinned" or "mismatch": do the hooks' files
    project this graph state? Anything but "match" (or "missing" before the first
    registration) is shown as a banner and refuses owner changes until republished."""
    snapshot_path = snapshot_path or default_snapshot_path()
    pin_path = pin_path or default_pin_path()
    try:
        document = json.loads(Path(snapshot_path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        if not body["roots"] and body["key_fingerprint"] is None:
            return "missing"
        return "mismatch"
    except (OSError, ValueError):
        return "unsigned"
    if type(document) is not dict:
        return "unsigned"
    signed = {key: value for key, value in document.items() if key != "signature"}
    if not verifier.verify(KEY_ID, 1, canonical(signed), str(document.get("signature", ""))):
        return "unsigned"
    try:
        pin = json.loads(Path(pin_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "unpinned"
    if (type(pin) is not dict or pin.get("key_id") != KEY_ID
            or pin.get("fingerprint") != body["key_fingerprint"]
            or signed.get("key_fingerprint") != body["key_fingerprint"]):
        return "unpinned"
    return "match" if signed == body else "mismatch"


def boot_check(authority, catalogue, *, caller, verifier=None, snapshot_path=None,
               pin_path=None) -> str:
    """Re-derive the projection from the graph and compare it with the hooks' files.
    A graph that never published the catalogue holds no roots (catalogue None)."""
    try:
        from .workspace_roots_signing import CngVerifier

        if catalogue is None:
            roots, pin = (), None
        else:
            _revision, roots, pin = read_state(authority, catalogue, caller=caller)
        return verify_projection(snapshot_body(roots, pin), verifier or CngVerifier(KEY_NAME),
                                 snapshot_path=snapshot_path, pin_path=pin_path)
    except Exception as exc:  # noqa: BLE001 - a check that cannot answer is not a match
        return "unverifiable: " + type(exc).__name__


def _predict(roots, action, values=None, root_id=None):
    """The roots after the change, without committing anything."""
    if action == "register":
        return tuple(roots) + ({**values, "instance": None},)
    if action == "unregister":
        matches = [root for root in roots if root.get("root_id") == root_id]
        if len(matches) != 1:
            raise WorkspaceRootRefused("no such workspace root")
        if matches[0].get("state") == "unregistered":
            raise WorkspaceRootRefused("that workspace root is already unregistered")
        return tuple({**root, "state": "unregistered"} if root is matches[0] else root
                     for root in roots)
    return tuple(roots)


def _comparable(roots):
    return [{key: value for key, value in root.items() if key != "instance"} for root in roots]


_FIELDS = {
    "list": {"action"},
    "republish": {"action"},
    "unregister": {"action", "id"},
    "register": {"action", "id", "path", "privacy", "profile", "writers"},
}
# A change approved in another (visible) process: "prepare" returns the exact
# snapshot that change would produce; the change then carries "signature".
_CHANGES = ("register", "unregister", "republish")
KEY_CHECK = b"archhub workspace-roots key check"


def _approval_key(verifier, pin):
    """The public half an approval made elsewhere must verify under: the protected
    key the store holds, which must be the pinned one once a pin exists. None when
    no key exists yet (the approving process creates it, with the owner prompt)."""
    from .workspace_roots_signing import SigningUnavailable
    try:
        blob = verifier.protected_public_blob()
    except SigningUnavailable as exc:
        raise WorkspaceRootRefused("the workspace-roots signing key is refused: " + str(exc)) from exc
    if blob is None:
        if pin is not None:
            raise WorkspaceRootRefused("the pinned workspace-roots signing key is missing")
        return None, None
    fingerprint = hashlib.sha256(bytes(blob)).hexdigest()
    if pin is not None and fingerprint != pin:
        raise WorkspaceRootRefused("the workspace-roots signing key is not the pinned key")
    return bytes(blob), fingerprint


def owner_change(authority, catalogue, request, *, caller, operation_id, lock,
                 signer_factory=None, fingerprint_of=None, verifier=None,
                 snapshot_path=None, pin_path=None, built_in=None) -> dict:
    """List, register, unregister or republish, with the owner's key as the approval.

    The snapshot a change will produce is signed BEFORE anything commits: the
    Windows owner prompt is the approval, so a request the owner did not make
    (any local process can reach a loopback route) changes nothing when it is
    declined. Signing happens outside `lock`; the graph is re-read under it and
    the change is refused if it moved meanwhile.
    """
    from .workspace_roots_signing import CngVerifier, SigningUnavailable

    preparing = type(request) is dict and request.get("action") == "prepare"
    if preparing:
        # The change the approving process will sign, never committed here.
        if set(request) != {"action", "change"} or type(request["change"]) is not dict:
            raise WorkspaceRootRefused("unexpected workspace-roots fields")
        request = request["change"]
        if request.get("action") not in _CHANGES or "signature" in request:
            raise WorkspaceRootRefused("only a change can be prepared for approval")
    if type(request) is not dict or request.get("action") not in _FIELDS:
        raise WorkspaceRootRefused(
            "workspace-roots action must be list, register, unregister or republish")
    action = request["action"]
    approval = request.get("signature")
    allowed = _FIELDS[action] | ({"signature"} if action in _CHANGES else set())
    if (set(request) - allowed or (action == "unregister" and "id" not in request)
            or ("signature" in request and (type(approval) is not str or len(approval) != 128))):
        raise WorkspaceRootRefused("unexpected workspace-roots fields")
    if action in _CHANGES and not preparing and approval is None and signer_factory is None:
        # This process (the graph's owner) has no visible window: a key prompt it
        # raised would never be seen and the change would hang. A change is approved
        # in the ArchHub window (approve_in_this_window) and arrives signed. Only a
        # court injects signer_factory to sign here.
        raise WorkspaceRootRefused(NO_WINDOW)
    verifier = verifier or CngVerifier(KEY_NAME)
    paths = {"snapshot_path": snapshot_path, "pin_path": pin_path}
    with lock:
        revision, roots, pin = read_state(authority, catalogue, caller=caller)
        if action == "list":
            status = verify_projection(snapshot_body(roots, pin), verifier, **paths)
            return roots_view(revision, roots, pin, status, built_in=built_in)
        values = None
        if action == "register":
            values = admit_folder(request.get("path"), request.get("id"),
                                  request.get("privacy"), request.get("profile", "client"),
                                  request.get("writers") or ["claude"], roots,
                                  built_in=built_in)
        predicted = _predict(roots, action, values, request.get("id"))
    if pin is None and action == "republish":
        raise WorkspaceRootRefused("nothing is registered yet")
    if preparing or approval is not None:
        # Approved in the visible desktop process (the owner prompt needs a window
        # this process does not have). This process only verifies: the signature
        # must be the protected, pinned key's, over exactly the snapshot derived
        # here from the graph as it is now; anything else commits nothing.
        blob, new_pin = _approval_key(verifier, pin)
        if preparing:
            if new_pin is None:
                return {"prepared": {"needs_key": True}}
            return {"prepared": {"body": snapshot_body(predicted, new_pin), "pin": new_pin}}
        if blob is None:
            raise WorkspaceRootRefused("no workspace-roots signing key exists yet")
        body = snapshot_body(predicted, new_pin)
        signature = approval
        if not verifier.verify_blob(blob, KEY_ID, 1, canonical(body), signature):
            raise WorkspaceRootRefused(
                "the approval does not match this change (the roots may have changed); "
                "nothing was changed")
    else:
        try:
            new_pin = pin
            if new_pin is None:
                signer_factory(None).sign(KEY_CHECK)
                new_pin = (fingerprint_of or CngVerifier(KEY_NAME).public_fingerprint)()
                if type(new_pin) is not str or not _FINGERPRINT.match(new_pin):
                    raise WorkspaceRootRefused("the signing key fingerprint is unreadable")
            body = snapshot_body(predicted, new_pin)
            signature = signer_factory(new_pin).sign(canonical(body))
        except SigningUnavailable as exc:
            raise WorkspaceRootRefused("the owner did not approve: " + str(exc)) from exc
    with lock:
        _now, current, current_pin = read_state(authority, catalogue, caller=caller)
        if _comparable(current) != _comparable(roots) or current_pin != pin:
            raise WorkspaceRootRefused(
                "workspace roots changed while waiting for approval; nothing was changed")
        if pin is None:
            pin_signing_key(authority, catalogue, new_pin, caller=caller,
                            operation_id=operation_id)
        if action == "register":
            register_root(authority, catalogue, values, caller=caller,
                          operation_id=operation_id)
        elif action == "unregister":
            unregister_root(authority, catalogue, request["id"], caller=caller,
                            operation_id=operation_id)
        revision, after, after_pin = read_state(authority, catalogue, caller=caller)
        if snapshot_body(after, after_pin) != body:
            raise InvalidCell("the committed workspace roots differ from the approved "
                              "projection; the hooks' files were left unchanged")
        write_projection(body, signature, **paths)
    return roots_view(revision, after, after_pin,
                      verify_projection(body, verifier, **paths), built_in=built_in)


ROOT_PATH_PREFIX = "workspace-roots/"


def read_registered_roots(verifier=None, *, snapshot_path=None, pin_path=None,
                          last_good_path=None):
    """(roots by id, pin) from the hooks' projection, or InvalidCell.

    The same trust as the hooks: the pin file names the key, the key store's
    public blob is read ONCE and must hash to the pin, and the snapshot must
    name that fingerprint and verify under exactly that blob."""
    from .workspace_roots_signing import CngVerifier

    verifier = verifier or CngVerifier(KEY_NAME)
    try:
        pin = json.loads(Path(pin_path or default_pin_path()).read_text(encoding="utf-8"))
        document = json.loads(Path(snapshot_path or default_snapshot_path()).read_text(
            encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise InvalidCell("the workspace-roots registry is unavailable") from exc
    if (type(pin) is not dict or set(pin) != {"format", "key_id", "fingerprint"}
            or pin["format"] != PIN_FORMAT or pin["key_id"] != KEY_ID
            or type(pin["fingerprint"]) is not str
            or not _FINGERPRINT.match(pin["fingerprint"])):
        raise InvalidCell("the workspace-roots signing key is not pinned")
    try:
        blob = verifier.public_blob()
    except Exception as exc:  # noqa: BLE001 - doubt is a refusal
        raise InvalidCell("the workspace-roots signing key is unavailable") from exc
    if not blob or hashlib.sha256(bytes(blob)).hexdigest() != pin["fingerprint"]:
        raise InvalidCell("the workspace-roots signing key is not the pinned key")
    if type(document) is not dict or type(document.get("signature")) is not str:
        raise InvalidCell("the workspace-roots registry is unsigned")
    signed = {key: value for key, value in document.items() if key != "signature"}
    if (signed.get("format") != SNAPSHOT_FORMAT
            or signed.get("format_version") != SNAPSHOT_VERSION
            or signed.get("key_id") != KEY_ID
            or signed.get("key_fingerprint") != pin["fingerprint"]
            or type(signed.get("roots")) is not list
            or len(signed["roots"]) > MAX_ROOTS
            or type(signed.get("removed")) is not list
            or len(signed["removed"]) > MAX_REMOVED
            or not verifier.verify_blob(bytes(blob), KEY_ID, 1, canonical(signed),
                                        document["signature"])):
        raise InvalidCell("the workspace-roots registry does not verify")
    _refuse_rollback(signed, blob, verifier, last_good_path)
    _require_graph_current(signed)
    roots = {}
    for entry in signed["roots"]:
        if type(entry) is not dict or type(entry.get("id")) is not str or entry["id"] in roots:
            raise InvalidCell("the workspace-roots registry is malformed")
        roots[entry["id"]] = entry
    return roots, pin["fingerprint"]


REGISTRY_DIGEST_SCHEMA = "archhub.workspace-roots.registry-digest/v1"
STATE_PURPOSE = "archhub.workspace-roots-state/v1"
ISSUER_IDENTITY = ("archhub", "cde-permit-issuer")
# The desktop's Settings -> Workspaces reaches the graph's owner under its own key,
# which is admitted for exactly one method (workspace_roots_settings).
SETTINGS_IDENTITY = ("archhub", "workspace-roots-settings")
# Browse waits for the owner's folder dialog and Add for his key prompt.
SETTINGS_TIMEOUT_SECONDS = 660.0
COORDINATION_ENDPOINT = "http://127.0.0.1:8474/coordination"
_NONCE = re.compile(r"^[0-9a-f]{32}$")
_STATEMENT_FIELDS = {"purpose", "graph_id", "request_id", "nonce", "revision", "registry_digest"}


def registry_digest(body) -> str:
    """ONE digest schema, used by the graph's owner and by the permit issuer."""
    return hashlib.sha256(canonical({"schema": REGISTRY_DIGEST_SCHEMA, "body": body})).hexdigest()


def current_registry_statement(authority, *, caller, request_id, parameters) -> dict:
    """The graph owner's answer: revision and registry digest from ONE contained-scope
    read, bound to the request's id and nonce and signed with the instance's own
    authority key. Reads only; commits nothing."""
    if type(parameters) is not dict or set(parameters) != {"nonce"} or not _NONCE.match(
            str(parameters.get("nonce"))):
        raise InvalidCell("workspace-roots state takes exactly one fresh nonce")
    catalogue = find_workspace_root_catalogue(authority, caller=caller)
    if catalogue is None:
        revision, roots, pin = authority.store.snapshot().revision, (), None
    else:
        revision, roots, pin = read_state(authority, catalogue, caller=caller)
    statement = {
        "purpose": STATE_PURPOSE,
        "graph_id": authority.manifest.graph_id,
        "request_id": request_id,
        "nonce": parameters["nonce"],
        "revision": revision,
        "registry_digest": registry_digest(snapshot_body(roots, pin)),
    }
    signature = authority.key_provider.sign(authority.manifest.key_id,
                                            authority.manifest.key_version, canonical(statement))
    return {"statement": statement, "signature": signature}


@dataclass(frozen=True, slots=True)
class CanonicalInstance:
    graph_id: str
    key_id: str
    key_version: int
    key_fingerprint: str


def canonical_instance(root=None) -> CanonicalInstance:
    """The selected generation's public bootstrap facts (no secret, no graph open)."""
    base = Path(root) if root is not None else (
        Path(os.environ.get("LOCALAPPDATA") or str(Path.home())) / "ArchHub" / "unified-authority")
    generation = (base / "CURRENT").read_text(encoding="ascii").strip()
    manifest = json.loads((base / "generations" / generation / "bootstrap.json").read_text(
        encoding="utf-8"))
    if manifest.get("graph_id") != generation:
        raise InvalidCell("the selected authority generation is inconsistent")
    return CanonicalInstance(manifest["graph_id"], manifest["key_id"], int(manifest["key_version"]),
                             manifest["key_fingerprint"])


def _default_graph_context():
    import urllib.error
    import urllib.request

    from .cell_secret_keys import WindowsDpapiSigningKeyProvider
    from .runtime_caller_capability import WindowsDpapiCallerKeyStore

    endpoint = os.environ.get("ARCHHUB_COORDINATION_ENDPOINT", "").strip() or COORDINATION_ENDPOINT

    def transport(payload, timeout=5.0):
        http = urllib.request.Request(endpoint, data=json.dumps(payload).encode("utf-8"),
                                      headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(http, timeout=timeout) as response:
                return json.loads(response.read(1 << 20).decode("utf-8"))
        except urllib.error.HTTPError as exc:
            # The owner answers a refusal with an HTTP status and its reason in a
            # JSON body ({"ok": false, "error": ...}): that is an answer, and the
            # reason is what the window must show. Only a status without such a
            # body (another server, a proxy) is an owner that is not answering.
            with exc:
                try:
                    answer = json.loads(exc.read(1 << 20).decode("utf-8"))
                except (OSError, ValueError):
                    answer = None
            if type(answer) is dict and answer.get("ok") is False:
                return answer
            raise
    return {
        "transport": transport,
        "settings_transport": lambda payload: transport(payload, SETTINGS_TIMEOUT_SECONDS),
        "key_store": WindowsDpapiCallerKeyStore(WindowsDpapiCallerKeyStore.default_path()),
        "provider": WindowsDpapiSigningKeyProvider(WindowsDpapiSigningKeyProvider.default_path()),
        "instance": canonical_instance(),
    }


# The one seam: where this process reaches the graph's owner. No fallback.
graph_context = _default_graph_context


def forward_workspace_settings(body) -> dict:
    """Settings -> Workspaces from a process that does not own the graph (the
    desktop's application server): the request goes to the graph's owner, signed
    with the settings key, and the owner answers it with the same function its
    own canvas route uses. Nothing is decided here."""
    from .clean_coordination_host import CoordinationIdentity, sign_coordination_request
    if type(body) is not dict:
        raise WorkspaceRootRefused("workspace-roots request is invalid")
    try:
        context = graph_context()
        request = sign_coordination_request(
            context["key_store"], CoordinationIdentity(*SETTINGS_IDENTITY),
            "workspace_roots_settings", {"body": body})
        answer = (context.get("settings_transport") or context["transport"])(request.to_payload())
    except InvalidCell:
        raise
    except Exception as exc:  # noqa: BLE001 - the owner is not reachable
        raise WorkspaceRootRefused(
            "the ArchHub graph owner is not answering (%s); start ArchHub's graph service"
            % type(exc).__name__) from exc
    if type(answer) is not dict or answer.get("ok") is not True:
        error = answer.get("error") if type(answer) is dict else None
        raise WorkspaceRootRefused(str(error or "the graph owner refused the workspace-roots request"))
    return {key: value for key, value in answer.items() if key != "ok"}


NO_WINDOW = "Open the ArchHub window to approve this change"


def _reflects(request, body) -> bool:
    """The snapshot the owner prepared is this request's outcome (checked before the
    owner is asked to approve it)."""
    if type(body) is not dict or type(body.get("roots")) is not list:
        return False
    active = {entry.get("id"): entry for entry in body["roots"] if type(entry) is dict}
    if request["action"] == "register":
        entry = active.get(request.get("id"))
        return (entry is not None
                and str(PureWindowsPath(entry.get("path", ""))).casefold()
                == str(PureWindowsPath(str(request.get("path", "")))).casefold())
    if request["action"] == "unregister":
        return request.get("id") not in active
    return True


def approve_in_this_window(body, *, window_handle, forward=None, signer_factory=None) -> dict:
    """Settings -> Workspaces Add/Remove/Republish from the desktop: the graph's
    owner prepares the exact snapshot, THIS process signs it with the owner's
    protected key (the Windows prompt is shown in front of `window_handle`), and the
    owner verifies that signature before it commits. No window, no signature."""
    from .workspace_roots_signing import CngSigner, SigningUnavailable
    forward = forward or forward_workspace_settings
    if type(body) is not dict or body.get("action") not in _CHANGES or "signature" in body:
        return forward(body)
    if not window_handle:
        raise WorkspaceRootRefused(NO_WINDOW)
    if signer_factory is None:
        def signer_factory(pinned):
            return CngSigner(KEY_NAME, protect=True, pinned_fingerprint=pinned,
                             window_handle=window_handle)
    change = {key: value for key, value in body.items() if key != "command_id"}
    try:
        prepared = forward({"action": "prepare", "change": change}).get("prepared") or {}
        if prepared.get("needs_key"):
            signer_factory(None).sign(KEY_CHECK)  # creates the key: the owner prompt
            prepared = forward({"action": "prepare", "change": change}).get("prepared") or {}
        pin, snapshot = prepared.get("pin"), prepared.get("body")
        if (type(pin) is not str or not _FINGERPRINT.match(pin) or type(snapshot) is not dict
                or snapshot.get("key_fingerprint") != pin or not _reflects(change, snapshot)):
            raise WorkspaceRootRefused("the graph owner prepared a different change; nothing was signed")
        signature = signer_factory(pin).sign(canonical(snapshot))
    except SigningUnavailable as exc:
        raise WorkspaceRootRefused("the owner did not approve: " + str(exc)) from exc
    return forward({**body, "signature": signature})


def verified_graph_state() -> dict:
    """Ask the canonical instance, with a fresh nonce, for its current registry
    digest; accept only a statement it signed for exactly this request."""
    import secrets

    from .clean_coordination_host import CoordinationIdentity, sign_coordination_request

    context = graph_context()
    instance = context["instance"]
    nonce = secrets.token_hex(16)
    request = sign_coordination_request(context["key_store"], CoordinationIdentity(*ISSUER_IDENTITY),
                                        "workspace_roots_state", {"nonce": nonce})
    answer = context["transport"](request.to_payload())
    if type(answer) is not dict or answer.get("ok") is not True:
        raise InvalidCell("the graph's owner refused the workspace-roots state")
    statement, signature = answer.get("statement"), answer.get("signature")
    if (type(statement) is not dict or set(statement) != _STATEMENT_FIELDS
            or type(signature) is not str
            or statement["purpose"] != STATE_PURPOSE
            or statement["graph_id"] != instance.graph_id
            or statement["request_id"] != request.request_id
            or statement["nonce"] != nonce
            or type(statement["revision"]) is not int
            or type(statement["registry_digest"]) is not str):
        raise InvalidCell("the workspace-roots state is not this instance's answer to this request")
    provider = context["provider"]
    if (provider.key_fingerprint(instance.key_id, instance.key_version) != instance.key_fingerprint
            or not provider.verify(instance.key_id, instance.key_version, canonical(statement),
                                   signature)):
        raise InvalidCell("the workspace-roots state is not signed by the canonical instance")
    return statement


def _require_graph_current(signed):
    """The signed files must be the graph's CURRENT projection: a root the graph
    revoked is refused even while stale files still verify. Unavailable = refused."""
    try:
        statement = verified_graph_state()
    except InvalidCell as exc:
        raise InvalidCell("the graph's current workspace-roots state is unavailable: %s" % exc) from exc
    except Exception as exc:  # noqa: BLE001 - doubt is a refusal
        raise InvalidCell("the graph's current workspace-roots state is unavailable") from exc
    if statement["registry_digest"] != registry_digest(signed):
        raise InvalidCell("the workspace-roots registry is not the graph's current projection")


def normalized_picked_folder(chosen) -> str:
    """A dialog's answer as a Windows folder path; "" when he cancelled."""
    chosen = str(chosen or "").strip()
    if not chosen:
        return ""
    chosen = str(PureWindowsPath(chosen))
    if not _local_folder_path(chosen):
        raise WorkspaceRootRefused("the chosen folder is not a local folder path")
    return chosen


def default_last_good_path() -> Path:
    """The hooks' last-good copy: the newest snapshot they verified."""
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "ArchHub" / "governance" / "workspace-roots.last-good.json"


def _refuse_rollback(signed, blob, verifier, last_good_path=None):
    """A snapshot older than the hooks' last-good copy is a replay: refused. The
    last-good copy must itself verify under the same captured blob, or nothing is
    admitted; an absent copy compares with nothing (first registration)."""
    target = Path(last_good_path or default_last_good_path())
    try:
        raw = target.read_bytes()
    except FileNotFoundError:
        return
    except OSError as exc:
        raise InvalidCell("the workspace-roots last-good copy is unreadable") from exc
    try:
        kept = json.loads(raw.decode("utf-8"))
        kept_signed = {key: value for key, value in kept.items() if key != "signature"}
        verified = (type(kept.get("signature")) is str
                    and kept_signed.get("key_fingerprint") == signed["key_fingerprint"]
                    and type(kept_signed.get("graph_revision")) is int
                    and verifier.verify_blob(blob, KEY_ID, 1, canonical(kept_signed),
                                             kept["signature"]))
    except Exception:  # noqa: BLE001 - doubt is a refusal
        verified = False
    if not verified:
        raise InvalidCell("the workspace-roots last-good copy does not verify")
    if type(signed.get("graph_revision")) is not int or signed["graph_revision"] < kept_signed["graph_revision"]:
        raise InvalidCell("the workspace-roots registry is older than its last-good copy (replay)")


def root_bound_admission(path, *, runtime=None, verifier=None, snapshot_path=None,
                         pin_path=None, last_good_path=None):
    """(container id, registration digest); see root_bound_registration."""
    container_id, digest, _entry = root_bound_registration(
        path, runtime=runtime, verifier=verifier, snapshot_path=snapshot_path,
        pin_path=pin_path, last_good_path=last_good_path)
    return container_id, digest


def root_bound_registration(path, *, runtime=None, verifier=None, snapshot_path=None,
                            pin_path=None, last_good_path=None):
    """("workspace-root:<id>", digest) for a write path inside a registered root.

    path is "workspace-roots/<id>/<path inside the root>". The root must be in the
    verified registry, its folder must still be the registered folder (identity),
    and a given runtime must be one of its writers. The digest binds the permit to
    this exact registration and key, so a changed root voids a pending permit."""
    parts = str(path).split("/")
    if (len(parts) < 3 or parts[0] + "/" != ROOT_PATH_PREFIX or not _ID.match(parts[1])
            or any(part in ("", ".", "..") for part in parts[2:])):
        raise InvalidCell("workspace-root write path is invalid")
    roots, pin = read_registered_roots(verifier, snapshot_path=snapshot_path,
                                       pin_path=pin_path, last_good_path=last_good_path)
    entry = roots.get(parts[1])
    if entry is None:
        raise InvalidCell("%s is not a registered workspace root" % parts[1])
    identity = folder_identity(entry.get("path"))
    if identity is None or list(identity) != entry.get("identity"):
        raise InvalidCell("registered workspace root %s is unavailable (moved, swapped "
                          "or missing)" % parts[1])
    if runtime is not None and runtime not in (entry.get("writers") or ()):
        raise InvalidCell("%s is not a writer of workspace root %s" % (runtime, parts[1]))
    digest = hashlib.sha256(canonical({"root": entry, "key": pin})).hexdigest()
    return "workspace-root:" + parts[1], digest, dict(entry)


def roots_view(revision, roots, pin, status, *, built_in=None) -> dict:
    return {
        "revision": revision,
        "built_in": {"id": "archhub", "path": built_in or built_in_path(), "removable": False},
        "roots": [
            {key: root[key] for key in ("root_id", "path", "privacy", "profile",
                                        "writers", "state", "registered_at")}
            for root in roots
        ],
        "key_pinned": pin is not None,
        "projection": status,
        "promise": PROMISE,
    }


__all__ = [
    "PROMISE",
    "WorkspaceRootCatalogue",
    "WorkspaceRootRefused",
    "admit_folder",
    "boot_check",
    "find_workspace_root_catalogue",
    "install_workspace_root_catalogue",
    "owner_change",
    "pin_signing_key",
    "current_registry_statement",
    "read_registered_roots",
    "registry_digest",
    "root_bound_registration",
    "verified_graph_state",
    "read_state",
    "register_root",
    "root_bound_admission",
    "roots_view",
    "sequence",
    "snapshot_body",
    "unregister_root",
    "verify_projection",
]
