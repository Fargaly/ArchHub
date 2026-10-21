use archhub_compiler::intent;
use serde_json::{json, Value};

fn context(event: Value) -> Value {
    json!({"intent":"ACOMPILER2B","author":"court","files":["03.TOOLS/tools/archhub-compiler/worker.py"],"conduct_events":[event]})
}
#[test]
fn six_conduct_rules_red_green() {
    let fixtures: Value = serde_json::from_str(include_str!("fixtures/conduct.json")).unwrap();
    for fixture in fixtures.as_array().unwrap() {
        let rule = fixture["rule"].as_str().unwrap();
        let red = intent::check(&context(fixture["red"].clone()), &[]);
        assert!(red.iter().any(|d| d.code == "E0102" && d.message.contains(rule)), "{rule} RED was admitted: {red:?}");
        let green = intent::check(&context(fixture["green"].clone()), &[]);
        assert!(green.is_empty(), "{rule} GREEN: {green:?}");
    }
}
#[test]
fn foreground_source_requires_dominating_away_guard() {
    let file = "03.TOOLS/tools/archhub-compiler/worker.py";
    let c = json!({"intent":"ACOMPILER2B","author":"court","files":[file]});
    for source in ["import pyautogui\npyautogui.click()\n", "import pyautogui\n# if founder_away():\npyautogui.click()\n", "import pyautogui\nif not founder_away():\n    pyautogui.click()\n", "import subprocess\nsubprocess.run(['pytest','tests'])\n"] {
        assert!(intent::check(&c, &[(file.into(), source.into())]).iter().any(|d| d.message.contains("R100")), "unguarded: {source}");
    }
    let green = "import pyautogui\nif founder_away():\n    pyautogui.click()\n";
    assert!(intent::check(&c, &[(file.into(), green.into())]).is_empty());
}

#[test]
fn conduct_cannot_hide_missing_or_forged_evidence() {
    for event in [json!({"kind":"operation"}), json!({"kind":"dispatch","agent":"invented","capability":"build","reviewer":"claude"}),
        json!({"kind":"operation","effect":"screen","presence":{"state":"away","age_seconds":99}}),
        json!({"kind":"regression","must_pass":[],"results":{}})] {
        assert!(intent::check(&context(event), &[]).iter().any(|d| d.code == "E0102"));
    }
}
#[test]
fn source_aliases_and_false_guards_cannot_bypass() {
    let file = "03.TOOLS/tools/archhub-compiler/worker.py";
    let c = json!({"intent":"ACOMPILER2B","author":"court","files":[file]});
    for source in ["import pyautogui as p\np.click()\n", "from pyautogui import click\nclick()\n", "import subprocess as s\ncmd=['pytest']\ns.run(cmd)\n", "import subprocess\na=['pytest']\nb=a\nsubprocess.run(b)\n", "import pyautogui\nif founder_away:\n    pyautogui.click()\n", "import pyautogui\nif founder_away():\n    def later():\n        pyautogui.click()\n"] {
        assert!(intent::check(&c, &[(file.into(), source.into())]).iter().any(|d| d.message.contains("R100")), "bypass: {source}");
    }
}

#[test]
fn review_regressions_stay_refused() {
    let file = "03.TOOLS/tools/archhub-compiler/worker.py";
    let c = json!({"intent":"ACOMPILER2B","author":"court","files":[file]});
    let source = "import pyautogui as p\np.click()\ndef unrelated():\n    p='safe'\n";
    assert!(intent::check(&c,&[(file.into(),source.into())]).iter().any(|d| d.message.contains("R100")));
    for event in [json!({"kind":"operation","tool":"AskUserQuestion","text":"Which port?"}),
        json!({"kind":"report","channel":"founder","text":"The update lands 16/10/2026."}),
        json!({"kind":"report","channel":"founder","text":"Saved 1/2/2026"}),
        json!({"kind":"report","channel":"founder","text":"Saved 2026-1-2"}),
        json!({"kind":"report","channel":"founder","text":"Ready 3:30 PM"}),
        json!({"kind":"report","channel":"founder","text":"Which port should I use?"})] {
        assert!(intent::check(&context(event),&[]).iter().any(|d| d.code == "E0102"));
    }
    assert!(intent::check(&context(json!({"kind":"report","channel":"founder","text":"The settings details are saved."})),&[]).is_empty());
    assert!(intent::check(&context(json!({"kind":"report","channel":"founder","text":"Which intent?","question_reason":"intent"})),&[]).is_empty());
}

#[test]
fn direct_shell_heavy_runs_need_admission() {
    for (file, source) in [("03.TOOLS/tools/archhub-compiler/worker.sh", "cargo test\n"), ("03.TOOLS/tools/archhub-compiler/worker.ps1", "pytest 02.TESTS\tests\n")] {
        let c=json!({"intent":"ACOMPILER2B","author":"court","files":[file]});
        assert!(intent::check(&c,&[(file.into(),source.into())]).iter().any(|d| d.message.contains("R100")), "{file}");
    }
}

#[test]
fn compound_heavy_argv_and_interpreter_commands_need_admission() {
    for command in ["python -c \"import subprocess; subprocess.run(['cargo','test'])\"", "powershell -Command '(Get-Process notepad).CloseMainWindow()'", "python -c 'import keyboard; keyboard.write(\"x\")'", "pkill app", "killall app", "echo pytest; cargo test", "git grep -Opytest pattern", "git grep --open-files-in-pager=pytest pattern", "git grep --textconv pytest", "git grep \"--open-files-in-pager=pytest\" pattern", "git grep \\-Opytest pattern"] {
        let mut event=json!({"kind":"operation","tool":"Bash","command":command,"presence":{"state":"active","age_seconds":0}});
        assert!(intent::check(&context(event.clone()),&[]).iter().any(|d| d.message.contains("R100")), "{command}");
        event["presence"]["state"]=json!("away");
        assert!(intent::check(&context(event),&[]).is_empty(), "{command}");
    }
    for command in ["echo pytest", "git grep pytest", "git grep -n pytest"] {
        assert!(intent::check(&context(json!({"kind":"operation","tool":"Bash","command":command,"presence":{"state":"active","age_seconds":0}})),&[]).is_empty(), "{command}");
    }
    let file="03.TOOLS/tools/archhub-compiler/worker.py";
    let c=json!({"intent":"ACOMPILER2B","author":"court","files":[file]});
    for source in ["import subprocess\nsubprocess.run(['cargo','test'])\n", "import subprocess\nsubprocess.run(['npm','run','build'])\n", "import subprocess\ncommand=['cargo','build']\nsubprocess.run(command)\n"] {
        assert!(intent::check(&c,&[(file.into(),source.into())]).iter().any(|d| d.message.contains("R100")), "{source}");
    }
    let file="03.TOOLS/tools/archhub-compiler/worker.sh";
    let c=json!({"intent":"ACOMPILER2B","author":"court","files":[file]});
    assert!(intent::check(&c,&[(file.into(),"python -m pytest 02.TESTS\tests\n".into())]).iter().any(|d| d.message.contains("R100")));
    assert!(intent::check(&c,&[(file.into(),"echo pytest\n".into())]).is_empty());
}

#[test]
fn plain_report_curly_and_ascii_apostrophes_are_refused() {
    for text in ["Next I\u{2019}ll check it.", "Next I'll check it."] {
        assert!(intent::check(&context(json!({"kind":"report","channel":"founder","text":text})),&[]).iter().any(|d| d.message.contains("R108")));
    }
}

#[test]
fn settings_conduct_parameters_are_typed_and_cannot_weaken_authority() {
    let mut c=context(json!({"kind":"operation","effect":"screen","presence":{"state":"away","age_seconds":1}}));
    assert!(intent::check(&c,&[]).is_empty());
    c["machine_rule_parameters"]=json!({"conduct":{"R100":{"max_presence_age_seconds":0,"message":"Fresh presence required","fix":"Sample again"}}});
    let strict=intent::check(&c,&[]);
    assert!(strict.iter().any(|d| d.message.contains("Fresh presence required") && d.help=="Sample again"));
    c["machine_rule_parameters"]=json!({"conduct":{"R100":{"max_presence_age_seconds":999}}});
    assert!(intent::check(&c,&[]).iter().any(|d| d.message.contains("weakening")));
    c["machine_rule_parameters"]=json!({"conduct":{"R110":{"must_pass":[]}}});
    assert!(intent::check(&c,&[]).iter().any(|d| d.message.contains("weakening")));
    let mut c=context(json!({"kind":"report","channel":"founder","text":"Summary saved"}));
    c["machine_rule_parameters"]=json!({"conduct":{"R108":{"banned_text":["summary"],"severity":"WARNING"}}});
    assert!(intent::check(&c,&[]).iter().any(|d| d.message.contains("R108") && d.note=="WARNING"));
}

#[test]
fn metadata_readers_do_not_become_foreground_effects() {
    let source=include_str!("../../pipeline/strict_check.py");
    let c=json!({"intent":"ACOMPILER2B","author":"court","files":["03.TOOLS/tools/pipeline/strict_check.py"]});
    let hits=intent::check(&c,&[("03.TOOLS/tools/pipeline/strict_check.py".into(),source.into())]);
    assert!(!hits.iter().any(|d| d.message.contains("R100")), "{hits:?}");
}
