"""Safe, generic DOM descriptors for graph-projected Properties content.

Descriptors are disposable projections, not a second semantic store.  Stable
keys and all semantic bindings originate in graph roots/incidences.  The
browser interprets only the allowlisted HTML vocabulary below; it does not
dispatch on ArchHub domains, node labels, or Properties panel names.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
import json
import re
from typing import Any

from .universal_cell import InvalidCell


ALLOWED_TAGS = frozenset({
    "button", "details", "div", "input", "label", "option", "section",
    "select", "span", "summary", "textarea",
})
ALLOWED_ATTRIBUTES = frozenset({
    "aria-controls", "aria-label", "aria-labelledby", "aria-pressed",
    "aria-selected", "autocomplete", "disabled",
    # draggable marks an element the pointer can pick up (the library
    # rows); it is a boolean hint, not executable content.
    "draggable", "hidden", "id",
    "maxlength", "open", "placeholder", "role", "spellcheck", "tabindex",
    "title", "step", "type",
})


def descriptor(
    key: str,
    tag: str = "div",
    *,
    class_name: str = "",
    text: object | None = None,
    value: object | None = None,
    attributes: Mapping[str, object] | None = None,
    children: Iterable[Mapping[str, object]] = (),
) -> dict[str, object]:
    """Build one bounded, non-executable presentation descriptor."""
    if not key or not isinstance(key, str):
        raise InvalidCell("view descriptor key is missing")
    if tag not in ALLOWED_TAGS:
        raise InvalidCell("view descriptor tag is outside the allowlist")
    if class_name and any(
        not token.replace("-", "").replace("_", "").isalnum()
        for token in class_name.split()
    ):
        raise InvalidCell("view descriptor class is invalid")
    admitted: dict[str, object] = {}
    for name, item in (attributes or {}).items():
        if name.startswith("on") or name in {"style", "src", "srcdoc"}:
            raise InvalidCell("executable view descriptor attribute denied")
        if name not in ALLOWED_ATTRIBUTES and not name.startswith("data-"):
            raise InvalidCell(
                "view descriptor attribute is outside the allowlist"
            )
        if isinstance(item, (str, int, float, bool)) or item is None:
            admitted[name] = item
        else:
            raise InvalidCell("view descriptor attribute is not scalar")
    result: dict[str, object] = {
        "key": key,
        "tag": tag,
        "class": class_name,
        "attributes": admitted,
        "children": [dict(child) for child in children],
    }
    if text is not None:
        result["text"] = str(text)
    if value is not None:
        result["value"] = str(value)
    return result


def _heading(key: str, text: str) -> dict[str, object]:
    return descriptor(
        "%s:heading" % key,
        class_name="inspector-heading",
        text=text,
    )


def _box(
    key: str,
    text: object,
    *,
    class_name: str = "connection-box",
    title: str | None = None,
) -> dict[str, object]:
    attributes = {"title": title} if title else None
    return descriptor(
        key, class_name=class_name, text=text, attributes=attributes
    )


def _row(
    key: str,
    label: object,
    content: Mapping[str, object],
    *,
    tag: str = "div",
    class_name: str = "property-row",
) -> dict[str, object]:
    return descriptor(
        key,
        tag,
        class_name=class_name,
        children=(
            descriptor(
                "%s:label" % key,
                tag="span",
                class_name="property-label",
                text=label,
            ),
            content,
        ),
    )


def _properties(projection: Mapping[str, Any]) -> list[dict[str, object]]:
    selected = str(projection.get("selected") or "none")
    rows = []
    for item in projection.get("properties", ()):
        relation = str(item["relation"])
        if item.get("editable"):
            label = str(item.get("label", ""))
            numeric = label in {"position_x", "position_y", "width"}
            input_type = (
                "color" if label == "color"
                and isinstance(item.get("value"), str)
                and re.fullmatch(r"#[0-9a-fA-F]{6}", item["value"])
                else "number" if numeric else "text"
            )
            attributes = {
                "type": input_type,
                "data-universal-control": str(item["control"]),
                "data-universal-event-fact-input": str(
                    item["event_fact_input"]
                ),
            }
            if numeric:
                attributes["step"] = "any"
            content = descriptor(
                "property-input:%s" % relation,
                tag="input",
                class_name="property-input",
                value=item.get("value", ""),
                attributes=attributes,
            )
        else:
            content = _box(
                "property-value:%s" % relation, item.get("value", "")
            )
        rows.append(_row(
            "property-row:%s" % relation,
            str(item.get("label", "")).replace("_", " "),
            content,
            tag="label",
        ))
    return [descriptor(
        "presenter:field-list:%s" % selected,
        tag="section",
        class_name="inspector-section",
        children=(_heading("properties", "PROPERTIES"), *rows),
    )]


def _focus(projection: Mapping[str, Any]) -> list[dict[str, object]]:
    focus = projection["focus"]
    root = str(focus["root"])
    summary = "%s / %s" % (
        str(focus["origin"]).upper(), str(focus["state"]).upper()
    )
    children: list[dict[str, object]] = [
        _heading("focus", "CURRENT FOCUS"),
        _box(
            "focus:summary:%s" % root,
            summary,
            class_name="connection-box focus-summary",
            title="Created %s" % focus["created_at"],
        ),
    ]
    for index, reason in enumerate(focus.get("reasons", ())):
        reason_root = str(reason["root"])
        target = descriptor(
            "focus:reason-button:%s" % reason_root,
            tag="button",
            class_name="connection-box connection-link focus-reason-link",
            text=reason["label"],
            attributes={
                "type": "button",
                "title": "Inspect this exact focus reason",
                "data-universal-focus": reason_root,
            },
        )
        children.append(_row(
            "focus:reason:%s:%s" % (index, reason_root), "WHY", target
        ))
    previous = focus.get("previous")
    if previous:
        target = descriptor(
            "focus:previous-button:%s" % previous,
            tag="button",
            class_name="connection-box connection-link",
            text="Previous focus",
            attributes={
                "type": "button",
                "title": "Inspect the previous persistent focus",
                "data-universal-focus": str(previous),
            },
        )
        children.append(_row("focus:previous:%s" % previous, "HISTORY", target))
    obligations = list(projection.get("obligations") or ())
    if obligations:
        obligation_rows = []
        for item in obligations:
            item_root = str(item["root"])
            obligation_rows.append(descriptor(
                "focus:obligation:%s" % item_root,
                tag="button",
                class_name="library-row focus-obligation-row",
                attributes={
                    "type": "button",
                    "title": "Inspect this exact persistent obligation",
                    "data-universal-focus": item_root,
                },
                children=(
                    descriptor(
                        "focus:obligation-label:%s" % item_root,
                        tag="span",
                        class_name="property-label",
                        text=item["label"],
                    ),
                    descriptor(
                        "focus:obligation-meta:%s" % item_root,
                        tag="span",
                        class_name="universal-library-meta",
                        text="%s / %s" % (
                            item["priority_label"], item["state"]
                        ),
                    ),
                ),
            ))
        open_count = sum(item["state"] == "open" for item in obligations)
        children.append(descriptor(
            "focus:obligations:%s" % root,
            tag="details",
            class_name="focus-obligations",
            children=(
                descriptor(
                    "focus:obligations-summary:%s" % root,
                    tag="summary",
                    class_name="inspector-heading",
                    text="OPEN OBLIGATIONS / %s" % open_count,
                ),
                *obligation_rows,
            ),
        ))
    return [descriptor(
        "presenter:focus-list:%s" % root,
        tag="section",
        class_name="inspector-section focus-section",
        children=children,
    )]


def _relations(projection: Mapping[str, Any]) -> list[dict[str, object]]:
    selected = str(projection.get("selected") or "none")
    relation = projection.get("selected_relation")
    children: list[dict[str, object]] = [
        _heading(
            "relations",
            "DATA FLOW" if relation else "CONNECTIONS",
        )
    ]
    if relation:
        gates = list(relation.get("gates") or ())
        authority_children: list[dict[str, object]] = [
            _heading(
                "relation-authority",
                "THIS RELATION / %s GATE" % len(gates),
            ),
            _box(
                "relation-flow:%s" % relation["id"],
                "%s -> %s" % (
                    (relation.get("source") or {}).get(
                        "participant_label", "Unresolved source"
                    ),
                    (relation.get("target") or {}).get(
                        "participant_label", "Unresolved target"
                    ),
                ),
                class_name="connection-box relation-flow-summary",
                title="relation node: %s\nobserved revision: %s" % (
                    relation["id"], relation["observed_revision"]
                ),
            ),
        ]
        for index, gate in enumerate(gates):
            gate_root = str(gate["participant"])
            if gate.get("navigable"):
                content = descriptor(
                    "relation-gate-button:%s:%s" % (index, gate_root),
                    tag="button",
                    class_name="connection-box connection-link",
                    text=gate["participant_label"],
                    attributes={
                        "type": "button",
                        "title": gate_root,
                        "data-universal-focus": gate_root,
                    },
                )
            else:
                content = _box(
                    "relation-gate-value:%s:%s" % (index, gate_root),
                    gate["participant_label"],
                    title=gate_root,
                )
            authority_children.append(_row(
                "relation-gate:%s:%s" % (index, gate_root),
                "%s %s / protected" % (gate.get("role") or "gate", index + 1),
                content,
            ))
        children.append(descriptor(
            "relation-authority:%s" % relation["id"],
            tag="section",
            class_name="relation-authority-summary",
            children=authority_children,
        ))

    connections = list(projection.get("connections") or ())
    if not connections:
        attached = [
            wire for wire in projection.get("wires", ())
            if wire["source"] == selected or wire["target"] == selected
        ]
        if not attached:
            children.append(_box(
                "relations:empty:%s" % selected, "0 relation cells attached"
            ))
        labels = {
            item["id"]: item.get("label", item["id"])
            for item in projection.get("nodes", ())
        }
        for wire in attached:
            wire_root = str(wire["id"])
            children.append(descriptor(
                "relation-link:%s" % wire_root,
                tag="button",
                class_name="library-row",
                text="%s -> %s" % (
                    labels.get(wire["source"], wire["source"]),
                    labels.get(wire["target"], wire["target"]),
                ),
                attributes={
                    "type": "button",
                    "title": wire_root,
                    "data-universal-relation": wire_root,
                },
            ))
    else:
        shown = [
            item for item in connections
            if not relation or item["role"] in {"source", "target"}
        ]
        for item in shown:
            incidence = str(item["incidence"])
            if item.get("editable", True) and item["role"] in {
                "source", "target"
            }:
                options = []
                selected_root = item.get("participant_owner") or item[
                    "participant"
                ]
                for node in projection.get("nodes", ()):
                    options.append(descriptor(
                        "relation-option:%s:%s" % (incidence, node["id"]),
                        tag="option",
                        text=node["label"],
                        value=node["id"],
                        attributes={
                            "data-selected": node["id"] == selected_root,
                        },
                    ))
                content = descriptor(
                    "relation-select:%s" % incidence,
                    tag="select",
                    class_name="property-input",
                    value=selected_root,
                    attributes={"data-universal-incidence": incidence},
                    children=options,
                )
            elif item.get("navigable"):
                participant = str(item["participant"])
                content = descriptor(
                    "relation-target:%s" % incidence,
                    tag="button",
                    class_name="connection-box connection-link",
                    text=item.get("participant_label") or participant,
                    attributes={
                        "type": "button",
                        "title": participant,
                        "data-universal-focus": participant,
                    },
                )
            else:
                content = _box(
                    "relation-value:%s" % incidence,
                    item.get("participant_label") or item["participant"],
                    title=str(item["participant"]),
                )
            children.append(_row(
                "relation-row:%s" % incidence,
                item["role"],
                content,
                tag="label",
            ))
    return [descriptor(
        "presenter:relation-list:%s" % selected,
        tag="section",
        class_name="inspector-section",
        children=children,
    )]


def _floor(projection: Mapping[str, Any]) -> list[dict[str, object]]:
    physical = projection["physical"]
    root = str(physical["identity"])
    rows = [
        _row(
            "floor:%s:%s" % (root, name.replace(" ", "-")),
            name,
            _box(
                "floor-value:%s:%s" % (root, name.replace(" ", "-")), value
            ),
        )
        for name, value in (
            ("identity", physical["identity"]),
            ("link 0", physical["link0"]),
            ("link 1", physical["link1"]),
        )
    ]
    if physical.get("editable"):
        atom = descriptor(
            "floor-atom-input:%s" % root,
            tag="input",
            class_name="property-input",
            value=physical.get("atom", ""),
            attributes={
                "type": "text",
                "data-universal-control": str(physical["control"]),
                "data-universal-event-fact-input": str(
                    physical["event_fact_input"]
                ),
            },
        )
    else:
        atom = _box(
            "floor-atom-value:%s" % root, physical.get("atom") or "empty"
        )
    rows.append(_row("floor-atom:%s" % root, "atom", atom, tag="label"))
    return [descriptor(
        "presenter:cell-floor:%s" % root,
        tag="details",
        class_name="inspector-section",
        children=(
            descriptor(
                "floor-summary:%s" % root,
                tag="summary",
                class_name="inspector-heading",
                text="PHYSICAL FLOOR",
            ),
            *rows,
        ),
    )]


def _presentation(projection: Mapping[str, Any]) -> list[dict[str, object]]:
    configuration = projection["configuration"]
    if projection.get("selected") != configuration.get("personal_asset"):
        selected = str(projection.get("selected") or "none")
        rows = []
        for item in projection.get("properties", ()):
            if item.get("label") not in {"color", "icon", "presentation"}:
                continue
            relation = str(item["relation"])
            value = str(item.get("value") or "")
            row_children: list[dict[str, object]] = [descriptor(
                "presentation-row:%s:label" % relation,
                tag="span",
                class_name="property-label",
                text=str(item["label"]).replace("_", " "),
            )]
            if item.get("presentation_editable"):
                row_children.append(descriptor(
                    "presentation-input:%s:personal" % relation,
                    tag="input",
                    class_name="property-input",
                    value=value,
                    attributes={
                        "type": "color",
                        "data-universal-control": str(
                            item["presentation_control"]
                        ),
                        "data-universal-event-fact-input": str(
                            item["presentation_event_fact_input"]
                        ),
                    },
                ))
                row_children.append(descriptor(
                    "presentation-row:%s:source" % relation,
                    class_name="presentation-source",
                    text="%s / %s" % (
                        str(item.get(
                            "presentation_source_mode", "inherited"
                        )).upper(),
                        item.get("presentation_source") or relation,
                    ),
                ))
                if item.get("presentation_reset"):
                    row_children.append(descriptor(
                        "presentation-row:%s:reset" % relation,
                        tag="button",
                        class_name="presentation-reset",
                        text="RESET",
                        attributes={
                            "type": "button",
                            "data-universal-control": str(
                                item["presentation_reset_control"]
                            ),
                        },
                    ))
            elif item.get("editable"):
                input_type = "color" if re.fullmatch(
                    r"#[0-9a-fA-F]{6}", value
                ) else "text"
                row_children.append(descriptor(
                    "presentation-input:%s" % relation,
                    tag="input",
                    class_name="property-input",
                    value=value,
                    attributes={
                        "type": input_type,
                        "data-universal-control": str(item["control"]),
                        "data-universal-event-fact-input": str(
                            item["event_fact_input"]
                        ),
                    },
                ))
            else:
                row_children.append(_box(
                    "presentation-value:%s" % relation, value
                ))
            rows.append(descriptor(
                "presentation-row:%s" % relation,
                tag="label",
                class_name="property-row",
                children=row_children,
            ))
        return [descriptor(
            "presenter:presentation-list:%s" % selected,
            tag="section",
            class_name="inspector-section",
            children=(_heading("presentation", "PRESENTATION"), *rows),
        )] if rows else []
    root = str(configuration["personal_asset"])
    children: list[dict[str, object]] = [
        _heading("presentation", "VERSIONED THEME"),
        _box(
            "presentation:state:%s" % root,
            "%s / %s / %s" % (
                configuration["state"],
                str(configuration["binding_mode"]).replace("-", " "),
                configuration["preview_revision"],
            ),
        ),
        _box(
            "presentation:binding:%s" % root,
            "ACTIVE WIRE %s / COURT %s" % (
                configuration["binding"],
                str(configuration["court"]["state"]).upper(),
            ),
        ),
    ]
    for field in configuration.get("theme_fields", ()):
        name = str(field["key"])
        value = field["value"]
        text = str(value)
        input_type = "color" if re.fullmatch(
            r"#[0-9a-fA-F]{6}", text
        ) else "text"
        children.append(_row(
            "theme-row:%s:%s" % (root, name),
            str(name).replace("_", " "),
            descriptor(
                "theme-input:%s:%s" % (root, name),
                tag="input",
                class_name="property-input",
                value=text,
                attributes={
                    "type": input_type,
                    "data-universal-control": str(field["control"]),
                    "data-universal-event-fact-input": str(
                        field["event_fact_input"]
                    ),
                },
            ),
            tag="label",
        ))

    history_rows = []
    for item in reversed(list(configuration.get("history", ()))):
        revision = str(item["revision"])
        row_children: list[dict[str, object]] = [
            descriptor(
                "theme-history-label:%s" % revision,
                tag="span",
                class_name="property-label",
                text="%s / %s / %s / %s evidence" % (
                    item["state"], item.get("reason") or "initial",
                    str(item["digest"])[:10], len(item.get("evidence", ())),
                ),
            ),
            descriptor(
                "theme-restore:%s" % revision,
                tag="button",
                class_name="operational-action",
                text=(
                    "CURRENT WIP" if item.get("current")
                    else "RESTORE AS NEW WIP"
                ),
                attributes={
                    "type": "button",
                    "disabled": bool(item.get("current")),
                    **(
                        {}
                        if item.get("current") else {
                            "data-universal-control": str(
                                item["restore_control"]
                            )
                        }
                    ),
                },
            ),
        ]
        for evidence in item.get("evidence", ()):
            evidence_root = str(evidence.get("root") or evidence["digest"])
            checks = list(evidence.get("checks", {}).items())
            passed = sum(bool(value) for _name, value in checks)
            proof_children = [
                descriptor(
                    "theme-evidence-summary:%s" % evidence_root,
                    tag="summary",
                    class_name="property-label",
                    text="%s COURT / %s OF %s CHECKS" % (
                        str(evidence["result"]).upper(), passed, len(checks)
                    ),
                ),
                _box(
                    "theme-evidence-meta:%s" % evidence_root,
                    "%s / %s ms / %s" % (
                        evidence["builder"], evidence["duration_ms"],
                        str(evidence["digest"])[:12],
                    ),
                ),
            ]
            proof_children.extend(
                descriptor(
                    "theme-check:%s:%s" % (evidence_root, name),
                    class_name="court-check",
                    text="%s %s" % (
                        "PASS" if value else "FAIL",
                        str(name).replace("-", " "),
                    ),
                )
                for name, value in checks
            )
            row_children.append(descriptor(
                "theme-evidence:%s" % evidence_root,
                tag="details",
                class_name="court-evidence",
                children=proof_children,
            ))
        history_rows.append(descriptor(
            "theme-history-row:%s" % revision,
            class_name="property-row",
            children=row_children,
        ))
    children.append(descriptor(
        "theme-history:%s" % root,
        tag="details",
        class_name="inspector-section",
        children=(
            descriptor(
                "theme-history-summary:%s" % root,
                tag="summary",
                class_name="inspector-heading",
                text="PREVIEW HISTORY / %s" % len(history_rows),
            ),
            *history_rows,
        ),
    ))

    can_publish = bool(configuration.get("can_publish"))
    can_promote = bool(configuration.get("can_promote"))
    published = configuration.get("published_revision")
    shared = configuration.get("shared_revision")
    if published:
        action_text = "PUBLISHED / BROWSER COURT PASSED"
    elif can_publish:
        action_text = "RUN BROWSER COURT + PUBLISH"
    elif can_promote:
        action_text = "RUN COURT + SHARE"
    elif shared:
        action_text = "SHARED / PUBLISH COURT UNAVAILABLE"
    else:
        action_text = "SHARE REQUIRES FOUNDER AUTHORITY"
    action_attributes: dict[str, object] = {
        "type": "button",
        "disabled": not (can_promote or can_publish),
    }
    if can_publish:
        action_attributes["data-universal-theme-publish"] = str(shared)
    else:
        action_attributes["data-universal-theme-share"] = str(
            configuration["preview_revision"]
        )
    children.append(descriptor(
        "theme-court-action:%s" % root,
        tag="button",
        class_name="operational-action",
        text=action_text,
        attributes=action_attributes,
    ))
    return [descriptor(
        "presenter:presentation-list:%s" % root,
        tag="section",
        class_name="inspector-section",
        children=children,
    )]


def _evidence(projection: Mapping[str, Any]) -> list[dict[str, object]]:
    definition = projection.get("selected_definition")
    if not definition:
        return []
    root = str(projection.get("selected") or "none")
    rows = []
    for label, value in (
        ("version", definition["version"]),
        ("interface count", definition["interfaces"]),
        ("cell count", definition["parts"]),
    ):
        slug = label.replace(" ", "-")
        rows.append(_row(
            "release:%s:%s" % (root, slug),
            label,
            _box("release-value:%s:%s" % (root, slug), value),
        ))
    return [descriptor(
        "presenter:evidence-list:%s" % root,
        tag="section",
        class_name="inspector-section",
        children=(_heading("release", "RELEASE"), *rows),
    )]


def _interfaces(projection: Mapping[str, Any]) -> list[dict[str, object]]:
    assembly = projection.get("selected_assembly")
    authoring = projection.get("authoring") or {}
    projected_interfaces = projection.get("selected_interfaces")
    interfaces = list(
        projected_interfaces
        if projected_interfaces is not None
        else (assembly or {}).get("interfaces", ())
    )
    if not interfaces and not authoring.get("add_interface"):
        return []
    root = str(projection["selected"])
    children: list[dict[str, object]] = [
        _heading("interfaces", "INTERFACES")
    ]
    nodes = {
        item["id"]: item for item in projection.get("nodes", ())
    }
    lifecycle = (assembly or {}).get("lifecycle")
    for item in interfaces:
        interface = str(item["id"])
        lifecycle_content = bool(
            lifecycle and not lifecycle.get("release_scoped")
            and interface == lifecycle.get("content_interface")
        )
        if lifecycle_content:
            wip = next(
                (state for state in lifecycle["states"]
                 if state["name"] == "WIP"),
                None,
            )
            controls = [descriptor(
                "interface-content:%s:%s" % (root, interface),
                tag="textarea",
                class_name="property-input lifecycle-content-input",
                value=item.get("value") or "",
                attributes={
                    "data-universal-lifecycle-content": "true",
                    "data-root": root,
                    "data-interface": interface,
                    "data-base": str((wip or {}).get("revision") or ""),
                },
            )]
            diverged = bool(wip and wip["head_count"] > 1)
            action_attributes: dict[str, object] = {
                "type": "button",
                "disabled": not bool(wip and wip["head_count"] >= 1),
                "data-root": root,
                "data-interface": interface,
            }
            if diverged:
                action_attributes.update({
                    "data-universal-lifecycle-merge": "true",
                    "data-parents": json.dumps(
                        [head["revision"] for head in wip["heads"]]
                    ),
                })
                action_text = "MERGE %s WIP HEADS" % wip["head_count"]
            else:
                action_attributes.update({
                    "data-universal-lifecycle-save": "true",
                    "data-base": str((wip or {}).get("revision") or ""),
                })
                action_text = "SAVE NEW WIP"
            controls.append(descriptor(
                "interface-content-action:%s:%s" % (root, interface),
                tag="button",
                class_name="operational-action",
                text=action_text,
                attributes=action_attributes,
            ))
            content = descriptor(
                "interface-content-controls:%s:%s" % (root, interface),
                class_name="universal-collection-row lifecycle-content-row",
                children=controls,
            )
        elif item["mode"] == "connection" and item.get("editable"):
            content = descriptor(
                "interface-input:%s:%s" % (root, interface),
                tag="input",
                class_name="property-input",
                value=item.get("value") or "",
                attributes={
                    "type": "text",
                    "title": "Edit %s through its declared interface"
                    % item["name"],
                    "data-universal-control": str(item["control"]),
                    "data-universal-event-fact-input": str(
                        item["event_fact_input"]
                    ),
                },
            )
        else:
            target = nodes.get(item.get("target"))
            if item["mode"] == "collection":
                value = "%s items" % len(item.get("items", ()))
            elif item["mode"] == "state":
                value = item.get("value") or "empty"
            elif target:
                value = target.get("label", target["id"])
            else:
                value = item.get("value") or "unwired"
            content = _box(
                "interface-value:%s:%s" % (root, interface), value
            )
        children.append(_row(
            "interface-row:%s:%s" % (root, interface),
            item["name"],
            content,
        ))

        if item["mode"] != "collection":
            continue
        members = list(item.get("items", ()))
        for index, member in enumerate(members):
            incidence = str(member["incidence"])
            controls: list[dict[str, object]] = [descriptor(
                "collection-input:%s" % incidence,
                tag="input",
                class_name="property-input",
                value=member["value"],
                attributes={
                    "type": "text",
                    "data-universal-control": str(member["control"]),
                    "data-universal-event-fact-input": str(
                        member["event_fact_input"]
                    ),
                },
            )]
            for action, label in (
                ("up", "\u2191"), ("down", "\u2193"), ("remove", "\u00d7")
            ):
                control_field = {
                    "up": "up_control",
                    "down": "down_control",
                    "remove": "remove_control",
                }[action]
                controls.append(descriptor(
                    "collection-action:%s:%s" % (incidence, action),
                    tag="button",
                    class_name="header-action",
                    text=label,
                    attributes={
                        "type": "button",
                        "title": action,
                        "disabled": (
                            action == "up" and index == 0
                            or action == "down" and index == len(members) - 1
                        ),
                        "data-universal-control": str(
                            member[control_field]
                        ),
                    },
                ))
            children.append(descriptor(
                "collection-row:%s" % incidence,
                class_name="universal-collection-row",
                children=controls,
            ))
        children.append(descriptor(
            "collection-add-row:%s:%s" % (root, interface),
            class_name="universal-collection-row",
            attributes={
                "data-universal-interaction-scope": str(
                    item["append_control"]
                ),
            },
            children=(
                descriptor(
                    "collection-add-input:%s:%s" % (root, interface),
                    tag="input",
                    class_name="property-input",
                    attributes={
                        "type": "text",
                        "placeholder": "New item",
                        "data-universal-event-fact-input": str(
                            item["append_event_fact_input"]
                        ),
                    },
                ),
                descriptor(
                    "collection-add:%s:%s" % (root, interface),
                    tag="button",
                    class_name="header-action",
                    text="+",
                    attributes={
                        "type": "button",
                        "title": "Add item",
                        "data-universal-control": str(
                            item["append_control"]
                        ),
                    },
                ),
            ),
        ))
    if authoring.get("add_interface"):
        form = authoring["interface_form"]
        presentation_options = tuple(
            descriptor(
                "interface-presentation-option:%s" % item["id"],
                tag="option",
                text=item["label"],
                value=item["id"],
            )
            for item in authoring.get("interface_presentations", ())
        )
        contract_options = tuple(
            descriptor(
                "interface-contract-option:%s" % item["id"],
                tag="option",
                text=item["label"],
                value=item["id"],
            )
            for item in authoring.get("interface_contracts", ())
        )
        form_key = "interface-create:%s" % root
        children.append(descriptor(
            form_key,
            class_name="interface-create",
            children=(
                descriptor(
                    "%s:name" % form_key,
                    tag="input",
                    class_name="property-input",
                    attributes={
                        "type": "text",
                        "placeholder": "Interface name",
                        "maxlength": "512",
                        "data-universal-relation-form-field": "name",
                        "data-universal-relation-form-input": form["inputs"]["name"],
                    },
                ),
                descriptor(
                    "%s:presentation" % form_key,
                    tag="select",
                    class_name="property-input",
                    attributes={
                        "data-universal-relation-form-field": "presentation",
                        "data-universal-relation-form-input": (
                            form["inputs"]["presentation"]
                        ),
                    },
                    children=presentation_options,
                ),
                descriptor(
                    "%s:contract" % form_key,
                    tag="select",
                    class_name="property-input",
                    attributes={
                        "data-universal-relation-form-field": "contract",
                        "data-universal-relation-form-input": (
                            form["inputs"]["contract"]
                        ),
                    },
                    children=contract_options,
                ),
                descriptor(
                    "%s:action" % form_key,
                    tag="button",
                    class_name="header-action",
                    text=form["control_label"],
                    attributes={
                        "type": "button",
                        "data-universal-relation-form-submit": form["root"],
                        "data-universal-control": form["control"],
                        "data-control-binding": form["control_binding"],
                        "data-control-capability": form["control_capability"],
                        "data-control-icon": form["control_icon"],
                        "title": form["control_title"],
                        "aria-label": form["control_title"],
                    },
                ),
            ),
            attributes={
                "data-universal-relation-form": form["root"],
                "data-universal-relation-form-operation": form["operation"],
                "data-universal-relation-form-path": form["operation_path"],
            },
        ))
    return [descriptor(
        "presenter:interface-list:%s" % root,
        tag="section",
        class_name="inspector-section",
        children=children,
    )]


def _controls(projection: Mapping[str, Any]) -> list[dict[str, object]]:
    assembly = projection.get("selected_assembly")
    if not assembly:
        return []
    root = str(projection["selected"])
    projected: list[dict[str, object]] = []
    state_items = [
        *assembly.get("status", ()), *assembly.get("errors", ())
    ]
    if state_items:
        rows = [
            _row(
                "state:%s:%s" % (root, item["id"]),
                item["label"],
                _box(
                    "state-value:%s:%s" % (root, item["id"]),
                    item.get("value") or "empty",
                ),
            )
            for item in state_items
        ]
        projected.append(descriptor(
            "presenter:control-list:state:%s" % root,
            tag="section",
            class_name="inspector-section",
            children=(_heading("state", "STATE"), *rows),
        ))

    operational = assembly.get("operational")
    if not operational:
        return projected
    children: list[dict[str, object]] = [
        _heading("operational", "OPERATIONAL STATE"),
        _row(
            "operational-current:%s" % root,
            "CURRENT",
            _box(
                "operational-current-value:%s" % root,
                operational["current_state_label"],
                class_name="connection-box operational-current",
            ),
        ),
    ]
    for item in operational.get("admitted_transitions", ()):
        event = str(item["event"])
        evidence = (
            ", ".join(
                value["label"] for value in item["required_evidence_types"]
            ) if item["required_evidence_types"] else "no evidence gate"
        )
        if item.get("user_decision"):
            action_text = str(item["event_label"]).upper()
        elif item.get("adapter_execute"):
            action_text = "EXECUTE"
        elif item["required_evidence_types"]:
            action_text = "EVIDENCE REQUIRED"
        else:
            action_text = str(item["event_label"])
        action_attributes: dict[str, object] = {
            "type": "button",
            "disabled": bool(
                item["required_evidence_types"]
                and not item.get("user_decision")
                and not item.get("adapter_execute")
            ),
            "data-root": root,
            "data-event": event,
            "data-expected": str(operational["current_state"]),
        }
        if item.get("adapter_execute"):
            action_attributes["data-universal-adapter-execute"] = "true"
            title = "Execute through the graph allowlisted adapter"
        elif item.get("control"):
            action_attributes["data-universal-control"] = str(
                item["control"]
            )
            if item.get("user_decision"):
                title = "Record authenticated %s decision" % item[
                    "event_label"
                ]
            else:
                title = "%s -> %s" % (
                    item["event_label"], item["to_state_label"]
                )
        else:
            if item["required_evidence_types"]:
                title = "Requires %s from an admitted adapter" % evidence
            else:
                title = "%s -> %s" % (
                    item["event_label"], item["to_state_label"]
                )
        action_attributes["title"] = title
        row = descriptor(
            "operational-transition:%s:%s" % (root, event),
            class_name="property-row",
            children=(
                descriptor(
                    "operational-transition-label:%s:%s" % (root, event),
                    tag="span",
                    class_name="property-label",
                    text="%s -> %s" % (
                        item["event_label"], item["to_state_label"]
                    ),
                ),
                _box(
                    "operational-transition-evidence:%s:%s" % (root, event),
                    evidence,
                ),
                descriptor(
                    "operational-transition-action:%s:%s" % (root, event),
                    tag="button",
                    class_name="operational-action",
                    text=action_text,
                    attributes=action_attributes,
                ),
            ),
        )
        children.append(row)
    history_rows = []
    for index, item in enumerate(operational.get("history", ())):
        history_rows.append(_row(
            "operational-history:%s:%s" % (root, index),
            item["event_label"],
            _box(
                "operational-history-value:%s:%s" % (root, index),
                "%s -> %s / %s evidence" % (
                    item["from_state_label"], item["to_state_label"],
                    len(item.get("evidence", ())),
                ),
            ),
        ))
    children.append(descriptor(
        "operational-history-list:%s" % root,
        tag="details",
        class_name="inspector-section",
        children=(
            descriptor(
                "operational-history-summary:%s" % root,
                tag="summary",
                class_name="inspector-heading",
                text="OPERATION HISTORY / %s" % len(history_rows),
            ),
            *history_rows,
        ),
    ))
    projected.append(descriptor(
        "presenter:control-list:operational:%s" % root,
        tag="section",
        class_name="inspector-section",
        children=children,
    ))
    return projected


def _timeline(projection: Mapping[str, Any]) -> list[dict[str, object]]:
    assembly = projection.get("selected_assembly")
    lifecycle = assembly.get("lifecycle") if assembly else None
    root = str(projection["selected"])
    children: list[dict[str, object]] = []
    actions = (projection.get("action_history") or {}).get(
        "transactions", ()
    )
    if actions:
        action_rows = []
        for item in actions:
            transaction_root = str(item["root"])
            row_key = "session-action:%s" % transaction_root
            change_count = int(item["change_count"])
            action_rows.append(_row(
                row_key,
                "%s / %s" % (
                    str(item["state"]).upper(), item["operation"]
                ),
                descriptor(
                    "%s:value" % row_key,
                    class_name="connection-box lifecycle-head",
                    text="%s %s" % (
                        change_count,
                        "change" if change_count == 1 else "changes",
                    ),
                    attributes={
                        "title": (
                            "route: %s\ncapability: %s\nscopes: %s"
                        ) % (
                            item["route"], item["capability"],
                            item["scope_count"],
                        )
                    },
                    children=(descriptor(
                        "%s:meta" % row_key,
                        tag="span",
                        class_name="lifecycle-head-meta",
                        text=item["timestamp"],
                    ),),
                ),
            ))
        children.append(descriptor(
            "session-actions",
            tag="section",
            class_name="inspector-section",
            children=(
                descriptor(
                    "session-actions:heading",
                    class_name="inspector-heading",
                    text="SESSION ACTIONS / %s" % len(action_rows),
                ),
                *action_rows,
            ),
        ))
    if not lifecycle:
        if not children:
            return []
        return [descriptor(
            "presenter:timeline:%s" % root,
            tag="section",
            class_name="inspector-section",
            children=children,
        )]
    children.append(_heading("lifecycle", "CONTROLLED REVISION HEADS"))
    for state in lifecycle.get("states", ()):
        state_name = str(state["name"])
        state_children: list[dict[str, object]] = [descriptor(
            "lifecycle-state-label:%s:%s" % (root, state_name),
            tag="span",
            class_name="property-label",
            text="%s / %s ACTIVE %s" % (
                state_name, state["head_count"],
                "HEAD" if state["head_count"] == 1 else "HEADS",
            ),
        )]
        if not state.get("heads"):
            state_children.append(_box(
                "lifecycle-empty:%s:%s" % (root, state_name),
                "not promoted",
            ))
        for head in state.get("heads", ()):
            revision = str(head["revision"])
            branch = head.get("branch_label") or head["branch"]
            head_box = descriptor(
                "lifecycle-head:%s" % revision,
                class_name="connection-box lifecycle-head",
                text="%s / %s bytes" % (branch, head["content_bytes"]),
                attributes={
                    "title": (
                        "revision: %s\ndigest: %s\nparents: %s\nactor: %s"
                        "\nevidence: %s"
                    ) % (
                        revision, head["content_digest"], len(head["parents"]),
                        head["actor"], len(head["evidence"]),
                    )
                },
                children=(descriptor(
                    "lifecycle-head-meta:%s" % revision,
                    tag="span",
                    class_name="lifecycle-head-meta",
                    text="%s / %s %s / %s evidence" % (
                        revision, len(head["parents"]),
                        "parent" if len(head["parents"]) == 1 else "parents",
                        len(head["evidence"]),
                    ),
                ),),
            )
            state_children.append(head_box)
            for evidence in head.get("evidence_details", ()):
                evidence_root = str(evidence["root"])
                checks = list((evidence.get("checks") or {}).items())
                passed = sum(bool(value) for _name, value in checks)
                proof_children = [descriptor(
                    "lifecycle-evidence-summary:%s" % evidence_root,
                    tag="summary",
                    class_name="property-label",
                    text=(
                        "%s COURT / %s OF %s CHECKS" % (
                            str(evidence["result"]).upper(), passed,
                            len(checks),
                        ) if evidence.get("court") else
                        "EVIDENCE / %s" % evidence_root
                    ),
                )]
                if evidence.get("court"):
                    proof_children.append(_box(
                        "lifecycle-evidence-meta:%s" % evidence_root,
                        "%s / %s ms / %s" % (
                            evidence["builder"], evidence["duration_ms"],
                            str(evidence.get("digest") or "")[:12],
                        ),
                    ))
                    proof_children.extend(
                        descriptor(
                            "lifecycle-check:%s:%s" % (evidence_root, name),
                            class_name="court-check",
                            text="%s %s" % (
                                "PASS" if value else "FAIL",
                                str(name).replace("-", " "),
                            ),
                        )
                        for name, value in checks
                    )
                state_children.append(descriptor(
                    "lifecycle-evidence:%s" % evidence_root,
                    tag="details",
                    class_name="court-evidence",
                    children=proof_children,
                ))
        if state["head_count"] > 1:
            state_children.append(descriptor(
                "lifecycle-divergence:%s:%s" % (root, state_name),
                class_name="lifecycle-divergence",
                text=(
                    "%s ACTIVE VARIATIONS / SELECT A BASE OR MERGE EXPLICITLY"
                    % state["head_count"]
                ),
            ))
        children.append(descriptor(
            "lifecycle-state:%s:%s" % (root, state_name),
            class_name="property-row",
            children=state_children,
        ))

    gate_rows = []
    for item in lifecycle.get("transitions", ()):
        relation = str(item["relation"])
        command = {
            "shared": "SHARE", "published": "PUBLISH", "archived": "ARCHIVE"
        }.get(item["target_name"], str(item["target_name"]).upper())
        if item.get("already_promoted"):
            action_text = "%s REVISION EXISTS" % str(
                item["target_name"]
            ).upper()
        elif item.get("ready"):
            action_text = "RUN COURT + %s" % command
        else:
            action_text = "REQUIRES ONE %s HEAD" % str(
                item["source_name"]
            ).upper()
        action = descriptor(
            "lifecycle-gate-action:%s" % relation,
            tag="button",
            class_name="operational-action",
            text=action_text,
            attributes={
                "type": "button",
                "disabled": not bool(item.get("ready")),
                "title": (
                    "transition relation: %s\ncourt: %s\n%s required evidence types"
                ) % (
                    relation, item["court"], len(item["required_evidence"])
                ),
                "data-universal-resource-promote": "true",
                "data-root": root,
                "data-target": str(item["target_name"]),
                "data-source": str(item.get("source_revision") or ""),
            },
        )
        gate_rows.append(_row(
            "lifecycle-gate:%s" % relation,
            "%s -> %s" % (
                str(item["source_name"]).upper(),
                str(item["target_name"]).upper(),
            ),
            action,
        ))
    children.append(descriptor(
        "lifecycle-gates:%s" % root,
        tag="section",
        class_name="inspector-section",
        children=(_heading("lifecycle-gates", "LIFECYCLE GATES"), *gate_rows),
    ))

    history_rows = []
    for item in lifecycle.get("history", ()):
        revision = str(item["revision"])
        history_rows.append(_row(
            "lifecycle-history:%s" % revision,
            "%s / %s" % (
                item["state"], item.get("branch_label") or item["branch"]
            ),
            descriptor(
                "lifecycle-history-value:%s" % revision,
                class_name="connection-box lifecycle-head",
                text=revision,
                attributes={
                    "title": "actor: %s\nparents: %s\nevidence: %s" % (
                        item["actor"], len(item["parents"]),
                        len(item["evidence"]),
                    )
                },
                children=(descriptor(
                    "lifecycle-history-meta:%s" % revision,
                    tag="span",
                    class_name="lifecycle-head-meta",
                    text="%s parents / %s evidence%s" % (
                        len(item["parents"]), len(item["evidence"]),
                        " / %s" % item["timestamp"]
                        if item.get("timestamp") else "",
                    ),
                ),),
            ),
        ))
    children.append(descriptor(
        "lifecycle-history-list:%s" % root,
        tag="details",
        class_name="inspector-section",
        children=(
            descriptor(
                "lifecycle-history-summary:%s" % root,
                tag="summary",
                class_name="inspector-heading",
                text="REVISION HISTORY / %s" % len(history_rows),
            ),
            *history_rows,
        ),
    ))
    return [descriptor(
        "presenter:timeline:%s" % root,
        tag="section",
        class_name="inspector-section",
        children=children,
    )]


def _authority(projection: Mapping[str, Any]) -> list[dict[str, object]]:
    authorization = projection["authorization"]
    configuration = projection["configuration"]
    root = str(projection.get("selected") or "none")
    fields = (
        ("identity", authorization["subject_label"]),
        ("scope", authorization["scope_label"]),
        ("session", authorization["session"]),
        (
            "data",
            "%s assigned canvas roots" % authorization[
                "assigned_canvas_roots"
            ],
        ),
        (
            "preview",
            "%s / %s head" % (
                configuration["state"], len(configuration["heads"])
            ),
        ),
        (
            "policy",
            "%s / v%s" % (
                authorization["state"], authorization["version"]
            ),
        ),
        (
            "decision",
            "%s / %s explicit rules" % (
                authorization["default"], authorization["rule_count"]
            ),
        ),
        ("assurance", authorization["assurance_label"]),
        (
            "device key",
            "%s active / %s TPM-backed" % (
                authorization["native_identity"]["device_custody"]["active"],
                authorization["native_identity"]["device_custody"][
                    "hardware_backed"
                ],
            ),
        ),
        ("tenant", authorization["tenant_label"]),
        ("state", projection["composer"]["state"]),
        (
            "catalogue",
            "%s released assemblies" % len(projection.get("catalog", ())),
        ),
        (
            "adapters",
            "%s admitted / deny by default" % projection["composer"][
                "admitted_adapters"
            ],
        ),
        ("extensions", projection["composer"]["extension_mode"]),
    )
    children: list[dict[str, object]] = [
        descriptor(
            "authority:summary:%s" % root,
            tag="summary",
            class_name="inspector-heading",
            text="AUTHORITY AND POLICY",
        )
    ]
    for label, value in fields:
        slug = label.replace(" ", "-")
        if label == "session":
            content = descriptor(
                "authority-session:%s" % value,
                tag="button",
                class_name="connection-box",
                text=value,
                attributes={
                    "type": "button",
                    "title": "Inspect the current graph session",
                    "data-universal-focus": str(value),
                },
            )
        else:
            content = _box(
                "authority-value:%s:%s" % (root, slug), value
            )
        children.append(_row(
            "authority-field:%s:%s" % (root, slug), label, content
        ))

    stack_rows = []
    for item in projection.get("authority_stack", ()):
        item_root = str(item["root"])
        stack_rows.append(descriptor(
            "authority-stack:%s" % item_root,
            tag="button",
            class_name="library-row property-row authority-relation-row",
            attributes={
                "type": "button",
                "title": "%s\n%s" % (item["role"], item_root),
                "data-universal-focus": item_root,
            },
            children=(
                descriptor(
                    "authority-stack-label:%s" % item_root,
                    tag="span",
                    class_name="property-label",
                    text=item["label"],
                ),
                descriptor(
                    "authority-stack-state:%s" % item_root,
                    class_name="connection-box",
                    text=item["state"],
                    children=(descriptor(
                        "authority-stack-role:%s" % item_root,
                        tag="span",
                        class_name="lifecycle-head-meta",
                        text=item["role"],
                    ),),
                ),
            ),
        ))
    children.append(descriptor(
        "authority-stack-list:%s" % root,
        tag="details",
        class_name="inspector-section",
        attributes={"open": True},
        children=(
            descriptor(
                "authority-stack-summary:%s" % root,
                tag="summary",
                class_name="inspector-heading",
                text="CURRENT AUTHORITY GRAPH / %s" % len(stack_rows),
            ),
            *stack_rows,
        ),
    ))

    browser_rows = []
    browser_sessions = list(authorization.get("browser_sessions") or ())
    for item in browser_sessions:
        item_root = str(item["root"])
        browser_rows.append(descriptor(
            "browser-session:%s" % item_root,
            tag="button",
            class_name="library-row property-row authority-relation-row",
            attributes={
                "type": "button",
                "title": "Inspect this browser session relation",
                "data-universal-focus": item_root,
            },
            children=(
                descriptor(
                    "browser-session-label:%s" % item_root,
                    tag="span",
                    class_name="property-label",
                    text="%s / %s" % (item["state"], item["assurance"]),
                ),
                descriptor(
                    "browser-session-value:%s" % item_root,
                    class_name="connection-box",
                    text=item_root,
                    children=(descriptor(
                        "browser-session-meta:%s" % item_root,
                        tag="span",
                        class_name="lifecycle-head-meta",
                        text=item.get("revocation_reason")
                        or "expires %s" % item["expires_at"],
                    ),),
                ),
            ),
        ))
    children.append(descriptor(
        "browser-session-list:%s" % root,
        tag="details",
        class_name="inspector-section",
        children=(
            descriptor(
                "browser-session-summary:%s" % root,
                tag="summary",
                class_name="inspector-heading",
                text="BROWSER SESSIONS / %s" % len(browser_rows),
            ),
            *browser_rows,
        ),
    ))

    relationship_rows = []
    relationships = list(authorization.get("relationships") or ())
    for relation in relationships:
        relation_root = str(relation["root"])
        relationship_rows.append(descriptor(
            "authority-relationship:%s" % relation_root,
            tag="button",
            class_name="library-row property-row authority-relation-row",
            attributes={
                "type": "button",
                "title": "Inspect this authority relation node",
                "data-authority-relationship": relation_root,
                "data-authority-verified": str(bool(relation["verified"])),
            },
            children=(
                descriptor(
                    "authority-relationship-label:%s" % relation_root,
                    tag="span",
                    class_name="property-label",
                    text="%s / %s" % (
                        relation["kind"], relation["state"]
                    ),
                ),
                descriptor(
                    "authority-relationship-value:%s" % relation_root,
                    class_name="connection-box",
                    text="%s -> %s" % (
                        relation["source"], relation["target"]
                    ),
                    attributes={
                        "title": (
                            "relation: %s\nscope: %s\nissuer: %s\n"
                            "changed by: %s\nchanged at: %s\nreason: %s\n"
                            "authority: %s"
                        ) % (
                            relation_root, relation.get("scope") or "tenant",
                            relation["issuer"], relation["changed_by"],
                            relation["changed_at"], relation["reason"],
                            relation["authority_reason"],
                        )
                    },
                    children=(descriptor(
                        "authority-relationship-meta:%s" % relation_root,
                        tag="span",
                        class_name="lifecycle-head-meta",
                        text="%s / %s" % (
                            "SIGNED" if relation["verified"] else "DENIED",
                            relation["reason"],
                        ),
                    ),),
                ),
            ),
        ))
    children.append(descriptor(
        "authority-relationship-list:%s" % root,
        tag="details",
        class_name="inspector-section",
        children=(
            descriptor(
                "authority-relationship-summary:%s" % root,
                tag="summary",
                class_name="inspector-heading",
                text="AUTHORITY RELATIONS / %s" % len(relationship_rows),
            ),
            *relationship_rows,
        ),
    ))
    return [descriptor(
        "presenter:authority-list:%s" % root,
        tag="details",
        class_name="inspector-section",
        children=children,
    )]


_PROJECTORS = {}


def project_presenter(
    presenter_name: str,
    projection: Mapping[str, Any],
) -> list[dict[str, object]] | None:
    """Project one admitted standard presenter, or signal migration pending."""
    projector = _PROJECTORS.get(presenter_name)
    return projector(projection) if projector is not None else None


__all__ = [
    "ALLOWED_ATTRIBUTES",
    "ALLOWED_TAGS",
    "descriptor",
    "project_presenter",
]
