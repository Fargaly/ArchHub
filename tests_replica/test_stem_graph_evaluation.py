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
def test_a_declared_operation_computes_from_the_graph_and_matches_the_fast_path():
    """SPEC 4.1: meaning resolves from released definitions in the graph, and a
    host fast path is admitted only when an equivalence court proves both give
    the same result at the same snapshot.

    Count is expressed as `length(path(root, "items"))` in graph cells and
    evaluated by the interpreter the views already use. The Python engine is
    run beside it on the same inputs; any disagreement fails here, and the
    graph path is the one the runner takes.
    """
    import tempfile
    from pathlib import Path

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
        segment = builder.atom("count:segment", "items")
        root = builder.expression("count:root", "root")
        argument = builder.expression("count:input", "path", (root, segment))
        expression_root = builder.expression("count:expr", "length", (argument,))
        builder.batch.commit()
        snapshot = store.snapshot()

        def evaluate(root_id, projection):
            return evaluate_view_expression(
                snapshot, protocol, root_id, projection
            )

        held = {
            "shape.count": (evaluate, expression_root, "count", "items"),
        }
        for items in ([], [1], [7, 7, 9, 4, 1], ["a", "b", "c"]):
            graph = evaluate_stem_graph(
                [
                    _n("src", "data.list", {"value": items}),
                    _n("count", "shape.count"),
                    _n("out", "output.parameter", {"name": "answer"}),
                ],
                [
                    StemWire("src", "value", "count", "items"),
                    StemWire("count", "count", "out", "value"),
                ],
                graph_expressions=held,
            )
            fast = evaluate_stem_graph(
                [
                    _n("src", "data.list", {"value": items}),
                    _n("count", "shape.count"),
                    _n("out", "output.parameter", {"name": "answer"}),
                ],
                [
                    StemWire("src", "value", "count", "items"),
                    StemWire("count", "count", "out", "value"),
                ],
            )
            assert graph.results == {"answer": len(items)}, (items, graph.results)
            assert graph.results == fast.results, (items, graph.results, fast.results)
            assert not graph.pending, graph.pending
    finally:
        store.close()
