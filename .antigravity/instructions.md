# Antigravity — project mandates

Read `AGENTS.md` at the repository root FIRST.

You were caught on 2026-05-25 making undiscussed destructive edits to
broker .cs files:
- `payload/sources/acad_mcp/AcadMCPApp.cs` — port 48885 → 48887
- `payload/sources/revit_mcp_core/RevitMCPCore.cs` — NopFP injection
- `payload/sources/shared/ScriptCompiler.cs` — coupled NopFP inject

All three reverted by the founder. Pre-commit + pre-push hooks now
BLOCK any future edit to `payload/sources/**/*.cs` unless
`ARCHHUB_ALLOW_CS_EDIT=1` is set in the env. Don't try to set it
yourself — only the founder does that, after signing off on an AgDR
in chat.

Treat AGENTS.md as the law. Treat CLAUDE.md as the long-form Claude
ruleset (you should also read it for full context). Don't bypass the
hooks. Don't push to `main` without explicit founder sign-off.
