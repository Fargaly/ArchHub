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
BUILT_IN_PATH = str(PureWindowsPath("C:/Users/fargaly/00.ARCHUB"))
SNAPSHOT_FORMAT = "archhub.workspace-roots"
SNAPSHOT_VERSION = 2
PIN_FORMAT = "archhub.workspace-roots-pin"
KEY_NAME = "ArchHub-workspace-roots-v1"
KEY_ID = "cng:" + KEY_NAME
MAX_ROOTS = 64
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


def admit_folder(path, root_id, privacy, profile, writers, roots):
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
    if _nests(path, BUILT_IN_PATH) or any(_nests(path, root["path"]) for root in active):
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


def snapshot_body(roots, pin) -> dict:
    """The hooks' view of the graph: registered roots only, ordered by id. The
    order is canonical, so the body signed before a commit (from a prediction)
    equals the body re-derived from the graph after it."""
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


def owner_change(authority, catalogue, request, *, caller, operation_id, lock,
                 signer_factory=None, fingerprint_of=None, verifier=None,
                 snapshot_path=None, pin_path=None) -> dict:
    """List, register, unregister or republish, with the owner's key as the approval.

    The snapshot a change will produce is signed BEFORE anything commits: the
    Windows owner prompt is the approval, so a request the owner did not make
    (any local process can reach a loopback route) changes nothing when it is
    declined. Signing happens outside `lock`; the graph is re-read under it and
    the change is refused if it moved meanwhile.
    """
    from .workspace_roots_signing import CngSigner, CngVerifier, SigningUnavailable

    if type(request) is not dict or request.get("action") not in _FIELDS:
        raise WorkspaceRootRefused(
            "workspace-roots action must be list, register, unregister or republish")
    action = request["action"]
    if set(request) - _FIELDS[action] or (action == "unregister" and "id" not in request):
        raise WorkspaceRootRefused("unexpected workspace-roots fields")
    if signer_factory is None:
        def signer_factory(pinned):
            return CngSigner(KEY_NAME, protect=True, pinned_fingerprint=pinned)
    if fingerprint_of is None:
        def fingerprint_of():
            return CngVerifier(KEY_NAME).public_fingerprint()
    verifier = verifier or CngVerifier(KEY_NAME)
    paths = {"snapshot_path": snapshot_path, "pin_path": pin_path}
    with lock:
        revision, roots, pin = read_state(authority, catalogue, caller=caller)
        if action == "list":
            status = verify_projection(snapshot_body(roots, pin), verifier, **paths)
            return roots_view(revision, roots, pin, status)
        values = None
        if action == "register":
            values = admit_folder(request.get("path"), request.get("id"),
                                  request.get("privacy"), request.get("profile", "client"),
                                  request.get("writers") or ["claude"], roots)
        predicted = _predict(roots, action, values, request.get("id"))
    try:
        new_pin = pin
        if new_pin is None:
            if action == "republish":
                raise WorkspaceRootRefused("nothing is registered yet")
            signer_factory(None).sign(b"archhub workspace-roots key check")
            new_pin = fingerprint_of()
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
                      verify_projection(body, verifier, **paths))


def roots_view(revision, roots, pin, status) -> dict:
    return {
        "revision": revision,
        "built_in": {"id": "archhub", "path": BUILT_IN_PATH, "removable": False},
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
    "read_state",
    "register_root",
    "roots_view",
    "sequence",
    "snapshot_body",
    "unregister_root",
    "verify_projection",
]
