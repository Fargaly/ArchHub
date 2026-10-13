"""Small runtime stability guards for the installed clean owner."""

from __future__ import annotations

import hashlib
import json
import os
import random
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from .unified_authority import COMMAND_BUDGET, read_relation


def stable_json_hash(value: object) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def catalogue_relation_generation(authority) -> str:
    snapshot = authority.store.snapshot()
    catalogue_members = tuple(read_relation(
        snapshot, authority.manifest.catalogue_root, budget=COMMAND_BUDGET
    ))
    members = sorted(
        (member.role_id, member.participant_id)
        for member in catalogue_members
    )
    definition_role = authority.role("definition")
    definition_revisions = []
    for member in catalogue_members:
        if member.role_id != definition_role:
            continue
        definition_members = sorted(
            (child.role_id, child.participant_id)
            for child in read_relation(
                snapshot, member.participant_id, budget=COMMAND_BUDGET
            )
        )
        definition_revisions.append((member.participant_id, definition_members))
    return stable_json_hash({
        "catalogue_root": authority.manifest.catalogue_root,
        "definition_revisions": sorted(definition_revisions),
        "members": members,
    })


def runtime_state_path(runtime_root: str | os.PathLike[str]) -> Path:
    return Path(runtime_root) / "catalogue-generation.json"


def read_generation_state(runtime_root: str | os.PathLike[str]) -> dict[str, object]:
    path = runtime_state_path(runtime_root)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if type(value) is dict else {}


def write_generation_state(
    runtime_root: str | os.PathLike[str],
    *,
    source_hash: str,
    generation: str,
    warmed: bool,
    now: Callable[[], float] = time.time,
) -> None:
    path = runtime_state_path(runtime_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "source_hash": source_hash,
                "generation": generation,
                "warmed": bool(warmed),
                "updated_at": float(now()),
            },
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="",
    )


def catalogue_refresh_required(
    runtime_root: str | os.PathLike[str],
    authority,
    *,
    source_hash: str,
    require_warmed: bool = False,
) -> tuple[bool, str]:
    generation = catalogue_relation_generation(authority)
    state = read_generation_state(runtime_root)
    required = (
        state.get("source_hash") != source_hash
        or state.get("generation") != generation
        or (require_warmed and state.get("warmed") is not True)
    )
    return required, generation


def rotate_root_logs(
    runtime_root: str | os.PathLike[str],
    *,
    keep: int,
    names: Iterable[str] = ("boot-timing.log", "gesture-timing.log"),
) -> None:
    if keep < 1:
        raise ValueError("runtime log keep count must be at least 1")
    root = Path(runtime_root)
    root.mkdir(parents=True, exist_ok=True)
    for name in names:
        current = root / name
        if not current.exists() or not current.is_file():
            continue
        oldest = root / ("%s.%d" % (name, keep))
        try:
            if oldest.exists():
                oldest.unlink()
            for index in range(keep - 1, 0, -1):
                src = root / ("%s.%d" % (name, index))
                if src.exists():
                    src.rename(root / ("%s.%d" % (name, index + 1)))
            current.rename(root / ("%s.1" % name))
        except OSError:
            continue


def backoff_delays(
    attempts: int,
    *,
    base: float = 0.25,
    factor: float = 2.0,
    cap: float = 5.0,
    jitter: float = 0.2,
    random_fn: Callable[[], float] | None = None,
) -> list[float]:
    if attempts < 0:
        raise ValueError("attempts must be nonnegative")
    if base <= 0 or factor < 1 or cap <= 0 or jitter < 0:
        raise ValueError("invalid backoff parameters")
    rand = random.random if random_fn is None else random_fn
    delays: list[float] = []
    for index in range(attempts):
        raw = min(cap, base * (factor ** index))
        spread = raw * jitter
        delays.append(max(0.0, raw - spread + (2.0 * spread * rand())))
    return delays


@dataclass(frozen=True)
class BaselineDecision:
    broker: str
    latency_ms: float
    baseline_ms: float
    deviation: float
    flagged: bool
    root_cause_line: str


class BrokerLatencyBaselines:
    def __init__(
        self,
        *,
        alpha: float = 0.25,
        deviation_factor: float = 3.0,
        min_deviation_ms: float = 250.0,
    ) -> None:
        self.alpha = alpha
        self.deviation_factor = deviation_factor
        self.min_deviation_ms = min_deviation_ms
        self._baselines: dict[str, float] = {}

    def record(self, broker: str, latency_ms: float, *, root_cause_line: str = "") -> BaselineDecision:
        if not broker:
            raise ValueError("broker name is required")
        if latency_ms < 0:
            raise ValueError("latency must be nonnegative")
        previous = self._baselines.get(broker)
        if previous is None:
            self._baselines[broker] = latency_ms
            return BaselineDecision(broker, latency_ms, latency_ms, 1.0, False, root_cause_line)
        deviation = latency_ms / max(previous, 0.001)
        flagged = (
            latency_ms - previous >= self.min_deviation_ms
            and deviation >= self.deviation_factor
        )
        if not flagged:
            self._baselines[broker] = previous + self.alpha * (latency_ms - previous)
        return BaselineDecision(broker, latency_ms, previous, deviation, flagged, root_cause_line)

    def observe(self, broker: str, started_at: float, finished_at: float, *, root_cause_line: str = "") -> BaselineDecision:
        return self.record(
            broker,
            max(0.0, (finished_at - started_at) * 1000.0),
            root_cause_line=root_cause_line,
        )


def root_cause_line(exc: BaseException) -> str:
    tb = traceback.extract_tb(exc.__traceback__)
    if not tb:
        return "%s: %s" % (exc.__class__.__name__, exc)
    frame = tb[-1]
    return "%s:%d in %s: %s: %s" % (
        frame.filename,
        frame.lineno,
        frame.name,
        exc.__class__.__name__,
        exc,
    )
