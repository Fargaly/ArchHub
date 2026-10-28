"""Fail-closed ACOMPILER gate; hooks judge explicitly owned or staged files only.

Run ``python tools/pipeline/strict_check.py --changed`` for the index,
``--session-record PATH`` for the Stop hook, or ``--files PATH ...`` for an
explicit edit set. A whole-model scan preserves cross-file type/owner checks;
added/changed lines in legacy files must be clean; new files must be fully clean.
Per-file/code and whole-model code/language counts may never rise.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import importlib.util
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


PRODUCT_ROOT = Path(__file__).resolve().parents[2]
if PRODUCT_ROOT.name == "03.TOOLS":
    PRODUCT_ROOT = PRODUCT_ROOT.parent


class CompilerFailure(RuntimeError):
    """The gate cannot establish a valid compiler result."""


CODES = ({f"E{number:04d}" for number in range(1, 12)} |
         {f"E{number:04d}" for number in range(20, 27)} |
         {"E0100", "E0101", "E0102", "E0200"})
RUNTIME_FILES = ("tools/__init__.py", "tools/ratchet.py", "tools/pipeline/__init__.py",
    "tools/pipeline/strict_check.py", "tools/pipeline/build.py", "tools/pipeline/land.py",
    "tools/pipeline/pre_commit.py", "tools/pipeline/install_hooks.py", "tools/pipeline/record_observation.py",
    "nodelang/enforce.py")
COMPILER_SOURCES = ("NOTICE", "tools/archhub-compiler/Cargo.toml", "tools/archhub-compiler/Cargo.lock",
    "tools/archhub-compiler/rules.json", "tools/archhub-compiler/src/lib.rs", "tools/archhub-compiler/src/main.rs",
    "tools/archhub-compiler/src/semantics.rs", "tools/archhub-compiler/src/intent.rs", "tools/archhub-compiler/src/deviation.rs",
    "tools/archhub-compiler/THIRD_PARTY.md",
    "tools/archhub-compiler/licenses/tree-sitter-html-0.23.2-LICENSE.txt",
    "tools/archhub-compiler/licenses/tree-sitter-json-0.24.8-LICENSE.txt",
    "tools/archhub-compiler/licenses/tree-sitter-sequel-0.3.11-LICENSE.txt",
    "tools/archhub-compiler/licenses/tree-sitter-toml-ng-0.7.0-LICENSE.txt",
    "tools/archhub-compiler/licenses/tree-sitter-typescript-0.23.2-LICENSE.txt")
WINDOWS_DLLS = {"kernel32.dll", "ntdll.dll", "advapi32.dll", "bcrypt.dll", "bcryptprimitives.dll", "userenv.dll",
    "ws2_32.dll", "dbghelp.dll", "user32.dll", "shell32.dll", "ole32.dll", "oleaut32.dll", "secur32.dll", "crypt32.dll",
    "iphlpapi.dll", "normaliz.dll", "version.dll", "gdi32.dll", "rpcrt4.dll", "combase.dll"}


def system_dependencies(names):
    if not isinstance(names, list) or not names or any(not isinstance(name, str) for name in names):
        raise CompilerFailure("compiler has no Windows dependency closure proof")
    unsupported = [name for name in names if name.lower() not in WINDOWS_DLLS and not name.lower().startswith(("api-ms-win-core-", "ext-ms-win-"))]
    if unsupported:
        raise CompilerFailure("compiler has unpackaged runtime dependencies: " + ", ".join(unsupported))
    return names


def source_digest(files):
    return hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def verify_runtime(owner):
    owner = Path(owner).resolve()
    runtime = owner / "runtime" / "acompiler"
    manifest = json.loads((runtime / "provenance.json").read_text(encoding="utf-8"))
    if (not isinstance(manifest, dict) or not isinstance(manifest.get("sources"), dict)
            or not isinstance(manifest.get("runtime_files"), dict)):
        raise CompilerFailure("installed compiler provenance schema is invalid")
    if manifest.get("schema_version") != 1 or manifest.get("source_sha256") != source_digest(manifest.get("sources", {})):
        raise CompilerFailure("installed compiler source provenance is invalid")
    if set(manifest.get("sources", {})) != set(COMPILER_SOURCES):
        raise CompilerFailure("installed compiler source/lock/rule proof is incomplete")
    if any(not isinstance(value, str) or len(value) != hashlib.sha256().digest_size * 2 or any(char not in "0123456789abcdef" for char in value)
           for value in manifest["sources"].values()):
        raise CompilerFailure("installed compiler source digest is malformed")
    if set(manifest.get("runtime_files", {})) != set(RUNTIME_FILES):
        raise CompilerFailure("installed compiler Python/seed closure is incomplete")
    for relative, expected in manifest["runtime_files"].items():
        if hashlib.sha256((owner / relative).read_bytes()).hexdigest() != expected:
            raise CompilerFailure(f"installed compiler runtime source changed: {relative}")
    for filename, key in (("archhub-compiler.exe", "executable_sha256"), ("rules.json", "rules_sha256"),
                          ("NOTICE", "notice_sha256"), ("LICENSES.txt", "licenses_sha256")):
        if hashlib.sha256((runtime / filename).read_bytes()).hexdigest() != manifest.get(key):
            raise CompilerFailure(f"installed compiler payload hash mismatch: {filename}")
    if manifest.get("crt") != "static" or manifest.get("rustflags") != "-C target-feature=+crt-static":
        raise CompilerFailure("installed compiler lacks a static CRT build proof")
    if manifest["rules_sha256"] != manifest["sources"].get("tools/archhub-compiler/rules.json"):
        raise CompilerFailure("installed compiler rule/source provenance differs")
    if manifest["notice_sha256"] != manifest["sources"].get("NOTICE"):
        raise CompilerFailure("installed compiler NOTICE/source provenance differs")
    system_dependencies(manifest.get("windows_dlls"))
    return runtime / "archhub-compiler.exe"


def node_parameter(name):
    # Read the one node seed without importing the application's bootstrap.
    source = (PRODUCT_ROOT / "01.APP" if (PRODUCT_ROOT / "01.APP").is_dir() else PRODUCT_ROOT) / "nodelang" / "enforce.py"
    spec = importlib.util.spec_from_file_location("archhub_enforce_seed", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.defaults()[name]


def node_timeout(value=None):
    return float(node_parameter("compiler_timeout") if value is None else value)


def git(root, *args, input=None):
    try:
        result = subprocess.run(["git", "-C", str(root), *args], input=input, capture_output=True, timeout=node_timeout())
    except (OSError, subprocess.SubprocessError) as exc:
        raise CompilerFailure(f"cannot establish changed-file scope: {exc}") from exc
    if result.returncode:
        raise CompilerFailure(result.stderr.decode("utf-8", errors="replace").strip())
    return result.stdout


def revision_blobs(root, revision, paths):
    """Bytes of each path at an immutable revision, or the index when revision is None.

    One listing and one batch read replace a Git spawn pair per path. The answer is
    the per-path ``ls-tree``/``ls-files --stage`` then ``show`` pair's: absent is
    None, and anything but a plain listed blob or a plain absent path (directory,
    gitlink, conflict, pathspec-magic name) takes exactly that pair.
    """
    listing = git(root, "ls-tree", "-r", "-z", revision) if revision else git(root, "ls-files", "--stage", "-z")
    plain, special, directories = {}, set(), set()
    for row in filter(None, listing.split(b"\0")):
        meta, _, name = row.partition(b"\t")
        name = name.decode("utf-8", "surrogateescape")
        fields = meta.decode("ascii").split()
        mode, oid, ok = (fields[0], fields[2], fields[1] == "blob") if revision else (fields[0], fields[1], fields[2] == "0")
        if ok and mode != "160000" and name not in special:
            plain[name] = oid
        else:
            special.add(name)
            plain.pop(name, None)
        parts = name.split("/")
        directories.update("/".join(parts[:end]) for end in range(1, len(parts)))
    def per_path(path):
        present = git(root, "ls-tree", "-z", revision, "--", path) if revision else git(root, "ls-files", "--stage", "-z", "--", path)
        return git(root, "show", f"{revision}:{path}" if revision else f":{path}") if present else None
    result, wanted = {}, {}
    for path in paths:
        if path.startswith(":") or path in special or path in directories or (
                revision is None and any(char in path for char in "*?[\\")):
            result[path] = per_path(path)
        elif path in plain:
            wanted[path] = plain[path]
        else:
            result[path] = None
    oids = sorted(set(wanted.values()))
    data = git(root, "cat-file", "--batch", input="".join(oid + "\n" for oid in oids).encode("ascii")) if oids else b""
    blobs, at = {}, 0
    while at < len(data):
        end = data.index(b"\n", at)
        header = data[at:end].decode("ascii", "replace").split()
        if len(header) != 3 or header[1] != "blob":
            raise CompilerFailure("cannot read revision blob: " + " ".join(header))
        size = int(header[2])
        blobs[header[0]] = data[end + 1:end + 1 + size]
        at = end + 2 + size
    for path, oid in wanted.items():
        if oid not in blobs:
            raise CompilerFailure(f"cannot read revision blob: {path}")
        result[path] = blobs[oid]
    return result


def normalize(root, path):
    root = Path(root).resolve()
    target = Path(path)
    target = target.resolve() if target.is_absolute() else (root / target).resolve()
    try:
        return target.relative_to(root).as_posix()
    except ValueError as exc:
        raise CompilerFailure(f"path outside compiler root: {path}") from exc


def selected_files(root, *, files=None, session_record=None, base=None, commit=None):
    """Return owned paths. Never infer ownership from global unstaged edits."""
    root = Path(root).resolve()
    if sum(x is not None for x in (files, session_record, base, commit)) > 1:
        raise CompilerFailure("choose one scope: files, session-record, base, or commit")
    if files is not None:
        paths = files
    elif session_record is not None:
        # One agent session may edit several product repositories. A shared
        # PostToolUse record owns only the entries inside this invocation root.
        paths = []
        record_text = Path(session_record).read_text(encoding="utf-8-sig")
        record_entries = json.loads(record_text).get("files", []) if record_text.lstrip().startswith("{") else record_text.splitlines()
        for recorded in record_entries:
            if not recorded.strip():
                continue
            try:
                paths.append(normalize(root, recorded))
            except CompilerFailure:
                continue
    elif commit is not None:
        revision = git(root, "rev-parse", "--verify", f"{commit}^{{commit}}").strip()
        if revision != git(root, "rev-parse", "HEAD").strip():
            raise CompilerFailure("--commit must identify the checked-out HEAD")
        paths = git(root, "diff-tree", "--root", "--no-commit-id", "--no-renames", "--name-only", "-r", "-z",
                    "--diff-filter=ACMRD", revision.decode()).decode("utf-8").split("\0")
    elif base is not None:
        git(root, "rev-parse", "--verify", f"{base}^{{commit}}")
        paths = git(root, "diff", "--no-renames", "--name-only", "-z", "--diff-filter=ACMRD", base, "--").decode("utf-8").split("\0")
        # Explicit branch/session base covers new source files too. The staged
        # default never consumes untracked files belonging to another session.
        paths += git(root, "ls-files", "--others", "--exclude-standard", "-z").decode("utf-8").split("\0")
    else:
        paths = git(root, "diff", "--cached", "--no-renames", "--name-only", "-z", "--diff-filter=ACMRD", "--").decode("utf-8").split("\0")
    return sorted({normalize(root, p) for p in paths if str(p).strip()})


def compiler_options(options=None):
    values = {"jobs": node_parameter("compiler_jobs"), "rustflags": node_parameter("compiler_rustflags"), **dict(options or {})}
    if type(values["jobs"]) is not int or values["jobs"] < 1 or not isinstance(values["rustflags"], str):
        raise CompilerFailure("compiler build options require positive integer jobs and text rustflags")
    return values


def idle_or_away():
    """Use BABOOM's input-age reader, as the launcher does; unknown is active."""
    import math
    try:
        app = PRODUCT_ROOT / "01.APP" if (PRODUCT_ROOT / "01.APP").is_dir() else PRODUCT_ROOT
        if str(app) not in sys.path:
            sys.path.insert(0, str(app))
        from nodelang.baboom_native_companion import desktop_input_idle_seconds
        age = desktop_input_idle_seconds()
        return math.isfinite(age) and age >= 2.0
    except (ImportError, OSError, AttributeError, TypeError, ValueError):
        return False


_BUILT_COMPILERS = {}


def _command(root, options=None, *, executable_only=False):
    # The product owns its compiler. A target project cannot replace admission
    # by placing a different executable/crate in the directory being checked.
    owner = Path(__file__).resolve().parents[2]
    if (owner / "runtime" / "acompiler").exists():
        return [str(verify_runtime(owner))]
    manifest = owner / "tools" / "archhub-compiler" / "Cargo.toml"
    if not manifest.is_file():
        raise CompilerFailure(f"missing compiler source: {manifest}")
    cargo_home = Path(os.environ.get("CARGO_HOME", str(rust_root(owner) / "cargo")))
    cargo = cargo_home / "bin" / ("cargo.exe" if os.name == "nt" else "cargo")
    if not cargo.is_file():
        raise CompilerFailure(f"missing supplied Cargo toolchain: {cargo}")
    options = compiler_options(options)
    env = _environment(options=options)
    crate = manifest.parent
    target = Path(env.get("CARGO_TARGET_DIR", str(crate / "target")))
    if not target.is_absolute():
        target = Path(root).resolve() / target
    inputs = [manifest, crate / "Cargo.lock", crate / "rules.json", *sorted((crate / "src").rglob("*"))]
    inputs += [crate / "build.rs"]
    directories = {crate, *crate.parents, Path(root).resolve(), *Path(root).resolve().parents}
    inputs += [directory / name for directory in directories for name in ("rust-toolchain.toml", "rust-toolchain")]
    inputs += [directory / ".cargo" / name for directory in directories
               for name in ("config", "config.toml")]
    inputs += [cargo_home / name for name in ("config", "config.toml")]
    fingerprint = source_digest({str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                                 for path in inputs if path.is_file()})
    key = (str(target), fingerprint, tuple(sorted(env.items())))
    prepared = _BUILT_COMPILERS.get(key)
    if prepared and prepared[0].is_file() and hashlib.sha256(prepared[0].read_bytes()).hexdigest() == prepared[1]:
        return [str(prepared[0])]
    if executable_only or idle_or_away():
        try:
            # Cold compilation must not consume or inherit the executable scan deadline.
            if idle_or_away():
                result = subprocess.run([str(cargo), "build", "--quiet", "--release", "--locked", "--jobs", str(options["jobs"]),
                    "--manifest-path", str(manifest), "--target-dir", str(target), "--message-format=json"],
                    cwd=root, env=env, capture_output=True, text=True, encoding="utf-8", check=True)
            else:
                # Resolve Cargo's actual artifact, never hash its launcher as the compiler.
                result = subprocess.run([str(cargo), "run", "--quiet", "--release", "--locked", "--jobs", str(options["jobs"]),
                    "--manifest-path", str(manifest), "--target-dir", str(target), "--message-format=json", "--", "source-identities"],
                    input="[]", cwd=root, env=env, capture_output=True, text=True, encoding="utf-8", check=True,
                    timeout=node_timeout())
            artifacts = [json.loads(line) for line in result.stdout.splitlines()]
            executables = {item["executable"] for item in artifacts if item.get("reason") == "compiler-artifact"
                           and item.get("target", {}).get("name") == "archhub-compiler" and item.get("executable")}
            if len(executables) != 1:
                raise CompilerFailure("compiler build did not identify exactly one executable")
            executable = Path(executables.pop())
            _BUILT_COMPILERS[key] = executable, hashlib.sha256(executable.read_bytes()).hexdigest()
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            detail = getattr(exc, "stderr", None) or str(exc)
            raise CompilerFailure(f"compiler build failed: {detail}") from exc
        return [str(executable)]
    else:
        return [str(cargo), "run", "--quiet", "--release", "--locked", "--jobs", str(options["jobs"]), "--manifest-path", str(manifest), "--"]


def rust_root(owner):
    """The supplied Rust toolchain: 10.PRODUCT/rust, or its workspace home since 2026-10-20 (50.TOOLING)."""
    owner = owner.parent if owner.name == "03.TOOLS" else owner
    moved = owner.parents[1] / "50.TOOLING" / "53.AGENT-TOOLS" / "53.08-RUST-TOOLCHAIN"
    return owner.parent / "rust" if (owner.parent / "rust").is_dir() or not moved.is_dir() else moved


def _build_environment(env, options):
    if options is not None:
        env["RUSTFLAGS"] = compiler_options(options)["rustflags"]
        env.pop("CARGO_ENCODED_RUSTFLAGS", None)
    return env


def _environment(compiler_command=None, owner=None, options=None):
    env = os.environ.copy()
    if compiler_command is not None:
        return _build_environment(env, options)
    explicit_owner = owner is not None
    owner = Path(owner).resolve() if owner else Path(__file__).resolve().parents[2]
    if not explicit_owner and (owner / "runtime" / "acompiler").exists():
        return _build_environment(env, options)
    rust = rust_root(owner)
    setup = owner / "tools" / "archhub-compiler" / "target" / "msvc" / "setup_x64.bat"
    if os.name == "nt" and setup.is_file():
        command = f'"{env.get("COMSPEC", "cmd.exe")}" /d /s /c ""{setup}" >nul && set"'
        result = subprocess.run(command,
                                capture_output=True, text=True, timeout=node_timeout())
        if result.returncode:
            raise CompilerFailure("compiler MSVC environment initialization failed")
        env.update(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line and not line.startswith("="))
    env.setdefault("CARGO_HOME", str(rust / "cargo"))
    env.setdefault("RUSTUP_HOME", str(rust / "rustup"))
    linker = rust / "rustup" / "toolchains" / "stable-x86_64-pc-windows-msvc" / "lib" / "rustlib" / "x86_64-pc-windows-msvc" / "bin" / "rust-lld.exe"
    if os.name == "nt" and setup.is_file() and linker.is_file():
        env["CARGO_TARGET_X86_64_PC_WINDOWS_MSVC_LINKER"] = str(linker)
    return _build_environment(env, options)


def _validate_report(report, root, artifact=False):
    if not isinstance(report, dict) or report.get("schema_version") != 1:
        raise CompilerFailure("invalid compiler report schema_version")
    counts, diagnostics, files = (report.get(k) for k in ("counts", "diagnostics", "files"))
    if not isinstance(counts, dict) or not isinstance(diagnostics, list) or not isinstance(files, list):
        raise CompilerFailure("compiler report missing counts/diagnostics/files")
    if set(counts) != CODES:
        raise CompilerFailure("compiler omitted required rule registry coverage")
    if any(not isinstance(item, dict) or not isinstance(item.get("language"), str) or not item["language"] for item in files):
        raise CompilerFailure("invalid compiler file language coverage")
    languages_in_files = {item["language"] for item in files}
    languages_in_files.update(item["language"] for item in diagnostics
                             if isinstance(item, dict) and isinstance(item.get("language"), str))
    if any(not isinstance(bucket, dict) or set(bucket) != languages_in_files for bucket in counts.values()):
        raise CompilerFailure("compiler omitted code/language rule coverage")
    actual = {}
    for diagnostic in diagnostics:
        if not isinstance(diagnostic, dict) or any(not isinstance(diagnostic.get(k), str) or not diagnostic[k]
                for k in ("code", "language", "file", "message", "help")):
            raise CompilerFailure("invalid compiler diagnostic")
        if any(type(diagnostic.get(k)) is not int or diagnostic[k] < 1 for k in ("line", "column")):
            raise CompilerFailure("invalid compiler diagnostic location")
        if not artifact:
            diagnostic["file"] = normalize(root, diagnostic["file"])
        languages = actual.setdefault(diagnostic["code"], {})
        languages[diagnostic["language"]] = languages.get(diagnostic["language"], 0) + 1
    for code, languages in counts.items():
        if not isinstance(code, str) or not isinstance(languages, dict):
            raise CompilerFailure("invalid compiler counts")
        for language, count in languages.items():
            if not isinstance(language, str) or type(count) is not int or count < 0:
                raise CompilerFailure("invalid compiler count")
            if count != actual.get(code, {}).get(language, 0):
                raise CompilerFailure("compiler counts disagree with diagnostics")
    for code, languages in actual.items():
        for language, count in languages.items():
            if counts.get(code, {}).get(language) != count:
                raise CompilerFailure("compiler omitted diagnostic count")
    for item in files:
        if not isinstance(item, dict) or not isinstance(item.get("file"), str) or not isinstance(item.get("language"), str):
            raise CompilerFailure("invalid compiler file coverage")
        if not artifact:
            item["file"] = normalize(root, item["file"])
    return report


def check_conduct(root, context, *, revision="HEAD", compiler_command=None, timeout=None):
    """Admit one trusted hook/watchdog envelope through the existing INTENT pass."""
    root = Path(root).resolve()
    command = list(compiler_command) if compiler_command is not None else _command(root)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".json", delete=False) as stream:
            json.dump(context, stream)
            temporary = stream.name
        result = subprocess.run(command + ["conduct", "--root", str(root), "--revision", revision,
            "--context", temporary], capture_output=True, text=True, encoding="utf-8",
            timeout=node_timeout(timeout), env=_environment(compiler_command))
        if result.returncode not in (0, 1):
            raise CompilerFailure("conduct admission failed: " + result.stderr.strip()[-1000:])
        report = _validate_report(json.loads(result.stdout), root)
        if (result.returncode == 0) != (not report["diagnostics"]):
            raise CompilerFailure("conduct exit status disagrees with diagnostics")
        return {**report, "ok": not report["diagnostics"]}
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise CompilerFailure(str(exc)) from exc
    finally:
        if temporary:
            Path(temporary).unlink(missing_ok=True)


def scan_model(root, *, overlay=None, revision=None, context=None, compiler_command=None, timeout=None, build_options=None):
    """Build current compiler sources with Cargo, then scan the complete model."""
    root = Path(root).resolve()
    timeout = node_timeout(timeout)
    command = list(compiler_command) if compiler_command is not None else _command(root, build_options)
    command += ["scan", "--root", str(root), "--json", "--report-only"]
    if revision is not None:
        command += ["--revision", revision]
    env = _environment(compiler_command, options=build_options)
    temporary = None
    context_temporary = None
    try:
        if overlay is not None:
            normalized = {normalize(root, key): value for key, value in overlay.items()}
            if any(value is not None and not isinstance(value, str) for value in normalized.values()):
                raise CompilerFailure("overlay content must be UTF-8 text or null for deletion")
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".json", delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(normalized, stream, ensure_ascii=False)
            command += ["--overlay", str(temporary)]
        if context is not None:
            if not isinstance(context, dict):
                raise CompilerFailure("compiler change context must be a JSON object")
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".json", delete=False) as stream:
                context_temporary = Path(stream.name)
                json.dump(context, stream, ensure_ascii=False)
            command += ["--context", str(context_temporary)]
        # Inherited pipe writers can outlive the compiler and defeat its deadline.
        with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as output, tempfile.TemporaryFile(mode="w+", encoding="utf-8") as errors:
            result = subprocess.run(command, cwd=root, env=env, stdout=output, stderr=errors, timeout=timeout)
            output.seek(0)
            errors.seek(0)
            stdout, stderr = output.read(), errors.read()
        if result.returncode:
            raise CompilerFailure(f"compiler exited {result.returncode}: {stderr.strip() or stdout.strip()}")
        try:
            report = json.loads(stdout)
        except ValueError as exc:
            raise CompilerFailure("compiler returned invalid JSON") from exc
        return _validate_report(report, root)
    except (OSError, subprocess.TimeoutExpired, UnicodeError) as exc:
        raise CompilerFailure(f"compiler invocation failed: {exc}") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        if context_temporary is not None:
            context_temporary.unlink(missing_ok=True)


# Documentation/data assets have no executable language. Every other uncovered
# extension is an error, including extensionless scripts and unknown languages.
NON_CODE = {".md", ".rst", ".txt", ".patch", ".sha256", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".woff2"}


def _machine_context(root, context):
    supplied = dict(context or {})
    selected_rules = supplied.pop("intent_rule_set", None)
    if selected_rules:
        if isinstance(selected_rules, str):
            rule_path = Path(selected_rules)
            if not rule_path.is_absolute():
                rule_path = Path(root) / rule_path
                if not rule_path.is_file() and selected_rules.replace("\\", "/") == "tools/archhub-compiler/rules.json":
                    owner = Path(__file__).resolve().parents[2]
                    installed_rules = owner / "runtime" / "acompiler" / "rules.json"
                    rule_path = installed_rules if installed_rules.is_file() else owner / selected_rules
            selected_rules = json.loads(rule_path.read_text(encoding="utf-8"))
        if not isinstance(selected_rules, dict):
            raise CompilerFailure("intent rule set must select a JSON machine-rule object")
        supplied["machine_rule_parameters"] = selected_rules.get("machine_rules", selected_rules)
        if isinstance(selected_rules.get("deviation"), dict):
            supplied["deviation_parameters"] = selected_rules["deviation"]
    return supplied


def check_artifact(root, pending, context=None, *, compiler_command=None, timeout=None, build_options=None):
    """Run the same binary's typed pending artifact and intent passes."""
    root = Path(root).resolve()
    timeout = node_timeout(timeout)
    command = list(compiler_command) if compiler_command is not None else _command(root, build_options)
    from tools.pipeline.record_observation import load_history, reserve_notices
    historical = load_history(root)
    prepared = _machine_context(root, context)
    if "rules" in prepared:
        prepared["artifact_rules"] = prepared.pop("rules")
    for key in ("scope", "rules", "history", "deviation_state", "metrics"):
        prepared.pop(key, None)
    prepared.update(files=[str(pending.get("target", ""))], history=historical.get("history", []),
                    deviation_state=historical.get("authors", {}).get(prepared.get("author", ""), {}).get("deviation_state", {}),
                    day=datetime.now(timezone.utc).date().isoformat())
    prepared["alert_state"] = prepared["deviation_state"].get("alert_state", {})
    prepared["metrics"] = {"files": len(prepared["files"]), "lines": len(json.dumps(pending.get("content"), ensure_ascii=False, indent=2).splitlines()),
                           "tests_removed": 0, "languages": len({pending.get("format", pending.get("kind", ""))}),
                           "scope_spread": len({str(pending.get("target", "")).split(":", 1)[0]})}
    env = _environment(compiler_command, options=build_options)
    paths = []
    try:
        for value in (pending, prepared):
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".json", delete=False) as stream:
                paths.append(Path(stream.name))
                json.dump(value, stream, ensure_ascii=False)
        command += ["artifact", "--payload", str(paths[0]), "--context", str(paths[1]),
                    "--authority-root", str(root), "--authority-revision", "HEAD", "--json", "--report-only"]
        result = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True, encoding="utf-8", errors="strict", timeout=timeout)
        if result.returncode:
            raise CompilerFailure(f"artifact compiler exited {result.returncode}: {result.stderr.strip()}")
        try:
            report = _validate_report(json.loads(result.stdout), root, artifact=True)
        except ValueError as exc:
            raise CompilerFailure("artifact compiler returned invalid JSON") from exc
        prepared["metrics"].update(rule_hits=sum(row["code"] not in {"E0100", "E0101", "E0102", "E0200"} for row in report["diagnostics"]),
                                   ratchet_deltas=sum(sum(languages.values()) for code, languages in report["counts"].items()
                                                     if code not in {"E0100", "E0101", "E0102", "E0200"}))
        reserve_notices(root, prepared, report.get("observation"))
        return {"ok": not report["diagnostics"], "diagnostics": report["diagnostics"], "counts": report["counts"],
                "observation": report.get("observation"), "context": prepared}
    except (OSError, UnicodeError, subprocess.SubprocessError) as exc:
        raise CompilerFailure(f"artifact compiler invocation failed: {exc}") from exc
    finally:
        for path in paths:
            path.unlink(missing_ok=True)


def renamed_sources(root, revision, selected, candidate, compiler_command=None, timeout=None):
    before = git(root, "ls-tree", "-r", "--name-only", "-z", revision).decode("utf-8").split("\0")
    if not any(path in before and candidate.get(path, "") is None for path in selected) or not any(
            path not in before and candidate.get(path) is not None for path in selected):
        return {}
    paths = sorted(set(filter(None, before)) | set(selected))
    command = list(compiler_command) if compiler_command is not None else _command(root)
    result = subprocess.run(command + ["source-identities"], input=json.dumps(paths), cwd=root,
                            env=_environment(compiler_command), capture_output=True, text=True,
                            encoding="utf-8", timeout=node_timeout(timeout))
    if result.returncode:
        raise CompilerFailure("compiler source identity failed: " + result.stderr.strip())
    identities = json.loads(result.stdout)
    if set(identities) != set(paths) or any(not isinstance(value, str) for value in identities.values()):
        raise CompilerFailure("compiler source identity inventory differs")
    predecessors = {}
    for path in filter(None, before):
        identity = identities[path]
        if identity in predecessors:
            raise CompilerFailure("ambiguous original source identity: " + identity)
        predecessors[identity] = path
    successors = {}
    renamed = {}
    for path in paths:
        present = candidate[path] is not None if path in candidate else path in before
        if not present:
            continue
        identity = identities[path]
        if identity in successors:
            raise CompilerFailure("ambiguous candidate source identity: " + identity)
        successors[identity] = path
        prior = predecessors.get(identity)
        if path in selected and prior in selected and prior != path:
            renamed[path] = prior
    # A moved file (git's own rename detection, same content give or take its edits) keeps its
    # predecessor's baseline: only its changed lines are new, exactly as for an identity rename.
    fields = git(root, "diff", "-M50%", "--name-status", "-z", revision, "HEAD").decode("utf-8").split("\0")
    taken, index = set(renamed.values()), 0
    while index < len(fields) and fields[index]:
        status = fields[index]
        width = 2 if status[:1] in ("R", "C") else 1          # rename/copy records carry two paths
        if status[:1] == "R" and index + 2 < len(fields):
            prior, path = fields[index + 1], fields[index + 2]
            if (path in selected and prior in selected and path not in renamed and prior not in taken
                    and candidate.get(path, "") is not None and candidate.get(prior, "") is None):
                renamed[path] = prior
                taken.add(prior)
        index += 1 + width
    return renamed


def change_context(root, selected, candidate, revision, context, *, patch_scope=None, committed_history=False, renamed=None):
    """Bind intent to real changed paths and repository-owned author history."""
    import difflib
    import re
    supplied = _machine_context(root, context)
    author = supplied.get("author")
    if not author:
        author = git(root, "var", "GIT_AUTHOR_IDENT").decode("utf-8").split("<", 1)[0].strip()
    renamed = renamed or {}
    added = removed = tests_removed = 0
    originals = revision_blobs(root, revision, [renamed.get(path, path) for path in selected if path not in renamed.values()])
    for path in selected:
        if path in renamed.values():
            continue
        original_path = renamed.get(path, path)
        present = originals[original_path] is not None
        before = originals[original_path].decode("utf-8", errors="replace") if present else ""
        after = candidate.get(path)
        if path not in candidate:
            target = root / path
            after = target.read_text(encoding="utf-8", errors="replace") if target.is_file() else ""
        ranges = []
        for line in difflib.unified_diff(before.splitlines(), (after or "").splitlines(), n=0):
            hunk = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", line)
            if hunk:
                start, length = int(hunk[1]), int(hunk[2] or 1)
                if length:
                    ranges.append([start, start + length - 1])
            elif line.startswith("+") and not line.startswith("+++"):
                added += 1
            elif line.startswith("-") and not line.startswith("---"):
                removed += 1
                tests_removed += bool(re.match(r"\s*(?:async\s+)?def\s+test_|\s*(?:test|it)\s*\(", line[1:]))
        if patch_scope is not None:
            patch_scope[path] = {"new": not present, "ranges": ranges}
    from tools.pipeline.record_observation import load_history
    historical = load_history(root, revision, include_local=not committed_history)
    # Scopes and machine rules are resolved by the binary's authoritative
    # rules.json, never a caller-provided permission list.
    for key in ("scope", "rules", "history", "deviation_state", "metrics"):
        supplied.pop(key, None)
    supplied.update(author=author, intent=supplied.get("intent", ""), files=selected,
        metrics={"files": len(selected), "lines": added + removed, "tests_removed": tests_removed,
                 "languages": len({Path(path).suffix.lower() for path in selected}),
                 "scope_spread": len({path.split("/", 1)[0] for path in selected})},
        history=historical.get("history", []),
        deviation_state=historical.get("authors", {}).get(author, {}).get("deviation_state", {}),
        day=datetime.now(timezone.utc).date().isoformat())
    events = list(supplied.get("conduct_events", [])) if isinstance(supplied.get("conduct_events", []), list) else None
    for path in selected:
        name = Path(path).name
        if not (name.startswith("RESULT-") and name.endswith(".md") or name.endswith(".founder.md")):
            continue
        after = candidate.get(path)
        if after is None and (Path(root) / path).is_file():
            after = (Path(root) / path).read_text(encoding="utf-8")
        if after is None:
            continue
        if events is None:
            continue  # malformed supplied events remain visible to the compiler
        if name.endswith(".founder.md"):
            events.append({"kind": "report", "channel": "founder", "text": after})
        else:
            ledger_text = candidate.get("tasks.json") if "tasks.json" in selected else None
            if ledger_text is None and git(root, "ls-tree", "-z", revision, "--", "tasks.json"):
                ledger_text = git(root, "show", f"{revision}:tasks.json").decode("utf-8")
            ledger = json.loads(ledger_text or "{}")
            if isinstance(ledger, list):  # GVS5H ledger: a list of tasks; the next one is the first not done
                pending = [t for t in ledger if isinstance(t, dict) and str(t.get("state", "")).lower() not in ("done", "pass", "landed")]
                ledger = {"next_task": (pending[0].get("id") if pending else None), "owner": None}
            elif not isinstance(ledger, dict):
                ledger = {}
            events.append({"kind": "lane_result", "done": bool(re.search(r"(?mi)^State:\s*DONE\s*$", after)),
                "ledger": {"next_task": ledger.get("next_task"), "owner": ledger.get("owner")}})
    if events is not None and events:
        supplied["conduct_events"] = events
    supplied["alert_state"] = supplied["deviation_state"].get("alert_state", {})
    return supplied


def check_files(root, paths, overlay=None, *, revision="HEAD", context=None, compiler_command=None, timeout=None, build_options=None, committed_history=False):
    root = Path(root).resolve()
    selected = selected_files(root, files=paths)
    overlay_paths = {normalize(root, p) for p in (overlay or {})}
    if overlay_paths - set(selected):
        raise CompilerFailure("pending overlay contains files outside the owned change set")
    if not selected:
        return {"ok": True, "selected": [], "diagnostics": [], "counts": {}}
    revision = git(root, "rev-parse", "--verify", revision).decode("ascii").strip()
    # Compose the candidate from an immutable Git revision plus only owned
    # changes. Unstaged/untracked work by another session never enters it.
    candidate = {normalize(root, path): value for path, value in (overlay or {}).items()}
    for path in selected:
        if path not in candidate:
            target = root / path
            if target.is_file() and target.suffix.lower() not in NON_CODE:
                try:
                    candidate[path] = target.read_text(encoding="utf-8")
                except (OSError, UnicodeError) as exc:
                    raise CompilerFailure(f"cannot read owned source {path}: {exc}") from exc
            elif not target.exists():
                candidate[path] = None
    renamed = renamed_sources(root, revision, selected, candidate, compiler_command, timeout)
    patch_scope = {}
    prepared_context = change_context(root, selected, candidate, revision, context, patch_scope=patch_scope,
                                      committed_history=committed_history, renamed=renamed)
    # Source-intent rules must see the same declared files on both revisions.
    # Caller flags/machine overrides are candidate-only, so invalid change
    # metadata cannot establish its own baseline.
    baseline_context = {key: prepared_context[key] for key in ("author", "intent", "files", "why") if key in prepared_context}
    original = scan_model(root, revision=revision, context=baseline_context,
                          compiler_command=compiler_command, timeout=timeout, build_options=build_options)
    prepared_context["baseline_counts"] = original["counts"]
    report = scan_model(root, overlay=candidate, revision=revision, context=prepared_context,
                        compiler_command=compiler_command, timeout=timeout, build_options=build_options)
    selected_set = set(selected)
    def on_changed_line(item):
        scope = patch_scope.get(item["file"])
        return scope is not None and (scope["new"] or any(
            start <= item["line"] <= end for start, end in scope["ranges"]))

    # Context/authority findings are about the whole change, even if their
    # display anchor is unchanged line 1. They can never be diff-filtered away.
    successors = {before: after for after, before in renamed.items()}
    original_intent = Counter((d["code"], successors.get(d["file"], d["file"]), d["message"])
                              for d in original["diagnostics"] if d["code"] == "E0102")
    diagnostics = []
    for item in report["diagnostics"]:
        context_error = item["code"] in {"E0100", "E0101", "E0200"}
        if item["code"] == "E0102":
            intent_key = tuple(item[key] for key in ("code", "file", "message"))
            context_error = not original_intent[intent_key]
            original_intent[intent_key] -= bool(original_intent[intent_key])
        if on_changed_line(item) or context_error:
            diagnostics.append(item)
    before_counts = Counter((successors.get(d["file"], d["file"]), d["code"]) for d in original["diagnostics"])
    after_counts = Counter((d["file"], d["code"]) for d in report["diagnostics"])
    file_regressions = [{"file": path, "code": code, "baseline": before_counts[path, code], "current": count}
                        for (path, code), count in sorted(after_counts.items())
                        if path in selected_set and count > before_counts[path, code]]
    regressions = compare_counts(report["counts"], original["counts"])

    outside = [d for d in report["diagnostics"] if d["file"] not in selected_set]
    if outside:
        # A changed reader/socket can cause a diagnostic in an unchanged
        # catalogue/wire. Compare semantic identities, not shifted line numbers.
        def identity(item):
            import re
            message = item['message']
            if item['code'] == 'E0001':
                owner = re.fullmatch(r'multiple owners of `([^`]+)` \(other: .+:\d+\)', message)
                if owner is not None:
                    message = 'multiple owners of `%s`' % owner[1]
            return item['code'], item['language'], successors.get(item['file'], item['file']), message
        existing = Counter(identity(item) for item in original["diagnostics"])
        for item in outside:
            key = identity(item)
            if existing[key]:
                existing[key] -= 1
            else:
                diagnostics.append(dict(item, caused_by=selected))
    covered = {f["file"] for f in report["files"]}
    for path in selected:
        if path not in covered and candidate.get(path) is not None and Path(path).suffix.lower() not in NON_CODE:
            diagnostics.append({"code": "E0010", "language": "unknown", "file": path, "line": 1, "column": 1,
                                "message": "file has no compiler rule-set coverage", "help": "register a grammar and rule set"})
    prepared_context["metrics"]["rule_hits"] = sum(item["file"] in selected_set for item in report["diagnostics"])
    prepared_context["metrics"]["ratchet_deltas"] = sum(max(0, count - original["counts"].get(code, {}).get(language, 0))
        for code, languages in report["counts"].items() for language, count in languages.items())
    from tools.pipeline.record_observation import reserve_notices
    reserve_notices(root, prepared_context, report.get("observation"))
    return {"ok": not diagnostics and not file_regressions and not regressions,
            "selected": selected, "diagnostics": diagnostics, "counts": report["counts"],
            "file_regressions": file_regressions, "regressions": regressions,
            "changed_lines": {path: scope["ranges"] for path, scope in patch_scope.items()},
            "observation": report.get("observation"), "context": prepared_context}


def check_changed(root, *, files=None, session_record=None, base=None, commit=None, context=None,
                  compiler_command=None, timeout=None):
    paths = selected_files(root, files=files, session_record=session_record, base=base, commit=commit)
    if context is None and session_record is not None:
        text = Path(session_record).read_text(encoding="utf-8-sig")
        if text.lstrip().startswith("{"):
            context = json.loads(text)
    if context is None and commit is not None:
        from tools.pipeline.pre_commit import trailers
        context = trailers(git(root, "show", "-s", "--format=%B", commit).decode("utf-8"))
        context["author"] = git(root, "show", "-s", "--format=%an", commit).decode("utf-8").strip()
    if paths and files is None and session_record is None and base is None:
        # An index/commit gate must never validate a different worktree version.
        differences = git(root, "diff", "--name-only", "-z", commit, "--") if commit else git(root, "diff", "--name-only", "-z", "--")
        dirty = set(differences.decode("utf-8").split("\0")) & set(paths)
        if dirty:
            raise CompilerFailure("selected files differ from checked revision/index: " + ", ".join(sorted(dirty)))
    revision = base or (f"{commit}^" if commit else "HEAD")
    overlay = None
    if paths and files is None and session_record is None and base is None:
        # Read immutable commit/index blobs after selection. A concurrent edit
        # cannot substitute unstaged bytes for the tree admission certifies.
        overlay = {}
        blobs = revision_blobs(root, commit, paths)
        for path in paths:
            raw = blobs[path]
            if raw is None:
                overlay[path] = None
                continue
            try:
                overlay[path] = raw.decode("utf-8")
            except UnicodeError as exc:
                if Path(path).suffix.lower() not in NON_CODE:
                    raise CompilerFailure(f"owned source is not UTF-8: {path}") from exc
    return check_files(root, paths, overlay=overlay, revision=revision, context=context, compiler_command=compiler_command, timeout=timeout)


def compare_counts(counts, baseline):
    """No missing code/language key can inherit a passing current value."""
    if not isinstance(baseline, dict):
        raise CompilerFailure("invalid compiler baseline counts")
    for code, languages in baseline.items():
        if not isinstance(code, str) or not isinstance(languages, dict) or any(
                not isinstance(language, str) or type(value) is not int or value < 0
                for language, value in languages.items()):
            raise CompilerFailure("invalid compiler baseline count")
    regressions = []
    for code, languages in counts.items():
        for language, current in languages.items():
            previous = baseline.get(code, {}).get(language, 0)
            if type(previous) is not int or previous < 0:
                raise CompilerFailure(f"invalid compiler baseline count: {code}/{language}")
            if current > previous:
                regressions.append({"code": code, "language": language, "baseline": previous, "current": current})
    return regressions


def check_ratchet(root, baseline=None, *, compiler_command=None, timeout=None):
    root = Path(root).resolve()
    baseline = Path(baseline) if baseline else root / ("05.EVIDENCE" if (root / "05.EVIDENCE").is_dir() else "evidence") / "acompiler.json"
    data = json.loads(baseline.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise CompilerFailure("invalid compiler baseline schema_version")
    report = scan_model(root, compiler_command=compiler_command, timeout=timeout)
    regressions = compare_counts(report["counts"], data["counts"])
    return {"ok": not regressions, "regressions": regressions, "counts": report["counts"]}


def print_diagnostics(result):
    for item in result.get("file_regressions", []):
        print(f"ACOMPILER FILE FAIL: {item['file']} {item['code']} {item['baseline']} -> {item['current']}")
    for item in result.get("regressions", []):
        print(f"ACOMPILER BUCKET FAIL: {item['code']}/{item['language']} {item['baseline']} -> {item['current']}")
    for diagnostic in result["diagnostics"]:
        print(f"error[{diagnostic['code']}]: {diagnostic['message']}\n"
              f" --> {diagnostic['file']}:{diagnostic['line']}:{diagnostic['column']}\n"
              f" note: {diagnostic.get('note', diagnostic['code'])}\n"
              f" help: {diagnostic['help']}")
        if diagnostic.get("caused_by"):
            print(" note: introduced by owned changes: " + ", ".join(diagnostic["caused_by"]))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(PRODUCT_ROOT))
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--changed", action="store_true", help="staged files only (default)")
    scope.add_argument("--files", nargs="+")
    scope.add_argument("--session-record")
    scope.add_argument("--base")
    scope.add_argument("--commit")
    parser.add_argument("--whole-tree", action="store_true", help="also enforce the code/language legacy ratchet")
    parser.add_argument("--baseline")
    parser.add_argument("--context", help="JSON author/intent/why; compiler binds actual files and authoritative scope")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        context_path = args.context or os.environ.get("ARCHHUB_INTENT_CONTEXT")
        context = json.loads(Path(context_path).read_text(encoding="utf-8")) if context_path else None
        result = check_changed(args.root, files=args.files, session_record=args.session_record, base=args.base, commit=args.commit, context=context)
        if args.whole_tree:
            result["ratchet"] = check_ratchet(args.root, args.baseline)
            result["ok"] = result["ok"] and result["ratchet"]["ok"]
        if args.json:
            print(json.dumps(result, ensure_ascii=False))
        else:
            print_diagnostics(result)
            for regression in result.get("ratchet", {}).get("regressions", []):
                print(f"ACOMPILER RATCHET FAIL: {regression['code']}/{regression['language']} "
                      f"{regression['baseline']} -> {regression['current']}")
            print("ACOMPILER PASS" if result["ok"] else "ACOMPILER FAIL")
        return 0 if result["ok"] else 1
    except (CompilerFailure, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc), "diagnostics": []}))
        else:
            print(f"error[E0010]: ACOMPILER REFUSED: {exc}\n help: repair the compiler/input contract before retrying")
        return 2


if __name__ == "__main__":
    sys.exit(main())
