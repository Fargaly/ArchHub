"""Cell-native design tokens and component bindings.

The graph is authoritative. DTCG 2025.10 JSON is an interchange projection,
not a persisted document hidden in an atom. Token values, aliases, groups,
resolver context, component bindings, provenance, and lifecycle are ordinary
Cell relations over the universal four-field floor.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from types import MappingProxyType
from typing import Iterable, Mapping

from .cell_protocols import compose_relation_cells, read_relation
from .universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell, Snapshot


from .cell_accessibility import (
    DEFAULT_OVERLAY as DEFAULT_OVERLAY_NAME,
    OVERLAYS as _OVERLAYS,
    ensure_active_overlay,
    project_accessibility_modifier,
)
from .cell_theme_sets import (
    DEFAULT_THEME as DEFAULT_THEME_NAME,
    THEMES as _THEMES,
    ensure_active_theme,
    project_theme_modifier,
)

THEME_CONTEXT_NAMES = tuple(_THEMES)
OVERLAY_CONTEXT_NAMES = tuple(_OVERLAYS)

DTCG_VERSION = "2025.10"
PROTOCOL_PREFIX = "app:design-token-protocol"
SYSTEM_ROOT = "app:design-token-system"
TOKEN_SET_ROOT = "app:design-token-set:interface"
RESOLVER_ROOT = "app:design-token-resolver:interface"
COMPONENT_SYSTEM_ROOT = "app:presentation-components"
PUBLISHED_ROOT = "app:design-token:lifecycle:published"
PROVENANCE_ROOT = "app:design-token:provenance:archhub-interface-v1"

ROLE_NAMES = (
    "vocabulary-member",
    "token",
    "group",
    "group-member",
    "name",
    "type",
    "value",
    "description",
    "alias",
    "set",
    "modifier",
    "context",
    "default-context",
    "resolution-item",
    "component",
    "binding",
    "property",
    "provenance",
    "lifecycle",
)

TYPE_NAMES = (
    "color",
    "dimension",
    "fontFamily",
    "fontWeight",
    "duration",
    "cubicBezier",
    "number",
    "strokeStyle",
    "border",
    "transition",
    "shadow",
    "gradient",
    "typography",
)

SEMANTIC_ALIASES: Mapping[str, Mapping[str, str]] = MappingProxyType({
    "surface": MappingProxyType({
        "canvas": "color.bg_canvas",
        "panel": "color.bg_panel",
        "deep": "color.bg_deep",
        # The design system holds bg_soft and bg_raised as two different
        # surfaces; this aliased both to bg_soft, so a raised surface and a
        # soft one were the same colour and the elevation never read.
        "raised": "color.bg_raised",
        "soft": "color.bg_soft",
        "hover": "color.bg_hover",
        "base": "color.bg",
        "ink": "color.bg_ink",
    }),
    "text": MappingProxyType({
        "primary": "color.ink",
        "secondary": "color.ink_soft",
        "muted": "color.ink_muted",
        "dim": "color.ink_dim",
        # Text sitting ON a filled swatch needs dark ink: white on the accent
        # measures 3.12:1. The design system names this role; the app had no
        # token for it, so every filled control guessed.
        "on-fill": "color.on_fill",
    }),
    "border": MappingProxyType({
        "default": "color.line",
        "subtle": "color.line_soft",
        "hair": "color.line_hair",
    }),
    "action": MappingProxyType({
        "primary": "color.accent",
        "primary-container": "color.accent_soft",
        "primary-dim": "color.accent_dim",
        "primary-hover": "color.accent_hi",
        "primary-press": "color.accent_press",
    }),
    "state": MappingProxyType({
        "success": "color.ok",
        "warning": "color.warn",
        "danger": "color.err",
    }),
    "relation": MappingProxyType({
        "default": "color.cyan",
        "composition": "color.purple",
        "data": "color.blue",
    }),
    "layout": MappingProxyType({
        "grid": "size.grid",
        "card-width": "size.card-width",
        "card-radius": "size.card-radius",
        "control-radius": "size.control-radius",
        "target-min": "size.target-min",
        "space-1": "size.space-1",
        "space-2": "size.space-2",
        "space-3": "size.space-3",
        "space-4": "size.space-4",
        "space-5": "size.space-5",
        "space-6": "size.space-6",
        "space-7": "size.space-7",
        "space-8": "size.space-8",
        "space-9": "size.space-9",
        "space-10": "size.space-10",
        "space-11": "size.space-11",
        "radius-xs": "size.radius-xs",
        "radius-sm": "size.radius-sm",
        "radius-lg": "size.radius-lg",
        "radius-xl": "size.radius-xl",
        "radius-pill": "size.radius-pill",
        "row-comfortable": "size.row-comfortable",
        "row-compact": "size.row-compact",
        "row-cozy": "size.row-cozy",
    }),
    "typography": MappingProxyType({
        "ui-family": "font.ui-family",
        "code-family": "font.code-family",
        "regular": "font.regular",
        "medium": "font.medium",
        "strong": "font.strong",
        "body-size": "font.body-size",
        "label-size": "font.label-size",
        "line-height": "font.line-height",
        "display-family": "font.display-family",
        "hand-family": "font.hand-family",
        "display-0": "font.display-0",
        "display-1": "font.display-1",
        "display-2": "font.display-2",
        "heading-1": "font.heading-1",
        "heading-2": "font.heading-2",
        "heading-3": "font.heading-3",
        "body-large": "font.body-large",
        "body-small": "font.body-small",
        "mono-size": "font.mono-size",
        "mono-small": "font.mono-small",
        "caption-size": "font.caption-size",
    }),
    "motion": MappingProxyType({
        "instant": "time.instant",
        "fast": "time.fast",
        "settle": "time.settle",
        "slow": "time.slow",
    }),
})

STATIC_TOKENS: Mapping[str, Mapping[str, tuple[str, str]]] = MappingProxyType({
    "size": MappingProxyType({
        "grid": ("dimension", "20px"),
        "card-width": ("dimension", "220px"),
        "card-radius": ("dimension", "6px"),
        "control-radius": ("dimension", "4px"),
        "target-min": ("dimension", "24px"),
        # The design system's spacing scale, all eleven steps. Three steps
        # meant every gap past 12px was an arbitrary literal.
        "space-1": ("dimension", "4px"),
        "space-2": ("dimension", "8px"),
        "space-3": ("dimension", "12px"),
        "space-4": ("dimension", "16px"),
        "space-5": ("dimension", "24px"),
        "space-6": ("dimension", "32px"),
        "space-7": ("dimension", "40px"),
        "space-8": ("dimension", "48px"),
        "space-9": ("dimension", "56px"),
        "space-10": ("dimension", "72px"),
        "space-11": ("dimension", "96px"),
        "radius-xs": ("dimension", "3px"),
        "radius-sm": ("dimension", "5px"),
        "radius-lg": ("dimension", "8px"),
        "radius-xl": ("dimension", "10px"),
        "radius-pill": ("dimension", "999px"),
        "row-comfortable": ("dimension", "32px"),
        "row-compact": ("dimension", "26px"),
        "row-cozy": ("dimension", "22px"),
    }),
    "font": MappingProxyType({
        "ui-family": ("fontFamily", "Inter, system-ui, sans-serif"),
        "code-family": ("fontFamily", "ui-monospace, monospace"),
        "regular": ("fontWeight", "400"),
        "medium": ("fontWeight", "550"),
        "strong": ("fontWeight", "650"),
        "body-size": ("dimension", "13px"),
        "label-size": ("dimension", "10px"),
        "line-height": ("number", "1.35"),
        # The brand's voice is the serif and the hand. The app carried neither
        # as a token while its own stylesheet hardcoded both by name.
        "display-family": (
            "fontFamily", "'Instrument Serif', Georgia, serif",
        ),
        "hand-family": (
            "fontFamily", "'Architects Daughter', 'Comic Sans MS', cursive",
        ),
        "display-0": ("dimension", "104px"),
        "display-1": ("dimension", "88px"),
        "display-2": ("dimension", "56px"),
        "heading-1": ("dimension", "40px"),
        "heading-2": ("dimension", "24px"),
        "heading-3": ("dimension", "21px"),
        "body-large": ("dimension", "16px"),
        "body-small": ("dimension", "13px"),
        "mono-size": ("dimension", "12px"),
        "mono-small": ("dimension", "11px"),
        "caption-size": ("dimension", "9px"),
    }),
    "time": MappingProxyType({
        "instant": ("duration", "60ms"),
        "fast": ("duration", "80ms"),
        "settle": ("duration", "180ms"),
        "slow": ("duration", "240ms"),
    }),
})

COMPONENT_BINDINGS: Mapping[str, Mapping[str, str]] = MappingProxyType({
    "canvas": MappingProxyType({
        "background": "surface.canvas",
        "grid": "border.subtle",
        "grid-size": "layout.grid",
    }),
    "card": MappingProxyType({
        "background": "surface.panel",
        "border": "border.default",
        "text": "text.primary",
        "width": "layout.card-width",
        "radius": "layout.card-radius",
        "font": "typography.ui-family",
        "font-size": "typography.body-size",
    }),
    "socket": MappingProxyType({
        "control": "relation.default",
        "surface": "surface.panel",
        "target-size": "layout.target-min",
    }),
    "relation-cable": MappingProxyType({
        "stroke": "relation.default",
        "focus": "action.primary",
    }),
    "toolbar": MappingProxyType({
        "background": "surface.panel",
        "border": "border.default",
        "radius": "layout.control-radius",
        "motion": "motion.fast",
    }),
    "tab-set": MappingProxyType({
        "active": "action.primary",
        "text": "text.secondary",
        "font": "typography.ui-family",
        "font-size": "typography.label-size",
    }),
    "properties-row": MappingProxyType({
        "background": "surface.deep",
        "label": "text.secondary",
    }),
    "library-row": MappingProxyType({
        "background": "surface.panel",
        "hover": "surface.hover",
    }),
    "status": MappingProxyType({
        "success": "state.success",
        "warning": "state.warning",
        "danger": "state.danger",
    }),
})


@dataclass(frozen=True, slots=True)
class DesignTokenProtocol:
    root_id: str
    roles: Mapping[str, str]
    types: Mapping[str, str]

    def role(self, name: str) -> str:
        try:
            return self.roles[name]
        except KeyError as exc:
            raise InvalidCell("unknown design-token role %r" % name) from exc


@dataclass(frozen=True, slots=True)
class TokenProjection:
    root_id: str
    name: str
    type_name: str
    value_root: str | None
    alias_root: str | None
    description: str
    provenance_root: str
    lifecycle_root: str


@dataclass(frozen=True, slots=True)
class DesignTokenSystemBuild:
    protocol: DesignTokenProtocol
    root_id: str
    token_set_root: str
    resolver_root: str
    component_system_root: str
    base_token_roots: Mapping[str, str]
    alias_token_roots: Mapping[str, str]
    group_roots: Mapping[str, str]
    component_roots: Mapping[str, str]


def _role_roots(prefix: str = PROTOCOL_PREFIX) -> dict[str, str]:
    return {name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES}


def _type_roots(prefix: str = PROTOCOL_PREFIX) -> dict[str, str]:
    return {name: "%s:type:%s" % (prefix, name) for name in TYPE_NAMES}


def _token_root(name: str) -> str:
    return "app:design-token:base:%s" % name


def _alias_root(group: str, name: str) -> str:
    return "app:design-token:semantic:%s:%s" % (group, name)


def _static_token_root(group: str, name: str) -> str:
    return "app:design-token:foundation:%s:%s" % (group, name)


def _group_root(name: str) -> str:
    return "app:design-token:group:%s" % name


def _component_root(name: str) -> str:
    return "app:presentation-component:%s" % name


def _text(snapshot: Snapshot, root_id: str) -> str:
    try:
        return snapshot.cells[root_id].atom.decode("utf-8")
    except (KeyError, UnicodeDecodeError) as exc:
        raise InvalidCell("design-token text leaf is missing or invalid") from exc


def _add(expected: dict[str, Cell], cell: Cell) -> None:
    previous = expected.get(cell.id)
    if previous is not None and previous != cell:
        raise InvalidCell("design-token build contains an id collision")
    expected[cell.id] = cell


def _add_text(expected: dict[str, Cell], root_id: str, value: str) -> str:
    _add(expected, Cell(
        root_id, NULL_CELL_ID, NULL_CELL_ID, value.encode("utf-8")
    ))
    return root_id


def _add_relation(
    expected: dict[str, Cell],
    root_id: str,
    members: Iterable[tuple[str, str]],
) -> str:
    relation = compose_relation_cells(tuple(members), relation_id=root_id)
    for cell in relation.cells:
        _add(expected, cell)
    return root_id


def _build_expected(
    theme_roots: Mapping[str, str],
) -> tuple[DesignTokenSystemBuild, tuple[Cell, ...]]:
    if not theme_roots:
        raise InvalidCell("design-token system requires theme value roots")
    roles = _role_roots()
    types = _type_roots()
    protocol = DesignTokenProtocol(
        PROTOCOL_PREFIX + ":root",
        MappingProxyType(roles),
        MappingProxyType(types),
    )
    expected: dict[str, Cell] = {}
    for name, root_id in roles.items():
        _add_text(expected, root_id, name)
    for name, root_id in types.items():
        _add_text(expected, root_id, name)
    _add_text(expected, PUBLISHED_ROOT, "published")
    _add_text(
        expected,
        PROVENANCE_ROOT,
        "ArchHub interface design system v1 / DTCG 2025.10",
    )
    _add_relation(
        expected,
        protocol.root_id,
        (
            (roles["vocabulary-member"], root)
            for root in (*roles.values(), *types.values())
        ),
    )

    base_token_roots: dict[str, str] = {}
    base_type_by_path: dict[str, str] = {}
    base_members: list[tuple[str, str]] = []
    for name, value_root in sorted(theme_roots.items()):
        token_root = _token_root(name)
        name_root = token_root + ":name"
        description_root = token_root + ":description"
        _add_text(expected, name_root, name)
        _add_text(
            expected,
            description_root,
            "Interface color token %s" % name.replace("_", " "),
        )
        _add_relation(expected, token_root, (
            (roles["name"], name_root),
            (roles["type"], types["color"]),
            (roles["value"], value_root),
            (roles["description"], description_root),
            (roles["provenance"], PROVENANCE_ROOT),
            (roles["lifecycle"], PUBLISHED_ROOT),
        ))
        base_token_roots["color.%s" % name] = token_root
        base_type_by_path["color.%s" % name] = "color"
        base_members.append((roles["token"], token_root))
    color_group = _group_root("color")
    color_name = color_group + ":name"
    color_description = color_group + ":description"
    _add_text(expected, color_name, "color")
    _add_text(expected, color_description, "ArchHub base color values")
    _add_relation(expected, color_group, (
        (roles["name"], color_name),
        (roles["description"], color_description),
        *base_members,
    ))

    group_roots: dict[str, str] = {"color": color_group}
    set_members: list[tuple[str, str]] = [(roles["group"], color_group)]
    for group, definitions in STATIC_TOKENS.items():
        group_root = _group_root(group)
        group_name = group_root + ":name"
        group_description = group_root + ":description"
        _add_text(expected, group_name, group)
        _add_text(expected, group_description, "ArchHub %s foundations" % group)
        members: list[tuple[str, str]] = [
            (roles["name"], group_name),
            (roles["description"], group_description),
        ]
        for name, (type_name, scalar) in definitions.items():
            token_root = _static_token_root(group, name)
            name_root = token_root + ":name"
            value_root = token_root + ":value"
            description_root = token_root + ":description"
            _add_text(expected, name_root, name)
            _add_text(expected, value_root, scalar)
            _add_text(
                expected,
                description_root,
                "Interface %s token %s" % (group, name),
            )
            _add_relation(expected, token_root, (
                (roles["name"], name_root),
                (roles["type"], types[type_name]),
                (roles["value"], value_root),
                (roles["description"], description_root),
                (roles["provenance"], PROVENANCE_ROOT),
                (roles["lifecycle"], PUBLISHED_ROOT),
            ))
            base_token_roots["%s.%s" % (group, name)] = token_root
            base_type_by_path["%s.%s" % (group, name)] = type_name
            members.append((roles["token"], token_root))
        _add_relation(expected, group_root, members)
        group_roots[group] = group_root
        set_members.append((roles["group"], group_root))

    alias_token_roots: dict[str, str] = {}
    for group, aliases in SEMANTIC_ALIASES.items():
        group_root = _group_root(group)
        group_name = group_root + ":name"
        group_description = group_root + ":description"
        _add_text(expected, group_name, group)
        _add_text(
            expected,
            group_description,
            "Semantic %s design tokens" % group,
        )
        members: list[tuple[str, str]] = [
            (roles["name"], group_name),
            (roles["description"], group_description),
        ]
        for alias_name, target_path in aliases.items():
            if target_path not in base_token_roots:
                raise InvalidCell("design-token alias has no base target")
            target_root = base_token_roots[target_path]
            target_type = base_type_by_path[target_path]
            token_root = _alias_root(group, alias_name)
            name_root = token_root + ":name"
            description_root = token_root + ":description"
            _add_text(expected, name_root, alias_name)
            _add_text(
                expected,
                description_root,
                "Semantic %s.%s token" % (group, alias_name),
            )
            _add_relation(expected, token_root, (
                (roles["name"], name_root),
                (roles["type"], types[target_type]),
                (roles["alias"], target_root),
                (roles["description"], description_root),
                (roles["provenance"], PROVENANCE_ROOT),
                (roles["lifecycle"], PUBLISHED_ROOT),
            ))
            alias_token_roots["%s.%s" % (group, alias_name)] = token_root
            members.append((roles["token"], token_root))
        _add_relation(expected, group_root, members)
        group_roots[group] = group_root
        set_members.append((roles["group"], group_root))

    set_name = TOKEN_SET_ROOT + ":name"
    _add_text(expected, set_name, "ArchHub interface")
    _add_relation(expected, TOKEN_SET_ROOT, (
        (roles["name"], set_name),
        *set_members,
        (roles["provenance"], PROVENANCE_ROOT),
        (roles["lifecycle"], PUBLISHED_ROOT),
    ))

    mode_root = RESOLVER_ROOT + ":modifier:theme"
    mode_name = mode_root + ":name"
    _add_text(expected, mode_name, "theme")
    # Which themes exist is authority, so the contexts are part of the
    # deterministic set. WHICH ONE IS ACTIVE is state and lives in its own
    # relation (`cell_theme_sets.ACTIVE_THEME_ROOT`) so switching it does not
    # make the design system read as drifted.
    context_members = []
    for theme_name in THEME_CONTEXT_NAMES:
        context_root = "%s:context:%s" % (mode_root, theme_name)
        _add_text(expected, context_root, theme_name)
        context_members.append((roles["context"], context_root))
    default_context_root = "%s:context:%s" % (mode_root, DEFAULT_THEME_NAME)
    _add_relation(expected, mode_root, (
        (roles["name"], mode_name),
        *context_members,
        (roles["default-context"], default_context_root),
    ))
    a11y_root = RESOLVER_ROOT + ":modifier:a11y"
    a11y_name = a11y_root + ":name"
    _add_text(expected, a11y_name, "a11y")
    # The overlay composes ONTO the theme, so it is a second modifier and it
    # resolves after the theme -- never instead of it.
    a11y_members = []
    for overlay_name in OVERLAY_CONTEXT_NAMES:
        overlay_root = "%s:context:%s" % (a11y_root, overlay_name)
        _add_text(expected, overlay_root, overlay_name)
        a11y_members.append((roles["context"], overlay_root))
    _add_relation(expected, a11y_root, (
        (roles["name"], a11y_name),
        *a11y_members,
        (roles["default-context"],
         "%s:context:%s" % (a11y_root, DEFAULT_OVERLAY_NAME)),
    ))
    resolver_name = RESOLVER_ROOT + ":name"
    resolver_version = RESOLVER_ROOT + ":version"
    _add_text(expected, resolver_name, "ArchHub interface resolver")
    _add_text(expected, resolver_version, DTCG_VERSION)
    _add_relation(expected, RESOLVER_ROOT, (
        (roles["name"], resolver_name),
        (roles["description"], resolver_version),
        (roles["set"], TOKEN_SET_ROOT),
        (roles["modifier"], mode_root),
        (roles["modifier"], a11y_root),
        (roles["resolution-item"], TOKEN_SET_ROOT),
        (roles["resolution-item"], mode_root),
        (roles["resolution-item"], a11y_root),
        (roles["provenance"], PROVENANCE_ROOT),
        (roles["lifecycle"], PUBLISHED_ROOT),
    ))

    component_roots: dict[str, str] = {}
    component_system_members: list[tuple[str, str]] = []
    for component_name, bindings in COMPONENT_BINDINGS.items():
        component_root = _component_root(component_name)
        name_root = component_root + ":name"
        _add_text(expected, name_root, component_name)
        component_members: list[tuple[str, str]] = [
            (roles["name"], name_root),
            (roles["lifecycle"], PUBLISHED_ROOT),
        ]
        for property_name, alias_path in bindings.items():
            try:
                token_root = alias_token_roots[alias_path]
            except KeyError as exc:
                raise InvalidCell("component binding names an unknown token") from exc
            binding_root = "%s:binding:%s" % (component_root, property_name)
            property_root = binding_root + ":property"
            _add_text(expected, property_root, property_name)
            _add_relation(expected, binding_root, (
                (roles["component"], component_root),
                (roles["property"], property_root),
                (roles["token"], token_root),
            ))
            component_members.append((roles["binding"], binding_root))
        _add_relation(expected, component_root, component_members)
        component_roots[component_name] = component_root
        component_system_members.append((roles["component"], component_root))
    _add_relation(
        expected, COMPONENT_SYSTEM_ROOT, component_system_members
    )
    _add_relation(expected, SYSTEM_ROOT, (
        (roles["vocabulary-member"], protocol.root_id),
        (roles["set"], TOKEN_SET_ROOT),
        (roles["modifier"], RESOLVER_ROOT),
        (roles["component"], COMPONENT_SYSTEM_ROOT),
        (roles["provenance"], PROVENANCE_ROOT),
        (roles["lifecycle"], PUBLISHED_ROOT),
    ))

    build = DesignTokenSystemBuild(
        protocol,
        SYSTEM_ROOT,
        TOKEN_SET_ROOT,
        RESOLVER_ROOT,
        COMPONENT_SYSTEM_ROOT,
        MappingProxyType(base_token_roots),
        MappingProxyType(alias_token_roots),
        MappingProxyType(group_roots),
        MappingProxyType(component_roots),
    )
    return build, tuple(expected.values())


def ensure_archhub_design_token_system(
    store: CellStore,
    theme_roots: Mapping[str, str],
) -> DesignTokenSystemBuild:
    """Install or verify the deterministic design-system graph."""
    build, expected_cells = _build_expected(theme_roots)
    snapshot = store.snapshot()
    missing: list[Cell] = []
    for expected in expected_cells:
        existing = snapshot.cells.get(expected.id)
        if existing is None:
            missing.append(expected)
        elif existing != expected:
            raise InvalidCell(
                "persisted design-token authority drifted at %s" % expected.id
            )
    if missing:
        store.commit(snapshot.revision, create=tuple(missing))
    verify_design_token_system(store.snapshot(), build)
    ensure_active_theme(store, build.resolver_root + ":modifier:theme")
    ensure_active_overlay(store, build.resolver_root + ":modifier:a11y")
    return build


def open_archhub_design_token_system(
    snapshot: Snapshot,
    theme_roots: Mapping[str, str],
) -> DesignTokenSystemBuild:
    """Open the deterministic design graph without mutating the store."""
    build, _ = _build_expected(theme_roots)
    verify_design_token_system(snapshot, build)
    return build


def design_token_system_member_roots(
    theme_roots: Mapping[str, str],
) -> tuple[str, ...]:
    build, _ = _build_expected(theme_roots)
    return (build.root_id,)


def design_token_title_specs(
    theme_roots: Mapping[str, str],
) -> tuple[tuple[str, str], ...]:
    build, _ = _build_expected(theme_roots)
    return (
        (build.root_id, "Design Tokens"),
        (build.token_set_root, "Interface Token Set"),
        (build.resolver_root, "Interface Token Resolver"),
        (build.component_system_root, "Presentation Components"),
        *((root, name.replace("-", " ").title())
          for name, root in build.group_roots.items()),
        *((root, name.replace("-", " ").title())
          for name, root in build.component_roots.items()),
    )


def _one(
    members,
    role_id: str,
    label: str,
    *,
    required: bool = True,
) -> str | None:
    values = tuple(
        member.participant_id for member in members
        if member.role_id == role_id
    )
    if len(values) > 1 or (required and len(values) != 1):
        raise InvalidCell("design-token %s cardinality is invalid" % label)
    return values[0] if values else None


def read_token(
    snapshot: Snapshot,
    protocol: DesignTokenProtocol,
    token_root: str,
) -> TokenProjection:
    members = read_relation(snapshot, token_root, budget=64)
    name_root = _one(members, protocol.role("name"), "name")
    type_root = _one(members, protocol.role("type"), "type")
    value_root = _one(
        members, protocol.role("value"), "value", required=False
    )
    alias_root = _one(
        members, protocol.role("alias"), "alias", required=False
    )
    if (value_root is None) == (alias_root is None):
        raise InvalidCell("token must have exactly one value or alias")
    description_root = _one(
        members, protocol.role("description"), "description"
    )
    provenance_root = _one(
        members, protocol.role("provenance"), "provenance"
    )
    lifecycle_root = _one(
        members, protocol.role("lifecycle"), "lifecycle"
    )
    type_names = {
        root: name for name, root in protocol.types.items()
    }
    if type_root not in type_names:
        raise InvalidCell("token type is outside the DTCG vocabulary")
    name = _text(snapshot, str(name_root))
    if not name or name.startswith("$") or any(c in name for c in "{}."):
        raise InvalidCell("token name is not DTCG-compatible")
    return TokenProjection(
        token_root,
        name,
        type_names[str(type_root)],
        value_root,
        alias_root,
        _text(snapshot, str(description_root)),
        str(provenance_root),
        str(lifecycle_root),
    )


def _hex_color(value: str) -> dict[str, object]:
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        raise InvalidCell("color token is not a six-digit sRGB value")
    components = [int(value[index:index + 2], 16) / 255 for index in (1, 3, 5)]
    return {
        "colorSpace": "srgb",
        "components": components,
        "alpha": 1,
        "hex": value.lower(),
    }


def _dtcg_value(type_name: str, scalar: str) -> object:
    if type_name == "color":
        return _hex_color(scalar)
    if type_name == "dimension":
        match = re.fullmatch(r"(-?(?:\d+(?:\.\d+)?|\.\d+))(px|rem)", scalar)
        if match is None:
            raise InvalidCell("dimension token is not a DTCG px/rem value")
        return {"value": float(match.group(1)), "unit": match.group(2)}
    if type_name == "duration":
        match = re.fullmatch(r"(-?(?:\d+(?:\.\d+)?|\.\d+))(ms|s)", scalar)
        if match is None:
            raise InvalidCell("duration token is not a DTCG ms/s value")
        return {"value": float(match.group(1)), "unit": match.group(2)}
    if type_name == "fontWeight":
        try:
            return int(scalar)
        except ValueError:
            return scalar
    if type_name == "number":
        try:
            return float(scalar)
        except ValueError as exc:
            raise InvalidCell("number token has a non-numeric value") from exc
    if type_name in ("fontFamily", "strokeStyle"):
        return scalar
    raise InvalidCell(
        "complex %s token requires a value-graph projector" % type_name
    )


def _token_paths(
    snapshot: Snapshot,
    protocol: DesignTokenProtocol,
    token_set_root: str,
) -> tuple[dict[str, tuple[str, ...]], dict[str, tuple[str, ...]]]:
    token_paths: dict[str, tuple[str, ...]] = {}
    group_paths: dict[str, tuple[str, ...]] = {}

    def walk(group_root: str, parent: tuple[str, ...]) -> None:
        if group_root in group_paths:
            raise InvalidCell("design-token group graph is recursive")
        members = read_relation(snapshot, group_root, budget=512)
        name_root = _one(members, protocol.role("name"), "group name")
        path = (*parent, _text(snapshot, str(name_root)))
        group_paths[group_root] = path
        for member in members:
            if member.role_id == protocol.role("token"):
                token = read_token(snapshot, protocol, member.participant_id)
                if token.root_id in token_paths:
                    raise InvalidCell("token appears in more than one group")
                token_paths[token.root_id] = (*path, token.name)
            elif member.role_id == protocol.role("group"):
                walk(member.participant_id, path)

    set_members = read_relation(snapshot, token_set_root, budget=512)
    for member in set_members:
        if member.role_id == protocol.role("group"):
            walk(member.participant_id, ())
    if not token_paths:
        raise InvalidCell("design-token set contains no tokens")
    return token_paths, group_paths


def resolve_design_tokens(
    snapshot: Snapshot,
    protocol: DesignTokenProtocol,
    token_set_root: str,
    *,
    value_overrides: Mapping[str, str] | None = None,
) -> Mapping[str, str]:
    """Resolve aliases with type and cycle checks."""
    token_paths, _ = _token_paths(snapshot, protocol, token_set_root)
    tokens = {
        root: read_token(snapshot, protocol, root) for root in token_paths
    }
    overrides = value_overrides or {}
    if set(overrides) - set(tokens):
        raise InvalidCell("design-token override leaves its token set")
    resolved: dict[str, str] = {}
    visiting: set[str] = set()

    def resolve(root: str) -> str:
        if root in resolved:
            return resolved[root]
        if root in visiting:
            raise InvalidCell("design-token alias cycle detected")
        try:
            token = tokens[root]
        except KeyError as exc:
            raise InvalidCell("design-token alias leaves its token set") from exc
        visiting.add(root)
        if token.value_root is not None:
            value = str(overrides.get(root, _text(snapshot, token.value_root)))
        else:
            target = tokens.get(str(token.alias_root))
            if target is None:
                raise InvalidCell("design-token alias target is missing")
            if target.type_name != token.type_name:
                raise InvalidCell("design-token alias changes token type")
            value = resolve(target.root_id)
        visiting.remove(root)
        resolved[root] = value
        return value

    for root in tokens:
        resolve(root)
    return MappingProxyType(resolved)


def project_design_system_runtime(
    snapshot: Snapshot,
    build: DesignTokenSystemBuild,
    *,
    theme_overrides: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Resolve semantic tokens and component bindings for a browser lens."""
    overrides = {
        build.base_token_roots["color.%s" % name]: str(value)
        for name, value in (theme_overrides or {}).items()
        if "color.%s" % name in build.base_token_roots
    }
    resolved = resolve_design_tokens(
        snapshot,
        build.protocol,
        build.token_set_root,
        value_overrides=overrides,
    )
    alias_path_by_root = {
        root: path for path, root in build.alias_token_roots.items()
    }
    tokens = {
        path: {
            "root": root,
            "type": read_token(snapshot, build.protocol, root).type_name,
            "value": resolved[root],
        }
        for path, root in build.alias_token_roots.items()
    }
    components: dict[str, dict[str, object]] = {}
    for component_name, component_root in build.component_roots.items():
        members = read_relation(snapshot, component_root, budget=128)
        projected_bindings: dict[str, object] = {}
        for member in members:
            if member.role_id != build.protocol.role("binding"):
                continue
            binding = read_relation(snapshot, member.participant_id, budget=16)
            property_root = _one(
                binding, build.protocol.role("property"), "binding property"
            )
            token_root = _one(
                binding, build.protocol.role("token"), "binding token"
            )
            alias_path = alias_path_by_root.get(str(token_root))
            if alias_path is None:
                raise InvalidCell("component binding bypasses semantic aliases")
            token = read_token(snapshot, build.protocol, str(token_root))
            projected_bindings[_text(snapshot, str(property_root))] = {
                "binding": member.participant_id,
                "token": alias_path,
                "token_root": token.root_id,
                "type": token.type_name,
                "value": resolved[token.root_id],
            }
        components[component_name] = projected_bindings
    return {
        "root": build.root_id,
        "token_set": build.token_set_root,
        "resolver": build.resolver_root,
        "lifecycle": PUBLISHED_ROOT,
        "tokens": tokens,
        "components": components,
    }


def project_dtcg_format(
    snapshot: Snapshot,
    protocol: DesignTokenProtocol,
    token_set_root: str,
) -> dict[str, object]:
    """Project the graph as a canonical DTCG 2025.10 format document."""
    token_paths, group_paths = _token_paths(
        snapshot, protocol, token_set_root
    )
    resolved = resolve_design_tokens(snapshot, protocol, token_set_root)
    document: dict[str, object] = {}
    groups: dict[tuple[str, ...], dict[str, object]] = {(): document}
    for _root, path in sorted(group_paths.items(), key=lambda item: item[1]):
        parent = groups[path[:-1]]
        group: dict[str, object] = {}
        parent[path[-1]] = group
        groups[path] = group
    for root, path in sorted(token_paths.items(), key=lambda item: item[1]):
        token = read_token(snapshot, protocol, root)
        if token.alias_root is not None:
            target_path = token_paths.get(token.alias_root)
            if target_path is None:
                raise InvalidCell("design-token alias target has no DTCG path")
            value: object = "{%s}" % ".".join(target_path)
        else:
            value = _dtcg_value(token.type_name, resolved[root])
        groups[path[:-1]][path[-1]] = {
            "$type": token.type_name,
            "$value": value,
            "$description": token.description,
            "$extensions": {
                "com.archhub.graph": {
                    "root": token.root_id,
                    "provenance": token.provenance_root,
                    "lifecycle": token.lifecycle_root,
                }
            },
        }
    return document


def project_dtcg_resolver(
    snapshot: Snapshot,
    build: DesignTokenSystemBuild,
) -> dict[str, object]:
    """Project the graph-held default dark context as a Resolver document."""
    read_relation(snapshot, build.resolver_root, budget=64)
    return {
        "$schema": "https://www.designtokens.org/schemas/2025.10/resolver.json",
        "name": "ArchHub interface resolver",
        "version": DTCG_VERSION,
        "sets": {
            "foundation": {
                "sources": [
                    project_dtcg_format(
                        snapshot, build.protocol, build.token_set_root
                    )
                ]
            }
        },
        # Read the themes and the active one out of the graph. This printed
        # `{"dark": []}` as a literal, so the founder's three themes could
        # never appear however the graph was wired.
        "modifiers": {
            "theme": project_theme_modifier(
                snapshot,
                build.resolver_root + ":modifier:theme",
                build.protocol.roles["context"],
            ),
            "a11y": project_accessibility_modifier(
                snapshot,
                build.resolver_root + ":modifier:a11y",
                build.protocol.roles["context"],
            ),
        },
        "resolutionOrder": [
            {"$ref": "#/sets/foundation"},
            {"$ref": "#/modifiers/theme"},
            {"$ref": "#/modifiers/a11y"},
        ],
    }


def import_dtcg_format(
    store: CellStore,
    document: Mapping[str, object],
    *,
    prefix: str = "imported-design-token",
) -> tuple[DesignTokenProtocol, str]:
    """Import a DTCG format projection into ordinary Cell relations.

    The importer is intentionally an interchange boundary. It supports all
    scalar token values and the normative 2025.10 color object; complex values
    must arrive through a released value-graph adapter rather than being hidden
    as JSON in one atom.
    """
    if not isinstance(document, Mapping) or not document:
        raise InvalidCell("DTCG document must be a non-empty mapping")
    roles = {
        name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES
    }
    types = {
        name: "%s:type:%s" % (prefix, name) for name in TYPE_NAMES
    }
    protocol = DesignTokenProtocol(
        prefix + ":protocol",
        MappingProxyType(roles),
        MappingProxyType(types),
    )
    expected: dict[str, Cell] = {}
    for name, root_id in roles.items():
        _add_text(expected, root_id, name)
    for name, root_id in types.items():
        _add_text(expected, root_id, name)
    _add_relation(expected, protocol.root_id, (
        (roles["vocabulary-member"], root)
        for root in (*roles.values(), *types.values())
    ))

    token_by_path: dict[tuple[str, ...], str] = {}
    token_specs: list[tuple[tuple[str, ...], Mapping[str, object]]] = []
    group_specs: list[
        tuple[tuple[str, ...], list[tuple[str, ...]], list[tuple[str, ...]]]
    ] = []

    def walk_group(
        source: Mapping[str, object], path: tuple[str, ...]
    ) -> None:
        token_paths: list[tuple[str, ...]] = []
        child_groups: list[tuple[str, ...]] = []
        for name, value in source.items():
            if name.startswith("$"):
                continue
            if not isinstance(value, Mapping):
                raise InvalidCell("DTCG group member must be an object")
            child_path = (*path, name)
            if "$value" in value:
                token_specs.append((child_path, value))
                token_paths.append(child_path)
            else:
                walk_group(value, child_path)
                child_groups.append(child_path)
        if path:
            group_specs.append((path, token_paths, child_groups))

    walk_group(document, ())
    if not token_specs:
        raise InvalidCell("DTCG document contains no tokens")

    pending_aliases: list[tuple[str, tuple[str, ...], str]] = []
    for path, spec in token_specs:
        type_name = spec.get("$type")
        if type_name not in types:
            raise InvalidCell("DTCG token has an unsupported or missing type")
        extensions = spec.get("$extensions", {})
        graph_extension = (
            extensions.get("com.archhub.graph", {})
            if isinstance(extensions, Mapping) else {}
        )
        root_hint = (
            graph_extension.get("root")
            if isinstance(graph_extension, Mapping) else None
        )
        digest = hashlib.sha256("/".join(path).encode("utf-8")).hexdigest()[:24]
        token_root = (
            root_hint if isinstance(root_hint, str) and root_hint
            else "%s:token:%s" % (prefix, digest)
        )
        if token_root in token_by_path.values():
            raise InvalidCell("DTCG token roots are not unique")
        token_by_path[path] = token_root
        name_root = token_root + ":name"
        description_root = token_root + ":description"
        provenance_root = (
            graph_extension.get("provenance")
            if isinstance(graph_extension, Mapping) else None
        )
        lifecycle_root = (
            graph_extension.get("lifecycle")
            if isinstance(graph_extension, Mapping) else None
        )
        if not isinstance(provenance_root, str) or not provenance_root:
            provenance_root = prefix + ":provenance"
        if not isinstance(lifecycle_root, str) or not lifecycle_root:
            lifecycle_root = prefix + ":lifecycle:wip"
        _add_text(expected, name_root, path[-1])
        _add_text(
            expected,
            description_root,
            str(spec.get("$description", "Imported DTCG token")),
        )
        if provenance_root not in expected:
            _add_text(expected, provenance_root, provenance_root)
        if lifecycle_root not in expected:
            _add_text(expected, lifecycle_root, lifecycle_root.rsplit(":", 1)[-1])
        value = spec["$value"]
        members: list[tuple[str, str]] = [
            (roles["name"], name_root),
            (roles["type"], types[str(type_name)]),
            (roles["description"], description_root),
            (roles["provenance"], provenance_root),
            (roles["lifecycle"], lifecycle_root),
        ]
        if isinstance(value, str) and value.startswith("{") and value.endswith("}"):
            target_path = tuple(value[1:-1].split("."))
            pending_aliases.append((token_root, target_path, str(type_name)))
        else:
            value_root = token_root + ":value"
            if type_name == "color":
                if not isinstance(value, Mapping):
                    raise InvalidCell("DTCG color value must be an object")
                color_space = value.get("colorSpace")
                components = value.get("components")
                hex_value = value.get("hex")
                if color_space != "srgb" or not isinstance(components, list):
                    raise InvalidCell("only DTCG sRGB color import is admitted")
                if isinstance(hex_value, str) and re.fullmatch(
                    r"#[0-9a-fA-F]{6}", hex_value
                ):
                    scalar = hex_value.lower()
                elif len(components) == 3 and all(
                    isinstance(item, (int, float)) and 0 <= item <= 1
                    for item in components
                ):
                    scalar = "#%02x%02x%02x" % tuple(
                        round(float(item) * 255) for item in components
                    )
                else:
                    raise InvalidCell("DTCG sRGB components are invalid")
            elif type_name in ("dimension", "duration"):
                if not isinstance(value, Mapping):
                    raise InvalidCell("DTCG measured value must be an object")
                number = value.get("value")
                unit = value.get("unit")
                admitted_units = (
                    ("px", "rem") if type_name == "dimension" else ("ms", "s")
                )
                if (
                    not isinstance(number, (int, float))
                    or isinstance(number, bool)
                    or unit not in admitted_units
                ):
                    raise InvalidCell("DTCG measured value is invalid")
                scalar = "%s%s" % (number, unit)
            elif type_name in ("fontWeight", "number"):
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    raise InvalidCell("DTCG numeric value is invalid")
                scalar = str(value)
            elif isinstance(value, (str, int, float)) and not isinstance(value, bool):
                scalar = str(value)
            else:
                raise InvalidCell(
                    "complex DTCG value requires the value-graph importer"
                )
            _add_text(expected, value_root, scalar)
            members.append((roles["value"], value_root))
        _add_relation(expected, token_root, members)

    for token_root, target_path, _type_name in pending_aliases:
        target_root = token_by_path.get(target_path)
        if target_root is None:
            raise InvalidCell("DTCG alias target is missing")
        token_members = read_relation(
            Snapshot(0, MappingProxyType(expected)), token_root, budget=64
        )
        if any(member.role_id == roles["value"] for member in token_members):
            raise InvalidCell("DTCG alias token also contains a value")
        rebuilt = compose_relation_cells((
            *((member.role_id, member.participant_id) for member in token_members),
            (roles["alias"], target_root),
        ), relation_id=token_root)
        for cell_id in tuple(expected):
            if cell_id == token_root or cell_id.startswith(token_root + ":incidence:") \
                    or cell_id.startswith(token_root + ":chain:"):
                expected.pop(cell_id)
        for cell in rebuilt.cells:
            _add(expected, cell)

    group_by_path: dict[tuple[str, ...], str] = {}
    for path, token_paths, child_paths in sorted(
        group_specs, key=lambda item: len(item[0]), reverse=True
    ):
        digest = hashlib.sha256("/".join(path).encode("utf-8")).hexdigest()[:24]
        group_root = "%s:group:%s" % (prefix, digest)
        group_by_path[path] = group_root
        name_root = group_root + ":name"
        description_root = group_root + ":description"
        _add_text(expected, name_root, path[-1])
        _add_text(expected, description_root, "Imported DTCG group")
        _add_relation(expected, group_root, (
            (roles["name"], name_root),
            (roles["description"], description_root),
            *((roles["token"], token_by_path[item]) for item in token_paths),
            *((roles["group"], group_by_path[item]) for item in child_paths),
        ))
    top_groups = tuple(
        root for path, root in group_by_path.items() if len(path) == 1
    )
    set_root = prefix + ":set"
    set_name = set_root + ":name"
    _add_text(expected, set_name, "Imported DTCG set")
    _add_relation(expected, set_root, (
        (roles["name"], set_name),
        *((roles["group"], root) for root in top_groups),
    ))
    store.commit(store.revision, create=tuple(expected.values()))
    resolve_design_tokens(store.snapshot(), protocol, set_root)
    return protocol, set_root


def verify_design_token_system(
    snapshot: Snapshot,
    build: DesignTokenSystemBuild,
) -> None:
    members = read_relation(snapshot, build.root_id, budget=64)
    required = {
        build.protocol.root_id,
        build.token_set_root,
        build.resolver_root,
        build.component_system_root,
        PROVENANCE_ROOT,
        PUBLISHED_ROOT,
    }
    actual = {member.participant_id for member in members}
    if not required.issubset(actual):
        raise InvalidCell("design-token system composition is incomplete")
    resolved = resolve_design_tokens(
        snapshot, build.protocol, build.token_set_root
    )
    if set(build.base_token_roots.values()) - set(resolved):
        raise InvalidCell("design-token base values are incomplete")
    if set(build.alias_token_roots.values()) - set(resolved):
        raise InvalidCell("design-token semantic aliases are incomplete")
    component_members = read_relation(
        snapshot, build.component_system_root, budget=128
    )
    components = tuple(
        member.participant_id for member in component_members
        if member.role_id == build.protocol.role("component")
    )
    if set(components) != set(build.component_roots.values()):
        raise InvalidCell("presentation component catalogue drifted")
    for component_root in components:
        component = read_relation(snapshot, component_root, budget=64)
        bindings = tuple(
            member.participant_id for member in component
            if member.role_id == build.protocol.role("binding")
        )
        if not bindings:
            raise InvalidCell("presentation component has no token bindings")
        for binding_root in bindings:
            binding = read_relation(snapshot, binding_root, budget=16)
            token_root = _one(
                binding, build.protocol.role("token"), "binding token"
            )
            if token_root not in build.alias_token_roots.values():
                raise InvalidCell("component bypasses semantic token authority")


__all__ = [
    "COMPONENT_BINDINGS",
    "COMPONENT_SYSTEM_ROOT",
    "DTCG_VERSION",
    "DesignTokenProtocol",
    "DesignTokenSystemBuild",
    "PUBLISHED_ROOT",
    "PROTOCOL_PREFIX",
    "PROVENANCE_ROOT",
    "RESOLVER_ROOT",
    "SEMANTIC_ALIASES",
    "SYSTEM_ROOT",
    "TOKEN_SET_ROOT",
    "TokenProjection",
    "design_token_system_member_roots",
    "design_token_title_specs",
    "ensure_archhub_design_token_system",
    "import_dtcg_format",
    "open_archhub_design_token_system",
    "project_design_system_runtime",
    "project_dtcg_format",
    "project_dtcg_resolver",
    "read_token",
    "resolve_design_tokens",
    "verify_design_token_system",
]
