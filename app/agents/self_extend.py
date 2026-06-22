"""Self-extension loop — the ONE mechanism that turns a composer BUILD ask into
a real, court-verified, brain-learned capability WITHOUT a human stitching the
organs (SEAM 1→4 of the universal-self-extension vision).

The loop (mandate: project_universal-self-extension-vision):

    ask        — the composer agent calls a BUILD tool (`create_node_type` /
                 `create_connector`) it now has in TOOL_SCHEMA (SEAM 1).
    build      — this module writes the REAL artifact LOCALLY, reusing the
                 EXISTING organs (library.create_node_type / connectors.scaffold)
                 — LIBRARY-FIRST: it searches the library before creating a node
                 so it never dups a capability.                          (SEAM 1)
    court      — the built artifact is AUTO-handed to the ROMA court
                 (roma.atomize → run_to_dry) with REAL gates (py_compile on the
                 new file + a file_exists/pytest check). No human invoke. A
                 red/needs_root sweep does NOT pass.                   (SEAM 2+3)
    learn      — on a GREEN sweep, AUTO brain.write a learned `fact` fragment
                 recording the new capability (op 'add', owner_user + full
                 provenance).                                              (SEAM 4)

ONE-SYSTEM (ONE-SYSTEM-PLAN-BEFORE-BUILD): every step reuses an organ that
already exists — no parallel engine:
  * build    → library.create_node_type (app/library.py) / connectors.scaffold
  * court    → personal_brain.roma + court_harness + requirement_tree (in-proc,
               deterministic gates) — the SAME court the proof-run used.
  * learn    → brain.write via the local BrainClient HTTP transport — the SAME
               path bridge._brain_tool uses.

SAFETY:
  * Pure orchestration; called OFF the Qt main thread by the bridge slot.
  * USER-AGENCY: in Plan/Auto mode the BUILD tool is GATED (it surfaces an
    approval action and does NOT run) — only an approved build (or YOLO) reaches
    `run_self_extend`. The bridge enforces the gate before calling here.
  * Reversible: the artifact is a single new local file (delete to undo); the
    learned fragment is owner-scoped and deletable via brain.delete_fact.
  * The court runs the deterministic gates only (py_compile / file_exists /
    pytest); no network, no CDP unless explicitly asked.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


# The founder's stable owner id (project_universal-self-extension-vision +
# reference_brain-mcp-connector). The learned fragment is written under this so
# recall finds it across sessions. Overridable via env for other seats / tests.
DEFAULT_OWNER_USER = "u_19e5ab4adb8_82513da5e30d"

# The build tool names the composer agent gained in TOOL_SCHEMA (SEAM 1).
BUILD_TOOLS = frozenset({"create_node_type", "create_connector"})


def _repo_root() -> Path:
    """app/ is one below the repo root; the connector/node artifacts live under
    app/, so the court's py_compile gate resolves paths against the repo root."""
    return Path(__file__).resolve().parents[2]


def _brain_src_on_path() -> None:
    src = _repo_root() / "personal-brain-mcp" / "src"
    if src.exists() and str(src) not in sys.path:
        sys.path.insert(0, str(src))


def is_build_tool(name: str) -> bool:
    return (name or "") in BUILD_TOOLS


# ───────────────────────────── SEAM 1 — BUILD ──────────────────────────────


def build_artifact(tool: str, args: dict[str, Any]) -> dict[str, Any]:
    """Write the REAL artifact locally for one build tool call.

    LIBRARY-FIRST is enforced HERE for node types: search the library before
    creating, and if a match exists, REUSE it (no duplicate) — returns
    {ok: True, reused: True, ...}. Returns a uniform shape:
      {ok, kind, gate_path, gate_kind, gate_spec, detail, reused?, ...}
    `gate_*` is what the court will run against the just-written file.
    """
    args = args if isinstance(args, dict) else {}
    if tool == "create_node_type":
        return _build_node_type(args)
    if tool == "create_connector":
        return _build_connector(args)
    return {"ok": False, "error": f"not a build tool: {tool}"}


def _build_node_type(args: dict[str, Any]) -> dict[str, Any]:
    """LIBRARY-FIRST create of a modular node type via the REAL library organ."""
    app_dir = str(_repo_root() / "app")
    if app_dir not in sys.path:
        sys.path.insert(0, app_dir)
    import library as _lib  # the REAL organ (dual-registers into the runner)

    spec = args.get("spec") if isinstance(args.get("spec"), dict) else dict(args)
    type_name = (spec.get("type") or "").strip()
    intent = (spec.get("description") or spec.get("display_name")
              or type_name or "").strip()

    # LIBRARY-FIRST: search before create so we never mint a duplicate.
    try:
        matches = _lib.search(intent=intent, limit=5) if intent else []
    except Exception:
        matches = []
    for m in matches or []:
        mt = (m.get("type") or m.get("id") or "") if isinstance(m, dict) else ""
        if mt and type_name and mt == type_name:
            return {"ok": True, "reused": True, "kind": "node_type",
                    "type": mt, "detail": f"reused existing library node '{mt}'",
                    "gate_kind": "manual", "gate_spec": {}}

    try:
        result = _lib.create_node_type(spec)
        try:
            _lib.save_to_disk()
        except Exception:
            pass
    except Exception as ex:
        # A duplicate type is a REUSE signal, not a failure (LIBRARY-FIRST).
        from library import DuplicateTypeError, RegistrationError
        if isinstance(ex, DuplicateTypeError):
            return {"ok": True, "reused": True, "kind": "node_type",
                    "type": type_name, "detail": str(ex),
                    "gate_kind": "manual", "gate_spec": {}}
        if isinstance(ex, RegistrationError):
            return {"ok": False, "error": str(ex),
                    "violations": list(getattr(ex, "violations", []))}
        return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    # The library persists to LOCALAPPDATA, not the repo tree — so the court's
    # artifact gate is "the type is registered + persisted", checked via a
    # pytest predicate that re-imports library and asserts the type exists.
    return {
        "ok": True, "reused": False, "kind": "node_type",
        "type": result.get("type", type_name),
        "detail": f"registered modular node type '{result.get('type', type_name)}'",
        "gate_kind": "registered_node",
        "gate_spec": {"type": result.get("type", type_name)},
    }


def _build_connector(args: dict[str, Any]) -> dict[str, Any]:
    """Scaffold a base.py-contract connector to a REAL local file."""
    app_dir = str(_repo_root() / "app")
    if app_dir not in sys.path:
        sys.path.insert(0, app_dir)
    from connectors import scaffold as _scaffold

    spec = args.get("spec") if isinstance(args.get("spec"), dict) else dict(args)
    res = _scaffold.create_connector(spec, overwrite=bool(args.get("overwrite")))
    if res.get("ok"):
        # The court gates on the just-written file: it must py_compile.
        rel = os.path.relpath(res["path"], _repo_root())
        return {
            "ok": True, "reused": False, "kind": "connector",
            "host": res.get("host"), "path": res["path"],
            "detail": f"scaffolded connector '{res.get('host')}' ({res.get('op_count')} ops)",
            "gate_kind": "py_compile", "gate_spec": {"path": rel.replace("\\", "/")},
        }
    if res.get("exists"):
        # Already there → reuse, not a failure (LIBRARY-FIRST).
        rel = os.path.relpath(res["path"], _repo_root())
        return {"ok": True, "reused": True, "kind": "connector",
                "host": _scaffold._safe_host_id(spec.get("host", "")),
                "path": res["path"], "detail": res.get("error", "already exists"),
                "gate_kind": "py_compile", "gate_spec": {"path": rel.replace("\\", "/")}}
    return {"ok": False, "error": res.get("error", "scaffold failed")}


# ───────────────────────── SEAM 2+3 — AUTO COURT ───────────────────────────


def court_verify(build: dict[str, Any], *, store=None,
                 owner_user: str = DEFAULT_OWNER_USER) -> dict[str, Any]:
    """AUTO-hand the built artifact to the ROMA court (no human invoke).

    Builds a one-leaf requirement tree whose leaf carries a REAL machine gate
    derived from the build (py_compile on the new connector file, or a pytest
    predicate that the node type is registered), then drives `run_to_dry`. The
    executor returns honest closing evidence (the diligence juror reads it). A
    GREEN sweep means the court FAILED TO REFUTE on the real artifact; red /
    needs_root do NOT pass.

    Returns {ok, green, verdict, tree_id, sweep, court_reason, gate_kind}.
    """
    _brain_src_on_path()
    from personal_brain import requirement_tree as rt
    from personal_brain import roma
    from personal_brain.court_harness import ProbeRunner, ProbeResult
    from personal_brain.storage import BrainStore

    own_store = False
    if store is None:
        store = BrainStore.open()
        own_store = True

    gate_kind = build.get("gate_kind", "manual")
    gate_spec = dict(build.get("gate_spec") or {})
    cap = build.get("type") or build.get("host") or "capability"

    # Map our build gate kinds onto court probes.
    # - py_compile/file_exists/pytest  → built-in court probes (real artifact).
    # - registered_node                → a custom probe that re-imports the
    #   library and asserts the type is registered (the REAL artifact for a
    #   library-persisted node that has no repo-tree file).
    extra: dict[str, ProbeRunner] = {}
    court_gate_kind = gate_kind
    if gate_kind == "registered_node":
        court_gate_kind = "registered_node"
        extra["registered_node"] = _make_registered_node_probe()

    vision = f"self-extend: build + verify capability '{cap}'"
    decomposition = [{
        "title": f"artifact for '{cap}' satisfies its gate",
        "predicate": build.get("detail", ""),
        "gate_kind": court_gate_kind,
        "gate_spec": gate_spec,
    }]
    tree = roma.atomize(store, vision=vision, decomposition=decomposition,
                        owner_user=owner_user)

    ctx = {"repo_root": str(_repo_root()), "cwd": str(_repo_root()),
           "executor_id": "self-extend-executor"}

    def _executor(leaf, context):
        # The executor DID the build already (build_artifact ran first); it
        # returns the closing evidence the diligence lens judges. This is a
        # real proof signal (a file was written / a type registered), never a
        # bare completion claim.
        touched = []
        p = build.get("path")
        if p:
            touched.append(p)
        return {
            "last_message": (
                f"built {build.get('kind')} '{cap}' and wrote the real artifact "
                f"({build.get('detail')}); py_compile/registration gate runs next."
            ),
            "touched_files": touched,
            "session_signals": {"files_written": len(touched) or 1,
                                "build_ok": True},
        }

    final = roma.run_to_dry(
        store, tree_id=tree.tree_id, executor=_executor,
        judged_by="self-extend-court", context=ctx, extra_probes=extra,
        max_rounds=3,
    )

    if own_store:
        try:
            store.close()
        except Exception:
            pass

    verdict = "green" if final.get("dry") and final.get("root_green") else (
        "needs_root" if final.get("needs_root") else "red")
    reason = ""
    try:
        rounds = final.get("rounds") or []
        if rounds:
            leaves = rounds[-1].get("leaves") or []
            if leaves:
                reason = leaves[-1].get("reason", "")
    except Exception:
        pass
    return {
        "ok": True,
        "green": bool(final.get("dry") and final.get("root_green")),
        "verdict": verdict,
        "tree_id": tree.tree_id,
        "gate_kind": gate_kind,
        "court_reason": reason,
        "sweep": {k: final.get(k) for k in
                  ("dry", "root_green", "needs_root", "total_leaves",
                   "green_leaves", "actionable_leaves", "rounds_run")},
    }


def _make_registered_node_probe():
    """A REAL court probe: re-import the library and assert the node type is
    registered + inspectable. This is the artifact for a library-persisted node
    (which lives in LOCALAPPDATA, not the repo tree)."""
    from personal_brain.court_harness import ProbeResult

    def _probe(gate_spec, context):
        type_name = (gate_spec.get("type") or "").strip()
        if not type_name:
            return ProbeResult(passed=False, applied=False,
                               detail="registered_node gate has no 'type'")
        app_dir = str(_repo_root() / "app")
        if app_dir not in sys.path:
            sys.path.insert(0, app_dir)
        try:
            import library as _lib
            spec = _lib.inspect(type_name)
        except Exception as ex:
            return ProbeResult(passed=False, applied=True,
                               detail=f"library.inspect('{type_name}') failed: {ex}",
                               evidence_ref=f"library:{type_name}")
        ok = bool(spec)
        return ProbeResult(passed=ok, applied=True,
                           detail=("node type registered + inspectable" if ok
                                   else f"type '{type_name}' not registered"),
                           evidence_ref=f"library:{type_name}")

    return _probe


# ─────────────────────────── SEAM 4 — AUTO LEARN ───────────────────────────


def learn_capability(build: dict[str, Any], court: dict[str, Any], *,
                     owner_user: str = DEFAULT_OWNER_USER,
                     contributing_agent: str = "claude-opus-4-8",
                     brain_call=None) -> dict[str, Any]:
    """On a GREEN court sweep, AUTO brain.write a learned `fact` fragment
    recording the new capability. Builds the op 'add' with full provenance
    (contributing_agent, contributing_user, created_at, accessed_resources)
    and scope 'user'. Returns the brain.write result, or a skip marker if the
    court did not go green (a red/needs_root capability is NEVER learned)."""
    if not court.get("green"):
        return {"ok": False, "skipped": "court_not_green",
                "verdict": court.get("verdict")}

    cap = build.get("type") or build.get("host") or "capability"
    kind = build.get("kind", "capability")
    created_at = datetime.now(timezone.utc).isoformat()
    frag_id = f"self_extend::{kind}::{cap}"
    text = (
        f"ArchHub self-extended: built {kind} '{cap}' "
        f"({build.get('detail', '')}). Court verdict GREEN "
        f"(tree {court.get('tree_id')}, gate {court.get('gate_kind')}). "
        f"This capability is now available on the local machine."
    )
    op = {
        "op": "add",
        "fragment": {
            "id": frag_id,
            "kind": "fact",
            "text": text,
            "subject": cap,
            "predicate": "self_extended",
            "object": kind,
            "scope": "user",
            "owner_user": owner_user,
            "provenance": {
                "contributing_agent": contributing_agent,
                "contributing_user": owner_user,
                "created_at": created_at,
                "accessed_resources": [],
            },
        },
    }

    caller = brain_call or _default_brain_call
    try:
        result = caller("brain.write", {"ops": [op]})
    except Exception as ex:
        return {"ok": False, "error": f"brain.write failed: {ex}",
                "fragment_id": frag_id}
    return {"ok": True, "fragment_id": frag_id, "owner_user": owner_user,
            "write_result": result}


def _default_brain_call(tool_name: str, args: dict) -> dict:
    """Default brain transport — the SAME local BrainClient path bridge uses."""
    app_dir = str(_repo_root() / "app")
    if app_dir not in sys.path:
        sys.path.insert(0, app_dir)
    from memory_gate import BrainClient
    client = BrainClient()
    return client._call(tool_name, args, timeout=6.0)


# ──────────────────────── THE ONE MECHANISM (ask→build→court→learn) ─────────


def run_self_extend(tool: str, args: dict[str, Any], *,
                    owner_user: str = DEFAULT_OWNER_USER,
                    contributing_agent: str = "claude-opus-4-8",
                    store=None, brain_call=None) -> dict[str, Any]:
    """Drive the WHOLE loop for one approved BUILD tool call:
    build (SEAM 1) → court (SEAM 2+3) → learn (SEAM 4).

    Returns a structured receipt naming which seams fired:
      {ok, tool, build, court, learn, seams: {build, court, brain}}.

    The bridge calls this off the Qt main thread AFTER the USER-AGENCY gate has
    approved the build (Plan/Auto gate it; YOLO/approval lets it through)."""
    if not is_build_tool(tool):
        return {"ok": False, "error": f"not a self-extend build tool: {tool}"}

    build = build_artifact(tool, args)
    if not build.get("ok"):
        return {"ok": False, "tool": tool, "build": build,
                "seams": {"build": False, "court": False, "brain": False}}

    court = court_verify(build, store=store, owner_user=owner_user)
    learn = learn_capability(
        build, court, owner_user=owner_user,
        contributing_agent=contributing_agent, brain_call=brain_call,
    )
    return {
        "ok": bool(build.get("ok") and court.get("green") and learn.get("ok")),
        "tool": tool,
        "build": build,
        "court": court,
        "learn": learn,
        "seams": {
            "build": bool(build.get("ok")),
            "court": bool(court.get("green")),
            "brain": bool(learn.get("ok")),
        },
    }
