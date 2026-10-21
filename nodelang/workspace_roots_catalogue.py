"""Workspace roots: the owner's registered folders, held in the one graph.

A root is an instance of the published "Workspace root" definition inside the
"Governance" composition, created and revised only through the signed authority
commands (instantiate_definition, revise_instance). Unregistering moves its state
to "unregistered"; no file is ever touched and the history stays in the graph.

The signing key's identity is graph-authoritative: the first registration records
the SHA-256 of the key's public half as the one "Workspace roots signing key"
instance, and later writes sign the projected snapshot before it commits. The
default writer is an app-held ECDSA P-256 key stored DPAPI current-user under
ArchHub's app state; its public half is pinned beside the registry so verifiers
never open a private key.

Legacy registries signed by the old CNG key remain valid because the pin carries
the public blob needed to verify them. The next app write signs with the DPAPI key
and updates the graph pin; it never opens the old CNG key.

Limits (stated, not hidden):
* Before the first registration nothing is pinned: a same-user process could
  replace the app key then. Once pinned, a substitute key is refused.
* Only the state of a root is revised here. Other values are fixed at
  registration because no path in this module or its route revises them; the
  definition itself does not forbid it.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
import os
from pathlib import Path, PureWindowsPath
import re
import secrets
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
    read_definition,
    revise_definition,
    revise_instance,
)
from .universal_cell import InvalidCell


ROOT_DEFINITION = "Workspace root"
KEY_DEFINITION = "Workspace roots signing key"
COMPOSITION = "Governance"
PRIVACY = ("private", "public")
PROFILES = ("client",)
OPEN_AGENT_RUNTIMES = (
    "claude",
    "codex",
    "gemini",
    "opencode",
    "antigravity",
    "cursor",
    "windsurf",
    "zed",
    "aider",
)
RUNTIMES = OPEN_AGENT_RUNTIMES


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
APP_KEY_ID = "app:ArchHub-workspace-roots-v1"
OWNER_OPENED = "owner-opened"
APP_WRITTEN = "app-written"
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
            "writers": list(OPEN_AGENT_RUNTIMES),
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
        # The pin cell IS the enrollment record: beyond the key identity it carries an
        # explicit enrollment attestation -- the mode (owner-opened), who admitted it, when
        # -- so a first-use trust is attributable and visible in Settings, never silent.
        {"key_id": KEY_ID, "fingerprint": "",
         "mode": "", "enrolled_by": "", "enrolled_at": ""},
        parameters={
            "key_id": {"type": "text"},
            "fingerprint": {"type": "text"},
            "mode": {"type": "text"},
            "enrolled_by": {"type": "text"},
            "enrolled_at": {"type": "text"},
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


def _enrolling_actor(caller) -> str:
    """A bounded, non-secret label for who admitted the first-use trust, best-effort."""
    for attr in ("actor", "identity", "name", "agent_session", "principal"):
        value = getattr(caller, attr, None)
        if isinstance(value, str) and value.strip():
            return value.strip()[:256]
    return "approving-window"


def _key_record(authority, catalogue, *, caller):
    governance = _governance(authority, caller)
    projection = read_contained_scope(
        authority, governance, scope_root=governance, caller=caller
    )
    pins = []
    for instance_root, instance in projection.instances.items():
        if instance.get("definition") == catalogue.key_definition:
            pins.append({"instance": instance_root, **dict(instance.get("values") or {})})
    if len(pins) > 1:
        raise InvalidCell("the graph holds more than one workspace-roots signing key")
    if not pins:
        return None
    pin = pins[0]
    if (pin.get("key_id") not in (KEY_ID, APP_KEY_ID)
            or not _FINGERPRINT.match(str(pin.get("fingerprint")))):
        raise InvalidCell("the pinned workspace-roots signing key record is invalid")
    return pin


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
            pins.append({"instance": instance_root, **dict(values)})
    if len(pins) > 1:
        raise InvalidCell("the graph holds more than one workspace-roots signing key")
    pin = None
    if pins:
        pin = pins[0]
        if (pin.get("key_id") not in (KEY_ID, APP_KEY_ID)
                or not _FINGERPRINT.match(str(pin.get("fingerprint")))):
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


def root_id_from_name(name, path, roots):
    """A valid, unused root id derived from what the user typed (or the folder name).

    Founder 2026-10-12: typing "BBC4" for E:\\01.PERSONAL\\BBC4 must register, not refuse.
    """
    raw = name if type(name) is str and name.strip() else PureWindowsPath(str(path or "")).name
    slug = re.sub(r"[^a-z0-9]+", "-", str(raw).strip().lower()).strip("-")[:63].strip("-")
    if not slug:
        slug = "workspace"
    if slug == "archhub":
        slug = "archhub-workspace"
    used = {root.get("root_id") for root in roots or []}
    candidate, n = slug, 2
    while candidate in used:
        suffix = "-%d" % n
        candidate = slug[:63 - len(suffix)].strip("-") + suffix
        n += 1
    return candidate


def _normalize_writers(writers):
    if type(writers) not in (list, tuple):
        raise WorkspaceRootRefused(
            "workspace root writers are invalid; choose agents in Settings > Workspaces")
    normalized = []
    for writer in writers:
        if type(writer) is not str:
            raise WorkspaceRootRefused(
                "workspace root writers are invalid; choose agents in Settings > Workspaces")
        value = writer.strip().lower()
        if value not in RUNTIMES:
            raise WorkspaceRootRefused(
                "workspace root writer '%s' is unknown; choose agents in Settings > Workspaces"
                % writer)
        if value in normalized:
            raise WorkspaceRootRefused(
                "workspace root writers are duplicated; turn each agent on only once")
        normalized.append(value)
    return normalized


def admit_folder(path, root_id, privacy, profile, writers, roots, *, built_in=None):
    """The registration values, or WorkspaceRootRefused for anything the hooks refuse."""
    if type(root_id) is not str or not _ID.match(root_id) or root_id == "archhub":
        root_id = root_id_from_name(root_id, path, roots)
    if privacy not in PRIVACY or profile not in PROFILES:
        raise WorkspaceRootRefused("workspace root privacy is invalid; choose Private or Public")
    writers = _normalize_writers(writers)
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
        "writers": writers,
        "identity": list(identity),
        "state": "registered",
        "registered_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


_ENROLLMENT_PARAMETERS = {
    "mode": {"type": "text"},
    "enrolled_by": {"type": "text"},
    "enrolled_at": {"type": "text"},
}
_ENROLLMENT_DEFAULTS = {"mode": "", "enrolled_by": "", "enrolled_at": ""}


def _ensure_enrollment_schema(authority, catalogue, *, caller, operation_id):
    """Make the published key definition declare the enrollment attestation
    before the FIRST pin, if an old graph retained a definition that predates it.

    On the founder's live graph _publish kept the old two-field key definition
    (key_id + fingerprint), so writing the full record would be an
    undeclared-parameter override. Rather than drop the attestation to "legacy",
    revise the definition through the product's own revision path so it DECLARES
    mode/enrolled_by/enrolled_at -- the key identity (key_id, fingerprint) is
    unchanged -- then the pin records the real owner-opened attestation. A
    definition that already declares the fields is left untouched.
    """
    current = read_definition(authority, catalogue.key_definition, caller=caller)
    if (set(_ENROLLMENT_PARAMETERS) <= set(current.contracts["parameters"])
            and current.lifecycle == "published"):
        return  # already migrated AND published -- nothing to do
    # Recoverable migration. The three steps carry STABLE, per-definition command
    # identities, so a retry after an interrupted or refused promotion re-issues the
    # EXACT same commands: the authority settles each already-done step from its own
    # receipt (idempotent, returning that receipt) and performs only the step that
    # never committed, driving the one held revision WIP -> shared -> published
    # through the same authority. No forked revision, no duplicate, no blind
    # re-revise -- the command identity makes a repeat the same act, not a new one.
    # The spec is rebuilt from `current`, which has already converged to the merged
    # contracts after the first revise, so every repeat hashes identically.
    seed = str(uuid.uuid5(
        uuid.NAMESPACE_URL,
        "archhub.workspace-roots.enrollment-schema:" + catalogue.key_definition))
    base = current.version
    for suffix in ("-enrollment-published", "-enrollment-shared", "-enrollment"):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
            break
    revised = revise_definition(
        authority,
        catalogue.key_definition,
        current.name,
        {**dict(current.contracts["defaults"]), **_ENROLLMENT_DEFAULTS},
        caller=caller,
        command_id=_subcommand(seed, "schema:revise"),
        version=base + "-enrollment",
        lifecycle="wip",
        parameters={**dict(current.contracts["parameters"]), **_ENROLLMENT_PARAMETERS},
        interfaces=dict(current.contracts["interfaces"]),
        rules=dict(current.contracts["rules"]),
        presentation=dict(current.contracts["presentation"]),
        courts=dict(current.contracts["courts"]),
        provenance=dict(current.contracts["provenance"]),
    )
    shared = promote_definition(
        authority,
        catalogue.key_definition,
        target_lifecycle="shared",
        version=base + "-enrollment-shared",
        evidence_roots=(revised.receipt_root,),
        caller=caller,
        command_id=_subcommand(seed, "schema:share"),
    )
    promote_definition(
        authority,
        catalogue.key_definition,
        target_lifecycle="published",
        version=base + "-enrollment-published",
        evidence_roots=(shared.receipt_root,),
        caller=caller,
        command_id=_subcommand(seed, "schema:publish"),
    )


def pin_signing_key(authority, catalogue, fingerprint, *, caller, operation_id,
                    mode=OWNER_OPENED, enrolled_by="", enrolled_at="",
                    key_id=KEY_ID, allow_repin=False):
    """Record the key's fingerprint once, with its enrollment attestation.

    The pin is written exactly once (a different fingerprint is refused), and it
    carries the explicit record of how the key was enrolled -- the mode (here
    "owner-opened": the window opened the owner-protected key once, non-silently,
    so the Windows prompt was the owner's consent), who admitted it and when -- so
    the enrollment is attributable and surfaced in Settings, never silent.
    """
    if type(fingerprint) is not str or not _FINGERPRINT.match(fingerprint):
        raise InvalidCell("workspace-roots key fingerprint is invalid")
    if key_id not in (KEY_ID, APP_KEY_ID):
        raise InvalidCell("workspace-roots key id is invalid; use the app Settings writer")
    existing = _key_record(authority, catalogue, caller=caller)
    if existing is not None:
        if existing["fingerprint"] != fingerprint and not allow_repin:
            raise InvalidCell("a different workspace-roots signing key is already pinned")
        if existing["fingerprint"] != fingerprint or existing.get("key_id") != key_id:
            _ensure_enrollment_schema(authority, catalogue, caller=caller, operation_id=operation_id)
            revise_instance(
                authority,
                existing["instance"],
                {"key_id": key_id, "fingerprint": fingerprint,
                 "mode": str(mode or APP_WRITTEN),
                 "enrolled_by": str(enrolled_by or ""),
                 "enrolled_at": str(enrolled_at or "")},
                scope_root=_governance(authority, caller),
                caller=caller,
                command_id=_subcommand(operation_id, "repin"),
            )
        return existing["fingerprint"]
    # First pin: on an old graph the retained key definition may not yet declare
    # the enrollment attestation; make it declare them (key identity unchanged)
    # so the record below is not an undeclared-parameter override.
    _ensure_enrollment_schema(authority, catalogue, caller=caller, operation_id=operation_id)
    instantiate_definition(
        authority,
        catalogue.key_definition,
        {"key_id": key_id, "fingerprint": fingerprint,
         "mode": str(mode or OWNER_OPENED),
         "enrolled_by": str(enrolled_by or ""),
         "enrolled_at": str(enrolled_at or "")},
        scope_root=_governance(authority, caller),
        caller=caller,
        command_id=_subcommand(operation_id, "pin"),
    )
    return fingerprint


def read_enrollment(authority, catalogue, *, caller):
    """The pinned key's enrollment record: {fingerprint, mode, enrolled_by, enrolled_at}.

    None when nothing is pinned. A pin written before this record existed reads back
    with mode 'legacy' and empty actor/time -- still visible, just not attributed.
    """
    governance = _governance(authority, caller)
    projection = read_contained_scope(
        authority, governance, scope_root=governance, caller=caller)
    for _instance_root, instance in projection.instances.items():
        if instance.get("definition") != catalogue.key_definition:
            continue
        values = dict(instance.get("values") or {})
        fingerprint = values.get("fingerprint")
        if not (type(fingerprint) is str and _FINGERPRINT.match(fingerprint)):
            continue
        mode = values.get("mode") or "legacy"
        return {"fingerprint": fingerprint, "mode": mode,
                "enrolled_by": values.get("enrolled_by") or "",
                "enrolled_at": values.get("enrolled_at") or ""}
    return None


def update_root_writers(authority, catalogue, root_id, writers, *, caller, operation_id):
    """Change who can write inside one registered workspace root."""
    _revision, roots, _pin = read_state(authority, catalogue, caller=caller)
    matches = [root for root in roots if root.get("root_id") == root_id]
    if len(matches) != 1:
        raise WorkspaceRootRefused("no such workspace root; register it in Settings > Workspaces")
    if matches[0].get("state") == "unregistered":
        raise WorkspaceRootRefused("that workspace root is removed; add it again in Settings > Workspaces")
    normalized = _normalize_writers(writers)
    return revise_instance(
        authority,
        matches[0]["instance"],
        {"writers": normalized},
        scope_root=_governance(authority, caller),
        caller=caller,
        command_id=_subcommand(operation_id, "writers"),
    )


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


def snapshot_body(roots, pin, *, key_id=KEY_ID) -> dict:
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
        "key_id": key_id,
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


def public_blob_of(text) -> bytes:
    """The offered public half: an ECCPUBLICBLOB for ECDSA P-256 (BCRYPT_ECDSA_PUBLIC_P256_MAGIC,
    32-byte coordinates), as hex. Anything else is refused before it is hashed or pinned."""
    try:
        blob = bytes.fromhex(text) if type(text) is str else b""
    except ValueError:
        blob = b""
    if len(blob) != 72 or blob[:8] != b"ECS1" + (32).to_bytes(4, "little"):
        raise WorkspaceRootRefused("the offered workspace-roots key is not an ECDSA P-256 public key")
    return blob


def _ecdsa_verify_blob(blob, payload, signature) -> bool:
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
        blob = bytes(blob)
        raw = bytes.fromhex(signature)
        if len(blob) != 72 or blob[:8] != b"ECS1" + (32).to_bytes(4, "little") or len(raw) != 64:
            return False
        x = int.from_bytes(blob[8:40], "big")
        y = int.from_bytes(blob[40:72], "big")
        key = ec.EllipticCurvePublicNumbers(x, y, ec.SECP256R1()).public_key()
        key.verify(encode_dss_signature(int.from_bytes(raw[:32], "big"),
                                        int.from_bytes(raw[32:], "big")),
                   payload, ec.ECDSA(hashes.SHA256()))
        return True
    except Exception:  # noqa: BLE001 - malformed keys/signatures are simply refused
        return False


def _verify_blob(key_id, blob, version, payload, signature, verifier) -> bool:
    if key_id in (KEY_ID, APP_KEY_ID):
        return version == 1 and _ecdsa_verify_blob(blob, payload, signature)
    return verifier.verify_blob(blob, key_id, version, payload, signature)


def default_app_key_path(snapshot_path=None) -> Path:
    if snapshot_path is not None:
        return Path(snapshot_path).with_name("workspace-roots.app-key.dpapi")
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "ArchHub" / "governance" / "workspace-roots.app-key.dpapi"


_APP_KEY_PURPOSE = "archhub:workspace-roots:app-signing-key"


class AppWorkspaceRootSigner:
    """Local app-owned ECDSA key for Settings writes; no Windows UI policy.

    Custody (AGENTS T3, Ping review 2026-10-12): the private key is never written in the
    clear. It is stored DPAPI-protected for this Windows user with purpose separation; the
    public blob sits beside it so verification never opens the private key. A plaintext
    key left by an earlier build is migrated into protected custody and removed.
    """

    def __init__(self, key_path=None):
        self.key_path = Path(key_path or default_app_key_path())
        self.public_path = self.key_path.with_suffix(".pub")

    def _store(self, key):
        from cryptography.hazmat.primitives import serialization
        from .cell_secret_keys import protect_current_user_data
        der = key.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption())
        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(self.key_path, protect_current_user_data(der, purpose=_APP_KEY_PURPOSE))
        _atomic_write(self.public_path, self._public_blob_of(key).hex().encode("ascii"))

    @staticmethod
    def _public_blob_of(key):
        numbers = key.public_key().public_numbers()
        return (b"ECS1" + (32).to_bytes(4, "little")
                + numbers.x.to_bytes(32, "big") + numbers.y.to_bytes(32, "big"))

    def _key(self):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from .cell_secret_keys import unprotect_current_user_data
        try:
            der = unprotect_current_user_data(self.key_path.read_bytes(), purpose=_APP_KEY_PURPOSE)
            return serialization.load_der_private_key(der, password=None)
        except FileNotFoundError:
            pass
        legacy = self.key_path.with_name("workspace-roots.app-key.pem")
        if legacy.exists():
            key = serialization.load_pem_private_key(legacy.read_bytes(), password=None)
            self._store(key)
            legacy.unlink()
            return key
        key = ec.generate_private_key(ec.SECP256R1())
        self._store(key)
        return key

    def public_blob(self):
        try:
            return bytes.fromhex(self.public_path.read_text(encoding="ascii").strip())
        except (FileNotFoundError, ValueError):
            return self._public_blob_of(self._key())

    def sign(self, payload):
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
        r, s = decode_dss_signature(self._key().sign(payload, ec.ECDSA(hashes.SHA256())))
        return (r.to_bytes(32, "big") + s.to_bytes(32, "big")).hex()


class AppWorkspaceRootVerifier:
    def __init__(self, key_path=None):
        self.signer = AppWorkspaceRootSigner(key_path)

    def public_blob(self):
        return self.signer.public_blob()

    def verify_blob(self, blob, key_id, version, payload, signature):
        return _verify_blob(key_id, blob, version, payload, signature, self)


def app_signing_components(*, snapshot_path=None):
    key_path = default_app_key_path(snapshot_path)

    def factory(_pinned):
        return AppWorkspaceRootSigner(key_path)

    def fingerprint():
        return hashlib.sha256(AppWorkspaceRootSigner(key_path).public_blob()).hexdigest()

    return factory, fingerprint, AppWorkspaceRootVerifier(key_path)


def pin_document(blob, *, key_id=KEY_ID) -> dict:
    """The hooks' trusted identity: the fingerprint AND the public half it hashes, so no
    reader ever opens the key store (a protected key cannot be opened silently)."""
    blob = bytes(blob)
    return {"format": PIN_FORMAT, "key_id": key_id,
            "fingerprint": hashlib.sha256(blob).hexdigest(), "public_blob": blob.hex()}


def read_pin(pin_path=None):
    """(fingerprint, blob) from the pin file, or None when it is absent or not exactly
    a pin whose blob hashes to its fingerprint."""
    try:
        pin = json.loads(Path(pin_path or default_pin_path()).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if (type(pin) is not dict or set(pin) != {"format", "key_id", "fingerprint", "public_blob"}
            or pin["format"] != PIN_FORMAT or pin["key_id"] not in (KEY_ID, APP_KEY_ID)
            or type(pin["fingerprint"]) is not str or not _FINGERPRINT.match(pin["fingerprint"])):
        return None
    try:
        blob = public_blob_of(pin["public_blob"])
    except WorkspaceRootRefused:
        return None
    if hashlib.sha256(blob).hexdigest() != pin["fingerprint"]:
        return None
    return pin["fingerprint"], blob


def write_projection(body: dict, signature: str, blob, *, snapshot_path=None, pin_path=None) -> None:
    """The pin first (the hooks' trusted identity, with its public half), then the signed
    snapshot. The pin's blob must be the key the snapshot names."""
    if hashlib.sha256(bytes(blob)).hexdigest() != body["key_fingerprint"]:
        raise InvalidCell("the projected pin is not the key the snapshot names")
    _atomic_write(Path(pin_path or default_pin_path()),
                  canonical(pin_document(blob, key_id=body.get("key_id", KEY_ID))))
    _atomic_write(Path(snapshot_path or default_snapshot_path()),
                  canonical({**body, "signature": signature}))


def verify_projection(body: dict, verifier, *, snapshot_path=None, pin_path=None) -> str:
    """"match", "missing", "unsigned", "unpinned" or "mismatch": do the hooks' files
    project this graph state? Anything but "match" (or "missing" before the first
    registration) is shown as a banner and refuses owner changes until republished.
    The signature is checked with the pin's own public blob: the key store is never
    opened (verifier.verify_blob is BCrypt only)."""
    snapshot_path = snapshot_path or default_snapshot_path()
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
    pinned = read_pin(pin_path)
    key_id = signed.get("key_id")
    if (pinned is None or pinned[0] != body["key_fingerprint"]
            or signed.get("key_fingerprint") != pinned[0]
            or key_id != body.get("key_id")
            or key_id not in (KEY_ID, APP_KEY_ID)):
        return "unpinned"
    if not _verify_blob(key_id, pinned[1], 1, canonical(signed),
                        str(document.get("signature", "")), verifier):
        return "unsigned"
    return "match" if signed == body else "mismatch"


def boot_check(authority, catalogue, *, caller, verifier=None, snapshot_path=None,
               pin_path=None) -> str:
    """Re-derive the projection from the graph and compare it with the hooks' files.
    A graph that never published the catalogue holds no roots (catalogue None)."""
    try:
        if catalogue is None:
            roots, pin, key_id = (), None, KEY_ID
        else:
            _revision, roots, pin = read_state(authority, catalogue, caller=caller)
            record = _key_record(authority, catalogue, caller=caller)
            key_id = (record or {}).get("key_id", KEY_ID)
        return verify_projection(snapshot_body(roots, pin, key_id=key_id),
                                 verifier or AppWorkspaceRootVerifier(),
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
    if action == "update-writers":
        matches = [root for root in roots if root.get("root_id") == root_id]
        if len(matches) != 1:
            raise WorkspaceRootRefused("no such workspace root; register it in Settings > Workspaces")
        if matches[0].get("state") == "unregistered":
            raise WorkspaceRootRefused("that workspace root is removed; add it again in Settings > Workspaces")
        return tuple({**root, "writers": list(values)} if root is matches[0] else root
                     for root in roots)
    return tuple(roots)


def _comparable(roots):
    return [{key: value for key, value in root.items() if key != "instance"} for root in roots]


_FIELDS = {
    "list": {"action"},
    "republish": {"action"},
    "unregister": {"action", "id"},
    "register": {"action", "id", "path", "privacy", "profile", "writers"},
    "update-writers": {"action", "id", "writers"},
}
# A change approved in another (visible) process: "prepare" returns the exact
# snapshot that change would produce; the change then carries "signature".
_CHANGES = ("register", "unregister", "republish", "update-writers")
KEY_CHECK = b"archhub workspace-roots key check"


def _offered_key(request, pin, verifier):
    """(blob, fingerprint, proven) for the public half the approving window offers.

    The owner never opens the key (a protected key cannot be opened silently): the
    desktop window opened it, checked it is non-exportable and owner-protected, and
    sends its public half. With a pin, that half must BE the pinned key. Before the
    first pin it is accepted only with a KEY_CHECK signature that verifies under it
    (proven=False when none was sent yet: the window is asked for one)."""
    blob = public_blob_of(request.get("public_blob"))
    fingerprint = hashlib.sha256(blob).hexdigest()
    if pin is not None:
        if fingerprint != pin:
            raise WorkspaceRootRefused("the offered workspace-roots signing key is not the pinned key")
        return blob, fingerprint, True
    check = request.get("key_check")
    if check is None:
        return blob, fingerprint, False
    if type(check) is not str or len(check) != 128 or not verifier.verify_blob(
            blob, KEY_ID, 1, KEY_CHECK, check):
        raise WorkspaceRootRefused(
            "the key check does not verify under the offered workspace-roots key; nothing was changed")
    return blob, fingerprint, True


_OFFER = {"public_blob", "key_check"}


def owner_change(authority, catalogue, request, *, caller, operation_id, lock,
                 signer_factory=None, fingerprint_of=None, verifier=None,
                 snapshot_path=None, pin_path=None, built_in=None, admission=None,
                 signing_key_id=KEY_ID, pin_mode=OWNER_OPENED, allow_key_migration=False) -> dict:
    """List, register, unregister or republish, with a signed projection.

    The normal Settings route injects the app DPAPI signer, so a user picks a
    folder and the app signs silently. Legacy prepared requests may still arrive
    with a public blob and signature; those are verified from the carried blob and
    never require opening a private key. Signing happens outside `lock`; the graph
    is re-read under it and the change is refused if it moved meanwhile.
    """
    preparing = type(request) is dict and request.get("action") == "prepare"
    offer = {}
    ticket_in = None
    if type(request) is dict:
        offer = {key: request[key] for key in _OFFER if key in request}
        ticket_in = request.get("admission_ticket")  # owner-signed, carried back at commit
    if preparing:
        # The change the approving process will sign, never committed here.
        if (not {"action", "change"} <= set(request) <= {"action", "change"} | _OFFER
                or type(request["change"]) is not dict):
            raise WorkspaceRootRefused("unexpected workspace-roots fields")
        request = request["change"]
        if (request.get("action") not in _CHANGES or "signature" in request
                or set(request) & _OFFER):
            raise WorkspaceRootRefused("only a change can be prepared for approval")
    elif type(request) is dict:
        request = {key: value for key, value in request.items()
                   if key not in _OFFER and key != "admission_ticket"}
    # The verified SETTINGS principal threaded from the authenticated transport (never
    # a caller-supplied body field). A change prepared or committed WITHOUT it is a
    # direct-to-owner call that skipped the window admission: refuse before any effect.
    principal = admission.get("principal") if isinstance(admission, dict) else None
    requires_admission = (request.get("action") in _CHANGES
                          if type(request) is dict else False) and (preparing or request.get("signature") is not None)
    if requires_admission and (not isinstance(principal, str) or not principal):
        raise WorkspaceRootRefused(
            "the authenticated workspace-roots settings admission is required; "
            "nothing was changed")
    if type(request) is not dict or request.get("action") not in _FIELDS:
        raise WorkspaceRootRefused(
            "workspace-roots action must be list, register, unregister, update-writers or republish")
    action = request["action"]
    approval = request.get("signature")
    allowed = _FIELDS[action] | ({"signature"} if action in _CHANGES else set())
    if (set(request) - allowed or (action == "unregister" and "id" not in request)
            or ("signature" in request and (type(approval) is not str or len(approval) != 128))
            or (offer and action not in _CHANGES)
            or ((preparing or approval is not None) and "public_blob" not in offer)):
        raise WorkspaceRootRefused("unexpected workspace-roots fields")
    if action in _CHANGES and not preparing and approval is None and signer_factory is None:
        # Direct owner calls without the app-injected signer are not Settings writes.
        raise WorkspaceRootRefused(NO_WINDOW)
    verifier = verifier or AppWorkspaceRootVerifier()
    paths = {"snapshot_path": snapshot_path, "pin_path": pin_path}
    with lock:
        revision, roots, pin = read_state(authority, catalogue, caller=caller)
        record = _key_record(authority, catalogue, caller=caller)
        current_key_id = (record or {}).get("key_id", KEY_ID)
        if action == "list":
            status = verify_projection(snapshot_body(roots, pin, key_id=current_key_id),
                                       verifier, **paths)
            return roots_view(revision, roots, pin, status, built_in=built_in,
                              enrollment=read_enrollment(authority, catalogue, caller=caller))
        values = None
        if action == "register":
            writers = request["writers"] if "writers" in request else list(OPEN_AGENT_RUNTIMES)
            values = admit_folder(request.get("path"), request.get("id"),
                                  request.get("privacy"), request.get("profile", "client"),
                                  writers, roots, built_in=built_in)
        elif action == "update-writers":
            values = _normalize_writers(request.get("writers"))
        predicted = _predict(roots, action, values, request.get("id"))
    if pin is None and action == "republish":
        raise WorkspaceRootRefused("nothing is registered yet")
    if preparing or approval is not None:
        # Legacy prepared request: verify only from the offered public blob.
        blob, new_pin, proven = _offered_key(offer, pin, verifier)
        if preparing:
            if not proven:
                return {"prepared": {"needs_key_check": True}}
            prepared = {"body": snapshot_body(predicted, new_pin, key_id=KEY_ID), "pin": new_pin}
            if pin is None:
                # First enrollment: issue the owner's single-use admission bound to the
                # verified principal, this instance, the offered key, the exact change
                # and revision, with an expiry. The window carries it back at commit.
                prepared["admission_ticket"] = mint_first_enrollment_admission(
                    authority, principal=principal, key_fingerprint=new_pin,
                    change_digest=_change_digest(request), revision=revision)
            return {"prepared": prepared}
        if not proven:
            raise WorkspaceRootRefused("the first workspace registration needs the key check; "
                                       "nothing was changed")
        body = snapshot_body(predicted, new_pin, key_id=KEY_ID)
        signature = approval
        if not _verify_blob(KEY_ID, blob, 1, canonical(body), signature, verifier):
            raise WorkspaceRootRefused(
                "the approval does not match this change (the roots may have changed); "
                "nothing was changed")
        if pin is None:
            # First enrollment also requires the owner's own admission ticket, carried
            # back from prepare, verified here BEFORE any effect: a direct call that did
            # not go through the owner-issued, authenticated ceremony is refused even
            # with a valid self-signed key + KEY_CHECK.
            change_core = {key: value for key, value in request.items() if key != "signature"}
            if not verify_first_enrollment_admission(
                    authority, ticket_in, principal=principal, key_fingerprint=new_pin,
                    change_digest=_change_digest(change_core), revision=revision):
                raise WorkspaceRootRefused(
                    "the first workspace enrollment admission is missing, forged, expired or "
                    "does not match this change; nothing was changed")
    else:
        # Courts only (signer_factory + a court verifier that is the key itself):
        # production passes no signer_factory and is refused above (NO_WINDOW).
        try:
            new_pin = pin
            if new_pin is None or signing_key_id == APP_KEY_ID:
                signer_factory(None).sign(KEY_CHECK)
                offered_pin = fingerprint_of() if fingerprint_of is not None else None
                if type(offered_pin) is not str or not _FINGERPRINT.match(offered_pin):
                    raise WorkspaceRootRefused("the signing key fingerprint is unreadable")
                if pin is None or allow_key_migration:
                    new_pin = offered_pin
                elif offered_pin != pin:
                    raise WorkspaceRootRefused("the signing key is not the pinned key")
            blob = bytes(verifier.public_blob())
            if hashlib.sha256(blob).hexdigest() != new_pin:
                raise WorkspaceRootRefused("the signing key is not the pinned key")
            body = snapshot_body(predicted, new_pin, key_id=signing_key_id)
            signature = signer_factory(new_pin).sign(canonical(body))
        except Exception as exc:  # noqa: BLE001 - signer factories normalize refusal here
            raise WorkspaceRootRefused("the owner did not approve: " + str(exc)) from exc
    with lock:
        _now, current, current_pin = read_state(authority, catalogue, caller=caller)
        if _comparable(current) != _comparable(roots) or current_pin != pin:
            raise WorkspaceRootRefused(
                "workspace roots changed while waiting for approval; nothing was changed")
        if pin is None or current_pin != new_pin or current_key_id != signing_key_id:
            # First enrollment: the approving window opened this owner-protected key
            # once, non-silently (the Windows prompt was the owner's consent) and read
            # its public half; record that attestation explicitly -- mode "owner-opened",
            # who admitted it, when -- so it is attributable and shown in Settings.
            # Afterwards _offered_key accepts only this pinned blob, so re-enrollment
            # requires the existing key's verify_blob.
            pin_signing_key(authority, catalogue, new_pin, caller=caller,
                            operation_id=operation_id,
                            key_id=signing_key_id,
                            mode=pin_mode,
                            allow_repin=allow_key_migration,
                            enrolled_by=principal,
                            enrolled_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        if action == "register":
            register_root(authority, catalogue, values, caller=caller,
                          operation_id=operation_id)
        elif action == "unregister":
            unregister_root(authority, catalogue, request["id"], caller=caller,
                            operation_id=operation_id)
        elif action == "update-writers":
            update_root_writers(authority, catalogue, request["id"], values, caller=caller,
                                operation_id=operation_id)
        revision, after, after_pin = read_state(authority, catalogue, caller=caller)
        if snapshot_body(after, after_pin, key_id=signing_key_id) != body:
            raise InvalidCell("the committed workspace roots differ from the approved "
                              "projection; the hooks' files were left unchanged")
        write_projection(body, signature, blob, **paths)
    return roots_view(revision, after, after_pin,
                      verify_projection(body, verifier, **paths), built_in=built_in,
                      enrollment=read_enrollment(authority, catalogue, caller=caller))


ROOT_PATH_PREFIX = "workspace-roots/"


def read_registered_roots(verifier=None, *, snapshot_path=None, pin_path=None,
                          last_good_path=None):
    """(roots by id, pin) from the hooks' projection, or InvalidCell.

    The same trust as the hooks: the pin file names the key and carries its public
    half (which must hash to the pin), and the snapshot must name that fingerprint
    and verify under exactly that blob. The key store is never opened."""
    verifier = verifier or AppWorkspaceRootVerifier()
    try:
        document = json.loads(Path(snapshot_path or default_snapshot_path()).read_text(
            encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise InvalidCell("the workspace-roots registry is unavailable") from exc
    pinned = read_pin(pin_path)
    if pinned is None:
        raise InvalidCell("the workspace-roots signing key is not pinned")
    pin, blob = {"fingerprint": pinned[0]}, pinned[1]
    if type(document) is not dict or type(document.get("signature")) is not str:
        raise InvalidCell("the workspace-roots registry is unsigned")
    signed = {key: value for key, value in document.items() if key != "signature"}
    if (signed.get("format") != SNAPSHOT_FORMAT
            or signed.get("format_version") != SNAPSHOT_VERSION
            or signed.get("key_id") not in (KEY_ID, APP_KEY_ID)
            or signed.get("key_fingerprint") != pin["fingerprint"]
            or type(signed.get("roots")) is not list
            or len(signed["roots"]) > MAX_ROOTS
            or type(signed.get("removed")) is not list
            or len(signed["removed"]) > MAX_REMOVED
            or not _verify_blob(signed.get("key_id"), bytes(blob), 1, canonical(signed),
                                document["signature"], verifier)):
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


FIRST_ENROLLMENT_ADMISSION_PURPOSE = "archhub.workspace-roots.first-enrollment-admission/v1"
# The window ceremony (Add waits for the owner's key prompt) can take a while; the
# admission ticket must outlive the prompt but not persist indefinitely.
ADMISSION_TTL_SECONDS = 900
_ADMISSION_FIELDS = {"purpose", "graph_id", "principal", "key_fingerprint",
                     "change_digest", "revision", "expiry", "nonce"}


def _change_digest(change) -> str:
    """A stable digest of the exact change the admission is bound to."""
    return hashlib.sha256(canonical(
        {"schema": "archhub.workspace-roots.change/v1", "change": change})).hexdigest()


def mint_first_enrollment_admission(authority, *, principal, key_fingerprint,
                                    change_digest, revision, now=None):
    """The owner's own one-time admission for a FIRST enrollment, bound to the verified
    settings principal, this instance, the offered key, the exact change and revision,
    and an expiry. Signed with the owner's authority key -- NO parallel approval key.
    Issued only at prepare; verified and single-used at commit (see owner_change)."""
    now = time.time() if now is None else now
    statement = {
        "purpose": FIRST_ENROLLMENT_ADMISSION_PURPOSE,
        "graph_id": authority.manifest.graph_id,
        "principal": principal,
        "key_fingerprint": key_fingerprint,
        "change_digest": change_digest,
        "revision": revision,
        "expiry": int(now) + ADMISSION_TTL_SECONDS,
        "nonce": secrets.token_hex(16),
    }
    signature = authority.key_provider.sign(
        authority.manifest.key_id, authority.manifest.key_version, canonical(statement))
    return {"statement": statement, "signature": signature}


def verify_first_enrollment_admission(authority, ticket, *, principal, key_fingerprint,
                                      change_digest, revision, now=None):
    """True only for the owner's own live admission bound to exactly these facts. The
    owner re-signs the statement with its authority key and compares (deterministic
    signer), so a forged or foreign ticket is refused; an expired or rebound one too.
    Single-use is enforced by the caller: a first enrollment pins the key once, so a
    replayed ticket afterwards finds the pin set and never re-pins."""
    now = time.time() if now is None else now
    if type(ticket) is not dict or set(ticket) != {"statement", "signature"}:
        return False
    statement = ticket["statement"]
    if (type(statement) is not dict or set(statement) != _ADMISSION_FIELDS
            or statement.get("purpose") != FIRST_ENROLLMENT_ADMISSION_PURPOSE
            or statement.get("graph_id") != authority.manifest.graph_id
            or statement.get("principal") != principal
            or statement.get("key_fingerprint") != key_fingerprint
            or statement.get("change_digest") != change_digest
            or statement.get("revision") != revision
            or type(statement.get("expiry")) is not int or statement["expiry"] < now
            or type(statement.get("nonce")) is not str or not _NONCE.match(statement["nonce"])):
        return False
    expected = authority.key_provider.sign(
        authority.manifest.key_id, authority.manifest.key_version, canonical(statement))
    return hmac.compare_digest(str(expected), str(ticket.get("signature")))


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
    """Settings -> Workspaces Add/Remove/Republish from the desktop.

    The app server owns the silent DPAPI app key and signs direct changes in
    owner_change. This compatibility entry point therefore forwards the request
    unchanged; it never opens the legacy CNG workspace key and never needs a
    Windows credential prompt.
    """
    forward = forward or forward_workspace_settings
    _ = window_handle, signer_factory
    return forward(body)


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
                    and kept_signed.get("key_id") == signed.get("key_id")
                    and _verify_blob(signed.get("key_id"), blob, 1, canonical(kept_signed),
                                     kept["signature"], verifier))
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
    and the registered folder identity must still match. The writers list is the
    Settings source of truth: empty means nobody, otherwise only listed runtimes
    write. The digest binds the permit to this exact registration and key, so a
    changed root voids a pending permit."""
    parts = str(path).split("/")
    if (len(parts) < 3 or parts[0] + "/" != ROOT_PATH_PREFIX or not _ID.match(parts[1])
            or any(part in ("", ".", "..") for part in parts[2:])):
        raise InvalidCell("workspace-root write path is invalid")
    roots, pin = read_registered_roots(verifier, snapshot_path=snapshot_path,
                                       pin_path=pin_path, last_good_path=last_good_path)
    entry = roots.get(parts[1])
    if entry is None:
        raise InvalidCell("%s is not a registered workspace root" % parts[1])
    runtime = str(runtime or "").strip().lower()
    writers = entry.get("writers") if type(entry.get("writers")) is list else []
    if runtime and runtime not in writers:
        raise InvalidCell(
            "%s is not enabled for workspace root %s; enable %s in Settings > Workspaces"
            % (runtime, parts[1], runtime))
    identity = folder_identity(entry.get("path"))
    if identity is None or list(identity) != entry.get("identity"):
        raise InvalidCell("registered workspace root %s is unavailable (moved, swapped "
                          "or missing)" % parts[1])
    digest = hashlib.sha256(canonical({"root": entry, "key": pin})).hexdigest()
    return "workspace-root:" + parts[1], digest, dict(entry)


_last_session_refusal = None


def private_grant_settings_view(grant_store) -> dict:
    """Read active consent and canonical sessions through the existing machine pipe."""
    from .private_root_grants import DEFAULT_OPERATIONS
    from .application_machine_transport import (
        UniversalRuntimeClient, default_runtime_descriptor_path,
    )
    grants = []
    if grant_store is not None:
        for grant in grant_store.list():
            if grant["revoked"] or grant["expires_at"] <= time.time():
                continue
            try:
                _, digest, registration = root_bound_registration(
                    "workspace-roots/%s/__grant__" % grant["root_id"], runtime=grant["runtime"])
            except InvalidCell:
                continue
            if registration.get("privacy") == "private" and digest == grant["root_digest"]:
                grants.append(grant)
    try:
        if grant_store is None:
            raise InvalidCell("private-root grant store is unavailable")
        client = UniversalRuntimeClient(default_runtime_descriptor_path(), grant_store.provider)
        sessions = client.request("GET", "/api/universal/private-root-grant",
                                  {"action": "list-sessions"})
    except (InvalidCell, OSError, RuntimeError, ValueError) as exc:
        sessions = {"status": "unavailable", "sessions": [], "reason": str(exc)}
        global _last_session_refusal
        if sessions["reason"] != _last_session_refusal:
            _last_session_refusal = sessions["reason"]
            from .private_root_grants import record_grant_event
            record_grant_event("list-sessions", "unavailable", "%s: %s" % (type(exc).__name__, exc),
                               directory=None if grant_store is None else grant_store.path.parent)
    return {
        "own_agents_write_without_asking": (True if grant_store is None else
            getattr(grant_store, "own_agents_write_without_asking", lambda: True)()),
        "private_grants": grants,
        # The existing store's default is measured against grant receipts by the court.
        "private_grant_defaults": {"operations": list(DEFAULT_OPERATIONS),
                                   "expires_after_seconds": 30 * 24 * 60 * 60},
        "private_grant_sessions": sessions,
    }


def roots_view(revision, roots, pin, status, *, built_in=None, enrollment=None) -> dict:
    return {
        "revision": revision,
        "built_in": {"id": "archhub", "path": built_in or built_in_path(), "removable": False},
        "roots": [
            {key: root[key] for key in ("root_id", "path", "privacy", "profile",
                                        "writers", "state", "registered_at")}
            for root in roots
        ],
        "key_pinned": pin is not None,
        # The enrollment attestation for the pinned key (mode/who/when/fp), so
        # Settings can show how the workspace-roots key came to be trusted. None until pinned.
        "enrollment": enrollment,
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
    "read_enrollment",
    "OWNER_OPENED",
    "OPEN_AGENT_RUNTIMES",
    "RUNTIMES",
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
