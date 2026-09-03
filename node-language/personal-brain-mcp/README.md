# personal-brain-mcp

Ambient agent substrate. Memory + skills + setups + secrets. Real-time. Cross-device. Cross-model. Inside + outside ArchHub.

**Status**: Slice 1 / 8 — FastMCP scaffold + 4 tools shipped. See [AgDR-0044](../docs/agdr/AgDR-0044-personal-brain-mcp.md) for full architecture.

## What it is

One MCP server. Five live loops:

| Loop | Hook | Tool |
|------|------|------|
| Context inject | `UserPromptSubmit` | `brain.context` |
| Memory write | `PostToolUse` | `brain.write` |
| Skill mint | `Stop` | `brain.skill_mint` |
| Wiring sync | `SessionStart` | `brain.wiring_announce` |
| Tool augment | `PreToolUse` | (resolver runs locally, no tool) |

Every MCP client (Claude Code, Cursor, ChatGPT desktop, Codex CLI, Gemini CLI, Cline, Continue, ArchHub Composer) connects to the SAME server. Same skills. Same facts. Same brain.

## Install

```bash
pip install -e ./personal-brain-mcp
```

ArchHub bundles this; manual install only for standalone use outside ArchHub.

## Run

```bash
# stdio (default — what Claude Code, Codex, Cursor expect)
personal-brain

# Streamable HTTP (for ChatGPT desktop + remote clients)
personal-brain --http 8473

# custom db path
personal-brain --db ~/brain/founder.db
```

Default DB: `%APPDATA%/ArchHub/brain/brain.db` (Windows), `~/.local/share/archhub/brain/brain.db` (Linux/macOS).

## Wire to Claude Code

Drop into `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "brain": {
      "command": "personal-brain",
      "args": []
    }
  },
  "hooks": {
    "SessionStart": [
      {"type": "mcp_tool", "server": "brain", "tool": "brain.wiring_announce"}
    ],
    "UserPromptSubmit": [
      {"type": "mcp_tool", "server": "brain", "tool": "brain.context"}
    ],
    "PostToolUse": [
      {"type": "mcp_tool", "server": "brain", "tool": "brain.write"}
    ],
    "Stop": [
      {"type": "mcp_tool", "server": "brain", "tool": "brain.skill_mint"}
    ]
  }
}
```

Slice 3 ships an automated installer that detects each client and writes the right config.

## Test

```bash
pip install -e '.[dev]'
pytest tests/ -v
```

## Architecture

Five scope tiers, dual-transport sync, bipartite ACL, real-time mint.

```
            ┌──────────────────────────────────┐
            │   Personal Brain MCP server      │
            │   stdio + HTTP · OAuth 2.1       │
            └────────────────┬─────────────────┘
                             ▼
        ┌────────────────────────────────────────┐
        │  SQLite + FTS5 + (FAISS in Slice 2)    │
        │  ─ fragments    facts/setups/traces    │
        │  ─ skills       voyager-mined          │
        │  ─ wiring       per-device MCP roster  │
        │  ─ secret_refs  op://… (no values)     │
        │  ─ access_log   retrospective audit    │
        └────────────────────────────────────────┘
                             ▼
        ┌────────────────────────────────────────┐
        │  Sync (Slice 6)                        │
        │  ├── Loro CRDT   memory/skills/setups  │
        │  └── Speckle     spatial/geometric     │
        └────────────────────────────────────────┘
```

## Slice progress

- ✅ **Slice 1** — FastMCP scaffold + 4 tools (this commit)
- ⏳ Slice 2 — Embedding + retrieval (MiniLM + FAISS)
- ⏳ Slice 3 — Claude Code wiring (installer + drop-in configs)
- ⏳ Slice 4 — ArchHub Layer 5 (llm_router.py hooks)
- ⏳ Slice 5 — Reflexion worker (Voyager + SkillWeaver hone)
- ⏳ Slice 6 — Loro + Speckle dual sync
- ⏳ Slice 7 — Bipartite ACL + redaction
- ⏳ Slice 8 — Community tier (FICAL + DP + ActivityPub)

## License

Apache-2.0. Ships with ArchHub.
