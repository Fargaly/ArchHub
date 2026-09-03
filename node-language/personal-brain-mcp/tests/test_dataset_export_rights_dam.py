"""BRV-04 — the export-time legal/training-rights dam must actually gate the
exporter the founder named.

Root cause this pins: ``BrainStore.export_trainable_fragments`` (the dam) lived
in storage.py, but ``dataset_export.export_fragments`` never called it — so a
``quarantine_flag=1`` (right-to-be-forgotten / poisoned) row, or a
``firm_private_only`` row, landed VERBATIM in a collective training export. The
dam was dead-wired. These tests fail on origin/main (the rows leak into
``fragments.jsonl``) and pass once the exporter consults the dam.

Export-gating is the only reliable unlearning (weights-level erasure is
impossible), so the gate MUST run here, at the export — not at recall.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from personal_brain.dataset_export import export_fragments
from personal_brain.storage import BrainStore as Store


def _ins(store, **kw):
    """Insert a fragment row carrying the AgDR-0054 legal columns directly.

    ``write_fragment`` doesn't persist the rights columns (they default at the
    schema level), so — exactly like ``test_export_tiers_v1.py`` — a row that
    exercises quarantine / tier must be inserted via raw SQL. Scope defaults to
    'user' so the default USER-scope export picks it up.
    """
    # Valid provenance: the exporter rehydrates rows through `_row_to_fragment`
    # (unlike the dam, which reads raw SQL), so Provenance must validate.
    prov_json = json.dumps(
        {"contributing_agent": "test", "contributing_user": "founder"}
    )
    cols = {
        "id": kw["id"],
        "kind": kw.get("kind", "trace"),
        "text": kw.get("text", "t"),
        "scope": kw.get("scope", "user"),
        "owner_user": "founder",
        "provenance_json": prov_json,
        "origin_kind": kw.get("origin_kind", "human_verified"),
        "training_rights_tier": kw.get("tier", "collective_ok"),
        "action_payload": kw.get("action", '{"op":"build_wall"}'),
        "language_payload": kw.get("lang"),
        "quarantine_flag": kw.get("quar", 0),
    }
    with store._lock:
        store._conn.execute(
            """INSERT INTO fragments(id,kind,text,scope,owner_user,provenance_json,
                origin_kind,training_rights_tier,action_payload,language_payload,
                quarantine_flag)
               VALUES(:id,:kind,:text,:scope,:owner_user,:provenance_json,
                :origin_kind,:training_rights_tier,:action_payload,:language_payload,
                :quarantine_flag)""",
            cols,
        )
        store._conn.commit()


def _exported_ids(manifest) -> set[str]:
    jsonl = Path(manifest["files"]["jsonl"]["path"])
    if not jsonl.exists():
        return set()
    text = jsonl.read_text(encoding="utf-8").strip()
    if not text:
        return set()
    return {json.loads(line)["id"] for line in text.split("\n")}


@pytest.fixture
def store(tmp_path) -> Store:
    return Store.open(tmp_path / "rights.db")


# ── the BRV-04 leak proof (identical call surface on main vs branch) ──────────

def test_dam_is_wired_quarantine_does_not_leak_with_default_call(store, tmp_path):
    """THE BRV-04 pin. Uses ONLY the call surface that exists on origin/main
    (no new kwargs) so the RED is a genuine *leak* — not an argument error.

    origin/main: ``export_fragments`` walks ``list_fragments`` with zero rights
    filtering, so the ``quarantine_flag=1`` row is written to fragments.jsonl
    and this assertion FAILS (the right-to-be-forgotten / poisoned fragment
    leaked into the training export).

    branch: the default gate (``respect_training_rights=True``) consults the dam
    and the quarantined row is absent → assertion passes.
    """
    _ins(store, id="keep", tier="firm_private_only", quar=0)
    _ins(store, id="quarantined", tier="firm_private_only", quar=1)

    manifest = export_fragments(
        store, out_dir=tmp_path / "exp", dataset_name="ds-brv04",
    )
    ids = _exported_ids(manifest)
    assert "quarantined" not in ids, (
        "BRV-04 REGRESSION: the export-time legal/rights dam is dead-wired — a "
        f"quarantined fragment leaked into the training export: {sorted(ids)}"
    )


# ── quarantine ───────────────────────────────────────────────────────────────

def test_quarantine_row_absent_from_collective_export(store, tmp_path):
    """A quarantine_flag=1 fragment must NEVER appear in a training export.

    RED on origin/main: the exporter walked list_fragments() with no rights
    filter, so the quarantined row was written to fragments.jsonl.
    """
    _ins(store, id="ok", tier="collective_ok", quar=0)
    _ins(store, id="quarantined", tier="collective_ok", quar=1)

    manifest = export_fragments(
        store, out_dir=tmp_path / "exp", dataset_name="ds",
        training_target="collective",
    )
    ids = _exported_ids(manifest)
    assert "quarantined" not in ids, (
        "quarantined (right-to-be-forgotten / poisoned) fragment leaked into the "
        f"training export: {ids}"
    )
    assert ids == {"ok"}, ids
    assert manifest["row_count"] == 1


def test_quarantine_row_absent_even_from_default_export(store, tmp_path):
    """The quarantine floor holds under the DEFAULT export call too — no caller
    opt-in required to keep right-to-be-forgotten data out."""
    _ins(store, id="keep", tier="firm_private_only", quar=0)
    _ins(store, id="forgotten", tier="firm_private_only", quar=1)

    manifest = export_fragments(
        store, out_dir=tmp_path / "exp", dataset_name="ds-default",
    )  # all defaults — respect_training_rights=True
    ids = _exported_ids(manifest)
    assert "forgotten" not in ids, ids
    assert ids == {"keep"}, ids
    assert manifest["training_rights"]["enforced"] is True
    assert manifest["training_rights"]["excluded_count"] == 1


# ── tier ─────────────────────────────────────────────────────────────────────

def test_firm_private_only_row_absent_from_collective_export(store, tmp_path):
    """A firm_private_only fragment must NOT reach the cross-firm collective pool.

    RED on origin/main: tier was never consulted, so the firm-private row was
    exported to the collective dataset.
    """
    _ins(store, id="shareable", tier="collective_ok")
    _ins(store, id="firm_secret", tier="firm_private_only")

    manifest = export_fragments(
        store, out_dir=tmp_path / "exp", dataset_name="ds-collective",
        training_target="collective",
    )
    ids = _exported_ids(manifest)
    assert "firm_secret" not in ids, (
        f"firm_private_only fragment leaked into the collective export: {ids}"
    )
    assert ids == {"shareable"}, ids
    assert manifest["training_rights"]["target"] == "collective"
    assert manifest["training_rights"]["excluded_count"] == 1


def test_firm_private_target_keeps_firm_rows_but_drops_quarantine(store, tmp_path):
    """firm_private target (the default legal floor) clears collective_ok +
    firm_private_only and still drops quarantined rows."""
    _ins(store, id="collective", tier="collective_ok")
    _ins(store, id="firm", tier="firm_private_only")
    _ins(store, id="never", tier="quarantine_never_trains")
    _ins(store, id="poisoned", tier="collective_ok", quar=1)

    manifest = export_fragments(
        store, out_dir=tmp_path / "exp", dataset_name="ds-firm",
        training_target="firm_private",
    )
    ids = _exported_ids(manifest)
    assert ids == {"collective", "firm"}, ids
    assert manifest["training_rights"]["excluded_count"] == 2  # never + poisoned


# ── escape hatch + guards ────────────────────────────────────────────────────

def test_disabling_gate_is_recorded_and_exports_everything(store, tmp_path):
    """respect_training_rights=False is the explicit operational-dump escape
    hatch — it exports everything BUT the manifest records the gate did NOT run,
    so the choice can never be silent."""
    _ins(store, id="ok", tier="collective_ok")
    _ins(store, id="quarantined", tier="collective_ok", quar=1)

    manifest = export_fragments(
        store, out_dir=tmp_path / "exp", dataset_name="ds-raw",
        respect_training_rights=False,
    )
    ids = _exported_ids(manifest)
    assert ids == {"ok", "quarantined"}, ids
    assert manifest["training_rights"]["enforced"] is False
    assert manifest["training_rights"]["target"] is None


def test_unknown_training_target_raises(store, tmp_path):
    """A typo in the target must raise, never silently widen the export."""
    _ins(store, id="ok", tier="collective_ok")
    with pytest.raises(ValueError):
        export_fragments(
            store, out_dir=tmp_path / "exp", dataset_name="ds-bad",
            training_target="public",  # not a real target
        )
