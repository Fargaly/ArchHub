# FAILURE_LOG

Append-only record of "shipped-but-invisible" claims, gaps the founder
caught, and how they were resolved. Established 2026-05-25 per
ROLLBACK-PROTOCOL mandate. Read at the start of every `/loop`
iteration so the same gap class doesn't recur.

**Format** (block-per-entry, per AgDR-0047 §A9 reformat 2026-05-26):

```
### YYYY-MM-DD · short slug
- **status**: open | closed
- **claim**: what was reported "shipped"
- **gap**: what the founder caught (or what the audit caught)
- **resolution**: what closes (or will close) the gap; link AgDR/sprint
```

Status legend:
- **open** = gap not yet closed, blocked by named AgDR / sprint / signoff
- **closed** = verified resolved, with the artifact named in `resolution`

---

### 2026-05-25 · graphhealth-badge-home-invisible
- **status**: open
- **claim**: "D2·A 1/3 GraphHealthBadge shipped" (commit `d772712`)
- **gap**: Visible in canvas but only in session view, not Home. Founder said "where are the nodes... none appeared in my app".
- **resolution**: AgDR-0043 workshop · Sprint 0+1 mandates user-visible default-view check.

### 2026-05-25 · brokenwire-dialog-buttons-disabled
- **status**: closed
- **claim**: "D2·A 2/3 BrokenWireDialog shipped" (commit `58fb6c0`)
- **gap**: Modal renders but "Insert adapter" + "Swap downstream" buttons STILL disabled at `studio-lm.jsx:6280` — D2·A 3/3 wired but dialog buttons never re-enabled.
- **resolution**: CLOSED 2026-05-25 — buttons re-enabled + wired via commit `5b8c7a2` (per `docs/status/2026-05-26.md` row 2). Synced open→closed 2026-05-30 in governance reconciliation (FAILURE_LOG had drifted behind the status doc).

### 2026-05-25 · agdr-0041-status-flip-without-ui-surface
- **status**: open
- **claim**: "AgDR-0041 status: executing → executed" (commit `a27196e` + others)
- **gap**: All 6 properties' BACKEND shipped but BrokenWireDialog adapter buttons disabled + 0 UI consumers exist for swap/freeze/bypass beyond the right-click context menu (low discoverability).
- **resolution**: Workshop · Sprint 0 mandates UI-surface check before status flip.

### 2026-05-25 · agdr-0042-zero-jsx-consumer
- **status**: closed
- **claim**: "D1·C 6/6 AgDR-0042 status: executing → executed" (commit `a5d868b`)
- **gap**: All 6 slices' BACKEND shipped (memory graph + 4 extractors + BFS query + community + sync) but ZERO JSX consumer. Founder cannot see his 197 nodes / 76 capabilities / 176 communities anywhere in the app.
- **resolution**: CLOSED 2026-05-25 — Memory Explorer modal shipped (commit `bbd3e87`) + memory pill + library hits surface the graph (per `docs/status/2026-05-26.md` row 4; BrainViewModal confirmed live in `REPO-MAP-2026-05-28` §2). Synced open→closed 2026-05-30 in governance reconciliation.

### 2026-05-25 · agdr-0024-hostnodev2-localstorage-gated-off
- **status**: closed
- **claim**: "AgDR-0024 Host Node v2 shipped" + AgDR `status: executed`
- **gap**: Built but localStorage-gated OFF by default. No Settings UI toggle. Founder must open DevTools to enable. S2/S3 sub-slices explicitly missing per code comment.
- **resolution**: CLOSED 2026-05-25 — default flipped ON (commit `51797b7`) + Settings panel toggle shipped (commit `1c5376f`) (per `docs/status/2026-05-26.md` row 5). Synced open→closed 2026-05-30 in governance reconciliation.

### 2026-05-26 · brainsection-cache-prototype-perf-triple-failure
- **status**: partially-closed
- **claim**: "BrainSection JSX panel merged + structurally verified · CDP pixel-proof pending"
- **gap**: Founder opened Settings → saw NOTHING for brain · panel looks "shitty unlike the design" · "lags too much." Three failures stacked: (1) JSX cache served pre-edit transpiled bundle in localStorage = BrainSection never reached DOM; (2) violated PROTOTYPE-IS-CONTRACT — inserted simple Row stack inside legacy Settings modal instead of mirroring the signed sidebar+cards prototype 1:1; (3) 4s polling interval + missing memoization caused observable lag.
- **resolution**: 2026-05-26 — VISIBILITY shipped via a different surface: native PyQt tab `BrainTab` in `app/settings_dialog.py` (5th tab of Settings dialog) replaces the JSX route approach. The native tab bypasses the JSX cache entirely (failure F1 dissolved), runs as a Qt widget without React polling cascade (F3 dissolved), and adopts native Qt design language instead of mirroring the HTML prototype (F2 explicitly rejected — see AgDR-0046 superseded-by). Live runtime verified via mss screenshots `proofs/2026-05-26/brain_tab_final_084027.png` + `proofs/2026-05-26/now_mon1_084935.png`. Founder eye-check 2026-05-26: *"great although the design is a total shit... but for now it will do."* Design-debt (polish to a non-shit Qt aesthetic) tracked in this wave's agent-2/agent-3 design pass — not a new AgDR per NO-NEW-AGDR-UNTIL-LAST-ONE-LIVES. AgDR-0046 status flipped to `superseded-by-shipped-native`.

### 2026-05-25 · agdr-0021-aiplan-zero-jsx-references
- **status**: closed
- **claim**: "AgDR-0021 ai.plan canvas node shipped" + AgDR `status: executed`
- **gap**: Engine registered, writes to disk. ZERO JSX references to `ai.plan` / `AiPlan` / plan history. Renders as generic palette tile. No replay button. No history viewer.
- **resolution**: CLOSED 2026-05-25 — Inspector tab (commit `9030eb0`) + plan History modal (commit `495fc4c`) surface the plan node + replay (per `docs/status/2026-05-26.md` row 7). Synced open→closed 2026-05-30 in governance reconciliation.

### 2026-05-25 · agdr-0022-reactflow-lock-contradiction
- **status**: closed
- **claim**: "AgDR-0022 ReactFlow scaffold" + ARCHITECTURE LOCK "ReactFlow is the canvas substrate"
- **gap**: ReactFlow NEVER installed. `NodeCanvasRF_Stub` is a placeholder that says "REACTFLOW CANVAS — PREVIEW · Migration ships across P2.a → P2.d". Direct contradiction of the locked architecture.
- **resolution**: RESOLVED 2026-05-25 — AgDR-0048 (renumber chain 0045→0046→0048) supersedes AgDR-0012's ReactFlow lock + AgDR-0022 in full. Custom canvas is the substrate of record. Stub kept only for `test_reactflow_p2a_groundwork.py`; per AgDR-0048 §Artifacts the removal lands after F4 signoff (AgDR-0047 §C3).

### 2026-05-26 · prototype-a-duplicated-assimilation-deepdive
- **status**: closed
- **claim**: "Prototype A · Visual/Render/Sketch unified library category" (`docs/prototypes/visual-render-sketch-library-2026-05-26.html`, 225 lines, 18 nodes proposed as NEW)
- **gap**: Founder caught immediately — *"WTF are you doing with visualization? we also already tackled those before · I clearly remember we tackled them in this assimilation-deepdive-2026-05-24 why are you producing lots of new things when we already tackled those before?"* The canonical 1590-line `assimilation-deepdive-2026-05-24.html` already mapped 50+ visual/render/sketch/vision/mesh/texture/animation nodes across ComfyUI + Alibaba + NEW sources. Compounding error: that canonical file had been moved to `_iterations/` earlier this loop session (tick 3 §A4) based on a shallow grep that only checked code refs, not the founder's mental model of authority.
- **resolution**: 2026-05-26 — (1) `git mv` restored `assimilation-deepdive-2026-05-24.html` back to active `docs/prototypes/`; (2) Prototype A given WITHDRAWN banner citing the duplication + linking to canonical; (3) Prototype B trimmed to founder-approved scope (Surfaces 3+4 kept, 1/2/5 withdrawn); (4) Prototype B Surface 6 added per founder ask "figure out how this connects with the brain system" (6 wiring points W1-W6 + slice plan S7.W1..W6); (5) SIGNOFF table converted to real HTML checkboxes (founder caught "isn't selectable"). Class-of-failure: before proposing ANY new prototype in the visual/library/node-grammar space, grep `docs/prototypes/*assimilation*` + `docs/prototypes/signed/*` for prior signed work AND read the founder's recent conversation history for what they remember signing off. Don't trust shallow ref-count grep when the founder remembers the file.

### 2026-05-25 · composer-relocation-shipped-without-approval
- **status**: closed
- **claim**: "ship(archhub-redesign A): composer-first home" (commit `34ad75a`) + "fix(home): explicit CSS order" (`0aa8c32`)
- **gap**: Composer moved from familiar bottom-fixed to top-of-page without founder approval. Founder: "do things deeply... won't fix something and fuck everything else up... why did you change the composer place?" Shipped Prototype A blindly without confirming the move was wanted; the followup order-fix patched a symptom of the same uncoordinated change.
- **resolution**: Reverted both commits (`537fab8` + `972962d`). Composer back to `position:fixed bottom:80`. Don't ship layout moves from a prototype again without explicit per-section confirmation.

### 2026-06-02 · session-save-falsely-fixed-synthetic-verification
- **status**: closed
- **claim**: "fix(sessions): graph-only sessions save + load back (was saved-but-empty)" (commit `85bbe15`) — reported verified live.
- **gap**: Founder still hit it — *"I DON'T GET WHY THE SESSION WASN'T SAVED AND WHENEVER I OPEN IT IT'S NOT CONNECTED AS IF THE NODES AREN'T WORKING?"* The bug had THREE stacked causes: (1) `_payload_is_empty` ignored graph nodes → save refused; (2) slug mismatch (hyphen session-id vs underscore `_slugify`) → save wrote a different file than load read; (3) `openSession` resets `LM_GRAPH` on navigation WITHOUT flushing the pending 250ms debounced save → the save fires against the empty graph and persists `nodes:[]`. 85bbe15 fixed (1)+(2). I had EARLIER written the fix for (3) (the `openSession` flush) then REVERTED it once I concluded (1)+(2) were the whole story. Worse: my "verified live" was SYNTHETIC — I drove `save_graph` directly and manually called `__archhub_flushGraphSave`, which bypassed the navigation race. The real gesture (spawn → switch session → reopen) still lost everything.
- **resolution**: 2026-06-02 — reproduced the REAL gesture via CDP (real `lm-composer-action` spawn + `lm-action-open-session` navigation, NO manual flush): spawn 2 nodes → navigate within debounce → reopen showed **0 nodes / 0 wires** (bug reproduced on the running app). Re-added the `openSession` flush (flush pending save to the current sid BEFORE the `LM_GRAPH` reset + id reassignment). Re-ran the SAME real-gesture repro → reopen shows **2 nodes / 1 wire preserved**. Regression harness committed: `tools/cdp_session_race.cjs`. **CLASS-OF-FAILURE: "verified live" must drive the ACTUAL user gesture (UI events → real handlers), never a synthetic bridge call that bypasses the real timing/navigation path. A synthetic round-trip proves the MECHANISM, not the FEATURE. Added to the verification bar.**
