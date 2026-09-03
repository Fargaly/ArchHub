"""Persist deterministic BABOOM stewardship through the standard attention protocol."""
from __future__ import annotations

from dataclasses import dataclass
import re

from .cell_attention import read_signal, record_signal
from .universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell


_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_SECRET = re.compile(r"(?i)\b(api[_-]?key|token|password|secret)\s*[:=]\s*\S+")
_PROTECTED = re.compile(r"(?i)\b(?:20\.CLIENTS|60\.PERSONAL|financial_plan|signature)\b")


@dataclass(frozen=True, slots=True)
class StewardSignal:
    root_id: str
    fingerprint: str
    source: str
    summary: str
    interaction_root: str


def _safe(value: str, limit: int) -> str:
    text = " ".join(str(value or "").split()).strip()
    text = _SECRET.sub("[redacted credential]", text)
    text = _PROTECTED.sub("[protected scope]", text)
    return text[:limit].rstrip() or "[redacted observation]"


def record_baboom_steward_signal(
    store: CellStore,
    authority,
    *,
    fingerprint: str,
    source: str,
    summary: str,
    interaction: str,
    observed_at: float,
) -> StewardSignal:
    """Create one durable, redacted Signal bound to a released interaction."""
    if not _DIGEST.fullmatch(fingerprint):
        raise InvalidCell("BABOOM steward fingerprint must be a SHA-256 digest")
    interaction_root = authority.interactions.get(interaction)
    if not interaction_root:
        raise InvalidCell("BABOOM steward interaction is not released")
    root_id = "baboom:steward-signal:" + fingerprint[:24]
    snapshot = store.snapshot()
    if root_id in snapshot.cells:
        signal = read_signal(snapshot, authority.attention_protocol, root_id)
        payload = snapshot.cells[signal.source_root].atom.decode("utf-8")
        source_value, _, summary_value = payload.partition("\n")
        return StewardSignal(root_id, fingerprint, source_value, summary_value, interaction_root)

    source_value = _safe(source, 80)
    summary_value = _safe(summary, 280)
    source_root = root_id + ":source"
    store.commit(
        snapshot.revision,
        create=(Cell(source_root, NULL_CELL_ID, NULL_CELL_ID, (source_value + "\n" + summary_value).encode("utf-8")),),
    )
    record_signal(
        store,
        authority.attention_protocol,
        signal_id=root_id,
        source_root=source_root,
        source_revision=1,
        observer_root=authority.agent_body.root_id,
        provenance_root=authority.agent_body.root_id,
        trust_root=authority.requirement_root,
        affected_roots=(authority.requirement_root, interaction_root),
        observed_at="%.6f" % observed_at,
        sensitivity_root=authority.requirement_root,
        audience_root=authority.requirement_root,
        idempotency_key=fingerprint,
        lifecycle_root=authority.attention_protocol.state("active"),
    )
    return StewardSignal(root_id, fingerprint, source_value, summary_value, interaction_root)


__all__ = ["StewardSignal", "record_baboom_steward_signal"]
