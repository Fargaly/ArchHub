# Skills

Skills are how ArchHub turns a useful chat into a reusable shortcut. They
are the product surface of the workflow engine — the thing your team
actually creates, runs, edits, and shares.

ArchHub is not a new tool to learn. It is a chat that already knows how to
drive Revit, AutoCAD, 3ds Max, Blender, and Speckle, and gets smarter the
more your team uses it. Each Skill is one of those learned patterns.

---

## Mental model

The mental model is borrowed from ComfyUI: behind every Skill is a graph
of nodes that produces a result. The architect rarely sees the graph. They
type in the chat. The chat finds the right Skill (or composes a new one),
runs it, and shows the answer.

```
       chat input ──► matcher ──► best Skill ──► executor ──► result
                          │
                          └──► no match ──► LLM composes new graph,
                                            optionally save as new Skill
```

Three things make a Skill:

1. **A workflow graph** — nodes that run in order. Almost every Skill is a
   four-node chain: input → template → LLM-with-tools → output.
2. **Skill metadata** — intent, keywords, when-to-use, examples, tags,
   required connectors, author, scope (user / team / firm).
3. **Usage stats** — runs, success rate, last used. Tracked locally.

---

## File layout

```
ArchHub/app/
├── workflows/                Graph engine. Knows nothing about Skills.
│   ├── graph.py              Workflow, Node, Edge, Port, Trigger.
│   ├── executor.py           Runs a Workflow in topological order.
│   ├── nodes/                Built-in node types (io, data, llm, tool, control).
│   ├── library.py            Save/load workflows.
│   └── chat_to_workflow.py   Capture chat history → workflow.
│
└── skills/                   Discovery + metadata + UX layer over workflows.
    ├── __init__.py           Public surface.
    ├── metadata.py           SkillMeta dataclass; lives in workflow.metadata['skill'].
    ├── library.py            list_skills, save_skill — across user + shared roots.
    ├── matcher.py            match_skills — keyword score + optional LLM rerank.
    ├── usage.py              record_run, get_usage — per-skill telemetry sidecar.
    ├── capture.py            capture_chat_as_skill — chat → workflow + auto metadata.
    └── seeds.py              ensure_starter_skills — ships with 3 starter Skills.
```

---

## On disk

A Skill is **one JSON file**. The same format as a Workflow, with the
`metadata.skill` block populated:

```
%LOCALAPPDATA%\ArchHub\workflows\dimension-walls__<id>.archhub-workflow.json
%PROGRAMDATA%\ArchHub\skills\<name>__<id>.archhub-workflow.json   # team/firm scope
```

Sidecar telemetry (per user only, never synced):

```
%LOCALAPPDATA%\ArchHub\skill_usage.json
```

The user library overrides the shared library on id collision so individual
edits never get clobbered by a firm-wide push.

---

## Anatomy of a Skill JSON

```jsonc
{
  "id": "seed-dimension-walls-v1",
  "name": "Dimension walls in active view",
  "description": "Add Linear dimensions to every wall in the active Revit view.",
  "schema_version": "1.0",

  "nodes": [
    { "id": "input_…", "type": "input.parameter", "config": {"name": "prompt", "type": "string"} },
    { "id": "tmpl_…",  "type": "data.template",   "config": {"template": "You are running…\n{var1}"} },
    { "id": "llm_…",   "type": "llm.complete_with_tools",
      "config": {
        "model": "auto",
        "allowed_tools": ["revit_info", "revit_execute_csharp"]
      } },
    { "id": "out_…",   "type": "output.parameter", "config": {"name": "answer"} }
  ],
  "edges": [ /* …prompt → template → llm → output… */ ],

  "metadata": {
    "skill": {
      "intent": "Auto-dimension every wall in the active Revit view.",
      "keywords": ["dimension", "dimensions", "wall", "walls", "annotate"],
      "when_to_use": "User asks to add dimensions to walls in the current Revit view.",
      "examples": [
        {"prompt": "Dimension all the walls in the active view", "expected_outcome": "…"}
      ],
      "tags": ["revit", "annotation"],
      "requires": ["revit"],
      "author": "ArchHub",
      "scope": "user",
      "version": "1.0.0"
    }
  }
}
```

Removing the `metadata.skill` block turns it back into a plain Workflow —
runnable from the Workflows tab but invisible to the matcher.

---

## How the matcher works

`skills.match_skills(prompt, ...)` returns a ranked list of candidates.

Tier 1 — **keyword score** (default; v0.7):

| signal           | weight |
|------------------|--------|
| metadata keyword | ×3.0   |
| tag              | ×2.0   |
| word in name     | ×1.5   |
| word in intent   | ×1.0   |

Score normalised against the maximum possible (every prompt token is a
keyword hit). A normalised score ≥ 0.45 is the floor for surfacing a
candidate. The chat only proposes a Skill if the top score is ≥ 0.55 or
clearly leads the runner-up by ≥ 0.10.

Tier 2 — **LLM rerank** (off by default; flip `use_llm_rerank=True`):
sends the top-N candidates to a small fast model (Haiku) for a final pick
when the keyword scores are tied.

The `requires` filter drops Skills whose connectors are not active before
scoring runs — there is no point proposing a Revit Skill when Revit is
turned off in the Connectors panel.

---

## Chat surface

Three slash commands and one inline suggestion.

```
/skill save [name]      — capture this conversation as a Skill
/skill list             — show saved Skills
/skill run <id|name>    — run a Skill by id prefix or name match
/skills                 — open the Skills panel
```

When the matcher finds a strong hit, the chat shows an inline “💡 Skill
match” bubble with two buttons: **Run “<name>”** or **Skip — answer
fresh**. Skipping falls through to the normal LLM tool loop.

---

## Capturing a chat as a Skill

`/skill save` runs `capture.capture_chat_as_skill(history, ...)`:

1. The conversation is summarised (last 12 turns).
2. Haiku is asked to fill out the metadata as strict JSON: name, intent,
   keywords, when_to_use, tags, requires.
3. `chat_to_workflow` builds a workflow graph mirroring the conversation:
   user prompts → llm.complete_with_tools nodes → tool nodes →
   output.parameter. The graph is editable afterwards.
4. The Skill is saved to the right library based on its scope.

The first user message becomes the workflow's `prompt` input, so re-running
the Skill against a different prompt is a one-liner.

---

## Adding a new Skill by hand

Three options, in order of effort:

1. **From a chat.** Have the conversation. Type `/skill save`. Done.
2. **By cloning a seed.** Open the Skills panel → Workflows tab → pick a
   seed → edit the JSON. Change the framing template, the
   `allowed_tools`, the metadata. Save. New Skill.
3. **From scratch.** Build a Workflow programmatically (see
   `skills/seeds.py` for the four-node chain pattern) and save it via
   `skills.save_skill(workflow, SkillMeta(...))`.

The four-node chain pattern handles 95% of single-step Skills:

```
input.parameter ──► data.template ──► llm.complete_with_tools ──► output.parameter
   (prompt)         (skill framing)    (with allowed_tools)         (answer)
```

For multi-step Skills (e.g. *push to Speckle, then re-render in Blender*),
keep adding LLM-with-tools nodes downstream and chain them through
intermediate `output.parameter` / `input.parameter` pairs.

---

## Sharing — copy and paste, like a ComfyUI workflow

A Skill is one JSON file. Move it however you like.

### From the chat

```
/skill share <id-or-name>     copy the Skill JSON to your clipboard
/skill import                 paste a Skill JSON in from the clipboard
```

`/skill share dimension` copies the dimension-walls Skill as JSON. Paste
the result into Slack, Notion, an email, or another machine running
ArchHub. On the receiving machine, `/skill import` reads from the
clipboard and saves it locally — the matcher picks it up immediately.

### From the Skills panel

Each Skill card has **Share** (copy JSON to clipboard) and **Export**
(save as `.archhub-workflow.json` to a file). The top of the panel has
**Paste from clipboard** and **Import file…** buttons. Drag-and-drop a
`.archhub-workflow.json` file onto the panel to import it directly.

### Single source of truth across devices

Two layers, two mechanisms:

- **Code** — the ArchHub source itself — lives in one private Git repo.
  Clone it on every device. See [docs/MULTI_DEVICE.md](MULTI_DEVICE.md)
  for the exact commands.
- **Skills** — your saved Skills folder — sync with one of:
  - **OneDrive symlink** (recommended): one folder, every device sees
    the same Skills. Set up once.
    ```cmd
    rmdir "%LOCALAPPDATA%\ArchHub\workflows"
    mklink /D "%LOCALAPPDATA%\ArchHub\workflows" "%OneDrive%\ArchHub\workflows"
    ```
  - **Per-Skill share via clipboard** for ad-hoc distribution.
  - **Firm-wide path** (`%PROGRAMDATA%\ArchHub\skills\`) populated by
    the IT team, mounted to a network share. Skills with
    `scope: 'team' | 'firm'` save here automatically.

API keys stay per-machine — the Windows Credential Manager is local.
Re-enter them on each device the first time you launch.

---

## Telemetry

`skill_usage.json` is a flat sidecar:

```json
{
  "seed-dimension-walls-v1": {
    "runs": 12, "successes": 11, "failures": 1,
    "last_used": "2026-05-05T14:33:00",
    "last_error": "",
    "total_elapsed_ms": 27_400
  }
}
```

It is written by `record_run(skill_id, success=..., elapsed_ms=..., error=...)`
inside the chat's run handler. Per-user only — nothing leaves the machine.

A future `skills.aggregate_usage()` will roll local stats into a shared
report; today the Skills panel shows them per-architect.

---

## Extension points

Want to extend the system without touching the engine?

| You want to…                         | Touch                                                |
|--------------------------------------|------------------------------------------------------|
| Add a new node kind (e.g. `acad.…`)  | `app/workflows/nodes/<file>.py`, call `register(...)` |
| Add a new tool to the LLM palette    | Append to `tool_engine.TOOLS`                        |
| Add a new starter Skill              | Append a factory to `app/skills/seeds.py`            |
| Switch the matcher to embeddings     | Replace `_keyword_score` in `app/skills/matcher.py`  |
| Persist usage somewhere else         | Override `_PATH` in `app/skills/usage.py`            |
| Resolve sharing                      | Implement sync in `app/skills/library.py`            |

---

## Roadmap notes

- v0.7: keyword matcher, slash commands, three seed Skills, local sharing.
- v0.8: shared library sync (mechanism TBD), skill telemetry rollup,
  embeddings matcher.
- v0.9: skill versioning + diff UI; team-edit history.
- v1.0: visible canvas for power users (ComfyUI-style graph editor).
