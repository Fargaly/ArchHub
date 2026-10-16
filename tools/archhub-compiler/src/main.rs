use archhub_compiler::{
    analyze_artifact, apply_context_with_authority, compile, explain, intent, language_name,
    Diagnostic, SourceFile,
};
use std::{
    collections::{BTreeMap, BTreeSet},
    env, fs,
    io::{Cursor, Read},
    path::PathBuf,
    process::{Command, ExitCode},
};

fn run() -> Result<bool, String> {
    let args: Vec<String> = env::args().skip(1).collect();
    if args.first().map(String::as_str) == Some("conduct") {
        let mut root = None;
        let mut context_path = None;
        let mut revision = "HEAD".to_string();
        let mut i = 1;
        while i < args.len() {
            let key = &args[i];
            i += 1;
            let value = args.get(i).ok_or("conduct option requires a value")?;
            match key.as_str() {
                "--root" => root = Some(PathBuf::from(value)),
                "--context" => context_path = Some(value),
                "--revision" => revision = value.clone(),
                _ => return Err(format!("unknown conduct argument `{key}`")),
            }
            i += 1;
        }
        let context: serde_json::Value = serde_json::from_slice(
            &fs::read(context_path.ok_or("conduct requires --context")?).map_err(|e| e.to_string())?
        ).map_err(|e| e.to_string())?;
        if !context["conduct_events"].as_array().is_some_and(|a| !a.is_empty()) {
            return Err("conduct requires nonempty conduct_events".into());
        }
        let authority = intent::repository_authority(&root.ok_or("conduct requires --root")?, &revision)?;
        let mut report = compile(&[], None);
        // Runtime conduct has no pending source diff and therefore no source
        // deviation metrics. Git/artifact paths still run their full pipeline.
        report.extend(intent::check_with_authority(&context, &[], &authority));
        println!("{}", serde_json::to_string(&report).map_err(|e| e.to_string())?);
        return Ok(report.diagnostics.is_empty());
    }
    if args.first().map(String::as_str) == Some("--explain") {
        let code = args.get(1).ok_or("--explain requires an error code")?;
        println!(
            "{code}: {}",
            explain(code).ok_or("unknown diagnostic code")?
        );
        return Ok(true);
    }
    if args.first().map(String::as_str) == Some("artifact") {
        let mut payload = None;
        let mut context = None;
        let mut json = false;
        let mut report_only = false;
        let mut authority_root = None;
        let mut authority_revision = "HEAD".to_string();
        let mut i = 1;
        while i < args.len() {
            match args[i].as_str() {
                "--payload" => {
                    i += 1;
                    payload = args.get(i).cloned();
                }
                "--context" => {
                    i += 1;
                    context = args.get(i).cloned();
                }
                "--authority-root" => {
                    i += 1;
                    authority_root = args.get(i).map(PathBuf::from);
                }
                "--authority-revision" => {
                    i += 1;
                    authority_revision = args.get(i).ok_or("missing authority revision")?.clone();
                }
                "--json" => json = true,
                "--report-only" => report_only = true,
                arg => return Err(format!("unknown artifact argument `{arg}`")),
            }
            i += 1;
        }
        let payload: serde_json::Value = serde_json::from_slice(
            &fs::read(payload.ok_or("--payload is required")?).map_err(|e| e.to_string())?,
        )
        .map_err(|e| e.to_string())?;
        let context: serde_json::Value = serde_json::from_slice(
            &fs::read(context.ok_or("--context is required")?).map_err(|e| e.to_string())?,
        )
        .map_err(|e| e.to_string())?;
        let mut report = analyze_artifact(&payload, &context);
        let authority = match authority_root {
            Some(root) => intent::repository_authority(&root, &authority_revision)?,
            None => intent::authority(),
        };
        apply_context_with_authority(&mut report, &context, &[], &authority);
        if json {
            println!(
                "{}",
                serde_json::to_string(&report).map_err(|e| e.to_string())?
            );
        } else {
            for d in &report.diagnostics {
                println!("{}", d.render());
            }
        }
        return Ok(report_only || report.diagnostics.is_empty());
    }
    if args.first().map(String::as_str) != Some("scan") {
        return Err(
            "usage: archhub-compiler scan --root PATH [--json] [--report-only] [--overlay FILE]"
                .into(),
        );
    }
    let mut root = None;
    let mut overlay = None;
    let mut revision = None;
    let mut context = None;
    let mut json = false;
    let mut report_only = false;
    let mut i = 1;
    while i < args.len() {
        match args[i].as_str() {
            "--root" => {
                i += 1;
                root = args.get(i).map(PathBuf::from);
            }
            "--overlay" => {
                i += 1;
                overlay = args.get(i).map(PathBuf::from);
            }
            "--revision" => {
                i += 1;
                revision = args.get(i).cloned();
            }
            "--context" => {
                i += 1;
                context = args.get(i).cloned();
            }
            "--json" => json = true,
            "--report-only" => report_only = true,
            arg => return Err(format!("unknown argument `{arg}`")),
        }
        i += 1;
    }
    let root = root
        .ok_or("--root is required")?
        .canonicalize()
        .map_err(|e| e.to_string())?;
    let overrides: BTreeMap<String, Option<String>> = if let Some(path) = overlay {
        serde_json::from_slice(&fs::read(path).map_err(|e| e.to_string())?)
            .map_err(|e| format!("invalid overlay: {e}"))?
    } else {
        BTreeMap::new()
    };
    let mut pending = BTreeMap::new();
    let authority = intent::repository_authority(&root, revision.as_deref().unwrap_or("HEAD"))?;
    let mut failures: Vec<(String, String)> = vec![];
    let removed: BTreeSet<_> = overrides
        .iter()
        .filter(|(_, v)| v.is_none())
        .map(|(k, _)| k.clone())
        .collect();
    if let Some(revision) = revision {
        if revision.starts_with('-') {
            return Err("invalid revision".into());
        }
        let inventory = Command::new("git")
            .arg("-C")
            .arg(&root)
            .args(["ls-tree", "-r", "--name-only", "-z", &revision])
            .output()
            .map_err(|e| e.to_string())?;
        if !inventory.status.success() {
            return Err("cannot enumerate revision source inventory".into());
        }
        let inventory = String::from_utf8(inventory.stdout).map_err(|e| e.to_string())?;
        let mut expected: BTreeSet<String> = inventory
            .split('\0')
            .filter(|s| !s.is_empty() && language_name(s) != "asset" && !overrides.contains_key(*s))
            .map(str::to_string)
            .collect();
        let output = Command::new("git")
            .arg("-C")
            .arg(&root)
            .args(["archive", "--format=tar", &revision])
            .output()
            .map_err(|e| e.to_string())?;
        if !output.status.success() {
            return Err(format!(
                "git revision enumeration failed: {}",
                String::from_utf8_lossy(&output.stderr)
            ));
        }
        let mut archive = tar::Archive::new(Cursor::new(output.stdout));
        for item in archive.entries().map_err(|e| e.to_string())? {
            let mut entry = item.map_err(|e| e.to_string())?;
            let file = entry
                .path()
                .map_err(|e| e.to_string())?
                .to_str()
                .ok_or("non-UTF8 source path")?
                .replace('\\', "/");
            if entry.header().entry_type().is_dir()
                || language_name(&file) == "asset"
                || removed.contains(&file)
                || overrides.contains_key(&file)
            {
                continue;
            }
            expected.remove(&file);
            if !entry.header().entry_type().is_file() {
                failures.push((file, "source is not a regular file".into()));
                continue;
            }
            let mut data = String::new();
            match entry.read_to_string(&mut data) {
                Ok(_) => {
                    pending.insert(file, data);
                }
                Err(e) => failures.push((file, e.to_string())),
            }
        }
        for file in expected {
            failures.push((
                file,
                "tracked source was omitted by archive attributes; source coverage is incomplete"
                    .into(),
            ));
        }
    } else {
        let output = Command::new("git")
            .arg("-C")
            .arg(&root)
            .args([
                "ls-files",
                "--cached",
                "--others",
                "--exclude-standard",
                "-z",
            ])
            .output()
            .map_err(|e| e.to_string())?;
        if !output.status.success() {
            return Err(format!(
                "git source enumeration failed: {}",
                String::from_utf8_lossy(&output.stderr)
            ));
        }
        let paths = String::from_utf8(output.stdout).map_err(|e| e.to_string())?;
        for file in paths.split('\0').filter(|s| !s.is_empty()) {
            if overrides.contains_key(file) || language_name(file) == "asset" {
                continue;
            }
            let path = root.join(file);
            if !path.exists() {
                continue;
            }
            match fs::symlink_metadata(&path) {
                Ok(metadata) if metadata.file_type().is_file() => match fs::read_to_string(path) {
                    Ok(data) => {
                        pending.insert(file.replace('\\', "/"), data);
                    }
                    Err(e) => failures.push((file.into(), e.to_string())),
                },
                Ok(_) => failures.push((
                    file.into(),
                    "symbolic/non-regular source is not admitted".into(),
                )),
                Err(e) => failures.push((file.into(), e.to_string())),
            }
        }
    }
    for (file, content) in overrides {
        if file.contains('\\')
            || file.starts_with('/')
            || file.contains(':')
            || file.split('/').any(|p| p == "..")
        {
            return Err(format!("overlay path is not repository relative: {file}"));
        }
        if let Some(content) = content {
            pending.insert(file, content);
        }
    }
    let sources = pending.into_iter().collect::<Vec<_>>();
    let context: Option<serde_json::Value> = context
        .map(|path| {
            fs::read(path)
                .map_err(|e| e.to_string())
                .and_then(|b| serde_json::from_slice(&b).map_err(|e| e.to_string()))
        })
        .transpose()?;
    let mut report = compile(&sources, None);
    for (file, message) in failures {
        let language = language_name(&file).to_string();
        report.files.push(SourceFile {
            file: file.clone(),
            language: language.clone(),
        });
        for counts in report.counts.values_mut() {
            counts.entry(language.clone()).or_insert(0);
        }
        *report
            .counts
            .entry("E0010".into())
            .or_default()
            .entry(language.clone())
            .or_default() += 1;
        report.diagnostics.push(Diagnostic {
            code: "E0010".into(),
            note: "source inventory must be complete before admission".into(),
            file,
            language,
            line: 1,
            column: 1,
            message,
            help: "provide readable UTF-8 source in a regular repository file".into(),
        });
    }
    if let Some(context) = context.as_ref() {
        apply_context_with_authority(&mut report, context, &sources, &authority);
    }
    if json {
        println!(
            "{}",
            serde_json::to_string(&report).map_err(|e| e.to_string())?
        );
    } else {
        for d in &report.diagnostics {
            println!("{}", d.render());
        }
        println!(
            "{} diagnostics across {} source files",
            report.diagnostics.len(),
            report.files.len()
        );
    }
    Ok(report_only || report.diagnostics.is_empty())
}
fn main() -> ExitCode {
    match run() {
        Ok(true) => ExitCode::SUCCESS,
        Ok(false) => ExitCode::from(1),
        Err(error) => {
            eprintln!(
                "error[E0010]: {error}\n  help: repair compiler invocation; no check has passed"
            );
            ExitCode::from(2)
        }
    }
}
