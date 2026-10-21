//! Parse -> source facts -> product model -> diagnostics. No source is executed.
//! Rustc/Clippy architecture is learned; no rustc code is included.
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::{BTreeMap, BTreeSet};
use tree_sitter::{Language, Node, Parser};
pub mod deviation;
pub mod intent;
pub mod semantics;

pub const CODES: &[&str] = &[
    "E0001", "E0002", "E0003", "E0004", "E0005", "E0006", "E0007", "E0008", "E0009", "E0010",
    "E0011", "E0020", "E0021", "E0022", "E0023", "E0024", "E0025", "E0026", "E0100", "E0101",
    "E0102", "E0200",
];

pub fn explain(code: &str) -> Option<&'static str> {
    Some(match code {
        "E0001"=>"Ownership: one product object has more than one defining owner. Merge the definitions; remove replaced references.",
        "E0002"=>"Unused: a declared parameter, route or module has no resolved runtime reader or shipped entrypoint. Test imports and prose do not count.",
        "E0003"=>"States: an async screen must render loaded, empty, error and waiting branches for one request state; runtime placeholders are refused.",
        "E0004"=>"Failure: discarded exceptions and actions without actionable failure UI hide unsuccessful work. Return a typed failure and offer retry.",
        "E0005"=>"Bindings: controls must name registered actions and Settings must bind real catalogue parameters.",
        "E0006"=>"Lifetime: a retired route or replaced path is still referenced. Remove it in the same change as its replacement.",
        "E0007"=>"Configuration: a behaviour-shaping literal must be a visible, editable node parameter with a typed socket.",
        "E0008"=>"Parameters: every node parameter needs an input socket of the same name. A local dictionary named params is insufficient.",
        "E0009"=>"Types: parameter, socket and wire endpoint types and directions must agree; proposed model values must match their declared types.",
        "E0010"=>"Coverage: source, language rules, artifact contracts or compiler dependencies are unavailable. This is a refusal, never a skipped pass.",
        "E0011"=>"Syntax: a parser recovery or missing token means there is no valid model to check. Repair syntax first.",
        "E0020"=>"Undefined name: declare or import the identifier in its lexical scope before reading it.",
        "E0021"=>"Redefinition: keep one definition per symbol in its lexical scope.",
        "E0022"=>"Unused binding: read the imported name or local variable, or remove the binding.",
        "E0023"=>"Unreachable code: statements after an unconditional terminator cannot execute.",
        "E0024"=>"Missing return: a function declaring a value result must return it on every reachable path.",
        "E0025"=>"Wrong arity: arguments must satisfy the statically resolved function signature.",
        "E0026"=>"Type mismatch: a statically declared JS/TS type is incompatible with the assigned value.",
        "E0100"=>"Intent: an agent or human change must identify an authoritative intent through its session record or Intent trailer.",
        "E0101"=>"Scope: touched files must be inside that intent's authoritative declared scope.",
        "E0102"=>"Intent rule: this change violates a compiled founder rule. Change the artifact or obtain an explicit authority update.",
        "E0200"=>"Deviation: a change outside the author's robust median/MAD band requires a Why line; a sustained shift becomes the new method.",
        _=>return None,
    })
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq, PartialOrd, Ord)]
pub struct Diagnostic {
    pub code: String,
    pub language: String,
    pub file: String,
    pub line: usize,
    pub column: usize,
    pub message: String,
    #[serde(default)]
    pub note: String,
    pub help: String,
}
impl Diagnostic {
    pub fn render(&self) -> String {
        format!(
            "error[{}]: {}\n  --> {}:{}:{}\n  note: {}\n  help: {}",
            self.code, self.message, self.file, self.line, self.column, self.note, self.help
        )
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SourceFile {
    pub file: String,
    pub language: String,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Report {
    pub schema_version: u32,
    pub counts: BTreeMap<String, BTreeMap<String, usize>>,
    pub diagnostics: Vec<Diagnostic>,
    pub files: Vec<SourceFile>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub observation: Option<Value>,
}
impl Report {
    pub fn extend(&mut self, diagnostics: Vec<Diagnostic>) {
        self.diagnostics.extend(diagnostics);
        self.diagnostics.sort();
        self.diagnostics.dedup();
        self.counts = CODES
            .iter()
            .map(|c| (c.to_string(), BTreeMap::new()))
            .collect();
        let languages: BTreeSet<_> = self
            .files
            .iter()
            .map(|f| f.language.clone())
            .chain(self.diagnostics.iter().map(|d| d.language.clone()))
            .collect();
        for language in languages {
            for per_language in self.counts.values_mut() {
                per_language.entry(language.clone()).or_insert(0);
            }
        }
        for d in &self.diagnostics {
            *self
                .counts
                .entry(d.code.clone())
                .or_default()
                .entry(d.language.clone())
                .or_default() += 1;
        }
    }
}

pub fn compile(sources: &[(String, String)], context: Option<&Value>) -> Report {
    compile_with_entrypoints(sources, context, &[])
}

pub fn compile_with_entrypoints(sources: &[(String, String)], context: Option<&Value>, entrypoints: &[String]) -> Report {
    let (expanded, locations) = expanded_sources(sources);
    let mut report = analyze_flat(&expanded, entrypoints);
    report.extend(semantics::check(&expanded));
    restore_locations(&mut report, &locations);
    if let Some(context) = context {
        apply_context(&mut report, context, sources);
    }
    report
}
pub fn analyze(sources: &[(String, String)]) -> Report {
    let (expanded, locations) = expanded_sources(sources);
    let mut report = analyze_flat(&expanded, &[]);
    restore_locations(&mut report, &locations);
    report
}
fn expanded_sources(
    sources: &[(String, String)],
) -> (
    Vec<(String, String)>,
    BTreeMap<String, (String, usize, usize)>,
) {
    let mut expanded = sources.to_vec();
    let mut locations = BTreeMap::new();
    for (file, source) in sources {
        if language_name(file) != "html" {
            continue;
        }
        let mut parser = Parser::new();
        if parser
            .set_language(&tree_sitter_html::LANGUAGE.into())
            .is_err()
        {
            continue;
        }
        let Some(tree) = parser.parse(source, None) else {
            continue;
        };
        let mut stack = vec![tree.root_node()];
        let mut index = 0;
        while let Some(node) = stack.pop() {
            if matches!(node.kind(), "script_element" | "style_element") {
                for body in children(node)
                    .into_iter()
                    .filter(|n| n.kind() == "raw_text")
                {
                    let extension = if node.kind() == "style_element" {
                        "css"
                    } else {
                        "js"
                    };
                    let name = format!("{file}.embedded-{index}.{extension}");
                    index += 1;
                    locations.insert(
                        name.clone(),
                        (
                            file.clone(),
                            body.start_position().row,
                            body.start_position().column,
                        ),
                    );
                    expanded.push((name, text(body, source).into()));
                }
            }
            stack.extend(children(node));
        }
    }
    (expanded, locations)
}
fn restore_locations(report: &mut Report, locations: &BTreeMap<String, (String, usize, usize)>) {
    for diagnostic in &mut report.diagnostics {
        if let Some((file, line, column)) = locations.get(&diagnostic.file) {
            diagnostic.file = file.clone();
            if diagnostic.line == 1 {
                diagnostic.column += column;
            }
            diagnostic.line += line;
        }
    }
    for file in &mut report.files {
        if let Some((original, _, _)) = locations.get(&file.file) {
            file.file = original.clone();
        }
    }
    report.extend(vec![]);
}
pub fn apply_context(report: &mut Report, context: &Value, sources: &[(String, String)]) {
    apply_context_with_authority(report, context, sources, &intent::authority());
}
pub fn apply_context_with_authority(report: &mut Report, context: &Value, sources: &[(String, String)], authority: &Value) {
    let mut context = context.clone();
    if !context.is_object() {
        context = serde_json::json!({});
    }
    if !context["metrics"].is_object() {
        context["metrics"] = serde_json::json!({});
    }
    let files = context["files"].as_array().cloned().unwrap_or_default();
    context["metrics"]["rule_hits"] = serde_json::json!(report
        .diagnostics
        .iter()
        .filter(|d| files.iter().any(|f| f.as_str() == Some(d.file.as_str())))
        .count());
    let mut deltas = 0usize;
    for (code, languages) in &report.counts {
        for (language, count) in languages {
            let baseline = context["baseline_counts"][code][language]
                .as_u64()
                .unwrap_or(0) as usize;
            deltas += count.saturating_sub(baseline);
        }
    }
    context["metrics"]["ratchet_deltas"] = serde_json::json!(deltas);
    report.extend(intent::check_with_authority(&context, sources, authority));
    report.extend(deviation::check(&context));
    report.observation = Some(deviation::observe(&context));
}

#[derive(Clone, Debug)]
struct Span {
    file: String,
    language: String,
    line: usize,
    column: usize,
}
impl Span {
    fn diagnostic(&self, code: &str, message: impl Into<String>, help: &str) -> Diagnostic {
        Diagnostic {
            code: code.into(),
            note: explain(code).unwrap_or("compiler input refusal").into(),
            file: self.file.clone(),
            language: self.language.clone(),
            line: self.line,
            column: self.column,
            message: message.into(),
            help: help.into(),
        }
    }
}
#[derive(Clone, Debug)]
struct Param {
    owner: String,
    name: String,
    kind: String,
    span: Span,
}
#[derive(Clone, Debug)]
struct Socket {
    owner: String,
    name: String,
    side: String,
    kind: String,
    span: Span,
}
#[derive(Clone, Debug)]
struct Wire {
    source: (String, String),
    target: (String, String),
    span: Span,
}
#[derive(Clone, Debug)]
struct Reader {
    name: String,
    function: String,
}

#[derive(Default)]
struct Model {
    owners: BTreeMap<String, Vec<Span>>,
    params: Vec<Param>,
    sockets: Vec<Socket>,
    wires: Vec<Wire>,
    readers: Vec<Reader>,
    function_engines: BTreeMap<String, BTreeSet<String>>,
    node_engines: BTreeMap<String, String>,
    calls: BTreeMap<String, BTreeSet<String>>,
    aliases: BTreeMap<String, String>,
    parameter_sources: Vec<(String, String, String)>,
    actions: BTreeMap<String, String>,
    buttons: Vec<(String, String, Span)>,
    settings: Vec<(String, Span)>,
    retired: BTreeSet<String>,
    uses: Vec<(String, Span)>,
    routes: Vec<(String, Span)>,
    imports: BTreeMap<String, BTreeSet<String>>,
    modules: BTreeMap<String, Span>,
    entrypoints: BTreeSet<String>,
    navigation_routes: BTreeSet<String>,
    diagnostics: Vec<Diagnostic>,
}

pub fn source_identity(file: &str) -> String {
    if file == "launch_archhub_test.py" || file == "01.APP/nodelang/launcher.py" {
        return "nodelang/launcher.py".into();
    }
    if file == "01.APP/nodelang/colleague_setup.py" { return "colleague_setup.py".into(); }
    for (area, native) in [("04.DOCS/", "docs/"), ("05.EVIDENCE/", "evidence/")] {
        if let Some(relative) = file.strip_prefix(area) { return format!("{native}{relative}"); }
    }
    for area in ["01.APP/", "02.TESTS/", "03.TOOLS/", "06.CLOUD/"] {
        if let Some(relative) = file.strip_prefix(area) {
            if relative.contains('/') { return relative.into(); }
        }
    }
    file.into()
}

pub fn language_name(path: &str) -> &'static str {
    let lower = path.to_lowercase();
    let ext = lower.rsplit('.').next().unwrap_or("");
    match ext {
        "py" | "pyw" => "python",
        "js" | "jsx" | "cjs" | "mjs" => "javascript",
        "ts" | "tsx" | "mts" | "cts" => "typescript",
        "cs" => "csharp",
        "ps1" | "psm1" | "psd1" => "powershell",
        "bat" | "cmd" => "cmd",
        "sh" | "bash" => "bash",
        "rs" => "rust",
        "sql" => "sql",
        "json" | "jsonl" => "json",
        "yaml" | "yml" => "yaml",
        "html" | "htm" | "svg" => "html",
        "css" => "css",
        "toml" => "toml",
        "ms" | "mcr" | "mse" => "maxscript",
        "md" | "txt" | "rst" | "patch" | "sha256" | "log" | "png" | "jpg" | "jpeg" | "gif"
        | "ico" | "webp" | "woff" | "woff2" | "ttf" | "otf" | "pdf" | "dxf" | "dwg" | "rvt"
        | "fbx" | "max" | "3dm" | "mp3" | "wav" | "mp4" => "asset",
        _ if lower.ends_with("cargo.lock") => "toml",
        _ if lower.ends_with(".gitignore")
            || lower.ends_with(".gitattributes")
            || lower.ends_with("notice")
            || lower.ends_with("version") =>
        {
            "asset"
        }
        _ => "unsupported",
    }
}

fn grammar(language: &str, path: &str) -> Option<Language> {
    Some(match language {
        "python" => tree_sitter_python::LANGUAGE.into(),
        "javascript" => tree_sitter_javascript::LANGUAGE.into(),
        "typescript" if path.ends_with("tsx") => tree_sitter_typescript::LANGUAGE_TSX.into(),
        "typescript" => tree_sitter_typescript::LANGUAGE_TYPESCRIPT.into(),
        "csharp" => tree_sitter_c_sharp::LANGUAGE.into(),
        "powershell" => tree_sitter_powershell::LANGUAGE.into(),
        "cmd" => tree_sitter_batch::LANGUAGE.into(),
        "bash" => tree_sitter_bash::LANGUAGE.into(),
        "rust" => tree_sitter_rust::LANGUAGE.into(),
        "sql" => tree_sitter_sequel::LANGUAGE.into(),
        "json" => tree_sitter_json::LANGUAGE.into(),
        "yaml" => tree_sitter_yaml::LANGUAGE.into(),
        "html" => tree_sitter_html::LANGUAGE.into(),
        "css" => tree_sitter_css::LANGUAGE.into(),
        "toml" => tree_sitter_toml_ng::LANGUAGE.into(),
        _ => return None,
    })
}

fn children(node: Node<'_>) -> Vec<Node<'_>> {
    let mut cursor = node.walk();
    node.named_children(&mut cursor).collect()
}
fn text<'a>(node: Node<'_>, source: &'a str) -> &'a str {
    source.get(node.byte_range()).unwrap_or("")
}
fn locally_shadowed(node: Node<'_>, name: &str, source: &str) -> bool {
    let mut ancestor = node.parent();
    while let Some(scope) = ancestor {
        if matches!(
            scope.kind(),
            "arrow_function" | "function_expression" | "function_declaration" | "method_definition"
        ) {
            if scope.child_by_field_name("parameters").is_some_and(|p| {
                let mut pending = vec![p];
                while let Some(n) = pending.pop() {
                    if n.kind() == "identifier" && text(n, source) == name {
                        return true;
                    }
                    pending.extend(children(n));
                }
                false
            }) {
                return true;
            }
            let mut pending = scope
                .child_by_field_name("body")
                .into_iter()
                .collect::<Vec<_>>();
            while let Some(n) = pending.pop() {
                if matches!(
                    n.kind(),
                    "arrow_function"
                        | "function_expression"
                        | "function_declaration"
                        | "class_declaration"
                ) {
                    continue;
                }
                if n.kind() == "variable_declarator"
                    && n.child_by_field_name("name")
                        .is_some_and(|id| text(id, source) == name)
                {
                    return true;
                }
                pending.extend(children(n));
            }
        }
        ancestor = scope.parent();
    }
    false
}
fn scalar(node: Node<'_>, source: &str) -> Option<String> {
    match node.kind() {
        "string"
        | "string_literal"
        | "interpreted_string_literal"
        | "raw_string_literal"
        | "template_string"
        | "string_value"
        | "quoted_attribute_value"
        | "string_scalar"
        | "double_quote_scalar"
        | "single_quote_scalar" => {
            let raw = text(node, source);
            if let Ok(s) = serde_json::from_str::<String>(raw) {
                return Some(s);
            }
            let raw = raw.trim_start_matches(['r', 'u', 'f', 'b', '$', '@']);
            Some(raw.trim_matches(['\'', '"', '`']).to_string())
        }
        "identifier" | "property_identifier" | "type_identifier" | "plain_scalar" | "bare_key" => {
            Some(text(node, source).to_string())
        }
        _ => None,
    }
}
fn value(node: Node<'_>, source: &str) -> Value {
    match node.kind() {
        "call" | "call_expression" => {
            let name = node
                .child_by_field_name("function")
                .map(|n| text(n, source))
                .unwrap_or("");
            let args = node
                .child_by_field_name("arguments")
                .map(children)
                .unwrap_or_default();
            let first = args
                .first()
                .map(|n| value(*n, source))
                .unwrap_or(Value::Null);
            match name {
                "_in" => serde_json::json!({"type":first,"direction":"input"}),
                "_out" => serde_json::json!({"type":first,"direction":"output"}),
                "_text" => serde_json::json!({"type":"string","default":first}),
                "_choice" => {
                    serde_json::json!({"type":"string","default":args.get(1).map(|n|value(*n,source))})
                }
                "frozenset" | "set" | "tuple" | "list" | "MappingProxyType" => first,
                _ => Value::Null,
            }
        }
        "dictionary" | "object" => {
            let mut map = serde_json::Map::new();
            for child in children(node) {
                if let (Some(k), Some(v)) = (
                    child.child_by_field_name("key"),
                    child.child_by_field_name("value"),
                ) {
                    if let Some(k) = scalar(k, source) {
                        map.insert(k, value(v, source));
                    }
                }
            }
            Value::Object(map)
        }
        "list" | "tuple" | "set" | "array" => Value::Array(
            children(node)
                .into_iter()
                .map(|n| value(n, source))
                .collect(),
        ),
        "integer" | "float" | "number" | "integer_literal" | "real_literal" | "float_literal" => {
            serde_json::from_str(text(node, source)).unwrap_or(Value::Null)
        }
        "true" | "false" | "boolean" | "boolean_literal" => {
            Value::Bool(text(node, source).eq_ignore_ascii_case("true"))
        }
        _ => scalar(node, source)
            .map(Value::String)
            .unwrap_or(Value::Null),
    }
}
// Bounded symbolic evaluation of catalogue builders. This reads syntax and
// literal containers; it cannot import code, perform IO or invoke user functions.
fn evaluated(node: Node<'_>, source: &str, env: &BTreeMap<String, Value>) -> Value {
    match node.kind() {
        "identifier" => env
            .get(text(node, source))
            .cloned()
            .unwrap_or_else(|| value(node, source)),
        "dictionary" | "object" => {
            let mut map = serde_json::Map::new();
            for pair in children(node) {
                if let (Some(key), Some(val)) = (
                    pair.child_by_field_name("key"),
                    pair.child_by_field_name("value"),
                ) {
                    if let Some(key) = evaluated(key, source, env).as_str() {
                        map.insert(key.into(), evaluated(val, source, env));
                    }
                }
            }
            Value::Object(map)
        }
        "list" | "tuple" | "array" => Value::Array(
            children(node)
                .into_iter()
                .map(|n| evaluated(n, source, env))
                .collect(),
        ),
        "subscript" => {
            let base = node
                .child_by_field_name("value")
                .map(|n| evaluated(n, source, env))
                .unwrap_or(Value::Null);
            let index = node
                .child_by_field_name("subscript")
                .map(|n| evaluated(n, source, env))
                .unwrap_or(Value::Null);
            index
                .as_str()
                .and_then(|key| base.get(key))
                .cloned()
                .unwrap_or(Value::Null)
        }
        "conditional_expression" => {
            let parts = children(node);
            if parts.len() == 3 {
                if evaluated(parts[1], source, env) == Value::Bool(true) {
                    evaluated(parts[0], source, env)
                } else {
                    evaluated(parts[2], source, env)
                }
            } else {
                Value::Null
            }
        }
        "comparison_operator" => {
            let parts = children(node);
            if parts.len() == 2 && text(node, source).contains("==") {
                Value::Bool(evaluated(parts[0], source, env) == evaluated(parts[1], source, env))
            } else {
                Value::Null
            }
        }
        "dictionary_comprehension" => {
            let clause = children(node)
                .into_iter()
                .find(|n| n.kind() == "for_in_clause");
            let body = node.child_by_field_name("body");
            if let (Some(clause), Some(body)) = (clause, body) {
                let left = clause
                    .child_by_field_name("left")
                    .map(children)
                    .unwrap_or_default();
                let right = clause.child_by_field_name("right");
                if left.len() == 2 {
                    if let Some(right) = right.filter(|n| n.kind() == "call") {
                        if let Some(fun) = right
                            .child_by_field_name("function")
                            .filter(|n| n.kind() == "attribute")
                        {
                            let attr = fun
                                .child_by_field_name("attribute")
                                .map(|n| text(n, source))
                                .unwrap_or("");
                            if attr == "items" {
                                let input = fun
                                    .child_by_field_name("object")
                                    .map(|n| evaluated(n, source, env))
                                    .unwrap_or(Value::Null);
                                if let Some(input) = input.as_object() {
                                    let mut output = serde_json::Map::new();
                                    for (key, val) in input {
                                        let mut local = env.clone();
                                        local.insert(
                                            text(left[0], source).into(),
                                            Value::String(key.clone()),
                                        );
                                        local.insert(text(left[1], source).into(), val.clone());
                                        if let (Some(k), Some(v)) = (
                                            body.child_by_field_name("key"),
                                            body.child_by_field_name("value"),
                                        ) {
                                            if let Some(k) = evaluated(k, source, &local).as_str() {
                                                output
                                                    .insert(k.into(), evaluated(v, source, &local));
                                            }
                                        }
                                    }
                                    return Value::Object(output);
                                }
                            }
                        }
                    }
                }
            }
            Value::Null
        }
        _ => value(node, source),
    }
}
fn string(value: &Value) -> Option<String> {
    value.as_str().map(str::to_string)
}
fn kind(value: &Value) -> String {
    match value {
        Value::Bool(_) => "boolean",
        Value::Number(_) => "number",
        Value::String(_) => "string",
        Value::Array(_) => "list",
        Value::Object(_) => "object",
        _ => "any",
    }
    .into()
}
fn datatype(kind: &str) -> String {
    match kind {
        "text" => "string",
        "bool" => "boolean",
        "float" | "int" => "number",
        other => other,
    }
    .into()
}
fn strings(value: &Value) -> Vec<String> {
    match value {
        Value::String(s) => vec![s.clone()],
        Value::Array(a) => a.iter().flat_map(strings).collect(),
        _ => vec![],
    }
}
// Test code is parsed, but is never a definition or a runtime reader in the
// shipped product model. Match path components, not incidental substrings.
fn product_source(path: &str) -> bool {
    let path = path.replace('\\', "/").to_lowercase();
    !path.split('/').any(|part| {
        matches!(
            part,
            "test" | "tests" | "fixture" | "fixtures" | "__tests__" | "__fixtures__"
        ) || part.starts_with("tests_")
    }) && !path.rsplit('/').next().is_some_and(|name| {
        name.starts_with("test_")
            || name.ends_with("_test.py")
            || name.contains(".test.")
            || name.contains(".spec.")
    })
}
fn execution_domain(path: &str) -> String {
    let parts: Vec<_> = path.split('/').collect();
    match parts.as_slice() {
        ["bridges", "sources", host, ..] => format!("bridge:{host}"),
        ["bridges", host, ..] => format!("bridge:{host}"),
        [area, _, ..] => area.to_string(),
        _ => "product".into(),
    }
}
fn retired_paths(data: &Value) -> Vec<String> {
    match data {
        Value::Array(rows)
            if rows.len() >= 2
                && rows[0].as_str().is_some_and(|s| {
                    matches!(
                        s,
                        "GET" | "POST" | "PUT" | "DELETE" | "PATCH" | "HEAD" | "OPTIONS"
                    )
                }) =>
        {
            rows[1].as_str().map(|s| vec![s.into()]).unwrap_or_default()
        }
        Value::Array(rows) => rows.iter().flat_map(retired_paths).collect(),
        Value::Object(row) => row
            .get("path")
            .or_else(|| row.get("route"))
            .map(retired_paths)
            .unwrap_or_default(),
        Value::String(path) if path.contains('/') || path.contains('\\')
            || path.rsplit_once('.').is_some_and(|(stem, extension)| !stem.is_empty() && !extension.is_empty() && extension.chars().all(char::is_alphabetic)) => vec![path.clone()],
        _ => vec![],
    }
}
fn retirement_registry(name: &str) -> bool {
    let upper = name.trim_matches('_').to_uppercase();
    matches!(upper.as_str(), "RETIRED" | "REPLACED")
        || ((upper.contains("RETIRED") || upper.contains("REPLACED"))
            && ["ROUTE", "PATH", "ADDRESS"]
                .iter()
                .any(|kind| upper.contains(kind)))
}
fn member_node<'a>(node: Node<'a>, key: &str, source: &str) -> Node<'a> {
    children(node)
        .into_iter()
        .find_map(|p| {
            let name = p.child_by_field_name("key").and_then(|n| scalar(n, source));
            if name.as_deref() == Some(key) {
                p.child_by_field_name("value")
            } else {
                None
            }
        })
        .unwrap_or(node)
}
fn is_literal(node: Node<'_>) -> bool {
    matches!(
        node.kind(),
        "string"
            | "string_literal"
            | "template_string"
            | "integer"
            | "float"
            | "number"
            | "integer_literal"
            | "float_literal"
            | "real_literal"
            | "true"
            | "false"
            | "boolean"
    )
}
fn behaviour(name: &str) -> bool {
    let name = name.to_lowercase().replace('-', "_");
    if name.chars().any(char::is_whitespace) || name.ends_with("_status") { return false; }
    [
        "timeout",
        "threshold",
        "default",
        "limit",
        "budget",
        "cadence",
        "retention",
        "keep_days",
        "archive_after",
        "seconds",
        "_days",
        "_ms",
        "_millis",
        "_duration",
        "_interval",
        "_delay",
        "_enabled",
        "flag",
        "route",
    ]
    .iter()
    .any(|part| if *part == "route" {
        name.split('_').any(|token| token == "route" || token == "routes")
    } else { name.contains(part) })
}
fn in_param(node: Node<'_>, source: &str) -> bool {
    let mut parent = node.parent();
    while let Some(p) = parent {
        if matches!(p.kind(), "pair" | "assignment" | "variable_declarator") {
            let key = p
                .child_by_field_name("key")
                .or_else(|| p.child_by_field_name("left"))
                .or_else(|| p.child_by_field_name("name"));
            if let Some(k) = key {
                let name = text(k, source).to_lowercase();
                if name.trim_matches(['\'', '"']) == "parameters"
                    || name.trim_matches(['\'', '"']) == "params"
                {
                    // A parameter exemption requires an enclosing catalogue node (engine/id),
                    // not merely a local dictionary called params.
                    let mut ancestor = p.parent();
                    while let Some(a) = ancestor {
                        if matches!(a.kind(), "dictionary" | "object") {
                            let data = value(a, source);
                            if data.get("engine").is_some()
                                || (data.get("id").is_some() && data.get("params").is_some())
                            {
                                return true;
                            }
                        }
                        if a.kind() == "function_definition" {
                            if let Some(body) = a.child_by_field_name("body") {
                                for statement in children(body)
                                    .into_iter()
                                    .filter(|n| n.kind() == "return_statement")
                                {
                                    if let Some(returned) = children(statement).first() {
                                        let row = value(*returned, source);
                                        if row.get("engine").is_some()
                                            && (row.get("parameters").and_then(Value::as_str)
                                                == Some(name.as_str())
                                                || row.get("params").and_then(Value::as_str)
                                                    == Some(name.as_str()))
                                        {
                                            return true;
                                        }
                                    }
                                }
                            }
                        }
                        ancestor = a.parent();
                    }
                }
            }
        }
        parent = p.parent();
    }
    false
}

struct Extractor<'a> {
    file: &'a str,
    language: &'a str,
    product: bool,
    source: &'a str,
    model: &'a mut Model,
}
impl Extractor<'_> {
    fn span(&self, node: Node<'_>) -> Span {
        Span {
            file: self.file.into(),
            language: self.language.into(),
            line: node.start_position().row + 1,
            column: node.start_position().column + 1,
        }
    }
    fn owner(&mut self, key: String, node: Node<'_>) {
        let span = self.span(node);
        self.model.owners.entry(key).or_default().push(span);
    }
    fn route(&mut self, method: &str, path: String, node: Node<'_>) {
        self.owner(
            format!("route:{}:{method} {path}", execution_domain(self.file)),
            node,
        );
        self.model.routes.push((path, self.span(node)));
    }
    fn lexical_binding<'a>(&self, name: &str, node: Node<'a>) -> Option<Node<'a>> {
        let is_scope = |n: Node<'_>| {
            matches!(
                n.kind(),
                "module"
                    | "program"
                    | "function_definition"
                    | "function_declaration"
                    | "function_expression"
                    | "arrow_function"
                    | "class_definition"
                    | "class_declaration"
            )
        };
        let mut parent = node.parent();
        while let Some(scope) = parent {
            parent = scope.parent();
            if !is_scope(scope) {
                continue;
            }
            let mut found: Option<Node<'a>> = None;
            let mut stack = vec![scope];
            while let Some(n) = stack.pop() {
                if n.start_byte() >= node.start_byte() {
                    continue;
                }
                if n.id() != scope.id() && is_scope(n) {
                    continue;
                }
                if matches!(n.kind(), "assignment" | "variable_declarator")
                    && n.end_byte() < node.start_byte()
                {
                    let lhs = n
                        .child_by_field_name("left")
                        .or_else(|| n.child_by_field_name("name"));
                    if lhs.is_some_and(|lhs| text(lhs, self.source) == name) {
                        if let Some(mut rhs) = n
                            .child_by_field_name("right")
                            .or_else(|| n.child_by_field_name("value"))
                        {
                            while rhs.kind() == "assignment" {
                                let Some(value) = rhs.child_by_field_name("right") else {
                                    break;
                                };
                                rhs = value;
                            }
                            if found.is_none_or(|old| rhs.start_byte() > old.start_byte()) {
                                found = Some(rhs);
                            }
                        }
                    }
                    // Chained assignments bind each LHS. Only that direct
                    // chain can introduce another binding in this scope;
                    // literal catalogues and embedded source are opaque here.
                    if let Some(rhs) = n
                        .child_by_field_name("right")
                        .or_else(|| n.child_by_field_name("value"))
                    {
                        if rhs.kind() == "assignment" {
                            stack.push(rhs);
                        }
                    }
                    continue;
                }
                if matches!(
                    n.kind(),
                    "call"
                        | "call_expression"
                        | "string"
                        | "string_literal"
                        | "import_statement"
                        | "import_from_statement"
                ) {
                    continue;
                }
                stack.extend(children(n));
            }
            if found.is_some() {
                return found;
            }
        }
        None
    }
    fn server_owner(&mut self, role: &str, node: Node<'_>) {
        // Separate server classes are separate runtime owners. A second
        // definition in the same host/class domain is still a duplicate.
        if role == "http-server" {
            if let Some(mut endpoint) = node
                .child_by_field_name("arguments")
                .and_then(|n| children(n).first().copied())
            {
                if endpoint.kind() == "identifier" {
                    if let Some(binding) = self.lexical_binding(text(endpoint, self.source), node) {
                        endpoint = binding;
                    }
                }
                if matches!(endpoint.kind(), "tuple" | "array")
                    && children(endpoint).iter().all(|n| is_literal(*n))
                {
                    self.owner(
                        format!(
                            "singleton:{}:{role}:{}",
                            execution_domain(self.file),
                            value(endpoint, self.source)
                        ),
                        node,
                    );
                    return;
                }
            }
        }
        let mut scope = Vec::new();
        let mut parent = node.parent();
        while let Some(p) = parent {
            if matches!(p.kind(), "class_definition" | "class_declaration") {
                if let Some(name) = p.child_by_field_name("name") {
                    scope.push(text(name, self.source));
                }
            }
            parent = p.parent();
        }
        scope.reverse();
        self.owner(
            format!(
                "singleton:{}:{}:{role}",
                execution_domain(self.file),
                scope.join("::")
            ),
            node,
        );
    }
    fn router_receiver(&self, receiver: &str, node: Node<'_>) -> bool {
        if matches!(receiver, "app" | "router") {
            return true;
        }
        self.lexical_binding(receiver, node).is_some_and(|rhs| {
            rhs.child_by_field_name("function").is_some_and(|n| {
                matches!(
                    text(n, self.source),
                    "express" | "express.Router" | "Router"
                )
            })
        })
    }
    fn route_prefix(&self, receiver: &str, node: Node<'_>) -> String {
        if let Some(args) = self
            .lexical_binding(receiver, node)
            .and_then(|rhs| rhs.child_by_field_name("arguments"))
        {
            for arg in children(args) {
                if arg.kind() == "keyword_argument"
                    && arg
                        .child_by_field_name("name")
                        .is_some_and(|n| text(n, self.source) == "prefix")
                {
                    return arg
                        .child_by_field_name("value")
                        .and_then(|n| scalar(n, self.source))
                        .unwrap_or_default();
                }
            }
        }
        String::new()
    }
    fn diag(&mut self, code: &str, node: Node<'_>, message: impl Into<String>, help: &str) {
        self.model
            .diagnostics
            .push(self.span(node).diagnostic(code, message, help));
    }
    fn registry(&mut self, name: &str, data: &Value, node: Node<'_>) {
        let upper = name.to_uppercase();
        for category in ["CONNECTIONS", "AGENTS", "STORES"] {
            if upper == category || upper.ends_with(&format!("_{category}")) {
                if let Some(rows) = data.as_object() {
                    for key in rows.keys() {
                        self.owner(
                            format!("{}:{key}", category.to_lowercase()),
                            member_node(node, key, self.source),
                        );
                    }
                }
            }
        }
        if upper.ends_with("ENGINES") {
            if let Some(map) = data.as_object() {
                for (engine, fun) in map {
                    if let Some(fun) = fun.as_str() {
                        self.model
                            .function_engines
                            .entry(format!("{}::{fun}", self.file))
                            .or_default()
                            .insert(engine.clone());
                    }
                }
            }
        }
        if retirement_registry(name) {
            self.model.retired.extend(retired_paths(data));
            return;
        }
        if upper.contains("HTTP_ROUTE_SPECS") || upper == "ROUTES" {
            if let Some(rows) = data.as_array() {
                for (index, row) in rows.iter().enumerate() {
                    let at = children(node).get(index).copied().unwrap_or(node);
                    if let Some(parts) = row.as_array() {
                        if let (Some(method), Some(path)) = (
                            parts.first().and_then(string),
                            parts.get(1).and_then(string),
                        ) {
                            self.route(&method, path, at);
                        }
                    }
                }
            }
        }
        if upper.contains("ACTIONS") {
            if let Some(map) = data.as_object() {
                for (id, handler) in map {
                    if let Some(handler) = handler
                        .as_str()
                        .or_else(|| handler.get("handler").and_then(Value::as_str))
                    {
                        self.model.actions.insert(id.clone(), handler.into());
                    }
                }
            }
        }
        if upper.contains("SETTING") && upper.contains("SPECS") {
            if let Some(map) = data.as_object() {
                for key in map.keys() {
                    self.model.settings.push((key.clone(), self.span(node)));
                }
                for key in map.keys() {
                    self.owner(
                        format!("setting:{key}"),
                        member_node(node, key, self.source),
                    );
                }
            }
        }
        if upper.contains("ITEM_ENGINES") || upper.contains("CATALOGUE") || upper == "NODES" {
            if let Some(map) = data.as_object() {
                for (key, row) in map {
                    if let Some(engine) = row.get("engine").and_then(string) {
                        let at = member_node(node, key, self.source);
                        // A named compatibility snapshot is a different value
                        // from the live catalogue. Active definitions retain
                        // their shared product identity across registries.
                        let id = if upper.starts_with("LEGACY_") {
                            format!("compatibility-node:{name}:{key}")
                        } else {
                            format!("node:{key}")
                        };
                        self.owner(id, at);
                        self.node_params(&engine, row, at);
                    }
                }
            }
            if let Some(rows) = data.as_array() {
                for (index, row) in rows.iter().enumerate() {
                    if let Some(id) = row.get("name").and_then(string) {
                        let at = children(node).get(index).copied().unwrap_or(node);
                        let owner = format!("catalogue:{id}");
                        self.owner(format!("node:{owner}"), at);
                        self.node_params(&owner, row, at);
                    }
                }
            }
        }
        if upper == "NAVIGATION_ROUTES" {
            if let Some(routes) = data.as_object() {
                self.model.navigation_routes.extend(routes.keys().cloned());
            }
        }
        if upper == "ENGINE_SOCKETS" {
            if let Some(map) = data.as_object() {
                for (engine, sides) in map {
                    if let Some(sides) = sides.as_object() {
                        for (side, names) in sides {
                            for name in strings(names) {
                                self.model.sockets.push(Socket {
                                    owner: engine.clone(),
                                    name,
                                    side: side.clone(),
                                    kind: "any".into(),
                                    span: self.span(node),
                                });
                            }
                        }
                    }
                }
            }
        }
        // Declarative product contracts are accepted in JSON or source dictionaries.
        if let Some(nodes) = data.get("nodes").and_then(Value::as_array) {
            for (index, row) in nodes.iter().enumerate() {
                if let Some(id) = row.get("id").and_then(string) {
                    let container = member_node(node, "nodes", self.source);
                    let at = children(container).get(index).copied().unwrap_or(node);
                    self.owner(format!("node:{id}"), at);
                    self.node_params(&id, row, at);
                }
            }
        }
        if let Some(rows) = data.get("routes").and_then(Value::as_array) {
            for row in rows {
                if let (Some(method), Some(path)) = (
                    row.get("method").and_then(string),
                    row.get("path").and_then(string),
                ) {
                    self.route(&method, path, node);
                }
            }
        }
        if let Some(actions) = data.get("actions") {
            if let Some(map) = actions.as_object() {
                for (id, handler) in map {
                    if let Some(handler) = handler.as_str() {
                        self.model.actions.insert(id.clone(), handler.into());
                    }
                }
            }
        }
        for category in ["connections", "agents", "stores", "settings"] {
            if let Some(rows) = data.get(category).and_then(Value::as_array) {
                for row in rows {
                    if let Some(id) = row.get("id").or_else(|| row.get("name")).and_then(string) {
                        self.owner(format!("{category}:{id}"), node);
                    }
                }
            }
        }
        if let Some(retired) = data.get("retired") {
            self.model.retired.extend(retired_paths(retired));
        }
        if let Some(wires) = data.get("wires").and_then(Value::as_array) {
            for wire in wires {
                let a = strings(&wire["from"]);
                let b = strings(&wire["to"]);
                if a.len() == 2 && b.len() == 2 {
                    self.model.wires.push(Wire {
                        source: (a[0].clone(), a[1].clone()),
                        target: (b[0].clone(), b[1].clone()),
                        span: self.span(node),
                    });
                } else {
                    self.diag(
                        "E0009",
                        node,
                        "wire has no typed endpoint pair",
                        "name the source and target node/socket pairs",
                    );
                }
            }
        }
        if let Some(buttons) = data.get("buttons").and_then(Value::as_array) {
            for button in buttons {
                self.model.buttons.push((
                    button.get("action").and_then(string).unwrap_or_default(),
                    button
                        .get("handler")
                        .and_then(string)
                        .map(|h| format!("handler:{h}"))
                        .unwrap_or_default(),
                    self.span(node),
                ));
            }
        }
    }
    fn node_params(&mut self, owner: &str, row: &Value, node: Node<'_>) {
        self.model.node_engines.insert(
            owner.into(),
            row.get("engine")
                .and_then(string)
                .unwrap_or_else(|| owner.into()),
        );
        if let Some(params) = row
            .get("params")
            .or_else(|| row.get("parameters"))
            .and_then(Value::as_object)
        {
            for (name, val) in params {
                if let Some(path) = val
                    .get("default")
                    .and_then(Value::as_str)
                    .filter(|p| matches!(language_name(p), "json" | "yaml" | "toml"))
                {
                    self.model
                        .parameter_sources
                        .push((path.into(), owner.into(), name.clone()));
                }
                let container = if row.get("params").is_some() {
                    member_node(node, "params", self.source)
                } else {
                    member_node(node, "parameters", self.source)
                };
                let at = member_node(container, name, self.source);
                let typ = datatype(
                    &val.get("type")
                        .and_then(string)
                        .unwrap_or_else(|| kind(val)),
                );
                self.model.params.push(Param {
                    owner: owner.into(),
                    name: name.clone(),
                    kind: typ,
                    span: self.span(at),
                });
            }
        }
        if let Some(sockets) = row.get("interfaces").and_then(Value::as_object) {
            for (name, val) in sockets {
                let direction = val.get("direction").and_then(Value::as_str).unwrap_or("");
                self.model.sockets.push(Socket {
                    owner: owner.into(),
                    name: name.clone(),
                    side: if direction == "output" {
                        "source"
                    } else {
                        "target"
                    }
                    .into(),
                    kind: val
                        .get("type")
                        .and_then(string)
                        .unwrap_or_else(|| "any".into()),
                    span: self.span(node),
                });
            }
        }
        if let Some(sockets) = row.get("sockets").and_then(Value::as_object) {
            for (name, val) in sockets {
                let typ = val
                    .as_str()
                    .map(str::to_string)
                    .or_else(|| val.get("type").and_then(string))
                    .unwrap_or_else(|| "any".into());
                let side = val
                    .get("side")
                    .and_then(string)
                    .unwrap_or_else(|| "target".into());
                self.model.sockets.push(Socket {
                    owner: owner.into(),
                    name: name.clone(),
                    side,
                    kind: typ,
                    span: self.span(node),
                });
            }
        }
    }
    fn walk(&mut self, node: Node<'_>) {
        let k = node.kind();
        if k.contains("comment") {
            return;
        }
        if node.is_error() || node.is_missing() {
            self.diag(
                "E0011",
                node,
                "source contains a syntax error or missing token",
                "fix syntax before product-model analysis",
            );
            return;
        }
        if !self.product {
            if node.has_error() {
                for child in children(node) {
                    self.walk(child);
                }
            }
            return;
        }
        self.language_rules(node);
        if self.language == "html" && k == "attribute" {
            let parts = children(node);
            let name = parts
                .first()
                .map(|n| text(*n, self.source).to_lowercase())
                .unwrap_or_default();
            let content = text(node, self.source).to_lowercase();
            if name.starts_with("on") || content.contains("javascript:") || name == "srcdoc" {
                self.diag("E0010", node, "executable HTML attribute has no safe static expansion", "move executable content into a checked JavaScript source; inline handlers and nested srcdoc are refused");
            }
        }
        if matches!(k, "call" | "call_expression" | "new_expression") {
            let callee = node
                .child_by_field_name("function")
                .or_else(|| node.child_by_field_name("constructor"));
            if callee.is_some_and(|n| {
                matches!(
                    text(n, self.source),
                    "exec"
                        | "eval"
                        | "Function"
                        | "builtins.exec"
                        | "builtins.eval"
                        | "globalThis.eval"
                )
            }) {
                self.diag(
                    "E0010",
                    node,
                    "dynamic code execution cannot be statically admitted",
                    "replace dynamic execution with checked source and a registered action",
                );
            }
        }
        if matches!(k, "dictionary" | "object") {
            let mut keys = BTreeSet::new();
            for pair in children(node) {
                if let Some(key) = pair
                    .child_by_field_name("key")
                    .and_then(|n| scalar(n, self.source))
                {
                    if !keys.insert(key.clone()) {
                        self.diag(
                            "E0001",
                            pair,
                            format!("duplicate object key `{key}`"),
                            "keep one owner of this key",
                        );
                    }
                }
            }
        }
        if matches!(
            k,
            "assignment"
                | "variable_declarator"
                | "assignment_expression"
                | "const_item"
                | "static_item"
                | "variable_assignment"
                | "assignment_statement"
        ) {
            let lhs = node
                .child_by_field_name("left")
                .or_else(|| node.child_by_field_name("name"));
            let rhs = node
                .child_by_field_name("right")
                .or_else(|| node.child_by_field_name("value"));
            if let (Some(lhs), Some(rhs)) = (lhs, rhs) {
                let name = text(lhs, self.source).trim();
                if lhs.kind() == "subscript" {
                    if let (Some(registry), Some(key)) = (
                        lhs.child_by_field_name("value"),
                        lhs.child_by_field_name("subscript")
                            .and_then(|n| scalar(n, self.source)),
                    ) {
                        let mut entry = serde_json::Map::new();
                        entry.insert(key, value(rhs, self.source));
                        self.registry(text(registry, self.source), &Value::Object(entry), rhs);
                    }
                } else {
                    self.registry(name, &value(rhs, self.source), rhs);
                }
                if rhs.kind() == "arrow_function"
                    && name.chars().next().is_some_and(char::is_uppercase)
                {
                    if let Some(body) = rhs.child_by_field_name("body") {
                        self.component(body);
                    }
                }
                if behaviour(name) && is_literal(rhs) && !in_param(node, self.source) {
                    self.diag(
                        "E0007",
                        rhs,
                        format!("behaviour `{name}` is hard-coded outside a node parameter"),
                        "declare a typed node parameter with a socket and read it here",
                    );
                }
            }
        }
        if k == "pair" {
            if let (Some(key), Some(val)) = (
                node.child_by_field_name("key"),
                node.child_by_field_name("value"),
            ) {
                if let Some(name) = scalar(key, self.source) {
                    let workspace_reference = self.language == "json" && self.file == ".vscode/settings.json"
                        && name == "python.defaultInterpreterPath"
                        && scalar(val, self.source).is_some_and(|value| value.starts_with("${workspaceFolder}/"));
                    if behaviour(&name) && is_literal(val) && !in_param(node, self.source) && !workspace_reference
                        && !(name == "route" && scalar(val, self.source).is_some_and(|v| self.model.navigation_routes.contains(&v))) {
                        self.diag(
                            "E0007",
                            val,
                            format!("behaviour `{name}` is hard-coded outside a node parameter"),
                            "move the value into the owning node's typed parameters",
                        );
                    }
                }
            }
        }
        if matches!(k, "call" | "call_expression" | "invocation_expression") {
            self.call(node);
        }
        if matches!(
            k,
            "function_definition"
                | "function_declaration"
                | "method_declaration"
                | "class_definition"
                | "class_declaration"
        ) {
            self.definition(node);
        }
        if matches!(k, "except_clause" | "catch_clause") {
            let body = node.child_by_field_name("body").or_else(|| {
                children(node)
                    .into_iter()
                    .find(|n| matches!(n.kind(), "block" | "statement_block"))
            });
            if let Some(body) = body {
                let statements: Vec<_> = children(body)
                    .into_iter()
                    .filter(|n| !n.kind().contains("comment"))
                    .collect();
                if statements.is_empty()
                    || statements.iter().all(|n| {
                        n.kind() == "pass_statement"
                            || matches!(
                                text(*n, self.source).trim(),
                                "return None" | "return null;" | "return;"
                            )
                    })
                {
                    self.diag(
                        "E0004",
                        node,
                        "exception is silently discarded",
                        "return a typed failure and expose an actionable error to the caller",
                    );
                }
            }
        }
        if matches!(k, "string" | "string_literal" | "template_string") {
            if let Some(s) = scalar(node, self.source) {
                let lower = s.to_lowercase();
                let runtime = self.file.starts_with("nodelang/")
                    || self.file.ends_with(".jsx")
                    || self.file.ends_with(".tsx");
                let docstring = node.parent().is_some_and(|p| {
                    p.kind() == "expression_statement"
                        && p.parent().is_some_and(|b| {
                            matches!(b.kind(), "block" | "module")
                                && children(b).first().is_some_and(|n| n.id() == p.id())
                        })
                });
                if runtime
                    && !docstring
                    && ["not available yet", "coming soon", "placeholder"]
                        .iter()
                        .any(|p| {
                            lower.match_indices(p).any(|(start, matched)| {
                                let boundary = |c: char| !c.is_alphanumeric() && c != '_';
                                lower[..start].chars().next_back().is_none_or(boundary)
                                    && lower[start + matched.len()..]
                                        .chars()
                                        .next()
                                        .is_none_or(boundary)
                            })
                        })
                {
                    self.diag(
                        "E0003",
                        node,
                        "placeholder reaches runtime source",
                        "implement loaded, empty, error, and waiting states with a real action",
                    );
                }
                let mut p = node.parent();
                let mut declaration = false;
                while let Some(n) = p {
                    if n.kind() == "decorator" {
                        declaration = true;
                        break;
                    }
                    if n.kind() == "pair" {
                        if let Some(key) = n
                            .child_by_field_name("key")
                            .and_then(|k| scalar(k, self.source))
                        {
                            if key == "retired" || key == "replaced" {
                                declaration = true;
                                break;
                            }
                        }
                    }
                    if matches!(n.kind(), "assignment" | "variable_declarator") {
                        if let Some(lhs) = n
                            .child_by_field_name("left")
                            .or_else(|| n.child_by_field_name("name"))
                        {
                            let name = text(lhs, self.source).to_uppercase();
                            declaration = name == "ROUTES"
                                || retirement_registry(&name)
                                || name.contains("HTTP_ROUTE_SPECS");
                        }
                        break;
                    }
                    p = n.parent();
                }
                if !declaration {
                    self.model.uses.push((s, self.span(node)));
                }
            }
            return; // Strings are opaque: source inside a string is never executed by the checker.
        }
        if k == "jsx_opening_element" || k == "jsx_self_closing_element" {
            self.jsx_control(node);
        }
        if k == "subscript" {
            if let Some(idx) = node.child_by_field_name("subscript") {
                if let Some(s) = scalar(idx, self.source) {
                    let receiver = node
                        .child_by_field_name("value")
                        .map(|n| text(n, self.source))
                        .unwrap_or("");
                    if matches!(receiver, "params" | "parameters" | "feeds" | "config") {
                        self.reader(s, node);
                    }
                }
            }
        }
        if matches!(k, "import_statement" | "import_from_statement") {
            self.imports(node);
        }
        for child in children(node) {
            self.walk(child);
        }
    }
    fn imports(&mut self, node: Node<'_>) {
        if node.kind() == "import_from_statement" {
            let module = node
                .child_by_field_name("module_name")
                .map(|n| text(n, self.source))
                .unwrap_or("");
            let path = if module.starts_with('.') {
                let parent = self.file.rsplit_once('/').map(|p| p.0).unwrap_or("");
                format!(
                    "{parent}/{}.py",
                    module.trim_start_matches('.').replace('.', "/")
                )
            } else {
                format!("{}.py", module.replace('.', "/"))
            };
            for child in children(node)
                .into_iter()
                .filter(|n| n.kind() == "aliased_import")
            {
                if let (Some(name), Some(alias)) = (
                    child.child_by_field_name("name"),
                    child.child_by_field_name("alias"),
                ) {
                    self.model.aliases.insert(
                        format!("{}::{}", self.file, text(alias, self.source)),
                        format!("{path}::{}", text(name, self.source)),
                    );
                }
            }
        }
        let mut stack = vec![node];
        while let Some(n) = stack.pop() {
            if matches!(n.kind(), "dotted_name" | "identifier" | "string") {
                let s = scalar(n, self.source).unwrap_or_else(|| text(n, self.source).into());
                self.model
                    .imports
                    .entry(self.file.into())
                    .or_default()
                    .insert(s);
            } else {
                stack.extend(children(n));
            }
        }
    }
    fn call(&mut self, node: Node<'_>) {
        let fun = node
            .child_by_field_name("function")
            .or_else(|| node.child_by_field_name("expression"));
        let args = node
            .child_by_field_name("arguments")
            .map(children)
            .unwrap_or_default();
        let name = fun.map(|n| text(n, self.source)).unwrap_or("");
        let function = self.function_name(node);
        if !name.contains('.') && !function.is_empty() {
            self.model
                .calls
                .entry(function)
                .or_default()
                .insert(format!("{}::{name}", self.file));
        }
        if ["params.get", "parameters.get", "feeds.get", "config.get"].contains(&name)
            || name.ends_with("coerce_parameter")
            || name.ends_with("_text")
            || name.ends_with("_number")
        {
            let index = if name.ends_with(".get") { 0 } else { 1 };
            if let Some(s) = args.get(index).and_then(|n| scalar(*n, self.source)) {
                self.reader(s, node);
            }
        }
        if name.ends_with(".update") {
            if let Some(arg) = args.first() {
                self.registry(
                    name.trim_end_matches(".update"),
                    &value(*arg, self.source),
                    *arg,
                );
            }
        }
        let decorated = node.parent().is_some_and(|p| p.kind() == "decorator");
        let (receiver, member) = name.rsplit_once('.').unwrap_or(("", name));
        let route_method = name.ends_with(".route")
            || [".get", ".post", ".put", ".delete", ".patch"]
                .iter()
                .any(|m| name.ends_with(m));
        let route_path = args
            .first()
            .and_then(|n| scalar(*n, self.source))
            .filter(|s| s.starts_with('/'));
        // Resolve receiver provenance only for a possible route declaration,
        // never for unrelated calls across a large JS/TS module.
        let registration = route_method
            && route_path.is_some()
            && (decorated
                || (matches!(self.language, "javascript" | "typescript")
                    && args.len() >= 2
                    && self.router_receiver(receiver, node)));
        if registration {
            if let Some(path) = route_path {
                let method = member.to_uppercase();
                let path = format!("{}{path}", self.route_prefix(receiver, node));
                self.route(&method, path, node);
            }
        }
        if [
            "HTTPServer",
            "ThreadingHTTPServer",
            "uvicorn.run",
            "web.run_app",
        ]
        .iter()
        .any(|s| name.ends_with(s))
        {
            self.server_owner("http-server", node);
        }
        let timing_index = match name.rsplit('.').next().unwrap_or("") {
            "setTimeout" | "setInterval" | "wait_for" => Some(1),
            "sleep" | "settimeout" => Some(0),
            _ => None,
        };
        if let Some(value) = timing_index
            .and_then(|i| args.get(i))
            .filter(|n| is_literal(**n))
        {
            self.diag(
                "E0007",
                *value,
                "execution timing is a positional literal",
                "read the timeout or cadence from its typed node parameter",
            );
        }
        // Literal defaults on a behaviour-shaping keyword argument are configuration too.
        for arg in &args {
            if arg.kind() == "keyword_argument" {
                if let (Some(key), Some(val)) = (
                    arg.child_by_field_name("name"),
                    arg.child_by_field_name("value"),
                ) {
                    let enum_default = name.ends_with(".add_argument")
                        && text(key, self.source) == "default"
                        && args.iter().any(|argument| {
                            argument.child_by_field_name("name").is_some_and(|key| text(key, self.source) == "choices")
                                && argument.child_by_field_name("value").is_some_and(|choices| {
                                    strings(&value(choices, self.source)).contains(&scalar(val, self.source).unwrap_or_default())
                                })
                        });
                    if behaviour(text(key, self.source))
                        && !enum_default
                        && is_literal(val)
                        && !in_param(node, self.source)
                    {
                        self.diag(
                            "E0007",
                            val,
                            format!("literal behaviour argument `{}`", text(key, self.source)),
                            "read a typed node parameter instead of an inline default",
                        );
                    }
                }
            }
        }
    }
    fn reader(&mut self, name: String, node: Node<'_>) {
        let function = self.function_name(node);
        self.model.readers.push(Reader { name, function });
    }
    fn function_name(&self, node: Node<'_>) -> String {
        let mut parent = Some(node);
        let mut function = String::new();
        while let Some(n) = parent {
            if matches!(
                n.kind(),
                "function_definition" | "function_declaration" | "method_declaration"
            ) {
                function = n
                    .child_by_field_name("name")
                    .map(|n| text(n, self.source).into())
                    .unwrap_or_default();
                break;
            }
            parent = n.parent();
        }
        format!("{}::{function}", self.file)
    }
    fn language_rules(&mut self, node: Node<'_>) {
        // Per-language syntax adapters: all supported languages have executable
        // semantic checks, not just a successfully loaded parser.
        let k = node.kind();
        let named = children(node);
        if self.language == "python"
            && matches!(
                k,
                "dictionary_comprehension"
                    | "list_comprehension"
                    | "generator_expression"
                    | "set_comprehension"
            )
        {
            if let Some(clause) = named.iter().find(|n| n.kind() == "for_in_clause") {
                if let (Some(key), Some(values)) = (
                    clause.child_by_field_name("left"),
                    clause.child_by_field_name("right"),
                ) {
                    if key.kind() == "identifier" {
                        let mut stack = node
                            .child_by_field_name("body")
                            .into_iter()
                            .collect::<Vec<_>>();
                        while let Some(part) = stack.pop() {
                            if part.kind() == "call" {
                                if let (Some(fun), Some(arguments)) = (
                                    part.child_by_field_name("function"),
                                    part.child_by_field_name("arguments"),
                                ) {
                                    let name = text(fun, self.source);
                                    let args = children(arguments);
                                    let index = if [
                                        "params.get",
                                        "parameters.get",
                                        "feeds.get",
                                        "config.get",
                                    ]
                                    .contains(&name)
                                    {
                                        Some(0)
                                    } else if name.ends_with("_number")
                                        || name.ends_with("_text")
                                        || name.ends_with("coerce_parameter")
                                    {
                                        Some(1)
                                    } else {
                                        None
                                    };
                                    if index.and_then(|i| args.get(i)).is_some_and(|n| {
                                        text(*n, self.source) == text(key, self.source)
                                    }) {
                                        for name in strings(&value(values, self.source)) {
                                            self.reader(name, part);
                                        }
                                    }
                                }
                            }
                            if part.kind() == "subscript" {
                                let receiver = part
                                    .child_by_field_name("value")
                                    .map(|n| text(n, self.source))
                                    .unwrap_or("");
                                let index = part
                                    .child_by_field_name("subscript")
                                    .map(|n| text(n, self.source))
                                    .unwrap_or("");
                                if ["params", "parameters", "feeds", "config"].contains(&receiver)
                                    && index == text(key, self.source)
                                {
                                    for name in strings(&value(values, self.source)) {
                                        self.reader(name, part);
                                    }
                                }
                            }
                            stack.extend(children(part));
                        }
                    }
                }
            }
        }
        let mut binding: Option<(String, Node<'_>)> = None;
        match self.language {
            "csharp" if k == "variable_declarator" => {
                if let (Some(name), Some(val)) = (node.child_by_field_name("name"), named.last()) {
                    if name.id() != val.id() {
                        binding = Some((text(name, self.source).into(), *val));
                    }
                }
            }
            "powershell" if k == "assignment_expression" => {
                if let (Some(name), Some(val)) = (named.first(), node.child_by_field_name("value"))
                {
                    binding = Some((text(*name, self.source).trim_start_matches('$').into(), val));
                }
            }
            "cmd" if k == "variable_assignment" => {
                // Batch represents NAME=value as an assignment literal. Splitting
                // this parser-delimited literal does not treat comments as code.
                let raw = text(node, self.source).trim();
                if let Some((name, val)) = raw.split_once('=') {
                    let name = name
                        .trim_start_matches('@')
                        .trim_start_matches("set ")
                        .trim_start_matches("SET ")
                        .trim_matches('"');
                    if behaviour(name) && !val.contains('%') && !val.contains('!') {
                        self.diag(
                            "E0007",
                            node,
                            format!("behaviour `{name}` is hard-coded outside a node parameter"),
                            "read the owning node parameter through the script input contract",
                        );
                    }
                }
            }
            "rust" if k == "let_declaration" => {
                if let (Some(name), Some(val)) = (
                    node.child_by_field_name("pattern"),
                    node.child_by_field_name("value"),
                ) {
                    binding = Some((text(name, self.source).into(), val));
                }
            }
            "bash" if k == "variable_assignment" => {
                if let (Some(name), Some(val)) = (
                    node.child_by_field_name("name"),
                    node.child_by_field_name("value"),
                ) {
                    binding = Some((text(name, self.source).into(), val));
                }
            }
            "yaml" if k == "block_mapping_pair" => {
                if let (Some(name), Some(val)) = (
                    node.child_by_field_name("key"),
                    node.child_by_field_name("value"),
                ) {
                    binding = Some((text(name, self.source).into(), val));
                }
            }
            "toml" if k == "pair" => {
                if let (Some(name), Some(val)) = (named.first(), named.last()) {
                    binding = Some((text(*name, self.source).into(), *val));
                }
            }
            "css" if k == "declaration" => {
                if let (Some(name), Some(val)) = (named.first(), named.get(1)) {
                    binding = Some((
                        text(*name, self.source).trim_start_matches('-').into(),
                        *val,
                    ));
                }
            }
            "html" if k == "attribute" => {
                if let (Some(name), Some(val)) = (named.first(), named.get(1)) {
                    binding = Some((
                        text(*name, self.source).trim_start_matches("data-").into(),
                        *val,
                    ));
                }
            }
            "sql" if k == "column_definition" => {
                if let Some(name) = named.first() {
                    if named.iter().any(|n| n.kind() == "keyword_default") {
                        if let Some(val) = named.last() {
                            binding = Some((text(*name, self.source).into(), *val));
                        }
                    }
                }
            }
            _ => {}
        }
        if let Some((name, val)) = binding {
            let raw = text(val, self.source).trim().trim_end_matches(';');
            let literal = raw.parse::<f64>().is_ok()
                || raw.starts_with(['\'', '"'])
                || matches!(raw, "true" | "false" | "$true" | "$false")
                || (self.language == "css"
                    && raw
                        .chars()
                        .all(|c| c.is_ascii_digit() || ".ms px".contains(c)));
            if behaviour(&name) && literal && !in_param(node, self.source) {
                self.diag(
                    "E0007",
                    val,
                    format!("behaviour `{name}` is hard-coded outside a node parameter"),
                    "declare a typed node parameter and bind this language's input adapter to it",
                );
            }
        }
    }
    fn definition(&mut self, node: Node<'_>) {
        let name = node
            .child_by_field_name("name")
            .map(|n| text(n, self.source))
            .unwrap_or("");
        let lower = name.to_lowercase();
        if node.kind().starts_with("class") {
            if lower.contains("revit") && (lower.contains("adapter") || lower.contains("bridge")) {
                self.owner("singleton:revit-adapter".into(), node);
            }
            if lower.ends_with("store") {
                self.owner(format!("store:{name}"), node);
            }
            if let Some(bases) = node.child_by_field_name("superclasses") {
                if text(bases, self.source).contains("BaseHTTPRequestHandler") {
                    self.server_owner("http-handler", node);
                }
            }
        }
        let body = node.child_by_field_name("body");
        if let Some(body) = body {
            if self.language == "python" && node.kind() == "function_definition" {
                let mut env = BTreeMap::new();
                for statement in children(body) {
                    let inner = if statement.kind() == "expression_statement" {
                        children(statement).first().copied().unwrap_or(statement)
                    } else {
                        statement
                    };
                    if inner.kind() == "assignment" {
                        if let (Some(key), Some(val)) = (
                            inner.child_by_field_name("left"),
                            inner.child_by_field_name("right"),
                        ) {
                            env.insert(
                                text(key, self.source).into(),
                                evaluated(val, self.source, &env),
                            );
                        }
                    }
                    if inner.kind() == "call" {
                        if let Some(fun) = inner.child_by_field_name("function") {
                            let raw = text(fun, self.source);
                            if let Some(name) = raw.strip_suffix(".update") {
                                if let Some(arg) = inner
                                    .child_by_field_name("arguments")
                                    .and_then(|n| children(n).first().copied())
                                {
                                    let incoming = evaluated(arg, self.source, &env);
                                    if let (Some(current), Some(incoming)) = (
                                        env.get_mut(name).and_then(Value::as_object_mut),
                                        incoming.as_object(),
                                    ) {
                                        current.extend(incoming.clone());
                                    }
                                }
                            }
                        }
                    }
                    if statement.kind() == "return_statement" {
                        if let Some(returned) = children(statement).first() {
                            let row = evaluated(*returned, self.source, &env);
                            if row.get("parameters").is_none() && row.get("interfaces").is_none() {
                                continue;
                            }
                            if let (Some(id), Some(_)) =
                                (row.get("name").and_then(string), row.get("engine"))
                            {
                                let owner = format!("catalogue:{id}");
                                self.owner(format!("node:{owner}"), *returned);
                                self.node_params(&owner, &row, *returned);
                                if !row["parameters"].is_object() || !row["interfaces"].is_object()
                                {
                                    self.diag("E0010",*returned,"catalogue builder has an unresolved parameter or interface expression","use supported literal catalogue constructors or add a symbolic extractor");
                                }
                            }
                        }
                    }
                }
            }
            if name.chars().next().is_some_and(char::is_uppercase)
                && matches!(self.language, "javascript" | "typescript")
            {
                self.component(body);
            }
        }
    }
    fn component(&mut self, body: Node<'_>) {
        let body_text = text(body, self.source);
        if !body_text.contains("fetch(") && !body_text.contains("useEffect(") {
            return;
        }
        // Unknown effects still require request states, including calls through
        // helpers. Exempt only a locally proven, synchronous confirmation timer.
        let mut pending = vec![body];
        let mut setters = BTreeSet::new();
        let mut effects = vec![];
        while let Some(node) = pending.pop() {
            if node.kind() == "variable_declarator" {
                if let (Some(name), Some(value)) = (node.child_by_field_name("name"), node.child_by_field_name("value")) {
                    if name.kind() == "array_pattern" && value.kind() == "call_expression" {
                        if let Some(function) = value.child_by_field_name("function") {
                            if matches!(text(function, self.source), "useState" | "React.useState") {
                                if let Some(setter) = children(name).get(1) {
                                    setters.insert(text(*setter, self.source).to_string());
                                }
                            }
                        }
                    }
                }
            }
            if node.kind() == "call_expression" {
                if let Some(function) = node.child_by_field_name("function") {
                    if matches!(text(function, self.source), "useEffect" | "React.useEffect") {
                        effects.push(node);
                    }
                }
            }
            pending.extend(children(node));
        }
        let timers_only = !effects.is_empty() && effects.iter().all(|effect| {
            let Some(arguments) = effect.child_by_field_name("arguments") else { return false; };
            let Some(callback) = children(arguments).first().copied() else { return false; };
            let mut pending = vec![callback];
            let (mut timer, mut cleanup) = (false, false);
            while let Some(node) = pending.pop() {
                if node.kind() == "await_expression" || text(node, self.source).trim_start().starts_with("async ") {
                    return false;
                }
                if node.kind() == "call_expression" {
                    let Some(function) = node.child_by_field_name("function") else { return false; };
                    match text(function, self.source) {
                        "setTimeout" => {
                            let Some(arguments) = node.child_by_field_name("arguments") else { return false; };
                            let Some(handler) = children(arguments).first().copied() else { return false; };
                            if !matches!(handler.kind(), "arrow_function" | "function_expression") { return false; }
                            timer = true;
                        }
                        "clearTimeout" => cleanup = true,
                        name if setters.contains(name) => {},
                        _ => return false,
                    }
                }
                pending.extend(children(node));
            }
            timer && cleanup
        });
        if !body_text.contains("fetch(") && timers_only {
            return;
        }
        let mut states: BTreeMap<String, BTreeSet<String>> = BTreeMap::new();
        let mut actionable_error = false;
        let mut stack = vec![body];
        while let Some(n) = stack.pop() {
            if matches!(
                n.kind(),
                "if_statement" | "ternary_expression" | "binary_expression"
            ) {
                if let Some(condition) = n
                    .child_by_field_name("condition")
                    .or_else(|| n.child_by_field_name("left"))
                {
                    let shown = n
                        .child_by_field_name("consequence")
                        .or_else(|| n.child_by_field_name("right"))
                        .map(|node| text(node, self.source))
                        .unwrap_or("");
                    if shown.contains('<') {
                        let mut predicates = vec![condition];
                        while let Some(predicate) = predicates.pop() {
                            if predicate.kind() == "binary_expression" {
                                if let (Some(left), Some(right)) = (
                                    predicate.child_by_field_name("left"),
                                    predicate.child_by_field_name("right"),
                                ) {
                                    let operator = self
                                        .source
                                        .get(left.end_byte()..right.start_byte())
                                        .unwrap_or("")
                                        .trim();
                                    if !["==", "==="].contains(&operator) {
                                        continue;
                                    }
                                    if let Some(state) = scalar(right, self.source).filter(|s| {
                                        ["loaded", "empty", "error", "waiting"]
                                            .contains(&s.as_str())
                                    }) {
                                        let owner = text(left, self.source);
                                        if matches!(left.kind(), "member_expression" | "identifier")
                                        {
                                            states
                                                .entry(owner.into())
                                                .or_default()
                                                .insert(state.clone());
                                            if state == "error"
                                                && [
                                                    "<button", "<Btn", "<Button", "onRetry=",
                                                    "retry={",
                                                ]
                                                .iter()
                                                .any(|p| shown.contains(p))
                                            {
                                                actionable_error = true;
                                            }
                                        }
                                    }
                                }
                            }
                            predicates.extend(children(predicate));
                        }
                    }
                }
            }
            stack.extend(children(n));
        }
        let best = states.values().max_by_key(|s| s.len());
        let missing: Vec<_> = ["loaded", "empty", "error", "waiting"]
            .into_iter()
            .filter(|s| best.is_none_or(|set| !set.contains(*s)))
            .collect();
        if !missing.is_empty() {
            self.diag(
                "E0003",
                body,
                format!(
                    "async component has no rendered {} state",
                    missing.join(", ")
                ),
                "render a branch for each request state; a variable or comment is insufficient",
            );
        }
        if !actionable_error {
            self.diag(
                "E0004",
                body,
                "user action has no actionable failure UI",
                "render the rejected result with a retry action",
            );
        }
    }
    fn jsx_control(&mut self, node: Node<'_>) {
        let name = node
            .child_by_field_name("name")
            .map(|n| text(n, self.source))
            .unwrap_or("");
        if !matches!(name, "button" | "Btn" | "Button") {
            return;
        }
        let mut action = children(node).into_iter().find_map(|attr| {
            let parts = children(attr);
            parts.first().filter(|n| matches!(text(**n, self.source), "action" | "actionId" | "data-action"))
                .and_then(|_| parts.get(1).and_then(|n| scalar(*n, self.source)))
        });
        let mut callback = String::new();
        let submit = children(node).into_iter().any(|attr| {
            let parts = children(attr);
            parts.first().is_some_and(|n| text(*n, self.source) == "type")
                && parts.get(1).and_then(|n| scalar(*n, self.source)).as_deref() == Some("submit")
        });
        let mut binding = node;
        if submit {
            let mut parent = node.parent();
            while let Some(element) = parent {
                if element.kind() == "jsx_element" {
                    if let Some(open) = children(element).into_iter().find(|n| n.kind() == "jsx_opening_element") {
                        let tag = open.child_by_field_name("name").map(|n| text(n, self.source)).unwrap_or("");
                        let composer_form = tag == "D.Composer" && children(open).into_iter().any(|attr| {
                            let parts = children(attr);
                            parts.first().is_some_and(|n| text(*n, self.source) == "as")
                                && parts.get(1).and_then(|n| scalar(*n, self.source)).as_deref() == Some("form")
                        });
                        if tag == "form" || composer_form {
                            binding = open;
                            break;
                        }
                    }
                }
                parent = element.parent();
            }
        }
        for attr in children(binding)
            .into_iter()
            .filter(|n| n.kind() == "jsx_attribute")
        {
            let parts = children(attr);
            let key = parts.first().map(|n| text(*n, self.source)).unwrap_or("");
            if matches!(key, "action" | "actionId" | "data-action") {
                action = parts.get(1).and_then(|n| scalar(*n, self.source));
            }
            if key == "onClick" || (submit && key == "onSubmit") {
                if let Some(expression) = parts.get(1) {
                    let expression = children(*expression)
                        .first()
                        .copied()
                        .unwrap_or(*expression);
                    let root =
                        if matches!(expression.kind(), "arrow_function" | "function_expression") {
                            expression.child_by_field_name("body").unwrap_or(expression)
                        } else {
                            expression
                        };
                    if root.kind() == "identifier"
                        && !locally_shadowed(root, text(root, self.source), self.source)
                    {
                        callback = format!("handler:{}", text(root, self.source));
                    }
                    let mut stack = vec![root];
                    while let Some(n) = stack.pop() {
                        if matches!(
                            n.kind(),
                            "arrow_function"
                                | "function_expression"
                                | "function_declaration"
                                | "class"
                        ) {
                            continue;
                        }
                        if n.kind() == "call_expression" {
                            if let Some(fun) = n.child_by_field_name("function") {
                                let name = text(fun, self.source);
                                if locally_shadowed(fun, name, self.source) {
                                    continue;
                                }
                                if ["dispatch", "runAction", "executeAction"].contains(&name) {
                                    if let Some(id) = n
                                        .child_by_field_name("arguments")
                                        .and_then(|n| children(n).first().copied())
                                        .and_then(|n| scalar(n, self.source))
                                    {
                                        callback = format!("id:{id}");
                                        break;
                                    }
                                } else {
                                    callback = format!("handler:{name}");
                                }
                            }
                        }
                        stack.extend(children(n));
                    }
                }
            }
        }
        self.model
            .buttons
            .push((action.unwrap_or_default(), callback, self.span(node)));
    }
}


fn finish(mut model: Model, files: Vec<SourceFile>) -> Report {
    for (alias, target) in &model.aliases {
        if let Some(engines) = model.function_engines.get(alias).cloned() {
            model
                .function_engines
                .entry(target.clone())
                .or_default()
                .extend(engines);
        }
    }
    // A helper reading a parameter is a reader only when a registered engine
    // actually calls that helper. A same-named key in another engine is not proof.
    loop {
        let mut additions = vec![];
        for (caller, callees) in &model.calls {
            if let Some(engines) = model.function_engines.get(caller) {
                for callee in callees {
                    additions.push((callee.clone(), engines.clone()));
                }
            }
        }
        let before: usize = model.function_engines.values().map(BTreeSet::len).sum();
        for (callee, engines) in additions {
            model
                .function_engines
                .entry(callee)
                .or_default()
                .extend(engines);
        }
        let after: usize = model.function_engines.values().map(BTreeSet::len).sum();
        if before == after {
            break;
        }
    }
    for (owner, spans) in &model.owners {
        if spans.len() > 1 {
            for span in spans {
                let other = spans
                    .iter()
                    .find(|p| p.file != span.file || p.line != span.line)
                    .unwrap_or(&spans[0]);
                model.diagnostics.push(span.diagnostic(
                    "E0001",
                    format!(
                        "multiple owners of `{owner}` (other: {}:{})",
                        other.file, other.line
                    ),
                    "merge the definitions into one owner and remove the replaced path",
                ));
            }
        }
    }
    for param in &model.params {
        let engine = model.node_engines.get(&param.owner).unwrap_or(&param.owner);
        if !model.readers.iter().any(|r| {
            r.name == param.name
                && model
                    .function_engines
                    .get(&r.function)
                    .is_some_and(|engines| engines.contains(engine))
        }) {
            model.diagnostics.push(param.span.diagnostic(
                "E0002",
                format!(
                    "parameter `{}.{}` has no runtime reader",
                    param.owner, param.name
                ),
                "bind a runtime reader or remove the parameter",
            ));
        }
        let socket = model
            .sockets
            .iter()
            .find(|s| s.owner == param.owner && s.name == param.name && s.side == "target");
        if let Some(socket) = socket {
            if socket.kind != "any" && param.kind != "any" && socket.kind != param.kind {
                model.diagnostics.push(socket.span.diagnostic(
                    "E0009",
                    format!(
                        "parameter `{}` is {}, socket is {}",
                        param.name, param.kind, socket.kind
                    ),
                    "give the parameter and socket the same type",
                ));
            }
        } else {
            model.diagnostics.push(param.span.diagnostic(
                "E0008",
                format!(
                    "parameter `{}.{}` has no input socket",
                    param.owner, param.name
                ),
                "expose a typed target socket with this parameter's name",
            ));
        }
    }
    for (name, span) in &model.settings {
        if !model.params.iter().any(|p| p.name == *name) {
            model.diagnostics.push(span.diagnostic(
                "E0005",
                format!("setting `{name}` has no real node parameter"),
                "bind the Settings row to the catalogue parameter",
            ));
        }
    }
    for (action, callback, span) in &model.buttons {
        let registered = if action.is_empty() {
            model.actions.iter().any(|(id, handler)| {
                callback == &format!("id:{id}") || callback == &format!("handler:{handler}")
            })
        } else {
            model.actions.get(action).is_some_and(|handler| {
                callback == &format!("id:{action}") || callback == &format!("handler:{handler}")
            })
        };
        if !registered {
            model.diagnostics.push(span.diagnostic(
                "E0005",
                format!("button action `{action}` has no matching registered callback"),
                "bind onClick to the registered action handler; an actionId attribute alone does not execute anything",
            ));
        }
    }
    for wire in &model.wires {
        let a = model.sockets.iter().find(|s| {
            (&s.owner, &s.name) == (&wire.source.0, &wire.source.1) && s.side == "source"
        });
        let b = model.sockets.iter().find(|s| {
            (&s.owner, &s.name) == (&wire.target.0, &wire.target.1) && s.side == "target"
        });
        if a.is_none()
            || b.is_none()
            || a.zip(b)
                .is_some_and(|(a, b)| a.kind != b.kind && a.kind != "any" && b.kind != "any")
        {
            model.diagnostics.push(wire.span.diagnostic(
                "E0009",
                "wire endpoints are missing or have incompatible types",
                "wire an existing output to an input of the same type",
            ));
        }
    }
    for (path, span) in &model.uses {
        if model
            .retired
            .iter()
            .any(|r| r == path || r.split_once(' ').is_some_and(|(_, p)| p == path))
        {
            model.diagnostics.push(span.diagnostic(
                "E0006",
                format!("replaced path `{path}` remains reachable"),
                "remove this reference and use the replacement owner",
            ));
        }
    }
    for (route, span) in &model.routes {
        if !model
            .uses
            .iter()
            .any(|(s, _)| s == route || s.ends_with(route))
        {
            model.diagnostics.push(span.diagnostic(
                "E0002",
                format!("route `{route}` has no caller or dispatcher"),
                "bind its user action/dispatcher or remove the route",
            ));
        }
    }
    // Module reachability starts at shipped launchers, never at tests.
    let mut reachable: BTreeSet<String> = model
        .modules
        .keys()
        .filter(|p| {
            model.entrypoints.contains(*p) || matches!(
                p.as_str(),
                "nodelang/launcher.py"
                    | "colleague_setup.py"
                    | "nodelang/desktop.py"
                    | "nodelang/clean_coordination_service.py"
                    | "cloud_backend/main.py"
            )
        })
        .cloned()
        .collect();
    loop {
        let mut added = vec![];
        for path in &reachable {
            if let Some(imports) = model.imports.get(path) {
                for candidate in model.modules.keys() {
                    let module = candidate.trim_end_matches(".py").replace('/', ".");
                    let stem = module.rsplit('.').next().unwrap_or("");
                    if imports.contains(&module) || imports.contains(stem) {
                        added.push(candidate.clone());
                    }
                }
            }
        }
        let old = reachable.len();
        reachable.extend(added);
        if old == reachable.len() {
            break;
        }
    }
    for (path, span) in &model.modules {
        if path.starts_with("nodelang/")
            && !reachable.contains(path)
            && !path.ends_with("__init__.py")
            && !path.ends_with("__main__.py")
        {
            model.diagnostics.push(span.diagnostic(
                "E0002",
                "module is unreachable from shipped entrypoints",
                "connect it to a product entrypoint or remove it",
            ));
        }
    }
    let configured_sources: BTreeSet<_> = model
        .parameter_sources
        .iter()
        .filter(|(_, owner, name)| {
            model
                .sockets
                .iter()
                .any(|s| &s.owner == owner && &s.name == name && s.side == "target")
        })
        .map(|(path, _, _)| source_identity(path))
        .collect();
    model
        .diagnostics
        .retain(|d| !(d.code == "E0007" && configured_sources.contains(&d.file)));
    model.diagnostics.sort();
    model.diagnostics.dedup();
    let mut counts: BTreeMap<String, BTreeMap<String, usize>> = CODES
        .iter()
        .map(|c| (c.to_string(), BTreeMap::new()))
        .collect();
    for f in &files {
        for per_language in counts.values_mut() {
            per_language.entry(f.language.clone()).or_insert(0);
        }
    }
    for d in &model.diagnostics {
        *counts
            .entry(d.code.clone())
            .or_default()
            .entry(d.language.clone())
            .or_default() += 1;
    }
    Report {
        schema_version: 1,
        counts,
        diagnostics: model.diagnostics,
        files,
        observation: None,
    }
}

fn analyze_flat(sources: &[(String, String)], entrypoints: &[String]) -> Report {
    let mut model = Model { entrypoints: entrypoints.iter().cloned().collect(), ..Model::default() };
    let mut files = vec![];
    for (file, source) in sources {
        let language = language_name(file);
        files.push(SourceFile {
            file: file.clone(),
            language: language.into(),
        });
        if language == "asset" {
            continue;
        }
        let span = Span {
            file: file.clone(),
            language: language.into(),
            line: 1,
            column: 1,
        };
        let Some(grammar) = grammar(language, file) else {
            model.diagnostics.push(span.diagnostic("E0010",format!("no grammar and rule set for `{language}`"),"install and register a grammar and semantic extractor; unsupported source cannot pass"));
            continue;
        };
        let mut parser = Parser::new();
        if let Err(err) = parser.set_language(&grammar) {
            model.diagnostics.push(span.diagnostic(
                "E0010",
                err.to_string(),
                "use compatible pinned tree-sitter grammars",
            ));
            continue;
        }
        // JSON Lines is a sequence of independent JSON source units.
        let units: Vec<(usize, &str)> = if file.ends_with(".jsonl") {
            source
                .split_inclusive('\n')
                .enumerate()
                .filter(|(_, s)| !s.trim().is_empty())
                .collect()
        } else {
            vec![(0, source.as_str())]
        };
        for (offset, unit) in units {
            let Some(tree) = parser.parse(unit, None) else {
                model.diagnostics.push(span.diagnostic(
                    "E0011",
                    "parser returned no syntax tree",
                    "reduce the source or repair the parser",
                ));
                continue;
            };
            let start = model.diagnostics.len();
            let mut extractor = Extractor {
                file,
                language,
                product: product_source(file),
                source: unit,
                model: &mut model,
            };
            if language == "json" && product_source(file) {
                if let Some(obj) = children(tree.root_node()).first() {
                    extractor.registry("document", &value(*obj, unit), *obj);
                }
            }
            extractor.walk(tree.root_node());
            if tree.root_node().has_error()
                && !model
                    .diagnostics
                    .iter()
                    .skip(start)
                    .any(|d| d.code == "E0011")
            {
                model.diagnostics.push(span.diagnostic(
                    "E0011",
                    "syntax tree contains a missing token",
                    "fix syntax before product-model analysis",
                ));
            }
            for d in model.diagnostics.iter_mut().skip(start) {
                d.line += offset;
            }
        }
        if language == "python" && product_source(file) {
            model.modules.insert(file.clone(), span);
        }
    }
    finish(model, files)
}

/// Static checks over pending non-code values. Host reference validity remains
/// a live adapter obligation, checked before and re-read after the effect.
pub fn analyze_artifact(pending: &Value, context: &Value) -> Report {
    let target = pending
        .get("target")
        .and_then(Value::as_str)
        .unwrap_or("<pending>");
    let span = Span {
        file: target.into(),
        language: "product".into(),
        line: 1,
        column: 1,
    };
    let mut model = Model::default();
    let mut emit = |code: &str, message: &str| {
        model.diagnostics.push(span.diagnostic(
            code,
            message,
            "correct the exact pending value and resubmit it through Enforce",
        ))
    };
    if matches!(
        language_name(target),
        "python"
            | "javascript"
            | "typescript"
            | "csharp"
            | "powershell"
            | "cmd"
            | "bash"
            | "rust"
            | "sql"
            | "json"
            | "yaml"
            | "html"
            | "css"
            | "toml"
            | "maxscript"
    ) {
        emit(
            "E0010",
            "a source-code destination requires a code overlay and source-language checks",
        );
    }
    let rules = context.get("artifact_rules").unwrap_or(&context["rules"]);
    if !pending.is_object() || target.trim().is_empty() || target == "<pending>" {
        emit(
            "E0010",
            "pending write must name an exact destination and typed content",
        );
    } else {
        let content = &pending["content"];
        if (target.starts_with("revit://") || target.starts_with("autocad://") || pending.get("host").is_some())
            && (pending["kind"] != "model" || pending["format"] != "host-parameter-edit-v1") {
            emit("E0010", "a host target cannot be disguised as another artifact kind");
        }
        match pending["kind"].as_str() {
            Some("model") if pending["format"] == "archhub-graph-v1" => {
                let action = content["action"].as_str().unwrap_or("");
                let reference = if action == "attach_subgraph" {
                    "manifest"
                } else {
                    "baseline"
                };
                if !["attach_subgraph", "restore_baseline"].contains(&action)
                    || !content["subgraph"].as_str().is_some_and(|s| !s.is_empty())
                    || !content[reference].as_str().is_some_and(|s| !s.is_empty())
                {
                    emit("E0009","graph effect requires a supported action and exact subgraph/manifest or baseline references");
                }
                let graph = &pending["graph"];
                if !graph["root"].as_str().is_some_and(|s| !s.is_empty())
                    || !graph["manifest"].as_str().is_some_and(|s| !s.is_empty())
                {
                    emit(
                        "E0009",
                        "graph effect requires the exact graph root and manifest identity",
                    );
                }
                if let Some(records) = graph["records"].as_array().filter(|rows| !rows.is_empty()) {
                    for record in records {
                        if !record["role"].as_str().is_some_and(|s| !s.is_empty())
                            || !record["title"].is_string()
                            || !["value", "merge"]
                                .contains(&record["primitive"].as_str().unwrap_or(""))
                            || !record["configuration"].is_object()
                        {
                            emit("E0009","graph record has no supported pure primitive/configuration contract");
                        }
                    }
                } else {
                    emit(
                        "E0009",
                        "graph effect requires its inspected pure dependency records",
                    );
                }
            }
            Some("model") => {
                let hosted = pending["format"] == "host-parameter-edit-v1"
                    || target.starts_with("revit://") || target.starts_with("autocad://") || pending.get("host").is_some();
                if hosted {
                    if pending["format"] != "host-parameter-edit-v1" {
                        emit("E0010", "a host target requires its supported typed host edit format");
                    }
                    let host = &pending["host"];
                    let program = host["program"].as_str().unwrap_or("");
                    let document = host["document"].as_str().unwrap_or("");
                    let elements = content["elements"].as_array();
                    let element = elements.and_then(|a| if a.len() == 1 { a.first() } else { None });
                    let id = element.and_then(|e| e["id"].as_str()).unwrap_or("");
                    if !matches!(program, "revit" | "autocad") || host["operation"] != "set_parameters"
                        || document.is_empty() || document.contains(['/', '\\', ':', '%'])
                        || id.is_empty() || id.contains(['/', '\\', ':', '%'])
                        || target != format!("{program}://{document}/element/{id}") {
                        emit("E0009", "host parameter edit must bind its supported operation, document, element and exact target");
                    }
                    if !rules["model"]["parameters"].as_object().is_some_and(|p| !p.is_empty()) {
                        emit("E0010", "host parameter edit requires the selected firm parameter standard");
                    }
                }
                if let Some(elements) = content["elements"].as_array().filter(|a| !a.is_empty()) {
                    let mut ids = BTreeSet::new();
                    for element in elements {
                        if !element["id"]
                            .as_str()
                            .is_some_and(|s| !s.is_empty() && ids.insert(s))
                        {
                            emit(
                                "E0001",
                                "model element ids must be nonempty and uniquely owned",
                            );
                        }
                        if let Some(parameters) =
                            element["parameters"].as_object().filter(|p| !p.is_empty())
                        {
                            for (name, parameter) in parameters {
                                let typ = parameter["type"].as_str().unwrap_or("");
                                let val = &parameter["value"];
                                let typed = match typ {
                                    "number" => val.is_number(),
                                    "integer" => val.is_i64() || val.is_u64(),
                                    "boolean" => val.is_boolean(),
                                    "string" => val.is_string(),
                                    "list" => val.is_array(),
                                    "object" => val.is_object(),
                                    _ => false,
                                };
                                let allowed = rules["model"]["value_types"]
                                    .as_array()
                                    .is_some_and(|a| a.iter().any(|t| t.as_str() == Some(typ)));
                                if !typed || !allowed {
                                    emit(
                                        "E0009",
                                        "model parameter has an unsupported or mismatched type",
                                    );
                                }
                                if hosted {
                                    let standard = &rules["model"]["parameters"][name];
                                    if !standard.is_object() || standard["type"] != parameter["type"] {
                                        emit("E0009", "host parameter is absent from the firm standard or has the wrong declared type");
                                    }
                                    for bound in ["min", "max"] {
                                        if let Some(limit) = standard.get(bound) {
                                            let within = limit.as_f64().zip(val.as_f64()).is_some_and(|(limit, value)|
                                                if bound == "min" { value >= limit } else { value <= limit });
                                            if !within { emit("E0009", "host parameter value violates a firm numeric bound"); }
                                        }
                                    }
                                    if let Some(allowed) = standard.get("enum") {
                                        if !allowed.as_array().is_some_and(|a| a.contains(val)) {
                                            emit("E0009", "host parameter value violates the firm allowed values");
                                        }
                                    }
                                }
                            }
                        } else {
                            emit(
                                "E0009",
                                "model element requires named typed parameter changes",
                            );
                        }
                    }
                } else {
                    emit(
                        "E0009",
                        "model requires a nonempty list of typed element changes",
                    );
                }
            }
            Some("document") => {
                if let Some(blocks) = content["blocks"].as_array().filter(|a| !a.is_empty()) {
                    for block in blocks {
                        let typ = block["type"].as_str().unwrap_or("");
                        let allowed = rules["document"]["block_types"]
                            .as_array()
                            .is_some_and(|a| a.iter().any(|t| t.as_str() == Some(typ)));
                        if !allowed
                            || !["paragraph", "heading"].contains(&typ)
                            || !block["text"].as_str().is_some_and(|s| !s.trim().is_empty())
                        {
                            emit(
                                "E0009",
                                "document block must have a configured type and nonempty text",
                            );
                        }
                    }
                } else {
                    emit("E0009", "document requires nonempty typed blocks");
                }
            }
            Some("post") => {
                if !["account", "platform", "body"]
                    .iter()
                    .all(|k| content[k].as_str().is_some_and(|s| !s.trim().is_empty()))
                {
                    emit(
                        "E0009",
                        "post must name an account, platform and nonempty body",
                    );
                } else if !rules["post"]["platforms"]
                    .as_array()
                    .is_some_and(|a| a.iter().any(|v| v == &content["platform"]))
                {
                    emit("E0010", "post platform has no configured rule set");
                } else if context["post_limit"].as_u64().is_none_or(|limit| {
                    content["body"].as_str().unwrap_or("").chars().count() as u64 > limit
                }) {
                    emit(
                        "E0009",
                        "post body exceeds the configured limit or the limit is unavailable",
                    );
                }
            }
            _ => emit("E0010", "pending kind has no registered artifact rule set"),
        }
    }
    finish(
        model,
        vec![SourceFile {
            file: target.into(),
            language: "product".into(),
        }],
    )
}

#[cfg(test)]
mod numbered_source_tests {
    #[test]
    fn vscode_workspace_input_does_not_exempt_literal_or_product_settings() {
        for (file, value, hardcoded) in [
            (".vscode/settings.json", "${workspaceFolder}/.venv/Scripts/python.exe", false),
            (".vscode/settings.json", "C:/Python/python.exe", true),
            ("nodelang/runtime.json", "${workspaceFolder}/.venv/Scripts/python.exe", true)] {
            let sources = vec![(file.into(), serde_json::json!({"python.defaultInterpreterPath": value}).to_string())];
            let report = super::compile(&sources, None);
            assert_eq!(report.diagnostics.iter().any(|d| d.code == "E0007"), hardcoded);
        }
    }

    #[test]
    fn numbered_paths_preserve_native_module_and_bootstrap_identity() {
        for (physical, native) in [("01.APP/nodelang/core.py", "nodelang/core.py"),
            ("02.TESTS/tests_js/check.cjs", "tests_js/check.cjs"),
            ("03.TOOLS/tools/pipeline/build.py", "tools/pipeline/build.py"),
            ("04.DOCS/SPEC.md", "docs/SPEC.md"), ("05.EVIDENCE/policy.json", "evidence/policy.json"),
            ("06.CLOUD/cloud_backend/main.py", "cloud_backend/main.py"),
            ("01.APP/nodelang/launcher.py", "nodelang/launcher.py"), ("launch_archhub_test.py", "nodelang/launcher.py"),
            ("01.APP/nodelang/colleague_setup.py", "colleague_setup.py"),
            ("07.UNRELATED/file.py", "07.UNRELATED/file.py")] {
            assert_eq!(super::source_identity(physical), native);
        }
    }
}

#[cfg(test)]
mod area_index_tests {
    #[test]
    fn area_indexes_keep_distinct_physical_identities() {
        for area in ["01.APP", "02.TESTS", "03.TOOLS", "06.CLOUD"] {
            let file = format!("{area}/README.md");
            assert_eq!(super::source_identity(&file), file);
        }
        assert_eq!(super::source_identity("README.md"), "README.md");
    }
}

#[cfg(test)]
mod numbered_parameter_source_tests {
    #[test]
    fn numbered_binding_still_requires_the_owners_input_socket() {
        for socket in [true, false] {
            let sockets = if socket { serde_json::json!({"config":"string"}) } else { serde_json::json!({}) };
            let model = serde_json::json!({"nodes":[{"id":"policy","engine":"policy",
                "params":{"config":{"type":"string","default":"03.TOOLS/tools/archhub-compiler/rules.json"}},
                "sockets":sockets}]});
            let sources = vec![("catalogue.json".into(), model.to_string()),
                ("tools/archhub-compiler/rules.json".into(), "{\"daily_alert_budget\":5}".into())];
            let report = super::compile(&sources, None);
            assert_eq!(report.diagnostics.iter().any(|d| d.file == "tools/archhub-compiler/rules.json" && d.code == "E0007"), !socket);
        }
    }
}
