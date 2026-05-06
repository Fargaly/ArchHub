# ArchHub Departments

A small team of role-scoped local-Ollama agents that runs continuously
on the founder's laptop and chips away at the backlog. Free — no
Claude tokens, no cloud spend, no rate limits.

## What's in here

| Department | Model | Output |
|------------|-------|--------|
| **Docs** | `llama3.1:latest` | Markdown only — keeps QUICKSTART, README, doc/* in sync |
| **QA** | `deepseek-r1:8b` | Test plans, edge cases, suggested test names — never writes test code |
| **R&D** | `qwen2.5-coder:7b` | Decision memos: problem · options · recommendation · risks · effort |
| **Engineering** | `qwen2.5-coder:7b` | Unified-diff patches saved to disk for human review (never auto-applied) |
| **Ops** | `llama3.2:3b` | Daily standup summaries, triage notes |

Every department's output lands in `agents/outputs/<dept>/<task-id>/`.
**Nothing is committed to the repo automatically.**

## How to run it

Double-click **`Run-Departments.bat`** at the repo root. It checks that
Ollama is running, then starts a daemon that:

1. Reads `agents/recurring.yaml` and creates fresh tasks whenever each
   recurring job's interval has elapsed.
2. Picks the highest-priority pending task per department and runs it.
3. Writes the output to `agents/outputs/<dept>/<task-id>/`.
4. Marks the task done in `agents/tasks/<dept>/<id>.done`.
5. Sleeps 5 minutes, repeats.

To stop: close the console window.

## CLI

```cmd
python -m agents.run --status      # print queue + Ollama state
python -m agents.run --once        # one cycle, print summary, exit
python -m agents.run --cycle 60    # daemon, 60-second cycle
python -m agents.run --enqueue path/to/tasks.yaml   # add tasks
```

## Adding a one-off task

Drop a JSON file at `agents/tasks/<dept>/<task-id>.yaml` (we use JSON
syntax inside `.yaml` so we don't need PyYAML):

```json
{
  "id": "review-pricing-page",
  "department": "docs",
  "title": "Polish the Plans & Pricing copy",
  "instructions": "Read app/pricing_dialog.py and STRATEGY.md. Suggest five concrete edits to the in-app pricing dialog text that make it punchier without changing the meaning. Output Markdown.",
  "priority": 30,
  "inputs": {
    "context_files": ["app/pricing_dialog.py", "STRATEGY.md"]
  }
}
```

The next scheduler cycle picks it up.

## Adding a recurring job

Edit `agents/recurring.yaml` and add an entry under `jobs:` with an
`id`, `department`, `title`, `instructions`, and `interval_minutes`.
The scheduler re-creates a fresh task each time the interval lapses.

## Safety contract

This is enforced in code, not a guideline:

- Departments **read** files via a glob whitelist defined per agent
  (e.g. Docs can't read `app/**/*.py`). Anything outside the
  whitelist returns "(redacted)".
- Departments **write** only to `agents/outputs/<dept>/<task-id>/`.
- The dispatcher does NOT run `git commit`, `git push`, `gh pr
  create`, or any shell command. It runs Ollama and writes files.
- All Ollama calls are logged to `agents/logs/<dept>-YYYYMMDD.log`
  with prompt + completion token counts.

If you decide later to auto-commit department outputs, build that as a
**separate** tool that takes outputs and proposes a `auto/<dept>/<id>`
branch + opens a draft PR. Never let an agent push to `main`.

## Running it 24/7

Three options, in order of "I just want it on":

**Easiest — hidden background process (no console window):**
Double-click `Run-Departments-Hidden.vbs` at the repo root. Nothing
visibly happens but the daemon is now running. Check `agents\logs\`
to verify. Stop it with `Stop-Departments.bat` (only kills the
`agents.run` python process, leaves your other python tools alone).

**Always-on at login** — drop a shortcut to the .vbs into your
Startup folder:
```cmd
%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
```

**Most robust — Windows Task Scheduler:**

```cmd
schtasks /create /tn "ArchHub Departments" ^
  /tr "wscript.exe \"C:\Users\fargaly\00.ARCHUB\ArchHub\Run-Departments-Hidden.vbs\"" ^
  /sc onlogon /rl HIGHEST /f
```

The daemon will start every time you log in. Remove with:

```cmd
schtasks /delete /tn "ArchHub Departments" /f
```

## What this isn't

- It isn't a replacement for the chat-driving Claude path inside
  ArchHub itself. The desktop app stays on whatever LLM the user
  selects (cloud or local). The departments are background workers
  for the **company**, not the **product**.
- It isn't autonomous deployment. Outputs are drafts for a human to
  review and act on.
- It isn't a way to ship code without thinking. The Engineering
  department writes patches; you read, judge, apply.

## Files

| File | What |
|------|------|
| `__init__.py` | Public surface |
| `base.py` | `Agent` base class — model + system prompt + read whitelist + output sink |
| `ollama.py` | Tiny non-streaming Ollama client (no streaming, no tool calls) |
| `queue.py` | File-on-disk task queue under `agents/tasks/` |
| `dispatcher.py` | Pulls one task per department per round, runs it |
| `scheduler.py` | Re-creates recurring tasks, drains the queue, sleeps |
| `departments.py` | Five Agent subclasses with role-specific prompts |
| `run.py` | Daemon CLI: `--status` / `--once` / `--enqueue` / `--cycle` |
| `recurring.yaml` | Recurring jobs definition |
| `tasks/<dept>/<id>.yaml` | Pending task |
| `tasks/<dept>/<id>.lock` | In-progress |
| `tasks/<dept>/<id>.done` | Completed |
| `tasks/<dept>/<id>.failed` | Failed (with reason) |
| `outputs/<dept>/<id>/...` | Agent's produced files |
| `logs/<dept>-YYYYMMDD.log` | Per-day per-department log |
