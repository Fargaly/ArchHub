"""Skill index exporter — feeds the Backlog + Telemetry depts.

Writes a JSON file the dept agents can read at task-build time. We
DON'T let depts read the raw Skill `.json` files (they often contain
prompt template fragments we'd rather not surface as `(redacted)` in
agent context). The exporter strips the workflow body and keeps only
the metadata + usage stats the dept needs to draft a fix.

Output: `agents/outputs/_index/skills.json`
   {
     "generated_at": ISO,
     "skills": [
       {"id", "name", "intent", "tags", "requires", "library",
        "runs", "successes", "failures", "retries", "last_error"}
     ]
   }
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .library import list_skills
from .usage import all_usage


# Same root the depts read from (agents/outputs/...).
_OUTPUT_ROOT = Path(__file__).resolve().parent.parent.parent / "agents" / "outputs" / "_index"


def export_skills_index(output_path: Optional[Path] = None) -> Path:
    """Write the index file. Returns the resolved path."""
    output_path = output_path or _OUTPUT_ROOT / "skills.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    usage = all_usage() or {}
    rows = []
    for s in list_skills():
        u = usage.get(s["id"]) or {}
        rows.append({
            "id":          s["id"],
            "name":        s.get("name") or "",
            "intent":      s.get("intent") or "",
            "tags":        s.get("tags") or [],
            "requires":    s.get("requires") or [],
            "library":     s.get("library") or "user",
            "runs":        int(u.get("runs", 0) or 0),
            "successes":   int(u.get("successes", 0) or 0),
            "failures":    int(u.get("failures", 0) or 0),
            "retries":     int(u.get("retries", 0) or 0),
            "last_error":  (u.get("last_error") or "")[:240],
            "last_used":   u.get("last_used") or "",
        })

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "skills": rows,
    }
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return output_path
