# Gemini / Antigravity — project mandates

Read `AGENTS.md` at the repository root FIRST.

ArchHub has a strict protected-files list (`payload/sources/**/*.cs`),
a destructive-operations blacklist, and a "no cross-surface change
without AgDR" rule. The Antigravity IDE was caught making undiscussed
edits to broker .cs files on 2026-05-25 — port 48885 → 48887 in
`AcadMCPApp.cs`, a new `NopFP` failure preprocessor in
`RevitMCPCore.cs`, and a coupled inject in `ScriptCompiler.cs`. All
three were reverted; pre-commit and pre-push hooks now block them.

If you need to edit any .cs in `payload/sources/`:
1. Write `docs/agdr/AgDR-<next>-<slug>.md` with the change.
2. Wait for the founder to sign off in chat.
3. Commit with `ARCHHUB_ALLOW_CS_EDIT=1 git commit ...`.

Never use `--no-verify` to bypass the hooks.
