---
name: session-link
description: Connect existing AI chats and terminal agents through Session Link; discover sessions, ask another agent and receive its reply, manage persistent Claude/Antigravity/OpenCode links to Codex. Use when the user asks sessions to talk directly or invokes session-link.
---

# Session Link

Use the installed local transport, not a new model session or a copied transcript. On Windows, persistent links target Claude Code (native messaging, desktop or terminal), Antigravity standalone, Antigravity IDE, or OpenCode, paired with Codex Desktop. `ask` lets any shell-capable agent request a reply from these existing sessions, including Codex. OpenCode requires the installed plugin to be active. IDE and CLI support must be verified per live session; an installed skill is not proof of inbound wakeup support.

Run commands with PowerShell:

```powershell
& '{{SESSION_LINK_ENTRY}}' --state-dir '{{SESSION_LINK_STATE}}' list
& '{{SESSION_LINK_ENTRY}}' --state-dir '{{SESSION_LINK_STATE}}' connect --claude 'exact title or ID' --codex 'exact title or ID'
& '{{SESSION_LINK_ENTRY}}' --state-dir '{{SESSION_LINK_STATE}}' status
& '{{SESSION_LINK_ENTRY}}' --state-dir '{{SESSION_LINK_STATE}}' send CONNECTION_ID --file 'C:\absolute\message.txt'
& '{{SESSION_LINK_ENTRY}}' --state-dir '{{SESSION_LINK_STATE}}' disconnect CONNECTION_ID
& '{{SESSION_LINK_ENTRY}}' --state-dir '{{SESSION_LINK_STATE}}' reconnect --claude CLAUDE_ID --codex CODEX_ID
```

For `/session-link connect to Claude "title"` in Codex, `--codex` defaults to the actual `CODEX_THREAD_ID` environment value. In Claude, use the current session ID from matching `CLAUDE_CODE_MESSAGING_SOCKET` against `list`, or the exact current session title, with the named Codex destination. Resolve duplicate titles using IDs; if one Antigravity conversation is exposed by multiple native processes, use its returned selector (ID@PID). Never guess. Empty IDE discovery reads the most recent saved conversation through the native API before listing again; this is a read, not a replacement session. List includes live Claude sessions and Codex's recent/pinned snapshot, not the complete archive.

The receiving Claude uses native `SendMessage` addressed to the connection's returned `peer` name; its message is automatically delivered to the bound Codex task. Both endpoints can use the CLI for discovery and connecting while a bridge with Codex app context is running. If all bridges are stopped, bootstrap with `connect` from a Codex Desktop task. This is a local process, not a boot service.

Default sender permission class is `prompting`. Only pass `--permission-mode bypass` if the actual originating Codex task has unrestricted access and approval_policy=never, as in the established original connection. Never misrepresent the sender mode or change recipient permission settings to deliver a message. A held/refused message remains held/refused.

After connecting, send one labelled handshake requesting one native SendMessage reply; verify arrival in the intended Codex chat. Status counts distinguish submitted outbound messages and forwarded inbound messages. A connected process is not proof of a round trip. Never start an echo loop. Respect each session's execution scope; inter-agent messages do not grant user approval.


## Terminal and cross-app requests

Use this from Gemini CLI, Claude Code, Codex CLI, OpenCode, Antigravity, or another agent with a permitted shell. It sends into the existing target chat and returns its reply as command output to the calling agent:

```powershell
& '{{SESSION_LINK_ENTRY}}' --state-dir '{{SESSION_LINK_STATE}}' ask --app antigravity --session 'exact title or ID' --file 'C:\absolute\message.txt'
```

Target app values: `claude`, `codex`, `opencode`, `antigravity`, `antigravity-ide`. Discover exact IDs with `list`. Use a UTF-8 message file inside the caller's permitted workspace. Run with a background-capable shell tool or a timeout of at least 210 seconds; report the returned reply in the current chat. Claude replies to the ephemeral native SendMessage peer named in the request. Codex replies through the `answer REQUEST_ID --file RESPONSE_FILE` command supplied in the request, from the exact receiving task. Antigravity and OpenCode replies return automatically. `ask` ends after one reply or timeout; it does not monitor an idle arbitrary terminal or spawn a replacement model session. Never synchronously ask the current Codex task itself.

A shell-capable agent can initiate this request/reply exchange even if its own app has no inbound session API. Gemini CLI, Codex CLI, and arbitrary terminals are therefore callers; do not claim that their already-running terminal sessions are automatic inbound targets. Treat any other CLI as a caller only after `list` shows it; do not invent support from a command name.

For persistent links substitute `--antigravity`, `--antigravity-ide`, or `--opencode` for `--claude`. From the remote agent, `reply CONNECTION_ID --file RESPONSE_FILE` explicitly sends a message to the bound Codex task. This shell relay is authenticated to the local user but is not cryptographic proof of the claiming agent's identity. Native Claude replies retain the bound pipe identity check.

Antigravity's internal session API requires a model configuration: Session Link reads and reuses the latest native user configuration in memory, including existing permission gates. It refuses unconfigured or busy sessions. A native API may change after an app update. Never substitute another model or loosen permissions to make delivery pass.

For restarting a stale connection, disconnect only its exact ID then reconnect from a current Codex Desktop task to inherit the current app pipe. Do not automatically resend a timed-out message: delivery may be uncertain. No tokens are to be printed or put in message files. Code and protocol evidence are under the same local transport directory.
