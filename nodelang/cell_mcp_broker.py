"""Graph-native MCP server and tool admission records.

The Universal Cell graph records only a released adapter binding, an opaque
local configuration fingerprint, negotiated capability and manifest digests,
and exact tool identity/schema digests.  MCP credentials, endpoint values,
raw manifests, tool names, arguments, outputs, and live client handles remain
inside the admitted local adapter runtime.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
import time
from types import MappingProxyType
from typing import Iterable, Mapping

from .cell_protocols import (
    CellBatch,
    RelationMember,
    compose_relation_cells,
    prepare_append_relation_member,
    read_relation,
)
from .universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell, Snapshot


ROLE_NAMES = (
    "vocabulary-member", "registry-member", "protocol-registry",
    "server-adapter", "server-transport", "server-config-digest",
    "server-datatype", "server-created-at", "negotiation-server",
    "negotiation-session", "negotiation-work", "negotiation-version",
    "negotiation-capabilities-digest", "negotiation-manifest-digest",
    "negotiation-observed-at", "negotiation-expires-at",
    "tool-negotiation", "tool-name-digest", "tool-schema-digest",
    "tool-datatype", "tool-provider",
)
REGISTRY_NAMES = ("server", "negotiation", "tool")

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_MCP_VERSION = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_TRANSPORTS = frozenset({"stdio", "https"})
_MAX_TOOL_COUNT = 256
_MAX_NEGOTIATION_LIFETIME_SECONDS = 3600.0


@dataclass(frozen=True, slots=True)
class McpBrokerProtocol:
    root_id: str
    roles: Mapping[str, str]
    registries: Mapping[str, str]

    def role(self, name: str) -> str:
        try:
            return self.roles[name]
        except KeyError as exc:
            raise InvalidCell("unknown MCP broker role %r" % name) from exc

    def registry(self, name: str) -> str:
        try:
            return self.registries[name]
        except KeyError as exc:
            raise InvalidCell("unknown MCP broker registry %r" % name) from exc


@dataclass(frozen=True, slots=True)
class McpServerProjection:
    root_id: str
    adapter_root: str
    transport: str
    config_digest: str
    datatype_roots: tuple[str, ...]
    created_at: float


@dataclass(frozen=True, slots=True)
class McpNegotiationProjection:
    root_id: str
    server_root: str
    session_root: str
    work_root: str
    protocol_version: str
    capabilities_digest: str
    manifest_digest: str
    observed_at: float
    expires_at: float


@dataclass(frozen=True, slots=True)
class McpToolProjection:
    root_id: str
    negotiation_root: str
    name_digest: str
    schema_digest: str
    datatype_root: str
    provider_root: str


def _terminal(root_id: str, value: object) -> Cell:
    return Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, str(value).encode("utf-8"))


def _text(snapshot: Snapshot, root_id: str, label: str) -> str:
    try:
        cell = snapshot.cells[root_id]
    except KeyError as exc:
        raise InvalidCell("%s Cell is missing" % label) from exc
    if cell.link0 != NULL_CELL_ID or cell.link1 != NULL_CELL_ID:
        raise InvalidCell("%s must be terminal" % label)
    try:
        return cell.atom.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InvalidCell("%s must be UTF-8" % label) from exc


def _one(members: Iterable[RelationMember], role_id: str, label: str) -> str:
    values = tuple(member.participant_id for member in members if member.role_id == role_id)
    if len(values) != 1:
        raise InvalidCell("%s requires exactly one participant" % label)
    return values[0]


def _many(members: Iterable[RelationMember], role_id: str) -> tuple[str, ...]:
    return tuple(member.participant_id for member in members if member.role_id == role_id)


def _closed(members: Iterable[RelationMember], allowed: Iterable[str], label: str) -> None:
    allowed_roles = frozenset(allowed)
    if any(member.role_id not in allowed_roles for member in members):
        raise InvalidCell("%s has an undeclared role" % label)


def _registered(
    snapshot: Snapshot,
    protocol: McpBrokerProtocol,
    name: str,
    root_id: str,
) -> bool:
    return sum(
        member.role_id == protocol.role("registry-member")
        and member.participant_id == root_id
        for member in read_relation(snapshot, protocol.registry(name), budget=100_000)
    ) == 1


def _require_digest(value: object, label: str) -> str:
    if type(value) is not str or _DIGEST.fullmatch(value) is None:
        raise InvalidCell("%s must be a SHA-256 hexadecimal digest" % label)
    return value


def _require_time(value: object, label: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(float(value)):
        raise InvalidCell("%s is invalid" % label)
    return float(value)


def _read_time(value: object, label: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise InvalidCell("%s is invalid" % label) from exc
    if not math.isfinite(parsed):
        raise InvalidCell("%s is invalid" % label)
    return parsed


def _require_version(value: object) -> str:
    if type(value) is not str or _MCP_VERSION.fullmatch(value) is None:
        raise InvalidCell("MCP protocol version is invalid")
    try:
        time.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise InvalidCell("MCP protocol version is invalid") from exc
    return value


def _require_transport(value: object) -> str:
    if type(value) is not str or value not in _TRANSPORTS:
        raise InvalidCell("MCP transport is not admitted")
    return value


def bootstrap_mcp_broker_protocol(
    store: CellStore,
    *,
    prefix: str = "app:mcp-broker:v1",
) -> McpBrokerProtocol:
    """Create or verify the append-only MCP admission vocabulary."""
    root_id = prefix + ":root"
    roles = MappingProxyType({name: prefix + ":role:" + name for name in ROLE_NAMES})
    registries = MappingProxyType({name: prefix + ":registry:" + name for name in REGISTRY_NAMES})
    snapshot = store.snapshot()
    if root_id not in snapshot.cells:
        batch = CellBatch(store)
        for name, root in roles.items():
            batch.add(_terminal(root, name))
        for root in registries.values():
            batch.relation((), relation_id=root)
        batch.relation(
            (
                *((roles["vocabulary-member"], root) for root in roles.values()),
                *((roles["protocol-registry"], root) for root in registries.values()),
            ),
            relation_id=root_id,
        )
        batch.commit()
        snapshot = store.snapshot()
    members = read_relation(snapshot, root_id, budget=100_000)
    _closed(
        members,
        (roles["vocabulary-member"], roles["protocol-registry"]),
        "MCP broker protocol",
    )
    if set(_many(members, roles["vocabulary-member"])) != set(roles.values()):
        raise InvalidCell("MCP broker vocabulary drifted")
    if set(_many(members, roles["protocol-registry"])) != set(registries.values()):
        raise InvalidCell("MCP broker registry wiring drifted")
    for root in registries.values():
        read_relation(snapshot, root, budget=100_000)
    return McpBrokerProtocol(root_id, roles, registries)


def register_mcp_server(
    store: CellStore,
    protocol: McpBrokerProtocol,
    *,
    server_id: str,
    adapter_root: str,
    transport: str,
    config_digest: str,
    datatype_roots: Iterable[str],
    created_at: float | None = None,
) -> McpServerProjection:
    """Register a local MCP configuration by fingerprint, never by value."""
    transport = _require_transport(transport)
    config_digest = _require_digest(config_digest, "MCP server configuration digest")
    datatypes = tuple(dict.fromkeys(datatype_roots))
    if not datatypes:
        raise InvalidCell("MCP server requires at least one data class")
    timestamp = time.time() if created_at is None else _require_time(created_at, "MCP server timestamp")
    snapshot = store.snapshot()
    if server_id in snapshot.cells:
        return read_mcp_server(snapshot, protocol, server_id)
    if adapter_root not in snapshot.cells or any(root not in snapshot.cells for root in datatypes):
        raise InvalidCell("MCP server adapter or data class is missing")
    for member in read_relation(snapshot, protocol.registry("server"), budget=100_000):
        if member.role_id != protocol.role("registry-member"):
            continue
        existing = read_mcp_server(snapshot, protocol, member.participant_id)
        if (
            existing.adapter_root == adapter_root
            and existing.transport == transport
            and existing.config_digest == config_digest
            and existing.datatype_roots == datatypes
        ):
            return existing
    values = {
        "transport": server_id + ":transport",
        "config": server_id + ":config-digest",
        "created": server_id + ":created-at",
    }
    relation = compose_relation_cells(
        (
            (protocol.role("server-adapter"), adapter_root),
            (protocol.role("server-transport"), values["transport"]),
            (protocol.role("server-config-digest"), values["config"]),
            *((protocol.role("server-datatype"), root) for root in datatypes),
            (protocol.role("server-created-at"), values["created"]),
        ),
        relation_id=server_id,
    )
    patch = prepare_append_relation_member(
        snapshot,
        protocol.registry("server"),
        protocol.role("registry-member"),
        server_id,
        budget=100_000,
    )
    store.commit(
        snapshot.revision,
        create=(
            _terminal(values["transport"], transport),
            _terminal(values["config"], config_digest),
            _terminal(values["created"], repr(timestamp)),
            *relation.cells,
            *patch.create,
        ),
        replace=patch.replace,
    )
    return read_mcp_server(store.snapshot(), protocol, server_id)


def read_mcp_server(
    snapshot: Snapshot,
    protocol: McpBrokerProtocol,
    server_root: str,
) -> McpServerProjection:
    if not _registered(snapshot, protocol, "server", server_root):
        raise InvalidCell("MCP server is not registered exactly once")
    members = read_relation(snapshot, server_root, budget=100_000)
    _closed(
        members,
        tuple(protocol.role(name) for name in (
            "server-adapter", "server-transport", "server-config-digest",
            "server-datatype", "server-created-at",
        )),
        "MCP server",
    )
    server = McpServerProjection(
        server_root,
        _one(members, protocol.role("server-adapter"), "MCP server adapter"),
        _require_transport(_text(
            snapshot,
            _one(members, protocol.role("server-transport"), "MCP server transport"),
            "MCP server transport",
        )),
        _require_digest(_text(
            snapshot,
            _one(members, protocol.role("server-config-digest"), "MCP server configuration digest"),
            "MCP server configuration digest",
        ), "MCP server configuration digest"),
        _many(members, protocol.role("server-datatype")),
        _read_time(_text(
            snapshot,
            _one(members, protocol.role("server-created-at"), "MCP server timestamp"),
            "MCP server timestamp",
        ), "MCP server timestamp"),
    )
    if (
        server.adapter_root not in snapshot.cells
        or not server.datatype_roots
        or len(server.datatype_roots) != len(set(server.datatype_roots))
        or any(root not in snapshot.cells for root in server.datatype_roots)
    ):
        raise InvalidCell("MCP server binding is invalid")
    return server


def record_mcp_negotiation(
    store: CellStore,
    protocol: McpBrokerProtocol,
    *,
    negotiation_id: str,
    server_root: str,
    session_root: str,
    work_root: str,
    protocol_version: str,
    capabilities_digest: str,
    manifest_digest: str,
    observed_at: float | None = None,
    expires_at: float,
) -> McpNegotiationProjection:
    """Record one bounded MCP handshake without retaining its raw manifest."""
    protocol_version = _require_version(protocol_version)
    capabilities_digest = _require_digest(capabilities_digest, "MCP capability digest")
    manifest_digest = _require_digest(manifest_digest, "MCP tool manifest digest")
    timestamp = time.time() if observed_at is None else _require_time(observed_at, "MCP negotiation timestamp")
    expiry = _require_time(expires_at, "MCP negotiation expiry")
    if expiry <= timestamp or expiry - timestamp > _MAX_NEGOTIATION_LIFETIME_SECONDS:
        raise InvalidCell("MCP negotiation lifetime is invalid")
    snapshot = store.snapshot()
    if negotiation_id in snapshot.cells:
        raise InvalidCell("MCP negotiation already exists")
    read_mcp_server(snapshot, protocol, server_root)
    if session_root not in snapshot.cells or work_root not in snapshot.cells:
        raise InvalidCell("MCP negotiation session or Work is missing")
    values = {
        "version": negotiation_id + ":version",
        "capabilities": negotiation_id + ":capabilities-digest",
        "manifest": negotiation_id + ":manifest-digest",
        "observed": negotiation_id + ":observed-at",
        "expires": negotiation_id + ":expires-at",
    }
    relation = compose_relation_cells(
        (
            (protocol.role("negotiation-server"), server_root),
            (protocol.role("negotiation-session"), session_root),
            (protocol.role("negotiation-work"), work_root),
            (protocol.role("negotiation-version"), values["version"]),
            (protocol.role("negotiation-capabilities-digest"), values["capabilities"]),
            (protocol.role("negotiation-manifest-digest"), values["manifest"]),
            (protocol.role("negotiation-observed-at"), values["observed"]),
            (protocol.role("negotiation-expires-at"), values["expires"]),
        ),
        relation_id=negotiation_id,
    )
    patch = prepare_append_relation_member(
        snapshot,
        protocol.registry("negotiation"),
        protocol.role("registry-member"),
        negotiation_id,
        budget=100_000,
    )
    store.commit(
        snapshot.revision,
        create=(
            _terminal(values["version"], protocol_version),
            _terminal(values["capabilities"], capabilities_digest),
            _terminal(values["manifest"], manifest_digest),
            _terminal(values["observed"], repr(timestamp)),
            _terminal(values["expires"], repr(expiry)),
            *relation.cells,
            *patch.create,
        ),
        replace=patch.replace,
    )
    return read_mcp_negotiation(store.snapshot(), protocol, negotiation_id)


def read_mcp_negotiation(
    snapshot: Snapshot,
    protocol: McpBrokerProtocol,
    negotiation_root: str,
) -> McpNegotiationProjection:
    if not _registered(snapshot, protocol, "negotiation", negotiation_root):
        raise InvalidCell("MCP negotiation is not registered exactly once")
    members = read_relation(snapshot, negotiation_root, budget=100_000)
    _closed(
        members,
        tuple(protocol.role(name) for name in (
            "negotiation-server", "negotiation-session", "negotiation-work",
            "negotiation-version", "negotiation-capabilities-digest",
            "negotiation-manifest-digest", "negotiation-observed-at",
            "negotiation-expires-at",
        )),
        "MCP negotiation",
    )
    values = {
        name: _one(members, protocol.role(role), "MCP negotiation " + name)
        for name, role in (
            ("server", "negotiation-server"), ("session", "negotiation-session"),
            ("work", "negotiation-work"), ("version", "negotiation-version"),
            ("capabilities", "negotiation-capabilities-digest"),
            ("manifest", "negotiation-manifest-digest"),
            ("observed", "negotiation-observed-at"),
            ("expires", "negotiation-expires-at"),
        )
    }
    negotiation = McpNegotiationProjection(
        negotiation_root,
        values["server"], values["session"], values["work"],
        _require_version(_text(snapshot, values["version"], "MCP negotiation version")),
        _require_digest(_text(snapshot, values["capabilities"], "MCP capability digest"), "MCP capability digest"),
        _require_digest(_text(snapshot, values["manifest"], "MCP tool manifest digest"), "MCP tool manifest digest"),
        _read_time(_text(snapshot, values["observed"], "MCP negotiation timestamp"), "MCP negotiation timestamp"),
        _read_time(_text(snapshot, values["expires"], "MCP negotiation expiry"), "MCP negotiation expiry"),
    )
    if (
        negotiation.expires_at <= negotiation.observed_at
        or negotiation.expires_at - negotiation.observed_at > _MAX_NEGOTIATION_LIFETIME_SECONDS
        or negotiation.session_root not in snapshot.cells
        or negotiation.work_root not in snapshot.cells
    ):
        raise InvalidCell("MCP negotiation binding is invalid")
    read_mcp_server(snapshot, protocol, negotiation.server_root)
    return negotiation


def register_mcp_tool(
    store: CellStore,
    protocol: McpBrokerProtocol,
    *,
    tool_id: str,
    negotiation_root: str,
    name_digest: str,
    schema_digest: str,
    datatype_root: str,
    provider_root: str,
) -> McpToolProjection:
    """Bind one negotiated tool identity to one graph-held connector provider."""
    name_digest = _require_digest(name_digest, "MCP tool name digest")
    schema_digest = _require_digest(schema_digest, "MCP tool schema digest")
    snapshot = store.snapshot()
    if tool_id in snapshot.cells:
        return read_mcp_tool(snapshot, protocol, tool_id)
    negotiation = read_mcp_negotiation(snapshot, protocol, negotiation_root)
    if time.time() >= negotiation.expires_at:
        raise InvalidCell("MCP negotiation has expired")
    server = read_mcp_server(snapshot, protocol, negotiation.server_root)
    if datatype_root not in server.datatype_roots or provider_root not in snapshot.cells:
        raise InvalidCell("MCP tool provider binding is invalid")
    tools = tuple(
        member.participant_id
        for member in read_relation(snapshot, protocol.registry("tool"), budget=100_000)
        if member.role_id == protocol.role("registry-member")
    )
    matching = 0
    for root in tools:
        tool = read_mcp_tool(snapshot, protocol, root)
        if tool.negotiation_root == negotiation_root:
            matching += 1
            if tool.name_digest == name_digest:
                raise InvalidCell("MCP tool identity is already registered")
    if matching >= _MAX_TOOL_COUNT:
        raise InvalidCell("MCP negotiation tool count exceeds its bound")
    values = {
        "name": tool_id + ":name-digest",
        "schema": tool_id + ":schema-digest",
    }
    relation = compose_relation_cells(
        (
            (protocol.role("tool-negotiation"), negotiation_root),
            (protocol.role("tool-name-digest"), values["name"]),
            (protocol.role("tool-schema-digest"), values["schema"]),
            (protocol.role("tool-datatype"), datatype_root),
            (protocol.role("tool-provider"), provider_root),
        ),
        relation_id=tool_id,
    )
    patch = prepare_append_relation_member(
        snapshot,
        protocol.registry("tool"),
        protocol.role("registry-member"),
        tool_id,
        budget=100_000,
    )
    store.commit(
        snapshot.revision,
        create=(
            _terminal(values["name"], name_digest),
            _terminal(values["schema"], schema_digest),
            *relation.cells,
            *patch.create,
        ),
        replace=patch.replace,
    )
    return read_mcp_tool(store.snapshot(), protocol, tool_id)


def read_mcp_tool(
    snapshot: Snapshot,
    protocol: McpBrokerProtocol,
    tool_root: str,
) -> McpToolProjection:
    if not _registered(snapshot, protocol, "tool", tool_root):
        raise InvalidCell("MCP tool is not registered exactly once")
    members = read_relation(snapshot, tool_root, budget=100_000)
    _closed(
        members,
        tuple(protocol.role(name) for name in (
            "tool-negotiation", "tool-name-digest", "tool-schema-digest",
            "tool-datatype", "tool-provider",
        )),
        "MCP tool",
    )
    tool = McpToolProjection(
        tool_root,
        _one(members, protocol.role("tool-negotiation"), "MCP tool negotiation"),
        _require_digest(_text(
            snapshot,
            _one(members, protocol.role("tool-name-digest"), "MCP tool name digest"),
            "MCP tool name digest",
        ), "MCP tool name digest"),
        _require_digest(_text(
            snapshot,
            _one(members, protocol.role("tool-schema-digest"), "MCP tool schema digest"),
            "MCP tool schema digest",
        ), "MCP tool schema digest"),
        _one(members, protocol.role("tool-datatype"), "MCP tool data class"),
        _one(members, protocol.role("tool-provider"), "MCP tool provider"),
    )
    negotiation = read_mcp_negotiation(snapshot, protocol, tool.negotiation_root)
    server = read_mcp_server(snapshot, protocol, negotiation.server_root)
    if tool.datatype_root not in server.datatype_roots or tool.provider_root not in snapshot.cells:
        raise InvalidCell("MCP tool binding drifted")
    return tool


def require_active_mcp_tool(
    snapshot: Snapshot,
    protocol: McpBrokerProtocol,
    tool_root: str,
    *,
    now: float | None = None,
) -> McpToolProjection:
    """Read an admitted tool and reject expired capability snapshots."""
    tool = read_mcp_tool(snapshot, protocol, tool_root)
    negotiation = read_mcp_negotiation(snapshot, protocol, tool.negotiation_root)
    timestamp = time.time() if now is None else _require_time(now, "MCP tool timestamp")
    if timestamp >= negotiation.expires_at:
        raise InvalidCell("MCP tool negotiation has expired")
    return tool


def list_mcp_servers(
    snapshot: Snapshot,
    protocol: McpBrokerProtocol,
) -> tuple[McpServerProjection, ...]:
    return tuple(
        read_mcp_server(snapshot, protocol, member.participant_id)
        for member in read_relation(snapshot, protocol.registry("server"), budget=100_000)
        if member.role_id == protocol.role("registry-member")
    )


def list_mcp_negotiations(
    snapshot: Snapshot,
    protocol: McpBrokerProtocol,
) -> tuple[McpNegotiationProjection, ...]:
    return tuple(
        read_mcp_negotiation(snapshot, protocol, member.participant_id)
        for member in read_relation(snapshot, protocol.registry("negotiation"), budget=100_000)
        if member.role_id == protocol.role("registry-member")
    )


def list_mcp_tools(
    snapshot: Snapshot,
    protocol: McpBrokerProtocol,
) -> tuple[McpToolProjection, ...]:
    return tuple(
        read_mcp_tool(snapshot, protocol, member.participant_id)
        for member in read_relation(snapshot, protocol.registry("tool"), budget=100_000)
        if member.role_id == protocol.role("registry-member")
    )


__all__ = [
    "McpBrokerProtocol", "McpServerProjection", "McpNegotiationProjection",
    "McpToolProjection", "bootstrap_mcp_broker_protocol", "register_mcp_server",
    "read_mcp_server", "record_mcp_negotiation", "read_mcp_negotiation",
    "register_mcp_tool", "read_mcp_tool", "require_active_mcp_tool",
    "list_mcp_servers", "list_mcp_negotiations", "list_mcp_tools",
]
