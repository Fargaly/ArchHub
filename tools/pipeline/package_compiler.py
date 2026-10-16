"""Build the static compiler from a verified release snapshot and stage its closure.

Called only by build_release.ps1 after its source-byte reconciliation. Build
artifacts stay in the originating checkout's ignored target, never the installer.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.pipeline.strict_check import CompilerFailure, COMPILER_SOURCES, RUNTIME_FILES, _environment, node_parameter, node_timeout, source_digest, system_dependencies, verify_runtime


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sources(root):
    return {name: sha(Path(root) / name) for name in COMPILER_SOURCES}


def dependency_closure(binary, env):
    tools = env.get("VCToolsInstallDir") or env.get("VCTOOLSINSTALLDIR")
    dumpbin = Path(tools or "") / "bin" / "Hostx64" / "x64" / "dumpbin.exe"
    if not tools or not dumpbin.is_file():
        raise CompilerFailure("static compiler dependency proof requires the selected MSVC dumpbin")
    result = subprocess.run([str(dumpbin), "/dependents", str(binary)], env=env, capture_output=True, text=True,
                            errors="replace", timeout=node_timeout())
    if result.returncode:
        raise CompilerFailure("compiler dependency inspection failed: " + result.stdout.strip())
    names = sorted({name.lower() for name in re.findall(r"(?mi)^\s+([A-Za-z0-9_.-]+\.dll)\s*$", result.stdout)})
    return system_dependencies(names)


def retained_license(root, package):
    crate = Path(root) / "tools" / "archhub-compiler"
    for line in (crate / "THIRD_PARTY.md").read_text(encoding="utf-8").splitlines():
        row = [cell.strip() for cell in line.split("|")]
        if len(row) != 7 or row[1:3] != [package["name"], package["version"]]:
            continue
        relative = "tools/archhub-compiler/" + row[3]
        if relative not in COMPILER_SOURCES or not row[3].startswith("licenses/"):
            raise CompilerFailure("retained package license is outside the verified source closure")
        vcs = json.loads((Path(package["manifest_path"]).parent / ".cargo_vcs_info.json").read_text(encoding="utf-8"))
        revision = vcs["git"]["sha1"]
        if not re.fullmatch(r"[0-9a-f]{40}", revision) or "/" + revision + "/" not in row[4]:
            raise CompilerFailure("retained package license has a different pinned upstream revision")
        source = Path(root) / relative
        if not re.fullmatch(r"[0-9a-f]{64}", row[5]) or sha(source) != row[5]:
            raise CompilerFailure("retained package license hash mismatch")
        return source
    raise CompilerFailure(f"missing license text for pinned package {package['name']} {package['version']}")


def licenses(metadata, rustup_home, root):
    entries = []
    for package in metadata["packages"]:
        if package["name"] == "archhub-compiler":
            continue
        folder = Path(package["manifest_path"]).parent
        files = {path for pattern in ("LICENSE*", "COPYING*", "NOTICE*") for path in folder.glob(pattern) if path.is_file()}
        if package.get("license_file"):
            files.add(folder / package["license_file"])
        if not files:
            files.add(retained_license(root, package))
        entries.append(f"\n=== {package['name']} {package['version']} ({package.get('license')}) ===\n")
        for path in sorted(files):
            entries.append(path.name + "\n" + path.read_text(encoding="utf-8", errors="replace") + "\n")
    toolchain = Path(rustup_home) / "toolchains" / "stable-x86_64-pc-windows-msvc" / "share" / "doc" / "rust"
    rust_licenses = [toolchain / name for name in ("LICENSE-APACHE", "LICENSE-MIT", "COPYRIGHT", "COPYRIGHT.html", "COPYRIGHT-library.html")
                     if (toolchain / name).is_file()]
    if not rust_licenses:
        raise CompilerFailure("Rust toolchain redistribution license texts are missing")
    for path in rust_licenses:
        entries.append("\n=== Rust standard library " + path.name + " ===\n" + path.read_text(encoding="utf-8", errors="replace") + "\n")
    return "".join(entries)


def package(root, toolchain_root):
    root, toolchain_root = Path(root).resolve(), Path(toolchain_root).resolve()
    crate = root / "tools" / "archhub-compiler"
    before = sources(root)
    env = _environment(owner=toolchain_root)
    env.pop("CARGO_ENCODED_RUSTFLAGS", None)
    env["RUSTFLAGS"] = str(node_parameter("compiler_rustflags"))
    if env["RUSTFLAGS"] != "-C target-feature=+crt-static":
        raise CompilerFailure("installer compiler node flags must produce a static CRT")
    cargo = toolchain_root.parent / "rust" / "cargo" / "bin" / "cargo.exe"
    target = toolchain_root / "tools" / "archhub-compiler" / "target" / "package-static"
    jobs = int(node_parameter("compiler_jobs"))
    if jobs <= 0:
        raise CompilerFailure("compiler jobs node parameter must be positive")
    command = [str(cargo), "build", "--release", "--locked", "--jobs", str(jobs), "--manifest-path", str(crate / "Cargo.toml"), "--target-dir", str(target)]
    subprocess.run(command, cwd=root, env=env, check=True, timeout=node_timeout())
    executable = target / "release" / "archhub-compiler.exe"
    dlls = dependency_closure(executable, env)
    metadata = subprocess.run([str(cargo), "metadata", "--locked", "--format-version", "1", "--manifest-path", str(crate / "Cargo.toml")],
        cwd=root, env=env, capture_output=True, text=True, encoding="utf-8", check=True, timeout=node_timeout())
    license_text = licenses(json.loads(metadata.stdout), env["RUSTUP_HOME"], root)
    if sources(root) != before:
        raise CompilerFailure("compiler source snapshot changed during static build")
    runtime = root / "runtime" / "acompiler"
    if runtime.exists():
        raise CompilerFailure("verified snapshot already contains generated compiler output")
    runtime.mkdir(parents=True)
    shutil.copyfile(executable, runtime / "archhub-compiler.exe")
    shutil.copyfile(crate / "rules.json", runtime / "rules.json")
    shutil.copyfile(root / "NOTICE", runtime / "NOTICE")
    (runtime / "LICENSES.txt").write_text(license_text, encoding="utf-8")
    provenance = {"schema_version": 1, "source_sha256": source_digest(before), "sources": before,
        "executable_sha256": sha(runtime / "archhub-compiler.exe"), "rules_sha256": sha(runtime / "rules.json"),
        "notice_sha256": sha(runtime / "NOTICE"), "licenses_sha256": sha(runtime / "LICENSES.txt"),
        "runtime_files": {name: sha(root / name) for name in RUNTIME_FILES},
        "crt": "static", "rustflags": env["RUSTFLAGS"], "windows_dlls": dlls}
    (runtime / "provenance.json").write_text(json.dumps(provenance, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    verify_runtime(root)
    return provenance


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--toolchain-root")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.verify:
            print(verify_runtime(args.root))
        elif args.toolchain_root:
            print(json.dumps(package(args.root, args.toolchain_root), sort_keys=True))
        else:
            raise CompilerFailure("static compiler build requires the originating toolchain root")
        return 0
    except (CompilerFailure, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print(f"ACOMPILER PACKAGE REFUSED: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
