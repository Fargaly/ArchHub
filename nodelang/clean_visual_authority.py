"""Install the existing graph-defined visual system in the clean authority.

The source template builders are compiled into ordinary Cells, remapped to
opaque identities, and committed through one signed authority receipt.  The
compiler is not a store and retains no second graph or runtime authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable, Mapping
import uuid

from . import (
    cell_result_view,
    cell_run_view,
    cell_authority_view,
    cell_canvas_card_view,
    cell_canvas_heading_view,
    cell_canvas_port_view,
    cell_canvas_toolbar_view,
    cell_control_view,
    cell_evidence_floor_view,
    cell_focus_view,
    cell_inspector_controls_view,
    cell_inspector_header_view,
    cell_inspector_shell_view,
    cell_interface_view,
    cell_library_definition_view,
    cell_library_primitive_view,
    cell_library_section_view,
    cell_library_shell_view,
    cell_presentation_view,
    cell_properties_view,
    cell_relation_composer_view,
    cell_relations_view,
    cell_timeline_view,
    cell_view_template,
)
from .cell_protocols import read_relation
from .clean_subsystem_revision import replace_interface_subsystem
from .cell_source_assembly import (
    SourceCellBatch,
    remap_source_cells,
    source_modules_digest,
)
from .cell_view_template import (
    OPERATION_NAMES,
    ROLE_NAMES,
    ViewTemplateProtocol,
    compose_view_template_protocol,
    is_view_template,
    render_view_template,
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
    typed_relation_cells,
    validate_command_participants,
    composition_root,
    read_scope_level,
    validate_composition,
)
from .universal_cell import NULL_CELL_ID, Cell, InvalidCell, Snapshot


VISUAL_SYSTEM_LABEL = "ArchHub graph visual system"
VISUAL_SYSTEM_VERSION = "clean-visual-system/v1"


@dataclass(frozen=True, slots=True)
class CleanVisualSystem:
    graph_id: str
    root_id: str
    protocol: ViewTemplateProtocol
    template_roots: Mapping[str, str]
    source_digest: str
    revision: int
    replayed: bool
    receipt_root: str | None


_TEMPLATE_SPECS: tuple[
    tuple[str, str, Callable[[SourceCellBatch, ViewTemplateProtocol], str]], ...
] = (
    (
        "properties",
        cell_properties_view.FIELD_LIST_TEMPLATE_ROOT,
        cell_properties_view.compose_field_list_template,
    ),
    (
        "focus",
        cell_focus_view.FOCUS_LIST_TEMPLATE_ROOT,
        cell_focus_view.compose_focus_list_template,
    ),
    (
        "interfaces",
        cell_interface_view.INTERFACE_LIST_TEMPLATE_ROOT,
        cell_interface_view.compose_interface_list_template,
    ),
    (
        "relations",
        cell_relations_view.RELATION_LIST_TEMPLATE_ROOT,
        cell_relations_view.compose_relation_list_template,
    ),
    (
        "controls",
        cell_control_view.CONTROL_LIST_TEMPLATE_ROOT,
        cell_control_view.compose_control_list_template,
    ),
    (
        "presentation",
        cell_presentation_view.PRESENTATION_LIST_TEMPLATE_ROOT,
        cell_presentation_view.compose_presentation_list_template,
    ),
    (
        "authority",
        cell_authority_view.AUTHORITY_LIST_TEMPLATE_ROOT,
        cell_authority_view.compose_authority_list_template,
    ),
    (
        "timeline",
        cell_timeline_view.TIMELINE_TEMPLATE_ROOT,
        cell_timeline_view.compose_timeline_template,
    ),
    (
        "evidence",
        cell_evidence_floor_view.EVIDENCE_LIST_TEMPLATE_ROOT,
        cell_evidence_floor_view.compose_evidence_list_template,
    ),
    (
        "cell-floor",
        cell_evidence_floor_view.CELL_FLOOR_TEMPLATE_ROOT,
        cell_evidence_floor_view.compose_cell_floor_template,
    ),
    (
        "inspector-header",
        cell_inspector_header_view.INSPECTOR_HEADER_TEMPLATE_ROOT,
        cell_inspector_header_view.compose_inspector_header_template,
    ),
    (
        "run",
        cell_run_view.RUN_TEMPLATE_ROOT,
        cell_run_view.compose_run_template,
    ),
    (
        "result",
        cell_result_view.RESULT_TEMPLATE_ROOT,
        cell_result_view.compose_result_template,
    ),
    (
        "canvas-card",
        cell_canvas_card_view.CANVAS_CARD_TEMPLATE_ROOT,
        cell_canvas_card_view.compose_canvas_card_template,
    ),
    (
        "inspector-controls",
        cell_inspector_controls_view.INSPECTOR_CONTROLS_TEMPLATE_ROOT,
        cell_inspector_controls_view.compose_inspector_controls_template,
    ),
    (
        "inspector-shell",
        cell_inspector_shell_view.INSPECTOR_SHELL_TEMPLATE_ROOT,
        cell_inspector_shell_view.compose_inspector_shell_template,
    ),
    (
        "canvas-port",
        cell_canvas_port_view.CANVAS_PORT_TEMPLATE_ROOT,
        cell_canvas_port_view.compose_canvas_port_template,
    ),
    (
        "canvas-toolbar",
        cell_canvas_toolbar_view.CANVAS_TOOLBAR_TEMPLATE_ROOT,
        cell_canvas_toolbar_view.compose_canvas_toolbar_template,
    ),
    (
        "canvas-heading",
        cell_canvas_heading_view.CANVAS_HEADING_TEMPLATE_ROOT,
        cell_canvas_heading_view.compose_canvas_heading_template,
    ),
    (
        "library-definition",
        cell_library_definition_view.LIBRARY_DEFINITION_TEMPLATE_ROOT,
        cell_library_definition_view.compose_library_definition_template,
    ),
    (
        "library-primitive",
        cell_library_primitive_view.LIBRARY_PRIMITIVE_TEMPLATE_ROOT,
        cell_library_primitive_view.compose_library_primitive_template,
    ),
    (
        "library-section",
        cell_library_section_view.LIBRARY_SECTION_TEMPLATE_ROOT,
        cell_library_section_view.compose_library_section_template,
    ),
    (
        "library-shell",
        cell_library_shell_view.LIBRARY_SHELL_TEMPLATE_ROOT,
        cell_library_shell_view.compose_library_shell_template,
    ),
    (
        "relation-composer",
        cell_relation_composer_view.RELATION_COMPOSER_VIEW_TEMPLATE_ROOT,
        cell_relation_composer_view.compose_relation_composer_view_template,
    ),
)

_SOURCE_MODULES = (
    cell_view_template,
    cell_properties_view,
    cell_focus_view,
    cell_interface_view,
    cell_relations_view,
    cell_control_view,
    cell_presentation_view,
    cell_authority_view,
    cell_timeline_view,
    cell_evidence_floor_view,
    cell_inspector_header_view,
    cell_run_view,
    cell_result_view,
    cell_canvas_card_view,
    cell_inspector_controls_view,
    cell_inspector_shell_view,
    cell_canvas_port_view,
    cell_canvas_toolbar_view,
    cell_canvas_heading_view,
    cell_library_definition_view,
    cell_library_primitive_view,
    cell_library_section_view,
    cell_library_shell_view,
    cell_relation_composer_view,
)


def _visual_source_digest() -> str:
    return source_modules_digest(VISUAL_SYSTEM_VERSION, _SOURCE_MODULES)


def _compile_visual_source() -> tuple[
    tuple[Cell, ...],
    ViewTemplateProtocol,
    Mapping[str, str],
]:
    batch = SourceCellBatch()
    source_protocol = compose_view_template_protocol(
        batch,
        prefix=cell_properties_view.VIEW_TEMPLATE_PREFIX,
    )
    source_roots: dict[str, str] = {}
    for name, expected_root, compose in _TEMPLATE_SPECS:
        root = compose(batch, source_protocol)
        if root != expected_root:
            raise InvalidCell("visual template source root drifted")
        source_roots[name] = root

    mapped_cells, identities = remap_source_cells(batch.cells)
    protocol = ViewTemplateProtocol(
        identities[source_protocol.root_id],
        MappingProxyType({
            name: identities[root]
            for name, root in source_protocol.roles.items()
        }),
        MappingProxyType({
            name: identities[root]
            for name, root in source_protocol.operations.items()
        }),
    )
    roots = MappingProxyType({
        name: identities[root] for name, root in source_roots.items()
    })
    return mapped_cells, protocol, roots


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
    cells = typed_relation_cells(
        entry_root,
        authority.role("conforms-to"),
        authority.shape("composition"),
        (
            (authority.role("label"), label_root),
            (authority.role("body"), target_root),
        ),
    )
    return entry_root, (*label_cells, *cells)


def _one_member(
    members,
    role_id: str,
    label: str,
) -> str:
    roots = tuple(
        member.participant_id for member in members
        if member.role_id == role_id
    )
    if len(roots) != 1:
        raise InvalidCell("visual system requires one %s" % label)
    return roots[0]


def _read_entry(
    authority: UnifiedAuthority,
    snapshot: Snapshot,
    entry_root: str,
) -> tuple[str, str]:
    validate_composition(authority, snapshot, entry_root)
    members = read_relation(snapshot, entry_root, budget=256)
    label_root = _one_member(members, authority.role("label"), "entry label")
    target_root = _one_member(members, authority.role("body"), "entry target")
    label = decode_value(authority, snapshot, label_root)
    if type(label) is not str or not label:
        raise InvalidCell("visual system entry label is invalid")
    if target_root not in snapshot.cells:
        raise InvalidCell("visual system entry target is missing")
    return label, target_root


def _read_visual_system(
    authority: UnifiedAuthority,
    snapshot: Snapshot,
    root_id: str,
    *,
    replayed: bool,
    receipt_root: str | None,
    require_current_catalogue: bool = True,
) -> CleanVisualSystem:
    # This reader is offered every member of the Interface, and one of
    # them is the scope interaction set -- a command-scale structure.
    # The read below already uses the command budget; validating at the
    # default refused one large neighbour and took the canvas with it.
    validate_composition(
        authority, snapshot, root_id, budget=COMMAND_BUDGET
    )
    members = read_relation(snapshot, root_id, budget=COMMAND_BUDGET)
    protocol_root = _one_member(
        members,
        authority.role("protocol-definition"),
        "view-template protocol",
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
        raise InvalidCell("visual system source digest is invalid")

    role_roots: dict[str, str] = {}
    operation_roots: dict[str, str] = {}
    template_roots: dict[str, str] = {}
    entry_roots = tuple(
        member.participant_id for member in members
        if member.role_id == authority.role("item")
    )
    if len(entry_roots) != len(set(entry_roots)):
        raise InvalidCell("visual system entries are duplicated")
    for entry_root in entry_roots:
        label, target = _read_entry(authority, snapshot, entry_root)
        if label.startswith("role/"):
            target_map = role_roots
            name = label.removeprefix("role/")
        elif label.startswith("operation/"):
            target_map = operation_roots
            name = label.removeprefix("operation/")
        elif label.startswith("template/"):
            target_map = template_roots
            name = label.removeprefix("template/")
        else:
            raise InvalidCell("visual system entry category is invalid")
        if not name or name in target_map:
            raise InvalidCell("visual system entry name is invalid or duplicated")
        target_map[name] = target
    if set(role_roots) != set(ROLE_NAMES):
        raise InvalidCell("visual role vocabulary is incomplete")
    if set(operation_roots) != set(OPERATION_NAMES):
        raise InvalidCell("visual operation vocabulary is incomplete")
    # A runtime must hold exactly the templates it knows how to draw, so
    # opening one to render with is strict. Revising is the opposite
    # situation: the installed system is EXPECTED to be older than the
    # code, and reading it is the first thing revising has to do. Holding
    # both to the same rule made adding a template impossible -- the new
    # name made the installed system unreadable, and the one command that
    # could have carried it forward reported that nothing was installed.
    if require_current_catalogue and (
        set(template_roots) != {item[0] for item in _TEMPLATE_SPECS}
    ):
        raise InvalidCell("visual template catalogue is incomplete")
    protocol = ViewTemplateProtocol(
        protocol_root,
        MappingProxyType(role_roots),
        MappingProxyType(operation_roots),
    )
    for template_root in template_roots.values():
        if not is_view_template(snapshot, protocol, template_root):
            raise InvalidCell("visual template is not an executable graph template")
    return CleanVisualSystem(
        authority.manifest.graph_id,
        root_id,
        protocol,
        MappingProxyType(template_roots),
        source_digest,
        snapshot.revision,
        replayed,
        receipt_root,
    )


def _visual_systems_in_interface(
    authority: UnifiedAuthority,
    snapshot: Snapshot,
    interface_root: str,
    *,
    require_current_catalogue: bool = True,
) -> tuple[CleanVisualSystem, ...]:
    members = read_relation(snapshot, interface_root, budget=COMMAND_BUDGET)
    candidates: list[CleanVisualSystem] = []
    for member in members:
        if member.role_id != authority.role("composition"):
            continue
        try:
            candidate = _read_visual_system(
                authority,
                snapshot,
                member.participant_id,
                require_current_catalogue=require_current_catalogue,
                replayed=False,
                receipt_root=None,
            )
        except InvalidCell:
            continue
        candidates.append(candidate)
    if len(candidates) > 1:
        raise InvalidCell("Interface contains duplicate graph visual systems")
    return tuple(candidates)


def revise_clean_visual_system(
    authority: UnifiedAuthority,
    *,
    caller: CallerCommandCapability,
    command_id: str,
) -> CleanVisualSystem:
    """Carry the current visual source onto a graph that holds an older one.

    Installing refuses a graph that already carries a different source, so
    without this every descriptor on a graph is whatever was written the
    first time, for good. This is how a descriptor changes: the Interface
    stops holding the installed system and holds the newly compiled one, in
    one signed revision.
    """
    source_digest = _visual_source_digest()
    snapshot = authority.store.snapshot()
    interface_root = composition_root(authority, "Interface", caller=caller)
    installed = _visual_systems_in_interface(
        authority, snapshot, interface_root, require_current_catalogue=False
    )
    if not installed:
        raise InvalidCell("no graph visual system is installed to revise")
    current = installed[0]
    if current.source_digest == source_digest:
        raise InvalidCell(
            "the installed graph visual system already carries this source"
        )

    visual_cells, protocol, template_roots = _compile_visual_source()
    cells: list[Cell] = list(visual_cells)
    entries: list[str] = []
    for category, roots in (
        ("role", protocol.roles),
        ("operation", protocol.operations),
        ("template", template_roots),
    ):
        for name, target in sorted(roots.items()):
            entry_root, entry_cells = _entry_cells(
                authority, "%s/%s" % (category, name), target
            )
            entries.append(entry_root)
            cells.extend(entry_cells)
    label_root, label_cells = build_value(
        authority.roles,
        authority.codecs[CODEC_NAME],
        VISUAL_SYSTEM_LABEL,
        shape_root=authority.shape("value"),
    )
    digest_root, digest_cells = build_value(
        authority.roles,
        authority.codecs[CODEC_NAME],
        source_digest,
        shape_root=authority.shape("value"),
    )
    system_root = new_id()
    system_cells = typed_relation_cells(
        system_root,
        authority.role("conforms-to"),
        authority.shape("composition"),
        (
            (authority.role("label"), label_root),
            (authority.role("content-digest"), digest_root),
            (authority.role("protocol-definition"), protocol.root_id),
            *((authority.role("item"), entry) for entry in entries),
        ),
    )
    receipt = replace_interface_subsystem(
        authority,
        caller=caller,
        command_id=command_id,
        intent="revise-clean-visual-system",
        held_root=current.root_id,
        replacement_root=system_root,
        replacement_cells=(
            *cells, *label_cells, *digest_cells, *system_cells
        ),
        source_digest=source_digest,
    )
    return _read_visual_system(
        authority,
        authority.store.snapshot(),
        system_root,
        replayed=False,
        receipt_root=getattr(receipt, "root_id", None),
    )


def install_clean_visual_system(
    authority: UnifiedAuthority,
    *,
    caller: CallerCommandCapability,
    command_id: str,
) -> CleanVisualSystem:
    """Install one opaque, signed instance of the existing visual assemblies."""
    source_digest = _visual_source_digest()
    request_digest = digest({
        "intent": "install-clean-visual-system",
        "source-digest": source_digest,
        "version": VISUAL_SYSTEM_VERSION,
    })
    snapshot = authority.store.snapshot()
    interface_root = composition_root(authority, "Interface", caller=caller)
    authenticated, policy_proof = validate_command_participants(
        authority,
        snapshot,
        caller,
        command_id,
        intent="install-clean-visual-system",
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
        return _read_visual_system(
            authority,
            current,
            existing.result_root,
            replayed=True,
            receipt_root=existing.root_id,
        )

    installed = _visual_systems_in_interface(
        authority, snapshot, interface_root
    )
    if installed:
        current = installed[0]
        if current.source_digest != source_digest:
            raise InvalidCell(
                "a different graph visual system source is already installed"
            )
        return CleanVisualSystem(
            current.graph_id,
            current.root_id,
            current.protocol,
            current.template_roots,
            current.source_digest,
            current.revision,
            True,
            None,
        )

    visual_cells, protocol, template_roots = _compile_visual_source()
    cells: list[Cell] = list(visual_cells)
    entries: list[str] = []
    for category, roots in (
        ("role", protocol.roles),
        ("operation", protocol.operations),
        ("template", template_roots),
    ):
        for name, target in sorted(roots.items()):
            entry_root, entry_cells = _entry_cells(
                authority, "%s/%s" % (category, name), target
            )
            entries.append(entry_root)
            cells.extend(entry_cells)

    label_root, label_cells = build_value(
        authority.roles,
        authority.codecs[CODEC_NAME],
        VISUAL_SYSTEM_LABEL,
        shape_root=authority.shape("value"),
    )
    digest_root, digest_cells = build_value(
        authority.roles,
        authority.codecs[CODEC_NAME],
        source_digest,
        shape_root=authority.shape("value"),
    )
    system_root = new_id()
    system_cells = typed_relation_cells(
        system_root,
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
        system_root,
    )
    result = commit_with_receipt(
        authority,
        snapshot,
        resource_create=(
            *cells,
            *label_cells,
            *digest_cells,
            *system_cells,
            *interface_patch.create,
        ),
        resource_replace=interface_patch.replace,
        authenticated=authenticated,
        result_root=system_root,
        policy_proof=policy_proof,
    )
    current = authority.store.snapshot()
    return _read_visual_system(
        authority,
        current,
        result.root_id,
        replayed=False,
        receipt_root=result.receipt_root,
    )


_OPENED_VISUAL_CACHE: dict[int, tuple[object, str, "CleanVisualSystem"]] = {}


def open_clean_visual_system(
    authority: UnifiedAuthority,
    *,
    caller: CallerCommandCapability,
) -> CleanVisualSystem:
    """Open the structurally unique visual assembly from Interface scope.

    Rendering one template re-opens this to check that the caller's
    binding still matches the graph, which is right: a stale binding must
    not draw. But the answer cannot change while the graph does not, and
    a canvas renders hundreds of templates per projection -- so every draw
    walked the whole Interface again, and one canvas became a million
    relation reads.

    The opened system is remembered against the exact cell mapping it was
    read from, and the mapping is compared by identity rather than by
    equality: an object that is still the same object is still the same
    graph. A commit replaces it, and the next open reads the graph again.
    """
    held = _OPENED_VISUAL_CACHE.get(id(authority))
    if held is not None:
        cells, graph_id, opened = held
        current = authority.store.snapshot()
        if cells is current.cells and graph_id == authority.manifest.graph_id:
            return opened
    interface_root = composition_root(authority, "Interface", caller=caller)
    read_scope_level(
        authority,
        interface_root,
        scope_root=interface_root,
        caller=caller,
    )
    snapshot = authority.store.snapshot()
    candidates = _visual_systems_in_interface(
        authority, snapshot, interface_root
    )
    if len(candidates) != 1:
        raise InvalidCell("Interface requires exactly one graph visual system")
    _OPENED_VISUAL_CACHE[id(authority)] = (
        snapshot.cells, authority.manifest.graph_id, candidates[0]
    )
    return candidates[0]


def render_clean_visual_template(
    authority: UnifiedAuthority,
    visual: CleanVisualSystem,
    template_name: str,
    projection: Mapping[str, object],
    *,
    caller: CallerCommandCapability,
) -> list[dict[str, object]]:
    """Interpret one persisted template after exact graph/scope authorization."""
    current = open_clean_visual_system(authority, caller=caller)
    if (
        visual.graph_id != current.graph_id
        or visual.root_id != current.root_id
        or visual.protocol.root_id != current.protocol.root_id
    ):
        raise InvalidCell("visual system binding is stale or belongs to another graph")
    try:
        template_root = current.template_roots[template_name]
    except KeyError as exc:
        raise InvalidCell("visual template is not in the admitted catalogue") from exc
    return render_view_template(
        authority.store.snapshot(),
        current.protocol,
        template_root,
        projection,
    )


__all__ = [
    "CleanVisualSystem",
    "VISUAL_SYSTEM_LABEL",
    "VISUAL_SYSTEM_VERSION",
    "revise_clean_visual_system",
    "install_clean_visual_system",
    "open_clean_visual_system",
    "render_clean_visual_template",
]
