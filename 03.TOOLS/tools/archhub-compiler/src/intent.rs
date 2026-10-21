//! Intent authority is compiled from the versioned rule source, never supplied scope.
use crate::{children, source_identity, text, Diagnostic};
use serde_json::Value;
use std::{fs, path::Path, process::Command};
use tree_sitter::Parser;

pub fn authority() -> Value {
    serde_json::from_str(include_str!("../rules.json"))
        .expect("versioned compiler rules must be valid JSON")
}
/// Request scopes are data, not new compiler code. Read only an immutable
/// policy revision; neither a pending overlay nor caller JSON grants scope.
fn repository_bytes(root: &Path, revision: &str, paths: &[&str]) -> Result<Option<Vec<u8>>, String> {
    for path in paths {
        if root.join(".git").exists() {
            let present = Command::new("git").arg("-C").arg(root)
                .args(["ls-tree", "-z", revision, "--", path]).output().map_err(|e| e.to_string())?;
            if !present.status.success() { return Err("authority inventory unavailable".into()); }
            if present.stdout.is_empty() { continue; }
            let output = Command::new("git").arg("-C").arg(root)
                .args(["show", &format!("{revision}:{path}")]).output().map_err(|e| e.to_string())?;
            if !output.status.success() { return Err("authority source unreadable".into()); }
            return Ok(Some(output.stdout));
        }
        match fs::read(root.join(path)) {
            Ok(bytes) => return Ok(Some(bytes)),
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => continue,
            Err(e) => return Err(e.to_string()),
        }
    }
    Ok(None)
}

pub fn repository_authority(root: &Path, revision: &str) -> Result<Value, String> {
    if revision.starts_with('-') { return Err("invalid authority revision".into()); }
    if root.join(".git").exists() {
        let commit = Command::new("git").arg("-C").arg(root)
            .args(["rev-parse", "--verify", &format!("{revision}^{{commit}}")])
            .output().map_err(|e| e.to_string())?;
        if !commit.status.success() { return Err("intent authority revision is unavailable".into()); }
    }
    // Old paths are immutable Git-history inputs, never a second live authority.
    let mut rules = match repository_bytes(root, revision,
            &["05.EVIDENCE/acompiler-intents.json", "evidence/acompiler-intents.json"])? {
        Some(bytes) => merge_registry(&bytes)?,
        None => authority(),
    };
    if let Some(bytes) = repository_bytes(root, revision,
            &["05.EVIDENCE/must_pass.json", "evidence/must_pass.json"])? {
        let manifest: Value = serde_json::from_slice(&bytes).map_err(|e| e.to_string())?;
        let cases = manifest["must_pass"].as_array().ok_or("must_pass manifest requires named cases")?;
        if manifest["schema_version"] != 1 || cases.is_empty() || cases.iter().any(|v| !nonempty(v)) {
            return Err("invalid must_pass authority".into());
        }
        let required = rules["machine_rules"]["conduct"]["R110"]["must_pass"].as_array_mut().unwrap();
        for case in cases { if !required.contains(case) { required.push(case.clone()); } }
    }
    Ok(rules)
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
        && !scope.contains(['*', '?', '#', '%'])
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
    let mut conduct_authority = rules.clone();
    if let Some(parameters) = context.get("machine_rule_parameters").or_else(|| context.get("intent_rule_overrides")) {
        if let Some(overlay) = parameters.get("conduct") {
            if let Err(message) = conduct_parameters(&mut conduct_authority, overlay) {
                diagnostics.push(error("E0102", anchor, 1, 1, message, "edit only typed conduct parameters; mandatory authority cannot be weakened"));
            }
        }
    }
    diagnostics.extend(conduct_checks(context, sources, &conduct_authority, anchor));
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
                    Some(Value::Object(_)) if key == "conduct" => value.is_object(),
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
        let bindings = conduct_bindings(tree.root_node(), source);
        let mut stack = vec![tree.root_node()];
        while let Some(node) = stack.pop() {
            if node.kind().contains("comment") {
                continue;
            }
            let content = text(node, source);
            let mut violated = None;
            let conduct = &conduct_authority["machine_rules"]["conduct"]["R100"];
            if foreground_call(node, source, conduct, &bindings) && !away_guarded(node, source, conduct) {
                diagnostics.push(error("E0102", file, node.start_position().row+1, node.start_position().column+1,
                    "R100: foreground effect has no dominating idle/away guard".into(),
                    "place the effect inside the positive founder_away() or idle_or_away() branch"));
            }
            if matches!(
                node.kind(),
                "string" | "string_literal" | "template_string" | "jsx_text" | "text" | "attribute_value"
            ) && !source_identity(file).starts_with("tests")
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

// Stage 1 conduct is policy data inside the existing INTENT pass. Event
// envelopes are supplied by trusted hooks; source calls are inspected directly.
fn conduct_parameters(rules: &mut Value, overlay: &Value) -> Result<(), String> {
    let compiled = authority();
    let baseline = &compiled["machine_rules"]["conduct"];
    let entries = overlay.as_object().ok_or("conduct parameters must be an object")?;
    let mut policy = rules["machine_rules"]["conduct"].clone();
    for (id, parameters) in entries {
        let original = &baseline[id];
        if !original.is_object() { return Err(format!("unknown conduct rule `{id}`")); }
        for (name, value) in parameters.as_object().ok_or("conduct rule parameters must be an object")? {
            if original.get(name).is_none() { return Err(format!("unknown conduct parameter `{id}.{name}`")); }
            if value == &original[name] {
                continue; // canonical Settings input never replaces merged must_pass authority
            }
            let allowed = match name.as_str() {
                "message" | "fix" => value.as_str().is_some_and(|s| !s.trim().is_empty() && s.len() <= 4096),
                "severity" => value.as_str().is_some_and(|s| matches!(s, "ERROR" | "WARNING" | "INFO" | "LOW" | "MEDIUM" | "HIGH" | "CRITICAL")),
                "max_presence_age_seconds" if id == "R100" => value.as_u64().is_some_and(|v| v <= original[name].as_u64().unwrap_or(0)),
                "allowed_presence" | "allowed_reasons" => value.as_array().is_some_and(|a| !a.is_empty() && a.iter().all(|v| original[name].as_array().is_some_and(|base| base.contains(v)))),
                "banned_text" if id == "R108" => value.as_array().is_some_and(|a| a.iter().all(nonempty)),
                _ => false,
            };
            if !allowed { return Err(format!("invalid or weakening conduct parameter `{id}.{name}`")); }
            if name == "banned_text" {
                let existing = policy[id][name].as_array_mut().unwrap();
                for item in value.as_array().unwrap() { if !existing.contains(item) { existing.push(item.clone()); } }
            } else { policy[id][name] = value.clone(); }
        }
    }
    rules["machine_rules"]["conduct"] = policy;
    Ok(())
}
fn strings(value: &Value) -> Vec<&str> {
    value.as_array().map(|a| a.iter().filter_map(Value::as_str).collect()).unwrap_or_default()
}
fn nonempty(value: &Value) -> bool {
    value.as_str().is_some_and(|s| !s.trim().is_empty())
}
fn contains_any(text: &str, values: &Value) -> bool {
    let lower = text.to_lowercase();
    strings(values).iter().any(|s| lower.contains(&s.to_lowercase()))
}
fn date_in(text: &str) -> bool {
    // Numeric calendar dates and ETA clock times; build ids remain references.
    text.split(|c: char| !(c.is_ascii_digit() || "-/:".contains(c))).any(|token| {
        for separator in ['-', '/'] {
            let parts: Vec<_> = token.split(separator).collect();
            if parts.len() == 3 && parts.iter().all(|p| !p.is_empty() && p.bytes().all(|b| b.is_ascii_digit()))
                && ((parts[0].len() == 4 && (1..=2).contains(&parts[1].len()) && (1..=2).contains(&parts[2].len()))
                    || ((1..=2).contains(&parts[0].len()) && (1..=2).contains(&parts[1].len()) && parts[2].len() == 4)) { return true; }
        }
        let parts: Vec<_> = token.split(':').collect();
        (parts.len() == 2 || parts.len() == 3) && (1..=2).contains(&parts[0].len())
            && parts[0].bytes().all(|b| b.is_ascii_digit())
            && parts[1..].iter().all(|p| p.len() == 2 && p.bytes().all(|b| b.is_ascii_digit()))
    })
}
fn banned_report(text: &str, values: &Value) -> bool {
    let lower = text.to_lowercase();
    strings(values).iter().any(|word| {
        let word = word.to_lowercase();
        lower.match_indices(&word).any(|(start, _)| {
            !lower[..start].chars().last().is_some_and(char::is_alphanumeric)
                && !lower[start+word.len()..].chars().next().is_some_and(char::is_alphanumeric)
        })
    })
}
fn conduct_event(event: &Value, policy: &Value) -> Option<(&'static str, &'static str)> {
    let kind = event["kind"].as_str().unwrap_or("");
    if !policy.as_object().is_some_and(|rules| rules.values().any(|rule| rule["pattern"] == kind)) {
        return Some(("CONDUCT", "event matches no registered policy pattern"));
    }
    match kind {
        "operation" => {
            let effect = event["effect"].as_str().unwrap_or("");
            if contains_any(event["tool"].as_str().unwrap_or(""), &policy["R106"]["tool_markers"])
                && (!nonempty(&event["text"]) || !strings(&policy["R106"]["allowed_reasons"])
                    .contains(&event["question_reason"].as_str().unwrap_or(""))) {
                return Some(("R106", "founder question tool has no intent/safety reason"));
            }
            if effect.is_empty() && !nonempty(&event["tool"]) && !nonempty(&event["command"]) {
                return Some(("R100", "operation has no classified action"));
            }
            let risky = strings(&policy["R100"]["effects"]).contains(&effect)
                || contains_any(event["tool"].as_str().unwrap_or(""), &policy["R100"]["tool_markers"])
                || (!literal_reference(event["command"].as_str().unwrap_or(""), &policy["R100"])
                    && (contains_any(&conduct_command_tokens(event["command"].as_str().unwrap_or("")), &policy["R100"]["command_markers"])
                        || contains_any(event["command"].as_str().unwrap_or(""), &policy["R100"]["source_calls"])));
            if risky && !(strings(&policy["R100"]["allowed_presence"]).contains(&event["presence"]["state"].as_str().unwrap_or(""))
                && event["presence"]["age_seconds"].as_u64().is_some_and(|age| age <= policy["R100"]["max_presence_age_seconds"].as_u64().unwrap_or(0))) {
                return Some(("R100", "foreground effect requires a fresh idle/away guard"));
            }
            if !risky && effect != "" && effect != "read" {
                return Some(("R100", "unknown effect cannot establish safe admission"));
            }
        }
        "dispatch" => {
            let agent = event["agent"].as_str().unwrap_or("");
            let capability = event["capability"].as_str().unwrap_or("");
            let reviewer = event["reviewer"].as_str().unwrap_or("");
            let capabilities = &policy["R104"]["capabilities"];
            if capability.is_empty() || !strings(&capabilities[agent]).contains(&capability)
                || reviewer == agent || !strings(&capabilities[reviewer]).contains(&"review") {
                return Some(("R104", "dispatch needs a registered capability and an independent capable reviewer"));
            }
        }
        "report" => {
            if event["channel"] == "founder" {
                let Some(text) = event["text"].as_str().filter(|s| !s.trim().is_empty()) else {
                    return Some(("R108", "founder report has no result"));
                };
                if text.contains(['?', '\u{061f}']) && !strings(&policy["R106"]["allowed_reasons"])
                    .contains(&event["question_reason"].as_str().unwrap_or("")) {
                    return Some(("R106", "founder report contains a question without an intent/safety reason"));
                }
                if banned_report(text, &policy["R108"]["banned_text"]) || date_in(text) {
                    return Some(("R108", "founder report contains process jargon or a date/ETA"));
                }
            } else if event["channel"] != "internal" {
                return Some(("R108", "report channel must be explicit"));
            }
        }
        "lane_result" => {
            if event["done"] != true && !(event["done"] == false
                && nonempty(&event["ledger"]["next_task"]) && nonempty(&event["ledger"]["owner"])) {
                return Some(("R102", "unfinished lane requires an owned ledger next-task"));
            }
        }
        "question" => {
            if event["channel"] == "founder" {
                if !nonempty(&event["text"]) || !strings(&policy["R106"]["allowed_reasons"]).contains(&event["reason"].as_str().unwrap_or("")) {
                    return Some(("R106", "founder questions are limited to intent or safety"));
                }
            } else if event["channel"] != "internal" {
                return Some(("R106", "question channel must be explicit"));
            }
        }
        "regression" => {
            let required = policy["R110"]["must_pass"].as_array();
            let extra = event["must_pass"].as_array();
            if extra.is_none() || required.is_none_or(|a| a.is_empty() || a.iter().any(|v| {
                v.as_str().is_none_or(|id| id.trim().is_empty() || event["results"][id] != "pass")
            })) || extra.is_some_and(|a| a.iter().any(|v| v.as_str().is_none_or(|id| event["results"][id] != "pass"))) {
                return Some(("R110", "every must_pass result must pass; missing/skipped is a regression"));
            }
        }
        _ => return Some(("CONDUCT", "unknown or malformed conduct event")),
    }
    None
}
fn conduct_checks(context: &Value, sources: &[(String, String)], rules: &Value, anchor: &str) -> Vec<Diagnostic> {
    let mut diagnostics = vec![];
    let policy = &rules["machine_rules"]["conduct"];
    // Never use the caller-editable machine-rule overlay for conduct authority.
    let mut batches: Vec<(String, Value)> = vec![];
    if let Some(events) = context.get("conduct_events") {
        batches.push((anchor.into(), events.clone()));
    }
    let files = file_names(context);
    for (file, source) in sources {
        if files.contains(file) && file.ends_with(".conduct.json") {
            match serde_json::from_str::<Value>(source) {
                Ok(value) => batches.push((file.clone(), value)),
                Err(_) => diagnostics.push(error("E0102", file, 1, 1, "CONDUCT: unreadable event record".into(), "write a JSON array of typed conduct events")),
            }
        }
    }
    for (file, batch) in batches {
        let Some(events) = batch.as_array().filter(|a| !a.is_empty()) else {
            diagnostics.push(error("E0102", &file, 1, 1, "CONDUCT: events must be a nonempty array".into(), "supply typed events from the trusted host adapter"));
            continue;
        };
        for event in events {
            if let Some((id, message)) = conduct_event(event, policy) {
                let rule = &policy[id];
                let mut diagnostic = error("E0102", &file, 1, 1,
                    format!("{id}: {} {message}", rule["message"].as_str().unwrap_or("Invalid conduct.")),
                    rule["fix"].as_str().unwrap_or("correct the action or its evidence before admission"));
                diagnostic.note = rule["severity"].as_str().unwrap_or("ERROR").into();
                diagnostics.push(diagnostic);
            }
        }
    }
    diagnostics
}
fn away_guarded(node: tree_sitter::Node<'_>, source: &str, policy: &Value) -> bool {
    let mut cursor = node;
    while let Some(parent) = cursor.parent() {
        if parent.kind() == "if_statement" {
            let condition = parent.child_by_field_name("condition");
            let body = parent.child_by_field_name("consequence");
            if let (Some(condition), Some(body)) = (condition, body) {
                let mut condition = text(condition, source).trim();
                while condition.starts_with('(') && condition.ends_with(')') {
                    condition = condition[1..condition.len()-1].trim();
                }
                if strings(&policy["guard_conditions"]).contains(&condition)
                    && node.start_byte() >= body.start_byte() && node.end_byte() <= body.end_byte() {
                    return true;
                }
            }
        }
        if matches!(parent.kind(), "function_definition" | "function_declaration" | "arrow_function" | "lambda") { break; }
        cursor = parent;
    }
    false
}
fn conduct_bindings(root: tree_sitter::Node<'_>, source: &str) -> Vec<(String, String)> {
    let mut bindings = vec![];
    let mut stack = vec![root];
    while let Some(node) = stack.pop() {
        let content = text(node, source);
        if node.kind() == "import_statement" {
            for part in content.trim_start_matches("import ").split(',') {
                if let Some((module, alias)) = part.trim().split_once(" as ") {
                    bindings.push((alias.trim().into(), module.trim().into()));
                }
            }
        } else if node.kind() == "import_from_statement" {
            if let Some((module, names)) = content.trim_start_matches("from ").split_once(" import ") {
                for name in names.split(',') {
                    let (name, alias) = name.trim().split_once(" as ").unwrap_or((name.trim(), name.trim()));
                    bindings.push((alias.into(), format!("{module}.{name}")));
                }
            }
        } else if matches!(node.kind(), "assignment" | "variable_declarator") {
            if let (Some(name), Some(value)) = (node.child_by_field_name("left").or_else(|| node.child_by_field_name("name")),
                node.child_by_field_name("right").or_else(|| node.child_by_field_name("value"))) {
                if name.kind() == "identifier" && matches!(value.kind(),
                    "identifier" | "attribute" | "member_expression" | "string" | "string_literal" | "list" | "tuple" | "array") {
                    bindings.push((text(name, source).into(), text(value, source).into()));
                }
            }
        }
        if !node.kind().contains("comment") { stack.extend(children(node)); }
    }
    bindings
}
fn conduct_provenance(seed: &str, bindings: &[(String, String)]) -> Option<std::collections::BTreeSet<String>> {
    // Preserve every possible provenance; a later unrelated binding may never
    // erase an earlier risky import. This is deliberately conservative.
    let mut resolved = std::collections::BTreeSet::from([seed.to_string()]);
    let mut pending = vec![(seed.to_string(), std::collections::BTreeSet::new())];
    let mut steps = 0;
    while let Some((candidate, visited)) = pending.pop() {
        for (index, (alias, value)) in bindings.iter().enumerate() {
                if visited.contains(&index) { continue; }
                let next = if candidate == *alias { Some(value.clone()) }
                else if let Some(tail) = candidate.strip_prefix(&format!("{alias}.")) {
                    Some(format!("{value}.{tail}"))
                } else { None };
                if let Some(next) = next {
                    steps += 1;
                    if next.len() > 4096 || steps > 256 { return None; }
                    if resolved.insert(next.clone()) {
                        let mut visited = visited.clone();
                        visited.insert(index);
                        pending.push((next, visited));
                    }
                }
        }
    }
    Some(resolved)
}
fn foreground_call(node: tree_sitter::Node<'_>, source: &str, policy: &Value, bindings: &[(String, String)]) -> bool {
    if !matches!(node.kind(), "call" | "call_expression" | "command" | "invocation_expression") { return false; }
    let content = text(node, source);
    if node.kind() == "command" && strings(&policy["heavy_commands"]).iter().any(|command| {
        conduct_command_tokens(content).starts_with(&command.to_lowercase())
    }) { return true; }
    let function = node.child_by_field_name("function").or_else(|| node.child_by_field_name("name"))
        .map(|n| text(n, source)).unwrap_or(content);
    let Some(resolved) = conduct_provenance(function, bindings) else { return true; };
    if resolved.iter().any(|value| contains_any(value, &policy["source_calls"])) { return true; }
    if !resolved.iter().any(|value| contains_any(value, &policy["launch_calls"])) { return false; }
    let mut arguments = content.to_string();
    if let Some(args) = node.child_by_field_name("arguments") {
        for arg in children(args) {
            if arg.kind() == "identifier" {
                let Some(values) = conduct_provenance(text(arg, source), bindings) else { return true; };
                for value in values { arguments.push_str(&value); }
            }
        }
    }
    contains_any(&conduct_command_tokens(&arguments), &policy["heavy_commands"])
}
fn conduct_command_tokens(value: &str) -> String {
    value.split(|c: char| c.is_whitespace() || "'\"[],()".contains(c))
        .filter(|part| !part.is_empty()).collect::<Vec<_>>().join(" ").to_lowercase()
}
fn literal_reference(command: &str, policy: &Value) -> bool {
    if command.chars().any(|c| !(c.is_alphanumeric() || " \t-_=./:'\"".contains(c))) { return false; }
    let words: Vec<_> = command.split_whitespace().collect();
    strings(&policy["literal_reference_commands"]).iter().any(|prefix| {
        let prefix: Vec<_> = prefix.split_whitespace().collect();
        words.starts_with(&prefix) && words[prefix.len()..].iter().all(|word| {
            let word = word.trim_matches(['\'', '"']);
            !word.starts_with('-') || strings(&policy["literal_reference_flags"]).contains(&word)
        })
    })
}

