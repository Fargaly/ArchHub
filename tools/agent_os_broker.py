#!/usr/bin/env python
"""Elevated local broker for ArchHub governed desktop app launches.

The IFEO gate calls this broker. The broker briefly disables the exact IFEO
filter for the requested app, starts the app through brainwrap governed-strict,
then restores the IFEO filter.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable


CHROMIUM_CHILD_ARG_PREFIXES = ("--type=",)
CHROMIUM_CHILD_ARGS = {"--type"}
WORKSHOP_AUTHORITY_REQUIRED = True


def load_config(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def brainwrap_argv(config: dict[str, Any], payload: dict[str, Any]) -> list[str]:
    return [
        str(config["pythonw"]),
        str(config["brainwrap"]),
        "launch",
        "--governed-strict",
        "--cwd",
        str(payload.get("cwd") or config["workspace_root"]),
        "--",
        str(payload["target"]),
        *[str(item) for item in payload.get("args") or []],
    ]


def _entry_for_app(config: dict[str, Any], app: str) -> dict[str, Any]:
    entries = list(config.get("ifeo_entries") or []) + list(config.get("ifeo_cleanup_entries") or [])
    for entry in entries:
        if entry.get("app") == app:
            return entry
    raise KeyError(f"unknown app: {app}")


def _same_windows_path(a: str, b: str) -> bool:
    return a.replace("/", "\\").rstrip("\\").lower() == b.replace("/", "\\").rstrip("\\").lower()


def validate_payload(config: dict[str, Any], payload: dict[str, Any]) -> None:
    app = str(payload.get("app") or "")
    apps = config.get("apps") if isinstance(config.get("apps"), dict) else {}
    app_config = apps.get(app) if isinstance(apps.get(app), dict) else {}
    configured = str(app_config.get("path") or "")
    requested = str(payload.get("target") or "")
    if not configured:
        raise ValueError(f"unknown app: {app}")
    if not _same_windows_path(configured, requested):
        raise ValueError(f"target mismatch for {app}")
    if config.get("workshop_authority_required", WORKSHOP_AUTHORITY_REQUIRED):
        if payload.get("workshop_authority_required") is not True:
            raise ValueError("workshop authority marker missing")


def is_chromium_child_launch(payload: dict[str, Any]) -> bool:
    if payload.get("launch_kind") == "app_child":
        return True
    for arg in payload.get("args") or []:
        arg = str(arg)
        if arg in CHROMIUM_CHILD_ARGS or any(arg.startswith(prefix) for prefix in CHROMIUM_CHILD_ARG_PREFIXES):
            return True
    return False


def _delete_key_tree(winreg: Any, root: Any, path: str) -> None:
    try:
        with winreg.OpenKey(root, path, 0, winreg.KEY_READ | winreg.KEY_WRITE) as key:
            while True:
                try:
                    child = winreg.EnumKey(key, 0)
                except OSError:
                    break
                _delete_key_tree(winreg, root, path + "\\" + child)
        winreg.DeleteKey(root, path)
    except FileNotFoundError:
        return


def set_ifeo_entry_enabled(config: dict[str, Any], app: str, enabled: bool) -> None:
    if os.name != "nt":
        return
    import winreg  # type: ignore

    entry = _entry_for_app(config, app)
    root_path = (
        "SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\"
        f"Image File Execution Options\\{entry['image_name']}"
    )
    sub_path = root_path + "\\" + entry["subkey_name"]
    if not enabled:
        _delete_key_tree(winreg, winreg.HKEY_LOCAL_MACHINE, sub_path)
        return

    with winreg.CreateKey(winreg.HKEY_LOCAL_MACHINE, root_path) as root_key:
        winreg.SetValueEx(root_key, "UseFilter", 0, winreg.REG_DWORD, 1)
    with winreg.CreateKey(winreg.HKEY_LOCAL_MACHINE, sub_path) as sub_key:
        winreg.SetValueEx(sub_key, "FilterFullPath", 0, winreg.REG_SZ, entry["filter_full_path"])
        winreg.SetValueEx(sub_key, "Debugger", 0, winreg.REG_SZ, entry["debugger"])


def launch_governed(
    config: dict[str, Any],
    payload: dict[str, Any],
    *,
    set_ifeo_fn: Callable[[dict[str, Any], str, bool], None] = set_ifeo_entry_enabled,
    popen_fn: Callable[..., Any] = subprocess.Popen,
) -> dict[str, Any]:
    try:
        validate_payload(config, payload)
        app = str(payload["app"])
        argv = brainwrap_argv(config, payload)
        set_ifeo_fn(config, app, False)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    try:
        proc = popen_fn(
            argv,
            cwd=str(payload.get("cwd") or config["workspace_root"]),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            close_fds=True,
        )
        return {"ok": True, "pid": getattr(proc, "pid", None)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    finally:
        set_ifeo_fn(config, app, True)


def dispatch_launch(
    config: dict[str, Any],
    payload: dict[str, Any],
    *,
    set_ifeo_fn: Callable[[dict[str, Any], str, bool], None] = set_ifeo_entry_enabled,
    popen_fn: Callable[..., Any] = subprocess.Popen,
) -> dict[str, Any]:
    if is_chromium_child_launch(payload):
        return {
            "ok": False,
            "error": "IFEO cannot pass through child process launches; remove the stale IFEO filter for this app",
        }
    return launch_governed(
        config,
        payload,
        set_ifeo_fn=set_ifeo_fn,
        popen_fn=popen_fn,
    )


def reconcile_ifeo_config(
    config: dict[str, Any],
    *,
    set_ifeo_fn: Callable[[dict[str, Any], str, bool], None] = set_ifeo_entry_enabled,
) -> dict[str, Any]:
    try:
        cleanup_entries = list(config.get("ifeo_cleanup_entries") or config.get("ifeo_entries") or [])
        enabled_entries = list(config.get("ifeo_entries") or [])
        for entry in cleanup_entries:
            set_ifeo_fn(config, str(entry["app"]), False)
        for entry in enabled_entries:
            set_ifeo_fn(config, str(entry["app"]), True)
        return {"ok": True, "removed": len(cleanup_entries), "enabled": len(enabled_entries)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


class BrokerHandler(BaseHTTPRequestHandler):
    config: dict[str, Any] = {}

    def log_message(self, _format: str, *_args: Any) -> None:
        return

    def do_POST(self) -> None:  # noqa: N802
        if self.path not in {"/launch", "/reconcile"}:
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length") or "0")
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            if self.path == "/launch":
                result = dispatch_launch(self.config, payload)
            else:
                result = reconcile_ifeo_config(self.config)
        except Exception as exc:  # noqa: BLE001
            result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        body = json.dumps(result).encode("utf-8")
        self.send_response(200 if result.get("ok") else 500)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve(config: dict[str, Any]) -> None:
    url = str(config.get("broker_url") or "http://127.0.0.1:8476")
    port = int(url.rsplit(":", 1)[1].split("/", 1)[0])
    BrokerHandler.config = config
    server = ThreadingHTTPServer(("127.0.0.1", port), BrokerHandler)
    server.serve_forever()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ArchHub governed OS broker.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    serve_cmd = sub.add_parser("serve")
    serve_cmd.add_argument("--config", required=True)
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    if args.cmd == "serve":
        serve(load_config(args.config))
        return 0
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
