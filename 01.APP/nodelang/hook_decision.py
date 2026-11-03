"""The one decision in ArchHub: every agent's tool call and every Approve/Deny.

Each agent's pre-tool hook runs ``hook_decision.py --vendor <name>`` with the event on
stdin (OpenCode's plugin calls the same file). For a tool call ``decide()`` returns:

    verdict   allow | organize | ask | refuse
    action    read | write | shell | delete | publish | send | screen | other
    rules     Cedar forbid ids or Settings mode ids that matched (refuse / ask)
    notes     plain-language guidance for organize / ask
    findings  [{kind: secret|pii|trace, rule, where}]  (values never included)
    scanners  {secrets, pii, policy, trace}: ok | skipped | unavailable
    mode      the run mode from Settings

Policy is Cedar (POLICY below, any forbid wins). Secrets: Betterleaks. PII:
Presidio. Trace rules: the Invariant lethal-trifecta and loop rules over this session's
recent calls, in LlamaFirewall's trace shape (ALLOW / BLOCK). Governance organizes,
never obstructs (F1/F4/A1): only a forbid refuses; a missing scanner never refuses.

Settings parameters (settings/permissions.json, the Settings > Hooks page):
    runMode  Ask first | Accept edits | Plan only   (Claude Code default/acceptEdits/plan,
             Codex untrusted/on-request/read-only)
    tools    {tool name or glob: Off | Ask | Allowed}  (Paperclip MCP gateway; a forbid wins)
Accept edits (the default) adds no prompt: today's behaviour. Ask first asks before a delete,
publish or send, and before any change outside his folders. Plan only refuses every change.
Routine work (read, write, shell, other) in his own folders never prompts (F1/A14).

An Approve/Deny is the same call with ``{"approval": kind, "decision": ...}``: decide()
checks the word and the run mode, then the kind's owner applies the effect (APPROVALS).
An "ask" verdict is one pending card in that same path (settings/ask-approvals.json,
listed with the other approvals). Approve releases the held action once. Deny refuses it.
"""
from __future__ import annotations

import contextvars
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Scans carry no own timeout: each agent's hook entry has its visible "timeout" setting.
# The Cedar perimeter, kept as policy text (any forbid wins; every statement has an @id).
POLICY = r'''
// ArchHub hook perimeter (Cedar). Everything is permitted; a forbid names real harm only.
// Founder rules F1/F4/A1: governance organizes, never obstructs routine work.
// Facts in `context` come from hook_decision.py (Betterleaks, Presidio, trace rules).

// Every statement carries an @id; Cedar names them policy0..N in this order.
@id("baseline-permit")
permit (principal, action, resource);

// A secret or client data going public (push, publish, send, upload).
@id("secret-going-public")
forbid (principal, action in [Action::"publish", Action::"send"], resource)
when { context.secret };

@id("client-data-going-public")
forbid (principal, action in [Action::"publish", Action::"send"], resource)
when { context.client_data };

// Deleting the founder's data.
@id("delete-founder-data")
forbid (principal, action == Action::"delete", resource)
when { context.founder_data };

// Driving the founder's screen (mouse, keyboard, apps) while he works.
@id("use-founder-screen")
forbid (principal, action == Action::"screen", resource);

// Lethal trifecta (Invariant rule, LlamaFirewall trace): private data read, untrusted
// content read, and now an outbound send in the same session.
@id("lethal-trifecta")
forbid (principal, action in [Action::"publish", Action::"send"], resource)
when { context.trifecta };

// S0 (F20): LiteLLM is banned; PyPI litellm 1.82.7 and 1.82.8 (March 2026) shipped a
// credential stealer. Refused for an install command or a dependency-file entry.
@id("banned-package")
forbid (principal, action, resource)
when { context.banned_package };
'''
VENDORS = ("claude-code", "codex", "gemini-cli", "antigravity", "opencode")
_ALIAS = {"claude": "claude-code", "gemini": "gemini-cli"}

_READ = re.compile(r"^(read|glob|grep|ls|list|view|read_file|read_many_files|search_file_content|"
                   r"notebookread|webfetch|websearch|web_fetch|google_web_search)$", re.I)
# Remote reads stay reads, so Ask first does not hold them. Effect tools leave the
# machine (the answer goes back to the remote agent), so client data forbids them.
_REMOTE_READS = frozenset({
    "hosts.status", "hosts.state", "revit.sessions", "connector.rows", "office.read",
    "outlook.inbox", "dropbox.list", "list_sessions", "open_session",
    "read_messages", "workshop.read",
})
_LEAVES = re.compile(r"^(host\.exec|connector\.call|canvas\.run)$", re.I)
_WRITE = re.compile(r"^(write|edit|multiedit|notebookedit|apply_patch|write_file|replace|patch)$", re.I)
_SHELL = re.compile(r"^(bash|powershell|shell|exec_command|run_shell_command|local_shell)$", re.I)
_UNTRUSTED = re.compile(r"(webfetch|websearch|web_fetch|web_search|fetch|browser|navigate|get_page_text|"
                        r"read_page|inbox|get_message|get_thread|slack_read|search_threads)", re.I)
_SEND_TOOL = re.compile(r"(send|post_message|publish|upload|share|create_draft|deploy|create_comment|"
                        r"reply|notion-create|notion-update|create_pages|tweet|categorize)", re.I)
_SCREEN_TOOL = re.compile(r"computer-use__(?!screenshot$|zoom$|cursor_position$|list_granted_applications$)", re.I)
_PUBLISH_CMD = re.compile(
    r"\bgit\s+push\b|\bgh\s+(pr|issue|release|gist|repo)\s+(create|edit|comment|upload)\b|"
    r"\bgh\s+api\b.*-X\s*(POST|PUT|PATCH)|\bnpm\s+publish\b|\btwine\s+upload\b|\bcargo\s+publish\b|"
    r"\bcurl\b.*\s(-d|--data\S*|-F|--form|-T|--upload-file|-X\s*(POST|PUT|PATCH))\b|"
    r"\bInvoke-(WebRequest|RestMethod)\b.*-(Method\s+(Post|Put|Patch)|Body|InFile)\b|\bscp\b", re.I)
_DELETE_CMD = re.compile(
    r"(^|[\s;&|(])(rm|del|erase|rmdir|rd|Remove-Item|ri)\b|\bgit\s+clean\s+-\S*f|"
    r"\bgit\s+reset\s+--hard\b|\bshutil\.rmtree\b|\bformat\s+[a-z]:|"
    r"\[(?:System\.)?IO\.(?:Directory|File)\]::Delete\b", re.I)
# A Python `del` drops a name. It is not a shell verb and not a path.
_PY_DEL_STMT = re.compile(
    r"(?im)(?<![\w.\\/])del[ \t]+(?:\([^)\n;]*\)|[A-Za-z_][\w]*(?:[ \t]*\.[ \t]*[A-Za-z_][\w]*"
    r"|[ \t]*\[[^\]\n;]*\])*(?:[ \t]*,[ \t]*[A-Za-z_][\w]*(?:[ \t]*\.[ \t]*[A-Za-z_][\w]*"
    r"|[ \t]*\[[^\]\n;]*\])*)*)[ \t]*(?=[#;]|$)")
_FILE_REMOVAL_CALL = re.compile(
    r"(?ix)(?:\bos\s*\.\s*(?:remove|unlink|removedirs|rmdir)\s*\("
    r"|\bshutil\s*\.\s*rmtree\s*\("
    r"|(?:pathlib\s*\.\s*)?Path\s*\([^)\n;]*[/\\][^)\n;]*\)\s*\.unlink\s*\()")
_PY_REMOVAL_PATH = re.compile(
    r"(?ix)(?:os\s*\.\s*(?:remove|unlink|removedirs|rmdir)|shutil\s*\.\s*rmtree)"
    r"\s*\(\s*r?(?P<q>['\"])(?P<path>.*?)(?P=q)"
    r"|(?:pathlib\s*\.\s*)?Path\s*\(\s*r?(?P<q2>['\"])(?P<path2>.*?)(?P=q2)\s*\)\s*\.unlink\s*\(")
_PRIVATE_PATH = re.compile(r"(20\.CLIENTS|60\.PERSONAL|62\.LIFE-AREAS)", re.I)
# 60.PERSONAL is his identity and branding. Client project folders (20.CLIENTS)
# and other people's records stay the data that must not go public.
_OTHERS_PATH = re.compile(r"(20\.CLIENTS|62\.LIFE-AREAS)", re.I)
# S0 (F20): LiteLLM is banned. PyPI litellm 1.82.7 and 1.82.8 (March 2026) shipped a
# credential stealer; no agent installs or declares it, by any route.
BANNED_PACKAGES = re.compile(r"(?<![\w.-])litellm(?![\w.-])", re.I)
_INSTALL_CMD = re.compile(r"\b(pip3?|uv|poetry|pipx|pdm|conda|mamba|rye|hatch)\b[^\n;&|]*\b(install|add|sync)\b", re.I)
_DEPENDENCY_FILE = re.compile(r"(requirements[^/\\]*\.(txt|in)|pyproject\.toml|setup\.(py|cfg)|Pipfile(\.lock)?|"
                              r"[^/\\]*\.lock|pylock[^/\\]*\.toml|environment\.ya?ml)$", re.I)
BANNED_REASON = ("LiteLLM is banned (PyPI litellm 1.82.7 and 1.82.8, March 2026, carried a credential stealer); "
                 "route models through nodelang/model_router.py instead")
_PII_PUBLIC = {"EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD", "IBAN_CODE", "US_SSN", "US_PASSPORT", "UK_NHS"}


def _founder_roots(environment):
    home = Path(environment.get("USERPROFILE") or environment.get("HOME") or Path.home())
    local = Path(environment.get("LOCALAPPDATA") or home / "AppData" / "Local")
    return [home / "00.ARCHUB", home / ".archhub", home / ".claude", home / ".codex", home / "Documents",
            home / "Desktop", local / "ArchHub-Test", local / "ArchHub", Path("G:/My Drive"), Path("E:/01.PERSONAL")]


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def normalize(payload: dict, vendor: str) -> dict:
    """Every vendor's pre-tool payload to {session, tool, input, cwd}."""
    tool = payload.get("tool_name") or payload.get("tool") or payload.get("toolName") or ""
    data = payload.get("tool_input")
    if data is None:
        data = payload.get("args", payload.get("toolArgs", payload.get("input", {})))
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except ValueError:
            data = {"value": data}
    return {"vendor": vendor, "session": str(payload.get("session_id") or payload.get("sessionId") or ""),
            "tool": str(tool), "input": data if isinstance(data, dict) else {"value": data},
            "cwd": str(payload.get("cwd") or os.getcwd())}


_DEST_KEYS = ("page_id", "page_url", "url", "parent", "parent_id", "database_id",
              "target", "to", "recipient", "channel", "file_id")
_EMAIL_ADDR = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)


def _destination_blob(data) -> str:
    if not isinstance(data, dict):
        return ""
    parts = []
    for key in _DEST_KEYS:
        held = data.get(key)
        if isinstance(held, str):
            parts.append(held)
    nested = data.get("arguments")
    if isinstance(nested, dict):
        parts.append(_destination_blob(nested))
    return "\n".join(parts)


def _public_target(data) -> bool:
    """A published page or an explicit public share. His notion.so page is still his."""
    if isinstance(data, dict):
        if data.get("public") is True:
            return True
        for key in ("visibility", "permission", "permissions", "access", "share"):
            held = data.get(key)
            if isinstance(held, str) and re.search(r"\b(public|anyone)\b", held, re.I):
                return True
    blob = _destination_blob(data)
    if re.search(r"notion\.site\b", blob, re.I):
        return True
    return bool(re.search(r"https?://(?!(?:www\.)?notion\.so(?:/|$))", blob, re.I))


def _outside_recipient(value) -> bool:
    text = value if isinstance(value, str) else ""
    return bool(_EMAIL_ADDR.search(text) or re.search(r"https?://", text, re.I))


def _own_workspace(tool: str, data) -> bool:
    """His Notion, his Drive, his mailbox drafts, his Workshop. Not a public send.

    A Workshop message that names a folder is not the file leaving his account.
    """
    name = tool.casefold()
    if "categorize" in name:
        return True
    connector = str(data.get("connector") or "").casefold() if isinstance(data, dict) else ""
    if "workshop" in name or connector == "workshop":
        return True
    leaf = re.split(r"[._]", name.split("__")[-1])[-1]
    body = data.get("text") or data.get("message") or data.get("body") if isinstance(data, dict) else None
    if (leaf == "send" and isinstance(data, dict) and "to" in data and isinstance(body, str)
            and not _outside_recipient(data.get("to"))):
        return True
    if "draft" in name and not re.search(r"send[-_]?draft|submit", name):
        return True
    if re.search(r"google[-_]?drive|gdrive", name) or re.search(r"(?:^|[._])drive(?:[._]|$)", name):
        if re.search(r"share|permission|publish", name) or _public_target(data):
            return False
        return True
    if "notion" in name:
        return not _public_target(data)
    return False


def _untrusted_content(tool: str) -> bool:
    """Outside web and mail. Fetching his Notion page is not untrusted web content."""
    name = tool.casefold()
    if "notion" in name and re.search(r"fetch|read|get|search|query", name):
        return False
    return bool(_UNTRUSTED.search(tool))


def _leaves_his_account(action: str, tool: str, data) -> bool:
    """Public web, a public repo, a public post, or a recipient outside his account."""
    return action in ("publish", "send") and not _own_workspace(tool, data)


def classify(event: dict, environment) -> tuple[str, dict]:
    tool, data = event["tool"], event["input"]
    text = "\n".join(_strings(data))
    command = str(data.get("command") or data.get("cmd") or "") if isinstance(data, dict) else ""
    if isinstance(data.get("command"), list):
        command = " ".join(map(str, data["command"]))
    target = str(data.get("file_path") or data.get("path") or data.get("filePath") or "") if isinstance(data, dict) else ""
    banned = bool((_INSTALL_CMD.search(command) and BANNED_PACKAGES.search(command))
                  or (_DEPENDENCY_FILE.search(target) and BANNED_PACKAGES.search(text))
                  or (tool.lower() == "apply_patch" and re.search(r"(requirements|pyproject|\.lock)", text, re.I)
                      and re.search(r"^\+.*" + BANNED_PACKAGES.pattern, text, re.I | re.M)))
    facts = {"banned_package": banned, "text": text, "command": command,
             "untrusted": _untrusted_content(tool),
             "private": bool(_PRIVATE_PATH.search(text)),
             "others": bool(_OTHERS_PATH.search(text))}
    if _SCREEN_TOOL.search(tool):
        return "screen", facts
    if _SHELL.match(tool):
        if _PUBLISH_CMD.search(command):
            return "publish", facts
        if _deletes_files(command):
            return "delete", facts
        return "shell", facts
    if _WRITE.match(tool):
        return "write", facts
    if (tool in _REMOTE_READS or _READ.match(tool)
            or tool.lower().endswith(("_read", "_list", "_search", "_get", "ping", "info"))):
        return "read", facts
    if _LEAVES.match(tool) or _SEND_TOOL.search(tool):
        return "send", facts
    return "other", facts


# Machine cleanup allowlist. Paths live in the file; this is only where to read them.
# Override with the cleanup_candidates argument or ARCHHUB_CLEANUP_CANDIDATES.
_CLEANUP_CANDIDATES = Path(
    r"C:\Users\fargaly\00.ARCHUB\00.GOVERNANCE\05.WORKSPACE-REPORTS"
    r"\machine-cleanup-candidates-2026-11-02.json")
_DELETE_VERBS = {"rm", "del", "erase", "rmdir", "rd", "remove-item", "ri"}
_LIST_VERBS = {"get-childitem", "gci", "ls", "dir"}
_UNIX_SWITCHES = {
    "-r", "-R", "-f", "-rf", "-fr", "-rr", "-i", "-I", "-v", "-d", "-x", "-X",
    "--recursive", "--force", "--dir", "--dry-run", "--preserve-root",
    "--no-preserve-root", "--one-file-system",
}
_PATH_PARAMS = ("literalpath", "path", "pspath")
_PATTERN_PARAMS = ("filter", "include", "exclude")
_VALUE_PARAMS = (
    "erroraction", "ea", "warningaction", "wa", "errorvariable", "ev",
    "warningvariable", "wv", "outvariable", "ov", "outbuffer", "ob",
    "pipelinevariable", "pv", "informationaction", "infa", "informationvariable", "iv",
    "depth", "attributes", "credential", "encoding",
)
_SWITCH_PARAMS = (
    "recurse", "force", "whatif", "verbose", "debug", "file", "directory", "hidden",
    "readonly", "system", "name", "container", "followsymlink", "casesensitive", "confirm",
)
_QUOTED_DELETE = re.compile(
    r"""(?:\[(?:System\.)?IO\.(?:Directory|File)\]::Delete|shutil\.rmtree)\s*\(\s*r?(?P<q>['"])(?P<path>.*?)(?P=q)""",
    re.I)
_FORMAT_DRIVE = re.compile(r"\bformat\s+([a-zA-Z]):", re.I)
_STATEMENT = {";", "&&", "||", "\n"}


def _expand_braces(text: str) -> list[str]:
    match = re.search(r"\{([^{}]+)\}", text)
    if not match:
        return [text]
    prefix, suffix = text[:match.start()], text[match.end():]
    expanded = []
    for part in match.group(1).split(","):
        part = part.strip()
        if part:
            expanded.extend(_expand_braces(prefix + part + suffix))
    return expanded or [text]


def _allowlist_entries(environment, cleanup_candidates) -> list[str]:
    """Candidate paths from the cleanup file. OtherReview stays preserved."""
    if cleanup_candidates is not None:
        source = cleanup_candidates
    else:
        source = environment.get("ARCHHUB_CLEANUP_CANDIDATES") or _CLEANUP_CANDIDATES
    try:
        data = json.loads(Path(source).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError):
        return []
    rows = data.get("Candidates") if isinstance(data, dict) else None
    entries = []
    for row in rows or []:
        raw = row.get("Path") if isinstance(row, dict) else None
        if raw:
            entries.extend(_expand_braces(str(raw)))
    return entries


def _disposable_roots(environment) -> list[Path]:
    """Temp, crash dumps, and regenerable caches. Project folders are not in this list."""
    home = Path(environment.get("USERPROFILE") or environment.get("HOME") or Path.home())
    local = Path(environment.get("LOCALAPPDATA") or home / "AppData" / "Local")
    roaming = Path(environment.get("APPDATA") or home / "AppData" / "Roaming")
    roots = []
    for key in ("TEMP", "TMP"):
        if environment.get(key):
            roots.append(Path(environment[key]))
    if not roots:
        roots.append(Path(tempfile.gettempdir()))
    roots.extend([
        local / "Temp", local / "CrashDumps", local / "npm-cache", roaming / "npm-cache",
        local / "ms-playwright", local / "pip" / "Cache", local / "pip" / "cache",
        roaming / "pip" / "Cache", roaming / "pip" / "cache", home / ".cache" / "pip",
        home / ".cache" / "pytest", local / "pytest-cache", local / "node-compile-cache",
        local / "Temp" / "node-compile-cache", local / "Temp" / "playwright-transform-cache",
    ])
    return roots


def _norm(path: Path) -> str:
    try:
        text = os.path.abspath(os.fspath(path))
    except (OSError, ValueError):
        text = os.fspath(path)
    text = os.path.normcase(os.path.normpath(text))
    if os.name == "nt" and len(text) == 2 and text[1] == ":":
        return text + os.sep
    if text.endswith(os.sep) and not (os.name == "nt" and len(text) == 3 and text[1] == ":"):
        return text.rstrip(os.sep)
    return text


def _same_tree(path: Path, root: Path) -> bool:
    left, right = _norm(path), _norm(root)
    return bool(left) and bool(right) and (left == right or left.startswith(right + os.sep))


def _tokenize(command: str) -> list[str]:
    tokens, i, n = [], 0, len(command)
    while i < n:
        ch = command[i]
        if ch in "\r\n":
            while i < n and command[i] in "\r\n":
                i += 1
            tokens.append("\n")
            continue
        if ch.isspace():
            i += 1
            continue
        if command.startswith("&&", i) or command.startswith("||", i):
            tokens.append(command[i:i + 2])
            i += 2
            continue
        if ch in "|;":
            tokens.append(ch)
            i += 1
            continue
        if ch in "'\"":
            quote = ch
            i += 1
            start = i
            while i < n and command[i] != quote:
                i += 1
            tokens.append(command[start:i])
            i = i + 1 if i < n else i
            continue
        start = i
        while i < n and not command[i].isspace() and command[i] not in "|;\r\n\"'" \
                and not command.startswith("&&", i) and not command.startswith("||", i):
            i += 1
        tokens.append(command[start:i])
    return tokens


def _groups(tokens: list[str], separators: set[str]) -> list[list[str]]:
    groups, current = [], []
    for token in tokens:
        if token in separators:
            if current:
                groups.append(current)
            current = []
        else:
            current.append(token)
    if current:
        groups.append(current)
    return groups


def _command_name(token: str) -> str | None:
    """A command word. Path arguments, even ones whose leaf is `rd`, are not commands."""
    if not token or token[0] in "-/$'\"()":
        return None
    if any(ch in token for ch in "()[]{}$"):
        return None
    leaf = token.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
    executable = leaf.lower().endswith((".exe", ".cmd", ".bat", ".ps1"))
    if ("\\" in token or "/" in token or ":" in token) and not executable:
        return None
    if executable:
        leaf = leaf.rsplit(".", 1)[0]
    return leaf.lower()


def _is_path_token(token: str) -> bool:
    if not token or token in {".", ".."}:
        return token in {".", ".."}
    if token.startswith("-") or re.fullmatch(r"/[a-zA-Z](?::.*)?", token):
        return False
    if any(ch in token for ch in "()[]{}") or ("$" in token and not re.match(r"(?i)^\$env:\w+", token)):
        return False
    if "::" in token or token.startswith(">") or token.startswith("2>"):
        return False
    # (Get-PSDrive C).Free/1GB and similar member expressions, not .\relative paths.
    if token.startswith(".") and not token.startswith(("./", ".\\", "../", "..\\")):
        if "/" in token or "\\" in token:
            return False
    return True


def _unique_param(name: str, options: tuple[str, ...]) -> str | None:
    if name in options:
        return name
    hits = [item for item in options if item.startswith(name)]
    return hits[0] if len(hits) == 1 else None


def _param_kind(name: str) -> str:
    if _unique_param(name, _PATH_PARAMS):
        return "path"
    if _unique_param(name, _PATTERN_PARAMS):
        return "pattern"
    if _unique_param(name, _VALUE_PARAMS):
        return "value"
    return "switch"


def _split_param(token: str) -> tuple[str, str | None]:
    body = token[2:] if token.startswith("--") else token[1:]
    for sep in (":", "="):
        if sep in body:
            name, value = body.split(sep, 1)
            return name.lower(), value
    return body.lower(), None


def _parse_paths(tokens: list[str]) -> list[str]:
    """Path arguments only. -Filter/-Include/-Exclude and other flags are not paths."""
    paths, i = [], 0
    while i < len(tokens):
        token = tokens[i]
        if token == "--":
            paths.extend(item for item in tokens[i + 1:] if _is_path_token(item))
            break
        if token in _UNIX_SWITCHES or re.fullmatch(r"/[a-zA-Z](?::.*)?", token):
            i += 1
            continue
        if token.startswith("-"):
            name, inline = _split_param(token)
            kind = _param_kind(name)
            if kind == "path":
                value = inline if inline else (tokens[i + 1] if i + 1 < len(tokens) else "")
                if not inline and value:
                    i += 1
                if value and _is_path_token(value):
                    paths.append(value)
            elif kind in ("pattern", "value") and not inline and i + 1 < len(tokens) \
                    and not tokens[i + 1].startswith("-"):
                i += 1
            i += 1
            continue
        if _is_path_token(token):
            paths.append(token)
        i += 1
    return paths


def _parse_git(tokens: list[str], index: int, cwd: str):
    """git clean / git reset --hard. -e patterns are not paths. No path means the repo."""
    i = index + 1
    repo = None
    while i < len(tokens):
        token = tokens[i]
        if token == "-C" and i + 1 < len(tokens):
            repo = tokens[i + 1]
            i += 2
            continue
        if token == "--work-tree" and i + 1 < len(tokens):
            repo = tokens[i + 1]
            i += 2
            continue
        if token.startswith("-"):
            i += 1
            continue
        break
    if i >= len(tokens):
        return None
    sub = tokens[i].lower()
    i += 1
    if sub == "clean":
        paths = []
        while i < len(tokens):
            token = tokens[i]
            if token == "--":
                paths.extend(item for item in tokens[i + 1:] if _is_path_token(item))
                break
            if token in ("-e", "--exclude"):
                i += 2
                continue
            if token.startswith("--exclude="):
                i += 1
                continue
            if token.startswith("-"):
                i += 1
                continue
            if _is_path_token(token):
                paths.append(token)
            i += 1
        return "git-clean", paths, repo or cwd
    if sub == "reset":
        hard = False
        paths = []
        while i < len(tokens) and tokens[i] != "--":
            if tokens[i] == "--hard":
                hard = True
            elif not tokens[i].startswith("-") and _is_path_token(tokens[i]):
                paths.append(tokens[i])
            i += 1
        if tokens[i:i + 1] == ["--"]:
            paths.extend(item for item in tokens[i + 1:] if _is_path_token(item))
        if hard:
            return "git-reset", paths, repo or cwd
    return None


def _classify_stage(tokens: list[str], cwd: str):
    named = [(i, name) for i, token in enumerate(tokens) if (name := _command_name(token))]
    for index, name in named:
        if name == "git":
            parsed = _parse_git(tokens, index, cwd)
            if parsed:
                return parsed
    for index, name in named:
        if name in _DELETE_VERBS:
            return "delete", _parse_paths(tokens[index + 1:]), None
    for index, name in named:
        if name in _LIST_VERBS:
            return "list", _parse_paths(tokens[index + 1:]), None
    return "other", [], None


def _blank(chars: list[str], start: int, end: int) -> None:
    for index in range(start, min(end, len(chars))):
        if chars[index] != "\n":
            chars[index] = " "


def _blank_quoted(chars: list[str], command: str, start: int) -> int:
    """Blank one quoted, here-string, or bare argument. Returns the index after it."""
    if start >= len(command):
        return start
    if command.startswith(('@"', "@'"), start):
        mark = command[start + 1] + "@"
        end = command.find(mark, start + 2)
        end = len(command) if end < 0 else end + 2
        _blank(chars, start, end)
        return end
    if command[start] in "'\"":
        quote = command[start]
        index = start + 1
        while index < len(command):
            if command[index] == "\\" and quote == '"':
                index += 2
                continue
            if command[index] == quote:
                index += 1
                break
            index += 1
        _blank(chars, start, index)
        return index
    index = start
    while index < len(command) and not command[index].isspace():
        index += 1
    _blank(chars, start, index)
    return index


def _python_regions_blanked(command: str) -> str:
    """Python -c text, a heredoc, or a here-string is source, not a shell delete verb."""
    chars = list(command)
    for match in re.finditer(r"<<-?\s*['\"]?(\w+)['\"]?", command):
        newline = command.find("\n", match.end())
        if newline < 0:
            continue
        close = re.search(r"(?m)^%s\s*$" % re.escape(match.group(1)), command[newline + 1:])
        if close:
            _blank(chars, newline + 1, newline + 1 + close.start())
    for match in re.finditer(r"(?i)\b(?:python(?:3)?|py)\b[^\n]*?\s-c\s+", command):
        _blank_quoted(chars, command, match.end())
    return "".join(chars)


def _deletes_files(command: str) -> bool:
    """Real deletes only: a shell verb at command position, or a file-removal call with a path.

    A Python ``del`` of a name, inside python -c, a heredoc, or a script, is not one of those.
    """
    if _FILE_REMOVAL_CALL.search(command):
        return True
    shell = _python_regions_blanked(command)
    if re.search(r"(?i)\b(?:import|from|def|class)\b|\bopen\s*\(|\bpathlib\b", command):
        shell = _PY_DEL_STMT.sub(" ", shell)
    return bool(_DELETE_CMD.search(shell))


def _delete_targets(command: str, cwd: str) -> list[str]:
    """Paths a delete will actually remove. Filters, expressions, and other quotes are ignored."""
    targets = [match.group("path") for match in _QUOTED_DELETE.finditer(command)]
    for match in _PY_REMOVAL_PATH.finditer(command):
        targets.append(match.group("path") or match.group("path2"))
    targets += ["%s:\\" % match.group(1) for match in _FORMAT_DRIVE.finditer(command)]
    for statement in _groups(_tokenize(command), _STATEMENT):
        previous = None
        for stage in _groups(statement, {"|"}):
            kind, paths, repo = _classify_stage(stage, cwd)
            if kind == "list":
                previous = paths
            elif kind == "delete":
                if paths:
                    targets.extend(paths)
                elif previous is not None:
                    # Get-ChildItem/ls with no path lists the current directory.
                    targets.extend(previous or [cwd])
                previous = None
            elif kind in ("git-clean", "git-reset"):
                targets.extend(paths or [repo or cwd])
                previous = None
    return targets


def _resolve_target(raw: str, cwd: str, environment) -> Path:
    text = str(raw).strip()

    def repl(match):
        return str(environment.get(match.group(1), match.group(0)))

    text = re.sub(r"%([^%]+)%", repl, text)
    text = re.sub(r"\$env:(\w+)", repl, text, flags=re.I)
    if text == "~" or text.startswith(("~/", "~\\")):
        home = environment.get("USERPROFILE") or environment.get("HOME") or str(Path.home())
        text = str(home) + text[1:]
    path = Path(text)
    if not path.is_absolute():
        path = Path(cwd) / path
    return path


def _is_free(path: Path, disposable: list[Path], allowlist: list[str]) -> bool:
    if any(_same_tree(path, root) for root in disposable):
        return True
    norm = _norm(path)
    for entry in allowlist:
        if any(ch in entry for ch in "*?"):
            if fnmatch.fnmatch(norm, os.path.normcase(os.path.normpath(entry))):
                return True
            continue
        if _same_tree(path, Path(entry)):
            return True
    return False


def _inside_protected_repo(path: Path, disposable: list[Path]) -> bool:
    """Repo sources stay protected. A git worktree under temp is disposable."""
    cursor = path
    for _ in range(64):
        try:
            tracked = (cursor / ".git").exists()
        except OSError:
            return False
        if tracked:
            return not any(_same_tree(cursor, root) for root in disposable)
        parent = cursor.parent
        if parent == cursor:
            return False
        cursor = parent
    return False


# Plot-and-Publish CSVs are regenerable logs. The isolate profile and the
# Autodesk local folder also hold PAT/hatch, settings, profiles, models, first90.
_PLOT_LOG_ROOT = Path(r"E:\01.PERSONAL\BBC4\00-OUT\10.WIP-408\_STAGING\_CORE_PROFILE")
_KEEP_NEWEST_PLOT_LOGS = re.compile(
    r"sort-object\b[\s\S]{0,240}?lastwritetime\b[\s\S]{0,160}?-descending\b[\s\S]{0,160}?"
    r"select(?:-object)?\b[\s\S]{0,80}?-skip\b\s+3\b",
    re.I)
_PLOT_FILTER = re.compile(r"plotandpublish\*\.csv", re.I)
_PLOT_CSV = re.compile(r"plotandpublish.*\.csv$", re.I)
_PROTECTED_ARTIFACT = re.compile(
    r"(?:^|[\\/])first90(?:[\\/]|$)"
    r"|(?:^|[\\/])settings(?:[\\/]|$)"
    r"|(?:^|[\\/])active-?profiles?(?:[\\/]|$)"
    r"|\.(?:pat|dwg|dxf|dgn|rvt|rfa|rte|ifc|arg|aws)\b"
    r"|hatch",
    re.I)
_FILTER_ARG = re.compile(r"-(?:filter|include)\b\s+[\"']?([^\s\"']+)", re.I)


def _plot_log_roots(environment) -> list[Path]:
    home = Path(environment.get("USERPROFILE") or environment.get("HOME") or Path.home())
    local = Path(environment.get("LOCALAPPDATA") or home / "AppData" / "Local")
    return [_PLOT_LOG_ROOT, local / "Autodesk"]


def _plot_publish_override(command: str, cwd: str, environment) -> bool | None:
    """False when old PlotandPublish logs are deleted and the newest 3 stay.

    True when the delete hits PAT/hatch, settings, an active profile, a model,
    or first90 under the isolate profile or the Autodesk local folder.
    """
    roots = _plot_log_roots(environment)
    resolved = [_resolve_target(raw, cwd, environment) for raw in _delete_targets(command, cwd)]
    under = [path for path in resolved if any(_same_tree(path, root) for root in roots)]
    if not under:
        return None
    filters = _FILTER_ARG.findall(command)
    protected = any(_PROTECTED_ARTIFACT.search(str(path)) for path in under) or any(
        _PROTECTED_ARTIFACT.search(item) for item in filters)
    if protected:
        return True
    keeps_newest = _PLOT_FILTER.search(command) and _KEEP_NEWEST_PLOT_LOGS.search(command)
    if keeps_newest and len(under) == len(resolved):
        return False
    if resolved and all(_PLOT_CSV.search(str(path)) for path in resolved):
        return not bool(_KEEP_NEWEST_PLOT_LOGS.search(command))
    if any(_norm(path) == _norm(root) for path in resolved for root in roots):
        return True
    return None


def founder_data_targeted(command: str, cwd: str, environment, cleanup_candidates=None) -> bool:
    """A delete aimed at the founder's data.

    Only the delete verb's path arguments count, plus the path of a Get-ChildItem/ls
    that pipes into Remove-Item. Temp, crash dumps, regenerable caches, and paths
    from the cleanup-candidate file are free. Old PlotandPublish logs are free when
    the newest three are kept. Client, personal, and ArchHub data, repo sources
    outside temp, and PAT/hatch, settings, profiles, models, and first90 stay protected.
    """
    plot = _plot_publish_override(command, cwd, environment)
    if plot is not None:
        return plot
    disposable = _disposable_roots(environment)
    allowlist = _allowlist_entries(environment, cleanup_candidates)
    roots = _founder_roots(environment)
    for raw in _delete_targets(command, cwd):
        path = _resolve_target(raw, cwd, environment)
        inside = any(_same_tree(path, root) for root in roots)
        contains = any(_same_tree(root, path) for root in roots)
        # A cache that sits inside a client or project folder is still his data.
        if _is_free(path, disposable, allowlist) and not inside and not contains:
            continue
        if inside or contains:
            return True
        if _inside_protected_repo(path, disposable):
            return True
    return False


def _under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root.resolve() if root.exists() else root)
        return True
    except ValueError:
        return False


# ---- Settings parameters: run mode and per-tool modes ---------------------------------

RUN_MODES = ("Ask first", "Accept edits", "Plan only")
TOOL_MODES = ("Off", "Ask", "Allowed")
DEFAULT_PERMISSIONS = {"runMode": "Accept edits", "tools": {}}
_ROUTINE = ("read", "write", "shell", "other")


def _settings_dir(environment) -> Path:
    home = Path(environment.get("USERPROFILE") or environment.get("HOME") or Path.home())
    return Path(environment.get("LOCALAPPDATA") or home / "AppData" / "Local") / "ArchHub" / "settings"


def checked_permissions(values) -> dict:
    """The permissions parameters, validated; raises ValueError naming what is wrong."""
    if type(values) is not dict or set(values) - set(DEFAULT_PERMISSIONS):
        raise ValueError("Permissions are a run mode and a list of tool modes.")
    values = {**DEFAULT_PERMISSIONS, **values}
    tools = values["tools"]
    if values["runMode"] not in RUN_MODES:
        raise ValueError("Choose Ask first, Accept edits or Plan only.")
    if (type(tools) is not dict or len(tools) > 200
            or any(type(k) is not str or not k.strip() or len(k) > 200 or v not in TOOL_MODES for k, v in tools.items())):
        raise ValueError("Each tool mode is a tool name (or pattern) set to Off, Ask or Allowed.")
    return {"runMode": values["runMode"], "tools": dict(tools)}


def read_permissions(environment=None, path: Path | None = None) -> dict:
    """Settings > Hooks parameters; a missing or broken file is the default (never blocks)."""
    environment = os.environ if environment is None else environment
    try:
        return checked_permissions(json.loads((path or _settings_dir(environment) / "permissions.json")
                                              .read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        return dict(DEFAULT_PERMISSIONS, tools={})


def write_permissions(changes, environment=None, path: Path | None = None) -> dict:
    environment = os.environ if environment is None else environment
    path = path or _settings_dir(environment) / "permissions.json"
    if type(changes) is not dict:
        raise ValueError("Permissions are a run mode and a list of tool modes.")
    values = checked_permissions({**read_permissions(environment, path), **changes})
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    try:
        temporary.write_text(json.dumps(values, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return values


def own_folder(event: dict, environment) -> bool:
    """The call's folder is one of his: his roots, a registered workspace, or temp (lane worktrees)."""
    data = event["input"]
    raw = str(data.get("file_path") or data.get("path") or data.get("filePath") or data.get("workdir")
              or data.get("cwd") or event["cwd"])
    if _PRIVATE_PATH.search(raw):
        return False  # client and personal folders are a real boundary, never routine
    roots = _founder_roots(environment) + [Path(environment.get("TEMP") or tempfile.gettempdir())]
    try:  # no registered workspaces yet: his built-in roots still count
        held = json.loads((_settings_dir(environment) / "workspaces.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        held = {}
    rows = held.get("roots") if isinstance(held, dict) else None
    roots += [Path(r["path"]) for r in rows or [] if isinstance(r, dict) and r.get("path")]
    path = Path(raw) if Path(raw).is_absolute() else Path(event["cwd"]) / raw
    try:
        path = path.resolve()
    except OSError:
        return False
    return any(_under(path, root) for root in roots)


def mode_verdict(event: dict, action: str, permissions: dict, environment):
    """(verdict, rule) from the Settings parameters, or None when they change nothing."""
    tool = event["tool"].lower()
    for pattern, mode in permissions["tools"].items():
        if fnmatch.fnmatchcase(tool, pattern.lower()):
            return None if mode == "Allowed" else ("refuse", "tool-off") if mode == "Off" else ("ask", "tool-ask")
    run = permissions["runMode"]
    if action == "read" or run == "Accept edits":  # Accept edits adds no prompt; the agent's own mode stays
        return None
    if run == "Plan only":
        return "refuse", "plan-only"
    if action in _ROUTINE and own_folder(event, environment):
        return None  # F1/A14: his own agents' routine work in his folders never prompts
    return "ask", "ask-first"


# ---- scanners -----------------------------------------------------------------------

def betterleaks_path(environment) -> Path | None:
    for candidate in (environment.get("ARCHHUB_BETTERLEAKS"),
                      HERE.parent / "runtime" / "betterleaks" / "betterleaks.exe"):
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    return None


_SCANNER_VERSIONS: dict[str, str] = {}


def scanner_version(exe: Path) -> str:
    """The installed Betterleaks version, cached for this hook process."""
    key = str(exe)
    if key not in _SCANNER_VERSIONS:
        try:
            run = subprocess.run([key, "version"], capture_output=True)
            match = re.search(r"(\d+\.\d+\.\d+)", (run.stdout or b"").decode("utf-8", "replace"))
            _SCANNER_VERSIONS[key] = match.group(1) if match and run.returncode == 0 else ""
        except OSError:
            _SCANNER_VERSIONS[key] = ""
    return _SCANNER_VERSIONS[key]


def scan_secrets(text: str, environment, *, git_cwd: str | None = None):
    """Betterleaks on the text (stdin) or on the commits a push would publish.

    Returns (state, findings, version). version is empty unless the scan ran.
    """
    exe = betterleaks_path(environment)
    if exe is None:
        return "unavailable", [], ""
    with tempfile.TemporaryDirectory(prefix="archhub-hook-") as tmp:
        report = Path(tmp) / "report.json"
        base = [str(exe), "--no-banner", "-f", "json", "-r", str(report), "--redact"]
        if git_cwd:
            upstream = subprocess.run(["git", "-C", git_cwd, "rev-parse", "--verify", "-q", "@{u}"],
                                      capture_output=True).returncode == 0
            # No upstream: the last 20 commits stand in for what the push would publish.
            span = "@{u}..HEAD" if upstream else "--max-count=20"
            run = subprocess.run([str(exe), "git", git_cwd, "--log-opts", span] + base[1:],
                                 capture_output=True, cwd=git_cwd)
        else:
            run = subprocess.run([str(exe), "stdin"] + base[1:], input=text.encode("utf-8", "replace"),
                                 capture_output=True)
        if run.returncode not in (0, 1) or not report.exists():
            return "unavailable", [], ""
        found = json.loads(report.read_text(encoding="utf-8") or "[]") or []
    return "ok", [{"kind": "secret", "rule": f.get("RuleID"), "where": f.get("File") or "input"} for f in found], scanner_version(exe)


_ANALYZER = None


def scan_pii(text: str):
    """Presidio pattern recognizers on a blank spaCy pipeline (no model download).

    shortcut: no NER model, so person names and places are not detected; ship
    en_core_web_sm in the wheelhouse when names must be caught.
    """
    global _ANALYZER
    try:
        if _ANALYZER is None:
            import spacy
            from presidio_analyzer import AnalyzerEngine
            from presidio_analyzer.nlp_engine import SpacyNlpEngine

            class BlankEngine(SpacyNlpEngine):
                def load(self):
                    self.nlp = {"en": spacy.blank("en")}

            engine = BlankEngine(models=[{"lang_code": "en", "model_name": "blank"}])
            engine.load()
            _ANALYZER = AnalyzerEngine(nlp_engine=engine, supported_languages=["en"])
        results = _ANALYZER.analyze(text=text[:200000], language="en", entities=sorted(_PII_PUBLIC))
    except Exception:
        return "unavailable", []
    return "ok", [{"kind": "pii", "rule": r.entity_type, "where": "input"} for r in results if r.score >= 0.5]


def cedar_forbids(action: str, context: dict, vendor: str):
    """Cedar decision; returns (state, matched forbid ids)."""
    try:
        import cedarpy
    except ImportError:
        return "unavailable", []
    policies = POLICY
    request = {"principal": 'Agent::"%s"' % vendor, "action": 'Action::"%s"' % action,
               "resource": 'Target::"tool"', "context": context}
    result = cedarpy.is_authorized(request, policies, [])
    if result.decision == cedarpy.Decision.Allow:
        return "ok", []
    ids = re.findall(r'@id\("([^"]+)"\)', policies)
    reasons = list(getattr(result.diagnostics, "reasons", []) or [])
    named = [ids[int(r.replace("policy", ""))] for r in reasons if re.fullmatch(r"policy\d+", r)
             and int(r.replace("policy", "")) < len(ids)]
    return "ok", named or reasons or ["forbid"]


# ---- trace (session memory for the Invariant rules) --------------------------------

def _trace_path(session: str, environment) -> Path:
    base = Path(environment.get("ARCHHUB_HOOK_STATE") or
                Path(environment.get("LOCALAPPDATA") or tempfile.gettempdir()) / "ArchHub" / "runtime-context" / "hook-decision")
    return base / (hashlib.sha256(session.encode()).hexdigest()[:32] + ".json")


def trace_rules(event, action, facts, environment):
    """Return (trifecta, looping) and remember this call; values are never stored."""
    if not event["session"]:
        return False, False, "skipped"
    path = _trace_path(event["session"], environment)
    try:
        trace = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        trace = []
    key = hashlib.sha256((event["tool"] + "\0" + json.dumps(event["input"], sort_keys=True, default=str)).encode()).hexdigest()
    private = facts["private"] or any(t.get("private") for t in trace)
    untrusted = facts["untrusted"] or any(t.get("untrusted") for t in trace)
    # His own workspace is not the outbound leg. The trifecta is private data,
    # untrusted web content, and a public or external send.
    trifecta = _leaves_his_account(action, event["tool"], event["input"]) and private and untrusted
    looping = sum(1 for t in trace[-9:] if t.get("key") == key) >= 4
    trace = (trace + [{"at": time.time(), "tool": event["tool"], "action": action, "key": key,
                       "private": facts["private"], "untrusted": facts["untrusted"]}])[-50:]
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(trace), encoding="utf-8")
    except OSError as exc:  # the decision still stands; the record says the trace was not kept
        return trifecta, looping, "unwritable: " + type(exc).__name__
    return trifecta, looping, "ok"


# ---- the one function ----------------------------------------------------------------

def decide(payload: dict, vendor: str = "", *, environment=None):
    """A tool call (pre-tool payload + vendor) or an Approve/Deny ({"approval": kind, ...})."""
    environment = os.environ if environment is None else environment
    if "approval" in payload:
        return _decide_approval(payload, environment)
    vendor = _ALIAS.get(vendor, vendor)
    event = normalize(payload, vendor)
    action, facts = classify(event, environment)
    scanners = {"secrets": "skipped", "pii": "skipped", "policy": "skipped", "trace": "skipped"}
    findings, notes = [], []
    secret_version = ""
    if action in ("write", "publish", "send", "shell", "other") and facts["text"]:
        git_cwd = event["cwd"] if action == "publish" and re.search(r"\bgit\s+push\b", facts["command"]) else None
        scanners["secrets"], found, seen = scan_secrets(facts["text"], environment)
        secret_version = seen or secret_version
        findings += found
        if git_cwd and scanners["secrets"] == "ok":  # the commits a push would publish
            scanners["secrets"], found, seen = scan_secrets("", environment, git_cwd=git_cwd)
            secret_version = seen or secret_version
            findings += found
    # Presidio costs ~7 s to load per hook process; text with no @, + or digit run has no PII it finds.
    if action in ("publish", "send") and re.search(r"@|\+\d|\d{4,}", facts["text"]):
        scanners["pii"], found = scan_pii(facts["text"])
        findings += found
    trifecta, looping, scanners["trace"] = trace_rules(event, action, facts, environment)
    if trifecta:
        findings.append({"kind": "trace", "rule": "lethal-trifecta", "where": "session"})
    if looping:
        findings.append({"kind": "trace", "rule": "loop", "where": "session"})
    secret = any(f["kind"] == "secret" for f in findings)
    # 60.PERSONAL is his. Client folders, other people's records, and PII are not.
    client = facts["others"] or any(f["kind"] == "pii" for f in findings)
    # Categorize, drafts, his Drive, his Notion and Workshop stay in his account.
    # A secret on any outbound send is still refused. Ask first can hold a real send.
    goes_public = _leaves_his_account(action, event["tool"], event["input"])
    context = {"secret": secret, "client_data": bool(client and goes_public),
               "founder_data": action == "delete" and founder_data_targeted(facts["command"], event["cwd"], environment),
               "trifecta": trifecta, "banned_package": facts["banned_package"]}
    scanners["policy"], rules = cedar_forbids(action, context, vendor)
    if secret and action not in ("publish", "send"):
        notes.append("A secret is in this %s. Keep it out of git (.gitignore or a credential store); "
                     "a push carrying it will be refused." % action)
    if looping:
        notes.append("The same call has repeated 5 times; change approach instead of retrying.")
    if scanners["secrets"] == "unavailable" and action in ("publish", "send"):
        notes.append("Secret scan unavailable (Betterleaks not found); nothing was refused for it.")
    elif secret_version and scanners["secrets"] == "ok":
        notes.append("Secret scan: Betterleaks %s." % secret_version)
    permissions = read_permissions(environment)
    mode = None if rules else mode_verdict(event, action, permissions, environment)  # a forbid wins
    hold_id = ""
    if mode and mode[0] == "ask":
        # A release in progress, or a one-shot permit from Approve, runs this call.
        # Every other ask is one pending card in the approval file.
        if _RELEASING.get():
            mode = None
        else:
            digest = _call_digest(event, action, mode[1])
            if _take_permit(digest, environment):
                mode = None
            else:
                summary = _REASONS.get(mode[1], mode[1])
                hold_id = _remember(event, action, mode[1], digest, summary, environment)
                notes.append(summary + "; confirm to run it.")
    if mode:
        rules = [mode[1]]
    # The version line records which scanner ran. It is not a reason to hold the call.
    substantive = [note for note in notes if not note.startswith("Secret scan: Betterleaks ")]
    verdict = mode[0] if mode else "refuse" if rules else "organize" if substantive else "allow"
    decision = {"verdict": verdict, "vendor": vendor, "tool": event["tool"], "action": action, "rules": rules,
                "notes": notes, "findings": findings, "scanners": scanners, "mode": permissions["runMode"]}
    if hold_id:
        decision["hold"] = hold_id
    return decision


# ---- Approve / Deny: the same decision for every approval the founder sees ----------------

_WORDS = {"approve": "approve", "deny": "deny", "decline": "deny", "reject": "deny", "cancel": "deny"}


def _owner_apply(request, decision):
    return request["owner"].apply(request["id"], request["digest"], decision)


def _social(request, decision):
    from . import social_approval
    return social_approval.apply(request["server"], request["binding"], request["body"])


def _desktop(request, decision):
    from . import social_approval
    return social_approval.apply_desktop(request["owner"], request["id"], request["digest"], decision)


def _watcher(request, decision):
    from . import social_approval
    if hasattr(request["owner"], "apply"):  # NOGRAPH: the Watcher owner file itself
        return _owner_apply(request, decision)
    return social_approval.apply_watcher(request["owner"], request["id"], request["digest"], decision)


def _permission_request(request, decision):
    from .cell_permission_requests import apply_permission_request
    return apply_permission_request(**request["arguments"])


def _baboom(request, decision):
    return request["owner"].apply_approval(request["id"], decision)


# kind -> the owner that applies the decided effect in its own store.
APPROVALS = {"social": _social, "desktop": _desktop, "schedule": _desktop, "watcher": _watcher,
             "hostskills": _owner_apply, "permission-request": _permission_request, "baboom": _baboom}


def _decide_approval(request: dict, environment):
    from .universal_cell import InvalidCell
    kind = request["approval"]
    word = request["body"].get("decision") if kind == "social" and type(request.get("body")) is dict \
        else request.get("decision")
    decision = _WORDS.get(word) if type(word) is str else None
    if kind not in APPROVALS:
        raise InvalidCell("Choose a listed approval kind.")
    if decision is None and kind != "social":  # social's own body check names the exact shape
        raise InvalidCell("Decide Approve or Deny on the exact approval shown.")
    if decision == "approve" and read_permissions(environment)["runMode"] == "Plan only":
        raise InvalidCell("Plan only is on in Settings: nothing runs until the run mode changes.")
    return APPROVALS[kind](request, decision)


_REASONS = {"secret-going-public": "a secret would go public",
            "client-data-going-public": "client or personal data would go public",
            "delete-founder-data": "this deletes the founder's data",
            "use-founder-screen": "this drives the founder's screen",
            "lethal-trifecta": "private data plus untrusted content would be sent out",
            "banned-package": BANNED_REASON,
            "tool-off": "this tool is Off in Settings",
            "plan-only": "Plan only is on in Settings, so nothing changes",
            "tool-ask": "this tool is set to Ask in Settings",
            "ask-first": "Ask first is on in Settings and this deletes, publishes, sends or works outside your folders"}


# Ask cards live beside permissions.json: the same settings store decide() already reads.
_ASK_FILE = "ask-approvals.json"
_RELEASING = contextvars.ContextVar("archhub_ask_release")
_RELEASING.set(False)
_ASK_TITLES = {"send": "Send", "publish": "Post", "delete": "Delete", "write": "Edit",
               "shell": "Run a command", "screen": "Use the screen"}
_ASK_VENDORS = {"claude-code": "Claude", "codex": "Codex", "gemini-cli": "Gemini",
                "antigravity": "Gemini", "opencode": "OpenCode"}


def _call_digest(event, action, rule) -> str:
    data = event["input"] if isinstance(event["input"], dict) else {"value": event["input"]}
    material = {"vendor": event.get("vendor") or "", "session": event.get("session") or "",
                "tool": event["tool"], "action": action, "rule": rule, "input": data}
    raw = json.dumps(material, sort_keys=True, default=str, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _ask_who(event, data) -> str:
    if event.get("session") == "archhub-remote-relay":
        return "Remote agent"
    named = _ASK_VENDORS.get(event.get("vendor") or "")
    if named:
        return named
    connector = data.get("connector") if isinstance(data, dict) else ""
    if not connector:
        return "This run"
    try:
        from .host_exec import _LABELS
    except ImportError:
        return str(connector)
    return str(_LABELS.get(str(connector), connector))


def _ask_text(action, data):
    if action not in ("send", "publish") or not isinstance(data, dict):
        return "", ""
    label = "Text to post" if action == "publish" else "Text to send"
    sources = [data]
    arguments = data.get("arguments")
    if isinstance(arguments, dict):
        sources.append(arguments)
    for source in sources:
        for key in ("text", "body", "content", "message", "query"):
            held = source.get(key)
            if isinstance(held, str) and held:
                return held, label
    return "", label


def _ask_replay(event, action) -> dict:
    data = event["input"] if isinstance(event["input"], dict) else {}
    if data.get("connector") and "arguments" in data:
        return {"kind": "connector", "connector": str(data.get("connector") or ""),
                "action": event["tool"], "arguments": data.get("arguments")}
    if event.get("session") == "archhub-remote-relay":
        return {"kind": "remote", "tool": event["tool"], "arguments": data}
    if event["tool"] == "write" and "code" in data and data.get("host") is not None:
        return {"kind": "host", "params": {
            "host": data.get("host") or "", "code": data.get("code") or "",
            "document": data.get("path") or "", "transaction_name": data.get("transaction_name") or "",
            "transaction": True}}
    return {"kind": "permit", "tool": event["tool"], "arguments": data}


def _ask_path(environment) -> Path:
    return _settings_dir(environment) / _ASK_FILE


def _read_holds(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {"revision": 0, "holds": {}}
    if type(data) is not dict or type(data.get("holds")) is not dict:
        return {"revision": 0, "holds": {}}
    return data


def _write_holds(path: Path, data: dict) -> None:
    closed = [(key, row) for key, row in data["holds"].items() if row.get("status") != "pending"]
    if len(closed) > 200:
        closed.sort(key=lambda item: item[1].get("at") or 0)
        for key, _row in closed[:len(closed) - 200]:
            data["holds"].pop(key, None)
    data["revision"] = int(data.get("revision") or 0) + 1
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    os.replace(temporary, path)


def _with_ask_file(environment, change):
    path = _ask_path(environment)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_suffix(".lock")
    held = None
    for _ in range(40):
        try:
            held = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_RDWR)
            break
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > 5:
                    lock.unlink(missing_ok=True)
                    continue
            except OSError as busy:
                if type(busy).__name__ == "":
                    break
    if held is None:
        raise OSError("The approval file is busy.")
    try:
        return change(path)
    finally:
        os.close(held)
        lock.unlink(missing_ok=True)


def _ask_card(row: dict) -> dict:
    return {"id": row["id"], "delegation": row["id"], "work": row["id"], "input_digest": row["input_digest"],
            "approvalKind": "ask", "kind": "ask", "title": row.get("title") or "Run", "who": row.get("who") or "This run",
            "text": row.get("text") or "", "textLabel": row.get("textLabel") or "", "summary": row.get("summary") or "",
            "description": row.get("summary") or "", "status": row.get("status") or "pending",
            "error": row.get("error") or "", "rows": [], "rubric": {}, "events": []}


def _remember(event, action, rule, digest, summary, environment) -> str:
    data = event["input"] if isinstance(event["input"], dict) else {}
    text, label = _ask_text(action, data)
    saved = {"id": ""}

    def change(path):
        held = _read_holds(path)
        for row in held["holds"].values():
            if row.get("status") == "pending" and row.get("input_digest") == digest:
                saved["id"] = row["id"]
                return None
        base = "app:ask:" + digest[:24]
        identity = base
        if identity in held["holds"]:
            number = 2
            while base + ":" + str(number) in held["holds"]:
                number += 1
            identity = base + ":" + str(number)
        held["holds"][identity] = {
            "id": identity, "input_digest": digest, "status": "pending", "at": time.time(),
            "title": _ASK_TITLES.get(action, "Run"), "who": _ask_who(event, data),
            "text": text, "textLabel": label, "summary": summary, "permit_open": False,
            "replay": _ask_replay(event, action)}
        _write_holds(path, held)
        saved["id"] = identity
        return None

    try:
        _with_ask_file(environment, change)
    except OSError:
        return ""
    return saved["id"]


def _take_permit(digest, environment) -> bool:
    path = _ask_path(environment)
    if not path.is_file():
        return False
    found = {"ok": False}

    def change(file_path):
        held = _read_holds(file_path)
        for row in held["holds"].values():
            if row.get("permit_open") and row.get("input_digest") == digest and row.get("status") == "approved":
                row["permit_open"] = False
                _write_holds(file_path, held)
                found["ok"] = True
                return None
        return None

    try:
        _with_ask_file(environment, change)
    except OSError:
        return False
    return found["ok"]


def ask_reviews(environment=None) -> list:
    """Pending and closed Ask cards, from the same file decide() writes."""
    environment = os.environ if environment is None else environment
    path = _ask_path(environment)
    if not path.is_file():
        return []
    try:
        rows = list(_read_holds(path)["holds"].values())
    except OSError:
        return []
    rows.sort(key=lambda row: row.get("at") or 0)
    return [_ask_card(row) for row in rows]


def _short_result(value) -> str:
    try:
        text = json.dumps(value, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        text = str(value)
    return text[:400]


def _release_ask(replay: dict):
    from . import host_exec as host_runtime
    kind = replay.get("kind")
    if kind == "connector":
        if replay.get("connector") not in host_runtime.INVOKERS:
            host_runtime._ensure_registry()
        invoker = host_runtime.INVOKERS.get(replay.get("connector"))
        if invoker is None:
            raise ValueError("This connector is not connected.")
        arguments = replay.get("arguments")
        if not isinstance(arguments, dict):
            arguments = {"value": arguments}
        return invoker(replay.get("action") or "", arguments)
    if kind == "host":
        from .library_engines import LIBRARY_ITEM_ENGINES
        params = dict(LIBRARY_ITEM_ENGINES["host_exec"]["params"])
        params.update(replay.get("params") or {})
        produced, display = host_runtime.host_exec(params)
        if display in ("Failed", "Waiting for you"):
            note = produced.get("log") if isinstance(produced, dict) else ""
            raise ValueError(note or display)
        return produced
    if kind == "remote":
        from .cloud_relay import run_remote_effect
        return run_remote_effect(replay.get("tool") or "", replay.get("arguments") or {})
    return None


def ask_apply(root, digest, decision, environment=None):
    """Approve releases the held action once. Deny refuses it. A second Approve does not run it again."""
    from .universal_cell import InvalidCell
    environment = os.environ if environment is None else environment
    if decision not in ("approve", "deny") or type(root) is not str or type(digest) is not str:
        raise InvalidCell("Decide Approve or Deny on the exact approval shown.")
    claimed = {"card": None, "row": None}

    def claim(path):
        held = _read_holds(path)
        row = held["holds"].get(root)
        if row is None or row.get("input_digest") != digest:
            raise InvalidCell("Decide the exact approval shown.")
        if row.get("status") == "approved" and decision == "approve":
            claimed["card"] = _ask_card(row)
            return None
        if row.get("status") != "pending":
            raise InvalidCell("This approval is closed.")
        if decision == "deny":
            row["status"] = "declined"
            _write_holds(path, held)
            claimed["card"] = _ask_card(row)
            return None
        row["status"] = "releasing"
        _write_holds(path, held)
        claimed["row"] = json.loads(json.dumps(row, default=str))
        return None

    try:
        _with_ask_file(environment, claim)
    except OSError as exc:
        raise InvalidCell("The approval could not be saved.") from exc
    if claimed["card"] is not None:
        return claimed["card"]
    token = _RELEASING.set(True)
    status, error, permit, outcome = "approved", "", False, None
    try:
        replay = claimed["row"].get("replay") or {}
        if replay.get("kind") == "permit":
            permit = True
        else:
            outcome = _release_ask(replay)
    except Exception as exc:
        status, error, permit = "failed", str(exc), False
    finally:
        _RELEASING.reset(token)

    def finish(path):
        held = _read_holds(path)
        row = held["holds"].get(root)
        if row is None:
            raise InvalidCell("This approval is no longer in the file.")
        row["status"] = status
        row["permit_open"] = bool(permit and status == "approved")
        if error:
            row["error"] = error
        if outcome is not None:
            row["result"] = _short_result(outcome)
        _write_holds(path, held)
        claimed["card"] = _ask_card(row)
        return None

    try:
        _with_ask_file(environment, finish)
    except OSError as exc:
        raise InvalidCell("The approval could not be saved.") from exc
    if status == "failed":
        raise InvalidCell(error or "The held action failed.")
    return claimed["card"]


def _ask(request, decision):
    return ask_apply(request.get("id"), request.get("digest"), decision)


APPROVALS["ask"] = _ask


def render(decision: dict, vendor: str, event_name: str = "PreToolUse") -> dict:
    """The decision in each agent's own hook wire format."""
    vendor = _ALIAS.get(vendor, vendor)
    reason = "ArchHub refused: " + "; ".join(_REASONS.get(r, r) for r in decision["rules"]) + \
             ". Everything else stays allowed." if decision["verdict"] == "refuse" else \
             "ArchHub asks: " + " ".join(decision["notes"]) if decision["verdict"] == "ask" else " ".join(decision["notes"])
    if vendor == "opencode":
        return decision
    if decision["verdict"] == "allow":
        return {}
    if vendor in ("claude-code", "codex"):
        # shortcut: Codex parses "ask" but runs the call (fails open); its own approval_policy asks.
        if decision["verdict"] in ("refuse", "ask"):
            return {"hookSpecificOutput": {"hookEventName": event_name, "permissionDecisionReason": reason,
                                           "permissionDecision": "deny" if decision["verdict"] == "refuse" else "ask"}}
        return {"hookSpecificOutput": {"hookEventName": event_name, "additionalContext": reason}}
    if decision["verdict"] in ("refuse", "ask"):  # gemini-cli, antigravity
        return {"decision": "deny" if decision["verdict"] == "refuse" else "ask", "reason": reason}
    return {"systemMessage": reason}


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="ArchHub hook decision (one function for every agent)")
    parser.add_argument("--vendor", required=True, choices=VENDORS + tuple(_ALIAS) + ("cursor",))
    args = parser.parse_args(argv)
    try:
        raw = sys.stdin.buffer.read(4 * 1024 * 1024 + 1)
        payload = json.loads(raw or b"{}")
        if (args.vendor == "cursor" and type(payload) is dict
                and payload.get("hook_event_name") in ("stop", "beforeSubmitPrompt")):
            from .native_agent_hooks import emit_cursor_hook
            return emit_cursor_hook(payload)
        decision = decide(payload, args.vendor)
        out = render(decision, args.vendor, payload.get("hook_event_name") or "PreToolUse")
    except Exception as exc:  # organize, never obstruct: a broken check never stops work
        print("ArchHub hook decision unavailable (%s); the call continues." % type(exc).__name__, file=sys.stderr)
        out = {} if args.vendor != "opencode" else {"verdict": "allow", "notes": [], "rules": []}
    sys.stdout.write(json.dumps(out, ensure_ascii=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
