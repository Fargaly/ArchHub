"""Illustrator connector — drives Adobe Illustrator via COM (pywin32).

Mechanism `com`: ArchHub COM-dispatches to an already-running
Illustrator from its own Python process — no localhost listener, no
plug-in is loaded into Illustrator. `live` means "GetActiveObject
succeeded".

Illustrator's COM ProgID is `Illustrator.Application`. The COM object
model exposes Documents / Artboards / Layers / Swatches well enough to
read directly; export options classes (ExportOptionsPNG24, etc.) are
also COM-dispatchable. ExtendScript via `app.DoJavaScript(...)` is the
fallback for anything the object model is awkward about.

Discipline (copied from outlook_runner.py):
  * Every worker thread CoInitializes before touching COM — see
    `com_thread()`. Qt6 background threads fast-fail without it.
  * pywin32 + the COM dispatch are lazy-imported, so a machine without
    pywin32 or without Illustrator still imports this module fine.
  * probe() uses GetActiveObject ONLY — it never launches Illustrator.
  * No operation ever raises to the caller — failures become
    OpResult.fail(...).
"""
from __future__ import annotations

import contextlib
import json
from typing import Any

from connectors.base import (
    Connector, ConnectorOp, ParamSpec, OpResult, register,
)


_PROGID = "Illustrator.Application"

# AiExportType enum.
_EXPORT_PNG24 = 5
_EXPORT_SVG = 3
# AiDocumentColorSpace enum.
_COLOR_SPACE = {1: "RGB", 2: "CMYK"}


# ── COM plumbing ────────────────────────────────────────────────────
@contextlib.contextmanager
def com_thread():
    """Init + uninit the COM apartment for the current thread. Prevents
    Qt6 0xc0000409 fast-fails when an op runs on a Qt-pumped background
    thread."""
    inited = False
    try:
        import pythoncom
        pythoncom.CoInitialize()
        inited = True
    except Exception:
        pass
    try:
        yield
    finally:
        if inited:
            try:
                import pythoncom
                pythoncom.CoUninitialize()
            except Exception:
                pass


def _active_app():
    """Return the running Illustrator COM object, or raise RuntimeError.

    GetActiveObject ONLY — never launches Illustrator. Caller must
    already be inside com_thread()."""
    try:
        import importlib as _il
        w = _il.import_module("win32com.client")
    except ImportError as ex:
        raise RuntimeError(
            "pywin32 not installed. Run: pip install pywin32"
        ) from ex
    try:
        return w.GetActiveObject(_PROGID)
    except Exception as ex:
        raise RuntimeError(
            "Illustrator is not running. Open Illustrator and a "
            f"document, then retry. ({ex})"
        ) from ex


def _safe(v: Any, n: int = 0) -> str:
    s = "" if v is None else str(v)
    return s if not n else s[:n]


def _num(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        try:
            return float(str(v).split()[0])
        except Exception:
            return default


def _eval_jsx(app, script: str) -> str:
    """Run ExtendScript in Illustrator, return its final expression as
    a string."""
    try:
        out = app.DoJavaScript(script)
    except Exception as ex:
        raise RuntimeError(f"ExtendScript failed: {ex}") from ex
    return "" if out is None else str(out)


def _jsx_json(app, script: str) -> Any:
    """Run ExtendScript ending in JSON.stringify(...) and parse it."""
    raw = _eval_jsx(app, script)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def _active_doc(app):
    """Return the active document or raise a clean RuntimeError."""
    try:
        if int(getattr(app.Documents, "Count", 0) or 0) == 0:
            raise RuntimeError("no document")
        return app.ActiveDocument
    except RuntimeError:
        raise
    except Exception as ex:
        raise RuntimeError(f"no active document ({ex})") from ex


# ── operation implementations ───────────────────────────────────────
def _list_documents() -> OpResult:
    with com_thread():
        try:
            app = _active_app()
        except RuntimeError as ex:
            return OpResult.fail(str(ex))
        try:
            docs = app.Documents
            active_name = ""
            try:
                active_name = _safe(app.ActiveDocument.Name)
            except Exception:
                active_name = ""
            out: list[dict] = []
            for i in range(int(getattr(docs, "Count", 0) or 0)):
                try:
                    d = docs.Item(i + 1)
                    name = _safe(d.Name)
                    cs_raw = getattr(d, "DocumentColorSpace", None)
                    out.append({
                        "name": name,
                        "color_space": _COLOR_SPACE.get(
                            int(cs_raw) if cs_raw is not None else -1,
                            str(cs_raw)),
                        "width_pt": round(_num(d.Width), 1),
                        "height_pt": round(_num(d.Height), 1),
                        "artboard_count": int(
                            getattr(d.Artboards, "Count", 0) or 0),
                        "layer_count": int(
                            getattr(d.Layers, "Count", 0) or 0),
                        "active": name == active_name,
                        "saved": bool(getattr(d, "Saved", False)),
                        "path": _safe(getattr(d, "FullName", "")),
                    })
                except Exception:
                    continue
            preview = (f"{len(out)} document"
                       f"{'s' if len(out) != 1 else ''} open")
            return OpResult(ok=True, value=out, value_preview=preview)
        except Exception as ex:
            return OpResult.fail(f"list_documents: {ex}")


def _list_artboards() -> OpResult:
    with com_thread():
        try:
            app = _active_app()
        except RuntimeError as ex:
            return OpResult.fail(str(ex))
        try:
            d = _active_doc(app)
        except RuntimeError as ex:
            return OpResult.fail(
                f"No active document. Open one in Illustrator. ({ex})")
        try:
            abs_ = d.Artboards
            active_idx = -1
            try:
                active_idx = int(getattr(abs_, "GetActiveArtboardIndex",
                                         lambda: -1)())
            except Exception:
                active_idx = -1
            out: list[dict] = []
            for i in range(int(getattr(abs_, "Count", 0) or 0)):
                try:
                    ab = abs_.Item(i + 1)
                    # ArtboardRect = [left, top, right, bottom] in pt.
                    rect = list(getattr(ab, "ArtboardRect", []) or [])
                    width = height = 0.0
                    if len(rect) == 4:
                        width = round(abs(_num(rect[2]) -
                                          _num(rect[0])), 1)
                        height = round(abs(_num(rect[1]) -
                                           _num(rect[3])), 1)
                    out.append({
                        "index": i,
                        "name": _safe(getattr(ab, "Name", "")),
                        "width_pt": width,
                        "height_pt": height,
                        "active": i == active_idx,
                    })
                except Exception:
                    continue
            preview = (f"{len(out)} artboard"
                       f"{'s' if len(out) != 1 else ''}")
            return OpResult(ok=True, value=out, value_preview=preview)
        except Exception as ex:
            return OpResult.fail(f"list_artboards: {ex}")


def _list_layers() -> OpResult:
    """Flat list of every layer (recursing sub-layers). ExtendScript —
    cleaner than recursive COM walking."""
    with com_thread():
        try:
            app = _active_app()
        except RuntimeError as ex:
            return OpResult.fail(str(ex))
        try:
            _ = _active_doc(app)
        except RuntimeError as ex:
            return OpResult.fail(
                f"No active document. Open one in Illustrator. ({ex})")
        script = r"""
        (function () {
          var out = [];
          function walk(layers, depth, path) {
            for (var i = 0; i < layers.length; i++) {
              var ly = layers[i];
              out.push({
                name: ly.name,
                depth: depth,
                path: path + ly.name,
                visible: ly.visible,
                locked: ly.locked,
                opacity: Math.round(ly.opacity),
                item_count: ly.pageItems.length
              });
              if (ly.layers && ly.layers.length > 0) {
                walk(ly.layers, depth + 1, path + ly.name + "/");
              }
            }
          }
          try { walk(app.activeDocument.layers, 0, ""); }
          catch (e) { return JSON.stringify({error: String(e)}); }
          return JSON.stringify(out);
        })();
        """
        try:
            data = _jsx_json(app, script)
        except RuntimeError as ex:
            return OpResult.fail(str(ex))
        if isinstance(data, dict) and data.get("error"):
            return OpResult.fail(f"list_layers: {data['error']}")
        if not isinstance(data, list):
            return OpResult.fail("list_layers: unexpected ExtendScript "
                                 "result")
        preview = f"{len(data)} layer{'s' if len(data) != 1 else ''}"
        return OpResult(ok=True, value=data, value_preview=preview)


def _list_swatches() -> OpResult:
    """Named color swatches of the active document."""
    with com_thread():
        try:
            app = _active_app()
        except RuntimeError as ex:
            return OpResult.fail(str(ex))
        try:
            _ = _active_doc(app)
        except RuntimeError as ex:
            return OpResult.fail(
                f"No active document. Open one in Illustrator. ({ex})")
        script = r"""
        (function () {
          var out = [];
          try {
            var sw = app.activeDocument.swatches;
            for (var i = 0; i < sw.length; i++) {
              var c = sw[i].color;
              var entry = {name: sw[i].name, color_type: c.typename};
              if (c.typename === "RGBColor") {
                entry.r = Math.round(c.red);
                entry.g = Math.round(c.green);
                entry.b = Math.round(c.blue);
              } else if (c.typename === "CMYKColor") {
                entry.c = Math.round(c.cyan);
                entry.m = Math.round(c.magenta);
                entry.y = Math.round(c.yellow);
                entry.k = Math.round(c.black);
              } else if (c.typename === "GrayColor") {
                entry.gray = Math.round(c.gray);
              } else if (c.typename === "SpotColor") {
                entry.spot = (c.spot ? c.spot.name : "");
              }
              out.push(entry);
            }
          } catch (e) { return JSON.stringify({error: String(e)}); }
          return JSON.stringify(out);
        })();
        """
        try:
            data = _jsx_json(app, script)
        except RuntimeError as ex:
            return OpResult.fail(str(ex))
        if isinstance(data, dict) and data.get("error"):
            return OpResult.fail(f"list_swatches: {data['error']}")
        if not isinstance(data, list):
            return OpResult.fail("list_swatches: unexpected result")
        preview = f"{len(data)} swatch{'es' if len(data) != 1 else ''}"
        return OpResult(ok=True, value=data, value_preview=preview)


def _export(format: str = "png", path: str = "") -> OpResult:
    """Export the active document to SVG, PNG or PDF.

    PDF uses SaveAs (PDF is a native Illustrator save format); SVG and
    PNG use Export with the matching ExportOptions class."""
    fmt = (format or "png").strip().lower()
    if fmt not in ("svg", "png", "pdf"):
        return OpResult.fail(f"Unsupported format '{format}'. "
                             "Use 'svg', 'png' or 'pdf'.")
    if not (path or "").strip():
        return OpResult.fail("export: 'path' is required.")
    with com_thread():
        try:
            app = _active_app()
        except RuntimeError as ex:
            return OpResult.fail(str(ex))
        try:
            d = _active_doc(app)
        except RuntimeError as ex:
            return OpResult.fail(
                f"No active document. Open one in Illustrator. ({ex})")
        try:
            import importlib as _il
            w = _il.import_module("win32com.client")
            if fmt == "pdf":
                opts = w.Dispatch("Illustrator.PDFSaveOptions")
                d.SaveAs(path, opts)
            elif fmt == "svg":
                opts = w.Dispatch("Illustrator.ExportOptionsSVG")
                d.Export(path, _EXPORT_SVG, opts)
            else:  # png
                opts = w.Dispatch("Illustrator.ExportOptionsPNG24")
                opts.AntiAliasing = True
                opts.Transparency = True
                d.Export(path, _EXPORT_PNG24, opts)
            out = {"exported": True, "path": path, "format": fmt}
            return OpResult(ok=True, value=out,
                            value_preview=f"exported {fmt.upper()} → "
                                          f"{path}")
        except Exception as ex:
            return OpResult.fail(f"export: {ex}")


def _set_layer_visibility(layer_name: str = "",
                          visible: bool = True) -> OpResult:
    """Toggle a layer's visibility by name (sub-layers searched)."""
    if not (layer_name or "").strip():
        return OpResult.fail("set_layer_visibility: 'layer_name' is "
                             "required.")
    want = bool(visible)
    with com_thread():
        try:
            app = _active_app()
        except RuntimeError as ex:
            return OpResult.fail(str(ex))
        try:
            _ = _active_doc(app)
        except RuntimeError as ex:
            return OpResult.fail(
                f"No active document. Open one in Illustrator. ({ex})")
        target = json.dumps(layer_name)
        script = r"""
        (function () {
          var want = %s;
          var target = %s;
          var found = false;
          function walk(layers) {
            for (var i = 0; i < layers.length; i++) {
              var ly = layers[i];
              if (!found && ly.name === target) {
                ly.visible = want;
                found = true;
              }
              if (ly.layers && ly.layers.length > 0) {
                walk(ly.layers);
              }
            }
          }
          try { walk(app.activeDocument.layers); }
          catch (e) { return JSON.stringify({error: String(e)}); }
          return JSON.stringify({found: found});
        })();
        """ % ("true" if want else "false", target)
        try:
            data = _jsx_json(app, script)
        except RuntimeError as ex:
            return OpResult.fail(str(ex))
        if isinstance(data, dict) and data.get("error"):
            return OpResult.fail(
                f"set_layer_visibility: {data['error']}")
        if not isinstance(data, dict) or not data.get("found"):
            return OpResult.fail(
                f"set_layer_visibility: no layer named '{layer_name}'")
        out = {"layer_name": layer_name, "visible": want}
        return OpResult(ok=True, value=out,
                        value_preview=f"'{layer_name}' "
                                      f"{'shown' if want else 'hidden'}")


# ── connector ───────────────────────────────────────────────────────
class IllustratorConnector(Connector):
    """Adobe Illustrator, driven over COM (pywin32) + ExtendScript."""

    host = "illustrator"
    display_name = "Adobe Illustrator"
    mechanism = "com"

    def probe(self) -> dict:
        """live  → Illustrator is running and reachable over COM.
        missing → Illustrator closed, or pywin32 not installed.
        Never launches Illustrator (GetActiveObject only)."""
        with com_thread():
            try:
                import importlib as _il
                w = _il.import_module("win32com.client")
            except ImportError:
                return {"status": "missing",
                        "note": "pywin32 not installed "
                                "(pip install pywin32)",
                        "detail": {}}
            try:
                app = w.GetActiveObject(_PROGID)
            except Exception:
                return {"status": "missing",
                        "note": "Illustrator is not running",
                        "detail": {"progid": _PROGID}}
            detail: dict = {"progid": _PROGID}
            try:
                detail["version"] = _safe(app.Version)
            except Exception:
                pass
            try:
                detail["open_documents"] = int(
                    getattr(app.Documents, "Count", 0) or 0)
            except Exception:
                detail["open_documents"] = 0
            try:
                detail["active_document"] = _safe(
                    app.ActiveDocument.Name)
            except Exception:
                detail["active_document"] = ""
            note = "Illustrator reachable"
            if detail.get("active_document"):
                note += f" · {detail['active_document']}"
            elif not detail.get("open_documents"):
                note += " · no document open"
            return {"status": "live", "note": note, "detail": detail}

    def build_ops(self) -> list:
        return [
            # ── reads ────────────────────────────────────────────────
            ConnectorOp(
                op_id="illustrator.list_documents",
                host="illustrator", kind="read",
                label="List documents",
                description="All open Illustrator documents with color "
                            "space, size and artboard count.",
                inputs=[],
                output_type="list", destructive=False,
                fn=_list_documents,
            ),
            ConnectorOp(
                op_id="illustrator.list_artboards",
                host="illustrator", kind="read",
                label="List artboards",
                description="Artboards of the active document — name "
                            "and size in points.",
                inputs=[],
                output_type="list", destructive=False,
                fn=_list_artboards,
            ),
            ConnectorOp(
                op_id="illustrator.list_layers",
                host="illustrator", kind="read",
                label="List layers",
                description="Every layer of the active document — "
                            "name, visibility, lock state (sub-layers "
                            "recursed).",
                inputs=[],
                output_type="list", destructive=False,
                fn=_list_layers,
            ),
            ConnectorOp(
                op_id="illustrator.list_swatches",
                host="illustrator", kind="read",
                label="List swatches",
                description="Named color swatches of the active "
                            "document with RGB/CMYK values.",
                inputs=[],
                output_type="list", destructive=False,
                fn=_list_swatches,
            ),
            # ── actions ──────────────────────────────────────────────
            ConnectorOp(
                op_id="illustrator.export",
                host="illustrator", kind="action",
                label="Export document",
                description="Export the active document to an SVG, PNG "
                            "or PDF file.",
                inputs=[
                    ParamSpec(id="format", label="Format",
                              type="choice", default="png",
                              options=["svg", "png", "pdf"],
                              required=True,
                              help="Output file format."),
                    ParamSpec(id="path", label="Output path",
                              type="file", default="", required=True,
                              help="Absolute path of the file to "
                                   "write."),
                ],
                output_type="any", destructive=True,
                fn=_export,
            ),
            ConnectorOp(
                op_id="illustrator.set_layer_visibility",
                host="illustrator", kind="action",
                label="Set layer visibility",
                description="Show or hide a layer by name in the "
                            "active document.",
                inputs=[
                    ParamSpec(id="layer_name", label="Layer name",
                              type="text", default="", required=True,
                              help="Name of the layer to toggle."),
                    ParamSpec(id="visible", label="Visible",
                              type="bool", default=True,
                              required=False,
                              help="True to show, False to hide."),
                ],
                output_type="any", destructive=True,
                fn=_set_layer_visibility,
            ),
        ]


register(IllustratorConnector())
