"""Legacy typed-runtime type compatibility table for wires.

Wires only connect ports whose types match OR are explicitly coercible
under the table here. The table is intentionally **explicit, not duck
typed** — if a coercion isn't listed, the canvas refuses to draw the
wire. That refusal is the user feedback that prevents the most common
ComfyUI-class footgun of "looks compatible, blows up at run time".

Three layers:

  1. Identity — same type connects.
  2. ANY      — ANY input or output trivially matches anything.
  3. Coercion — listed pairs are accepted; arrows indicate direction
                (output type → input type).

Execution pins (EXEC) connect only to other EXEC pins. Data pins
never wire into EXEC pins and vice versa.

The function `can_wire(output, input)` is what the canvas calls
before drawing the rubber-band line and committing the wire.

This table is compatibility machinery for the old typed runtime. Universal Cell
authority represents types/contracts as graph protocols, not enum dispatch.
"""
from __future__ import annotations

from .graph import PortType, normalize_port_type_ref, port_type_id

TypeRef = PortType | str

LEGACY_MIGRATION_ONLY = True
AUTHORITY_STATUS = "superseded_by_universal_cell"
ACTIVE_AUTHORITY = "10.PRODUCT/13.NODE-LANGUAGE"
PROMOTION_ALLOWED = False

# Output type → set of input types it can flow into. Direction matters
# because some coercions are one-way (e.g. WALL → SELECTION is
# trivially fine, SELECTION → WALL needs an explicit unpack node).
_COERCIONS: dict[PortType, set[PortType]] = {
    # Primitives
    PortType.STRING:    {PortType.PROMPT, PortType.MESSAGE, PortType.PATH},
    PortType.NUMBER:    set(),
    PortType.BOOLEAN:   set(),
    PortType.OBJECT:    set(),
    PortType.LIST:      {PortType.SELECTION},
    # Bridge
    PortType.HOST:      set(),
    PortType.DOCUMENT:  {PortType.MODEL, PortType.FILE},
    PortType.MODEL:     {PortType.DOCUMENT},
    PortType.PROJECT:   set(),
    # AI
    PortType.PROMPT:    {PortType.STRING, PortType.MESSAGE},
    PortType.MESSAGE:   {PortType.STRING},
    PortType.CONVERSATION: set(),
    PortType.INTENT:    {PortType.STRING},
    PortType.COMPLETION: {PortType.STRING, PortType.MESSAGE},
    PortType.TOOL_RESULT: {PortType.OBJECT},
    # AEC entities
    PortType.ELEMENT:   {PortType.SELECTION},
    PortType.SELECTION: {PortType.LIST},   # iterate-as-list
    # Files
    PortType.FILE:      {PortType.PATH, PortType.STRING},
    PortType.PATH:      {PortType.STRING},
    PortType.IMAGE:     set(),
    PortType.IFC:       {PortType.FILE, PortType.DOCUMENT},
    PortType.CSV:       {PortType.FILE, PortType.LIST},
    # Geometry
    PortType.GEOMETRY:  set(),
    # Control flow — exec is segregated (never coerces to data)
    PortType.EXEC:      set(),
    PortType.CRON:      {PortType.TRIGGER},
    PortType.TRIGGER:   {PortType.EXEC},     # a trigger fires an exec
    PortType.EVENT:     {PortType.TRIGGER, PortType.EXEC},
    # ANY is handled outside the table (always matches)
    PortType.ANY:       set(),
}


def normalize_type_ref(value: TypeRef | None) -> str:
    """Return an open type identifier without collapsing unknown types.

    ``PortType`` remains a legacy convenience vocabulary. New types are plain
    namespaced strings and require no enum or engine change.
    """
    return port_type_id(normalize_port_type_ref(value))


def _matches_type_family(output_ref: str, input_ref: str) -> bool:
    if input_ref.endswith(".*"):
        prefix = input_ref[:-1]
        return output_ref.startswith(prefix)
    if input_ref.endswith("/*"):
        prefix = input_ref[:-1]
        return output_ref.startswith(prefix)
    return False


def can_wire(output_port_type: TypeRef, input_port_type: TypeRef,
              *, output_is_exec: bool = False,
              input_is_exec: bool = False) -> bool:
    """Return True if a wire can be drawn from output → input.

    EXEC-ness of each end MUST match — you can't connect a data pin to
    an execution pin. Pass `output_is_exec` / `input_is_exec` from
    `Port.exec` on the caller side.
    """
    if bool(output_is_exec) != bool(input_is_exec):
        # exec / data mismatch — never connectable
        return False
    if output_is_exec and input_is_exec:
        # Exec wires connect any exec-typed ports; the type discriminant
        # is the `exec` flag itself, not the PortType.
        return True
    output_ref = normalize_type_ref(output_port_type)
    input_ref = normalize_type_ref(input_port_type)
    # Data wires:
    if output_ref == input_ref:
        return True
    if output_ref == PortType.ANY.value or input_ref == PortType.ANY.value:
        return True
    if _matches_type_family(output_ref, input_ref):
        return True
    try:
        output_key = PortType(output_ref)
    except ValueError:
        output_key = None
    legacy_inputs = _COERCIONS.get(output_key, set()) if output_key is not None else set()
    return input_ref in {normalize_type_ref(value) for value in legacy_inputs}


def list_compatible_inputs(output_type: TypeRef) -> list[TypeRef]:
    """For UI helpers — what input types accept this output?"""
    if isinstance(output_type, PortType) and output_type == PortType.ANY:
        return list(PortType)
    if not isinstance(output_type, PortType):
        output_ref = normalize_type_ref(output_type)
        return sorted({output_ref, PortType.ANY.value})
    out = {output_type}
    out |= _COERCIONS.get(output_type, set())
    out.add(PortType.ANY)
    return sorted(out, key=lambda t: t.value)
