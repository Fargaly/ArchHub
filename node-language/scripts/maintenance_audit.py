"""AgDR-0034 — ArchHub static maintenance audit.

Scans the Python backend + JSX UI for the anti-pattern CLASSES the
2026-05-21 deep audit found recurring.  Emits a Markdown report to
stdout (and to --out FILE) plus a one-line JSON summary on the last
line for the CI workflow to parse.

Run:
    python scripts/maintenance_audit.py
    python scripts/maintenance_audit.py --out audit-report.md

Exit code is always 0 — the audit is informational.  The CI workflow
reads the JSON summary's `critical` count to decide whether to open a
tracking issue.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
APP = REPO / "app"


@dataclass
class Finding:
    severity: str   # CRITICAL | HIGH | MEDIUM | INFO
    cls: str        # short class name
    file: str
    line: int
    detail: str


@dataclass
class Audit:
    findings: list[Finding] = field(default_factory=list)

    def add(self, sev, cls, path: Path, line, detail):
        self.findings.append(Finding(
            sev, cls, str(path.relative_to(REPO)).replace("\\", "/"),
            line, detail))


# ─── Python scanners ─────────────────────────────────────────────────


def _py_files() -> list[Path]:
    out = []
    for p in APP.rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        out.append(p)
    return sorted(out)


def scan_bare_except(audit: Audit, path: Path, lines: list[str]) -> None:
    for i, ln in enumerate(lines, 1):
        s = ln.strip()
        if s == "except:" or s.startswith("except:"):
            # A truly bare `except:` also swallows KeyboardInterrupt /
            # SystemExit / MemoryError — never a legitimate fail-soft, so
            # the marker does NOT clear it. Stays a hard HIGH.
            audit.add("HIGH", "bare-except", path, i,
                      "bare `except:` swallows every error including bugs")
        # `except Exception: pass` — a one-line silent swallow.  Mirroring
        # the `_SUCCESS_MASK_OK` convention scan_success_mask honors, an
        # explicit `# audit: deliberate-fail-soft` marker — either trailing
        # the except line or on the comment line directly above it —
        # certifies the swallow as a documented, auditable fail-soft and
        # clears the finding.  The marker must carry an inline rationale so
        # the choice is auditable, not silent; an undocumented swallow still
        # flags.
        if re.match(r"except\s+Exception\s*:\s*pass\b", s):
            prev = lines[i - 2].strip() if i >= 2 else ""
            marked = (_SUCCESS_MASK_OK in ln
                      or (prev.startswith("#") and _SUCCESS_MASK_OK in prev))
            if not marked:
                audit.add("MEDIUM", "except-pass", path, i,
                          "`except Exception: pass` — silent swallow; log it")


# AgDR-0036 — the blocking-call patterns.  Beyond direct stdlib
# blockers, this catches the HELPER-HOP cases the first detector
# missed: a slot that LOOKS clean but calls `c.probe()` /
# `broker.forward(...)` / `cloud_client._request(...)` /
# `detect_all_*` / a recursive `glob("**/...")` — each blocks one or
# two hops down.  Those five+ hidden offenders are what kept the
# founder pointing at the lag.
#
# APP-01 (court-root, 2026-06-15): added the LLM-provider probe helpers.
# `get_providers` / `get_provider_stats` / `get_runtime_info` called
# `router.configured_providers()`, which calls `llm_detector.probe_lmstudio`
# (+ probes Ollama) → a full ~1.5 s `urlopen` stall on a half-open LM
# Studio port, ON the Qt main thread, INSIDE the boot pullAll batch.  The
# old pattern set listed `.probe()` (empty-parens only) so none of
# `configured_providers(` / `lmstudio_models(` / `ollama_models(` /
# `probe_lmstudio` / `probe_ollama` matched, and the guard stayed green
# over three real blocking slots.  These names make the CALL SITE in the
# slot body match directly; the two-hop resolver below catches the general
# case where a slot calls a same-package helper that blocks.
# NOTE on regex shape (APP-01 court-root fix): the previous single
# pattern wrapped the whole alternation in `\b(...)\b`.  A trailing `\b`
# after a `name\(` alternative requires a WORD char right after `(` — so
# `configured_providers()`, `_request("POST"`, `list_sessions()` (a `(`
# followed by `)` or `"`) silently FAILED to match.  That is a second
# reason the guard stayed green over real blocking slots.  Split into two
# patterns: identifier-form blockers carry their own `\b`; call-form
# blockers anchor on `\(` with NO trailing boundary so they match
# regardless of the next char.
_BLOCKING_IDENT = re.compile(
    r"\b(urlopen|time\.sleep|socket\.create_connection|"
    r"detect_all_hosts|detect_all_local_llms|_probe_host_status|"
    r"probe_lmstudio|probe_ollama|GetActiveObject)\b")
_BLOCKING_CALL = re.compile(
    r"(subprocess\.(run|call|check_output|Popen)|"
    r"\.recv|requests\.(get|post)|"
    r"\.forward|\.probe|_request|"
    r"configured_providers|lmstudio_models|ollama_models|"
    r"detect_all|list_local_models|"
    r"list_sessions|sessions_count|is_reachable|com_thread)\s*\(")


def _blocking_search(txt: str):
    """True-ish if `txt` contains a blocking primitive in either form."""
    return _BLOCKING_IDENT.search(txt) or _BLOCKING_CALL.search(txt)


# Back-compat shim: some callers/tests referenced `_BLOCKING_PATTERNS`
# directly.  Expose an object whose `.search` checks both sub-patterns.
class _BlockingPatternsCompat:
    @staticmethod
    def search(txt: str):
        return _blocking_search(txt)


_BLOCKING_PATTERNS = _BlockingPatternsCompat()
# A recursive glob is a separate, multi-line-safe check.
_RECURSIVE_GLOB = re.compile(r"\.glob\(\s*['\"]\*\*")
# Markers that prove the slow work was moved OFF the Qt main thread.
_OFFTHREAD = ("Thread(", "to_thread", "QThread", "_cached_async",
              "_async_state", ".submit(", "singleShot")

# Generic method names that recur across unrelated classes.  Even within
# one file the same-file two-hop resolver must not treat a benign
# `x.search(...)` / `p.resolve()` as "calls a blocking helper" just
# because SOME class in the file has a blocking method by that name.  The
# genuinely-dangerous cross-file helpers are matched precisely by name in
# `_BLOCKING_CALL`, so excluding these from the fuzzy resolver only drops
# false positives, never a real catch.
_GENERIC_HELPER_NAMES = {
    "run", "search", "stop", "start", "resolve", "register", "me",
    "ops", "get", "post", "close", "open", "read", "write", "load",
    "save", "send", "emit", "call", "probe", "forward", "request",
    "to_dict", "keys", "values", "items", "update", "clear", "list",
}


# ─── two-hop helper resolution (APP-01 court-root, defect #2) ─────────
#
# The first detector only inspected a slot's OWN body text — so a slot
# that calls a clean-looking helper whose blocking lives one MORE hop
# down stayed invisible.  TWO complementary fixes close the class:
#
#   (a) PRECISE cross-file names — the specific dangerous helpers a slot
#       reaches into another module for (`configured_providers`,
#       `lmstudio_models`, `probe_lmstudio`, `_request`, …) are matched
#       by name in `_BLOCKING_CALL`, regardless of the receiver.  This is
#       what catches the court's `self.router.configured_providers()`.
#
#   (b) GENERAL same-file resolution — for a slot that calls a private
#       helper DEFINED IN THE SAME FILE (bare `foo()` or `self.foo()`),
#       we build that file's index of blocking helpers and flag the call.
#       Scoping (b) to same-file + self/bare receivers is deliberate: a
#       static scanner cannot type an arbitrary `obj.foo()`, so resolving
#       generic method names (`search`, `stop`, `resolve`) repo-wide
#       produced rampant collision false positives.  Same-file + `self.`
#       is provably the same object, so it stays sound.
#
# Hardcoding every helper name forever would be the "patch one call site"
# whack-a-mole the engineering mandate bans; (b) is the structural net
# that catches new same-file blockers without a code change.

def _build_blocking_helper_index(py_files: list[Path]) -> set[str]:
    """Return the set of function/method NAMES (across the given files)
    whose body does blocking I/O directly and is not itself moved
    off-thread.  A slot that calls any of these names is blocking one or
    two hops down.

    Indent-STACK based: real modules alternate between module-level
    functions (indent 0) and class methods (indent 4), so a naive
    monotonic "deeper == nested" rule mis-attributes a method that
    follows a module-level def (it read `4 > 0` as nested and never
    opened the method's own scope — the exact bug that hid
    `configured_providers`).  Here each `def` pushes a frame; a `def`/
    dedent to indent I closes (commits) every open frame whose indent
    >= I; a blocking primitive marks the INNERMOST open frame, and an
    off-thread marker clears it.  A nested closure dispatched off-thread
    (the `_work` passed to `_cached_async`) therefore does NOT mark its
    enclosing helper."""
    blocking: set[str] = set()
    for path in py_files:
        try:
            lines = path.read_text(encoding="utf-8",
                                   errors="replace").splitlines()
        except Exception:
            continue
        # stack of frames: [name, indent, blocks, off_thread]
        stack: list[list] = []

        def _commit(frame):
            if frame[0] and frame[2] and not frame[3]:
                blocking.add(frame[0])

        for ln in lines:
            s = ln.strip()
            if not s or s.startswith("#"):
                continue
            indent = len(ln) - len(ln.lstrip())
            # A line at indent I closes every frame whose def-indent >= I
            # (the frame's body has ended).  A `def` line at indent I is
            # itself a sibling/outer of any frame with indent >= I.
            while stack and indent <= stack[-1][1]:
                _commit(stack.pop())
            dm = re.match(r"(?:async\s+)?def\s+([A-Za-z_]\w*)\s*\(", s)
            if dm:
                stack.append([dm.group(1), indent, False, False])
                continue
            if stack:
                top = stack[-1]
                if any(m in ln for m in _OFFTHREAD):
                    top[3] = True
                if _BLOCKING_PATTERNS.search(ln) or _RECURSIVE_GLOB.search(ln):
                    top[2] = True
        while stack:
            _commit(stack.pop())
    # Never let the generic resolver treat the async plumbing itself as a
    # "blocking helper" — these MOVE work off-thread, they don't block.
    # `_work` / `_refresh` are the closure convention for the body that
    # RUNS on the background pool (passed to `_cached_async` / `_bg_pool`),
    # so a reference to them is not a blocking call on the Qt thread.
    for safe in ("_cached_async", "_bg_pool", "_refresh", "_work"):
        blocking.discard(safe)
    return blocking


def _helper_call_re(names: set[str]) -> Optional[re.Pattern]:
    """A regex matching a call to a SAME-FILE helper in `names`, invoked
    either bare (``name(``) or on ``self`` (``self.name(``).

    Deliberately NOT matching an arbitrary attribute chain
    (``obj.name(``): a static text scanner cannot know the type of
    ``obj``, so resolving ``obj.search()`` against every ``search`` method
    in the repo produced rampant name-collision false positives
    (``Path(...).resolve()`` tripping a connector's ``resolve``, etc.).
    Two-hop resolution is therefore scoped to names DEFINED in the same
    file and reached bare or through ``self`` — which is provably the
    same object.  Dangerous cross-file helpers (``configured_providers``,
    ``probe_lmstudio``, ``_request`` …) are matched precisely by name in
    ``_BLOCKING_CALL`` instead, so the court's
    ``self.router.configured_providers()`` is still caught — just not via
    this fuzzy resolver."""
    if not names:
        return None
    alt = "|".join(re.escape(n) for n in sorted(names))
    # Start-of-token or `self.` only — never a generic `obj.` receiver.
    return re.compile(r"(?<![\w.])(?:self\.)?(?:" + alt + r")\s*\(")


def scan_blocking_in_slot(audit: Audit, path: Path, lines: list[str],
                          helper_index: "set[str] | None" = None) -> None:
    """Flag any @pyqtSlot whose body does blocking I/O — directly OR via a
    helper that blocks (one OR two hops down) — without an off-thread
    marker.  This is the guard for the whole UI-freeze CLASS
    (AgDR-0035 / AgDR-0036 / APP-01).

    `helper_index` is the set of SAME-FILE blocking helper names (built by
    `_build_blocking_helper_index([path])`).  When omitted it is built
    from `path` itself on demand, so the 3-arg call shape (used by the
    gate test) keeps working unchanged AND stays same-file-scoped (the
    sound scope — see `_helper_call_re`)."""
    if helper_index is None:
        helper_index = _build_blocking_helper_index([path])
    # Drop generic method names that collide across unrelated classes even
    # within one file — the precise cross-file blockers are already in
    # `_BLOCKING_CALL`, so excluding these here only removes noise.
    helper_names = set(helper_index) - _GENERIC_HELPER_NAMES
    helper_re = _helper_call_re(helper_names)

    in_slot = False
    slot_line = 0
    slot_off_thread = False
    slot_body: list[tuple[int, str]] = []

    def _flush():
        nonlocal slot_body, slot_off_thread, slot_line
        if slot_body and not slot_off_thread:
            for ln_no, txt in slot_body:
                two_hop = bool(helper_re and helper_re.search(txt))
                if (_BLOCKING_PATTERNS.search(txt)
                        or _RECURSIVE_GLOB.search(txt) or two_hop):
                    why = ("calls a blocking helper" if two_hop and not
                           _BLOCKING_PATTERNS.search(txt) else "blocking I/O")
                    audit.add("HIGH", "blocking-in-pyqtslot", path, ln_no,
                              f"{why} in @pyqtSlot (slot at line "
                              f"{slot_line}) — freezes the Qt UI thread; "
                              f"route through _cached_async or a thread")
        slot_body = []
        slot_off_thread = False

    pending_slot = False
    for i, ln in enumerate(lines, 1):
        s = ln.strip()
        if s.startswith("@pyqtSlot"):
            _flush()
            pending_slot = True
            continue
        if pending_slot and s.startswith("def "):
            in_slot = True
            slot_line = i
            pending_slot = False
            continue
        if in_slot:
            indent = len(ln) - len(ln.lstrip())
            if s and indent <= 4 and (s.startswith("def ")
                                       or s.startswith("@")
                                       or s.startswith("class ")):
                _flush()
                in_slot = False
                if s.startswith("@pyqtSlot"):
                    pending_slot = True
                continue
            if any(m in ln for m in _OFFTHREAD):
                slot_off_thread = True
            slot_body.append((i, ln))
    _flush()


# A method becomes a periodic poller when it's wired to a QTimer's
# `timeout` signal OR handed to `QTimer.singleShot(...)`. Those callbacks
# run ON the Qt GUI thread, so blocking I/O in them freezes the UI exactly
# like a blocking @pyqtSlot does — but the @pyqtSlot detector never saw
# them. This pair of patterns harvests the wired callback method names.
_TIMER_TIMEOUT_CONNECT = re.compile(
    r"\.timeout\.connect\(\s*self\.([A-Za-z_]\w*)")
_TIMER_SINGLESHOT = re.compile(
    r"singleShot\(\s*[^,]+,\s*self\.([A-Za-z_]\w*)")


def _timer_callback_names(lines: list[str]) -> set[str]:
    names: set[str] = set()
    for ln in lines:
        for m in _TIMER_TIMEOUT_CONNECT.finditer(ln):
            names.add(m.group(1))
        for m in _TIMER_SINGLESHOT.finditer(ln):
            names.add(m.group(1))
    return names


def scan_blocking_in_timer_callback(audit: Audit, path: Path,
                                    lines: list[str]) -> None:
    """Flag any method wired to a QTimer (`.timeout.connect(self.X)` or
    `QTimer.singleShot(ms, self.X)`) whose body does blocking I/O — directly
    or one helper-hop down — without an off-thread marker.

    Root: a QTimer callback runs on the Qt GUI thread just like a @pyqtSlot,
    so a blocking port-scan / HTTP / COM call in it freezes the UI on every
    tick. The host-pill idle-stall (chat_window._refresh_host_pills, fixed
    2026-06-02) was exactly this class and the @pyqtSlot-only detector missed
    it. The off-thread markers (QThread / Thread / .submit / _cached_async /
    a NESTED singleShot that re-defers) clear the finding."""
    targets = _timer_callback_names(lines)
    if not targets:
        return

    in_fn = False
    fn_name = ""
    fn_off_thread = False
    fn_body: list[tuple[int, str]] = []

    def _flush():
        nonlocal fn_body, fn_off_thread, fn_name
        if fn_body and fn_name in targets and not fn_off_thread:
            for ln_no, txt in fn_body:
                if _BLOCKING_PATTERNS.search(txt) or _RECURSIVE_GLOB.search(txt):
                    audit.add("HIGH", "blocking-in-timer-callback", path, ln_no,
                              f"blocking I/O in QTimer callback "
                              f"`{fn_name}` — runs on the Qt GUI thread; "
                              f"freezes the UI on every tick. Fan it onto a "
                              f"QThread / _bg_pool and repaint via a signal.")
        fn_body = []
        fn_off_thread = False

    for i, ln in enumerate(lines, 1):
        s = ln.strip()
        dm = re.match(r"def\s+([A-Za-z_]\w*)\s*\(", s)
        if dm:
            indent = len(ln) - len(ln.lstrip())
            # Only treat a top-level (method-depth) def as a new scope; a
            # nested worker def (e.g. _HostPillsWorker.run) stays inside the
            # callback body so its off-thread markers still count.
            if indent <= 4:
                _flush()
                in_fn = True
                fn_name = dm.group(1)
                continue
        if in_fn:
            if any(m in ln for m in _OFFTHREAD):
                fn_off_thread = True
            fn_body.append((i, ln))
    _flush()


# A `return status:ok` inside an `except` is normally a mask. But some
# except blocks are a DELIBERATE, honest fail-OVER / degraded path that
# does NOT claim the real operation succeeded — it returns a clearly
# self-labelled degraded result (e.g. a stub response carrying
# `"stub": True`). Mirroring the `_OFFTHREAD` marker convention the
# blocking scanners use, an explicit in-source marker on the return's
# block clears the finding. The marker must be justified inline so the
# choice is auditable, not silent. Keep this allowlist SHORT — only a
# genuine documented fail-soft earns it; a real lie never does.
_SUCCESS_MASK_OK = "audit: deliberate-fail-soft"


def scan_success_mask(audit: Audit, path: Path, lines: list[str]) -> None:
    """A `return {"status": "ok"...}` inside an `except` block masks
    a failure as success — UNLESS the except block carries the explicit
    `# audit: deliberate-fail-soft` marker (a documented degraded path
    that self-labels and does not claim real success)."""
    in_except = False
    except_indent = 0
    block_lines: list[tuple[int, str]] = []

    def _flush():
        nonlocal block_lines
        # The marker anywhere in the except block (a comment line)
        # certifies the whole block as a deliberate fail-soft.
        cleared = any(_SUCCESS_MASK_OK in txt for _, txt in block_lines)
        if not cleared:
            for ln_no, txt in block_lines:
                if ('"status": "ok"' in txt or "'status': 'ok'" in txt) \
                        and "return" in txt:
                    audit.add("HIGH", "success-mask", path, ln_no,
                              "returns status:ok from inside an except "
                              "block — masks a real failure as success")
        block_lines = []

    for i, ln in enumerate(lines, 1):
        s = ln.strip()
        indent = len(ln) - len(ln.lstrip())
        if s.startswith("except"):
            _flush()
            in_except = True
            except_indent = indent
            continue
        if in_except:
            if s and indent <= except_indent and not s.startswith("#"):
                _flush()
                in_except = False
                # The dedented line could itself open a new except.
                if s.startswith("except"):
                    in_except = True
                    except_indent = indent
            else:
                block_lines.append((i, ln))
    _flush()


def scan_todos(audit: Audit, path: Path, lines: list[str]) -> None:
    for i, ln in enumerate(lines, 1):
        m = re.search(r"\b(TODO|FIXME|HACK|XXX)\b", ln)
        if m:
            audit.add("INFO", "todo-marker", path, i,
                      f"{m.group(1)}: {ln.strip()[:80]}")


def scan_huge_functions(audit: Audit, path: Path, lines: list[str]) -> None:
    def_line = 0
    def_name = ""
    def_indent = 0
    count = 0
    for i, ln in enumerate(lines, 1):
        s = ln.strip()
        indent = len(ln) - len(ln.lstrip())
        if s.startswith("def ") or s.startswith("async def "):
            if def_line and count > 150:
                audit.add("MEDIUM", "huge-function", path, def_line,
                          f"`{def_name}` is {count} lines — hard to "
                          f"review / test; consider splitting")
            def_line = i
            def_name = s.split("(")[0].replace("def ", "").replace("async ", "")
            def_indent = indent
            count = 0
        elif def_line:
            count += 1
    if def_line and count > 150:
        audit.add("MEDIUM", "huge-function", path, def_line,
                  f"`{def_name}` is {count} lines")


# ─── JSX scanners ────────────────────────────────────────────────────


def scan_jsx_listener_leak(audit: Audit, path: Path, text: str) -> None:
    """Flag addEventListener whose handler name has no matching
    removeEventListener anywhere in the file."""
    adds = re.findall(r"addEventListener\(\s*['\"]([a-z]+)['\"]\s*,\s*"
                      r"([A-Za-z_$][\w$]*)", text)
    removes = set(re.findall(
        r"removeEventListener\(\s*['\"][a-z]+['\"]\s*,\s*"
        r"([A-Za-z_$][\w$]*)", text))
    for ev, handler in adds:
        if handler not in removes:
            # Locate first occurrence for the line number.
            idx = text.find(f"addEventListener('{ev}', {handler}")
            if idx < 0:
                idx = text.find(f'addEventListener("{ev}", {handler}')
            line = text[:idx].count("\n") + 1 if idx >= 0 else 0
            audit.add("HIGH", "listener-leak", path, line,
                      f"addEventListener('{ev}', {handler}) has no "
                      f"matching removeEventListener — listener leak")


def scan_jsx_bridge_sync(audit: Audit, path: Path, text: str) -> None:
    """bridgeJson is async; using its result synchronously is a bug."""
    for m in re.finditer(r"=\s*bridgeJson\(", text):
        line = text[:m.start()].count("\n") + 1
        # Heuristic: the assigned var used with Array.isArray on a
        # nearby line without await / .then.
        seg = text[m.start():m.start() + 200]
        if "await" not in text[max(0, m.start() - 12):m.start()]:
            if ".then(" not in seg and "Promise" not in seg:
                audit.add("HIGH", "bridge-sync-misuse", path, line,
                          "bridgeJson() result used synchronously — it "
                          "returns a Promise; await it or use .then()")


def scan_jsx_console(audit: Audit, path: Path, text: str) -> None:
    for m in re.finditer(r"\bconsole\.log\(", text):
        line = text[:m.start()].count("\n") + 1
        audit.add("INFO", "console-log", path, line,
                  "console.log left in shipped UI code")


# ─── run ─────────────────────────────────────────────────────────────


def run_audit() -> Audit:
    audit = Audit()
    files = _py_files()
    for path in files:
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            continue
        scan_bare_except(audit, path, lines)
        # Same-file two-hop index (APP-01): a slot is also blocking if it
        # calls a private helper DEFINED IN THIS FILE that blocks.  Built
        # per-file so the resolver stays same-file-scoped (sound); the
        # dangerous cross-file helpers are matched by name in
        # `_BLOCKING_CALL` regardless of file.
        helper_index = _build_blocking_helper_index([path])
        scan_blocking_in_slot(audit, path, lines, helper_index)
        scan_blocking_in_timer_callback(audit, path, lines)
        scan_success_mask(audit, path, lines)
        scan_todos(audit, path, lines)
        scan_huge_functions(audit, path, lines)
    for jsx in sorted((APP / "web_ui").glob("*.jsx")):
        try:
            text = jsx.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        scan_jsx_listener_leak(audit, jsx, text)
        scan_jsx_bridge_sync(audit, jsx, text)
        scan_jsx_console(audit, jsx, text)
    return audit


def render_report(audit: Audit) -> str:
    by_sev: dict[str, list[Finding]] = {}
    for f in audit.findings:
        by_sev.setdefault(f.severity, []).append(f)
    order = ["CRITICAL", "HIGH", "MEDIUM", "INFO"]
    lines = ["# ArchHub maintenance audit", ""]
    counts = {s: len(by_sev.get(s, [])) for s in order}
    lines.append("| Severity | Count |")
    lines.append("|---|---|")
    for s in order:
        lines.append(f"| {s} | {counts[s]} |")
    lines.append("")
    for s in order:
        items = by_sev.get(s, [])
        if not items:
            continue
        lines.append(f"## {s} ({len(items)})")
        lines.append("")
        # Group by class.
        by_cls: dict[str, list[Finding]] = {}
        for f in items:
            by_cls.setdefault(f.cls, []).append(f)
        for cls, fs in sorted(by_cls.items()):
            lines.append(f"### `{cls}` — {len(fs)}")
            for f in fs[:40]:
                lines.append(f"- `{f.file}:{f.line}` — {f.detail}")
            if len(fs) > 40:
                lines.append(f"- … +{len(fs) - 40} more")
            lines.append("")
    return "\n".join(lines)


def main(argv=None) -> int:
    # Windows consoles default to cp1252 — audit text may carry non-ASCII
    # from scanned source lines.  Force UTF-8 so printing never crashes.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", help="write the Markdown report to this file")
    args = ap.parse_args(argv)

    audit = run_audit()
    report = render_report(audit)
    if args.out:
        Path(args.out).write_text(report, encoding="utf-8")
    print(report)

    summary = {
        "critical": sum(1 for f in audit.findings if f.severity == "CRITICAL"),
        "high":     sum(1 for f in audit.findings if f.severity == "HIGH"),
        "medium":   sum(1 for f in audit.findings if f.severity == "MEDIUM"),
        "info":     sum(1 for f in audit.findings if f.severity == "INFO"),
        "total":    len(audit.findings),
    }
    # Last line — machine-readable for the CI workflow.
    print("AUDIT_SUMMARY_JSON " + json.dumps(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
