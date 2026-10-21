use archhub_compiler::analyze_artifact;
use serde_json::{json, Value};
fn context() -> Value {
    json!({"rules":{"model":{"value_types":["number","string","boolean","integer","list","object"]},"document":{"block_types":["paragraph","heading"]},"post":{"platforms":["linkedin"]}},"post_limit":10})
}
#[test]
fn model_types_and_duplicate_owners() {
    let bad = json!({"kind":"model","target":"wall:1","content":{"elements":[{"id":"a","parameters":{"height":{"type":"number","value":"wrong"}}}]}});
    let mut good = bad.clone();
    good["content"]["elements"][0]["parameters"]["height"]["value"] = json!(3);
    assert!(analyze_artifact(&bad, &context())
        .diagnostics
        .iter()
        .any(|d| d.code == "E0009"));
    assert!(analyze_artifact(&good, &context()).diagnostics.is_empty());
    let row = good["content"]["elements"][0].clone();
    good["content"]["elements"]
        .as_array_mut()
        .unwrap()
        .push(row);
    assert!(analyze_artifact(&good, &context())
        .diagnostics
        .iter()
        .any(|d| d.code == "E0001"));
}
#[test]
fn document_blocks_and_post_rules() {
    let bad = json!({"kind":"document","target":"report","content":{"blocks":[{"type":"paragraph","text":""}]}});
    let mut good = bad.clone();
    good["content"]["blocks"][0]["text"] = json!("Checked text");
    assert!(!analyze_artifact(&bad, &context()).diagnostics.is_empty());
    assert!(analyze_artifact(&good, &context()).diagnostics.is_empty());
    let post = json!({"kind":"post","target":"account:1","content":{"account":"a","platform":"linkedin","body":"hello"}});
    assert!(analyze_artifact(&post, &context()).diagnostics.is_empty());
    let mut too_long = post.clone();
    too_long["content"]["body"] = json!("A long post exceeds the configured node parameter");
    assert!(!analyze_artifact(&too_long, &context())
        .diagnostics
        .is_empty());
    let mut unsupported = post;
    unsupported["content"]["platform"] = json!("unsupported");
    assert!(analyze_artifact(&unsupported, &context())
        .diagnostics
        .iter()
        .any(|d| d.code == "E0010"));
}
#[test]
fn unknown_write_kind_cannot_pass() {
    assert!(analyze_artifact(
        &json!({"kind":"unknown","target":"a","content":{}}),
        &context()
    )
    .diagnostics
    .iter()
    .any(|d| d.code == "E0010"));
}
#[test]
fn document_contract_cannot_disguise_a_code_write() {
    let pending = json!({"kind":"document","target":"nodelang/new.py","content":{"blocks":[{"type":"paragraph","text":"undefined()"}]}});
    assert!(analyze_artifact(&pending, &context())
        .diagnostics
        .iter()
        .any(|d| d.code == "E0010"));
}
#[test]
fn graph_contract_has_pure_records_and_exact_references() {
    let good = json!({"kind":"model","format":"archhub-graph-v1","target":"graph:1","content":{"action":"attach_subgraph","subgraph":"g","manifest":"m"},"graph":{"root":"g","manifest":"m","records":[{"role":"value","title":"Input","primitive":"value","configuration":{"value":1}}]}});
    assert!(analyze_artifact(&good, &context()).diagnostics.is_empty());
    let mut bad = good;
    bad["graph"]["records"][0]["primitive"] = json!("shell_exec");
    assert!(analyze_artifact(&bad, &context())
        .diagnostics
        .iter()
        .any(|d| d.code == "E0009"));
}
