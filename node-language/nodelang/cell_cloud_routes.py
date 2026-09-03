"""Graph-defined HTTP route bindings for the universal cloud request gate.

HTTP is only an adapter.  A protected route is an immutable relation whose
participants identify the action, object binding, interface, purpose, audience,
and state supplied to authorization.  The adapter may project this relation;
it may not invent route-local roles or permissions.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
import re
from types import MappingProxyType
from typing import Mapping

from .cell_protocols import (
    RelationMember,
    compose_relation_cells,
    prepare_append_relation_member,
    read_relation,
)
from .universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell, Snapshot


ROLE_NAMES = (
    "vocabulary-member",
    "route-member",
    "method",
    "path-template",
    "action",
    "object",
    "object-namespace",
    "object-path-parameter",
    "interface",
    "purpose",
    "audience",
    "classification",
    "lifecycle-state",
    "operational-state",
    "resource-lineage",
    "route-digest",
)

_METHOD = re.compile(r"^[A-Z][A-Z0-9!#$%&'*+.^_`|~-]{0,31}$")
_PATH_PARAMETER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_TEMPLATE_PARAMETER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]{0,63})(?::[^{}]+)?\}")
_MAX_PATH = 2048
_MAX_EXTERNAL_ID = 1024


class CloudRouteDenied(PermissionError):
    pass


@dataclass(frozen=True, slots=True)
class CloudRouteProtocol:
    root_id: str
    roles: Mapping[str, str]

    def role(self, name: str) -> str:
        try:
            return self.roles[name]
        except KeyError as exc:
            raise InvalidCell("unknown cloud-route role %r" % name) from exc


@dataclass(frozen=True, slots=True)
class CloudRouteProjection:
    root_id: str
    method: str
    path_template: str
    action_root: str
    object_root: str | None
    object_namespace: str | None
    object_path_parameter: str | None
    interface_root: str | None
    purpose_root: str | None
    audience_root: str | None
    classification_root: str | None
    lifecycle_state_root: str | None
    operational_state_root: str | None
    resource_lineage_roots: tuple[str, ...]
    digest: str


@dataclass(frozen=True, slots=True)
class ResolvedCloudRoute:
    route_root: str
    action_root: str
    object_root: str
    resource_lineage_roots: tuple[str, ...]
    interface_root: str | None
    purpose_root: str | None
    audience_root: str | None
    classification_root: str | None
    lifecycle_state_root: str | None
    operational_state_root: str | None


def _terminal(root_id: str, value: str) -> Cell:
    atom = value.encode("utf-8")
    if not atom:
        raise InvalidCell("cloud-route scalar cannot be empty")
    return Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, atom)


def _atom(snapshot: Snapshot, root_id: str, label: str) -> str:
    try:
        cell = snapshot.cells[root_id]
        if cell.link0 != NULL_CELL_ID or cell.link1 != NULL_CELL_ID:
            raise CloudRouteDenied("%s is not a scalar Cell" % label)
        return cell.atom.decode("utf-8")
    except (KeyError, UnicodeDecodeError) as exc:
        raise CloudRouteDenied("%s is missing or invalid" % label) from exc


def _for_role(
    members: tuple[RelationMember, ...], role_id: str
) -> tuple[str, ...]:
    return tuple(
        member.participant_id for member in members
        if member.role_id == role_id
    )


def _one(
    members: tuple[RelationMember, ...], role_id: str, label: str
) -> str:
    values = _for_role(members, role_id)
    if len(values) != 1:
        raise CloudRouteDenied("route requires exactly one %s" % label)
    return values[0]


def _optional_one(
    members: tuple[RelationMember, ...], role_id: str, label: str
) -> str | None:
    values = _for_role(members, role_id)
    if len(values) > 1:
        raise CloudRouteDenied("route permits at most one %s" % label)
    return values[0] if values else None


def _validate_method(method: str) -> str:
    canonical = str(method).upper()
    if not _METHOD.fullmatch(canonical):
        raise ValueError("invalid HTTP method")
    return canonical


def _validate_path_template(path_template: str) -> str:
    path = str(path_template)
    if (
        not path.startswith("/")
        or len(path) > _MAX_PATH
        or "?" in path
        or "#" in path
        or "//" in path
        or "\\" in path
    ):
        raise ValueError("invalid route path template")
    return path


def _route_payload(
    *,
    method: str,
    path_template: str,
    action_root: str,
    object_root: str | None,
    object_namespace: str | None,
    object_path_parameter: str | None,
    interface_root: str | None,
    purpose_root: str | None,
    audience_root: str | None,
    classification_root: str | None,
    lifecycle_state_root: str | None,
    operational_state_root: str | None,
    resource_lineage_roots: tuple[str, ...],
) -> bytes:
    return json.dumps(
        {
            "action": action_root,
            "audience": audience_root,
            "classification": classification_root,
            "interface": interface_root,
            "lifecycle_state": lifecycle_state_root,
            "method": method,
            "object": object_root,
            "object_namespace": object_namespace,
            "object_path_parameter": object_path_parameter,
            "operational_state": operational_state_root,
            "path_template": path_template,
            "purpose": purpose_root,
            "resource_lineage": sorted(set(resource_lineage_roots)),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def _digest(**fields: object) -> str:
    return hashlib.sha256(_route_payload(**fields)).hexdigest()


def bootstrap_cloud_route_protocol(
    store: CellStore, *, prefix: str = "cloud-route-protocol"
) -> CloudRouteProtocol:
    roles = {name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES}
    root_id = prefix + ":root"
    relation = compose_relation_cells(
        ((roles["vocabulary-member"], root) for root in roles.values()),
        relation_id=root_id,
    )
    cells = tuple(_terminal(root, name) for name, root in roles.items())
    snapshot = store.snapshot()
    store.commit(snapshot.revision, create=(*cells, *relation.cells))
    return CloudRouteProtocol(root_id, MappingProxyType(roles))


def project_cloud_route_protocol(
    snapshot: Snapshot, *, prefix: str = "cloud-route-protocol"
) -> CloudRouteProtocol:
    roles = {name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES}
    root_id = prefix + ":root"
    if any(root not in snapshot.cells for root in (root_id, *roles.values())):
        raise InvalidCell("cloud-route protocol is incomplete")
    return CloudRouteProtocol(root_id, MappingProxyType(roles))


def build_cloud_route(
    store: CellStore,
    protocol: CloudRouteProtocol,
    *,
    route_id: str,
    method: str,
    path_template: str,
    action_root: str,
    object_root: str | None = None,
    object_namespace: str | None = None,
    object_path_parameter: str | None = None,
    interface_root: str | None = None,
    purpose_root: str | None = None,
    audience_root: str | None = None,
    classification_root: str | None = None,
    lifecycle_state_root: str | None = None,
    operational_state_root: str | None = None,
    resource_lineage_roots: tuple[str, ...] = (),
) -> str:
    """Create and register one immutable protected-route relation."""
    method = _validate_method(method)
    path_template = _validate_path_template(path_template)
    static = object_root is not None
    dynamic = object_namespace is not None or object_path_parameter is not None
    if static == dynamic:
        raise ValueError(
            "route needs either one static object or one dynamic object binding"
        )
    if dynamic:
        if not object_namespace or not object_path_parameter:
            raise ValueError("dynamic object binding is incomplete")
        if not _PATH_PARAMETER.fullmatch(object_path_parameter):
            raise ValueError("invalid object path-parameter name")
        if object_path_parameter not in _TEMPLATE_PARAMETER.findall(path_template):
            raise ValueError("object path parameter is absent from route template")
    lineage = tuple(dict.fromkeys(resource_lineage_roots))
    fields = {
        "method": method,
        "path_template": path_template,
        "action_root": action_root,
        "object_root": object_root,
        "object_namespace": object_namespace,
        "object_path_parameter": object_path_parameter,
        "interface_root": interface_root,
        "purpose_root": purpose_root,
        "audience_root": audience_root,
        "classification_root": classification_root,
        "lifecycle_state_root": lifecycle_state_root,
        "operational_state_root": operational_state_root,
        "resource_lineage_roots": lineage,
    }
    digest = _digest(**fields)
    snapshot = store.snapshot()
    if route_id in snapshot.cells:
        raise InvalidCell("cloud route identity already exists")
    for existing in list_cloud_routes(snapshot, protocol):
        if existing.method == method and existing.path_template == path_template:
            raise InvalidCell("HTTP method/path pair is already registered")

    scalar_values: tuple[tuple[str, str], ...] = tuple(
        (name, value) for name, value in (
            ("method", method),
            ("path-template", path_template),
            ("object-namespace", object_namespace),
            ("object-path-parameter", object_path_parameter),
            ("route-digest", digest),
        ) if value is not None
    )
    scalar_roots = {
        name: "%s:field:%s" % (route_id, name) for name, _ in scalar_values
    }
    members: list[tuple[str, str]] = [
        (protocol.role("method"), scalar_roots["method"]),
        (protocol.role("path-template"), scalar_roots["path-template"]),
        (protocol.role("action"), action_root),
    ]
    if object_root is not None:
        members.append((protocol.role("object"), object_root))
    if object_namespace is not None:
        members.extend((
            (protocol.role("object-namespace"), scalar_roots["object-namespace"]),
            (
                protocol.role("object-path-parameter"),
                scalar_roots["object-path-parameter"],
            ),
        ))
    for role, participant in (
        ("interface", interface_root),
        ("purpose", purpose_root),
        ("audience", audience_root),
        ("classification", classification_root),
        ("lifecycle-state", lifecycle_state_root),
        ("operational-state", operational_state_root),
    ):
        if participant is not None:
            members.append((protocol.role(role), participant))
    members.extend(
        (protocol.role("resource-lineage"), root) for root in lineage
    )
    members.append((protocol.role("route-digest"), scalar_roots["route-digest"]))
    relation = compose_relation_cells(members, relation_id=route_id)
    registry_patch = prepare_append_relation_member(
        snapshot,
        protocol.root_id,
        protocol.role("route-member"),
        route_id,
        budget=100_000,
    )
    scalars = tuple(
        _terminal(scalar_roots[name], value) for name, value in scalar_values
    )
    store.commit(
        snapshot.revision,
        create=(*scalars, *relation.cells, *registry_patch.create),
        replace=registry_patch.replace,
    )
    read_cloud_route(store.snapshot(), protocol, route_id)
    return route_id


def read_cloud_route(
    snapshot: Snapshot,
    protocol: CloudRouteProtocol,
    route_root: str,
) -> CloudRouteProjection:
    registered = _for_role(
        read_relation(snapshot, protocol.root_id, budget=100_000),
        protocol.role("route-member"),
    )
    if route_root not in registered:
        raise CloudRouteDenied("cloud route is not protocol-registered")
    members = read_relation(snapshot, route_root, budget=256)
    allowed = {protocol.role(name) for name in ROLE_NAMES[2:]}
    if any(member.role_id not in allowed for member in members):
        raise CloudRouteDenied("cloud route contains an undeclared field")

    method = _validate_method(_atom(
        snapshot, _one(members, protocol.role("method"), "method"), "method"
    ))
    path_template = _validate_path_template(_atom(
        snapshot,
        _one(members, protocol.role("path-template"), "path template"),
        "path template",
    ))
    object_root = _optional_one(members, protocol.role("object"), "object")
    namespace_root = _optional_one(
        members, protocol.role("object-namespace"), "object namespace"
    )
    parameter_root = _optional_one(
        members,
        protocol.role("object-path-parameter"),
        "object path parameter",
    )
    object_namespace = (
        _atom(snapshot, namespace_root, "object namespace")
        if namespace_root else None
    )
    object_path_parameter = (
        _atom(snapshot, parameter_root, "object path parameter")
        if parameter_root else None
    )
    static = object_root is not None
    dynamic = object_namespace is not None or object_path_parameter is not None
    if static == dynamic or (
        dynamic and (not object_namespace or not object_path_parameter)
    ):
        raise CloudRouteDenied("cloud route object binding is ambiguous")
    action_root = _one(members, protocol.role("action"), "action")
    interface_root = _optional_one(
        members, protocol.role("interface"), "interface"
    )
    purpose_root = _optional_one(members, protocol.role("purpose"), "purpose")
    audience_root = _optional_one(
        members, protocol.role("audience"), "audience"
    )
    classification_root = _optional_one(
        members, protocol.role("classification"), "classification"
    )
    lifecycle_state_root = _optional_one(
        members, protocol.role("lifecycle-state"), "lifecycle state"
    )
    operational_state_root = _optional_one(
        members, protocol.role("operational-state"), "operational state"
    )
    lineage = _for_role(members, protocol.role("resource-lineage"))
    digest_root = _one(
        members, protocol.role("route-digest"), "route digest"
    )
    digest = _atom(snapshot, digest_root, "route digest")
    expected = _digest(
        method=method,
        path_template=path_template,
        action_root=action_root,
        object_root=object_root,
        object_namespace=object_namespace,
        object_path_parameter=object_path_parameter,
        interface_root=interface_root,
        purpose_root=purpose_root,
        audience_root=audience_root,
        classification_root=classification_root,
        lifecycle_state_root=lifecycle_state_root,
        operational_state_root=operational_state_root,
        resource_lineage_roots=lineage,
    )
    if not secrets_compare(digest, expected):
        raise CloudRouteDenied("cloud route digest mismatch")
    return CloudRouteProjection(
        route_root,
        method,
        path_template,
        action_root,
        object_root,
        object_namespace,
        object_path_parameter,
        interface_root,
        purpose_root,
        audience_root,
        classification_root,
        lifecycle_state_root,
        operational_state_root,
        lineage,
        digest,
    )


def secrets_compare(left: str, right: str) -> bool:
    """Constant-time compare without making route digests into credentials."""
    return hmac.compare_digest(left, right)


def list_cloud_routes(
    snapshot: Snapshot, protocol: CloudRouteProtocol
) -> tuple[CloudRouteProjection, ...]:
    roots = _for_role(
        read_relation(snapshot, protocol.root_id, budget=100_000),
        protocol.role("route-member"),
    )
    if len(roots) != len(set(roots)):
        raise CloudRouteDenied("cloud-route registry contains duplicates")
    return tuple(read_cloud_route(snapshot, protocol, root) for root in roots)


def find_cloud_route(
    snapshot: Snapshot,
    protocol: CloudRouteProtocol,
    *,
    method: str,
    path_template: str,
) -> CloudRouteProjection:
    method = _validate_method(method)
    path_template = _validate_path_template(path_template)
    matches = tuple(
        route for route in list_cloud_routes(snapshot, protocol)
        if route.method == method and route.path_template == path_template
    )
    if len(matches) != 1:
        raise CloudRouteDenied("request has no unique registered cloud route")
    return matches[0]


def external_object_root(namespace: str, external_id: str) -> str:
    """Return a pseudonymous, deterministic graph identity for an adapter ID."""
    namespace_bytes = str(namespace).encode("utf-8")
    value_bytes = str(external_id).encode("utf-8")
    if not namespace_bytes or not value_bytes or len(value_bytes) > _MAX_EXTERNAL_ID:
        raise ValueError("external object identity is missing or too large")
    framed = (
        len(namespace_bytes).to_bytes(4, "big") + namespace_bytes
        + len(value_bytes).to_bytes(4, "big") + value_bytes
    )
    return "external-object:sha256:" + hashlib.sha256(framed).hexdigest()


def provision_external_object(
    store: CellStore, *, namespace: str, external_id: str
) -> str:
    """Materialize only the pseudonymous identity, never the raw adapter ID."""
    root = external_object_root(namespace, external_id)
    atom = ("external-object-reference:" + root.rsplit(":", 1)[-1]).encode("ascii")
    snapshot = store.snapshot()
    existing = snapshot.cells.get(root)
    expected = Cell(root, NULL_CELL_ID, NULL_CELL_ID, atom)
    if existing is None:
        store.commit(snapshot.revision, create=(expected,))
    elif existing != expected:
        raise InvalidCell("external object identity drifted")
    return root


def resolve_cloud_route(
    snapshot: Snapshot,
    route: CloudRouteProjection,
    *,
    path_parameters: Mapping[str, object] | None = None,
) -> ResolvedCloudRoute:
    if route.object_root is not None:
        object_root = route.object_root
    else:
        parameters = path_parameters or {}
        assert route.object_namespace is not None
        assert route.object_path_parameter is not None
        if route.object_path_parameter not in parameters:
            raise CloudRouteDenied("required object path parameter is absent")
        object_root = external_object_root(
            route.object_namespace,
            str(parameters[route.object_path_parameter]),
        )
    if object_root not in snapshot.cells:
        raise CloudRouteDenied("resolved route object is not graph-provisioned")
    return ResolvedCloudRoute(
        route.root_id,
        route.action_root,
        object_root,
        route.resource_lineage_roots,
        route.interface_root,
        route.purpose_root,
        route.audience_root,
        route.classification_root,
        route.lifecycle_state_root,
        route.operational_state_root,
    )


__all__ = [
    "CloudRouteDenied",
    "CloudRouteProjection",
    "CloudRouteProtocol",
    "ResolvedCloudRoute",
    "bootstrap_cloud_route_protocol",
    "build_cloud_route",
    "external_object_root",
    "find_cloud_route",
    "list_cloud_routes",
    "project_cloud_route_protocol",
    "provision_external_object",
    "read_cloud_route",
    "resolve_cloud_route",
]
