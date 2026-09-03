# Codex — project mandates

Read `../AGENTS.md` at the repository root FIRST.

ArchHub has protected-files (`payload/sources/**/*.cs`) blocked by
source-controlled git hooks. Don't edit them without an AgDR + founder
sign-off in chat. Don't bypass `.githooks/pre-commit` with
`--no-verify`. See AGENTS.md §1 for the full list + procedure.

CLAUDE.md is the long-form ruleset — read it for full context.

Brain: connect to the personal-brain daemon (http://127.0.0.1:8473/mcp)
before work — see AGENTS.md → BRAIN-FIRST. If this client has no auto
hook, run tools/brainwrap or call brain.health + brain.context yourself
first.
