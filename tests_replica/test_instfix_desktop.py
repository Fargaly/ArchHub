"""The real Qt close callback follows the user's existing graph setting."""
import ast
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("keep_running", [False, True])
def test_window_x_quits_by_default_and_only_hides_when_opted_in(keep_running):
    from PyQt6.QtWidgets import QApplication, QMainWindow
    from PyQt6.QtGui import QCloseEvent
    application = QApplication.instance() or QApplication([])
    source = ast.parse((ROOT / "launch_archhub_test.py").read_text(encoding="utf-8"))
    window_class = next(node for node in ast.walk(source) if isinstance(node, ast.ClassDef) and node.name == "_ArchHubWindow")
    quits = []
    namespace = {"QMainWindow": QMainWindow, "_quit_from_window": lambda widget: quits.append(widget),
        "_hide_in_tray_if_enabled": lambda widget: (widget.hide() or True) if keep_running else False}
    exec(compile(ast.Module(body=[window_class], type_ignores=[]), "launcher-close", "exec"), namespace)
    window = namespace["_ArchHubWindow"]()
    try:
        window.show()
        application.processEvents()
        event = QCloseEvent()
        window.closeEvent(event)
        assert event.isAccepted() is not keep_running
        assert bool(quits) is not keep_running
        assert window.quitting is not keep_running
    finally:
        window.deleteLater()
        application.processEvents()


def test_tray_toggle_is_the_same_graph_property_read_by_the_launcher():
    from nodelang import universal_application as app
    from nodelang.map_import import resolve_map_path
    from nodelang.universal_cell import InvalidCell
    store, registry = app.build_universal_application(resolve_map_path())
    initial = store.revision
    assert app.read_universal_keep_running_in_tray(store.snapshot(), registry) is False
    assert store.revision == initial
    root = app._system_tool_canvas_root("tool_workshop")
    app.apply_universal_canvas_gesture(store, registry, roots=[root], focus_root=root)
    canvas = app.project_universal_canvas(store, registry)
    row = next(item for item in canvas["properties"] if item["label"] == "keep_running_in_tray")
    assert row["value"] is False and row["editor"] == "boolean"
    app.edit_universal_property(store, registry, row["relation"], "true")
    assert app.read_universal_keep_running_in_tray(store.snapshot(), registry) is True
    changed = store.revision
    with pytest.raises(InvalidCell):
        app.edit_universal_property(store, registry, row["relation"], "yes")
    assert store.revision == changed
    app.edit_universal_property(store, registry, row["relation"], "false")
    assert app.read_universal_keep_running_in_tray(store.snapshot(), registry) is False
