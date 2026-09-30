"""Court: the desktop start shows the boot's progress while the graph opens.

launch_archhub_test.py (the founder's start path: ArchHub.vbs) opened the graph
first and only then built its window, so a start showed nothing for the whole
boot and the "phase k of n" page (clean_boot_surface) was never on his screen.
The window now stands first on the boot page, dark before its first paint, and
the graph opens off the Qt thread. The offscreen run of the real launcher is
the behavioural proof; this court holds the order in the source.
"""
from __future__ import annotations

import ast
from pathlib import Path

LAUNCHER = Path(__file__).resolve().parents[1] / "launch_archhub_test.py"


def _module():
    return ast.parse(LAUNCHER.read_text(encoding="utf-8"))


def _line_of(source: str, needle: str) -> int:
    for number, line in enumerate(source.splitlines(), 1):
        if needle in line:
            return number
    raise AssertionError("not in the launcher: %s" % needle)


def test_the_window_and_boot_page_stand_before_the_graph_opens():
    source = LAUNCHER.read_text(encoding="utf-8")
    window = _line_of(source, "app = QApplication(sys.argv)")
    surface = _line_of(source, "BootSurface(\"127.0.0.1\", _boot_port).start()")
    shown = _line_of(source, "    window.show()")
    opened = _line_of(source, "server, boot_refusal = _off_the_qt_thread(_open_saved_graph)")
    assert window < surface < shown < opened


def test_the_graph_opens_off_the_qt_thread_and_the_pipeline_is_phase_two():
    tree = _module()
    def boot_calls(node):
        return {
            id(call) for call in ast.walk(node)
            if isinstance(call, ast.Call) and getattr(call.func, "id", None) == "_boot"
        }
    opener = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_open_saved_graph"
    )
    # Every _boot() call is inside _open_saved_graph, which runs off the Qt thread.
    assert boot_calls(tree) and boot_calls(tree) == boot_calls(opener)
    source = LAUNCHER.read_text(encoding="utf-8")
    assert _line_of(source, "_boot_phase(1)") < _line_of(source, "_off_the_qt_thread(_prepare_pipeline)")


def test_the_window_is_dark_before_its_first_paint_and_releases_the_boot_port():
    source = LAUNCHER.read_text(encoding="utf-8")
    assert 'view.page().setBackgroundColor(QColor(_BOOT_THEME["bg"]))' in source
    assert _line_of(source, "setBackgroundColor") < _line_of(source, "    window.show()")
    assert "view.loadFinished.connect(_release_boot_surface)" in source
    assert "held.hand_over" in source
