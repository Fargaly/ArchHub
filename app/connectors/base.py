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

from host_aliases import canonical_host, canonical_op_id


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
        self._ops_error: str = ""   # set when build_ops() raised, so the
                                    # failure surfaces as an honest status
                                    # instead of a silent zero-op host.

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
        """Memoised list of this connector's ops.

        If build_ops() raises we must NOT re-raise — that would crash
        connector enumeration (all_ops/registry iteration) and take a
        broken host's neighbours down with it. But we must also NOT
        silently return an empty list: a host that exposes zero ops is
        indistinguishable from a host with no capabilities, so a broken
        build_ops() would masquerade as a healthy-but-empty host. The
        honest middle ground: return [] so enumeration keeps working,
        AND record the failure on `_ops_error` so `to_dict()`/`ops_status`
        report the host as errored (loaded_dead), never as a clean zero."""
        if self._ops_cache is None:
            try:
                self._ops_cache = list(self.build_ops() or [])
                self._ops_error = ""
            except Exception as ex:
                traceback.print_exc()
                self._ops_error = f"{type(ex).__name__}: {ex}"
                self._ops_cache = []
        return self._ops_cache

    def ops_status(self) -> dict:
        """Honest report of the op layer: did build_ops() succeed?

        Returns {"ok": bool, "count": int, "error": str}. `ok=False` with
        a non-empty `error` means build_ops() raised — the host is broken,
        not capability-free. Callers use this to avoid the silent-empty
        trap when an op list comes back empty."""
        ops = self.ops()   # populates _ops_error as a side effect
        return {"ok": not self._ops_error,
                "count": len(ops),
                "error": self._ops_error}

    def op(self, op_id: str) -> Optional[ConnectorOp]:
        wanted = canonical_op_id(op_id)
        for o in self.ops():
            if o.op_id == op_id or canonical_op_id(o.op_id) == wanted:
                return o
        return None

    def to_dict(self) -> dict:
        st = {}
        try:
            st = self.probe()
        except Exception as ex:
            st = {"status": "missing", "note": f"probe failed: {ex}",
                  "detail": {}}
        ops = self.ops()                 # populates _ops_error
        status = st.get("status", "missing")
        note = st.get("note", "")
        # Honest-status rule (founder: "report honest status, never
        # fabricate"). A build_ops() failure means this host's capability
        # layer is dead. Surfacing it as the probe's status (e.g. "live")
        # with an empty op list would fake a working-but-feature-less host
        # — the exact silent-empty trap. So when build_ops() raised, mark
        # the host loaded_dead unless probe already reported a stronger
        # failure (missing/unauthorized), and always carry ops_error so the
        # break is visible downstream.
        if self._ops_error:
            if status not in ("missing", "unauthorized"):
                status = "loaded_dead"
            ops_note = f"ops unavailable — build_ops failed: {self._ops_error}"
            note = f"{note} · {ops_note}" if note else ops_note
        return {
            "host": self.host,
            "display_name": self.display_name,
            "mechanism": self.mechanism,
            "status": status,
            "note": note,
            "ops_error": self._ops_error,
            "ops": [o.to_dict() for o in ops],
        }


# ── global connector registry ───────────────────────────────────────
_CONNECTORS: dict[str, Connector] = {}


def register(connector: Connector) -> None:
    """Register a connector instance under its host id."""
    if connector and connector.host:
        connector.host = canonical_host(connector.host)
        _CONNECTORS[connector.host] = connector


def get(host: str) -> Optional[Connector]:
    return _CONNECTORS.get(canonical_host(host))


def all_connectors() -> list:
    return list(_CONNECTORS.values())


def all_ops() -> list:
    """Every operation across every registered connector."""
    out: list = []
    for c in _CONNECTORS.values():
        out.extend(c.ops())
    return out


# ── per-op hard wall-clock budget ───────────────────────────────────
# ENGINEERING-MANDATE class fix (founder 2026-06-20, "notion prompt hangs
# the chat turn"): a connector op that makes a blocking network/auth/COM
# call with no bound (e.g. notion's urlopen(timeout=30) × MAX_PAGES=10 =
# up to 300s, or a stalled broker/COM probe) BLOCKS the chat worker thread
# that dispatched it. The router buffers the model's streamed text and only
# flushes it when complete() RETURNS — so a blocked op means the user sees
# ZERO chat_chunk for the whole stall. The fix is at the SHARED chokepoint
# every connector op flows through: run_op. We run the op on a daemon
# worker and enforce a hard wall-clock deadline; on overrun we return an
# honest `unreachable` OpResult instead of blocking unbounded. This bounds
# the WHOLE connector CLASS (notion, dropbox, teams, procore, …), not one
# host. The orphaned worker is a daemon — it cannot keep the process alive
# and its eventual return is discarded.
#
# Override per call with the `_op_timeout` kwarg (seconds); 0/None disables
# the bound (used by long-running intentional ops). Default is generous
# enough for a healthy REST/COM round-trip yet far under the per-turn
# budget so the turn never starves.
DEFAULT_OP_TIMEOUT_SECONDS = 20.0


def run_op(op_id: str, **params) -> OpResult:
    """Resolve an op_id across all connectors and run it.

    The op runs under a hard wall-clock budget (`DEFAULT_OP_TIMEOUT_SECONDS`,
    overridable via the `_op_timeout` kwarg) so a slow/unreachable host can
    NEVER block the caller (the chat worker thread) unbounded — it returns an
    honest 'unreachable' OpResult at the deadline instead.
    """
    canonical_id = canonical_op_id(op_id)
    host = canonical_id.split(".", 1)[0] if "." in canonical_id else ""
    c = get(host)
    if c is None:
        return OpResult.fail(f"no connector for host '{host}'", op_id)
    o = c.op(canonical_id)
    if o is None:
        return OpResult.fail(f"unknown op '{op_id}'", op_id)

    # Pull the optional per-call override out of params — it's a transport
    # control, never a connector op input.
    timeout = params.pop("_op_timeout", DEFAULT_OP_TIMEOUT_SECONDS)
    try:
        timeout = float(timeout) if timeout is not None else 0.0
    except Exception:
        timeout = DEFAULT_OP_TIMEOUT_SECONDS
    if timeout <= 0:
        # Bound explicitly disabled — run inline (back-compat escape hatch).
        return o.run(**params)

    import concurrent.futures as _cf
    t0 = time.time()
    pool = _cf.ThreadPoolExecutor(
        max_workers=1, thread_name_prefix=f"connop-{host}")
    fut = pool.submit(o.run, **params)
    try:
        return fut.result(timeout=timeout)
    except _cf.TimeoutError:
        # The op is still running on the orphaned daemon worker; we abandon
        # it and report honestly. Do NOT pool.shutdown(wait=True) — that
        # would re-block on the very op we just timed out. Let the daemon
        # thread finish in the background; its result is discarded.
        pool.shutdown(wait=False)
        return OpResult(
            ok=False, op_id=op_id,
            error=(f"{op_id}: host unreachable — no response within "
                   f"{timeout:.0f}s (connector timed out, the chat turn "
                   f"was not blocked)."),
            elapsed_ms=int((time.time() - t0) * 1000),
        )
    except Exception as ex:
        pool.shutdown(wait=False)
        return OpResult(
            ok=False, op_id=op_id,
            error=f"{type(ex).__name__}: {ex}",
            elapsed_ms=int((time.time() - t0) * 1000),
        )
    finally:
        # Reap the pool only if the worker already finished (non-blocking);
        # a timed-out worker is left as a daemon, reaped by interpreter exit.
        if fut.done():
            pool.shutdown(wait=False)


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
        "connectors.procore_connector",
        "connectors.dropbox_connector",
        "connectors.teams_connector",
        "connectors.blender_connector",
        "connectors.rhino_connector",
        "connectors.revit_connector",
        "connectors.autocad_connector",
        "connectors.max_connector",
        # AgDR-0041-adjacent · ComfyUI + Alibaba assimilation (2026-05-24).
        "connectors.comfyui_connector",
        "connectors.dashscope_connector",
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
