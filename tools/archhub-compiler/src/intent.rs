//! Intent authority is compiled from the versioned rule source, never supplied scope.
use crate::{children, text, Diagnostic};
use serde_json::Value;
use tree_sitter::Parser;

pub fn authority() -> Value {
    serde_json::from_str(include_str!("../rules.json"))
        .expect("versioned compiler rules must be valid JSON")
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
    !file.starts_with('/')
        && !file.contains('\\')
        && !file.contains(':')
        && !file.split('/').any(|p| p == "..")
        && (file == scope || (scope.ends_with('/') && file.starts_with(scope)))
}
pub fn check(context: &Value, sources: &[(String, String)]) -> Vec<Diagnostic> {
    let rules = authority();
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
                "string" | "string_literal" | "template_string" | "jsx_text"
            ) && !file.starts_with("tests")
                && file.starts_with("nodelang/")
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
                "jsx_opening_element" | "jsx_self_closing_element"
            ) {
                if let Some(name) = node.child_by_field_name("name") {
                    if machine["forbidden_frame_elements"]
                        .as_array()
                        .is_some_and(|a| {
                            a.iter()
                                .filter_map(Value::as_str)
                                .any(|s| s == text(name, source))
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
