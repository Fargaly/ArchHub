# CONVENTIONS

The full project conventions, mandates, and protected-files list live
in [`AGENTS.md`](./AGENTS.md). Every AI coding agent (Aider, Continue,
Codex, Antigravity, etc.) MUST read AGENTS.md before any edit.

Source-controlled `.githooks/pre-commit` + `.githooks/pre-push` block
edits to `payload/sources/**/*.cs` unless `ARCHHUB_ALLOW_CS_EDIT=1` is
set in the env. Don't bypass with `--no-verify`.
