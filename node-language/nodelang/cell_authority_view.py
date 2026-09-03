"""Graph-authored authority-list presenter over raw inspector projections.

The persisted template reads the universal application projection directly.
Transparent fragments splice repeated authority compositions without adding
disposable wrapper descriptors, and nested relationship fragments resolve their
enclosing relation through the generic parent context.
"""
from __future__ import annotations

from .cell_protocols import CellBatch
from .cell_view_template import ViewTemplateBuilder, ViewTemplateProtocol


VIEW_TEMPLATE_PREFIX = "app:view-template-protocol"
AUTHORITY_LIST_PREFIX = "app:properties-template:authority-list:v1"
AUTHORITY_LIST_TEMPLATE_ROOT = AUTHORITY_LIST_PREFIX + ":section"

_SUMMARY_ROOT = AUTHORITY_LIST_PREFIX + ":summary"
_IDENTITY_ROW_ROOT = AUTHORITY_LIST_PREFIX + ":field:identity:row"
_IDENTITY_VALUE_ROOT = AUTHORITY_LIST_PREFIX + ":field:identity:value"
_STACK_DETAILS_ROOT = AUTHORITY_LIST_PREFIX + ":stack:details"
_STACK_FRAGMENT_ROOT = AUTHORITY_LIST_PREFIX + ":stack:fragment"
_STACK_ROW_ROOT = AUTHORITY_LIST_PREFIX + ":stack:row"
_STACK_LABEL_ROOT = AUTHORITY_LIST_PREFIX + ":stack:label"
_STACK_VALUE_ROOT = AUTHORITY_LIST_PREFIX + ":stack:value"
_STACK_META_ROOT = AUTHORITY_LIST_PREFIX + ":stack:meta"
_BROWSER_DETAILS_ROOT = AUTHORITY_LIST_PREFIX + ":browser:details"
_BROWSER_FRAGMENT_ROOT = AUTHORITY_LIST_PREFIX + ":browser:fragment"
_BROWSER_ROW_ROOT = AUTHORITY_LIST_PREFIX + ":browser:row"
_BROWSER_LABEL_ROOT = AUTHORITY_LIST_PREFIX + ":browser:label"
_BROWSER_VALUE_ROOT = AUTHORITY_LIST_PREFIX + ":browser:value"
_BROWSER_META_ROOT = AUTHORITY_LIST_PREFIX + ":browser:meta"
_RELATIONSHIP_DETAILS_ROOT = AUTHORITY_LIST_PREFIX + ":relationship:details"
_RELATIONSHIP_FRAGMENT_ROOT = AUTHORITY_LIST_PREFIX + ":relationship:fragment"
_RELATIONSHIP_ROW_ROOT = AUTHORITY_LIST_PREFIX + ":relationship:row"
_RELATIONSHIP_LABEL_ROOT = AUTHORITY_LIST_PREFIX + ":relationship:label"
_RELATIONSHIP_VALUE_ROOT = AUTHORITY_LIST_PREFIX + ":relationship:value"
_RELATIONSHIP_META_ROOT = AUTHORITY_LIST_PREFIX + ":relationship:meta"

# Ordered replacement for section, heading, list, row, text, button, details,
# and action-binding. The relationship button owns its exact action attributes,
# so the button and action-binding incidences intentionally share one root.
AUTHORITY_LIST_TEMPLATE_MEMBER_ROOTS = (
    AUTHORITY_LIST_TEMPLATE_ROOT,
    _SUMMARY_ROOT,
    _STACK_FRAGMENT_ROOT,
    _IDENTITY_ROW_ROOT,
    _IDENTITY_VALUE_ROOT,
    _RELATIONSHIP_ROW_ROOT,
    _STACK_DETAILS_ROOT,
    _RELATIONSHIP_ROW_ROOT,
)


def compose_authority_list_template(
    batch: CellBatch,
    protocol: ViewTemplateProtocol,
) -> str:
    """Compose the authority inspector as rewritable graph relations."""
    builder = ViewTemplateBuilder(batch, protocol)
    prefix = AUTHORITY_LIST_PREFIX
    segments: dict[str, str] = {}

    def expression(
        name: str,
        operation: str,
        *arguments: str,
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
            base,
            *(segment(item) for item in names),
        )

    def concat(name: str, *arguments: str) -> str:
        return expression(name, "concat", *arguments)

    def attribute(name: str, attribute_name: str, value: str) -> str:
        return builder.attribute(
            "%s:attribute:%s" % (prefix, name),
            attribute_name,
            value,
        )

    root_context = expression("root-context", "root")
    item_context = expression("item-context", "item")
    parent_context = expression("parent-context", "parent")
    transparent = builder.atom(prefix + ":transparent", "transparent")

    selected = path("selected", root_context, "selected")
    selected_text = expression("selected-text", "string", selected)
    selected_or_none = expression(
        "selected-or-none",
        "choose",
        selected,
        selected_text,
        literal("selected-none", "none"),
    )
    authorization = path("authorization", root_context, "authorization")
    configuration = path("configuration", root_context, "configuration")
    composer = path("composer", root_context, "composer")
    catalog = path("catalog", root_context, "catalog")

    section_key = concat(
        "section-key",
        literal("section-key-prefix", "presenter:authority-list:"),
        selected_or_none,
    )
    builder.template(
        _SUMMARY_ROOT,
        tag=literal("summary-tag", "summary"),
        key=concat(
            "summary-key",
            literal("summary-key-prefix", "authority:summary:"),
            selected_or_none,
        ),
        class_name=literal("summary-class", "inspector-heading"),
        text=literal("summary-text", "AUTHORITY AND POLICY"),
    )

    def field(
        slug: str,
        label: str,
        value: str,
        *,
        session: bool = False,
    ) -> str:
        row_root = prefix + ":field:%s:row" % slug
        label_root = prefix + ":field:%s:label" % slug
        value_root = prefix + ":field:%s:value" % slug
        row_key = concat(
            "field-%s-row-key" % slug,
            literal(
                "field-%s-row-key-prefix" % slug,
                "authority-field:",
            ),
            selected_or_none,
            literal("field-%s-row-key-divider" % slug, ":"),
            literal("field-%s-row-key-slug" % slug, slug),
        )
        builder.template(
            label_root,
            tag=literal("field-%s-label-tag" % slug, "span"),
            key=concat(
                "field-%s-label-key" % slug,
                row_key,
                literal("field-%s-label-suffix" % slug, ":label"),
            ),
            class_name=literal(
                "field-%s-label-class" % slug, "property-label"
            ),
            text=literal("field-%s-label-text" % slug, label),
        )
        if session:
            session_text = expression(
                "field-%s-session-text" % slug, "string", value
            )
            value_key = concat(
                "field-%s-value-key" % slug,
                literal(
                    "field-%s-value-key-prefix" % slug,
                    "authority-session:",
                ),
                session_text,
            )
            attributes = (
                attribute(
                    "field-%s-button-type" % slug,
                    "type",
                    literal("field-%s-button-type-value" % slug, "button"),
                ),
                attribute(
                    "field-%s-button-title" % slug,
                    "title",
                    literal(
                        "field-%s-button-title-value" % slug,
                        "Inspect the current graph session",
                    ),
                ),
                attribute(
                    "field-%s-button-focus" % slug,
                    "data-universal-focus",
                    session_text,
                ),
            )
            builder.template(
                value_root,
                tag=literal("field-%s-value-tag" % slug, "button"),
                key=value_key,
                class_name=literal(
                    "field-%s-value-class" % slug, "connection-box"
                ),
                text=session_text,
                attributes=attributes,
            )
        else:
            builder.template(
                value_root,
                tag=literal("field-%s-value-tag" % slug, "div"),
                key=concat(
                    "field-%s-value-key" % slug,
                    literal(
                        "field-%s-value-key-prefix" % slug,
                        "authority-value:",
                    ),
                    selected_or_none,
                    literal("field-%s-value-key-divider" % slug, ":"),
                    literal("field-%s-value-key-slug" % slug, slug),
                ),
                class_name=literal(
                    "field-%s-value-class" % slug, "connection-box"
                ),
                text=value,
            )
        builder.template(
            row_root,
            tag=literal("field-%s-row-tag" % slug, "div"),
            key=row_key,
            class_name=literal(
                "field-%s-row-class" % slug, "property-row"
            ),
            children=(label_root, value_root),
        )
        return row_root

    subject_label = path(
        "authorization-subject-label", authorization, "subject_label"
    )
    scope_label = path(
        "authorization-scope-label", authorization, "scope_label"
    )
    session_root = path(
        "authorization-session", authorization, "session"
    )
    assigned_canvas_roots = path(
        "assigned-canvas-roots", authorization, "assigned_canvas_roots"
    )
    configuration_state = path(
        "configuration-state", configuration, "state"
    )
    configuration_heads = path(
        "configuration-heads", configuration, "heads"
    )
    authorization_state = path(
        "authorization-state", authorization, "state"
    )
    authorization_version = path(
        "authorization-version", authorization, "version"
    )
    authorization_default = path(
        "authorization-default", authorization, "default"
    )
    authorization_rule_count = path(
        "authorization-rule-count", authorization, "rule_count"
    )
    assurance_label = path(
        "authorization-assurance-label", authorization, "assurance_label"
    )
    device_custody = path(
        "device-custody", authorization, "native_identity", "device_custody"
    )
    device_active = path("device-active", device_custody, "active")
    device_hardware_backed = path(
        "device-hardware-backed", device_custody, "hardware_backed"
    )
    tenant_label = path(
        "authorization-tenant-label", authorization, "tenant_label"
    )
    composer_state = path("composer-state", composer, "state")
    admitted_adapters = path(
        "composer-admitted-adapters", composer, "admitted_adapters"
    )
    extension_mode = path(
        "composer-extension-mode", composer, "extension_mode"
    )

    field_roots = (
        field("identity", "identity", subject_label),
        field("scope", "scope", scope_label),
        field("session", "session", session_root, session=True),
        field(
            "data",
            "data",
            concat(
                "data-field-text",
                assigned_canvas_roots,
                literal("data-field-suffix", " assigned canvas roots"),
            ),
        ),
        field(
            "preview",
            "preview",
            concat(
                "preview-field-text",
                configuration_state,
                literal("preview-field-divider", " / "),
                expression(
                    "configuration-head-count", "length", configuration_heads
                ),
                literal("preview-field-suffix", " head"),
            ),
        ),
        field(
            "policy",
            "policy",
            concat(
                "policy-field-text",
                authorization_state,
                literal("policy-field-divider", " / v"),
                authorization_version,
            ),
        ),
        field(
            "decision",
            "decision",
            concat(
                "decision-field-text",
                authorization_default,
                literal("decision-field-divider", " / "),
                authorization_rule_count,
                literal("decision-field-suffix", " explicit rules"),
            ),
        ),
        field("assurance", "assurance", assurance_label),
        field(
            "device-key",
            "device key",
            concat(
                "device-key-field-text",
                device_active,
                literal("device-key-active-suffix", " active / "),
                device_hardware_backed,
                literal("device-key-backed-suffix", " TPM-backed"),
            ),
        ),
        field("tenant", "tenant", tenant_label),
        field("state", "state", composer_state),
        field(
            "catalogue",
            "catalogue",
            concat(
                "catalogue-field-text",
                expression("catalogue-count", "length", catalog),
                literal(
                    "catalogue-field-suffix", " released assemblies"
                ),
            ),
        ),
        field(
            "adapters",
            "adapters",
            concat(
                "adapters-field-text",
                admitted_adapters,
                literal(
                    "adapters-field-suffix",
                    " admitted / deny by default",
                ),
            ),
        ),
        field("extensions", "extensions", extension_mode),
    )

    stack = path("authority-stack", root_context, "authority_stack")
    stack_item_root = path("stack-item-root", item_context, "root")
    stack_item_root_text = expression(
        "stack-item-root-text", "string", stack_item_root
    )
    stack_roots = expression(
        "stack-roots", "map", stack, stack_item_root
    )
    stack_count = expression("stack-count", "length", stack_roots)
    stack_label = path("stack-label", item_context, "label")
    stack_role = path("stack-role", item_context, "role")
    stack_state = path("stack-state", item_context, "state")
    stack_row_key = concat(
        "stack-row-key",
        literal("stack-row-key-prefix", "authority-stack:"),
        stack_item_root_text,
    )
    builder.template(
        _STACK_LABEL_ROOT,
        tag=literal("stack-label-tag", "span"),
        key=concat(
            "stack-label-key",
            literal("stack-label-key-prefix", "authority-stack-label:"),
            stack_item_root_text,
        ),
        class_name=literal("stack-label-class", "property-label"),
        text=stack_label,
    )
    builder.template(
        _STACK_META_ROOT,
        tag=literal("stack-meta-tag", "span"),
        key=concat(
            "stack-meta-key",
            literal("stack-meta-key-prefix", "authority-stack-role:"),
            stack_item_root_text,
        ),
        class_name=literal("stack-meta-class", "lifecycle-head-meta"),
        text=stack_role,
    )
    builder.template(
        _STACK_VALUE_ROOT,
        tag=literal("stack-value-tag", "div"),
        key=concat(
            "stack-value-key",
            literal("stack-value-key-prefix", "authority-stack-state:"),
            stack_item_root_text,
        ),
        class_name=literal("stack-value-class", "connection-box"),
        text=stack_state,
        children=(_STACK_META_ROOT,),
    )
    builder.template(
        _STACK_ROW_ROOT,
        tag=literal("stack-row-tag", "button"),
        key=stack_row_key,
        class_name=literal(
            "stack-row-class",
            "library-row property-row authority-relation-row",
        ),
        attributes=(
            attribute(
                "stack-row-type",
                "type",
                literal("stack-row-type-value", "button"),
            ),
            attribute(
                "stack-row-title",
                "title",
                concat(
                    "stack-row-title-value",
                    stack_role,
                    literal("stack-row-title-divider", "\n"),
                    stack_item_root_text,
                ),
            ),
            attribute(
                "stack-row-focus",
                "data-universal-focus",
                stack_item_root_text,
            ),
        ),
        children=(_STACK_LABEL_ROOT, _STACK_VALUE_ROOT),
    )
    builder.template(
        _STACK_FRAGMENT_ROOT,
        tag=None,
        key=None,
        children=(_STACK_ROW_ROOT,),
        repeat=stack,
        transparent=transparent,
    )
    builder.template(
        prefix + ":stack:summary",
        tag=literal("stack-summary-tag", "summary"),
        key=concat(
            "stack-summary-key",
            literal(
                "stack-summary-key-prefix", "authority-stack-summary:"
            ),
            selected_or_none,
        ),
        class_name=literal("stack-summary-class", "inspector-heading"),
        text=concat(
            "stack-summary-text",
            literal(
                "stack-summary-text-prefix", "CURRENT AUTHORITY GRAPH / "
            ),
            stack_count,
        ),
    )
    builder.template(
        _STACK_DETAILS_ROOT,
        tag=literal("stack-details-tag", "details"),
        key=concat(
            "stack-details-key",
            literal(
                "stack-details-key-prefix", "authority-stack-list:"
            ),
            selected_or_none,
        ),
        class_name=literal("stack-details-class", "inspector-section"),
        attributes=(
            attribute(
                "stack-details-open",
                "open",
                expression(
                    "stack-details-open-value",
                    "equals",
                    literal("stack-open-left", "open"),
                    literal("stack-open-right", "open"),
                ),
            ),
        ),
        children=(prefix + ":stack:summary", _STACK_FRAGMENT_ROOT),
    )

    browser_sessions = path(
        "browser-sessions", authorization, "browser_sessions"
    )
    browser_item_root = path("browser-item-root", item_context, "root")
    browser_item_root_text = expression(
        "browser-item-root-text", "string", browser_item_root
    )
    browser_roots = expression(
        "browser-roots", "map", browser_sessions, browser_item_root
    )
    browser_count = expression("browser-count", "length", browser_roots)
    browser_state = path("browser-state", item_context, "state")
    browser_assurance = path(
        "browser-assurance", item_context, "assurance"
    )
    browser_expires_at = path(
        "browser-expires-at", item_context, "expires_at"
    )
    browser_revocation_reason = path(
        "browser-revocation-reason", item_context, "revocation_reason"
    )
    browser_meta_text = expression(
        "browser-meta-text",
        "choose",
        browser_revocation_reason,
        browser_revocation_reason,
        concat(
            "browser-expiry-text",
            literal("browser-expiry-prefix", "expires "),
            browser_expires_at,
        ),
    )
    builder.template(
        _BROWSER_LABEL_ROOT,
        tag=literal("browser-label-tag", "span"),
        key=concat(
            "browser-label-key",
            literal("browser-label-key-prefix", "browser-session-label:"),
            browser_item_root_text,
        ),
        class_name=literal("browser-label-class", "property-label"),
        text=concat(
            "browser-label-text",
            browser_state,
            literal("browser-label-divider", " / "),
            browser_assurance,
        ),
    )
    builder.template(
        _BROWSER_META_ROOT,
        tag=literal("browser-meta-tag", "span"),
        key=concat(
            "browser-meta-key",
            literal("browser-meta-key-prefix", "browser-session-meta:"),
            browser_item_root_text,
        ),
        class_name=literal("browser-meta-class", "lifecycle-head-meta"),
        text=browser_meta_text,
    )
    builder.template(
        _BROWSER_VALUE_ROOT,
        tag=literal("browser-value-tag", "div"),
        key=concat(
            "browser-value-key",
            literal("browser-value-key-prefix", "browser-session-value:"),
            browser_item_root_text,
        ),
        class_name=literal("browser-value-class", "connection-box"),
        text=browser_item_root_text,
        children=(_BROWSER_META_ROOT,),
    )
    builder.template(
        _BROWSER_ROW_ROOT,
        tag=literal("browser-row-tag", "button"),
        key=concat(
            "browser-row-key",
            literal("browser-row-key-prefix", "browser-session:"),
            browser_item_root_text,
        ),
        class_name=literal(
            "browser-row-class",
            "library-row property-row authority-relation-row",
        ),
        attributes=(
            attribute(
                "browser-row-type",
                "type",
                literal("browser-row-type-value", "button"),
            ),
            attribute(
                "browser-row-title",
                "title",
                literal(
                    "browser-row-title-value",
                    "Inspect this browser session relation",
                ),
            ),
            attribute(
                "browser-row-focus",
                "data-universal-focus",
                browser_item_root_text,
            ),
        ),
        children=(_BROWSER_LABEL_ROOT, _BROWSER_VALUE_ROOT),
    )
    builder.template(
        _BROWSER_FRAGMENT_ROOT,
        tag=None,
        key=None,
        children=(_BROWSER_ROW_ROOT,),
        repeat=browser_sessions,
        transparent=transparent,
    )
    builder.template(
        prefix + ":browser:summary",
        tag=literal("browser-summary-tag", "summary"),
        key=concat(
            "browser-summary-key",
            literal(
                "browser-summary-key-prefix", "browser-session-summary:"
            ),
            selected_or_none,
        ),
        class_name=literal("browser-summary-class", "inspector-heading"),
        text=concat(
            "browser-summary-text",
            literal(
                "browser-summary-text-prefix", "BROWSER SESSIONS / "
            ),
            browser_count,
        ),
    )
    builder.template(
        _BROWSER_DETAILS_ROOT,
        tag=literal("browser-details-tag", "details"),
        key=concat(
            "browser-details-key",
            literal(
                "browser-details-key-prefix", "browser-session-list:"
            ),
            selected_or_none,
        ),
        class_name=literal("browser-details-class", "inspector-section"),
        children=(prefix + ":browser:summary", _BROWSER_FRAGMENT_ROOT),
    )

    relationships = path(
        "authority-relationships", authorization, "relationships"
    )
    relationship_item_root = path(
        "relationship-item-root", item_context, "root"
    )
    relationship_item_root_text = expression(
        "relationship-item-root-text", "string", relationship_item_root
    )
    relationship_roots = expression(
        "relationship-roots",
        "map",
        relationships,
        relationship_item_root,
    )
    relationship_count = expression(
        "relationship-count", "length", relationship_roots
    )
    relationship_kind = path(
        "relationship-kind", item_context, "kind"
    )
    relationship_state = path(
        "relationship-state", item_context, "state"
    )
    relationship_source = path(
        "relationship-source", item_context, "source"
    )
    relationship_target = path(
        "relationship-target", item_context, "target"
    )
    relationship_scope = path(
        "relationship-scope", item_context, "scope"
    )
    relationship_issuer = path(
        "relationship-issuer", item_context, "issuer"
    )
    relationship_changed_by = path(
        "relationship-changed-by", item_context, "changed_by"
    )
    relationship_changed_at = path(
        "relationship-changed-at", item_context, "changed_at"
    )
    relationship_reason = path(
        "relationship-reason", item_context, "reason"
    )
    relationship_verified = path(
        "relationship-verified", item_context, "verified"
    )
    relationship_authority_reason = path(
        "relationship-authority-reason",
        item_context,
        "authority_reason",
    )
    verified_boolean = expression(
        "relationship-verified-boolean",
        "not",
        expression(
            "relationship-not-verified", "not", relationship_verified
        ),
    )
    verified_text = expression(
        "relationship-verified-text", "string", verified_boolean
    )
    relationship_scope_or_tenant = expression(
        "relationship-scope-or-tenant",
        "choose",
        relationship_scope,
        relationship_scope,
        literal("relationship-tenant-scope", "tenant"),
    )
    builder.template(
        _RELATIONSHIP_LABEL_ROOT,
        tag=literal("relationship-label-tag", "span"),
        key=concat(
            "relationship-label-key",
            literal(
                "relationship-label-key-prefix",
                "authority-relationship-label:",
            ),
            relationship_item_root_text,
        ),
        class_name=literal("relationship-label-class", "property-label"),
        text=concat(
            "relationship-label-text",
            relationship_kind,
            literal("relationship-label-divider", " / "),
            relationship_state,
        ),
    )

    # The meta descriptor is selected from the raw relation mapping. Mapping
    # each entry creates bounded fragments; parent resolves the enclosing
    # relation while the selected fragment supplies the reason value.
    relationship_mapping_fragments = expression(
        "relationship-mapping-fragments",
        "map",
        item_context,
        item_context,
    )
    fragment_key = path("relationship-fragment-key", item_context, "key")
    fragment_value = path(
        "relationship-fragment-value", item_context, "value"
    )
    reason_fragment = expression(
        "relationship-reason-fragment",
        "equals",
        fragment_key,
        literal("relationship-reason-key", "reason"),
    )
    parent_relationship_root = path(
        "parent-relationship-root", parent_context, "root"
    )
    parent_relationship_root_text = expression(
        "parent-relationship-root-text",
        "string",
        parent_relationship_root,
    )
    parent_relationship_verified = path(
        "parent-relationship-verified", parent_context, "verified"
    )
    relationship_signature = expression(
        "relationship-signature",
        "choose",
        parent_relationship_verified,
        literal("relationship-signed", "SIGNED"),
        literal("relationship-denied", "DENIED"),
    )
    builder.template(
        _RELATIONSHIP_META_ROOT,
        tag=literal("relationship-meta-tag", "span"),
        key=concat(
            "relationship-meta-key",
            literal(
                "relationship-meta-key-prefix",
                "authority-relationship-meta:",
            ),
            parent_relationship_root_text,
        ),
        class_name=literal(
            "relationship-meta-class", "lifecycle-head-meta"
        ),
        text=concat(
            "relationship-meta-text",
            relationship_signature,
            literal("relationship-meta-divider", " / "),
            fragment_value,
        ),
        repeat=relationship_mapping_fragments,
        condition=reason_fragment,
    )
    builder.template(
        _RELATIONSHIP_VALUE_ROOT,
        tag=literal("relationship-value-tag", "div"),
        key=concat(
            "relationship-value-key",
            literal(
                "relationship-value-key-prefix",
                "authority-relationship-value:",
            ),
            relationship_item_root_text,
        ),
        class_name=literal("relationship-value-class", "connection-box"),
        text=concat(
            "relationship-value-text",
            relationship_source,
            literal("relationship-value-arrow", " -> "),
            relationship_target,
        ),
        attributes=(
            attribute(
                "relationship-value-title",
                "title",
                concat(
                    "relationship-value-title-text",
                    literal("relationship-title-relation", "relation: "),
                    relationship_item_root_text,
                    literal("relationship-title-scope", "\nscope: "),
                    relationship_scope_or_tenant,
                    literal("relationship-title-issuer", "\nissuer: "),
                    relationship_issuer,
                    literal(
                        "relationship-title-changed-by", "\nchanged by: "
                    ),
                    relationship_changed_by,
                    literal(
                        "relationship-title-changed-at", "\nchanged at: "
                    ),
                    relationship_changed_at,
                    literal("relationship-title-reason", "\nreason: "),
                    relationship_reason,
                    literal(
                        "relationship-title-authority", "\nauthority: "
                    ),
                    relationship_authority_reason,
                ),
            ),
        ),
        children=(_RELATIONSHIP_META_ROOT,),
    )
    builder.template(
        _RELATIONSHIP_ROW_ROOT,
        tag=literal("relationship-row-tag", "button"),
        key=concat(
            "relationship-row-key",
            literal(
                "relationship-row-key-prefix", "authority-relationship:"
            ),
            relationship_item_root_text,
        ),
        class_name=literal(
            "relationship-row-class",
            "library-row property-row authority-relation-row",
        ),
        attributes=(
            attribute(
                "relationship-row-type",
                "type",
                literal("relationship-row-type-value", "button"),
            ),
            attribute(
                "relationship-row-title",
                "title",
                literal(
                    "relationship-row-title-value",
                    "Inspect this authority relation node",
                ),
            ),
            attribute(
                "relationship-row-root",
                "data-authority-relationship",
                relationship_item_root_text,
            ),
            attribute(
                "relationship-row-verified",
                "data-authority-verified",
                verified_text,
            ),
        ),
        children=(_RELATIONSHIP_LABEL_ROOT, _RELATIONSHIP_VALUE_ROOT),
    )
    builder.template(
        _RELATIONSHIP_FRAGMENT_ROOT,
        tag=None,
        key=None,
        children=(_RELATIONSHIP_ROW_ROOT,),
        repeat=relationships,
        transparent=transparent,
    )
    builder.template(
        prefix + ":relationship:summary",
        tag=literal("relationship-summary-tag", "summary"),
        key=concat(
            "relationship-summary-key",
            literal(
                "relationship-summary-key-prefix",
                "authority-relationship-summary:",
            ),
            selected_or_none,
        ),
        class_name=literal(
            "relationship-summary-class", "inspector-heading"
        ),
        text=concat(
            "relationship-summary-text",
            literal(
                "relationship-summary-text-prefix",
                "AUTHORITY RELATIONS / ",
            ),
            relationship_count,
        ),
    )
    builder.template(
        _RELATIONSHIP_DETAILS_ROOT,
        tag=literal("relationship-details-tag", "details"),
        key=concat(
            "relationship-details-key",
            literal(
                "relationship-details-key-prefix",
                "authority-relationship-list:",
            ),
            selected_or_none,
        ),
        class_name=literal(
            "relationship-details-class", "inspector-section"
        ),
        children=(
            prefix + ":relationship:summary",
            _RELATIONSHIP_FRAGMENT_ROOT,
        ),
    )

    builder.template(
        AUTHORITY_LIST_TEMPLATE_ROOT,
        tag=literal("section-tag", "details"),
        key=section_key,
        class_name=literal("section-class", "inspector-section"),
        children=(
            _SUMMARY_ROOT,
            *field_roots,
            _STACK_DETAILS_ROOT,
            _BROWSER_DETAILS_ROOT,
            _RELATIONSHIP_DETAILS_ROOT,
        ),
    )
    return AUTHORITY_LIST_TEMPLATE_ROOT


__all__ = [
    "AUTHORITY_LIST_PREFIX",
    "AUTHORITY_LIST_TEMPLATE_MEMBER_ROOTS",
    "AUTHORITY_LIST_TEMPLATE_ROOT",
    "VIEW_TEMPLATE_PREFIX",
    "compose_authority_list_template",
]
