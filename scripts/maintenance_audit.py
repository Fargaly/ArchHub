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
            audit.add("HIGH", "bare-except", path, i,
                      "bare `except:` swallows every error including bugs")
        # `except Exception: pass` on the same or next line.
        if re.match(r"except\s+Exception\s*:\s*pass\s*$", s):
            audit.add("MEDIUM", "except-pass", path, i,
                      "`except Exception: pass` — silent swallow; log it")


# AgDR-0036 — the blocking-call patterns.  Beyond direct stdlib
# blockers, this catches the HELPER-HOP cases the first detector
# missed: a slot that LOOKS clean but calls `c.probe()` /
# `broker.forward(...)` / `cloud_client._request(...)` /
# `detect_all_*` / a recursive `glob("**/...")` — each blocks one or
# two hops down.  Those five+ hidden offenders are what kept the
# founder pointing at the lag.
_BLOCKING_PATTERNS = re.compile(
    r"\b(urlopen|subprocess\.(run|call|check_output|Popen)|"
    r"\.recv\(|time\.sleep|socket\.create_connection|"
    r"requests\.(get|post)|"
    r"\.forward\(|\.probe\(\)|_request\(|"
    r"detect_all_hosts|detect_all_local_llms|"
    r"list_sessions\(|sessions_count\(|is_reachable\(|"
    r"com_thread\(|GetActiveObject)\b")
# A recursive glob is a separate, multi-line-safe check.
_RECURSIVE_GLOB = re.compile(r"\.glob\(\s*['\"]\*\*")
# Markers that prove the slow work was moved OFF the Qt main thread.
_OFFTHREAD = ("Thread(", "to_thread", "QThread", "_cached_async",
              "_async_state", ".submit(", "singleShot")


def scan_blocking_in_slot(audit: Audit, path: Path, lines: list[str]) -> None:
    """Flag any @pyqtSlot whose body does blocking I/O — directly OR
    one helper-hop down — without an off-thread marker.  This is the
    guard for the whole UI-freeze CLASS (AgDR-0035 / AgDR-0036)."""
    in_slot = False
    slot_line = 0
    slot_off_thread = False
    slot_body: list[tuple[int, str]] = []

    def _flush():
        nonlocal slot_body, slot_off_thread, slot_line
        if slot_body and not slot_off_thread:
            for ln_no, txt in slot_body:
                if _BLOCKING_PATTERNS.search(txt) or _RECURSIVE_GLOB.search(txt):
                    audit.add("HIGH", "blocking-in-pyqtslot", path, ln_no,
                              f"blocking I/O in @pyqtSlot (slot at line "
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


def scan_success_mask(audit: Audit, path: Path, lines: list[str]) -> None:
    """A `return {"status": "ok"...}` inside an `except` block masks
    a failure as success."""
    in_except = False
    except_indent = 0
    for i, ln in enumerate(lines, 1):
        s = ln.strip()
        indent = len(ln) - len(ln.lstrip())
        if s.startswith("except"):
            in_except = True
            except_indent = indent
            continue
        if in_except:
            if s and indent <= except_indent and not s.startswith("#"):
                in_except = False
            elif '"status": "ok"' in ln or "'status': 'ok'" in ln:
                if "return" in ln:
                    audit.add("HIGH", "success-mask", path, i,
                              "returns status:ok from inside an except "
                              "block — masks a real failure as success")


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
    for path in _py_files():
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            continue
        scan_bare_except(audit, path, lines)
        scan_blocking_in_slot(audit, path, lines)
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
