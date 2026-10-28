# ArchHub Node Specification

Version: 0.2 WIP (NOGRAPH)
Date: 2026-10-28
Status: normative implementation target; not a completion claim
Supersedes: the Universal Cell Specification 0.1 (2026-07-16), kept unchanged at
`04.ARCHIVE/SPEC-universal-cell-2026-07-16.md`. Decision: D-014 in `DECISIONS.md`.

This document defines what ArchHub must become. It does not report mutable
progress, test counts, percentages, deployments, or release status. Those belong
in revision-bound evidence.

The words MUST, MUST NOT, REQUIRED, SHALL, SHALL NOT, SHOULD, SHOULD NOT, and MAY
are normative.

## 1. Product invariant

ArchHub is a simple visual node application, like Grasshopper, Dynamo and
ComfyUI: blocks wired together on a canvas, saved as files people can share.

1. **Everything is a node.** Every capability of the app (a host action, a
   setting owner, an agent, the Workshop, the Brain, a model route, a check) can
   be dropped on a canvas as a node with sockets and parameters and wired to
   other nodes. "Everything is a node" means everything is wireable. It does NOT
   mean everything is stored in one graph.
2. **A canvas is a workspace of nodes where people and agents work.** Any use of
   the words "graph" or "canvas" in the product means this workspace. There is no
   single always-running application graph.
3. **A document is a file.** Each canvas is one `.archhub` file (see `FORMAT.md`
   and `ARCHHUB.schema.json`). A workflow and a skill are both `.archhub` files.
   Save, open, copy and share work like any desktop program.
4. **The whole app is parametric.** Pure nodes re-solve when an input, wire or
   parameter changes. Effect nodes (anything that writes a file, changes a host
   program, sends, posts, spends or calls a model) run only when the user presses
   Run, and then pass the one Approve card where their policy requires it.
5. **Nothing runs in the background by itself.** No graph is kept running, and
   nothing blocks other work while idle. Work runs on Run, on an explicit trigger
   the user set (schedule, file change, host event), or on an agent request.
6. **Provider agnostic.** Every node, broker, Workshop message and canvas tool
   works for any agent installed on the PC (Claude Code, Codex, OpenCode, Gemini
   CLI, Goose/BABOOM and others). No capability is tied to one vendor.
7. **We give up nothing.** Re-engineering changes what sits underneath, never
   what the user gets. A feature that worked on the Cell graph and has no file
   owner yet is an open item with a visible notice, never a silent removal.

## 2. Terms

- **Node:** one block with an engine type, typed input and output sockets, and
  typed parameters. A parameter is also a socket: type a value or wire one in.
- **Socket:** a typed connection point. Colour is data type; shape is structure
  (event, single, list).
- **Wire:** one connection from an output socket to an input socket, optionally
  with a rule (condition) using the existing wire condition grammar.
- **Group:** nodes collapsed into one node; crossing wires become its sockets.
- **Document:** one `.archhub` file holding nodes, wires, groups, notes and the
  viewport.
- **Workflow:** a document saved to be run again.
- **Skill:** a document saved so that it appears as one node in the Library.
- **Pure node:** a node whose outputs depend only on its inputs and parameters.
- **Effect node:** a node that changes something outside the document.
- **Solve:** recomputing pure nodes downstream of a change.
- **Run:** executing the open document in wire order, including effect nodes.
- **Owner:** the one module that holds one kind of data in one plain file or one
  small SQLite file.
- **System graph:** a live, read-only view of how the running app is wired
  (owners, brokers, routes, agents). It is a picture of the app, not a store and
  not an editor.
- **Lens:** an authorised view of the same data for a purpose and audience.
- **Court:** an executable acceptance check bound to an exact artifact, revision,
  environment and evidence set.
- **Broker:** the narrow admitted bridge to one host program or service.

## 3. Storage floor

### 3.1 Owners and files

Each kind of data has exactly one owner and one file. No owner reads another
owner's file directly; it calls that owner.

| Data | Owner | File |
|---|---|---|
| Canvas documents, workflows, skills | `session_files` | `*.archhub` (portable) |
| Settings | one owner per page | `settings/<owner>.json` |
| Workshop messages and Workshop | `workshop_mailbox` | `workshop/messages.sqlite3` |
| Model routing | `model_router` | `settings/router.json`, `router.sqlite` |
| Host programs | `host_brokers`, `pipeline_engines` | live broker session files |
| Workspaces | settings owner | `settings/workspaces.json` |
| Secrets | OS Credential Manager | never in a file above |

Rules:

1. Settings files are replaced atomically (write temporary, then replace).
2. A `.archhub` document holds no account identity, local recent paths, tokens or
   secrets. Recent paths and recovery files are local metadata.
3. Opening a document never executes it.
4. Boot opens no graph journal, enrols no agent and checks no signed authority.
   The app is usable as soon as its window and its files are readable.
5. A search index, cache or thumbnail MAY exist only as disposable acceleration;
   deleting it MUST NOT change meaning.
6. The retired universal graph journal is not opened, read or written by the
   app. It stays on disk until the founder decides otherwise.

### 3.2 Execution boundary

```text
solve(document, changed_nodes)          pure nodes only, on every edit
run(document, from?, to?)               all nodes in wire order, on Run
invoke(broker_action, inputs, approval) the only path to an outside effect
```

- `solve` MUST be bounded, deterministic and side-effect free. It recomputes only
  nodes downstream of the change and marks effect nodes "out of date".
- `run` executes in topological order. Cycles refuse before any effect. A failed
  node keeps its error; downstream nodes show Blocked.
- `invoke` carries a typed request; writes pass the one Approve card where the
  policy requires it, and the result is re-read from the real target.

Every solve, run and invoke has an explicit budget and a deterministic failure
state.

### 3.3 Honest boundary

Pixels, DOM nodes, GPU buffers, OS handles, sockets, key bytes and process stacks
are machinery, not nodes. Their contracts, settings, requests and observable
outcomes are visible as node parameters and results.

## 4. Meaning and computation

### 4.1 No hidden logic

Logic lives in nodes and wires the user can see. An engine implements one node
type behind its declared sockets; product behaviour MUST NOT hide in a branch the
canvas cannot show. A chat request becomes nodes the user can see and edit.

### 4.2 Wires

A wire connects one output to one input. Before a wire is made, socket types are
compared; a mismatch is refused with a reason and an **Insert Convert** fix. One
wire per input. A wire may carry a rule ("only if the check passed"). Named socket
values are delivered in topological order.

### 4.3 Properties and parameters

Each parameter has a type (number, text, yes/no, file, colour, list, choice,
slider), a default, limits and an editor. It is shown with the right widget,
never as a text blob. Editing a value in the inspector re-solves pure nodes at
once. A Settings row and the matching node parameter are the same value in the
same owner file; changing one changes the other.

### 4.4 Composition and scale

Grouping creates one node from several and keeps their identities and wires.
Ungrouping restores them. Opening a group changes scope; it does not open a
second store. A saved skill is a group saved as its own `.archhub` file.

### 4.5 Reusable catalogue

The Library lists node types (from engines, importers, mods) and saved skills.
Click, drag and keyboard placement create the same node. Filtering is local view
state and changes no file. Importers bring ecosystems in as nodes: MCP tools,
flow files (read only, their servers never run), skills, host verbs.

### 4.6 Agents on the canvas

Agents work inside the canvas through the same node, wire, parameter, solve and
run operations the user has, exposed as canvas tools to any installed agent. An
agent's work is visible as nodes. Agents cannot bypass the Approve card or gain
authority by using a private API.

## 5. Attention and memory

Persistent attention survives from the earlier specification as a target; its
records are owned by the Brain and Workshop owners in plain files, not Cells.

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
  authority, evidence, effect receipt, reconciliation, and reversal/compensation.

The first ordering policy MUST be a visible partial order: safety and data-loss
risk, explicit user/founder pin, blocking dependency, failed active court,
accepted due work and fairness, then optional model-proposed relevance. Every
ordering edge has an inspectable reason. Model output is untrusted proposal
evidence and cannot broaden scope or authority.

Candidates MUST be authorised before ranking. Hidden items MUST NOT influence
visible counts, order, explanation, embeddings, or model context. These records
MUST survive process close and restart.

## 6. One application, many lawful lenses

The same data is reachable, subject to authority, from every applicable screen.
No screen owns a duplicate truth field.

1. **Use:** ordinary work, clear names, status, direct manipulation, safe
   actions. No hashes, raw ids or JSON.
2. **Build:** nodes, sockets, wires, parameters, groups and presentation.
3. **Govern:** authority, lifecycle, provenance, courts, decisions, history,
   impact and release evidence.
4. **Advanced:** raw parameters, file paths, digests and broker diagnostics for
   authorised experts.

Visibility is an authorisation result, not CSS hiding. Brain, Cockpit, Grand Map
and the System graph open inside the same application and read the same owners.

## 7. Visual language and interaction

1. The app opens on Home; the canvas is one click away.
2. Groups are enterable by double-click/Enter, with breadcrumbs and Esc back.
3. Wheel zoom is cursor-centred. Pan, drag, wire and resize use pointer capture
   and stay stable under zoom.
4. Selection follows AEC behaviour: click, Ctrl additive toggle, Shift
   removal/range, left-to-right containing window, right-to-left crossing window.
5. The inspector for a multi-selection shows only parameters common to all;
   mixed values are explicit; editing one is one undoable step.
6. Every visible socket is a real declared socket; every cable is a real wire.
7. Selecting a node, wire or group opens its inspector. Tabs appear only when
   they apply; empty or decorative tabs are forbidden.
8. Users edit labels, icons, colours, parameters and rules without CSS or code.
9. Delete, group, ungroup, arrange, drag and paste are single undoable steps.
10. Technical identity and hashes are available in Govern/Advanced only.

Interaction courts use real browsers and the actual artifact. Source-string
assertions and backend-only tests cannot release visible behaviour.

## 8. History, lifecycle and concurrent work

Undo, restore and rejection add new steps; they do not erase history.

The following independent axes MUST NOT be collapsed into one status string:

- information authoring/review: WIP, Shared, Published, Archived;
- canonical product source: WIP or Production;
- deployment selection: candidate, Deployed, retired;
- operational state: pending, running, succeeded, failed, denied, reconciled;
- visibility/trust: private, team, public, confidentiality tier, approval state;
- external outcome: requested, accepted, settled/issued, rejected, reversed.

A document save is atomic: a failed write keeps the old file. Two people editing
copies of one `.archhub` file produce two files; merging is an explicit, visible
choice, never last-write-wins. Host writes, sends, payments and deployments
separate request, approval, attempt, outcome, reconciliation and current view. A
label such as `done` is never proof of an external effect. Large geometry, image
and document bytes stay in their own files; a node references them.

## 9. Security and external capabilities

1. Every read, write, send and publish evaluates actor, action, object, audience,
   scope, policy and data classification.
2. Network or process location grants no implicit trust.
3. Secret bytes, private keys, bearer tokens and live capability handles MUST NOT
   enter `.archhub` files, settings files, logs, model prompts, URLs, command
   lines or client bundles. Secrets live in the OS Credential Manager.
4. Brokers are versioned, allowlisted, least-privilege and revocable. Unknown
   actions fail closed. Raw "run any code" exists only as an escape hatch behind
   the Approve card.
5. The account is the identity, never the machine (D-009). No signed-owner key
   layer may block the app.
6. A registered workspace is open to the user's own agents without prompts. The
   permission system stays at the real edges: other people, client data, the
   public, writes to host models, and real harm.
7. Untrusted content and model output cannot change policy or run an effect
   without the required approval path.

## 10. Governance and Core Values

The founder Core Values are constitutional input; their translation remains WIP
until founder-reviewed. Every released slice maps the ten values to exact
controls or explicit gaps:

- Security is Sacred Trust -> threat model, least privilege, secret handling,
  privacy, incident and recovery evidence.
- Truth Over Comfort -> honest status, residual risk, and no false completion.
- You Build It, You Own It -> named owner, operation, observability, maintenance,
  and decommission path.
- Respect Every Second -> measured latency, bounded work, direct manipulation,
  and no needless user ceremony.
- Architect Review Mandatory -> founder/architect review at the defined authority
  threshold.
- Solve Real Pain -> traced founder/user requirement and outcome evidence.
- Simplicity Conquers Complexity -> nodes, wires and files; progressive
  disclosure.
- Test What You Ship -> courts on the real packaged artifact.
- Break It Down, Iterate Fast -> bounded WIP slices without partial-green claims.
- Fix Root Causes -> contradiction and recurrence analysis, not cosmetic patches.

The Workspace Standard governs placement, privacy and release custody. It does
not define a second node model.

## 11. Required acceptance courts

A slice is complete only when all applicable courts pass against its exact
revision and artifact:

1. One owner: each kind of data has one owner and one file; no second copy.
2. No graph at boot: boot opens no graph journal, imports no graph server and
   enrols no agent.
3. File round trip: save, close, open and share a `.archhub` document with no
   loss; opening never executes it.
4. Parametric solve: editing a parameter re-solves pure downstream nodes and
   marks effect nodes out of date without running them.
5. Run: Run executes in wire order, refuses cycles before effects, and stops at
   the Approve card where required; the result is re-read from the real target.
6. Every app capability is placeable as a node with sockets and parameters.
7. Provider agnostic: brokers, Workshop and canvas tools work for every installed
   agent, proved with at least two different vendors.
8. Nothing given up: every behaviour that worked before is listed and still works,
   or is shown as an open item.
9. User control: a nontechnical user can understand cause, edit permitted state,
   undo and recover.
10. Interaction: selection, zoom, pan, drag, wire, keyboard, focus and pointer
    capture pass in a real browser.
11. Performance: pointer frame p95 <= 16.7 ms, same-frame selection feedback,
    local mutation acknowledgement <= 100 ms, bounded scope entry <= 150 ms, and
    no steady-state long task over 50 ms on the reference machine.
12. Lifecycle/effect: independent states, receipts, reconciliation and recovery
    are proven.
13. Core Values: each value maps to a passing control or visible gap.
14. No false done: report exact revision, environment, evidence, open items,
    residual risk and untested boundary.

Security, privacy, data-loss and one-owner failures are release blockers.

## 12. Migration and conformance

The Universal Cell runtime and its journal are retired as the store. Migration
proceeds owner by owner (strangler pattern):

1. trace the founder requirement;
2. list the user-visible behaviours the area had on the graph;
3. give the data one owner and one file;
4. serve the Studio route from that owner;
5. prove each listed behaviour still works on the installed app;
6. remove the graph path for that function in the same patch (delete on replace);
7. archive, never delete, the documentation it replaces.

Routes still answering `not_available` are open items until step 5 passes.

## 13. Evidence and references

Authority order is defined in `AUTHORITY.md`. Implementation truth is recorded
separately from this specification.

- `DECISIONS.md` D-014 NOGRAPH (request, prior art, replacement, budgets).
- `FORMAT.md` and `ARCHHUB.schema.json` (the `.archhub` document).
- `01.APP/nodelang/nograph_server.py` (the file server and its route table).
- `70.COMPANY/72.HANDOFFS/72.60-NEW-APP/APP-BUTTONS/RESULT-NOGRAPH-SERVER.md`.
- Archived Universal Cell specification: `04.ARCHIVE/SPEC-universal-cell-2026-07-16.md`.
