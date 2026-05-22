"""Type compatibility table for wires (ADR-003).

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
"""
from __future__ import annotations

from .graph import PortType

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


def can_wire(output_port_type: PortType, input_port_type: PortType,
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
    # Data wires:
    if output_port_type == input_port_type:
        return True
    if output_port_type == PortType.ANY or input_port_type == PortType.ANY:
        return True
    return input_port_type in _COERCIONS.get(output_port_type, set())


def list_compatible_inputs(output_type: PortType) -> list[PortType]:
    """For UI helpers — what input types accept this output?"""
    if output_type == PortType.ANY:
        return list(PortType)
    out = {output_type}
    out |= _COERCIONS.get(output_type, set())
    out.add(PortType.ANY)
    return sorted(out, key=lambda t: t.value)
