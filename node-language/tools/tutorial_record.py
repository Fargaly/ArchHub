"""Tutorial recorder — companion to `brain.skill_mint`.

Walks a trace JSON, captures a screenshot per `tool_call` via `mss`, and
writes the images to `docs/tutorials/_media/<slug>/step-N.png`.

This is the SECOND output of a successful trace (per Content-Ecosystem
2026-05-26 §3 deliverable 4): the trace mints a SKILL via the reflexion
worker AND a TUTORIAL via this recorder. The tutorial markdown is drafted
by `personal_brain.reflexion.extract_tutorial_draft`; this CLI fills the
visual half.

Reference: `tools/cdp_brain_proof.py` shows the same shape — capture once
per logical step, write to a dated proofs directory. We mirror that
pattern with `mss` (which works without ArchHub running, capturing the
foreground monitor) so the recorder can be triggered from a Stop hook
without coupling to QtWebEngine's CDP port.

Usage::

    python tools/tutorial_record.py --trace path/to/trace.json
    python tools/tutorial_record.py --trace -          # stdin
    python tools/tutorial_record.py \\
        --trace trace.json --out docs/tutorials/_media

Exit codes:
  0 — at least one screenshot written.
  1 — bad input or no tool_calls in trace.
  2 — mss not importable.

This CLI captures screenshots from THE HOST it runs on. It is NOT
intended to be invoked by Claude inside an agent session — it's a tool
to be triggered by the brain's Stop hook after a real human trace
completes.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


def _load_trace(arg: str) -> dict[str, Any]:
    """Load trace JSON from a path or `-` (stdin)."""
    if arg == "-":
        data = sys.stdin.read()
    else:
        p = Path(arg)
        if not p.is_file():
            raise SystemExit(f"trace file not found: {arg}")
        data = p.read_text(encoding="utf-8")
    try:
        obj = json.loads(data)
    except json.JSONDecodeError as ex:
        raise SystemExit(f"trace is not valid JSON: {ex}") from ex
    if not isinstance(obj, dict):
        raise SystemExit("trace JSON must be a top-level object")
    return obj


def _slug_for(trace: dict[str, Any]) -> str:
    """Derive a kebab-case slug from the trace's skill name or title."""
    raw = (
        trace.get("slug")
        or trace.get("skill_name")
        or trace.get("proposed_name")
        or trace.get("title")
        or f"tutorial-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    )
    raw = str(raw).strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", raw).strip("-") or "tutorial"
    return slug[:64]


def _ensure_mss():
    """Import mss with a graceful failure mode.

    `cdp_brain_proof.py` exits with code 2 when its websocket dep is
    missing — we mirror that contract so the calling hook script can
    distinguish "tool absent" (2) from "trace bad" (1)."""
    try:
        import mss  # type: ignore
        return mss
    except ImportError:
        print(
            "mss not installed. Install with `pip install mss` to enable "
            "tutorial screenshot capture.",
            file=sys.stderr,
        )
        sys.exit(2)


def capture_step(
    sct: Any,
    *,
    out_dir: Path,
    step_n: int,
    monitor_idx: int = 1,
) -> Path:
    """Capture one screenshot for one step. Returns the written path.

    `monitor_idx=1` is the primary monitor in mss numbering; `0` is the
    bounding box across all monitors. The recorder defaults to the
    primary because the user's flow is almost always on the main screen.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"step-{step_n}.png"
    monitors = sct.monitors
    if monitor_idx >= len(monitors):
        monitor_idx = 1 if len(monitors) > 1 else 0
    monitor = monitors[monitor_idx]
    img = sct.grab(monitor)
    # mss has a built-in PNG writer; matches cdp_brain_proof.py's
    # png-bytes-to-disk pattern.
    from mss import tools as mss_tools  # type: ignore
    mss_tools.to_png(img.rgb, img.size, output=str(out_path))
    return out_path


def record_trace(
    trace: dict[str, Any],
    *,
    out_root: Path,
    step_delay_s: float = 0.0,
    monitor_idx: int = 1,
) -> dict[str, Any]:
    """Walk a trace's tool_calls, capture a screenshot per step.

    Returns a manifest dict naming the slug, every step number, and the
    written path. The manifest is also written to
    `<out_root>/<slug>/manifest.json` so a downstream renderer can
    cross-reference frames against the tutorial markdown without
    re-walking the trace.

    `step_delay_s` is a deliberate pause BEFORE each capture so the UI
    has time to settle. Defaults to 0 — when called from the Stop hook
    the user has already finished the trace, so the screen is stable
    anyway. For live-recording mode, set this to ~0.5s.
    """
    tool_calls = trace.get("tool_calls") or []
    if not tool_calls:
        return {
            "ok": False,
            "reason": "no tool_calls in trace",
            "slug": _slug_for(trace),
            "shots": [],
        }

    mss = _ensure_mss()
    slug = _slug_for(trace)
    slug_dir = out_root / slug

    shots: list[dict[str, Any]] = []
    with mss.mss() as sct:
        for i, tc in enumerate(tool_calls, start=1):
            if step_delay_s > 0:
                time.sleep(step_delay_s)
            try:
                p = capture_step(
                    sct, out_dir=slug_dir, step_n=i,
                    monitor_idx=monitor_idx,
                )
                shots.append({
                    "n": i,
                    "tool": (tc.get("name") if isinstance(tc, dict) else "?"),
                    "path": str(p),
                })
            except Exception as ex:
                shots.append({
                    "n": i,
                    "tool": (tc.get("name") if isinstance(tc, dict) else "?"),
                    "error": f"{type(ex).__name__}: {ex}",
                })

    manifest = {
        "ok": any("path" in s for s in shots),
        "slug": slug,
        "captured_at": datetime.utcnow().isoformat() + "Z",
        "shots": shots,
        "trace_id": trace.get("trace_id"),
        "session_id": trace.get("session_id"),
    }
    slug_dir.mkdir(parents=True, exist_ok=True)
    (slug_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8",
    )
    return manifest


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Walk a trace JSON and capture one mss screenshot per "
            "tool_call. Companion to brain.skill_mint."
        ),
    )
    parser.add_argument(
        "--trace", required=True,
        help="Path to trace JSON, or '-' to read from stdin.",
    )
    parser.add_argument(
        "--out", default=None,
        help=(
            "Output root. Defaults to docs/tutorials/_media/ relative to "
            "the ArchHub repo root inferred from this file's location."
        ),
    )
    parser.add_argument(
        "--monitor", type=int, default=1,
        help="mss monitor index (1 = primary). Default: 1.",
    )
    parser.add_argument(
        "--delay", type=float, default=0.0,
        help="Seconds to wait before each capture. Default: 0.",
    )
    args = parser.parse_args(argv)

    trace = _load_trace(args.trace)

    if args.out:
        out_root = Path(args.out)
    else:
        # Walk up to ArchHub repo root from this file.
        out_root = (
            Path(__file__).resolve().parent.parent
            / "docs" / "tutorials" / "_media"
        )

    manifest = record_trace(
        trace, out_root=out_root,
        step_delay_s=args.delay, monitor_idx=args.monitor,
    )
    print(json.dumps(manifest, indent=2))
    return 0 if manifest.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
