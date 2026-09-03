"""Brain privacy layer — tests.

Pins the runtime built from
``docs/research/privacy-respecting-knowledge-sharing-2026-05-26.md``:

  - scope ladder ordering (USER < PROJECT < FIRM < COMMUNITY < GLOBAL)
  - may_cross gate: same/narrower OK; widening into the collective pool
    needs dp_applied=True (raw fragments NEVER reach collective)
  - laplace_noise is zero-mean over many samples
  - dp_count is non-negative and ≈ true_count over many samples
  - dp_aggregate releases noised sum/mean/count
  - privatize_for_collective emits ONLY aggregates — the core privacy
    guarantee: no raw subject/object/predicate/text string leaks
"""
from __future__ import annotations

import json
import random
import statistics

import pytest

from personal_brain import privacy
from personal_brain.models import Fragment, FragmentKind, Provenance, Scope


# ───────────────────────── fixtures / helpers ───────────────────────────


def _make_fragment(
    fid: str = "f_test",
    kind: FragmentKind = FragmentKind.FACT,
    scope: Scope = Scope.USER,
    *,
    text: str = "hello world",
    subject: str | None = None,
    predicate: str | None = None,
    obj: str | None = None,
    owner_user: str = "founder",
    project_id: str | None = None,
    firm_id: str | None = None,
    success_count: int = 0,
    fail_count: int = 0,
) -> Fragment:
    return Fragment(
        id=fid,
        kind=kind,
        scope=scope,
        text=text,
        subject=subject,
        predicate=predicate,
        object=obj,
        owner_user=owner_user,
        project_id=project_id,
        firm_id=firm_id,
        success_count=success_count,
        fail_count=fail_count,
        provenance=Provenance(
            contributing_agent="test",
            contributing_user=owner_user,
        ),
    )


# ───────────────────────── scope ladder ─────────────────────────────────


def test_scope_rank_ordering():
    assert (
        privacy.scope_rank(Scope.USER)
        < privacy.scope_rank(Scope.PROJECT)
        < privacy.scope_rank(Scope.FIRM)
        < privacy.scope_rank(Scope.COMMUNITY)
        < privacy.scope_rank(Scope.GLOBAL)
    )


def test_scope_rank_accepts_strings_and_collective_alias():
    assert privacy.scope_rank("user") == 0
    assert privacy.scope_rank("firm") == 2
    # "collective" is the spec alias for the COMMUNITY pool.
    assert privacy.scope_rank("collective") == privacy.scope_rank(Scope.COMMUNITY)


def test_scope_rank_rejects_unknown():
    with pytest.raises(ValueError):
        privacy.scope_rank("nonsense-scope")


def test_collective_alias_is_community():
    assert privacy.COLLECTIVE == Scope.COMMUNITY
    assert privacy.is_collective_scope(Scope.COMMUNITY)
    assert privacy.is_collective_scope(Scope.GLOBAL)
    assert privacy.is_collective_scope("collective")
    assert not privacy.is_collective_scope(Scope.FIRM)
    assert not privacy.is_collective_scope(Scope.USER)


# ───────────────────────── the crossing gate ────────────────────────────


def test_may_cross_same_scope_ok():
    assert privacy.may_cross(Scope.FIRM, Scope.FIRM, dp_applied=False)


def test_may_cross_narrower_always_ok():
    # FIRM fact visible to PROJECT / USER callers (narrowing).
    assert privacy.may_cross(Scope.FIRM, Scope.PROJECT, dp_applied=False)
    assert privacy.may_cross(Scope.FIRM, Scope.USER, dp_applied=False)
    assert privacy.may_cross(Scope.COMMUNITY, Scope.FIRM, dp_applied=False)


def test_may_cross_widen_within_org_ladder_ok():
    # Org-internal escalation (not into a collective pool) is legal.
    assert privacy.may_cross(Scope.PROJECT, Scope.FIRM, dp_applied=False)
    assert privacy.may_cross(Scope.USER, Scope.PROJECT, dp_applied=False)


def test_may_cross_into_collective_blocked_without_dp():
    # THE core guarantee — a raw fragment may never reach the collective pool.
    assert privacy.may_cross(Scope.FIRM, Scope.COMMUNITY, dp_applied=False) is False
    assert privacy.may_cross(Scope.USER, Scope.COMMUNITY, dp_applied=False) is False
    assert privacy.may_cross(Scope.FIRM, "collective", dp_applied=False) is False
    # GLOBAL is collective-class too.
    assert privacy.may_cross(Scope.FIRM, Scope.GLOBAL, dp_applied=False) is False


def test_may_cross_into_collective_allowed_with_dp():
    assert privacy.may_cross(Scope.FIRM, Scope.COMMUNITY, dp_applied=True) is True
    assert privacy.may_cross(Scope.USER, "collective", dp_applied=True) is True
    assert privacy.may_cross(Scope.FIRM, Scope.GLOBAL, dp_applied=True) is True


# ───────────────────────── laplace mechanism ────────────────────────────


def test_laplace_noise_zero_mean():
    rng = random.Random(1234)
    samples = [privacy.laplace_noise(2.0, rng=rng) for _ in range(20000)]
    # Zero-mean distribution — mean of many draws is close to 0.
    assert abs(statistics.fmean(samples)) < 0.1


def test_laplace_noise_requires_positive_scale():
    with pytest.raises(ValueError):
        privacy.laplace_noise(0.0)
    with pytest.raises(ValueError):
        privacy.laplace_noise(-1.0)


def test_is_opendp_available_returns_bool():
    # Either path is acceptable; the call must never raise + must be cached.
    val = privacy.is_opendp_available()
    assert isinstance(val, bool)
    assert privacy.is_opendp_available() is val


# ───────────────────────── dp_count ─────────────────────────────────────


def test_dp_count_never_negative():
    rng = random.Random(7)
    # Tiny epsilon = huge noise; must still clamp to >= 0 and stay int.
    for _ in range(2000):
        c = privacy.dp_count(0, epsilon=0.05, rng=rng)
        assert isinstance(c, int)
        assert c >= 0


def test_dp_count_mean_near_true_count():
    rng = random.Random(99)
    true = 500
    samples = [privacy.dp_count(true, epsilon=1.0, rng=rng) for _ in range(4000)]
    mean = statistics.fmean(samples)
    # Zero-mean noise → average of noised counts hugs the true count.
    # (clamping at 0 is irrelevant this far from zero.)
    assert abs(mean - true) < 5.0


def test_dp_count_validates_params():
    with pytest.raises(ValueError):
        privacy.dp_count(10, epsilon=0)
    with pytest.raises(ValueError):
        privacy.dp_count(10, epsilon=1.0, sensitivity=0)


# ───────────────────────── dp_aggregate ─────────────────────────────────


def test_dp_aggregate_keys_present_and_noised():
    rng = random.Random(3)
    agg = privacy.dp_aggregate(
        [1.0, 2.0, 3.0, 4.0], epsilon=1.0, sensitivity=1.0, rng=rng
    )
    for key in ("count", "sum", "mean", "epsilon", "sensitivity", "dp_applied"):
        assert key in agg
    assert agg["dp_applied"] is True
    assert agg["count"] >= 0
    # sum is noised — almost surely not exactly the true sum of 10.0
    assert agg["sum"] != 10.0


def test_dp_aggregate_mean_tracks_true_mean_on_average():
    rng = random.Random(11)
    vals = [10.0] * 200
    means = [
        privacy.dp_aggregate(vals, epsilon=2.0, sensitivity=1.0, rng=rng)["mean"]
        for _ in range(300)
    ]
    # True mean is 10; noised means average near it.
    assert abs(statistics.fmean(means) - 10.0) < 1.0


def test_dp_aggregate_empty_is_safe():
    agg = privacy.dp_aggregate([], epsilon=1.0, sensitivity=1.0)
    assert agg["count"] >= 0
    assert agg["mean"] == 0.0


# ───────────────────────── privatize_for_collective ─────────────────────
#
# The crown-jewel test: raw fragments in → ONLY aggregates out. No raw
# subject / object / predicate / text / origin id may appear in the output.


_SECRET_STRINGS = [
    "SECRET_SUBJECT_doubletree_walls",
    "SECRET_PREDICATE_classified_as",
    "SECRET_OBJECT_load_bearing_v0024",
    "SECRET_TEXT_client_name_acme_corp_address_123_main",
    "p-664-doubletree",          # project_id
    "fargaly",                   # owner_user
    "firm-archhub-internal",     # firm_id
]


def _fragments_with_secrets() -> list[Fragment]:
    return [
        _make_fragment(
            "f_a",
            kind=FragmentKind.FACT,
            scope=Scope.FIRM,
            subject=_SECRET_STRINGS[0],
            predicate=_SECRET_STRINGS[1],
            obj=_SECRET_STRINGS[2],
            text=_SECRET_STRINGS[3],
            owner_user=_SECRET_STRINGS[5],
            project_id=_SECRET_STRINGS[4],
            firm_id=_SECRET_STRINGS[6],
            success_count=3,
            fail_count=1,
        ),
        _make_fragment(
            "f_b",
            kind=FragmentKind.SKILL,
            scope=Scope.PROJECT,
            subject=_SECRET_STRINGS[0],
            text=_SECRET_STRINGS[3],
            owner_user=_SECRET_STRINGS[5],
            success_count=5,
            fail_count=0,
        ),
        _make_fragment(
            "f_c",
            kind=FragmentKind.FACT,
            scope=Scope.FIRM,
            obj=_SECRET_STRINGS[2],
            text="another raw note",
            success_count=2,
            fail_count=2,
        ),
    ]


def test_privatize_for_collective_emits_only_aggregate_keys():
    rng = random.Random(42)
    out = privacy.privatize_for_collective(_fragments_with_secrets(), epsilon=1.0, rng=rng)
    # Every top-level key is an allow-listed aggregate/metadata key.
    assert privacy.is_pure_aggregate(out), f"unexpected keys: {set(out.keys())}"
    assert out["dp_applied"] is True
    assert "counts_by_kind" in out
    assert "counts_by_scope" in out
    # Counts present for the kinds/scopes that were in the input.
    assert set(out["counts_by_kind"].keys()) == {"fact", "skill"}
    assert set(out["counts_by_scope"].keys()) == {"firm", "project"}


def test_privatize_for_collective_no_raw_strings_leak():
    """CORE PRIVACY GUARANTEE: no raw fragment string survives into the
    collective output. Serialise the whole output and assert every secret
    string is absent."""
    rng = random.Random(42)
    out = privacy.privatize_for_collective(_fragments_with_secrets(), epsilon=1.0, rng=rng)
    blob = json.dumps(out)
    for secret in _SECRET_STRINGS:
        assert secret not in blob, f"raw string leaked into collective output: {secret!r}"


def test_privatize_for_collective_output_passes_the_gate():
    """The DP output is what is allowed to cross into COLLECTIVE."""
    out = privacy.privatize_for_collective(_fragments_with_secrets(), epsilon=1.0)
    assert privacy.may_cross(
        Scope.FIRM, privacy.COLLECTIVE, dp_applied=out["dp_applied"]
    )


def test_privatize_for_collective_counts_are_nonneg_ints():
    rng = random.Random(5)
    out = privacy.privatize_for_collective(_fragments_with_secrets(), epsilon=0.5, rng=rng)
    assert isinstance(out["total_fragments"], int) and out["total_fragments"] >= 0
    for v in out["counts_by_kind"].values():
        assert isinstance(v, int) and v >= 0
    for v in out["counts_by_scope"].values():
        assert isinstance(v, int) and v >= 0
    assert 0.0 <= out["success_rate"] <= 1.0


def test_privatize_for_collective_empty_input():
    out = privacy.privatize_for_collective([], epsilon=1.0)
    assert out["total_fragments"] >= 0
    assert out["counts_by_kind"] == {}
    assert out["counts_by_scope"] == {}
    assert privacy.is_pure_aggregate(out)


# ───────────────────────── dataset_export wiring ────────────────────────
#
# The thin hook in dataset_export.export_fragments: a collective-class scope
# routes through privacy.privatize_for_collective and emits DP aggregates —
# never raw rows. Pins that the wire is live + that the file artefact carries
# no raw fragment strings either.

from pathlib import Path  # noqa: E402

from personal_brain.dataset_export import export_fragments  # noqa: E402
from personal_brain.storage import BrainStore as _Store  # noqa: E402


@pytest.fixture
def store(tmp_path):
    return _Store.open(tmp_path / "test.db")


def _write_secret_frag(store, fid, scope, **kw):
    store.write_fragment(
        _make_fragment(fid, scope=scope, **kw)
    )


def test_export_collective_scope_emits_dp_not_raw_rows(store, tmp_path):
    _write_secret_frag(
        store, "f_a", Scope.COMMUNITY,
        subject=_SECRET_STRINGS[0], text=_SECRET_STRINGS[3],
        owner_user=_SECRET_STRINGS[5],
    )
    _write_secret_frag(
        store, "f_b", Scope.COMMUNITY,
        obj=_SECRET_STRINGS[2], text="raw note two",
    )
    manifest = export_fragments(
        store, out_dir=tmp_path / "exp", dataset_name="ds-collective",
        scope_filter=[Scope.COMMUNITY],
    )
    assert manifest["mode"] == "collective_dp"
    assert manifest["differential_privacy"] is True
    assert manifest["row_count"] == 0
    # No raw fragments.jsonl written at all.
    target = tmp_path / "exp" / "ds-collective"
    assert not (target / "fragments.jsonl").exists()
    # An aggregates.json artefact exists + carries NO raw strings.
    agg_path = Path(manifest["files"]["aggregates"]["path"])
    assert agg_path.exists()
    blob = agg_path.read_text(encoding="utf-8")
    for secret in _SECRET_STRINGS:
        assert secret not in blob, f"raw string leaked to collective file: {secret!r}"


def test_export_non_collective_scope_still_writes_raw_rows(store, tmp_path):
    """Regression guard — USER/PROJECT/FIRM exports are unchanged by the hook."""
    _write_secret_frag(store, "f_u", Scope.USER, text="user fact")
    manifest = export_fragments(
        store, out_dir=tmp_path / "exp", dataset_name="ds-user",
        scope_filter=[Scope.USER],
    )
    # Old code path: real rows + jsonl file, no DP mode.
    assert manifest.get("mode") != "collective_dp"
    assert manifest["row_count"] == 1
    jsonl = Path(manifest["files"]["jsonl"]["path"])
    assert jsonl.exists()


def test_export_mixed_scope_with_collective_routes_to_dp(store, tmp_path):
    """If COMMUNITY/GLOBAL appears anywhere in the filter, DP wins."""
    _write_secret_frag(store, "f_u", Scope.USER, text="user fact")
    _write_secret_frag(store, "f_g", Scope.GLOBAL, text="global fact")
    manifest = export_fragments(
        store, out_dir=tmp_path / "exp", dataset_name="ds-mixed",
        scope_filter=[Scope.USER, Scope.GLOBAL],
    )
    assert manifest["mode"] == "collective_dp"
    assert not (tmp_path / "exp" / "ds-mixed" / "fragments.jsonl").exists()
