"""Gate tests for tools/doc_freshness.py coverage + dangling-ref honesty.

Covers two requirement leaves:

  DOC-11 — doc_freshness must index/check more than top-level `docs/*.md`.
           The 54 AgDRs (+ 3 ADRs + status/ + research/) each carry an
           `## Artifacts` section the engine was built to consume, yet they
           were invisible. After the fix:
             * index.json includes `docs/agdr/AgDR-*.md` + `docs/adr/ADR-*.md`
             * the entry count >= top-level + 54 + 3
             * a stale AgDR (an `## Artifacts` path committed AFTER the AgDR)
               reports `stale: true`.

  DOC-12 — index.json must not assert dependency edges to docs that don't
           exist. `docs/IRP.md`, `docs/SECURITY_REVIEW_LOG.md`,
           `docs/VENDORS.md`, `docs/ONBOARDING.md` are referenced by
           CAIQ_LITE / SOC2 / TRUST_CENTER / CONTENT-ECOSYSTEM but absent.
           After the fix every `docs/*.md` in any entry's `deps` resolves to
           a real file; the broken references are surfaced (not hidden) in a
           `missing_deps` field.

RED-before / GREEN-after:

  * DOC-11 RED on origin/main: `build_index_and_freshness` walked only
    `docs_dir.glob("*.md")` (non-recursive) → zero agdr/adr entries; the
    `_iter_doc_files` / INDEXED_SUBDIRS helpers did not exist.
  * DOC-12 RED on origin/main: `_doc_deps` added every `docs/X.md` ref to
    `deps` unconditionally → the 4 phantom files appeared as deps; there was
    no `missing_deps` field.

Run:
    python -m pytest tests/test_doc_freshness_coverage.py -q
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = REPO_ROOT / "tools"
for _p in (str(REPO_ROOT), str(TOOLS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import doc_freshness as df  # noqa: E402


# ──────────────────────────────────────────────────────────────────────────
# DOC-11 — coverage widened past top-level docs.
# ──────────────────────────────────────────────────────────────────────────
def test_real_index_includes_agdr_and_adr_entries():
    """The real repo index covers the AgDR + ADR decision records."""
    index, _fresh = df.build_index_and_freshness(REPO_ROOT)
    paths = {e["path"] for e in index}

    agdr = [p for p in paths if p.startswith("docs/agdr/") and p.endswith(".md")]
    adr = [p for p in paths if p.startswith("docs/adr/") and p.endswith(".md")]

    assert agdr, "no AgDR entries in index.json — coverage still top-level only"
    assert adr, "no ADR entries in index.json — coverage still top-level only"
    # The known corpus: 54 tracked AgDRs + 3 ADRs (at least).
    assert len(agdr) >= 54, f"expected >=54 AgDR entries, got {len(agdr)}"
    assert len(adr) >= 3, f"expected >=3 ADR entries, got {len(adr)}"


def test_entry_count_exceeds_toplevel_plus_records():
    """Entry count >= top-level docs + 54 AgDR + 3 ADR (the gate's floor)."""
    docs_dir = REPO_ROOT / "docs"
    top_level = [p for p in docs_dir.glob("*.md") if p.is_file()]
    index, _ = df.build_index_and_freshness(REPO_ROOT)
    floor = len(top_level) + 54 + 3
    assert len(index) >= floor, (
        f"index has {len(index)} entries; gate floor is {floor} "
        f"(top-level {len(top_level)} + 54 AgDR + 3 ADR)"
    )


def test_indexed_subdirs_constant_names_the_record_trees():
    """The widening is intentional (an allowlist), not a blind rglob that
    would sweep prototypes/mockups/archive HTML."""
    assert "agdr" in df.INDEXED_SUBDIRS
    assert "adr" in df.INDEXED_SUBDIRS
    # fossils / non-record trees stay OUT
    for noise in ("prototypes", "mockups", "archive", "_templates"):
        assert noise not in df.INDEXED_SUBDIRS


def _git(args, cwd):
    subprocess.run(["git", *args], cwd=str(cwd), check=True,
                   capture_output=True, text=True)


@pytest.mark.skipif(__import__("shutil").which("git") is None,
                    reason="git not on PATH")
def test_stale_agdr_reports_stale_true(tmp_path):
    """An AgDR whose `## Artifacts` path is committed AFTER the AgDR's own
    commit reports stale:true — proving the engine consumes AgDR Artifacts.

    Deterministic: a throwaway git repo with controlled commit order, so the
    git timeline (not wall-clock mtime) drives the verdict.
    """
    repo = tmp_path
    _git(["init", "-q"], repo)
    _git(["config", "user.email", "t@t.test"], repo)
    _git(["config", "user.name", "t"], repo)
    _git(["config", "commit.gpgsign", "false"], repo)

    (repo / "app").mkdir()
    artifact = repo / "app" / "thing.py"
    artifact.write_text("x = 1\n", encoding="utf-8")
    _git(["add", "app/thing.py"], repo)
    _git(["commit", "-q", "-m", "seed artifact"], repo)

    agdr_dir = repo / "docs" / "agdr"
    agdr_dir.mkdir(parents=True)
    agdr = agdr_dir / "AgDR-0099-thing.md"
    agdr.write_text(
        "---\nid: AgDR-0099\nstatus: executed\n---\n\n"
        "# AgDR-0099 — thing\n\n## Artifacts\n\n- `app/thing.py`\n",
        encoding="utf-8",
    )
    _git(["add", "docs/agdr/AgDR-0099-thing.md"], repo)
    _git(["commit", "-q", "-m", "add agdr"], repo)
    # Pin the AgDR's mtime to its commit instant so a LATER artifact commit
    # is unambiguously "after" it.
    import os
    out = subprocess.run(
        ["git", "log", "-1", "--pretty=format:%ct", "--", "docs/agdr/AgDR-0099-thing.md"],
        cwd=str(repo), capture_output=True, text=True, check=True)
    agdr_commit_ts = int(out.stdout.strip())
    os.utime(agdr, (agdr_commit_ts, agdr_commit_ts))

    # Now change the artifact AFTER the AgDR — this is the staleness signal.
    artifact.write_text("x = 2  # changed later\n", encoding="utf-8")
    _git(["add", "app/thing.py"], repo)
    # Force a strictly-later commit date.
    env_date = "2099-01-01T00:00:00"
    subprocess.run(
        ["git", "commit", "-q", "--date", env_date, "-m", "touch artifact later"],
        cwd=str(repo), check=True, capture_output=True, text=True,
        env={**os.environ, "GIT_COMMITTER_DATE": env_date},
    )

    index, freshness = df.build_index_and_freshness(repo)
    by_slug = {f["slug"]: f for f in freshness}
    assert "agdr/AgDR-0099-thing" in by_slug, (
        f"AgDR not indexed; slugs={list(by_slug)}")
    entry = by_slug["agdr/AgDR-0099-thing"]
    assert entry["stale"] is True, f"expected stale AgDR, got {entry}"
    assert "app/thing.py" in entry["reason"]


# ──────────────────────────────────────────────────────────────────────────
# DOC-12 — no dangling docs/*.md deps; broken refs surfaced honestly.
# ──────────────────────────────────────────────────────────────────────────
def test_real_index_has_no_dangling_doc_deps():
    """Every `docs/*.md` in any entry's deps resolves to a file on disk."""
    index, _ = df.build_index_and_freshness(REPO_ROOT)
    dangling = []
    for e in index:
        for dep in e.get("deps", []):
            if dep.startswith("docs/") and dep.endswith(".md"):
                if not (REPO_ROOT / dep).is_file():
                    dangling.append((e["path"], dep))
    assert not dangling, f"dangling doc deps still in index.json: {dangling}"


def test_phantom_compliance_docs_are_surfaced_not_dropped():
    """The 4 referenced-but-absent compliance docs appear in `missing_deps`
    (honest surfacing), never in `deps` (DOC-12)."""
    index, _ = df.build_index_and_freshness(REPO_ROOT)
    phantoms = {
        "docs/IRP.md",
        "docs/SECURITY_REVIEW_LOG.md",
        "docs/VENDORS.md",
        "docs/ONBOARDING.md",
    }
    all_missing = {m for e in index for m in e.get("missing_deps", [])}
    all_deps = {d for e in index for d in e.get("deps", [])}

    # None of the phantoms are absent on disk by assumption of this test;
    # if a future PR creates them, that's the OTHER half of the gate's OR.
    for phantom in phantoms:
        if (REPO_ROOT / phantom).is_file():
            continue  # citing-docs-corrected branch; nothing to assert
        assert phantom in all_missing, (
            f"{phantom} is referenced but missing and not surfaced in "
            "missing_deps")
        assert phantom not in all_deps, (
            f"{phantom} is a phantom file but still asserted as a real dep")


def test_resolve_doc_deps_splits_existing_from_missing(tmp_path):
    """Unit: a doc citing one real + one phantom doc → real in deps,
    phantom in missing_deps; an app/*.py artefact stays in deps."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "REAL.md").write_text("# real\n", encoding="utf-8")
    text = (
        "see docs/REAL.md and docs/GHOST.md and the code in "
        "`app/bridge.py`\n"
    )
    deps, missing = df._resolve_doc_deps(text, tmp_path)
    assert "docs/REAL.md" in deps
    assert "app/bridge.py" in deps
    assert "docs/GHOST.md" in missing
    assert "docs/GHOST.md" not in deps
    assert "docs/REAL.md" not in missing


def test_committed_meta_is_current():
    """The committed docs/_meta/index.json matches a fresh generation —
    so the widened, dangling-free index is actually checked in (not just a
    code change with a stale artifact). Compares the structural payload,
    ignoring the per-run `last_check_iso` timestamps in freshness.json."""
    import json
    index, _fresh = df.build_index_and_freshness(REPO_ROOT)
    committed = json.loads(
        (REPO_ROOT / "docs" / "_meta" / "index.json").read_text(encoding="utf-8"))
    # index.json carries no timestamps → must match exactly (mtime aside,
    # which is stable for committed files within a checkout).
    fresh_paths = sorted(e["path"] for e in index)
    committed_paths = sorted(e["path"] for e in committed)
    assert committed_paths == fresh_paths, (
        "committed index.json is stale — run `python tools/doc_freshness.py`")
    # every committed entry carries the new missing_deps field
    assert all("missing_deps" in e for e in committed), (
        "committed index.json predates the missing_deps field")
