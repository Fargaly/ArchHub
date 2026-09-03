"""Grammar-health audit tests.

The audit is REGRESSION INFRASTRUCTURE: future drift between the
grammar primitives, registered engine types, and receive-side
classifier must surface immediately. These tests pin the contract
of the audit util + assert today's grammar is healthy.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

# Force engines + connector classifier to register.
import workflows.nodes  # noqa: F401, E402
import connectors.revit_connector  # noqa: F401, E402

from grammar_health import (  # noqa: E402
    audit_grammar_health,
    format_health_report,
    GrammarHealthReport,
)


# ─── 1. report shape ─────────────────────────────────────────────────


def test_audit_returns_grammar_health_report():
    report = audit_grammar_health()
    assert isinstance(report, GrammarHealthReport)
    assert isinstance(report.critical_violations, list)
    assert isinstance(report.warnings, list)
    assert isinstance(report.summary, dict)
    # Summary fields the format_health_report renderer expects.
    for key in ("primitive_count", "visible_count", "hidden_count",
                "registered_types", "referenced_types",
                "critical_count", "warning_count"):
        assert key in report.summary


def test_audit_ok_property_reflects_critical_violations():
    """ok = no critical violations. Warnings don't fail."""
    r = GrammarHealthReport()
    assert r.ok is True
    r.warnings.append({"kind": "x"})
    assert r.ok is True
    r.critical_violations.append({"kind": "y"})
    assert r.ok is False


# ─── 2. current grammar is healthy ───────────────────────────────────


def test_grammar_has_no_critical_violations_today():
    """Pinned regression: TODAY's grammar passes every critical check.
    Any future drift (missing executor, adapter→classifier gap,
    duplicate kind, missing blurb/display) breaks this test."""
    report = audit_grammar_health()
    assert report.ok, (
        "Grammar health audit failed:\n" +
        format_health_report(report))


def test_every_visible_primitive_has_blurb_and_display():
    report = audit_grammar_health()
    blurb_misses = [v for v in report.critical_violations
                     if v["kind"] == "missing_blurb"]
    display_misses = [v for v in report.critical_violations
                       if v["kind"] == "missing_display"]
    assert not blurb_misses, blurb_misses
    assert not display_misses, display_misses


def test_no_duplicate_kinds():
    report = audit_grammar_health()
    dups = [v for v in report.critical_violations
             if v["kind"] == "duplicate_kind"]
    assert not dups, dups


# ─── 3. executor coverage ────────────────────────────────────────────


def test_every_engine_type_referenced_by_grammar_is_registered():
    """A primitive that resolves to engine type 'X' must have 'X'
    in the registry — otherwise placing the node errors at cook."""
    report = audit_grammar_health()
    misses = [v for v in report.critical_violations
              if v["kind"] == "missing_executor"]
    assert not misses, (
        "Primitives resolving to unregistered engines:\n" +
        "\n".join(f"  {v['primitive']} → {v['engine_type']}"
                  for v in misses))


# ─── 4. adapter classifier symmetry ──────────────────────────────────


def test_every_adapter_writes_classifier_recognisable_annotations():
    """Each adapter primitive's typical output annotation must be
    classifiable by `revit_speckle_ops._classify_item` as something
    OTHER than 'skip' — otherwise the receive-side silently drops
    the item."""
    report = audit_grammar_health()
    drift = [v for v in report.critical_violations
              if v["kind"] == "adapter_classifier_drift"]
    assert not drift, (
        "Adapter→classifier drift:\n" +
        "\n".join(f"  {v['primitive']}: verdict={v['verdict']}"
                  for v in drift))


def test_every_adapter_has_a_sentinel_for_audit():
    """Every adapter primitive must have a sentinel input in
    `_adapter_annotation_sentinel` — otherwise the audit can't
    verify the adapter ↔ classifier contract."""
    report = audit_grammar_health()
    missing = [w for w in report.warnings
                if w["kind"] == "no_classifier_sentinel"]
    assert not missing, (
        "Adapters without audit sentinels:\n" +
        "\n".join(f"  {w['primitive']}" for w in missing))


# ─── 5. report rendering ─────────────────────────────────────────────


def test_format_health_report_is_human_readable():
    report = audit_grammar_health()
    text = format_health_report(report)
    assert isinstance(text, str)
    assert "Grammar health:" in text
    # Healthy grammar → "All checks passed." at the tail.
    if report.ok and not report.warnings:
        assert "All checks passed." in text


def test_format_health_report_lists_critical_when_present():
    """Synthetic report with a violation → renders the CRITICAL
    section + the violation note."""
    r = GrammarHealthReport()
    r.summary = {"primitive_count": 5, "visible_count": 4,
                  "hidden_count": 1, "registered_types": 10,
                  "referenced_types": 5, "critical_count": 1,
                  "warning_count": 0}
    r.critical_violations.append({
        "kind": "missing_executor",
        "primitive": "demo_kind",
        "engine_type": "demo.engine",
        "note": "demo engine is not registered",
    })
    text = format_health_report(r)
    assert "CRITICAL (1)" in text
    assert "demo_kind" in text
    assert "demo engine is not registered" in text


def test_format_health_report_lists_warnings_when_present():
    r = GrammarHealthReport()
    r.summary = {"primitive_count": 1, "visible_count": 1,
                  "hidden_count": 0, "registered_types": 1,
                  "referenced_types": 1, "critical_count": 0,
                  "warning_count": 1}
    r.warnings.append({"kind": "no_classifier_sentinel",
                        "primitive": "demo",
                        "note": "add a sentinel"})
    text = format_health_report(r)
    assert "WARNINGS (1)" in text
    assert "demo" in text


# ─── 6. catches synthetic regressions ─────────────────────────────────


def test_audit_catches_synthetic_missing_executor(monkeypatch):
    """Inject a fake primitive whose engine_types points at an
    unregistered type. Audit must flag it."""
    from workflows import node_grammar as ng
    from dataclasses import replace

    bad = ng.Primitive(
        kind="synthetic_test_kind",
        display="Synthetic",
        cat="test",
        selector="",
        engine_types={"": "nonexistent.engine.xyz"},
        status=ng.READY,
        note="audit-test fixture",
        params=(),
        blurb="Synthetic audit test",
    )
    monkeypatch.setattr(ng, "PRIMITIVES",
                         list(ng.PRIMITIVES) + [bad])
    report = audit_grammar_health()
    flagged = [v for v in report.critical_violations
                if v["kind"] == "missing_executor"
                and v["primitive"] == "synthetic_test_kind"]
    assert flagged, (
        "audit should flag synthetic primitive with no executor")


def test_audit_catches_synthetic_duplicate_kind(monkeypatch):
    from workflows import node_grammar as ng

    # Duplicate of an existing kind.
    by_kind = {p.kind: p for p in ng.PRIMITIVES}
    if not by_kind:
        pytest.skip("no primitives to duplicate")
    target = next(iter(by_kind.values()))
    dup = ng.Primitive(
        kind=target.kind,
        display=target.display,
        cat=target.cat,
        selector=target.selector,
        engine_types=dict(target.engine_types),
        status=target.status,
        note=target.note,
        params=target.params,
        blurb=target.blurb,
    )
    monkeypatch.setattr(ng, "PRIMITIVES",
                         list(ng.PRIMITIVES) + [dup])
    report = audit_grammar_health()
    flagged = [v for v in report.critical_violations
                if v["kind"] == "duplicate_kind"
                and v["primitive"] == target.kind]
    assert flagged


def test_no_visible_primitive_carries_dropdown_selector():
    """Founder mandate (2026-05-21): no dropdown selectors on the
    canvas surface. Every visible primitive must be typed-per-action
    (Slice-I pattern) — selector masters belong in `hidden=True` for
    saved-graph back-compat only. Pinned regression guard."""
    from workflows import node_grammar as ng
    violators = [
        {"kind": p.kind, "selector": p.selector,
         "engine_values": list(p.engine_types.keys())}
        for p in ng.PRIMITIVES
        if not p.hidden and p.selector
    ]
    assert not violators, (
        "Visible primitives still expose selector dropdowns "
        "(founder gripe 2026-05-21 — must be typed-per-action):\n" +
        "\n".join(f"  {v['kind']} selector={v['selector']!r} "
                  f"values={v['engine_values']}" for v in violators))


def test_no_visible_primitive_param_renders_as_dropdown():
    """A primitive's params must not declare `type` ∈ {choice, enum,
    select} OR carry an `options` list — both render as <select>
    in the inspector. Allowed in connector-op params (host-specific)
    but NOT in the grammar primitives' default param rows."""
    from workflows import node_grammar as ng
    violators: list[dict] = []
    for p in ng.PRIMITIVES:
        if p.hidden:
            continue
        for pp in p.params:
            if not isinstance(pp, dict):
                continue
            if pp.get("type") in ("choice", "enum", "select"):
                violators.append({
                    "kind": p.kind, "param": pp.get("k"),
                    "type": pp.get("type"),
                })
            if pp.get("options"):
                violators.append({
                    "kind": p.kind, "param": pp.get("k"),
                    "options": pp.get("options"),
                })
    assert not violators, (
        "Visible primitive params render as dropdowns "
        "(founder gripe — typed primitives should never emit "
        "a <select>):\n" +
        "\n".join(f"  {v['kind']}/{v['param']}" for v in violators))


def test_audit_catches_synthetic_missing_blurb(monkeypatch):
    from workflows import node_grammar as ng

    bad = ng.Primitive(
        kind="synthetic_no_blurb",
        display="NoBlurb",
        cat="test",
        selector="",
        engine_types={"": "data.constant"},
        status=ng.READY,
        note="audit-test fixture",
        params=(),
        blurb="",  # missing
    )
    monkeypatch.setattr(ng, "PRIMITIVES",
                         list(ng.PRIMITIVES) + [bad])
    report = audit_grammar_health()
    flagged = [v for v in report.critical_violations
                if v["kind"] == "missing_blurb"
                and v["primitive"] == "synthetic_no_blurb"]
    assert flagged
