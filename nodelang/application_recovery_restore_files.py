"""Prepare an exact-byte restore folder; owner admission and startup are separate.

Only a complete format-1 physical recovery directory is accepted. Its manifest
is evidence to verify, never graph/content authority. Neither the source recovery
folder nor a live application directory is modified or replaced.
"""
from contextlib import closing
import hashlib
import json
import math
import os
from pathlib import Path, PureWindowsPath
import re
import sqlite3
import stat
import time
import uuid

from .application_recovery_files import (
    _FILE_NAMES, _MANIFEST_BYTES, _METADATA_BYTES, _check_file,
    _check_stage_files, _cleanup_stage, _create_file, _file_evidence,
    _json_bytes, _require_disk_reserve,
)


_SIDE_SUFFIXES = ("-journal", "-wal", "-shm")
_RESERVED_NAMES = {"con", "prn", "aux", "nul", "clock$", "conin$", "conout$"} | {
    prefix + number for prefix in ("com", "lpt") for number in "123456789\u00b9\u00b2\u00b3"}


def _strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("restore manifest contains a duplicate field")
        result[key] = value
    return result


def _nonfinite(value):
    raise ValueError("restore manifest contains a nonfinite number")


def _plain_path(value):
    path = Path(value).absolute()
    if ".." in path.parts or path.is_symlink() or path.resolve(strict=False) != path:
        raise ValueError("restore path contains an alias or traversal")
    return path


def _file_identity(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError("restore file must be regular and without aliases: %s" % path)
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _directory_identity(path):
    if path.is_symlink() or path.resolve(strict=True) != path:
        raise ValueError("restore source directory identity changed")
    info = path.stat()
    if not stat.S_ISDIR(info.st_mode):
        raise NotADirectoryError(path)
    return info.st_dev, info.st_ino


def _read_manifest(directory):
    path = directory / "recovery.json"
    identity = _file_identity(path)
    if identity[2] > _MANIFEST_BYTES:
        raise ValueError("restore manifest exceeds its byte budget")
    with path.open("rb") as stream:
        raw = stream.read(_MANIFEST_BYTES + 1)
    if len(raw) > _MANIFEST_BYTES or _file_identity(path) != identity:
        raise ValueError("restore manifest changed while reading")
    manifest = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_object,
                          parse_constant=_nonfinite)
    if type(manifest) is not dict or set(manifest) != {"format", "files", "metadata"}:
        raise ValueError("restore manifest fields are invalid")
    if type(manifest["format"]) is not int or manifest["format"] != 1:
        raise ValueError("unsupported restore manifest format")
    files = manifest["files"]
    if type(files) is not dict or set(files) not in ({"graph"}, {"graph", "content"}):
        raise ValueError("restore manifest file roles are invalid")
    for role, description in files.items():
        if type(description) is not dict or set(description) != {"name", "size_bytes", "sha256"}:
            raise ValueError("restore manifest file fields are invalid")
        if description["name"] != _FILE_NAMES[role]:
            raise ValueError("restore manifest source filename is invalid")
        if type(description["size_bytes"]) is not int or description["size_bytes"] < 100:
            raise ValueError("restore manifest file size is invalid")
        if type(description["sha256"]) is not str or re.fullmatch(r"[0-9a-f]{64}", description["sha256"]) is None:
            raise ValueError("restore manifest file digest is invalid")
    if type(manifest["metadata"]) is not dict:
        raise ValueError("restore manifest metadata must be an object")
    _json_bytes(manifest["metadata"], _METADATA_BYTES)
    return manifest, hashlib.sha256(raw).hexdigest(), identity


def _output_names(names, roles):
    if type(names) is not dict or set(names) != set(roles):
        raise ValueError("restore output names must match the exact source roles")
    folded = set()
    for name in names.values():
        if (type(name) is not str or not name or name in {".", ".."}
                or name[-1] in " ." or any(ord(character) < 32 or character in '<>:"/\\|?*' for character in name)
                or PureWindowsPath(name).name != name
                or len(name.encode("utf-16-le")) > 510):
            raise ValueError("restore output filename is not a safe basename")
        normalized = name.casefold()
        if (normalized.split(".", 1)[0].rstrip(" .") in _RESERVED_NAMES
                or normalized in {"restoration.json", "recovery.json"}
                or normalized.endswith(_SIDE_SUFFIXES) or normalized in folded):
            raise ValueError("restore output filenames collide or are reserved")
        folded.add(normalized)
    if any(name + suffix in folded for name in folded for suffix in _SIDE_SUFFIXES):
        raise ValueError("restore output filenames collide with SQLite sidecars")
    return dict(names)


def _check_source(directory, directory_identity, identities, required_names):
    if _directory_identity(directory) != directory_identity:
        raise ValueError("restore source directory identity changed")
    found = set()
    with os.scandir(directory) as entries:
        for entry in entries:
            if entry.name not in required_names or not entry.is_file(follow_symlinks=False):
                raise ValueError("restore source contains an unexpected file: %s" % entry.path)
            found.add(entry.name)
    if found != required_names:
        raise ValueError("restore source is missing a required file")
    for name, expected in identities.items():
        if _file_identity(directory / name) != expected:
            raise ValueError("restore source file changed: %s" % (directory / name))


def _hash_source(path, expected, identity, check_budget):
    digest, size = hashlib.sha256(), 0
    with path.open("rb") as stream:
        while True:
            check_budget()
            block = stream.read(min(1024 * 1024, expected["size_bytes"] - size + 1))
            if not block:
                break
            size += len(block)
            if size > expected["size_bytes"]:
                raise ValueError("restore source file size changed")
            digest.update(block)
    if (size != expected["size_bytes"] or digest.hexdigest() != expected["sha256"]
            or _file_identity(path) != identity):
        raise ValueError("restore source file does not match its manifest")


def _copy_exact(source, destination, expected, identity, check_budget):
    digest, size = hashlib.sha256(), 0
    if _file_identity(source) != identity:
        raise ValueError("restore source file changed before copying")
    with source.open("rb") as reader, destination.open("r+b") as writer:
        while True:
            check_budget()
            block = reader.read(min(1024 * 1024, expected["size_bytes"] - size + 1))
            if not block:
                break
            size += len(block)
            if size > expected["size_bytes"]:
                raise ValueError("restore source grew while copying")
            if writer.write(block) != len(block):
                raise OSError("restore copy write was incomplete")
            digest.update(block)
        writer.flush()
        os.fsync(writer.fileno())
    if (size != expected["size_bytes"] or digest.hexdigest() != expected["sha256"]
            or _file_identity(source) != identity):
        raise ValueError("restore copied bytes do not match the source manifest")
    check_budget()


def _verify_sqlite_readonly(path, check_budget):
    with path.open("rb") as stream:
        header = stream.read(100)
    if (len(header) != 100 or header[:16] != b"SQLite format 3\x00"
            or header[18:20] != b"\x01\x01"):
        raise ValueError("restore requires a self-contained rollback-journal SQLite file")
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True,
                                  timeout=0.1, isolation_level=None)) as database:
        def progress():
            try:
                check_budget()
            except TimeoutError:
                return 1
            return 0

        database.execute("PRAGMA cache_size=-1024")
        database.execute("PRAGMA query_only=ON")
        database.set_progress_handler(progress, 1000)
        try:
            check_budget()
            if database.execute("PRAGMA quick_check(1)").fetchall() != [("ok",)]:
                raise ValueError("restore SQLite quick_check failed")
            if database.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise ValueError("restore SQLite foreign_key_check failed")
            check_budget()
        except sqlite3.OperationalError:
            check_budget()
            raise


def _verify_staged(copies, manifest, stage, parent, check_budget):
    _check_stage_files(stage, parent, {path.name for path in copies.values()})
    identities = {}
    for role, path in copies.items():
        _check_file(path, stage, parent)
        _file_identity(path)
        _verify_sqlite_readonly(path, check_budget)
        evidence = _file_evidence(path, check_budget)
        expected = manifest["files"][role]
        if any(evidence[key] != expected[key] for key in ("size_bytes", "sha256")):
            raise ValueError("restore staged bytes changed or do not match the manifest")
        identities[path.name] = _file_identity(path)
    _check_stage_files(stage, parent, {path.name for path in copies.values()})
    return identities


def prepare_application_restore(recovery_directory, destination, *, output_names,
                                verify_copies, before_publish, deadline):
    """Prepare exact startup filenames in a new folder; never replace live data."""
    if not callable(verify_copies) or not callable(before_publish):
        raise TypeError("restore verification and publication admission must be callable")
    if type(deadline) not in (int, float) or not math.isfinite(deadline):
        raise ValueError("restore deadline must be a finite monotonic timestamp")

    def check_budget():
        if time.monotonic() >= deadline:
            raise TimeoutError("application restore time budget exceeded")

    check_budget()
    source = _plain_path(recovery_directory)
    if source.name.casefold().startswith(".application-recovery-"):
        raise ValueError("restore source is an unpublished staging directory")
    directory_identity = _directory_identity(source)
    manifest, manifest_digest, manifest_identity = _read_manifest(source)
    roles = tuple(role for role in _FILE_NAMES if role in manifest["files"])
    names = _output_names(output_names, roles)
    destination = _plain_path(destination)
    if os.path.lexists(destination):
        raise FileExistsError("restore destination already exists: %s" % destination)
    if source in destination.parents or destination in source.parents:
        raise ValueError("restore destination overlaps the source recovery directory")
    parent = destination.parent
    if parent.resolve(strict=True) != parent or not parent.is_dir():
        raise ValueError("restore destination parent is not a plain existing directory")
    identities = {"recovery.json": manifest_identity}
    for role in roles:
        description = manifest["files"][role]
        identity = _file_identity(source / description["name"])
        if identity[2] != description["size_bytes"]:
            raise ValueError("restore source file size does not match its manifest")
        identities[description["name"]] = identity
    required_names = set(identities)
    _check_source(source, directory_identity, identities, required_names)
    required_bytes = sum(manifest["files"][role]["size_bytes"] for role in roles)
    _require_disk_reserve(parent, required_bytes)
    check_budget()
    stage = parent / (".application-recovery-restore-" + uuid.uuid4().hex)
    stage.mkdir(mode=0o700)
    owned_paths = []
    try:
        copies = {}
        remaining = required_bytes
        for role in roles:
            check_budget()
            _require_disk_reserve(parent, remaining)
            description = manifest["files"][role]
            path = stage / names[role]
            _check_file(path, stage, parent)
            _create_file(path, owned_paths)
            owned_paths.extend(Path(str(path) + suffix) for suffix in _SIDE_SUFFIXES)
            _copy_exact(source / description["name"], path, description,
                        identities[description["name"]], check_budget)
            copies[role] = path
            remaining -= description["size_bytes"]
        _check_source(source, directory_identity, identities, required_names)
        _verify_staged(copies, manifest, stage, parent, check_budget)
        verifier_manifest = json.loads(_json_bytes(manifest, _MANIFEST_BYTES))
        verify_copies(dict(copies), verifier_manifest, check_budget)
        check_budget()
        staged_identities = _verify_staged(copies, manifest, stage, parent, check_budget)
        _check_source(source, directory_identity, identities, required_names)
        for role in roles:
            description = manifest["files"][role]
            _hash_source(source / description["name"], description,
                         identities[description["name"]], check_budget)
        _hash_source(source / "recovery.json",
            {"size_bytes": manifest_identity[2], "sha256": manifest_digest},
            manifest_identity, check_budget)
        receipt = {
            "format": 1, "source_manifest_sha256": manifest_digest,
            "files": {role: {"source_name": manifest["files"][role]["name"], "name": names[role],
                "size_bytes": manifest["files"][role]["size_bytes"],
                "sha256": manifest["files"][role]["sha256"]} for role in roles},
            "metadata": manifest["metadata"],
        }
        receipt_path = stage / "restoration.json"
        _check_file(receipt_path, stage, parent)
        _create_file(receipt_path, owned_paths)
        with receipt_path.open("r+b") as stream:
            stream.write(_json_bytes(receipt, _MANIFEST_BYTES))
            stream.flush()
            os.fsync(stream.fileno())
        staged_identities[receipt_path.name] = _file_identity(receipt_path)
        _require_disk_reserve(parent, 0)
        expected_names = {path.name for path in copies.values()} | {"restoration.json"}
        _check_stage_files(stage, parent, expected_names)
        _check_source(source, directory_identity, identities, required_names)
        if any(_file_identity(stage / name) != identity for name, identity in staged_identities.items()):
            raise ValueError("restore staged files changed before publication")
        check_budget()
        before_publish()
        check_budget()
        _check_stage_files(stage, parent, expected_names)
        _check_source(source, directory_identity, identities, required_names)
        if any(_file_identity(stage / name) != identity for name, identity in staged_identities.items()):
            raise ValueError("restore staged files changed before publication")
        if os.path.lexists(destination):
            raise FileExistsError("restore destination already exists: %s" % destination)
        check_budget()
        os.rename(stage, destination)
        return destination
    except BaseException as error:
        _cleanup_stage(stage, parent, owned_paths, error)
        raise
