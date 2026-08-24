"""Courts for the stem graph evaluator: values flow, refusals are named."""
from nodelang.stem_graph_evaluation import (
    StemNode,
    StemWire,
    evaluate_stem_graph,
)


def _n(root, engine, params=None, **_ignored):
    return StemNode(root, engine, params or {})


def test_a_number_flows_into_a_result():
    ev = evaluate_stem_graph(
        [
            _n("num", "data.constant", {"value": "42"}, outputs=("value",)),
            _n("res", "output.parameter", {"name": "answer"}, inputs=("value",)),
        ],
        [StemWire("num", "value", "res", "value")],
    )
    assert ev.results == {"answer": 42}
    assert ev.display["num"] == "42"
    assert ev.display["res"] == "42"
    assert not ev.pending


def test_watch_passes_through_and_shows_the_value():
    ev = evaluate_stem_graph(
        [
            _n("txt", "data.constant", {"value": "hello"}, outputs=("value",)),
            _n("watch", "watch.preview", {}, inputs=("in",), outputs=("out",)),
            _n("res", "output.parameter", {}, inputs=("value",)),
        ],
        [
            StemWire("txt", "value", "watch", "in"),
            StemWire("watch", "out", "res", "value"),
        ],
    )
    assert ev.display["watch"] == "hello"
    assert ev.results == {"result": "hello"}


def test_if_routes_by_condition_and_merge_picks_the_live_branch():
    ev = evaluate_stem_graph(
        [
            _n("num", "data.constant", {"value": "7"}, outputs=("value",)),
            _n("flag", "data.constant", {"value": "false"}, outputs=("value",)),
            _n("gate", "control.if", {}, inputs=("value", "condition")),
            _n("merge", "control.merge", {}, inputs=("a", "b")),
            _n("res", "output.parameter", {}, inputs=("value",)),
        ],
        [
            StemWire("num", "value", "gate", "value"),
            StemWire("flag", "value", "gate", "condition"),
            StemWire("gate", "false", "merge", "b"),
            StemWire("merge", "value", "res", "value"),
        ],
    )
    assert ev.display["gate"] == "false"
    assert ev.results == {"result": 7}


def test_unrunnable_engines_and_unwired_inputs_are_named_not_guessed():
    ev = evaluate_stem_graph(
        [
            _n("ai", "ai.master", {"prompt": "think"}, outputs=("response",)),
            _n("res", "output.parameter", {}, inputs=("value",)),
        ],
        [StemWire("ai", "response", "res", "value")],
    )
    assert ev.pending["ai"] == "engine ai.master is pending"
    assert ev.pending["res"] == "blocked by ai"
    assert ev.results == {}


def test_a_cycle_is_reported_and_the_rest_still_evaluates():
    ev = evaluate_stem_graph(
        [
            _n("a", "watch.preview", {}, inputs=("in",), outputs=("out",)),
            _n("b", "watch.preview", {}, inputs=("in",), outputs=("out",)),
            _n("num", "data.constant", {"value": "1"}, outputs=("value",)),
            _n("res", "output.parameter", {}, inputs=("value",)),
        ],
        [
            StemWire("a", "out", "b", "in"),
            StemWire("b", "out", "a", "in"),
            StemWire("num", "value", "res", "value"),
        ],
    )
    assert ev.pending["a"] == "cycle" or ev.pending["b"] == "cycle"
    assert ev.results == {"result": 1}
def test_every_graph_held_operation_matches_its_fast_path():
    """SPEC 4.1: a fast path is admitted only where an equivalence court proves
    the generic graph path gives the same result at the same snapshot.

    Each operation in GRAPH_EXPRESSIONS is built as cells -- reading its wired
    inputs by interface name and its own settings under "parameters" -- then
    compared against the Python engine on the same rows and settings.
    """
    import tempfile
    from pathlib import Path

    from nodelang.base_universal_catalogue import GRAPH_EXPRESSIONS
    from nodelang.cell_protocols import CellBatch
    from nodelang.cell_view_template import (
        ViewTemplateBuilder,
        compose_view_template_protocol,
        evaluate_view_expression,
    )
    from nodelang.universal_cell import CellStore

    store = CellStore(Path(tempfile.mkdtemp()) / "equivalence.sqlite3")
    try:
        batch = CellBatch(store)
        protocol = compose_view_template_protocol(batch)
        batch.commit()
        builder = ViewTemplateBuilder(CellBatch(store), protocol)
        built = {}
        for engine, (operation, arguments, output) in GRAPH_EXPRESSIONS.items():
            tag = engine.replace(".", "-")
            root = builder.expression("%s:root" % tag, "root")
            parts = []
            for index, (kind, name) in enumerate(arguments):
                if kind == "in":
                    segment = builder.atom("%s:s%d" % (tag, index), name)
                    parts.append(builder.expression(
                        "%s:a%d" % (tag, index), "path", (root, segment)))
                else:
                    holder = builder.atom("%s:p%d" % (tag, index), "parameters")
                    named = builder.atom("%s:n%d" % (tag, index), name)
                    parts.append(builder.expression(
                        "%s:a%d" % (tag, index), "path", (root, holder, named)))
            built[engine] = (
                builder.expression("%s:e" % tag, operation, tuple(parts)),
                output,
                tuple(name for kind, name in arguments if kind == "in"),
            )
        builder.batch.commit()
        snapshot = store.snapshot()

        def evaluate(expression_root, projection):
            return evaluate_view_expression(
                snapshot, protocol, expression_root, projection
            )

        # One expression per output, which is what the runner takes now.
        table = {
            engine: (evaluate, ((output, expression),), inputs)
            for engine, (expression, output, inputs) in built.items()
        }
        rows = [
            {"name": "b", "size": 2},
            {"name": "a", "size": 9},
            {"name": "b", "size": 1},
        ]
        settings = {
            "field": "name", "by": "size", "direction": "asc",
            "count": "2", "from": "start",
        }
        for engine, (_operation, arguments, output) in GRAPH_EXPRESSIONS.items():
            wired = [name for kind, name in arguments if kind == "in"]
            nodes = [_n("op", engine, settings)]
            wires = []
            for index, name in enumerate(wired):
                nodes.append(_n("src%d" % index, "data.list", {"value": rows}))
                wires.append(StemWire("src%d" % index, "value", "op", name))
            nodes.append(_n("out", "output.parameter", {"name": "answer"}))
            wires.append(StemWire("op", output, "out", "value"))
            graph = evaluate_stem_graph(nodes, wires, graph_expressions=table)
            fast = evaluate_stem_graph(nodes, wires)
            assert not graph.pending, (engine, graph.pending)
            assert graph.results == fast.results, (
                engine, graph.results, fast.results
            )
    finally:
        store.close()
def test_a_branching_operation_routes_from_the_graph_and_matches_the_fast_path():
    """A node whose ports differ by branch says so in the graph too.

    control.if carries the value on "true" or on "false" and says nothing on
    the other; the branch not taken is silent, not empty. Both branches are
    held against the Python engine.
    """
    import tempfile
    from pathlib import Path

    from nodelang.base_universal_catalogue import GRAPH_BRANCHES
    from nodelang.cell_protocols import CellBatch
    from nodelang.cell_view_template import (
        ViewTemplateBuilder,
        compose_view_template_protocol,
        evaluate_view_expression,
    )
    from nodelang.universal_cell import CellStore

    store = CellStore(Path(tempfile.mkdtemp()) / "branch.sqlite3")
    try:
        batch = CellBatch(store)
        protocol = compose_view_template_protocol(batch)
        batch.commit()
        builder = ViewTemplateBuilder(CellBatch(store), protocol)
        table = {}
        for engine, (required, outputs) in GRAPH_BRANCHES.items():
            tag = engine.replace(".", "-")
            root = builder.expression("%s:root" % tag, "root")
            built = []
            for output, operation, arguments in outputs:
                parts = []
                for index, (kind, name) in enumerate(arguments):
                    key = "%s:%s%d" % (tag, output, index)
                    if kind == "in":
                        segment = builder.atom(key + ":s", name)
                        parts.append(builder.expression(key, "path", (root, segment)))
                    elif kind == "param":
                        holder = builder.atom(key + ":p", "parameters")
                        named = builder.atom(key + ":n", name)
                        parts.append(builder.expression(
                            key, "path", (root, holder, named)))
                    else:
                        parts.append(builder.expression(key, name))
                built.append((
                    output,
                    builder.expression("%s:%s" % (tag, output), operation, tuple(parts)),
                ))
            table[engine] = (
                built, tuple(name for kind, name in required if kind == "in")
            )
        builder.batch.commit()
        snapshot = store.snapshot()

        def evaluate(expression_root, projection):
            return evaluate_view_expression(
                snapshot, protocol, expression_root, projection
            )

        held = {
            engine: (evaluate, outputs, required)
            for engine, (outputs, required) in table.items()
        }
        for condition in (True, False):
            nodes = [
                _n("v", "data.constant", {"value": "42"}),
                _n("c", "data.constant", {"value": "true" if condition else "false"}),
                _n("gate", "control.if"),
                _n("out", "output.parameter", {"name": "answer"}),
            ]
            wires = [
                StemWire("v", "value", "gate", "value"),
                StemWire("c", "value", "gate", "condition"),
                StemWire("gate", "true" if condition else "false", "out", "value"),
            ]
            graph = evaluate_stem_graph(nodes, wires, graph_expressions=held)
            fast = evaluate_stem_graph(nodes, wires)
            assert graph.results == {"answer": 42}, (condition, graph.results)
            assert graph.results == fast.results, (
                condition, graph.results, fast.results
            )
    finally:
        store.close()
