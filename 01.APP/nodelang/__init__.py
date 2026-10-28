"""nodelang -- ground-up node language (SPEC.md). ONE node table; everything
(wire/group/param/session/ui/proposal/secret-ref/history) is an instance of
the ONE node primitive. See nodelang.core for the law and the shape."""


def _use_packed_runtime():
    """An agent connector reads its runtime from two zips (03.TOOLS/packaging/pack_runtime.py):
    one file read instead of hundreds, so it answers initialize fast. Only connector processes
    (ARCHHUB_COORDINATION_VENDOR is set by their MCP entry), only for the interpreter they were built for."""
    import json
    import os
    import sys
    from pathlib import Path
    folder = Path(__file__).resolve().parents[1] / "packed"
    if not os.environ.get("ARCHHUB_COORDINATION_VENDOR") or not (folder / "stamp.json").is_file():
        return
    try:
        stamp = json.loads((folder / "stamp.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as unreadable:
        sys.stderr.write("packed runtime ignored: %s\n" % unreadable)
        return
    if stamp.get("hexversion") == sys.hexversion:
        sys.path[0:0] = [str(folder / "site.zip"), str(folder / "stdlib.zip")]


_use_packed_runtime()
from .core import (  # noqa: E402
    KINDS,
    NODE_KEYS,
    GROUPISH,
    NO_VALUE,
    Store,
    OneTableViolation,
    HistoryImmutable,
    FrozenNode,
    validate_node,
    validate_store,
    relation_endpoints,
    relation_sources,
    relation_targets,
    relation_stages,
)
from .laws_structure import (
    set_gate,
    clear_gate,
    group,
    ungroup,
    promote_param,
    demote_param,
    set_relation_stage,
    clear_relation_stage,
)
from .laws_effect import (
    dry_run,
    apply_effect,
    revert_effect,
)
from .laws_relation import (
    append_endpoint,
    remove_endpoint,
    rewire_endpoint,
    set_relation_parameter,
    build_payload_envelope,
    attach_payload,
    build_json_codec_stage,
    build_aead_stage,
)

__all__ = [
    'KINDS', 'NODE_KEYS', 'GROUPISH', 'NO_VALUE', 'Store',
    'OneTableViolation', 'HistoryImmutable', 'FrozenNode',
    'validate_node', 'validate_store',
    'relation_endpoints', 'relation_sources', 'relation_targets', 'relation_stages',
    'set_gate', 'clear_gate', 'group', 'ungroup',
    'promote_param', 'demote_param',
    'set_relation_stage', 'clear_relation_stage',
    'dry_run', 'apply_effect', 'revert_effect',
    'append_endpoint', 'remove_endpoint', 'rewire_endpoint', 'set_relation_parameter',
    'build_payload_envelope', 'attach_payload',
    'build_json_codec_stage', 'build_aead_stage',
]
