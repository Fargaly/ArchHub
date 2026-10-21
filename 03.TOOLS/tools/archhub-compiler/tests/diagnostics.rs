use archhub_compiler::{analyze, language_name, Report};

fn report(path: &str, source: &str) -> Report {
    let (source, runtime) = source
        .split_once("\n---runtime---\n")
        .unwrap_or((source, ""));
    let mut files = vec![(path.into(), source.into())];
    if !runtime.is_empty() {
        files.push(("runtime.py".into(), runtime.into()));
    }
    analyze(&files)
}
fn has(r: &Report, code: &str) -> bool {
    r.diagnostics.iter().any(|d| d.code == code)
}
fn court(code: &str, path: &str, bad: &str, fixed: &str) {
    let red = report(path, bad);
    assert!(
        has(&red, code),
        "{code} did not fire: {:?}",
        red.diagnostics
    );
    let green = report(path, fixed);
    assert!(
        !has(&green, code),
        "{code} survived repair: {:?}",
        green.diagnostics
    );
    assert!(
        !has(&red, "E0011"),
        "RED fixture is malformed rather than invalid product state"
    );
    assert!(
        green.diagnostics.is_empty(),
        "fixed fixture must have zero diagnostics: {:?}",
        green.diagnostics
    );
}

#[test]
fn e0001_duplicate_route() {
    court(
        "E0001",
        "routes.py",
        "ROUTES = [('GET','/same'),('GET','/same')]\nvisit('/same')\n",
        "ROUTES = [('GET','/same')]\nvisit('/same')\n",
    );
}

#[test]
fn test_and_fixture_sources_never_define_product_objects_or_readers() {
    for path in [
        "tests/test_routes.py",
        "cloud_backend/tests/probe.py",
        "tests_replica/test_routes.py",
        "fixtures/routes.py",
        "ui/routes.test.js",
        "ui/__fixtures__/routes.json",
    ] {
        let fake = if path.ends_with(".json") {
            r#"{"routes":[{"method":"GET","path":"/real"}]}"#
        } else if path.ends_with(".js") {
            "app.get('/real', handler);"
        } else {
            "ROUTES = [('GET','/real')]\nclient.get('/real')\n"
        };
        let r = analyze(&[
            ("routes.py".into(), "ROUTES = [('GET','/real')]\n".into()),
            (path.into(), fake.into()),
        ]);
        assert!(!has(&r, "E0001"), "{path}: {:?}", r.diagnostics);
        assert!(
            r.diagnostics
                .iter()
                .any(|d| d.code == "E0002" && d.file == "routes.py"),
            "test request counted as runtime caller: {path}"
        );
        assert!(
            r.files.iter().any(|f| f.file == path),
            "test source lost syntax coverage"
        );
    }
    assert!(has(&report("tests/test_broken.py", "def (:"), "E0011"));
}

#[test]
fn http_requests_are_uses_and_decorators_are_definitions() {
    let r = report("api.py", "@app.get('/real')\ndef read():\n    return 1\nclient.get('/real')\nrequests.post('/remote')\n");
    assert!(r.diagnostics.is_empty(), "{:?}", r.diagnostics);
    let r = report("api.py", "@app.get('/real')\ndef one():\n    return 1\n@app.get('/real')\ndef two():\n    return 2\nclient.get('/real')\n");
    assert!(has(&r, "E0001"));
}

#[test]
fn independent_host_servers_have_distinct_ownership_domains() {
    let source =
        "class Handler(BaseHTTPRequestHandler):\n    pass\nserver = HTTPServer(address, Handler)\n";
    let r = analyze(&[
        ("bridges/blender/server.py".into(), source.into()),
        ("bridges/rhino/server.py".into(), source.into()),
        ("nodelang/server.py".into(), source.into()),
    ]);
    assert!(!has(&r, "E0001"), "{:?}", r.diagnostics);
    let r = analyze(&[
        ("bridges/blender/one.py".into(), source.into()),
        ("bridges/blender/two.py".into(), source.into()),
    ]);
    assert!(has(&r, "E0001"), "same-host duplicate escaped");
}

#[test]
fn retirement_records_do_not_retire_http_method_tokens() {
    let r = report(
        "routes.py",
        "RETIRED = [('POST', '/old')]\nROUTES = [('POST','/new')]\nvisit('/new')\n",
    );
    assert!(r.diagnostics.is_empty(), "{:?}", r.diagnostics);
    let r = report("routes.py", "RETIRED = [('POST', '/old')]\nvisit('/old')\n");
    assert!(has(&r, "E0006"));
}

#[test]
fn router_prefixes_are_part_of_route_identity() {
    let r = report("api.py", "app = FastAPI()\nrouter = APIRouter(prefix='/founder')\n@app.get('/')\ndef root():\n    return 1\n@router.get('/')\ndef founder():\n    return 2\nvisit('/')\nvisit('/founder/')\n");
    assert!(r.diagnostics.is_empty(), "{:?}", r.diagnostics);
}

#[test]
fn compatibility_registry_is_not_a_second_owner_of_the_live_registry() {
    let r = report("library.py", "LIBRARY_ITEM_ENGINES = {'a':{'engine':'run','params':{}}}\nLEGACY_LIBRARY_ITEM_ENGINES = {'a':{'engine':'run','params':{}}}\n");
    assert!(!has(&r, "E0001"), "{:?}", r.diagnostics);
}

#[test]
fn host_api_identifiers_in_opaque_strings_are_not_placeholder_sentinels() {
    let r = report(
        "nodelang/desktop.py",
        "source = 'if (vs.IsPlaceholder) continue;'\n",
    );
    assert!(!has(&r, "E0003"), "{:?}", r.diagnostics);
    assert!(has(
        &report("nodelang/desktop.py", "text = 'placeholder content'\n"),
        "E0003"
    ));
}

#[test]
fn finite_helper_reader_keys_are_resolved_in_registered_engine() {
    let r = report("library.py", "LIBRARY_ITEM_ENGINES = {'a':{'engine':'move','params':{'dx':0,'dy':0}}}\nENGINE_SOCKETS = {'move':{'target':('dx','dy')}}\ndef move(params):\n    return tuple(_number(params, name, 0) for name in ('dx','dy'))\nENGINES = {'move':move}\n");
    assert!(r.diagnostics.is_empty(), "{:?}", r.diagnostics);
}

#[test]
fn active_registries_still_share_the_product_node_identity() {
    let r = report("library.py", "LIBRARY_ITEM_ENGINES = {'a':{'engine':'run','params':{}}}\nCATALOGUE = {'a':{'engine':'other','params':{}}}\n");
    assert!(
        has(&r, "E0001"),
        "conflicting active node definitions escaped"
    );
}

#[test]
fn actual_prefixed_retirement_route_registry_still_refuses_a_live_reference() {
    let r = report(
        "api.py",
        "_RETIRED_APPLICATION_HTTP_ROUTE_KEYS = frozenset({'POST /old'})\nvisit('/old')\n",
    );
    assert!(
        has(&r, "E0006"),
        "actual product retirement convention lost"
    );
    let r = report("api.py", "_SHARE_PATH_RETIRED = {'error':'retired','use':'publish in the app'}\nmessage = 'retired'\n");
    assert!(
        !has(&r, "E0006"),
        "error payload mistaken for a path registry"
    );
}

#[test]
fn same_host_same_literal_listener_cannot_hide_behind_different_class_names() {
    let r = report("bridges/revit/server.py", "class One:\n    def start(self):\n        return HTTPServer(('127.0.0.1', 8475), Handler)\nclass Two:\n    def start(self):\n        return HTTPServer(('127.0.0.1', 8475), Handler)\n");
    assert!(
        has(&r, "E0001"),
        "same host/listener duplicated behind separate classes"
    );
}

#[test]
fn same_host_listener_constant_resolves_across_class_scopes() {
    let r = report("bridges/revit/server.py", "ADDR = ('127.0.0.1', 8475)\nclass One:\n    def start(self):\n        return HTTPServer(ADDR, Handler)\nclass Two:\n    def start(self):\n        return HTTPServer(ADDR, Handler)\n");
    assert!(has(&r, "E0001"));
}

#[test]
fn chained_listener_constant_binding_keeps_same_host_duplicate_detection() {
    let r = report("bridges/revit/server.py", "OTHER = ADDR = ('127.0.0.1', 8475)\nclass One:\n    def start(self):\n        return HTTPServer(ADDR, Handler)\nclass Two:\n    def start(self):\n        return HTTPServer(ADDR, Handler)\n");
    assert!(has(&r, "E0001"));
}

#[test]
fn local_router_prefix_does_not_overwrite_module_router_prefix() {
    let r = report("api.py", "router = APIRouter(prefix='/a')\n@router.get('/x')\ndef first():\n    return 1\n@router.get('/x')\ndef second():\n    return 2\nvisit('/a/x')\ndef isolated():\n    router = APIRouter(prefix='/b')\n    @router.get('/x')\n    def local():\n        return 3\n    visit('/b/x')\n");
    let duplicate = r
        .diagnostics
        .iter()
        .filter(|d| d.code == "E0001")
        .collect::<Vec<_>>();
    assert_eq!(duplicate.len(), 2, "{:?}", r.diagnostics);
    assert!(duplicate.iter().all(|d| d.message.contains("/a/x")));
}

#[test]
fn express_router_alias_remains_a_defining_owner() {
    let r = report(
        "api.js",
        "const api = express.Router();\napi.get('/x', read);\napi.get('/x', read);\n",
    );
    assert!(has(&r, "E0001"), "aliased router registration escaped");
}

#[test]
fn declared_non_code_assets_have_coverage_without_an_invented_grammar() {
    let r = analyze(&[
        ("NOTICE".into(), "License text".into()),
        (".gitignore".into(), "target/\n".into()),
    ]);
    assert!(r.diagnostics.is_empty());
    assert_eq!(r.files.len(), 2);
}
#[test]
fn e0002_unused_param() {
    court("E0002","model.json",r#"{"nodes":[{"id":"n","params":{"x":1},"sockets":{"x":"number"}}]}"#,
        "{\"nodes\":[{\"id\":\"n\",\"params\":{\"x\":1},\"sockets\":{\"x\":\"number\"}}]}\n---runtime---\ndef execute(params):\n    return params.get('x')\nENGINES = {'n':execute}\n");
}
#[test]
fn e0003_exhaustive_states() {
    court("E0003","screen.jsx",
        "const Screen = () => {useEffect(() => fetch('/items')); return <div>ready</div>;};",
        "const retry = () => reload(); const ACTIONS = {retry:retry}; const Screen = () => {useEffect(() => fetch('/items')); if(state.status === 'error') return <button actionId='retry' onClick={() => retry()}>Retry</button>; if(state.status === 'waiting') return <div>wait</div>; if(state.status === 'empty') return <div>empty</div>; if(state.status === 'loaded') return <div>ready</div>;};");
}
#[test]
fn e0004_silent_failure() {
    court(
        "E0004",
        "action.py",
        "try:\n    save()\nexcept Exception:\n    pass\n",
        "try:\n    save()\nexcept Exception as failed:\n    raise ActionError(str(failed))\n",
    );
}
#[test]
fn e0005_button_binding() {
    court(
        "E0005",
        "screen.jsx",
        "const save = () => send(); const ACTIONS = {save: save}; const View = () => <button actionId='absent' onClick={() => save()}>Save</button>;",
        "const save = () => send(); const ACTIONS = {save: save}; const View = () => <button actionId='save' onClick={() => save()}>Save</button>;",
    );
}
#[test]
fn e0006_replaced_path() {
    court(
        "E0006",
        "old.py",
        "RETIRED = ['/old']\nvisit('/old')\n",
        "RETIRED = ['/old']\nvisit('/new')\n",
    );
}
#[test]
fn e0007_behaviour_constant() {
    court(
        "E0007",
        "policy.py",
        "KEEP_DAYS = 3\nprune(KEEP_DAYS)\n",
        "KEEP_DAYS = params.get('keep_days')\nprune(KEEP_DAYS)\n",
    );
}
#[test]
fn e0008_missing_socket() {
    court("E0008","model.json",r#"{"nodes":[{"id":"n","params":{"x":1},"reads":["x"]}]}"#,
        "{\"nodes\":[{\"id\":\"n\",\"params\":{\"x\":1},\"sockets\":{\"x\":\"number\"}}]}\n---runtime---\ndef execute(params):\n    return params.get('x')\nENGINES = {'n':execute}\n");
}
#[test]
fn e0009_wire_type() {
    court(
        "E0009",
        "model.json",
        r#"{"nodes":[{"id":"a","sockets":{"out":{"side":"source","type":"number"}}},{"id":"b","sockets":{"in":"string"}}],"wires":[{"from":["a","out"],"to":["b","in"]}]}"#,
        r#"{"nodes":[{"id":"a","sockets":{"out":{"side":"source","type":"number"}}},{"id":"b","sockets":{"in":"number"}}],"wires":[{"from":["a","out"],"to":["b","in"]}]}"#,
    );
}
#[test]
fn e0010_unknown_never_passes() {
    assert!(has(&report("feature.exotic", "anything"), "E0010"));
    assert!(has(&report("feature.ms", "print 1"), "E0010"));
}
#[test]
fn e0011_parse_errors_never_pass() {
    assert!(has(&report("broken.py", "def (:"), "E0011"));
}
#[test]
fn comments_are_not_runtime_readers_or_failures() {
    let r = report(
        "view.jsx",
        "// coming soon; error loading data empty\nconst n = 'fine';",
    );
    assert!(r.diagnostics.is_empty());
}
#[test]
fn duplicate_attributed_to_each_owner() {
    let r = analyze(&[
        (
            "old.py".into(),
            "ROUTES = [('GET','/x')]\nvisit('/x')".into(),
        ),
        (
            "new.py".into(),
            "ROUTES = [('GET','/x')]\nvisit('/x')".into(),
        ),
    ]);
    for file in ["old.py", "new.py"] {
        assert!(r
            .diagnostics
            .iter()
            .any(|d| d.code == "E0001" && d.file == file));
    }
}
#[test]
fn extracts_real_catalogue_helpers() {
    let r=report("catalogue.py","BASE_CATALOGUE: tuple = ({'name':'n','parameters':{'x':_text('')},'interfaces':{'x':_in('string')},'engine':'test'},)\ndef execute(params):\n    return params.get('x')\nENGINES = {'test':execute}\n");
    assert!(r.diagnostics.is_empty(), "{:?}", r.diagnostics);
    let missing=report("catalogue.py","BASE_CATALOGUE: tuple = ({'name':'n','parameters':{'x':_text('')},'interfaces':{},'engine':'test'},)\nparams.get('x')");
    assert!(has(&missing, "E0008"));
}
#[test]
fn unrelated_reader_does_not_clear_another_engine() {
    let r=report("catalogue.py","LIBRARY_ITEM_ENGINES = {'a':{'engine':'a','params':{'x':1}},'b':{'engine':'b','params':{'x':1}}}\nENGINE_SOCKETS = {'a':{'target':('x',)},'b':{'target':('x',)}}\ndef read_a(params):\n    return params.get('x')\nENGINES = {'a':read_a}\n");
    assert!(r
        .diagnostics
        .iter()
        .any(|d| d.code == "E0002" && d.message.contains("b.x")));
    assert!(!r
        .diagnostics
        .iter()
        .any(|d| d.code == "E0002" && d.message.contains("a.x")));
}
#[test]
fn parameter_shaped_local_dictionary_is_not_a_node() {
    assert!(has(&report("fake.py", "params = {'timeout':20}"), "E0007"));
}
#[test]
fn tests_cannot_make_dead_modules_reachable() {
    let r = analyze(&[
        (
            "nodelang/unused.py".into(),
            "def work():\n    return 1".into(),
        ),
        (
            "tests_replica/test_unused.py".into(),
            "from nodelang import unused".into(),
        ),
    ]);
    assert!(r
        .diagnostics
        .iter()
        .any(|d| d.code == "E0002" && d.file == "nodelang/unused.py"));
}
#[test]
fn behaviour_rules_execute_in_every_admitted_language() {
    let cases = [
        ("a.py", "timeout = 20", "timeout = params.get('timeout')"),
        (
            "a.jsx",
            "const timeout = 20;",
            "const timeout = params.timeout;",
        ),
        (
            "a.ts",
            "const timeout: number = 20;",
            "const timeout = params.timeout;",
        ),
        (
            "a.cs",
            "class X { int timeout = 20; }",
            "class X { int timeout = Params.Timeout; }",
        ),
        ("a.ps1", "$timeout = 20", "$timeout = $params.timeout"),
        (
            "a.cmd",
            "set TIMEOUT=20\r\n",
            "set TIMEOUT=%PARAM_TIMEOUT%\r\n",
        ),
        ("a.sh", "timeout=20\n", "timeout=$PARAM_TIMEOUT\n"),
        (
            "a.rs",
            "const TIMEOUT: u64 = 20;",
            "fn main() { let timeout = params.timeout; }",
        ),
        (
            "a.sql",
            "CREATE TABLE policies (timeout INT DEFAULT 20);",
            "CREATE TABLE policies (value INT);",
        ),
        ("a.json", "{\"timeout\":20}", "{\"value\":20}"),
        ("a.yml", "timeout: 20\n", "value: 20\n"),
        ("a.html", "<div data-timeout=\"20\"></div>", "<div></div>"),
        (
            "a.css",
            ":root { --timeout: 20ms; }",
            ":root { color: red; }",
        ),
        ("a.toml", "timeout = 20\n", "value = 20\n"),
    ];
    for (file, bad, fixed) in cases {
        court("E0007", file, bad, fixed);
    }
}
#[test]
fn literal_catalogue_builder_and_typed_socket_comprehension() {
    let source="def catalogue_entry():\n    parameters = {'timeout': {'type':'text','default':'20'}}\n    interfaces = {name: {'direction':'input','type':'string' if spec['type'] == 'text' else spec['type']} for name,spec in parameters.items()}\n    return {'name':'Enforce','parameters':parameters,'interfaces':interfaces,'engine':'enforce'}\ndef execute(params):\n    return helper(params)\ndef helper(config):\n    return config.get('timeout')\nENGINES = {'enforce':execute}\n";
    let r = report("catalogue.py", source);
    assert!(r.diagnostics.is_empty(), "{:?}", r.diagnostics);
    let changed = source.replace("'direction':'input'", "'direction':'output'");
    assert!(has(&report("catalogue.py", &changed), "E0008"));
}
#[test]
fn all_registered_grammars_parse_real_syntax() {
    let cases = [
        ("a.py", "x = 1"),
        ("a.jsx", "const x = <div />;"),
        ("a.ts", "const x: number = 1;"),
        ("a.tsx", "const x = <div />;"),
        ("a.cs", "class X { int x = 1; }"),
        ("a.ps1", "$x = 1"),
        ("a.cmd", "@echo off\r\necho hello\r\n"),
        ("a.sh", "x=1\necho hello"),
        ("a.rs", "fn main() {}"),
        ("a.sql", "SELECT 1;"),
        ("a.json", "{\"x\":1}"),
        ("a.yml", "x: 1\n"),
        ("a.html", "<div>hello</div>"),
        ("a.css", "a { color: red; }"),
        ("a.toml", "x = 1\n"),
    ];
    for (file, source) in cases {
        let r = report(file, source);
        assert_ne!(language_name(file), "unsupported");
        assert!(
            !has(&r, "E0010") && !has(&r, "E0011"),
            "{file}: {:?}",
            r.diagnostics
        );
    }
}

#[test]
fn an_action_id_without_a_callback_is_not_a_working_button() {
    let r=report("view.jsx", "const save=()=>send(); const ACTIONS={save:save}; const View=()=> <button actionId='save'>Save</button>;");
    assert!(has(&r, "E0005"));
}
#[test]
fn embedded_html_and_svg_code_is_checked_with_original_locations() {
    for file in ["view.html", "icon.svg"] {
        let report = archhub_compiler::compile(
            &[(
                file.into(),
                "<html>\n<script>const timeout=20; missing();</script>\n</html>".into(),
            )],
            None,
        );
        assert!(report
            .diagnostics
            .iter()
            .any(|d| d.code == "E0007" && d.file == file && d.line == 2));
        assert!(report
            .diagnostics
            .iter()
            .any(|d| d.code == "E0020" && d.file == file && d.line == 2));
    }
}
#[test]
fn opaque_executable_content_refuses_and_nested_callbacks_do_not_run() {
    for (file, source) in [
        ("a.py", "exec('missing()')"),
        ("a.js", "eval('missing()')"),
        ("b.js", "new Function('missing()')"),
        ("a.svg", "<svg onload='missing()'/>"),
        ("a.html", "<a href='javascript:missing()'>go</a>"),
    ] {
        assert!(has(&report(file, source), "E0010"), "{file}");
    }
    for body in ["()=>()=>save()", "()=>{const save=()=>{};save();}"] {
        let source = format!("const save=()=>send(); const ACTIONS={{save:save}}; const View=()=> <button actionId='save' onClick={{{body}}}>Save</button>;");
        assert!(has(&report("view.jsx", &source), "E0005"), "{body}");
    }
}

#[test]
fn retirement_tokens_and_descriptive_metric_labels_are_not_paths_or_controls() {
    let r = report("a.py", "RETIRED = ['replace', 'retired']\nLABELS = {'model_routers': 'description'}\ntext = 'replace'\n");
    assert!(!has(&r, "E0006"), "{:?}", r.diagnostics);
    assert!(!has(&r, "E0007"), "{:?}", r.diagnostics);
    assert!(has(&report("a.py", "RETIRED = ['/old']\nvisit('/old')\n"), "E0006"));
    assert!(has(&report("a.py", "timeout = 5\n"), "E0007"));
    assert!(has(&report("a.py", "RETIRED = ['old.py']\nvisit('old.py')\n"), "E0006"));
}

#[test]
fn synchronous_timer_effect_is_not_a_request() {
    let r = report("hub.jsx", "const Hub = () => { const [open,setOpen]=useState(false); useEffect(() => { if(!open) return; const timer=setTimeout(() => setOpen(false),6000); return () => clearTimeout(timer); },[open]); return <div>{open ? 'Confirm' : 'Ready'}</div>; };");
    assert!(!has(&r, "E0003") && !has(&r, "E0004"), "timer effect is synchronous UI state: {:?}", r.diagnostics);
}

#[test]
fn submit_button_uses_its_registered_form_action() {
    let source = "const save=()=>send(); const ACTIONS={save:save}; const View=()=> <form onSubmit={()=>save()}><button type='submit'>Save</button></form>;";
    assert!(!has(&report("view.jsx", source), "E0005"));
    assert!(has(&report("view.jsx", &source.replace(" onSubmit={()=>save()}", "")), "E0005"));
    assert!(has(&report("view.jsx", &source.replace("save()}", "missing()}")), "E0005"));
    assert!(has(&report("view.jsx", &source.replace("type='submit'", "type='submit' actionId='absent'")), "E0005"));
}
#[test]
fn request_effects_still_need_rendered_request_states() {
    for source in [
        "const Screen = () => {useEffect(() => { fetch('/items'); }, []); return <div>ready</div>;};",
        "const Screen = () => {useEffect(async () => {await loadItems();}, []); return <div>ready</div>;};",
        "const Screen = () => {useEffect(() => {loadItems().then(setItems);}, []); return <div>ready</div>;};",
        "const loadItems = () => fetch('/items'); const Screen = () => {useEffect(() => {loadItems();}, []); return <div>ready</div>;};",
        "const Screen = () => {useEffect(() => {const timer=setTimeout(() => fetch('/items'), delay); return () => clearTimeout(timer);}, []); return <div>ready</div>;};",
    ] {
        let r = report("screen.jsx", source);
        assert!(has(&r, "E0003") && has(&r, "E0004"), "request effect escaped: {:?}", r.diagnostics);
    }
}

#[test]
fn external_roots_follow_real_imports_and_do_not_hide_unused_modules() {
    let files = vec![
        ("EXTERNAL/PLUGIN/ENTRY.py".into(), "from nodelang import extension
".into()),
        ("nodelang/extension.py".into(), "def answer():
    return 1
".into()),
        ("nodelang/orphan.py".into(), "def orphan():
    return 2
".into()),
    ];
    assert!(analyze(&files).diagnostics.iter().any(|d| d.code == "E0002" && d.file == "nodelang/extension.py"));
    let report = archhub_compiler::compile_with_entrypoints(&files, None, &["EXTERNAL/PLUGIN/ENTRY.py".into()]);
    assert!(!report.diagnostics.iter().any(|d| d.code == "E0002" && d.file == "nodelang/extension.py"));
    assert!(report.diagnostics.iter().any(|d| d.code == "E0002" && d.file == "nodelang/orphan.py"));
}

#[test]
fn state_messages_and_registered_ui_targets_are_not_configuration() {
    let source = "const NAVIGATION_ROUTES={canvas:'Canvas'}; const doc={route:'canvas'};";
    assert!(!has(&report("ui.js", source), "E0007"));
    assert!(has(&report("ui.js", "const NAVIGATION_ROUTES={canvas:'Canvas'}; const config={route:'remote'};"), "E0007"));
    assert!(!has(&report("status.py", "archive_status = 'failed'
codes = {'response timeout invalid':'invalid'}
"), "E0007"));
    assert!(has(&report("policy.py", "archive_timeout = 5
"), "E0007"));
}
