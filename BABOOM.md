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
  `read_universal_baboom_startup` (`nodelang/universal_application.py:26583-26663`)
  derives one asset root and one binding root from the owner's view session
  and `app:agent-body:baboom` (`_baboom_startup_roots`, `:26568-26580`;
  `_AGENT_BODY_BABOOM_ROOT`, `:1643`); the binding's expected members include
  the owner role on `app:agent-body:baboom` and the contract
  `app:contract:baboom-startup:v1` (`:825-830`, `:26612-26618`).
- Absent record: when neither the asset nor the binding cell exists, the
  reader returns `value` `"on"` with `source` `"default"`
  (`_BABOOM_STARTUP_DEFAULT = "on"`, `:828`; `:26600-26608`), so a graph that
  has never stored the setting starts BABOOM. The court
  `tests_replica/test_baboom_startup_setting.py:137`
  (`test_a_fresh_graph_reads_default_on_without_a_write_or_a_cell`) holds that.
- Malformed record: a partial binding (`:26609-26610`), a drifted binding or
  contract (`:26620-26634`), more than one WIP head (`:26644-26645`), a value
  other than `on`/`off` (`:26648-26653`) or an actor other than the owner
  (`:26654-26655`) raises `InvalidCell`. The launcher then does not start
  BABOOM and records "BABOOM did not start because its Settings value is
  unreadable; no action was performed." (`launch_archhub_test.py:1013-1022`),
  and the canvas projection reports `source` `"unreadable"` (`:26672-26685`).
  The court `test_baboom_startup_setting.py:385` holds that. This is where the
  code fails closed; an absent record does not.
- `off`: the launcher records "BABOOM is turned off in Settings; no action
  was performed." and returns before any key file, custody commit or attach
  attempt (`launch_archhub_test.py:1025-1028`). While no host is attached,
  a relay execute request is refused with that recorded reason
  (`_cockpit_execute`, `:1101-1108`); the `DELIVERY-STATUS.md` row "DONE landed 2026-09-16 17:33" states that relay
  reads are answered while off.
- Writing: `set_universal_baboom_startup` (`:26711` onward) accepts `on` or
  `off` only (`:26725-26726`), is owner-only ("BABOOM startup belongs to the
  instance owner", `:26731-26734`), takes effect at the next launch
  (`:26721`), refuses a stale base revision ("BABOOM startup changed; refresh
  before saving") and a no-op ("BABOOM startup is already on/off"), and
  appends a WIP revision outside canvas undo history (`:26721-26723`).
  Studio: Settings > BABOOM switch (`nodelang/studio/studio-lm.jsx`,
  `setBaboomStartup` and `configuration.baboom_startup`;
  `nodelang/studio/studio-existing-workshop.js:87-106`, kind `baboom-startup`);
  `nodelang/application_server.py:491` carries `baboom_startup` in the
  configuration delta. Courts tracked at `f61ac9b`:
  `tests_replica/test_baboom_startup_setting.py`,
  `test_baboom_startup_lifecycle.py`, `test_studio_baboom_startup.cjs`;
  `test_baboom_startup_qt.py` is untracked in the working tree.
- The session-only controls (hide, stop-new-requests, voice cancellation,
  stale-report suppression; `DELIVERY-STATUS.md` row "ACTIVE - BABOOM") and the tray action "Stop
  BABOOM for this launch" (`launch_archhub_test.py:912`) remain session-only
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
