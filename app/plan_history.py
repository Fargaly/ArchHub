"""Plan-history persistence — M4 foundation (AgDR-0021).

Each `ai.plan` cook writes a JSON record under
`<project_dir>/.archhub/plans/<plan_id>.json`. `plan_id` is a
deterministic 16-hex hash of `(prompt, model, extra[, session_id])` so
the same inputs always map to the same file — replay-mode reads the
cached record without re-calling the LLM.

Session-keying (IA fix, ia-critique-ai-stemcells-2026-06-03 — plans
belong to a SESSION, not a global pool): when constructed with a
non-empty `session_id`, records root under
`<project_dir>/.archhub/sessions/<session_id>/plans/` and the same
`session_id` folds into `id_for` so two sessions that ask the same
prompt get distinct slots. This is ADDITIVE + back-compat: an empty /
omitted `session_id` keeps the historical global root
`<project_dir>/.archhub/plans/` and the historical id, so plans
written before session-keying still load unchanged.

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


def _safe_session(session_id: str) -> str:
    """Sanitise a session id for use as a single path segment.

    Sessions are named by the JSX side (`sess-…`, a uuid, or a slug). We
    never trust an externally-supplied name as a raw directory: strip any
    char outside `[A-Za-z0-9._-]` so a stray `/`, `..`, or drive-letter
    can't escape `<project_dir>/.archhub/sessions/`. The id stays
    deterministic (same input → same safe segment), so a record written
    for a session is always found again under the same folder. Empty
    after sanitising → a stable `_unnamed` bucket rather than the project
    root."""
    sid = (session_id or "").strip()
    safe = "".join(c if (c.isalnum() or c in "._-") else "_" for c in sid)
    safe = safe.strip(".")  # never a leading/trailing dot segment
    return safe or "_unnamed"


class PlanHistory:
    """Per-project (optionally per-session) plan history.

    Construct with `project_dir` (and, for session-scoped history, a
    `session_id`); `save`/`load`/`list_ids`/`delete` are all rooted at:

      * `<project_dir>/.archhub/sessions/<session_id>/plans/` when a
        non-empty `session_id` is given, OR
      * `<project_dir>/.archhub/plans/` (the historical global pool)
        when `session_id` is empty / omitted.

    The empty-session root is preserved byte-for-byte from the
    pre-session-keying layout so old global plans keep loading.
    """

    def __init__(self, project_dir: str | Path,
                 session_id: str | None = None) -> None:
        self.session_id = (session_id or "").strip()
        base = Path(project_dir) / ".archhub"
        if self.session_id:
            # Session-scoped: plans live with the session they belong to.
            # `_safe_session` keeps the id filesystem-safe (sessions are
            # named by the JSX side; never let a stray char escape the dir).
            self.root = base / "sessions" / _safe_session(self.session_id) / "plans"
        else:
            # Back-compat global pool — unchanged from before session-keying.
            self.root = base / "plans"
        try:
            self.root.mkdir(parents=True, exist_ok=True)
        except Exception:
            # If we can't create the dir, save/load will fail
            # honestly. Don't crash construction.
            pass

    # ── id allocation ────────────────────────────────────────────

    @staticmethod
    def id_for(*, prompt: str, model: str, extra: str = "",
               session_id: str = "") -> str:
        """Deterministic 16-hex plan id from
        `(prompt, model, extra[, session_id])`. Same inputs → same id →
        cache hit on replay.

        `session_id` defaults to "" so a call that omits it produces the
        EXACT id the pre-session-keying code produced (back-compat: the
        payload is unchanged when session_id is empty). A non-empty
        `session_id` folds into the hash so the same prompt asked in two
        different sessions maps to two distinct slots."""
        h = hashlib.sha256()
        payload = f"{prompt or ''}|{model or ''}|{extra or ''}"
        sid = (session_id or "").strip()
        if sid:
            # Append-only: keeps the empty-session payload identical to
            # the historical one (no id churn for existing global plans).
            payload = f"{payload}|{sid}"
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
