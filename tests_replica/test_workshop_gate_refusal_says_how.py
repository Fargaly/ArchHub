"""Rule 16: a refused effect says which part of the plan is missing and how to add it.

The execution gate (universal_application._require_workshop_execution_gate)
already refuses every agent effect of claimed Work until the Workshop holds a
plan and a research entry backed by a captured source. The refusal used to
say only that; an agent could not tell which part was missing or how to add
it. Each state below names the part and the exact entry that fixes it.
"""
from __future__ import annotations

from nodelang.universal_application import workshop_execution_gate_refusal

WORK = "app:work:court-rule-16"


def test_nothing_planned_names_the_plan_and_the_prior_art():
    said = workshop_execution_gate_refusal(WORK, plan=True, research=True, research_source=False)
    assert "missing: plan, prior-art research" in said
    assert '"category": "plan"' in said and '"category": "research"' in said
    assert "add a prior-art entry to the Work plan" in said
    assert '"refs": ["%s"]' % WORK in said
    assert "plan and source-backed research" in said, "older callers match this phrase"


def test_a_plan_without_prior_art_names_only_the_prior_art():
    said = workshop_execution_gate_refusal(WORK, plan=False, research=True, research_source=False)
    assert "missing: prior-art research" in said and '"category": "plan"' not in said
    assert '"capture": {"path": "<workspace file you read>"}' in said


def test_prior_art_without_a_source_names_the_capture():
    said = workshop_execution_gate_refusal(WORK, plan=False, research=False, research_source=True)
    assert "missing: research source" in said
    assert "cites no captured source" in said and "read-* connector" in said
    assert '"category": "plan"' not in said and "add a prior-art entry" not in said
