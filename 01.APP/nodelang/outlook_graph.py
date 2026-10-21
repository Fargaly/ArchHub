"""Fixed Microsoft Graph mailbox transport with previewed category writes.

Microsoft's installed SDK owns authentication and its protected token cache.
Only explicit connect can show sign-in. No tokens or caller-supplied URLs cross
this boundary. Inbox reads require an exact expected mailbox.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess
from collections.abc import Mapping

OPERATIONS = frozenset({"prerequisites", "status", "connect", "inbox", "disconnect", "categories", "categorize"})
SCRIPT = Path(__file__).with_name("outlook_graph.ps1")


def _failure(state: str, reason: str) -> dict:
    return {"ok": False, "state": state, "reason": reason, "out": []}


def invoke(operation: str, params: Mapping[str, object]) -> dict:
    if operation not in OPERATIONS:
        return _failure("unsupported", "Unsupported Graph mailbox operation")
    request = {"operation": operation}
    if operation in {"inbox", "categories", "categorize"}:
        account = str(params.get("account") or "").strip()
        if not re.fullmatch(r"[^\s@]{1,254}@[^\s@]{1,253}", account):
            return _failure("account-required", "Select the exact connected mailbox before reading")
        request["account"] = account
    if operation == "inbox":
        folder = params.get("folder", "inbox")
        if folder not in ("inbox", "sentitems"):
            return _failure("invalid-folder", "Select inbox or sentitems")
        request["folder"] = folder
        count = params.get("count", 20)
        if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 50:
            return _failure("invalid-count", "Inbox count must be an integer from 1 to 50")
        request.update(account=account, count=count)
    if operation == "categorize":
        for key in ("message_id", "internet_message_id"):
            value = params.get(key)
            if not isinstance(value, str) or not 1 <= len(value) <= 2048 or any(ord(c) < 32 for c in value):
                return _failure("invalid-message", "Exact Graph and Internet message IDs are required")
            request[key] = value
        for key in ("categories", "expected_categories"):
            value = params.get(key)
            if not isinstance(value, list) or len(value) > 25 or any(
                not isinstance(c, str) or not c.strip() or len(c) > 255 or any(ord(ch) < 32 for ch in c)
                for c in value
            ) or len(set(value)) != len(value):
                return _failure("invalid-categories", "Provide up to 25 distinct category names and the observed baseline")
            request[key] = value
        apply = params.get("apply", False)
        if not isinstance(apply, bool):
            return _failure("invalid-apply", "Apply must be a boolean; preview is the default")
        request["apply"] = apply
    executable = shutil.which("pwsh")
    if not SCRIPT.is_file():
        return _failure("dependency-missing", "ArchHub's Microsoft Graph transport is missing; repair the ArchHub installation")
    if not executable:
        return _failure("dependency-missing", "PowerShell 7 is required for Microsoft Graph; install it before connecting this mailbox")
    if operation == "connect":
        category_access = params.get("category_access", False)
        if not isinstance(category_access, bool):
            return _failure("invalid-consent", "Category access must be an explicit boolean")
        current = invoke("status", {})
        if current.get("state") == "authenticated" and (not category_access or current.get("category_consent")):
            return current
        if current.get("state") == "dependency-missing":
            return current
        try:
            process = subprocess.Popen(
                [executable, "-NoLogo", "-NoProfile", "-File", str(SCRIPT), "-InteractiveSignIn"] + (["-CategoryAccess"] if category_access else []),
                creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
            )
        except OSError:
            return _failure("unavailable", "Microsoft sign-in window could not open")
        return {"ok": True, "state": "sign-in-started", "process_id": process.pid,
                "reason": "Complete Microsoft device sign-in in the opened window, then check status", "out": []}
    try:
        completed = subprocess.run(
            [executable, "-NoLogo", "-NoProfile", "-NonInteractive", "-File", str(SCRIPT)],
            input=json.dumps(request), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=5 if operation == "prerequisites" else 30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired:
        if operation == "categorize" and request.get("apply"):
            return _failure("write-outcome-unknown", "Category write timed out; read the message before retrying")
        return _failure("timeout", "Microsoft Graph operation timed out; check status before retrying sign-in")
    except OSError:
        return _failure("unavailable", "Microsoft Graph transport could not start")
    try:
        result = json.loads(completed.stdout)
    except (ValueError, TypeError):
        if operation == "categorize" and request.get("apply"):
            return _failure("write-outcome-unknown", "No valid write result; reconcile category state before retrying")
        return _failure("unavailable", "Microsoft Graph transport returned no valid result")
    if completed.returncode or not isinstance(result, dict) or not isinstance(result.get("ok"), bool):
        if operation == "categorize" and request.get("apply"):
            return _failure("write-outcome-unknown", "Category transport failed; reconcile state before retrying")
        return _failure("unavailable", "Microsoft Graph transport failed")
    return result


def inbox(params: Mapping[str, object], feeds: Mapping[str, object]):
    result = invoke("inbox", params)
    return result, ("%d inbox item(s) via Microsoft Graph" % len(result.get("out", []))
                    if result.get("ok") else result["reason"])


def status(params: Mapping[str, object], feeds: Mapping[str, object]):
    result = invoke("status", {})
    return result, result.get("reason", result.get("state", "unknown"))


def categories(params: Mapping[str, object], feeds: Mapping[str, object]):
    result = invoke("categories", params)
    return result, result.get("reason", result.get("state", "unknown"))


def categorize(params: Mapping[str, object], feeds: Mapping[str, object]):
    result = invoke("categorize", params)
    return result, result.get("reason", result.get("state", "unknown"))
