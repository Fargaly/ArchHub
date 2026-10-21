"""Done needs docs: published base definitions reach the real Docs renderer.

No installed app, network, private graph or persisted documentation copy is used.
The negative cases deliberately damage the generated output, not the catalogue.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import subprocess

import pytest

from nodelang.base_universal_catalogue import BASE_CATALOGUE, install_base_universal_catalogue
from nodelang.clean_visual_projection import _catalog_projection
from nodelang.site_export import project_documentation
from nodelang.unified_application_lens import project_unified_scope, scope_lens_payload
from tests_replica.test_unified_authority import _authority, _Caller, composition_root

ROOT = Path(__file__).resolve().parents[2]

# Load the production library adapter, projection and JSX renderer. Only host
# observations and presentation tokens are fakes; catalogue facts come from the
# signed, published definitions installed below.
RENDER = r"""
const fs = require('node:fs'), vm = require('node:vm');
(async () => {
  const input = JSON.parse(fs.readFileSync(0, 'utf8'));
  const {JSDOM} = await import('jsdom');
  const dom = new JSDOM('<div id="root"></div>', {runScripts:'outside-only'});
  const win = dom.window;
  win.eval(fs.readFileSync('01.APP/nodelang/studio/studio-authority.js', 'utf8'));
  const api = win.ArchHubStudioAuthority.create({get:async () => input,
    post:async () => { throw Error('Docs must not write'); }});
  await api.load();
  win.eval(fs.readFileSync('01.APP/nodelang/studio/vendor/react.js', 'utf8'));
  win.eval(fs.readFileSync('01.APP/nodelang/studio/vendor/react-dom.js', 'utf8'));
  const compiler = vm.createContext({});
  vm.runInContext(fs.readFileSync('01.APP/nodelang/studio/vendor/babel.js','utf8'), compiler);
  const source = fs.readFileSync('01.APP/nodelang/studio/studio-lm.jsx', 'utf8');
  const helpers = source.slice(source.indexOf('const docsNodeGroups ='), source.indexOf('const DOC_KIND ='));
  win.library = api.getSnapshot().library;
  win.documentation = input.documentation;
  const prelude = `const LM = {accent:'#888888',onFill:'#ffffff',bgDeep:'#111111',ink:'#ffffff',inkSoft:'#aaaaaa',line:'#333333',sans:'Inter',sp:{xs:4,sm:8,md:12,lg:16},rad:{control:4,sm:2},fs:{label:{sz:11,ln:14,wt:500},caption:{sz:12,ln:16}},icon:{category:{box:20,size:12}}};
    const studioCategory = name => ({col:LM.accent,icon:'○',label:name});
    const hostTally = () => ({read:true}); const hostStateWord = () => 'Connected';
    const plural = (n, word) => n+' '+word+(n===1?'':'s');`;
  win.eval(compiler.Babel.transform(prelude + helpers + `
    window.projection = buildDocsProjection({documentation:window.documentation,hosts:[]});
    const root = ReactDOM.createRoot(document.getElementById('root'));
    ReactDOM.flushSync(() => root.render(<DNodeGroups groups={window.projection.nodeGroups}/>));
  `, {presets:['react']}).code);
  const rows = [...win.document.querySelectorAll('[data-docs-node-category]')].flatMap(group =>
    [...group.querySelectorAll('[data-docs-node-tile]')].map(tile => ({
      id:tile.getAttribute('data-docs-node-id'), cat:group.getAttribute('data-docs-node-category'),
      title:tile.querySelector('[data-docs-node-title]')?.textContent,
      detail:tile.querySelector('[data-docs-node-detail]')?.textContent,
    })));
  process.stdout.write(JSON.stringify({rows,index:win.projection.index}));
  dom.window.close();
})().catch(error => { console.error(error); process.exitCode=1; });
"""


@pytest.fixture(scope="module")
def documented_catalogue():
    authority = _authority()
    caller = _Caller(authority)
    try:
        roots = install_base_universal_catalogue(authority, caller=caller)
        lens = scope_lens_payload(project_unified_scope(
            authority, composition_root(authority, "Projects"), caller=caller,
        ))
        catalogue = _catalog_projection([
            {**item, "id": item["root_id"], "kind": "assembly"}
            for item in lens["catalogue"]
        ], {"owner":"test-owner", "title":"Place", "icon":"play",
            "activation":{"binding":"test-binding", "capability":"test-capability"}})
        before = authority.store.revision
        rendered = subprocess.run(
            ["node", "-e", RENDER], cwd=ROOT,
            input=json.dumps({"graph_id":authority.manifest.application_root,
                "root":lens["scope_root"], "revision":lens["revision"],
                "nodes":[], "wires":[], "catalog":catalogue,
                "documentation":project_documentation(catalogue=catalogue)}),
            text=True, encoding="utf-8", capture_output=True, timeout=90,
        )
        assert rendered.returncode == 0, rendered.stderr
        assert authority.store.revision == before, "reading docs changed the graph"
        expected = [{"id":roots[entry["name"]], "cat":entry["category"],
            "title":entry["name"], "detail":entry["description"]}
            for entry in BASE_CATALOGUE]
        yield expected, json.loads(rendered.stdout)
    finally:
        authority.store.close()


def _assert_documented(expected, rows):
    assert len(rows) == len(expected), "a catalogue doc is missing or duplicated"
    assert {row["id"] for row in rows} == {row["id"] for row in expected}, "doc identities drifted"
    assert sorted(rows, key=lambda row:row["id"]) == sorted(expected, key=lambda row:row["id"]), "a generated doc was hand-edited"


def test_every_published_base_node_has_an_unedited_generated_doc(documented_catalogue):
    expected, rendered = documented_catalogue
    _assert_documented(expected, rendered["rows"])
    topics = [row for row in rendered["index"] if row["s"] == "canvas" and row["k"] == "topic"]
    assert {(row["t"], row["d"]) for row in topics} >= {(row["title"],row["cat"]) for row in expected}


@pytest.mark.parametrize("damage", ["missing", "duplicate", "title", "detail", "cat", "id"])
def test_done_needs_docs_rejects_missing_or_hand_edited_entries(documented_catalogue, damage):
    expected, rendered = documented_catalogue
    rows = deepcopy(rendered["rows"])
    _assert_documented(expected, rows)
    if damage == "missing":
        rows.pop()
    elif damage == "duplicate":
        rows.append(deepcopy(rows[0]))
    else:
        rows[0][damage] = "hand-edited"
    with pytest.raises(AssertionError):
        _assert_documented(expected, rows)


def test_public_tutorial_docs_cover_the_same_base_catalogue():
    body = next(page["text"] for page in project_documentation()["tutorials"]
        if page["id"] == "composer-canvas")
    for entry in BASE_CATALOGUE:
        assert "### " + entry["category"] in body
        assert "`%s` - %s" % (entry["name"], entry["description"]) in body


def test_existing_workshop_canvas_projects_shared_tutorials_without_persisting_them():
    from nodelang.application_server import ApplicationServer
    from nodelang import commit_intent
    from nodelang.map_import import PUBLIC_MAP_PATH
    from nodelang.universal_application import build_universal_application
    from nodelang.site_export import project_documentation

    store, registry = build_universal_application(PUBLIC_MAP_PATH)
    server = ApplicationServer(universal_store=store, universal_registry=registry,
        enable_machine_transport=False).start()
    try:
        binding = server._resolve_browser_session(server.browser_session_token)

        def read():
            with commit_intent.declare(commit_intent.USER_ACTION,
                    actor=binding.subject_root, reason="open documentation court canvas"):
                return server.project_interaction_canvas(binding)

        first = read()  # Existing interaction bindings may be published once.
        assert first["documentation"] == project_documentation(catalogue=first["catalog"])
        before = server.universal_store.revision
        first["documentation"]["tutorials"][0]["text"] = "hand-edited tutorial"
        assert read()["documentation"] == project_documentation(catalogue=first["catalog"])
        assert server.universal_store.revision == before
    finally:
        server.close()
