"""Export the brain's REAL community data → the website's COMMITTED static files.

WHY THIS EXISTS
===============
The marketing site (`web/`) builds with `astro build` and reads ONLY committed
JSON under `web/src/data/` — no live daemon at deploy time (per the build
decoupling in `web/astro.config.mjs`). A maintainer refreshes that committed
data from the live brain with this tool, then commits the diff.

`web/scripts/from-brain.js` already pulls community skills over the MCP wire,
but the `brain.skill_export` MCP response intentionally omits per-skill SUCCESS
STATS (`success_count`, `fail_count`, honing trials, minted date). The website
wants those stats to show real provenance ("minted 2026-05-30, honed 2/3"), so
this exporter reads the brain STORE directly (the same public storage API that
`tools/brain_graph_export.py` and `tools/backfill_skills.py` already use) and
captures the full picture. The daemon holds `brain.db` in WAL mode, so a
concurrent reader is safe while the daemon runs.

It writes TWO committed files the site reads at build time:

  * web/src/data/skills-export.json — real COMMUNITY-scope skills with stats.
    /features renders a card per skill (honest empty state if there are 0).
  * web/src/data/contributors.json — the federation contributor leaderboard,
    DERIVED from real data: any reputation rows the brain holds PLUS the
    authors of the published community skills (a person who has published a
    community skill IS a real contributor). 0 → /community shows a data-driven
    "be the first contributor" state, never a fabricated leaderboard.

Both files are honest: real rows when real data exists, an explicit empty list
(not a hardcoded fake) when it does not.

USAGE
=====
    python tools/export_web_data.py                 # live, against real brain.db
    python tools/export_web_data.py --db PATH        # explicit brain.db path
    python tools/export_web_data.py --dry-run        # print, do not write files

READ-ONLY: this tool never writes to brain.db. It only reads skills + reputation
and writes the two committed JSON files under web/src/data/.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ── make personal_brain importable (personal-brain-mcp/src on sys.path) ──
_REPO = Path(__file__).resolve().parent.parent
_PB_SRC = _REPO / "personal-brain-mcp" / "src"
if _PB_SRC.exists() and str(_PB_SRC) not in sys.path:
    sys.path.insert(0, str(_PB_SRC))

from personal_brain.models import Scope  # noqa: E402
from personal_brain.storage import BrainStore, default_brain_path  # noqa: E402

_WEB_DATA = _REPO / "web" / "src" / "data"
SKILLS_JSON = _WEB_DATA / "skills-export.json"
CONTRIBUTORS_JSON = _WEB_DATA / "contributors.json"


def _iso(dt: Any) -> Optional[str]:
    """Best-effort ISO string for a datetime-ish value."""
    if dt is None:
        return None
    if isinstance(dt, str):
        return dt
    try:
        return dt.isoformat()
    except Exception:
        return str(dt)


def _contributor_of(sk: Any) -> str:
    """The human credited with a skill: provenance.contributing_user, else owner."""
    prov = getattr(sk, "provenance", None)
    cu = getattr(prov, "contributing_user", None) if prov else None
    return cu or getattr(sk, "owner_user", None) or "unknown"


def collect(store: BrainStore, *, limit: int = 200) -> dict[str, Any]:
    """Read REAL community skills + reputation from the brain store.

    Returns the two payloads ready to serialise: {"skills": {...},
    "contributors": {...}}.
    """
    skills = store.list_skills(scope=Scope.COMMUNITY, limit=limit)
    exported_at = datetime.now(timezone.utc).isoformat()

    skill_rows: list[dict[str, Any]] = []
    for sk in skills:
        scope_val = sk.scope.value if hasattr(sk.scope, "value") else str(sk.scope)
        skill_rows.append({
            "id": sk.id,
            "name": sk.name,
            "description": sk.description,
            "scope": scope_val,
            "contributor": _contributor_of(sk),
            "triggers": list(sk.triggers or []),
            "requires_mcps": list(sk.requires_mcps or []),
            # Real success stats the MCP export omits.
            "success_count": int(getattr(sk, "success_count", 0) or 0),
            "fail_count": int(getattr(sk, "fail_count", 0) or 0),
            "honed_trials": int(getattr(sk, "honed_trials", 0) or 0),
            "honed_passed": int(getattr(sk, "honed_passed", 0) or 0),
            "minted_at": _iso(getattr(sk, "minted_at", None)),
            "last_used_at": _iso(getattr(sk, "last_used_at", None)),
        })

    skills_payload = {
        "exported_at": exported_at,
        "scope": "community",
        "count": len(skill_rows),
        "source": "brain.list_skills(scope=COMMUNITY) via tools/export_web_data.py",
        "note": (
            f"{len(skill_rows)} community skill(s) exported from the live brain."
            if skill_rows else
            "No community skills published to the federation yet — /features "
            "renders an honest empty state. Regenerate with "
            "`python tools/export_web_data.py` (needs the brain on :8473)."
        ),
        "skills": skill_rows,
    }

    # ── contributors: real reputation rows + community-skill authorship ──
    # A person who has published a community skill is a real contributor even
    # before any peer reputation has been exchanged. We aggregate per author.
    agg: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "published_skills": 0,
            "success_total": 0,
            "honed_passed": 0,
            "honed_trials": 0,
            "skills": [],
            "first_published": None,
        }
    )
    for sk in skills:
        who = _contributor_of(sk)
        a = agg[who]
        a["published_skills"] += 1
        a["success_total"] += int(getattr(sk, "success_count", 0) or 0)
        a["honed_passed"] += int(getattr(sk, "honed_passed", 0) or 0)
        a["honed_trials"] += int(getattr(sk, "honed_trials", 0) or 0)
        a["skills"].append(sk.name)
        minted = _iso(getattr(sk, "minted_at", None))
        if minted and (a["first_published"] is None or minted < a["first_published"]):
            a["first_published"] = minted

    # Merge any real reputation rows the federation holds (currently 0).
    reputations: list[Any] = []
    try:
        if hasattr(store, "list_reputations"):
            reputations = store.list_reputations() or []
    except Exception:
        reputations = []

    rep_by_user: dict[str, float] = {}
    for r in reputations:
        uid = (
            getattr(r, "user_id", None)
            or getattr(r, "contributor", None)
            or getattr(r, "peer_id", None)
        )
        score = (
            getattr(r, "score", None)
            or getattr(r, "reputation", None)
            or getattr(r, "mean", None)
        )
        if uid is not None:
            rep_by_user[str(uid)] = float(score) if score is not None else 0.0
            agg[str(uid)]  # ensure the user appears even with no skills

    contributors: list[dict[str, Any]] = []
    for who, a in agg.items():
        contributors.append({
            "contributor": who,
            "published_skills": a["published_skills"],
            "success_total": a["success_total"],
            "honed_passed": a["honed_passed"],
            "honed_trials": a["honed_trials"],
            "reputation": rep_by_user.get(who),
            "first_published": a["first_published"],
            "skills": a["skills"],
        })
    # Rank: most published skills, then most honed passes, then name.
    contributors.sort(
        key=lambda c: (-c["published_skills"], -c["honed_passed"], c["contributor"])
    )

    contributors_payload = {
        "exported_at": exported_at,
        "count": len(contributors),
        "reputation_rows": len(reputations),
        "source": (
            "brain.list_reputations() + community-skill authorship via "
            "tools/export_web_data.py"
        ),
        "note": (
            f"{len(contributors)} contributor(s) have published to the "
            f"community scope ({len(reputations)} peer-reputation row(s) "
            f"exchanged)."
            if contributors else
            "No contributors have published to the community federation yet — "
            "/community renders a data-driven 'be the first' state, not a "
            "fabricated leaderboard."
        ),
        "contributors": contributors,
    }

    return {"skills": skills_payload, "contributors": contributors_payload}


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Export real brain community data → committed web JSON.")
    parser.add_argument("--db", default=None,
                        help="path to brain.db (default: OS brain path)")
    parser.add_argument("--dry-run", action="store_true",
                        help="print payloads; do not write files")
    args = parser.parse_args(argv)

    db_path = args.db or str(default_brain_path())
    store = BrainStore.open(db_path)
    try:
        try:
            store._conn.execute("PRAGMA busy_timeout=5000")
        except Exception:
            pass
        payloads = collect(store)
    finally:
        store.close()

    skills_p = payloads["skills"]
    contrib_p = payloads["contributors"]

    print(f"brain.db            : {db_path}")
    print(f"community skills    : {skills_p['count']}")
    for s in skills_p["skills"]:
        print(f"  - {s['name']}  (by {s['contributor']}, "
              f"honed {s['honed_passed']}/{s['honed_trials']}, "
              f"succ {s['success_count']})")
    print(f"contributors        : {contrib_p['count']}  "
          f"(reputation rows: {contrib_p['reputation_rows']})")
    for c in contrib_p["contributors"]:
        print(f"  - {c['contributor']}  published={c['published_skills']} "
              f"honed={c['honed_passed']}/{c['honed_trials']}")

    if args.dry_run:
        print("\n[dry-run] not writing files. Payloads:")
        print(json.dumps(payloads, indent=2)[:2000])
        return 0

    _WEB_DATA.mkdir(parents=True, exist_ok=True)
    SKILLS_JSON.write_text(json.dumps(skills_p, indent=2) + "\n", encoding="utf-8")
    CONTRIBUTORS_JSON.write_text(
        json.dumps(contrib_p, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {SKILLS_JSON}")
    print(f"wrote {CONTRIBUTORS_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
