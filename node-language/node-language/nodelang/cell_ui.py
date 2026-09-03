"""Safe HTML projection from universal-cell UI relations.

UI elements, text, attributes, classes, and child order are ordinary cells.
The renderer is a presentation-boundary interpreter with a narrow allowlist;
it is not semantic application authority and it executes no graph atom as code.
"""
from __future__ import annotations

from dataclasses import dataclass
import html
import re
from types import MappingProxyType
from typing import Iterable, Mapping
import uuid

from .cell_protocols import CellBatch, read_relation
from .universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell, Snapshot


ROLE_NAMES = (
    "vocabulary-member",
    "tag",
    "class",
    "text",
    "attribute",
    "attribute-name",
    "attribute-value",
    "child",
)

ALLOWED_TAGS = frozenset({
    "a", "article", "aside", "button", "div", "footer", "h1", "h2",
    "h3", "header", "li", "main", "nav", "p", "section", "span",
    "strong", "ul",
})
ALLOWED_ATTRIBUTES = frozenset({
    "href", "type", "title", "role", "tabindex",
})
CLASS_PATTERN = re.compile(r"^[A-Za-z0-9_-]+(?: [A-Za-z0-9_-]+)*$")
ATTRIBUTE_PATTERN = re.compile(r"^[a-z][a-z0-9_.:-]*$")


@dataclass(frozen=True, slots=True)
class UIProtocol:
    root_id: str
    roles: Mapping[str, str]

    def role(self, name: str) -> str:
        try:
            return self.roles[name]
        except KeyError as exc:
            raise InvalidCell("unknown UI role %r" % name) from exc


class UIBuilder:
    """Compose a UI tree into one caller-visible Store revision."""

    def __init__(self, store: CellStore, protocol: UIProtocol) -> None:
        self.store = store
        self.protocol = protocol
        self.batch = CellBatch(store)

    def _atom(self, prefix: str, value: str) -> str:
        root_id = "ui:%s:%s" % (prefix, uuid.uuid4().hex)
        self.batch.add(Cell(
            root_id, NULL_CELL_ID, NULL_CELL_ID, value.encode("utf-8")
        ))
        return root_id

    def attribute(self, name: str, value: str) -> str:
        name_root = self._atom("attribute-name", name)
        value_root = self._atom("attribute-value", value)
        root_id = "ui:attribute:%s" % uuid.uuid4().hex
        self.batch.relation((
            (self.protocol.role("attribute-name"), name_root),
            (self.protocol.role("attribute-value"), value_root),
        ), relation_id=root_id)
        return root_id

    def element(
        self,
        tag: str,
        *,
        class_name: str = "",
        text: str | None = None,
        text_root: str | None = None,
        attributes: Mapping[str, str] | None = None,
        children: Iterable[str] = (),
        element_id: str | None = None,
    ) -> str:
        tag_root = self._atom("tag", tag)
        members = [(self.protocol.role("tag"), tag_root)]
        if class_name:
            members.append((
                self.protocol.role("class"),
                self._atom("class", class_name),
            ))
        if text is not None and text_root is not None:
            raise InvalidCell("UI element cannot copy and bind text together")
        if text_root is not None:
            members.append((self.protocol.role("text"), text_root))
        elif text is not None:
            members.append((
                self.protocol.role("text"), self._atom("text", text)
            ))
        for name, value in (attributes or {}).items():
            members.append((
                self.protocol.role("attribute"), self.attribute(name, value)
            ))
        members.extend(
            (self.protocol.role("child"), child) for child in children
        )
        root_id = element_id or "ui:element:%s" % uuid.uuid4().hex
        self.batch.relation(members, relation_id=root_id)
        return root_id

    def commit(self) -> int:
        return self.batch.commit()


def bootstrap_ui_protocol(
    store: CellStore,
    *,
    prefix: str = "ui-protocol",
) -> UIProtocol:
    roles = {name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES}
    batch = CellBatch(store)
    for name, root_id in roles.items():
        batch.add(Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, name.encode("ascii")))
    root_id = "%s:root" % prefix
    batch.relation(
        ((roles["vocabulary-member"], root) for root in roles.values()),
        relation_id=root_id,
    )
    batch.commit()
    return UIProtocol(root_id, MappingProxyType(roles))


def _one(members, role_id: str, label: str) -> str | None:
    values = [
        member.participant_id for member in members
        if member.role_id == role_id
    ]
    if len(values) > 1:
        raise InvalidCell("UI element repeats %s" % label)
    return values[0] if values else None


def _text(snapshot: Snapshot, root_id: str) -> str:
    try:
        return snapshot.cells[root_id].atom.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InvalidCell("UI text is not UTF-8") from exc


def _validate_attribute(name: str, value: str) -> None:
    if not ATTRIBUTE_PATTERN.fullmatch(name):
        raise InvalidCell("UI attribute name is invalid")
    if name.startswith("on") or name in {"style", "srcdoc"}:
        raise InvalidCell("executable UI attributes are forbidden")
    if (
        name not in ALLOWED_ATTRIBUTES
        and not name.startswith("aria-")
        and not name.startswith("data-")
    ):
        raise InvalidCell("UI attribute is outside the renderer allowlist")
    if "\x00" in value:
        raise InvalidCell("UI attribute contains a null byte")
    if name == "href" and (
        not value.startswith("/")
        or value.startswith("//")
        or "\\" in value
        or any(ord(character) < 32 for character in value)
    ):
        raise InvalidCell("UI link must be a local absolute path")


def render_ui(
    snapshot: Snapshot,
    protocol: UIProtocol,
    root_id: str,
    *,
    budget: int = 10_000,
) -> str:
    """Render one graph UI tree without evaluating atoms as HTML or code."""
    remaining = budget
    active: set[str] = set()

    def render(element_root: str) -> str:
        nonlocal remaining
        remaining -= 1
        if remaining < 0:
            raise InvalidCell("UI render exceeded its element budget")
        if element_root in active:
            raise InvalidCell("UI child graph contains a cycle")
        active.add(element_root)
        members = read_relation(snapshot, element_root, budget=10_000)
        tag_root = _one(members, protocol.role("tag"), "tag")
        if tag_root is None:
            raise InvalidCell("UI element has no tag")
        tag = _text(snapshot, tag_root)
        if tag not in ALLOWED_TAGS:
            raise InvalidCell("UI tag is outside the renderer allowlist")
        class_root = _one(members, protocol.role("class"), "class")
        text_root = _one(members, protocol.role("text"), "text")
        attributes: list[str] = []
        if class_root is not None:
            class_name = _text(snapshot, class_root)
            if not CLASS_PATTERN.fullmatch(class_name):
                raise InvalidCell("UI class list is invalid")
            attributes.append('class="%s"' % html.escape(class_name, quote=True))
        for member in members:
            if member.role_id != protocol.role("attribute"):
                continue
            attribute = read_relation(
                snapshot, member.participant_id, budget=32
            )
            name_root = _one(
                attribute, protocol.role("attribute-name"), "attribute name"
            )
            value_root = _one(
                attribute, protocol.role("attribute-value"), "attribute value"
            )
            if name_root is None or value_root is None:
                raise InvalidCell("UI attribute is incomplete")
            name, value = _text(snapshot, name_root), _text(snapshot, value_root)
            _validate_attribute(name, value)
            attributes.append('%s="%s"' % (
                name, html.escape(value, quote=True)
            ))
        inner = html.escape(
            _text(snapshot, text_root), quote=False
        ) if text_root is not None else ""
        for member in members:
            if member.role_id == protocol.role("child"):
                inner += render(member.participant_id)
        active.remove(element_root)
        opening = "<%s%s>" % (
            tag, (" " + " ".join(attributes)) if attributes else ""
        )
        return "%s%s</%s>" % (opening, inner, tag)

    if budget < 1:
        raise InvalidCell("UI render budget must be positive")
    return render(root_id)


__all__ = [
    "UIProtocol",
    "UIBuilder",
    "bootstrap_ui_protocol",
    "render_ui",
]
