"""Atomic accepted-source compiler into the one Unified Cell authority."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from types import MappingProxyType
from typing import Iterable, Mapping

from markdown_it import MarkdownIt

from .unified_authority import (
    CODEC_NAME,
    COMMAND_BUDGET,
    PANEL_AUDIENCE,
    CallerCommandCapability,
    CommandResult,
    UnifiedAuthority,
    append_relation_members,
    build_definition_revision,
    build_property,
    build_value,
    commit_with_receipt,
    definition_spec,
    digest,
    find_receipt,
    new_id,
    typed_relation_cells,
    validate_command_participants,
    composition_root,
    read_contained_scope,
    relation_members,
)
from .universal_cell import InvalidCell


DOMAIN_FIELDS = ("key", "title")
REQUIREMENT_FIELDS = (
    "id",
    "category",
    "title",
    "description",
    "status",
    "parameters",
    "evidence_reference",
    "last_verified",
    "authority_source",
    "bim_phase",
    "standard",
    "subgraph_reference",
)
SPEC_SECTION_FIELDS = (
    "key",
    "title",
    "level",
    "line_start",
    "line_end",
)
SPEC_REQUIREMENT_FIELDS = (
    "id",
    "section",
    "ordinal",
    "kind",
    "statement",
    "modality",
    "line_start",
    "line_end",
)


@dataclass(frozen=True, slots=True)
class RequirementGraphImportResult:
    root_id: str
    revision: int
    replayed: bool
    domain_roots: Mapping[str, str]
    requirement_roots: Mapping[str, str]
    relation_roots: tuple[str, ...]
    source_digest: str


@dataclass(frozen=True, slots=True)
class SpecificationGraphImportResult:
    root_id: str
    revision: int
    replayed: bool
    section_roots: Mapping[str, str]
    requirement_roots: Mapping[str, str]
    relation_roots: tuple[str, ...]
    source_digest: str


@dataclass(frozen=True, slots=True)
class _SpecificationRequirement:
    requirement_id: str
    section_key: str
    ordinal: int
    kind: str
    statement: str
    modality: str
    line_start: int
    line_end: int


@dataclass(frozen=True, slots=True)
class _SpecificationSection:
    key: str
    title: str
    level: int
    parent_key: str | None
    line_start: int
    line_end: int
    requirements: tuple[_SpecificationRequirement, ...]


def _object(value: object, message: str) -> Mapping[str, object]:
    if type(value) is not dict:
        raise InvalidCell(message)
    return value  # type: ignore[return-value]


def _text(value: object, message: str) -> str:
    if type(value) is not str or not value.strip():
        raise InvalidCell(message)
    return value.strip()


def _parameters(value: object) -> dict[str, object]:
    if type(value) is not list:
        raise InvalidCell("requirement parameters are not a list")
    found: dict[str, object] = {}
    for raw in value:
        item = _object(raw, "requirement parameter is not an object")
        if not {"k", "v"}.issubset(item) or set(item) - {"k", "v", "type"}:
            raise InvalidCell("requirement parameter fields are invalid")
        key = _text(item["k"], "requirement parameter key is invalid")
        if key in found:
            raise InvalidCell("requirement parameter key is duplicated")
        parameter = {"value": item["v"]}
        if "type" in item:
            parameter["type"] = _text(
                item["type"], "requirement parameter type is invalid"
            )
        found[key] = parameter
    return found


def _optional_source_text(
    source: Mapping[str, object], key: str
) -> str | None:
    value = source.get(key)
    if value is None or value == "":
        return None
    if type(value) is not str or not value.strip():
        raise InvalidCell("optional requirement text is invalid")
    return value.strip()


def _validated_source(source_bytes: bytes) -> tuple[Mapping[str, object], ...]:
    try:
        decoded = json.loads(source_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InvalidCell("accepted requirement source is invalid JSON") from exc
    if type(decoded) is not list or not decoded:
        raise InvalidCell("accepted requirement source has no domains")
    domains = tuple(
        _object(item, "accepted requirement domain is not an object")
        for item in decoded
    )
    domain_keys: set[str] = set()
    requirement_ids: set[str] = set()
    for domain in domains:
        if set(domain) != {"key", "title", "nodes", "wires", "cross"}:
            raise InvalidCell("accepted requirement domain fields are invalid")
        domain_key = _text(domain["key"], "accepted domain key is invalid")
        _text(domain["title"], "accepted domain title is invalid")
        if domain_key in domain_keys:
            raise InvalidCell("accepted domain key is duplicated")
        domain_keys.add(domain_key)
        if type(domain["nodes"]) is not list or type(domain["wires"]) is not list:
            raise InvalidCell("accepted domain nodes or wires are invalid")
        if type(domain["cross"]) is not list:
            raise InvalidCell("accepted domain cross relations are invalid")
        local_ids: set[str] = set()
        for raw_node in domain["nodes"]:  # type: ignore[union-attr]
            node = _object(raw_node, "accepted requirement is not an object")
            required = {
                "id", "cat", "title", "sub", "status", "params",
                "evidence_ref", "authority_source",
            }
            optional = {
                "last_verified", "bim_phase", "standard", "subgraph_ref",
            }
            if not required.issubset(node) or set(node) - required - optional:
                raise InvalidCell("accepted requirement fields are invalid")
            node_id = _text(node["id"], "accepted requirement id is invalid")
            if node_id in requirement_ids:
                raise InvalidCell("accepted requirement id is duplicated")
            requirement_ids.add(node_id)
            local_ids.add(node_id)
            for field in ("cat", "title", "sub", "status"):
                _text(node[field], "accepted requirement text is invalid")
            _parameters(node["params"])
            _optional_source_text(node, "evidence_ref")
            _text(node["authority_source"], "accepted authority source is invalid")
            for field in ("last_verified", "bim_phase", "standard", "subgraph_ref"):
                _optional_source_text(node, field)
        for raw_wire in domain["wires"]:  # type: ignore[union-attr]
            if (
                type(raw_wire) is not list
                or len(raw_wire) != 2
                or any(type(value) is not str for value in raw_wire)
                or set(raw_wire) - local_ids
            ):
                raise InvalidCell("accepted internal relation is invalid")
    for domain in domains:
        local_ids = {
            str(node["id"])
            for node in domain["nodes"]  # type: ignore[union-attr]
        }
        for raw_cross in domain["cross"]:  # type: ignore[union-attr]
            cross = _object(raw_cross, "accepted cross relation is not an object")
            if set(cross) != {"from", "to_domain", "why"}:
                raise InvalidCell("accepted cross relation fields are invalid")
            if (
                _text(cross["from"], "cross relation source is invalid")
                not in local_ids
                or _text(cross["to_domain"], "cross relation target is invalid")
                not in domain_keys
            ):
                raise InvalidCell("accepted cross relation endpoint is missing")
            _text(cross["why"], "accepted cross relation reason is invalid")
    return domains


_MODALITY_PATTERNS = (
    ("must-not", re.compile(r"\b(?:MUST NOT|SHALL NOT)\b")),
    ("must", re.compile(r"\b(?:MUST|REQUIRED|SHALL)\b")),
    ("should-not", re.compile(r"\bSHOULD NOT\b")),
    ("should", re.compile(r"\bSHOULD\b")),
    ("may", re.compile(r"\bMAY\b")),
)


def _spec_modality(statement: str) -> str:
    for name, pattern in _MODALITY_PATTERNS:
        if pattern.search(statement):
            return name
    return "declared"


def _section_key(title: str) -> str:
    numbered = re.match(r"^(\d+(?:\.\d+)*)\.?(?:\s+|$)", title)
    if numbered is not None:
        return numbered.group(1)
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    if not slug:
        raise InvalidCell("specification section has no stable source key")
    return slug


def _validated_specification_source(
    source_bytes: bytes,
) -> tuple[str, tuple[_SpecificationSection, ...]]:
    try:
        text = source_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InvalidCell("accepted specification source is not UTF-8") from exc
    tokens = MarkdownIt("commonmark").parse(text)
    if any(
        token.type == "html_block"
        or any(child.type == "html_inline" for child in (token.children or ()))
        for token in tokens
    ):
        raise InvalidCell("accepted specification contains executable HTML")
    title = ""
    current: dict[str, object] | None = None
    current_parent_key: str | None = None
    sections: list[dict[str, object]] = []

    def ensure_preamble(line_start: int) -> dict[str, object]:
        nonlocal current
        if current is None:
            current = {
                "key": "0",
                "title": "Preamble",
                "level": 1,
                "parent_key": None,
                "line_start": line_start,
                "line_end": line_start,
                "requirements": [],
            }
            sections.append(current)
        return current

    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.type == "heading_open":
            if index + 1 >= len(tokens) or tokens[index + 1].type != "inline":
                raise InvalidCell("specification heading has no text")
            heading = " ".join(tokens[index + 1].content.split())
            level = int(token.tag[1:])
            line_start = (token.map or [0, 0])[0] + 1
            if level == 1:
                if title:
                    raise InvalidCell("specification has more than one title")
                title = heading
            elif level in {2, 3}:
                key = _section_key(heading)
                if any(section["key"] == key for section in sections):
                    raise InvalidCell("specification section key is duplicated")
                if level == 2:
                    current_parent_key = key
                    parent_key = None
                else:
                    if current_parent_key is None:
                        raise InvalidCell(
                            "specification subsection has no parent section"
                        )
                    parent_key = current_parent_key
                current = {
                    "key": key,
                    "title": heading,
                    "level": level,
                    "parent_key": parent_key,
                    "line_start": line_start,
                    "line_end": line_start,
                    "requirements": [],
                }
                sections.append(current)
            index += 2
            continue
        if token.type == "paragraph_open":
            if index + 1 >= len(tokens) or tokens[index + 1].type != "inline":
                raise InvalidCell("specification paragraph has no content")
            statement = " ".join(tokens[index + 1].content.split())
            mapped = token.map or tokens[index + 1].map
            if statement and mapped is not None:
                target = ensure_preamble(mapped[0] + 1)
                requirements = target["requirements"]
                if not isinstance(requirements, list):
                    raise InvalidCell("specification section accumulator is invalid")
                ordinal = len(requirements) + 1
                requirements.append(_SpecificationRequirement(
                    "spec:%s:%03d" % (target["key"], ordinal),
                    str(target["key"]),
                    ordinal,
                    "statement",
                    statement,
                    _spec_modality(statement),
                    mapped[0] + 1,
                    mapped[1],
                ))
                target["line_end"] = max(int(target["line_end"]), mapped[1])
            index += 2
            continue
        if token.type in {"fence", "code_block"}:
            mapped = token.map
            statement = token.content.rstrip("\n")
            if statement and mapped is not None:
                target = ensure_preamble(mapped[0] + 1)
                requirements = target["requirements"]
                if not isinstance(requirements, list):
                    raise InvalidCell("specification section accumulator is invalid")
                ordinal = len(requirements) + 1
                requirements.append(_SpecificationRequirement(
                    "spec:%s:%03d" % (target["key"], ordinal),
                    str(target["key"]),
                    ordinal,
                    "code",
                    statement,
                    "declared",
                    mapped[0] + 1,
                    mapped[1],
                ))
                target["line_end"] = max(int(target["line_end"]), mapped[1])
        index += 1
    if not title or not sections:
        raise InvalidCell("accepted specification has no title or sections")
    built = tuple(
        _SpecificationSection(
            str(section["key"]),
            str(section["title"]),
            int(section["level"]),
            (
                str(section["parent_key"])
                if section["parent_key"] is not None
                else None
            ),
            int(section["line_start"]),
            int(section["line_end"]),
            tuple(section["requirements"]),  # type: ignore[arg-type]
        )
        for section in sections
    )
    line_ends = {section.key: section.line_end for section in built}
    for section in reversed(built):
        if section.parent_key is not None:
            line_ends[section.parent_key] = max(
                line_ends[section.parent_key], line_ends[section.key]
            )
    built = tuple(
        _SpecificationSection(
            section.key,
            section.title,
            section.level,
            section.parent_key,
            section.line_start,
            line_ends[section.key],
            section.requirements,
        )
        for section in built
    )
    child_keys = {
        section.parent_key
        for section in built
        if section.parent_key is not None
    }
    if any(
        not section.requirements and section.key not in child_keys
        for section in built
    ):
        raise InvalidCell("accepted specification contains an empty section")
    return title, built


IMPORT_CONNECTION = "requirement-link"


# The inspector's tabs are a thing the graph declares, not a default the
# projector invents. A scope that declares none should show none, which is
# only distinguishable from "never declared any" if the bootstrap declares
# something real.
SCOPE_PANELS = ("Properties",)


def _definition_cells(
    authority: UnifiedAuthority,
    *,
    name: str,
    fields: Iterable[str],
    evidence_roots: tuple[str, ...],
    source_digest: str,
    presentation: Mapping[str, object] | None = None,
) -> tuple[str, str, tuple]:
    definition_root = new_id()
    parameters = {
        field: {"editor": "structured" if field == "parameters" else "text"}
        for field in fields
    }
    spec = definition_spec(
        name,
        "accepted-" + source_digest[:12],
        "published",
        {},
        parameters,
        {
            IMPORT_CONNECTION: {
                # A requirement may be wired to many others, and an imported
                # source is read-only until it is revised through a command.
                "direction": "target",
                "multiple": True,
                "permission": "read",
            }
        },
        {"source-digest": source_digest},
        dict(presentation or {}),
        {"source-integrity": "required"},
        {"source-digest": source_digest},
        evidence_roots,
    )
    revision_root, _, revision_cells = build_definition_revision(authority, spec)
    definition_cells = typed_relation_cells(
        definition_root,
        authority.role("conforms-to"),
        authority.shape("definition"),
        ((authority.role("current-revision"), revision_root),),
    )
    return definition_root, revision_root, (*revision_cells, *definition_cells)


def _instance_cells(
    authority: UnifiedAuthority,
    *,
    definition_root: str,
    revision_root: str,
    values: Mapping[str, object],
    children: Iterable[tuple[str, str]] = (),
) -> tuple[str, tuple]:
    root = new_id()
    cells: list = []
    members: list[tuple[str, str]] = [
        (authority.role("definition"), definition_root),
        (authority.role("definition-revision"), revision_root),
    ]
    for key in sorted(values):
        property_root, property_cells = build_property(
            authority, key, values[key], owner_root=root
        )
        cells.extend(property_cells)
        members.append((authority.role("override"), property_root))
    members.extend(children)
    cells.extend(typed_relation_cells(
        root,
        authority.role("conforms-to"),
        authority.shape("instance"),
        members,
    ))
    return root, tuple(cells)


def _relation_cells_for_import(
    authority: UnifiedAuthority,
    *,
    source_root: str,
    target_root: str,
    properties: Mapping[str, object],
) -> tuple[str, tuple]:
    root = new_id()
    cells: list = []
    members: list[tuple[str, str]] = [
        (authority.role("source"), source_root),
        (authority.role("target"), target_root),
    ]
    # A drawn wire is a socket on both nodes. Naming the interface it
    # satisfies lets a reader ask the definition what that socket permits
    # instead of leaving the renderer to assume.
    properties = {"connection": IMPORT_CONNECTION, **dict(properties)}
    for key in sorted(properties):
        property_root, property_cells = build_property(
            authority, key, properties[key], owner_root=root
        )
        cells.extend(property_cells)
        members.append((authority.role("property"), property_root))
    cells.extend(typed_relation_cells(
        root,
        authority.role("conforms-to"),
        authority.shape("relation"),
        members,
    ))
    return root, tuple(cells)


def _read_result(
    authority: UnifiedAuthority,
    result: CommandResult,
    source_digest: str,
    *,
    scope_root: str,
    caller: CallerCommandCapability,
) -> RequirementGraphImportResult:
    snapshot = authority.store.at(result.revision)
    direct = relation_members(snapshot, result.root_id)
    contained = read_contained_scope(
        authority,
        result.root_id,
        scope_root=scope_root,
        caller=caller,
        at_revision=result.revision,
    )
    if contained.revision != result.revision:
        raise InvalidCell("imported requirement graph revision is not exact")
    domain_roots: dict[str, str] = {}
    requirement_roots: dict[str, str] = {}
    relation_roots = list(contained.relations)
    for member in direct:
        if member.role_id != authority.role("composition"):
            continue
        domain = contained.instances.get(member.participant_id)
        if domain is None:
            raise InvalidCell("imported requirement domain is not an instance")
        key = domain["values"]["key"]  # type: ignore[index]
        if type(key) is not str or key in domain_roots:
            raise InvalidCell("imported domain key is invalid or duplicated")
        domain_roots[key] = member.participant_id
        for nested in relation_members(snapshot, member.participant_id):
            if nested.role_id == authority.role("composition"):
                requirement = contained.instances.get(nested.participant_id)
                if requirement is None:
                    raise InvalidCell("imported requirement is not an instance")
                requirement_id = requirement["values"]["id"]  # type: ignore[index]
                if type(requirement_id) is not str or requirement_id in requirement_roots:
                    raise InvalidCell("imported requirement id is invalid or duplicated")
                requirement_roots[requirement_id] = nested.participant_id
    return RequirementGraphImportResult(
        result.root_id,
        result.revision,
        result.replayed,
        MappingProxyType(domain_roots),
        MappingProxyType(requirement_roots),
        tuple(relation_roots),
        source_digest,
    )


def import_requirement_graph(
    authority: UnifiedAuthority,
    source_bytes: bytes,
    *,
    expected_sha256: str,
    caller: CallerCommandCapability,
    command_id: str,
) -> RequirementGraphImportResult:
    """Verify and atomically import one accepted requirement graph revision."""
    source_digest = hashlib.sha256(source_bytes).hexdigest()
    if source_digest != expected_sha256.lower():
        raise InvalidCell("accepted requirement source digest does not match")
    domains = _validated_source(source_bytes)
    request_digest = digest({
        "intent": "import-requirement-graph",
        "source-digest": source_digest,
    })
    snapshot = authority.store.snapshot()
    grand_map_root = composition_root(authority, "Grand Map", caller=caller)
    authenticated, policy_proof = validate_command_participants(
        authority,
        snapshot,
        caller,
        command_id,
        intent="import-requirement-graph",
        request_digest=request_digest,
        object_root=grand_map_root,
        scope_root=grand_map_root,
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
        return _read_result(
            authority,
            CommandResult(
                existing.result_root,
                existing.result_revision,
                True,
                0,
                0,
                existing.root_id,
            ),
            source_digest,
            scope_root=grand_map_root,
            caller=caller,
        )

    cells: list = []
    label_root, label_cells = build_value(
        authority.roles,
        authority.codecs[CODEC_NAME],
        "Accepted requirement source " + source_digest[:12],
        shape_root=authority.shape("value"),
    )
    digest_root, digest_cells = build_value(
        authority.roles,
        authority.codecs[CODEC_NAME],
        source_digest,
        shape_root=authority.shape("value"),
    )
    evidence_root = new_id()
    cells.extend(label_cells)
    cells.extend(digest_cells)
    cells.extend(typed_relation_cells(
        evidence_root,
        authority.role("conforms-to"),
        authority.shape("composition"),
        (
            (authority.role("label"), label_root),
            (authority.role("content-digest"), digest_root),
        ),
    ))
    # One applicability relation per scope, named as evidence on every
    # definition in it. A definition cannot be asked which scope holds it --
    # relations only walk forwards -- so the revision carries the answer
    # instead, and revising a presentation contract can find the relation to
    # revise by reading its own evidence rather than searching the graph.
    import_root = new_id()
    panel_audience_root, panel_audience_cells = build_value(
        authority.roles,
        authority.codecs[CODEC_NAME],
        PANEL_AUDIENCE,
        shape_root=authority.shape("value"),
    )
    panel_applicability_root = new_id()
    cells.extend(panel_audience_cells)
    definition_evidence = (evidence_root, panel_applicability_root)
    domain_definition, domain_revision, domain_definition_cells = _definition_cells(
        authority,
        name="Domain composition",
        fields=DOMAIN_FIELDS,
        evidence_roots=definition_evidence,
        source_digest=source_digest,
        presentation={"panels": list(SCOPE_PANELS)},
    )
    requirement_definition, requirement_revision, requirement_definition_cells = (
        _definition_cells(
            authority,
            name="Requirement composition",
            fields=REQUIREMENT_FIELDS,
            evidence_roots=definition_evidence,
            source_digest=source_digest,
        )
    )
    cells.extend(domain_definition_cells)
    cells.extend(requirement_definition_cells)
    # The declared tabs exist as graph compositions, not only as contract
    # text: each carries its label and the definition that declared it, and
    # the scope's one applicability relation names which panels apply here.
    panel_members: list[tuple[str, str]] = [
        (authority.role("scope"), import_root),
        (authority.role("audience"), panel_audience_root),
    ]
    for panel_label in SCOPE_PANELS:
        panel_label_root, panel_label_cells = build_value(
            authority.roles,
            authority.codecs[CODEC_NAME],
            panel_label,
            shape_root=authority.shape("value"),
        )
        panel_root = new_id()
        cells.extend(panel_label_cells)
        cells.extend(typed_relation_cells(
            panel_root,
            authority.role("conforms-to"),
            authority.shape("composition"),
            (
                (authority.role("label"), panel_label_root),
                (authority.role("definition"), domain_definition),
            ),
        ))
        panel_members.append((authority.role("object"), panel_root))
    cells.extend(typed_relation_cells(
        panel_applicability_root,
        authority.role("conforms-to"),
        authority.shape("relation"),
        tuple(panel_members),
    ))

    domain_roots: dict[str, str] = {}
    requirement_roots: dict[str, str] = {}
    domain_cells: dict[str, list] = {}
    domain_children: dict[str, list[tuple[str, str]]] = {}
    for domain in domains:
        domain_key = str(domain["key"])
        domain_root = new_id()
        domain_roots[domain_key] = domain_root
        domain_cells[domain_key] = []
        domain_children[domain_key] = []
        for raw_node in domain["nodes"]:  # type: ignore[union-attr]
            node = _object(raw_node, "accepted requirement is not an object")
            requirement_id = str(node["id"])
            values = {
                "id": requirement_id,
                "category": node["cat"],
                "title": node["title"],
                "description": node["sub"],
                "status": node["status"],
                "parameters": _parameters(node["params"]),
                "evidence_reference": _optional_source_text(node, "evidence_ref"),
                "last_verified": _optional_source_text(node, "last_verified"),
                "authority_source": node["authority_source"],
                "bim_phase": _optional_source_text(node, "bim_phase"),
                "standard": _optional_source_text(node, "standard"),
                "subgraph_reference": _optional_source_text(
                    node, "subgraph_ref"
                ),
            }
            requirement_root, requirement_cells = _instance_cells(
                authority,
                definition_root=requirement_definition,
                revision_root=requirement_revision,
                values=values,
            )
            requirement_roots[requirement_id] = requirement_root
            domain_cells[domain_key].extend(requirement_cells)
            domain_children[domain_key].append(
                (authority.role("composition"), requirement_root)
            )

    relation_roots: list[str] = []
    cross_relations: list[tuple[str, str]] = []
    for domain in domains:
        domain_key = str(domain["key"])
        for raw_wire in domain["wires"]:  # type: ignore[union-attr]
            source_id, target_id = raw_wire
            relation_root, relation_cells = _relation_cells_for_import(
                authority,
                source_root=requirement_roots[source_id],
                target_root=requirement_roots[target_id],
                properties={"relation_kind": "internal"},
            )
            relation_roots.append(relation_root)
            domain_cells[domain_key].extend(relation_cells)
            domain_children[domain_key].append(
                (authority.role("relation"), relation_root)
            )
        for raw_cross in domain["cross"]:  # type: ignore[union-attr]
            cross = _object(raw_cross, "accepted cross relation is not an object")
            relation_root, relation_cells = _relation_cells_for_import(
                authority,
                source_root=requirement_roots[str(cross["from"])],
                target_root=domain_roots[str(cross["to_domain"])],
                properties={
                    "relation_kind": "cross-domain",
                    "reason": cross["why"],
                },
            )
            relation_roots.append(relation_root)
            cells.extend(relation_cells)
            cross_relations.append((authority.role("relation"), relation_root))

    import_members: list[tuple[str, str]] = [
        (authority.role("label"), label_root),
        (authority.role("evidence"), evidence_root),
        (authority.role("definition"), domain_definition),
        (authority.role("definition"), requirement_definition),
    ]
    for domain in domains:
        domain_key = str(domain["key"])
        domain_root = domain_roots[domain_key]
        values = {"key": domain_key, "title": domain["title"]}
        built_root, built_cells = _instance_cells(
            authority,
            definition_root=domain_definition,
            revision_root=domain_revision,
            values=values,
            children=domain_children[domain_key],
        )
        if built_root == domain_root:
            raise InvalidCell("domain identity was unexpectedly reused")
        replacements = {built_root: domain_root}
        rewritten = tuple(
            type(cell)(
                replacements.get(cell.id, cell.id),
                replacements.get(cell.link0, cell.link0),
                replacements.get(cell.link1, cell.link1),
                cell.atom,
            )
            for cell in built_cells
        )
        cells.extend(domain_cells[domain_key])
        cells.extend(rewritten)
        import_members.append((authority.role("composition"), domain_root))
    import_members.extend(cross_relations)
    cells.extend(typed_relation_cells(
        import_root,
        authority.role("conforms-to"),
        authority.shape("composition"),
        import_members,
    ))

    catalogue_patch = append_relation_members(
        snapshot,
        authority.manifest.catalogue_root,
        (
            (authority.role("definition"), domain_definition),
            (authority.role("definition"), requirement_definition),
        ),
    )
    grand_map_patch = append_relation_members(
        snapshot,
        grand_map_root,
        ((authority.role("composition"), import_root),),
    )
    result = commit_with_receipt(
        authority,
        snapshot,
        resource_create=(
            *cells,
            *catalogue_patch.create,
            *grand_map_patch.create,
        ),
        resource_replace=(
            *catalogue_patch.replace,
            *grand_map_patch.replace,
        ),
        authenticated=authenticated,
        result_root=import_root,
        policy_proof=policy_proof,
    )
    return _read_result(
        authority,
        result,
        source_digest,
        scope_root=grand_map_root,
        caller=caller,
    )


def _read_specification_result(
    authority: UnifiedAuthority,
    result: CommandResult,
    source_digest: str,
    *,
    scope_root: str,
    caller: CallerCommandCapability,
) -> SpecificationGraphImportResult:
    snapshot = authority.store.at(result.revision)
    direct = relation_members(snapshot, result.root_id)
    contained = read_contained_scope(
        authority,
        result.root_id,
        scope_root=scope_root,
        caller=caller,
        at_revision=result.revision,
    )
    if contained.revision != result.revision:
        raise InvalidCell("imported specification revision is not exact")
    section_roots: dict[str, str] = {}
    requirement_roots: dict[str, str] = {}
    relation_roots = list(contained.relations)
    for member in direct:
        if member.role_id != authority.role("composition"):
            continue
        section = contained.instances.get(member.participant_id)
        if section is None:
            raise InvalidCell("imported specification section is not an instance")
        key = section["values"]["key"]  # type: ignore[index]
        if type(key) is not str or key in section_roots:
            raise InvalidCell("imported specification section is invalid or duplicated")
        section_roots[key] = member.participant_id
        for nested in relation_members(snapshot, member.participant_id):
            if nested.role_id == authority.role("composition"):
                requirement = contained.instances.get(nested.participant_id)
                if requirement is None:
                    raise InvalidCell(
                        "imported specification requirement is not an instance"
                    )
                requirement_id = requirement["values"]["id"]  # type: ignore[index]
                if (
                    type(requirement_id) is not str
                    or requirement_id in requirement_roots
                ):
                    raise InvalidCell(
                        "imported specification requirement is invalid or duplicated"
                    )
                requirement_roots[requirement_id] = nested.participant_id
    return SpecificationGraphImportResult(
        result.root_id,
        result.revision,
        result.replayed,
        MappingProxyType(section_roots),
        MappingProxyType(requirement_roots),
        tuple(relation_roots),
        source_digest,
    )


def import_specification_graph(
    authority: UnifiedAuthority,
    source_bytes: bytes,
    *,
    expected_sha256: str,
    caller: CallerCommandCapability,
    command_id: str,
) -> SpecificationGraphImportResult:
    """Parse and atomically import one exact normative specification revision."""
    source_digest = hashlib.sha256(source_bytes).hexdigest()
    if source_digest != expected_sha256.lower():
        raise InvalidCell("accepted specification source digest does not match")
    title, sections = _validated_specification_source(source_bytes)
    request_digest = digest({
        "intent": "import-specification-graph",
        "source-digest": source_digest,
    })
    snapshot = authority.store.snapshot()
    governance_root = composition_root(authority, "Governance", caller=caller)
    authenticated, policy_proof = validate_command_participants(
        authority,
        snapshot,
        caller,
        command_id,
        intent="import-specification-graph",
        request_digest=request_digest,
        object_root=governance_root,
        scope_root=governance_root,
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
        return _read_specification_result(
            authority,
            CommandResult(
                existing.result_root,
                existing.result_revision,
                True,
                0,
                0,
                existing.root_id,
            ),
            source_digest,
            scope_root=governance_root,
            caller=caller,
        )

    cells: list = []
    label_root, label_cells = build_value(
        authority.roles,
        authority.codecs[CODEC_NAME],
        title,
        shape_root=authority.shape("value"),
    )
    digest_root, digest_cells = build_value(
        authority.roles,
        authority.codecs[CODEC_NAME],
        source_digest,
        shape_root=authority.shape("value"),
    )
    evidence_root = new_id()
    cells.extend((*label_cells, *digest_cells))
    cells.extend(typed_relation_cells(
        evidence_root,
        authority.role("conforms-to"),
        authority.shape("composition"),
        (
            (authority.role("label"), label_root),
            (authority.role("content-digest"), digest_root),
        ),
    ))
    section_definition, section_revision, section_definition_cells = (
        _definition_cells(
            authority,
            name="Specification section composition",
            fields=SPEC_SECTION_FIELDS,
            evidence_roots=(evidence_root,),
            source_digest=source_digest,
        )
    )
    requirement_definition, requirement_revision, requirement_definition_cells = (
        _definition_cells(
            authority,
            name="Specification requirement composition",
            fields=SPEC_REQUIREMENT_FIELDS,
            evidence_roots=(evidence_root,),
            source_digest=source_digest,
        )
    )
    cells.extend((*section_definition_cells, *requirement_definition_cells))

    section_roots: dict[str, str] = {}
    requirement_roots: dict[str, str] = {}
    relation_roots: list[str] = []
    section_relation_roots: list[str] = []
    for section in sections:
        children: list[tuple[str, str]] = []
        prior_requirement: str | None = None
        for requirement in section.requirements:
            requirement_root, requirement_cells = _instance_cells(
                authority,
                definition_root=requirement_definition,
                revision_root=requirement_revision,
                values={
                    "id": requirement.requirement_id,
                    "section": requirement.section_key,
                    "ordinal": requirement.ordinal,
                    "kind": requirement.kind,
                    "statement": requirement.statement,
                    "modality": requirement.modality,
                    "line_start": requirement.line_start,
                    "line_end": requirement.line_end,
                },
            )
            cells.extend(requirement_cells)
            requirement_roots[requirement.requirement_id] = requirement_root
            children.append((authority.role("composition"), requirement_root))
            if prior_requirement is not None:
                relation_root, relation_cells = _relation_cells_for_import(
                    authority,
                    source_root=prior_requirement,
                    target_root=requirement_root,
                    properties={},
                )
                cells.extend(relation_cells)
                relation_roots.append(relation_root)
                children.append((authority.role("relation"), relation_root))
            prior_requirement = requirement_root
        section_root, section_cells = _instance_cells(
            authority,
            definition_root=section_definition,
            revision_root=section_revision,
            values={
                "key": section.key,
                "title": section.title,
                "level": section.level,
                "line_start": section.line_start,
                "line_end": section.line_end,
            },
            children=children,
        )
        cells.extend(section_cells)
        section_roots[section.key] = section_root

    for section in sections:
        if section.parent_key is None:
            continue
        relation_root, relation_cells = _relation_cells_for_import(
            authority,
            source_root=section_roots[section.parent_key],
            target_root=section_roots[section.key],
            properties={},
        )
        cells.extend(relation_cells)
        relation_roots.append(relation_root)
        section_relation_roots.append(relation_root)

    import_root = new_id()
    cells.extend(typed_relation_cells(
        import_root,
        authority.role("conforms-to"),
        authority.shape("composition"),
        (
            (authority.role("label"), label_root),
            (authority.role("evidence"), evidence_root),
            (authority.role("definition"), section_definition),
            (authority.role("definition"), requirement_definition),
            *((authority.role("composition"), root) for root in section_roots.values()),
            *((authority.role("relation"), root) for root in section_relation_roots),
        ),
    ))
    catalogue_patch = append_relation_members(
        snapshot,
        authority.manifest.catalogue_root,
        (
            (authority.role("definition"), section_definition),
            (authority.role("definition"), requirement_definition),
        ),
    )
    governance_patch = append_relation_members(
        snapshot,
        governance_root,
        ((authority.role("composition"), import_root),),
    )
    result = commit_with_receipt(
        authority,
        snapshot,
        resource_create=(
            *cells,
            *catalogue_patch.create,
            *governance_patch.create,
        ),
        resource_replace=(
            *catalogue_patch.replace,
            *governance_patch.replace,
        ),
        authenticated=authenticated,
        result_root=import_root,
        policy_proof=policy_proof,
    )
    return _read_specification_result(
        authority,
        result,
        source_digest,
        scope_root=governance_root,
        caller=caller,
    )


__all__ = [
    "RequirementGraphImportResult",
    "SpecificationGraphImportResult",
    "import_requirement_graph",
    "import_specification_graph",
]
