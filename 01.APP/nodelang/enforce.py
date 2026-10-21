"""Enforce: inspect the pending value before an admitted effect may write it.

Approval remains a separate authority. A compiler pass grants no host permission.
Grand Map: selfext_convene_court, selfext_agency_gate, brain_court_gate,
models_mode_gate. Diagnostics travel in the ordinary node result to BABOOM.
"""
from __future__ import annotations

import copy
from functools import partial
import hashlib
import json
from pathlib import Path
from collections.abc import Mapping

def catalogue_entry():
    """One seed, imported by the base catalogue without a bootstrap cycle."""
    parameters = {
        "rule_set": {"type": "text", "editor": "text", "default": "product-v1"},
        "repo_root": {"type": "text", "editor": "text", "default": ""},
        "max_attempts": {"type": "integer", "editor": "number", "default": 3},
        "compiler_timeout": {"type": "number", "editor": "number", "default": 240},
        "compiler_rustflags": {"type": "text", "editor": "text", "default": "-C target-feature=+crt-static"},
        "compiler_jobs": {"type": "integer", "editor": "number", "default": 2},
        "post_limit": {"type": "integer", "editor": "number", "default": 3000},
        "rules": {"type": "text", "editor": "multiline", "default": '{"document":{"block_types":["paragraph","heading"]},"model":{"value_types":["string","number","integer","boolean","object","list"]},"post":{"platforms":["web"]}}'},
        "intent_rule_set": {"type": "text", "editor": "text", "default": "tools/archhub-compiler/rules.json"},
        "intent": {"type": "text", "editor": "text", "default": ""},
        "author": {"type": "text", "editor": "text", "default": ""},
        "why": {"type": "text", "editor": "multiline", "default": ""},
        "daily_alert_budget": {"type": "integer", "editor": "number", "default": 5},
    }
    interfaces = {name: {"direction": "input", "type": "string" if spec["type"] == "text" else spec["type"]}
                  for name, spec in parameters.items()}
    interfaces.update({"pending": {"direction": "input", "type": "object", "required": True},
                       "admitted": {"direction": "output", "type": "object"},
                       "diagnostics": {"direction": "output", "type": "list"},
                       "out": {"direction": "output", "type": "object"}})
    return {"name": "Enforce", "category": "Logic", "description": "Check pending writes, intent and deviation before approval.",
            "parameters": parameters, "interfaces": interfaces, "engine": "archhub.enforce"}

def defaults():
    """Settings, sockets and execution read the same catalogue seed."""
    entry = catalogue_entry()
    return {name: spec["default"] for name, spec in entry["parameters"].items()}

def _diagnostic(message, *, code="E0005", target="<pending>", help_text="Correct the pending value and retry."):
    return {"code": code, "language": "product", "file": str(target), "line": 1,
            "column": 1, "message": message, "note": "pending-value admission", "help": help_text}

def display_diagnostics(rows):
    return "\n".join("error[{code}]: {message}\n --> {file}:{line}:{column}\n note: {note}\n help: {help}".format(**dict(row, note=row.get("note", row["code"]))) for row in rows)

def pending_digest(pending):
    """Canonical exact-value identity shared by inspection, write and readback."""
    return hashlib.sha256(json.dumps(pending, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False, separators=(",", ":")).encode("utf-8")).hexdigest()

def inspect_pending(pending, params=None, *, compiler=None, artifact_compiler=None, graph_validator=None):
    """Validate actual proposed content, never the already-written destination."""
    config = {**defaults(), **dict(params or {})}
    diagnostics = []
    build_options = {"jobs": config["compiler_jobs"], "rustflags": config["compiler_rustflags"]}
    report = None
    root = Path(str(config["repo_root"]) or str(Path(__file__).resolve().parents[1])).resolve()
    context = {key: config[key] for key in ("intent", "author", "why", "daily_alert_budget", "intent_rule_set", "rules", "post_limit", "rule_set")}
    try:
        if isinstance(context["rules"], str):
            context["rules"] = json.loads(context["rules"])
    except ValueError as error:
        rows = [_diagnostic("invalid rule JSON: %s" % error, code="E0010")]
        return {"ok": False, "diagnostics": rows, "display": display_diagnostics(rows), "pending": copy.deepcopy(pending)}
    if isinstance(pending, Mapping):
        context.update({key: pending[key] for key in ("intent", "author", "why") if key in pending})
    if not isinstance(pending, Mapping):
        diagnostics.append(_diagnostic("a typed pending write is required"))
    else:
        target = pending.get("target", "<pending>")
        kind = pending.get("kind")
        if config["rule_set"] != "product-v1":
            diagnostics.append(_diagnostic("unsupported rule set: %s" % config["rule_set"], code="E0010"))
        elif not isinstance(target, str) or not target.strip():
            diagnostics.append(_diagnostic("a write must name its destination"))
        elif kind == "code":
            from tools.pipeline.strict_check import NON_CODE
            changes = pending.get("changes")
            if not isinstance(changes, Mapping) or not changes or any(type(k) is not str or (v is not None and type(v) is not str) for k, v in changes.items()):
                diagnostics.append(_diagnostic("code requires relative paths to pending UTF-8 content or null deletions", target=target))
            elif any(Path(path).suffix.lower() in NON_CODE for path in changes):
                diagnostics.append(_diagnostic("an asserted code write has a path without a source language rule set", code="E0010", target=target))
            else:
                if any(Path(path).is_absolute() or root not in (root / path).resolve().parents for path in changes):
                    diagnostics.append(_diagnostic("pending source path leaves the selected repository", target=target))
                else:
                    try:
                        if compiler is None:
                            from tools.pipeline.strict_check import check_files
                            compiler = partial(check_files, build_options=build_options)
                        report = compiler(root, list(changes), overlay=dict(changes), timeout=float(config["compiler_timeout"]), context=context)
                    except Exception as error:
                        diagnostics.append(_diagnostic("compiler unavailable: %s" % error, code="E0010", target=target,
                                                       help_text="Restore the compiler, then retry this same pending write."))
        else:
            try:
                if kind == "model" and pending.get("format") == "archhub-graph-v1":
                    if not callable(graph_validator):
                        raise ValueError("a live graph schema/reference validator is required")
                    graph_validator(pending)
                if artifact_compiler is None:
                    from tools.pipeline.strict_check import check_artifact
                    artifact_compiler = partial(check_artifact, build_options=build_options)
                report = artifact_compiler(root, dict(pending), context=context, timeout=float(config["compiler_timeout"]))
            except Exception as error:
                diagnostics.append(_diagnostic("artifact compiler refused: %s" % error, code="E0010", target=target))
    if report is not None:
        diagnostics.extend(report["diagnostics"])
        if not report["ok"] and not diagnostics:
            diagnostics.append(_diagnostic("compiler refused without diagnostics", target=pending["target"]))
    return {"ok": not diagnostics, "diagnostics": diagnostics, "display": display_diagnostics(diagnostics),
            "pending": copy.deepcopy(pending), "context": context, "observation": report.get("observation") if report else None,
            "measured_context": report.get("context") if report else None, "history_root": str(root)}

def guarded_write(pending, writer, *, readback=None, params=None, correct=None, compiler=None, artifact_compiler=None, graph_validator=None, expected_kind=None, record_effect=True):
    """Bounded agent correction; the writer receives exactly the checked value once.

    ``correct`` only proposes new content. It never receives the write callback.
    This function is the shared agent/engine admission boundary, not an approval.
    """
    config = {**defaults(), **dict(params or {})}
    candidate = copy.deepcopy(pending)
    try:
        if not callable(readback):
            raise ValueError("an exact pending-value readback adapter is required before writing")
        attempts = int(config["max_attempts"])
        if attempts < 1:
            raise ValueError("max_attempts must be positive")
        for attempt in range(1, attempts + 1):
            if expected_kind is not None and (not isinstance(candidate, Mapping) or candidate.get("kind") != expected_kind):
                rows = [_diagnostic("correction changed the write adapter's declared artifact kind")]
                result = {"ok": False, "diagnostics": rows, "display": display_diagnostics(rows), "pending": candidate}
            else:
                result = inspect_pending(candidate, config, compiler=compiler, artifact_compiler=artifact_compiler, graph_validator=graph_validator)
            result["attempts"] = attempt
            if result["ok"]:
                expected = pending_digest(candidate)
                result["rule_context_sha256"] = pending_digest(result["context"])
                submitted = copy.deepcopy(candidate)
                receipt = writer(submitted)
                observed = readback(copy.deepcopy(candidate), receipt)
                actual = pending_digest(observed)
                result["content_sha256"] = expected
                result["readback_sha256"] = actual
                if pending_digest(submitted) != expected or actual != expected:
                    result.update(ok=False, diagnostics=[_diagnostic("write readback differs from the compiler-admitted content")])
                    result["display"] = display_diagnostics(result["diagnostics"])
                if isinstance(receipt, Mapping) and receipt.get("ok") is False:
                    result.update(ok=False, diagnostics=[_diagnostic("write refused: %s" % receipt.get("error", "no receipt"))])
                    result["display"] = display_diagnostics(result["diagnostics"])
                result["receipt"] = receipt
                if record_effect and result["ok"] and result.get("measured_context") is not None and candidate.get("kind") != "code":
                    from tools.pipeline.record_observation import record_action
                    record_action(result["history_root"], candidate, result)
                return result
            if not callable(correct) or attempt == attempts:
                return result
            candidate = correct(copy.deepcopy(candidate), copy.deepcopy(result))
        raise RuntimeError("Enforce exhausted its correction attempts without a result")
    except Exception as error:
        rows = [_diagnostic("Enforce refused: %s" % error)]
        return {"ok": False, "diagnostics": rows, "display": display_diagnostics(rows), "pending": candidate}

def engine(params, feeds):
    config = {**dict(params or {}), **{key: value for key, value in feeds.items() if key in defaults()}}
    pending = feeds.get("pending", params.get("pending"))
    if isinstance(pending, str):
        try:
            pending = json.loads(pending)
        except ValueError as error:
            return {"ok": False, "diagnostics": [_diagnostic(str(error))]}, "Enforce: invalid pending JSON"
    # The node and effect adapters use the same bounded admission loop. Its
    # local writer only returns the admitted value; approval remains separate.
    result = guarded_write(pending, lambda candidate: {"pending": copy.deepcopy(candidate)},
                           readback=lambda candidate, receipt: receipt["pending"], params=config, record_effect=False)
    return {**result, "out": result, "admitted": result["pending"] if result["ok"] else None}, result["display"] or "Enforce passed; approval is still required"

def graph_parameters(store):
    """Read the unique Enforce node's Settings parameters from the same graph."""
    if store is None:
        return defaults()
    from .domains.selfext import SHIPPED_MOD_ROWS, _decode_mod_state
    base = next(row for row in SHIPPED_MOD_ROWS if row["id"] == "enforce")
    state = _decode_mod_state(store.snapshot(), base)
    if not state["enabled"]:
        raise ValueError("Enforce is disabled; writes are refused until it is enabled")
    return {**defaults(), **dict(state["params"])}

def guard_effect(name, effect, params, feeds, *, config=None):
    """Admit explicit pending writes at the common pipeline effect boundary.

    A writer must expose ``pending`` as the exact value it consumes, declaring
    ``enforce_pending``; effects without it keep their own approval and grant checks.
    Existing grants remain in the original engine and are never synthesized here.
    """
    pending = feeds.get("pending", params.get("pending"))
    if not getattr(effect, "enforce_pending", False):
        # Reads, and writers that keep their own approval/grant checks, run unchanged;
        # an engine that declares an Enforce write adapter is inspected below.
        return effect(params, feeds)
    artifact_kind = getattr(effect, "enforce_kind", None)
    if artifact_kind not in {"code", "model", "document", "post"} or not isinstance(pending, Mapping) or pending.get("kind") != artifact_kind:
        rows = [_diagnostic("pending artifact type does not match the write adapter's declared kind")]
        result = {"ok": False, "diagnostics": rows, "display": display_diagnostics(rows)}
        return result, result["display"]
    try:
        if callable(config):
            config = config()
    except Exception as error:
        rows = [_diagnostic("Enforce Settings unavailable: %s" % error, code="E0010")]
        result = {"ok": False, "diagnostics": rows, "display": display_diagnostics(rows)}
        return result, result["display"]

    def write(candidate):
        outputs, shown = effect({**params, "pending": candidate}, {**feeds, "pending": candidate})
        return {**dict(outputs), "display": shown}

    readback_adapter = getattr(effect, "enforce_readback", None)
    correction_adapter = getattr(effect, "enforce_correct", None)
    result = guarded_write(pending, write, readback=readback_adapter, params=config, correct=correction_adapter, expected_kind=artifact_kind)
    if result["ok"]:
        receipt = {**result["receipt"], "enforcement": {
            "content_sha256": result["content_sha256"], "readback_sha256": result["readback_sha256"],
            "attempts": result["attempts"], "diagnostics": result["diagnostics"],
            "rule_context_sha256": result["rule_context_sha256"],
            "observation": result["observation"],
        }}
        return receipt, receipt["display"]
    return result, result["display"]
