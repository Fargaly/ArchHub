"""Tests for the Microsoft Office COM connector cluster.

Covers `word_connector`, `excel_connector`, `powerpoint_connector` — the
three connectors built against the uniform `connectors/base.py` contract.

DESIGN CONSTRAINT: these tests MUST pass on a machine where Word / Excel /
PowerPoint are NOT installed and pywin32 may be absent. So no test requires
a live host. We exercise:

  * `build_ops()` returns the right op set with correct metadata
    (`op_id`, `kind`, `destructive`, `inputs`, `output_type`).
  * `probe()` returns `missing` cleanly when the host is closed / pywin32
    missing — never raises.
  * Every connector `register()`s into the global registry.
  * COM failures inside an op fn surface as `OpResult(ok=False)` — they
    never raise to the caller.
  * Mocked-COM happy paths for a couple of representative read ops so the
    win32com call shape is verified without a real Office install.

`win32com.client` and `pythoncom` are stubbed via `sys.modules` so the
connector modules import on any OS.
"""
from __future__ import annotations

import importlib
import os
import sys
import types

import pytest


# ── make `app/` importable + stub the Windows COM modules ───────────
_APP_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app")
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)


def _install_com_stubs():
    """Install minimal `pythoncom` + `win32com.client` stubs so the
    connector modules import even off-Windows. `win32com.client` has no
    behaviour by default — individual tests monkeypatch
    `GetActiveObject` / `Dispatch` on it as needed."""
    if "pythoncom" not in sys.modules:
        pc = types.ModuleType("pythoncom")
        pc.CoInitialize = lambda: None
        pc.CoUninitialize = lambda: None
        sys.modules["pythoncom"] = pc

    if "win32com" not in sys.modules:
        sys.modules["win32com"] = types.ModuleType("win32com")
    if "win32com.client" not in sys.modules:
        wc = types.ModuleType("win32com.client")

        def _no_instance(progid):
            # Default: behave as if no Office app is running.
            raise OSError(f"no running instance of {progid}")

        wc.GetActiveObject = _no_instance
        wc.Dispatch = _no_instance
        sys.modules["win32com.client"] = wc
        sys.modules["win32com"].client = wc


_install_com_stubs()

from connectors import base  # noqa: E402
from connectors.base import Connector, ConnectorOp, OpResult, ParamSpec  # noqa: E402
import connectors.word_connector as word_mod  # noqa: E402
import connectors.excel_connector as excel_mod  # noqa: E402
import connectors.powerpoint_connector as ppt_mod  # noqa: E402


# ── fake COM object tree ────────────────────────────────────────────
class FakeCollection:
    """A COM-style 1-based collection with a `.Count` and `.Item(i)`."""

    def __init__(self, items):
        self._items = list(items)

    @property
    def Count(self):
        return len(self._items)

    def Item(self, i):
        return self._items[i - 1]

    def __iter__(self):
        return iter(self._items)


class FakeRange:
    """Stand-in for a Word/Excel Range."""

    def __init__(self, text="", value=None):
        self.Text = text
        self.Value = value
        self._inserted = []

    def Address(self, *a, **k):
        return "A1:B2"

    def Collapse(self, *a, **k):
        pass

    def InsertAfter(self, t):
        self._inserted.append(t)


class FakeWordDoc:
    def __init__(self, name="Brief.docx"):
        self.Name = name
        self.FullName = r"C:\\docs\\" + name
        self.Saved = True
        self.ReadOnly = False
        para = types.SimpleNamespace(
            Range=FakeRange("Hello world\r"),
            Style=types.SimpleNamespace(NameLocal="Heading 1"),
            OutlineLevel=1,
        )
        self.Paragraphs = FakeCollection([para, para])
        self.Tables = FakeCollection([])
        self.Comments = FakeCollection([])
        self.Content = FakeRange("Hello world\r")

    def Range(self, *a, **k):
        return FakeRange("Hello world\r")


class FakeWordApp:
    def __init__(self, docs=None):
        d = docs if docs is not None else [FakeWordDoc()]
        self.Documents = FakeCollection(d)
        self.ActiveDocument = d[0] if d else None
        self.Version = "16.0"


class FakeExcelWS:
    def __init__(self, name="Sheet1"):
        self.Name = name
        self.Visible = -1
        used = FakeRange(value=((1, 2), (3, 4)))
        used.Rows = types.SimpleNamespace(Count=2)
        used.Columns = types.SimpleNamespace(Count=2)
        self.UsedRange = used

    def Range(self, addr):
        r = FakeRange(value=((1, 2), (3, 4)))
        r.Rows = types.SimpleNamespace(Count=2)
        r.Columns = types.SimpleNamespace(Count=2)
        return r


class FakeExcelWB:
    def __init__(self, name="Costs.xlsx"):
        self.Name = name
        self.FullName = r"C:\\books\\" + name
        self.Saved = True
        self.ReadOnly = False
        ws = FakeExcelWS()
        self.Worksheets = FakeCollection([ws])
        self.ActiveSheet = ws
        self.Names = FakeCollection([])


class FakeExcelApp:
    def __init__(self, wbs=None):
        b = wbs if wbs is not None else [FakeExcelWB()]
        self.Workbooks = FakeCollection(b)
        self.ActiveWorkbook = b[0] if b else None
        self.Version = "16.0"
        self.Selection = None


class FakePPTSlide:
    def __init__(self, idx=1):
        self.SlideID = 256 + idx
        self.SlideIndex = idx
        self.Layout = 1
        self.Shapes = FakeCollection([])
        self.Shapes.HasTitle = 0
        self.NotesPage = types.SimpleNamespace(Shapes=FakeCollection([]))


class FakePPTPres:
    def __init__(self, name="Pitch.pptx"):
        self.Name = name
        self.FullName = r"C:\\decks\\" + name
        self.Saved = True
        self.ReadOnly = 0
        self.Slides = FakeCollection([FakePPTSlide(1), FakePPTSlide(2)])


class FakePPTApp:
    def __init__(self, pres=None):
        p = pres if pres is not None else [FakePPTPres()]
        self.Presentations = FakeCollection(p)
        self.ActivePresentation = p[0] if p else None
        self.Version = "16.0"


# ── fixtures ────────────────────────────────────────────────────────
@pytest.fixture
def word():
    return word_mod.WordConnector()


@pytest.fixture
def excel():
    return excel_mod.ExcelConnector()


@pytest.fixture
def powerpoint():
    return ppt_mod.PowerPointConnector()


@pytest.fixture(autouse=True)
def _reset_com(monkeypatch):
    """Before every test, reset the win32com stub to the 'no running app'
    default so probe tests see `missing` unless a test opts into a fake."""
    wc = sys.modules["win32com.client"]

    def _no_instance(progid):
        raise OSError(f"no running instance of {progid}")

    monkeypatch.setattr(wc, "GetActiveObject", _no_instance, raising=False)
    monkeypatch.setattr(wc, "Dispatch", _no_instance, raising=False)
    yield


def _use_fake_app(monkeypatch, module, fake):
    """Point a connector module's win32com stub at a fake Office app for
    both GetActiveObject and Dispatch."""
    wc = sys.modules["win32com.client"]
    monkeypatch.setattr(wc, "GetActiveObject", lambda progid: fake)
    monkeypatch.setattr(wc, "Dispatch", lambda progid: fake)


# ════════════════════════════════════════════════════════════════════
# 1. Registration
# ════════════════════════════════════════════════════════════════════
def test_all_three_connectors_register():
    """Importing the modules must self-register all three hosts."""
    for host in ("word", "excel", "powerpoint"):
        c = base.get(host)
        assert c is not None, f"{host} connector not registered"
        assert isinstance(c, Connector)
        assert c.host == host


def test_connectors_declare_com_mechanism(word, excel, powerpoint):
    for c in (word, excel, powerpoint):
        assert c.mechanism == "com"
        assert c.display_name  # non-empty human label


def test_load_all_connectors_includes_office():
    """base.load_all_connectors() must pick up the Office modules."""
    base.load_all_connectors()
    for host in ("word", "excel", "powerpoint"):
        assert base.get(host) is not None


# ════════════════════════════════════════════════════════════════════
# 2. Op set + metadata
# ════════════════════════════════════════════════════════════════════
def test_word_op_set(word):
    ids = {o.op_id for o in word.build_ops()}
    assert ids == {
        "word.list_documents", "word.list_paragraphs", "word.list_headings",
        "word.list_tables", "word.list_comments", "word.get_text",
        "word.find_replace", "word.insert_text", "word.export_pdf",
    }


def test_excel_op_set(excel):
    ids = {o.op_id for o in excel.build_ops()}
    assert ids == {
        "excel.list_workbooks", "excel.list_worksheets", "excel.read_range",
        "excel.list_named_ranges", "excel.get_selection",
        "excel.write_range", "excel.export_pdf",
    }


def test_powerpoint_op_set(powerpoint):
    ids = {o.op_id for o in powerpoint.build_ops()}
    assert ids == {
        "powerpoint.list_presentations", "powerpoint.list_slides",
        "powerpoint.list_shapes", "powerpoint.read_notes",
        "powerpoint.add_slide", "powerpoint.set_shape_text",
        "powerpoint.export_pdf",
    }


@pytest.mark.parametrize("fixture_name", ["word", "excel", "powerpoint"])
def test_op_metadata_is_well_formed(fixture_name, request):
    """Every op has a sane shape per the ConnectorOp contract."""
    connector = request.getfixturevalue(fixture_name)
    for op in connector.build_ops():
        assert isinstance(op, ConnectorOp)
        assert op.op_id.startswith(connector.host + ".")
        assert op.host == connector.host
        assert op.kind in ("read", "action")
        assert op.label  # non-empty
        assert callable(op.fn)  # real implementation, never None
        assert all(isinstance(p, ParamSpec) for p in op.inputs)


@pytest.mark.parametrize("fixture_name", ["word", "excel", "powerpoint"])
def test_reads_are_non_destructive(fixture_name, request):
    """Every 'read' op must be non-destructive; safe to call speculatively."""
    connector = request.getfixturevalue(fixture_name)
    for op in connector.build_ops():
        if op.kind == "read":
            assert op.destructive is False, f"{op.op_id} read marked destructive"


def test_destructive_actions_flagged():
    """The mutating actions across all three hosts must set destructive=True."""
    expected_destructive = {
        "word.find_replace", "word.insert_text", "word.export_pdf",
        "excel.write_range", "excel.export_pdf",
        "powerpoint.add_slide", "powerpoint.set_shape_text",
        "powerpoint.export_pdf",
    }
    seen = set()
    for host in ("word", "excel", "powerpoint"):
        for op in base.get(host).build_ops():
            if op.destructive:
                seen.add(op.op_id)
            if op.op_id in expected_destructive:
                assert op.kind == "action"
    assert seen == expected_destructive


def test_excel_read_range_inputs(excel):
    """excel.read_range must take workbook + worksheet + range params."""
    op = next(o for o in excel.build_ops() if o.op_id == "excel.read_range")
    input_ids = {p.id for p in op.inputs}
    assert {"workbook", "worksheet", "range"} <= input_ids
    assert op.output_type == "range_values"


def test_excel_write_range_required_inputs(excel):
    """excel.write_range must require range + values."""
    op = next(o for o in excel.build_ops() if o.op_id == "excel.write_range")
    required = {p.id for p in op.inputs if p.required}
    assert {"range", "values"} <= required
    assert op.destructive is True


def test_powerpoint_list_shapes_needs_slide_index(powerpoint):
    op = next(o for o in powerpoint.build_ops()
              if o.op_id == "powerpoint.list_shapes")
    assert any(p.id == "slide_index" and p.required for p in op.inputs)


def test_op_to_dict_round_trips(word):
    """ConnectorOp.to_dict() must yield a JSON-safe dict with the keys the
    bridge / canvas expect."""
    op = word.build_ops()[0]
    d = op.to_dict()
    for key in ("op_id", "host", "kind", "label", "inputs",
                "output_type", "destructive"):
        assert key in d
    assert isinstance(d["inputs"], list)


# ════════════════════════════════════════════════════════════════════
# 3. probe() — honest + never raises (host closed / pywin32 missing)
# ════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("fixture_name", ["word", "excel", "powerpoint"])
def test_probe_missing_when_host_closed(fixture_name, request):
    """With no running Office app, probe() must report 'missing' cleanly."""
    connector = request.getfixturevalue(fixture_name)
    result = connector.probe()
    assert isinstance(result, dict)
    assert result["status"] == "missing"
    assert "note" in result and result["note"]
    assert "detail" in result


@pytest.mark.parametrize("fixture_name", ["word", "excel", "powerpoint"])
def test_probe_never_raises(fixture_name, request):
    """probe() must swallow every error — even a hard COM explosion."""
    connector = request.getfixturevalue(fixture_name)
    wc = sys.modules["win32com.client"]

    def _boom(progid):
        raise RuntimeError("catastrophic COM failure")

    wc.GetActiveObject = _boom
    try:
        result = connector.probe()  # must not raise
        assert result["status"] in (
            "missing", "unauthorized", "loaded_dead")
    finally:
        wc.GetActiveObject = lambda p: (_ for _ in ()).throw(OSError(p))


def test_probe_missing_when_pywin32_absent(word, excel, powerpoint,
                                           monkeypatch):
    """If win32com import fails, probe() reports 'missing' with a pip hint —
    never raises ImportError."""
    for mod in (word_mod, excel_mod, ppt_mod):
        def _no_win32():
            raise RuntimeError("pywin32 not installed. Run: pip install pywin32")
        monkeypatch.setattr(mod, "_win32", _no_win32)
    for connector in (word, excel, powerpoint):
        result = connector.probe()
        assert result["status"] == "missing"
        assert "pywin32" in result["note"]


def test_probe_unauthorized_on_access_denied(word, monkeypatch):
    """A COM access-denied error must map to 'unauthorized', not 'missing'."""
    wc = sys.modules["win32com.client"]

    def _denied(progid):
        raise OSError("Access is denied. (0x80070005)")

    monkeypatch.setattr(wc, "GetActiveObject", _denied)
    result = word.probe()
    assert result["status"] == "unauthorized"


def test_probe_live_with_fake_running_app(word, excel, powerpoint,
                                          monkeypatch):
    """When a (fake) Office app is running, probe() reports 'live' with a
    populated detail dict."""
    cases = [
        (word, word_mod, FakeWordApp(), "documents_open"),
        (excel, excel_mod, FakeExcelApp(), "workbooks_open"),
        (powerpoint, ppt_mod, FakePPTApp(), "presentations_open"),
    ]
    for connector, module, fake, detail_key in cases:
        _use_fake_app(monkeypatch, module, fake)
        result = connector.probe()
        assert result["status"] == "live", f"{connector.host} not live"
        assert detail_key in result["detail"]


def test_connector_to_dict_includes_status_and_ops(word):
    """Connector.to_dict() must fold in probe status + the op list without
    raising even when the host is offline."""
    d = word.to_dict()
    assert d["host"] == "word"
    assert d["mechanism"] == "com"
    assert d["status"] == "missing"  # nothing running in the test env
    assert len(d["ops"]) == 9


# ════════════════════════════════════════════════════════════════════
# 4. ops never raise — COM failure → OpResult(ok=False)
# ════════════════════════════════════════════════════════════════════
def test_ops_return_opresult_fail_when_host_unavailable():
    """Every op, run with no Office app available, must return an OpResult
    with ok=False — never raise. This is the 'one broken host can't crash
    the canvas' guarantee."""
    for host in ("word", "excel", "powerpoint"):
        connector = base.get(host)
        for op in connector.build_ops():
            result = op.run()  # ConnectorOp.run() — no params
            assert isinstance(result, OpResult), f"{op.op_id} not OpResult"
            assert result.ok is False, f"{op.op_id} unexpectedly ok"
            assert result.error, f"{op.op_id} missing error message"
            assert result.op_id == op.op_id


def test_op_run_times_every_call():
    """ConnectorOp.run() stamps elapsed_ms even on the failure path."""
    op = base.get("excel").op("excel.list_workbooks")
    result = op.run()
    assert result.elapsed_ms >= 0


def test_run_op_resolves_via_registry():
    """base.run_op() must route an op_id to the right connector and return
    an OpResult (failing cleanly here — no Excel running)."""
    result = base.run_op("excel.list_workbooks")
    assert isinstance(result, OpResult)
    assert result.op_id == "excel.list_workbooks"


def test_unknown_op_fails_cleanly():
    result = base.run_op("word.does_not_exist")
    assert result.ok is False
    assert "unknown op" in result.error.lower()


# ════════════════════════════════════════════════════════════════════
# 5. mocked-COM happy paths — verify the win32com call shape
# ════════════════════════════════════════════════════════════════════
def test_word_list_documents_happy_path(monkeypatch):
    """word.list_documents against a fake Word returns list[dict] with the
    documented stable keys."""
    _use_fake_app(monkeypatch, word_mod, FakeWordApp())
    result = word_mod._list_documents()
    assert result.ok is True
    assert isinstance(result.value, list) and len(result.value) == 1
    doc = result.value[0]
    for key in ("name", "full_name", "saved", "read_only", "paragraphs"):
        assert key in doc
    assert "document" in result.value_preview


def test_word_list_headings_filters_to_headings(monkeypatch):
    """list_headings keeps only heading-styled paragraphs."""
    _use_fake_app(monkeypatch, word_mod, FakeWordApp())
    result = word_mod._list_headings()
    assert result.ok is True
    assert all(h["level"] >= 1 or "heading" in h["style"].lower()
               for h in result.value)


def test_excel_read_range_returns_2d_array(monkeypatch):
    """excel.read_range yields a rectangular 2-D array + a rows×cols
    preview."""
    _use_fake_app(monkeypatch, excel_mod, FakeExcelApp())
    result = excel_mod._read_range(range="A1:B2")
    assert result.ok is True
    grid = result.value["values"]
    assert grid == [[1, 2], [3, 4]]
    assert result.value["rows"] == 2 and result.value["cols"] == 2
    assert "rows" in result.value_preview and "cols" in result.value_preview


def test_excel_grid_normalizes_com_shapes():
    """The _grid helper coerces None / scalar / tuple-of-tuples to
    list[list]."""
    assert excel_mod._grid(None) == []
    assert excel_mod._grid(42) == [[42]]
    assert excel_mod._grid(((1, 2), (3, 4))) == [[1, 2], [3, 4]]


def test_excel_list_worksheets_happy_path(monkeypatch):
    _use_fake_app(monkeypatch, excel_mod, FakeExcelApp())
    result = excel_mod._list_worksheets()
    assert result.ok is True
    assert result.value[0]["name"] == "Sheet1"
    assert "worksheet" in result.value_preview


def test_powerpoint_list_slides_happy_path(monkeypatch):
    """powerpoint.list_slides returns one dict per slide."""
    _use_fake_app(monkeypatch, ppt_mod, FakePPTApp())
    result = ppt_mod._list_slides()
    assert result.ok is True
    assert len(result.value) == 2
    for slide in result.value:
        for key in ("index", "slide_id", "title", "shape_count"):
            assert key in slide
    assert "slide" in result.value_preview


def test_powerpoint_export_pdf_missing_presentation_fails_cleanly(monkeypatch):
    """An op pointed at a non-existent presentation must fail as an
    OpResult, not raise."""
    _use_fake_app(monkeypatch, ppt_mod, FakePPTApp())
    result = ppt_mod._export_pdf(presentation="NotOpen.pptx")
    assert result.ok is False
    assert "not open" in result.error.lower()


def test_word_find_replace_rejects_empty_find(monkeypatch):
    """Destructive find_replace must refuse an empty search string."""
    _use_fake_app(monkeypatch, word_mod, FakeWordApp())
    result = word_mod._find_replace(find_text="")
    assert result.ok is False
    assert "find_text" in result.error


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
