"""PowerPoint connector — drives Microsoft PowerPoint via COM (pywin32).

Part of the Office COM connector cluster (Word · Excel · PowerPoint).
Subclasses the uniform `Connector` contract in `connectors/base.py`.

Architecture mirrors `outlook_runner.py`: the connector runs IN ArchHub's
own Python process and COM-dispatches to the user's PowerPoint. There is no
localhost listener and no add-in loaded into PowerPoint.

COM discipline:
  * Every public op runs inside `com_thread()` so `pythoncom.CoInitialize()`
    fires first — PowerPoint COM calls fast-fail (0xc0000409) on Qt-pumped
    worker threads without it.
  * `probe()` uses `GetActiveObject` ONLY, so it reports `missing` when
    PowerPoint is closed instead of launching it.
  * Ops use `_ppt_app()` which prefers `GetActiveObject` and falls back to
    `Dispatch` so driving an op can always complete.

Limitations:
  * Classic desktop PowerPoint only. PowerPoint for the web has no COM.
  * Operates on the presentations open in PowerPoint's `Presentations`
    collection; callers pass a presentation name to target one.
"""
from __future__ import annotations

import contextlib
import os
from typing import Any, Optional

from connectors.base import (
    Connector,
    ConnectorOp,
    OpResult,
    ParamSpec,
    register,
)


_PROGID = "PowerPoint.Application"

# PowerPoint enum constants (avoid importing the typelib).
_PP_SAVE_AS_PDF = 32             # PpSaveAsFileType.ppSaveAsPDF
_PP_LAYOUT_TEXT = 2              # PpSlideLayout.ppLayoutText
_PP_LAYOUT_BLANK = 12            # PpSlideLayout.ppLayoutBlank
_MSO_TRUE = -1                   # MsoTriState.msoTrue
_PP_PLACEHOLDER = 14             # MsoShapeType.msoPlaceholder


def _shape_type_name(code: int) -> str:
    """MsoShapeType code → readable label for the common cases."""
    return {
        1: "auto_shape", 3: "chart", 6: "group", 7: "embedded_ole",
        8: "form_control", 9: "line", 11: "ole_control", 13: "picture",
        14: "placeholder", 17: "text_box", 19: "table", 20: "smart_art",
        21: "media", 24: "diagram", 25: "canvas",
    }.get(int(code or 0), f"type_{code}")


# ── COM thread discipline ───────────────────────────────────────────
@contextlib.contextmanager
def com_thread():
    """Init + uninit the COM apartment for the current thread. Wrap every
    public op in this — prevents Qt6Core 0xc0000409 fast-fails when ops run
    on background threads pumped by Qt. Copied from outlook_runner.py."""
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


def _win32():
    """Lazy import of win32com.client. Raises a clean RuntimeError when
    pywin32 is missing so a worker can surface one readable message."""
    try:
        import win32com.client as w
        return w
    except ImportError as ex:
        raise RuntimeError(
            "pywin32 not installed. Run: pip install pywin32"
        ) from ex


def _ppt_app():
    """Get the PowerPoint.Application COM object for OPERATIONS.

    Prefers a running instance via GetActiveObject; falls back to Dispatch
    (which starts PowerPoint) so an op can always complete its work.
    """
    w = _win32()
    try:
        return w.GetActiveObject(_PROGID)
    except Exception:
        pass
    try:
        app = w.Dispatch(_PROGID)
        # PowerPoint must be visible before most object-model calls work.
        try:
            app.Visible = _MSO_TRUE
        except Exception:
            pass
        return app
    except Exception as ex:
        raise RuntimeError(
            f"Could not connect to PowerPoint. Open PowerPoint and try "
            f"again. ({ex})"
        ) from ex


def _ppt_app_probe():
    """PowerPoint.Application for PROBE only — GetActiveObject ONLY, never
    starts PowerPoint. Raises if PowerPoint is not already running."""
    w = _win32()
    return w.GetActiveObject(_PROGID)


def _safe(s: Any, n: int = 0) -> str:
    s = "" if s is None else str(s)
    return s if not n else s[:n]


def _find_pres(app, presentation: str = ""):
    """Resolve a presentation by name from the Presentations collection.

    Match is case-insensitive against the short Name and the FullName path.
    Empty name → the ActivePresentation. Raises a clean RuntimeError listing
    what IS open on miss.
    """
    pres = app.Presentations
    if pres is None or pres.Count == 0:
        raise RuntimeError("No presentations are open in PowerPoint.")
    if not presentation:
        try:
            active = app.ActivePresentation
            if active is not None:
                return active
        except Exception:
            pass
        return pres.Item(1)
    want = str(presentation).strip().lower()
    names: list[str] = []
    for i in range(pres.Count):
        p = pres.Item(i + 1)
        name = _safe(getattr(p, "Name", ""))
        full = _safe(getattr(p, "FullName", ""))
        names.append(name)
        if want in (name.lower(), full.lower()):
            return p
        if want == os.path.basename(full).lower():
            return p
    raise RuntimeError(
        f"Presentation '{presentation}' not open. Open presentations: "
        + ", ".join(names)
    )


def _slide_at(pres, slide_index: int):
    """Resolve a 1-based slide index within a presentation. Raises a clean
    RuntimeError when out of range."""
    slides = pres.Slides
    count = int(slides.Count)
    if count == 0:
        raise RuntimeError("Presentation has no slides.")
    idx = int(slide_index or 1)
    if idx < 1 or idx > count:
        raise RuntimeError(
            f"Slide index {idx} out of range (1..{count})."
        )
    return slides.Item(idx)


def _shape_text(shape) -> str:
    """Best-effort extraction of a shape's text."""
    try:
        if int(getattr(shape, "HasTextFrame", 0)) != -1:
            return ""
        tf = shape.TextFrame
        if int(getattr(tf, "HasText", 0)) != -1:
            return ""
        return _safe(tf.TextRange.Text).replace("\r", "\n")
    except Exception:
        return ""


# ── operation implementations ───────────────────────────────────────
def _list_presentations() -> OpResult:
    """Every presentation currently open in PowerPoint."""
    with com_thread():
        try:
            app = _ppt_app()
        except RuntimeError as ex:
            return OpResult.fail(str(ex), "powerpoint.list_presentations")
        try:
            pres = app.Presentations
            out: list[dict] = []
            for i in range(pres.Count):
                p = pres.Item(i + 1)
                try:
                    slide_count = int(p.Slides.Count)
                except Exception:
                    slide_count = -1
                out.append({
                    "name": _safe(getattr(p, "Name", "")),
                    "full_name": _safe(getattr(p, "FullName", "")),
                    "saved": bool(getattr(p, "Saved", True)),
                    "read_only": int(getattr(p, "ReadOnly", 0)) == -1,
                    "slides": slide_count,
                })
            active = ""
            try:
                active = _safe(app.ActivePresentation.Name)
            except Exception:
                pass
            return OpResult(
                ok=True, value=out, op_id="powerpoint.list_presentations",
                value_preview=(
                    f"{len(out)} presentation"
                    f"{'s' if len(out) != 1 else ''}"
                    + (f" · active: {active}" if active else "")
                ),
            )
        except Exception as ex:
            return OpResult.fail(
                f"{type(ex).__name__}: {ex}",
                "powerpoint.list_presentations")


def _list_slides(presentation: str = "") -> OpResult:
    """Every slide in a presentation with its title and shape count."""
    with com_thread():
        try:
            app = _ppt_app()
            pres = _find_pres(app, presentation)
        except RuntimeError as ex:
            return OpResult.fail(str(ex), "powerpoint.list_slides")
        try:
            slides = pres.Slides
            out: list[dict] = []
            for i in range(int(slides.Count)):
                s = slides.Item(i + 1)
                # Title — prefer the title placeholder.
                title = ""
                try:
                    if int(s.Shapes.HasTitle) == -1:
                        title = _safe(
                            s.Shapes.Title.TextFrame.TextRange.Text
                        ).replace("\r", " ").strip()
                except Exception:
                    title = ""
                layout = ""
                try:
                    layout = _safe(s.Layout)
                except Exception:
                    pass
                out.append({
                    "index": i + 1,
                    "slide_id": int(getattr(s, "SlideID", 0) or 0),
                    "title": title[:300],
                    "layout": layout,
                    "shape_count": int(s.Shapes.Count),
                })
            return OpResult(
                ok=True, value=out, op_id="powerpoint.list_slides",
                value_preview=(
                    f"{len(out)} slide{'s' if len(out) != 1 else ''}"
                ),
            )
        except Exception as ex:
            return OpResult.fail(
                f"{type(ex).__name__}: {ex}", "powerpoint.list_slides")


def _list_shapes(presentation: str = "", slide_index: int = 1) -> OpResult:
    """Every shape on one slide with type, position, and text."""
    with com_thread():
        try:
            app = _ppt_app()
            pres = _find_pres(app, presentation)
            slide = _slide_at(pres, slide_index)
        except RuntimeError as ex:
            return OpResult.fail(str(ex), "powerpoint.list_shapes")
        try:
            shapes = slide.Shapes
            out: list[dict] = []
            for i in range(int(shapes.Count)):
                sh = shapes.Item(i + 1)
                stype = 0
                try:
                    stype = int(sh.Type)
                except Exception:
                    pass
                out.append({
                    "index": i + 1,
                    "name": _safe(getattr(sh, "Name", "")),
                    "shape_type": _shape_type_name(stype),
                    "shape_type_code": stype,
                    "left": round(float(getattr(sh, "Left", 0) or 0), 1),
                    "top": round(float(getattr(sh, "Top", 0) or 0), 1),
                    "width": round(float(getattr(sh, "Width", 0) or 0), 1),
                    "height": round(float(getattr(sh, "Height", 0) or 0), 1),
                    "has_text": int(getattr(sh, "HasTextFrame", 0)) == -1,
                    "text": _shape_text(sh)[:2000],
                })
            return OpResult(
                ok=True, value=out, op_id="powerpoint.list_shapes",
                value_preview=(
                    f"{len(out)} shape{'s' if len(out) != 1 else ''} "
                    f"on slide {int(slide_index or 1)}"
                ),
            )
        except Exception as ex:
            return OpResult.fail(
                f"{type(ex).__name__}: {ex}", "powerpoint.list_shapes")


def _read_notes(presentation: str = "") -> OpResult:
    """The speaker-notes text of every slide."""
    with com_thread():
        try:
            app = _ppt_app()
            pres = _find_pres(app, presentation)
        except RuntimeError as ex:
            return OpResult.fail(str(ex), "powerpoint.read_notes")
        try:
            slides = pres.Slides
            out: list[dict] = []
            for i in range(int(slides.Count)):
                s = slides.Item(i + 1)
                notes = ""
                try:
                    np = s.NotesPage
                    # The notes body is the placeholder with text on the
                    # notes page (skip the slide-image placeholder).
                    for j in range(int(np.Shapes.Count)):
                        sh = np.Shapes.Item(j + 1)
                        if int(getattr(sh, "HasTextFrame", 0)) != -1:
                            continue
                        tr = sh.TextFrame.TextRange
                        txt = _safe(tr.Text).replace("\r", "\n").strip()
                        if txt:
                            notes = txt
                            break
                except Exception:
                    notes = ""
                out.append({
                    "slide_index": i + 1,
                    "notes": notes[:5000],
                    "char_count": len(notes),
                })
            with_notes = sum(1 for n in out if n["char_count"] > 0)
            return OpResult(
                ok=True, value=out, op_id="powerpoint.read_notes",
                value_preview=(
                    f"{with_notes}/{len(out)} slides have notes"
                ),
            )
        except Exception as ex:
            return OpResult.fail(
                f"{type(ex).__name__}: {ex}", "powerpoint.read_notes")


def _add_slide(presentation: str = "", position: int = 0,
               layout: str = "blank") -> OpResult:
    """Add a new slide. DESTRUCTIVE — mutates the presentation.
    position 0 = append at the end."""
    with com_thread():
        try:
            app = _ppt_app()
            pres = _find_pres(app, presentation)
        except RuntimeError as ex:
            return OpResult.fail(str(ex), "powerpoint.add_slide")
        try:
            slides = pres.Slides
            count = int(slides.Count)
            pos = int(position or 0)
            if pos < 1 or pos > count + 1:
                pos = count + 1
            layout_code = (
                _PP_LAYOUT_TEXT if str(layout or "").lower() == "text"
                else _PP_LAYOUT_BLANK
            )
            new = slides.Add(pos, layout_code)
            return OpResult(
                ok=True,
                value={
                    "presentation": _safe(getattr(pres, "Name", "")),
                    "slide_index": int(getattr(new, "SlideIndex", pos)),
                    "slide_id": int(getattr(new, "SlideID", 0) or 0),
                    "layout": str(layout or "blank"),
                    "total_slides": int(slides.Count),
                },
                op_id="powerpoint.add_slide",
                value_preview=(
                    f"added slide {int(getattr(new, 'SlideIndex', pos))} "
                    f"of {int(slides.Count)}"
                ),
            )
        except Exception as ex:
            return OpResult.fail(
                f"{type(ex).__name__}: {ex}", "powerpoint.add_slide")


def _set_shape_text(presentation: str = "", slide_index: int = 1,
                    shape_index: int = 1, text: str = "") -> OpResult:
    """Set the text of a shape on a slide. DESTRUCTIVE — mutates the slide."""
    with com_thread():
        try:
            app = _ppt_app()
            pres = _find_pres(app, presentation)
            slide = _slide_at(pres, slide_index)
        except RuntimeError as ex:
            return OpResult.fail(str(ex), "powerpoint.set_shape_text")
        try:
            shapes = slide.Shapes
            count = int(shapes.Count)
            idx = int(shape_index or 1)
            if idx < 1 or idx > count:
                return OpResult.fail(
                    f"Shape index {idx} out of range (1..{count}).",
                    "powerpoint.set_shape_text")
            sh = shapes.Item(idx)
            if int(getattr(sh, "HasTextFrame", 0)) != -1:
                return OpResult.fail(
                    f"Shape {idx} ('{_safe(getattr(sh, 'Name', ''))}') "
                    f"has no text frame.",
                    "powerpoint.set_shape_text")
            sh.TextFrame.TextRange.Text = str(text)
            return OpResult(
                ok=True,
                value={
                    "presentation": _safe(getattr(pres, "Name", "")),
                    "slide_index": int(slide_index or 1),
                    "shape_index": idx,
                    "shape_name": _safe(getattr(sh, "Name", "")),
                    "text_length": len(str(text)),
                },
                op_id="powerpoint.set_shape_text",
                value_preview=(
                    f"set {len(str(text))} chars on "
                    f"'{_safe(getattr(sh, 'Name', ''))}'"
                ),
            )
        except Exception as ex:
            return OpResult.fail(
                f"{type(ex).__name__}: {ex}", "powerpoint.set_shape_text")


def _export_pdf(presentation: str = "", output_path: str = "") -> OpResult:
    """Export a presentation to PDF. DESTRUCTIVE — writes to disk."""
    with com_thread():
        try:
            app = _ppt_app()
            pres = _find_pres(app, presentation)
        except RuntimeError as ex:
            return OpResult.fail(str(ex), "powerpoint.export_pdf")
        try:
            path = str(output_path or "").strip()
            if not path:
                full = _safe(getattr(pres, "FullName", ""))
                if full and not full.lower().endswith(".pdf"):
                    base = os.path.splitext(full)[0]
                else:
                    name = _safe(getattr(pres, "Name", "presentation"))
                    base = os.path.join(
                        os.path.expanduser("~"), os.path.splitext(name)[0])
                path = base + ".pdf"
            parent = os.path.dirname(path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            # SaveAs with the PDF file type is the most reliable export path.
            pres.SaveAs(path, _PP_SAVE_AS_PDF)
            size = os.path.getsize(path) if os.path.exists(path) else 0
            return OpResult(
                ok=True,
                value={
                    "presentation": _safe(getattr(pres, "Name", "")),
                    "pdf_path": path,
                    "size_bytes": size,
                },
                op_id="powerpoint.export_pdf",
                value_preview=f"PDF · {size:,} bytes",
            )
        except Exception as ex:
            return OpResult.fail(
                f"{type(ex).__name__}: {ex}", "powerpoint.export_pdf")


# ── connector ───────────────────────────────────────────────────────
class PowerPointConnector(Connector):
    """Microsoft PowerPoint — drives the desktop app over COM."""

    host = "powerpoint"
    display_name = "Microsoft PowerPoint"
    mechanism = "com"

    def probe(self) -> dict:
        """live only when PowerPoint is already running (GetActiveObject
        succeeds); missing when closed; unauthorized on COM-permission
        failures. Never starts PowerPoint."""
        try:
            _win32()
        except RuntimeError as ex:
            return {"status": "missing", "note": str(ex), "detail": {}}
        with com_thread():
            try:
                app = _ppt_app_probe()
            except Exception as ex:
                msg = str(ex).lower()
                if "access" in msg or "denied" in msg or "0x80070005" in msg:
                    return {
                        "status": "unauthorized",
                        "note": f"PowerPoint COM access denied: {ex}",
                        "detail": {},
                    }
                return {
                    "status": "missing",
                    "note": (
                        "PowerPoint is not running. Open PowerPoint to "
                        "connect."
                    ),
                    "detail": {},
                }
            try:
                pres = app.Presentations
                pres_count = int(pres.Count)
                active = ""
                try:
                    active = _safe(app.ActivePresentation.Name)
                except Exception:
                    active = ""
                return {
                    "status": "live",
                    "note": (
                        f"PowerPoint running · {pres_count} presentation"
                        f"{'s' if pres_count != 1 else ''} open"
                    ),
                    "detail": {
                        "version": _safe(getattr(app, "Version", "")),
                        "presentations_open": pres_count,
                        "active_presentation": active,
                    },
                }
            except Exception as ex:
                return {
                    "status": "loaded_dead",
                    "note": (
                        f"PowerPoint reachable but not responding: {ex}"
                    ),
                    "detail": {},
                }

    def build_ops(self) -> list:
        pres_param = ParamSpec(
            id="presentation", label="Presentation", type="choice",
            options_source="powerpoint.list_presentations",
            help="Open presentation to target. Empty = active presentation.",
        )
        return [
            # ---- READS ----
            ConnectorOp(
                op_id="powerpoint.list_presentations", host="powerpoint",
                kind="read", label="List presentations",
                description="Every presentation open in PowerPoint.",
                inputs=[], output_type="list", destructive=False,
                fn=_list_presentations,
            ),
            ConnectorOp(
                op_id="powerpoint.list_slides", host="powerpoint",
                kind="read", label="List slides",
                description="Every slide with title and shape count.",
                inputs=[pres_param],
                output_type="slide", destructive=False,
                fn=_list_slides,
            ),
            ConnectorOp(
                op_id="powerpoint.list_shapes", host="powerpoint",
                kind="read", label="List shapes",
                description="Every shape on one slide.",
                inputs=[
                    pres_param,
                    ParamSpec(id="slide_index", label="Slide index",
                              type="number", default=1, required=True,
                              help="1-based slide number."),
                ],
                output_type="list", destructive=False,
                fn=_list_shapes,
            ),
            ConnectorOp(
                op_id="powerpoint.read_notes", host="powerpoint",
                kind="read", label="Read notes",
                description="Speaker notes of every slide.",
                inputs=[pres_param],
                output_type="list", destructive=False,
                fn=_read_notes,
            ),
            # ---- ACTIONS ----
            ConnectorOp(
                op_id="powerpoint.add_slide", host="powerpoint",
                kind="action", label="Add slide",
                description="Insert a new slide into the presentation.",
                inputs=[
                    pres_param,
                    ParamSpec(id="position", label="Position",
                              type="number", default=0,
                              help="1-based insert index. 0 = append at end."),
                    ParamSpec(id="layout", label="Layout", type="choice",
                              default="blank", options=["blank", "text"],
                              help="Slide layout for the new slide."),
                ],
                output_type="any", destructive=True,
                fn=_add_slide,
            ),
            ConnectorOp(
                op_id="powerpoint.set_shape_text", host="powerpoint",
                kind="action", label="Set shape text",
                description="Set the text of a shape on a slide.",
                inputs=[
                    pres_param,
                    ParamSpec(id="slide_index", label="Slide index",
                              type="number", default=1, required=True,
                              help="1-based slide number."),
                    ParamSpec(id="shape_index", label="Shape index",
                              type="number", default=1, required=True,
                              help="1-based shape number on the slide."),
                    ParamSpec(id="text", label="Text", type="text",
                              required=True, help="Text to set on the shape."),
                ],
                output_type="any", destructive=True,
                fn=_set_shape_text,
            ),
            ConnectorOp(
                op_id="powerpoint.export_pdf", host="powerpoint",
                kind="action", label="Export PDF",
                description="Export the presentation to a PDF file.",
                inputs=[
                    pres_param,
                    ParamSpec(id="output_path", label="Output path",
                              type="file", default="",
                              help="Target .pdf path. Empty = next to the file."),
                ],
                output_type="any", destructive=True,
                fn=_export_pdf,
            ),
        ]


register(PowerPointConnector())
