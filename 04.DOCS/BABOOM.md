# BABOOM Assistant Boundary

Status: WIP capability boundary, not a release claim.

BABOOM is ArchHub's founder-facing projection of the same Universal Cell
application that holds Work, Workshop, attention, device custody, consent,
delegations, grants, and receipts. It is not a separate chat history, task
queue, supervisor, or model control plane.

## Current graph authority

- One Workshop root and Workbench scope hold research, planning, priority,
  approval, review, and validation evidence.
- Admitted providers are graph-defined reviewers. They receive the bounded
  shared coordination brief only after a graph request and cannot advance Work
  without the applicable approval and one-use grant.
- Founder task creation is explicit and idempotent. A BABOOM task remains open
  until a device-proven runtime claims it through the Work lifecycle.
- Foreground activity is an expiring, allowlisted application label only. It
  excludes titles, paths, documents, pixels, audio, clipboard, keystrokes, and
  process metadata.

## Workshop Council Contract

Every admitted provider receives the same sealed, bounded coordination brief
for the same planned Work. The brief is a Cell-held snapshot of the applicable
Workshop entries, active Work, plan state, released priority policy, attention
obligations, and previously recorded safe peer-review evidence. It does not
expose raw graph access, protected material, credentials, file paths, or live
screen content.

The enforced order is research, scope and privacy review, priority, bounded
proposal, founder approval, then validation and review. A provider review is
untrusted evidence, never an instruction or a second control plane. A later
reviewer sees earlier admitted reviews through the same brief, so it can test
and improve the work rather than restart from an isolated prompt. Each provider
still needs its own approved invocation, and every external effect remains
separately consented, granted, and receipted.

## Native companion

The Windows companion is a disposable projection. It uses the packaged
transparent BABOOM sprite atlas, derives placement from the graph frame, avoids
the foreground window, and has no local task or conversation store.

### Presence requirements before native release

- One graph identity projects as at most one BABOOM presence on an allowed
  surface. A duplicate window, bubble-only remnant, or a local companion state
  independent of the graph is a defect.
- BABOOM and any compact report remain wholly inside the recoverable work area.
  They yield to foreground controls, focused inputs, modals, canvas selections,
  and declared active work rather than competing for desktop space.
- A report is one plain compact rectangle. It has no tail, decorative dots,
  transparent outer frame, conspicuous outline, or nested card. The staff
  crystal is the only optional graph-derived health cue; a separate green dot
  is forbidden.
- Presence changes are revision, attention, approval, receipt, or collision
  driven. Idle wandering, unconditional layout movement, flicker, and
  crossfade ghosts are defects. A rendering cadence may repaint a released
  pose, but it must not re-place or re-raise the companion without such an
  event.
- A compact report may summarise, but its full authorised message, source,
  freshness, scope, and applicable evidence or receipt must remain available
  through the same graph-backed command route. It must not silently truncate a
  founder-relevant outcome.

- Click BABOOM to reply or assign a task.
- `Talk` requests one Windows SAPI dictation utterance. It never starts a
  background listener, retains audio, or creates Work directly.
- A recognized utterance follows the same graph-backed command path as typed
  input. Consequential Work creation still requires the existing confirmation.
- A device-proven native host may publish one released foreground-app label,
  throttled to an expiring activity lease.

Creating the companion assembly alone does not connect a device, start a
heartbeat, show a window, activate voice, or replace an existing runtime.

### Warnings on real events (lane baboom-settings patch 2026-09-24; not landed, not installed)

BABOOM's directive (`project_universal_baboom_companion_directive`) warns,
after blocked Work and a silent brain and before every count, when:

- an agent session stopped answering: its graph presence lease lapsed in the
  last 15 minutes (`list_lapsed_runtime_presences`, the same leases Presence
  reads; no cleanup write, no second store). Reported as runtime names in
  `agents.gone`.
- the last Run failed or a host or connector refused: `last_pipeline_run()`
  now records `failed` (engines whose effect raised) and `refused` (engines
  that answered `ok: False`), engine names only.
- an update is ready: unchanged, the staged-update record.

The message names runtimes and engines, never node titles, values or refusal
text. The directive carries the `status` action so the companion panel shows
the message; the next clean Run or a renewed lease clears it. No new top-level
context key: the machine transport reads the same seventeen keys.

### Stop that ends the run (same patch)

A Workshop Stop (`stop_native`) first sends interrupt and closes the agent's
input. When the child ignores both past its stop budget, the owned process
tree (only PIDs this process owner observed, matched by creation time) is
killed and the status reads `error_code: forced_stop`, `drained: true`,
`requires_reconciliation: true`; the interrupted turn's outcome is
`uncertain` and is never replayed. The same session can start again. Before
this patch such a child kept running with `cooperative_stop_timeout`.
BABOOM's own Stop remains session-only (no new requests; see below).

### Persistent startup control (approved 2026-09-16 as designed; landed and installed, not released)

Approved design (717 record line 32): one persistent on/off control held on
the BABOOM agent-body composition, owner-only, effective at the next launch,
fail-closed, relay reads allowed while it is off. Landed in source at commit
`f61ac9b` (2026-09-16 17:34; four commits below HEAD `b914892`), first
installed as build `20260916-1740-f61ac9b` (17:47, "boot 72s") and now
installed as `20260916-2105-b914892` (`%LOCALAPPDATA%\ArchHub\BUILD_ID`
written 20:53; `%LOCALAPPDATA%\ArchHub-Test\boot-profile.log` "boot 67s";
`launcher.log` "BABOOM : attached (signed agent session)"). Publicly released
20:58 as GitHub release `build-20260916-2105-b914892` (`DELIVERY-STATUS.md`
row "DONE installed 2026-09-16 20:53"); not accepted (row "BLOCKED / OPEN").
The landing record (row "DONE landed 2026-09-16 17:33") reports 56 courts
passed; they were not re-run for this page. What the code
does, read from the working tree on 2026-09-16 (line numbers as of HEAD
`b914892`):

- The value lives in the graph, not in a marker file.
  `read_universal_baboom_startup` (`01.APP/nodelang/universal_application.py:26583-26663`)
  derives one asset root and one binding root from the owner's view session
  and `app:agent-body:baboom` (`_baboom_startup_roots`, `:26568-26580`;
  `_AGENT_BODY_BABOOM_ROOT`, `:1643`); the binding's expected members include
  the owner role on `app:agent-body:baboom` and the contract
  `app:contract:baboom-startup:v1` (`:825-830`, `:26612-26618`).
- Absent record: when neither the asset nor the binding cell exists, the
  reader returns `value` `"on"` with `source` `"default"`
  (`_BABOOM_STARTUP_DEFAULT = "on"`, `:828`; `:26600-26608`), so a graph that
  has never stored the setting starts BABOOM. The court
  `02.TESTS/tests_replica/test_baboom_startup_setting.py:137`
  (`test_a_fresh_graph_reads_default_on_without_a_write_or_a_cell`) holds that.
- Malformed record: a partial binding (`:26609-26610`), a drifted binding or
  contract (`:26620-26634`), more than one WIP head (`:26644-26645`), a value
  other than `on`/`off` (`:26648-26653`) or an actor other than the owner
  (`:26654-26655`) raises `InvalidCell`. The launcher then does not start
  BABOOM and records "BABOOM did not start because its Settings value is
  unreadable; no action was performed." (`01.APP/nodelang/launcher.py:1013-1022`),
  and the canvas projection reports `source` `"unreadable"` (`:26672-26685`).
  The court `test_baboom_startup_setting.py:385` holds that. This is where the
  code fails closed; an absent record does not.
- `off`: the launcher records "BABOOM is turned off in Settings; no action
  was performed." and returns before any key file, custody commit or attach
  attempt (`01.APP/nodelang/launcher.py:1025-1028`). While no host is attached,
  a relay execute request is refused with that recorded reason
  (`_cockpit_execute`, `:1101-1108`); the `DELIVERY-STATUS.md` row "DONE landed 2026-09-16 17:33" states that relay
  reads are answered while off.
- Writing: `set_universal_baboom_startup` (`:26711` onward) accepts `on` or
  `off` only (`:26725-26726`), is owner-only ("BABOOM startup belongs to the
  instance owner", `:26731-26734`), takes effect at the next launch
  (`:26721`), refuses a stale base revision ("BABOOM startup changed; refresh
  before saving") and a no-op ("BABOOM startup is already on/off"), and
  appends a WIP revision outside canvas undo history (`:26721-26723`).
  Studio: Settings > BABOOM switch (`01.APP/nodelang/studio/studio-lm.jsx`,
  `setBaboomStartup` and `configuration.baboom_startup`;
  `01.APP/nodelang/studio/studio-existing-workshop.js:87-106`, kind `baboom-startup`);
  `01.APP/nodelang/application_server.py:491` carries `baboom_startup` in the
  configuration delta. Courts tracked at `f61ac9b`:
  `02.TESTS/tests_replica/test_baboom_startup_setting.py`,
  `test_baboom_startup_lifecycle.py`, `test_studio_baboom_startup.cjs`;
  `test_baboom_startup_qt.py` is untracked in the working tree.
- The session-only controls (hide, stop-new-requests, voice cancellation,
  stale-report suppression; `DELIVERY-STATUS.md` row "ACTIVE - BABOOM") and the tray action "Stop
  BABOOM for this launch" (`01.APP/nodelang/launcher.py:912`) remain session-only
  and do not write the setting.

## External capability boundary

- GPT, Claude, Gemini, OpenRouter, and local models are admitted only through
  the graph-held model execution protocol. Physical CLI discovery or a
  credential is not execution authority.
- Meeting-notes consent is graph-held. Joining meetings, microphone capture,
  transcription, and external publication remain separate physical adapters and
  need explicit provider configuration, consent, approval, and receipts.
- Notion publication requires an admitted configured connector and live meeting
  consent. It must not treat an expired or missing OAuth grant as access.
- Cross-device presence and Work handoff require separately device-proven
  sessions and an available remote gateway. They are not implied by a local
  desktop companion.

## Handoff rule

The canonical Node Language runtime may be started only through the controlled
handoff gate. A copied or legacy holder must never be restarted, replaced, or
described as canonical merely because a newer companion projection exists.


### F278 / F279 / F280: shared persona, standard and reactions (candidate)

Founder request: "personality is data and can never change permissions or outcomes"; "ONE standard index shared with the baboom.archhub.io site chat"; "agent-event -> pose map for EVERY agent". Research: res-020 (2026-11-05) and res-021 (2026-11-06), read in full. Fit the existing site BM25 owner and Workshop activity log; no new brain, message channel, index source, agent runtime or permission owner.

The human voice source is `30.KNOWLEDGE/35.DESIGN-SYSTEM/35.07-BABOOM-BRAND/01.WIP/BABOOM-BRAND-BOOK.html#s03`: "One voice, his: precise, practical, a little playful. The tone moves with the moment." Source SHA-256: `795e3a5aff86e1c35c9ce631051686c484945850d83373d5e1c9128d107cbdb6`. `03.TOOLS/tools/baboom_persona.py` extracts tone, examples, forbidden words and all six EN/AR moments into `01.APP/nodelang/data/baboom/persona.json`. Regenerate from that source rather than hand-editing a second persona. Counts in the book are explicitly samples, never outcome receipts. Goose snapshots communication fields at each turn; those fields cannot configure permissions or replace host outcomes. Failed, denied and unknown receipts, including nested ACP content and structuredContent, use deterministic host status. The public site and Workshop reply boundary identify BABOOM as an AI assistant independently of persona/model text. English/Arabic identity questions have a deterministic answer.

Prior art: OpenPets (MIT, mechanisms studied in res-021) supplies the event-to-reaction, ten-second anti-nag and data-only persona patterns; Notion AI's cited workspace answers (res-020) supplies the grounded-answer pattern. Adapted to existing owners, rather than adding another pet runtime or retrieval corpus. Current primary references checked: SQLite FTS5 BM25 documentation and Claude Code hooks documentation. The existing site's BM25 shape is retained (k1 1.2, b .75, heading weight 3); direct excerpt answers carry STD citations and unsupported queries are refused. The prepared site retains the existing authenticated router adapter, with passages treated as data and a prompt requiring document citations. Signed-out visitors receive the existing English/Arabic sign-in response and closest-document links without any model call; closest-document retrieval uses the live site BM25 rules, while direct grounded lookup retains its stricter matching.

The ONE standard index remains `/opt/baboom-chat/index.json`, built by the existing `50.TOOLING/52.AEC-LIBRARIES/52.03-BA-STANDARD/14.BABOOM-CHAT` publisher from its privacy-scanned edition. Desktop `baboom_standard.ask_standard` calls the existing site's `/api/chat`; it has no local corpus or bearer, refuses redirects and bounds its response. Standard lookup accepts questions, not commands to apply a standard. `03.TOOLS/tools/prepare_baboom_site.py <existing server.py> --out <deployment artifact>` removes the old Index/answer/VOICE definitions from that server and imports the same packaged product modules and persona. It preserves the existing routes, rate limits and authentication code, and does not build or deploy an index. Deploy the resulting server.py and nodelang package together through the existing site publisher; keep its existing index.json. Preparing an artifact is not live deployment. A sign-in response is navigation and is reported as unavailable by the desktop, even if its prose contains a citation; it is never passed off as a grounded answer.

Hook feedback and native Claude/Codex events go through `baboom_reactions` into the existing Workshop `workshop_activity` table. Only hashed session identity, reaction kind and a deduplication digest are retained; no prompt, source path, code, model speech or secret. Prompt/task_started -> thinking; Edit/Write/apply_patch -> editing; test commands -> testing; PermissionRequest/ask -> waiting; Stop/task_complete -> success pose with the truthful line "The agent turn ended."; failure/refusal -> error. Ten seconds per session/reaction, canonical vendor aliases, bounded native tails, explicit profile propagation and explicit SQLite connection closing. A 100 ms Qt reaction poll refreshes only on a state change; full idle polling retains its existing slower interval. Reduced motion holds a pose. Speech is one line, at most 140 characters, rejecting whole unsafe text and unsafe fallbacks before display. Host receipts outrank model prose in both the transport and the actual Qt report label.

Packaging explicitly admits only `nodelang/data/baboom/persona.json` through the existing release allowlist and adds that exact path to the hash-checked installed source manifest, preserving all user-data exclusions; executable PowerShell checks reject unrelated JSON and credential files. Native log caching compares both size and mtime because an open Windows rollout can append without updating mtime; event timestamps determine freshness. Failed Codex command-completion records project an error before the eventual turn-ended pose.

Scope boundary: commit-only candidate, no push, no live app/profile/screen changes, no deployment. Actual Claude Code and Codex CLI tasks ran in disposable profiles through the existing Ollama gemma4:cloud route, observed in the real offscreen Qt window with its shipped sprite atlas. Both showed thinking/editing/success within 224 ms of their Workshop events, with zero unsafe speech lines. Claude wrote its synthetic note. Codex's restricted sandbox denied its attempted note write: the companion truthfully showed error, then "The agent turn ended."; that pose does not claim the write succeeded. Separate native-event replays verify every required reaction and the actual failed-tool report label. These runs prove native clients, not Anthropic/OpenAI model authentication. The shared-site equality proof uses the exact deployed index in the prepared candidate service; the live older site has not been replaced. The phone app consumes this same persona/standard owner when its later surface is implemented. Full verification and exact revision belong in the revision-bound evidence and failure log.
