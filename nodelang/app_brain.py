"""The application's own Brain: graph-held memory the product reads and edits.

The personal-brain daemon on 127.0.0.1:8473 is retired (founder 2026-09-15/16;
WORKSPACE-STANDARD :490 one Brain per instance). Its store was ported into this
graph (``brain_store_port``). The tool names the application used against the
daemon are served here from ``cell_brain_memory`` and ``cell_brain_skills`` in
the running application's graph:

  brain.health       {ok, facts, skills, owner_user}
  brain.context      {facts:[{id, text, kind}]} best lexical matches for a prompt
  brain.list_facts   {ok, total, held, offset, limit, folders:[{id, label, count, facts}]}
  brain.delete_fact  forget one fact (kept, recoverable, in the graph's history)
  brain.edit_fact    replace one fact's text in place
  brain.write        add facts ({ops:[{op:"add", fragment:{id, kind, text}}]}); never classifies
  brain.publish      share ONE fact with the Community Brain, the owner's deliberate act
                     (published skill); refused for anything naming the client area

Nothing is dialed. When no application graph is bound in this process, every
call raises ``BrainUnavailable`` -- never a network fallback.
"""
from __future__ import annotations

import re
import threading
import time
import unicodedata
import urllib.parse
from typing import Any, Mapping

from . import commit_intent
from .cell_brain_governance import (
    GRANT, classify, firms_of, may_release, record_consent, solo_firm_root,
)
from .cell_brain_memory import MEMORY_KINDS, _memories, forget, recall_by_owner, remember
from .cell_brain_skills import recall_skills
from .cell_session_state import open_session
from .universal_cell import NULL_CELL_ID, Cell

SESSION_ROOT = "app:sessions:application-brain"
ORIGIN = "archhub-application"
_FOLDERS = (("user", "User", ("fact",)), ("feedback", "Feedback", ("mandate", "practice")),
            ("projects", "Projects", ("document",)), ("reference", "Reference", ("setup", "spatial", "hook")))
_WORD = re.compile(r"[a-z0-9]{3,}")
# A publish is refused when the fact names the client area, the personal area,
# a client folder that exists in this workspace's 20.CLIENTS, or a project code
# (P-603, P603), however it is spelled: separators, full-width forms and URL
# encoding are undone first. Client names written out in words cannot all be
# caught; that is why publishing is a deliberate act on one fact at a time.
_AREAS = ("20.clients", "20clients", "60.personal", "60personal")
_PROJECT_CODE = re.compile(r"(?<![a-z0-9])p[-_]?\d{3,4}(?![a-z0-9])")
_CLIENTS_DIR = "20.CLIENTS"
PUBLISHED_CLASS, PUBLISHED_STRATUM = "published-skills", "category"
_LOCK = threading.RLock()
_BOUND: dict[str, Any] = {}


class BrainUnavailable(RuntimeError):
    """No application graph is bound in this process, or the tool is not provided."""


def bind(store, registry) -> None:
    """The running application names its graph; the last bound application answers."""
    with _LOCK:
        _BOUND.update(store=store, owner=registry.authorization.subject_root,
                      protocol=registry.assembly_protocol)


def unbind(store=None) -> None:
    with _LOCK:
        if store is None or _BOUND.get("store") is store:
            _BOUND.clear()


def _bound():
    with _LOCK:
        if not _BOUND:
            raise BrainUnavailable("no application Brain is bound in this process")
        return _BOUND["store"], _BOUND["owner"], _BOUND["protocol"]


def _now_ms() -> int:
    return int(time.time() * 1000)


def _live(snapshot, owner):
    return _memories(snapshot, owner)


def health() -> dict:
    store, owner, protocol = _bound()
    snapshot = store.snapshot()
    try:
        skills = len(recall_skills(snapshot, protocol, "", released_only=False))
    except Exception:  # noqa: BLE001 -- a malformed skill never hides the fact count
        skills = None
    return {"ok": True, "facts": len(_live(snapshot, owner)), "skills": skills, "owner_user": owner}


def context(prompt: str, *, limit: int = 8) -> dict:
    store, owner, _protocol = _bound()
    wanted = set(_WORD.findall(str(prompt or "").lower()))
    if not wanted:
        return {"facts": []}
    scored = []
    for memory in _live(store.snapshot(), owner):
        overlap = len(wanted & set(_WORD.findall(memory.text.lower())))
        if overlap:
            scored.append((-overlap, -memory.text_clock, memory))
    scored.sort(key=lambda row: row[:2])
    return {"facts": [{"id": m.fragment_id, "text": m.text, "kind": m.kind}
                      for _a, _b, m in scored[:max(1, int(limit))]]}


def list_facts(*, limit: int = 500, offset: int = 0) -> dict:
    store, owner, _protocol = _bound()
    held = _live(store.snapshot(), owner)
    page = held[max(0, int(offset)):max(0, int(offset)) + max(1, int(limit))]
    folders = []
    placed = set()
    for key, label, kinds in _FOLDERS:
        facts = [m for m in page if m.kind in kinds]
        placed.update(m.fragment_id for m in facts)
        folders.append({"id": key, "label": label, "count": len(facts), "facts": [_record(m, key) for m in facts]})
    rest = [m for m in page if m.fragment_id not in placed]
    if rest:
        folders.append({"id": "other", "label": "Other", "count": len(rest), "facts": [_record(m, "other") for m in rest]})
    return {"ok": True, "total": len(page), "held": len(held), "offset": int(offset),
            "limit": int(limit), "folders": folders}


def _record(memory, folder):
    first = memory.text.strip().splitlines()[0] if memory.text.strip() else memory.fragment_id
    return {"id": memory.fragment_id, "name": first[:80], "desc": first[:160], "body": memory.text,
            "type": folder, "kind": memory.kind, "scope": "user"}


def _write(reason, operation, actor=None):
    """One governed write: a declared user action attributed to the caller."""
    store, owner, _protocol = _bound()
    with commit_intent.declare(commit_intent.USER_ACTION, actor=actor or owner, reason=reason):
        if SESSION_ROOT not in store.snapshot().cells:
            open_session(store, session_root=SESSION_ROOT, owner_root=owner)
        return operation(store, owner)


def delete_fact(fragment_id: str, *, actor=None) -> dict:
    fragment_id = str(fragment_id or "").strip()
    if not fragment_id:
        return {"ok": False, "error": "missing fragment_id"}

    def run(store, owner):
        existing = recall_by_owner(store.snapshot(), owner, fragment_id)
        if existing is None:
            return {"ok": False, "error": "no such fact"}
        clock = max(_now_ms(), existing.text_clock + 1, existing.state_clock + 1)
        forget(store, session_root=SESSION_ROOT, fragment_id=fragment_id, origin=ORIGIN, clock=clock)
        return {"ok": True, "id": fragment_id}
    return _write("forget one Brain fact", run, actor)


def edit_fact(fragment_id: str, text: str, *, actor=None) -> dict:
    fragment_id, text = str(fragment_id or "").strip(), str(text or "").strip()
    if not fragment_id or not text:
        return {"ok": False, "error": "need a fact id and text", "edited": False}

    def run(store, owner):
        existing = recall_by_owner(store.snapshot(), owner, fragment_id)
        if existing is None:
            return {"ok": False, "error": "no such fact", "edited": False}
        clock = max(_now_ms(), existing.text_clock + 1, existing.state_clock + 1)
        remember(store, session_root=SESSION_ROOT, fragment_id=fragment_id, text=text,
                 kind=existing.kind, origin=ORIGIN, clock=clock, confidence=existing.confidence)
        return {"ok": True, "id": fragment_id, "edited": True}
    return _write("edit one Brain fact", run, actor)


def _decoded(text):
    text = str(text)
    for _ in range(8):  # %252E, %25252E ...: unquote until nothing changes
        once = urllib.parse.unquote(text)
        if once == text:
            break
        text = once
    return unicodedata.normalize("NFKC", text).casefold()


def _client_folder_forms():
    """The client folders of this workspace, by name only, in every spelling a fact
    might use: 22.BBC4 -> "22.bbc4", "22bbc4", "bbc4". None on a machine without
    the client area. Names shorter than three characters are not matched alone."""
    from .resource_probe import _workspace_root
    try:
        names = [p.name for p in (_workspace_root() / _CLIENTS_DIR).iterdir() if p.is_dir()]
    except OSError:
        return ()
    forms = set()
    for name in names:
        dotted = re.sub(r"[^a-z0-9]+", ".", _decoded(name)).strip(".")
        bare = re.sub(r"^\d+\.", "", dotted)
        for form in (dotted, dotted.replace(".", ""), bare, bare.replace(".", "")):
            if len(form.replace(".", "")) >= 3:
                forms.add(form)
    return tuple(sorted(forms))


def names_the_client_area(*texts):
    forms = _AREAS + _client_folder_forms()
    for text in texts:
        decoded = _decoded(text)
        dotted = "." + re.sub(r"[^a-z0-9]+", ".", decoded).strip(".") + "."
        if any("." + form + "." in dotted for form in forms) or _PROJECT_CODE.search(decoded):
            return True
    return False


def publish(fragment_id: str, *, actor=None) -> dict:
    """Share one of the owner's facts with the Community Brain, as a published skill.

    Default-deny: nothing is ever shared by writing it. A solo account decides
    p2f and f2c itself and the cloud's founder review decides what members may
    pull; inside a firm the owner records p2f (and f2c when they own the firm)
    and the fact waits for that firm's gates.
    """
    fragment_id = str(fragment_id or "").strip()
    if not fragment_id:
        return {"ok": False, "error": "missing fragment_id"}

    def run(store, owner):
        existing = recall_by_owner(store.snapshot(), owner, fragment_id)
        if existing is None:
            return {"ok": False, "error": "no such fact"}
        if names_the_client_area(existing.text, fragment_id):
            return {"ok": False, "error": "this fact names the client area; it stays on this machine"}
        clock = max(_now_ms(), existing.text_clock + 1, existing.state_clock + 1)
        classify(store, session_root=SESSION_ROOT, fragment_id=fragment_id,
                 data_class=PUBLISHED_CLASS, stratum=PUBLISHED_STRATUM, origin=ORIGIN, clock=clock)
        firms = firms_of(store.snapshot(), owner)
        if not firms:
            firm_root = solo_firm_root(owner)
            snapshot = store.snapshot()
            if firm_root not in snapshot.cells:
                store.commit(snapshot.revision, create=(
                    Cell(firm_root, NULL_CELL_ID, NULL_CELL_ID, b"solo firm"),))
            gates = ("p2f", "f2c")
        else:
            firm = firms[0]
            firm_root = firm.root_id
            gates = ("p2f", "f2c") if firm.owner_root == owner else ("p2f",)
        for step, gate in enumerate(gates):
            record_consent(store, session_root=SESSION_ROOT, fragment_id=fragment_id, gate=gate,
                           decision=GRANT, firm_root=firm_root, clock=clock + 1 + step,
                           reason="published to the ArchHub community by its owner")
        released = may_release(store.snapshot(), session_root=SESSION_ROOT,
                               fragment_id=fragment_id, to_lake="community", firm_root=firm_root)
        return {"ok": True, "id": fragment_id, "published": released.allowed,
                "waiting": None if released.allowed else released.reason}
    return _write("publish one Brain fact to the community", run, actor)


def write(ops, *, actor=None) -> dict:
    added = [op.get("fragment") for op in (ops or []) if isinstance(op, Mapping)
             and str(op.get("op") or "").lower() == "add" and isinstance(op.get("fragment"), Mapping)]

    def run(store, _owner):
        written = 0
        for fragment in added:
            kind = str(fragment.get("kind") or "fact")
            remember(store, session_root=SESSION_ROOT, fragment_id=str(fragment["id"]),
                     text=str(fragment["text"]), kind=kind if kind in MEMORY_KINDS else "fact",
                     origin=ORIGIN, clock=_now_ms(), confidence="extracted")
            written += 1
        return {"ok": True, "written": written}
    return _write("remember Brain facts", run, actor)


def call(tool: str, arguments: Mapping[str, Any], *, actor=None):
    """One tool of the retired daemon's surface, answered from the graph.

    ``actor`` is the caller's subject; every write commit is attributed to it.
    """
    arguments = dict(arguments or {})
    if tool == "brain.health":
        return health()
    if tool == "brain.context":
        return context(arguments.get("prompt", ""), limit=arguments.get("limit", 8))
    if tool == "brain.list_facts":
        return list_facts(limit=arguments.get("limit", 500), offset=arguments.get("offset", 0))
    if tool == "brain.delete_fact":
        return delete_fact(arguments.get("fragment_id", ""), actor=actor)
    if tool == "brain.edit_fact":
        return edit_fact(arguments.get("fragment_id", ""), arguments.get("text", ""), actor=actor)
    if tool == "brain.write":
        return write(arguments.get("ops"), actor=actor)
    if tool == "brain.publish":
        return publish(arguments.get("fragment_id", ""), actor=actor)
    raise BrainUnavailable("the application Brain does not provide %s" % tool)


__all__ = ["BrainUnavailable", "bind", "call", "context", "delete_fact", "edit_fact",
           "health", "list_facts", "names_the_client_area", "publish", "unbind", "write"]