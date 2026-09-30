"""Court: BABOOM's sprite atlas is inspected off the Qt GUI thread.

At every desktop start the `land` slot decoded the packaged 1536x2288 RGBA
spritesheet in pure Python on the GUI thread, holding the GIL: the window froze
for ~3.6s while the Studio loaded (py-spy: MainThread in _unfilter_rgba_rows,
three dumps in a row). The attach worker now prepares the atlas and the GUI
thread only builds the window with it.
"""
from __future__ import annotations

import ast
import threading
from pathlib import Path

import pytest

from nodelang import baboom_native_runtime as runtime
from nodelang.baboom_visual_assets import inspect_baboom_sprite_atlas_v2

LAUNCHER = Path(__file__).resolve().parents[1] / "launch_archhub_test.py"


def test_the_prepared_atlas_equals_a_direct_inspection_and_is_made_off_the_gui_thread():
    made = {}

    def worker():
        made["atlas"] = runtime.prepare_baboom_native_atlas()

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(60)
    direct = inspect_baboom_sprite_atlas_v2(runtime.default_baboom_sprite_atlas_path())
    assert made["atlas"] == direct


def test_a_prepared_atlas_is_used_as_given_and_nothing_else_is_accepted(monkeypatch):
    atlas = runtime.prepare_baboom_native_atlas()
    decoded = []
    monkeypatch.setattr(runtime, "inspect_baboom_sprite_atlas_v2",
                        lambda path: decoded.append(path) or atlas)
    monkeypatch.setattr(runtime, "BaboomNativeCompanionController", lambda host, given: ("controller", given))
    monkeypatch.setattr(runtime, "create_baboom_native_companion_window", lambda controller, **_: controller)

    class _App:
        @staticmethod
        def thread():
            return "gui"

    import PyQt6.QtCore as core
    import PyQt6.QtWidgets as widgets
    monkeypatch.setattr(widgets.QApplication, "instance", staticmethod(lambda: _App()))
    monkeypatch.setattr(core.QThread, "currentThread", staticmethod(lambda: "gui"))
    assert runtime.create_baboom_native_projection(object(), atlas=atlas) == ("controller", atlas)
    assert decoded == []  # the GUI thread decoded nothing
    with pytest.raises(TypeError):
        runtime.create_baboom_native_projection(object(), atlas="not an atlas")


def test_the_launcher_prepares_the_atlas_on_the_attach_worker_and_lands_with_it():
    tree = ast.parse(LAUNCHER.read_text(encoding="utf-8"))
    functions = {node.name: node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    worker = ast.unparse(functions["_keep_attaching"])
    land = ast.unparse(functions["land"])
    assert "prepare_baboom_native_atlas(" in worker
    assert worker.index("prepare_baboom_native_atlas(") < worker.index("ready.emit(host)")
    assert "atlas=self.prepared_atlas" in land
    assert "prepare_baboom_native_atlas(" not in land
