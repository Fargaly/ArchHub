"""Grammar-health audit — QA tooling for the node grammar.

Sweeps the relationships between three sources of truth:
  • `node_grammar.PRIMITIVES` (the user-facing grammar)
  • `workflows.registry._REGISTRY` (the engine executor table)
  • `connectors.revit_speckle_ops._classify_item` (the annotation
    classifier for receive-side C# generation)

Catches the drift classes:
  1. A grammar primitive whose `engine_types` reference an UNREGISTERED
     engine type → user places the node, runner errors with
     `no executor for 'X'`.
  2. An adapter primitive whose annotation key isn't in
     `_classify_item`'s recognised set → silent skip during receive,
     no native creation, no error.
  3. A registered engine type with NO grammar primitive → orphan
     executor; only reachable from legacy saved graphs or programmatic
     invocation. Not a bug per se (host.*, doc.* engines are this way)
     but surfaces a warning so future devs check.
  4. A hidden primitive whose engine type is no longer registered →
     legacy saved graphs that reference it will error on cook.

The audit is a pure inspection function — never mutates state. Use
`audit_grammar_health()` from CI / tests / a `/audit grammar`
command (future).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class GrammarHealthReport:
    """Structured result. `ok` is True iff `critical_violations` is empty."""
    critical_violations: list[dict] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)
    summary: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.critical_violations


def audit_grammar_health() -> GrammarHealthReport:
    """Run the full audit. Returns a `GrammarHealthReport` with
    counts + per-issue dicts. Caller decides whether warnings block."""
    report = GrammarHealthReport()

    # Lazy imports — defer cost until called + survive a half-built
    # environment (e.g. tests that haven't imported every module).
    try:
        from workflows import node_grammar as ng
    except Exception as ex:
        report.critical_violations.append({
            "kind": "import_error",
            "where": "workflows.node_grammar",
            "error": f"{type(ex).__name__}: {ex}",
        })
        return report

    try:
        from workflows.registry import _REGISTRY
    except Exception as ex:
        report.critical_violations.append({
            "kind": "import_error",
            "where": "workflows.registry",
            "error": f"{type(ex).__name__}: {ex}",
        })
        return report

    # Force import of all node modules so the registry is populated.
    try:
        import workflows.nodes  # noqa: F401
    except Exception as ex:
        report.warnings.append({
            "kind": "node_modules_partial",
            "where": "workflows.nodes",
            "error": f"{type(ex).__name__}: {ex}",
        })

    primitives = list(ng.PRIMITIVES)
    registered_types: set[str] = set(_REGISTRY.keys())

    # ─── Check 1: every primitive's engine types are registered ─────
    referenced_types: set[str] = set()
    for p in primitives:
        for value_key, engine_type in p.engine_types.items():
            if not engine_type:
                continue
            referenced_types.add(engine_type)
            if engine_type not in registered_types:
                # Some primitives are NON_REGISTRY_KINDS (cf. node_grammar).
                if p.kind in getattr(ng, "NON_REGISTRY_KINDS", set()):
                    continue
                report.critical_violations.append({
                    "kind": "missing_executor",
                    "primitive": p.kind,
                    "selector_value": value_key,
                    "engine_type": engine_type,
                    "primitive_status": p.status,
                    "hidden": p.hidden,
                    "note": (
                        "primitive resolves to an UNREGISTERED engine "
                        "type; placing this node will error at cook"),
                })

    # ─── Check 2: adapter annotations map cleanly into the classifier ─
    try:
        from connectors.revit_speckle_ops import _classify_item
        # Sentinel inputs — exercise each adapter's annotation
        # template and assert the classifier returns a NON-SKIP kind.
        adapter_kinds = [p for p in primitives if p.cat == "adapter"]
        for ap in adapter_kinds:
            # Resolve a representative engine type for the adapter.
            rep = next(iter(ap.engine_types.values()), "")
            if not rep:
                continue
            sentinels = _adapter_annotation_sentinel(ap.kind)
            if sentinels is None:
                # Adapter kind we don't have a sentinel for yet —
                # warn + move on rather than blocking.
                report.warnings.append({
                    "kind": "no_classifier_sentinel",
                    "primitive": ap.kind,
                    "note": ("no annotation sentinel in audit "
                             "table — add one to test the receive "
                             "classifier covers this adapter"),
                })
                continue
            verdict = _classify_item(sentinels)
            if verdict == "skip":
                report.critical_violations.append({
                    "kind": "adapter_classifier_drift",
                    "primitive": ap.kind,
                    "engine_type": rep,
                    "verdict": verdict,
                    "note": (
                        "adapter writes annotations the receive-side "
                        "classifier doesn't recognise — receive will "
                        "silently skip these items"),
                })
    except Exception as ex:
        report.warnings.append({
            "kind": "classifier_import_failed",
            "error": f"{type(ex).__name__}: {ex}",
        })

    # ─── Check 3: every visible primitive has a blurb + display ──────
    for p in primitives:
        if p.hidden:
            continue
        if not p.blurb:
            report.critical_violations.append({
                "kind": "missing_blurb",
                "primitive": p.kind,
                "note": "user-facing primitive has no palette subtitle",
            })
        if not p.display:
            report.critical_violations.append({
                "kind": "missing_display",
                "primitive": p.kind,
                "note": "primitive has no display name",
            })

    # ─── Check 4: no kind appears twice ──────────────────────────────
    seen_kinds: dict[str, int] = {}
    for p in primitives:
        seen_kinds[p.kind] = seen_kinds.get(p.kind, 0) + 1
    for kind, count in seen_kinds.items():
        if count > 1:
            report.critical_violations.append({
                "kind": "duplicate_kind",
                "primitive": kind,
                "count": count,
                "note": ("primitive kind appears multiple times — "
                         "ambiguous engine resolution"),
            })

    # ─── Summary counts ──────────────────────────────────────────────
    report.summary = {
        "primitive_count":      len(primitives),
        "visible_count":        sum(1 for p in primitives if not p.hidden),
        "hidden_count":         sum(1 for p in primitives if p.hidden),
        "registered_types":     len(registered_types),
        "referenced_types":     len(referenced_types),
        "orphan_types":         sorted(registered_types - referenced_types),
        "critical_count":       len(report.critical_violations),
        "warning_count":        len(report.warnings),
    }
    return report


def _adapter_annotation_sentinel(adapter_kind: str) -> dict | None:
    """A representative annotated item for each known adapter kind.
    Used by Check 2 to exercise the receive-side classifier. Returning
    None means "no sentinel coded yet" — the audit warns the dev to
    add one when introducing a new adapter."""
    sentinels: dict[str, dict] = {
        "cad_to_revit_wall": {
            "revit_target_category": "Walls",
            "revit_polyline": [[0, 0, 0], [1, 0, 0]],
            "revit_level": "L1",
            "revit_wall_type": "WT",
            "revit_height_mm": 1000,
        },
        "to_revit_directshape": {
            "revit_directshape_category": "OST_GenericModel",
        },
        "max_to_revit_family": {
            "revit_family_name": "M",
            "revit_target_category": "Mass",
        },
        "cad_to_revit_detail_line": {
            "revit_target_category": "DetailLines",
            "revit_polyline": [[0, 0, 0], [1, 0, 0]],
        },
        "rhino_to_revit_beam": {
            "revit_target_category": "StructuralFraming",
            "revit_beam_family": "WideFlange",
            "revit_polyline": [[0, 0, 0], [1, 0, 0]],
        },
        "excel_to_revit_params": {
            "revit_element_id": 42,
            "revit_parameters": {"X": 1},
        },
    }
    return sentinels.get(adapter_kind)


def format_health_report(report: GrammarHealthReport) -> str:
    """Human-readable summary for a `/audit grammar` command or
    CI failure message."""
    lines: list[str] = []
    s = report.summary
    lines.append(
        f"Grammar health: {s.get('visible_count', 0)} visible + "
        f"{s.get('hidden_count', 0)} hidden = "
        f"{s.get('primitive_count', 0)} primitives; "
        f"{s.get('registered_types', 0)} engine types registered "
        f"({s.get('referenced_types', 0)} referenced by grammar)")
    if report.critical_violations:
        lines.append("")
        lines.append(f"CRITICAL ({len(report.critical_violations)}):")
        for v in report.critical_violations:
            lines.append(
                f"  ✗ [{v.get('kind')}] "
                f"{v.get('primitive') or v.get('where', '?')}: "
                f"{v.get('note') or v.get('error', '')}")
    if report.warnings:
        lines.append("")
        lines.append(f"WARNINGS ({len(report.warnings)}):")
        for w in report.warnings:
            lines.append(
                f"  ! [{w.get('kind')}] "
                f"{w.get('primitive') or w.get('where', '?')}: "
                f"{w.get('note') or w.get('error', '')}")
    if report.ok and not report.warnings:
        lines.append("")
        lines.append("All checks passed.")
    return "\n".join(lines)


__all__ = [
    "audit_grammar_health",
    "format_health_report",
    "GrammarHealthReport",
]
