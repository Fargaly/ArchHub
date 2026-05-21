"""Plan-history persistence — M4 foundation (AgDR-0021).

Each `ai.plan` cook writes a JSON record under
`<project_dir>/.archhub/plans/<plan_id>.json`. `plan_id` is a
deterministic 16-hex hash of `(prompt, model, extra)` so the same
inputs always map to the same file — replay-mode reads the cached
record without re-calling the LLM.

Record shape:
    {
      "plan_id":  str,
      "prompt":   str,
      "model":    str,
      "plan":     list[dict],      # tool_invocations from the LLM
      "result":   str,             # final LLM text
      "status":   "ok" | "error",
      "error":    str | None,
      "ts":       int (unix epoch),
    }

Saves are best-effort + atomic where possible (write to .tmp then
rename). Failure to persist does NOT block the cook — the in-process
record is still returned.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


_PLAN_ID_HEX_LEN = 16


class PlanHistory:
    """Per-project plan history. Construct with project_dir;
    `save`/`load`/`list_ids`/`delete` all rooted at
    `<project_dir>/.archhub/plans/`."""

    def __init__(self, project_dir: str | Path) -> None:
        self.root = Path(project_dir) / ".archhub" / "plans"
        try:
            self.root.mkdir(parents=True, exist_ok=True)
        except Exception:
            # If we can't create the dir, save/load will fail
            # honestly. Don't crash construction.
            pass

    # ── id allocation ────────────────────────────────────────────

    @staticmethod
    def id_for(*, prompt: str, model: str, extra: str = "") -> str:
        """Deterministic 16-hex plan id from `(prompt, model, extra)`.
        Same inputs → same id → cache hit on replay."""
        h = hashlib.sha256()
        payload = f"{prompt or ''}|{model or ''}|{extra or ''}"
        h.update(payload.encode("utf-8"))
        return h.hexdigest()[:_PLAN_ID_HEX_LEN]

    # ── persistence ──────────────────────────────────────────────

    def _path_for(self, plan_id: str) -> Path:
        return self.root / f"{plan_id}.json"

    def save(self, record: dict) -> bool:
        """Write the record atomically. Returns True on success,
        False on any IO failure (without raising — failure to
        persist must NOT block the cook)."""
        if not isinstance(record, dict) or not record.get("plan_id"):
            return False
        target = self._path_for(record["plan_id"])
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            # Write to a sibling .tmp + os.replace for atomicity.
            with tempfile.NamedTemporaryFile(
                    mode="w", encoding="utf-8", delete=False,
                    dir=self.root,
                    prefix=record["plan_id"] + ".",
                    suffix=".tmp") as f:
                json.dump(record, f, indent=2, default=str)
                tmp_name = f.name
            os.replace(tmp_name, target)
            return True
        except Exception:
            return False

    def load(self, plan_id: str) -> dict | None:
        """Load a record by id. None when absent or unreadable."""
        path = self._path_for(plan_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def list_ids(self) -> list[str]:
        """All plan ids on disk, sorted by file mtime descending
        (most-recent first) so a JSX history view shows the latest
        turn at the top."""
        if not self.root.exists():
            return []
        files = list(self.root.glob("*.json"))
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return [p.stem for p in files]

    def list_records(self, limit: int = 50) -> list[dict]:
        """Convenience: load + return the most-recent N records.
        Used by the Composer history panel (M4 phase 2)."""
        out: list[dict] = []
        for pid in self.list_ids()[:limit]:
            r = self.load(pid)
            if r is not None:
                out.append(r)
        return out

    def delete(self, plan_id: str) -> bool:
        """Remove a record. Returns True if deleted, False if absent
        or unremovable."""
        path = self._path_for(plan_id)
        if not path.exists():
            return False
        try:
            path.unlink()
            return True
        except Exception:
            return False

    def prune(self, keep_last: int = 100) -> int:
        """Keep only the most-recent `keep_last` records; delete the
        rest. Returns the deletion count. Use sparingly — plan
        records are small + the founder's mandate is "every action
        reversible"."""
        all_ids = self.list_ids()
        if len(all_ids) <= keep_last:
            return 0
        to_drop = all_ids[keep_last:]
        n = 0
        for pid in to_drop:
            if self.delete(pid):
                n += 1
        return n


__all__ = ["PlanHistory"]
