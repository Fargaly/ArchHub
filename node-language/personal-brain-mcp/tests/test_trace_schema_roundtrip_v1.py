"""AgDR-0054 slice 1b — per-trace fields round-trip through the REAL write path.

The acceptance gate the column-existence tests (test_trace_schema_v1.py) and the
raw-SQL export tests (test_export_tiers_v1.py) do NOT cover: the 9 AgDR-0054
columns must survive a write through the application surface —
``Fragment`` model → ``BrainStore.write_fragment`` → row → ``get_fragment`` →
``Fragment`` — not just a hand-rolled ``INSERT INTO fragments(...)``.

Before this fix the columns existed in the schema but ``write_fragment`` only
INSERTed through ``blob_bytes``, so every fragment written by the running brain
fell back to the SQL defaults (``firm_private_only`` / not-quarantined) no matter
what the caller intended — the training/export dam was dead because nothing could
ever populate a non-default tier except raw SQL. ``Fragment`` itself carried zero
of the fields (models.py: 0 hits), so a caller could not even express the intent.

These tests fail RED on origin/main:
  - ``Fragment`` has no AgDR-0054 fields → constructing one with them raises.
  - even via construct-bypass, ``write_fragment`` never writes the columns, so the
    round-trip reads back the SQL default, not the written value.
"""
from __future__ import annotations

from datetime import datetime, timezone

from personal_brain.models import (
    Confidence,
    Fragment,
    FragmentKind,
    Provenance,
    Scope,
    Visibility,
)
from personal_brain.storage import BrainStore


def _prov() -> Provenance:
    return Provenance(
        contributing_agent="claude-opus-4.8",
        contributing_user="Fargaly",
        created_at=datetime.now(timezone.utc),
    )


def _trace_fragment(fid: str, **overrides) -> Fragment:
    """A trace Fragment carrying the AgDR-0054 per-trace fields.

    Kwargs default to NON-default values (different from the SQL column
    defaults) so a round-trip that reads back the default is provably a
    drop, not a coincidence.
    """
    kw = dict(
        id=fid,
        kind=FragmentKind.TRACE,
        text="built a curtain wall on level 3",
        owner_user="Fargaly",
        scope=Scope.USER,
        visibility=Visibility.PRIVATE,
        confidence=Confidence.EXTRACTED,
        provenance=_prov(),
        # ── AgDR-0054 per-trace fields (the 9 the dam needs) ──
        origin_kind="model_generated",                # default is 'human_verified'
        generating_model_id="claude-opus-4.8",
        training_rights_tier="collective_ok",         # default is 'firm_private_only'
        format_shape_descriptor="prompt->revit.create_wall->result",
        content_hash_pre="sha256:" + "a" * 8,
        content_hash_post="sha256:" + "b" * 8,
        action_payload='{"op":"revit.create_wall","level":3}',
        language_payload='{"note":"architect asked for a CW run"}',
        quarantine_flag=False,                         # default is 0
    )
    kw.update(overrides)
    return Fragment(**kw)


def test_trace_schema_roundtrip_collective_tier(tmp_path):
    """The headline gate from the brain: a Fragment written
    ``training_rights_tier='collective_ok'`` reads back that value."""
    s = BrainStore.open(tmp_path / "rt.db")
    try:
        s.write_fragment(_trace_fragment("rt-collective"))
        got = s.get_fragment("rt-collective")
        assert got is not None, "fragment did not persist"
        assert got.training_rights_tier == "collective_ok", (
            "training_rights_tier was dropped on the write path — read back "
            f"{got.training_rights_tier!r} (the SQL default), not the written value"
        )
    finally:
        s.close()


def test_trace_schema_roundtrip_all_nine_fields(tmp_path):
    """Every one of the 9 AgDR-0054 fields survives Fragment→write→read."""
    s = BrainStore.open(tmp_path / "rt9.db")
    try:
        s.write_fragment(_trace_fragment("rt-all"))
        got = s.get_fragment("rt-all")
        assert got is not None
        assert got.origin_kind == "model_generated"
        assert got.generating_model_id == "claude-opus-4.8"
        assert got.training_rights_tier == "collective_ok"
        assert got.format_shape_descriptor == "prompt->revit.create_wall->result"
        assert got.content_hash_pre == "sha256:" + "a" * 8
        assert got.content_hash_post == "sha256:" + "b" * 8
        assert got.action_payload == '{"op":"revit.create_wall","level":3}'
        assert got.language_payload == '{"note":"architect asked for a CW run"}'
        assert got.quarantine_flag is True or got.quarantine_flag == 0  # written False → stored 0
        # written quarantine_flag=False must read back falsy, not the truthy we didn't set
        assert not got.quarantine_flag
    finally:
        s.close()


def test_trace_schema_roundtrip_reaches_export_dam(tmp_path):
    """End-to-end: a Fragment written via the model with
    ``training_rights_tier='collective_ok'`` is selected by the export dam —
    proving the write path actually populates the columns the dam reads.

    A quarantined fragment written the same way must NOT export.
    """
    s = BrainStore.open(tmp_path / "rtdam.db")
    try:
        s.write_fragment(_trace_fragment("dam-ok", training_rights_tier="collective_ok"))
        s.write_fragment(
            _trace_fragment(
                "dam-quar", training_rights_tier="collective_ok", quarantine_flag=True
            )
        )
        s.write_fragment(
            _trace_fragment("dam-priv", training_rights_tier="firm_private_only")
        )
        exported = {r["id"] for r in s.export_trainable_fragments(target="collective")}
        assert exported == {"dam-ok"}, (
            "export dam did not see the model-written tier — got "
            f"{exported!r}; the write path is not populating the AgDR-0054 columns"
        )
        # action_payload (Tier-0) rode through too.
        row = next(
            r for r in s.export_trainable_fragments(target="collective") if r["id"] == "dam-ok"
        )
        assert row["action_payload"] == '{"op":"revit.create_wall","level":3}'
    finally:
        s.close()
