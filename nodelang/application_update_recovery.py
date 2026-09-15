"""Bind a staged update to an already verified final-close recovery receipt.

The launcher calls ``arm_update`` only after authorized final recovery and close
succeed. It keeps its instance lock through arming, restart and preboot admission.
This module creates no backup, opens no database and grants no runtime authority.
File identities detect ordinary changes after arming; they do not prove that live
bytes equal the backup, close the owner's close-to-arm gap, or resist an actor
able to rewrite this receipt and restore filesystem timestamps. The updater must
still verify the installer bytes and hold its existing instance lock while using
the returned admission. No recovery files are deleted, including after refusal.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile

from .application_recovery_files import _json_bytes
from .application_recovery_restore_files import (
    _check_source, _directory_identity, _file_identity, _nonfinite, _plain_path,
    _read_manifest, _strict_object,
)


_MARKER_NAME = "update-ready.json"
_MARKER_BYTES = 256 * 1024
_STAGED_BYTES = 16 * 1024
_BUILD_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,128}")
_SHA_PATTERN = re.compile(r"[0-9a-fA-F]{64}")
_DURABLE_SUFFIXES = ("", "-wal", "-journal")


def _plain_file_identity(path):
    info = path.lstat()
    if getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
        raise ValueError("update recovery file is a reparse point")
    return _file_identity(path)


def _small_file(path: Path, limit: int):
    path = _plain_path(path)
    identity = _plain_file_identity(path)
    if identity[2] > limit:
        raise ValueError("update recovery input exceeds its byte budget")
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit or _plain_file_identity(path) != identity:
        raise ValueError("update recovery input changed while reading")
    return raw, list(identity)


def _object(raw: bytes):
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_object,
                       parse_constant=_nonfinite)
    if type(value) is not dict:
        raise ValueError("update recovery input must be an object")
    return value


def _optional_identity(path: Path):
    path = _plain_path(path)
    if not os.path.lexists(path):
        return None
    return list(_plain_file_identity(path))


def _source(path):
    path = _plain_path(path)
    files = {}
    for suffix in _DURABLE_SUFFIXES:
        identity = _optional_identity(Path(str(path) + suffix))
        if not suffix and identity is None:
            raise ValueError("the closed application database is missing")
        files[suffix] = identity
    # SHM carries reader/lock marks, not durable messages. Check path safety but
    # do not invalidate a receipt solely because another read changes SHM.
    _optional_identity(Path(str(path) + "-shm"))
    return {"path": str(path), "files": files}


def _recovery_metadata(metadata, roles):
    fields = {"application_root", "graph_revision", "instance_id", "bindings",
              "conversation_heads", "boundary"}
    if type(metadata) is not dict or set(metadata) != fields:
        raise ValueError("update requires an application-owner recovery receipt")
    if (type(metadata["application_root"]) is not str or not metadata["application_root"]
            or len(metadata["application_root"]) > 4096
            or type(metadata["graph_revision"]) is not int or metadata["graph_revision"] < 0
            or metadata["boundary"] != "committed-owner-snapshot"):
        raise ValueError("update recovery owner metadata is invalid")
    instance = metadata["instance_id"]
    if instance is not None and (type(instance) is not str or not instance or len(instance) > 128):
        raise ValueError("update recovery instance metadata is invalid")
    bindings, heads = metadata["bindings"], metadata["conversation_heads"]
    if (type(bindings) is not dict or type(heads) is not dict
            or len(bindings) > 4096 or len(heads) > 4096):
        raise ValueError("update recovery conversation metadata is invalid")
    for root, binding in bindings.items():
        if (type(root) is not str or not root or len(root) > 4096
                or type(binding) is not str or not binding or len(binding) > 4096):
            raise ValueError("update recovery binding metadata is invalid")
    for root, head in heads.items():
        if (type(root) is not str or not root or len(root) > 4096
                or type(head) is not int or head < 0):
            raise ValueError("update recovery conversation head is invalid")
    if set(bindings) - heads.keys():
        raise ValueError("update recovery omits an admitted conversation")
    if "content" in roles:
        if instance is None:
            raise ValueError("update recovery content has no instance identity")
    elif bindings or heads:
        raise ValueError("update recovery is missing its ordinary content file")


def _capture(state_dir, app_dir, graph_path, content_path, recovery_path):
    # Keep the updater's public asset name without an import-time cycle when it
    # imports this admission helper before calling apply_staged.
    from .quiet_update import ASSET_NAME, _utc_build_time

    state = _plain_path(state_dir)
    application = _plain_path(app_dir)
    updates = _plain_path(state / "updates")
    directories = {"state": list(_directory_identity(state)),
                   "application": list(_directory_identity(application)),
                   "updates": list(_directory_identity(updates))}
    build_path = _plain_path(application / "BUILD_ID")
    build_raw, build_identity = _small_file(build_path, 256)
    build = build_raw.decode("utf-8").strip()
    if _BUILD_PATTERN.fullmatch(build) is None:
        raise ValueError("update requires a valid currently installed build identity")
    build_metadata_path = _plain_path(application / "BUILD_METADATA.json")
    build_metadata = None
    if os.path.lexists(build_metadata_path):
        metadata_raw, metadata_identity = _small_file(build_metadata_path, 4096)
        metadata = _object(metadata_raw)
        if (set(metadata) != {"format", "build_id", "built_at"}
                or type(metadata["format"]) is not int or metadata["format"] != 1
                or metadata["build_id"] != build or _utc_build_time(metadata["built_at"]) is None):
            raise ValueError("installed build ordering metadata is invalid")
        build_metadata = {"built_at": metadata["built_at"], "identity": metadata_identity,
                          "sha256": hashlib.sha256(metadata_raw).hexdigest()}

    staged_raw, staged_identity = _small_file(updates / "staged.json", _STAGED_BYTES)
    staged = _object(staged_raw)
    if (not {"build_id", "sha256"} <= set(staged)
            or set(staged) - {"build_id", "built_at", "sha256", "url", "tag", "phase"}
            or type(staged["build_id"]) is not str
            or _BUILD_PATTERN.fullmatch(staged["build_id"]) is None
            or type(staged["sha256"]) is not str
            or _SHA_PATTERN.fullmatch(staged["sha256"]) is None
            or ("built_at" in staged and _utc_build_time(staged["built_at"]) is None)
            or ("url" in staged and (type(staged["url"]) is not str
                or not staged["url"] or len(staged["url"]) > 4096))
            or ("phase" in staged and staged["phase"] != "staged")
            or (staged.get("tag") is not None and (
                type(staged["tag"]) is not str or len(staged["tag"]) > 4096))):
        raise ValueError("staged update identity is invalid")
    if staged["build_id"] == build:
        raise ValueError("the staged update is already installed")
    installer_path = _plain_path(updates / ASSET_NAME)
    installer_identity = list(_plain_file_identity(installer_path))
    if installer_identity[2] <= 0:
        raise ValueError("the staged installer is empty")

    sources = {"graph": _source(graph_path)}
    if content_path is not None:
        sources["content"] = _source(content_path)
    all_source_paths = {
        Path(value["path"] + suffix)
        for value in sources.values() for suffix in (*_DURABLE_SUFFIXES, "-shm")
    }
    if len(all_source_paths) != 4 * len(sources):
        raise ValueError("update database paths or sidecars overlap")

    recovery = _plain_path(recovery_path)
    if recovery.name.startswith(".application-recovery-"):
        raise ValueError("update recovery has not been published")
    recovery_identity = _directory_identity(recovery)
    manifest, manifest_sha, manifest_identity = _read_manifest(recovery)
    if _plain_file_identity(recovery / "recovery.json") != manifest_identity:
        raise ValueError("update recovery manifest changed while reading")
    if set(manifest["files"]) != set(sources):
        raise ValueError("update sources do not match the final recovery file roles")
    _recovery_metadata(manifest["metadata"], set(sources))
    identities = {"recovery.json": manifest_identity}
    for role, description in manifest["files"].items():
        path = _plain_path(recovery / description["name"])
        if path in all_source_paths:
            raise ValueError("update recovery aliases a current application database")
        identity = _plain_file_identity(path)
        if identity[2] != description["size_bytes"]:
            raise ValueError("update recovery file size no longer matches its receipt")
        identities[path.name] = identity
    _check_source(recovery, recovery_identity, identities, set(identities))

    return {
        "format": 1,
        "state_dir": str(state),
        "app_dir": str(application),
        "directories": directories,
        "installed": {"build_id": build, "identity": build_identity,
                      "sha256": hashlib.sha256(build_raw).hexdigest(),
                      "build_metadata": build_metadata},
        "staged": {"build_id": staged["build_id"], "sha256": staged["sha256"].lower(),
                   "marker_identity": staged_identity,
                   "marker_sha256": hashlib.sha256(staged_raw).hexdigest(),
                   "installer_identity": installer_identity},
        "sources": sources,
        "recovery": {"path": str(recovery), "directory_identity": list(recovery_identity),
                     "manifest_sha256": manifest_sha, "manifest": manifest,
                     "files": {name: list(value) for name, value in identities.items()}},
    }


def arm_update(state_dir, app_dir, graph_path, content_path, recovery_path) -> Path:
    """Record a successful final close; caller retains its existing instance lock.

    No installed files, source databases or recovery artifacts are changed. A
    previous ready marker remains intact until this exact atomic replacement.
    Only the helper-created temporary marker is cleaned on failure.
    """
    evidence = _capture(state_dir, app_dir, graph_path, content_path, recovery_path)
    raw = _json_bytes(evidence, _MARKER_BYTES)
    updates = _plain_path(Path(evidence["state_dir"]) / "updates")
    marker = _plain_path(updates / _MARKER_NAME)
    if os.path.lexists(marker):
        _plain_file_identity(marker)
    descriptor, name = tempfile.mkstemp(prefix=".update-ready-", suffix=".tmp", dir=updates)
    temporary = Path(name)
    published = False
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        current = _capture(state_dir, app_dir, graph_path, content_path, recovery_path)
        if _json_bytes(current, _MARKER_BYTES) != raw:
            raise ValueError("update recovery inputs changed before arming")
        _plain_path(temporary)
        _plain_file_identity(temporary)
        _plain_path(marker)
        if os.path.lexists(marker):
            _plain_file_identity(marker)
        os.replace(temporary, marker)
        published = True
        return marker
    except BaseException as error:
        try:
            if list(_directory_identity(updates)) != evidence["directories"]["updates"]:
                raise ValueError("update marker directory changed during cleanup")
            _plain_path(temporary)
            temporary.unlink(missing_ok=True)
        except BaseException as cleanup_error:
            error.add_note("Update marker cleanup failed for %s: %s" % (temporary, cleanup_error))
        if published:
            error.add_note("Update ready marker was published at %s; revalidate before use." % marker)
        raise


def validate_update_ready(state_dir, app_dir, graph_path, content_path) -> dict:
    """Read-only preboot admission; caller must verify installer bytes separately.

    Raises on a missing marker or any durable-file/staged-build/receipt drift.
    Nothing-staged and already-installed cases belong to the owning updater.
    This function neither consumes the marker nor starts a replacement runtime.
    """
    state = _plain_path(state_dir)
    marker = _plain_path(state / "updates" / _MARKER_NAME)
    raw, identity = _small_file(marker, _MARKER_BYTES)
    evidence = _object(raw)
    if (set(evidence) != {"format", "state_dir", "app_dir", "directories", "installed",
                         "staged", "sources", "recovery"}
            or type(evidence["format"]) is not int or evidence["format"] != 1
            or type(evidence["recovery"]) is not dict
            or type(evidence["recovery"].get("path")) is not str):
        raise ValueError("update ready marker is invalid")
    current = _capture(state, app_dir, graph_path, content_path, evidence["recovery"]["path"])
    if (_json_bytes(current, _MARKER_BYTES) != _json_bytes(evidence, _MARKER_BYTES)
            or list(_plain_file_identity(marker)) != identity):
        raise ValueError("update inputs changed after final recovery; preserve current state again")
    return current


__all__ = ["arm_update", "validate_update_ready"]
