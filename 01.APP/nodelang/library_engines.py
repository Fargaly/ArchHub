"""Engines for the node library cards that had none.

The library offered fifty-three cards and only twenty-two carried an
engine. Dropping any of the other thirty-one put a card in local React
state alone: Run never saw it, the graph never held it, and a reload threw
it away. A library that offers what it cannot run is a library that lies,
so the gap is closed here, from the engine side.

Every engine has the shape the pipeline already speaks: it takes
(parameters, feeds) and answers (outputs, display). A wire delivers into
the feed named "in" and is read from the output named "out"
(universal_pipeline binds exactly those two), so that is what these use.

Two laws hold across all of them.

Nothing is invented. An engine with no wired input answers empty and says
so on its card; it never manufactures rows to look busy. An engine that
changes only the stream says "stream only" on its card, because a founder
who reads "moved 40 walls" has the right to know whether Revit moved.

One meaning per operation. Where the stem evaluator already decides what
"where", "sort by", "group by", "if", "switch" and "loop" mean, these call
into it rather than keeping a second copy that will drift.
"""
from __future__ import annotations

from typing import Mapping
import json
import math

from .stem_graph_evaluation import (
    as_list,
    coerce_parameter,
    item_field,
    run_stem_operation,
)

_OPERATORS = (">=", "<=", "!=", "==", ">", "<")

_EMPTY_LIST = "nothing is wired in"

ENGINE_INTERFACE_ALIASES = {
    "shape.sort": {
        "source": {"out": "items_out"},
        "target": {"in": "items"},
    },
    "revit.elements_of_category": {
        "source": {"els": "elements"},
    },
    "revit.get_parameter": {
        "target": {"els": "elements", "name": "parameter"},
        "param": {"name": "parameter"},
    },
    "revit.set_parameter_by_name": {
        "target": {"els": "elements", "name": "parameter"},
        "param": {"name": "parameter"},
    },
    "revit.renumber_rename": {
        "source": {"els": "elements"},
        "target": {
            "els": "elements",
            "number_pattern": "number_format",
            "name_pattern": "name_format",
        },
        "param": {
            "number_pattern": "number_format",
            "name_pattern": "name_format",
        },
    },
}


def canonical_engine_interface(engine: object, side: str, name: object) -> object:
    """Map saved old interface names onto the current engine contract."""
    held = ENGINE_INTERFACE_ALIASES.get(str(engine or "").strip()) or {}
    aliases = held.get(side) or {}
    return aliases.get(name, name)


def canonical_engine_parameters(engine: object, params: Mapping[str, object]) -> dict:
    held = dict(params or {})
    aliases = (ENGINE_INTERFACE_ALIASES.get(str(engine or "").strip()) or {}).get("param") or {}
    for old, new in aliases.items():
        if old in held and new not in held:
            held[new] = held[old]
    return held


def _wired(feeds: Mapping[str, object], *names: str) -> object:
    """The first wired feed among the names the graph might have used."""
    for name in names or ("in",):
        if name in feeds and feeds[name] is not None:
            return feeds[name]
    return None


def _rows(feeds: Mapping[str, object]) -> list:
    """The wired stream as a list, or an empty list when nothing is wired."""
    held = _wired(feeds, "in", "items", "value")
    return [] if held is None else as_list(held)


def _text(params: Mapping[str, object], name: str, fallback: str = "") -> str:
    value = params.get(name)
    return fallback if value is None else str(value).strip()


def _number(params: Mapping[str, object], name: str, fallback: float) -> float:
    value = coerce_parameter(params.get(name))
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return fallback
    return float(value)


def _plain(text: str, label: str) -> str:
    """A field or value that cannot smuggle a comparison into a rule."""
    for operator in _OPERATORS:
        if operator in text:
            raise ValueError(
                "%s may not contain %r; use where parameter instead"
                % (label, operator)
            )
    return text


def _filter_by_rule(rows: list, rule: str, mode: str) -> tuple:
    produced, _shown = run_stem_operation(
        "shape.filter", {"predicate": rule, "mode": mode}, {"items": rows}
    )
    kept = produced["items_out"]
    return kept, "%d of %d rows - %s" % (len(kept), len(rows), rule)


# ------------------------------------------------------------- filter --

def filter_field(params: Mapping[str, object], feeds: Mapping[str, object]):
    """where type / where category / where level: rows whose field matches."""
    rows = _rows(feeds)
    field = _plain(_text(params, "field"), "field")
    wanted = _plain(_text(params, "value"), "value")
    if not field:
        raise ValueError("set the field parameter to the field to match on")
    if not rows:
        return {"out": []}, _EMPTY_LIST
    if not wanted:
        # No value yet is not a filter that keeps nothing: it is a filter
        # nobody has finished writing, and the card must say which.
        return {"out": list(rows)}, "%d rows - no %s value set yet" % (
            len(rows), field)
    mode = _text(params, "mode", "keep") or "keep"
    kept, shown = _filter_by_rule(rows, "item.%s == %s" % (field, wanted), mode)
    return {"out": kept}, shown


def filter_compare(params: Mapping[str, object], feeds: Mapping[str, object]):
    """where parameter: a declared comparison on one field."""
    rows = _rows(feeds)
    field = _plain(_text(params, "field"), "field")
    operator = _text(params, "operator", "==") or "=="
    wanted = _plain(_text(params, "value"), "value")
    if operator not in _OPERATORS:
        raise ValueError("operator must be one of %s" % ", ".join(_OPERATORS))
    if not field:
        raise ValueError("set the field parameter to the parameter to test")
    if not rows:
        return {"out": []}, _EMPTY_LIST
    mode = _text(params, "mode", "keep") or "keep"
    kept, shown = _filter_by_rule(
        rows, "item.%s %s %s" % (field, operator, wanted), mode
    )
    return {"out": kept}, shown


def filter_rule(params: Mapping[str, object], feeds: Mapping[str, object]):
    """where custom: the rule text the founder wrote, evaluated as declared.

    The card once promised an arbitrary JS predicate. This version does not
    run founder text as code, so a rule outside the declared comparisons is
    refused by name instead of being half-honoured.
    """
    rows = _rows(feeds)
    rule = _text(params, "rule") or _text(params, "predicate")
    if not rule:
        raise ValueError(
            "set the rule parameter, for example: item.height > 3000")
    if not rows:
        return {"out": []}, _EMPTY_LIST
    mode = _text(params, "mode", "keep") or "keep"
    kept, shown = _filter_by_rule(rows, rule, mode)
    return {"out": kept}, shown


def rule_check(params: Mapping[str, object], feeds: Mapping[str, object]):
    rows = _rows(feeds)
    if not rows:
        return {"out": []}, _EMPTY_LIST
    rule = _text(params, "rule") or _text(params, "predicate")
    if not rule:
        field = _plain(_text(params, "parameter") or _text(params, "field"), "parameter")
        operator = _text(params, "operator", "==") or "=="
        wanted = _plain(_text(params, "value"), "value")
        if operator not in _OPERATORS:
            raise ValueError("operator must be one of %s" % ", ".join(_OPERATORS))
        if not field:
            raise ValueError("set parameter, operator, and value")
        rule = "item.%s %s %s" % (field, operator, wanted)
    passed, _ = _filter_by_rule(rows, rule, "keep")
    failed, _ = _filter_by_rule(rows, rule, "drop")
    report = {
        "rule": rule,
        "passed": len(passed),
        "failed": len(failed),
        "total": len(rows),
    }
    return {"pass": passed, "fail": failed, "report": report, "out": report}, (
        "%d pass, %d fail" % (len(passed), len(failed)))


# ---------------------------------------------------------- transform --

def set_field(params: Mapping[str, object], feeds: Mapping[str, object]):
    """set parameter: write a value onto every row flowing through.

    This changes the stream, not the host. A downstream host engine is what
    puts a value into Revit, and the card says so rather than letting the
    founder read "set 40 walls" and believe the model changed.
    """
    rows = _rows(feeds)
    field = _text(params, "field") or _text(params, "name")
    if not field:
        raise ValueError("set the field parameter to the parameter to write")
    if not rows:
        return {"out": []}, _EMPTY_LIST
    value = coerce_parameter(params.get("value"))
    written = []
    for row in rows:
        if isinstance(row, Mapping):
            held = dict(row)
            held[field] = value
            written.append(held)
        else:
            written.append({"value": row, field: value})
    return {"out": written}, "%s set on %d rows - stream only" % (
        field, len(written))


def _coordinates(row: object):
    """The numbers this row carries as geometry, or None when it carries none.

    Two carried shapes reach here: a line as [x1, y1, x2, y2] in millimetres,
    and a point-bearing row with x / y (and optionally z).
    """
    if isinstance(row, (list, tuple)):
        numbers = [n for n in row if isinstance(n, (int, float))
                   and not isinstance(n, bool)]
        if len(numbers) >= 2 and len(numbers) == len(row):
            return [float(n) for n in row]
        return None
    if isinstance(row, Mapping):
        held = [row.get(axis) for axis in ("x", "y", "z")]
        present = [n for n in held if isinstance(n, (int, float))
                   and not isinstance(n, bool)]
        return [float(n) for n in present] if len(present) >= 2 else None
    return None


def _points_of(numbers: list) -> list:
    """Coordinates split into points: pairs for a line, one point otherwise."""
    if len(numbers) >= 4 and len(numbers) % 2 == 0:
        return [numbers[index:index + 2] for index in range(0, len(numbers), 2)]
    return [list(numbers)]


def _rewrite(row: object, points: list) -> object:
    """The row again, carrying the moved points in the shape it arrived in."""
    if isinstance(row, (list, tuple)):
        flat = [value for point in points for value in point]
        return list(flat[:len(row)])
    held = dict(row)
    axes = [axis for axis in ("x", "y", "z")
            if isinstance(row.get(axis), (int, float))
            and not isinstance(row.get(axis), bool)]
    point = points[0]
    for index, axis in enumerate(axes):
        if index < len(point):
            held[axis] = point[index]
    return held


def _mapped(rows: list, move_point) -> tuple:
    """Every row with its geometry moved; rows carrying none pass untouched."""
    out, touched = [], 0
    for row in rows:
        numbers = _coordinates(row)
        if numbers is None:
            out.append(row)
            continue
        moved = [move_point(point) for point in _points_of(numbers)]
        out.append(_rewrite(row, moved))
        touched += 1
    return out, touched


def _geometry_display(verb: str, touched: int, total: int) -> str:
    missed = total - touched
    tail = " - %d carry no coordinates" % missed if missed else ""
    return "%s %d of %d rows%s - stream only" % (verb, touched, total, tail)


def move(params: Mapping[str, object], feeds: Mapping[str, object]):
    """move: translate every wired coordinate by dx / dy / dz millimetres."""
    rows = _rows(feeds)
    if not rows:
        return {"out": []}, _EMPTY_LIST
    deltas = [_number(params, name, 0.0) for name in ("dx", "dy", "dz")]

    def shifted(point):
        return [value + deltas[index] if index < len(deltas) else value
                for index, value in enumerate(point)]

    out, touched = _mapped(rows, shifted)
    return {"out": out}, _geometry_display("moved", touched, len(rows))


def rotate(params: Mapping[str, object], feeds: Mapping[str, object]):
    """rotate: turn every wired coordinate about a centre, in degrees."""
    import math

    rows = _rows(feeds)
    if not rows:
        return {"out": []}, _EMPTY_LIST
    degrees = _number(params, "degrees", _number(params, "angle", 0.0))
    angle = math.radians(degrees)
    cx = _number(params, "cx", 0.0)
    cy = _number(params, "cy", 0.0)
    cosine, sine = math.cos(angle), math.sin(angle)

    def turned(point):
        x, y = point[0] - cx, point[1] - cy
        return [cx + x * cosine - y * sine,
                cy + x * sine + y * cosine] + list(point[2:])

    out, touched = _mapped(rows, turned)
    return {"out": out}, _geometry_display(
        "rotated %.4gdeg" % degrees, touched, len(rows))


def scale(params: Mapping[str, object], feeds: Mapping[str, object]):
    """scale: uniform or per-axis, about a centre."""
    rows = _rows(feeds)
    if not rows:
        return {"out": []}, _EMPTY_LIST
    uniform = _number(params, "factor", 1.0)
    factors = [_number(params, name, uniform) for name in ("sx", "sy", "sz")]
    centre = [_number(params, "cx", 0.0), _number(params, "cy", 0.0), 0.0]

    def stretched(point):
        return [centre[index] + (value - centre[index]) * factors[index]
                if index < 3 else value
                for index, value in enumerate(point)]

    out, touched = _mapped(rows, stretched)
    return {"out": out}, _geometry_display("scaled", touched, len(rows))


def group_by(params: Mapping[str, object], feeds: Mapping[str, object]):
    """group by: key to list, using the grouping the evaluator already holds."""
    rows = _rows(feeds)
    if not rows:
        return {"out": []}, _EMPTY_LIST
    field = _text(params, "by") or _text(params, "field")
    produced, shown = run_stem_operation(
        "shape.group", {"by": field}, {"items": rows})
    return {"out": produced["groups"]}, shown


def sort_by(params: Mapping[str, object], feeds: Mapping[str, object]):
    """sort by: ascending or descending on a key."""
    rows = _rows(feeds)
    if not rows:
        return {"out": []}, _EMPTY_LIST
    produced, shown = run_stem_operation(
        "shape.sort",
        {"by": _text(params, "by") or _text(params, "field"),
         "direction": _text(params, "direction", "asc") or "asc"},
        {"items": rows},
    )
    return {"out": produced["items_out"]}, shown


# ------------------------------------------------------------- logic --

def branch_if(params: Mapping[str, object], feeds: Mapping[str, object]):
    """if: the wired value leaves on ``out`` when the predicate holds and on
    ``false`` when it does not -- one side only, never both.

    A wired ``condition`` decides before the card's own rule does.
    """
    value = _wired(feeds, "in", "value")
    if value is None:
        return {}, _EMPTY_LIST
    condition = feeds.get("condition")
    if condition is None:
        rule = _text(params, "rule") or _text(params, "predicate")
        if rule:
            candidates = value if isinstance(value, list) else [value]
            passed, _shown = _filter_by_rule(candidates, rule, "keep")
            condition = bool(passed)
        else:
            condition = bool(value)
    produced, _shown = run_stem_operation(
        "control.if", {}, {"value": value, "condition": condition})
    if "true" in produced:
        return {"out": produced["true"]}, "true"
    return {"false": produced["false"]}, "false - value left on the false branch"


def branch_switch(params: Mapping[str, object], feeds: Mapping[str, object]):
    """switch: name the branch a key selects and pass the value along it."""
    value = _wired(feeds, "in", "value")
    if value is None:
        return {}, _EMPTY_LIST
    key = feeds.get("key")
    if key is None:
        key = _text(params, "key", "a") or "a"
    produced, shown = run_stem_operation(
        "control.switch", {"cases": _text(params, "cases", "a, b, c") or "a, b, c"},
        {"value": value, "key": key})
    taken = next(iter(produced))
    # ``out`` always carries the routed value; the named branch carries it
    # too, so a wire from a, b or c fires only when that case is taken.
    return {"out": produced[taken], taken: produced[taken]}, "branch %s" % (shown or taken)


def loop(params: Mapping[str, object], feeds: Mapping[str, object]):
    """loop: iterate a wired list, one item at a time, downstream."""
    rows = _rows(feeds)
    if not rows:
        return {"out": []}, _EMPTY_LIST
    produced, shown = run_stem_operation("control.foreach", {}, {"items": rows})
    return {"out": produced["results"], "each": produced["each"]}, shown


def merge(params: Mapping[str, object], feeds: Mapping[str, object]):
    """merge: concat the streams wired to ``in`` and ``b``; dedupe when asked."""
    rows = _rows(feeds)
    second = feeds.get("b")
    rows = rows + ([] if second is None else as_list(second))
    if not rows:
        return {"out": []}, _EMPTY_LIST
    joined = []
    for row in rows:
        joined.extend(row if isinstance(row, list) else [row])
    if _text(params, "mode", "concat") != "dedupe":
        return {"out": joined}, "%d items concatenated" % len(joined)
    produced, shown = run_stem_operation("shape.unique", {}, {"items": joined})
    return {"out": produced["items_out"]}, "%s of %d" % (shown, len(joined))


# ---------------------------------------------------------- annotate --

def add_text(params: Mapping[str, object], feeds: Mapping[str, object]):
    """add_text: one positioned text note, appended to the stream.

    A host engine downstream is what places it in a view. This produces the
    note; it does not claim to have drawn it.
    """
    text = _text(params, "text")
    if not text:
        raise ValueError("set the text parameter to the note to add")
    note = {
        "kind": "text", "text": text,
        "x": _number(params, "x", 0.0), "y": _number(params, "y", 0.0),
    }
    rows = _rows(feeds)
    return {"out": rows + [note]}, "1 note on %d rows - stream only" % len(rows)


def dimensions(params: Mapping[str, object], feeds: Mapping[str, object]):
    """create_dimensions: one measured dimension per wired line.

    The length is computed from the coordinates that arrived, in the
    millimetres the pipeline carries. Rows without two points produce no
    dimension, and the card counts them rather than padding the answer.
    """
    import math

    rows = _rows(feeds)
    if not rows:
        return {"out": []}, _EMPTY_LIST
    style = _text(params, "style", "aligned") or "aligned"
    if style not in ("aligned", "parallel", "baseline"):
        raise ValueError("style must be aligned, parallel or baseline")
    offset = _number(params, "offset", 0.0)
    measured = []
    for row in rows:
        numbers = _coordinates(row)
        if numbers is None or len(numbers) < 4:
            continue
        x1, y1, x2, y2 = numbers[:4]
        measured.append({
            "kind": "dimension", "style": style, "offset": offset,
            "x1": x1, "y1": y1, "x2": x2, "y2": y2,
            "length_mm": math.hypot(x2 - x1, y2 - y1),
        })
    missed = len(rows) - len(measured)
    tail = " - %d rows are not lines" % missed if missed else ""
    return {"out": measured}, "%d %s dimensions%s - stream only" % (
        len(measured), style, tail)


# ----------------------------------------------------------- compose --

def _columns_of(rows: list, declared: str) -> list:
    if declared:
        return [part.strip() for part in declared.split(",") if part.strip()]
    found: list = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        for key in row:
            if str(key) not in found:
                found.append(str(key))
    return found


def build_schedule(params: Mapping[str, object], feeds: Mapping[str, object]):
    """build_schedule: a table from the stream, columns read not invented."""
    rows = _rows(feeds)
    columns = _columns_of(rows, _text(params, "columns"))
    if not rows:
        return {"out": {"columns": columns, "rows": []}}, _EMPTY_LIST
    if not columns:
        return (
            {"out": {"columns": ["value"], "rows": [[row] for row in rows]}},
            "%d rows - 1 column (the stream carries no fields)" % len(rows),
        )
    table = [[item_field(row, column) for column in columns] for row in rows]
    return (
        {"out": {"columns": columns, "rows": table}},
        "%d rows x %d columns" % (len(table), len(columns)),
    )


def make_legend(params: Mapping[str, object], feeds: Mapping[str, object]):
    """make_legend: one entry per distinct symbol in the stream, with counts."""
    rows = _rows(feeds)
    if not rows:
        return {"out": []}, _EMPTY_LIST
    field = _text(params, "by") or _text(params, "field") or "type"
    produced, _shown = run_stem_operation(
        "shape.group", {"by": field}, {"items": rows})
    entries = [
        {"symbol": group["key"], "count": len(group["items"])}
        for group in produced["groups"]
    ]
    entries.sort(key=lambda entry: (-entry["count"], str(entry["symbol"])))
    return {"out": entries}, "%d legend entries by %s" % (len(entries), field)


# ------------------------------------------------------------ output --

def _local_output_path(path: str):
    """A destination the graph names must be a local file, never a share.

    Same law as the pipeline input guard: a graph is data anyone can hand
    you, and a UNC destination makes this process authenticate to a remote
    SMB host and write whatever it is told there.
    """
    from pathlib import Path

    text = str(path or "").strip()
    if not text:
        raise ValueError("set the path parameter to where the skill is saved")
    upper = text.upper()
    if text.startswith(("\\\\", "//")) or upper.startswith(
        ("\\\\?\\UNC", "SMB:", "FILE:")
    ):
        raise ValueError("path must be a local file, not a network share")
    return Path(text)


def save_skill(params: Mapping[str, object], feeds: Mapping[str, object]):
    """save_skill: template this run as a skill file the agents already read.

    The front matter matches what skills_catalogue parses, so a skill saved
    here is found by the same node that lists every other one.
    """
    held = _wired(feeds, "in", "value")
    destination = _local_output_path(_text(params, "path"))
    if held is None:
        # Writing an empty skill would put a lie on disk that every agent
        # afterwards reads back as if it were work.
        return {"out": ""}, "nothing is wired in - nothing saved"
    name = _text(params, "name") or destination.parent.name or "saved-run"
    description = _text(params, "description") or "Saved from an ArchHub run."
    body = held if isinstance(held, str) else repr(held)
    document = chr(10).join([
        "---", "name: %s" % name, "description: %s" % description, "---", "",
        "# %s" % name, "", body, "",
    ])
    overwrite = str(params.get("overwrite") or "").strip().lower() == "true"
    if destination.exists() and not overwrite:
        raise ValueError(
            "%s already exists; set overwrite to true to replace it"
            % destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(document, encoding="utf-8")
    return {"out": str(destination)}, "%s - %d chars" % (name, len(document))


def weighted_valuation(params: Mapping[str, object], feeds: Mapping[str, object]):
    """Weighted min/max normalization of actual wired rows, with typed criteria."""
    criteria = feeds.get('criteria', params.get('criteria', []))
    if isinstance(criteria, str):
        criteria = json.loads(criteria)
    if type(criteria) is not list or not criteria:
        raise ValueError('Criteria must be a nonempty list of field, weight and direction records')
    for criterion in criteria:
        if (type(criterion) is not dict or set(criterion) != {'field','weight','direction'}
                or type(criterion['field']) is not str or not criterion['field'].strip()
                or type(criterion['weight']) not in (int,float)
                or not math.isfinite(criterion['weight']) or criterion['weight'] < 0
                or criterion['direction'] not in ('minimize','maximize')):
            raise ValueError('Each criterion needs a field, finite nonnegative weight and minimize/maximize direction')
    total = sum(c['weight'] for c in criteria)
    if not math.isfinite(total) or total <= 0 or len({c['field'] for c in criteria}) != len(criteria):
        raise ValueError('Criteria must be unique and have a positive finite total weight')
    rows = _rows(feeds)
    if not rows:
        return {'out':[]}, _EMPTY_LIST
    columns = []
    for criterion in criteria:
        values = [row.get(criterion['field']) if type(row) is dict else None for row in rows]
        if any(type(value) not in (int,float) or not math.isfinite(value) for value in values):
            raise ValueError('Every selected row must contain finite numeric criterion values')
        low, high = min(values), max(values)
        width = high - low
        if not math.isfinite(width):
            raise ValueError('Criterion range exceeds finite numeric limits')
        normalized = [(value-low)/width if width else 1.0 for value in values]
        if criterion['direction'] == 'minimize' and width:
            normalized = [1-value for value in normalized]
        columns.append([value * (criterion['weight']/total) for value in normalized])
    scored = [{**row,'score':sum(column[index] for column in columns)} for index,row in enumerate(rows)]
    scored.sort(key=lambda row:row['score'], reverse=True)
    return {'out':[{**row,'rank':index+1} for index,row in enumerate(scored)]}, 'Scored %d linked rows' % len(rows)


LIBRARY_ENGINES = {
    'research.weighted': weighted_valuation,
    "library.filter_field": filter_field,
    "library.filter_compare": filter_compare,
    "library.filter_rule": filter_rule,
    "library.rule_check": rule_check,
    "library.set_field": set_field,
    "library.move": move,
    "library.rotate": rotate,
    "library.scale": scale,
    "library.group_by": group_by,
    "library.sort_by": sort_by,
    "library.if": branch_if,
    "library.switch": branch_switch,
    "library.loop": loop,
    "library.merge": merge,
    "library.add_text": add_text,
    "library.dimensions": dimensions,
    "library.build_schedule": build_schedule,
    "library.make_legend": make_legend,
    "library.save_skill": save_skill,
}

STEM_RUN_ENGINES = frozenset({
    "data.constant", "data.list", "input.parameter", "output.parameter",
    "watch.preview", "trigger.emit", "control.if", "control.foreach",
    "control.switch", "control.merge", "shape.filter", "shape.map",
    "shape.sort", "shape.group", "shape.unique", "shape.pluck",
    "shape.count", "shape.slice", "shape.flatten", "shape.concat",
    "note", "reroute", "ai.master", "skill.wrap",
})


def engine_runs(engine: str, pipeline_engines=None) -> bool:
    """True when a listed card is executable by the stem or effect runner."""
    name = str(engine or "").strip()
    return name in STEM_RUN_ENGINES or (
        pipeline_engines is not None and name in pipeline_engines
    )

# Which library card each engine answers, and the parameters that card is
# placed with. The studio owner reads this to give every listed item an
# engine; until it does, these cards still vanish when they are dropped.
LIBRARY_ITEM_ENGINES = {
    "f_type": {"engine": "shape.filter",
               "params": {"predicate": "item.type == ''", "mode": "keep"}},
    "f_cat": {"engine": "shape.filter",
              "params": {"predicate": "item.category == ''", "mode": "keep"}},
    "f_level": {"engine": "shape.filter",
                "params": {"predicate": "item.level == ''", "mode": "keep"}},
    "f_param": {"engine": "shape.filter",
                "params": {"predicate": "item.parameter == ''", "mode": "keep"}},
    "f_pred": {"engine": "shape.filter",
               "params": {"predicate": "", "mode": "keep"}},
    "t_setp": {"engine": "library.set_field",
               "params": {"field": "", "value": ""}},
    "t_move": {"engine": "library.move",
               "params": {"dx": "0", "dy": "0", "dz": "0"}},
    "t_rot": {"engine": "library.rotate",
              "params": {"degrees": "0", "cx": "0", "cy": "0"}},
    "t_scale": {"engine": "library.scale",
                "params": {"factor": "1", "cx": "0", "cy": "0"}},
    "t_group": {"engine": "shape.group", "params": {"by": ""}},
    "t_sort": {"engine": "shape.sort",
               "params": {"by": "", "direction": "asc"}},
    "l_if": {"engine": "control.if", "params": {"condition": ""}},
    "l_switch": {"engine": "control.switch", "params": {"key": "a", "cases": "a, b, c"}},
    "l_loop": {"engine": "control.foreach", "params": {}},
    "l_merge": {"engine": "control.merge", "params": {}},
    "a_text": {"engine": "library.add_text",
               "params": {"text": "", "x": "0", "y": "0"}},
    "a_dims": {"engine": "library.dimensions",
               "params": {"style": "aligned", "offset": "0"}},
    "c_sched": {"engine": "library.build_schedule", "params": {"columns": ""}},
    "c_legend": {"engine": "library.make_legend", "params": {"by": "type"}},
    "o_skill": {"engine": "library.save_skill",
                "params": {"path": "", "name": "", "description": ""}},
}

# Cards this module deliberately leaves without an engine: each needs a host
# write or a model this version does not carry, and inventing an answer for
# them is exactly the defect being fixed. Grey them out; do not fake them.
LIBRARY_ITEMS_WITHOUT_ENGINE = {
    "a_tags": "needs host element ids and leader placement",
    "a_rooms": "needs host room boundaries",
    "c_sheet": "needs a host sheet and viewport placement",
    "i_think": "needs a model call this build does not wire",
    "i_vis": "needs a vision model call this build does not wire",
    "i_match": "needs the brain skill matcher wired as an engine",
    "i_embed": "needs an embedding model call this build does not wire",
    "o_pdf": "needs the host print pipeline",
    "o_spk": "Speckle Manager is installed but no wire exists in this build",
    "o_email": "sending mail is the founder action, not the graph action",
    "o_notify": "needs a desktop notification surface this build does not carry",
}


# ------------------------------------------------------------ five more --
# Five cards that had no engine get one from what this build already has:
# the model route (think), the skills catalogue (match_skill), the brain
# recall (embed), the open Outlook (draft_email) and the tray (notify).

# How long one model call may hold the canvas (the pipeline runs under the
# app's mutation lock). Raise it per card with the timeout_s parameter.
MODEL_CALL_SECONDS = 30.0

_NOTIFY_SURFACE: list = []


def set_notify_surface(surface) -> None:
    """The desktop surface a notification lands on; the launcher registers its tray."""
    _NOTIFY_SURFACE[:] = [surface]


def _wired_text(feeds: Mapping[str, object]) -> str:
    import json
    held = _wired(feeds, "in", "text", "value")
    if held is None:
        return ""
    if isinstance(held, str):
        return held
    return json.dumps(held, default=str)[:12000]


# Model cards whose blank "model" row the pipeline run fills from the graph's
# composer pick (universal_pipeline.run_universal_pipeline) before it runs.
MODEL_PICK_ENGINES = frozenset({"library.think", "library.vision"})


def _model_route(params: Mapping[str, object]) -> str:
    """The card's model (the graph pick when it was blank), else the declared env route."""
    import os
    return _text(params, "model") or os.environ.get("ARCHHUB_AGENT_MODEL", "").strip()


def think(params: Mapping[str, object], feeds: Mapping[str, object]):
    """Reason with the picked model over the wired stream; never a hidden default."""
    from . import model_router
    from .agent_composer import NO_MODEL_CHOSEN
    route = _model_route(params)
    if not route:
        return {"out": []}, NO_MODEL_CHOSEN
    prompt = _text(params, "prompt")
    context = _wired_text(feeds)
    if not prompt and not context:
        return {"out": []}, "nothing to think about: no prompt, nothing wired in"
    messages = [
        {"role": "system", "content": "You are ArchHub. Be terse and technical. Units: millimetres."},
        {"role": "user", "content": (prompt + chr(10) + chr(10) + context).strip()},
    ]
    try:
        # The pipeline runs under the app's one mutation lock, so a model call
        # holds the canvas while it waits: bounded, and the founder can raise
        # it on the card when he means to wait (audit 2026-09-07).
        answer = model_router.route_chat(
            route, messages, max_tokens=int(_number(params, "max_tokens", 600)),
            timeout=max(5.0, min(_number(params, "timeout_s", MODEL_CALL_SECONDS), 120.0)))
    except Exception as refused:
        return {"out": []}, "%s refused: %s" % (route, str(refused)[:160])
    text = str(answer.get("text") or "") if isinstance(answer, Mapping) else str(answer)
    return {"out": text}, "%s answered (%d chars)" % (route, len(text))


def match_skill(params: Mapping[str, object], feeds: Mapping[str, object]):
    """The saved skills whose name or description share words with the intent."""
    import re
    from .pipeline_engines import skills_catalogue
    intent = _text(params, "intent") or _wired_text(feeds)
    if not intent:
        return {"out": []}, "no intent given, nothing wired in"
    outputs, _said = skills_catalogue({}, {})
    words = set(re.findall(r"[a-z0-9]+", intent.casefold())) - {"a", "an", "the", "in", "of", "to", "for"}
    scored = []
    for row in as_list(outputs.get("out")):
        hay = ("%s %s" % (item_field(row, "name"), item_field(row, "description"))).casefold()
        hits = sum(1 for word in words if word in hay)
        if hits:
            scored.append((hits, str(item_field(row, "name")), row))
    scored.sort(key=lambda entry: (-entry[0], entry[1]))
    count = max(1, int(_number(params, "count", 3)))
    top = [dict(row, score=hits) for hits, _name, row in scored[:count]]
    if not top:
        return {"out": []}, "no saved skill shares a word with that intent"
    return {"out": top}, "%d skill(s) by word overlap, not a model: %s" % (
        len(top), ", ".join(str(row["name"]) for row in top))


def embed(params: Mapping[str, object], feeds: Mapping[str, object]):
    """What the brain recalls for a query: its own similarity search, not ours."""
    import json
    from .pipeline_engines import BrainSilent, _brain_call
    query = _text(params, "query") or _wired_text(feeds)
    if not query:
        return {"out": []}, "no query, nothing wired in"
    try:
        answer = str(_brain_call("brain.context", {"prompt": query}))
    except BrainSilent as silence:
        return {"out": []}, "no recall: %s" % silence
    try:
        parsed = json.loads(answer)
    except ValueError:
        parsed = None
    rows = []
    if isinstance(parsed, Mapping):
        for key in ("facts", "results", "hits", "context", "items"):
            if isinstance(parsed.get(key), list):
                rows = parsed[key]
                break
    elif isinstance(parsed, list):
        rows = parsed
    if rows:
        return {"out": rows}, "%d recalled fact(s) for %r" % (len(rows), query[:40])
    return {"out": answer}, "the brain answered in prose, not rows"


def notify(params: Mapping[str, object], feeds: Mapping[str, object]):
    """A desktop notification through the surface the app registered (its tray)."""
    # notice_title, not title: every placed card already holds its own title
    # property, so a "title" parameter could never be created (2026-09-24).
    title = _text(params, "notice_title") or "ArchHub"
    message = _text(params, "message") or _wired_text(feeds)
    if not message:
        return {"out": []}, "nothing to say: no message, nothing wired in"
    if not _NOTIFY_SURFACE:
        return {"out": message}, "no desktop surface registered; the app registers its tray at boot"
    try:
        _NOTIFY_SURFACE[0](title, message)
    except Exception as failed:
        return {"out": message}, "the desktop refused: %s" % failed
    return {"out": message}, "sent to the desktop tray: %s" % message[:60]


def _open_outlook():
    """The OPEN Outlook, or None; this never launches it."""
    from .host_brokers import _com_alive, _outlook_application
    if not _com_alive("Outlook.Application"):
        return None
    return _outlook_application()


_OUTLOOK = [_open_outlook]


def draft_email(params: Mapping[str, object], feeds: Mapping[str, object]):
    """A draft on screen in the open Outlook; sending stays the founder's click."""
    to = _text(params, "to")
    subject = _text(params, "subject") or "From ArchHub"
    body = _text(params, "body") or _wired_text(feeds)
    if not body:
        return {"out": []}, "nothing to write: no body, nothing wired in"
    app = _OUTLOOK[0]()
    if app is None:
        return {"out": []}, "Outlook is not open; the draft needs it open"
    try:
        mail = app.CreateItem(0)
        mail.To = to
        mail.Subject = subject
        mail.Body = body
        mail.Display()
    except Exception as failed:
        return {"out": []}, "Outlook refused the draft: %s" % failed
    return {"out": {"to": to, "subject": subject, "chars": len(body)}}, (
        "draft open in Outlook (%s) - you send it" % (to or "no recipient yet"))


LIBRARY_ENGINES.update({
    "library.think": think,
    "library.match_skill": match_skill,
    "library.embed": embed,
    "library.notify": notify,
    "library.draft_email": draft_email,
})

LIBRARY_ITEM_ENGINES.update({
    "i_think": {"engine": "library.think",
                "params": {"prompt": "", "model": "", "max_tokens": "600"}},
    "i_match": {"engine": "library.match_skill",
                "params": {"intent": "", "count": "3"}},
    "i_embed": {"engine": "library.embed", "params": {"query": ""}},
    "o_email": {"engine": "library.draft_email",
                "params": {"to": "", "subject": "", "body": ""}},
    "o_notify": {"engine": "library.notify",
                 "params": {"notice_title": "ArchHub", "message": ""}},
})
for _wired_now in ("i_think", "i_match", "i_embed", "o_email", "o_notify"):
    LIBRARY_ITEMS_WITHOUT_ENGINE.pop(_wired_now, None)

LIBRARY_ITEM_ENGINES.update({
    "tool_studio": {"engine": "tool.studio",
                    "params": {"tool": "studio"}},
    "tool_workshop": {"engine": "tool.workshop",
                      "params": {"tool": "workshop", "stale_claim_after_idle_minutes": "30",
                                 "archive_after_idle_days": "20", "tick_cadence_minutes": 5,
                                 "backup_count": 3, "backup_budget_bytes": 34359738368,
                                 "recovery_timeout_seconds": 30,
                                 "instance_retry_ms": 500,
                                 "preflight_database_ms": 1000,
                                 "broker_start_ms": 60000,
                                 "refusal_poll_ms": 200,
                                 "quit_watchdog_ms": 3000,
                                 "account_http_ms": 25000,
                                 "session_minimum_validity_seconds": 5,
                                 "session_poll_ms": 5000,
                                 "worker_join_ms": 5000,
                                 "host_stop_ms": 1000,
                                 "host_cancel_ms": 10,
                                 "mutation_poll_ms": 100,
                                 "desktop_refresh_ms": 5000,
                                 "archive_step_ms": 2000,
                                 "cloud_shutdown_ms": 1000,
                                 "update_shutdown_ms": 6000,
                                 "export_release_ms": 1000,
                                 "toast_visible_ms": 6000,
                                 "voice_hold_ms": 300,
                                 "model_request_ms": 90000,
                                 "model_cli_request_ms": 240000,
                                 "keep_running_in_tray": False,
                                 "update_check_interval_minutes": 30, "update_auto_apply_on_quit": True,
                                 "update_preview_channel": False, "backup_location": "auto"}},
    "tool_brain": {"engine": "tool.brain",
                   "params": {"tool": "brain"}},
    "tool_baboom": {"engine": "tool.baboom",
                    "params": {"tool": "baboom", "start_with_archhub": True}},
    "tool_connectors": {"engine": "tool.connectors",
                        "params": {"tool": "connectors"}},
    "tool_cloud": {"engine": "tool.cloud",
                   "params": {"tool": "cloud"}},
})


_IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".webp": "image/webp", ".gif": "image/gif"}


def vision(params: Mapping[str, object], feeds: Mapping[str, object]):
    """Read a sketch or screenshot with the picked model; the image travels as a data URL."""
    import base64
    from pathlib import Path
    from . import model_router
    from .agent_composer import NO_MODEL_CHOSEN
    from .pipeline_engines import _local_input_path
    route = _model_route(params)
    if not route:
        return {"out": []}, NO_MODEL_CHOSEN
    held = _wired(feeds, "in", "image_path", "path")
    try:
        path = _local_input_path(_text(params, "image_path") or (held if isinstance(held, str) else ""), label="image_path")
    except ValueError as missing:
        return {"out": []}, str(missing)
    kind = _IMAGE_TYPES.get(Path(path).suffix.lower())
    if not kind:
        return {"out": []}, "not an image this card reads: %s" % Path(path).name
    raw = Path(path).read_bytes()
    if len(raw) > 8_000_000:
        return {"out": []}, "image too large for a model call: %.1f MB (8 MB is the ceiling)" % (len(raw) / 1e6)
    data = base64.b64encode(raw).decode("ascii")
    prompt = _text(params, "prompt") or (
        "Describe this architectural drawing: rooms, walls, openings, and any "
        "dimensions or text you can read. Millimetres. Be terse.")
    messages = [{"role": "user", "content": [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": "data:%s;base64,%s" % (kind, data)}},
    ]}]
    try:
        answer = model_router.route_chat(
            route, messages, max_tokens=int(_number(params, "max_tokens", 600)),
            timeout=max(5.0, min(_number(params, "timeout_s", MODEL_CALL_SECONDS), 120.0)))
    except Exception as refused:
        return {"out": []}, "%s refused: %s" % (route, str(refused)[:160])
    text = str(answer.get("text") or "") if isinstance(answer, Mapping) else str(answer)
    return {"out": text, "image_path": path}, "%s read %s (%d chars)" % (route, Path(path).name, len(text))


LIBRARY_ENGINES["library.vision"] = vision
LIBRARY_ITEM_ENGINES["i_vis"] = {"engine": "library.vision",
                                 "params": {"image_path": "", "prompt": "", "model": "", "max_tokens": "600"}}
LIBRARY_ITEMS_WITHOUT_ENGINE.pop("i_vis", None)


_EXPORT_PDF = """
var folder = %s;
var wanted = new List<string>{%s};
var sheets = new List<ElementId>();
foreach (ViewSheet vs in new FilteredElementCollector(Doc).OfClass(typeof(ViewSheet))) {
    if (vs.IsPlaceholder) continue;
    if (wanted.Count > 0 && !wanted.Contains(vs.SheetNumber)) continue;
    sheets.Add(vs.Id);
}
if (sheets.Count == 0) throw new Exception("no sheet to publish");
System.IO.Directory.CreateDirectory(folder);
var options = new PDFExportOptions();
options.Combine = false;
if (!Doc.Export(folder, sheets, options)) throw new Exception("Revit declined the PDF export");
var written = new List<string>();
foreach (var f in System.IO.Directory.GetFiles(folder, "*.pdf")) written.Add(f);
result = new Dictionary<string, object>{ {"sheets", sheets.Count}, {"folder", folder}, {"files", written} };
"""


def publish_pdf(params: Mapping[str, object], feeds: Mapping[str, object]):
    """The sheets of the open model as PDF files, exported by the live Revit; files, never a claim."""
    import json
    import os
    import time
    from .clean_revit_adapter import _execute, sole_session
    session, why = sole_session()
    if session is None:
        return {"out": []}, why
    held = _wired(feeds, "in", "sheets")
    wanted = [str(item_field(row, "number") or row) for row in as_list(held)] if held is not None else [
        piece.strip() for piece in _text(params, "sheets").split(",") if piece.strip()]
    # Always a fresh, dated folder under Documents/ArchHub/pdf: a graph is
    # data anyone can hand you, so a folder it names is only a NAME inside
    # that base (never a share, never a path of its own), and the listing
    # afterwards is exactly what this run wrote.
    base = os.path.join(os.path.expanduser("~"), "Documents", "ArchHub", "pdf")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    asked = os.path.basename(_text(params, "folder").replace(chr(92), "/").rstrip("/"))
    safe = "".join(ch for ch in asked if ch.isalnum() or ch in "-_ ").strip()
    folder = os.path.join(base, (safe + "-" + stamp) if safe else stamp)
    script = _EXPORT_PDF % (json.dumps(folder), ", ".join(json.dumps(number) for number in wanted))
    try:
        # A sheet set takes longer than a read: three minutes before "did not answer".
        answer = _execute(session, script, "ArchHub publish pdf", timeout=180.0)
    except Exception as failed:
        return {"out": []}, "Revit did not answer: %s" % str(failed)[:160]
    if not isinstance(answer, Mapping) or answer.get("status") != "ok":
        return {"out": []}, "Revit refused: %s" % ((answer or {}).get("error") if isinstance(answer, Mapping) else answer)
    result = answer.get("result") if isinstance(answer.get("result"), Mapping) else {}
    files = [str(name) for name in as_list(result.get("files"))]
    return {"out": files, "folder": folder}, "%d PDF(s) in %s from %s" % (
        len(files), folder, session.get("document") or session["port"])


LIBRARY_ENGINES["library.publish_pdf"] = publish_pdf
LIBRARY_ITEM_ENGINES["o_pdf"] = {"engine": "library.publish_pdf",
                                 "params": {"sheets": "", "folder": ""}}
LIBRARY_ITEMS_WITHOUT_ENGINE.pop("o_pdf", None)


# --------------------------------------------------- revit authoring --
# Three cards that write into the open model through the same broker the
# wall cards use. Each runs in one named transaction, skips what is already
# done, and answers with counts the model itself reported.

_TAG_ROOMS = """
var view = Doc.ActiveView;
var already = new HashSet<int>();
foreach (Element e in new FilteredElementCollector(Doc, view.Id).OfClass(typeof(SpatialElementTag))) {
    var rt = e as Autodesk.Revit.DB.Architecture.RoomTag; if (rt != null && rt.Room != null) already.Add(rt.Room.Id.IntegerValue);
}
int tagged = 0, skipped = 0;
// The broker runs this inside the transaction it named; a second Start here would throw.
foreach (Element e in new FilteredElementCollector(Doc, view.Id).OfCategory(BuiltInCategory.OST_Rooms).WhereElementIsNotElementType()) {
    var room = e as Autodesk.Revit.DB.Architecture.Room;
    if (room == null || room.Area <= 0 || already.Contains(room.Id.IntegerValue)) { skipped++; continue; }
    var lp = room.Location as LocationPoint;
    if (lp == null) { skipped++; continue; }
    Doc.Create.NewRoomTag(new LinkElementId(room.Id), new UV(lp.Point.X, lp.Point.Y), view.Id);
    tagged++;
}
result = new Dictionary<string, object>{ {"tagged", tagged}, {"skipped", skipped}, {"view", view.Name} };
"""


def tag_rooms(params: Mapping[str, object], feeds: Mapping[str, object]):
    """A room tag on every untagged room of the active view, placed at the room point."""
    from .clean_revit_adapter import authoring
    session, result = authoring(_TAG_ROOMS, "ArchHub tag rooms", params)
    if session is None:
        return {"out": []}, str(result)
    return {"out": result, "tagged": result.get("tagged")}, "%s room(s) tagged, %s skipped, in %s of %s" % (
        result.get("tagged"), result.get("skipped"), result.get("view"), session.get("document") or session["port"])


_PLACE_TAGS = """
var view = Doc.ActiveView;
var catName = %s;
BuiltInCategory bic;
if (!Enum.TryParse("OST_" + catName, out bic)) throw new Exception("unknown category " + catName);
bool leader = %s;
var already = new HashSet<int>();
foreach (Element e in new FilteredElementCollector(Doc, view.Id).OfClass(typeof(IndependentTag))) {
    var it = e as IndependentTag; if (it == null) continue;
    foreach (var id in it.GetTaggedLocalElementIds()) already.Add(id.IntegerValue);
}
int tagged = 0, skipped = 0;
// The broker runs this inside the transaction it named; a second Start here would throw.
foreach (Element e in new FilteredElementCollector(Doc, view.Id).OfCategory(bic).WhereElementIsNotElementType()) {
    if (already.Contains(e.Id.IntegerValue)) { skipped++; continue; }
    var bb = e.get_BoundingBox(view); if (bb == null) { skipped++; continue; }
    var c = (bb.Min + bb.Max) / 2;
    IndependentTag.Create(Doc, view.Id, new Reference(e), leader, TagMode.TM_ADDBY_CATEGORY, TagOrientation.Horizontal, c);
    tagged++;
}
result = new Dictionary<string, object>{ {"tagged", tagged}, {"skipped", skipped}, {"category", catName}, {"view", view.Name} };
"""


def place_tags(params: Mapping[str, object], feeds: Mapping[str, object]):
    """A tag on every untagged element of one category in the active view, leader optional."""
    import json
    category = _text(params, "category", "Doors")
    leader = _text(params, "leader", "true").casefold() in ("1", "true", "yes", "on")
    script = _PLACE_TAGS % (json.dumps(category), "true" if leader else "false")
    from .clean_revit_adapter import authoring
    session, result = authoring(script, "ArchHub place tags", params)
    if session is None:
        return {"out": []}, str(result)
    return {"out": result, "tagged": result.get("tagged")}, "%s %s tagged, %s skipped, in %s" % (
        result.get("tagged"), category.lower(), result.get("skipped"), result.get("view"))


_PLACE_ON_SHEET = """
var number = %s;
var names = new List<string>{%s};
ViewSheet sheet = null;
foreach (ViewSheet vs in new FilteredElementCollector(Doc).OfClass(typeof(ViewSheet))) if (vs.SheetNumber == number) { sheet = vs; break; }
var placed = new List<string>(); var skipped = new List<string>();
// The broker runs this inside the transaction it named; a second Start here would throw.
if (sheet == null) {
    ElementId tb = ElementId.InvalidElementId;
    foreach (Element e in new FilteredElementCollector(Doc).OfCategory(BuiltInCategory.OST_TitleBlocks).OfClass(typeof(FamilySymbol))) { tb = e.Id; break; }
    sheet = ViewSheet.Create(Doc, tb);
    sheet.SheetNumber = number;
}
var box = sheet.Outline;
double w = box.Max.U - box.Min.U, h = box.Max.V - box.Min.V;
int i = 0;
foreach (var name in names) {
    View view = null;
    foreach (Element e in new FilteredElementCollector(Doc).OfClass(typeof(View))) { var v = e as View; if (v != null && !v.IsTemplate && v.Name == name) { view = v; break; } }
    if (view == null || !Viewport.CanAddViewToSheet(Doc, sheet.Id, view.Id)) { skipped.Add(name); continue; }
    int col = i %% 2, row = i / 2;
    var pt = new XYZ(box.Min.U + w * (0.25 + 0.5 * col), box.Max.V - h * (0.25 + 0.5 * row), 0);
    Viewport.Create(Doc, sheet.Id, view.Id, pt);
    placed.Add(name); i++;
}
result = new Dictionary<string, object>{ {"sheet", sheet.SheetNumber}, {"placed", placed}, {"skipped", skipped} };
"""


def place_on_sheet(params: Mapping[str, object], feeds: Mapping[str, object]):
    """Named views onto one sheet (made if missing), two per row, through the live Revit."""
    import json
    number = _text(params, "sheet")
    if not number:
        return {"out": []}, "no sheet number given"
    held = _wired(feeds, "in", "views")
    names = [str(item_field(row, "name") or row) for row in as_list(held)] if held is not None else [
        piece.strip() for piece in _text(params, "views").split(",") if piece.strip()]
    if not names:
        return {"out": []}, "no view named, nothing wired in"
    script = _PLACE_ON_SHEET % (json.dumps(number), ", ".join(json.dumps(name) for name in names))
    from .clean_revit_adapter import authoring
    session, result = authoring(script, "ArchHub place on sheet", params)
    if session is None:
        return {"out": []}, str(result)
    placed = as_list(result.get("placed"))
    skipped = as_list(result.get("skipped"))
    return {"out": result, "placed": placed}, "%d view(s) on sheet %s%s" % (
        len(placed), result.get("sheet"), (", %d skipped" % len(skipped)) if skipped else "")


LIBRARY_ENGINES.update({
    "library.tag_rooms": tag_rooms,
    "library.place_tags": place_tags,
    "library.place_on_sheet": place_on_sheet,
})
LIBRARY_ITEM_ENGINES.update({
    "a_rooms": {"engine": "library.tag_rooms", "params": {}},
    "a_tags": {"engine": "library.place_tags", "params": {"category": "Doors", "leader": "true"}},
    "c_sheet": {"engine": "library.place_on_sheet", "params": {"sheet": "", "views": ""}},
})
for _wired_now in ("a_rooms", "a_tags", "c_sheet"):
    LIBRARY_ITEMS_WITHOUT_ENGINE.pop(_wired_now, None)


# ------------------------------------------------------------- speckle --
# The last card. Same wire the 2026-05 client used: one object uploaded to
# /objects/<project>, one commitCreate on the branch, plain urllib, the
# token from the environment or the secrets store, never typed here.

SPECKLE_SERVER = "https://app.speckle.systems"
_COMMIT_CREATE = "mutation CreateCommit($commit: CommitCreateInput!) { commitCreate(commit: $commit) }"


def _speckle_token(environ=None, secrets_loader=None) -> str:
    import os
    env = os.environ if environ is None else environ
    token = str(env.get("SPECKLE_TOKEN") or "").strip()
    if token:
        return token
    if secrets_loader is None:
        def secrets_loader(name):
            try:
                from app import secrets_store  # noqa: PLC0415
                return str(secrets_store.load_api_key(name) or "")
            except Exception:
                return ""
    return str(secrets_loader("speckle") or "").strip()


def _speckle_object_id(obj: Mapping[str, object]) -> str:
    import hashlib
    import json
    canonical = json.dumps({k: v for k, v in obj.items() if k != "id"},
                           sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _speckle_call(url: str, body: object, token: str, opener=None) -> dict:
    import json
    import urllib.request
    request = urllib.request.Request(
        url, data=json.dumps(body, ensure_ascii=True, default=str).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json",
                 "Authorization": "Bearer " + token})
    return _speckle_send(request, opener)


def _speckle_objects(url: str, objects: list, token: str, opener=None) -> dict:
    """Upload a batch to /objects/<project> the way the server takes it.

    Speckle's object endpoint reads a MULTIPART file part whose content is the
    JSON array of objects (docs.speckle.systems, REST API); a raw JSON body is
    answered 400 and the card could never push (audit 2026-09-07)."""
    import json
    import urllib.request
    boundary = "archhub-" + _speckle_object_id({"batch": len(objects)})[:24]
    payload = json.dumps(objects, ensure_ascii=True, default=str).encode("utf-8")
    eol = (chr(13) + chr(10)).encode("ascii")
    body = b"".join([
        b"--" + boundary.encode("ascii") + eol,
        b'Content-Disposition: form-data; name="batch1"; filename="batch1"' + eol,
        b"Content-Type: application/json" + eol + eol,
        payload,
        eol + b"--" + boundary.encode("ascii") + b"--" + eol,
    ])
    request = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "multipart/form-data; boundary=" + boundary,
                 "Accept": "application/json",
                 "Authorization": "Bearer " + token})
    return _speckle_send(request, opener)


def _speckle_send(request, opener=None) -> dict:
    import json
    import urllib.request
    with (opener or urllib.request.urlopen)(request, timeout=60) as response:
        raw = response.read()
    try:
        parsed = json.loads(raw.decode("utf-8")) if raw else {}
    except ValueError:
        parsed = {}
    return parsed if isinstance(parsed, dict) else {}


def push_speckle(params: Mapping[str, object], feeds: Mapping[str, object], *,
                 opener=None, environ=None, secrets_loader=None):
    """The wired rows as one Speckle object, committed to a branch of a project."""
    rows = _rows(feeds)
    if not rows:
        return {"out": []}, _EMPTY_LIST
    project = _text(params, "project")
    if not project:
        return {"out": []}, "no Speckle project id given"
    branch = _text(params, "branch", "archhub/main")
    message = _text(params, "message", "ArchHub push")
    server = (_text(params, "server") or SPECKLE_SERVER).rstrip("/")
    token = _speckle_token(environ, secrets_loader)
    if not token:
        return {"out": []}, "no Speckle token: set SPECKLE_TOKEN or store a key named speckle"
    obj = {"speckle_type": "Objects.BuiltElements.ArchHub.RowSet@1.0.0", "__closure": {},
           "applicationId": None, "rows": rows, "count": len(rows)}
    obj["id"] = _speckle_object_id(obj)
    try:
        _speckle_objects("%s/objects/%s" % (server, project), [obj], token, opener)
        answer = _speckle_call("%s/graphql" % server, {
            "query": _COMMIT_CREATE,
            "variables": {"commit": {"streamId": project, "branchName": branch, "objectId": obj["id"],
                                     "message": message, "sourceApplication": "ArchHub"}},
        }, token, opener)
    except Exception as failed:
        return {"out": []}, "Speckle refused: %s" % str(failed)[:160]
    errors = answer.get("errors")
    if errors:
        first = errors[0] if isinstance(errors, list) and errors else errors
        return {"out": []}, "Speckle refused: %s" % (first.get("message") if isinstance(first, Mapping) else first)
    commit = str((answer.get("data") or {}).get("commitCreate") or "")
    if not commit:
        return {"out": []}, "Speckle made no commit"
    return {"out": {"commit_id": commit, "object_id": obj["id"], "branch": branch,
                    "project": project, "rows": len(rows)}}, (
        "commit %s on %s (%d rows) at %s" % (commit[:8], branch, len(rows), server))


LIBRARY_ENGINES["library.push_speckle"] = push_speckle
LIBRARY_ITEM_ENGINES["o_spk"] = {"engine": "library.push_speckle",
                                 "params": {"project": "", "branch": "archhub/main", "message": "ArchHub push", "server": ""}}
LIBRARY_ITEMS_WITHOUT_ENGINE.pop("o_spk", None)


def host_read(params: Mapping[str, object], feeds: Mapping[str, object]):
    """Generic handoff host read, dispatched to the engines this build already runs."""
    host = _text(params, "host", "Revit").casefold()
    operation = _text(params, "operation", "List walls").casefold()
    if "revit" in host:
        op_map = {
            "list walls": "revit.list_walls",
            "list doors": "revit.list_doors",
            "list windows": "revit.list_windows",
            "list sheets": "revit.list_sheets",
            "list views": "revit.list_views",
            "list levels": "revit.list_levels",
            "get selection": "revit.get_selection",
            "list warnings": "revit.list_warnings",
        }
        if operation not in op_map:
            return {"out": []}, "unknown Revit read operation: %s" % _text(params, "operation", "operation")
        from .pipeline_engines import revit_read
        try:
            return revit_read({"operation": op_map[operation]}, feeds)
        except ValueError as refusal:
            return {"out": []}, str(refusal)
    if "autocad" in host:
        from .pipeline_engines import cad_lines_from_host
        return cad_lines_from_host(params, feeds)
    return {"out": []}, "%s read %r is not wired in this build" % (
        _text(params, "host", "host"), _text(params, "operation", "operation"))


def host_write(params: Mapping[str, object], feeds: Mapping[str, object]):
    """Generic handoff host write: explicit refusal unless a specific broker owns it."""
    rows = _rows(feeds)
    if not rows:
        return {"out": []}, "nothing is wired in"
    return {"out": []}, (
        "host write needs a specific approved host operation; %d item(s) held"
        % len(rows)
    )


def speckle_receive(params: Mapping[str, object], feeds: Mapping[str, object]):
    """Receive-from-Speckle handoff node, bounded at the credential edge."""
    if not _text(params, "project"):
        return {"out": []}, "set the Speckle project before receiving"
    return {"out": []}, "Speckle receive needs the Speckle download adapter"


def speckle_diff(params: Mapping[str, object], feeds: Mapping[str, object]):
    """Diff handoff node: refuses incomplete version pairs instead of guessing."""
    if not _text(params, "project"):
        return {"out": []}, "set the Speckle project before diffing"
    if not _text(params, "from"):
        return {"out": []}, "set the from version before diffing"
    return {"out": []}, "Speckle diff needs the Speckle download adapter"


LIBRARY_ENGINES.update({
    "host.read": host_read,
    "speckle.send": push_speckle,
})

# Workshop, Agent session and Independent review: the clean-bootstrap contracts
# reconciled into this one running catalogue (workshop_workflow.WORKSHOP_CATALOGUE).
# Placing one runs nothing; the canvas Run refuses them and only an approved
# Workshop workflow binds their effects (workshop_workflow._bound_engines).
from .workshop_workflow import WORKSHOP_CATALOGUE, approval_required  # noqa: E402

for _item, _row in WORKSHOP_CATALOGUE.items():
    LIBRARY_ENGINES[_row["engine"]] = approval_required
    LIBRARY_ITEM_ENGINES[_item] = {"engine": _row["engine"], "params": dict(_row["params"])}

# Terminal: a real shell in a folder inside this ArchHub's admitted workspace
# root. The application server owns the sessions (terminal_sessions.py) and binds
# this engine to them; outside a server the card refuses rather than spawn a shell.
def terminal_unbound(params, feeds):
    raise ValueError("the terminal runs only inside the ArchHub application")


LIBRARY_ENGINES["library.terminal"] = terminal_unbound
LIBRARY_ITEM_ENGINES["o_term"] = {"engine": "library.terminal",
                                  "params": {"cwd": "", "command": ""}}
LIBRARY_ITEMS_WITHOUT_ENGINE.pop("o_term", None)

# The sockets an engine card is placed with. Every card has ``out`` and
# ``in``; a logic card's other branches are real, named sockets on the graph
# (universal_pipeline._ensure_pipeline_node_interfaces mints them), so what
# the library says a card does is what can be wired to it.
ENGINE_SOCKETS = {
    'research.weighted': {'source':('out',), 'target':('in','criteria')},
    "tool.workshop": {"source": ("out",), "target": (
        "tool", "stale_claim_after_idle_minutes", "archive_after_idle_days",
        "tick_cadence_minutes", "backup_count", "backup_budget_bytes", "recovery_timeout_seconds", "instance_retry_ms", "preflight_database_ms", "broker_start_ms", "refusal_poll_ms", "quit_watchdog_ms", "account_http_ms", "session_minimum_validity_seconds", "session_poll_ms", "worker_join_ms", "host_stop_ms", "host_cancel_ms", "mutation_poll_ms", "desktop_refresh_ms", "archive_step_ms", "cloud_shutdown_ms", "update_shutdown_ms", "export_release_ms", "toast_visible_ms", "voice_hold_ms", "model_request_ms", "model_cli_request_ms", "keep_running_in_tray",
        "update_check_interval_minutes", "update_auto_apply_on_quit", "update_preview_channel", "backup_location")},
    "data.constant": {"source": ("value",), "target": ()},
    "data.list": {"source": ("value",), "target": ()},
    "input.parameter": {"source": ("value",), "target": ()},
    "trigger.emit": {"source": ("out", "fire"), "target": ()},
    "trigger.schedule": {"source": ("fire", "payload"), "target": ()},
    "trigger.file": {"source": ("fire", "payload"), "target": ()},
    "trigger.host": {"source": ("fire", "payload"), "target": ()},
    "trigger.approval": {"source": ("fire", "payload"), "target": ()},
    "approval.gate": {"source": ("out", "grant"), "target": ("in", "value", "grant")},
    "trigger.webhook": {"source": ("fire", "payload"), "target": ()},
    "output.parameter": {"source": (), "target": ("value",)},
    "watch.preview": {"source": ("out",), "target": ("in",)},
    "note": {"source": (), "target": ()},
    "reroute": {"source": ("out",), "target": ("in",)},
    "input.slider": {"source": ("value",), "target": ()},
    "ai.master": {"source": ("response", "intent"), "target": ("context",)},
    "brain.recall": {"source": ("out",), "target": ("in",)},
    "brain.remember": {"source": ("out",), "target": ("in",)},
    "skill.wrap": {"source": ("result",), "target": ("trace",)},
    "host.read": {"source": ("out",), "target": ("in",)},
    "office.read": {"source": ("out",), "target": ()},
    "speckle.send": {"source": ("out",), "target": ("in",)},
    "revit.elements_of_category": {"source": ("elements", "out"), "target": ()},
    "revit.get_parameter": {"source": ("values", "out"), "target": ("elements", "parameter")},
    "text.ops": {"source": ("text", "out"), "target": ("text", "items")},
    "math.expression": {"source": ("value", "out"), "target": ("a", "b", "c", "x", "y")},
    "math.series": {"source": ("values", "out"), "target": ()},
    "archhub.dry_run_diff": {"source": ("diff", "out"), "target": ("before", "after", "proposed")},
    "host.health": {"source": ("out",), "target": ()},
    "evidence.attach": {"source": ("evidence", "out"), "target": ("files",)},
    "control.if": {"source": ("true", "false"), "target": ("value", "condition")},
    "control.switch": {"source": ("a", "b", "c"), "target": ("value", "key")},
    "control.foreach": {"source": ("each", "results"), "target": ("items",)},
    "control.merge": {"source": ("value",), "target": ("a", "b")},
    "shape.map": {"source": ("items_out",), "target": ("items",)},
    "shape.unique": {"source": ("items_out",), "target": ("items",)},
    "shape.pluck": {"source": ("values",), "target": ("items",)},
    "shape.count": {"source": ("count",), "target": ("items",)},
    "shape.slice": {"source": ("items_out",), "target": ("items",)},
    "shape.flatten": {"source": ("items_out",), "target": ("items",)},
    "shape.concat": {"source": ("items_out",), "target": ("a", "b")},
    "library.if": {"source": ("out", "false"), "target": ("in", "condition")},
    "library.switch": {"source": ("out", "a", "b", "c"), "target": ("in", "key")},
    "library.loop": {"source": ("out", "each"), "target": ("in",)},
    "library.merge": {"source": ("out",), "target": ("in", "b")},
    "library.rule_check": {"source": ("pass", "fail", "report", "out"), "target": ("in",)},
    "revit.set_parameter_by_name": {"source": ("elements", "out"), "target": ("elements", "parameter", "value", "grant")},
    "excel.write_range": {"source": ("file", "out"), "target": ("rows", "grant")},
    "revit.create_sheets": {"source": ("sheets", "out"), "target": ("rows", "grant")},
    "revit.renumber_rename": {"source": ("elements", "out"), "target": ("elements", "number_format", "name_format", "grant")},
}


def engine_sockets(engine: str) -> dict:
    """{"source": names, "target": names} for one engine card."""
    held = ENGINE_SOCKETS.get(str(engine or "").strip()) or {}
    return {
        "source": tuple(held["source"]) if "source" in held else ("out",),
        "target": tuple(held["target"]) if "target" in held else ("in",),
    }


# -------------------------------------------------- the base AI and Skill --
# The base catalogue's AI and Skill stems (ai.master, skill.wrap) answered
# "engine ... is pending" on every Run. They are the same model route, skill
# matcher, brain recall and skill reader the library cards already use.

def ai_master(params: Mapping[str, object], feeds: Mapping[str, object]):
    """AI: one model card with an action picker, over the wired context."""
    action = _text(params, "action", "think") or "think"
    context = feeds.get("context")
    shared = {} if context is None else {"in": context}
    prompt = _text(params, "prompt")
    if action in ("think", "converse"):
        outputs, shown = think(params, shared)
    elif action == "vision":
        outputs, shown = vision(params, shared)
    elif action == "match":
        outputs, shown = match_skill(dict(params, intent=prompt), shared)
    elif action == "embed":
        outputs, shown = embed(dict(params, query=prompt), shared)
    else:
        raise ValueError(
            "action %r is not one of converse, think, vision, match, embed" % action)
    return {"response": outputs.get("out"), "intent": prompt}, "%s: %s" % (action, shown)


def skill_wrap(params: Mapping[str, object], feeds: Mapping[str, object]):
    """Skill: the saved skill this card names, as its instructions text."""
    from .pipeline_engines import skill_read
    name = _text(params, "name")
    if not name:
        raise ValueError("set the name parameter to a saved skill")
    outputs, shown = skill_read({"skill": name}, {})
    return {"result": outputs["out"]}, shown


STEM_EFFECT_ENGINES = {"ai.master": ai_master, "skill.wrap": skill_wrap}

# Library engines that compute over the wired stream alone: no host, no
# network, no model, no file, no shell. The clean shell (which carries no host
# adapter) runs only these and the owner-gated STEM_EFFECT_ENGINES.
PURE_LIBRARY_ENGINES = frozenset({
    "library.filter_field", "library.filter_compare", "library.filter_rule",
    "library.set_field", "library.move", "library.rotate", "library.scale",
    "library.group_by", "library.sort_by", "library.if", "library.switch",
    "library.loop", "library.merge", "library.add_text", "library.dimensions",
    "library.build_schedule", "library.make_legend",
})
MODEL_PICK_ENGINES = MODEL_PICK_ENGINES | {"ai.master"}


# ------------------------------------------------------ one node library --
# The hosts and reads the library offers, with the engines and parameters
# they are placed with. Studio used to type these (and every card title) in
# its own copy (node-registry.jsx AH_LIBRARY); it is served from here now.
LIBRARY_ITEM_ENGINES.update({
    "h_revit": {"engine": "revit.sessions", "params": {}},
    "h_autocad": {"engine": "cad.host_lines", "params": {}},
    "h_max": {"engine": "max.exec", "params": {"code": ""}},
    "h_rhino": {"engine": "rhino.exec", "params": {"code": ""}},
    "h_blender": {"engine": "blender.exec", "params": {"code": ""}},
    "h_excel": {"engine": "office.read", "params": {"operation": "excel.list_workbooks"}},
    "h_word": {"engine": "office.read", "params": {"operation": "word.list_documents"}},
    "h_ppt": {"engine": "office.read", "params": {"operation": "powerpoint.list_presentations"}},
    "h_outlook": {"engine": "outlook.inbox", "params": {"count": "20"}},
    "h_notion": {"engine": "notion.search", "params": {"query": ""}},
    "h_dropbox": {"engine": "dropbox.list", "params": {"path": ""}},
    "h_speckle": {"engine": "library.push_speckle",
                  "params": dict(LIBRARY_ITEM_ENGINES["o_spk"]["params"])},
    "r_walls": {"engine": "revit.read", "params": {"operation": "revit.list_walls"}},
    "r_doors": {"engine": "revit.read", "params": {"operation": "revit.list_doors"}},
    "r_windows": {"engine": "revit.read", "params": {"operation": "revit.list_windows"}},
    "r_sheets": {"engine": "revit.read", "params": {"operation": "revit.list_sheets"}},
    "r_views": {"engine": "revit.read", "params": {"operation": "revit.list_views"}},
    "r_levels": {"engine": "revit.read", "params": {"operation": "revit.list_levels"}},
    "r_selection": {"engine": "revit.read", "params": {"operation": "revit.get_selection"}},
    "r_warnings": {"engine": "revit.read", "params": {"operation": "revit.list_warnings"}},
    "r_xl_sheets": {"engine": "office.read", "params": {"operation": "excel.list_worksheets"}},
    "r_xl_range": {"engine": "office.read",
                   "params": {"operation": "excel.read_range", "file": "", "sheet": "Sheet1", "range": "A1:B10"}},
    "r_doc_paras": {"engine": "office.read", "params": {"operation": "word.list_paragraphs"}},
    "r_ppt_slides": {"engine": "office.read", "params": {"operation": "powerpoint.list_slides"}},
    "tr_manual": {"engine": "trigger.emit", "params": {}},
    "tr_schedule": {"engine": "trigger.schedule", "params": {"schedule": "every day 08:00", "every_seconds": "300", "daily_at": "08:00"}},
    "tr_file": {"engine": "trigger.file", "params": {"folder": "", "pattern": "*.*", "debounce_seconds": "5"}},
    "tr_host": {"engine": "trigger.host", "params": {"event": "revit.document_saved"}},
    "tr_approval": {"engine": "trigger.approval", "params": {"grant_id": "revit-write"}},
    "tr_webhook": {"engine": "trigger.webhook", "params": {"url": "", "token": ""}},
    "l_foreach": {"engine": "control.foreach", "params": {"items": ""}},
})

LIBRARY_ITEM_ENGINES.update({
    "n_number": {"engine": "data.constant",
                 "params": {"value": "0", "min": "", "max": ""}},
    "n_text": {"engine": "data.constant", "params": {"value": ""}},
    "n_list": {"engine": "data.list", "params": {"value": "[1, 2, 3]"}},
    "n_yesno": {"engine": "data.constant", "params": {"value": "false"}},
    "n_file": {"engine": "data.constant", "params": {"value": "", "extensions": ""}},
    "n_colour": {"engine": "data.constant", "params": {"value": "#d97757"}},
    "n_parameter": {"engine": "input.parameter",
                    "params": {"name": "parameter", "type": "any", "default": ""}},
    "n_slider": {"engine": "input.slider",
                 "params": {"min": "0", "max": "100", "step": "1", "value": "50"}},
    "n_run": {"engine": "trigger.emit", "params": {}},
    "h_read": {"engine": "host.read",
               "params": {"host": "Revit", "operation": "List walls", "view": "active"}},
    "b_all_category": {"engine": "revit.elements_of_category",
                       "params": {"category": "Walls", "scope": "document"}},
    "b_get_parameter": {"engine": "revit.get_parameter",
                        "params": {}},
    "s_filter": {"engine": "shape.filter",
                 "params": {"predicate": "item.height > 3000", "mode": "keep"}},
    "s_map": {"engine": "shape.map", "params": {"expression": "item"}},
    "s_sort": {"engine": "shape.sort",
               "params": {"by": "name", "direction": "asc"}},
    "s_group": {"engine": "shape.group", "params": {"by": "category"}},
    "s_unique": {"engine": "shape.unique", "params": {}},
    "s_pluck": {"engine": "shape.pluck", "params": {"field": "name"}},
    "s_count": {"engine": "shape.count", "params": {}},
    "s_slice": {"engine": "shape.slice", "params": {"count": "10", "from": "start"}},
    "s_flatten": {"engine": "shape.flatten", "params": {}},
    "s_join": {"engine": "shape.concat", "params": {}},
    "t_set_field": {"engine": "library.set_field",
                    "params": {"field": "", "value": ""}},
    "t_move_handoff": {"engine": "library.move",
                       "params": {"dx": "0", "dy": "0", "dz": "0"}},
    "t_rotate_handoff": {"engine": "library.rotate",
                         "params": {"degrees": "0", "cx": "0", "cy": "0"}},
    "t_scale_handoff": {"engine": "library.scale",
                        "params": {"factor": "1", "cx": "0", "cy": "0"}},
    "l_if_handoff": {"engine": "control.if", "params": {"condition": ""}},
    "l_switch_handoff": {"engine": "control.switch",
                         "params": {"key": "a", "cases": "a, b, c"}},
    "l_loop_handoff": {"engine": "control.foreach", "params": {}},
    "l_merge_handoff": {"engine": "control.merge", "params": {}},
    "d_add_text": {"engine": "library.add_text",
                   "params": {"text": "", "x": "0", "y": "0"}},
    "d_dimensions": {"engine": "library.dimensions",
                     "params": {"style": "aligned", "offset": "0"}},
    "d_tag_rooms": {"engine": "library.tag_rooms", "params": {}},
    "d_place_tags": {"engine": "library.place_tags",
                     "params": {"category": "Doors", "leader": "true"}},
    "d_place_sheet": {"engine": "library.place_on_sheet",
                      "params": {"sheet": "", "views": ""}},
    "d_schedule": {"engine": "library.build_schedule", "params": {"columns": ""}},
    "d_legend": {"engine": "library.make_legend", "params": {"by": "type"}},
    "text_ops": {"engine": "text.ops",
                 "params": {"operation": "replace", "text": "", "pattern": "", "replacement": "",
                            "separator": ",", "template": "{value}", "width": "0", "fill": " "}},
    "math_expression": {"engine": "math.expression",
                        "params": {"expression": "a + b", "a": "0", "b": "0"}},
    "math_series": {"engine": "math.series",
                    "params": {"start": "0", "step": "1", "count": "10"}},
    "ai_master": {"engine": "ai.master",
                  "params": {"action": "think", "model": "", "prompt": ""}},
    "ai_recall": {"engine": "brain.recall", "params": {"query": "", "limit": "5"}},
    "g_remember": {"engine": "brain.remember",
                   "params": {"text": "", "source": "nodeslib"}},
    "g_dryrun_diff": {"engine": "archhub.dry_run_diff",
                      "params": {"changes": "[]"}},
    "g_host_health": {"engine": "host.health", "params": {"host": ""}},
    "g_evidence_attach": {"engine": "evidence.attach", "params": {"path": ""}},
    "g_approval_gate": {"engine": "approval.gate",
                        "params": {"operation": "revit.write", "scope": "revit.write"}},
    "g_rule_check": {"engine": "library.rule_check",
                     "params": {"parameter": "height", "operator": ">", "value": "3000"}},
    "b_set_parameter": {"engine": "revit.set_parameter_by_name",
                        "params": {}},
    "f_write_table": {"engine": "excel.write_range",
                      "params": {"format": "xlsx", "sheet": "Sheet1", "range": "A1"}},
    "b_create_sheets": {"engine": "revit.create_sheets", "params": {}},
    "b_renumber": {"engine": "revit.renumber_rename",
                   "params": {}},
    "w_watch": {"engine": "watch.preview", "params": {"as": "table"}},
    "o_result": {"engine": "output.parameter", "params": {"name": "result"}},
    "o_skill_handoff": {"engine": "library.save_skill",
                        "params": {"name": "", "path": "", "description": ""}},
    "o_pdf_handoff": {"engine": "library.publish_pdf",
                      "params": {"sheets": "", "folder": ""}},
    "o_email_handoff": {"engine": "library.draft_email",
                        "params": {"to": "", "subject": ""}},
    "o_notify_handoff": {"engine": "library.notify",
                         "params": {"notice_title": "ArchHub", "message": ""}},
    "o_speckle_send": {"engine": "speckle.send",
                       "params": {"project": "", "branch": "main"}},
    "n_note": {"engine": "note", "params": {"text": ""}},
    "n_reroute": {"engine": "reroute", "params": {}},
    "sk_skill": {"engine": "skill.wrap", "params": {"name": "untitled skill"}},
})

# How each card is listed: category, then (item, title, one-line summary).
# This is the handoff catalogue, reconciled to executable engines in this build.
LIBRARY_PRESENTATION = (
    ("trigger", (
        ("tr_manual", "Manual run", "starts when you press Run"),
        ("tr_schedule", "Schedule", "clock trigger"),
        ("tr_file", "File change", "folder and pattern watcher"),
        ("tr_host", "Host event", "event from Revit or another host"),
        ("tr_approval", "Approval", "runs after approval grant"),
        ("tr_webhook", "Webhook", "read-only URL trigger"),
    )),
    ("input", (
        ("n_number", "Number", "A number the graph holds"),
        ("n_text", "Text", "A text the graph holds"),
        ("n_list", "List", "A list, as JSON or comma-separated"),
        ("n_yesno", "Yes / No", "True or false"),
        ("n_file", "File", "A local file value"),
        ("n_colour", "Colour", "A hex colour value"),
        ("n_parameter", "Parameter", "Set by whoever runs this graph"),
        ("n_slider", "Slider", "A bounded numeric input"),
        ("n_run", "Run button", "Starts the graph when you press Run"),
    )),
    ("host", (
        ("h_read", "Read from host", "Ask a connected host for elements"),
        ("r_xl_range", "Excel read range", "Rows from a fixture workbook range"),
        ("b_all_category", "All elements of category", "Read elements by Revit category"),
        ("b_get_parameter", "Get parameter by name", "Read a named parameter from elements"),
        ("b_set_parameter", "Set parameter by name", "Write a named parameter after approval"),
        ("b_create_sheets", "Create sheets", "Create sheets from approved rows"),
        ("b_renumber", "Renumber", "Renumber or rename approved elements"),
    )),
    ("shape", (
        ("s_filter", "Filter", "Keep or drop items by a rule"),
        ("s_map", "Map", "Change each item by an expression"),
        ("s_sort", "Sort", "Order items by a field"),
        ("s_group", "Group by", "Group items by a field"),
        ("s_unique", "Unique", "Drop duplicate items"),
        ("s_pluck", "Pluck", "Take one field from each item"),
        ("s_count", "Count", "How many items"),
        ("s_slice", "Slice", "First or last N items"),
        ("s_flatten", "Flatten", "Nested lists into one"),
        ("s_join", "Join lists", "Join lists end to end"),
    )),
    ("transform", (
        ("t_set_field", "Set field", "Write a value onto every item"),
        ("t_move_handoff", "Move", "Translate coordinates in millimetres"),
        ("t_rotate_handoff", "Rotate", "Turn coordinates about a centre"),
        ("t_scale_handoff", "Scale", "Scale coordinates about a centre"),
    )),
    ("logic", (
        ("l_if_handoff", "If", "Route by a rule"),
        ("l_foreach", "Batch", "Batch over a list"),
        ("l_switch_handoff", "Switch", "Route by a key"),
        ("l_loop_handoff", "For each", "Iterate a list"),
        ("l_merge_handoff", "Merge", "Merge streams"),
    )),
    ("document", (
        ("d_add_text", "Add text", "A text note in the stream"),
        ("d_dimensions", "Dimensions", "One dimension per line"),
        ("d_tag_rooms", "Tag rooms", "Tag every untagged room"),
        ("d_place_tags", "Place tags", "Tag every untagged element"),
        ("d_place_sheet", "Place on sheet", "Put named views on a sheet"),
        ("d_schedule", "Schedule", "A table from the stream"),
        ("d_legend", "Legend", "One entry per symbol"),
    )),
    ("file", (
        ("f_write_table", "Write Excel / CSV", "Write rows to an Excel or CSV file"),
    )),
    ("text", (
        ("text_ops", "Text ops", "Replace, split, join, format or pad text"),
    )),
    ("math", (
        ("math_expression", "Expression", "Safe numeric expression"),
        ("math_series", "Series", "Start, step and count"),
    )),
    ("ai", (
        ("ai_master", "AI", "Ask a model"),
        ("ai_recall", "Recall", "What the Brain remembers for a query"),
    )),
    ("governance", (
        ("g_remember", "Remember", "Write back to Brain"),
        ("g_dryrun_diff", "Dry-run diff", "Show proposed changes without applying them"),
        ("g_host_health", "Host health probe", "Read connector health"),
        ("g_evidence_attach", "Evidence attach", "Attach file hashes as evidence"),
        ("g_approval_gate", "Approval gate", "Hold data until approved"),
        ("g_rule_check", "Rule check", "Pass/fail report from a rule"),
    )),
    ("watch", (
        ("w_watch", "Watch", "See what flows through"),
    )),
    ("output", (
        ("o_result", "Result", "What this graph returns"),
        ("o_skill_handoff", "Save as skill", "Save this run as a skill file"),
        ("o_pdf_handoff", "Publish PDF", "Export sheets from open Revit"),
        ("o_email_handoff", "Email draft", "A draft in open Outlook"),
        ("o_notify_handoff", "Notify", "A desktop notification"),
        ("o_speckle_send", "Send to Speckle", "Send elements to Speckle"),
    )),
    ("note", (
        ("n_note", "Note", "Words on the canvas"),
        ("n_reroute", "Reroute", "A dot a wire passes through"),
    )),
    ("skill", (
        ("sk_skill", "Skill", "A saved graph as one node"),
    )),
)


# Stable placement bindings from the pre-consolidation catalogue. These seed
# compatibility metadata in Cells; the visible catalogue remains LIBRARY_PRESENTATION.
LEGACY_LIBRARY_ITEM_ENGINES = {'a_dims': {'engine': 'library.dimensions', 'params': {'offset': '0', 'style': 'aligned'}},
 'a_rooms': {'engine': 'library.tag_rooms', 'params': {}},
 'a_tags': {'engine': 'library.place_tags', 'params': {'category': 'Doors', 'leader': 'true'}},
 'a_text': {'engine': 'library.add_text', 'params': {'text': '', 'x': '0', 'y': '0'}},
 'c_legend': {'engine': 'library.make_legend', 'params': {'by': 'type'}},
 'c_sched': {'engine': 'library.build_schedule', 'params': {'columns': ''}},
 'c_sheet': {'engine': 'library.place_on_sheet', 'params': {'sheet': '', 'views': ''}},
 'f_cat': {'engine': 'library.filter_field', 'params': {'field': 'category', 'mode': 'keep', 'value': ''}},
 'f_level': {'engine': 'library.filter_field', 'params': {'field': 'level', 'mode': 'keep', 'value': ''}},
 'f_param': {'engine': 'library.filter_compare',
             'params': {'field': '', 'mode': 'keep', 'operator': '==', 'value': ''}},
 'f_pred': {'engine': 'library.filter_rule', 'params': {'mode': 'keep', 'rule': ''}},
 'f_type': {'engine': 'library.filter_field', 'params': {'field': 'type', 'mode': 'keep', 'value': ''}},
 'h_autocad': {'engine': 'cad.host_lines', 'params': {}},
 'h_blender': {'engine': 'blender.exec', 'params': {'code': ''}},
 'h_dropbox': {'engine': 'dropbox.list', 'params': {'path': ''}},
 'h_excel': {'engine': 'office.read', 'params': {'operation': 'excel.list_workbooks'}},
 'h_max': {'engine': 'max.exec', 'params': {'code': ''}},
 'h_notion': {'engine': 'notion.search', 'params': {'query': ''}},
 'h_outlook': {'engine': 'outlook.inbox', 'params': {'count': '20'}},
 'h_ppt': {'engine': 'office.read', 'params': {'operation': 'powerpoint.list_presentations'}},
 'h_revit': {'engine': 'revit.sessions', 'params': {}},
 'h_rhino': {'engine': 'rhino.exec', 'params': {'code': ''}},
 'h_speckle': {'engine': 'library.push_speckle',
               'params': {'branch': 'archhub/main', 'message': 'ArchHub push', 'project': '', 'server': ''}},
 'h_word': {'engine': 'office.read', 'params': {'operation': 'word.list_documents'}},
 'i_embed': {'engine': 'library.embed', 'params': {'query': ''}},
 'i_match': {'engine': 'library.match_skill', 'params': {'count': '3', 'intent': ''}},
 'i_think': {'engine': 'library.think', 'params': {'max_tokens': '600', 'model': '', 'prompt': ''}},
 'i_vis': {'engine': 'library.vision',
           'params': {'image_path': '', 'max_tokens': '600', 'model': '', 'prompt': ''}},
 'l_if': {'engine': 'library.if', 'params': {'rule': ''}},
 'l_loop': {'engine': 'library.loop', 'params': {}},
 'l_merge': {'engine': 'library.merge', 'params': {'mode': 'concat'}},
 'l_switch': {'engine': 'library.switch', 'params': {'cases': 'a, b, c', 'key': 'a'}},
 'o_email': {'engine': 'library.draft_email', 'params': {'body': '', 'subject': '', 'to': ''}},
 'o_notify': {'engine': 'library.notify', 'params': {'message': '', 'notice_title': 'ArchHub'}},
 'o_pdf': {'engine': 'library.publish_pdf', 'params': {'folder': '', 'sheets': ''}},
 'o_skill': {'engine': 'library.save_skill', 'params': {'description': '', 'name': '', 'path': ''}},
 'o_spk': {'engine': 'library.push_speckle',
           'params': {'branch': 'archhub/main', 'message': 'ArchHub push', 'project': '', 'server': ''}},
 'o_term': {'engine': 'library.terminal', 'params': {'command': '', 'cwd': ''}},
 'r_doc_paras': {'engine': 'office.read', 'params': {'operation': 'word.list_paragraphs'}},
 'r_doors': {'engine': 'revit.read', 'params': {'operation': 'revit.list_doors'}},
 'r_levels': {'engine': 'revit.read', 'params': {'operation': 'revit.list_levels'}},
 'r_ppt_slides': {'engine': 'office.read', 'params': {'operation': 'powerpoint.list_slides'}},
 'r_selection': {'engine': 'revit.read', 'params': {'operation': 'revit.get_selection'}},
 'r_sheets': {'engine': 'revit.read', 'params': {'operation': 'revit.list_sheets'}},
 'r_views': {'engine': 'revit.read', 'params': {'operation': 'revit.list_views'}},
 'r_walls': {'engine': 'revit.read', 'params': {'operation': 'revit.list_walls'}},
 'r_warnings': {'engine': 'revit.read', 'params': {'operation': 'revit.list_warnings'}},
 'r_windows': {'engine': 'revit.read', 'params': {'operation': 'revit.list_windows'}},
 'r_xl_sheets': {'engine': 'office.read', 'params': {'operation': 'excel.list_worksheets'}},
 't_group': {'engine': 'library.group_by', 'params': {'by': ''}},
 't_move': {'engine': 'library.move', 'params': {'dx': '0', 'dy': '0', 'dz': '0'}},
 't_rot': {'engine': 'library.rotate', 'params': {'cx': '0', 'cy': '0', 'degrees': '0'}},
 't_scale': {'engine': 'library.scale', 'params': {'cx': '0', 'cy': '0', 'factor': '1'}},
 't_setp': {'engine': 'library.set_field', 'params': {'field': '', 'value': ''}},
 't_sort': {'engine': 'library.sort_by', 'params': {'by': '', 'direction': 'asc'}},
 'tool_baboom': {'engine': 'tool.baboom',
                 'params': {'start_with_archhub': True, 'tool': 'baboom'}},
 'tool_brain': {'engine': 'tool.brain', 'params': {'tool': 'brain'}},
 'tool_cloud': {'engine': 'tool.cloud', 'params': {'tool': 'cloud'}},
 'tool_connectors': {'engine': 'tool.connectors', 'params': {'tool': 'connectors'}},
 'tool_studio': {'engine': 'tool.studio', 'params': {'tool': 'studio'}},
 'tool_workshop': {'engine': 'tool.workshop',
                   'params': {'archive_after_idle_days': '20',
                              'stale_claim_after_idle_minutes': '30',
                              'tool': 'workshop'}}}
LEGACY_LIBRARY_PRESENTATION = (('host',
  (('h_revit', 'Revit', 'live sessions on this machine'),
   ('h_autocad', 'AutoCAD', 'line work from the live drawing'),
   ('h_max', '3ds Max', 'MAXScript / Python in the open scene'),
   ('h_rhino', 'Rhino', 'RhinoPython in the open model'),
   ('h_blender', 'Blender', 'Python in the open scene'),
   ('h_excel', 'Excel', 'open workbooks and their sheets'),
   ('h_word', 'Word', 'open documents and their paragraphs'),
   ('h_ppt', 'PowerPoint', 'open decks and their slides'),
   ('h_outlook', 'Outlook', 'the inbox, newest first'),
   ('h_notion', 'Notion', 'search your workspace'),
   ('h_dropbox', 'Dropbox', 'files in your Dropbox folder'),
   ('h_speckle', 'Speckle', 'commit the wired rows to a branch'))),
 ('read',
  (('r_walls', 'list_walls', 'pull walls from active view'),
   ('r_doors', 'list_doors', 'pull doors + swings + marks'),
   ('r_windows', 'list_windows', 'pull windows + types'),
   ('r_sheets', 'list_sheets', 'enumerate sheets in set'),
   ('r_views', 'list_views', 'plans, sections, schedules'),
   ('r_levels', 'list_levels', 'levels + elevations'),
   ('r_selection', 'get_selection', 'whatever is selected in host'),
   ('r_warnings', 'list_warnings', 'host warnings · by severity'),
   ('r_xl_sheets', 'excel worksheets', 'sheets of the workbook in front'),
   ('r_doc_paras', 'word paragraphs', 'paragraphs of the document in front'),
   ('r_ppt_slides', 'powerpoint slides', 'slides of the deck in front'))),
 ('filter',
  (('f_type', 'where type', 'by family/type'),
   ('f_cat', 'where category', 'by Revit category'),
   ('f_level', 'where level', 'by level reference'),
   ('f_param', 'where parameter', 'predicate on a parameter'),
   ('f_pred', 'where custom', 'a comparison rule, e.g. item.height >= 3000'))),
 ('transform',
  (('t_setp', 'set parameter', 'sets a field on the stream'),
   ('t_move', 'move', 'translation'),
   ('t_rot', 'rotate', 'rotation'),
   ('t_scale', 'scale', 'uniform'),
   ('t_group', 'group by', 'key → list'),
   ('t_sort', 'sort by', 'asc / desc on key'))),
 ('annotate',
  (('a_dims', 'create_dimensions', 'aligned, parallel, baseline'),
   ('a_tags', 'place_tags', 'tag every untagged element of a category'),
   ('a_text', 'add_text', 'text note · positioned'),
   ('a_rooms', 'tag_rooms', 'tag every untagged room in the view'))),
 ('compose',
  (('c_sched', 'build_schedule', 'table from a stream'),
   ('c_sheet', 'place_on_sheet', 'named views onto a sheet'),
   ('c_legend', 'make_legend', 'symbol legend block'))),
 ('logic',
  (('l_if', 'if', 'rule → out (true) / false branches'),
   ('l_switch', 'switch', 'key → branch a / b / c by its cases'),
   ('l_loop', 'loop', 'iterate a list: each (first) and out (all)'),
   ('l_merge', 'merge', 'concat / dedupe streams in + b'))),
 ('ai',
  (('i_think', 'think', 'reason with the picked model'),
   ('i_vis', 'vision', 'read a sketch / screenshot with the picked model'),
   ('i_match', 'match_skill', 'best saved skill for an intent'),
   ('i_embed', 'embed', 'similar facts from the brain'))),
 ('workshop',
  (('w_workshop', 'Workshop', 'this conversation; routes wired agents into it'),
   ('w_agent', 'Agent session', 'one live native session through Session Link'),
   ('w_review', 'Independent review', 'a different agent reviews the wired artifact'))),
 ('tools',
  (('tool_studio', 'Studio', 'canvas and session workspace settings'),
   ('tool_workshop', 'Workshop', 'projects, tasks and governed work settings'),
   ('tool_brain', 'Brain', 'memory, facts and recall settings'),
   ('tool_baboom', 'BABOOM', 'desktop companion settings'),
   ('tool_connectors', 'Connectors', 'host bridge settings'),
   ('tool_cloud', 'Cloud', 'account, devices and relay settings'))),
 ('output',
  (('o_skill', 'save_skill', 'template this run'),
   ('o_pdf', 'publish_pdf', 'sheets → PDF files via the live Revit'),
   ('o_spk', 'push_speckle', 'commit the wired rows to a branch'),
   ('o_email', 'draft_email', 'draft in Outlook · you send'),
   ('o_notify', 'notify', 'desktop notification'),
   ('o_term', 'terminal', 'a shell in a folder this ArchHub admits'))))
for _legacy_item, _legacy_row in WORKSHOP_CATALOGUE.items():
    LEGACY_LIBRARY_ITEM_ENGINES.setdefault(_legacy_item, {
        "engine": _legacy_row["engine"], "params": dict(_legacy_row["params"])})
for _legacy_item, _legacy_binding in LEGACY_LIBRARY_ITEM_ENGINES.items():
    LIBRARY_ITEM_ENGINES.setdefault(_legacy_item, _legacy_binding)


def library_catalogue() -> list:
    """Canonical cards plus hidden compatibility bindings for exact old IDs.

    Every row is seeded into the same graph. Ordinary projections omit hidden
    rows before counts/search/rendering; explicit old placements keep their IDs.
    """
    from .pipeline_engines import PIPELINE_ENGINES
    visible_ids = {item for _category, rows in LIBRARY_PRESENTATION for item, _title, _summary in rows}
    legacy_rows = {item: (category, title, summary)
                   for category, rows in LEGACY_LIBRARY_PRESENTATION
                   for item, title, summary in rows}
    sections = {category: list(rows) for category, rows in LIBRARY_PRESENTATION}
    for item, wiring in LIBRARY_ITEM_ENGINES.items():
        if item not in visible_ids:
            category, title, summary = legacy_rows.get(item, ("compatibility", item, "Existing graph placement binding"))
            sections.setdefault(category, []).append((item, title, summary))
    groups = []
    for category, rows in sections.items():
        items = []
        for item, title, summary in rows:
            wiring = LIBRARY_ITEM_ENGINES.get(item)
            if wiring is None:
                continue
            entry = {
                "id": item, "cat": category, "title": title, "sub": summary,
                "engine": wiring["engine"], "params": dict(wiring["params"]),
                "sockets": {side: list(names) for side, names in engine_sockets(wiring["engine"]).items()},
                "ports": library_item_ports(item, wiring["engine"], title),
            }
            if item not in visible_ids:
                entry["hidden"] = True
            legacy = LEGACY_LIBRARY_ITEM_ENGINES.get(item)
            if legacy is not None and legacy != wiring:
                entry["compatibility"] = {legacy["engine"]: {
                    "engine": legacy["engine"], "params": dict(legacy["params"])}}
            reason = LIBRARY_ITEMS_WITHOUT_ENGINE.get(item)
            if not engine_runs(wiring["engine"], PIPELINE_ENGINES) or reason:
                entry["noEngine"] = True
                entry["reason"] = reason or "engine %s is not in this build" % wiring["engine"]
            items.append(entry)
        groups.append({"cat": category, "items": items})
    return groups


def _base_catalogue_interfaces() -> dict:
    """(name, engine) -> declared base catalogue interfaces."""
    from .base_universal_catalogue import BASE_CATALOGUE
    out = {}
    for entry in BASE_CATALOGUE:
        engine = entry.get("engine")
        name = entry.get("name")
        if not engine or not name:
            continue
        out[(str(name).casefold(), str(engine))] = dict(entry.get("interfaces") or {})
    return out

def _interface_ports(interfaces: Mapping[str, object], sockets: Mapping[str, object]) -> dict:
    by_side = {"source": [], "target": []}
    for name, spec in (interfaces or {}).items():
        if not isinstance(spec, Mapping):
            spec = {}
        direction = str(spec.get("direction") or "").lower()
        side = "source" if direction in ("output", "out", "source") else "target"
        type_name = str(spec.get("type") or spec.get("logical_type") or "any")
        cardinality = "many" if spec.get("multiple") or type_name == "list" else "one"
        by_side[side].append({
            "id": str(name),
            "type": type_name,
            "cardinality": cardinality,
        })
    known = {side: {port["id"] for port in ports} for side, ports in by_side.items()}
    for side, names in sockets.items():
        for name in names:
            if str(name) not in known[side]:
                by_side[side].append({
                    "id": str(name),
                    "type": "unknown",
                    "cardinality": "unknown",
                })
    return by_side

def library_item_ports(item: str, engine: str, title: str = "") -> dict:
    """Projected port metadata: id, type and cardinality for the library card."""
    sockets = engine_sockets(engine)
    interfaces = _base_catalogue_interfaces().get((str(title or "").casefold(), str(engine or "")), {})
    if engine == 'research.weighted':
        interfaces = {'in':{'type':'list','direction':'input'},'criteria':{'type':'list','direction':'input'},
                      'out':{'type':'list','direction':'output'}}
    return _interface_ports(interfaces, sockets)


def engine_categories(groups=None) -> dict:
    """engine -> the category its card is drawn in, for every engine this build runs.

    A library card's category is its own; an engine no card lists (the seed's
    sketch, CAD, watch, walls, brain and BABOOM cards) is placed by its family.
    """
    from .pipeline_engines import PIPELINE_ENGINES
    held = {}
    if groups is not None:
        # The served library (graph relations) decides a card's category.
        for group in groups:
            for entry in group.get("items") or ():
                held.setdefault(entry["engine"], group["cat"])
    else:
        for category, rows in LIBRARY_PRESENTATION:
            for item, _title, _summary in rows:
                if item in LIBRARY_ITEM_ENGINES:
                    held.setdefault(LIBRARY_ITEM_ENGINES[item]["engine"], category)
    families = (
        (("vision.", "cad."), "read"), (("lines.",), "annotate"),
        (("revit.",), "host"), (("brain.", "ai.", "baboom."), "ai"),
        (("tool.",), "tools"), (("trigger.",), "trigger"),
    )
    for engine in sorted(
        set(PIPELINE_ENGINES) | STEM_RUN_ENGINES | {"baboom.status", "baboom.presence"}
    ):
        if engine in held:
            continue
        held[engine] = next(
            (category for prefixes, category in families if engine.startswith(prefixes)),
            "logic")
    return held


__all__ = [
    "LIBRARY_ENGINES",
    "set_notify_surface",
    "engine_categories",
    "LIBRARY_ITEM_ENGINES",
    "LIBRARY_ITEMS_WITHOUT_ENGINE",
    "ENGINE_SOCKETS",
    "STEM_EFFECT_ENGINES",
    "engine_sockets",
    "library_catalogue",
]


# Compatibility names share the NODES engine implementation and verifier state.
from . import nodeslib_v2_engines as _nodeslib  # noqa: E402
_digest_payload = _nodeslib._digest_payload
_params_with_wired_grant = _nodeslib._params_with_wired_grant
_verified_write_grant = _nodeslib._verified_write_grant
_require_grant = _nodeslib._require_grant
_require_file_grant = _nodeslib._require_file_grant
_confirmed_write = _nodeslib._confirmed_write
_revit = _nodeslib._revit
revit_elements_of_category = _nodeslib.revit_elements_of_category
revit_get_parameter = _nodeslib.revit_get_parameter
revit_set_parameter = _nodeslib.revit_set_parameter
revit_create_sheets = _nodeslib.revit_create_sheets
revit_renumber_rename = _nodeslib.revit_renumber_rename
write_table_file = _nodeslib.write_table_file
approval_gate = _nodeslib.approval_gate

# HOME3: the ordinary pipeline owns package publication; signed grants and the
# existing file broker remain mandatory, including when run from Workshop.
LIBRARY_ENGINES["library.publish_package"] = _nodeslib.publish_package
ENGINE_SOCKETS["library.publish_package"] = {"source": ("out", "folder", "receipt"), "target": ("grant",)}

# Appended identities keep every existing saved catalogue placement stable.
from .enforce import engine as _enforce_engine, defaults as _enforce_defaults
LIBRARY_ENGINES["archhub.enforce"] = _enforce_engine
LIBRARY_ITEM_ENGINES["archhub_enforce"] = {"engine": "archhub.enforce", "params": _enforce_defaults()}
ENGINE_SOCKETS["archhub.enforce"] = {
    "source": ("admitted", "diagnostics", "out"),
    "target": ("pending", *_enforce_defaults()),
}
LIBRARY_PRESENTATION = LIBRARY_PRESENTATION + (("enforce", (("archhub_enforce", "Enforce", "Check pending writes; correct compiler diagnostics before approval"),)),)
LIBRARY_ITEM_ENGINES['research_valuation'] = {'engine':'research.weighted','params':{'criteria':'[]'}}
LIBRARY_PRESENTATION = LIBRARY_PRESENTATION + (('logic', (('research_valuation','Weighted valuation','Score wired rows using explicit numeric criteria and weights'),)),)
