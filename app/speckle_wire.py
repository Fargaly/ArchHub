"""Speckle Wire — M1 (AgDR-0012 §"Architecture, in one paragraph").

Direction X commits: "every wire is a Speckle `Operations.send/receive`
segment." This module is the substrate.

  • SpeckleWire   — wraps specklepy `operations.send / .receive`.
  • Per-project `.speckle/<project>/speckle.db` SQLiteTransport (default).
  • Coerces Python values (primitives, dicts, lists) to `Base` objects
    on send; unwraps to plain Python on receive.
  • Hash-equality dirty-tracking: identical input → identical hash →
    downstream nodes can cache outputs by hash.

What it does NOT do (yet):
  • Replace `WorkflowRunner` wire serialization (M1.b — deferred slice).
  • ServerTransport / cloud push — `speckle_server.py` + SHARE typed
    nodes handle that in M1.5.

Founder decision 2026-05-21:
  • DiskTransport (SQLiteTransport at project path) stays the default
    substrate. Server is OPT-IN via SHARE nodes (`speckle.publish`
    etc.) — not wired by default.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional, Union

from specklepy.objects.base import Base
from specklepy.api import operations
from specklepy.transports.sqlite import SQLiteTransport


def default_project_dir() -> Path:
    """`%LOCALAPPDATA%/ArchHub/projects/default/.speckle/` on Windows.

    M1 stores all wires under one "default" project. M3 will let the
    user pick the project; the path is per-graph after that.
    """
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "ArchHub" / "projects" / "default" / ".speckle"


# ---------------------------------------------------------------------------
# Value <-> Speckle Base coercion
#
# The grammar (slices A-K) passes Python dicts/lists/primitives between
# nodes. Speckle wires require Speckle `Base` objects. This pair makes
# the conversion automatic — engine code never needs to know about Base.


def _coerce_to_base(value: Any) -> Base:
    """Wrap a Python value in a Speckle Base.

    Strategy: JSON-wrap. Sidesteps Speckle attribute-name reservations
    (id / speckle_type / etc.) and underscore-attr filtering. Speckle
    carries the wire's payload as a single string field; ArchHub
    round-trips through `json.dumps`/`loads`.

      • Already a Base (host-extracted Wall / Mesh / Room / …) →
        pass through; treated as foreign-typed Base on receive.
      • Anything else → Base with `archhubJson` + `archhubShape="json"`.

    Reason for the JSON wrap (not per-key setattr):
      • Speckle filters underscore-prefixed attrs from serialization.
      • Some Speckle Base attr names are reserved (id, applicationId,
        speckle_type, totalChildrenCount, units).
      • Dict values can contain nested dicts / lists / None / bools
        which Speckle's attr serializer handles inconsistently across
        versions.
      • One JSON string is round-trip-safe + version-stable.
    """
    if isinstance(value, Base):
        return value
    b = Base()
    setattr(b, "archhubJson", json.dumps(value, default=str))
    setattr(b, "archhubShape", "json")
    return b


def _coerce_from_base(base: Base) -> Any:
    """Unwrap a Speckle Base back to a Python value.

    • `archhubShape == "json"` → returns `json.loads(archhubJson)`.
    • absent (foreign Base — host-extracted Wall / Mesh / Room) →
      returns the Base object itself so downstream nodes can pluck
      speckle_type / displayValue / parameters / units directly.
    """
    if getattr(base, "archhubShape", None) == "json":
        raw = getattr(base, "archhubJson", "null")
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None
    return base  # foreign Base — typed host payload, return as-is


# ---------------------------------------------------------------------------
# SpeckleWire — the substrate.


class SpeckleWire:
    """Per-project Speckle transport wrapper.

    Default transport is `SQLiteTransport` rooted at
    `<project_dir>/speckle.db`. Each `send(value)` returns a
    content-addressed hash; `receive(hash)` returns the Python value.

    Idempotent send: identical `value` → identical hash. Caller can
    skip downstream re-execution when the hash hasn't changed.
    """

    def __init__(self, project_dir: Optional[Union[str, Path]] = None,
                 *, app_name: str = "archhub") -> None:
        self.project_dir = Path(project_dir) if project_dir \
            else default_project_dir()
        self.project_dir.mkdir(parents=True, exist_ok=True)
        # Speckle's SQLiteTransport puts the DB under
        # <base_path>/<app_name>/<scope>/.
        self.transport = SQLiteTransport(
            base_path=str(self.project_dir),
            app_name=app_name,
        )

    def send(self, value: Any) -> str:
        """Push a value through the wire. Returns content-addressed hash.

        Identical values produce identical hashes — caller-side dirty
        tracking just compares hashes.

        `use_default_cache=False` is critical: specklepy's default sends
        ALSO write to a process-wide cache at `%APPDATA%/Speckle/Objects.db`.
        That would silently merge every project's wires into one shared
        store, defeating per-project isolation.
        """
        base = _coerce_to_base(value)
        return operations.send(base, [self.transport],
                                use_default_cache=False)

    def receive(self, hash_: str) -> Any:
        """Read the value previously sent under `hash_`.

        Pass our transport as `local_transport` so specklepy doesn't
        fall back to the system-wide default cache.
        """
        base = operations.receive(hash_, local_transport=self.transport)
        return _coerce_from_base(base)

    def send_base(self, base: Base) -> str:
        """Skip-coerce variant: send a Speckle Base directly. Used by
        host connectors (Speckle Revit etc.) whose extractors already
        produce typed Base objects (Wall, Room, Mesh, …)."""
        return operations.send(base, [self.transport],
                                use_default_cache=False)

    def receive_base(self, hash_: str) -> Base:
        """Skip-coerce variant: return the raw Speckle Base. Used by
        host receive-side adapters that need `speckle_type` + geometry."""
        return operations.receive(hash_, local_transport=self.transport)

    def close(self) -> None:
        """Closing is optional with SQLiteTransport — the underlying
        DB connection auto-closes. Kept for API parity with future
        transports (ServerTransport / MemoryTransport).
        """
        try:
            self.transport.close()
        except Exception:
            pass
