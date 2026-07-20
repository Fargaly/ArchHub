#!/usr/bin/env python
"""IFEO gate client for ArchHub governed desktop apps.

Windows Image File Execution Options can redirect an exact executable launch to
this script. The script does not run the vendor app itself. It asks the local
elevated broker to launch the app through brainwrap, and fails closed if the
broker is unavailable.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any, Callable


GATE_BLOCK_EXIT = 78
WORKSHOP_AUTHORITY_REQUIRED = True
CHROMIUM_CHILD_ARG_PREFIXES = ("--type=",)
CHROMIUM_CHILD_ARGS = {"--type"}


def load_config(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _same_windows_path(a: str, b: str) -> bool:
    return a.replace("/", "\\").rstrip("\\").lower() == b.replace("/", "\\").rstrip("\\").lower()


def classify_launch_args(args: list[str]) -> str:
    for arg in args:
        if arg in CHROMIUM_CHILD_ARGS or any(arg.startswith(prefix) for prefix in CHROMIUM_CHILD_ARG_PREFIXES):
            return "app_child"
    return "top_level"


def ifeo_request_payload(
    config: dict[str, Any],
    app: str,
    original_argv: list[str],
) -> dict[str, Any]:
    apps = config.get("apps") if isinstance(config.get("apps"), dict) else {}
    app_config = apps.get(app) if isinstance(apps.get(app), dict) else {}
    target = str(app_config.get("path") or "")
    args = list(original_argv)
    if args and target and _same_windows_path(args[0], target):
        args = args[1:]
    return {
        "app": app,
        "target": target,
        "args": args,
        "cwd": str(config.get("workspace_root") or ""),
        "launch_kind": classify_launch_args(args),
        "governed_strict": True,
        "workshop_authority_required": WORKSHOP_AUTHORITY_REQUIRED,
    }


def post_launch_request(config: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    base = str(config.get("broker_url") or "http://127.0.0.1:8476").rstrip("/")
    req = urllib.request.Request(
        base + "/launch",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def cmd_ifeo_from_config(
    config: dict[str, Any],
    *,
    app: str,
    original_argv: list[str],
    post_fn: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]] = post_launch_request,
) -> int:
    payload = ifeo_request_payload(config, app, original_argv)
    result = post_fn(config, payload)
    if result.get("ok"):
        return 0
    return GATE_BLOCK_EXIT


def _strip_remainder_separator(values: list[str]) -> list[str]:
    if values and values[0] == "--":
        return values[1:]
    return values


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ArchHub IFEO raw-launch gate.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    ifeo = sub.add_parser("ifeo")
    ifeo.add_argument("--config", required=True)
    ifeo.add_argument("--app", required=True)
    ifeo.add_argument("original_argv", nargs=argparse.REMAINDER)
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    if args.cmd == "ifeo":
        return cmd_ifeo_from_config(
            load_config(args.config),
            app=args.app,
            original_argv=_strip_remainder_separator(args.original_argv),
        )
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
