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

from .stem_graph_evaluation import (
    as_list,
    coerce_parameter,
    item_field,
    run_stem_operation,
)

_OPERATORS = (">=", "<=", "!=", "==", ">", "<")

_EMPTY_LIST = "nothing is wired in"


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
    """if: the wired value passes only when the predicate holds.

    A wire carries one output, so the false branch is an empty answer whose
    card says which way the test went, never a value on both sides.
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
    return {}, "false - nothing passed"


def branch_switch(params: Mapping[str, object], feeds: Mapping[str, object]):
    """switch: name the branch a key selects and pass the value along it."""
    value = _wired(feeds, "in", "value")
    if value is None:
        return {}, _EMPTY_LIST
    key = feeds.get("key")
    if key is None:
        key = _text(params, "key", "a") or "a"
    produced, shown = run_stem_operation(
        "control.switch", {}, {"value": value, "key": key})
    taken = next(iter(produced))
    return {"out": produced[taken]}, "branch %s" % (shown or taken)


def loop(params: Mapping[str, object], feeds: Mapping[str, object]):
    """loop: iterate a wired list, one item at a time, downstream."""
    rows = _rows(feeds)
    if not rows:
        return {"out": []}, _EMPTY_LIST
    produced, shown = run_stem_operation("control.foreach", {}, {"items": rows})
    return {"out": produced["results"], "each": produced["each"]}, shown


def merge(params: Mapping[str, object], feeds: Mapping[str, object]):
    """merge: concat the wired streams, and dedupe them when asked."""
    rows = _rows(feeds)
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


LIBRARY_ENGINES = {
    "library.filter_field": filter_field,
    "library.filter_compare": filter_compare,
    "library.filter_rule": filter_rule,
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

# Which library card each engine answers, and the parameters that card is
# placed with. The studio owner reads this to give every listed item an
# engine; until it does, these cards still vanish when they are dropped.
LIBRARY_ITEM_ENGINES = {
    "f_type": {"engine": "library.filter_field",
               "params": {"field": "type", "value": "", "mode": "keep"}},
    "f_cat": {"engine": "library.filter_field",
              "params": {"field": "category", "value": "", "mode": "keep"}},
    "f_level": {"engine": "library.filter_field",
                "params": {"field": "level", "value": "", "mode": "keep"}},
    "f_param": {"engine": "library.filter_compare",
                "params": {"field": "", "operator": "==", "value": "",
                           "mode": "keep"}},
    "f_pred": {"engine": "library.filter_rule",
               "params": {"rule": "", "mode": "keep"}},
    "t_setp": {"engine": "library.set_field",
               "params": {"field": "", "value": ""}},
    "t_move": {"engine": "library.move",
               "params": {"dx": "0", "dy": "0", "dz": "0"}},
    "t_rot": {"engine": "library.rotate",
              "params": {"degrees": "0", "cx": "0", "cy": "0"}},
    "t_scale": {"engine": "library.scale",
                "params": {"factor": "1", "cx": "0", "cy": "0"}},
    "t_group": {"engine": "library.group_by", "params": {"by": ""}},
    "t_sort": {"engine": "library.sort_by",
               "params": {"by": "", "direction": "asc"}},
    "l_if": {"engine": "library.if", "params": {"rule": ""}},
    "l_switch": {"engine": "library.switch", "params": {"key": "a"}},
    "l_loop": {"engine": "library.loop", "params": {}},
    "l_merge": {"engine": "library.merge", "params": {"mode": "concat"}},
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


def think(params: Mapping[str, object], feeds: Mapping[str, object]):
    """Reason with the picked model over the wired stream; never a hidden default."""
    import os
    from . import model_router
    from .agent_composer import NO_MODEL_CHOSEN
    route = _text(params, "model") or os.environ.get("ARCHHUB_AGENT_MODEL", "").strip()
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
        answer = model_router.route_chat(route, messages, max_tokens=int(_number(params, "max_tokens", 600)))
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
    title = _text(params, "title", "ArchHub")
    message = _text(params, "message") or _wired_text(feeds)
    if not message:
        return {"out": []}, "nothing to say: no message, nothing wired in"
    if not _NOTIFY_SURFACE:
        return {"out": message}, "no desktop surface registered; the app registers its tray at boot"
    try:
        _NOTIFY_SURFACE[0](title, message)
    except Exception as failed:
        return {"out": message}, "the desktop refused: %s" % failed
    return {"out": message}, "shown on the desktop: %s" % message[:60]


def _open_outlook():
    """The OPEN Outlook, or None; this never launches it."""
    from .host_brokers import _com_alive
    if not _com_alive("Outlook.Application"):
        return None
    import win32com.client as client  # type: ignore
    return client.GetActiveObject("Outlook.Application")


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
                 "params": {"title": "ArchHub", "message": ""}},
})
for _wired_now in ("i_think", "i_match", "i_embed", "o_email", "o_notify"):
    LIBRARY_ITEMS_WITHOUT_ENGINE.pop(_wired_now, None)


_IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".webp": "image/webp", ".gif": "image/gif"}


def vision(params: Mapping[str, object], feeds: Mapping[str, object]):
    """Read a sketch or screenshot with the picked model; the image travels as a data URL."""
    import base64
    import os
    from pathlib import Path
    from . import model_router
    from .agent_composer import NO_MODEL_CHOSEN
    from .pipeline_engines import _local_input_path
    route = _text(params, "model") or os.environ.get("ARCHHUB_AGENT_MODEL", "").strip()
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
    data = base64.b64encode(Path(path).read_bytes()).decode("ascii")
    prompt = _text(params, "prompt") or (
        "Describe this architectural drawing: rooms, walls, openings, and any "
        "dimensions or text you can read. Millimetres. Be terse.")
    messages = [{"role": "user", "content": [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": "data:%s;base64,%s" % (kind, data)}},
    ]}]
    try:
        answer = model_router.route_chat(route, messages, max_tokens=int(_number(params, "max_tokens", 600)))
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
    from .clean_revit_adapter import _call, live_sessions
    sessions = [s for s in live_sessions() if s.get("revit_version")]
    if not sessions:
        return {"out": []}, "no Revit session is listening"
    session = sessions[-1]
    held = _wired(feeds, "in", "sheets")
    wanted = [str(item_field(row, "number") or row) for row in as_list(held)] if held is not None else [
        piece.strip() for piece in _text(params, "sheets").split(",") if piece.strip()]
    folder = _text(params, "folder") or os.path.join(
        os.path.expanduser("~"), "Documents", "ArchHub", "pdf", time.strftime("%Y%m%d-%H%M%S"))
    script = _EXPORT_PDF % (json.dumps(folder), ", ".join(json.dumps(number) for number in wanted))
    try:
        answer = _call(session["port"], "/exec", {"code": script, "transaction_name": "ArchHub publish pdf"})
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

def _revit_exec(script: str, transaction: str, params: Mapping[str, object]):
    """One /exec against the newest live Revit session; (session, answer) or (None, why)."""
    from .clean_revit_adapter import _call, live_sessions
    sessions = [s for s in live_sessions() if s.get("revit_version")]
    if not sessions:
        return None, "no Revit session is listening"
    session = sessions[-1]
    try:
        answer = _call(session["port"], "/exec", {"code": script, "transaction_name": transaction})
    except Exception as failed:
        return None, "Revit did not answer: %s" % str(failed)[:160]
    if not isinstance(answer, Mapping) or answer.get("status") != "ok":
        return None, "Revit refused: %s" % (answer.get("error") if isinstance(answer, Mapping) else answer)
    return session, answer.get("result") if isinstance(answer.get("result"), Mapping) else {}


_TAG_ROOMS = """
var view = Doc.ActiveView;
var already = new HashSet<int>();
foreach (Element e in new FilteredElementCollector(Doc, view.Id).OfClass(typeof(SpatialElementTag))) {
    var rt = e as RoomTag; if (rt != null && rt.Room != null) already.Add(rt.Room.Id.IntegerValue);
}
int tagged = 0, skipped = 0;
using (var t = new Transaction(Doc, "ArchHub tag rooms")) {
    t.Start();
    foreach (Element e in new FilteredElementCollector(Doc, view.Id).OfCategory(BuiltInCategory.OST_Rooms).WhereElementIsNotElementType()) {
        var room = e as Room;
        if (room == null || room.Area <= 0 || already.Contains(room.Id.IntegerValue)) { skipped++; continue; }
        var lp = room.Location as LocationPoint;
        if (lp == null) { skipped++; continue; }
        Doc.Create.NewRoomTag(new LinkElementId(room.Id), new UV(lp.Point.X, lp.Point.Y), view.Id);
        tagged++;
    }
    t.Commit();
}
result = new Dictionary<string, object>{ {"tagged", tagged}, {"skipped", skipped}, {"view", view.Name} };
"""


def tag_rooms(params: Mapping[str, object], feeds: Mapping[str, object]):
    """A room tag on every untagged room of the active view, placed at the room point."""
    session, result = _revit_exec(_TAG_ROOMS, "ArchHub tag rooms", params)
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
using (var t = new Transaction(Doc, "ArchHub place tags")) {
    t.Start();
    foreach (Element e in new FilteredElementCollector(Doc, view.Id).OfCategory(bic).WhereElementIsNotElementType()) {
        if (already.Contains(e.Id.IntegerValue)) { skipped++; continue; }
        var bb = e.get_BoundingBox(view); if (bb == null) { skipped++; continue; }
        var c = (bb.Min + bb.Max) / 2;
        IndependentTag.Create(Doc, view.Id, new Reference(e), leader, TagMode.TM_ADDBY_CATEGORY, TagOrientation.Horizontal, c);
        tagged++;
    }
    t.Commit();
}
result = new Dictionary<string, object>{ {"tagged", tagged}, {"skipped", skipped}, {"category", catName}, {"view", view.Name} };
"""


def place_tags(params: Mapping[str, object], feeds: Mapping[str, object]):
    """A tag on every untagged element of one category in the active view, leader optional."""
    import json
    category = _text(params, "category", "Doors")
    leader = _text(params, "leader", "true").casefold() in ("1", "true", "yes", "on")
    script = _PLACE_TAGS % (json.dumps(category), "true" if leader else "false")
    session, result = _revit_exec(script, "ArchHub place tags", params)
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
using (var t = new Transaction(Doc, "ArchHub place on sheet")) {
    t.Start();
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
    t.Commit();
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
    session, result = _revit_exec(script, "ArchHub place on sheet", params)
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
        _speckle_call("%s/objects/%s" % (server, project), [obj], token, opener)
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

__all__ = [
    "LIBRARY_ENGINES",
    "set_notify_surface",
    "LIBRARY_ITEM_ENGINES",
    "LIBRARY_ITEMS_WITHOUT_ENGINE",
]
