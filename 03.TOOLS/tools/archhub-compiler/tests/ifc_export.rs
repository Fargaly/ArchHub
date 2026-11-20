use archhub_compiler::{analyze_artifact, intent};
use serde_json::{json, Value};

fn proposal() -> Value {
    json!({"kind":"ifc-export","operation":"revit.export_ifc","target":"workspace-roots/private-project/exports/model.ifc","content":{
        "project_id":"private-project","session":"48884","document":"C:\\Private\\model.rvt","path":"C:\\Private\\exports\\model.ifc","version":"IFC4RV","setup":"","views":[]}})
}
fn context() -> Value {
    json!({"artifact_kind":"ifc-export","artifact_rules":{"ifc-export":{"operation":"revit.export_ifc","versions":["IFC2x3CV2","IFC4RV","IFC4DTV","IFC4x3RV","IFC4x3DTV"]}},"intent":"IFCEXPORT","author":"agent:test-ifc-court","files":[proposal()["target"]]})
}
#[test]
fn typed_ifc_contract_accepts_explicit_supported_values() {
    for version in ["IFC2x3CV2", "IFC4RV", "IFC4DTV", "IFC4x3RV", "IFC4x3DTV"] {
        for views in [json!([]), json!([123])] {
            let mut p=proposal();p["content"]["version"]=json!(version);p["content"]["views"]=views;
            assert!(analyze_artifact(&p,&context()).diagnostics.is_empty());
        }
    }
    assert!(intent::check(&context(), &[]).is_empty());
}
#[test]
fn typed_ifc_contract_refuses_mutated_operation_paths_and_values() {
    for (pointer,value) in [
        ("/operation",json!("revit.delete")),("/target",json!("C:\\Private\\exports\\model.ifc")),
        ("/target",json!("workspace-roots/other/exports/model.ifc")),
        ("/target",json!("workspace-roots/private-project/../exports/model.ifc")),
        ("/target",json!("workspace-roots/private-project/exports/model.py")),
        ("/content/path",json!("C:\\Private\\other.ifc")),
        ("/content/path",json!("\\\\server\\share\\exports\\model.ifc")),
        ("/content/path",json!("C:\\Private\\..\\exports\\model.ifc")),
        ("/content/path",json!("C:\\Private\\exports\\model.ifc:stream")),
        ("/content/document",json!("relative.rvt")),("/content/document",json!("C:\\Private\\model.py")),
        ("/content/session",json!(48884)),("/content/session",json!("048884")),("/content/session",json!("48900")),
        ("/content/version",json!("IFC4")),("/content/setup",json!(null)),
        ("/content/views",json!([true])),("/content/views",json!([0])),("/content/views",json!([-1])),
        ("/content/views",json!([1,2])),("/content/views",json!([9223372036854775808u64])),
    ] {
        let mut p=proposal();*p.pointer_mut(pointer).unwrap()=value;
        assert!(!analyze_artifact(&p,&context()).diagnostics.is_empty(),"accepted {pointer}: {p}");
    }
    let mut p=proposal();p["content"]["grant"]=json!("untrusted");
    assert!(!analyze_artifact(&p,&context()).diagnostics.is_empty());
    p["content"].as_object_mut().unwrap().remove("grant");p["content"].as_object_mut().unwrap().remove("setup");
    assert!(!analyze_artifact(&p,&context()).diagnostics.is_empty());
    assert!(!analyze_artifact(&proposal(),&json!({})).diagnostics.is_empty());
}
#[test]
fn runtime_intent_preserves_author_and_source_boundaries() {
    let mut c=context();c["author"]=json!("");assert!(intent::check(&c,&[]).iter().any(|d|d.code=="E0100"));
    c=context();c["intent"]=json!("ACOMPILER2B");assert!(intent::check(&c,&[]).iter().any(|d|d.code=="E0101"));
    c=context();c["files"]=json!(["nodelang/enforce.py"]);assert!(intent::check(&c,&[]).iter().any(|d|d.code=="E0101"));
    c=context();c["files"]=json!(["workspace-roots/private-project/../other.ifc"]);assert!(intent::check(&c,&[]).iter().any(|d|d.code=="E0101"));
}
#[test]
fn literal_aec_destination_names_do_not_broaden_generic_scope() {
    for name in ["90% Design", "RFI #42", "Coordination 2026", "تنسيق"] {
        let mut p=proposal();let target=format!("workspace-roots/private-project/{name}/model.ifc");
        p["target"]=json!(target);p["content"]["path"]=json!(format!("C:\\Private\\{name}\\model.ifc"));
        let mut c=context();c["files"]=json!([target]);
        assert!(analyze_artifact(&p,&c).diagnostics.is_empty());assert!(intent::check(&c,&[]).is_empty());
        if name.contains(['%', '#']) {
            c.as_object_mut().unwrap().remove("artifact_kind");assert!(intent::check(&c,&[]).iter().any(|d|d.code=="E0101"));
        }
    }
    for target in ["workspace-roots/private-project/../model.ifc", "workspace-roots/private-project/a?b/model.ifc", "workspace-roots/private-project/a/model.py", "workspace-roots/private-project//model.ifc", "workspace-roots/private-project/https://a/model.ifc"] {
        assert!(!intent::valid_ifc_target(target));
    }
}
