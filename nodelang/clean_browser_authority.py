"""Bind browser sessions to the clean Unified Cell authority.

The browser-session vocabulary is compiled from the existing graph protocol,
remapped to opaque Cell identities, and installed beneath the existing
Interface composition. Opaque browser credentials remain transient; only
their digests and signed command receipts enter the one selected graph.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import time
from types import MappingProxyType
from typing import Mapping
import uuid

from .cell_attention import (
    active_focus,
    install_attention_protocol,
    open_attention_protocol,
    prepare_accepted_focus_transition,
)
from . import cell_browser_sessions
from .cell_browser_sessions import (
    MAX_SESSION_SECONDS,
    ROLE_NAMES,
    STATE_NAMES,
    BrowserSessionDenied,
    BrowserSessionProjection,
    BrowserSessionProtocol,
    compose_browser_session_protocol,
    list_browser_session_roots,
    read_browser_session,
    verify_browser_session,
)
from .cell_protocols import read_relation
from .cell_source_assembly import (
    SourceCellBatch,
    remap_source_cells,
    source_modules_digest,
)
from .unified_authority import (
    CODEC_NAME,
    COMMAND_BUDGET,
    CallerCommandCapability,
    CommandResult,
    UnifiedAuthority,
    append_relation_member,
    build_value,
    commit_with_receipt,
    decode_value,
    digest,
    find_receipt,
    new_id,
    relation_cells,
    typed_relation_cells,
    validate_command_participants,
    composition_root,
    read_scope_level,
    validate_composition,
)
from .universal_cell import NULL_CELL_ID, Cell, InvalidCell, Snapshot


BROWSER_AUTHORITY_LABEL = "ArchHub browser-session authority"
BROWSER_AUTHORITY_VERSION = "clean-browser-authority/v1"
_SOURCE_PREFIX = "source:clean-browser-session-protocol"


@dataclass(frozen=True, slots=True)
class CleanBrowserAuthority:
    graph_id: str
    root_id: str
    protocol: BrowserSessionProtocol
    source_digest: str
    revision: int
    replayed: bool
    receipt_root: str | None


@dataclass(frozen=True, slots=True)
class CleanBrowserSessionResult:
    graph_id: str
    root_id: str
    subject_root: str
    view_root: str
    tenant_root: str
    assurance_root: str
    state_root: str
    accepted_revision: int
    revision: int
    replayed: bool
    receipt_root: str | None


def _normalized_focus_selection(
    selected_roots: tuple[str, ...] | list[str] | set[str] | frozenset[str],
    primary_root: str,
) -> tuple[str, ...]:
    selected = tuple(dict.fromkeys(selected_roots))
    if not selected or primary_root not in selected:
        raise InvalidCell("browser focus primary must be selected")
    if not all(type(root) is str and root for root in selected):
        raise InvalidCell("browser focus selection contains an invalid root")
    return selected


def _source_digest() -> str:
    return source_modules_digest(
        BROWSER_AUTHORITY_VERSION,
        (cell_browser_sessions,),
    )


def _compile_source() -> tuple[tuple[Cell, ...], BrowserSessionProtocol]:
    batch = SourceCellBatch()
    source = compose_browser_session_protocol(batch, prefix=_SOURCE_PREFIX)
    cells, identities = remap_source_cells(batch.cells)
    return cells, BrowserSessionProtocol(
        identities[source.root_id],
        MappingProxyType({
            name: identities[root] for name, root in source.roles.items()
        }),
        MappingProxyType({
            name: identities[root] for name, root in source.states.items()
        }),
    )


def _entry_cells(
    authority: UnifiedAuthority,
    label: str,
    target_root: str,
) -> tuple[str, tuple[Cell, ...]]:
    label_root, label_cells = build_value(
        authority.roles,
        authority.codecs[CODEC_NAME],
        label,
        shape_root=authority.shape("value"),
    )
    entry_root = new_id()
    return entry_root, (
        *label_cells,
        *typed_relation_cells(
            entry_root,
            authority.role("conforms-to"),
            authority.shape("composition"),
            (
                (authority.role("label"), label_root),
                (authority.role("body"), target_root),
            ),
        ),
    )


def _one_member(members, role_id: str, label: str) -> str:
    roots = tuple(
        member.participant_id for member in members
        if member.role_id == role_id
    )
    if len(roots) != 1:
        raise InvalidCell("browser authority requires one %s" % label)
    return roots[0]


def _read_entry(
    authority: UnifiedAuthority,
    snapshot: Snapshot,
    root_id: str,
) -> tuple[str, str]:
    validate_composition(authority, snapshot, root_id)
    members = read_relation(snapshot, root_id, budget=256)
    label_root = _one_member(
        members,
        authority.role("label"),
        "entry label",
    )
    target_root = _one_member(
        members,
        authority.role("body"),
        "entry target",
    )
    label = decode_value(authority, snapshot, label_root)
    if type(label) is not str or not label or target_root not in snapshot.cells:
        raise InvalidCell("browser authority entry is invalid")
    return label, target_root


def _validate_protocol(
    snapshot: Snapshot,
    protocol: BrowserSessionProtocol,
) -> None:
    required = {
        protocol.root_id,
        *protocol.roles.values(),
        *protocol.states.values(),
    }
    if any(_root not in snapshot.cells for _root in required):
        raise InvalidCell("browser-session protocol is incomplete")
    members = read_relation(snapshot, protocol.root_id, budget=100_000)
    allowed_roles = {
        protocol.role("vocabulary-member"),
        protocol.role("session-member"),
    }
    if any(member.role_id not in allowed_roles for member in members):
        raise InvalidCell("browser-session protocol has an undeclared member")
    vocabulary = {
        member.participant_id for member in members
        if member.role_id == protocol.role("vocabulary-member")
    }
    if vocabulary != {*protocol.roles.values(), *protocol.states.values()}:
        raise InvalidCell("browser-session vocabulary drifted")
    sessions = tuple(
        member.participant_id for member in members
        if member.role_id == protocol.role("session-member")
    )
    if len(sessions) != len(set(sessions)):
        raise InvalidCell("browser-session registry contains a duplicate")


def _read_authority(
    authority: UnifiedAuthority,
    snapshot: Snapshot,
    root_id: str,
    *,
    replayed: bool,
    receipt_root: str | None,
) -> CleanBrowserAuthority:
    # Every member of the Interface is offered to this reader, and one of
    # them is the scope interaction set -- a command-scale structure. The
    # line below already reads at the command budget; validating at the
    # ten-thousand default meant one large neighbour stopped the browser
    # authority opening at all, and with it the whole canvas.
    validate_composition(
        authority, snapshot, root_id, budget=COMMAND_BUDGET
    )
    members = read_relation(snapshot, root_id, budget=COMMAND_BUDGET)
    protocol_root = _one_member(
        members,
        authority.role("protocol-definition"),
        "browser-session protocol",
    )
    digest_root = _one_member(
        members,
        authority.role("content-digest"),
        "source digest",
    )
    source_digest = decode_value(authority, snapshot, digest_root)
    if (
        type(source_digest) is not str
        or len(source_digest) != 64
        or any(char not in "0123456789abcdef" for char in source_digest)
    ):
        raise InvalidCell("browser authority source digest is invalid")

    roles: dict[str, str] = {}
    states: dict[str, str] = {}
    entries = tuple(
        member.participant_id for member in members
        if member.role_id == authority.role("item")
    )
    if len(entries) != len(set(entries)):
        raise InvalidCell("browser authority entries are duplicated")
    for entry_root in entries:
        label, target = _read_entry(authority, snapshot, entry_root)
        if label.startswith("role/"):
            target_map = roles
            name = label.removeprefix("role/")
        elif label.startswith("state/"):
            target_map = states
            name = label.removeprefix("state/")
        else:
            raise InvalidCell("browser authority entry category is invalid")
        if not name or name in target_map:
            raise InvalidCell("browser authority entry is duplicated")
        target_map[name] = target
    if set(roles) != set(ROLE_NAMES) or set(states) != set(STATE_NAMES):
        raise InvalidCell("browser authority vocabulary is incomplete")
    protocol = BrowserSessionProtocol(
        protocol_root,
        MappingProxyType(roles),
        MappingProxyType(states),
    )
    _validate_protocol(snapshot, protocol)
    return CleanBrowserAuthority(
        authority.manifest.graph_id,
        root_id,
        protocol,
        source_digest,
        snapshot.revision,
        replayed,
        receipt_root,
    )


def _authorities_in_interface(
    authority: UnifiedAuthority,
    snapshot: Snapshot,
    interface_root: str,
) -> tuple[CleanBrowserAuthority, ...]:
    candidates: list[CleanBrowserAuthority] = []
    for member in read_relation(snapshot, interface_root, budget=COMMAND_BUDGET):
        if member.role_id != authority.role("composition"):
            continue
        try:
            candidate = _read_authority(
                authority,
                snapshot,
                member.participant_id,
                replayed=False,
                receipt_root=None,
            )
        except InvalidCell:
            continue
        candidates.append(candidate)
    if len(candidates) > 1:
        raise InvalidCell("Interface contains duplicate browser authorities")
    return tuple(candidates)


def install_clean_browser_authority(
    authority: UnifiedAuthority,
    *,
    caller: CallerCommandCapability,
    command_id: str,
) -> CleanBrowserAuthority:
    """Install the exact existing browser-session protocol in one graph."""
    install_attention_protocol(
        authority,
        caller=caller,
        command_id=str(uuid.uuid5(uuid.UUID(command_id), "attention-protocol")),
    )
    source_digest = _source_digest()
    request_digest = digest({
        "intent": "install-clean-browser-authority",
        "source-digest": source_digest,
        "version": BROWSER_AUTHORITY_VERSION,
    })
    snapshot = authority.store.snapshot()
    interface_root = composition_root(authority, "Interface", caller=caller)
    authenticated, policy_proof = validate_command_participants(
        authority,
        snapshot,
        caller,
        command_id,
        intent="install-clean-browser-authority",
        request_digest=request_digest,
        object_root=interface_root,
        scope_root=interface_root,
        budget=COMMAND_BUDGET,
    )
    existing = find_receipt(
        authority,
        snapshot,
        authenticated.actor_root,
        authenticated.session_root,
        command_id,
    )
    if existing is not None:
        if existing.request_digest != request_digest:
            raise InvalidCell("idempotency key was reused with another request")
        current = authority.store.snapshot()
        return _read_authority(
            authority,
            current,
            existing.result_root,
            replayed=True,
            receipt_root=existing.root_id,
        )

    installed = _authorities_in_interface(
        authority,
        snapshot,
        interface_root,
    )
    if installed:
        current = installed[0]
        if current.source_digest != source_digest:
            raise InvalidCell("a different browser authority is already installed")
        return CleanBrowserAuthority(
            current.graph_id,
            current.root_id,
            current.protocol,
            current.source_digest,
            current.revision,
            True,
            None,
        )

    protocol_cells, protocol = _compile_source()
    cells: list[Cell] = list(protocol_cells)
    entries: list[str] = []
    for category, roots in (
        ("role", protocol.roles),
        ("state", protocol.states),
    ):
        for name, target_root in sorted(roots.items()):
            entry_root, entry_cells = _entry_cells(
                authority,
                "%s/%s" % (category, name),
                target_root,
            )
            entries.append(entry_root)
            cells.extend(entry_cells)

    label_root, label_cells = build_value(
        authority.roles,
        authority.codecs[CODEC_NAME],
        BROWSER_AUTHORITY_LABEL,
        shape_root=authority.shape("value"),
    )
    digest_root, digest_cells = build_value(
        authority.roles,
        authority.codecs[CODEC_NAME],
        source_digest,
        shape_root=authority.shape("value"),
    )
    root_id = new_id()
    root_cells = typed_relation_cells(
        root_id,
        authority.role("conforms-to"),
        authority.shape("composition"),
        (
            (authority.role("label"), label_root),
            (authority.role("content-digest"), digest_root),
            (authority.role("protocol-definition"), protocol.root_id),
            *((authority.role("item"), entry) for entry in entries),
        ),
    )
    interface_patch = append_relation_member(
        snapshot,
        interface_root,
        authority.role("composition"),
        root_id,
    )
    result = commit_with_receipt(
        authority,
        snapshot,
        resource_create=(
            *cells,
            *label_cells,
            *digest_cells,
            *root_cells,
            *interface_patch.create,
        ),
        resource_replace=interface_patch.replace,
        authenticated=authenticated,
        result_root=root_id,
        policy_proof=policy_proof,
    )
    return _read_authority(
        authority,
        authority.store.snapshot(),
        result.root_id,
        replayed=False,
        receipt_root=result.receipt_root,
    )


def open_clean_browser_authority(
    authority: UnifiedAuthority,
    *,
    caller: CallerCommandCapability,
) -> CleanBrowserAuthority:
    """Open the one authorized browser-session composition."""
    interface_root = composition_root(authority, "Interface", caller=caller)
    read_scope_level(
        authority,
        interface_root,
        scope_root=interface_root,
        caller=caller,
    )
    snapshot = authority.store.snapshot()
    candidates = _authorities_in_interface(
        authority,
        snapshot,
        interface_root,
    )
    if len(candidates) != 1:
        raise InvalidCell("Interface requires exactly one browser authority")
    return candidates[0]


def _current_browser(
    authority: UnifiedAuthority,
    browser: CleanBrowserAuthority,
    snapshot: Snapshot,
) -> CleanBrowserAuthority:
    if browser.graph_id != authority.manifest.graph_id:
        raise InvalidCell("browser authority belongs to another graph")
    current = _read_authority(
        authority,
        snapshot,
        browser.root_id,
        replayed=False,
        receipt_root=None,
    )
    if (
        browser.protocol.root_id != current.protocol.root_id
        or browser.source_digest != current.source_digest
    ):
        raise InvalidCell("browser authority binding is stale")
    return current


def _credential_digest(value: str, label: str) -> str:
    if type(value) is not str:
        raise InvalidCell("%s must be an opaque string" % label)
    encoded = value.encode("utf-8")
    if not encoded or len(encoded) > 4096:
        raise InvalidCell("%s size is invalid" % label)
    return hashlib.sha256(encoded).hexdigest()


def _plain_value(value: str) -> tuple[str, Cell]:
    root_id = new_id()
    return root_id, Cell(
        root_id,
        NULL_CELL_ID,
        NULL_CELL_ID,
        value.encode("utf-8"),
    )


def _session_result(
    authority: UnifiedAuthority,
    browser: CleanBrowserAuthority,
    session_root: str,
    *,
    accepted_revision: int,
    replayed: bool,
    receipt_root: str | None,
) -> CleanBrowserSessionResult:
    snapshot = authority.store.snapshot()
    session = read_browser_session(
        snapshot,
        browser.protocol,
        session_root,
    )
    if (
        session.tenant_root != authority.manifest.application_root
        or session.assurance_root != browser.root_id
    ):
        raise InvalidCell("browser session is outside its graph authority")
    return CleanBrowserSessionResult(
        authority.manifest.graph_id,
        session.root_id,
        session.subject_root,
        session.view_root,
        session.tenant_root,
        session.assurance_root,
        session.state_root,
        accepted_revision,
        snapshot.revision,
        replayed,
        receipt_root,
    )


def _registered_credential_roots(
    snapshot: Snapshot,
    browser: CleanBrowserAuthority,
    token_digest: str,
) -> tuple[str, ...]:
    matches: list[str] = []
    for session_root in list_browser_session_roots(
        snapshot,
        browser.protocol,
    ):
        session = read_browser_session(
            snapshot,
            browser.protocol,
            session_root,
        )
        try:
            stored = snapshot.cells[session.token_digest_root].atom.decode("utf-8")
        except (KeyError, UnicodeDecodeError) as exc:
            raise InvalidCell("browser credential digest is unreadable") from exc
        if stored == token_digest:
            matches.append(session_root)
    return tuple(matches)


def issue_clean_browser_session(
    authority: UnifiedAuthority,
    browser: CleanBrowserAuthority,
    *,
    token: str,
    csrf_token: str,
    lifetime_seconds: float = 900.0,
    caller: CallerCommandCapability,
    command_id: str,
) -> CleanBrowserSessionResult:
    """Issue one signed browser session bound to the authenticated graph caller."""
    lifetime = float(lifetime_seconds)
    if lifetime <= 0 or lifetime > MAX_SESSION_SECONDS:
        raise ValueError("browser session lifetime must be within one hour")
    token_digest = _credential_digest(token, "browser token")
    csrf_digest = _credential_digest(csrf_token, "browser CSRF token")
    current = open_clean_browser_authority(authority, caller=caller)
    snapshot = authority.store.snapshot()
    current = _current_browser(authority, current, snapshot)
    interface_root = composition_root(authority, "Interface", caller=caller)
    request_digest = digest({
        "intent": "issue-clean-browser-session",
        "browser-authority": current.root_id,
        "token-digest": token_digest,
        "csrf-digest": csrf_digest,
        "lifetime-seconds": lifetime,
    })
    authenticated, policy_proof = validate_command_participants(
        authority,
        snapshot,
        caller,
        command_id,
        intent="issue-clean-browser-session",
        request_digest=request_digest,
        object_root=current.root_id,
        scope_root=interface_root,
        budget=COMMAND_BUDGET,
    )
    existing = find_receipt(
        authority,
        snapshot,
        authenticated.actor_root,
        authenticated.session_root,
        command_id,
    )
    if existing is not None:
        if existing.request_digest != request_digest:
            raise InvalidCell("idempotency key was reused with another request")
        return _session_result(
            authority,
            current,
            existing.result_root,
            accepted_revision=existing.result_revision,
            replayed=True,
            receipt_root=existing.root_id,
        )

    if _registered_credential_roots(snapshot, current, token_digest):
        raise InvalidCell("browser credential is already registered")
    now = time.time()
    values = {
        "issued-at": _plain_value(repr(now)),
        "expires-at": _plain_value(repr(now + lifetime)),
        "token-digest": _plain_value(token_digest),
        "csrf-digest": _plain_value(csrf_digest),
    }
    session_root = new_id()
    session_cells = relation_cells(
        session_root,
        (
            (current.protocol.role("subject"), authenticated.actor_root),
            (current.protocol.role("view"), authenticated.session_root),
            (
                current.protocol.role("tenant"),
                authority.manifest.application_root,
            ),
            (current.protocol.role("assurance"), current.root_id),
            (current.protocol.role("issued-at"), values["issued-at"][0]),
            (current.protocol.role("expires-at"), values["expires-at"][0]),
            (
                current.protocol.role("token-digest"),
                values["token-digest"][0],
            ),
            (
                current.protocol.role("csrf-digest"),
                values["csrf-digest"][0],
            ),
            (
                current.protocol.role("state"),
                current.protocol.states["active"],
            ),
        ),
    )
    registry_patch = append_relation_member(
        snapshot,
        current.protocol.root_id,
        current.protocol.role("session-member"),
        session_root,
    )
    result = commit_with_receipt(
        authority,
        snapshot,
        resource_create=(
            *(cell for _, cell in values.values()),
            *session_cells,
            *registry_patch.create,
        ),
        resource_replace=registry_patch.replace,
        authenticated=authenticated,
        result_root=session_root,
        policy_proof=policy_proof,
    )
    return _session_result(
        authority,
        current,
        result.root_id,
        accepted_revision=result.revision,
        replayed=False,
        receipt_root=result.receipt_root,
    )


def verify_clean_browser_session(
    authority: UnifiedAuthority,
    browser: CleanBrowserAuthority,
    session_root: str,
    *,
    token: str,
    csrf_token: str | None = None,
    require_csrf: bool = False,
    now: float | None = None,
) -> BrowserSessionProjection:
    """Verify transient credentials against the exact current graph revision."""
    snapshot = authority.store.snapshot()
    current = _current_browser(authority, browser, snapshot)
    session = verify_browser_session(
        snapshot,
        current.protocol,
        session_root,
        token=token,
        csrf_token=csrf_token,
        require_csrf=require_csrf,
        now=now,
    )
    if (
        session.tenant_root != authority.manifest.application_root
        or session.assurance_root != current.root_id
    ):
        raise BrowserSessionDenied("browser session authority binding drifted")
    return session


def revoke_clean_browser_session(
    authority: UnifiedAuthority,
    browser: CleanBrowserAuthority,
    session_root: str,
    *,
    reason: str,
    caller: CallerCommandCapability,
    command_id: str,
) -> CleanBrowserSessionResult:
    """Revoke one browser session through a signed graph command."""
    normalized_reason = str(reason).strip()
    if not normalized_reason or len(normalized_reason.encode("utf-8")) > 1024:
        raise ValueError("browser-session revocation reason is required")
    current = open_clean_browser_authority(authority, caller=caller)
    snapshot = authority.store.snapshot()
    current = _current_browser(authority, current, snapshot)
    interface_root = composition_root(authority, "Interface", caller=caller)
    request_digest = digest({
        "intent": "revoke-clean-browser-session",
        "browser-authority": current.root_id,
        "session": session_root,
        "reason": normalized_reason,
    })
    authenticated, policy_proof = validate_command_participants(
        authority,
        snapshot,
        caller,
        command_id,
        intent="revoke-clean-browser-session",
        request_digest=request_digest,
        object_root=current.root_id,
        scope_root=interface_root,
        budget=COMMAND_BUDGET,
    )
    existing = find_receipt(
        authority,
        snapshot,
        authenticated.actor_root,
        authenticated.session_root,
        command_id,
    )
    if existing is not None:
        if existing.request_digest != request_digest:
            raise InvalidCell("idempotency key was reused with another request")
        return _session_result(
            authority,
            current,
            existing.result_root,
            accepted_revision=existing.result_revision,
            replayed=True,
            receipt_root=existing.root_id,
        )

    session = read_browser_session(snapshot, current.protocol, session_root)
    if (
        session.tenant_root != authority.manifest.application_root
        or session.assurance_root != current.root_id
    ):
        raise BrowserSessionDenied("browser session authority binding drifted")
    if session.state_root != current.protocol.states["active"]:
        raise BrowserSessionDenied("browser session is already revoked")
    reason_root, reason_cell = _plain_value(normalized_reason)
    reason_patch = append_relation_member(
        snapshot,
        session_root,
        current.protocol.role("revocation-reason"),
        reason_root,
        budget=256,
    )
    state_incidence = snapshot.cells[session.state_incidence]
    result = commit_with_receipt(
        authority,
        snapshot,
        resource_create=(reason_cell, *reason_patch.create),
        resource_replace=(
            Cell(
                state_incidence.id,
                state_incidence.link0,
                current.protocol.states["revoked"],
                state_incidence.atom,
            ),
            *reason_patch.replace,
        ),
        authenticated=authenticated,
        result_root=session_root,
        policy_proof=policy_proof,
    )
    return _session_result(
        authority,
        current,
        result.root_id,
        accepted_revision=result.revision,
        replayed=False,
        receipt_root=result.receipt_root,
    )


def revise_clean_browser_focus(
    authority: UnifiedAuthority,
    browser: CleanBrowserAuthority,
    browser_session_root: str,
    *,
    scope_root: str,
    selected_roots: tuple[str, ...] | list[str] | set[str] | frozenset[str],
    primary_root: str,
    caller: CallerCommandCapability,
    command_id: str,
    expected_revision: int | None = None,
):
    """Commit one accepted Focus transition for an issued browser/view session."""
    selected = _normalized_focus_selection(selected_roots, primary_root)
    if expected_revision is not None and (
        type(expected_revision) is not int or expected_revision < 0
    ):
        raise InvalidCell("browser focus base is invalid")
    request: dict[str, object] = {
        "intent": "revise-clean-browser-focus",
        "browser-authority": browser.root_id,
        "browser-session": browser_session_root,
        "scope": scope_root,
        "selected": selected,
        "primary": primary_root,
    }
    if expected_revision is not None:
        request["expected_revision"] = expected_revision
    request_digest = digest(request)
    snapshot = authority.store.snapshot()
    authenticated, policy_proof = validate_command_participants(
        authority,
        snapshot,
        caller,
        command_id,
        intent="revise-clean-browser-focus",
        request_digest=request_digest,
        object_root=primary_root,
        scope_root=scope_root,
        budget=COMMAND_BUDGET,
    )
    existing = find_receipt(
        authority,
        snapshot,
        authenticated.actor_root,
        authenticated.session_root,
        command_id,
    )
    if existing is not None:
        if existing.request_digest != request_digest:
            raise InvalidCell("idempotency key was reused with another request")
        return CommandResult(
            existing.result_root,
            existing.result_revision,
            True,
            0,
            0,
            existing.root_id,
        )
    if expected_revision is not None and snapshot.revision != expected_revision:
        raise InvalidCell("browser focus base is stale")
    current = _current_browser(authority, browser, snapshot)
    session = read_browser_session(snapshot, current.protocol, browser_session_root)
    if (
        session.tenant_root != authority.manifest.application_root
        or session.assurance_root != current.root_id
    ):
        raise BrowserSessionDenied("browser session authority binding drifted")
    try:
        issued_at = float(snapshot.cells[session.issued_at_root].atom.decode("utf-8"))
        expires_at = float(snapshot.cells[session.expires_at_root].atom.decode("utf-8"))
    except (KeyError, UnicodeDecodeError, ValueError) as exc:
        raise BrowserSessionDenied("browser session timing is invalid") from exc
    current_time = time.time()
    if issued_at > current_time + 5 or expires_at <= current_time:
        raise BrowserSessionDenied("browser session is expired")
    if session.state_root != current.protocol.states["active"]:
        raise BrowserSessionDenied("browser session is revoked")
    if session.subject_root != authenticated.actor_root:
        raise BrowserSessionDenied("browser session subject drifted")
    if session.view_root != authenticated.session_root:
        raise BrowserSessionDenied("browser session is bound to another view session")
    scope = read_scope_level(
        authority,
        scope_root,
        scope_root=scope_root,
        caller=caller,
        at_revision=snapshot.revision,
        budget=COMMAND_BUDGET,
    )
    visible = frozenset(scope.composition_roots)
    if not set(selected).issubset(visible):
        raise InvalidCell("browser focus selection is outside the current scope")
    protocol = open_attention_protocol(snapshot)
    current_focus = active_focus(
        snapshot,
        protocol,
        session_root=session.view_root,
    )
    if (
        current_focus is not None
        and current_focus.actor_root == session.subject_root
        and current_focus.scope_root == scope_root
        and current_focus.selected_roots == selected
        and current_focus.primary_root == primary_root
        and current_focus.state_root == protocol.state("active")
    ):
        return commit_with_receipt(
            authority,
            snapshot,
            resource_create=(),
            resource_replace=(),
            authenticated=authenticated,
            result_root=current_focus.root_id,
            policy_proof=policy_proof,
        )
    transition = prepare_accepted_focus_transition(
        snapshot,
        protocol,
        focus_id=new_id(),
        actor_root=session.subject_root,
        session_root=session.view_root,
        scope_root=scope_root,
        selected_roots=selected,
        primary_root=primary_root,
        origin="user",
        reason_roots=(browser_session_root,),
        attention_roots=(),
        authority_root=current.root_id,
        consent_evidence_root=browser_session_root,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    return commit_with_receipt(
        authority,
        snapshot,
        resource_create=transition.create,
        resource_replace=transition.replace,
        authenticated=authenticated,
        result_root=transition.root_id,
        policy_proof=policy_proof,
    )


__all__ = [
    "BROWSER_AUTHORITY_LABEL",
    "BROWSER_AUTHORITY_VERSION",
    "CleanBrowserAuthority",
    "CleanBrowserSessionResult",
    "install_clean_browser_authority",
    "issue_clean_browser_session",
    "open_clean_browser_authority",
    "revise_clean_browser_focus",
    "revoke_clean_browser_session",
    "verify_clean_browser_session",
]
