use archhub_compiler::{deviation, intent, semantics};
use serde_json::json;
fn has(code: &str, file: &str, source: &str) -> bool {
    semantics::check(&[(file.into(), source.into())])
        .iter()
        .any(|d| d.code == code)
}
#[test]
fn undefined_name_red_fixed_and_lexical_isolation() {
    assert!(has("E0020", "a.py", "def f():\n    return missing\n"));
    assert!(!has("E0020", "a.py", "def f(value):\n    return value\n"));
    assert!(has(
        "E0020",
        "a.py",
        "def first():\n    hidden = 1\n    return hidden\ndef second():\n    return hidden\n"
    ));
    assert!(has("E0020", "a.js", "function f() { return missing; }"));
    assert!(!has("E0020", "a.js", "function f(value) { return value; }"));
}

#[test]
fn catch_bindings_are_local_and_platform_builtins_are_resolved() {
    assert!(!has("E0020", "a.js", "try { fetch('/'); } catch (error) { console.error(error); }"));
    assert!(has("E0020", "a.js", "try { fetch('/'); } catch (error) { console.error(error); } console.log(error);"));
    assert!(!has("E0020", "a.js", "fetch('/', {signal: AbortSignal.timeout(100)});"));
    assert!(!has("E0020", "a.py", "try:\n    print('ready')\nexcept (KeyboardInterrupt, ConnectionRefusedError):\n    raise\n"));
    assert!(has("E0020", "a.py", "raise ConnectionRefussedError()\n"));
}

#[test]
fn optional_destructured_parameters_still_occupy_argument_positions() {
    let source = "function mount(data, {active = true} = {}) { return [data, active]; } mount({}, {});";
    assert!(!has("E0025", "a.js", source));
    assert!(has("E0025", "a.js", &source.replace("mount({}, {});", "mount({}, {}, {});")));
}

#[test]
fn anonymous_function_returns_do_not_belong_to_the_enclosing_function() {
    assert!(!has("E0024", "a.js", "(() => { const f = function() { return 1; }; console.log(f()); })();"));
    assert!(has("E0024", "a.js", "function f(value) { if(value) return 1; }"));
    assert!(!has("E0024", "a.js", "(() => { const api = { read() { return 1; } }; console.log(api.read()); })();"));
}

#[test]
fn javascript_loop_declarations_have_block_scope() {
    assert!(!has("E0021", "a.js", "for(const fn of [1]) { console.log(fn); } for(const fn of [2]) { console.log(fn); }"));
    assert!(has("E0020", "a.js", "for(const fn of [1]) { console.log(fn); } console.log(fn);"));
    assert!(!has("E0020", "a.js", "for(var fn of [1]) { console.log(fn); } console.log(fn);"));
    assert!(!has("E0020", "a.js", "let fn=0; for(fn of [1]) { console.log(fn); } console.log(fn);"));
}
#[test]
fn redefinition_red_fixed_shadow_is_allowed() {
    assert!(has(
        "E0021",
        "a.py",
        "def f():\n    pass\ndef f():\n    pass\n"
    ));
    assert!(!has(
        "E0021",
        "a.py",
        "def f():\n    pass\ndef g():\n    pass\n"
    ));
    assert!(!has(
        "E0021",
        "a.js",
        "const x=1; function f(){const x=2;return x;} console.log(x);"
    ));
}
#[test]
fn unused_import_and_variable_red_fixed() {
    assert!(has("E0022", "a.py", "import os\n"));
    assert!(!has("E0022", "a.py", "import os\nprint(os.name)\n"));
    assert!(has(
        "E0022",
        "a.js",
        "function f(){const unused=1;return 2;}"
    ));
    assert!(!has(
        "E0022",
        "a.js",
        "function f(){const value=1;return value;}"
    ));
}
#[test]
fn unreachable_red_fixed() {
    assert!(has(
        "E0023",
        "a.py",
        "def f():\n    return 1\n    print(2)\n"
    ));
    assert!(!has(
        "E0023",
        "a.py",
        "def f():\n    print(2)\n    return 1\n"
    ));
}
#[test]
fn missing_return_red_fixed() {
    assert!(has(
        "E0024",
        "a.py",
        "def f(flag) -> int:\n    if flag:\n        return 1\n"
    ));
    assert!(!has(
        "E0024",
        "a.py",
        "def f(flag) -> int:\n    if flag:\n        return 1\n    return 0\n"
    ));
}
#[test]
fn wrong_arity_red_fixed() {
    assert!(has("E0025", "a.py", "def f(a,b=1):\n    return a+b\nf()\n"));
    assert!(!has(
        "E0025",
        "a.py",
        "def f(a,b=1):\n    return a+b\nf(2)\n"
    ));
    assert!(has(
        "E0025",
        "a.py",
        "def f(a,b=1):\n    return a+b\nf(unknown=2)\n"
    ));
    assert!(!has(
        "E0025",
        "a.py",
        "def f(a,b=1):\n    return a+b\nf(a=2)\n"
    ));
}
#[test]
fn explicit_type_red_fixed() {
    assert!(has(
        "E0026",
        "a.ts",
        "const value: number = 'wrong'; console.log(value);"
    ));
    assert!(!has(
        "E0026",
        "a.ts",
        "const value: number = 2; console.log(value);"
    ));
}
fn context() -> serde_json::Value {
    json!({"author":"court-human","intent":"ACOMPILER","files":["03.TOOLS/tools/archhub-compiler/src/lib.rs"]})
}
#[test]
fn intent_no_intent_red_fixed() {
    let mut c = context();
    c["intent"] = json!("");
    assert!(intent::check(&c, &[]).iter().any(|d| d.code == "E0100"));
    assert!(intent::check(&context(), &[]).is_empty());
}
#[test]
fn intent_outside_scope_red_fixed_and_scope_cannot_be_forged() {
    let mut c = context();
    c["files"] = json!(["unrelated.py"]);
    c["scope"] = json!(["unrelated.py"]);
    assert!(intent::check(&c, &[]).iter().any(|d| d.code == "E0101"));
    assert!(!intent::check(&context(), &[])
        .iter()
        .any(|d| d.code == "E0101"));
}
#[test]
fn machine_intent_rule_red_fixed() {
    let mut c = context();
    c["files"] = json!(["01.APP/nodelang/enforce.py"]);
    assert!(intent::check(
        &c,
        &[(
            "01.APP/nodelang/enforce.py".into(),
            "title = 'Not available yet'\n".into()
        )]
    )
    .iter()
    .any(|d| d.code == "E0102"));
    assert!(!intent::check(
        &c,
        &[("01.APP/nodelang/enforce.py".into(), "title = 'Ready'\n".into())]
    )
    .iter()
    .any(|d| d.code == "E0102"));
}
fn deviation_context() -> serde_json::Value {
    let mut c = context();
    c["metrics"] = json!({"files":100,"lines":0,"ratchet_deltas":0,"tests_removed":0,"languages":0,"scope_spread":0,"rule_hits":0});
    c["history"] = json!((0..8)
        .map(|_| json!({"author":"court-human","metrics":{"files":2}}))
        .collect::<Vec<_>>());
    c
}
#[test]
fn deviation_red_fixed_author_isolation_and_budget_cannot_bypass() {
    let mut c = deviation_context();
    c["daily_alert_budget"] = json!(0);
    assert!(deviation::check(&c).iter().any(|d| d.code == "E0200"));
    c["why"] = json!("Authorized mechanical relocation of the compiler.");
    assert!(deviation::check(&c).is_empty());
    c["why"] = json!("");
    c["author"] = json!("another-human");
    assert!(deviation::check(&c).is_empty());
}
#[test]
fn sustained_change_is_recorded_as_method() {
    let mut c = deviation_context();
    c["deviation_state"] =
        json!({"author":"court-human","metrics":{"files":{"median":2,"mad":0,"cusum_up":300}}});
    for _ in 0..3 {
        c["history"]
            .as_array_mut()
            .unwrap()
            .push(json!({"author":"court-human","metrics":{"files":100}}));
    }
    let observation = deviation::observe(&c);
    assert_eq!(observation["method_changes"][0]["metric"], "files");
    assert!(deviation::check(&c).is_empty());
}
#[test]
fn absorbed_passes_require_no_external_checker_executable() {
    // All entrypoints below are direct library calls with no process runner.
    let source = include_str!("../src/semantics.rs");
    assert!(!source.contains("std::process"));
    assert!(!source.contains("Command::"));
    assert!(has("E0020", "court.py", "print(undefined_name)\n"));
    assert!(intent::check(&context(), &[]).is_empty());
    let _ = deviation::observe(&context());
}

#[test]
fn python_directives_aliases_annotations_and_lambda_are_scoped() {
    let source = "from __future__ import annotations\nfrom pathlib import Path\ndef f(path: Path) -> str:\n    try:\n        with path.open() as stream:\n            return stream.read()\n    except OSError as error:\n        return str(error)\nquote = lambda value: str(value)\nprint(quote('ok'))\n";
    let rows = semantics::check(&[("a.py".into(), source.into())]);
    assert!(
        !rows
            .iter()
            .any(|d| matches!(d.code.as_str(), "E0020" | "E0022")),
        "{rows:?}"
    );
    assert!(has(
        "E0020",
        "a.py",
        "class C:\n    value = 1\n    def f(self):\n        return value\n"
    ));
    assert!(has(
        "E0020",
        "a.py",
        "result = [x for x in range(2)]\nprint(x)\n"
    ));
}

#[test]
fn machine_parameters_edit_rules_without_rewriting_intent_authority() {
    let mut c = context();
    c["files"] = json!(["01.APP/nodelang/enforce.py"]);
    c["machine_rule_parameters"] = json!({"banned_user_text":[]});
    assert!(!intent::check(
        &c,
        &[(
            "01.APP/nodelang/enforce.py".into(),
            "title='Not available yet'\n".into()
        )]
    )
    .iter()
    .any(|d| d.code == "E0102"));
    c["machine_rule_parameters"] = json!({"intents":{"ANY":{"scope":["/"]}}});
    assert!(intent::check(&c, &[]).iter().any(|d| d.code == "E0102"));
}

#[test]
fn deviation_state_cannot_cross_author_and_missing_metrics_refuse() {
    let mut c = deviation_context();
    c["metrics"]["files"] = json!(2);
    c["deviation_state"] =
        json!({"author":"other-agent","metrics":{"files":{"median":100,"mad":0,"cusum_down":50}}});
    assert!(deviation::check(&c).is_empty());
    c["metrics"].as_object_mut().unwrap().remove("rule_hits");
    c["why"] = json!("A reason cannot invent a missing measurement");
    assert!(deviation::check(&c).iter().any(|d| d.code == "E0200"));
}

#[test]
fn python_mapping_keys_nonlocal_and_variadic_keyword_calls() {
    for source in [
        "def f(items):\n    return {name: value for name, value in items}\n",
        "def f():\n    seen = False\n    def g():\n        nonlocal seen\n        if not seen:\n            seen = True\n        return seen\n    return g()\n",
        "def report(*diagnostics, files=None):\n    return diagnostics, files\nreport(1, files=[])\n",
        "raise FileExistsError('busy')\n",
    ] {
        let result = semantics::check(&[("a.py".into(), source.into())]);
        assert!(result.is_empty(), "{:?}", result);
    }
    assert!(has("E0025", "a.py", "def f(x, *, y):\n    return x, y\nf(1)\n"));
    assert!(has("E0025", "a.py", "def f(*args, required):\n    return args, required\nf(1)\n"));
    assert!(has("E0025", "a.py", "def f(x, *, y):\n    return x, y\nf(1, 2)\n"));
    assert!(has("E0025", "a.py", "def f(*args):\n    return args\nf(wrong=1)\n"));
    assert!(has("E0020", "a.py", "def f():\n    print(x)\n    x = 1\n    return x\n"));
}

#[test]
fn assigned_functions_enforce_arity_red_green() {
    for (file, bad, good) in [
        ("a.js", "const f=(x)=>x; console.log(f());", "const f=(x)=>x; console.log(f(1));"),
        ("a.py", "f = lambda x: x\nprint(f())\n", "f = lambda x: x\nprint(f(1))\n"),
    ] {
        assert!(has("E0025", file, bad), "{file}: assigned function escaped arity");
        assert!(!has("E0025", file, good));
    }
}

#[test]
fn typed_calls_enforce_declared_parameter_red_green() {
    assert!(has("E0026", "a.ts", "function f(n:number):number{return n;} console.log(f('bad'));"));
    assert!(!has("E0026", "a.ts", "function f(n:number):number{return n;} console.log(f(1));"));
}

#[test]
fn alert_budget_batches_at_break_and_resets_without_admitting_errors() {
    let mut c = deviation_context();
    c["day"] = json!("2026-10-16");
    c["daily_alert_budget"] = json!(1);
    let first = deviation::observe(&c);
    assert_eq!(first["notices"].as_array().unwrap().len(), 1);
    assert_eq!(first["notices"][0]["deliver_at"], "natural_break");
    c["alert_state"] = first["alert_state"].clone();
    assert!(deviation::observe(&c)["notices"].as_array().unwrap().is_empty());
    assert!(!deviation::check(&c).is_empty());
    c["day"] = json!("2026-10-17");
    assert_eq!(deviation::observe(&c)["notices"].as_array().unwrap().len(), 1);
}

#[test]
fn intent_rules_inspect_source_without_voluntary_vendor_or_panel_flags() {
    let mut c = context();
    c["files"] = json!(["vendor/product/main.js"]);
    assert!(intent::check(&c, &[("vendor/product/main.js".into(), "export const ready=true;".into())])
        .iter().any(|d| d.code == "E0102"));
    c["files"] = json!(["01.APP/nodelang/presentation.jsx"]);
    assert!(intent::check(&c, &[("01.APP/nodelang/presentation.jsx".into(), "export const Surface=()=> <Panel/>;".into())])
        .iter().any(|d| d.code == "E0102"));
    assert!(!intent::check(&c, &[("01.APP/nodelang/presentation.jsx".into(), "export const Surface=()=> <Graph/>;".into())])
        .iter().any(|d| d.code == "E0102"));
}

#[test]
fn html_intent_rules_use_html_ast_text_attributes_and_tags() {
    let mut c = context();
    c["files"] = json!(["index.html"]);
    for source in ["<p>coming soon</p>", "<button title='coming soon'>Open</button>", "<iframe src='/x'></iframe>"] {
        assert!(intent::check(&c, &[("index.html".into(), source.into())]).iter().any(|d| d.code == "E0102"), "{source}");
    }
    assert!(!intent::check(&c, &[("index.html".into(), "<p>Ready</p>".into())]).iter().any(|d| d.code == "E0102"));
}
