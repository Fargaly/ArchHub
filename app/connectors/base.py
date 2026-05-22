"""Uniform connector contract — the spine every host connector implements.

Founder mandate 2026-05-15: ALL 18 host connectors working, orchestrated.
Before today every `*_runner.py` had its own ad-hoc shape (Outlook = COM,
Blender = HTTP-to-addon, Procore = REST). This module gives them ONE
contract so the workflow registry, the bridge, host_detector and the
canvas can treat every host identically.

A connector exposes a set of OPERATIONS. Each operation is either:
  * a READ   — pulls data out of the host, no side effects, safe to call
               speculatively (list views, read a range, list emails)
  * an ACTION — mutates the host or the outside world, needs user intent
               (create a dimension, write a cell, send a draft)

The split mirrors the MCP resources-vs-tools distinction and lets the
agent reason about what is safe to call without confirmation.

Every connector method is best-effort and must never raise to the
caller — they return an `OpResult` with `ok=False` + `error` instead, so
one broken host never takes down the canvas.
"""
from __future__ import annotations

import time
import traceback
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


# ── operation result ────────────────────────────────────────────────
@dataclass
class OpResult:
    """The return shape of every connector operation."""
    ok: bool
    value: Any = None                       # the payload (list/dict/scalar)
    value_preview: str = ""                 # short human summary for the node body
    error: str = ""
    elapsed_ms: int = 0
    op_id: str = ""

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "value": self.value,
            "value_preview": self.value_preview,
            "error": self.error,
            "elapsed_ms": self.elapsed_ms,
            "op_id": self.op_id,
        }

    @staticmethod
    def fail(msg: str, op_id: str = "") -> "OpResult":
        return OpResult(ok=False, error=str(msg), op_id=op_id)


# ── parameter definition ────────────────────────────────────────────
@dataclass
class ParamSpec:
    """One typed input parameter for an operation."""
    id: str
    label: str
    type: str = "text"        # text|number|bool|choice|multi|list|range|file
    default: Any = None
    options: list = field(default_factory=list)   # for choice/multi
    options_source: str = ""  # name of a connector method that returns options
    required: bool = False
    help: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id, "label": self.label, "type": self.type,
            "default": self.default, "options": list(self.options),
            "options_source": self.options_source,
            "required": self.required, "help": self.help,
        }


# ── operation definition ────────────────────────────────────────────
@dataclass
class ConnectorOp:
    """One callable operation a connector exposes."""
    op_id: str                              # unique, e.g. "excel.read_range"
    host: str                               # "excel"
    kind: str                               # "read" | "action"
    label: str                              # "Read range"
    description: str = ""
    inputs: list = field(default_factory=list)      # list[ParamSpec]
    output_type: str = "any"                # graph PortType name
    destructive: bool = False               # action that needs explicit confirm
    fn: Optional[Callable[..., Any]] = None # the implementation

    def run(self, **params) -> OpResult:
        """Invoke the operation. Times it, catches everything, always
        returns an OpResult so a single bad call can never crash the
        canvas or the bridge."""
        t0 = time.time()
        if self.fn is None:
            return OpResult.fail(f"{self.op_id}: not implemented", self.op_id)
        try:
            raw = self.fn(**params)
        except Exception as ex:
            return OpResult(
                ok=False, op_id=self.op_id,
                error=f"{type(ex).__name__}: {ex}",
                elapsed_ms=int((time.time() - t0) * 1000),
            )
        elapsed = int((time.time() - t0) * 1000)
        if isinstance(raw, OpResult):
            raw.elapsed_ms = raw.elapsed_ms or elapsed
            raw.op_id = raw.op_id or self.op_id
            return raw
        # Bare return value — wrap it.
        return OpResult(ok=True, value=raw, op_id=self.op_id,
                         elapsed_ms=elapsed,
                         value_preview=_preview(raw))

    def to_dict(self) -> dict:
        return {
            "op_id": self.op_id, "host": self.host, "kind": self.kind,
            "label": self.label, "description": self.description,
            "inputs": [p.to_dict() for p in self.inputs],
            "output_type": self.output_type,
            "destructive": self.destructive,
        }


def _preview(value: Any, limit: int = 80) -> str:
    """Short human summary of an op's return value for the node body."""
    try:
        if value is None:
            return "—"
        if isinstance(value, (list, tuple)):
            return f"{len(value)} item{'s' if len(value) != 1 else ''}"
        if isinstance(value, dict):
            return f"{len(value)} field{'s' if len(value) != 1 else ''}"
        s = str(value)
        return s if len(s) <= limit else s[:limit] + "…"
    except Exception:
        return "?"


# ── connector base ──────────────────────────────────────────────────
class Connector(ABC):
    """Base class every host connector subclasses.

    An ABC (founder mandate 2026-05-18): `probe()` and `build_ops()` are
    `@abstractmethod`, so a connector that fails to implement EITHER
    cannot be instantiated — it fails loud at import instead of
    shipping as a silent shell. tests/test_connector_contract.py is the
    CI-side twin that also checks every op is well-formed.

    Subclass contract:
      host          — the host id ("excel", "speckle", ...)
      display_name  — human label
      mechanism     — "com" | "broker" | "python_api" | "rest" | "local_llm"
      probe()       — returns {"status": "live"|"loaded_dead"|"missing"|
                               "unauthorized", "note": str, "detail": dict}
      build_ops()   — returns list[ConnectorOp]

    `ops()` memoises build_ops(). `op(op_id)` looks one up.
    """

    host: str = ""
    display_name: str = ""
    mechanism: str = ""

    def __init__(self) -> None:
        self._ops_cache: Optional[list] = None

    # -- status -------------------------------------------------------
    @abstractmethod
    def probe(self) -> dict:
        """MUST be overridden. Returns {"status": ..., "note": str,
        "detail": dict} — status is live / loaded_dead / missing /
        unauthorized."""
        raise NotImplementedError

    # -- operations ---------------------------------------------------
    @abstractmethod
    def build_ops(self) -> list:
        """MUST be overridden. Returns list[ConnectorOp]."""
        raise NotImplementedError

    def ops(self) -> list:
        if self._ops_cache is None:
            try:
                self._ops_cache = list(self.build_ops() or [])
            except Exception:
                traceback.print_exc()
                self._ops_cache = []
        return self._ops_cache

    def op(self, op_id: str) -> Optional[ConnectorOp]:
        for o in self.ops():
            if o.op_id == op_id:
                return o
        return None

    def to_dict(self) -> dict:
        st = {}
        try:
            st = self.probe()
        except Exception as ex:
            st = {"status": "missing", "note": f"probe failed: {ex}",
                  "detail": {}}
        return {
            "host": self.host,
            "display_name": self.display_name,
            "mechanism": self.mechanism,
            "status": st.get("status", "missing"),
            "note": st.get("note", ""),
            "ops": [o.to_dict() for o in self.ops()],
        }


# ── global connector registry ───────────────────────────────────────
_CONNECTORS: dict[str, Connector] = {}


def register(connector: Connector) -> None:
    """Register a connector instance under its host id."""
    if connector and connector.host:
        _CONNECTORS[connector.host] = connector


def get(host: str) -> Optional[Connector]:
    return _CONNECTORS.get(host)


def all_connectors() -> list:
    return list(_CONNECTORS.values())


def all_ops() -> list:
    """Every operation across every registered connector."""
    out: list = []
    for c in _CONNECTORS.values():
        out.extend(c.ops())
    return out


def run_op(op_id: str, **params) -> OpResult:
    """Resolve an op_id across all connectors and run it."""
    host = op_id.split(".", 1)[0] if "." in op_id else ""
    c = get(host)
    if c is None:
        return OpResult.fail(f"no connector for host '{host}'", op_id)
    o = c.op(op_id)
    if o is None:
        return OpResult.fail(f"unknown op '{op_id}'", op_id)
    return o.run(**params)


def load_all_connectors() -> int:
    """Import every connector module so each self-registers. Returns the
    count registered. Best-effort — a broken connector module is skipped,
    never fatal.
    """
    import importlib
    modules = [
        "connectors.word_connector",
        "connectors.excel_connector",
        "connectors.powerpoint_connector",
        "connectors.outlook_connector",
        "connectors.photoshop_connector",
        "connectors.illustrator_connector",
        "connectors.indesign_connector",
        "connectors.speckle_connector",
        "connectors.notion_connector",
        "connectors.dropbox_connector",
        "connectors.teams_connector",
        "connectors.blender_connector",
        "connectors.rhino_connector",
        "connectors.revit_connector",
        "connectors.autocad_connector",
        "connectors.max_connector",
    ]
    for m in modules:
        try:
            importlib.import_module(m)
        except Exception:
            # Connector not built yet, or its host SDK is missing —
            # skip it. The host simply won't appear until its module
            # lands. Never fatal.
            pass
    return len(_CONNECTORS)
