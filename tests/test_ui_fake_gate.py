"""Static fake-gate for the React UI (MAKE-IT-REAL plan §7, item G).

WHY THIS EXISTS
---------------
The founder's recurring complaint: "empty shells and clicks that don't do
real work." The root cause the repo-map found (2026-05-28 §8): the *entire*
React UI + JS↔Qt boundary was "tested" by grepping `studio-lm.jsx` as a
string for the *presence* of a symbol. A scaffold with a fake number, or a
button whose `onClick` does nothing, passes a presence-grep. So a naked shell
shipped as "done" and nothing caught it.

This gate inverts that. Instead of asserting a symbol *exists*, it scans the
JSX for the two fake-classes the founder kept pointing at and FAILS when it
finds one:

  (A) INTERACTIVE DEAD-ENDS — an `onClick`/`onKeyDown` handler whose body
      reaches NO real effect: no bridge call, no event dispatch, no state
      mutation, no callback-prop invocation, no navigation. A button that is
      "for show." (e.g. the old AIBody Send / OutputBody save / HealthStripItem
      rows that dispatched an event nothing listened to.)

  (B) FABRICATED CHROME STRINGS — a hardcoded telemetry/date literal baked
      into the UI chrome instead of derived from real data. (e.g. the old
      ServerStrip `· 4.2k tok · $0.024 · server :7300` and the ConversationRail
      `WEDNESDAY · MAY 13` divider — cosmetic fabrications that lied about
      real usage / dates.)

CALIBRATION CONTRACT (proven in CI, both directions):
  * The CURRENTLY-WIRED studio-lm.jsx must PASS every assertion here.
  * A deliberately re-introduced fake (naked onClick, or a fabricated
    `4.2k tok` / `WEDNESDAY · MAY 13` literal) must FAIL — see
    `test_fake_gate_self_check.py`, which feeds this same scanner an injected
    shell and asserts the scanner flags it.

The scanner functions (`scan_dead_end_handlers`, `scan_fabricated_strings`)
are importable so the self-check can run them over a mutated source string
WITHOUT touching the real file — that is the "prove the fake FAILS" half of
the founder's two-run requirement.

This is a STATIC gate: it parses source text, runs headless, ships in CI. The
live-click proof (a real CDP click producing a real DOM/state change) lives in
`test_ui_cdp_smoke.py`. Two layers: this one fails fast on a shell in source;
that one proves the wire reaches the running backend.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


JSX = Path(__file__).resolve().parents[1] / "app" / "web_ui" / "studio-lm.jsx"


def _src() -> str:
    return JSX.read_text(encoding="utf-8")


# ───────────────────────────────────────────────────────────────────────────
# Handler-body extraction
# ───────────────────────────────────────────────────────────────────────────
# A handler "does real work" when, after stripping comments, its body contains
# any of:
#   * a function CALL          — `foo(x)` / `sendReply()` / `fire('regen')`
#   * an assignment / mutation — `x = …`, `n.messages = …`, `+=`
#   * an await / new           — `await …`, `new …`
# A naked shell has NONE of these: it is empty, a no-op literal, or comment-only
# (the founder's "buttons are for show"). This is intentionally permissive on
# the ALLOW side — a handler that calls *any* named function delegates to logic
# defined elsewhere, and a naked shell never bothers to. The precise lie the
# founder hit (a handler that dispatches an event NOTHING listens to) is caught
# separately by the dead-dispatch scan below, which is stricter than "does it
# call a function."

# A call expression: an identifier/member chain immediately followed by `(`.
# Matches `foo(`, `obj.method(`, `setX(`, but NOT a bare `if (` / `for (` /
# `while (` / `switch (` / `return (` (control-flow, not an effect by itself).
_CALL_RE = re.compile(r"(?<![.\w])(?!(?:if|for|while|switch|return|catch)\b)"
                      r"[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*\s*\(")
# An assignment / compound-assignment / mutation (not `==`/`===`/`<=`/`>=`).
_ASSIGN_RE = re.compile(r"(?<![=!<>])=(?!=)|[-+*/]=|\+\+|--")
_AWAIT_NEW_RE = re.compile(r"\b(?:await|new)\b")

# An onClick whose ENTIRE body is one of these is a naked shell.
_NOOP_BODIES = (
    "", "{}", "()", "null", "undefined", "void 0", ";",
    "() => {}", "() => null", "()=>{}", "()=>null",
    "function(){}", "function() {}", "return", "return;",
)


def _strip_comments(body: str) -> str:
    """Blank out // line comments and /* */ block comments so a comment-only
    handler body collapses to empty (a comment is not a real effect) and audit
    prose describing an old fake is never matched. LENGTH- AND NEWLINE-
    PRESERVING (replaces comment chars with spaces, keeps \\n) so byte offsets
    and line numbers stay valid for callers that report a location."""
    def _blank(m: re.Match) -> str:
        return "".join("\n" if ch == "\n" else " " for ch in m.group(0))
    body = re.sub(r"/\*.*?\*/", _blank, body, flags=re.DOTALL)
    body = re.sub(r"//[^\n]*", _blank, body)
    return body


def _balanced_slice(src: str, open_idx: int, open_ch: str, close_ch: str) -> tuple[str, int]:
    """Return (inner, end_idx) for the balanced region starting at the opener
    located at open_idx. Naively brace-counts; good enough for handler bodies
    in this codebase (no template-literal braces inside the handlers we scan).
    """
    depth = 0
    i = open_idx
    n = len(src)
    while i < n:
        c = src[i]
        if c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
            if depth == 0:
                return src[open_idx + 1:i], i
        i += 1
    return src[open_idx + 1:], n


def _extract_attr_handlers(src: str, attr: str) -> list[tuple[int, str]]:
    """Find every `attr={ ... }` occurrence and return (char_offset, raw_body).

    raw_body is the JSX expression inside the braces — an arrow function, a
    bare identifier (`onClick={submit}`), or a call. We balance braces so
    nested object/lambda braces are captured whole.
    """
    out: list[tuple[int, str]] = []
    for m in re.finditer(re.escape(attr) + r"\s*=\s*\{", src):
        brace_idx = src.index("{", m.start())
        inner, _ = _balanced_slice(src, brace_idx, "{", "}")
        out.append((m.start(), inner))
    return out


def _handler_does_work(raw_body: str) -> bool:
    """True if this handler body does real work.

    Resolution order:
      1. Bare identifier / member expression (`onClick={submit}` /
         `onClick={onClose}` / `onClick={fire('regen')}`): real — it delegates
         to a named function/prop/curried-handler defined elsewhere. A naked
         shell never bothers to name a handler.
      2. Inline body: strip comments. If what remains is empty or a no-op
         literal → does NO work. Otherwise it does work iff it contains a
         function call, an assignment/mutation, or an await/new.
    """
    body = raw_body.strip()

    # (1) Bare identifier / member / single call with no arrow — delegates.
    #     `submit`, `onClose`, `fire('regen')`, `obj.method` → real.
    #     (An arrow `() => …` is NOT bare; it falls through to (2).)
    if "=>" not in body and "{" not in body:
        if re.fullmatch(r"[A-Za-z_$][\w$.]*", body):
            return True
        if _CALL_RE.search(body):      # `fire('regen')`, `pick(x)`
            return True

    stripped = _strip_comments(body).strip()

    # Collapse an arrow wrapper to its body for the no-op check:
    # `() => {}` / `e => {}` / `(e) => { /* c */ }` → inner.
    arrow = re.match(r"^\(?[^)]*\)?\s*=>\s*(.*)$", stripped, flags=re.DOTALL)
    inner = arrow.group(1).strip() if arrow else stripped
    # Unwrap a single brace block.
    if inner.startswith("{") and inner.endswith("}"):
        inner = inner[1:-1].strip()

    if inner in _NOOP_BODIES or inner == "":
        return False

    # Real work == a call, an assignment/mutation, or await/new anywhere.
    return bool(
        _CALL_RE.search(inner)
        or _ASSIGN_RE.search(inner)
        or _AWAIT_NEW_RE.search(inner)
    )


def scan_dead_end_handlers(src: str) -> list[tuple[int, str]]:
    """PUBLIC: return [(offset, body)] for every interactive handler that
    does NO real work (empty / no-op / comment-only). Empty list == the UI has
    no naked shells.

    Importable so the self-check can run it over an injected-shell string.
    """
    dead: list[tuple[int, str]] = []
    for attr in ("onClick", "onKeyDown", "onSubmit"):
        for offset, body in _extract_attr_handlers(src, attr):
            if not _handler_does_work(body):
                dead.append((offset, body))
    return dead


# ── Dead-dispatch: a CustomEvent fired that NOTHING listens to ────────────
# This is the EXACT mechanism that bit the founder: HealthStripItem dispatched
# `lm-focus-node` but no `addEventListener('lm-focus-node'` existed, so the
# click silently did nothing. A handler can "do work" (it calls dispatchEvent)
# yet still be a dead-end because the event falls on deaf ears. We pair every
# dispatched custom-event name against the set of listened names; a dispatch
# with no listener is a dead-end.

_DISPATCH_NAME_RE = re.compile(
    r"dispatchEvent\(\s*new\s+(?:CustomEvent|Event)\(\s*['\"]([\w.-]+)['\"]")
_LISTEN_NAME_RE = re.compile(
    r"addEventListener\(\s*['\"]([\w.-]+)['\"]")

# Browser-native / framework events that legitimately have no in-app
# addEventListener (the platform or another surface handles them).
_NATIVE_EVENTS = {
    "resize", "scroll", "keydown", "keyup", "click", "mousedown", "mouseup",
    "mousemove", "load", "beforeunload", "message", "storage", "popstate",
    "focus", "blur", "input", "change", "submit", "wheel", "contextmenu",
}


# Load-bearing INTERACTION events: a user-triggered event whose WHOLE PURPOSE
# is to cause an effect on another surface. If one of these has no listener,
# the user action it backs does nothing — the founder's exact `lm-focus-node`
# bug. (Internal "notification" dispatches that ride alongside a real effect —
# a localStorage write, a saveCurrentGraph — are NOT in this set; a missing
# listener there is a redundant-notify smell, tracked separately, not a dead
# click.) Curated so the gate stays a precise dead-CLICK detector.
_INTERACTION_EVENTS = (
    "lm-focus-node",        # health issue row → pan+select the flagged node
    "lm-composer-action",   # composer command → graph mutation
    "lm-spawn-skill",       # skill row click → spawn skill node
    "lm-new-session",       # new-chat button → create session
    "lm-share-canvas",      # share button → share flow
    "lm-wire-promote",      # promote-wire action → host output promote
    "lm-new-node",          # add-node → create node
    "lm-graph-bump",        # streaming/edit → canvas refresh
    "lm-canvas-toast",      # any action → toast feedback
    "lm-brain-view-open",   # brain button → open brain modal
    "archhub-minimap-jump", # minimap click → pan canvas
)


def scan_dead_dispatches(src: str, names=None) -> list[tuple[str, int]]:
    """PUBLIC: return [(event_name, count)] for every dispatched custom event
    that is never LISTENED to anywhere in the bundle.

    `names=None` → scan ALL dispatched custom events (broad diagnostic; will
    surface redundant-notification orphans too). `names=<iterable>` → restrict
    to that curated set (the load-bearing interaction events the gate enforces).
    Excludes native browser events. Empty list == all targeted events reach a
    listener.
    """
    src_nc = _strip_comments(src)
    dispatched: dict[str, int] = {}
    for m in _DISPATCH_NAME_RE.finditer(src_nc):
        dispatched[m.group(1)] = dispatched.get(m.group(1), 0) + 1
    listened = set(_LISTEN_NAME_RE.findall(src_nc))
    want = set(names) if names is not None else None
    orphans: list[tuple[str, int]] = []
    for name, count in sorted(dispatched.items()):
        if want is not None and name not in want:
            continue
        if name in listened or name in _NATIVE_EVENTS:
            continue
        orphans.append((name, count))
    return orphans


# ── App-namespace dead-dispatch: the WHOLE class, not a curated subset ─────
# The curated `_INTERACTION_EVENTS` test below pins the specific clicks the
# founder hit. But the founder wants the dead-dispatch CLASS gone, not 11
# instances patched (MAKE-IT-REAL-NEVER-TRIM, 2026-05-30). So this scanner
# enforces that EVERY app-namespaced CustomEvent the UI dispatches — anything
# named `lm-*` or `archhub-*` — has a matching `addEventListener`. These names
# are OURS; a dispatch with no listener is dead by construction (it cannot be a
# browser-native event, and there is no third surface in this single-window app
# that consumes them — bridge.py consumes Qt SLOTS, never DOM CustomEvents;
# verified 2026-05-30 there are zero `lm-*`/`archhub-*` addEventListener or
# CustomEvent references outside studio-lm.jsx, and zero document.dispatchEvent
# of these events).
_APP_EVENT_PREFIXES = ("lm-", "archhub-")

# Genuinely cross-boundary app events that are dispatched in studio-lm.jsx but
# LISTENED FOR elsewhere (Python/Qt bridge, index.html, a second document, or a
# web-worker) — i.e. a missing in-file listener is correct, not dead. Each entry
# MUST carry a one-line reason naming the consumer. EMPTY TODAY: every `lm-*` /
# `archhub-*` event is window-internal to studio-lm.jsx (audited 2026-05-30).
# The mechanism stays so a future cross-surface event can be declared here with
# its consumer rather than silently exempted.
_CROSS_BOUNDARY_EVENTS: dict[str, str] = {
    # "archhub-foo": "consumed by app/bridge.py via runJavaScript injection",
}


def scan_app_dead_dispatches(src: str) -> list[tuple[str, int]]:
    """PUBLIC: every dispatched `lm-*`/`archhub-*` CustomEvent with NO matching
    window.addEventListener, minus the documented cross-boundary allowlist.

    This is the FULL-CLASS gate (vs `scan_dead_dispatches(names=...)`'s curated
    subset). Empty list == no app-namespaced event falls on deaf ears.
    """
    src_nc = _strip_comments(src)
    dispatched: dict[str, int] = {}
    for m in _DISPATCH_NAME_RE.finditer(src_nc):
        dispatched[m.group(1)] = dispatched.get(m.group(1), 0) + 1
    listened = set(_LISTEN_NAME_RE.findall(src_nc))
    orphans: list[tuple[str, int]] = []
    for name, count in sorted(dispatched.items()):
        if not name.startswith(_APP_EVENT_PREFIXES):
            continue
        if name in listened or name in _CROSS_BOUNDARY_EVENTS:
            continue
        orphans.append((name, count))
    return orphans


# ───────────────────────────────────────────────────────────────────────────
# Fabricated-chrome-string detection
# ───────────────────────────────────────────────────────────────────────────
# These match the CLASS of fabrication the founder kept catching, as a string
# LITERAL embedded in JSX text/quotes — not a value derived from data. The old
# fakes were:
#   ServerStrip:      `· 4.2k tok · $0.024 · server :7300`
#   ConversationRail: `WEDNESDAY · MAY 13`
# A regex on the literal SHAPE catches any future re-introduction of the same
# lie, even with different numbers.

# A hardcoded combined usage+cost telemetry literal, e.g. "4.2k tok · $0.024".
# The real ServerStrip derives BOTH via `tokFmt(usage.tokens)` /
# `costFmt(usage.tokens)` interpolated into a template — never a flat literal.
# We require BOTH a token-count AND a cost in the same string so a legitimate
# real-data label like "{m.tokens_out} tok" (no literal number, no cost) is not
# flagged. This is the founder's exact ServerStrip fake shape.
_FAKE_USAGE_COST_RE = re.compile(
    r"\b\d+(?:\.\d+)?k?\s*tok\b.{0,12}\$\s?\d+\.\d{2,}")

# A hardcoded "server :NNNN" port literal in chrome. The real port comes from
# get_runtime_info → realPort, interpolated as `:${realPort}`. We require the
# word "server" adjacent so a bare ":3000" elsewhere isn't flagged.
_FAKE_PORT_RE = re.compile(r"server\s*:\s?\d{3,5}\b")

# A hardcoded weekday·month·day divider literal, e.g. "WEDNESDAY · MAY 13".
# The real divider is computed by `_dayLabelOf` from message timestamps and is
# emitted via a template `${wd} · ${mo} ${d.getDate()}` (interpolated → never a
# flat literal). A flat "WEEKDAY <sep> MONTH <day>" string is the fabrication.
_FAKE_DATE_RE = re.compile(
    r"\b(?:MONDAY|TUESDAY|WEDNESDAY|THURSDAY|FRIDAY|SATURDAY|SUNDAY)\b"
    r"\s*[·.\-|]?\s*"
    r"\b(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\b"
    r"\s*\d{1,2}\b"
)


def _mask_interpolated_templates(src: str) -> str:
    """Blank out the CONTENTS of any backtick template-literal that contains an
    `${…}` interpolation — those render a value DERIVED from data, never a flat
    fabrication, so a `…tok` / weekday inside such a template (e.g. the real
    `${wd} · ${mo} ${d.getDate()}`) must not be flagged. Length-preserving
    (replaces with spaces) so byte offsets stay valid.

    This is deliberately NOT a full JS tokenizer — it only neutralises the one
    construct that produces legitimate "derived" text matching our fake shapes.
    Plain quoted strings and JSX text are left intact so a fabricated LITERAL
    there is still caught, regardless of its position in the file (no fragile
    cross-file quote-pairing — see the self-check's odd-quote-count case).
    """
    out = list(src)
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if c == "`":
            # Find the matching closing backtick (honor \` escapes).
            j = i + 1
            while j < n and src[j] != "`":
                if src[j] == "\\":
                    j += 2
                    continue
                j += 1
            body = src[i + 1:j]
            if "${" in body:
                for k in range(i + 1, min(j, n)):
                    if src[k] != "\n":
                        out[k] = " "
            i = j + 1
            continue
        i += 1
    return "".join(out)


def scan_fabricated_strings(src: str) -> list[tuple[int, str, str]]:
    """PUBLIC: return [(offset, kind, snippet)] for every fabricated-chrome
    literal found — a hardcoded usage+cost / server-port / weekday·month·day
    string baked into the UI instead of derived from real data.

    Position-independent: we strip comments (so audit prose describing an old
    fake isn't matched) and mask interpolated `${…}` templates (so the REAL
    derived divider/usage isn't matched), then search the remaining source text
    directly for the fabricated SHAPES. Searching the masked source directly —
    rather than first extracting individual quoted literals — avoids fragile
    quote-pairing across a 14k-line file with an odd quote count.

    Offsets are into the comment-stripped + template-masked source. Importable
    so the self-check can run it over an injected-fake string.
    """
    text = _mask_interpolated_templates(_strip_comments(src))
    hits: list[tuple[int, str, str]] = []
    checks = (
        ("fake_usage_cost", _FAKE_USAGE_COST_RE),
        ("fake_server_port", _FAKE_PORT_RE),
        ("fake_date_divider", _FAKE_DATE_RE),
    )
    for kind, rx in checks:
        for m in rx.finditer(text):
            snippet = text[max(0, m.start() - 4):m.end() + 4].strip()[:80]
            hits.append((m.start(), kind, snippet))
    return hits


def _line_of(src: str, offset: int) -> int:
    return src.count("\n", 0, offset) + 1


# ───────────────────────────────────────────────────────────────────────────
# THE GATE — run against the real, currently-wired studio-lm.jsx
# ───────────────────────────────────────────────────────────────────────────


def test_jsx_present():
    assert JSX.exists(), f"studio-lm.jsx not found at {JSX}"
    assert JSX.stat().st_size > 100_000, "studio-lm.jsx unexpectedly small"


def test_no_naked_interactive_dead_ends():
    """Every onClick/onKeyDown/onSubmit in the shipped UI reaches a real
    effect — a bridge call, an event dispatch, a state mutation, or a named
    callback. A handler that is pure decoration (empty / no-op / comment-only)
    is the founder's "buttons are for show" complaint and FAILS here."""
    src = _src()
    dead = scan_dead_end_handlers(src)
    if dead:
        lines = "\n".join(
            f"  line {_line_of(src, off)}: {body.strip()[:120]!r}"
            for off, body in dead
        )
        pytest.fail(
            "Naked interactive dead-end handler(s) found — a click that does "
            "no real work (MAKE-IT-REAL §7). Wire each to a real bridge slot / "
            "event / state change, or it is a shell:\n" + lines
        )


def test_no_fabricated_telemetry_or_date_strings():
    """No hardcoded usage+cost / server-port telemetry or weekday·month·day
    divider baked into chrome. The real values come from get_runtime_info /
    window.__archhub_usage / _dayLabelOf(message timestamps). A literal like
    `4.2k tok · $0.024` or `WEDNESDAY · MAY 13` is a fabrication that lies about
    real state (ANTI-LIE) and FAILS here."""
    src = _src()
    hits = scan_fabricated_strings(src)
    if hits:
        # _strip_comments + _mask_interpolated_templates are length-preserving,
        # so offsets map 1:1 to lines in the original source.
        lines = "\n".join(
            f"  line {_line_of(src, off)} [{kind}]: {snip!r}"
            for off, kind, snip in hits
        )
        pytest.fail(
            "Fabricated chrome string(s) found — hardcoded telemetry/date "
            "instead of a value derived from real data (ANTI-LIE):\n" + lines
        )


def test_load_bearing_interaction_events_have_listeners():
    """Every load-bearing INTERACTION event the UI dispatches has a listener.
    A `dispatchEvent(new CustomEvent('lm-focus-node'))` with no matching
    `addEventListener('lm-focus-node'` is the EXACT lie that bit the founder —
    the health-issue click fired the event and nothing listened, so the click
    silently did nothing. This pins the click→effect wiring for the curated
    set of events whose whole purpose is to drive another surface."""
    src = _src()
    orphans = scan_dead_dispatches(src, names=_INTERACTION_EVENTS)
    if orphans:
        lines = "\n".join(f"  '{name}' dispatched {cnt}× — NO listener"
                          for name, cnt in orphans)
        pytest.fail(
            "Load-bearing interaction event(s) dispatched into the void — the "
            "user action they back does nothing (MAKE-IT-REAL §7, the "
            "lm-focus-node bug class):\n" + lines
        )


def test_no_dead_event_dispatches():
    """WHOLE-CLASS gate: every `lm-*` / `archhub-*` CustomEvent the UI dispatches
    has a matching `window.addEventListener`. These names are OURS — a dispatch
    with no listener cannot be a browser-native event and is not consumed by any
    other surface (bridge.py uses Qt slots, not DOM events; audited 2026-05-30),
    so it is dead by construction: the founder's lm-focus-node bug class.

    Unlike `test_load_bearing_interaction_events_have_listeners` (a curated
    subset), this fails on ANY app-namespaced dead dispatch — so reintroducing a
    `dispatchEvent(new CustomEvent('lm-anything'))` with no listener turns this
    RED. Genuinely cross-boundary events (listened for in Python / index.html /
    a worker) must be declared in `_CROSS_BOUNDARY_EVENTS` with their consumer;
    that allowlist is EMPTY today because no such event exists.

    Calibrated 2026-05-30 after wiring the 4 dead dispatches found in the audit
    (lm-skills-changed→lm-skills-refresh, lm-canvas-bump→lm-graph-bump, +
    listeners added for archhub-host-node-v2 and archhub-minimap-toggle)."""
    src = _src()
    orphans = scan_app_dead_dispatches(src)
    if orphans:
        lines = "\n".join(
            f"  '{name}' dispatched {cnt}× — NO window.addEventListener('{name}')"
            for name, cnt in orphans
        )
        pytest.fail(
            "Dead app-namespaced event dispatch(es) — an `lm-*`/`archhub-*` "
            "CustomEvent fired that nothing listens to (MAKE-IT-REAL-NEVER-TRIM "
            "dead-dispatch class). Make it real: rename the dispatch to the event "
            "that IS listened to, OR add the missing listener. If it is genuinely "
            "consumed off-window (Python/bridge, index.html, worker), declare it "
            "in _CROSS_BOUNDARY_EVENTS with its consumer:\n" + lines
        )


# ───────────────────────────────────────────────────────────────────────────
# WIRED-PROOF — assert the specific surfaces the plan §2 made real are wired
# to their real slots (positive coverage: the fakes became real, and stay so).
# ───────────────────────────────────────────────────────────────────────────


def test_serverstrip_reads_real_usage_and_port():
    """ServerStrip pulls the real runtime port (get_runtime_info) + the real
    accumulated session usage (window.__archhub_usage), not the old constants."""
    src = _src()
    strip = _component_body(src, "ServerStrip")
    assert "get_runtime_info" in strip, "ServerStrip must read the real runtime port"
    assert "__archhub_usage" in strip, "ServerStrip must read real accumulated usage"
    # The real derivations (function calls on live values), not flat literals.
    assert "tokFmt(" in strip and "costFmt(" in strip
    assert "realPort" in strip
    # The old fabrications must not survive as rendered literals (they may
    # remain only in the audit comment explaining the fix). The global
    # `test_no_fabricated_telemetry_or_date_strings` enforces this bundle-wide;
    # here we additionally assert the strip body (sans comments) is clean.
    strip_nc = _strip_comments(strip)
    assert "4.2k" not in strip_nc
    assert "$0.024" not in strip_nc


def test_aibody_send_wired_to_send_chat_history():
    """AIBody's inline reply Send calls send_chat_history (was: no handler)."""
    src = _src()
    body = _component_body(src, "AIBody")
    assert "send_chat_history" in body, "AIBody Send must call send_chat_history"
    assert "sendReply" in body, "AIBody Send must be wired to sendReply"
    assert "onClick={sendReply}" in body


def test_outputbody_save_wired_to_save_node_output():
    """OutputBody's save calls save_node_output (was: decorative)."""
    src = _src()
    body = _component_body(src, "OutputBody")
    assert "save_node_output" in body, "OutputBody save must call save_node_output"
    assert "onSave" in body


def test_focus_node_listener_present():
    """The Home health chip / HealthStripItem dispatch `lm-focus-node`; the
    canvas must LISTEN (the old gap: nothing listened → click did nothing)."""
    src = _src()
    assert "addEventListener('lm-focus-node'" in src, (
        "lm-focus-node listener missing — clicking a health issue must pan "
        "the canvas to the flagged node"
    )
    # The listener must do real work: pan + select + focus.
    seg = src[src.index("addEventListener('lm-focus-node'") - 1200:
              src.index("addEventListener('lm-focus-node'") + 200]
    assert "setPan(" in seg and "setSelectedIds(" in seg and "setFocusId(" in seg


def test_date_divider_is_computed_not_hardcoded():
    """The conversation date divider is derived from message timestamps via
    _dayLabelOf, not the old `WEDNESDAY · MAY 13` literal."""
    src = _src()
    assert "_dayLabelOf" in src and "_dayKeyOf" in src
    # _dayLabelOf must compute from a real Date, not return a constant.
    body = _function_body(src, "_dayLabelOf")
    assert "getDay()" in body and "getMonth()" in body


def test_paper_and_accent2_tokens_defined():
    """LM.paper + LM.accent2 were referenced but undefined (rendered the
    literal string `undefined`). They must now resolve as real getters."""
    src = _src()
    assert re.search(r"get\s+paper\s*\(\)", src), "LM.paper must be a defined token"
    assert re.search(r"get\s+accent2\s*\(\)", src), "LM.accent2 must be a defined token"


# ── small structural helpers shared by the wired-proof tests ──────────────


def _component_body(src: str, name: str) -> str:
    """Return the source slice of a `const <name> = (...) => { ... }`
    component, balanced from its first `{` after the arrow to the matching
    close. Falls back to a forward window if the arrow shape isn't found."""
    m = re.search(r"const\s+" + re.escape(name) + r"\s*=\s*\([^)]*\)\s*=>\s*\{", src)
    if not m:
        idx = src.index("const " + name)
        return src[idx:idx + 4000]
    brace_idx = src.index("{", m.end() - 1)
    inner, _ = _balanced_slice(src, brace_idx, "{", "}")
    return inner


def _function_body(src: str, name: str) -> str:
    """Return the body of a `const <name> = (...) => { ... }` arrow fn."""
    return _component_body(src, name)
