"""Point this install's Revit add-in and AutoCAD bundle at the newest bridge.

The installer runs this after the new DLLs are in
bridges/<host>/<year>/<build-id>/. It never starts Revit or AutoCAD. An
unsupported Revit year's ArchHub manifests are retired; changes take effect
at the next host start. Retirement failures are reported to setup.
"""
from __future__ import annotations

import sys
import hashlib
import json
import os
import re
import tempfile
import time
from pathlib import Path, PurePosixPath


ROOTS = {"nodelang", "studio", "app", "bridges"}
STATE_DIRS = {"settings", "workshop", "logs", "sessions", "recent", "checkpoints", ".venv"}
HEADER = "ARCHHUB_INSTALLED_SOURCE_MANIFEST_V1"
RECEIPT = "installed-source-state.json"
DATA_TYPES = {".archhub", ".db", ".sqlite", ".sqlite3", ".json", ".yaml", ".yml", ".toml", ".log"}
PROGRAM_TYPES = {".py", ".pyc", ".pyd", ".pyi", ".js", ".jsx", ".mjs", ".cjs", ".css", ".map"}
LEGACY_DIRS = ('_config_backup_2026-06-01', '_deploy_backup_20260623-002259',
               '_syncrung_backup_20260623-005335', '.retired-v1-docs')
LEGACY_CUTOFF = 1782864000  # 2026-07-01 UTC, exclusive.
LEGACY_NAMES = {'settings.json', 'config.json', 'version.json', 'build_metadata.json',
                'host_artifacts.json', 'readme.md', 'claude.md', 'agents.md', 'spec.md',
                'authority.md', 'founder_mandates.md', 'failure_log.md', 'decisions.md',
                'requirements.txt', 'notice', 'build_id', 'archhub.bat', 'archhub.vbs',
                'quickstart.md', 'version', '_config.yml'}


def cleanup_legacy(root):
    """Exact founder-authorized remnants; unknown or recent contents keep the whole folder."""
    for name in LEGACY_DIRS:
        folder = root / name
        if not folder.exists():
            continue
        entries = []
        reasons = []
        if not _plain(folder) or not folder.is_dir():
            reasons.append('redirected or non-directory target')
        else:
            # Do not traverse links, even to produce the required inventory.
            for directory, dirs, names in os.walk(folder, followlinks=False, onerror=lambda error:
                    reasons.append('unreadable directory ' + str(error.filename))):
                for child in list(dirs):
                    path = Path(directory) / child
                    if not plain(path) or child.casefold() in STATE_DIRS | {'keys'}:
                        reasons.append('protected/redirected directory ' + path.relative_to(root).as_posix())
                        if not plain(path):
                            dirs.remove(child)
                for child in names:
                    path = Path(directory) / child
                    relative = path.relative_to(root).as_posix()
                    entries.append(path)
                    if not plain(path) or not path.is_file():
                        reasons.append('redirected/non-file ' + relative)
                    elif path.stat().st_mtime >= LEGACY_CUTOFF:
                        reasons.append('newer file ' + relative)
                    elif (path.name.casefold() not in LEGACY_NAMES
                          and path.suffix.casefold() not in PROGRAM_TYPES | {'.ps1', '.iss', '.html'}
                          and not (name == '.retired-v1-docs' and path.relative_to(folder).parts[0] == 'docs'
                                   and (path.suffix.casefold() == '.md' or path.relative_to(folder).as_posix()
                                        in {'docs/_meta/freshness.json', 'docs/_meta/index.json'}))):
                        reasons.append('unknown/user file ' + relative)
        print('PRUNE LEGACY INVENTORY ' + name + ' ' + json.dumps(
            [path.relative_to(root).as_posix() for path in entries]), flush=True)
        if reasons:
            print('PRUNE legacy kept: ' + name + ' ' + '; '.join(reasons), flush=True)
            continue
        try:
            for path in entries:
                path.unlink()
            for directory, _, _ in os.walk(folder, topdown=False):
                Path(directory).rmdir()
        except OSError:
            print('PRUNE ' + name + ' deferred: in use by a running program', flush=True)
        else:
            print('PRUNE legacy removed ' + name, flush=True)
    for year in ('2020', '2023', '2024', '2025'):
        path = root / 'Revit' / year / 'RevitMCP.dll'
        if not _plain(path) or not path.is_file():
            continue
        try:
            path.unlink()
        except OSError:
            print('PRUNE Revit/' + year + '/RevitMCP.dll deferred: in use by a running program', flush=True)
            continue
        print('PRUNE Revit/' + year + '/RevitMCP.dll', flush=True)
        if not any(path.parent.iterdir()):
            path.parent.rmdir()
    # Also works when invoked as the installer's standalone script.
    if any(root.glob('*.log')) or (root / 'logs' / 'root').exists():
        from importlib import import_module
        rotation = import_module('nodelang.log_rotation' if __package__ else 'log_rotation')
        rotation.collect_root_logs(root)


def protected(relative):
    name = relative.name.casefold()
    base = re.sub(r"-(wal|shm)$", "", name)
    return (any(part.casefold() in STATE_DIRS for part in relative.parts)
            or PurePosixPath(base).suffix in DATA_TYPES)


def plain(path):
    return not path.is_symlink() and not path.is_junction()


def files(directory):
    if not plain(directory):
        return
    for entry in sorted(directory.iterdir()) if directory.exists() else []:
        if not plain(entry) or protected(entry):
            continue
        if entry.is_dir():
            yield from files(entry)
        elif entry.is_file():
            yield entry


def write_manifest(source, hosts, destination):
    """Mirror the installer's four product-root [Files] selections, including generated bytes."""
    rows = {}
    for path in files(source / "nodelang"):
        if ("__pycache__" in path.parts or path.suffix in {".pyc", ".pyo", ".key", ".pem"}
                or path.name == ".env" or path.name.startswith(".env.")
                or path.suffix in {".sqlite3", ".db"}
                or ".sqlite3-" in path.name or ".db-" in path.name):
            continue
        rows[path.relative_to(source).as_posix()] = path
    for name in ("__init__.py", "credential_lock.py", "secrets_store.py"):
        rows["app/" + name] = source / "app" / name
    for installed, original in (
        ("bridges/rhino/archhub_mcp.py", "bridges/rhino/archhub_mcp.py"),
        ("bridges/blender/archhub_mcp/__init__.py", "bridges/blender/archhub_mcp/__init__.py"),
        ("bridges/max/max_mcp_startup.py", "bridges/sources/max_mcp/max_mcp_startup.py"),
    ):
        rows[installed] = source / original
    for host in ("revit", "autocad"):
        for path in files(hosts / "bridges" / host):
            rows[path.relative_to(hosts).as_posix()] = path
    lines = [HEADER, "path\tsha256"]
    for relative, path in sorted(rows.items()):
        lines.append(relative + "\t" + hashlib.sha256(path.read_bytes()).hexdigest())
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")


def manifest_rows(raw):
    lines = raw.decode("utf-8").splitlines()
    if lines[:2] != [HEADER, "path\tsha256"]:
        raise ValueError("unsupported installed source manifest")
    rows = {}
    for line in lines[2:]:
        relative, digest = line.split("\t")
        if not valid_row(relative, digest) or relative.casefold() in rows:
            raise ValueError("invalid installed source manifest row")
        rows[relative.casefold()] = digest
    # Validate the complete manifest and copied payload before deleting anything.
    if not {name.split("/")[0] for name in rows} >= {"nodelang", "app", "bridges"}:
        raise ValueError("incomplete installed source manifest")
    return rows


def valid_row(relative, digest):
    path = PurePosixPath(relative)
    return (bool(path.parts) and path.parts[0] in ROOTS and not path.is_absolute()
            and not any(part in {".", ".."} or ":" in part or "\\" in part
                        or part.endswith((".", " ")) for part in path.parts)
            and path.as_posix() == relative and bool(re.fullmatch("[0-9a-f]{64}", digest)))


def legacy_program(relative, years):
    return (relative.suffix.casefold() in PROGRAM_TYPES
            or relative.suffix.casefold() == ".html" and "studio" in relative.parts[:-1]
            or relative.suffix.casefold() in {".dll", ".exe", ".addin"}
            and tuple(relative.parts[:3]) in years)


def save_receipt(root, raw, pending, years):
    state = {"manifest": raw.decode("utf-8"), "installed_at_ns": time.time_ns(),
             "pending_prune": pending, "bridge_years": sorted(years)}
    save_state(root, state)


def save_state(root, state):
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=root, delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(state, stream)
    try:
        os.replace(temporary, root / RECEIPT)
    finally:
        temporary.unlink(missing_ok=True)


def prepare(root, manifest, expected):
    """Record directory creation authority before Inno copies any host payload."""
    if root.absolute() != (Path(os.environ["LOCALAPPDATA"]) / "ArchHub").absolute() or not _plain(root):
        raise ValueError("PRUNE prepare refused: outside plain %LOCALAPPDATA%/ArchHub")
    raw = manifest.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("installed source manifest digest mismatch")
    rows = manifest_rows(raw)
    root.mkdir(parents=True, exist_ok=True)
    if not all(plain(root / name) for name in (RECEIPT, "source-manifest.tsv", "BUILD_ID")):
        raise ValueError("PRUNE prepare refused: redirected install metadata")
    if (root / RECEIPT).exists():
        state = json.loads((root / RECEIPT).read_text(encoding="utf-8"))
    else:
        old = root / "source-manifest.tsv"
        state = {"manifest": old.read_text(encoding="utf-8") if old.is_file() else None,
                 "installed_at_ns": (root / "BUILD_ID").stat().st_mtime_ns if (root / "BUILD_ID").is_file() else 0,
                 "pending_prune": {}, "bridge_years": []}
    years = set(state["bridge_years"])
    for name in rows:
        if re.match(r"^bridges/(revit|autocad)/20[0-9]{2}/", name):
            year = "/".join(PurePosixPath(name).parts[:3])
            if not (root / year).exists():
                years.add(year)
    state["bridge_years"] = sorted(years)
    save_state(root, state)


def prune(root, expected):
    # Never let an installer directory override broaden the deletion boundary.
    allowed = Path(os.environ["LOCALAPPDATA"]) / "ArchHub"
    if root.absolute() != allowed.absolute() or not _plain(root):
        raise ValueError("PRUNE refused: outside plain %LOCALAPPDATA%/ArchHub")
    for name in ("source-manifest.tsv", RECEIPT, "BUILD_ID"):
        if not plain(root / name):
            raise ValueError("PRUNE refused: redirected install metadata")
    raw = (root / "source-manifest.tsv").read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("installed source manifest digest mismatch")
    keep = manifest_rows(raw)
    for relative, digest in keep.items():
        path = root / relative
        if any(not plain(parent) for parent in (path, *path.parents) if parent != root.parent):
            raise ValueError("redirected installed payload")
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("installed payload differs from source manifest: " + relative)
    previous, pending, years = {}, {}, set()
    cutoff = (root / "BUILD_ID").stat().st_mtime_ns if (root / "BUILD_ID").is_file() else 0
    has_previous = (root / RECEIPT).exists()
    try:
        if has_previous:
            state = json.loads((root / RECEIPT).read_text(encoding="utf-8"))
            has_previous = state["manifest"] is not None
            if has_previous:
                previous = manifest_rows(state["manifest"].encode("utf-8"))
            cutoff = state["installed_at_ns"]
            if type(cutoff) is not int or cutoff < 0:
                raise ValueError("invalid previous install time")
            pending = state["pending_prune"]
            years = set(state["bridge_years"])
            if any(not re.fullmatch(r"bridges/(revit|autocad)/20[0-9]{2}", year) for year in years):
                raise ValueError("invalid installer-created bridge year")
            for name, row in pending.items():
                if (not valid_row(name, row["sha256"] or "0" * 64)
                        or type(row["mtime_ns"]) is not int):
                    raise ValueError("invalid deferred modification time")
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ValueError("PRUNE refused: invalid previous installed manifest/pending-prune list") from exc
    candidates = {name: digest for name, digest in previous.items() if name not in keep}
    candidates.update({name: row["sha256"] for name, row in pending.items() if name not in keep})
    if not has_previous and cutoff:
        for name in sorted(ROOTS):
            for path in files(root / name):
                relative = path.relative_to(root)
                key = relative.as_posix().casefold()
                if key not in keep and legacy_program(relative, {tuple(year.split("/")) for year in years}):
                    candidates[key] = None
    print("PRUNE DRY RUN " + json.dumps(sorted(candidates)), flush=True)
    forbidden = [name for name in candidates if protected(PurePosixPath(name))]
    if forbidden:
        print("PRUNE skipped: never-delete candidate " + json.dumps(forbidden), flush=True)
        deferred = {}
        for name, digest in candidates.items():
            path = root / name
            if not protected(PurePosixPath(name)) and _plain(path) and path.is_file():
                stamp = path.stat().st_mtime_ns
                if stamp <= cutoff:
                    deferred[name] = pending.get(name, {"sha256": digest, "mtime_ns": stamp})
        save_receipt(root, raw, deferred, years)
        return []
    deferred = {}
    removed = []
    for name, digest in sorted(candidates.items()):
        path = root / name
        if not _plain(path) or not path.is_file():
            continue
        stamp = path.stat().st_mtime_ns
        if stamp > cutoff or name in pending and stamp != pending[name]["mtime_ns"]:
            print("PRUNE kept: newer/changed file " + name, flush=True)
            continue
        try:
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest is not None and actual != digest:
                print("PRUNE kept: modified installed file " + name, flush=True)
                continue
            path.unlink()
        except PermissionError:
            deferred[name] = {"sha256": digest, "mtime_ns": stamp}
            print("PRUNE " + name + " deferred: in use by a running program", flush=True)
        else:
            removed.append(name)
            print("PRUNE " + name, flush=True)
    save_receipt(root, raw, deferred, years)
    cleanup_legacy(root)
    return removed


def _owned_manifest(path):
    from nodelang.host_broker_installation import (
        _read_registration, _parse_registration, _same_id, CLASS_NAME, VENDOR_ID,
        RegistrationRefused)
    try:
        _, text = _read_registration(path)
        entries = list(_parse_registration(path, text).iter("AddIn"))
        return bool(entries) and all(
            (_same_id(entry.findtext("AddInId", "")) or _same_id(entry.findtext("ClientId", "")))
            and entry.findtext("FullClassName", "").strip() == CLASS_NAME
            and entry.findtext("VendorId", "").strip() == VENDOR_ID for entry in entries)
    except RegistrationRefused:
        return False


def _plain(path):
    return all(not item.is_symlink() and not item.is_junction() for item in (path, *path.parents))


def addins_roots(environment):
    return [Path(environment[key]) / "Autodesk/Revit/Addins" for key in ("APPDATA", "ProgramData")]


def foreign_manifests(roots):
    result = {}
    for root in roots:
        if not _plain(root) or not root.exists():
            continue
        for year in sorted(root.iterdir()):
            if not re.fullmatch(r"20[0-9]{2}", year.name) or not year.is_dir() or not _plain(year):
                continue
            for path in sorted(year.iterdir()):
                if (path.name.casefold().endswith((".addin", ".addin.retired"))
                        and _plain(path) and path.is_file() and not _owned_manifest(path)):
                    result[path] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def cleanup_revit(root, roots, outcomes):
    for base in roots:
        if not _plain(base) or not base.exists():
            continue
        for year in sorted(base.iterdir()):
            if not re.fullmatch(r"20[0-9]{2}", year.name) or not year.is_dir() or not _plain(year):
                continue
            for path in sorted(year.iterdir()):
                if not _plain(path) or not path.is_file():
                    continue
                name = path.name.casefold()
                if name.endswith(".addin.retired") and _owned_manifest(path):
                    path.unlink()
                    print("REVIT CLEAN " + str(path), flush=True)


def retarget(root, setup, environment):
    roots = addins_roots(environment)
    before = foreign_manifests(roots)
    try:
        revit = setup.register_revit_add_ins(root)
        setup.register_autocad_add_ins(root)
        cleanup_revit(root, roots, revit)
        return 1 if any(row["status"] in ("failed", "partial_failure") for row in revit) else 0
    finally:
        changed = []
        for path, digest in before.items():
            after = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "missing"
            print("REVIT FOREIGN RECEIPT " + json.dumps({"path": str(path), "before_sha256": digest,
                  "after_sha256": after, "unchanged": digest == after}), flush=True)
            if digest != after:
                changed.append(str(path))
        if changed:
            raise RuntimeError("third-party Revit manifests changed: " + ", ".join(changed))


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) == 4 and argv[0] == "--manifest":
        write_manifest(Path(argv[1]), Path(argv[2]), Path(argv[3]))
        return 0
    if len(argv) == 4 and argv[0] == "--prepare":
        prepare(Path(argv[1]), Path(argv[2]), argv[3])
        return 0
    if len(argv) == 3 and argv[0] == "--prune":
        prune(Path(argv[1]), argv[2])
        return 0
    if len(argv) != 1:
        print("  host add-in: install directory required")
        return 1
    root = Path(argv[0])
    if not root.is_dir():
        print("  host add-in: install directory is missing")
        return 1
    sys.path.insert(0, str(root))
    import colleague_setup
    try:
        return retarget(root, colleague_setup, os.environ)
    except Exception as exc:  # noqa: BLE001 - the new DLLs are already installed
        print("  host add-in: not retargeted (%s)" % type(exc).__name__)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
