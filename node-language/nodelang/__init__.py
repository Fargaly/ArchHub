"""nodelang -- ground-up node language (SPEC.md). ONE node table; everything
(wire/group/param/session/ui/proposal/secret-ref/history) is an instance of
the ONE node primitive. See nodelang.core for the law and the shape."""
from .core import (
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
