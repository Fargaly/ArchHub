"""Graph-authored lifecycle timeline presenter over the raw projection."""
from __future__ import annotations

from .cell_protocols import CellBatch
from .cell_view_template import ViewTemplateBuilder, ViewTemplateProtocol


VIEW_TEMPLATE_PREFIX = "app:view-template-protocol"
TIMELINE_PREFIX = "app:properties-template:timeline:v2"
TIMELINE_TEMPLATE_ROOT = TIMELINE_PREFIX + ":section"

_CONTROL_HEADING_ROOT = TIMELINE_PREFIX + ":control-heading"
_STATE_ROOT = TIMELINE_PREFIX + ":state"
_STATE_LABEL_ROOT = TIMELINE_PREFIX + ":state-label"
_STATE_EMPTY_ROOT = TIMELINE_PREFIX + ":state-empty"
_STATE_MEMBER_ROOT = TIMELINE_PREFIX + ":state-member"
_HEAD_ROOT = TIMELINE_PREFIX + ":head"
_HEAD_META_ROOT = TIMELINE_PREFIX + ":head-meta"
_EVIDENCE_ROOT = TIMELINE_PREFIX + ":evidence"
_EVIDENCE_SUMMARY_ROOT = TIMELINE_PREFIX + ":evidence-summary"
_EVIDENCE_META_ROOT = TIMELINE_PREFIX + ":evidence-meta"
_EVIDENCE_CHECK_ROOT = TIMELINE_PREFIX + ":evidence-check"
_DIVERGENCE_ROOT = TIMELINE_PREFIX + ":divergence"
_GATES_ROOT = TIMELINE_PREFIX + ":gates"
_GATES_HEADING_ROOT = TIMELINE_PREFIX + ":gates-heading"
_GATE_ROW_ROOT = TIMELINE_PREFIX + ":gate-row"
_GATE_LABEL_ROOT = TIMELINE_PREFIX + ":gate-label"
_ACTION_ROOT = TIMELINE_PREFIX + ":action"
_HISTORY_ROOT = TIMELINE_PREFIX + ":history"
_HISTORY_SUMMARY_ROOT = TIMELINE_PREFIX + ":history-summary"
_HISTORY_ROW_ROOT = TIMELINE_PREFIX + ":history-row"
_HISTORY_LABEL_ROOT = TIMELINE_PREFIX + ":history-label"
_HISTORY_VALUE_ROOT = TIMELINE_PREFIX + ":history-value"
_HISTORY_META_ROOT = TIMELINE_PREFIX + ":history-meta"
_ACTION_HISTORY_ROOT = TIMELINE_PREFIX + ":action-history"
_ACTION_HISTORY_HEADING_ROOT = TIMELINE_PREFIX + ":action-history-heading"
_ACTION_HISTORY_ROW_ROOT = TIMELINE_PREFIX + ":action-history-row"
_ACTION_HISTORY_LABEL_ROOT = TIMELINE_PREFIX + ":action-history-label"
_ACTION_HISTORY_VALUE_ROOT = TIMELINE_PREFIX + ":action-history-value"
_ACTION_HISTORY_META_ROOT = TIMELINE_PREFIX + ":action-history-meta"

# Existing presenter slots are ordered as section, heading, list, row, text,
# button, details, condition, action-binding.  Button and action-binding share
# one executable relation, preserving nine incidences with eight identities.
TIMELINE_TEMPLATE_MEMBER_ROOTS = (
    TIMELINE_TEMPLATE_ROOT,
    _CONTROL_HEADING_ROOT,
    _STATE_ROOT,
    _GATE_ROW_ROOT,
    _STATE_MEMBER_ROOT,
    _ACTION_ROOT,
    _HISTORY_ROOT,
    _STATE_EMPTY_ROOT,
    _ACTION_ROOT,
    _ACTION_HISTORY_ROOT,
    _ACTION_HISTORY_ROW_ROOT,
    _ACTION_HISTORY_VALUE_ROOT,
)


def compose_timeline_template(
    batch: CellBatch,
    protocol: ViewTemplateProtocol,
) -> str:
    """Compose the complete lifecycle timeline as rewritable relations."""
    builder = ViewTemplateBuilder(batch, protocol)
    prefix = TIMELINE_PREFIX
    segments: dict[str, str] = {}

    def expression(
        name: str,
        operation: str,
        arguments: tuple[str, ...] = (),
    ) -> str:
        return builder.expression(
            "%s:expression:%s" % (prefix, name), operation, arguments
        )

    def literal(name: str, value: object) -> str:
        return builder.literal(
            "%s:expression:%s" % (prefix, name), value
        )

    def segment(name: str) -> str:
        if name not in segments:
            segments[name] = builder.atom(
                "%s:segment:%s" % (prefix, name), name
            )
        return segments[name]

    def path(name: str, base: str, *names: str) -> str:
        return expression(
            name,
            "path",
            (base, *(segment(item) for item in names)),
        )

    def concat(name: str, *arguments: str) -> str:
        return expression(name, "concat", arguments)

    def attribute(name: str, attribute_name: str, value: str) -> str:
        return builder.attribute(
            "%s:attribute:%s" % (prefix, name),
            attribute_name,
            value,
        )

    root_context = expression("root-context", "root")
    item_context = expression("item-context", "item")
    selected_assembly = path(
        "selected-assembly", root_context, "selected_assembly"
    )
    lifecycle = path(
        "lifecycle", selected_assembly, "lifecycle"
    )
    measurable_lifecycle = expression(
        "measurable-lifecycle",
        "fallback",
        (lifecycle, literal("empty-lifecycle", "")),
    )
    lifecycle_size = expression(
        "lifecycle-size", "length", (measurable_lifecycle,)
    )
    lifecycle_size_text = expression(
        "lifecycle-size-text", "string", (lifecycle_size,)
    )
    has_lifecycle = expression(
        "has-lifecycle",
        "not",
        (expression(
            "lifecycle-is-empty",
            "equals",
            (lifecycle_size_text, literal("zero-lifecycle-size", "0")),
        ),),
    )
    action_history = path("action-history", root_context, "action_history")
    action_transactions = path(
        "action-transactions", action_history, "transactions"
    )
    action_count = expression(
        "action-count", "length", (action_transactions,)
    )
    action_count_text = expression(
        "action-count-text", "string", (action_count,)
    )
    has_action_history = expression(
        "has-action-history",
        "not",
        (expression(
            "action-history-is-empty",
            "equals",
            (action_count_text, literal("zero-action-count", "0")),
        ),),
    )
    has_timeline = expression(
        "has-timeline", "or", (has_lifecycle, has_action_history)
    )
    selected = path("selected", root_context, "selected")
    states = path("states", lifecycle, "states")
    transitions = path("transitions", lifecycle, "transitions")
    history = path("history", lifecycle, "history")
    state_name = path("state-name", item_context, "name")
    state_head_count = path(
        "state-head-count", item_context, "head_count"
    )
    state_head_count_text = expression(
        "state-head-count-text", "string", (state_head_count,)
    )
    state_heads = path("state-heads", item_context, "heads")
    singular_head = expression(
        "singular-head",
        "equals",
        (state_head_count_text, literal("one-head", "1")),
    )
    no_heads = expression("no-heads", "not", (state_heads,))
    ordinary_head_count = expression(
        "ordinary-head-count",
        "member-of",
        (
            state_head_count_text,
            literal("zero-heads", "0"),
            literal("one-head-for-divergence", "1"),
        ),
    )
    diverged = expression(
        "diverged", "not", (ordinary_head_count,)
    )
    state_key = concat(
        "state-key",
        literal("state-key-prefix", "lifecycle-state:"),
        selected,
        literal("state-key-divider", ":"),
        state_name,
    )
    state_label_key = concat(
        "state-label-key",
        literal("state-label-key-prefix", "lifecycle-state-label:"),
        selected,
        literal("state-label-key-divider", ":"),
        state_name,
    )
    state_label_text = concat(
        "state-label-text",
        state_name,
        literal("state-label-count-divider", " / "),
        state_head_count,
        literal("state-label-active", " ACTIVE "),
        expression(
            "state-head-word",
            "choose",
            (
                singular_head,
                literal("head-singular", "HEAD"),
                literal("head-plural", "HEADS"),
            ),
        ),
    )
    empty_key = concat(
        "empty-key",
        literal("empty-key-prefix", "lifecycle-empty:"),
        selected,
        literal("empty-key-divider", ":"),
        state_name,
    )
    divergence_key = concat(
        "divergence-key",
        literal("divergence-key-prefix", "lifecycle-divergence:"),
        selected,
        literal("divergence-key-divider", ":"),
        state_name,
    )
    divergence_text = concat(
        "divergence-text",
        state_head_count,
        literal(
            "divergence-text-suffix",
            " ACTIVE VARIATIONS / SELECT A BASE OR MERGE EXPLICITLY",
        ),
    )

    revision = path("head-revision", item_context, "revision")
    head_key = concat(
        "head-key", literal("head-key-prefix", "lifecycle-head:"), revision
    )
    branch_label = path("head-branch-label", item_context, "branch_label")
    branch = path("head-branch", item_context, "branch")
    display_branch = expression(
        "head-display-branch", "fallback", (branch_label, branch)
    )
    content_bytes = path("head-content-bytes", item_context, "content_bytes")
    head_text = concat(
        "head-text",
        display_branch,
        literal("head-bytes-divider", " / "),
        content_bytes,
        literal("head-bytes-suffix", " bytes"),
    )
    content_digest = path(
        "head-content-digest", item_context, "content_digest"
    )
    parents = path("head-parents", item_context, "parents")
    parent_count = expression("head-parent-count", "length", (parents,))
    actor = path("head-actor", item_context, "actor")
    head_evidence = path("head-evidence", item_context, "evidence")
    head_evidence_count = expression(
        "head-evidence-count", "length", (head_evidence,)
    )
    head_title = concat(
        "head-title",
        literal("head-title-revision", "revision: "),
        revision,
        literal("head-title-digest", "\ndigest: "),
        content_digest,
        literal("head-title-parents", "\nparents: "),
        parent_count,
        literal("head-title-actor", "\nactor: "),
        actor,
        literal("head-title-evidence", "\nevidence: "),
        head_evidence_count,
    )
    title_attribute = attribute("head-title", "title", head_title)
    head_meta_key = concat(
        "head-meta-key",
        literal("head-meta-key-prefix", "lifecycle-head-meta:"),
        revision,
    )
    parent_word = expression(
        "head-parent-word",
        "choose",
        (
            expression(
                "head-has-one-parent",
                "equals",
                (
                    expression(
                        "head-parent-count-text", "string", (parent_count,)
                    ),
                    literal("one-parent", "1"),
                ),
            ),
            literal("parent-singular", "parent"),
            literal("parent-plural", "parents"),
        ),
    )
    head_meta_text = concat(
        "head-meta-text",
        revision,
        literal("head-meta-parent-divider", " / "),
        parent_count,
        literal("head-meta-parent-space", " "),
        parent_word,
        literal("head-meta-evidence-divider", " / "),
        head_evidence_count,
        literal("head-meta-evidence-suffix", " evidence"),
    )

    evidence_details = path(
        "head-evidence-details", item_context, "evidence_details"
    )
    evidence_root = path("evidence-root", item_context, "root")
    evidence_key = concat(
        "evidence-key",
        literal("evidence-key-prefix", "lifecycle-evidence:"),
        evidence_root,
    )
    evidence_court = path("evidence-court", item_context, "court")
    evidence_result = path("evidence-result", item_context, "result")
    evidence_result_upper = expression(
        "evidence-result-upper", "upper", (evidence_result,)
    )
    evidence_checks = path("evidence-checks", item_context, "checks")
    check_value = path("check-value", item_context, "value")
    passed_checks = expression(
        "evidence-passed-checks",
        "count-where",
        (evidence_checks, check_value),
    )
    total_checks = expression(
        "evidence-total-checks", "length", (evidence_checks,)
    )
    court_summary_text = concat(
        "court-summary-text",
        evidence_result_upper,
        literal("court-summary-court", " COURT / "),
        passed_checks,
        literal("court-summary-of", " OF "),
        total_checks,
        literal("court-summary-checks", " CHECKS"),
    )
    plain_evidence_text = concat(
        "plain-evidence-text",
        literal("plain-evidence-prefix", "EVIDENCE / "),
        evidence_root,
    )
    evidence_summary_text = expression(
        "evidence-summary-text",
        "choose",
        (evidence_court, court_summary_text, plain_evidence_text),
    )
    evidence_summary_key = concat(
        "evidence-summary-key",
        literal(
            "evidence-summary-key-prefix", "lifecycle-evidence-summary:"
        ),
        evidence_root,
    )
    evidence_builder = path("evidence-builder", item_context, "builder")
    evidence_duration = path(
        "evidence-duration", item_context, "duration_ms"
    )
    evidence_digest = path("evidence-digest", item_context, "digest")
    evidence_digest_or_empty = expression(
        "evidence-digest-or-empty",
        "fallback",
        (evidence_digest, literal("empty-evidence-digest", "")),
    )
    digest_preview = expression(
        "evidence-digest-preview",
        "slice",
        (
            evidence_digest_or_empty,
            literal("digest-slice-start", 0),
            literal("digest-slice-stop", 12),
        ),
    )
    evidence_meta_key = concat(
        "evidence-meta-key",
        literal("evidence-meta-key-prefix", "lifecycle-evidence-meta:"),
        evidence_root,
    )
    evidence_meta_text = concat(
        "evidence-meta-text",
        evidence_builder,
        literal("evidence-meta-duration-divider", " / "),
        evidence_duration,
        literal("evidence-meta-ms", " ms / "),
        digest_preview,
    )
    parent_context = expression("parent-context", "parent")
    check_evidence_root = path(
        "check-evidence-root", parent_context, "root"
    )
    check_court = path("check-court", parent_context, "court")
    check_name = path("check-name", item_context, "key")
    check_key = concat(
        "check-key",
        literal("check-key-prefix", "lifecycle-check:"),
        check_evidence_root,
        literal("check-key-divider", ":"),
        check_name,
    )
    display_check_name = expression(
        "display-check-name",
        "replace",
        (
            check_name,
            literal("check-hyphen", "-"),
            literal("check-space", " "),
        ),
    )
    check_status = expression(
        "check-status",
        "choose",
        (
            check_value,
            literal("check-pass", "PASS"),
            literal("check-fail", "FAIL"),
        ),
    )
    check_text = concat(
        "check-text",
        check_status,
        literal("check-text-space", " "),
        display_check_name,
    )

    builder.template(
        _HEAD_META_ROOT,
        tag=literal("head-meta-tag", "span"),
        key=head_meta_key,
        class_name=literal("head-meta-class", "lifecycle-head-meta"),
        text=head_meta_text,
    )
    builder.template(
        _EVIDENCE_SUMMARY_ROOT,
        tag=literal("evidence-summary-tag", "summary"),
        key=evidence_summary_key,
        class_name=literal("evidence-summary-class", "property-label"),
        text=evidence_summary_text,
    )
    builder.template(
        _EVIDENCE_META_ROOT,
        tag=literal("evidence-meta-tag", "div"),
        key=evidence_meta_key,
        class_name=literal("evidence-meta-class", "connection-box"),
        text=evidence_meta_text,
        condition=evidence_court,
    )
    builder.template(
        _EVIDENCE_CHECK_ROOT,
        tag=literal("evidence-check-tag", "div"),
        key=check_key,
        class_name=literal("evidence-check-class", "court-check"),
        text=check_text,
        repeat=evidence_checks,
        condition=check_court,
    )
    builder.template(
        _EVIDENCE_ROOT,
        tag=literal("evidence-tag", "details"),
        key=evidence_key,
        class_name=literal("evidence-class", "court-evidence"),
        children=(
            _EVIDENCE_SUMMARY_ROOT,
            _EVIDENCE_META_ROOT,
            _EVIDENCE_CHECK_ROOT,
        ),
        repeat=evidence_details,
    )
    builder.template(
        _HEAD_ROOT,
        tag=literal("head-tag", "div"),
        key=head_key,
        class_name=literal("head-class", "connection-box lifecycle-head"),
        text=head_text,
        attributes=(title_attribute,),
        children=(_HEAD_META_ROOT,),
    )
    builder.template(
        _STATE_MEMBER_ROOT,
        tag=None,
        key=None,
        children=(_HEAD_ROOT, _EVIDENCE_ROOT),
        repeat=state_heads,
        transparent=builder.atom(
            prefix + ":transparent:head-group", "transparent"
        ),
    )
    builder.template(
        _STATE_LABEL_ROOT,
        tag=literal("state-label-tag", "span"),
        key=state_label_key,
        class_name=literal("state-label-class", "property-label"),
        text=state_label_text,
    )
    builder.template(
        _STATE_EMPTY_ROOT,
        tag=literal("state-empty-tag", "div"),
        key=empty_key,
        class_name=literal("state-empty-class", "connection-box"),
        text=literal("state-empty-text", "not promoted"),
        condition=no_heads,
    )
    builder.template(
        _DIVERGENCE_ROOT,
        tag=literal("divergence-tag", "div"),
        key=divergence_key,
        class_name=literal("divergence-class", "lifecycle-divergence"),
        text=divergence_text,
        condition=diverged,
    )
    builder.template(
        _STATE_ROOT,
        tag=literal("state-tag", "div"),
        key=state_key,
        class_name=literal("state-class", "property-row"),
        children=(
            _STATE_LABEL_ROOT,
            _STATE_EMPTY_ROOT,
            _STATE_MEMBER_ROOT,
            _DIVERGENCE_ROOT,
        ),
        repeat=states,
    )

    relation = path("gate-relation", item_context, "relation")
    source_name = path("gate-source-name", item_context, "source_name")
    target_name = path("gate-target-name", item_context, "target_name")
    source_revision = path(
        "gate-source-revision", item_context, "source_revision"
    )
    ready = path("gate-ready", item_context, "ready")
    already_promoted = path(
        "gate-already-promoted", item_context, "already_promoted"
    )
    gate_court = path("gate-court", item_context, "court")
    required_evidence = path(
        "gate-required-evidence", item_context, "required_evidence"
    )
    required_evidence_count = expression(
        "gate-required-evidence-count", "length", (required_evidence,)
    )
    source_upper = expression("gate-source-upper", "upper", (source_name,))
    target_upper = expression("gate-target-upper", "upper", (target_name,))
    is_shared = expression(
        "gate-is-shared",
        "equals",
        (target_name, literal("shared-target", "shared")),
    )
    is_published = expression(
        "gate-is-published",
        "equals",
        (target_name, literal("published-target", "published")),
    )
    is_archived = expression(
        "gate-is-archived",
        "equals",
        (target_name, literal("archived-target", "archived")),
    )
    gate_command = expression(
        "gate-command",
        "choose",
        (
            is_shared,
            literal("share-command", "SHARE"),
            expression(
                "published-or-other-command",
                "choose",
                (
                    is_published,
                    literal("publish-command", "PUBLISH"),
                    expression(
                        "archived-or-other-command",
                        "choose",
                        (
                            is_archived,
                            literal("archive-command", "ARCHIVE"),
                            target_upper,
                        ),
                    ),
                ),
            ),
        ),
    )
    already_text = concat(
        "gate-already-text",
        target_upper,
        literal("gate-revision-exists", " REVISION EXISTS"),
    )
    ready_text = concat(
        "gate-ready-text",
        literal("gate-run-court", "RUN COURT + "),
        gate_command,
    )
    blocked_text = concat(
        "gate-blocked-text",
        literal("gate-requires-one", "REQUIRES ONE "),
        source_upper,
        literal("gate-head-suffix", " HEAD"),
    )
    gate_action_text = expression(
        "gate-action-text",
        "choose",
        (
            already_promoted,
            already_text,
            expression(
                "gate-ready-or-blocked",
                "choose",
                (ready, ready_text, blocked_text),
            ),
        ),
    )
    gate_key = concat(
        "gate-key", literal("gate-key-prefix", "lifecycle-gate:"), relation
    )
    gate_label_key = concat(
        "gate-label-key", gate_key, literal("gate-label-suffix", ":label")
    )
    gate_label_text = concat(
        "gate-label-text",
        source_upper,
        literal("gate-label-arrow", " -> "),
        target_upper,
    )
    gate_action_key = concat(
        "gate-action-key",
        literal("gate-action-key-prefix", "lifecycle-gate-action:"),
        relation,
    )
    gate_title = concat(
        "gate-title",
        literal("gate-title-transition", "transition relation: "),
        relation,
        literal("gate-title-court", "\ncourt: "),
        gate_court,
        literal("gate-title-evidence", "\n"),
        required_evidence_count,
        literal("gate-title-evidence-suffix", " required evidence types"),
    )
    data_source = expression(
        "gate-data-source",
        "choose",
        (source_revision, source_revision, literal("empty-data-source", "")),
    )
    action_attributes = (
        attribute("action-type", "type", literal("action-button-type", "button")),
        attribute(
            "action-disabled",
            "disabled",
            expression("action-not-ready", "not", (ready,)),
        ),
        attribute("action-title", "title", gate_title),
        attribute(
            "action-promote",
            "data-universal-resource-promote",
            literal("action-promote-value", "true"),
        ),
        attribute("action-root", "data-root", selected),
        attribute("action-target", "data-target", target_name),
        attribute("action-source", "data-source", data_source),
    )
    builder.template(
        _GATE_LABEL_ROOT,
        tag=literal("gate-label-tag", "span"),
        key=gate_label_key,
        class_name=literal("gate-label-class", "property-label"),
        text=gate_label_text,
    )
    builder.template(
        _ACTION_ROOT,
        tag=literal("gate-action-tag", "button"),
        key=gate_action_key,
        class_name=literal("gate-action-class", "operational-action"),
        text=gate_action_text,
        attributes=action_attributes,
    )
    builder.template(
        _GATE_ROW_ROOT,
        tag=literal("gate-row-tag", "div"),
        key=gate_key,
        class_name=literal("gate-row-class", "property-row"),
        children=(_GATE_LABEL_ROOT, _ACTION_ROOT),
        repeat=transitions,
    )
    builder.template(
        _GATES_HEADING_ROOT,
        tag=literal("gates-heading-tag", "div"),
        key=literal("gates-heading-key", "lifecycle-gates:heading"),
        class_name=literal("gates-heading-class", "inspector-heading"),
        text=literal("gates-heading-text", "LIFECYCLE GATES"),
    )
    gates_key = concat(
        "gates-key",
        literal("gates-key-prefix", "lifecycle-gates:"),
        selected,
    )
    builder.template(
        _GATES_ROOT,
        tag=literal("gates-tag", "section"),
        key=gates_key,
        class_name=literal("gates-class", "inspector-section"),
        children=(_GATES_HEADING_ROOT, _GATE_ROW_ROOT),
        condition=has_lifecycle,
    )

    history_revision = path(
        "history-revision", item_context, "revision"
    )
    history_state = path("history-state", item_context, "state")
    history_branch_label = path(
        "history-branch-label", item_context, "branch_label"
    )
    history_branch = path("history-branch", item_context, "branch")
    history_display_branch = expression(
        "history-display-branch",
        "fallback",
        (history_branch_label, history_branch),
    )
    history_parents = path("history-parents", item_context, "parents")
    history_parent_count = expression(
        "history-parent-count", "length", (history_parents,)
    )
    history_evidence = path("history-evidence", item_context, "evidence")
    history_evidence_count = expression(
        "history-evidence-count", "length", (history_evidence,)
    )
    history_actor = path("history-actor", item_context, "actor")
    history_timestamp = path(
        "history-timestamp", item_context, "timestamp"
    )
    history_row_key = concat(
        "history-row-key",
        literal("history-row-key-prefix", "lifecycle-history:"),
        history_revision,
    )
    history_label_key = concat(
        "history-label-key",
        history_row_key,
        literal("history-label-key-suffix", ":label"),
    )
    history_label_text = concat(
        "history-label-text",
        history_state,
        literal("history-label-divider", " / "),
        history_display_branch,
    )
    history_value_key = concat(
        "history-value-key",
        literal(
            "history-value-key-prefix", "lifecycle-history-value:"
        ),
        history_revision,
    )
    history_value_title = concat(
        "history-value-title",
        literal("history-title-actor", "actor: "),
        history_actor,
        literal("history-title-parents", "\nparents: "),
        history_parent_count,
        literal("history-title-evidence", "\nevidence: "),
        history_evidence_count,
    )
    history_meta_key = concat(
        "history-meta-key",
        literal("history-meta-key-prefix", "lifecycle-history-meta:"),
        history_revision,
    )
    history_timestamp_suffix = expression(
        "history-timestamp-suffix",
        "choose",
        (
            history_timestamp,
            concat(
                "history-present-timestamp",
                literal("history-timestamp-divider", " / "),
                history_timestamp,
            ),
            literal("history-no-timestamp", ""),
        ),
    )
    history_meta_text = concat(
        "history-meta-text",
        history_parent_count,
        literal("history-meta-parents", " parents / "),
        history_evidence_count,
        literal("history-meta-evidence", " evidence"),
        history_timestamp_suffix,
    )
    builder.template(
        _HISTORY_META_ROOT,
        tag=literal("history-meta-tag", "span"),
        key=history_meta_key,
        class_name=literal("history-meta-class", "lifecycle-head-meta"),
        text=history_meta_text,
    )
    builder.template(
        _HISTORY_VALUE_ROOT,
        tag=literal("history-value-tag", "div"),
        key=history_value_key,
        class_name=literal(
            "history-value-class", "connection-box lifecycle-head"
        ),
        text=history_revision,
        attributes=(attribute(
            "history-value-title", "title", history_value_title
        ),),
        children=(_HISTORY_META_ROOT,),
    )
    builder.template(
        _HISTORY_LABEL_ROOT,
        tag=literal("history-label-tag", "span"),
        key=history_label_key,
        class_name=literal("history-label-class", "property-label"),
        text=history_label_text,
    )
    builder.template(
        _HISTORY_ROW_ROOT,
        tag=literal("history-row-tag", "div"),
        key=history_row_key,
        class_name=literal("history-row-class", "property-row"),
        children=(_HISTORY_LABEL_ROOT, _HISTORY_VALUE_ROOT),
        repeat=history,
    )
    history_count = expression("history-count", "length", (history,))
    history_summary_key = concat(
        "history-summary-key",
        literal(
            "history-summary-key-prefix", "lifecycle-history-summary:"
        ),
        selected,
    )
    history_summary_text = concat(
        "history-summary-text",
        literal("history-summary-prefix", "REVISION HISTORY / "),
        history_count,
    )
    builder.template(
        _HISTORY_SUMMARY_ROOT,
        tag=literal("history-summary-tag", "summary"),
        key=history_summary_key,
        class_name=literal("history-summary-class", "inspector-heading"),
        text=history_summary_text,
    )
    history_key = concat(
        "history-key",
        literal("history-key-prefix", "lifecycle-history-list:"),
        selected,
    )
    builder.template(
        _HISTORY_ROOT,
        tag=literal("history-tag", "details"),
        key=history_key,
        class_name=literal("history-class", "inspector-section"),
        children=(_HISTORY_SUMMARY_ROOT, _HISTORY_ROW_ROOT),
        condition=has_lifecycle,
    )

    action_root = path("action-root", item_context, "root")
    action_state = path("action-state", item_context, "state")
    action_state_upper = expression(
        "action-state-upper", "upper", (action_state,)
    )
    action_operation = path("action-operation", item_context, "operation")
    action_changes = path("action-changes", item_context, "change_count")
    action_changes_text = expression(
        "action-changes-text", "string", (action_changes,)
    )
    action_one_change = expression(
        "action-one-change",
        "equals",
        (action_changes_text, literal("one-action-change", "1")),
    )
    action_change_word = expression(
        "action-change-word",
        "choose",
        (
            action_one_change,
            literal("action-change-singular", "change"),
            literal("action-change-plural", "changes"),
        ),
    )
    action_timestamp = path(
        "action-timestamp", item_context, "timestamp"
    )
    action_route = path("action-route", item_context, "route")
    action_capability = path(
        "action-capability", item_context, "capability"
    )
    action_scope_count = path(
        "action-scope-count", item_context, "scope_count"
    )
    action_row_key = concat(
        "action-row-key",
        literal("action-row-key-prefix", "session-action:"),
        action_root,
    )
    action_label_text = concat(
        "action-label-text",
        action_state_upper,
        literal("action-label-divider", " / "),
        action_operation,
    )
    action_value_text = concat(
        "action-value-text",
        action_changes_text,
        literal("action-value-space", " "),
        action_change_word,
    )
    action_title = concat(
        "action-title",
        literal("action-title-route", "route: "),
        action_route,
        literal("action-title-capability", "\ncapability: "),
        action_capability,
        literal("action-title-scopes", "\nscopes: "),
        action_scope_count,
    )
    builder.template(
        _ACTION_HISTORY_META_ROOT,
        tag=literal("action-meta-tag", "span"),
        key=concat(
            "action-meta-key", action_row_key,
            literal("action-meta-key-suffix", ":meta"),
        ),
        class_name=literal(
            "action-meta-class", "lifecycle-head-meta"
        ),
        text=action_timestamp,
    )
    builder.template(
        _ACTION_HISTORY_VALUE_ROOT,
        tag=literal("action-value-tag", "div"),
        key=concat(
            "action-value-key", action_row_key,
            literal("action-value-key-suffix", ":value"),
        ),
        class_name=literal(
            "action-value-class", "connection-box lifecycle-head"
        ),
        text=action_value_text,
        attributes=(attribute("action-value-title", "title", action_title),),
        children=(_ACTION_HISTORY_META_ROOT,),
    )
    builder.template(
        _ACTION_HISTORY_LABEL_ROOT,
        tag=literal("action-label-tag", "span"),
        key=concat(
            "action-label-key", action_row_key,
            literal("action-label-key-suffix", ":label"),
        ),
        class_name=literal("action-label-class", "property-label"),
        text=action_label_text,
    )
    builder.template(
        _ACTION_HISTORY_ROW_ROOT,
        tag=literal("action-row-tag", "div"),
        key=action_row_key,
        class_name=literal("action-row-class", "property-row"),
        children=(_ACTION_HISTORY_LABEL_ROOT, _ACTION_HISTORY_VALUE_ROOT),
        repeat=action_transactions,
    )
    builder.template(
        _ACTION_HISTORY_HEADING_ROOT,
        tag=literal("action-heading-tag", "div"),
        key=literal("action-heading-key", "session-actions:heading"),
        class_name=literal("action-heading-class", "inspector-heading"),
        text=concat(
            "action-heading-text",
            literal("action-heading-prefix", "SESSION ACTIONS / "),
            action_count,
        ),
    )
    builder.template(
        _ACTION_HISTORY_ROOT,
        tag=literal("action-history-tag", "section"),
        key=literal("action-history-key", "session-actions"),
        class_name=literal(
            "action-history-class", "inspector-section"
        ),
        children=(_ACTION_HISTORY_HEADING_ROOT, _ACTION_HISTORY_ROW_ROOT),
        condition=has_action_history,
    )

    builder.template(
        _CONTROL_HEADING_ROOT,
        tag=literal("control-heading-tag", "div"),
        key=literal("control-heading-key", "lifecycle:heading"),
        class_name=literal("control-heading-class", "inspector-heading"),
        text=literal(
            "control-heading-text", "CONTROLLED REVISION HEADS"
        ),
        condition=has_lifecycle,
    )
    root_key = concat(
        "root-key",
        literal("root-key-prefix", "presenter:timeline:"),
        selected,
    )
    builder.template(
        TIMELINE_TEMPLATE_ROOT,
        tag=literal("root-tag", "section"),
        key=root_key,
        class_name=literal("root-class", "inspector-section"),
        children=(
            _ACTION_HISTORY_ROOT,
            _CONTROL_HEADING_ROOT,
            _STATE_ROOT,
            _GATES_ROOT,
            _HISTORY_ROOT,
        ),
        condition=has_timeline,
    )
    return TIMELINE_TEMPLATE_ROOT


__all__ = [
    "TIMELINE_PREFIX",
    "TIMELINE_TEMPLATE_MEMBER_ROOTS",
    "TIMELINE_TEMPLATE_ROOT",
    "VIEW_TEMPLATE_PREFIX",
    "compose_timeline_template",
]
