# BABOOM: adopted agent, Phase A

Founder, verbatim: "بابوم تاعبين نفسكم في ليه ما تاخدوا أحسن ايجنت فري سورس واعملوله ريفيرس انجنيرينج وركبوه على الابليكيشن"

WHY: Goose already owns the model/tool turn loop, MCP extension lifecycle and ACP interface; adopt that engine instead of maintaining another one in BABOOM.
COMPARE: Goose, Hermes and Cline share context → model → tool → observation. Goose contributes an embeddable Rust engine, MCP and YAML recipes; Hermes contributes task-to-skill refinement and FTS5 recall; Cline contributes visible tool review and bounded permission. The engine is Goose; complementary ideas fit ArchHub's existing owners.
FIT: keep the ArchHub v3 face, native companion and graph. Agent/model/workflow settings remain visible node parameters. Host reads stay lazy and cross-program. Every proposed write remains an editable diff behind the ONE existing Approve card, followed by the existing receipt/readback/undo path. Only OpenRouter free routes or local Ollama are admitted.
DROPPED: Goose desktop UI, built-in shell/filesystem/browser/developer extensions, autonomous execution and schedules, paid model fallback, Hermes auto-execute, a second skill store, a second profile, and model-created permission.

## Verified prior art

| Source | License checked 2026-10-15 | Decision |
| --- | --- | --- |
| https://github.com/block/goose/blob/v1.54.0/LICENSE (repository now redirects to aaif-goose/goose) | Apache-2.0; Copyright 2024 Block, Inc. | ADAPT: packaged CLI in ACP server mode; MCP extensions, recipes, provider abstraction. No Goose UI. |
| https://github.com/NousResearch/hermes-agent/blob/main/LICENSE | MIT; Copyright (c) 2025 Nous Research; read through GitHub contents API | ADAPT ideas: automatic skill drafts/refinement after complex tasks; FTS5 session search. No Hermes process or auto-execute. |
| https://github.com/cline/cline/blob/main/LICENSE | Apache-2.0 | LEARN: explicit review at the tool boundary. Keep ArchHub's one approval card. |

Primary implementation references: Goose `crates/goose/src/acp/server.rs`, `crates/goose-cli/src/cli.rs`, `crates/goose/src/config/paths.rs` at v1.54.0; https://block.github.io/goose/ ; Hermes `tools/session_search_tool.py`, `website/docs/user-guide/features/skills.md`, `website/docs/reference/tools-reference.md`.

## Existing source discovery and ownership

Read AUTHORITY.md, SPEC.md, founder intent decoder, LANE-DISCIPLINE.md, BRIEF-GOOSE.md, founder mandates and failure log; searched the lane's nodelang, launcher, installer, tests and evidence bindings. Read the canonical main SHA, DELIVERY-STATUS and XRAY prior-art map (Hermes was previously marked unconfirmed). ../../AGENTS.md is absent in this temporary extraction; the supplied workspace contract controls.

Baseline: lane 5727a9b2e7825d3fac1e3b8333677c6218a80931 (`base main aa690eeb + brief`); canonical main aa690eeb9924d12410cab45382281dca147b16a0. No installed app/service/host is exercised or changed.

KEEP: `baboom_native_companion`, `baboom_native_host`, signed machine transport, `native_host_tools.hosts_state`, graph composer/action validation and shared approval. ADAPT: composer model boundary and launcher lifecycle. RETIRE: BABOOM tool specifications, provider turn closure, tool-capability guessing and BABOOM loop wrapper in `agent_composer.py`. The Workshop native tool loop has other callers and is outside this replacement.

## Hermes fit (Phase A design; not claimed implemented by the Phase B proof)

After a complex task, the existing skill owner `cell_brain_skills.py` should receive a proposed skill plus trace/evidence; success feeds `promote_skill`, failure feeds the existing `record_failure` reflexion owner, producing a refined WIP skill. Promotion is an approved graph change, never a silent file write. FTS5 is a disposable, identity-scoped index of authorised session messages; search returns source session/message references into the existing PROFILE node. The graph remains authority; index rebuild/deletion preserves source history. Neither feature grants host authority. Phase B closes the agent transport/read proof, not these later Grand Map requirements.

## Packaging and lifecycle

Pin Goose v1.54.0, Windows x86_64 CLI archive (not the desktop archive):
https://github.com/aaif-goose/goose/releases/download/v1.54.0/goose-x86_64-pc-windows-msvc.zip

Published GitHub asset digest (metadata read this turn):
`5c39bc91c3eadc231847e21a8a469e778431084437b233a63a950fee22db6239`.

Installer accepts that exact archive supplied by 717, verifies its SHA-256, packages the executable with a generated executable digest and full upstream license. Runtime verifies the executable digest before spawning `<app>/runtime/goose/goose.exe acp`. Launcher owns process start/stop; no PATH lookup, separate install, download-on-start, live provider court or fallback loop. Runtime config/data are scoped to the ArchHub instance. MCP is a private authenticated loopback extension exposing the existing `hosts_state` implementation; Phase B admits no host writes. Coordination is an extension mapping to the existing admitted native coordination server, not a new coordination engine; full write-capable coordination admission remains outside the first read proof.

Goose recipes map their instructions/extensions/parameters/subrecipes to existing workflow node inputs; no second workflow catalogue or hidden scheduler is introduced in this proof.

## Plan / exact initial owned files (Tier L, isolated proof)

1. This Step 0 and PROGRESS.md, committed before product edits.
2. `nodelang/goose_adapter.py`, `nodelang/goose_runtime.py`, `nodelang/agent_composer.py`, `nodelang/native_host_tools.py`, `nodelang/baboom_native_host.py`, `launch_archhub_test.py`: one ACP client, managed lifecycle, existing host MCP read, old BABOOM-loop deletion.
3. `installer/build_release.ps1`, `installer/ArchHub.iss`, `packaging/windows/goose-pin.json`, `NOTICE`, license files: offline pinned packaging, fail closed if missing/mismatched.
4. `tests_replica/test_goose_brain.py` and touched existing caller courts; `evidence/grandmap_bindings.json`: fake transport/process, actual MCP protocol with fake host, face result, write refusal, missing binary, timeout, paid-route refusal and cleanup. Run only touched courts via run-heavy. Independent review is evidence, not installed acceptance.
5. `GOOSE.patch`, `RESULT-GOOSE.md`: exact Removed symbols/paths, file:line, GM ids and scoped pass lines; SHA-256; final commit. No live install; 717 fetches the pinned archive with founder OK.

Approval points: none for lane source/fake tests. Binary fetch/install remains with 717 as explicitly instructed. Recovery: revert lane commits; no shared runtime or user data migration occurs.
