//! Intent authority is compiled from the versioned rule source, never supplied scope.
use crate::{children, text, Diagnostic};
use serde_json::Value;
use std::{fs, path::Path, process::Command};
use tree_sitter::Parser;

pub fn authority() -> Value {
    serde_json::from_str(include_str!("../rules.json"))
        .expect("versioned compiler rules must be valid JSON")
}
/// Request scopes are data, not new compiler code. Read only an immutable
/// policy revision; neither a pending overlay nor caller JSON grants scope.
pub fn repository_authority(root: &Path, revision: &str) -> Result<Value, String> {
    if revision.starts_with('-') {
        return Err("invalid authority revision".into());
    }
    let path = "evidence/acompiler-intents.json";
    if !root.join(".git").exists() {
        // Host projects need no Git repository. The policy file is an input to
        // admission, never part of the pending model edit it authorizes.
        return match fs::read(root.join(path)) {
            Ok(bytes) => merge_registry(&bytes),
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(authority()),
            Err(e) => Err(e.to_string()),
        };
    }
    let commit = Command::new("git")
        .arg("-C")
        .arg(root)
        .args(["rev-parse", "--verify", &format!("{revision}^{{commit}}")])
        .output()
        .map_err(|e| e.to_string())?;
    if !commit.status.success() {
        return Err("intent authority revision is unavailable".into());
    }
    let commit = String::from_utf8(commit.stdout).map_err(|e| e.to_string())?;
    let revision = commit.trim();
    let present = Command::new("git")
        .arg("-C")
        .arg(root)
        .args(["ls-tree", "-z", revision, "--", path])
        .output()
        .map_err(|e| e.to_string())?;
    if !present.status.success() {
        return Err("intent authority inventory is unavailable".into());
    }
    let rules = authority();
    if present.stdout.is_empty() {
        return Ok(rules);
    }
    let output = Command::new("git")
        .arg("-C")
        .arg(root)
        .args(["show", &format!("{revision}:{path}")])
        .output()
        .map_err(|e| e.to_string())?;
    if !output.status.success() {
        return Err("intent authority source is unreadable".into());
    }
    merge_registry(&output.stdout)
}
fn merge_registry(bytes: &[u8]) -> Result<Value, String> {
    let mut rules = authority();
    let registry: Value = serde_json::from_slice(bytes).map_err(|e| e.to_string())?;
    if registry["schema_version"] != 1 {
        return Err("invalid intent authority schema".into());
    }
    let entries = registry["intents"]
        .as_object()
        .ok_or("intent authority requires an intents object")?;
    for (id, entry) in entries {
        if id.trim().is_empty()
            || !entry["source"]
                .as_str()
                .is_some_and(|s| !s.trim().is_empty())
            || !entry["scope"].as_array().is_some_and(|a| {
                !a.is_empty() && a.iter().all(|v| v.as_str().is_some_and(valid_scope))
            })
        {
            return Err(format!("invalid source/scope for intent `{id}`"));
        }
        if rules["intents"].get(id).is_some() {
            return Err(format!("intent `{id}` replaces compiled authority"));
        }
        rules["intents"][id] = entry.clone();
    }
    Ok(rules)
}
fn valid_scope(scope: &str) -> bool {
    !scope.is_empty()
        && !scope.starts_with('/')
        && !scope.contains('\\')
        && !scope.contains(['?', '#', '%'])
        && !scope.split('/').any(|p| p == ".." || p == ".")
        && match scope.split_once("://") {
            Some((scheme, target)) => {
                matches!(scheme, "revit" | "autocad")
                    && !target.is_empty()
                    && !target.starts_with('/')
                    && !target.contains(':')
                    && !target.split('/').next().unwrap_or("").is_empty()
            }
            None => !scope.contains(':'),
        }
}
fn error(
    code: &str,
    file: &str,
    line: usize,
    column: usize,
    message: String,
    help: &str,
) -> Diagnostic {
    Diagnostic {
        code: code.into(),
        note: crate::explain(code)
            .unwrap_or("intent authority pass")
            .into(),
        language: crate::language_name(file).into(),
        file: file.into(),
        line,
        column,
        message,
        help: help.into(),
    }
}
fn file_names(context: &Value) -> Vec<String> {
    context
        .get("files")
        .and_then(Value::as_array)
        .map(|a| {
            a.iter()
                .filter_map(|v| v.as_str().map(str::to_string))
                .collect()
        })
        .unwrap_or_default()
}
fn in_scope(file: &str, scope: &str) -> bool {
    valid_scope(file)
        && valid_scope(scope)
        && (file == scope || (scope.ends_with('/') && file.starts_with(scope)))
}
pub fn check(context: &Value, sources: &[(String, String)]) -> Vec<Diagnostic> {
    check_with_authority(context, sources, &authority())
}
pub fn check_with_authority(
    context: &Value,
    sources: &[(String, String)],
    rules: &Value,
) -> Vec<Diagnostic> {
    let mut diagnostics = vec![];
    let files = file_names(context);
    let intent = context
        .get("intent")
        .and_then(Value::as_str)
        .unwrap_or("")
        .trim();
    let author = context
        .get("author")
        .and_then(Value::as_str)
        .unwrap_or("")
        .trim();
    let anchor = files
        .first()
        .map(String::as_str)
        .unwrap_or("COMMIT_EDITMSG");
    let entry = rules.get("intents").and_then(|i| i.get(intent));
    if intent.is_empty() || author.is_empty() || entry.is_none() {
        diagnostics.push(error("E0100",anchor,1,1,"change has no registered intent and identified author".into(),"supply an authoritative founder-row or session-record intent and author; register its declared scope in rules.json"));
        return diagnostics;
    }
    let scopes: Vec<&str> = entry
        .and_then(|e| e.get("scope"))
        .and_then(Value::as_array)
        .map(|a| a.iter().filter_map(Value::as_str).collect())
        .unwrap_or_default();
    for file in &files {
        if !scopes.iter().any(|scope| in_scope(file, scope)) {
            diagnostics.push(error(
                "E0101",
                file,
                1,
                1,
                format!("`{file}` lies outside authoritative intent `{intent}`"),
                "split this change or amend the source intent's declared scope before editing",
            ));
        }
    }
    let mut machine = rules["machine_rules"].clone();
    if let Some(overrides) = context
        .get("machine_rule_parameters")
        .or_else(|| context.get("intent_rule_overrides"))
    {
        if let Some(parameters) = overrides.as_object() {
            for (key, value) in parameters {
                let valid = match machine.get(key) {
                    Some(Value::Array(_)) => value
                        .as_array()
                        .is_some_and(|a| a.iter().all(Value::is_string)),
                    Some(Value::Bool(_)) => value.is_boolean(),
                    _ => false,
                };
                if valid {
                    machine[key] = value.clone();
                } else {
                    diagnostics.push(error("E0102",anchor,1,1,format!("invalid editable machine-rule parameter `{key}`"),
                    "edit only typed machine_rules parameters; intent identities and scopes remain governed authority"));
                }
            }
        } else {
            diagnostics.push(error(
                "E0102",
                anchor,
                1,
                1,
                "machine-rule parameters must be an object".into(),
                "supply the typed machine_rules Settings object",
            ));
        }
    }
    if context
        .get("vendor")
        .and_then(|v| v.get("unmodified"))
        .and_then(Value::as_bool)
        == Some(true)
        && machine["unmodified_vendor_refused"] == true
    {
        diagnostics.push(error("E0102",anchor,1,1,"unmodified vendored product has no recorded ArchHub fit".into(),"record and implement the authorized integration instead of shipping an unmodified product"));
    }
    // Product source under a declared vendor root needs an authoritative fit
    // record, even when its caller omits voluntary vendor metadata. Libraries
    // linked through Cargo/npm remain dependencies, not vendored products.
    if machine["unmodified_vendor_refused"] == true {
        for file in &files {
            if let Some(root) = machine["vendor_product_roots"]
                .as_array()
                .and_then(|roots| {
                    roots
                        .iter()
                        .filter_map(Value::as_str)
                        .find(|root| file.starts_with(root))
                })
            {
                let fit = &entry.unwrap()["vendor_fits"][root];
                let references = ["patches", "settings", "router", "approval", "ledger"];
                let fitted = fit["source_revision"]
                    .as_str()
                    .is_some_and(|s| !s.is_empty())
                    && references.iter().all(|key| {
                        fit[key].as_array().is_some_and(|a| {
                            !a.is_empty()
                                && a.iter().all(|p| {
                                    p.as_str()
                                        .is_some_and(|p| sources.iter().any(|(file, _)| file == p))
                                })
                        })
                    });
                if !fitted {
                    diagnostics.push(error("E0102",file,1,1,"vendored product lacks a pinned source and resolvable ArchHub integration record".into(),
                        "declare the source revision and patch, Settings, router, approval and ledger readers in the authoritative intent record"));
                }
            }
        }
    }
    if context.get("example_as_scope").and_then(Value::as_bool) == Some(true)
        && machine["example_as_scope_refused"] == true
    {
        diagnostics.push(error(
            "E0102",
            anchor,
            1,
            1,
            "example was promoted into change scope without authority".into(),
            "use the declared intent scope; register a new intent for additional work",
        ));
    }
    for (file, source) in sources {
        if !files.contains(file) {
            continue;
        }
        let language = crate::language_name(file);
        let Some(grammar) = crate::grammar(language, file) else {
            continue;
        };
        let mut parser = Parser::new();
        if parser.set_language(&grammar).is_err() {
            continue;
        }
        let Some(tree) = parser.parse(source, None) else {
            continue;
        };
        let mut stack = vec![tree.root_node()];
        while let Some(node) = stack.pop() {
            if node.kind().contains("comment") {
                continue;
            }
            let content = text(node, source);
            let mut violated = None;
            if matches!(
                node.kind(),
                "string" | "string_literal" | "template_string" | "jsx_text" | "text" | "attribute_value"
            ) && !file.starts_with("tests")
                && matches!(language, "python" | "javascript" | "typescript" | "html")
            {
                if let Some(values) = machine["banned_user_text"].as_array() {
                    if values
                        .iter()
                        .filter_map(Value::as_str)
                        .any(|s| content.to_lowercase().contains(&s.to_lowercase()))
                    {
                        violated = Some("banned user-visible sentinel text");
                    }
                }
            }
            if matches!(
                node.kind(),
                "jsx_opening_element" | "jsx_self_closing_element" | "start_tag" | "self_closing_tag"
            ) {
                if let Some(name) = node.child_by_field_name("name").or_else(|| children(node).into_iter().find(|n| n.kind() == "tag_name")) {
                    if machine["forbidden_frame_elements"]
                        .as_array()
                        .is_some_and(|a| {
                            a.iter()
                                .filter_map(Value::as_str)
                                .any(|s| if language == "html" { s.eq_ignore_ascii_case(text(name, source)) } else { s == text(name, source) })
                        })
                    {
                        violated = Some("separate frame bypasses graph presentation authority");
                    }
                }
            }
            if matches!(node.kind(), "assignment" | "variable_declarator") {
                if let Some(name) = node
                    .child_by_field_name("left")
                    .or_else(|| node.child_by_field_name("name"))
                {
                    if machine["hand_listed_settings_names"]
                        .as_array()
                        .is_some_and(|a| {
                            a.iter()
                                .filter_map(Value::as_str)
                                .any(|s| s == text(name, source))
                        })
                    {
                        violated = Some("hand-listed Settings rows bypass the catalogue");
                    }
                }
            }
            if let Some(message) = violated {
                diagnostics.push(error("E0102",file,node.start_position().row+1,node.start_position().column+1,message.into(),"derive the user surface from the authorized node catalogue and live graph state"));
            }
            stack.extend(children(node));
        }
    }
    diagnostics.sort();
    diagnostics.dedup();
    diagnostics
}
