#!/usr/bin/env python
"""Plan a non-destructive drain of the copied legacy node_runtime.

The copied runtime remains live-held by existing processes. This tool does not
kill, move, or archive anything. It writes current holder evidence and registers
one Brain active-work leaf so the drain is coordinated through the authority
layer instead of handled as an ad-hoc cleanup.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import live_runtime_holders


TITLE = "Drain copied legacy node_runtime holders into Universal Cell authority"
LONG_RUNNING_TEST_SECONDS = 60 * 60
LOW_ACTIVITY_CPU_RATIO = 0.01
ACTIVE_AUTHORITY_RUNTIME_RESPONSE_TIMEOUT_SECONDS = 15.0
SOURCE_DRIFT_DIRS = (
    "nodelang",
    "tests_replica",
    "tests_domains",
    "packaging",
    "public_site",
)
SOURCE_DRIFT_IGNORED_PARTS = {
    ".git",
    ".pytest_cache",
    "__pycache__",
    "dist",
    "node_modules",
}
SOURCE_DRIFT_IGNORED_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".map",
}
SOURCE_DRIFT_AUTHORITY_BASIS = (
    "10.PRODUCT/13.NODE-LANGUAGE/AUTHORITY.md precedence table",
    "10.PRODUCT/13.NODE-LANGUAGE/SPEC.md sections 1, 4.1, 4.5, 6, 7",
)
SOURCE_DRIFT_EVIDENCE_GLOB = "legacy_runtime_source_drift_*_evidence.latest.json"
SOURCE_DRIFT_EVIDENCE_SCHEMAS = {
    "archhub-runtime-source-drift-authority-evidence/v1",
    "archhub-runtime-source-drift-authority-slice-evidence/v1",
    "legacy_runtime_source_drift_visual_evidence_v1",
    "legacy_runtime_source_drift_relation_security_evidence_v1",
}
MIGRATION_TRACK_METADATA = {
    "application_graph_projection": {
        "title": "Resolve application graph projection drift",
        "priority": 9100,
        "required_outcome": (
            "application lenses consume canonical graph roots without duplicate "
            "truth or copied runtime state"
        ),
    },
    "baboom_context_and_cognition": {
        "title": "Resolve BABOOM context and cognition drift",
        "priority": 9000,
        "required_outcome": (
            "BABOOM identity, context, presence, and cognition are released "
            "Cell protocols before behavior is accepted"
        ),
    },
    "governed_work_lifecycle": {
        "title": "Resolve governed work lifecycle drift",
        "priority": 8950,
        "required_outcome": (
            "work completion is graph-held decision/outcome/revision state"
        ),
    },
    "public_site_projection": {
        "title": "Resolve public site projection drift",
        "priority": 7600,
        "required_outcome": (
            "public site output is a projection of released application roots"
        ),
    },
    "revision_integrity_court": {
        "title": "Resolve revision integrity court drift",
        "priority": 8800,
        "required_outcome": (
            "any accepted concurrency invariant is proven against the canonical "
            "Cell revision/commit protocol"
        ),
    },
    "runtime_transport_and_broker": {
        "title": "Resolve runtime transport and broker drift",
        "priority": 9300,
        "required_outcome": (
            "runtime transport and broker behavior derive from graph-held "
            "session, capability, grant, outcome, and revocation roots"
        ),
    },
    "visual_workspace_interaction": {
        "title": "Resolve visual workspace interaction drift",
        "priority": 9200,
        "required_outcome": (
            "visual interaction courts prove the graph workspace semantics in "
            "the canonical authority"
        ),
    },
    "unmapped_runtime_candidate": {
        "title": "Classify unmapped runtime drift",
        "priority": 7000,
        "required_outcome": "candidate is classified before any integration claim",
    },
}


def default_product_root() -> Path:
    return Path(__file__).resolve().parents[1]


def default_workspace(product_root: Path) -> Path:
    return product_root.parents[1]


def default_handoff_dir(workspace: Path) -> Path:
    return workspace / "70.HANDOFFS" / "public-wip-convergence" / "20260717-150723"


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def write_holder_report(
    product_root: Path,
    workspace: Path,
    out_dir: Path,
    timestamp: str | None = None,
) -> dict[str, Any]:
    ts = timestamp or _timestamp()
    report = live_runtime_holders.audit(live_runtime_holders.default_runtime_copy(product_root))
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"legacy-runtime-drain-holders-{ts}.json"
    payload = {
        "schema": "archhub-legacy-runtime-drain-holder-report/v1",
        "authority": str(workspace / "10.PRODUCT" / "13.NODE-LANGUAGE"),
        "runtime_copy": str(product_root / "node_runtime"),
        "holder_report": report,
        "decision": (
            "do not archive or move the copied runtime while holder_count > 0; "
            "drain by relaunching holders from 10.PRODUCT/13.NODE-LANGUAGE or "
            "letting them finish naturally"
        ),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    payload["path"] = str(path)
    return payload


def build_holder_payload(product_root: Path, workspace: Path) -> dict[str, Any]:
    report = live_runtime_holders.audit(live_runtime_holders.default_runtime_copy(product_root))
    return {
        "schema": "archhub-legacy-runtime-drain-holder-report/v1",
        "authority": str(workspace / "10.PRODUCT" / "13.NODE-LANGUAGE"),
        "runtime_copy": str(product_root / "node_runtime"),
        "holder_report": report,
        "decision": (
            "do not archive or move the copied runtime while holder_count > 0; "
            "drain by relaunching holders from 10.PRODUCT/13.NODE-LANGUAGE or "
            "letting them finish naturally"
        ),
        "path": None,
    }


def classify_holder(holder: dict[str, Any]) -> dict[str, Any]:
    cmd = str(holder.get("cmdline") or "")
    lower = cmd.lower()
    runtime_args = parse_runtime_args(cmd)
    script = holder_script_evidence(cmd, str(holder.get("cwd") or ""))
    if "pytest" in lower:
        holder_type = "test_runner"
        action = (
            "let the test process finish; future equivalent tests must run from "
            "10.PRODUCT/13.NODE-LANGUAGE, not the copied node_runtime"
        )
    elif "nodelang.application_server" in lower or "run_application_server.py" in lower:
        holder_type = "application_server"
        action = (
            "keep running until the visible session is no longer needed, then "
            "relaunch from 10.PRODUCT/13.NODE-LANGUAGE with the same port/state "
            "arguments"
        )
    elif cmd.strip().endswith("python.exe -") or cmd.strip().endswith("pythonw.exe -"):
        holder_type = "stdin_python"
        action = (
            "inspect owner before interruption; if disposable, let it exit; if "
            "needed, relaunch its script from 10.PRODUCT/13.NODE-LANGUAGE"
        )
    else:
        holder_type = "unknown_python_holder"
        action = (
            "inspect manually before any interruption; do not archive the copied "
            "runtime while this holder remains"
        )
    classified = {
        "pid": holder.get("pid"),
        "name": holder.get("name"),
        "holder_type": holder_type,
        "runtime_args": runtime_args,
        "script_evidence": script,
        **holder_risk_class(holder_type, cmd, runtime_args, script),
        "cwd": holder.get("cwd"),
        "cmdline": cmd,
        "process_status": holder.get("status") or "",
        "age_seconds": holder.get("age_seconds"),
        "create_time": holder.get("create_time"),
        "cpu_total_seconds": holder.get("cpu_total_seconds"),
        "allowed_action": action,
        "forbidden_action": "kill, move, or archive as an uncoordinated cleanup",
    }
    return classified


def holder_script_evidence(cmdline: str, cwd: str) -> dict[str, Any]:
    """Extract read-only script/module/stdin evidence from a command line."""
    evidence: dict[str, Any] = {
        "launch_mode": "unknown",
        "module": None,
        "stdin_mode": False,
        "script_path": None,
        "script_exists": False,
        "script_size_bytes": None,
        "script_mtime_utc": None,
        "script_sha256": None,
    }
    module = re.search(r"(?:^|\s)-m\s+([^\s]+)", cmdline)
    if module:
        evidence["launch_mode"] = "python_module"
        evidence["module"] = module.group(1)
        return evidence
    if re.search(r"(?:^|\s)-(?:\s|$)", cmdline):
        evidence["launch_mode"] = "python_stdin"
        evidence["stdin_mode"] = True
        return evidence
    script = re.search(r"((?:[A-Za-z]:\\)?[^\s]+\.py)(?:\s|$)", cmdline)
    if not script:
        return evidence
    candidate = Path(script.group(1))
    if not candidate.is_absolute() and cwd:
        candidate = Path(cwd) / candidate
    evidence["launch_mode"] = "python_script"
    evidence["script_path"] = str(candidate)
    if not candidate.is_file():
        return evidence
    try:
        stat = candidate.stat()
        evidence.update({
            "script_exists": True,
            "script_size_bytes": int(stat.st_size),
            "script_mtime_utc": stat.st_mtime,
            "script_sha256": _sha256(candidate),
        })
    except OSError:
        pass
    return evidence


def _sha256(path: Path) -> str | None:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def holder_risk_class(
    holder_type: str,
    cmdline: str,
    runtime_args: dict[str, Any],
    script: dict[str, Any],
) -> dict[str, str]:
    lower = cmdline.lower()
    script_path = str(script.get("script_path") or "").lower()
    script_name = Path(script_path).name.lower() if script_path else ""
    if (
        holder_type == "application_server"
        and runtime_args.get("port") == 8482
        and runtime_args.get("cloud_port") == 8484
    ):
        return {
            "holder_risk_class": "visible_legacy_endpoint",
            "drain_posture": (
                "coordinate visible endpoint handoff; this is the user-facing old runtime"
            ),
        }
    if script_name == "archhub_nary_qa_server.py":
        return {
            "holder_risk_class": (
                "qa_server_script" if script.get("script_exists")
                else "qa_server_script_missing"
            ),
            "drain_posture": (
                "script-backed QA holder; verify owner before handoff"
                if script.get("script_exists")
                else "orphaned temp-script holder; inspect live process before cleanup"
            ),
        }
    if holder_type == "stdin_python":
        return {
            "holder_risk_class": "stdin_python_holder",
            "drain_posture": (
                "stdin-launched Python holder; inspect parent/child/listener evidence"
            ),
        }
    if "pytest" in lower:
        return {
            "holder_risk_class": "test_runner",
            "drain_posture": "let test runner finish or prove it stale before cleanup",
        }
    return {
        "holder_risk_class": "unclassified_copied_runtime_holder",
        "drain_posture": "inspect manually before any drain decision",
    }


def parse_runtime_args(cmdline: str) -> dict[str, Any]:
    def _value(flag: str) -> str | None:
        match = re.search(rf"(?:^|\s){re.escape(flag)}\s+([^\s]+)", cmdline)
        return match.group(1) if match else None

    def _int(flag: str) -> int | None:
        value = _value(flag)
        if value is None:
            return None
        try:
            return int(value)
        except ValueError:
            return None

    return {
        "host": _value("--host"),
        "port": _int("--port"),
        "cloud_host": _value("--cloud-host"),
        "cloud_port": _int("--cloud-port"),
        "state_path": _value("--state-path"),
        "fresh": " --fresh" in f" {cmdline}",
        "pytest_target": _pytest_target(cmdline),
    }


def _pytest_target(cmdline: str) -> str | None:
    if "pytest" not in cmdline.lower():
        return None
    parts = cmdline.split()
    for index, part in enumerate(parts):
        if part.endswith("pytest") or part == "pytest":
            for candidate in parts[index + 1:]:
                if not candidate.startswith("-"):
                    return candidate
    return None


def _source_drift_files(root: Path) -> list[Path]:
    files: list[Path] = []
    if not root.exists():
        return files
    for directory in SOURCE_DRIFT_DIRS:
        base = root / directory
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            if any(part in SOURCE_DRIFT_IGNORED_PARTS for part in path.parts):
                continue
            if path.suffix.lower() in SOURCE_DRIFT_IGNORED_SUFFIXES:
                continue
            files.append(path)
    return sorted(files, key=lambda item: item.relative_to(root).as_posix())


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _evidence_track(payload: dict[str, Any]) -> str | None:
    track = payload.get("migration_track") or payload.get("scope")
    if not track:
        return None
    return str(track).replace("\\", "/").split("/", 1)[0]


def _evidence_tracks(payload: dict[str, Any]) -> list[str]:
    tracks: list[str] = []
    slices = payload.get("slices")
    if isinstance(slices, list):
        for item in slices:
            track = str(item).replace("\\", "/").split("/", 1)[0]
            if track in MIGRATION_TRACK_METADATA and track not in tracks:
                tracks.append(track)
    primary = _evidence_track(payload)
    if primary and primary in MIGRATION_TRACK_METADATA and primary not in tracks:
        tracks.append(primary)
    if not tracks and primary:
        tracks.append(primary)
    return tracks


def _evidence_authority_files(payload: dict[str, Any]) -> list[str]:
    files = payload.get("authority_files") or payload.get("canonical_files") or []
    if isinstance(files, dict):
        return sorted(str(path).replace("\\", "/") for path in files)
    if isinstance(files, list):
        paths: list[str] = []
        for item in files:
            if isinstance(item, dict) and item.get("path"):
                paths.append(str(item["path"]).replace("\\", "/"))
            elif isinstance(item, str):
                paths.append(item.replace("\\", "/"))
        return sorted(paths)
    return []


def _evidence_commands(payload: dict[str, Any]) -> list[dict[str, Any]]:
    commands = (
        payload.get("commands")
        or payload.get("courts")
        or payload.get("tests")
        or []
    )
    if not isinstance(commands, list):
        return []
    return [item for item in commands if isinstance(item, dict)]


def _evidence_decision(payload: dict[str, Any]) -> dict[str, Any]:
    decision = payload.get("decision")
    return decision if isinstance(decision, dict) else {}


def _evidence_non_promoting(payload: dict[str, Any]) -> bool:
    decision = _evidence_decision(payload)
    explicit_false_keys = (
        "runtime_copy_promoted",
        "bulk_copy_performed",
        "bulk_copy_used",
        "runtime_copy_used_as_authority",
        "live_process_interruption",
    )
    for key in explicit_false_keys:
        if key in payload and bool(payload[key]) is True:
            return False
        if key in decision and bool(decision[key]) is True:
            return False
    non_interruption = payload.get("non_interruption")
    if isinstance(non_interruption, dict):
        if bool(non_interruption.get("no_running_sessions_restarted")) is False:
            return False
        if bool(non_interruption.get("no_processes_terminated")) is False:
            return False
    if "non_interrupting" in payload and bool(payload["non_interrupting"]) is False:
        return False
    return True


def _evidence_is_usable(payload: dict[str, Any]) -> bool:
    if payload.get("schema") not in SOURCE_DRIFT_EVIDENCE_SCHEMAS:
        return False
    if not _evidence_track(payload):
        return False
    if not _evidence_non_promoting(payload):
        return False
    if not _evidence_authority_files(payload):
        return False
    commands = _evidence_commands(payload)
    if not commands:
        return False
    return any(
        "passed" in str(command.get("result") or "").lower()
        for command in commands
    )


def source_drift_resolution_ledger(product_root: Path) -> dict[str, Any]:
    """Read committed drift evidence without making it product authority."""
    evidence_dir = product_root / "docs" / "_meta"
    evidence_files: list[dict[str, Any]] = []
    by_track: dict[str, list[dict[str, Any]]] = {}
    by_path: dict[str, list[dict[str, Any]]] = {}
    if evidence_dir.exists():
        for path in sorted(evidence_dir.glob(SOURCE_DRIFT_EVIDENCE_GLOB)):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict) or not _evidence_is_usable(payload):
                continue
            tracks = _evidence_tracks(payload)
            if not tracks:
                continue
            record = {
                "path": path.relative_to(product_root).as_posix(),
                "schema": payload.get("schema"),
                "migration_track": tracks[0],
                "migration_tracks": tracks,
                "slice": payload.get("slice") or payload.get("scope") or "",
                "authority_files": _evidence_authority_files(payload),
                "command_count": len(_evidence_commands(payload)),
                "runtime_copy_promoted": False,
                "bulk_copy_performed": False,
                "live_process_interruption": False,
            }
            evidence_files.append(record)
            for track in tracks:
                by_track.setdefault(track, []).append(record)

            decision = _evidence_decision(payload)
            pending_text = json.dumps(
                decision.get("pending_not_ported") or [], sort_keys=True
            ).replace("\\", "/")
            for authority_file in record["authority_files"]:
                by_path.setdefault(authority_file, []).append(record)
            runtime_candidate = payload.get("runtime_candidate")
            if isinstance(runtime_candidate, dict) and runtime_candidate.get("path"):
                candidate_path = str(runtime_candidate["path"]).replace("\\", "/")
                by_path.setdefault(candidate_path, []).append(record)
            candidate_decisions = payload.get("runtime_candidate_decisions")
            if isinstance(candidate_decisions, list):
                for decision_row in candidate_decisions:
                    if not isinstance(decision_row, dict) or not decision_row.get("path"):
                        continue
                    candidate_path = str(decision_row["path"]).replace("\\", "/")
                    by_path.setdefault(candidate_path, []).append({
                        **record,
                        "explicit_candidate_decision": True,
                        "candidate_decision": decision_row.get("decision"),
                        "resolution_state": decision_row.get("resolution_state"),
                    })
            runtime_read_only = payload.get("runtime_evidence_read_only")
            if isinstance(runtime_read_only, dict):
                for candidate_path in runtime_read_only:
                    by_path.setdefault(
                        str(candidate_path).replace("\\", "/"),
                        [],
                    ).append({
                        **record,
                        "pending_canonical_root_decision": True,
                    })
            pending_path_pattern = (
                r"(?:nodelang|tests_replica|tests_domains|packaging|public_site)"
                r"/[A-Za-z0-9_./-]+"
            )
            for raw_path in re.findall(pending_path_pattern, pending_text):
                by_path.setdefault(raw_path.replace("\\", "/"), []).append({
                    **record,
                    "pending_canonical_root_decision": True,
                })
    return {
        "schema": "archhub-runtime-source-drift-resolution-ledger/v1",
        "evidence_glob": SOURCE_DRIFT_EVIDENCE_GLOB,
        "evidence_file_count": len(evidence_files),
        "evidence_files": evidence_files,
        "by_track": {key: rows for key, rows in sorted(by_track.items())},
        "by_path": {key: rows for key, rows in sorted(by_path.items())},
        "rule": (
            "Evidence can classify the canonical decision status, but it does "
            "not clear physical source drift or authorize runtime interruption."
        ),
    }


def apply_source_drift_resolution_evidence(
    candidate: dict[str, Any],
    ledger: dict[str, Any],
) -> dict[str, Any]:
    normalized_path = str(candidate.get("path") or "").replace("\\", "/")
    track = str(candidate.get("migration_track") or "")
    by_path = ledger.get("by_path") if isinstance(ledger, dict) else {}
    by_track = ledger.get("by_track") if isinstance(ledger, dict) else {}
    path_records = by_path.get(normalized_path, []) if isinstance(by_path, dict) else []
    track_records = by_track.get(track, []) if isinstance(by_track, dict) else []
    records = path_records or track_records
    if not records:
        return candidate
    deduped_records: list[dict[str, Any]] = []
    seen_records: set[tuple[Any, Any, Any]] = set()
    for record in records:
        key = (
            record.get("path"),
            record.get("slice"),
            bool(record.get("pending_canonical_root_decision")),
        )
        if key in seen_records:
            continue
        seen_records.add(key)
        deduped_records.append(record)
    records = deduped_records
    explicit = [record for record in records if record.get("explicit_candidate_decision")]
    pending = any(record.get("pending_canonical_root_decision") for record in records)
    if explicit:
        state = str(
            explicit[0].get("resolution_state")
            or "explicit_candidate_decision_pending_runtime_retirement"
        )
        decision = str(explicit[0].get("candidate_decision") or "recorded")
        if decision == "preserve_as_migration_evidence":
            action = (
                "explicit decision records this copied-runtime candidate as "
                "migration evidence only; do not promote it and keep it only "
                "until the runtime copy is safely retired"
            )
        else:
            action = (
                "explicit decision records the canonical authority path for "
                "this candidate; keep the copied runtime file only until the "
                "runtime copy is safely retired"
            )
    elif pending:
        state = "pending_canonical_root_decision"
        action = (
            "preserve as read-only migration evidence until the canonical "
            "root/form decision is made; do not port by bulk copy"
        )
    elif path_records:
        state = "canonical_evidence_recorded_pending_runtime_retirement"
        action = (
            "canonical authority evidence exists for this relative path; keep "
            "the copied runtime file as migration evidence until the runtime "
            "copy is safely retired"
        )
    else:
        state = "track_evidence_recorded_pending_candidate_decision"
        action = (
            "track-level canonical evidence exists, but this relative path "
            "still needs an explicit reconstruct/reject/preserve decision"
        )
    candidate = {**candidate}
    candidate.update({
        "resolution_state": state,
        "resolution_evidence": [
            {
                "path": record.get("path"),
                "slice": record.get("slice"),
                "migration_track": record.get("migration_track"),
                "command_count": record.get("command_count"),
            }
            for record in records
        ],
        "allowed_next_action": action,
    })
    return candidate


def _source_drift_candidate(
    *,
    status: str,
    row: dict[str, Any],
    runtime_copy: Path,
    authority: Path,
    resolution_ledger: dict[str, Any] | None = None,
) -> dict[str, Any]:
    path = str(row["path"])
    digest_body = {
        "status": status,
        "path": path,
        "runtime_sha256": row.get("runtime_sha256"),
        "authority_sha256": row.get("authority_sha256"),
    }
    candidate_id = "runtime-source-drift:%s" % hashlib.sha256(
        json.dumps(digest_body, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()[:16]
    candidate = {
        "candidate_id": candidate_id,
        "path": path,
        "status": status,
        **classify_source_drift_candidate(path),
        "runtime_path": str(runtime_copy / path),
        "authority_path": str(authority / path),
        "runtime_sha256": row.get("runtime_sha256"),
        "authority_sha256": row.get("authority_sha256"),
        "required_decision": (
            "reconstruct_in_canonical_authority, reject_as_experiment, or "
            "preserve_as_migration_evidence"
        ),
        "allowed_next_action": (
            "read and compare as evidence; if accepted, rebuild through "
            "10.PRODUCT/13.NODE-LANGUAGE with red courts first"
        ),
        "forbidden_action": (
            "bulk-copy ignored runtime source or cite this candidate as "
            "delivered authority"
        ),
    }
    if resolution_ledger:
        candidate = apply_source_drift_resolution_evidence(candidate, resolution_ledger)
    return candidate


def classify_source_drift_candidate(path: str) -> dict[str, Any]:
    """Classify an ignored-runtime source difference without accepting it."""
    normalized = path.replace("\\", "/")
    candidate_kind = (
        "court_candidate"
        if normalized.startswith("tests_replica/")
        else "implementation_candidate"
    )
    if "baboom" in normalized:
        track = "baboom_context_and_cognition"
        required_canonical_first_step = (
            "define/release BABOOM graph protocols and red courts in "
            "13.NODE-LANGUAGE before implementation"
        )
    elif (
        "canvas" in normalized
        or "visual" in normalized
        or "relation_" in normalized
        or "playable_interaction" in normalized
        or normalized == "nodelang/cell_relations_view.py"
        or normalized == "nodelang/ui_runtime.py"
        or normalized == "tests_replica/test_universal_ui_interactions.py"
    ):
        track = "visual_workspace_interaction"
        required_canonical_first_step = (
            "rebuild the interaction or visual grammar as authority courts "
            "against the released graph protocols"
        )
    elif (
        "authority_bridge" in normalized
        or "application_server" in normalized
        or normalized == "nodelang/capabilities.py"
        or "cloud_gateway" in normalized
        or "universal_cell_capabilities" in normalized
        or "machine_transport" in normalized
        or "boundary_ports" in normalized
    ):
        track = "runtime_transport_and_broker"
        required_canonical_first_step = (
            "define graph-held broker/session/capability lifecycle courts "
            "before accepting transport behavior"
        )
    elif normalized.startswith("public_site/"):
        track = "public_site_projection"
        required_canonical_first_step = (
            "derive the website projection from released application roots, "
            "not from copied runtime state"
        )
    elif "universal_application" in normalized:
        track = "application_graph_projection"
        required_canonical_first_step = (
            "prove the application lens consumes the canonical graph root and "
            "does not introduce duplicate product truth"
        )
    elif "projection_delta" in normalized:
        track = "application_graph_projection"
        required_canonical_first_step = (
            "prove projection changes as graph-derived deltas from released "
            "roots, not copied runtime state"
        )
    elif "work_completion" in normalized:
        track = "governed_work_lifecycle"
        required_canonical_first_step = (
            "prove work completion as graph-held decision/outcome/revision "
            "state before accepting runtime behavior"
        )
    elif "store_concurrency" in normalized:
        track = "revision_integrity_court"
        required_canonical_first_step = (
            "rebuild as a canonical revision/commit court if it covers a "
            "real Cell-store invariant"
        )
    else:
        track = "unmapped_runtime_candidate"
        required_canonical_first_step = (
            "manually classify before any integration, archive, or release claim"
        )
    return {
        "candidate_kind": candidate_kind,
        "migration_track": track,
        "authority_disposition": "migration_evidence_not_authority",
        "resolution_state": "classified_unresolved",
        "promotion_allowed": False,
        "bulk_copy_allowed": False,
        "authority_basis": list(SOURCE_DRIFT_AUTHORITY_BASIS),
        "required_canonical_first_step": required_canonical_first_step,
    }


def _source_drift_decision_summary(
    migration_candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    by_track: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    by_state: dict[str, int] = {}
    unmapped: list[str] = []
    for candidate in migration_candidates:
        track = str(candidate.get("migration_track") or "unmapped_runtime_candidate")
        kind = str(candidate.get("candidate_kind") or "unknown")
        state = str(candidate.get("resolution_state") or "unknown")
        by_track[track] = by_track.get(track, 0) + 1
        by_kind[kind] = by_kind.get(kind, 0) + 1
        by_state[state] = by_state.get(state, 0) + 1
        if track == "unmapped_runtime_candidate":
            unmapped.append(str(candidate.get("path") or ""))
    return {
        "schema": "archhub-runtime-source-drift-decision-summary/v1",
        "candidate_count": len(migration_candidates),
        "all_classified": not unmapped,
        "unmapped_paths": unmapped,
        "by_track": dict(sorted(by_track.items())),
        "by_kind": dict(sorted(by_kind.items())),
        "by_resolution_state": dict(sorted(by_state.items())),
        "promotion_allowed": False,
        "bulk_copy_allowed": False,
    }


def runtime_copy_source_drift(product_root: Path, authority: Path) -> dict[str, Any]:
    """Detect source hidden in ignored node_runtime that authority does not own."""
    runtime_copy = product_root / "node_runtime"
    resolution_ledger = source_drift_resolution_ledger(product_root)
    missing_in_authority: list[dict[str, Any]] = []
    different_from_authority: list[dict[str, Any]] = []
    checked = 0
    for runtime_file in _source_drift_files(runtime_copy):
        checked += 1
        rel = runtime_file.relative_to(runtime_copy).as_posix()
        authority_file = authority / rel
        runtime_sha = _sha256_file(runtime_file)
        if not authority_file.exists():
            missing_in_authority.append({
                "path": rel,
                "runtime_sha256": runtime_sha,
            })
            continue
        authority_sha = _sha256_file(authority_file)
        if runtime_sha != authority_sha:
            different_from_authority.append({
                "path": rel,
                "runtime_sha256": runtime_sha,
                "authority_sha256": authority_sha,
            })
    drift_count = len(missing_in_authority) + len(different_from_authority)
    migration_candidates = [
        *[
            _source_drift_candidate(
                status="missing_in_authority",
                row=row,
                runtime_copy=runtime_copy,
                authority=authority,
                resolution_ledger=resolution_ledger,
            )
            for row in missing_in_authority
        ],
        *[
            _source_drift_candidate(
                status="different_from_authority",
                row=row,
                runtime_copy=runtime_copy,
                authority=authority,
                resolution_ledger=resolution_ledger,
            )
            for row in different_from_authority
        ],
    ]
    decision_summary = _source_drift_decision_summary(migration_candidates)
    return {
        "schema": "archhub-runtime-copy-source-drift/v1",
        "runtime_copy": str(runtime_copy),
        "authority": str(authority),
        "source_dirs": list(SOURCE_DRIFT_DIRS),
        "ignored_parts": sorted(SOURCE_DRIFT_IGNORED_PARTS),
        "ignored_suffixes": sorted(SOURCE_DRIFT_IGNORED_SUFFIXES),
        "checked_runtime_files": checked,
        "drift_count": drift_count,
        "migration_candidate_count": len(migration_candidates),
        "resolution_ledger": {
            "schema": resolution_ledger["schema"],
            "evidence_file_count": resolution_ledger["evidence_file_count"],
            "tracks_with_evidence": sorted(resolution_ledger["by_track"]),
            "rule": resolution_ledger["rule"],
        },
        "decision_summary": decision_summary,
        "ok": drift_count == 0,
        "missing_in_authority": missing_in_authority,
        "different_from_authority": different_from_authority,
        "migration_candidates": migration_candidates,
        "rule": (
            "An ignored runtime copy cannot be archived while it contains source "
            "files that are missing or different in the declared authority."
        ),
    }


def build_source_drift_migration_work(
    source_drift: dict[str, Any],
    *,
    product_root: Path,
    workspace: Path,
) -> dict[str, Any]:
    """Group ignored-runtime drift candidates into canonical migration work."""
    authority = workspace / "10.PRODUCT" / "13.NODE-LANGUAGE"
    grouped: dict[str, list[dict[str, Any]]] = {}
    for candidate in source_drift.get("migration_candidates") or []:
        if not isinstance(candidate, dict):
            continue
        track = str(candidate.get("migration_track") or "unmapped_runtime_candidate")
        grouped.setdefault(track, []).append(candidate)

    work_items: list[dict[str, Any]] = []
    for track, candidates in sorted(
        grouped.items(),
        key=lambda item: (
            -int(MIGRATION_TRACK_METADATA.get(item[0], {}).get("priority", 0)),
            item[0],
        ),
    ):
        metadata = MIGRATION_TRACK_METADATA.get(
            track,
            MIGRATION_TRACK_METADATA["unmapped_runtime_candidate"],
        )
        implementation_paths = sorted(
            str(candidate["path"])
            for candidate in candidates
            if candidate.get("candidate_kind") == "implementation_candidate"
        )
        court_paths = sorted(
            str(candidate["path"])
            for candidate in candidates
            if candidate.get("candidate_kind") == "court_candidate"
        )
        candidate_ids = sorted(str(candidate["candidate_id"]) for candidate in candidates)
        required_steps = sorted({
            str(candidate.get("required_canonical_first_step") or "")
            for candidate in candidates
            if candidate.get("required_canonical_first_step")
        })
        candidate_states = sorted({
            str(candidate.get("resolution_state") or "classified_unresolved")
            for candidate in candidates
        })
        if len(candidate_states) == 1:
            resolution_state = candidate_states[0]
        else:
            resolution_state = "mixed_resolution_states"
        work_id = "runtime-source-drift-track:%s" % track
        work_items.append({
            "work_id": work_id,
            "title": metadata["title"],
            "migration_track": track,
            "priority": int(metadata["priority"]),
            "authority": str(authority),
            "runtime_copy": str(product_root / "node_runtime"),
            "cde_container": {
                "container_id": "10.PRODUCT/13.NODE-LANGUAGE",
                "authority": "10.PRODUCT/13.NODE-LANGUAGE",
                "lifecycle": "WIP",
                "privacy_tier": "T0 PUBLIC",
            },
            "resolution_state": resolution_state,
            "candidate_resolution_states": candidate_states,
            "candidate_count": len(candidates),
            "candidate_ids": candidate_ids,
            "implementation_candidate_paths": implementation_paths,
            "court_candidate_paths": court_paths,
            "required_canonical_first_steps": required_steps,
            "required_outcome": metadata["required_outcome"],
            "required_decisions": [
                "reconstruct_in_canonical_authority",
                "reject_as_experiment",
                "preserve_as_migration_evidence",
            ],
            "completion_gate": {
                "kind": "canonical_resolution_required",
                "must_prove": [
                    "every accepted behavior is rebuilt in 10.PRODUCT/13.NODE-LANGUAGE",
                    "red courts exist before accepted behavior changes",
                    "rejected candidates have recorded rejection rationale",
                    "preserved candidates are marked migration evidence only",
                    "no copied-runtime file is bulk-copied as authority",
                    "runtime drain gate no longer reports this track as source drift",
                ],
            },
            "promotion_allowed": False,
            "bulk_copy_allowed": False,
            "live_process_interruption_allowed": False,
            "forbidden_actions": [
                "bulk-copy ignored node_runtime source into authority",
                "cite ignored runtime code as delivered product authority",
                "interrupt, stop, or restart live holders from this work plan",
            ],
        })
    unresolved_count = sum(
        1 for item in work_items if item.get("resolution_state") != "resolved"
    )
    evidence_covered_count = sum(
        1
        for item in work_items
        if item.get("resolution_state")
        not in {"classified_unresolved", "resolved"}
    )
    return {
        "schema": "archhub-runtime-source-drift-migration-work/v1",
        "source_schema": source_drift.get("schema"),
        "authority": str(authority),
        "runtime_copy": str(product_root / "node_runtime"),
        "candidate_count": int(source_drift.get("migration_candidate_count") or 0),
        "track_count": len(work_items),
        "unresolved_track_count": unresolved_count,
        "evidence_covered_track_count": evidence_covered_count,
        "all_candidates_classified": bool(
            (source_drift.get("decision_summary") or {}).get("all_classified")
        ),
        "all_work_authority_scoped": all(
            str(item["authority"]).endswith("10.PRODUCT\\13.NODE-LANGUAGE")
            or str(item["authority"]).endswith("10.PRODUCT/13.NODE-LANGUAGE")
            for item in work_items
        ),
        "all_non_promoting": all(not item["promotion_allowed"] for item in work_items),
        "all_bulk_copy_forbidden": all(not item["bulk_copy_allowed"] for item in work_items),
        "all_non_interrupting": all(
            not item["live_process_interruption_allowed"] for item in work_items
        ),
        "work_items": work_items,
        "rule": (
            "This is a migration-control plan. It does not accept copied runtime "
            "source as authority and does not authorize live process interruption."
        ),
    }


def build_drain_plan(
    product_root: Path,
    workspace: Path,
    holder_payload: dict[str, Any],
    *,
    run_shadow_probe: bool = False,
) -> dict[str, Any]:
    holder_report = holder_payload["holder_report"]
    authority = workspace / "10.PRODUCT" / "13.NODE-LANGUAGE"
    readiness = authority_launch_readiness(authority)
    shadow_probe = (
        authority_shadow_launch_probe(authority)
        if run_shadow_probe
        else authority_shadow_launch_probe_not_run(authority)
    )
    active_bridge = active_authority_runtime_bridge_status(product_root, workspace)
    source_drift = runtime_copy_source_drift(product_root, authority)
    holders = [classify_holder(holder) for holder in holder_report["holders"]]
    bridge_launch = authority_bridge_launch_spec(authority, holders)
    for holder in holders:
        holder["authority_relaunch"] = authority_relaunch_spec(holder, authority)
        holder["desktop_authority_handoff"] = desktop_authority_handoff_spec(
            holder, authority
        )
    listener_map = active_tcp_listeners()
    replacement_summary = annotate_authority_replacements(holders, listener_map)
    by_type: dict[str, int] = {}
    for holder in holders:
        by_type[holder["holder_type"]] = by_type.get(holder["holder_type"], 0) + 1
    duplicate_groups = duplicate_server_groups(holders)
    handoff_schedule = build_handoff_schedule(holders, duplicate_groups)
    handoff_board = build_handoff_board(
        holders,
        replacement_summary,
        handoff_schedule,
        source_drift,
    )
    retirement_gate = build_retirement_gate(
        holder_report,
        readiness,
        shadow_probe,
        active_bridge,
        replacement_summary,
        handoff_schedule,
        source_drift,
    )
    return {
        "schema": "archhub-legacy-runtime-drain-plan/v1",
        "authority": str(authority),
        "runtime_copy": str(product_root / "node_runtime"),
        "authority_launch_readiness": readiness,
        "authority_bridge_launch": bridge_launch,
        "authority_shadow_launch_probe": shadow_probe,
        "active_authority_runtime_bridge": active_bridge,
        "runtime_copy_source_drift": source_drift,
        "holder_count": holder_report["holder_count"],
        "archive_safe_now": holder_report["archive_safe_now"],
        "drain_complete": holder_report["holder_count"] == 0,
        "by_type": by_type,
        "duplicate_server_groups": duplicate_groups,
        "exact_authority_replacement": replacement_summary,
        "handoff_schedule": handoff_schedule,
        "handoff_board": handoff_board,
        "retirement_gate": retirement_gate,
        "holders": holders,
        "rule": (
            "No holder may be interrupted by this planner. Drain by natural exit "
            "or coordinated relaunch from the Universal Cell authority."
        ),
    }


def build_handoff_board(
    holders: list[dict[str, Any]],
    replacement_summary: dict[str, Any],
    handoff_schedule: dict[str, Any],
    source_drift: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a compact operator board derived from the full drain plan.

    The full JSON is intentionally detailed, but it is too large to use as the
    day-to-day control surface. This board keeps the same evidence while making
    the actionable blockers visible without granting permission to stop
    anything.
    """
    endpoint_cards: list[dict[str, Any]] = []
    passive_wait_pids: list[int] = []
    long_running_test_pids: list[int] = []
    low_activity_test_pids: list[int] = []
    inspect_pids: list[int] = []
    inspect_cards: list[dict[str, Any]] = []
    risk_classes: dict[str, int] = {}

    for holder in sorted(holders, key=lambda item: str(item.get("pid"))):
        holder_type = holder["holder_type"]
        risk = str(holder.get("holder_risk_class") or "unclassified")
        risk_classes[risk] = risk_classes.get(risk, 0) + 1
        if holder_type == "test_runner":
            passive_wait_pids.append(holder["pid"])
            age = holder.get("age_seconds")
            if isinstance(age, (int, float)) and age >= LONG_RUNNING_TEST_SECONDS:
                long_running_test_pids.append(holder["pid"])
                cpu = holder.get("cpu_total_seconds")
                if isinstance(cpu, (int, float)) and cpu / max(age, 1.0) <= LOW_ACTIVITY_CPU_RATIO:
                    low_activity_test_pids.append(holder["pid"])
            continue
        if holder_type in {"unknown_python_holder", "stdin_python"}:
            inspect_pids.append(holder["pid"])
            inspect_cards.append({
                "pid": holder["pid"],
                "holder_type": holder_type,
                "holder_risk_class": holder.get("holder_risk_class"),
                "drain_posture": holder.get("drain_posture"),
                "script_evidence": holder.get("script_evidence"),
                "age_seconds": holder.get("age_seconds"),
                "process_status": holder.get("process_status"),
                "cpu_total_seconds": holder.get("cpu_total_seconds"),
                "allowed_action": holder["allowed_action"],
                "forbidden_action": holder["forbidden_action"],
            })
            continue
        if holder_type != "application_server":
            continue
        status = holder.get("authority_replacement_status", {})
        port_owners = status.get("port_owners", {})
        co_owner_pids = sorted({
            int(pid)
            for pids in port_owners.values()
            for pid in pids
            if int(pid) != int(holder["pid"])
        })
        holder_pids = {int(item["pid"]) for item in holders}
        endpoint_cards.append({
            "pid": holder["pid"],
            "status": status.get("status", "unknown"),
            "ports": status.get("ports", []),
            "port_owners": port_owners,
            "co_owner_pids": co_owner_pids,
            "non_holder_port_owner_pids": [
                pid for pid in co_owner_pids if pid not in holder_pids
            ],
            "state_path": holder["runtime_args"].get("state_path"),
            "age_seconds": holder.get("age_seconds"),
            "process_status": holder.get("process_status"),
            "cpu_total_seconds": holder.get("cpu_total_seconds"),
            "holder_risk_class": holder.get("holder_risk_class"),
            "drain_posture": holder.get("drain_posture"),
            "script_evidence": holder.get("script_evidence"),
            "authority_relaunch": holder.get("authority_relaunch"),
            "desktop_authority_handoff": holder.get("desktop_authority_handoff"),
            "allowed_action": holder["allowed_action"],
            "forbidden_action": holder["forbidden_action"],
        })

    blocked_endpoints = [
        card for card in endpoint_cards
        if card["status"] in {"blocked_by_this_live_holder", "shadow_holder_without_endpoint"}
    ]
    runnable_endpoints = [card for card in endpoint_cards if card["status"] == "runnable_now"]
    unknown_endpoints = [card for card in endpoint_cards if card["status"] == "unknown"]
    drift = source_drift or {"ok": True, "drift_count": 0}
    source_readiness = source_drift_archive_readiness(drift)
    source_drift_blocker = {
        "ok": bool(drift.get("ok")),
        "archive_ready": bool(source_readiness.get("ok")),
        "readiness_state": source_readiness.get("state"),
        "drift_count": int(drift.get("drift_count") or 0),
        "missing_in_authority": len(drift.get("missing_in_authority") or []),
        "different_from_authority": len(drift.get("different_from_authority") or []),
    }

    return {
        "schema": "archhub-runtime-handoff-board/v1",
        "purpose": (
            "compact visual/control evidence for draining copied node_runtime "
            "without interrupting running sessions"
        ),
        "archive_allowed": (
            not holders
            and int(replacement_summary.get("blocked_exact_authority_launches") or 0) == 0
            and source_drift_blocker["archive_ready"]
        ),
        "summary": {
            "holders": len(holders),
            "application_servers": len(endpoint_cards),
            "blocked_endpoints": len(blocked_endpoints),
            "runnable_endpoints": len(runnable_endpoints),
            "unknown_endpoints": len(unknown_endpoints),
            "passive_wait_pids": len(passive_wait_pids),
            "long_running_test_pids": len(long_running_test_pids),
            "low_activity_test_pids": len(low_activity_test_pids),
            "inspect_pids": len(inspect_pids),
            "handoff_steps": int(handoff_schedule.get("step_count") or 0),
            "replacement_specs": replacement_summary.get("replacement_specs", 0),
            "source_drift_count": source_drift_blocker["drift_count"],
        },
        "blockers": {
            "source_drift": source_drift_blocker,
            "passive_wait_pids": passive_wait_pids,
            "long_running_test_pids": long_running_test_pids,
            "low_activity_test_pids": low_activity_test_pids,
            "inspect_before_touch_pids": inspect_pids,
            "blocked_endpoint_pids": [card["pid"] for card in blocked_endpoints],
        },
        "risk_classes": dict(sorted(risk_classes.items())),
        "inspect_cards": inspect_cards,
        "endpoint_cards": endpoint_cards,
        "rule": (
            "This board is read-only evidence. It may name a relaunch command, "
            "but it must not execute, kill, archive, or move any holder."
        ),
    }


DISPOSABLE_QA_PORTS = {8515, 8516}
PROTECTED_VISIBLE_PORTS = {8482, 8484, 8501}


def build_disposable_holder_court(
    handoff_board: dict[str, Any],
    inspection: dict[str, Any],
) -> dict[str, Any]:
    """Judge whether inspected non-visible holders are disposable.

    This is an executable preflight only. It never stops a process and it never
    overrides the visible endpoint handoff rule.
    """
    protected_pids = _protected_handoff_pids(handoff_board)
    inspect_pids = set(
        int(pid)
        for pid in (
            (handoff_board.get("blockers") or {}).get("inspect_before_touch_pids")
            or []
        )
    )
    rows: list[dict[str, Any]] = []
    process_by_pid = {
        int(process["pid"]): process
        for process in inspection.get("processes") or []
        if isinstance(process, dict) and isinstance(process.get("pid"), int)
    }
    if not inspection.get("available", True):
        return {
            "schema": "archhub-disposable-runtime-holder-court/v1",
            "available": False,
            "cleanup_allowed_pids": [],
            "blocked_pids": [],
            "rows": [],
            "reason": inspection.get("reason") or "process inspection unavailable",
            "rule": (
                "No holder cleanup is allowed when read-only process inspection "
                "is unavailable."
            ),
        }
    for process in inspection.get("processes") or []:
        if not isinstance(process, dict) or not isinstance(process.get("pid"), int):
            continue
        pid = int(process["pid"])
        if pid not in inspect_pids and pid not in protected_pids:
            continue
        checks = _disposable_holder_checks(
            process,
            protected_pids=protected_pids,
            inspect_pids=inspect_pids,
            process_by_pid=process_by_pid,
        )
        failed = [name for name, ok in checks.items() if not ok]
        cleanup_allowed = not failed
        rows.append({
            "pid": pid,
            "verdict": (
                "disposable_cleanup_allowed"
                if cleanup_allowed
                else "blocked_or_unknown_holder"
            ),
            "cleanup_allowed": cleanup_allowed,
            "checks": checks,
            "failed_checks": failed,
            "risk_class": process.get("process_risk_class"),
            "listening_ports": process.get("listening_ports") or [],
            "established_connection_count": int(
                process.get("established_connection_count") or 0
            ),
            "rule": (
                "This row is a decision court only; it does not stop, relaunch, "
                "move, or archive the process."
            ),
        })
    return {
        "schema": "archhub-disposable-runtime-holder-court/v1",
        "available": True,
        "cleanup_allowed_pids": [
            row["pid"] for row in rows if row["cleanup_allowed"]
        ],
        "blocked_pids": [row["pid"] for row in rows if not row["cleanup_allowed"]],
        "rows": rows,
        "rule": (
            "A copied-runtime holder may be cleaned only when this court proves "
            "it is a non-visible disposable holder. The court itself remains "
            "read-only and never interrupts a process."
        ),
    }


def build_holder_tree_court(
    handoff_board: dict[str, Any],
    inspection: dict[str, Any],
) -> dict[str, Any]:
    """Group inspected holder PIDs by parent/child evidence.

    This is visual/control evidence only.  A process tree is still live if any
    PID in it is live; grouping prevents the operator from reading a parent and
    its child as unrelated blockers.
    """
    if not inspection.get("available", True):
        return {
            "schema": "archhub-runtime-holder-tree-court/v1",
            "available": False,
            "tree_count": 0,
            "trees": [],
            "reason": inspection.get("reason") or "process inspection unavailable",
            "rule": "No tree grouping is trusted when process inspection is unavailable.",
        }
    processes = [
        process
        for process in inspection.get("processes") or []
        if isinstance(process, dict) and isinstance(process.get("pid"), int)
    ]
    process_by_pid = {int(process["pid"]): process for process in processes}
    pids = set(process_by_pid)
    roots = sorted(
        pid
        for pid, process in process_by_pid.items()
        if int(process.get("parent_pid") or -1) not in pids
    )
    endpoint_pids = {
        int(pid)
        for pid in (handoff_board.get("blockers") or {}).get("blocked_endpoint_pids") or []
    }
    inspect_pids = {
        int(pid)
        for pid in (handoff_board.get("blockers") or {}).get("inspect_before_touch_pids") or []
    }

    def collect_tree(root: int) -> list[int]:
        ordered: list[int] = []
        stack = [root]
        while stack:
            pid = stack.pop(0)
            if pid in ordered or pid not in process_by_pid:
                continue
            ordered.append(pid)
            children = [
                int(child)
                for child in process_by_pid[pid].get("child_pids") or []
                if int(child) in process_by_pid
            ]
            stack.extend(sorted(children))
        return ordered

    trees: list[dict[str, Any]] = []
    for root in roots:
        tree_pids = collect_tree(root)
        tree_processes = [process_by_pid[pid] for pid in tree_pids]
        risk_classes = sorted({
            str(process.get("process_risk_class") or "unclassified")
            for process in tree_processes
        })
        listening_ports = sorted({
            int(port)
            for process in tree_processes
            for port in process.get("listening_ports") or []
        })
        established = sum(
            int(process.get("established_connection_count") or 0)
            for process in tree_processes
        )
        if endpoint_pids.intersection(tree_pids):
            posture = "coordinate_visible_endpoint_handoff"
        elif inspect_pids.intersection(tree_pids):
            posture = "inspect_unknown_holder_tree"
        else:
            posture = "observed_child_dependency"
        trees.append({
            "root_pid": root,
            "pids": tree_pids,
            "posture": posture,
            "risk_classes": risk_classes,
            "listening_ports": listening_ports,
            "established_connection_count": established,
            "interrupt_allowed": False,
            "rule": (
                "Tree grouping is evidence only; it does not stop, relaunch, "
                "move, archive, or mark a holder safe."
            ),
        })
    return {
        "schema": "archhub-runtime-holder-tree-court/v1",
        "available": True,
        "tree_count": len(trees),
        "trees": trees,
        "rule": (
            "A holder tree is one live blocker group when parent/child evidence "
            "connects its PIDs; cleanup still requires a separate disposable "
            "holder court."
        ),
    }


def build_stale_stdin_tree_court(
    holder_tree_court: dict[str, Any],
    inspection: dict[str, Any],
) -> dict[str, Any]:
    """Decide if an unknown stdin holder tree is stale enough to clean.

    This deliberately does not modify the broader disposable-holder court.  A
    stdin tree must prove a stricter no-client/no-visible-port/low-activity
    shape before a later exact PID cleanup can touch it.
    """
    if not inspection.get("available", True) or not holder_tree_court.get("available", True):
        return {
            "schema": "archhub-stale-stdin-holder-tree-court/v1",
            "available": False,
            "cleanup_allowed_trees": [],
            "blocked_trees": [],
            "reason": "process inspection or holder-tree grouping unavailable",
            "rule": "No stale stdin cleanup is allowed without current inspection.",
        }
    process_by_pid = {
        int(process["pid"]): process
        for process in inspection.get("processes") or []
        if isinstance(process, dict) and isinstance(process.get("pid"), int)
    }
    allowed: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    for tree in holder_tree_court.get("trees") or []:
        if not isinstance(tree, dict):
            continue
        pids = [int(pid) for pid in tree.get("pids") or []]
        processes = [process_by_pid[pid] for pid in pids if pid in process_by_pid]
        checks = _stale_stdin_tree_checks(tree, processes)
        failed = [name for name, ok in checks.items() if not ok]
        row = {
            "root_pid": tree.get("root_pid"),
            "pids": pids,
            "cleanup_allowed": not failed,
            "checks": checks,
            "failed_checks": failed,
            "rule": (
                "This row is a decision court only. Cleanup still requires an "
                "immediate exact PID/command/port recheck."
            ),
        }
        rows.append(row)
        (allowed if row["cleanup_allowed"] else blocked).append(row)
    return {
        "schema": "archhub-stale-stdin-holder-tree-court/v1",
        "available": True,
        "cleanup_allowed_trees": [
            {"root_pid": row["root_pid"], "pids": row["pids"]}
            for row in allowed
        ],
        "blocked_trees": [
            {"root_pid": row["root_pid"], "pids": row["pids"]}
            for row in blocked
        ],
        "rows": rows,
        "rule": (
            "Only stale stdin process trees with no clients, no protected ports, "
            "low activity, and no HTTP identity may be cleaned."
        ),
    }


def _stale_stdin_tree_checks(
    tree: dict[str, Any],
    processes: list[dict[str, Any]],
) -> dict[str, bool]:
    risk_classes = {
        str(process.get("process_risk_class") or "")
        for process in processes
    }
    listening_ports = {
        int(port)
        for process in processes
        for port in process.get("listening_ports") or []
    }
    ages = [
        float(process.get("age_seconds"))
        for process in processes
        if isinstance(process.get("age_seconds"), (int, float))
    ]
    cpu_ratios = [
        float(process.get("cpu_total_seconds") or 0.0)
        / max(float(process.get("age_seconds") or 1.0), 1.0)
        for process in processes
        if isinstance(process.get("age_seconds"), (int, float))
    ]
    http_identity = any(
        bool(fingerprint.get("ok"))
        and int(fingerprint.get("status") or 0) < 500
        for process in processes
        for fingerprint in process.get("endpoint_fingerprints") or []
        if isinstance(fingerprint, dict)
    )
    return {
        "tree_is_unknown_stdin": tree.get("posture") == "inspect_unknown_holder_tree",
        "all_processes_present": bool(processes) and len(processes) == len(tree.get("pids") or []),
        "only_stdin_python_risks": bool(risk_classes) and risk_classes.issubset({
            "stdin_python_parent",
            "stdin_python_listener_child",
        }),
        "has_listener": bool(listening_ports),
        "no_protected_visible_ports": not listening_ports.intersection(
            PROTECTED_VISIBLE_PORTS
        ),
        "no_established_clients": all(
            int(process.get("established_connection_count") or 0) == 0
            for process in processes
        ),
        "stale_by_age": bool(ages) and min(ages) >= LONG_RUNNING_TEST_SECONDS,
        "low_cpu_activity": bool(cpu_ratios) and max(cpu_ratios) <= LOW_ACTIVITY_CPU_RATIO,
        "no_http_identity": not http_identity,
        "root_has_child": len(tree.get("pids") or []) > 1,
    }


def _protected_handoff_pids(handoff_board: dict[str, Any]) -> set[int]:
    protected: set[int] = set()
    blockers = handoff_board.get("blockers") or {}
    for key in ("blocked_endpoint_pids", "passive_wait_pids"):
        protected.update(int(pid) for pid in blockers.get(key) or [])
    for card in handoff_board.get("endpoint_cards") or []:
        if isinstance(card.get("pid"), int):
            protected.add(int(card["pid"]))
        protected.update(int(pid) for pid in card.get("co_owner_pids") or [])
        protected.update(
            int(pid) for pid in card.get("non_holder_port_owner_pids") or []
        )
    return protected


def _disposable_holder_checks(
    process: dict[str, Any],
    *,
    protected_pids: set[int],
    inspect_pids: set[int],
    process_by_pid: dict[int, dict[str, Any]],
) -> dict[str, bool]:
    pid = int(process.get("pid"))
    risk = str(process.get("process_risk_class") or "")
    ports = {int(port) for port in process.get("listening_ports") or []}
    child_pids = [int(child) for child in process.get("child_pids") or []]
    fingerprints = process.get("endpoint_fingerprints") or []
    script_path = str(process.get("script_path") or "")
    has_http_probe = any(
        bool(item.get("ok")) and int(item.get("status") or 0) < 500
        for item in fingerprints
        if isinstance(item, dict)
    )
    known_missing_temp_qa = (
        risk == "qa_server_script_missing"
        and script_path.lower().endswith("archhub_nary_qa_server.py")
        and process.get("script_exists") is False
    )
    return {
        "exists": process.get("exists") is True,
        "is_inspect_before_touch_holder": pid in inspect_pids,
        "not_protected_endpoint_or_coowner": pid not in protected_pids,
        "known_disposable_shape": known_missing_temp_qa,
        "no_child_dependency": _no_unsafe_child_dependency(
            child_pids,
            process_by_pid,
        ),
        "no_established_clients": int(
            process.get("established_connection_count") or 0
        ) == 0,
        "known_local_qa_ports_only": bool(ports) and ports.issubset(
            DISPOSABLE_QA_PORTS
        ),
        "fingerprint_matches_expected_qa_surface": has_http_probe,
    }


def _no_unsafe_child_dependency(
    child_pids: list[int],
    process_by_pid: dict[int, dict[str, Any]],
) -> bool:
    if not child_pids:
        return True
    return all(
        _is_inert_console_child(process_by_pid.get(child_pid))
        for child_pid in child_pids
    )


def _is_inert_console_child(process: dict[str, Any] | None) -> bool:
    if not process or process.get("exists") is not True:
        return False
    name = str(process.get("name") or "").lower()
    command = str(process.get("cmdline") or "").lower()
    return (
        name == "conhost.exe"
        and "conhost.exe" in command
        and not (process.get("child_pids") or [])
        and not (process.get("listening_ports") or [])
        and int(process.get("established_connection_count") or 0) == 0
    )


def duplicate_server_groups(holders: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[int | None, int | None, str | None], list[dict[str, Any]]] = {}
    for holder in holders:
        if holder["holder_type"] != "application_server":
            continue
        args = holder["runtime_args"]
        key = (args.get("port"), args.get("cloud_port"), args.get("state_path"))
        groups.setdefault(key, []).append(holder)
    duplicates: list[dict[str, Any]] = []
    for (port, cloud_port, state_path), items in sorted(groups.items(), key=lambda item: str(item[0])):
        if len(items) < 2:
            continue
        duplicates.append({
            "port": port,
            "cloud_port": cloud_port,
            "state_path": state_path,
            "pids": [item["pid"] for item in items],
            "authority_relaunch": items[0].get("authority_relaunch"),
            "desktop_authority_handoff": items[0].get("desktop_authority_handoff"),
            "required_action": (
                "coordinate before stopping anything; this looks like duplicate "
                "legacy servers for the same endpoint/state and should be "
                "collapsed into one Universal Cell authority launch"
            ),
        })
    return duplicates


def active_tcp_listeners() -> dict[int, set[int]]:
    """Return local TCP listening ports by owning PID.

    This is read-only process evidence. If psutil is unavailable or the OS
    refuses a connection row, the drain plan still works but cannot classify
    exact port blockers.
    """
    try:
        import psutil  # type: ignore
    except Exception:
        return {}

    listeners: dict[int, set[int]] = {}
    try:
        connections = psutil.net_connections(kind="tcp")
    except Exception:
        return listeners
    for conn in connections:
        try:
            if str(conn.status).upper() != "LISTEN" or conn.pid is None or not conn.laddr:
                continue
            port = int(conn.laddr.port)
            listeners.setdefault(port, set()).add(int(conn.pid))
        except (AttributeError, TypeError, ValueError):
            continue
    return listeners


def annotate_authority_replacements(
    holders: list[dict[str, Any]],
    listener_map: dict[int, set[int]],
) -> dict[str, Any]:
    blocked = 0
    endpoint_owners = 0
    shadow_holders = 0
    runnable_now = 0
    unknown = 0
    for holder in holders:
        if holder["holder_type"] != "application_server":
            continue
        args = holder["runtime_args"]
        wanted_ports = [
            port for port in (args.get("port"), args.get("cloud_port")) if port is not None
        ]
        if not wanted_ports:
            holder["authority_replacement_status"] = {
                "status": "unknown",
                "reason": "server command has no parsed port arguments",
                "ports": [],
            }
            unknown += 1
            continue
        port_owners = {str(port): sorted(listener_map.get(int(port), set())) for port in wanted_ports}
        owned_ports = [
            int(port)
            for port, pids in port_owners.items()
            if holder.get("pid") in pids
        ]
        occupied_ports = [
            int(port)
            for port, pids in port_owners.items()
            if pids
        ]
        if occupied_ports:
            blocked += 1
            if owned_ports:
                endpoint_owners += 1
                status = "blocked_by_this_live_holder"
                reason = (
                    "exact authority replacement would bind the same live port; "
                    "coordinate handoff before relaunch"
                )
            else:
                shadow_holders += 1
                status = "shadow_holder_without_endpoint"
                reason = (
                    "holder still references copied runtime but does not own the "
                    "parsed endpoint; inspect before any interruption"
                )
        else:
            runnable_now += 1
            status = "runnable_now"
            reason = "parsed endpoint is not currently listening"
        holder["authority_replacement_status"] = {
            "status": status,
            "reason": reason,
            "ports": wanted_ports,
            "port_owners": port_owners,
        }
    return {
        "replacement_specs": sum(1 for holder in holders if holder["holder_type"] == "application_server"),
        "blocked_exact_authority_launches": blocked,
        "endpoint_owning_legacy_holders": endpoint_owners,
        "shadow_legacy_holders": shadow_holders,
        "runnable_now": runnable_now,
        "unknown": unknown,
        "rule": "do not execute exact authority relaunch while its target ports are occupied",
    }


def authority_relaunch_spec(holder: dict[str, Any], authority: Path) -> dict[str, Any] | None:
    if holder["holder_type"] != "application_server":
        return None
    args = holder["runtime_args"]
    command = ["python", "-m", "nodelang.application_server"]
    if args.get("host"):
        command += ["--host", args["host"]]
    if args.get("port") is not None:
        command += ["--port", str(args["port"])]
    if args.get("cloud_host"):
        command += ["--cloud-host", args["cloud_host"]]
    if args.get("cloud_port") is not None:
        command += ["--cloud-port", str(args["cloud_port"])]
    if args.get("state_path"):
        command += ["--state-path", args["state_path"]]
    if args.get("fresh"):
        command.append("--fresh")
    return {
        "cwd": str(authority),
        "command": command,
        "dry_run_only": True,
        "machine_transport": False,
        "note": (
            "Derived raw server relaunch command only; this planner does not "
            "execute it. This preserves parsed server flags but does not enable "
            "the Brain/Workshop machine transport."
        ),
    }


def desktop_authority_handoff_spec(
    holder: dict[str, Any],
    authority: Path,
) -> dict[str, Any] | None:
    if holder["holder_type"] != "application_server":
        return None
    args = holder["runtime_args"]
    state_path = str(args.get("state_path") or "")
    default_state = str(
        Path.home() / "AppData" / "Local" / "ArchHub" / "node-native-wip.json.gz"
    )
    default_endpoint = args.get("port") in (None, 8482)
    default_state_path = (not state_path) or Path(state_path) == Path(default_state)
    candidate = bool(default_endpoint and default_state_path)
    return {
        "cwd": str(authority),
        "command": ["python", "-m", "nodelang.desktop"],
        "dry_run_only": True,
        "machine_transport": True,
        "visible_url": "http://127.0.0.1:8482",
        "state_path": default_state,
        "status": (
            "blocked_until_visible_authority_handoff"
            if candidate else "not_exact_for_non_default_endpoint"
        ),
        "requires_endpoint_free": True,
        "requires_machine_descriptor_free": True,
        "requires_browser_session_handoff": True,
        "safe_to_execute_now": False,
        "note": (
            "DesktopRuntime is the intended founder-facing authority launch "
            "path, but this card is not executable evidence. A real handoff must "
            "prove the visible endpoint is free, the machine descriptor is not "
            "owned by another authority bridge, and the browser session can be "
            "transferred without falling back to a copied runtime."
        ),
    }


def authority_bridge_launch_spec(
    authority: Path,
    holders: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    default_state = str(
        Path.home() / "AppData" / "Local" / "ArchHub" / "node-native-wip.json.gz"
    )
    default_descriptor = str(
        Path.home() / "AppData" / "Local" / "ArchHub"
        / "active-universal-runtime.json"
    )
    default_status = str(
        Path.home() / "AppData" / "Local" / "ArchHub" / "authority-bridge.json"
    )
    live_state_owner_pids: list[int] = []
    for holder in holders or ():
        if holder.get("holder_type") != "application_server":
            continue
        args = holder.get("runtime_args") or {}
        state_path = str(args.get("state_path") or "")
        try:
            targets_default_state = (
                not state_path
                or Path(state_path).expanduser().resolve()
                == Path(default_state).expanduser().resolve()
            )
        except OSError:
            targets_default_state = state_path == default_state
        if targets_default_state and type(holder.get("pid")) is int:
            live_state_owner_pids.append(holder["pid"])
    live_state_owner_pids.sort()
    return {
        "cwd": str(authority),
        "command": [
            "python", "-m", "nodelang.authority_bridge", "--standalone-owner",
        ],
        "dry_run_only": True,
        "machine_transport": True,
        "safe_to_execute_now": False,
        "requires_exclusive_universal_state": True,
        "requires_founder_approved_handoff": True,
        "live_default_state_owner_pids": live_state_owner_pids,
        "state_path": default_state,
        "descriptor_path": default_descriptor,
        "status_path": default_status,
        "window_style": "hidden",
        "note": (
            "Headless authority bridge: starts the Node Language "
            "ApplicationServer on an OS-assigned local port with Universal "
            "machine transport enabled. It does not bind 8482/8484 or stop "
            "a copied host, but it can supersede graph ownership if both use "
            "the same Universal state. Do not launch it while a live default "
            "state owner is present; use a controlled founder-approved handoff."
        ),
    }


def authority_launch_readiness(authority: Path) -> dict[str, Any]:
    required_flags = (
        "--host",
        "--port",
        "--cloud-host",
        "--cloud-port",
        "--state-path",
        "--fresh",
        "--universal-state-path",
        "--universal-checkpoint-path",
        "--universal-checkpoint-authority-path",
    )
    bridge_required_flags = (
        "--state-path",
        "--descriptor-path",
        "--status-path",
        "--probe",
        "--standalone-owner",
    )
    module_path = authority / "nodelang" / "application_server.py"
    bridge_module_path = authority / "nodelang" / "authority_bridge.py"
    result: dict[str, Any] = {
        "schema": "archhub-authority-launch-readiness/v1",
        "authority": str(authority),
        "module": "nodelang.application_server",
        "module_path": str(module_path),
        "module_exists": module_path.exists(),
        "command": [sys.executable, "-m", "nodelang.application_server", "--help"],
        "bridge_module": "nodelang.authority_bridge",
        "bridge_module_path": str(bridge_module_path),
        "bridge_module_exists": bridge_module_path.exists(),
        "bridge_command": [sys.executable, "-m", "nodelang.authority_bridge", "--help"],
        "ok": False,
        "required_flags": list(required_flags),
        "missing_flags": list(required_flags),
        "bridge_required_flags": list(bridge_required_flags),
        "bridge_missing_flags": list(bridge_required_flags),
    }
    if not result["module_exists"]:
        result["reason"] = "authority application_server module is missing"
        return result
    if not result["bridge_module_exists"]:
        result["reason"] = "authority bridge module is missing"
        return result
    try:
        completed = subprocess.run(
            result["command"],
            cwd=str(authority),
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )
    except Exception as exc:
        result["reason"] = f"authority help command failed before completion: {exc}"
        return result
    help_text = (completed.stdout or "") + (completed.stderr or "")
    missing = [flag for flag in required_flags if flag not in help_text]
    try:
        bridge_completed = subprocess.run(
            result["bridge_command"],
            cwd=str(authority),
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )
    except Exception as exc:
        result.update({
            "returncode": completed.returncode,
            "missing_flags": missing,
            "reason": f"authority bridge help command failed before completion: {exc}",
        })
        return result
    bridge_help = (bridge_completed.stdout or "") + (bridge_completed.stderr or "")
    bridge_missing = [
        flag for flag in bridge_required_flags if flag not in bridge_help
    ]
    ok = (
        completed.returncode == 0
        and not missing
        and bridge_completed.returncode == 0
        and not bridge_missing
    )
    result.update({
        "returncode": completed.returncode,
        "bridge_returncode": bridge_completed.returncode,
        "missing_flags": missing,
        "bridge_missing_flags": bridge_missing,
        "ok": ok,
        "reason": (
            "authority application_server and authority_bridge CLIs are importable and expose required handoff flags"
            if ok
            else "authority launch CLIs are not ready for derived handoff commands"
        ),
    })
    return result


def authority_shadow_launch_probe_not_run(authority: Path) -> dict[str, Any]:
    return {
        "schema": "archhub-authority-shadow-launch-probe/v1",
        "authority": str(authority),
        "ok": False,
        "ran": False,
        "reason": (
            "shadow launch probe was not run; pass --authority-shadow-probe "
            "before using the retirement gate as green evidence"
        ),
    }


def authority_shadow_launch_probe(authority: Path) -> dict[str, Any]:
    module_path = authority / "nodelang" / "application_server.py"
    result: dict[str, Any] = {
        "schema": "archhub-authority-shadow-launch-probe/v1",
        "authority": str(authority),
        "module": "nodelang.application_server",
        "module_path": str(module_path),
        "module_exists": module_path.exists(),
        "command": [sys.executable, "-c", "<authority-shadow-launch-probe>"],
        "ok": False,
        "ran": True,
    }
    if not module_path.exists():
        result["reason"] = "authority application_server module is missing"
        return result
    probe_script = r'''
import json
import re
import tempfile
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.request import HTTPCookieProcessor, build_opener

from nodelang.application_server import ApplicationServer
from nodelang.application_machine_transport import UniversalRuntimeClient
from nodelang.cell_secret_keys import MemorySigningKeyProvider

result = {"ok": False}
try:
    with tempfile.TemporaryDirectory(prefix="archhub-authority-shadow-") as tmp:
        state_path = Path(tmp) / "shadow-state.json.gz"
        descriptor_path = Path(tmp) / "active-universal-runtime.json"
        provider = MemorySigningKeyProvider(
            "archhub.local.universal-runtime-pipe",
            b"s" * 32,
        )
        server = None
        try:
            server = ApplicationServer(
                host="127.0.0.1",
                port=0,
                cloud_host="127.0.0.1",
                cloud_port=0,
                state_path=state_path,
                enable_machine_transport=True,
                machine_descriptor_path=descriptor_path,
                machine_key_provider=provider,
            ).start()
            opener = build_opener(HTTPCookieProcessor(CookieJar()))
            with opener.open(server.bootstrap_url, timeout=30) as response:
                page = response.read().decode("utf-8")
                bootstrap_status = response.status
                cookie = response.headers.get("Set-Cookie") or ""
            csrf_match = re.search(
                r'<meta name="archhub-csrf" content="([A-Za-z0-9_-]+)">',
                page,
            )
            with opener.open(server.url + "/api/state", timeout=30) as response:
                state_payload = json.loads(response.read().decode("utf-8"))
                state_status = response.status
            with opener.open(
                server.url + "/api/universal/health", timeout=30
            ) as response:
                health_payload = json.loads(response.read().decode("utf-8"))
                health_status = response.status
            machine_client = UniversalRuntimeClient(descriptor_path, provider)
            machine_work = machine_client.request(
                "GET", "/api/universal/work"
            )
            result = {
                "ok": (
                    bootstrap_status == 200
                    and state_status == 200
                    and health_status == 200
                    and state_payload.get("valid") is True
                    and health_payload.get("ok") is True
                    and machine_work.get("application")
                    == server.universal_registry.application_root
                    and machine_work.get("registry")
                    == server.universal_registry.governed_work_registry_root
                ),
                "server_url": server.url,
                "bootstrap_status": bootstrap_status,
                "state_status": state_status,
                "health_status": health_status,
                "state_valid": state_payload.get("valid"),
                "health_ok": health_payload.get("ok"),
                "cells": health_payload.get("cells"),
                "revision": health_payload.get("revision"),
                "machine_transport_descriptor": descriptor_path.exists(),
                "machine_work_application": machine_work.get("application"),
                "machine_work_registry": machine_work.get("registry"),
                "machine_work_items": len(machine_work.get("items") or []),
                "csrf_meta_present": bool(csrf_match),
                "session_cookie_http_only": "HttpOnly" in cookie,
                "state_path_inside_temp": str(state_path).startswith(tmp),
            }
        finally:
            if server is not None:
                server.close()
except Exception as exc:
    result = {
        "ok": False,
        "error_type": type(exc).__name__,
        "error": str(exc),
    }
print(json.dumps(result, sort_keys=True))
'''
    try:
        completed = subprocess.run(
            [sys.executable, "-c", probe_script],
            cwd=str(authority),
            text=True,
            capture_output=True,
            timeout=120,
            check=False,
        )
    except Exception as exc:
        result["reason"] = f"authority shadow launch probe failed before completion: {exc}"
        return result
    result.update({
        "returncode": completed.returncode,
        "stderr_tail": (completed.stderr or "")[-2000:],
    })
    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError:
        result["reason"] = "authority shadow launch probe did not emit JSON"
        result["stdout_tail"] = (completed.stdout or "")[-2000:]
        return result
    result.update(payload)
    result["ok"] = completed.returncode == 0 and bool(payload.get("ok"))
    result["reason"] = (
        "authority shadow launch started on temporary ports and served authenticated state/health plus machine work transport"
        if result["ok"]
        else "authority shadow launch did not prove authenticated state/health plus machine work transport"
    )
    return result


def active_authority_runtime_bridge_status(
    product_root: Path,
    workspace: Path,
) -> dict[str, Any]:
    descriptor = (
        Path.home() / "AppData" / "Local" / "ArchHub"
        / "active-universal-runtime.json"
    )
    result: dict[str, Any] = {
        "schema": "archhub-active-authority-runtime-bridge/v1",
        "authority": str(workspace / "10.PRODUCT" / "13.NODE-LANGUAGE"),
        "descriptor": str(descriptor),
        "descriptor_exists": descriptor.exists(),
        "ok": False,
    }
    if descriptor.exists():
        try:
            payload = json.loads(descriptor.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            result.update({
                "reason": "active Universal runtime descriptor is unreadable",
                "error_type": type(exc).__name__,
            })
            return result
        result.update({
            "descriptor_status": payload.get("status"),
            "descriptor_process_id": payload.get("process_id"),
            "descriptor_runtime_id": payload.get("runtime_id"),
            "descriptor_database": payload.get("database"),
        })
        if payload.get("status") != "active":
            result["reason"] = "active Universal runtime descriptor is not active"
            return result
    source = product_root / "personal-brain-mcp" / "src"
    if not source.is_dir():
        result["reason"] = "personal-brain runtime bridge source is unavailable"
        return result
    inserted = str(source) not in sys.path
    if inserted:
        sys.path.insert(0, str(source))
    try:
        from personal_brain.universal_runtime import (  # noqa: WPS433
            UniversalRuntimeBridge,
        )

        bridge = UniversalRuntimeBridge()
        state = _runtime_work_index(
            bridge,
            response_timeout_seconds=ACTIVE_AUTHORITY_RUNTIME_RESPONSE_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        result.update({
            "reason": str(exc),
            "error_type": type(exc).__name__,
        })
        return result
    handoff: dict[str, Any] = {}
    handoff_error: dict[str, str] = {}
    try:
        try:
            handoff = bridge.browser_handoff_status(
                response_timeout_seconds=ACTIVE_AUTHORITY_RUNTIME_RESPONSE_TIMEOUT_SECONDS
            )
        except TypeError:
            handoff = bridge.browser_handoff_status()
    except Exception as exc:
        handoff_error = {
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
    finally:
        if inserted:
            try:
                sys.path.remove(str(source))
            except ValueError:
                pass
    handoff_ok = (
        handoff.get("application") == "app:archhub"
        and handoff.get("supported") is True
        and handoff.get("one_use_route") == "POST /api/universal/browser-handoff"
        and type(handoff.get("server_url")) is str
        and str(handoff.get("server_url")).startswith("http://127.0.0.1:")
    )
    result.update({
        "ok": bool(handoff_ok),
        "reason": (
            "active Universal runtime bridge is reachable and proves visible browser handoff readiness"
            if handoff_ok
            else "active Universal runtime bridge is reachable through the compact work index but visible browser handoff is not proven"
        ),
        "machine_work_index_ok": True,
        "visible_browser_handoff_ok": bool(handoff_ok),
        "visible_browser_handoff": {
            "supported": handoff.get("supported"),
            "application": handoff.get("application"),
            "server_url": handoff.get("server_url"),
            "one_use_route": handoff.get("one_use_route"),
            "revision": handoff.get("revision"),
            **handoff_error,
        },
        "revision": state.get("revision"),
        "application": state.get("application"),
        "registry": state.get("registry"),
        "brain_scope": state.get("brain_scope"),
        "items": len(state.get("items") or []),
        "agent_session": state.get("agent_session"),
    })
    return result


def _runtime_work_index(
    runtime: Any, *, response_timeout_seconds: float | None = None
) -> dict[str, Any]:
    work_index = getattr(runtime, "work_index", None)
    if callable(work_index):
        if response_timeout_seconds is not None:
            try:
                return work_index(
                    response_timeout_seconds=response_timeout_seconds
                )
            except TypeError:
                pass
        return work_index()
    if response_timeout_seconds is not None:
        try:
            return runtime.work_list(
                response_timeout_seconds=response_timeout_seconds
            )
        except TypeError:
            pass
    return runtime.work_list()


def build_handoff_schedule(
    holders: list[dict[str, Any]],
    duplicate_groups: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build an ordered, non-executing handoff schedule.

    The schedule is intentionally conservative: it names what must be inspected
    or coordinated, but it never chooses to stop a process.
    """
    by_pid = {holder.get("pid"): holder for holder in holders}
    steps: list[dict[str, Any]] = []
    sequence = 1

    test_pids = sorted(
        holder["pid"] for holder in holders if holder["holder_type"] == "test_runner"
    )
    if test_pids:
        steps.append({
            "sequence": sequence,
            "kind": "passive_wait",
            "pids": test_pids,
            "required_action": (
                "let test runners finish naturally or verify they are stale "
                "before any manual cleanup"
            ),
            "may_interrupt": False,
        })
        sequence += 1

    unknown_pids = sorted(
        holder["pid"]
        for holder in holders
        if holder["holder_type"] in {"unknown_python_holder", "stdin_python"}
    )
    if unknown_pids:
        inspect_cards = [
            {
                "pid": holder["pid"],
                "holder_type": holder["holder_type"],
                "holder_risk_class": holder.get("holder_risk_class"),
                "drain_posture": holder.get("drain_posture"),
                "script_evidence": holder.get("script_evidence"),
            }
            for holder in holders
            if holder["pid"] in unknown_pids
        ]
        steps.append({
            "sequence": sequence,
            "kind": "inspect_unknown_holder",
            "pids": unknown_pids,
            "inspect_cards": inspect_cards,
            "required_action": (
                "identify owner and purpose; do not archive copied runtime while "
                "these holders reference it"
            ),
            "may_interrupt": False,
        })
        sequence += 1

    for group in duplicate_groups:
        pids = list(group["pids"])
        owners = [
            pid for pid in pids
            if by_pid.get(pid, {}).get("authority_replacement_status", {}).get("status")
            == "blocked_by_this_live_holder"
        ]
        shadows = [
            pid for pid in pids
            if by_pid.get(pid, {}).get("authority_replacement_status", {}).get("status")
            == "shadow_holder_without_endpoint"
        ]
        steps.append({
            "sequence": sequence,
            "kind": "coordinate_duplicate_endpoint_handoff",
            "port": group["port"],
            "cloud_port": group["cloud_port"],
            "state_path": group["state_path"],
            "endpoint_owner_pids": owners,
            "shadow_pids": shadows,
            "authority_relaunch": group["authority_relaunch"],
            "desktop_authority_handoff": group["desktop_authority_handoff"],
            "required_action": (
                "choose a handoff window for the endpoint owner, then relaunch "
                "the same endpoint from the Universal Cell authority; inspect "
                "shadow holders separately before cleanup"
            ),
            "may_interrupt": False,
        })
        sequence += 1

    grouped_pids = {pid for group in duplicate_groups for pid in group["pids"]}
    ungrouped_servers = [
        holder for holder in holders
        if holder["holder_type"] == "application_server" and holder["pid"] not in grouped_pids
    ]
    for holder in sorted(ungrouped_servers, key=lambda item: str(item.get("pid"))):
        status = holder.get("authority_replacement_status", {})
        steps.append({
            "sequence": sequence,
            "kind": "coordinate_single_endpoint_handoff",
            "pid": holder["pid"],
            "status": status.get("status"),
            "ports": status.get("ports", []),
            "authority_relaunch": holder.get("authority_relaunch"),
            "desktop_authority_handoff": holder.get("desktop_authority_handoff"),
            "required_action": (
                "coordinate the visible session before relaunching this endpoint "
                "from the Universal Cell authority"
            ),
            "may_interrupt": False,
        })
        sequence += 1

    steps.append({
        "sequence": sequence,
        "kind": "verify_drain_complete",
        "command": [
            "python",
            "tools/legacy_runtime_drain.py",
            "--no-write",
            "--enforce-drained",
        ],
        "required_action": (
            "only archive node_runtime after this command proves holder_count is zero"
        ),
        "may_interrupt": False,
    })
    return {
        "schema": "archhub-legacy-runtime-handoff-schedule/v1",
        "step_count": len(steps),
        "all_steps_non_interrupting": all(not step["may_interrupt"] for step in steps),
        "steps": steps,
    }


def source_drift_archive_readiness(
    source_drift: dict[str, Any] | None,
) -> dict[str, Any]:
    if source_drift is None:
        return {
            "ok": True,
            "state": "not_checked",
            "reason": "no source drift report was supplied to this gate",
        }
    if bool(source_drift.get("ok")):
        return {
            "ok": True,
            "state": "clear",
            "drift_count": int(source_drift.get("drift_count") or 0),
            "reason": "runtime copy has no source drift against authority",
        }
    decision = source_drift.get("decision_summary")
    if not isinstance(decision, dict):
        return {
            "ok": False,
            "state": "unclassified_source_drift",
            "drift_count": int(source_drift.get("drift_count") or 0),
            "reason": (
                "runtime source drift exists without a decision summary; "
                "classify before any archive"
            ),
        }
    candidates = [
        candidate
        for candidate in source_drift.get("migration_candidates") or []
        if isinstance(candidate, dict)
    ]
    states = {
        str(candidate.get("resolution_state") or "classified_unresolved")
        for candidate in candidates
    }
    allowed_states = {
        "canonical_evidence_recorded_pending_runtime_retirement",
        "preserved_as_migration_evidence_pending_runtime_retirement",
        "pending_canonical_root_decision",
    }
    unmapped_paths = decision.get("unmapped_paths") or []
    disallowed_states = sorted(states - allowed_states)
    ok = (
        bool(decision.get("all_classified"))
        and not unmapped_paths
        and bool(decision.get("promotion_allowed")) is False
        and bool(decision.get("bulk_copy_allowed")) is False
        and not disallowed_states
        and len(candidates) == int(source_drift.get("migration_candidate_count") or 0)
    )
    return {
        "ok": ok,
        "state": (
            "classified_migration_evidence_ready_for_archive"
            if ok
            else "source_drift_requires_decision"
        ),
        "drift_count": int(source_drift.get("drift_count") or 0),
        "candidate_count": len(candidates),
        "allowed_resolution_states": sorted(allowed_states),
        "seen_resolution_states": sorted(states),
        "disallowed_resolution_states": disallowed_states,
        "unmapped_paths": unmapped_paths,
        "promotion_allowed": bool(decision.get("promotion_allowed")),
        "bulk_copy_allowed": bool(decision.get("bulk_copy_allowed")),
        "reason": (
            "runtime source drift is physically present but fully classified as "
            "non-promotable migration evidence; archive may preserve it only "
            "after live holders are gone"
            if ok
            else "runtime source drift still has unclassified, promotable, or unresolved candidates"
        ),
    }


def build_retirement_gate(
    holder_report: dict[str, Any],
    readiness: dict[str, Any],
    shadow_probe: dict[str, Any],
    active_bridge: dict[str, Any],
    replacement_summary: dict[str, Any],
    handoff_schedule: dict[str, Any],
    source_drift: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source_readiness = source_drift_archive_readiness(source_drift)
    checks = {
        "runtime_copy_exists": bool(holder_report.get("exists")),
        "runtime_copy_source_drift_archive_ready": bool(source_readiness.get("ok")),
        "authority_launch_ready": bool(readiness.get("ok")),
        "authority_shadow_launch_proven": bool(shadow_probe.get("ok")),
        "active_authority_runtime_bridge": bool(active_bridge.get("ok")),
        "no_live_holders": int(holder_report.get("holder_count") or 0) == 0,
        "no_blocked_exact_replacements": (
            int(replacement_summary.get("blocked_exact_authority_launches") or 0) == 0
        ),
        "handoff_schedule_non_interrupting": bool(
            handoff_schedule.get("all_steps_non_interrupting")
        ),
    }
    failures = [name for name, ok in checks.items() if not ok]
    archive_allowed = not failures
    if archive_allowed:
        required_action = (
            "archive copied node_runtime through governed archive procedure; "
            "rerun WIP classifier and focused courts afterward"
        )
    else:
        required_action = (
            "do not archive copied node_runtime; complete the non-interrupting "
            "handoff schedule and rerun this gate"
        )
    return {
        "schema": "archhub-runtime-copy-retirement-gate/v1",
        "archive_allowed": archive_allowed,
        "checks": checks,
        "source_drift_archive_readiness": source_readiness,
        "failures": failures,
        "required_action": required_action,
    }


def _existing_universal_external_keys(runtime_state: dict[str, Any]) -> dict[str, str]:
    existing: dict[str, str] = {}
    for item in runtime_state.get("items") or ():
        if not isinstance(item, dict):
            continue
        interfaces = item.get("interfaces")
        if not isinstance(interfaces, dict):
            continue
        external = interfaces.get("external-key")
        if not isinstance(external, dict):
            continue
        value = external.get("value")
        root = item.get("root")
        if isinstance(value, str) and isinstance(root, str):
            existing[value] = root
    return existing


def holder_external_key(holder: dict[str, Any]) -> str:
    created = holder.get("create_time")
    created_key = (
        str(int(float(created) * 1000))
        if isinstance(created, (int, float))
        else "unknown"
    )
    return "runtime-holder:%s:%s" % (holder.get("pid"), created_key)


def _holder_priority(holder: dict[str, Any]) -> int:
    risk = holder.get("holder_risk_class")
    if risk == "visible_legacy_endpoint":
        return 9900
    if risk in {"qa_server_script_missing", "stdin_python_holder"}:
        return 9700
    return 9500


def sync_runtime_holders_to_universal(
    plan: dict[str, Any],
    *,
    bridge=None,
) -> dict[str, Any]:
    """Mirror live-holder drain blockers into the Universal work registry.

    This is a graph-owned work sync through the signed Universal runtime route.
    It does not open the Cell database and does not touch running processes.
    """
    runtime = bridge
    if runtime is None:
        sys.path.insert(0, str(default_product_root() / "personal-brain-mcp" / "src"))
        from personal_brain.universal_runtime import (  # noqa: WPS433
            UniversalRuntimeBridge,
        )

        runtime = UniversalRuntimeBridge()
    runtime_state = _runtime_work_index(runtime)
    existing = _existing_universal_external_keys(runtime_state)
    scope = runtime_state.get("brain_scope") or runtime_state.get("application")
    imported: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    latest_revision = runtime_state.get("revision")
    for index, holder in enumerate(plan.get("holders") or []):
        if not isinstance(holder, dict):
            continue
        external_key = holder_external_key(holder)
        if external_key in existing:
            skipped.append({
                "external_key": external_key,
                "pid": holder.get("pid"),
                "work_root": existing[external_key],
            })
            continue
        risk = str(holder.get("holder_risk_class") or "unclassified")
        title = "Drain live runtime holder %s (%s)" % (holder.get("pid"), risk)
        created = runtime.work_create(
            title=title,
            description=str(holder.get("drain_posture") or ""),
            priority=_holder_priority(holder),
            external_key=external_key,
            references={"scope": str(scope or "")},
            structured_references={
                "requirements": {
                    "gate": {
                        "kind": "pytest",
                        "spec": {
                            "selectors": [
                                "tests/test_live_runtime_holders.py",
                                "tests/test_legacy_runtime_drain.py",
                                "tests/test_runtime_retirement_hook.py",
                            ],
                        },
                    },
                },
                "cde-container": {
                    "container_id": "10.PRODUCT/12.PRODUCTION",
                    "authority": "10.PRODUCT/13.NODE-LANGUAGE",
                    "lifecycle": "WIP",
                    "privacy_tier": "T0 PUBLIC",
                },
                "applicable-policy": {
                    "schema": "archhub-runtime-holder-universal-sync/v1",
                    "authority": plan.get("authority"),
                    "runtime_copy": plan.get("runtime_copy"),
                    "non_destructive": True,
                    "no_process_interruption": True,
                    "retirement_gate_failures": (
                        (plan.get("retirement_gate") or {}).get("failures")
                        or []
                    ),
                },
                "inputs": {
                    "source": {
                        "system": "tools.legacy_runtime_drain",
                        "schema": plan.get("schema"),
                        "holder_count": plan.get("holder_count"),
                        "archive_safe_now": plan.get("archive_safe_now"),
                    },
                    "holder": holder,
                    "handoff_board": plan.get("handoff_board"),
                    "retirement_gate": plan.get("retirement_gate"),
                    "state_policy": (
                        "This work item tracks a live process node. It may be "
                        "closed only after the non-interrupting drain gate proves "
                        "the holder exited or was deliberately handed off."
                    ),
                },
            },
            x=980.0 + ((index % 2) * 420.0),
            y=920.0 + ((index // 2) * 260.0),
        )
        root = created["created_root"]
        latest_revision = created.get("revision", latest_revision)
        existing[external_key] = root
        imported.append({
            "external_key": external_key,
            "pid": holder.get("pid"),
            "holder_risk_class": risk,
            "work_root": root,
            "membership_wire": created.get("membership_wire"),
        })
    return {
        "schema": "archhub-runtime-holder-universal-sync/v1",
        "source_schema": plan.get("schema"),
        "holder_count": plan.get("holder_count"),
        "imported": imported,
        "skipped": skipped,
        "runtime_revision": latest_revision,
        "known_external_keys": len(existing),
        "non_destructive": True,
    }


def verify_runtime_holders_in_universal(
    plan: dict[str, Any],
    *,
    bridge=None,
) -> dict[str, Any]:
    """Read-only proof that live holder process nodes have Universal work.

    This uses the same external-key contract as the sync path but never creates
    or mutates a work item. It is the safe status check for the remaining
    authority split.
    """
    runtime = bridge
    if runtime is None:
        sys.path.insert(0, str(default_product_root() / "personal-brain-mcp" / "src"))
        from personal_brain.universal_runtime import (  # noqa: WPS433
            UniversalRuntimeBridge,
        )

        runtime = UniversalRuntimeBridge()
    runtime_state = _runtime_work_index(runtime)
    existing = _existing_universal_external_keys(runtime_state)
    verified: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for holder in plan.get("holders") or []:
        if not isinstance(holder, dict):
            continue
        external_key = holder_external_key(holder)
        row = {
            "external_key": external_key,
            "pid": holder.get("pid"),
            "holder_risk_class": holder.get("holder_risk_class"),
        }
        if external_key in existing:
            row["work_root"] = existing[external_key]
            verified.append(row)
        else:
            missing.append(row)
    return {
        "schema": "archhub-runtime-holder-universal-verification/v1",
        "source_schema": plan.get("schema"),
        "holder_count": len(verified) + len(missing),
        "verified_count": len(verified),
        "missing_count": len(missing),
        "ok": not missing,
        "verified": verified,
        "missing": missing,
        "runtime_revision": runtime_state.get("revision"),
        "known_external_keys": len(existing),
        "non_destructive": True,
    }


def write_drain_plan(
    product_root: Path,
    workspace: Path,
    out_dir: Path,
    timestamp: str | None = None,
    *,
    run_shadow_probe: bool = False,
) -> dict[str, Any]:
    holder_payload = write_holder_report(product_root, workspace, out_dir, timestamp)
    plan = build_drain_plan(
        product_root,
        workspace,
        holder_payload,
        run_shadow_probe=run_shadow_probe,
    )
    holder_path = Path(holder_payload["path"])
    plan_path = holder_path.with_name(holder_path.name.replace("holders", "plan", 1))
    plan["holder_report"] = str(holder_path)
    plan_path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    plan["path"] = str(plan_path)
    return plan


def build_drain_leaf(
    product_root: Path,
    workspace: Path,
    holder_payload: dict[str, Any],
) -> dict[str, Any]:
    holder_report = holder_payload["holder_report"]
    report_path = holder_payload["path"]
    return {
        "title": TITLE,
        "gate_kind": "file_exists",
        "gate_spec": {"path": report_path},
        "fit": ["governance", "runtime-drain", "universal-cell-authority"],
        "priority": 9500,
        "cde_container": {
            "container_id": "10.PRODUCT/12.PRODUCTION",
            "authority": "10.PRODUCT/13.NODE-LANGUAGE",
            "lifecycle": "WIP",
            "privacy_tier": "T0 PUBLIC",
        },
        "governance_context": {
            "schema": "archhub-legacy-runtime-drain-work/v1",
            "authority": str(workspace / "10.PRODUCT" / "13.NODE-LANGUAGE"),
            "runtime_copy": str(product_root / "node_runtime"),
            "holder_report": report_path,
            "holder_count": holder_report["holder_count"],
            "archive_safe_now": holder_report["archive_safe_now"],
            "required_action": holder_report["required_action"],
            "non_destructive": True,
        },
    }


def register_drain_leaf(
    product_root: Path,
    workspace: Path,
    owner_user: str,
    out_dir: Path,
    timestamp: str | None = None,
    brain_path: Path | None = None,
    *,
    run_shadow_probe: bool = False,
) -> dict[str, Any]:
    holder_payload = write_holder_report(product_root, workspace, out_dir, timestamp)
    plan = build_drain_plan(
        product_root,
        workspace,
        holder_payload,
        run_shadow_probe=run_shadow_probe,
    )
    plan_path = Path(holder_payload["path"]).with_name(
        Path(holder_payload["path"]).name.replace("holders", "plan", 1)
    )
    plan["holder_report"] = holder_payload["path"]
    plan_path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    leaf = build_drain_leaf(product_root, workspace, holder_payload)
    leaf["governance_context"]["drain_plan"] = str(plan_path)

    sys.path.insert(0, str(product_root / "personal-brain-mcp" / "src"))
    from personal_brain import active_work as aw  # noqa: WPS433
    from personal_brain.storage import BrainStore, default_brain_path  # noqa: WPS433

    store = BrainStore.open(brain_path or default_brain_path())
    try:
        ledger = aw.add_leaves(store, owner_user=owner_user, leaves=[leaf])
        registered = ledger.leaves[aw._leaf_id(owner_user, TITLE)]
    finally:
        store.close()

    return {
        "schema": "archhub-legacy-runtime-drain-registration/v1",
        "owner_user": owner_user,
        "leaf_id": registered.leaf_id,
        "leaf_state": registered.state.value,
        "holder_report": holder_payload["path"],
        "drain_plan": str(plan_path),
        "holder_count": holder_payload["holder_report"]["holder_count"],
        "archive_safe_now": holder_payload["holder_report"]["archive_safe_now"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Register a non-destructive legacy runtime drain leaf.")
    parser.add_argument("--product-root", default=str(default_product_root()))
    parser.add_argument("--workspace", default="")
    parser.add_argument("--owner-user", default="founder")
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--timestamp", default="")
    parser.add_argument("--brain-path", default="")
    parser.add_argument(
        "--enforce-drained",
        action="store_true",
        help="Exit nonzero while copied runtime holders still exist.",
    )
    parser.add_argument(
        "--enforce-retirement-gate",
        action="store_true",
        help="Exit nonzero until the copied runtime retirement gate allows archive.",
    )
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="Print the drain plan without writing files or registering Brain work.",
    )
    parser.add_argument(
        "--handoff-board",
        action="store_true",
        help=(
            "Print only the compact handoff board. This is always read-only and "
            "never writes files or registers Brain work."
        ),
    )
    parser.add_argument(
        "--inspect-board-pids",
        action="store_true",
        help=(
            "Print read-only inspection details for PIDs named by the compact "
            "handoff board. This never writes or interrupts processes."
        ),
    )
    parser.add_argument(
        "--authority-shadow-probe",
        action="store_true",
        help=(
            "Start 10.PRODUCT/13.NODE-LANGUAGE on temporary ports, authenticate "
            "through the browser bootstrap path, prove state/health, and close "
            "it. This never touches live ports."
        ),
    )
    parser.add_argument(
        "--sync-universal-holders",
        action="store_true",
        help=(
            "Create or skip governed Universal work items for current live "
            "holders. This writes to the active Universal runtime and never "
            "touches running processes."
        ),
    )
    parser.add_argument(
        "--verify-universal-holders",
        action="store_true",
        help=(
            "Read-only proof that current live holders already have Universal "
            "work items. This never creates work and never touches processes."
        ),
    )
    parser.add_argument(
        "--source-drift-report",
        action="store_true",
        help=(
            "Print the ignored runtime source-drift inventory and migration "
            "candidates. This is read-only and never touches processes."
        ),
    )
    parser.add_argument(
        "--source-drift-work-plan",
        action="store_true",
        help=(
            "Print authority-scoped work items for resolving ignored runtime "
            "source drift. This is read-only and never touches processes."
        ),
    )
    parser.add_argument(
        "--output-json",
        default="",
        help=(
            "Also write the selected JSON result to this path. This records "
            "evidence only and never interrupts processes."
        ),
    )
    args = parser.parse_args(argv)

    product_root = Path(args.product_root).resolve()
    workspace = Path(args.workspace).resolve() if args.workspace else default_workspace(product_root)
    out_dir = Path(args.output_dir).resolve() if args.output_dir else default_handoff_dir(workspace)
    read_only = (
        args.no_write
        or args.handoff_board
        or args.inspect_board_pids
        or args.verify_universal_holders
        or args.source_drift_report
        or args.source_drift_work_plan
    )
    if args.sync_universal_holders and read_only:
        print(json.dumps({
            "schema": "archhub-legacy-runtime-drain-error/v1",
            "ok": False,
            "reason": (
                "--sync-universal-holders writes graph work items and cannot "
                "be combined with read-only flags"
            ),
        }, indent=2))
        return 2
    if read_only:
        plan = build_drain_plan(
            product_root,
            workspace,
            build_holder_payload(product_root, workspace),
            run_shadow_probe=args.authority_shadow_probe,
        )
        if args.inspect_board_pids:
            board = plan["handoff_board"]
            pids = list(dict.fromkeys(
                board["blockers"]["low_activity_test_pids"]
                + board["blockers"]["inspect_before_touch_pids"]
                + board["blockers"]["blocked_endpoint_pids"]
                + [
                    pid
                    for card in board["endpoint_cards"]
                    for pid in card.get("non_holder_port_owner_pids", [])
                ]
            ))
            inspection = live_runtime_holders.inspect_pids(pids)
            child_pids = sorted({
                int(child_pid)
                for process in inspection.get("processes") or []
                if isinstance(process, dict)
                for child_pid in process.get("child_pids") or []
                if int(child_pid) not in set(pids)
            })
            if child_pids:
                child_inspection = live_runtime_holders.inspect_pids(child_pids)
                if child_inspection.get("available") is True:
                    seen_pids = {
                        int(process["pid"])
                        for process in inspection.get("processes") or []
                        if isinstance(process, dict)
                        and isinstance(process.get("pid"), int)
                    }
                    inspection.setdefault("processes", []).extend(
                        process
                        for process in child_inspection.get("processes") or []
                        if isinstance(process, dict)
                        and isinstance(process.get("pid"), int)
                        and int(process["pid"]) not in seen_pids
                    )
                inspection["expanded_child_pids"] = child_pids
                inspection["child_inspection_available"] = bool(
                    child_inspection.get("available")
                )
            result = {
                "schema": "archhub-runtime-handoff-pid-inspection/v1",
                "handoff_board": board,
                "inspection": inspection,
                "rule": (
                    "read-only inspection only; no process may be killed, moved, "
                    "archived, or relaunched by this command"
                ),
            }
            result["disposable_holder_court"] = build_disposable_holder_court(
                board,
                result["inspection"],
            )
            result["holder_tree_court"] = build_holder_tree_court(
                board,
                result["inspection"],
            )
            result["stale_stdin_tree_court"] = build_stale_stdin_tree_court(
                result["holder_tree_court"],
                result["inspection"],
            )
        elif args.verify_universal_holders:
            result = verify_runtime_holders_in_universal(plan)
        elif args.source_drift_report:
            result = plan["runtime_copy_source_drift"]
        elif args.source_drift_work_plan:
            result = build_source_drift_migration_work(
                plan["runtime_copy_source_drift"],
                product_root=product_root,
                workspace=workspace,
            )
        else:
            result = plan["handoff_board"] if args.handoff_board else plan
    else:
        result = register_drain_leaf(
            product_root,
            workspace,
            args.owner_user,
            out_dir,
            args.timestamp or None,
            Path(args.brain_path).resolve() if args.brain_path else None,
            run_shadow_probe=args.authority_shadow_probe,
        )
        if args.sync_universal_holders:
            plan = json.loads(Path(result["drain_plan"]).read_text(encoding="utf-8"))
            result["universal_holder_sync"] = sync_runtime_holders_to_universal(plan)
    text = json.dumps(result, indent=2) + "\n"
    if args.output_json:
        output_path = Path(args.output_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text, encoding="utf-8")
    print(text, end="")
    if args.enforce_retirement_gate:
        gate = result.get("retirement_gate")
        if gate is None and args.handoff_board:
            gate = {"archive_allowed": bool(result.get("archive_allowed"))}
        if gate is None and result.get("drain_plan"):
            try:
                gate = json.loads(Path(result["drain_plan"]).read_text(encoding="utf-8")).get(
                    "retirement_gate"
                )
            except Exception:
                gate = None
        if not gate or not gate.get("archive_allowed"):
            return 2
    if args.enforce_drained and not (
        result.get("archive_safe_now") or result.get("archive_allowed")
    ):
        return 2
    if args.verify_universal_holders and not result.get("ok"):
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
