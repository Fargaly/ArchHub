"""One hook decision for every agent: Claude Code, Codex, Gemini CLI, Antigravity, OpenCode.

Each agent's pre-tool hook runs ``hook_decision.py --vendor <name>`` with the event on
stdin (OpenCode's plugin calls the same file). ``decide()`` returns one record:

    verdict   allow | organize | refuse
    action    read | write | shell | delete | publish | send | screen | other
    rules     Cedar forbid ids that matched (refuse only)
    notes     plain-language guidance for organize
    findings  [{kind: secret|pii|trace, rule, where}]  (values never included)
    scanners  {secrets, pii, policy, trace}: ok | skipped | unavailable

Policy is Cedar (POLICY below, any forbid wins). Secrets: Betterleaks. PII:
Presidio. Trace rules: the Invariant lethal-trifecta and loop rules over this session's
recent calls, in LlamaFirewall's trace shape (ALLOW / BLOCK). Governance organizes,
never obstructs (F1/F4/A1): only a forbid refuses; a missing scanner never refuses.
"""
from __future__ import annotations

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
_WRITE = re.compile(r"^(write|edit|multiedit|notebookedit|apply_patch|write_file|replace|patch)$", re.I)
_SHELL = re.compile(r"^(bash|powershell|shell|exec_command|run_shell_command|local_shell)$", re.I)
_UNTRUSTED = re.compile(r"(webfetch|websearch|web_fetch|web_search|fetch|browser|navigate|get_page_text|"
                        r"read_page|inbox|get_message|get_thread|slack_read|search_threads)", re.I)
_SEND_TOOL = re.compile(r"(send|post_message|publish|upload|share|create_draft|deploy|create_comment|"
                        r"reply|notion-create|notion-update|create_pages|tweet)", re.I)
_SCREEN_TOOL = re.compile(r"computer-use__(?!screenshot$|zoom$|cursor_position$|list_granted_applications$)", re.I)
_PUBLISH_CMD = re.compile(
    r"\bgit\s+push\b|\bgh\s+(pr|issue|release|gist|repo)\s+(create|edit|comment|upload)\b|"
    r"\bgh\s+api\b.*-X\s*(POST|PUT|PATCH)|\bnpm\s+publish\b|\btwine\s+upload\b|\bcargo\s+publish\b|"
    r"\bcurl\b.*\s(-d|--data\S*|-F|--form|-T|--upload-file|-X\s*(POST|PUT|PATCH))\b|"
    r"\bInvoke-(WebRequest|RestMethod)\b.*-(Method\s+(Post|Put|Patch)|Body|InFile)\b|\bscp\b", re.I)
_DELETE_CMD = re.compile(r"(^|[\s;&|(])(rm|del|erase|rmdir|rd|Remove-Item|ri)\b|\bgit\s+clean\s+-\S*f|"
                         r"\bgit\s+reset\s+--hard\b|\bshutil\.rmtree\b|\bformat\s+[a-z]:", re.I)
_PRIVATE_PATH = re.compile(r"(20\.CLIENTS|60\.PERSONAL|62\.LIFE-AREAS)", re.I)
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
    facts = {"banned_package": banned, "text": text, "command": command, "untrusted": bool(_UNTRUSTED.search(tool)),
             "private": bool(_PRIVATE_PATH.search(text))}
    if _SCREEN_TOOL.search(tool):
        return "screen", facts
    if _SHELL.match(tool):
        if _PUBLISH_CMD.search(command):
            return "publish", facts
        if _DELETE_CMD.search(command):
            return "delete", facts
        return "shell", facts
    if _WRITE.match(tool):
        return "write", facts
    if _READ.match(tool) or tool.lower().endswith(("_read", "_list", "_search", "_get", "ping", "info")):
        return "read", facts
    if _SEND_TOOL.search(tool):
        return "send", facts
    return "other", facts


def founder_data_targeted(command: str, cwd: str, environment) -> bool:
    """A delete aimed at the founder's data; temp folders and lane worktrees are free."""
    temp = [Path(environment.get("TEMP") or tempfile.gettempdir()).resolve()]
    roots = _founder_roots(environment)
    paths = re.findall(r"""["']([^"']+)["']|(\S*[\\/]\S*)""", command)
    candidates = [Path(a or b) for a, b in paths if (a or b)]
    if re.search(r"\bgit\s+(clean|reset)\b", command, re.I) or not candidates:
        candidates.append(Path(cwd))
    for raw in candidates:
        text = str(raw).replace("~", str(roots[0].parent), 1) if str(raw).startswith("~") else str(raw)
        path = Path(text) if Path(text).is_absolute() else Path(cwd) / text
        try:
            path = path.resolve()
        except OSError:
            continue
        if any(_under(path, t) for t in temp):
            continue
        if any(_under(path, r) for r in roots):
            return True
    return False


def _under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root.resolve() if root.exists() else root)
        return True
    except ValueError:
        return False


# ---- scanners -----------------------------------------------------------------------

def betterleaks_path(environment) -> Path | None:
    for candidate in (environment.get("ARCHHUB_BETTERLEAKS"),
                      HERE.parent / "runtime" / "betterleaks" / "betterleaks.exe"):
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    return None


def scan_secrets(text: str, environment, *, git_cwd: str | None = None):
    """Betterleaks on the text (stdin) or on the commits a push would publish."""
    exe = betterleaks_path(environment)
    if exe is None:
        return "unavailable", []
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
            return "unavailable", []
        found = json.loads(report.read_text(encoding="utf-8") or "[]") or []
    return "ok", [{"kind": "secret", "rule": f.get("RuleID"), "where": f.get("File") or "input"} for f in found]


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
    trifecta = action in ("publish", "send") and private and untrusted
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

def decide(payload: dict, vendor: str, *, environment=None) -> dict:
    environment = os.environ if environment is None else environment
    vendor = _ALIAS.get(vendor, vendor)
    event = normalize(payload, vendor)
    action, facts = classify(event, environment)
    scanners = {"secrets": "skipped", "pii": "skipped", "policy": "skipped", "trace": "skipped"}
    findings, notes = [], []
    if action in ("write", "publish", "send", "shell", "other") and facts["text"]:
        git_cwd = event["cwd"] if action == "publish" and re.search(r"\bgit\s+push\b", facts["command"]) else None
        scanners["secrets"], found = scan_secrets(facts["text"], environment)
        findings += found
        if git_cwd and scanners["secrets"] == "ok":  # the commits a push would publish
            scanners["secrets"], found = scan_secrets("", environment, git_cwd=git_cwd)
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
    client = facts["private"] or any(f["kind"] == "pii" for f in findings)
    context = {"secret": secret, "client_data": bool(client and action in ("publish", "send")),
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
    verdict = "refuse" if rules else "organize" if notes else "allow"
    return {"verdict": verdict, "vendor": vendor, "tool": event["tool"], "action": action, "rules": rules,
            "notes": notes, "findings": findings, "scanners": scanners}


_REASONS = {"secret-going-public": "a secret would go public",
            "client-data-going-public": "client or personal data would go public",
            "delete-founder-data": "this deletes the founder's data",
            "use-founder-screen": "this drives the founder's screen",
            "lethal-trifecta": "private data plus untrusted content would be sent out",
            "banned-package": BANNED_REASON}


def render(decision: dict, vendor: str, event_name: str = "PreToolUse") -> dict:
    """The decision in each agent's own hook wire format."""
    vendor = _ALIAS.get(vendor, vendor)
    reason = "ArchHub refused: " + "; ".join(_REASONS.get(r, r) for r in decision["rules"]) + \
             ". Everything else stays allowed." if decision["verdict"] == "refuse" else " ".join(decision["notes"])
    if vendor == "opencode":
        return decision
    if decision["verdict"] == "allow":
        return {}
    if vendor in ("claude-code", "codex"):
        if decision["verdict"] == "refuse":
            return {"hookSpecificOutput": {"hookEventName": event_name, "permissionDecision": "deny",
                                           "permissionDecisionReason": reason}}
        return {"hookSpecificOutput": {"hookEventName": event_name, "additionalContext": reason}}
    if decision["verdict"] == "refuse":  # gemini-cli, antigravity
        return {"decision": "deny", "reason": reason}
    return {"systemMessage": reason}


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="ArchHub hook decision (one function for every agent)")
    parser.add_argument("--vendor", required=True, choices=VENDORS + tuple(_ALIAS))
    args = parser.parse_args(argv)
    try:
        raw = sys.stdin.buffer.read(4 * 1024 * 1024 + 1)
        payload = json.loads(raw or b"{}")
        decision = decide(payload, args.vendor)
        out = render(decision, args.vendor, payload.get("hook_event_name") or "PreToolUse")
    except Exception as exc:  # organize, never obstruct: a broken check never stops work
        print("ArchHub hook decision unavailable (%s); the call continues." % type(exc).__name__, file=sys.stderr)
        out = {} if args.vendor != "opencode" else {"verdict": "allow", "notes": [], "rules": []}
    sys.stdout.write(json.dumps(out, ensure_ascii=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
