"""Library validator — Layer 4 of the LIBRARY-FIRST + MODULARITY mandate.

Reference: docs/agdr/AgDR-0014-library-design-system.md — the design tokens
(categories, side-effects, status, port-type taxonomy) backing this validator.
Reference: docs/agdr/AgDR-0013-multi-llm-library-first-enforcement.md — the
four-layer enforcement architecture that uses this validator as Layer 4.
Reference: docs/agdr/AgDR-0012-architecture-direction-x.md §"Mandate 3 —
MODULARITY" — the rules.

When any caller (LLM router gate, bridge.save_as_skill, library import) tries
to register a new node-type spec, this validator decides whether the spec is
MODULAR enough to enter the library.

Design tokens (locked in AgDR-0014):

- Category enum (11) aligned with engine `cat` + 2 cross-host extensions.
- Side effects (3): pure | host_write | network — drives approval gating
  AND the examples-count tier.
- Description floor: 80 chars — one full descriptive sentence; floor is
  empirical (Speckle ~110, ComfyUI ~95). Sufficient for library.search
  similarity matching.
- Examples min count tiered by side_effects:
    pure        ≥1
    host_write  ≥2  (happy + offline-host / approval-gated edge)
    network     ≥2  (happy + failure mode)
- Status (4): registered | proposed | superseded | deprecated. Default
  `registered`. `proposed` = AI-minted in Plan mode awaiting user OK.
- Port type taxonomy: free-string today; `resolve_port_type(value)` returns
  `(kind, canonical)` so callers can warn (not reject) on free strings while
  the Speckle migration narrows the taxonomy.

Renamed from `NodeSpec` to `ModularNodeSpec` to avoid collision with the
existing `workflows.registry.NodeSpec` engine dataclass. Same shape role,
different layer (validator vs registrar).

`validate(spec)` returns `ValidationResult(ok, violations)` — never raises.
Pydantic v2 ValidationError is flattened into one violation per failed rule
so the LLM can fix every problem in a single retry.
"""
from __future__ import annotations

from typing import Any, Literal, NamedTuple, Optional

from pydantic import (
    BaseModel,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)


# Categories permitted on a modular node spec — design-system token 1.
# Aligned with `workflows.node_grammar.Primitive.cat` (the existing engine
# display-group field, 9 values) + 2 cross-host extensions.
#   input      — value source (covers `input` + `constant` primitives)
#   connector  — host-bound op
#   ai         — model-driven
#   logic      — control flow (if / foreach / merge / switch)
#   output     — terminal sink
#   skill      — user-saved composition (wrapper shape)
#   shape      — pure data transformation (covers `filter` + `transform`)
#   watch      — non-terminal viewer (covers `watch` + `trigger`)
#   note       — annotation / wire routing (covers `note` + `reroute`)
#   glue       — fallback cross-host bridge when Speckle can't carry
#   adapter    — typed bridge (units, port-type coercion)
Category = Literal[
    "input",
    "connector",
    "ai",
    "logic",
    "output",
    "skill",
    "shape",
    "watch",
    "note",
    "glue",
    "adapter",
]


# Side-effect classes — used by the user-agency mandate to decide whether
# a call needs approval gating, AND to set the examples-count tier.
SideEffect = Literal["pure", "host_write", "network"]


# Lifecycle status — design-system token 6. Curation needs this; flat
# "in library or not" was undermodelled.
NodeStatus = Literal["registered", "proposed", "superseded", "deprecated"]


# Examples-count tier by side_effects — design-system token 3.
# Encoded here so the validator + JSON Schema + JSX client all agree.
EXAMPLES_MIN_BY_SIDE_EFFECTS: dict[str, int] = {
    "pure": 1,
    "host_write": 2,
    "network": 2,
}


# Description floor — design-system token 2. Empirical: 80 chars ≈ one
# full descriptive sentence. Speckle ~110, ComfyUI ~95.
DESCRIPTION_MIN_LENGTH = 80


class PortSpec(BaseModel):
    """One input or output port on a modular node."""

    name: str = Field(min_length=1, max_length=40)
    port_type: str = Field(min_length=1, max_length=80)
    required: bool = False
    description: Optional[str] = Field(default=None, max_length=200)

    @field_validator("name")
    @classmethod
    def _name_snake_case(cls, v: str) -> str:
        # Names must be valid identifier-ish so they can be addressed in
        # graph.connect("n_x.<port>") and in JSON without quoting.
        if not v.replace("_", "").isalnum():
            raise ValueError(
                "port name must be alphanumeric + underscores only"
            )
        if v[0].isdigit():
            raise ValueError("port name must not start with a digit")
        return v


class ExampleSpec(BaseModel):
    """One worked example used by library.search similarity matching."""

    input: dict = Field(default_factory=dict)
    output: dict = Field(default_factory=dict)
    note: Optional[str] = Field(default=None, max_length=200)


class ModularNodeSpec(BaseModel):
    """The contract every library-registered node must satisfy.

    Locked by AgDR-0012 §"Mandate 3 — MODULARITY". Backed by AgDR-0013 as
    Layer 4 of the multi-LLM enforcement model. Design tokens locked by
    AgDR-0014.
    """

    # type: lowercase ASCII dot-separated identifier, e.g. "revit.tag_by_room".
    type: str = Field(pattern=r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
    display_name: str = Field(min_length=3, max_length=60)
    category: Category
    inputs: list[PortSpec] = Field(default_factory=list)
    outputs: list[PortSpec] = Field(min_length=1)
    config_schema: dict = Field(default_factory=dict)
    description: str = Field(min_length=DESCRIPTION_MIN_LENGTH)
    examples: list[ExampleSpec] = Field(default_factory=list)
    side_effects: SideEffect = "pure"
    status: NodeStatus = "registered"

    @field_validator("config_schema")
    @classmethod
    def _config_schema_must_declare_at_least_one_property(
        cls, v: dict
    ) -> dict:
        # Empty config = unparameterised body = literals baked in.
        # AgDR-0012 §MODULARITY rule 3: "Hard-coded literal values inside
        # the body are a code smell — refactor to config." We enforce that
        # at registration time. Accept any of:
        #   {"properties": {...}}       — JSON Schema standard
        #   {"<field>": {"type": "..."}}  — flat shorthand sometimes used
        if not isinstance(v, dict):
            raise ValueError("config_schema must be an object")
        if not v:
            raise ValueError(
                "config_schema must declare at least one parameter "
                "(use {} only for genuinely pure pass-through primitives, "
                "which should not be library-registered separately)"
            )
        if "properties" in v:
            if not isinstance(v["properties"], dict) or not v["properties"]:
                raise ValueError(
                    "config_schema.properties must declare at least one field"
                )
        # else: flat shorthand — at least one entry is required (already
        # ensured by the `if not v` check above).
        return v

    @model_validator(mode="after")
    def _examples_count_matches_side_effects_tier(self) -> "ModularNodeSpec":
        # AgDR-0014 token 3: examples count is tiered by side_effects.
        # pure ≥1, host_write ≥2, network ≥2. The host_write/network tiers
        # exist because USER-AGENCY demands the failure / approval state be
        # part of the documented contract, not an afterthought.
        required = EXAMPLES_MIN_BY_SIDE_EFFECTS.get(self.side_effects, 1)
        if len(self.examples) < required:
            raise ValueError(
                f"examples list has {len(self.examples)} item(s); "
                f"`side_effects: {self.side_effects}` requires at least "
                f"{required} example(s) — "
                + (
                    "one happy-path example is enough for a pure op"
                    if required == 1
                    else (
                        "document the happy path AND at least one failure "
                        "/ approval-gated edge case (USER-AGENCY mandate)"
                    )
                )
            )
        return self


class ValidationResult(BaseModel):
    """Validator output.

    `ok=True` means the spec is modular and the caller may proceed to
    register it. `ok=False` means the caller must surface the violations
    to the LLM (or the user) so a corrected spec can be re-submitted.

    Violations are human-readable strings, one per failed rule, formatted
    so they read well embedded in a tool-call error result.
    """

    ok: bool
    violations: list[str] = Field(default_factory=list)


class ResolvedPortType(NamedTuple):
    """Result of `resolve_port_type(value)` — design-system token 8.

    `kind` is one of:
      - "speckle" — value matches a known Speckle Base subclass
      - "legacy"  — value matches the legacy `workflows.graph.PortType`
      - "free"    — anything else; validator warns but does not reject
    `canonical` is the lookup-normalised form.
    """

    kind: Literal["speckle", "legacy", "free"]
    canonical: str


# Known Speckle Base subclasses we expect to see on ports during M1+.
# Not exhaustive — extend as M2/M5 land more host connectors. We match by
# prefix (`Objects.`) for speckle types since the subclass tree is large.
_SPECKLE_PREFIX = "Objects."

# Known legacy PortType enum values (sample — full list lives in
# `workflows.graph.PortType`; we duplicate the common ones here to avoid an
# import-time dependency on the engine module).
_LEGACY_PORT_TYPES = frozenset({
    "any",
    "string",
    "text",
    "number",
    "boolean",
    "list",
    "object",
    "trace",
    "geometry",
    "walls",
    "doors",
    "windows",
    "rooms",
    "element",
    "elements",
    "selection",
    "view",
    "file",
    "path",
    "image",
    "ifc",
    "csv",
    "host",
    "document",
    "model",
})


# ---------------------------------------------------------------------------
# Public API


def validate(spec: dict[str, Any]) -> ValidationResult:
    """Validate a raw spec dict against ModularNodeSpec.

    The LLM emits a JSON object via `library.create_node_type(spec=...)`;
    this function decides whether that object is acceptable.

    Returns a ValidationResult — never raises. Pydantic's ValidationError is
    flattened into a list of readable strings (one per failed field).
    """
    if not isinstance(spec, dict):
        return ValidationResult(
            ok=False,
            violations=[
                f"spec must be a JSON object, got {type(spec).__name__}"
            ],
        )

    try:
        ModularNodeSpec.model_validate(spec)
        return ValidationResult(ok=True, violations=[])
    except ValidationError as ex:
        return ValidationResult(
            ok=False,
            violations=_flatten_pydantic_errors(ex),
        )


def schema_json() -> dict:
    """The JSON Schema for ModularNodeSpec — for the JSX client validator
    + for documentation. Stable across calls.
    """
    return ModularNodeSpec.model_json_schema()


def resolve_port_type(value: str) -> ResolvedPortType:
    """Map a raw `port_type` string to its taxonomy bucket.

    Design-system token 8 (AgDR-0014). During the Speckle migration the
    validator accepts any non-empty string but callers may surface a
    non-fatal WARNING when `kind=="free"`. M1+ tightens the taxonomy by
    expanding the recognised speckle / legacy sets.
    """
    v = (value or "").strip()
    if not v:
        return ResolvedPortType("free", "")
    if v.startswith(_SPECKLE_PREFIX):
        return ResolvedPortType("speckle", v)
    lowered = v.lower()
    if lowered in _LEGACY_PORT_TYPES:
        return ResolvedPortType("legacy", lowered)
    return ResolvedPortType("free", v)


# ---------------------------------------------------------------------------
# Helpers


def _flatten_pydantic_errors(ex: ValidationError) -> list[str]:
    """Format Pydantic v2 ValidationError into human-readable violations.

    Each Pydantic error becomes one line; the field path is rendered as
    dotted (e.g. `outputs[0].name`) so the LLM can see exactly what to
    fix without re-reading the whole schema.
    """
    out: list[str] = []
    for err in ex.errors():
        loc = ".".join(_render_loc(part) for part in err["loc"])
        msg = err.get("msg", "invalid")
        # Strip Pydantic's "Input should be a valid string" preamble noise
        # — keep the actionable part.
        cleaned = msg.replace("Input should be ", "must be ")
        out.append(f"{loc}: {cleaned}" if loc else cleaned)
    return out


def _render_loc(part: Any) -> str:
    if isinstance(part, int):
        return f"[{part}]"
    return str(part)
