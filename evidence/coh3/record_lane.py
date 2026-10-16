"""Generate lane read proof and artifact register from disk, never status claims."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_proof():
    inputs = [
        ('BRIEF-COH3.md', 'Deliver the pinned-base patch, courts, generated export and six real screenshot tutorials; no deploy.'),
        ('LANE-DISCIPLINE.md', 'Keep the ledger, target courts serially, preserve baseline, retire duplicates, provide compliance evidence.'),
        ('READ-PROOF-REQUIRED.md', 'Add this mechanical record at the next commit and a requirement-by-requirement compliance table.'),
        ('../cohmain2/RESULT-COHMAIN2.md', 'Preserve the reviewed single generator and prior retirement, distinguish source export from installed/live acceptance.'),
        ('AUTHORITY.md', 'Founder intent and SPEC control; revision-bound court evidence cannot become a release claim.'),
        ('SPEC.md', 'Docs and website project one graph; no idle semantic writes or duplicate authority.'),
        ('AGENTS.md', 'Preserve public boundaries and follow authority/mandate/failure records.'),
        ('docs/FOUNDER_MANDATES.md', 'Use the current authority and canonical delivery ledger, not retired mandates.'),
        ('docs/FAILURE_LOG.md', 'Preserve incident history; do not claim recovery from test presence alone.'),
        ('evidence/coh3/original-gate-timeout.json', 'Use the captured original gate termination; separate the verified batch timeout from unproven test-deadlock attribution.'),
        ('nodelang/site_export.py', 'Extend the sole public generator, retain offer/download/privacy checks and seal all copied assets.'),
        ('nodelang/cell_website.py', 'Keep existing website revisions readable; generate new routes through the same graph.'),
        ('nodelang/application_server.py', 'Serve only the exact public tutorial capture, with existing HTTP response handling.'),
        ('nodelang/base_universal_catalogue.py', 'Do not duplicate node names, descriptions or parameter semantics.'),
        ('nodelang/library_engines.py', 'Use canonical child summaries/default parameters and declared unavailable engines.'),
        ('nodelang/universal_pipeline.py', 'Generate six tutorials from the same usage starter definitions and preserve Start/Edit semantics.'),
        ('nodelang/social_connections.py', 'Document provider names and explicit connection/blocker states, never assume a connected account.'),
        ('nodelang/universal_application.py', 'Project System tool names from application-owned catalogue nodes.'),
        ('nodelang/universal_cell.py', 'Preserve count semantics while removing repeated lazy historical journal scans from the test.'),
        ('public_site/README.md', 'Describe generated page and asset inventory and keep dist regenerable.'),
        ('package.json', 'Use existing single Studio build and dependency versions.'),
        ('STEP0-GOOSE.md', 'Preserve current-main Goose scope; package metadata is not live-process proof.'),
        ('packaging/windows/goose-pin.json', 'Project the selected pinned version; do not download or stage a runtime.'),
        ('nodelang/goose_adapter.py', 'Keep free OpenRouter/local Ollama and default generation limits; host-state reads only.'),
        ('nodelang/goose_runtime.py', 'Describe package/digest checks and missing-package refusal without spawning the runtime.'),
        ('nodelang/application.py', 'Keep legacy graph identity while removing the parallel website builder.'),
        ('nodelang/persistence.py', 'Preserve snapshot recovery and selected graph state.'),
        ('nodelang/migration.py', 'Preserve versioned old graph recovery and archive custody.'),
        ('nodelang/cell_ui.py', 'Do not broaden safe graph UI image/source permissions for a public screenshot.'),
        ('nodelang/clean_host_catalogue_source.py', 'Use selected operation descriptions and catalogue counts, not invented capabilities.'),
        ('nodelang/studio/studio-lm.jsx', 'Keep in-app Docs on the same server projection and real mounted component behavior.'),
        ('nodelang/studio/ds/index.jsx', 'Reuse current main shared controls; inspect native disabled behavior and tokens at this owner.'),
        ('packaging/compile_studio.cjs', 'Build the new main fifteen-input manifest with flattened DS output exactly once this round.'),
        ('tests/test_ds_port_assets.py', 'Check real DS asset bytes and traversal/archive refusal after the main advance.'),
        ('tests/test_ds_port_ratchet.py', 'Keep both new DS metric non-growth contracts; compare against the current main baseline.'),
        ('tests_replica/test_website_definition_revision.py', 'Prove contiguous revision history and no second-boot writes.'),
        ('tools/ratchet.py', 'Do not increase the inherited measured mess counts.'),
    ]
    for name in ('test_application_persistence', 'test_clean_server_visual_projection', 'test_done_needs_docs',
                 'test_node_native_application', 'test_node_native_website', 'test_the_launcher_starts_no_brain',
                 'test_website_docs_pages', 'test_website_live_findings', 'test_website_package_docs',
                 'test_website_public_routes', 'test_website_site_script', 'test_website_truth'):
        inputs.append(('tests_replica/' + name + '.py', 'Run the whole requested file; preserve behavior assertions and record the verbatim receipt.'))
    for name in ('docs_source.cjs', 'studio_design_screens.test.cjs', 'studio_docs_coherence.test.cjs',
                 'studio_foundations_tokens.test.cjs', 'studio_rail_shortcuts.test.cjs'):
        inputs.append(('tests_js/' + name, 'Run the affected mounted/coherence court after one Studio build, with temporary sibling dependencies.'))
    inputs.append(('tests/test_zero_idle_growth.py', 'Run both old-release graph scenarios; no idle growth and no waived cases.'))
    for path in ('C:/Users/fargaly/.claude/rules/intent-decoder.md',
                 'C:/Users/fargaly/.agents/skills/archhub-prior-art/SKILL.md',
                 'C:/Users/fargaly/.agents/skills/archhub-plan-first/SKILL.md',
                 'C:/Users/fargaly/.agents/skills/archhub-independent-verdict/SKILL.md',
                 'C:/Users/fargaly/.agents/skills/archhub-handoff-followup/SKILL.md',
                 'C:/Users/fargaly/.agents/skills/ship-discipline/SKILL.md',
                 'C:/Users/fargaly/.agents/skills/caveman/SKILL.md',
                 'C:/Users/fargaly/.agents/skills/founder-intent/SKILL.md',
                 'C:/Users/fargaly/.agents/skills/solution-only/SKILL.md'):
        inputs.append((path, 'Apply existing intent, prior-art, delivery, communication and independent review requirements.'))
    lines = ['# COH3 read proof', '', 'Captured from disk at ' + datetime.now(timezone.utc).isoformat() + '.',
             'Added at next commit after RULE 1e arrived during this active lane. Earlier source inputs were already read.', '']
    for name, requires in inputs:
        path = ROOT / name
        quotes = [line for line in path.read_text(encoding='utf-8-sig').splitlines() if line.strip()][:3]
        if name == 'evidence/coh3/original-gate-timeout.json':
            quotes = json.loads(path.read_text(encoding='utf-8-sig'))['events'][:3]
        lines += ['## ' + name, '', 'SHA-256: `' + sha(path) + '`', '']
        lines += ['> ' + line for line in quotes]
        lines += ['', 'What this requires: ' + requires, '']
    captures = {
        '03_rail_Home.png': ['No tasks in flight', 'Sheet register review', 'No completed results yet.'],
        '07_rail_Library.png': ['Nodes', 'Loading nodes...', 'No tasks in flight'],
        '43_SOC_connections.png': ['Connections', 'Studio', 'Cloud'],
        '39_SX_system_graph_open.png': ['ArchHub application', 'Sketch Lines', 'Settings'],
        '05_rail_Workshop.png': ['Workshop', 'New task', 'Not available yet'],
        '45_BB_baboom.png': ['BABOOM', 'PONG', 'Retry'],
        '23_Settings_Connections.png': ['Settings', 'Connections', 'Cloud'],
        '32_D3_workshop_open.png': ['Sketch Lines', 'Line Watcher', 'Revit Walls'],
        '38_GR_group.png': ['Group 2 nodes', 'Arrange selected', 'relation root is missing'],
    }
    for name, visible in captures.items():
        capture = ROOT / '../rig2/gate-he41d56asocial3-232226' / name
        lines += ['## ' + str(capture.relative_to(ROOT)), '', 'SHA-256: `' + sha(capture) + '`',
                  'Binary PNG. Three visually read strings:', *('> ' + value for value in visible),
                  '', 'What this requires: preserve the observed state; do not turn an empty/loading/refused view into execution proof. '
                  + ('This Home capture alone is copied unchanged into all six tutorial exports.' if name == '03_rail_Home.png' else 'Reviewed for context only; not copied into the export.'), '']
    (ROOT / 'READ-PROOF.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def register():
    paths = [ROOT / name for name in ('PROGRESS.md', 'plan.md', 'tasks.json', 'notes.md', 'READ-PROOF.md',
                                      'RESULT-COH3.md', 'COH3.patch', 'COH3.patch.sha256',
                                      'COH3-current-main.patch', 'COH3-current-main.patch.sha256')]
    paths += sorted((ROOT / 'evidence/coh3').glob('*'))
    lines = ['# COH3 artifact register', '', 'Generated from disk by evidence/coh3/record_lane.py.', '',
             '| No | Title | Rev | State | Date UTC | File | SHA-256 |',
             '| --- | --- | --- | --- | --- | --- | --- |']
    for number, path in enumerate((path for path in paths if path.is_file()), 1):
        date = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
        lines.append('| %d | %s | %s | WIP source handoff | %s | %s | `%s` |' % (
            number, path.stem, sha(path)[:12], date, path.relative_to(ROOT).as_posix(), sha(path)))
    (ROOT / 'REGISTER.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')


if __name__ == '__main__':
    import sys
    if '--read-proof' in sys.argv:
        read_proof()
    register()
