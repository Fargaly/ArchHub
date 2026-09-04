"""Import Claude Code project sessions into ArchHub sessions + brain.

Reads Claude's per-project JSONL transcripts, writes ArchHub-compatible
`.archhub-session.json` files, and stores compact searchable trace fragments in
the canonical personal-brain SQLite store. Full transcripts stay in the session
files; brain fragments keep summaries and file pointers so the brain DB does
not balloon with raw tool logs.

Run from the repo root:

    python tools/import_claude_sessions.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional


_REPO = Path(__file__).resolve().parent.parent
_PB_SRC = _REPO / "personal-brain-mcp" / "src"
if str(_PB_SRC) not in sys.path:
    sys.path.insert(0, str(_PB_SRC))

from personal_brain.models import (  # noqa: E402
    Confidence,
    Fragment,
    FragmentKind,
    Provenance,
    Scope,
    Visibility,
)
from personal_brain.storage import BrainStore, default_brain_path  # noqa: E402


DEFAULT_PROJECT_DIRS = [
    Path.home() / ".claude" / "projects" / "C--Users-fargaly-00-ARCHUB",
    Path.home() / ".claude" / "projects" / "C--Users-fargaly-00-ARCHUB-ArchHub",
]

DEFAULT_SESSIONS_DIR = (
    Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
    / "ArchHub"
    / "sessions"
)

SESSION_EXT = ".archhub-session.json"
OWNER_USER = "founder"
PROJECT_ID = "archhub"


def _parse_ts(raw: Any) -> Optional[datetime]:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        value = float(raw)
        if value > 10_000_000_000:
            value /= 1000.0
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(raw, str):
        value = raw.strip()
        if not value:
            return None
        if value.isdigit():
            return _parse_ts(int(value))
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _iso(dt: Optional[datetime]) -> str:
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _epoch(dt: Optional[datetime]) -> float:
    if dt is None:
        return datetime.now(timezone.utc).timestamp()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _clean_text(text: Any, *, limit: Optional[int] = None) -> str:
    if text is None:
        return ""
    if not isinstance(text, str):
        try:
            text = json.dumps(text, ensure_ascii=False, default=str)
        except TypeError:
            text = str(text)
    text = text.replace("\x00", "")
    if limit is not None and len(text) > limit:
        return text[:limit] + "\n\n[truncated]"
    return text


def _content_to_text(content: Any) -> tuple[str, list[str], list[dict[str, Any]]]:
    images: list[str] = []
    tools: list[dict[str, Any]] = []
    if isinstance(content, str):
        return _clean_text(content), images, tools
    if not isinstance(content, list):
        return _clean_text(content), images, tools

    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
            continue
        if not isinstance(block, dict):
            parts.append(_clean_text(block))
            continue
        btype = block.get("type") or block.get("kind") or ""
        if btype == "text":
            parts.append(str(block.get("text") or ""))
        elif btype in ("image", "image_url"):
            src = block.get("source") or block.get("url") or block.get("path")
            if isinstance(src, dict):
                src = src.get("url") or src.get("path") or src.get("data")
            if src:
                images.append(str(src))
            parts.append("[image]")
        elif btype == "tool_use":
            name = block.get("name") or block.get("tool") or "tool"
            tool_id = block.get("id") or hashlib.sha1(
                json.dumps(block, sort_keys=True, default=str).encode("utf-8")
            ).hexdigest()[:16]
            args = block.get("input") or block.get("arguments") or {}
            tools.append({
                "id": tool_id,
                "tool_name": name,
                "arguments": args,
                "status": "called",
                "result": None,
            })
            parts.append(f"[tool_use {name}]")
        elif btype == "tool_result":
            content_text = _clean_text(block.get("content"))
            parts.append(f"[tool_result]\n{content_text}".strip())
        else:
            text = block.get("text") or block.get("content")
            if text:
                parts.append(_clean_text(text))
    return _clean_text("\n".join(p for p in parts if p)), images, tools


def _record_timestamp(record: dict[str, Any]) -> Optional[datetime]:
    for key in ("timestamp", "created_at", "createdAt", "startedAt"):
        dt = _parse_ts(record.get(key))
        if dt is not None:
            return dt
    return None


def _record_session_id(record: dict[str, Any], fallback: str) -> str:
    return str(record.get("sessionId") or record.get("session_id") or fallback)


def _message_from_record(record: dict[str, Any]) -> Optional[dict[str, Any]]:
    if record.get("type") not in ("user", "assistant", "system"):
        if "message" not in record:
            return None

    msg = record.get("message")
    role = record.get("type")
    content: Any = record.get("content")
    model = record.get("model") or ""

    if isinstance(msg, dict):
        role = msg.get("role") or role
        content = msg.get("content", content)
        model = msg.get("model") or model

    if role not in ("user", "assistant", "system"):
        return None

    text, images, tools = _content_to_text(content)
    if not text and not images and not tools:
        return None

    dt = _record_timestamp(record)
    return {
        "role": role,
        "content": text,
        "model": str(model or record.get("version") or ""),
        "images": images,
        "tool_invocations": tools,
        "timestamp": _iso(dt),
    }


def _hook_message(record: dict[str, Any]) -> Optional[dict[str, Any]]:
    attachment = record.get("attachment")
    if not isinstance(attachment, dict):
        return None
    atype = attachment.get("type")
    if atype not in ("hook_success", "hook_error"):
        return None
    hook = attachment.get("hookName") or attachment.get("hookEvent") or "hook"
    content = attachment.get("content") or attachment.get("stdout") or ""
    if not content:
        return None
    dt = _record_timestamp(record)
    return {
        "role": "system",
        "content": _clean_text(f"[{atype} {hook}]\n{content}", limit=40_000),
        "model": "",
        "images": [],
        "tool_invocations": [],
        "timestamp": _iso(dt),
    }


def _first_nonempty_user(messages: list[dict[str, Any]]) -> str:
    for msg in messages:
        if msg.get("role") == "user":
            text = " ".join(str(msg.get("content") or "").split())
            if text:
                return text
    return ""


def _title_from_messages(session_id: str, messages: list[dict[str, Any]]) -> str:
    first = _first_nonempty_user(messages)
    if not first:
        return f"Claude session {session_id[:8]}"
    return first[:90]


def _slug(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "_", text)
    return text[:60] or "claude_session"


def _conversation_graph(
    *,
    session_id: str,
    title: str,
    messages: list[dict[str, Any]],
    created: Optional[datetime],
    updated: Optional[datetime],
) -> dict[str, Any]:
    node_id = f"conv_{session_id.replace('-', '')[:10]}"
    slim_messages = [
        {"role": m.get("role", "user"), "content": m.get("content", "")}
        for m in messages
    ]
    return {
        "id": session_id,
        "name": title,
        "description": "Imported from Claude Code JSONL",
        "schema_version": "1.0",
        "nodes": [
            {
                "id": node_id,
                "type": "conversation.chat",
                "label": title,
                "config": {
                    "model": "claude",
                    "system": "",
                    "temperature": 0.7,
                    "max_tokens": 4096,
                    "body": {"messages": slim_messages},
                },
                "inputs": [],
                "outputs": [],
                "position": {"x": 0.0, "y": 0.0},
            }
        ],
        "edges": [],
        "triggers": [],
        "inputs": [],
        "outputs": [],
        "metadata": {
            "imported_from": "claude_code_jsonl",
            "imported_at": _iso(datetime.now(timezone.utc)),
        },
        "created_at": _iso(created),
        "updated_at": _iso(updated),
    }


def read_claude_session(path: Path) -> Optional[dict[str, Any]]:
    session_id = path.stem
    messages: list[dict[str, Any]] = []
    cwd = ""
    version = ""
    entrypoint = ""
    timestamps: list[datetime] = []
    tools = Counter()
    records = 0
    errors = 0

    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            records += 1
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                errors += 1
                continue
            if isinstance(record, dict):
                session_id = _record_session_id(record, session_id)
                cwd = cwd or str(record.get("cwd") or "")
                version = version or str(record.get("version") or "")
                entrypoint = entrypoint or str(record.get("entrypoint") or "")
                dt = _record_timestamp(record)
                if dt is not None:
                    timestamps.append(dt)

                msg = _message_from_record(record) or _hook_message(record)
                if msg is not None:
                    messages.append(msg)
                    for inv in msg.get("tool_invocations") or []:
                        name = inv.get("tool_name")
                        if name:
                            tools[str(name)] += 1

                attachment = record.get("attachment")
                if isinstance(attachment, dict):
                    if attachment.get("type") == "deferred_tools_delta":
                        for name in attachment.get("addedNames") or []:
                            tools[str(name)] += 0

    if not messages:
        return None

    first = min(timestamps) if timestamps else None
    last = max(timestamps) if timestamps else None
    title = _title_from_messages(session_id, messages)
    return {
        "source_id": path.stem,
        "source_path": str(path),
        "source_bytes": path.stat().st_size,
        "session_id": session_id,
        "title": title,
        "cwd": cwd,
        "version": version,
        "entrypoint": entrypoint,
        "created": first,
        "updated": last,
        "messages": messages,
        "records": records,
        "json_errors": errors,
        "tools": dict(sorted(tools.items())),
    }


def write_archhub_session(session: dict[str, Any], sessions_dir: Path) -> Path:
    sessions_dir.mkdir(parents=True, exist_ok=True)
    source_id = session["source_id"]
    sid = session["session_id"]
    title = session["title"]
    path = sessions_dir / f"claude_{_slug(title)}_{source_id[:8]}{SESSION_EXT}"
    messages = session["messages"]
    data = {
        "id": source_id.replace("-", ""),
        "created_at": _epoch(session["created"]),
        "parameters": [],
        "chain": [],
        "graph": _conversation_graph(
            session_id=source_id,
            title=title,
            messages=messages,
            created=session["created"],
            updated=session["updated"],
        ),
        "_name": f"Claude: {title}",
        "_saved_at": _iso(session["updated"] or session["created"]),
        "_messages": messages,
        "_import": {
            "source": "claude_code_jsonl",
            "source_id": source_id,
            "claude_session_id": sid,
            "source_path": session["source_path"],
            "source_bytes": session["source_bytes"],
            "records": session["records"],
            "json_errors": session["json_errors"],
            "cwd": session["cwd"],
            "version": session["version"],
            "entrypoint": session["entrypoint"],
        },
    }
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str),
                    encoding="utf-8")
    return path


def _summary_text(session: dict[str, Any], session_path: Path) -> str:
    user_prompts: list[str] = []
    assistant_notes: list[str] = []
    for msg in session["messages"]:
        content = " ".join(str(msg.get("content") or "").split())
        if not content:
            continue
        if msg.get("role") == "user" and len(user_prompts) < 28:
            user_prompts.append(content[:500])
        elif msg.get("role") == "assistant" and len(assistant_notes) < 8:
            assistant_notes.append(content[:500])
    tool_names = ", ".join(list(session["tools"].keys())[:40])
    parts = [
        f"Claude session imported for ArchHub: {session['title']}",
        f"cwd: {session['cwd']}",
        f"session_id: {session['session_id']}",
        f"date_range: {_iso(session['created'])} to {_iso(session['updated'])}",
        f"messages: {len(session['messages'])}; source_records: {session['records']}",
        f"archhub_session_file: {session_path}",
    ]
    if tool_names:
        parts.append(f"tools referenced: {tool_names}")
    if user_prompts:
        parts.append("user prompts:\n- " + "\n- ".join(user_prompts))
    if assistant_notes:
        parts.append("assistant notes:\n- " + "\n- ".join(assistant_notes))
    return "\n\n".join(parts)[:24_000]


def write_brain_fragment(
    store: BrainStore,
    session: dict[str, Any],
    session_path: Path,
) -> bool:
    source_id = session["source_id"]
    sid = session["session_id"]
    now = datetime.now(timezone.utc)
    fragment = Fragment(
        id=f"claude-session:{source_id}",
        kind=FragmentKind.TRACE,
        text=_summary_text(session, session_path),
        subject=session["title"],
        predicate="claude_session",
        object=str(session_path),
        scope=Scope.PROJECT,
        visibility=Visibility.PRIVATE,
        owner_user=OWNER_USER,
        project_id=PROJECT_ID,
        confidence=Confidence.EXTRACTED,
        provenance=Provenance(
            contributing_agent="claude_session_importer",
            contributing_user=OWNER_USER,
            session_id=sid,
            accessed_resources=[session["source_path"]],
            created_at=session["created"] or now,
        ),
        valid_from=session["created"],
        last_used_at=session["updated"],
        extra={
            "source": "claude_code_jsonl",
            "source_id": source_id,
            "claude_session_id": sid,
            "source_path": session["source_path"],
            "source_bytes": session["source_bytes"],
            "archhub_session_path": str(session_path),
            "cwd": session["cwd"],
            "version": session["version"],
            "entrypoint": session["entrypoint"],
            "message_count": len(session["messages"]),
            "record_count": session["records"],
            "json_errors": session["json_errors"],
            "tools": session["tools"],
            "imported_at": _iso(now),
        },
    )
    return store.write_fragment(fragment)


def sqlite_backup(db_path: Path, backup_dir: Path) -> Optional[Path]:
    if not db_path.exists():
        return None
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"brain.db.pre-claude-import-{stamp}.bak"
    src = sqlite3.connect(str(db_path))
    dst = sqlite3.connect(str(backup_path))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return backup_path


def iter_sources(project_dirs: Iterable[Path]) -> list[Path]:
    files: list[Path] = []
    for directory in project_dirs:
        if not directory.is_dir():
            continue
        files.extend(sorted(directory.glob("*.jsonl")))
    return sorted(files, key=lambda p: (str(p.parent), p.name))


def import_sessions(
    *,
    project_dirs: list[Path],
    sessions_dir: Path,
    brain_path: Path,
    dry_run: bool = False,
) -> dict[str, Any]:
    sources = iter_sources(project_dirs)
    result: dict[str, Any] = {
        "project_dirs": [str(p) for p in project_dirs],
        "sources_found": len(sources),
        "sessions_parsed": 0,
        "skipped_empty": 0,
        "sessions_dir": str(sessions_dir),
        "brain_path": str(brain_path),
        "dry_run": dry_run,
        "session_files_written": 0,
        "brain_fragments_inserted": 0,
        "brain_fragments_updated": 0,
        "messages_total": 0,
        "source_bytes_total": 0,
        "json_errors_total": 0,
        "backup_path": None,
        "items": [],
    }
    store: Optional[BrainStore] = None
    try:
        if not dry_run:
            backup = sqlite_backup(brain_path, brain_path.parent / "backups")
            result["backup_path"] = str(backup) if backup else None
            store = BrainStore.open(brain_path)

        for src in sources:
            session = read_claude_session(src)
            if session is None:
                result["skipped_empty"] += 1
                continue
            result["sessions_parsed"] += 1
            result["messages_total"] += len(session["messages"])
            result["source_bytes_total"] += session["source_bytes"]
            result["json_errors_total"] += session["json_errors"]

            item = {
                "source_id": session["source_id"],
                "session_id": session["session_id"],
                "title": session["title"],
                "messages": len(session["messages"]),
                "source_path": session["source_path"],
                "brain_fragment_id": f"claude-session:{session['source_id']}",
            }
            if not dry_run:
                session_path = write_archhub_session(session, sessions_dir)
                result["session_files_written"] += 1
                assert store is not None
                inserted = write_brain_fragment(store, session, session_path)
                if inserted:
                    result["brain_fragments_inserted"] += 1
                else:
                    result["brain_fragments_updated"] += 1
                item["archhub_session_path"] = str(session_path)
            result["items"].append(item)
    finally:
        if store is not None:
            store.close()

    if dry_run:
        return result

    report_path = sessions_dir / "claude_import_report.json"
    report_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    result["report_path"] = str(report_path)
    return result


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Import Claude Code JSONL sessions into ArchHub + brain."
    )
    parser.add_argument("--project-dir", action="append", default=None,
                        help="Claude project directory. Repeatable.")
    parser.add_argument("--sessions-dir", default=str(DEFAULT_SESSIONS_DIR))
    parser.add_argument("--brain-db", default=str(default_brain_path()))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    project_dirs = (
        [Path(p) for p in args.project_dir]
        if args.project_dir
        else DEFAULT_PROJECT_DIRS
    )
    result = import_sessions(
        project_dirs=project_dirs,
        sessions_dir=Path(args.sessions_dir),
        brain_path=Path(args.brain_db),
        dry_run=args.dry_run,
    )
    print(json.dumps(result, indent=2, ensure_ascii=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
