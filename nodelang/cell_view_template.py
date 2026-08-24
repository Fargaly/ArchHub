"""Bounded graph-held templates for safe presentation descriptors.

The interpreter knows only this protocol's role and operation roots. Product
labels, panel names, and template identities never select host behavior. Paths,
conditions, repetition, ordering, keys, text, values, and attributes are all
ordinary Cell relations and may be inspected or rewired before interpretation.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from functools import wraps
from decimal import Decimal, InvalidOperation
import json
import threading
from types import MappingProxyType
from typing import Any, Iterable, Mapping
from weakref import WeakKeyDictionary, ref

from .cell_protocols import CellBatch, read_relation
from .universal_cell import (
    NULL_CELL_ID,
    Cell,
    CellStore,
    InvalidCell,
    MatchBudgetExceeded,
    Snapshot,
)


ROLE_NAMES = (
    "vocabulary-member",
    "operation",
    "argument",
    "item",
    "order",
    "tag",
    "class",
    "key",
    "text",
    "value",
    "attribute",
    "attribute-name",
    "expression",
    "child",
    "repeat",
    "condition",
    "transparent",
)

OPERATION_NAMES = (
    "literal",
    "root",
    "item",
    "index",
    "parent",
    "path",
    "concat",
    "join",
    "replace",
    "equals",
    "member-of",
    "and",
    "or",
    "not",
    "choose",
    "fallback",
    "string",
    "upper",
    "length",
    "count-where",
    "find-where",
    "map",
    "slice",
    "add",
    "json",
    # Generic list operations, so a node that sorts or de-duplicates can
    # SAY so in the graph instead of being answered by a Python branch on
    # its name (SPEC 4.1).
    "unique",
    "flatten",
    "reverse",
    "first",
    "last",
    # A node that sorts, groups, filters or plucks names the FIELD and
    # the direction it works by; without these the graph cannot say what
    # such a node means and a Python branch answers for it (SPEC 4.1).
    "pluck",
    "sort-by",
    "group-by",
    "keep-where",
    "slice",
    "append",
    "value-of",
    "list-of",
)

_MISSING = object()


def _as_text(value: object) -> str:
    """What a parameter says, as text, with absence reading as empty."""
    if value is _MISSING or value is None:
        return ""
    return str(value)


def _truthy(value: object) -> bool:
    """What a template condition treats as true.

    ``bool(_MISSING)`` is True because the sentinel is a plain object, so
    every choose over an absent field took the TRUE branch: each library
    row rendered as selected, and a card whose fallback was the atom
    ``False`` read "ASSEMBLY" forever. Absent and null are false; every
    held value keeps Python's own truth.
    """
    return value is not _MISSING and value is not None and bool(value)


@dataclass(frozen=True, slots=True)
class ViewTemplateProtocol:
    root_id: str
    roles: Mapping[str, str]
    operations: Mapping[str, str]

    def role(self, name: str) -> str:
        try:
            return self.roles[name]
        except KeyError as exc:
            raise InvalidCell("unknown view-template role %r" % name) from exc

    def operation(self, name: str) -> str:
        try:
            return self.operations[name]
        except KeyError as exc:
            raise InvalidCell(
                "unknown view-template operation %r" % name
            ) from exc


def compose_view_template_protocol(
    batch: CellBatch,
    *,
    prefix: str = "view-template-protocol",
) -> ViewTemplateProtocol:
    roles = {
        name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES
    }
    operations = {
        name: "%s:operation:%s" % (prefix, name)
        for name in OPERATION_NAMES
    }
    for name, root_id in (*roles.items(), *operations.items()):
        batch.add(Cell(
            root_id, NULL_CELL_ID, NULL_CELL_ID, name.encode("ascii")
        ))
    root_id = prefix + ":root"
    batch.relation(
        (
            (roles["vocabulary-member"], root)
            for root in (*roles.values(), *operations.values())
        ),
        relation_id=root_id,
    )
    return ViewTemplateProtocol(
        root_id,
        MappingProxyType(roles),
        MappingProxyType(operations),
    )


def open_view_template_protocol(
    snapshot: Snapshot,
    *,
    prefix: str = "view-template-protocol",
) -> ViewTemplateProtocol:
    protocol = ViewTemplateProtocol(
        prefix + ":root",
        MappingProxyType({
            name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES
        }),
        MappingProxyType({
            name: "%s:operation:%s" % (prefix, name)
            for name in OPERATION_NAMES
        }),
    )
    expected = {
        protocol.root_id,
        *protocol.roles.values(),
        *protocol.operations.values(),
    }
    if any(_root not in snapshot.cells for _root in expected):
        raise InvalidCell("view-template protocol is incomplete")
    members = read_relation(snapshot, protocol.root_id, budget=128)
    vocabulary = {
        member.participant_id for member in members
        if member.role_id == protocol.role("vocabulary-member")
    }
    if vocabulary != expected - {protocol.root_id}:
        raise InvalidCell("view-template protocol vocabulary drifted")
    return protocol


class ViewTemplateBuilder:
    """Compose template relations into an existing caller-owned CellBatch."""

    def __init__(
        self,
        batch: CellBatch,
        protocol: ViewTemplateProtocol,
    ) -> None:
        self.batch = batch
        self.protocol = protocol

    def atom(self, root_id: str, value: object) -> str:
        self.batch.add(Cell(
            root_id,
            NULL_CELL_ID,
            NULL_CELL_ID,
            str(value).encode("utf-8"),
        ))
        return root_id

    def _ordered(
        self,
        owner_root: str,
        role_name: str,
        roots: Iterable[str],
    ) -> tuple[str, ...]:
        wrappers = []
        for index, item_root in enumerate(tuple(roots)):
            order_root = "%s:%s:%s:order" % (
                owner_root, role_name, index
            )
            wrapper_root = "%s:%s:%s" % (owner_root, role_name, index)
            self.atom(order_root, index)
            self.batch.relation((
                (self.protocol.role("item"), item_root),
                (self.protocol.role("order"), order_root),
            ), relation_id=wrapper_root)
            wrappers.append(wrapper_root)
        return tuple(wrappers)

    def expression(
        self,
        root_id: str,
        operation: str,
        arguments: Iterable[str] = (),
    ) -> str:
        ordered = self._ordered(root_id, "argument", arguments)
        self.batch.relation((
            (
                self.protocol.role("operation"),
                self.protocol.operation(operation),
            ),
            *((self.protocol.role("argument"), root) for root in ordered),
        ), relation_id=root_id)
        return root_id

    def literal(self, root_id: str, value: object) -> str:
        value_root = self.atom(root_id + ":value", value)
        return self.expression(root_id, "literal", (value_root,))

    def attribute(
        self,
        root_id: str,
        name: str,
        expression_root: str,
    ) -> str:
        name_root = self.atom(root_id + ":name", name)
        self.batch.relation((
            (self.protocol.role("attribute-name"), name_root),
            (self.protocol.role("expression"), expression_root),
        ), relation_id=root_id)
        return root_id

    def template(
        self,
        root_id: str,
        *,
        tag: str | None,
        key: str | None,
        class_name: str | None = None,
        text: str | None = None,
        value: str | None = None,
        attributes: Iterable[str] = (),
        children: Iterable[str] = (),
        repeat: str | None = None,
        condition: str | None = None,
        transparent: str | None = None,
    ) -> str:
        attribute_roots = tuple(attributes)
        child_roots = tuple(children)
        if transparent is None and (tag is None or key is None):
            raise InvalidCell("non-transparent template needs tag and key")
        if transparent is not None and any(
            value is not None
            for value in (tag, key, class_name, text, value)
        ):
            raise InvalidCell(
                "transparent template cannot own descriptor fields"
            )
        if transparent is not None and attribute_roots:
            raise InvalidCell(
                "transparent template cannot own attributes"
            )
        child_wrappers = self._ordered(root_id, "child", child_roots)
        members = [
            *((self.protocol.role("attribute"), root)
              for root in attribute_roots),
            *((self.protocol.role("child"), root)
              for root in child_wrappers),
        ]
        if tag is not None:
            members.append((self.protocol.role("tag"), tag))
        if key is not None:
            members.append((self.protocol.role("key"), key))
        for role_name, expression_root in (
            ("class", class_name),
            ("text", text),
            ("value", value),
            ("repeat", repeat),
            ("condition", condition),
            ("transparent", transparent),
        ):
            if expression_root is not None:
                members.append((
                    self.protocol.role(role_name), expression_root
                ))
        self.batch.relation(members, relation_id=root_id)
        return root_id


def _single(members, role_id: str, label: str, *, optional: bool = False):
    values = tuple(
        member.participant_id for member in members
        if member.role_id == role_id
    )
    if len(values) > 1 or (not optional and not values):
        raise InvalidCell("view template has invalid %s cardinality" % label)
    return values[0] if values else None


def _text(snapshot: Snapshot, root_id: str) -> str:
    cell = snapshot.cells.get(root_id)
    if cell is None:
        raise InvalidCell("view template references a missing Cell")
    if cell.link0 != NULL_CELL_ID or cell.link1 != NULL_CELL_ID:
        raise InvalidCell("view template expected a terminal atom")
    try:
        return cell.atom.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InvalidCell("view template atom is not UTF-8") from exc


def is_view_template(
    snapshot: Snapshot,
    protocol: ViewTemplateProtocol,
    root_id: str,
) -> bool:
    """Recognize a template by its graph shape, never by a product name."""
    cell = snapshot.cells.get(root_id)
    if cell is None or (
        cell.link0 == NULL_CELL_ID and cell.link1 == NULL_CELL_ID
    ):
        return False
    try:
        members = read_relation(snapshot, root_id, budget=256)
    except (InvalidCell, MatchBudgetExceeded):
        return False
    tag_count = sum(
        member.role_id == protocol.role("tag") for member in members
    )
    key_count = sum(
        member.role_id == protocol.role("key") for member in members
    )
    transparent_count = sum(
        member.role_id == protocol.role("transparent")
        for member in members
    )
    return (
        tag_count == 1 and key_count == 1 and transparent_count == 0
    ) or (
        tag_count == 0 and key_count == 0 and transparent_count == 1
    )


class _Budget:
    def __init__(self, limit: int) -> None:
        if limit < 1:
            raise MatchBudgetExceeded("view-template budget must be positive")
        self.remaining = limit

    def spend(self, amount: int = 1) -> None:
        self.remaining -= amount
        if self.remaining < 0:
            raise MatchBudgetExceeded("view-template budget exceeded")


@dataclass(frozen=True, slots=True)
class _TemplatePlan:
    repeat_root: str | None
    condition_root: str | None
    transparent_root: str | None
    child_roots: tuple[str, ...]
    tag_root: str | None
    key_root: str | None
    class_root: str | None
    text_root: str | None
    value_root: str | None
    attributes: tuple[tuple[str, str], ...]


@dataclass
class _TemplatePlanCache:
    expression_plans: dict[str, tuple[str, tuple[str, ...]]]
    template_plans: dict[str, _TemplatePlan]
    text: dict[str, str]
    dependencies: set[str]


_VIEW_TEMPLATE_PLAN_CACHE: ContextVar[_TemplatePlanCache | None] = ContextVar(
    "view_template_plan_cache", default=None
)
_STABLE_VIEW_TEMPLATE_PLAN_CACHES: WeakKeyDictionary[
    CellStore, _TemplatePlanCache
] = WeakKeyDictionary()
_STABLE_VIEW_TEMPLATE_PLAN_CACHE_LOCK = threading.RLock()


def _new_template_plan_cache() -> _TemplatePlanCache:
    return _TemplatePlanCache({}, {}, {}, set())


def _stable_template_plan_cache(store: CellStore) -> _TemplatePlanCache:
    with _STABLE_VIEW_TEMPLATE_PLAN_CACHE_LOCK:
        cached = _STABLE_VIEW_TEMPLATE_PLAN_CACHES.get(store)
        if cached is not None:
            return cached
        cached = _new_template_plan_cache()
        _STABLE_VIEW_TEMPLATE_PLAN_CACHES[store] = cached
        cache_ref = ref(cached)

        def invalidate(event) -> None:
            active = cache_ref()
            if active is None or not event.touched.intersection(
                active.dependencies
            ):
                return
            with _STABLE_VIEW_TEMPLATE_PLAN_CACHE_LOCK:
                active.expression_plans.clear()
                active.template_plans.clear()
                active.text.clear()
                active.dependencies.clear()

        store.subscribe(invalidate)
        return cached


@contextmanager
def view_template_projection_scope(store: CellStore | None = None):
    """Reuse exact graph template plans only inside one projection request."""
    existing = _VIEW_TEMPLATE_PLAN_CACHE.get()
    if existing is not None:
        yield
        return
    cache = (
        _stable_template_plan_cache(store)
        if store is not None else _new_template_plan_cache()
    )
    token = _VIEW_TEMPLATE_PLAN_CACHE.set(cache)
    try:
        yield
    finally:
        _VIEW_TEMPLATE_PLAN_CACHE.reset(token)


def with_view_template_projection_scope(function):
    """Run one projector with a revision-bound template-plan cache."""
    @wraps(function)
    def wrapped(*args, **kwargs):
        store = args[0] if args and isinstance(args[0], CellStore) else None
        with view_template_projection_scope(store):
            return function(*args, **kwargs)
    return wrapped


def _ordered_roots(
    snapshot: Snapshot,
    protocol: ViewTemplateProtocol,
    members,
    role_name: str,
    budget: _Budget,
    dependencies: set[str],
) -> tuple[str, ...]:
    indexed = []
    for member in members:
        if member.role_id != protocol.role(role_name):
            continue
        budget.spend()
        wrapper = read_relation(
            snapshot, member.participant_id, budget=max(1, budget.remaining)
        )
        dependencies.add(member.participant_id)
        dependencies.update(item.incidence_id for item in wrapper)
        item_root = _single(
            wrapper, protocol.role("item"), "ordered item"
        )
        order_root = _single(
            wrapper, protocol.role("order"), "ordered index"
        )
        dependencies.update((item_root, order_root))
        try:
            order = int(_text(snapshot, order_root))
        except ValueError as exc:
            raise InvalidCell("view-template order is not an integer") from exc
        indexed.append((order, item_root))
    indexed.sort()
    if [order for order, _root in indexed] != list(range(len(indexed))):
        raise InvalidCell("view-template order is not contiguous and unique")
    return tuple(root for _order, root in indexed)


def _track_relation_dependencies(
    snapshot: Snapshot,
    root_id: str,
    members,
    dependencies: set[str],
) -> None:
    """Record every physical Cell read while compiling one relation plan."""
    dependencies.add(root_id)
    cursor = root_id
    for member in members:
        chain = snapshot.cells[cursor]
        dependencies.update((cursor, chain.link0, member.incidence_id))
        cursor = chain.link1


def evaluate_view_expression(
    snapshot: Snapshot,
    protocol: ViewTemplateProtocol,
    expression_root: str,
    projection: Mapping[str, Any],
    *,
    budget: int = 250_000,
    repeat_limit: int = 2_000,
) -> object:
    """The VALUE one released graph expression denotes over a projection.

    The same interpreter a template renders with, asked for the value
    instead of a descriptor. A node computes what its released definition
    SAYS it computes -- SPEC 4.1 -- rather than what a Python branch on
    its engine name decides.
    """
    return render_view_template(
        snapshot,
        protocol,
        expression_root,
        projection,
        budget=budget,
        repeat_limit=repeat_limit,
        value_only=True,
    )


def render_view_template(
    snapshot: Snapshot,
    protocol: ViewTemplateProtocol,
    template_root: str,
    projection: Mapping[str, Any],
    *,
    budget: int = 250_000,
    repeat_limit: int = 2_000,
    value_only: bool = False,
) -> list[dict[str, object]]:
    """Interpret one released graph template into safe disposable descriptors."""
    from .inspector_descriptor import descriptor

    work = _Budget(budget)
    active_templates: set[str] = set()
    plan_cache = _VIEW_TEMPLATE_PLAN_CACHE.get() or _new_template_plan_cache()
    expression_plans = plan_cache.expression_plans
    template_plans = plan_cache.template_plans
    text_cache = plan_cache.text
    dependencies = plan_cache.dependencies
    dependencies.add(protocol.root_id)
    dependencies.update(protocol.roles.values())
    dependencies.update(protocol.operations.values())
    expression_cache: dict[
        tuple[str, int, int | None, tuple[tuple[int, int | None], ...]],
        object,
    ] = {}

    def atom_text(root_id: str) -> str:
        cached = text_cache.get(root_id)
        if cached is not None:
            return cached
        value = _text(snapshot, root_id)
        dependencies.add(root_id)
        text_cache[root_id] = value
        return value

    def expression(
        root_id: str,
        item: object,
        index: int | None,
        active: set[str],
        parents: tuple[tuple[object, int | None], ...] = (),
    ):
        cache_key = (
            root_id,
            id(item),
            index,
            tuple((id(parent_item), parent_index)
                  for parent_item, parent_index in parents),
        )
        if cache_key in expression_cache:
            return expression_cache[cache_key]
        work.spend()
        if root_id in active:
            raise InvalidCell("view-template expression contains a cycle")
        active.add(root_id)
        plan = expression_plans.get(root_id)
        if plan is None:
            members = read_relation(
                snapshot, root_id, budget=max(1, work.remaining)
            )
            _track_relation_dependencies(
                snapshot, root_id, members, dependencies
            )
            operation = _single(
                members, protocol.role("operation"), "expression operation"
            )
            arguments = _ordered_roots(
                snapshot,
                protocol,
                members,
                "argument",
                work,
                dependencies,
            )
            expression_plans[root_id] = (operation, arguments)
        else:
            operation, arguments = plan
            work.spend(len(arguments))

        def evaluate(argument_root: str):
            return expression(
                argument_root, item, index, active, parents
            )

        if operation == protocol.operation("literal"):
            if len(arguments) != 1:
                raise InvalidCell("literal expression needs one value")
            result = atom_text(arguments[0])
        elif operation == protocol.operation("root"):
            if arguments:
                raise InvalidCell("root expression takes no arguments")
            result = projection
        elif operation == protocol.operation("item"):
            if arguments:
                raise InvalidCell("item expression takes no arguments")
            result = item
        elif operation == protocol.operation("index"):
            if arguments:
                raise InvalidCell("index expression takes no arguments")
            result = index
        elif operation == protocol.operation("parent"):
            if arguments:
                raise InvalidCell("parent expression takes no arguments")
            result = parents[0][0] if parents else _MISSING
        elif operation == protocol.operation("path"):
            if not arguments:
                raise InvalidCell("path expression has no base")
            result = evaluate(arguments[0])
            for segment_root in arguments[1:]:
                segment = atom_text(segment_root)
                if isinstance(result, Mapping):
                    result = result.get(segment, _MISSING)
                elif isinstance(result, (list, tuple)) and segment.isdigit():
                    offset = int(segment)
                    result = (
                        result[offset] if 0 <= offset < len(result)
                        else _MISSING
                    )
                else:
                    result = _MISSING
                if result is _MISSING:
                    break
        elif operation == protocol.operation("concat"):
            result = "".join(
                "" if (value := evaluate(root)) is _MISSING
                else str(value)
                for root in arguments
            )
        elif operation == protocol.operation("join"):
            if len(arguments) != 2:
                raise InvalidCell(
                    "join expression needs a collection and separator"
                )
            collection = evaluate(arguments[0])
            separator = str(evaluate(arguments[1]))
            if collection is _MISSING or collection is None:
                values = ()
            elif isinstance(collection, Mapping):
                values = tuple(collection.values())
            elif isinstance(collection, (list, tuple)):
                values = tuple(collection)
            else:
                raise InvalidCell(
                    "join collection is not a bounded iterable"
                )
            if len(values) > repeat_limit:
                raise MatchBudgetExceeded(
                    "join collection exceeds repeat limit"
                )
            result = separator.join(str(value) for value in values)
            if len(result.encode("utf-8")) > 65_536:
                raise MatchBudgetExceeded(
                    "join expression output exceeds 65536 bytes"
                )
        elif operation == protocol.operation("replace"):
            if len(arguments) != 3:
                raise InvalidCell("replace expression needs three arguments")
            source, old, new = (evaluate(root) for root in arguments)
            result = str(source).replace(str(old), str(new))
        elif operation == protocol.operation("equals"):
            if len(arguments) != 2:
                raise InvalidCell("equals expression needs two arguments")
            result = evaluate(arguments[0]) == evaluate(arguments[1])
        elif operation == protocol.operation("member-of"):
            if len(arguments) < 2:
                raise InvalidCell("member-of needs a value and candidates")
            result = evaluate(arguments[0]) in tuple(
                evaluate(root) for root in arguments[1:]
            )
        elif operation in (
            protocol.operation("and"), protocol.operation("or")
        ):
            values = tuple(_truthy(evaluate(root)) for root in arguments)
            result = (
                all(values) if operation == protocol.operation("and")
                else any(values)
            )
        elif operation == protocol.operation("not"):
            if len(arguments) != 1:
                raise InvalidCell("not expression needs one argument")
            result = not _truthy(evaluate(arguments[0]))
        elif operation == protocol.operation("choose"):
            if len(arguments) != 3:
                raise InvalidCell("choose expression needs three arguments")
            result = evaluate(
                arguments[1] if _truthy(evaluate(arguments[0]))
                else arguments[2]
            )
        elif operation == protocol.operation("fallback"):
            result = _MISSING
            for root in arguments:
                candidate = evaluate(root)
                if (
                    candidate is not _MISSING
                    and candidate is not None
                    and candidate != ""
                ):
                    result = candidate
                    break
        elif operation == protocol.operation("string"):
            if len(arguments) != 1:
                raise InvalidCell("string expression needs one argument")
            value = evaluate(arguments[0])
            result = "" if value is _MISSING else str(value)
        elif operation == protocol.operation("upper"):
            if len(arguments) != 1:
                raise InvalidCell("upper expression needs one argument")
            result = str(evaluate(arguments[0])).upper()
        elif operation == protocol.operation("list-of"):
            # A list nobody filled is the empty LIST; emptiness has a type.
            held_list = evaluate(arguments[0]) if arguments else _MISSING
            result = (
                list(held_list) if isinstance(held_list, (list, tuple)) else []
            )
        elif operation == protocol.operation("value-of"):
            # A setting nobody set reads as empty, not as absence: a constant
            # with no value is the empty value, which is what every reader of
            # it already assumes.
            held_value = evaluate(arguments[0]) if arguments else _MISSING
            result = "" if held_value is _MISSING else held_value
        elif operation == protocol.operation("pluck"):
            values = evaluate(arguments[0]) if arguments else ()
            field = _as_text(evaluate(arguments[1])) if len(arguments) > 1 else ""
            result = [
                item.get(field) if isinstance(item, Mapping) else _MISSING
                for item in (values if isinstance(values, (list, tuple)) else ())
            ]
        elif operation == protocol.operation("sort-by"):
            values = list(evaluate(arguments[0]) or ()) if arguments else []
            field = _as_text(evaluate(arguments[1])) if len(arguments) > 1 else ""
            descending = (
                _as_text(evaluate(arguments[2])).strip().lower() == "desc"
                if len(arguments) > 2 else False
            )

            def _key(item):
                held = (
                    item.get(field) if isinstance(item, Mapping) and field
                    else item
                )
                return (held is None, str(held))

            result = sorted(values, key=_key, reverse=descending)
        elif operation == protocol.operation("group-by"):
            values = evaluate(arguments[0]) if arguments else ()
            field = _as_text(evaluate(arguments[1])) if len(arguments) > 1 else ""
            groups: dict[str, list] = {}
            for item in (values if isinstance(values, (list, tuple)) else ()):
                held = (
                    item.get(field) if isinstance(item, Mapping) and field
                    else item
                )
                groups.setdefault(str(held), []).append(item)
            result = [
                {"key": key, "items": items}
                for key, items in sorted(groups.items())
            ]
        elif operation == protocol.operation("keep-where"):
            values = evaluate(arguments[0]) if arguments else ()
            field = _as_text(evaluate(arguments[1])) if len(arguments) > 1 else ""
            wanted = _as_text(evaluate(arguments[2])) if len(arguments) > 2 else ""
            result = [
                item for item in (
                    values if isinstance(values, (list, tuple)) else ()
                )
                if str(
                    item.get(field) if isinstance(item, Mapping) and field
                    else item
                ) == wanted
            ]
        elif operation == protocol.operation("slice"):
            values = list(evaluate(arguments[0]) or ()) if arguments else []
            count = _as_text(evaluate(arguments[1])) if len(arguments) > 1 else "10"
            take = int(count) if count.strip().lstrip("-").isdigit() else 10
            from_end = (
                _as_text(evaluate(arguments[2])).strip().lower() == "end"
                if len(arguments) > 2 else False
            )
            result = values[-take:] if from_end else values[:take]
        elif operation == protocol.operation("append"):
            left = list(evaluate(arguments[0]) or ()) if arguments else []
            right = (
                list(evaluate(arguments[1]) or ()) if len(arguments) > 1 else []
            )
            result = left + right
        elif operation == protocol.operation("unique"):
            values = evaluate(arguments[0]) if arguments else ()
            seen = []
            for value in (values if isinstance(values, (list, tuple)) else ()):
                if value not in seen:
                    seen.append(value)
            result = seen
        elif operation == protocol.operation("flatten"):
            values = evaluate(arguments[0]) if arguments else ()
            flat = []
            for value in (values if isinstance(values, (list, tuple)) else ()):
                if isinstance(value, (list, tuple)):
                    flat.extend(value)
                else:
                    flat.append(value)
            result = flat
        elif operation == protocol.operation("reverse"):
            values = evaluate(arguments[0]) if arguments else ()
            result = list(reversed(list(values))) if isinstance(
                values, (list, tuple)
            ) else []
        elif operation == protocol.operation("first"):
            values = evaluate(arguments[0]) if arguments else ()
            result = (
                values[0] if isinstance(values, (list, tuple)) and values
                else _MISSING
            )
        elif operation == protocol.operation("last"):
            values = evaluate(arguments[0]) if arguments else ()
            result = (
                values[-1] if isinstance(values, (list, tuple)) and values
                else _MISSING
            )
        elif operation == protocol.operation("length"):
            if len(arguments) != 1:
                raise InvalidCell("length expression needs one argument")
            value = evaluate(arguments[0])
            result = 0 if value is _MISSING else len(value)
        elif operation == protocol.operation("count-where"):
            if len(arguments) != 2:
                raise InvalidCell(
                    "count-where expression needs a collection and predicate"
                )
            collection = evaluate(arguments[0])
            if collection is _MISSING or collection is None:
                result = 0
            elif isinstance(collection, Mapping):
                if len(collection) > repeat_limit:
                    raise MatchBudgetExceeded(
                        "count-where collection exceeds repeat limit"
                    )
                result = sum(
                    bool(expression(
                        arguments[1],
                        {"key": key, "value": value},
                        offset,
                        set(active),
                        ((item, index), *parents),
                    ))
                    for offset, (key, value) in enumerate(collection.items())
                )
            elif isinstance(collection, (list, tuple)):
                if len(collection) > repeat_limit:
                    raise MatchBudgetExceeded(
                        "count-where collection exceeds repeat limit"
                    )
                result = sum(
                    bool(expression(
                        arguments[1],
                        value,
                        offset,
                        set(active),
                        ((item, index), *parents),
                    ))
                    for offset, value in enumerate(collection)
                )
            else:
                raise InvalidCell(
                    "count-where collection is not a bounded iterable"
                )
        elif operation == protocol.operation("find-where"):
            if len(arguments) != 2:
                raise InvalidCell(
                    "find-where expression needs a collection and predicate"
                )
            collection = evaluate(arguments[0])
            if collection is _MISSING or collection is None:
                result = _MISSING
            elif isinstance(collection, Mapping):
                if len(collection) > repeat_limit:
                    raise MatchBudgetExceeded(
                        "find-where collection exceeds repeat limit"
                    )
                result = _MISSING
                for offset, (key, value) in enumerate(collection.items()):
                    candidate = {"key": key, "value": value}
                    if bool(expression(
                        arguments[1],
                        candidate,
                        offset,
                        set(active),
                        ((item, index), *parents),
                    )):
                        result = candidate
                        break
            elif isinstance(collection, (list, tuple)):
                if len(collection) > repeat_limit:
                    raise MatchBudgetExceeded(
                        "find-where collection exceeds repeat limit"
                    )
                result = _MISSING
                for offset, candidate in enumerate(collection):
                    if bool(expression(
                        arguments[1],
                        candidate,
                        offset,
                        set(active),
                        ((item, index), *parents),
                    )):
                        result = candidate
                        break
            else:
                raise InvalidCell(
                    "find-where collection is not a bounded iterable"
                )
        elif operation == protocol.operation("map"):
            if len(arguments) != 2:
                raise InvalidCell(
                    "map expression needs a collection and mapper"
                )
            collection = evaluate(arguments[0])
            if collection is _MISSING or collection is None:
                result = []
            elif isinstance(collection, Mapping):
                if len(collection) > repeat_limit:
                    raise MatchBudgetExceeded(
                        "map collection exceeds repeat limit"
                    )
                result = [
                    expression(
                        arguments[1],
                        {"key": key, "value": value},
                        offset,
                        set(active),
                        ((item, index), *parents),
                    )
                    for offset, (key, value) in enumerate(collection.items())
                ]
            elif isinstance(collection, (list, tuple)):
                if len(collection) > repeat_limit:
                    raise MatchBudgetExceeded(
                        "map collection exceeds repeat limit"
                    )
                result = [
                    expression(
                        arguments[1],
                        candidate,
                        offset,
                        set(active),
                        ((item, index), *parents),
                    )
                    for offset, candidate in enumerate(collection)
                ]
            else:
                raise InvalidCell(
                    "map collection is not a bounded iterable"
                )
        elif operation == protocol.operation("slice"):
            if len(arguments) != 3:
                raise InvalidCell(
                    "slice expression needs a value, start, and stop"
                )
            value = evaluate(arguments[0])
            try:
                start = int(evaluate(arguments[1]))
                stop = int(evaluate(arguments[2]))
            except (TypeError, ValueError) as exc:
                raise InvalidCell("slice bounds are not integers") from exc
            if value is _MISSING or value is None:
                result = ""
            elif isinstance(value, (str, bytes, list, tuple)):
                result = value[start:stop]
            else:
                raise InvalidCell("slice value is not sliceable")
        elif operation == protocol.operation("add"):
            if not arguments:
                raise InvalidCell("add expression needs at least one argument")
            numbers = []
            for root in arguments:
                value = evaluate(root)
                if isinstance(value, bool) or value is _MISSING:
                    raise InvalidCell("add argument is not numeric")
                try:
                    number = Decimal(str(value))
                except (InvalidOperation, ValueError) as exc:
                    raise InvalidCell("add argument is not numeric") from exc
                if not number.is_finite():
                    raise InvalidCell("add argument is not finite")
                numbers.append(number)
            total = sum(numbers, Decimal(0))
            result = (
                int(total)
                if total == total.to_integral_value()
                else float(total)
            )
        elif operation == protocol.operation("json"):
            if len(arguments) != 1:
                raise InvalidCell("json expression needs one argument")
            value = evaluate(arguments[0])
            if value is _MISSING:
                value = None
            try:
                result = json.dumps(
                    value,
                    ensure_ascii=True,
                    allow_nan=False,
                    sort_keys=True,
                )
            except (TypeError, ValueError) as exc:
                raise InvalidCell(
                    "json expression value is not serializable"
                ) from exc
            if len(result.encode("utf-8")) > 65_536:
                raise MatchBudgetExceeded(
                    "json expression output exceeds 65536 bytes"
                )
        else:
            raise InvalidCell("view-template expression operation is unknown")
        active.remove(root_id)
        expression_cache[cache_key] = result
        return result

    def template_plan(root_id: str) -> _TemplatePlan:
        cached = template_plans.get(root_id)
        if cached is not None:
            work.spend(len(cached.child_roots))
            return cached
        members = read_relation(
            snapshot, root_id, budget=max(1, work.remaining)
        )
        _track_relation_dependencies(snapshot, root_id, members, dependencies)
        repeat_root = _single(
            members, protocol.role("repeat"), "repeat", optional=True
        )
        condition_root = _single(
            members, protocol.role("condition"), "condition", optional=True
        )
        transparent_root = _single(
            members,
            protocol.role("transparent"),
            "transparent",
            optional=True,
        )
        child_roots = _ordered_roots(
            snapshot,
            protocol,
            members,
            "child",
            work,
            dependencies,
        )
        attributes = []
        for member in members:
            if member.role_id != protocol.role("attribute"):
                continue
            attribute_members = read_relation(
                snapshot,
                member.participant_id,
                budget=max(1, work.remaining),
            )
            _track_relation_dependencies(
                snapshot,
                member.participant_id,
                attribute_members,
                dependencies,
            )
            name_root = _single(
                attribute_members,
                protocol.role("attribute-name"),
                "attribute name",
            )
            expression_root = _single(
                attribute_members,
                protocol.role("expression"),
                "attribute expression",
            )
            attributes.append((atom_text(name_root), expression_root))
        field_roots = {
            name: _single(
                members,
                protocol.role(name),
                name,
                optional=True,
            )
            for name in ("tag", "key", "class", "text", "value")
        }
        if transparent_root is not None:
            if any(field_roots.values()) or attributes:
                raise InvalidCell(
                    "transparent template owns descriptor fields"
                )
        elif field_roots["tag"] is None or field_roots["key"] is None:
            raise InvalidCell("view template requires tag and key")
        plan = _TemplatePlan(
            repeat_root,
            condition_root,
            transparent_root,
            child_roots,
            field_roots["tag"],
            field_roots["key"],
            field_roots["class"],
            field_roots["text"],
            field_roots["value"],
            tuple(attributes),
        )
        template_plans[root_id] = plan
        return plan

    def render(
        root_id: str,
        item: object = _MISSING,
        index: int | None = None,
        parents: tuple[tuple[object, int | None], ...] = (),
    ) -> list[dict[str, object]]:
        work.spend()
        if root_id in active_templates:
            raise InvalidCell("view-template child graph contains a cycle")
        active_templates.add(root_id)
        plan = template_plan(root_id)

        contexts: list[
            tuple[
                object,
                int | None,
                tuple[tuple[object, int | None], ...],
            ]
        ]
        if plan.repeat_root is None:
            contexts = [(item, index, parents)]
        else:
            repeated = expression(
                plan.repeat_root, item, index, set(), parents
            )
            nested_parents = (
                ((item, index), *parents)
                if item is not _MISSING
                else parents
            )
            if repeated is _MISSING or repeated is None:
                contexts = []
            elif isinstance(repeated, Mapping):
                contexts = [
                    (
                        {"key": key, "value": value},
                        offset,
                        nested_parents,
                    )
                    for offset, (key, value) in enumerate(repeated.items())
                ]
            elif isinstance(repeated, (list, tuple)):
                contexts = [
                    (value, offset, nested_parents)
                    for offset, value in enumerate(repeated)
                ]
            else:
                raise InvalidCell("view-template repeat source is not iterable")
            if len(contexts) > repeat_limit:
                raise MatchBudgetExceeded("view-template repeat limit exceeded")

        projected = []
        for current_item, current_index, current_parents in contexts:
            if plan.condition_root is not None and not bool(expression(
                plan.condition_root,
                current_item,
                current_index,
                set(),
                current_parents,
            )):
                continue

            def optional_expression(role_name: str):
                expression_root = getattr(plan, role_name + "_root")
                if expression_root is None:
                    return _MISSING
                return expression(
                    expression_root,
                    current_item,
                    current_index,
                    set(),
                    current_parents,
                )

            class_name = optional_expression("class")
            text = optional_expression("text")
            value = optional_expression("value")
            attributes: dict[str, object] = {}
            for attribute_name, expression_root in plan.attributes:
                attribute_value = expression(
                    expression_root,
                    current_item,
                    current_index,
                    set(),
                    current_parents,
                )
                if attribute_value is not _MISSING and attribute_value is not None:
                    attributes[attribute_name] = attribute_value
            children = []
            for child_root in plan.child_roots:
                children.extend(render(
                    child_root,
                    current_item,
                    current_index,
                    current_parents,
                ))
            if plan.transparent_root is not None:
                projected.extend(children)
                continue
            tag = expression(
                plan.tag_root,
                current_item,
                current_index,
                set(),
                current_parents,
            )
            key = expression(
                plan.key_root,
                current_item,
                current_index,
                set(),
                current_parents,
            )
            projected.append(descriptor(
                str(key),
                str(tag),
                class_name=(
                    "" if class_name is _MISSING else str(class_name)
                ),
                text=None if text is _MISSING else text,
                value=None if value is _MISSING else value,
                attributes=attributes,
                children=children,
            ))
        active_templates.remove(root_id)
        return projected

    if value_only:
        return expression(template_root, None, None, set())
    return render(template_root)


__all__ = [
    "OPERATION_NAMES",
    "ROLE_NAMES",
    "ViewTemplateBuilder",
    "ViewTemplateProtocol",
    "compose_view_template_protocol",
    "is_view_template",
    "open_view_template_protocol",
    "evaluate_view_expression",
    "render_view_template",
    "view_template_projection_scope",
    "with_view_template_projection_scope",
]
