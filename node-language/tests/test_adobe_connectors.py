"""Adobe COM connector cluster tests — Photoshop, Illustrator, InDesign.

These pin the *static* surface of the three Adobe connectors so they
PASS on any machine, with no Adobe app installed and no pywin32
required:

  * Each module imports cleanly and self-registers under base.py.
  * build_ops() exposes exactly the expected op_id set, each op carries
    correct host / kind / destructive metadata, and required ParamSpec
    inputs are present.
  * probe() returns a clean `missing` envelope when GetActiveObject
    cannot find a running app (the normal CI state) — and never raises.
  * COM failures inside an op surface as OpResult.fail(...) — the op
    never raises to the caller.
  * InDesign's probe tries the generic ProgID first, then year-suffixed
    variants.

The COM layer is mocked: we patch each connector module's
`win32com.client` lookup so the tests are deterministic without Adobe.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from connectors.base import (  # noqa: E402
    Connector, ConnectorOp, OpResult, ParamSpec,
)
from connectors import (  # noqa: E402
    photoshop_connector as ps,
    illustrator_connector as ai,
    indesign_connector as idn,
)


# ─── expected op surface per host ───────────────────────────────────
PHOTOSHOP_OPS = {
    "photoshop.list_documents",
    "photoshop.document_info",
    "photoshop.list_layers",
    "photoshop.get_selection_bounds",
    "photoshop.export",
    "photoshop.run_action",
    "photoshop.set_layer_visibility",
}
ILLUSTRATOR_OPS = {
    "illustrator.list_documents",
    "illustrator.list_artboards",
    "illustrator.list_layers",
    "illustrator.list_swatches",
    "illustrator.export",
    "illustrator.set_layer_visibility",
}
INDESIGN_OPS = {
    "indesign.list_documents",
    "indesign.list_spreads",
    "indesign.list_text_frames",
    "indesign.list_paragraph_styles",
    "indesign.list_links",
    "indesign.export_pdf",
    "indesign.update_links",
}


# ─── helpers ────────────────────────────────────────────────────────
def _ops(connector: Connector) -> dict:
    """op_id -> ConnectorOp for one connector."""
    return {o.op_id: o for o in connector.build_ops()}


def _fresh(connector_cls) -> Connector:
    """A non-memoised connector instance (build_ops() not yet cached)."""
    return connector_cls()


# ════════════════════════════════════════════════════════════════════
# Registration — all three connectors land in the base.py registry.
# ════════════════════════════════════════════════════════════════════
class TestRegistration:
    def test_all_three_connectors_register(self):
        # load_all_connectors imports the modules; importing the modules
        # above already ran register(). Confirm via the registry.
        from connectors.base import load_all_connectors, get
        load_all_connectors()
        for host in ("photoshop", "illustrator", "indesign"):
            c = get(host)
            assert c is not None, f"{host} connector not registered"
            assert isinstance(c, Connector)
            assert c.host == host

    def test_connectors_declare_com_mechanism(self):
        for mod, host, name in (
            (ps, "photoshop", "Adobe Photoshop"),
            (ai, "illustrator", "Adobe Illustrator"),
            (idn, "indesign", "Adobe InDesign"),
        ):
            from connectors.base import get
            c = get(host)
            assert c.mechanism == "com"
            assert c.display_name == name

    def test_load_all_connectors_counts_them(self):
        from connectors.base import load_all_connectors, all_connectors
        load_all_connectors()
        hosts = {c.host for c in all_connectors()}
        assert {"photoshop", "illustrator", "indesign"} <= hosts


# ════════════════════════════════════════════════════════════════════
# build_ops() — exact op sets + metadata.
# ════════════════════════════════════════════════════════════════════
class TestPhotoshopOps:
    def test_op_set_exact(self):
        assert set(_ops(ps.PhotoshopConnector())) == PHOTOSHOP_OPS

    def test_kinds_and_destructive_flags(self):
        ops = _ops(ps.PhotoshopConnector())
        # Reads are non-destructive, host is photoshop.
        for op_id in ("photoshop.list_documents",
                      "photoshop.document_info",
                      "photoshop.list_layers",
                      "photoshop.get_selection_bounds"):
            assert ops[op_id].kind == "read"
            assert ops[op_id].destructive is False
            assert ops[op_id].host == "photoshop"
        # Actions are destructive per the mandate.
        for op_id in ("photoshop.export", "photoshop.run_action",
                      "photoshop.set_layer_visibility"):
            assert ops[op_id].kind == "action"
            assert ops[op_id].destructive is True
            assert ops[op_id].host == "photoshop"

    def test_every_op_has_callable_fn(self):
        for op in ps.PhotoshopConnector().build_ops():
            assert callable(op.fn), f"{op.op_id} has no fn"

    def test_export_op_inputs(self):
        export = _ops(ps.PhotoshopConnector())["photoshop.export"]
        by_id = {p.id: p for p in export.inputs}
        assert {"format", "path"} <= set(by_id)
        assert by_id["format"].required is True
        assert by_id["path"].required is True
        # format is a choice constrained to png/jpg.
        assert by_id["format"].type == "choice"
        assert set(by_id["format"].options) == {"png", "jpg"}

    def test_run_action_requires_action_name(self):
        ra = _ops(ps.PhotoshopConnector())["photoshop.run_action"]
        by_id = {p.id: p for p in ra.inputs}
        assert by_id["action_name"].required is True


class TestIllustratorOps:
    def test_op_set_exact(self):
        assert set(_ops(ai.IllustratorConnector())) == ILLUSTRATOR_OPS

    def test_kinds_and_destructive_flags(self):
        ops = _ops(ai.IllustratorConnector())
        for op_id in ("illustrator.list_documents",
                      "illustrator.list_artboards",
                      "illustrator.list_layers",
                      "illustrator.list_swatches"):
            assert ops[op_id].kind == "read"
            assert ops[op_id].destructive is False
        for op_id in ("illustrator.export",
                      "illustrator.set_layer_visibility"):
            assert ops[op_id].kind == "action"
            assert ops[op_id].destructive is True

    def test_export_supports_svg_png_pdf(self):
        export = _ops(ai.IllustratorConnector())["illustrator.export"]
        by_id = {p.id: p for p in export.inputs}
        assert set(by_id["format"].options) == {"svg", "png", "pdf"}
        assert by_id["path"].required is True

    def test_every_op_has_callable_fn(self):
        for op in ai.IllustratorConnector().build_ops():
            assert callable(op.fn), f"{op.op_id} has no fn"


class TestInDesignOps:
    def test_op_set_exact(self):
        assert set(_ops(idn.InDesignConnector())) == INDESIGN_OPS

    def test_kinds_and_destructive_flags(self):
        ops = _ops(idn.InDesignConnector())
        for op_id in ("indesign.list_documents",
                      "indesign.list_spreads",
                      "indesign.list_text_frames",
                      "indesign.list_paragraph_styles",
                      "indesign.list_links"):
            assert ops[op_id].kind == "read"
            assert ops[op_id].destructive is False
        for op_id in ("indesign.export_pdf", "indesign.update_links"):
            assert ops[op_id].kind == "action"
            assert ops[op_id].destructive is True

    def test_export_pdf_requires_path(self):
        ep = _ops(idn.InDesignConnector())["indesign.export_pdf"]
        by_id = {p.id: p for p in ep.inputs}
        assert by_id["path"].required is True
        # preset is optional.
        assert by_id["preset"].required is False

    def test_every_op_has_callable_fn(self):
        for op in idn.InDesignConnector().build_ops():
            assert callable(op.fn), f"{op.op_id} has no fn"

    def test_progid_list_generic_first(self):
        # The generic ProgID must be tried before any year-suffixed
        # variant — the mandate is explicit about this ordering.
        assert idn._PROGIDS[0] == "InDesign.Application"
        assert any(p != "InDesign.Application" and
                   p.startswith("InDesign.Application.")
                   for p in idn._PROGIDS[1:])


# ════════════════════════════════════════════════════════════════════
# probe() — honest 'missing' when no app is running, never raises.
# ════════════════════════════════════════════════════════════════════
class TestProbeMissing:
    def test_photoshop_probe_missing_when_not_running(self):
        # GetActiveObject raises when the app isn't running.
        fake_win32 = SimpleNamespace(
            GetActiveObject=MagicMock(
                side_effect=Exception("Operation unavailable")))
        with patch.dict(sys.modules,
                        {"win32com.client": fake_win32}):
            st = ps.PhotoshopConnector().probe()
        assert st["status"] == "missing"
        assert "not running" in st["note"].lower()

    def test_illustrator_probe_missing_when_not_running(self):
        fake_win32 = SimpleNamespace(
            GetActiveObject=MagicMock(
                side_effect=Exception("Operation unavailable")))
        with patch.dict(sys.modules,
                        {"win32com.client": fake_win32}):
            st = ai.IllustratorConnector().probe()
        assert st["status"] == "missing"
        assert "not running" in st["note"].lower()

    def test_indesign_probe_missing_tries_all_progids(self):
        get_active = MagicMock(side_effect=Exception("not found"))
        fake_win32 = SimpleNamespace(GetActiveObject=get_active)
        with patch.dict(sys.modules,
                        {"win32com.client": fake_win32}):
            st = idn.InDesignConnector().probe()
        assert st["status"] == "missing"
        # Every ProgID variant must have been attempted.
        assert get_active.call_count == len(idn._PROGIDS)
        tried = [c.args[0] for c in get_active.call_args_list]
        assert tried == list(idn._PROGIDS)

    def test_probe_never_raises_on_pywin32_missing(self):
        # Simulate pywin32 absent. Connectors resolve win32com via
        # importlib.import_module, which consults sys.modules first — so
        # to genuinely simulate "pywin32 not installed" we must REMOVE
        # any win32com* entries (sibling connector test files install a
        # stub that leaks) AND block the real import machinery.
        import builtins
        real_import = builtins.__import__

        def _block(name, *a, **kw):
            if name == "win32com.client" or name == "win32com":
                raise ImportError("No module named 'win32com'")
            return real_import(name, *a, **kw)

        purge = {k: sys.modules.pop(k)
                 for k in list(sys.modules)
                 if k == "win32com" or k.startswith("win32com.")}
        try:
            for connector_cls in (ps.PhotoshopConnector,
                                  ai.IllustratorConnector,
                                  idn.InDesignConnector):
                with patch.object(builtins, "__import__", _block):
                    st = connector_cls().probe()
                assert st["status"] == "missing"
                assert "pywin32" in st["note"].lower()
        finally:
            sys.modules.update(purge)

    def test_probe_live_when_app_reachable(self):
        # A fake running app — probe should report 'live'.
        fake_app = MagicMock()
        fake_app.Version = "26.0"
        fake_app.Documents.Count = 1
        fake_app.ActiveDocument.Name = "poster.psd"
        fake_win32 = SimpleNamespace(
            GetActiveObject=MagicMock(return_value=fake_app))
        with patch.dict(sys.modules,
                        {"win32com.client": fake_win32}):
            st = ps.PhotoshopConnector().probe()
        assert st["status"] == "live"
        assert st["detail"]["active_document"] == "poster.psd"


# ════════════════════════════════════════════════════════════════════
# COM failure path — ops fail soft, never raise.
# ════════════════════════════════════════════════════════════════════
class TestOpsFailSoft:
    """With no app running, GetActiveObject raises inside _active_app;
    every op must translate that into OpResult.fail, not an exception.
    base.py's ConnectorOp.run() would also catch a raise — we assert the
    fn itself already returns a clean OpResult."""

    def _no_app(self):
        return SimpleNamespace(
            GetActiveObject=MagicMock(
                side_effect=Exception("Operation unavailable")))

    def test_photoshop_reads_fail_soft(self):
        with patch.dict(sys.modules,
                        {"win32com.client": self._no_app()}):
            for op in ps.PhotoshopConnector().build_ops():
                if op.kind != "read":
                    continue
                res = op.fn()
                assert isinstance(res, OpResult)
                assert res.ok is False
                assert res.error

    def test_illustrator_reads_fail_soft(self):
        with patch.dict(sys.modules,
                        {"win32com.client": self._no_app()}):
            for op in ai.IllustratorConnector().build_ops():
                if op.kind != "read":
                    continue
                res = op.fn()
                assert isinstance(res, OpResult)
                assert res.ok is False
                assert res.error

    def test_indesign_reads_fail_soft(self):
        with patch.dict(sys.modules,
                        {"win32com.client": self._no_app()}):
            for op in idn.InDesignConnector().build_ops():
                if op.kind != "read":
                    continue
                res = op.fn()
                assert isinstance(res, OpResult)
                assert res.ok is False
                assert res.error

    def test_connectorop_run_wraps_failures(self):
        # Drive an op through ConnectorOp.run() — the public path the
        # canvas/bridge use — and confirm an OpResult comes back even
        # with the COM layer broken.
        with patch.dict(sys.modules,
                        {"win32com.client": self._no_app()}):
            op = _ops(ps.PhotoshopConnector())["photoshop.list_layers"]
            res = op.run()
        assert isinstance(res, OpResult)
        assert res.ok is False
        assert res.op_id == "photoshop.list_layers"

    def test_export_validates_inputs_before_com(self):
        # Input validation must happen before any COM dispatch — a
        # missing path fails fast with a clear message.
        ps_export = _ops(ps.PhotoshopConnector())["photoshop.export"]
        res = ps_export.run(format="png", path="")
        assert res.ok is False
        assert "path" in res.error.lower()

        ai_export = _ops(ai.IllustratorConnector())["illustrator.export"]
        res = ai_export.run(format="bmp", path="x")
        assert res.ok is False
        assert "format" in res.error.lower() or \
               "unsupported" in res.error.lower()

        idn_pdf = _ops(idn.InDesignConnector())["indesign.export_pdf"]
        res = idn_pdf.run(path="")
        assert res.ok is False
        assert "path" in res.error.lower()

    def test_action_required_param_validation(self):
        # run_action with no action name fails before COM.
        ra = _ops(ps.PhotoshopConnector())["photoshop.run_action"]
        res = ra.run(action_set="Default Actions", action_name="")
        assert res.ok is False
        assert "action_name" in res.error.lower()

        # set_layer_visibility with no layer name fails before COM.
        for connector_cls, op_id in (
            (ps.PhotoshopConnector, "photoshop.set_layer_visibility"),
            (ai.IllustratorConnector,
             "illustrator.set_layer_visibility"),
        ):
            op = _ops(connector_cls())[op_id]
            res = op.run(layer_name="", visible=True)
            assert res.ok is False
            assert "layer_name" in res.error.lower()


# ════════════════════════════════════════════════════════════════════
# to_dict() — the serialised shape the bridge/canvas consume.
# ════════════════════════════════════════════════════════════════════
class TestSerialisation:
    def test_connector_to_dict_shape(self):
        # to_dict() calls probe(); with no app it should still produce a
        # well-formed dict, status 'missing'.
        fake_win32 = SimpleNamespace(
            GetActiveObject=MagicMock(
                side_effect=Exception("unavailable")))
        with patch.dict(sys.modules,
                        {"win32com.client": fake_win32}):
            d = ps.PhotoshopConnector().to_dict()
        assert d["host"] == "photoshop"
        assert d["mechanism"] == "com"
        assert d["status"] == "missing"
        assert isinstance(d["ops"], list)
        assert len(d["ops"]) == len(PHOTOSHOP_OPS)
        # Each serialised op carries the contract keys.
        for od in d["ops"]:
            assert {"op_id", "host", "kind", "label", "inputs",
                    "output_type", "destructive"} <= set(od)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
