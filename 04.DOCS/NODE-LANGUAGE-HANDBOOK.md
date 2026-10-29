# ArchHub Node Language Handbook

Status: WIP explanatory handbook; not a completion, release, or deployment claim
Authority date reviewed: 2026-10-28 (NOGRAPH, decision D-014)
Language target: ArchHub Node Specification 0.2 WIP ([SPEC.md](./SPEC.md))

This handbook teaches the language defined by [SPEC.md](./SPEC.md). It does not
replace the specification, the founder's decisions, the Core Values source, or
revision-bound executable evidence. When this handbook conflicts with a higher
authority, [AUTHORITY.md](./AUTHORITY.md) decides which source controls.

The previous handbook taught a universal Cell graph as the only store. That model
is retired (D-014). Its exact text is kept at
[04.ARCHIVE/NODE-LANGUAGE-HANDBOOK-universal-cell-2026-07-22.md](./04.ARCHIVE/NODE-LANGUAGE-HANDBOOK-universal-cell-2026-07-22.md)
as historical evidence.

Normative words in quoted or restated rules keep their specification meaning.
Text marked **Explanation**, **Example**, **Counterexample**, or **Current
implementation status** is non-normative.

The same seven questions are applied to every topic:

1. **WHAT** is the thing?
2. **WHY** does it exist?
3. **HOW** is it built, changed, and verified?
4. **WHO** may see, author, approve, or run it?
5. **WHEN** does it change, run, or retire?
6. **WHERE** does its data and physical effect live?
7. **PROOF** shows that the claim is true on an exact revision and artifact.

The scales:

```text
APP       the application: owners, brokers, Workshop, Brain, Settings, canvases
DOCUMENT  one .archhub file: a workflow or a skill
NODE      one block: sockets, parameters, engine
VALUE     one parameter or socket value, one wire
```

"Everything is a node" means everything can be wired and has sockets and
parameters. It does not mean everything is stored in one graph. When the product
says "graph" or "canvas", it means the canvas workspace of nodes where people and
agents work.

## 1. Reading and Using the Language

Scale: all.

### WHAT

The Node Language is a visual language of blocks wired together, in the family
of Grasshopper, Dynamo and ComfyUI. A canvas holds nodes; nodes have typed sockets
and parameters; wires carry values from outputs to inputs. A canvas is saved as
one `.archhub` file. A workflow and a skill are both such files.

### WHY

The founder asked for "something simple like Grasshopper, Dynamo and ComfyUI" and
"blocks wired together". Files make work portable and shareable, like any desktop
program. Visible nodes keep logic inspectable instead of hidden in code.

### HOW

Read any visible thing from outside in:

```text
canvas -> node card -> sockets and parameters -> engine type -> owner/broker
```

Read any change from intent to outcome:

```text
edit or agent request -> node/parameter change -> solve (pure nodes)
  -> Run (effect nodes) -> Approve card where required -> re-read real target
```

**Worked example:** a user drags "Doors of level" from the Library, sets Level to
`L3`, wires its output to "Count". The count updates at once (solve). The user
wires "Place tags" after it and presses Run; the write stops at the Approve card,
then the tags are re-read from Revit.

**Failure/counterexample:** a chat reply says "I tagged 46 doors" but no node or
re-read exists. The words are not the node and are no proof.

### WHO

Users work on the canvas through Use and Build. Agents use the same canvas tools.
Stewards and the founder see Govern. Nobody needs a private language.

### WHEN

Use nodes whenever work should be visible, repeatable, parameterised or shared.

### WHERE

Documents live in `.archhub` files; settings in `settings/<owner>.json`; messages
in `workshop/messages.sqlite3`. See section 3.

### PROOF

- **Authority:** [SPEC.md sections 1 and 2](./SPEC.md), [DECISIONS.md](./DECISIONS.md) D-014.
- **Literature:** Grasshopper, Dynamo and ComfyUI file and solve models, cited in D-014.
- **Court:** `02.TESTS/tests_replica/test_session_files.py` covers the document owner.

## 2. App Scale: Many Nodes, Not One Graph

Scale: app.

### WHAT

The application is a set of owners (canvas documents, settings, Workshop, router,
brokers, Brain) and the canvases people open. Each owner can appear on a canvas as
a node. There is no always-running application graph.

### WHY

Under the retired design every request walked one multi-gigabyte graph; real
sessions timed out at enrollment. The founder: not "an always-running graph
blocking everything". Separate small owners keep the app fast and each failure
local.

### HOW

The launcher starts one file server (`nograph_server.py`). Each Studio route is
answered by the owner that holds that data. The System graph draws how owners,
brokers, routes and agents are wired, live and read-only.

**Worked example:** opening Settings > Workshop reads `settings/workshop.json`;
dropping the Workshop node on a canvas shows the same values as parameters.

**Failure/counterexample:** copying Workshop status into a second file so a
dashboard can read it. That is two truths; the dashboard must call the owner.

### WHO

Each owner has one module responsible for it. Agents and users reach it through
its routes, nodes and canvas tools.

### WHEN

Owners load on demand. Nothing runs in the background unless a user-set trigger
or an agent request starts it.

### WHERE

Under the profile's ArchHub data folder, one file or one small SQLite file per
owner. The retired graph journal stays on disk, unopened.

### PROOF

- **Authority:** [SPEC.md sections 1 and 3](./SPEC.md).
- **Literature:** the strangler pattern for replacing a system route by route.
- **Court:** boot evidence in D-014: 0 graph files opened, 57 of 57 routes answer.

## 3. Floor: Owners and Files

Scale: app floor.

### WHAT

| Data | Owner | File |
|---|---|---|
| Canvas documents, workflows, skills | `session_files` | `*.archhub` |
| Settings | one owner per page | `settings/<owner>.json` |
| Workshop and Workshop | `workshop_mailbox` | `workshop/messages.sqlite3` |
| Model routing | `model_router` | `settings/router.json`, `router.sqlite` |
| Host programs | `host_brokers` | live broker session files |
| Secrets | OS Credential Manager | never in the files above |

### WHY

One owner per kind of data means one truth, simple backup, and no lock on the
whole app.

### HOW

Settings files are replaced atomically. Documents are validated, written to a
temporary file, fsynced and replaced; a failed write keeps the old file. Limits
are in [FORMAT.md](./FORMAT.md).

**Worked example:** two settings pages save at the same moment; each replaces its
own file and neither waits for the other.

**Failure/counterexample:** one JSON blob holding settings, messages and routes;
every write locks everything again.

### WHO

The owner module writes its file. Everyone else calls the owner.

### WHEN

On every save. Opening a document never executes it.

### WHERE

Portable documents anywhere the user saves them; app data under the profile.

### PROOF

- **Authority:** [SPEC.md section 3](./SPEC.md), [FORMAT.md](./FORMAT.md).
- **Literature:** atomic replace on Windows and POSIX file systems.
- **Court:** `02.TESTS/tests_replica/test_session_files.py`, `02.TESTS/tests/test_wire_settings_owner.py`.

## 4. Document Scale: The .archhub File

Scale: document.

### WHAT

A UTF-8 JSON document with `format: "archhub"`, `version: 1`, `id`, `title`,
`nodes`, `wires`, `groups`, `notes` and `viewport`. The schema is
[ARCHHUB.schema.json](./ARCHHUB.schema.json).

### WHY

"Like programs where you save files and share them; those are the workflows and
skills." A file can be emailed, versioned in Git, or dropped onto another machine.

### HOW

Save a canvas as a workflow to run it again, or as a skill to see it as one node
in the Library. Unknown engines survive opening and refuse clearly on Run.

**Worked example:** the founder saves "Tag doors by level" as a skill, sends the
file to a colleague, who drops it in and runs it on their own model.

**Failure/counterexample:** a document that embeds an account token or a local
recent-file path; sharing it would leak data. The format forbids both.

### WHO

The author owns the file. Whoever receives it can open it; effects still need
their own Approve.

### WHEN

On Save, Save As, and recovery autosave.

### WHERE

Wherever the user saves it. Recovery files are local metadata.

### PROOF

- **Authority:** [FORMAT.md](./FORMAT.md), [SPEC.md section 3.1](./SPEC.md).
- **Literature:** Grasshopper `.gh`, Dynamo `.dyn`, ComfyUI workflow JSON.
- **Court:** `02.TESTS/tests_replica/test_session_files.py`.

## 5. Node Scale: Nodes, Sockets and Wires

Scale: node and value.

### WHAT

A node has an engine type, typed input and output sockets, and parameters. A wire
connects one output to one input and may carry a rule.

### WHY

Wires are the only way logic exists on the canvas, so cause and effect stay
visible.

### HOW

Before a wire is made, types are compared; a mismatch is refused with a reason
and an Insert Convert fix. One wire per input. Cycles refuse before any effect.
Socket colour is data type; shape is structure.

**Worked example:** wiring a text output into a number input offers
"Insert text -> number"; one click makes it valid.

**Failure/counterexample:** a line drawn between card centres with no real
sockets behind it.

### WHO

Users and agents, through the same canvas operations.

### WHEN

On every wire gesture; validation happens before the wire exists.

### WHERE

Nodes and wires live in the document.

### PROOF

- **Authority:** [SPEC.md sections 4.2 and 7](./SPEC.md).
- **Literature:** typed ports in Dynamo and ComfyUI.
- **Court:** `02.TESTS/tests_replica/test_canvas_wires_rendered.py`, `02.TESTS/tests_replica/test_crossing_wire_rides_group_boundary.py`.

## 6. Value Scale: Parameters

Scale: value.

### WHAT

Each parameter has a type (number, text, yes/no, file, colour, list, choice,
slider), a default, limits and an editor. Each parameter is also a socket.

### WHY

"Parameters have a data type and a shape according to their job." Every setting
in the app is visible and editable.

### HOW

A Settings row and the node parameter for the same value are one value in one
owner file. Editing either changes both. A changed value shows a dot; Reset
restores the default.

**Worked example:** BABOOM's "Paid use per day" is a Settings row and a socket on
the BABOOM node; wiring a value into the socket changes the row.

**Failure/counterexample:** a parameter shown as a raw JSON text box.

### WHO

Users within their scope; agents through canvas tools.

### WHEN

Applies live; pure downstream nodes re-solve.

### WHERE

In the document for canvas nodes; in `settings/<owner>.json` for app settings.

### PROOF

- **Authority:** [SPEC.md section 4.3](./SPEC.md).
- **Literature:** Grasshopper sliders and panels.
- **Court:** `02.TESTS/tests_replica/test_wire_group_param.py`.

## 7. Solve and Run: The Whole App Is Parametric

Scale: document.

### WHAT

`solve` recomputes pure nodes downstream of a change. `run` executes the document
in wire order, including effect nodes. `invoke` is the only path to an outside
effect.

### WHY

"I want the whole app parametric." Users see results change as they edit, while
writes to real files never happen by surprise.

### HOW

On an edit, pure nodes re-solve within budget; effect nodes are marked "out of
date". Run executes effects in order, stops at the Approve card where policy
requires, then re-reads the real target. A failed node keeps its error; downstream
nodes show Blocked.

**Worked example:** changing a height threshold updates the filtered wall count
at once; the "Set parameter in Revit" node shows "out of date" until Run.

**Failure/counterexample:** an edit that silently writes to Revit because the
graph is always running.

### WHO

Anyone who can edit the document solves it. Running effects needs the Approve
card where policy requires.

### WHEN

Solve on every edit; Run on the Run button, a user-set trigger, or an agent
request.

### WHERE

Solve runs in the app; effects run through brokers in the host programs.

### PROOF

- **Authority:** [SPEC.md section 3.2](./SPEC.md).
- **Literature:** Dynamo Automatic versus Manual run; ComfyUI runs only changed nodes.
- **Current implementation status:** parametric solve is being built (D-014 open item).

## 8. Groups, Library, Workflows and Skills

Scale: document and app.

### WHAT

A group is several nodes shown as one node. The Library lists node types and
saved skills. A skill is a saved document shown as one node.

### WHY

"A node is really a group of smaller nodes." Reuse is save and drop, not code.

### HOW

Ctrl G groups; crossing wires become the group's sockets. Ungroup restores them.
Importers bring MCP tools, flow files (read only), skills and host verbs in as
nodes. Mods install only after a review card.

**Worked example:** five nodes for redline QC are grouped and saved as a skill;
it appears in the Library and on Home with Start.

**Failure/counterexample:** a template that can only be run, never opened as
nodes.

### WHO

Authors save skills; the Library shows them to whoever may use them.

### WHEN

On group, save, import and install.

### WHERE

Skills are `.archhub` files; the Library index is disposable.

### PROOF

- **Authority:** [SPEC.md sections 4.4 and 4.5](./SPEC.md).
- **Literature:** Blender node groups; Dynamo custom nodes.
- **Court:** `02.TESTS/tests_replica/test_crossing_wire_rides_group_boundary.py`.

## 9. Lenses and Progressive Visibility

Scale: app.

### WHAT

| Lens | Shows by default |
|---|---|
| Use | useful objects, values, state, safe actions |
| Build | nodes, sockets, wires, parameters, groups, presentation |
| Govern | authority, lifecycle, provenance, courts, history, impact |
| Advanced | raw parameters, paths, digests, broker diagnostics |

### WHY

Most users should not see hashes to change a colour; experts still need a path
to the detail.

### HOW

Visibility is an authorisation result, not CSS hiding. The server returns only
what the actor may see.

**Worked example:** selecting a wire in Use shows its label; Build adds its rule
and data; Advanced adds socket types and ids.

**Failure/counterexample:** sending secret references to everyone and hiding them
with CSS.

### WHO

Grants decide available lenses.

### WHEN

On every view and change.

### WHERE

Lens choice is view state; data stays in its owner.

### PROOF

- **Authority:** [SPEC.md section 6](./SPEC.md).
- **Literature:** progressive disclosure in WCAG 2.2 and WAI-ARIA practices.
- **Court:** not yet one release court for the full audience matrix.

## 10. Lifecycle, History and Effects

Scale: app and document.

### WHAT

Independent axes stay separate:

- information state: WIP, Shared, Published, Archived;
- product source: WIP, Production;
- deployment: candidate, Deployed, retired;
- operation: pending, running, succeeded, failed, denied, reconciled;
- visibility/trust: private, team, public, classification, approval;
- external outcome: requested, accepted, settled/issued, rejected, reversed.

### WHY

One `status` field cannot say whether something was approved, written, or
actually happened in the host program.

### HOW

Saves are atomic. Two edited copies of one file are two files; merging is an
explicit choice. Effects separate request, approval, attempt, outcome,
reconciliation and current view.

**Worked example:** a sheet export is requested, approved, attempted; the broker
reports success; the file is re-read; only then the node shows done.

**Failure/counterexample:** a node marked done because the agent said so.

### WHO

Authors create WIP; the founder's Approve card authorises real-world effects.

### WHEN

On save, Run and every external effect.

### WHERE

Documents in files; outcomes from the host program are re-read, not assumed.

### PROOF

- **Authority:** [SPEC.md section 8](./SPEC.md).
- **Literature:** UK BIM Framework CDE states (WIP, Shared, Published, Archived).
- **Court:** effect re-read is required by SPEC court 5.

## 11. Security, Brokers and Accounts

Scale: app.

### WHAT

Brokers are the narrow bridges to host programs and services. The account is the
identity, never the machine.

### WHY

Agents must read and write every program the founder uses without leaking data
or blocking his own work.

### HOW

Brokers expose typed actions; raw code exists only behind the Approve card.
Secrets live in the OS Credential Manager. A registered workspace is open to the
user's own agents with no prompt. The permission system stays at the real edges:
other people, client data, the public, model writes, real harm. No signed-owner
key layer may block the app (D-009).

**Worked example:** an agent reads Revit doors freely; placing tags shows the
Approve card with the count.

**Failure/counterexample:** a token written into a shared `.archhub` file.

### WHO

The founder approves effects; brokers enforce their action lists.

### WHEN

On every broker call.

### WHERE

Host programs; Credential Manager for secrets.

### PROOF

- **Authority:** [SPEC.md section 9](./SPEC.md), [DECISIONS.md](./DECISIONS.md) D-009.
- **Literature:** least-privilege capability design.
- **Court:** broker courts per host; installed acceptance with 717.

## 12. Agents, the Workshop and Attention

Scale: app.

### WHAT

Any agent installed on the PC (Claude Code, Codex, OpenCode, Gemini CLI, Goose
as BABOOM and others) works inside the canvas through canvas tools, and talks in
the one Workshop with Workshop.

Attention records, owned by the Brain and Workshop in plain files:

- A **Signal** records an observed committed change with source revision,
  provenance, trust, audience, time, and deduplication identity.
- **Attention** relates an observer to an authorised candidate, source snapshot,
  explicit reasons, ordering policy revision, expiry, and evidence.
- **Focus** records the bounded current working set for an actor/view session,
  including scope, reason, origin, interruption state, and recovery history.
- An **Obligation** unifies requirements, Grand Map leaves, Core Value gaps,
  failing courts, security findings, accepted work, dependencies, evidence, and
  resolution history.
- **Decision** and **Outcome** compositions preserve the selected action, actor,
  authority, evidence, effect receipt, reconciliation, and
  reversal/compensation.

### WHY

Provider agnostic: "everything works for any agent installed on the PC". Work an
agent does must be visible as nodes, not hidden in its transcript.

### HOW

Attention ordering is a visible partial order:

1. safety and data-loss risk;
2. explicit user/founder pin;
3. blocking dependency;
4. failed active court;
5. accepted due work and fairness;
6. optional model-proposed relevance.

Candidates are authorised before ranking. Model output is untrusted proposal
evidence. Workshop messages are addressed and injected into the recipient session.

**Worked example:** the founder asks BABOOM to tag doors; Codex places the nodes
on a canvas, Claude Code reviews them in the same Workshop task, and the write
stops at the Approve card.

**Failure/counterexample:** a capability that works only for one vendor's CLI.

### WHO

The founder sets intent; agents propose and do bounded work; reviewers check the
real result.

### WHEN

On request; nothing runs while idle.

### WHERE

`workshop/messages.sqlite3` for messages; documents for canvas work.

### PROOF

- **Authority:** [SPEC.md sections 4.6 and 5](./SPEC.md), [CLEAN-COORDINATION-ENDPOINT.md](./CLEAN-COORDINATION-ENDPOINT.md).
- **Literature:** MCP tools as the common agent interface.
- **Current implementation status:** agent canvas tools are being built (D-014 open item).

## 13. Visual Authoring and Performance

Scale: document.

### WHAT

The canvas is the primary language surface: cards are nodes, dots are sockets,
cables are wires, the left panel is the Library, the right panel is the inspector.

### WHY

A universal back end is useless if the canvas lies about topology or controls
cannot be found.

### HOW

- wheel zoom is cursor-centred;
- pan, drag, wire, resize and marquee use pointer capture;
- left-to-right marquee contains, right-to-left crosses;
- double-click or Enter opens a group; breadcrumbs and Esc return;
- tabs exist only when they apply.

| Interaction measure | Required threshold |
|---|---|
| Pointer frame | p95 <= 16.7 ms |
| Selection feedback | same frame |
| Local mutation acknowledgement | <= 100 ms |
| Bounded scope entry | <= 150 ms |
| Steady-state long task | no task > 50 ms on the reference machine |

**Worked example:** dragging from a socket highlights only compatible targets;
release creates one undoable wire.

**Failure/counterexample:** rebuilding the whole DOM on every pointer move.

### WHO

All users; keyboard and pointer have equivalent actions.

### WHEN

Every gesture; courts run on the packaged artifact before release.

### WHERE

Gesture paint in the browser; committed state in the document.

### PROOF

- **Authority:** [SPEC.md sections 7 and 11](./SPEC.md).
- **Literature:** Pointer Events; WCAG 2.2.
- **Court:** `02.TESTS/tests_replica/test_universal_ui_performance.py`.

## 14. Migration From the Retired Cell Graph

Scale: app.

### WHAT

The strangler migration: each Studio route moves from the graph to its file owner.

### WHY

"We give up nothing." The store changes; what the user gets does not.

### HOW

For each area: list the behaviours it had, give the data one owner and file,
serve the route from that owner, prove each behaviour on the installed app, then
remove the graph path in the same patch. Routes not yet moved answer a plain
`not_available` notice and stay open items.

**Worked example:** the Workshop route is answered from
`workshop/messages.sqlite3` with Workshop; the graph is not read for it.

**Failure/counterexample:** deleting a screen because its graph route is gone.

### WHO

Lanes build; 717 lands and installs; the founder accepts on his machine.

### WHEN

Owner by owner, close before open.

### WHERE

The route table in `01.APP/nodelang/nograph_server.py`.

### PROOF

- **Authority:** [SPEC.md section 12](./SPEC.md), D-014.
- **Literature:** strangler fig application pattern.
- **Court:** 57 of 57 routes answer (D-014 evidence).

## 15. Normative Target Versus Current Status

Scale: all.

### WHAT

This handbook describes the target. Current status lives in revision-bound
evidence and result files, not here.

### WHY

Truth over comfort: a document cannot make a feature work.

### HOW

Open items named here (parametric solve, agent canvas tools, graph-only routes)
are closed only by evidence on the installed app.

**Worked example:** D-014 records boot 0.403 s and 57 of 57 routes from a
disposable profile; installed acceptance is still open.

**Failure/counterexample:** quoting a test count as completion.

### WHO

Builders record evidence; independent verifiers check it.

### WHEN

After every install.

### WHERE

`05.EVIDENCE/` and the lane RESULT files.

### PROOF

- **Authority:** [AUTHORITY.md](./AUTHORITY.md) "Mutable truth".
- **Literature:** none required.
- **Court:** the release gate on the installed app.

## 16. Sources and Maintenance

Scale: all.

### WHAT

| Source | Kind | Use here |
|---|---|---|
| [SPEC.md](./SPEC.md) | authority | normative target |
| [DECISIONS.md](./DECISIONS.md) D-014 | decision | request, prior art, budgets |
| [FORMAT.md](./FORMAT.md) | contract | `.archhub` document |
| [04.ARCHIVE/MANIFEST.md](./04.ARCHIVE/MANIFEST.md) | archive | retired Cell texts and hashes |

### WHY

One place to see what this handbook depends on.

### HOW

Change this handbook only after the specification or a decision changes.

**Worked example:** D-014 changed the store; this handbook was rewritten the same
day and the old text archived.

**Failure/counterexample:** editing the handbook to describe a design that no
decision adopted.

### WHO

Docs lanes; reviewed by 717.

### WHEN

With every authority change.

### WHERE

`04.DOCS/`.

### PROOF

- **Authority:** [AUTHORITY.md](./AUTHORITY.md).
- **Literature:** none.
- **Court:** the old byte-pinning handbook court (`02.TESTS/tests_replica/test_node_language_handbook_conformance.py`) targets the archived Cell handbook and must be updated by the code owner.
