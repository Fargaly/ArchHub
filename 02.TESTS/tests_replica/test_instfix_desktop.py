"""The real Qt close callback follows the user's existing graph setting."""
import ast
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("keep_running", [False, True])
def test_window_x_quits_by_default_and_only_hides_when_opted_in(keep_running):
    from PyQt6.QtWidgets import QApplication, QMainWindow
    from PyQt6.QtGui import QCloseEvent
    application = QApplication.instance() or QApplication([])
    source = ast.parse((ROOT / "01.APP/nodelang/launcher.py").read_text(encoding="utf-8"))
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
    timing = next(item for item in canvas['properties'] if item['label'] == 'toast_visible_ms')
    assert timing['value'] == app._application_setting_default('toast_visible_ms')
    app.edit_universal_property(store, registry, timing['relation'], '4500')
    source = ast.parse((ROOT / "01.APP/nodelang/launcher.py").read_text(encoding='utf-8'))
    methods = [node for node in source.body if isinstance(node, ast.FunctionDef)
               and node.name in ('_launcher_parameter', '_launcher_seconds')]
    from types import SimpleNamespace
    namespace = {'server': SimpleNamespace(universal_store=store, universal_registry=registry)}
    exec(compile(ast.Module(body=methods, type_ignores=[]), 'launcher-parameters', 'exec'), namespace)
    assert namespace['_launcher_seconds']('toast_visible_ms') == 4.5
    assert app.project_universal_canvas(store, registry)['runtime_parameters']['toast_visible_ms'] == 4500
    changed = store.revision
    with pytest.raises(InvalidCell):
        app.edit_universal_property(store, registry, timing['relation'], '-1')
    assert store.revision == changed


def test_workshop_runtime_uses_typed_defaults_and_wired_feed_precedence():
    from nodelang.pipeline_engines import tool_settings
    from nodelang.universal_application import _application_setting_default
    result, _ = tool_settings({'tool': 'workshop'}, {})
    settings = result['out']
    assert settings['keep_running_in_tray'] is False
    for name in ('stale_claim_after_idle_minutes', 'archive_after_idle_days'):
        assert type(settings[name]) is int
        assert settings[name] == _application_setting_default(name)
    result, _ = tool_settings({'tool': 'workshop', 'keep_running_in_tray': True}, {'keep_running_in_tray': False})
    assert result['out']['keep_running_in_tray'] is False
    result, _ = tool_settings({'tool': 'workshop'}, {'keep_running_in_tray': True})
    assert result['out']['keep_running_in_tray'] is True
    with pytest.raises(ValueError, match='must be a boolean'):
        tool_settings({'tool': 'workshop', 'keep_running_in_tray': 'yes'}, {})
    with pytest.raises(ValueError):
        tool_settings({'tool': 'workshop', 'archive_after_idle_days': True}, {})
