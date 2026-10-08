"""BABOOM's words: a few plain sentences composed from the admitted briefing.

Presentation only. The graph decides what matters (the directive and the
context lens); this module decides how it is said. It is deterministic
templates, no model call, and it never reads a store: every number and name
in a sentence comes from the briefing it was handed.

Rules (BABOOM-DESIGN-BRIEF section 3): one to three short sentences; what
needs the founder first, then what is running, then one offer; no internal
counters (Workshop entries, brain facts); no identifiers; names in plain
words; every sentence closed.
"""
from __future__ import annotations

import re
from typing import Mapping

_WORDS = ("no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine")

# Runtime and host names as the founder says them. Anything else is shown
# with its first letter raised, or dropped when it looks like an identifier.
_NAMES = {
    "claude": "Claude", "codex": "Codex", "gemini": "Gemini", "gpt": "GPT",
    "opencode": "OpenCode", "antigravity": "Antigravity", "ping": "Ping",
    "dropbox": "Dropbox", "revit": "Revit", "autocad": "AutoCAD", "acad": "AutoCAD",
    "3dsmax": "3ds Max", "max": "3ds Max", "rhino": "Rhino", "blender": "Blender",
    "outlook": "Outlook", "notion": "Notion", "office": "Office",
}
# Raised inside an app-composed sentence only where the word cannot be
# anything else ("max" or "office" in a sentence stay as written).
_RAISED_IN_SENTENCES = {
    "claude", "codex", "gemini", "opencode", "antigravity",
    "dropbox", "revit", "autocad", "rhino", "blender", "outlook",
}
_IDENTIFIER = re.compile(
    r"(?i)^(?:sha256:)?(?:[a-z]{1,4}-)?(?=[0-9a-f-]*\d)[0-9a-f-]{7,}$"
)
_TRAILING = {"for", "to", "of", "in", "on", "with", "and", "the", "a", "an", "by", "from", "at", "or"}
_MORE = re.compile(r"\s*\(\+\d+ more\)")
_AGENT_LINE = re.compile(r"^(?P<agent>.+?) is on: (?P<title>.+)$")
_SENTENCE_END = re.compile(r"(?<=[.?!])\s+(?=[A-Z0-9])")
_TITLE_LIMIT = 48


def sentences_of(text: str) -> list[str]:
    """Split composed speech into its sentences (for courts and layout)."""
    return [part for part in _SENTENCE_END.split(text.strip()) if part]


def plain_count(value: int, capital: bool = False) -> str:
    """'one', 'two' ... 'nine', then digits with thousands separators."""
    word = _WORDS[value] if 0 <= value < 10 else f"{value:,}"
    return word[:1].upper() + word[1:] if capital else word


def _counted(value: int, singular: str, plural: str, capital: bool = True) -> str:
    return "%s %s" % (plain_count(value, capital), singular if value == 1 else plural)


def _is_identifier(word: str) -> bool:
    bare = word.strip(".,;:()[]'\"")
    return ":" in bare or bool(_IDENTIFIER.match(bare))


def plain_name(raw: object) -> str:
    """A runtime or host name in plain words, or '' when it is only an id."""
    text = str(raw or "").rsplit(":", 1)[-1].strip()
    if not text or _is_identifier(text):
        return ""
    known = _NAMES.get(text.casefold())
    if known:
        return known
    words = [w for w in re.split(r"[-_\s]+", text) if w]
    return " ".join(_NAMES.get(w.casefold(), w[:1].upper() + w[1:]) for w in words)


def _names_said(text: str) -> str:
    """Raise known runtime and host names inside an app-composed sentence."""
    return re.sub(
        r"\b[\w]+\b",
        lambda m: _NAMES[m.group(0)] if m.group(0) in _RAISED_IN_SENTENCES else m.group(0),
        text,
    )


def _clause(text: str) -> str:
    """Strip an app sentence to one clause: no '(+N more)', no end mark."""
    text = _MORE.sub("", " ".join(str(text or "").split()))
    text = _SENTENCE_END.split(text)[0]
    return _names_said(text.rstrip(" .;:!?"))


def plain_title(raw: object) -> str:
    """A Work title as a short phrase: first clause, no ids, lower first word."""
    text = " ".join(str(raw or "").split())
    if not text or text.startswith("["):
        return ""
    text = re.split(r"(?<=[.?!])\s|;\s|\s[\u2014-]\s", text)[0]
    head, comma, _rest = text.partition(", ")
    if comma and len(head.split()) >= 3:
        text = head
    words = [w for w in text.split() if not _is_identifier(w)]
    while words and len(" ".join(words)) > _TITLE_LIMIT:
        words.pop()
    while words and words[-1].strip(".,;:").casefold() in _TRAILING:
        words.pop()
    if not words:
        return ""
    first = words[0]
    if first[1:] == first[1:].lower() and first.casefold() not in _NAMES:
        words[0] = first[:1].lower() + first[1:]
    return " ".join(words).rstrip(" .,;:!?")


def _join(names: list[str]) -> str:
    if len(names) > 3:
        names = names[:3] + ["%s others" % plain_count(len(names) - 3)]
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " and " + names[-1]


def _greeting(hour: int | None) -> str | None:
    if hour is None:
        return None
    if 5 <= hour < 12:
        return "Morning."
    if 12 <= hour < 18:
        return "Afternoon."
    return "Evening."


def _mapping(value: object) -> Mapping:
    return value if isinstance(value, Mapping) else {}


def _count(value: object) -> int:
    if isinstance(value, (list, tuple)):
        return len(value)
    return value if type(value) is int and value > 0 else 0


def _agent_sentence(agent: object, title: object) -> str | None:
    phrase = plain_title(title)
    if not phrase:
        return None
    if str(agent or "").rsplit(":", 1)[-1].strip().casefold() == "baboom":
        return "I'm working on: %s." % phrase
    return "%s is working on: %s." % (plain_name(agent) or "An agent", phrase)


def _refuse_malformed(briefing: object) -> None:
    """The admitted steward-briefing shape; anything else is not a report."""
    if not isinstance(briefing, Mapping):
        raise ValueError("BABOOM native report is invalid")
    work = briefing.get("governed_work")
    workshop = briefing.get("workshop")
    attention = briefing.get("attention")
    if not (
        isinstance(work, Mapping)
        and isinstance(workshop, Mapping)
        and isinstance(attention, Mapping)
        and type(work.get("active")) is int
        and type(workshop.get("count")) is int
        and type(attention.get("blocked_obligations")) is int
    ):
        raise ValueError("BABOOM native report is invalid")
    items = work.get("items", ())
    if not isinstance(items, (list, tuple)) or not all(isinstance(i, Mapping) for i in items):
        raise ValueError("BABOOM native report is invalid")


def compose_baboom_speech(
    briefing: Mapping,
    directive: Mapping | None = None,
    *,
    hour: int | None = None,
) -> str:
    """Compose one to three plain sentences from one admitted briefing.

    ``briefing`` is the steward-briefing ``data`` (context lens, governed
    Work, Workshop, attention). ``directive`` is the graph's own directive;
    where it already composed the sentence for the chosen state, that
    sentence is reused and only cleaned. ``hour`` adds a greeting.

    A malformed briefing is refused, never spoken as a calm empty sentence.
    """
    _refuse_malformed(briefing)
    data = briefing
    directive = _mapping(directive)
    lens = _mapping(data.get("context"))
    governed = _mapping(data.get("governed_work"))
    action = str(directive.get("message") and directive.get("action") or "")
    message = str(directive.get("message") or "")

    items = list(governed.get("items", ()))
    work = _mapping(lens.get("work"))

    def work_count(state: str) -> int:
        if state in work:
            return _count(work.get(state))
        return sum(1 for item in items if str(item.get("state") or "").casefold() == state)

    active = _count(governed.get("active"))
    stale = _count(governed.get("stale_claims"))
    blocked = work_count("blocked")
    review = work_count("review")
    claimable = work_count("open")
    holds = _count(_mapping(lens.get("attention")).get("blocked_obligations")) or _count(
        _mapping(data.get("attention")).get("blocked_obligations"))
    brain = _mapping(lens.get("brain"))
    agents = _mapping(lens.get("agents"))
    canvas = _mapping(lens.get("canvas"))
    update = _mapping(lens.get("update"))
    down = [n for n in (plain_name(h) for h in (_mapping(lens.get("hosts")).get("down") or ())) if n]

    # What needs him now, most serious first; each carries one offer.
    severe = None
    if blocked:
        severe = "%s stuck and %s your eyes \u2014 want to open %s?" % (
            _counted(blocked, "job is", "jobs are"),
            "needs" if blocked == 1 else "need", "it" if blocked == 1 else "them")
    elif brain.get("ok") is False:
        said = _clause(message) if action == "brain-health" else "The brain is not answering"
        severe = said + " \u2014 want me to check on it?"
    else:
        warning = _clause(message) if action == "status" else ""
        if not warning:
            gone = [n for n in (plain_name(r) for r in (agents.get("gone") or ())) if n]
            failed = [str(n)[:30] for n in (canvas.get("failed") or ())][:2]
            refused = [str(n)[:30] for n in (canvas.get("refused") or ())][:2]
            if gone:
                warning = "A %s session stopped answering" % gone[0]
            elif failed:
                warning = "The last run failed in %s" % _join(failed)
            elif refused:
                warning = "%s refused in the last run" % _join(refused)
        if warning:
            severe = warning[:1].upper() + warning[1:] + " \u2014 want the details?"
        elif holds:
            severe = "%s your attention \u2014 want to look now?" % _counted(
                holds, "governance hold needs", "governance holds need")

    stale_status = "%s held by agents that stopped." % _counted(
        stale, "old claim is", "old claims are") if stale else None
    if not active:
        status = None
    elif severe and blocked:
        others = active - blocked
        status = ("%s %s running." % (_counted(others, "other", "others"), "is" if others == 1 else "are")
                  if others > 0 else None)
    elif severe:
        status = "%s running." % _counted(active, "job is", "jobs are")
    else:
        status = "%s running and nothing is stuck." % _counted(active, "job is", "jobs are")

    # Otherwise: the one thing that waits on him, else what the graph chose.
    follow = None
    if not severe:
        if down:
            follow = "%s %s offline \u2014 want me to check %s?" % (
                _join(down), "is" if len(down) == 1 else "are", "it" if len(down) == 1 else "them")
        elif review:
            follow = "%s for your review \u2014 want to open %s?" % (
                _counted(review, "job is waiting", "jobs are waiting"), "it" if review == 1 else "them")
        elif update.get("build_id"):
            follow = "A new build is ready \u2014 want me to restart now?"
        else:
            agent_line = None
            parsed = _AGENT_LINE.match(_MORE.sub("", message)) if action == "show-claimed-work-plan" else None
            if parsed:
                agent_line = _agent_sentence(parsed.group("agent"), parsed.group("title"))
            if agent_line is None:
                working = [r for r in (agents.get("working") or ()) if isinstance(r, Mapping)]
                working.sort(key=lambda r: str(r.get("agent") or "").casefold() == "baboom")
                for row in working:
                    agent_line = _agent_sentence(row.get("agent"), row.get("title"))
                    if agent_line:
                        break
            if agent_line and action != "claim-next-governed-work":
                follow = agent_line
            elif claimable:
                follow = "%s ready to claim \u2014 want me to take %s?" % (
                    _counted(claimable, "job is", "jobs are"),
                    "it" if claimable == 1 else "the next one")
            else:
                follow = agent_line

    said = [s for s in (_greeting(hour), severe, status, stale_status) if s] if severe else [
        s for s in (_greeting(hour), status, stale_status, follow) if s]
    if len(said) == (1 if hour is not None else 0):
        said.append("Nothing needs you right now.")
    return " ".join(said)


__all__ = [
    "compose_baboom_speech",
    "plain_count",
    "plain_name",
    "plain_title",
    "sentences_of",
]
