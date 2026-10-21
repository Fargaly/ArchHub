"""The graph commit gate: a graph revision exists only for a declared reason.

SPEC.md section 3.3 (founder clarification, 2026-09-22) keeps permission
policy, identity, workflows and their relationships in the graph, and puts
per-write permits and receipts, heartbeat timestamps and audit history in
bounded indexed records. This module is the foundation that holds that line
at the one physical choke point, ``CellStore.commit``:

* every commit to a gated store declares exactly one intent from a closed
  set: a user action, an agent action on admitted work, or an admitted
  migration/install;
* a commit attempted while an operational path is running (heartbeat, lease
  renewal, browser session, runtime ownership, receipt, permit, signal,
  presence, activity) is refused even when an intent is also declared, so an
  operational path can never borrow the intent of the request that carried it;
* unchanged content never commits (the store compares first; see
  ``CellStore.commit``).

Declarations are context-local (``contextvars``). A worker thread does not
inherit them; code that hands admitted work to another thread must carry the
declaration explicitly with ``capture``/``resume``. Idle machinery therefore
has no intent and cannot publish a revision.
"""
from __future__ import annotations

from contextlib import contextmanager
import contextvars
from dataclasses import dataclass
from typing import Callable, Iterator, TypeVar


USER_ACTION = "user_action"
AGENT_WORK = "agent_work"
MIGRATION = "migration"

INTENTS = frozenset({USER_ACTION, AGENT_WORK, MIGRATION})

OPERATIONAL_KINDS = frozenset({
    "heartbeat",
    "lease-renewal",
    "browser-session",
    "runtime-ownership",
    "receipt",
    "permit",
    "signal",
    "presence",
    "activity",
})

_T = TypeVar("_T")


@dataclass(frozen=True, slots=True)
class CommitDeclaration:
    """Why the next graph revision exists, and on whose behalf."""

    intent: str
    actor: str
    reason: str
    work: str | None = None


class _RequestSlot:
    """One authenticated request's admission, filled after authentication."""

    __slots__ = ("declaration",)

    def __init__(self) -> None:
        self.declaration: CommitDeclaration | None = None


_DECLARATION: contextvars.ContextVar[CommitDeclaration | None] = (
    contextvars.ContextVar("archhub_commit_declaration", default=None)
)
_REQUEST: contextvars.ContextVar[_RequestSlot | None] = contextvars.ContextVar(
    "archhub_commit_request", default=None
)
_OPERATIONAL: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "archhub_commit_operational", default=None
)


def _declaration(
    intent: str, actor: str, reason: str, work: str | None
) -> CommitDeclaration:
    if intent not in INTENTS:
        raise ValueError("graph commit intent is not in the closed set")
    for label, value in (("actor", actor), ("reason", reason)):
        if type(value) is not str or not value.strip() or len(value) > 512:
            raise ValueError("graph commit %s is invalid" % label)
    if work is not None and (
        type(work) is not str or not work or len(work) > 512
    ):
        raise ValueError("graph commit work is invalid")
    return CommitDeclaration(intent, actor, reason, work)


@contextmanager
def declare(
    intent: str, *, actor: str, reason: str, work: str | None = None
) -> Iterator[CommitDeclaration]:
    """Admit graph commits in this context for one closed-set intent."""
    declaration = _declaration(intent, actor, reason, work)
    reset = _DECLARATION.set(declaration)
    try:
        yield declaration
    finally:
        _DECLARATION.reset(reset)


@contextmanager
def request_scope() -> Iterator[None]:
    """Open one request whose admission is decided after authentication."""
    reset = _REQUEST.set(_RequestSlot())
    try:
        yield
    finally:
        _REQUEST.reset(reset)


def admit(
    intent: str, *, actor: str, reason: str, work: str | None = None
) -> bool:
    """Record the authenticated intent of the current request scope.

    Outside a request scope this does nothing and returns False; it never
    widens a context that was not opened as one request.
    """
    slot = _REQUEST.get()
    if slot is None:
        return False
    slot.declaration = _declaration(intent, actor, reason, work)
    return True


_REFUSALS: contextvars.ContextVar[list | None] = contextvars.ContextVar(
    "archhub_commit_operational_refusals", default=None
)


@contextmanager
def recording_refusals() -> Iterator[list]:
    """Collect every commit refused inside an operational path here, even one
    a caller catches as InvalidCell: a read that wanted to publish must know."""
    outer = _REFUSALS.get()
    refused: list = []
    reset = _REFUSALS.set(refused)
    try:
        yield refused
    finally:
        _REFUSALS.reset(reset)
        # A nested recorder never hides a refusal from the one around it.
        if outer is not None:
            outer.extend(refused)


@contextmanager
def operational(kind: str) -> Iterator[None]:
    """Run an operational path; any graph commit inside it is refused."""
    if kind not in OPERATIONAL_KINDS:
        raise ValueError("operational commit kind is not in the closed set")
    reset = _OPERATIONAL.set(kind)
    try:
        yield
    finally:
        _OPERATIONAL.reset(reset)


def current_declaration() -> CommitDeclaration | None:
    declaration = _DECLARATION.get()
    if declaration is not None:
        return declaration
    slot = _REQUEST.get()
    return None if slot is None else slot.declaration


def current_operational() -> str | None:
    return _OPERATIONAL.get()


def capture() -> CommitDeclaration | None:
    """The declaration a hand-off to another thread must carry."""
    return current_declaration()


@contextmanager
def resume(declaration: CommitDeclaration | None) -> Iterator[None]:
    """Continue admitted work on another thread, or remain undeclared."""
    if declaration is None:
        yield
        return
    if type(declaration) is not CommitDeclaration:
        raise TypeError("carried graph commit declaration is invalid")
    with declare(
        declaration.intent,
        actor=declaration.actor,
        reason=declaration.reason,
        work=declaration.work,
    ):
        yield


def carried(function: Callable[..., _T]) -> Callable[..., _T]:
    """Bind ``function`` to the caller's declaration for a worker thread."""
    declaration = capture()

    def run(*args, **kwargs):
        with resume(declaration):
            return function(*args, **kwargs)

    return run


def refusal(requires_declared_intent: bool) -> str | None:
    """Why a commit must be refused now, or None when it is admitted."""
    kind = _OPERATIONAL.get()
    if kind is not None:
        refused = _REFUSALS.get()
        if refused is not None:
            refused.append(kind)
        return (
            "graph commit refused: %s is operational; SPEC 3.3 keeps it in "
            "bounded indexed records, not graph revisions" % kind
        )
    if requires_declared_intent and current_declaration() is None:
        return (
            "graph commit refused: no declared intent (user action, agent "
            "action on admitted Work, or admitted migration/install)"
        )
    return None


__all__ = [
    "AGENT_WORK",
    "CommitDeclaration",
    "INTENTS",
    "MIGRATION",
    "OPERATIONAL_KINDS",
    "USER_ACTION",
    "admit",
    "capture",
    "carried",
    "current_declaration",
    "current_operational",
    "declare",
    "operational",
    "refusal",
    "request_scope",
    "resume",
]