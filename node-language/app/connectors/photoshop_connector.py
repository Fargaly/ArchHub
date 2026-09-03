"""Photoshop connector — drives Adobe Photoshop via COM (pywin32).

Mechanism `com`: ArchHub dispatches COM to an already-running Photoshop
in its own Python process — there is no localhost listener, no DLL is
loaded into Photoshop. So `live` means "GetActiveObject succeeded", not
"a listener responded".

Photoshop's COM ProgID is `Photoshop.Application`. Its object model
exposes Documents / ArtLayers / LayerSets directly, but a lot of detail
(precise unit-aware sizes, action-set enumeration, selection bounds) is
cleaner via ExtendScript through `app.DoJavaScript(...)`. We use the COM
object model where it is reliable and ExtendScript for the rest.

Discipline (copied from outlook_runner.py):
  * Every worker thread MUST CoInitialize before touching COM — the
    `com_thread()` context manager handles that. Qt6 background threads
    fast-fail 0xc0000409 without it.
  * pywin32 + the COM dispatch are lazy-imported so a machine without
    pywin32 or without Photoshop still imports this module fine.
  * probe() uses GetActiveObject ONLY — it never launches Photoshop.
  * No operation ever raises to the caller — COM failures become
    OpResult.fail(...).
"""
from __future__ import annotations

import contextlib
import json
from typing import Any

from connectors.base import (
    Connector, ConnectorOp, ParamSpec, OpResult, register,
)


_PROGID = "Photoshop.Application"

# Photoshop PsExportType enum.
_PS_SAVE_FOR_WEB = 2
# Photoshop PsLayerKind enum (subset we surface).
_LAYER_KIND = {
    1: "normal", 2: "text", 3: "solidfill", 4: "gradientfill",
    5: "patternfill", 6: "levels", 7: "curves", 8: "colorbalance",
    9: "brightnesscontrast", 10: "huesaturation", 11: "selectivecolor",
    12: "channelmixer", 13: "gradientmap", 14: "invert", 15: "threshold",
    16: "posterize", 17: "smartobject",
}


# ── COM plumbing ────────────────────────────────────────────────────
@contextlib.contextmanager
def com_thread():
    """Init + uninit the COM apartment for the current thread. Wrapping
    every public call in this prevents Qt6 0xc0000409 fast-fails when an
    op runs on a Qt-pumped background thread."""
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
    """Return the running Photoshop COM object, or raise RuntimeError.

    GetActiveObject ONLY — never launches Photoshop. Caller must already
    be inside com_thread()."""
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
            "Photoshop is not running. Open Photoshop and a document, "
            f"then retry. ({ex})"
        ) from ex


def _safe(v: Any, n: int = 0) -> str:
    s = "" if v is None else str(v)
    return s if not n else s[:n]


def _num(v: Any, default: float = 0.0) -> float:
    """Coerce a COM scalar / UnitValue to a float. Photoshop returns
    UnitValue objects for lengths — they stringify as e.g. '1920 px'."""
    try:
        return float(v)
    except Exception:
        try:
            return float(str(v).split()[0])
        except Exception:
            return default


def _eval_jsx(app, script: str) -> str:
    """Run ExtendScript in Photoshop, return the last expression as a
    string. Photoshop's DoJavaScript returns whatever the script's final
    statement evaluates to."""
    try:
        out = app.DoJavaScript(script)
    except Exception as ex:
        raise RuntimeError(f"ExtendScript failed: {ex}") from ex
    return "" if out is None else str(out)


def _jsx_json(app, script: str) -> Any:
    """Run ExtendScript expected to end with a JSON.stringify(...) and
    parse the result. Returns None on any parse failure."""
    raw = _eval_jsx(app, script)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


# ── operation implementations ───────────────────────────────────────
def _list_documents() -> OpResult:
    with com_thread():
        try:
            app = _active_app()
        except RuntimeError as ex:
            return OpResult.fail(str(ex))
        try:
            docs = app.Documents
            out: list[dict] = []
            active_name = ""
            try:
                active_name = _safe(app.ActiveDocument.Name)
            except Exception:
                active_name = ""
            for i in range(int(getattr(docs, "Count", 0) or 0)):
                try:
                    d = docs.Item(i + 1)
                    name = _safe(d.Name)
                    out.append({
                        "name": name,
                        "width_px": round(_num(d.Width), 1),
                        "height_px": round(_num(d.Height), 1),
                        "resolution_dpi": round(_num(d.Resolution), 1),
                        "layer_count": int(getattr(d.Layers, "Count", 0)
                                            or 0),
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


def _document_info() -> OpResult:
    with com_thread():
        try:
            app = _active_app()
        except RuntimeError as ex:
            return OpResult.fail(str(ex))
        try:
            d = app.ActiveDocument
        except Exception:
            return OpResult.fail(
                "No active document. Open a document in Photoshop.")
        try:
            mode_raw = getattr(d, "Mode", None)
            mode_map = {1: "Grayscale", 2: "RGB", 3: "CMYK", 4: "Lab",
                        5: "Bitmap", 6: "Indexed", 7: "Multichannel",
                        8: "Duotone"}
            mode = mode_map.get(int(mode_raw) if mode_raw is not None
                                else -1, str(mode_raw))
            bit_depth = 0
            try:
                bit_depth = int(getattr(d, "BitsPerChannel", 0) or 0)
            except Exception:
                bit_depth = 0
            info = {
                "name": _safe(d.Name),
                "path": _safe(getattr(d, "FullName", "")),
                "width_px": round(_num(d.Width), 1),
                "height_px": round(_num(d.Height), 1),
                "resolution_dpi": round(_num(d.Resolution), 1),
                "color_mode": mode,
                "bits_per_channel": bit_depth,
                "layer_count": int(getattr(d.Layers, "Count", 0) or 0),
                "saved": bool(getattr(d, "Saved", False)),
            }
            preview = (f"{info['name']} · "
                       f"{int(info['width_px'])}x{int(info['height_px'])}px"
                       f" · {info['color_mode']} · "
                       f"{int(info['resolution_dpi'])}dpi")
            return OpResult(ok=True, value=info, value_preview=preview)
        except Exception as ex:
            return OpResult.fail(f"document_info: {ex}")


def _list_layers() -> OpResult:
    """Flat list of every layer (recursing into groups). ExtendScript is
    far cleaner than walking COM LayerSets recursively."""
    with com_thread():
        try:
            app = _active_app()
        except RuntimeError as ex:
            return OpResult.fail(str(ex))
        try:
            _ = app.ActiveDocument
        except Exception:
            return OpResult.fail(
                "No active document. Open a document in Photoshop.")
        script = r"""
        (function () {
          var out = [];
          function walk(layers, depth, path) {
            for (var i = 0; i < layers.length; i++) {
              var ly = layers[i];
              var isGroup = (ly.typename === "LayerSet");
              var kind = "group";
              if (!isGroup) {
                try { kind = String(ly.kind); } catch (e) { kind = "art"; }
              }
              out.push({
                name: ly.name,
                kind: kind,
                is_group: isGroup,
                visible: ly.visible,
                depth: depth,
                path: path + ly.name,
                opacity: isGroup ? 100 : Math.round(ly.opacity)
              });
              if (isGroup) {
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
        # Normalize the kind field — ExtendScript returns the PsLayerKind
        # ordinal as a string for art layers.
        for row in data:
            k = row.get("kind", "")
            if k.isdigit():
                row["kind"] = _LAYER_KIND.get(int(k), f"kind{k}")
        preview = f"{len(data)} layer{'s' if len(data) != 1 else ''}"
        return OpResult(ok=True, value=data, value_preview=preview)


def _get_selection_bounds() -> OpResult:
    """Bounding box of the active selection, in pixels. ExtendScript —
    Photoshop's COM Selection object does not expose Bounds cleanly."""
    with com_thread():
        try:
            app = _active_app()
        except RuntimeError as ex:
            return OpResult.fail(str(ex))
        try:
            _ = app.ActiveDocument
        except Exception:
            return OpResult.fail(
                "No active document. Open a document in Photoshop.")
        script = r"""
        (function () {
          try {
            var b = app.activeDocument.selection.bounds;
            return JSON.stringify({
              has_selection: true,
              left:   b[0].as("px"),
              top:    b[1].as("px"),
              right:  b[2].as("px"),
              bottom: b[3].as("px")
            });
          } catch (e) {
            return JSON.stringify({has_selection: false});
          }
        })();
        """
        try:
            data = _jsx_json(app, script)
        except RuntimeError as ex:
            return OpResult.fail(str(ex))
        if not isinstance(data, dict):
            return OpResult.fail("get_selection_bounds: unexpected result")
        if not data.get("has_selection"):
            return OpResult(ok=True,
                            value={"has_selection": False},
                            value_preview="no active selection")
        left = round(_num(data.get("left")), 1)
        top = round(_num(data.get("top")), 1)
        right = round(_num(data.get("right")), 1)
        bottom = round(_num(data.get("bottom")), 1)
        out = {
            "has_selection": True,
            "left": left, "top": top, "right": right, "bottom": bottom,
            "width": round(right - left, 1),
            "height": round(bottom - top, 1),
        }
        preview = (f"selection {int(out['width'])}x{int(out['height'])}px "
                   f"@ ({int(left)},{int(top)})")
        return OpResult(ok=True, value=out, value_preview=preview)


def _export(format: str = "png", path: str = "") -> OpResult:
    """Export the active document to PNG or JPG via Save For Web."""
    fmt = (format or "png").strip().lower()
    if fmt not in ("png", "jpg", "jpeg"):
        return OpResult.fail(f"Unsupported format '{format}'. "
                             "Use 'png' or 'jpg'.")
    if not (path or "").strip():
        return OpResult.fail("export: 'path' is required.")
    with com_thread():
        try:
            app = _active_app()
        except RuntimeError as ex:
            return OpResult.fail(str(ex))
        try:
            d = app.ActiveDocument
        except Exception:
            return OpResult.fail(
                "No active document. Open a document in Photoshop.")
        try:
            import importlib as _il
            w = _il.import_module("win32com.client")
            opts = w.Dispatch("Photoshop.ExportOptionsSaveForWeb")
            if fmt in ("jpg", "jpeg"):
                opts.Format = 6      # PsSaveDocumentType.JPEG
                opts.Quality = 80
            else:
                opts.Format = 13     # PsSaveDocumentType.PNG
                opts.PNG8 = False
            d.Export(ExportIn=path, ExportAs=_PS_SAVE_FOR_WEB,
                     Options=opts)
            out = {"exported": True, "path": path, "format": fmt}
            return OpResult(ok=True, value=out,
                            value_preview=f"exported {fmt.upper()} → "
                                          f"{path}")
        except Exception as ex:
            return OpResult.fail(f"export: {ex}")


def _run_action(action_set: str = "", action_name: str = "") -> OpResult:
    """Play a recorded Photoshop action. `action_set` is the action
    set/folder name; `action_name` the action inside it."""
    if not (action_name or "").strip():
        return OpResult.fail("run_action: 'action_name' is required.")
    aset = (action_set or "Default Actions").strip()
    with com_thread():
        try:
            app = _active_app()
        except RuntimeError as ex:
            return OpResult.fail(str(ex))
        try:
            # Photoshop.Application.DoAction(action, from_set).
            app.DoAction(action_name, aset)
            out = {"ran": True, "action_set": aset,
                   "action_name": action_name}
            return OpResult(ok=True, value=out,
                            value_preview=f"ran '{action_name}' "
                                          f"({aset})")
        except Exception as ex:
            return OpResult.fail(
                f"run_action: could not play '{action_name}' from "
                f"set '{aset}' ({ex})")


def _set_layer_visibility(layer_name: str = "",
                          visible: bool = True) -> OpResult:
    """Toggle a layer's visibility by name. Searches groups recursively;
    acts on the first match."""
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
            _ = app.ActiveDocument
        except Exception:
            return OpResult.fail(
                "No active document. Open a document in Photoshop.")
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
              if (ly.typename === "LayerSet") { walk(ly.layers); }
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
class PhotoshopConnector(Connector):
    """Adobe Photoshop, driven over COM (pywin32) + ExtendScript."""

    host = "photoshop"
    display_name = "Adobe Photoshop"
    mechanism = "com"

    def probe(self) -> dict:
        """live  → Photoshop is running and reachable over COM.
        missing → Photoshop closed, or pywin32 not installed.
        Never launches Photoshop (GetActiveObject only)."""
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
                        "note": "Photoshop is not running",
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
            note = "Photoshop reachable"
            if detail.get("active_document"):
                note += f" · {detail['active_document']}"
            elif not detail.get("open_documents"):
                note += " · no document open"
            return {"status": "live", "note": note, "detail": detail}

    def build_ops(self) -> list:
        return [
            # ── reads ────────────────────────────────────────────────
            ConnectorOp(
                op_id="photoshop.list_documents",
                host="photoshop", kind="read",
                label="List documents",
                description="All open Photoshop documents with size, "
                            "dpi and layer count.",
                inputs=[],
                output_type="list", destructive=False,
                fn=_list_documents,
            ),
            ConnectorOp(
                op_id="photoshop.document_info",
                host="photoshop", kind="read",
                label="Document info",
                description="Size, resolution and color mode of the "
                            "active document.",
                inputs=[],
                output_type="any", destructive=False,
                fn=_document_info,
            ),
            ConnectorOp(
                op_id="photoshop.list_layers",
                host="photoshop", kind="read",
                label="List layers",
                description="Every layer in the active document — "
                            "name, kind, visibility (groups recursed).",
                inputs=[],
                output_type="list", destructive=False,
                fn=_list_layers,
            ),
            ConnectorOp(
                op_id="photoshop.get_selection_bounds",
                host="photoshop", kind="read",
                label="Get selection bounds",
                description="Bounding box of the active marquee "
                            "selection, in pixels.",
                inputs=[],
                output_type="any", destructive=False,
                fn=_get_selection_bounds,
            ),
            # ── actions ──────────────────────────────────────────────
            ConnectorOp(
                op_id="photoshop.export",
                host="photoshop", kind="action",
                label="Export document",
                description="Export the active document to a PNG or "
                            "JPG file.",
                inputs=[
                    ParamSpec(id="format", label="Format",
                              type="choice", default="png",
                              options=["png", "jpg"], required=True,
                              help="Output image format."),
                    ParamSpec(id="path", label="Output path",
                              type="file", default="", required=True,
                              help="Absolute path of the file to "
                                   "write."),
                ],
                output_type="any", destructive=True,
                fn=_export,
            ),
            ConnectorOp(
                op_id="photoshop.run_action",
                host="photoshop", kind="action",
                label="Run action",
                description="Play a recorded Photoshop action from an "
                            "action set.",
                inputs=[
                    ParamSpec(id="action_set", label="Action set",
                              type="text", default="Default Actions",
                              required=False,
                              help="Name of the action set/folder."),
                    ParamSpec(id="action_name", label="Action name",
                              type="text", default="", required=True,
                              help="Name of the action to play."),
                ],
                output_type="any", destructive=True,
                fn=_run_action,
            ),
            ConnectorOp(
                op_id="photoshop.set_layer_visibility",
                host="photoshop", kind="action",
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


register(PhotoshopConnector())
