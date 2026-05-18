"""Word connector — drives Microsoft Word via COM (pywin32).

Part of the Office COM connector cluster (Word · Excel · PowerPoint).
Subclasses the uniform `Connector` contract in `connectors/base.py`.

Architecture mirrors `outlook_runner.py`: the connector runs IN ArchHub's
own Python process and COM-dispatches to the user's Word. There is no
localhost listener and no DLL loaded into Word.

COM discipline:
  * Every public op runs inside `com_thread()` so `pythoncom.CoInitialize()`
    fires first — without it, Word COM calls fast-fail (0xc0000409) on the
    Qt-pumped worker threads.
  * `probe()` uses `GetActiveObject` ONLY, so it reports `missing` when Word
    is closed instead of launching it.
  * Ops use `_word_app()` which prefers `GetActiveObject` (attach to a
    running instance) and falls back to `Dispatch` (start Word) — driving an
    op should always be able to do its job.

Limitations:
  * Classic desktop Word only. Word for the web / UWP doesn't expose COM.
  * Operates on the documents already open in Word's `Documents` collection;
    callers pass a document name to target a specific one.
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


_PROGID = "Word.Application"

# Word WdSaveFormat / WdExportFormat constants (avoid importing the typelib).
_WD_FORMAT_PDF = 17           # WdSaveFormat.wdFormatPDF
_WD_EXPORT_PDF = 17           # WdExportFormat.wdExportFormatPDF
_WD_REPLACE_ALL = 2          # WdReplace.wdReplaceAll
_WD_FIND_CONTINUE = 1        # WdFindWrap.wdFindContinue
_WD_STORY_END = 6            # WdUnits.wdStory (collapse direction)
_WD_COLLAPSE_END = 0        # WdCollapseDirection.wdCollapseEnd
_WD_STAT_PAGES = 2          # WdStatistic.wdStatisticPages


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


def _word_app():
    """Get the Word.Application COM object for OPERATIONS.

    Prefers an already-running instance via GetActiveObject; falls back to
    Dispatch (which starts Word) so an op can always complete its work.
    Raises a clean RuntimeError on total failure.
    """
    w = _win32()
    try:
        return w.GetActiveObject(_PROGID)
    except Exception:
        pass
    try:
        return w.Dispatch(_PROGID)
    except Exception as ex:
        raise RuntimeError(
            f"Could not connect to Word. Open Word and try again. ({ex})"
        ) from ex


def _word_app_probe():
    """Word.Application for PROBE only — GetActiveObject ONLY, never starts
    Word. Raises if Word is not already running."""
    w = _win32()
    return w.GetActiveObject(_PROGID)


def _safe(s: Any, n: int = 0) -> str:
    s = "" if s is None else str(s)
    return s if not n else s[:n]


def _find_doc(app, workbook_or_doc: str = ""):
    """Resolve a document by name from Word's Documents collection.

    Match is case-insensitive against both the short Name and the full
    FullName (path). Empty name → the ActiveDocument. Returns the COM Document
    or raises a clean RuntimeError listing what IS open.
    """
    docs = app.Documents
    if docs is None or docs.Count == 0:
        raise RuntimeError("No documents are open in Word.")
    if not workbook_or_doc:
        active = getattr(app, "ActiveDocument", None)
        if active is not None:
            return active
        return docs.Item(1)
    want = str(workbook_or_doc).strip().lower()
    names: list[str] = []
    for i in range(docs.Count):
        d = docs.Item(i + 1)
        name = _safe(getattr(d, "Name", ""))
        full = _safe(getattr(d, "FullName", ""))
        names.append(name)
        if want in (name.lower(), full.lower()):
            return d
        if want == os.path.basename(full).lower():
            return d
    raise RuntimeError(
        f"Document '{workbook_or_doc}' not open. Open documents: "
        + ", ".join(names)
    )


# ── operation implementations ───────────────────────────────────────
def _list_documents() -> OpResult:
    """Every document currently open in Word."""
    with com_thread():
        try:
            app = _word_app()
        except RuntimeError as ex:
            return OpResult.fail(str(ex), "word.list_documents")
        try:
            docs = app.Documents
            out: list[dict] = []
            for i in range(docs.Count):
                d = docs.Item(i + 1)
                try:
                    paras = int(d.Paragraphs.Count)
                except Exception:
                    paras = -1
                out.append({
                    "name": _safe(getattr(d, "Name", "")),
                    "full_name": _safe(getattr(d, "FullName", "")),
                    "saved": bool(getattr(d, "Saved", True)),
                    "read_only": bool(getattr(d, "ReadOnly", False)),
                    "paragraphs": paras,
                })
            active = ""
            try:
                active = _safe(app.ActiveDocument.Name)
            except Exception:
                pass
            return OpResult(
                ok=True, value=out, op_id="word.list_documents",
                value_preview=(
                    f"{len(out)} document{'s' if len(out) != 1 else ''}"
                    + (f" · active: {active}" if active else "")
                ),
            )
        except Exception as ex:
            return OpResult.fail(
                f"{type(ex).__name__}: {ex}", "word.list_documents")


def _list_paragraphs(document: str = "", limit: int = 500) -> OpResult:
    """Every paragraph's text + style for one document."""
    with com_thread():
        try:
            app = _word_app()
            doc = _find_doc(app, document)
        except RuntimeError as ex:
            return OpResult.fail(str(ex), "word.list_paragraphs")
        try:
            paras = doc.Paragraphs
            cap = min(int(limit or 500), int(paras.Count))
            out: list[dict] = []
            for i in range(cap):
                p = paras.Item(i + 1)
                rng = p.Range
                text = _safe(getattr(rng, "Text", "")).replace("\r", "")
                try:
                    style = _safe(p.Style.NameLocal)
                except Exception:
                    style = ""
                out.append({
                    "index": i + 1,
                    "text": text[:2000],
                    "style": style,
                    "char_count": len(text),
                })
            return OpResult(
                ok=True, value=out, op_id="word.list_paragraphs",
                value_preview=(
                    f"{len(out)} paragraph{'s' if len(out) != 1 else ''}"
                    f" of {int(paras.Count)}"
                ),
            )
        except Exception as ex:
            return OpResult.fail(
                f"{type(ex).__name__}: {ex}", "word.list_paragraphs")


def _list_headings(document: str = "") -> OpResult:
    """Only the heading-styled paragraphs — the document outline."""
    with com_thread():
        try:
            app = _word_app()
            doc = _find_doc(app, document)
        except RuntimeError as ex:
            return OpResult.fail(str(ex), "word.list_headings")
        try:
            paras = doc.Paragraphs
            out: list[dict] = []
            for i in range(int(paras.Count)):
                p = paras.Item(i + 1)
                try:
                    style = _safe(p.Style.NameLocal)
                except Exception:
                    style = ""
                low = style.lower()
                # Word OutlineLevel: 1-9 = Heading 1-9, 10 = Body Text.
                level = 0
                try:
                    ol = int(getattr(p, "OutlineLevel", 10))
                    if 1 <= ol <= 9:
                        level = ol
                except Exception:
                    level = 0
                is_heading = level > 0 or low.startswith(("heading", "title"))
                if not is_heading:
                    continue
                text = _safe(getattr(p.Range, "Text", "")).replace(
                    "\r", "").strip()
                out.append({
                    "index": i + 1,
                    "text": text[:500],
                    "style": style,
                    "level": level if level else (1 if "title" in low else 0),
                })
            return OpResult(
                ok=True, value=out, op_id="word.list_headings",
                value_preview=(
                    f"{len(out)} heading{'s' if len(out) != 1 else ''}"
                ),
            )
        except Exception as ex:
            return OpResult.fail(
                f"{type(ex).__name__}: {ex}", "word.list_headings")


def _list_tables(document: str = "") -> OpResult:
    """Every table in the document with row/column dimensions."""
    with com_thread():
        try:
            app = _word_app()
            doc = _find_doc(app, document)
        except RuntimeError as ex:
            return OpResult.fail(str(ex), "word.list_tables")
        try:
            tables = doc.Tables
            out: list[dict] = []
            for i in range(int(tables.Count)):
                t = tables.Item(i + 1)
                try:
                    rows = int(t.Rows.Count)
                except Exception:
                    rows = -1
                try:
                    cols = int(t.Columns.Count)
                except Exception:
                    cols = -1
                first_cell = ""
                try:
                    first_cell = _safe(
                        t.Cell(1, 1).Range.Text).replace(
                        "\r", "").replace("\x07", "").strip()
                except Exception:
                    pass
                out.append({
                    "index": i + 1,
                    "rows": rows,
                    "columns": cols,
                    "first_cell": first_cell[:120],
                })
            return OpResult(
                ok=True, value=out, op_id="word.list_tables",
                value_preview=(
                    f"{len(out)} table{'s' if len(out) != 1 else ''}"
                ),
            )
        except Exception as ex:
            return OpResult.fail(
                f"{type(ex).__name__}: {ex}", "word.list_tables")


def _list_comments(document: str = "") -> OpResult:
    """Every review comment in the document."""
    with com_thread():
        try:
            app = _word_app()
            doc = _find_doc(app, document)
        except RuntimeError as ex:
            return OpResult.fail(str(ex), "word.list_comments")
        try:
            comments = doc.Comments
            out: list[dict] = []
            for i in range(int(comments.Count)):
                c = comments.Item(i + 1)
                date_iso = ""
                try:
                    d = getattr(c, "Date", None)
                    if d is not None:
                        date_iso = d.isoformat()
                except Exception:
                    date_iso = ""
                ctext = ""
                try:
                    ctext = _safe(c.Range.Text).replace("\r", "")
                except Exception:
                    pass
                scope = ""
                try:
                    scope = _safe(c.Scope.Text).replace("\r", "")
                except Exception:
                    pass
                out.append({
                    "index": i + 1,
                    "author": _safe(getattr(c, "Author", "")),
                    "initial": _safe(getattr(c, "Initial", "")),
                    "date": date_iso,
                    "text": ctext[:2000],
                    "scope_text": scope[:300],
                    "done": bool(getattr(c, "Done", False)),
                })
            return OpResult(
                ok=True, value=out, op_id="word.list_comments",
                value_preview=(
                    f"{len(out)} comment{'s' if len(out) != 1 else ''}"
                ),
            )
        except Exception as ex:
            return OpResult.fail(
                f"{type(ex).__name__}: {ex}", "word.list_comments")


def _get_text(document: str = "", start: int = 0, end: int = 0) -> OpResult:
    """Full document text, or a character range [start, end)."""
    with com_thread():
        try:
            app = _word_app()
            doc = _find_doc(app, document)
        except RuntimeError as ex:
            return OpResult.fail(str(ex), "word.get_text")
        try:
            s = int(start or 0)
            e = int(end or 0)
            if e > s > -1:
                rng = doc.Range(Start=s, End=e)
            else:
                rng = doc.Content
            text = _safe(getattr(rng, "Text", "")).replace("\r", "\n")
            chars = len(text)
            words = len(text.split())
            return OpResult(
                ok=True,
                value={
                    "name": _safe(getattr(doc, "Name", "")),
                    "text": text,
                    "char_count": chars,
                    "word_count": words,
                    "range": [s, e] if e > s else None,
                },
                op_id="word.get_text",
                value_preview=f"{chars} chars · {words} words",
            )
        except Exception as ex:
            return OpResult.fail(
                f"{type(ex).__name__}: {ex}", "word.get_text")


def _find_replace(document: str = "", find_text: str = "",
                  replace_text: str = "", match_case: bool = False,
                  whole_word: bool = False) -> OpResult:
    """Find + replace all occurrences. DESTRUCTIVE — mutates the document."""
    with com_thread():
        if not find_text:
            return OpResult.fail(
                "find_text is empty — nothing to search for.",
                "word.find_replace")
        try:
            app = _word_app()
            doc = _find_doc(app, document)
        except RuntimeError as ex:
            return OpResult.fail(str(ex), "word.find_replace")
        try:
            # Count first so we can report how many were replaced.
            scan = doc.Content.Find
            scan.ClearFormatting()
            scan.Replacement.ClearFormatting()
            scan.Text = str(find_text)
            scan.MatchCase = bool(match_case)
            scan.MatchWholeWord = bool(whole_word)
            scan.Forward = True
            scan.Wrap = _WD_FIND_CONTINUE
            count = 0
            while scan.Execute() and count < 100000:
                count += 1
            # Now perform the replacement on a fresh Content range.
            rng = doc.Content
            find = rng.Find
            find.ClearFormatting()
            find.Replacement.ClearFormatting()
            find.Text = str(find_text)
            find.Replacement.Text = str(replace_text)
            find.MatchCase = bool(match_case)
            find.MatchWholeWord = bool(whole_word)
            find.Forward = True
            find.Wrap = _WD_FIND_CONTINUE
            find.Execute(Replace=_WD_REPLACE_ALL)
            return OpResult(
                ok=True,
                value={
                    "document": _safe(getattr(doc, "Name", "")),
                    "find": str(find_text),
                    "replace": str(replace_text),
                    "replaced": count,
                },
                op_id="word.find_replace",
                value_preview=(
                    f"{count} replacement{'s' if count != 1 else ''}"
                ),
            )
        except Exception as ex:
            return OpResult.fail(
                f"{type(ex).__name__}: {ex}", "word.find_replace")


def _insert_text(document: str = "", text: str = "",
                 position: str = "end") -> OpResult:
    """Insert text at the start, end, or current selection of a document.
    DESTRUCTIVE — mutates the document."""
    with com_thread():
        if not text:
            return OpResult.fail(
                "text is empty — nothing to insert.", "word.insert_text")
        try:
            app = _word_app()
            doc = _find_doc(app, document)
        except RuntimeError as ex:
            return OpResult.fail(str(ex), "word.insert_text")
        try:
            pos = str(position or "end").lower()
            if pos == "start":
                rng = doc.Range(Start=0, End=0)
                rng.InsertAfter(str(text))
            elif pos == "selection":
                sel = getattr(app, "Selection", None)
                if sel is not None:
                    sel.TypeText(str(text))
                else:
                    rng = doc.Content
                    rng.Collapse(_WD_COLLAPSE_END)
                    rng.InsertAfter(str(text))
            else:  # end
                rng = doc.Content
                rng.Collapse(_WD_COLLAPSE_END)
                rng.InsertAfter(str(text))
            return OpResult(
                ok=True,
                value={
                    "document": _safe(getattr(doc, "Name", "")),
                    "inserted_chars": len(str(text)),
                    "position": pos,
                },
                op_id="word.insert_text",
                value_preview=f"inserted {len(str(text))} chars at {pos}",
            )
        except Exception as ex:
            return OpResult.fail(
                f"{type(ex).__name__}: {ex}", "word.insert_text")


def _export_pdf(document: str = "", output_path: str = "") -> OpResult:
    """Export the document to a PDF file. DESTRUCTIVE — writes to disk."""
    with com_thread():
        try:
            app = _word_app()
            doc = _find_doc(app, document)
        except RuntimeError as ex:
            return OpResult.fail(str(ex), "word.export_pdf")
        try:
            path = str(output_path or "").strip()
            if not path:
                full = _safe(getattr(doc, "FullName", ""))
                if full and not full.lower().endswith((".pdf",)):
                    path = os.path.splitext(full)[0] + ".pdf"
                else:
                    name = _safe(getattr(doc, "Name", "document"))
                    path = os.path.join(
                        os.path.expanduser("~"),
                        os.path.splitext(name)[0] + ".pdf")
            parent = os.path.dirname(path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            doc.ExportAsFixedFormat(
                OutputFileName=path,
                ExportFormat=_WD_EXPORT_PDF,
            )
            size = os.path.getsize(path) if os.path.exists(path) else 0
            return OpResult(
                ok=True,
                value={
                    "document": _safe(getattr(doc, "Name", "")),
                    "pdf_path": path,
                    "size_bytes": size,
                },
                op_id="word.export_pdf",
                value_preview=f"PDF · {size:,} bytes",
            )
        except Exception as ex:
            return OpResult.fail(
                f"{type(ex).__name__}: {ex}", "word.export_pdf")


# ── connector ───────────────────────────────────────────────────────
class WordConnector(Connector):
    """Microsoft Word — drives the desktop app over COM."""

    host = "word"
    display_name = "Microsoft Word"
    mechanism = "com"

    def probe(self) -> dict:
        """live only when Word is already running (GetActiveObject succeeds);
        missing when Word is closed; unauthorized on COM-permission failures.
        Never starts Word."""
        try:
            _win32()
        except RuntimeError as ex:
            return {"status": "missing", "note": str(ex), "detail": {}}
        with com_thread():
            try:
                app = _word_app_probe()
            except Exception as ex:
                msg = str(ex).lower()
                if "access" in msg or "denied" in msg or "0x80070005" in msg:
                    return {
                        "status": "unauthorized",
                        "note": f"Word COM access denied: {ex}",
                        "detail": {},
                    }
                # GetActiveObject raises when no running instance exists.
                return {
                    "status": "missing",
                    "note": "Word is not running. Open Word to connect.",
                    "detail": {},
                }
            try:
                docs = app.Documents
                doc_count = int(docs.Count)
                active = ""
                try:
                    active = _safe(app.ActiveDocument.Name)
                except Exception:
                    active = ""
                return {
                    "status": "live",
                    "note": (
                        f"Word running · {doc_count} document"
                        f"{'s' if doc_count != 1 else ''} open"
                    ),
                    "detail": {
                        "version": _safe(getattr(app, "Version", "")),
                        "documents_open": doc_count,
                        "active_document": active,
                    },
                }
            except Exception as ex:
                return {
                    "status": "loaded_dead",
                    "note": f"Word reachable but not responding: {ex}",
                    "detail": {},
                }

    def build_ops(self) -> list:
        doc_param = ParamSpec(
            id="document", label="Document", type="choice",
            options_source="word.list_documents",
            help="Open Word document to target. Empty = active document.",
        )
        return [
            # ---- READS ----
            ConnectorOp(
                op_id="word.list_documents", host="word", kind="read",
                label="List documents",
                description="Every document currently open in Word.",
                inputs=[], output_type="list", destructive=False,
                fn=_list_documents,
            ),
            ConnectorOp(
                op_id="word.list_paragraphs", host="word", kind="read",
                label="List paragraphs",
                description="Each paragraph's text and style.",
                inputs=[
                    doc_param,
                    ParamSpec(id="limit", label="Max paragraphs",
                              type="number", default=500,
                              help="Cap on paragraphs returned."),
                ],
                output_type="paragraph", destructive=False,
                fn=_list_paragraphs,
            ),
            ConnectorOp(
                op_id="word.list_headings", host="word", kind="read",
                label="List headings",
                description="Heading-styled paragraphs — the outline.",
                inputs=[doc_param],
                output_type="paragraph", destructive=False,
                fn=_list_headings,
            ),
            ConnectorOp(
                op_id="word.list_tables", host="word", kind="read",
                label="List tables",
                description="Every table with row/column dimensions.",
                inputs=[doc_param],
                output_type="list", destructive=False,
                fn=_list_tables,
            ),
            ConnectorOp(
                op_id="word.list_comments", host="word", kind="read",
                label="List comments",
                description="Every review comment in the document.",
                inputs=[doc_param],
                output_type="list", destructive=False,
                fn=_list_comments,
            ),
            ConnectorOp(
                op_id="word.get_text", host="word", kind="read",
                label="Get text",
                description="Full document text or a character range.",
                inputs=[
                    doc_param,
                    ParamSpec(id="start", label="Range start",
                              type="number", default=0,
                              help="Start char index. 0 with end 0 = whole doc."),
                    ParamSpec(id="end", label="Range end",
                              type="number", default=0,
                              help="End char index. 0 = whole document."),
                ],
                output_type="text", destructive=False,
                fn=_get_text,
            ),
            # ---- ACTIONS ----
            ConnectorOp(
                op_id="word.find_replace", host="word", kind="action",
                label="Find and replace",
                description="Replace every occurrence of a string.",
                inputs=[
                    doc_param,
                    ParamSpec(id="find_text", label="Find", type="text",
                              required=True, help="Text to search for."),
                    ParamSpec(id="replace_text", label="Replace with",
                              type="text", default="",
                              help="Replacement text. Empty = delete matches."),
                    ParamSpec(id="match_case", label="Match case",
                              type="bool", default=False),
                    ParamSpec(id="whole_word", label="Whole word only",
                              type="bool", default=False),
                ],
                output_type="any", destructive=True,
                fn=_find_replace,
            ),
            ConnectorOp(
                op_id="word.insert_text", host="word", kind="action",
                label="Insert text",
                description="Insert text at start, end, or selection.",
                inputs=[
                    doc_param,
                    ParamSpec(id="text", label="Text", type="text",
                              required=True, help="Text to insert."),
                    ParamSpec(id="position", label="Position", type="choice",
                              default="end",
                              options=["start", "end", "selection"],
                              help="Where to insert the text."),
                ],
                output_type="any", destructive=True,
                fn=_insert_text,
            ),
            ConnectorOp(
                op_id="word.export_pdf", host="word", kind="action",
                label="Export PDF",
                description="Export the document to a PDF file.",
                inputs=[
                    doc_param,
                    ParamSpec(id="output_path", label="Output path",
                              type="file", default="",
                              help="Target .pdf path. Empty = next to the doc."),
                ],
                output_type="any", destructive=True,
                fn=_export_pdf,
            ),
        ]


register(WordConnector())
