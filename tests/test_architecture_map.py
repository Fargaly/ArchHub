"""Gate test for the canonical architecture / system map (DOC-13).

The gap: there was no single "what-is-built" entry point — truth was scattered
across 3 ADRs, 54 AgDRs, CLAUDE.md "Key files", and partly-stale `*_PLAN.md`,
so a new contributor or auditing agent had no canonical place to start.

The gate (verbatim): `docs/ARCHITECTURE.md` exists, is listed in `index.json`,
declares its `app/*` artifact deps, and is linked from ROADMAP.

RED-before / GREEN-after:
  * RED on origin/main: `docs/ARCHITECTURE.md` does not exist; the index built
    from origin/main has no ARCHITECTURE entry; ROADMAP does not link it.
  * GREEN on this branch: the file exists with a real `## Artifacts` block of
    `app/*` paths, the freshness index lists it with those deps, and ROADMAP
    points at it.

Run:
    python -m pytest tests/test_architecture_map.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = REPO_ROOT / "tools"
for _p in (str(REPO_ROOT), str(TOOLS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import doc_freshness as df  # noqa: E402

ARCH = REPO_ROOT / "docs" / "ARCHITECTURE.md"
ROADMAP = REPO_ROOT / "docs" / "ROADMAP.md"


def test_architecture_file_exists():
    assert ARCH.is_file(), "docs/ARCHITECTURE.md must exist (the system map)"
    text = ARCH.read_text(encoding="utf-8")
    # It must be a real map, not a stub: a meaningful body + the Artifacts hook.
    assert len(text.split()) > 300, "ARCHITECTURE.md looks like a stub"
    assert "## Artifacts" in text, "must carry an Artifacts section for freshness"


def test_architecture_declares_real_app_artifact_deps():
    """The map names real `app/*` artifacts and every one resolves on disk."""
    text = ARCH.read_text(encoding="utf-8")
    artefacts = df._artifacts_paths(text)
    app_paths = [a for a in artefacts if a.startswith("app/")]
    assert len(app_paths) >= 5, (
        f"ARCHITECTURE.md must declare its app/* artifact deps; got {app_paths}")
    for a in app_paths:
        assert (REPO_ROOT / a).is_file(), (
            f"declared artifact {a} does not exist — the map cites a phantom")


def test_architecture_is_listed_in_index_with_deps():
    """`build_index_and_freshness` lists ARCHITECTURE.md, and its index entry
    carries the `app/*` deps — and no dangling doc refs (DOC-12 holds for the
    new doc too)."""
    index, _fresh = df.build_index_and_freshness(REPO_ROOT)
    entry = next((e for e in index if e["path"] == "docs/ARCHITECTURE.md"), None)
    assert entry is not None, "ARCHITECTURE.md not in the generated index"
    app_deps = [d for d in entry["deps"] if d.startswith("app/")]
    assert len(app_deps) >= 5, f"index entry lacks app/* deps: {entry['deps']}"
    assert entry.get("missing_deps") == [], (
        f"ARCHITECTURE.md introduced dangling refs: {entry.get('missing_deps')}")


def test_architecture_listed_in_committed_index_json():
    """The COMMITTED index.json (not just a fresh build) lists ARCHITECTURE.md
    — proving the regenerated index is checked in."""
    import json
    committed = json.loads(
        (REPO_ROOT / "docs" / "_meta" / "index.json").read_text(encoding="utf-8"))
    paths = {e["path"] for e in committed}
    assert "docs/ARCHITECTURE.md" in paths, (
        "committed index.json does not list ARCHITECTURE.md — "
        "run `python tools/doc_freshness.py`")


def test_architecture_is_linked_from_roadmap():
    """ROADMAP points at the system map."""
    roadmap = ROADMAP.read_text(encoding="utf-8")
    assert "ARCHITECTURE.md" in roadmap, (
        "docs/ROADMAP.md must link docs/ARCHITECTURE.md (the entry point)")
