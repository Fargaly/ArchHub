"""InDesign connector — drives Adobe InDesign via COM (pywin32).

Mechanism `com`: ArchHub COM-dispatches to an already-running InDesign
from its own Python process — no localhost listener, no plug-in is
loaded into InDesign. `live` means "GetActiveObject succeeded".

InDesign's COM ProgID is version-suffixed in practice. The generic
`InDesign.Application` resolves to the most recently registered
install, but on machines with several InDesign versions it can be
absent — so we probe the generic ProgID first, then a couple of
year-suffixed variants (`InDesign.Application.2024`, etc.).

InDesign's scripting bridge is ExtendScript via `app.DoScript(...)`
(NOT DoJavaScript — that is the Photoshop/Illustrator spelling).
DoScript takes a script string + a language constant; we pass the
InDesign JavaScript language enum so the same JSON-stringify pattern
works. Its COM object model also exposes Documents / Spreads /
TextFrames / styles / links, but DoScript keeps the recursion and
collection walking far simpler, so reads go through ExtendScript.

Discipline (copied from outlook_runner.py):
  * Every worker thread CoInitializes before touching COM — see
    `com_thread()`. Qt6 background threads fast-fail without it.
  * pywin32 + the COM dispatch are lazy-imported, so a machine without
    pywin32 or without InDesign still imports this module fine.
  * probe() uses GetActiveObject ONLY — it never launches InDesign.
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


# Generic ProgID first, then recent year-suffixed variants. InDesign
# bumps the suffix every release; this list covers the spread of
# installs ArchHub is likely to meet without launching anything.
_PROGIDS = [
    "InDesign.Application",
    "InDesign.Application.2025",
    "InDesign.Application.2024",
    "InDesign.Application.2023",
]

# idScriptLanguage.javascript — DoScript language constant. The numeric
# value (1246973031) is stable across InDesign versions; using the int
# avoids needing the typelib's named enum.
_JAVASCRIPT = 1246973031


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


def _get_active_app():
    """Return (app, progid) for the running InDesign, or raise
    RuntimeError. Tries the generic ProgID then year-suffixed variants.

    GetActiveObject ONLY — never launches InDesign. Caller must already
    be inside com_thread()."""
    try:
        import importlib as _il
        w = _il.import_module("win32com.client")
    except ImportError as ex:
        raise RuntimeError(
            "pywin32 not installed. Run: pip install pywin32"
        ) from ex
    last_err: Exception | None = None
    for progid in _PROGIDS:
        try:
            return w.GetActiveObject(progid), progid
        except Exception as ex:
            last_err = ex
            continue
    raise RuntimeError(
        "InDesign is not running. Open InDesign and a document, then "
        f"retry. ({last_err})"
    )


def _active_app():
    """Convenience: just the COM object."""
    app, _ = _get_active_app()
    return app


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


def _do_script(app, script: str) -> str:
    """Run ExtendScript in InDesign via DoScript, return the script's
    final expression as a string. InDesign's DoScript returns the value
    of the last statement."""
    try:
        out = app.DoScript(script, _JAVASCRIPT)
    except Exception as ex:
        raise RuntimeError(f"DoScript failed: {ex}") from ex
    return "" if out is None else str(out)


def _script_json(app, script: str) -> Any:
    """Run ExtendScript ending in JSON.stringify(...) and parse it.

    InDesign's ExtendScript engine has no global JSON object — we
    prepend a tiny json2-style stringify shim so scripts can rely on
    JSON.stringify regardless of the host version."""
    raw = _do_script(app, _JSON_SHIM + script)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


# Minimal JSON.stringify for InDesign's ExtendScript engine — handles
# the objects/arrays/strings/numbers/booleans our read scripts emit.
_JSON_SHIM = r"""
if (typeof JSON === "undefined") { JSON = {}; }
if (typeof JSON.stringify !== "function") {
  JSON.stringify = function (v) {
    function esc(s) {
      s = String(s);
      var o = "";
      for (var i = 0; i < s.length; i++) {
        var c = s.charAt(i), n = s.charCodeAt(i);
        if (c === '"' || c === '\\') { o += '\\' + c; }
        else if (c === '\n') { o += '\\n'; }
        else if (c === '\r') { o += '\\r'; }
        else if (c === '\t') { o += '\\t'; }
        else if (n < 32) {
          var h = n.toString(16);
          while (h.length < 4) { h = '0' + h; }
          o += '\\u' + h;
        } else { o += c; }
      }
      return o;
    }
    function enc(x) {
      if (x === null || x === undefined) { return "null"; }
      var t = typeof x;
      if (t === "number") { return isFinite(x) ? String(x) : "null"; }
      if (t === "boolean") { return String(x); }
      if (t === "string") { return '"' + esc(x) + '"'; }
      if (x instanceof Array) {
        var a = [];
        for (var i = 0; i < x.length; i++) { a.push(enc(x[i])); }
        return "[" + a.join(",") + "]";
      }
      if (t === "object") {
        var p = [];
        for (var k in x) {
          if (x.hasOwnProperty(k)) {
            p.push('"' + esc(k) + '":' + enc(x[k]));
          }
        }
        return "{" + p.join(",") + "}";
      }
      return "null";
    }
    return enc(v);
  };
}
"""


# ── operation implementations ───────────────────────────────────────
def _list_documents() -> OpResult:
    with com_thread():
        try:
            app = _active_app()
        except RuntimeError as ex:
            return OpResult.fail(str(ex))
        script = r"""
        (function () {
          var out = [];
          try {
            var active = "";
            try { active = app.activeDocument.name; } catch (e) {}
            for (var i = 0; i < app.documents.length; i++) {
              var d = app.documents[i];
              var path = "";
              try { path = d.fullName ? String(d.fullName) : ""; }
              catch (e) { path = ""; }
              out.push({
                name: d.name,
                page_count: d.pages.length,
                spread_count: d.spreads.length,
                story_count: d.stories.length,
                modified: d.modified,
                saved: (path !== ""),
                path: path,
                active: (d.name === active)
              });
            }
          } catch (e) { return JSON.stringify({error: String(e)}); }
          return JSON.stringify(out);
        })();
        """
        try:
            data = _script_json(app, script)
        except RuntimeError as ex:
            return OpResult.fail(str(ex))
        if isinstance(data, dict) and data.get("error"):
            return OpResult.fail(f"list_documents: {data['error']}")
        if not isinstance(data, list):
            return OpResult.fail("list_documents: unexpected result")
        preview = (f"{len(data)} document"
                   f"{'s' if len(data) != 1 else ''} open")
        return OpResult(ok=True, value=data, value_preview=preview)


def _list_spreads() -> OpResult:
    """Spreads of the active document with the pages on each."""
    with com_thread():
        try:
            app = _active_app()
        except RuntimeError as ex:
            return OpResult.fail(str(ex))
        script = r"""
        (function () {
          var out = [];
          try {
            var doc = app.activeDocument;
            for (var i = 0; i < doc.spreads.length; i++) {
              var sp = doc.spreads[i];
              var pages = [];
              for (var p = 0; p < sp.pages.length; p++) {
                pages.push(sp.pages[p].name);
              }
              out.push({
                index: i,
                page_count: sp.pages.length,
                pages: pages,
                item_count: sp.pageItems.length
              });
            }
          } catch (e) { return JSON.stringify({error: String(e)}); }
          return JSON.stringify(out);
        })();
        """
        try:
            data = _script_json(app, script)
        except RuntimeError as ex:
            return OpResult.fail(str(ex))
        if isinstance(data, dict) and data.get("error"):
            return OpResult.fail(
                f"list_spreads: {data['error']} "
                "(is a document open?)")
        if not isinstance(data, list):
            return OpResult.fail("list_spreads: no active document")
        preview = f"{len(data)} spread{'s' if len(data) != 1 else ''}"
        return OpResult(ok=True, value=data, value_preview=preview)


def _list_text_frames() -> OpResult:
    """Every text frame of the active document — page, contents
    preview, overset state."""
    with com_thread():
        try:
            app = _active_app()
        except RuntimeError as ex:
            return OpResult.fail(str(ex))
        script = r"""
        (function () {
          var out = [];
          try {
            var doc = app.activeDocument;
            var tfs = doc.textFrames;
            for (var i = 0; i < tfs.length; i++) {
              var tf = tfs[i];
              var page = "";
              try { page = tf.parentPage ? tf.parentPage.name
                                         : "(pasteboard)"; }
              catch (e) { page = ""; }
              var txt = "";
              try { txt = String(tf.contents); } catch (e) { txt = ""; }
              if (txt.length > 120) { txt = txt.substring(0, 120); }
              out.push({
                index: i,
                page: page,
                overset: tf.overflows,
                char_count: (function () {
                  try { return tf.characters.length; }
                  catch (e) { return 0; }
                })(),
                contents_preview: txt
              });
            }
          } catch (e) { return JSON.stringify({error: String(e)}); }
          return JSON.stringify(out);
        })();
        """
        try:
            data = _script_json(app, script)
        except RuntimeError as ex:
            return OpResult.fail(str(ex))
        if isinstance(data, dict) and data.get("error"):
            return OpResult.fail(
                f"list_text_frames: {data['error']} "
                "(is a document open?)")
        if not isinstance(data, list):
            return OpResult.fail(
                "list_text_frames: no active document")
        preview = (f"{len(data)} text frame"
                   f"{'s' if len(data) != 1 else ''}")
        return OpResult(ok=True, value=data, value_preview=preview)


def _list_paragraph_styles() -> OpResult:
    """Paragraph styles of the active document, including styles nested
    in style groups."""
    with com_thread():
        try:
            app = _active_app()
        except RuntimeError as ex:
            return OpResult.fail(str(ex))
        script = r"""
        (function () {
          var out = [];
          try {
            var doc = app.activeDocument;
            var styles = doc.allParagraphStyles;
            for (var i = 0; i < styles.length; i++) {
              var st = styles[i];
              var size = 0;
              try { size = st.pointSize; } catch (e) { size = 0; }
              out.push({
                name: st.name,
                point_size: size,
                applied: false
              });
            }
          } catch (e) { return JSON.stringify({error: String(e)}); }
          return JSON.stringify(out);
        })();
        """
        try:
            data = _script_json(app, script)
        except RuntimeError as ex:
            return OpResult.fail(str(ex))
        if isinstance(data, dict) and data.get("error"):
            return OpResult.fail(
                f"list_paragraph_styles: {data['error']} "
                "(is a document open?)")
        if not isinstance(data, list):
            return OpResult.fail(
                "list_paragraph_styles: no active document")
        preview = f"{len(data)} paragraph style" + (
            "s" if len(data) != 1 else "")
        return OpResult(ok=True, value=data, value_preview=preview)


def _list_links() -> OpResult:
    """Placed links (images, etc.) of the active document with their
    status."""
    with com_thread():
        try:
            app = _active_app()
        except RuntimeError as ex:
            return OpResult.fail(str(ex))
        script = r"""
        (function () {
          var out = [];
          try {
            var doc = app.activeDocument;
            for (var i = 0; i < doc.links.length; i++) {
              var lk = doc.links[i];
              out.push({
                name: lk.name,
                status: String(lk.status),
                file_path: (function () {
                  try { return String(lk.filePath); }
                  catch (e) { return ""; }
                })(),
                size_bytes: (function () {
                  try { return Number(lk.size); }
                  catch (e) { return 0; }
                })()
              });
            }
          } catch (e) { return JSON.stringify({error: String(e)}); }
          return JSON.stringify(out);
        })();
        """
        try:
            data = _script_json(app, script)
        except RuntimeError as ex:
            return OpResult.fail(str(ex))
        if isinstance(data, dict) and data.get("error"):
            return OpResult.fail(
                f"list_links: {data['error']} "
                "(is a document open?)")
        if not isinstance(data, list):
            return OpResult.fail("list_links: no active document")
        # InDesign LinkStatus enums stringify as e.g. 'NORMAL',
        # 'LINK_OUT_OF_DATE', 'LINK_MISSING' — normalize to lower-case.
        for row in data:
            row["status"] = _safe(row.get("status")).lower()
        out_of_date = sum(1 for r in data
                          if "out_of_date" in r.get("status", "")
                          or "missing" in r.get("status", ""))
        preview = f"{len(data)} link{'s' if len(data) != 1 else ''}"
        if out_of_date:
            preview += f" · {out_of_date} need update"
        return OpResult(ok=True, value=data, value_preview=preview)


def _export_pdf(path: str = "", preset: str = "") -> OpResult:
    """Export the active document to PDF.

    `preset` is an optional PDF export preset name (e.g. '[High Quality
    Print]'); empty uses InDesign's current default. Export goes through
    the COM object model — Document.Export(format, to, showingOptions,
    using)."""
    if not (path or "").strip():
        return OpResult.fail("export_pdf: 'path' is required.")
    with com_thread():
        try:
            app = _active_app()
        except RuntimeError as ex:
            return OpResult.fail(str(ex))
        try:
            doc = app.ActiveDocument
        except Exception:
            return OpResult.fail(
                "No active document. Open one in InDesign.")
        try:
            # Resolve the PDF export preset by name when one is given.
            preset_obj = None
            chosen_preset = ""
            pname = (preset or "").strip()
            if pname:
                try:
                    p = app.PDFExportPresets.Item(pname)
                    # Touch a property to confirm it resolved.
                    chosen_preset = _safe(p.Name)
                    preset_obj = p
                except Exception:
                    preset_obj = None
                    chosen_preset = ""
            # idExportFormat.pdfType — the string form 'PDF Type' is
            # accepted by Document.Export across InDesign versions.
            if preset_obj is not None:
                doc.Export("PDF Type", path, False, preset_obj)
            else:
                doc.Export("PDF Type", path, False)
            out = {"exported": True, "path": path,
                   "preset": chosen_preset or "(default)"}
            return OpResult(ok=True, value=out,
                            value_preview=f"exported PDF → {path}")
        except Exception as ex:
            return OpResult.fail(f"export_pdf: {ex}")


def _update_links(only_out_of_date: bool = True) -> OpResult:
    """Update placed links in the active document. When
    `only_out_of_date` is True, relinks only modified/out-of-date
    links; otherwise updates every link that can be updated."""
    with com_thread():
        try:
            app = _active_app()
        except RuntimeError as ex:
            return OpResult.fail(str(ex))
        flag = "true" if bool(only_out_of_date) else "false"
        script = r"""
        (function () {
          var onlyStale = %s;
          var updated = 0, failed = 0, skipped = 0;
          try {
            var doc = app.activeDocument;
            for (var i = 0; i < doc.links.length; i++) {
              var lk = doc.links[i];
              var status = String(lk.status);
              var stale = (status.indexOf("OUT_OF_DATE") !== -1) ||
                          (status.indexOf("MISSING") !== -1);
              if (onlyStale && !stale) { skipped++; continue; }
              try { lk.update(); updated++; }
              catch (e) { failed++; }
            }
          } catch (e) { return JSON.stringify({error: String(e)}); }
          return JSON.stringify({updated: updated, failed: failed,
                                 skipped: skipped});
        })();
        """ % flag
        try:
            data = _script_json(app, script)
        except RuntimeError as ex:
            return OpResult.fail(str(ex))
        if isinstance(data, dict) and data.get("error"):
            return OpResult.fail(
                f"update_links: {data['error']} "
                "(is a document open?)")
        if not isinstance(data, dict):
            return OpResult.fail("update_links: no active document")
        out = {
            "updated": int(data.get("updated", 0)),
            "failed": int(data.get("failed", 0)),
            "skipped": int(data.get("skipped", 0)),
            "only_out_of_date": bool(only_out_of_date),
        }
        preview = (f"{out['updated']} link"
                   f"{'s' if out['updated'] != 1 else ''} updated")
        if out["failed"]:
            preview += f" · {out['failed']} failed"
        return OpResult(ok=True, value=out, value_preview=preview)


# ── connector ───────────────────────────────────────────────────────
class InDesignConnector(Connector):
    """Adobe InDesign, driven over COM (pywin32) + ExtendScript."""

    host = "indesign"
    display_name = "Adobe InDesign"
    mechanism = "com"

    def probe(self) -> dict:
        """live  → InDesign is running and reachable over COM.
        missing → InDesign closed, or pywin32 not installed.
        Tries the generic ProgID then year-suffixed variants. Never
        launches InDesign (GetActiveObject only)."""
        with com_thread():
            try:
                import importlib as _il
                w = _il.import_module("win32com.client")
            except ImportError:
                return {"status": "missing",
                        "note": "pywin32 not installed "
                                "(pip install pywin32)",
                        "detail": {}}
            app = None
            used_progid = ""
            for progid in _PROGIDS:
                try:
                    app = w.GetActiveObject(progid)
                    used_progid = progid
                    break
                except Exception:
                    continue
            if app is None:
                return {"status": "missing",
                        "note": "InDesign is not running",
                        "detail": {"progids_tried": list(_PROGIDS)}}
            detail: dict = {"progid": used_progid}
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
            note = "InDesign reachable"
            if detail.get("active_document"):
                note += f" · {detail['active_document']}"
            elif not detail.get("open_documents"):
                note += " · no document open"
            return {"status": "live", "note": note, "detail": detail}

    def build_ops(self) -> list:
        return [
            # ── reads ────────────────────────────────────────────────
            ConnectorOp(
                op_id="indesign.list_documents",
                host="indesign", kind="read",
                label="List documents",
                description="All open InDesign documents with page, "
                            "spread and story counts.",
                inputs=[],
                output_type="list", destructive=False,
                fn=_list_documents,
            ),
            ConnectorOp(
                op_id="indesign.list_spreads",
                host="indesign", kind="read",
                label="List spreads",
                description="Spreads of the active document and the "
                            "pages on each.",
                inputs=[],
                output_type="list", destructive=False,
                fn=_list_spreads,
            ),
            ConnectorOp(
                op_id="indesign.list_text_frames",
                host="indesign", kind="read",
                label="List text frames",
                description="Every text frame of the active document "
                            "— page, contents preview, overset state.",
                inputs=[],
                output_type="list", destructive=False,
                fn=_list_text_frames,
            ),
            ConnectorOp(
                op_id="indesign.list_paragraph_styles",
                host="indesign", kind="read",
                label="List paragraph styles",
                description="Paragraph styles of the active document, "
                            "including styles inside style groups.",
                inputs=[],
                output_type="list", destructive=False,
                fn=_list_paragraph_styles,
            ),
            ConnectorOp(
                op_id="indesign.list_links",
                host="indesign", kind="read",
                label="List links",
                description="Placed links (images, etc.) of the "
                            "active document with their status.",
                inputs=[],
                output_type="list", destructive=False,
                fn=_list_links,
            ),
            # ── actions ──────────────────────────────────────────────
            ConnectorOp(
                op_id="indesign.export_pdf",
                host="indesign", kind="action",
                label="Export PDF",
                description="Export the active document to a PDF "
                            "file, optionally using a named preset.",
                inputs=[
                    ParamSpec(id="path", label="Output path",
                              type="file", default="", required=True,
                              help="Absolute path of the PDF to "
                                   "write."),
                    ParamSpec(id="preset", label="PDF preset",
                              type="text", default="", required=False,
                              help="PDF export preset name, e.g. "
                                   "'[High Quality Print]'. Empty "
                                   "uses the default."),
                ],
                output_type="any", destructive=True,
                fn=_export_pdf,
            ),
            ConnectorOp(
                op_id="indesign.update_links",
                host="indesign", kind="action",
                label="Update links",
                description="Relink/update placed links in the active "
                            "document.",
                inputs=[
                    ParamSpec(id="only_out_of_date",
                              label="Only out-of-date",
                              type="bool", default=True,
                              required=False,
                              help="True updates only modified or "
                                   "missing links; False updates all."),
                ],
                output_type="any", destructive=True,
                fn=_update_links,
            ),
        ]


register(InDesignConnector())
