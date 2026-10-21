"""One source for governed wire parameters."""
from __future__ import annotations


WIRE_PARAMETER_SPECS = (
    {"k": "enabled", "label": "Enabled", "type": "toggle", "def": True,
     "help": "Mute the connection without deleting it - downstream sees nothing."},
    {"k": "lacing", "label": "Lacing", "type": "menu", "def": "shortest",
     "opts": ["shortest", "longest", "cross product"],
     "help": "How lists of different length are paired."},
    {"k": "tree", "label": "Data tree", "type": "menu", "def": "none",
     "opts": ["none", "flatten", "graft", "simplify"],
     "help": "Restructure on the way through - flatten, graft, or simplify."},
    {"k": "condition", "label": "Condition", "type": "text", "def": "", "page": "Rules",
     "help": "The wire only carries when this holds. Empty means always."},
    {"k": "on_fail", "label": "On block", "type": "menu", "def": "block",
     "opts": ["block", "pass last", "pass empty"], "page": "Rules",
     "help": "What downstream receives when the condition blocks or the source errors."},
    {"k": "throttle_ms", "label": "Throttle", "type": "number", "def": 0,
     "unit": "ms", "min": 0, "max": 2000, "step": 50, "page": "Rules",
     "help": "Minimum gap between deliveries for a wire fed by a live host."},
    {"k": "operation", "label": "Operation", "type": "menu", "def": "pass",
     "opts": ["pass", "first", "flatten", "count", "scale", "clamp", "round"],
     "help": "Transform the delivered value; pass keeps today's behavior."},
)


def row_default(value) -> str:
    return ("true" if value else "false") if isinstance(value, bool) else str(value)


WIRE_PARAMETER_DEFAULTS = {
    str(spec["k"]): row_default(spec["def"]) for spec in WIRE_PARAMETER_SPECS
}
