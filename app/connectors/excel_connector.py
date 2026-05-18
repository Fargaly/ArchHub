"""Excel connector — drives Microsoft Excel via COM (pywin32).

Part of the Office COM connector cluster (Word · Excel · PowerPoint).
Subclasses the uniform `Connector` contract in `connectors/base.py`.

Architecture mirrors `outlook_runner.py`: the connector runs IN ArchHub's
own Python process and COM-dispatches to the user's Excel. There is no
localhost listener and no add-in loaded into Excel.

COM discipline:
  * Every public op runs inside `com_thread()` so `pythoncom.CoInitialize()`
    fires first — Excel COM calls fast-fail (0xc0000409) on Qt-pumped worker
    threads without it.
  * `probe()` uses `GetActiveObject` ONLY, so it reports `missing` when Excel
    is closed instead of launching it.
  * Ops use `_excel_app()` which prefers `GetActiveObject` and falls back to
    `Dispatch` so driving an op can always complete.

Output shapes follow `docs/HOST_NODE_UI_GRAMMAR_2026-05-15.md` §2.2.6:
ranges return 2-D arrays (`list[list]`); list ops return `list[dict]`.

Limitations:
  * Classic desktop Excel only. Excel for the web doesn't expose COM.
  * Operates on the workbooks already open in Excel's `Workbooks` collection.
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


_PROGID = "Excel.Application"

# Excel XlFixedFormatType constant (avoid importing the typelib).
_XL_TYPE_PDF = 0              # XlFixedFormatType.xlTypePDF


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


def _excel_app():
    """Get the Excel.Application COM object for OPERATIONS.

    Prefers a running instance via GetActiveObject; falls back to Dispatch
    (which starts Excel) so an op can always complete its work.
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
            f"Could not connect to Excel. Open Excel and try again. ({ex})"
        ) from ex


def _excel_app_probe():
    """Excel.Application for PROBE only — GetActiveObject ONLY, never starts
    Excel. Raises if Excel is not already running."""
    w = _win32()
    return w.GetActiveObject(_PROGID)


def _safe(s: Any, n: int = 0) -> str:
    s = "" if s is None else str(s)
    return s if not n else s[:n]


def _find_wb(app, workbook: str = ""):
    """Resolve a workbook by name from Excel's Workbooks collection.

    Match is case-insensitive against the short Name and the FullName path.
    Empty name → the ActiveWorkbook. Raises a clean RuntimeError listing what
    IS open on miss.
    """
    wbs = app.Workbooks
    if wbs is None or wbs.Count == 0:
        raise RuntimeError("No workbooks are open in Excel.")
    if not workbook:
        active = getattr(app, "ActiveWorkbook", None)
        if active is not None:
            return active
        return wbs.Item(1)
    want = str(workbook).strip().lower()
    names: list[str] = []
    for i in range(wbs.Count):
        wb = wbs.Item(i + 1)
        name = _safe(getattr(wb, "Name", ""))
        full = _safe(getattr(wb, "FullName", ""))
        names.append(name)
        if want in (name.lower(), full.lower()):
            return wb
        if want == os.path.basename(full).lower():
            return wb
    raise RuntimeError(
        f"Workbook '{workbook}' not open. Open workbooks: " + ", ".join(names)
    )


def _find_ws(wb, worksheet: str = ""):
    """Resolve a worksheet by name or 1-based index within a workbook.
    Empty name → the ActiveSheet (or first sheet)."""
    sheets = wb.Worksheets
    if sheets is None or sheets.Count == 0:
        raise RuntimeError("Workbook has no worksheets.")
    if not worksheet:
        active = getattr(wb, "ActiveSheet", None)
        if active is not None:
            return active
        return sheets.Item(1)
    w = str(worksheet).strip()
    # Numeric index?
    if w.isdigit():
        idx = int(w)
        if 1 <= idx <= sheets.Count:
            return sheets.Item(idx)
    want = w.lower()
    names: list[str] = []
    for i in range(sheets.Count):
        s = sheets.Item(i + 1)
        name = _safe(getattr(s, "Name", ""))
        names.append(name)
        if name.lower() == want:
            return s
    raise RuntimeError(
        f"Worksheet '{worksheet}' not found. Sheets: " + ", ".join(names)
    )


def _normalize_cell(v: Any) -> Any:
    """COM-returned cell values → JSON-safe scalars. pywin32 hands back
    pywintypes.datetime for dates and floats for numbers."""
    if v is None:
        return None
    if isinstance(v, (int, float, bool, str)):
        return v
    # pywintypes datetime / time exposes isoformat.
    iso = getattr(v, "isoformat", None)
    if callable(iso):
        try:
            return iso()
        except Exception:
            pass
    return str(v)


def _grid(value: Any) -> list[list]:
    """Coerce a Range.Value COM payload into a 2-D list.

    Excel returns: None for an empty range, a scalar for a 1x1 range, a tuple
    of tuples for a multi-cell range. Normalise all three to list[list].
    """
    if value is None:
        return []
    if not isinstance(value, (tuple, list)):
        return [[_normalize_cell(value)]]
    rows: list[list] = []
    for row in value:
        if isinstance(row, (tuple, list)):
            rows.append([_normalize_cell(c) for c in row])
        else:
            # A single-row range comes back as a flat tuple.
            rows.append([_normalize_cell(row)])
    return rows


# ── operation implementations ───────────────────────────────────────
def _list_workbooks() -> OpResult:
    """Every workbook currently open in Excel."""
    with com_thread():
        try:
            app = _excel_app()
        except RuntimeError as ex:
            return OpResult.fail(str(ex), "excel.list_workbooks")
        try:
            wbs = app.Workbooks
            out: list[dict] = []
            for i in range(wbs.Count):
                wb = wbs.Item(i + 1)
                try:
                    sheet_count = int(wb.Worksheets.Count)
                except Exception:
                    sheet_count = -1
                out.append({
                    "name": _safe(getattr(wb, "Name", "")),
                    "full_name": _safe(getattr(wb, "FullName", "")),
                    "saved": bool(getattr(wb, "Saved", True)),
                    "read_only": bool(getattr(wb, "ReadOnly", False)),
                    "worksheets": sheet_count,
                })
            active = ""
            try:
                active = _safe(app.ActiveWorkbook.Name)
            except Exception:
                pass
            return OpResult(
                ok=True, value=out, op_id="excel.list_workbooks",
                value_preview=(
                    f"{len(out)} workbook{'s' if len(out) != 1 else ''}"
                    + (f" · active: {active}" if active else "")
                ),
            )
        except Exception as ex:
            return OpResult.fail(
                f"{type(ex).__name__}: {ex}", "excel.list_workbooks")


def _list_worksheets(workbook: str = "") -> OpResult:
    """Every worksheet in a workbook with used-range dimensions."""
    with com_thread():
        try:
            app = _excel_app()
            wb = _find_wb(app, workbook)
        except RuntimeError as ex:
            return OpResult.fail(str(ex), "excel.list_worksheets")
        try:
            sheets = wb.Worksheets
            active = ""
            try:
                active = _safe(wb.ActiveSheet.Name)
            except Exception:
                pass
            out: list[dict] = []
            for i in range(sheets.Count):
                s = sheets.Item(i + 1)
                used = ""
                rows = cols = 0
                try:
                    ur = s.UsedRange
                    rows = int(ur.Rows.Count)
                    cols = int(ur.Columns.Count)
                    used = _safe(ur.Address(False, False))
                except Exception:
                    pass
                out.append({
                    "index": i + 1,
                    "name": _safe(getattr(s, "Name", "")),
                    "visible": int(getattr(s, "Visible", 1)) == -1,
                    "used_range": used,
                    "used_rows": rows,
                    "used_cols": cols,
                    "is_active": _safe(getattr(s, "Name", "")) == active,
                })
            return OpResult(
                ok=True, value=out, op_id="excel.list_worksheets",
                value_preview=(
                    f"{len(out)} worksheet{'s' if len(out) != 1 else ''}"
                ),
            )
        except Exception as ex:
            return OpResult.fail(
                f"{type(ex).__name__}: {ex}", "excel.list_worksheets")


def _read_range(workbook: str = "", worksheet: str = "",
                range: str = "") -> OpResult:
    """Read an A1-notation range into a 2-D array. Empty range = UsedRange."""
    with com_thread():
        try:
            app = _excel_app()
            wb = _find_wb(app, workbook)
            ws = _find_ws(wb, worksheet)
        except RuntimeError as ex:
            return OpResult.fail(str(ex), "excel.read_range")
        try:
            addr = str(range or "").strip()
            if addr:
                rng = ws.Range(addr)
            else:
                rng = ws.UsedRange
            grid = _grid(rng.Value)
            rows = len(grid)
            cols = max((len(r) for r in grid), default=0)
            resolved = ""
            try:
                resolved = _safe(rng.Address(False, False))
            except Exception:
                resolved = addr
            return OpResult(
                ok=True,
                value={
                    "workbook": _safe(getattr(wb, "Name", "")),
                    "worksheet": _safe(getattr(ws, "Name", "")),
                    "range": resolved,
                    "rows": rows,
                    "cols": cols,
                    "values": grid,
                },
                op_id="excel.read_range",
                value_preview=f"{rows} rows × {cols} cols",
            )
        except Exception as ex:
            return OpResult.fail(
                f"{type(ex).__name__}: {ex}", "excel.read_range")


def _list_named_ranges(workbook: str = "") -> OpResult:
    """Every defined name (named range) in a workbook."""
    with com_thread():
        try:
            app = _excel_app()
            wb = _find_wb(app, workbook)
        except RuntimeError as ex:
            return OpResult.fail(str(ex), "excel.list_named_ranges")
        try:
            names = wb.Names
            out: list[dict] = []
            for i in range(int(names.Count)):
                n = names.Item(i + 1)
                refers = ""
                try:
                    refers = _safe(getattr(n, "RefersTo", ""))
                except Exception:
                    pass
                out.append({
                    "name": _safe(getattr(n, "Name", "")),
                    "refers_to": refers,
                    "visible": bool(getattr(n, "Visible", True)),
                })
            return OpResult(
                ok=True, value=out, op_id="excel.list_named_ranges",
                value_preview=(
                    f"{len(out)} named range{'s' if len(out) != 1 else ''}"
                ),
            )
        except Exception as ex:
            return OpResult.fail(
                f"{type(ex).__name__}: {ex}", "excel.list_named_ranges")


def _get_selection() -> OpResult:
    """The cells currently selected in Excel, as a 2-D array."""
    with com_thread():
        try:
            app = _excel_app()
        except RuntimeError as ex:
            return OpResult.fail(str(ex), "excel.get_selection")
        try:
            sel = getattr(app, "Selection", None)
            if sel is None:
                return OpResult.fail(
                    "Nothing is selected in Excel.", "excel.get_selection")
            addr = ""
            try:
                addr = _safe(sel.Address(False, False))
            except Exception:
                pass
            ws_name = ""
            wb_name = ""
            try:
                ws_name = _safe(sel.Worksheet.Name)
                wb_name = _safe(sel.Worksheet.Parent.Name)
            except Exception:
                pass
            grid: list[list] = []
            try:
                grid = _grid(sel.Value)
            except Exception:
                grid = []
            rows = len(grid)
            cols = max((len(r) for r in grid), default=0)
            return OpResult(
                ok=True,
                value={
                    "workbook": wb_name,
                    "worksheet": ws_name,
                    "range": addr,
                    "rows": rows,
                    "cols": cols,
                    "values": grid,
                },
                op_id="excel.get_selection",
                value_preview=(
                    f"{addr or 'selection'} · "
                    f"{rows} rows × {cols} cols"
                ),
            )
        except Exception as ex:
            return OpResult.fail(
                f"{type(ex).__name__}: {ex}", "excel.get_selection")


def _write_range(workbook: str = "", worksheet: str = "",
                 range: str = "", values: Any = None) -> OpResult:
    """Write a 2-D array of values into an A1-notation range.
    DESTRUCTIVE — overwrites cell contents."""
    with com_thread():
        addr = str(range or "").strip()
        if not addr:
            return OpResult.fail(
                "range is empty — specify a target like 'A1:C3'.",
                "excel.write_range")
        if values is None:
            return OpResult.fail(
                "values is empty — nothing to write.", "excel.write_range")
        # Coerce a scalar / 1-D list into a proper 2-D grid.
        if not isinstance(values, (list, tuple)):
            grid = [[values]]
        elif values and not isinstance(values[0], (list, tuple)):
            grid = [list(values)]
        else:
            grid = [list(r) for r in values]
        try:
            app = _excel_app()
            wb = _find_wb(app, workbook)
            ws = _find_ws(wb, worksheet)
        except RuntimeError as ex:
            return OpResult.fail(str(ex), "excel.write_range")
        try:
            target = ws.Range(addr)
            n_rows = len(grid)
            n_cols = max((len(r) for r in grid), default=0)
            # Resize the anchor to exactly match the grid so a single-cell
            # `range` arg still fills the whole supplied block.
            if n_rows and n_cols:
                anchor = target.Cells(1, 1)
                block = anchor.Resize(n_rows, n_cols)
                # Pad ragged rows so COM gets a rectangular tuple-of-tuples.
                padded = [
                    tuple(r) + (None,) * (n_cols - len(r)) for r in grid
                ]
                block.Value = tuple(padded)
                written_addr = _safe(block.Address(False, False))
            else:
                written_addr = addr
            return OpResult(
                ok=True,
                value={
                    "workbook": _safe(getattr(wb, "Name", "")),
                    "worksheet": _safe(getattr(ws, "Name", "")),
                    "range": written_addr,
                    "rows": n_rows,
                    "cols": n_cols,
                    "cells_written": n_rows * n_cols,
                },
                op_id="excel.write_range",
                value_preview=(
                    f"wrote {n_rows} rows × {n_cols} cols"
                ),
            )
        except Exception as ex:
            return OpResult.fail(
                f"{type(ex).__name__}: {ex}", "excel.write_range")


def _export_pdf(workbook: str = "", worksheet: str = "",
                output_path: str = "") -> OpResult:
    """Export a workbook (or one worksheet) to PDF. DESTRUCTIVE — writes to
    disk."""
    with com_thread():
        try:
            app = _excel_app()
            wb = _find_wb(app, workbook)
        except RuntimeError as ex:
            return OpResult.fail(str(ex), "excel.export_pdf")
        try:
            # Whole workbook unless a worksheet is named.
            target = wb
            scope = "workbook"
            if str(worksheet or "").strip():
                target = _find_ws(wb, worksheet)
                scope = "worksheet"
            path = str(output_path or "").strip()
            if not path:
                full = _safe(getattr(wb, "FullName", ""))
                if full and not full.lower().endswith(".pdf"):
                    base = os.path.splitext(full)[0]
                else:
                    name = _safe(getattr(wb, "Name", "workbook"))
                    base = os.path.join(
                        os.path.expanduser("~"), os.path.splitext(name)[0])
                path = base + ".pdf"
            parent = os.path.dirname(path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            target.ExportAsFixedFormat(Type=_XL_TYPE_PDF, Filename=path)
            size = os.path.getsize(path) if os.path.exists(path) else 0
            return OpResult(
                ok=True,
                value={
                    "workbook": _safe(getattr(wb, "Name", "")),
                    "scope": scope,
                    "pdf_path": path,
                    "size_bytes": size,
                },
                op_id="excel.export_pdf",
                value_preview=f"PDF ({scope}) · {size:,} bytes",
            )
        except Exception as ex:
            return OpResult.fail(
                f"{type(ex).__name__}: {ex}", "excel.export_pdf")


# ── connector ───────────────────────────────────────────────────────
class ExcelConnector(Connector):
    """Microsoft Excel — drives the desktop app over COM."""

    host = "excel"
    display_name = "Microsoft Excel"
    mechanism = "com"

    def probe(self) -> dict:
        """live only when Excel is already running (GetActiveObject succeeds);
        missing when Excel is closed; unauthorized on COM-permission failures.
        Never starts Excel."""
        try:
            _win32()
        except RuntimeError as ex:
            return {"status": "missing", "note": str(ex), "detail": {}}
        with com_thread():
            try:
                app = _excel_app_probe()
            except Exception as ex:
                msg = str(ex).lower()
                if "access" in msg or "denied" in msg or "0x80070005" in msg:
                    return {
                        "status": "unauthorized",
                        "note": f"Excel COM access denied: {ex}",
                        "detail": {},
                    }
                return {
                    "status": "missing",
                    "note": "Excel is not running. Open Excel to connect.",
                    "detail": {},
                }
            try:
                wbs = app.Workbooks
                wb_count = int(wbs.Count)
                active = ""
                try:
                    active = _safe(app.ActiveWorkbook.Name)
                except Exception:
                    active = ""
                return {
                    "status": "live",
                    "note": (
                        f"Excel running · {wb_count} workbook"
                        f"{'s' if wb_count != 1 else ''} open"
                    ),
                    "detail": {
                        "version": _safe(getattr(app, "Version", "")),
                        "workbooks_open": wb_count,
                        "active_workbook": active,
                    },
                }
            except Exception as ex:
                return {
                    "status": "loaded_dead",
                    "note": f"Excel reachable but not responding: {ex}",
                    "detail": {},
                }

    def build_ops(self) -> list:
        wb_param = ParamSpec(
            id="workbook", label="Workbook", type="choice",
            options_source="excel.list_workbooks",
            help="Open Excel workbook to target. Empty = active workbook.",
        )
        ws_param = ParamSpec(
            id="worksheet", label="Worksheet", type="choice",
            options_source="excel.list_worksheets",
            help="Worksheet name or 1-based index. Empty = active sheet.",
        )
        return [
            # ---- READS ----
            ConnectorOp(
                op_id="excel.list_workbooks", host="excel", kind="read",
                label="List workbooks",
                description="Every workbook currently open in Excel.",
                inputs=[], output_type="list", destructive=False,
                fn=_list_workbooks,
            ),
            ConnectorOp(
                op_id="excel.list_worksheets", host="excel", kind="read",
                label="List worksheets",
                description="Every worksheet in a workbook.",
                inputs=[wb_param],
                output_type="list", destructive=False,
                fn=_list_worksheets,
            ),
            ConnectorOp(
                op_id="excel.read_range", host="excel", kind="read",
                label="Read range",
                description="Read an A1 range into a 2-D array.",
                inputs=[
                    wb_param, ws_param,
                    ParamSpec(id="range", label="Range", type="range",
                              default="",
                              help="A1 notation, e.g. A1:G47. Empty = used range."),
                ],
                output_type="range_values", destructive=False,
                fn=_read_range,
            ),
            ConnectorOp(
                op_id="excel.list_named_ranges", host="excel", kind="read",
                label="List named ranges",
                description="Every defined name in a workbook.",
                inputs=[wb_param],
                output_type="list", destructive=False,
                fn=_list_named_ranges,
            ),
            ConnectorOp(
                op_id="excel.get_selection", host="excel", kind="read",
                label="Get selection",
                description="The cells currently selected in Excel.",
                inputs=[], output_type="range_values", destructive=False,
                fn=_get_selection,
            ),
            # ---- ACTIONS ----
            ConnectorOp(
                op_id="excel.write_range", host="excel", kind="action",
                label="Write range",
                description="Write a 2-D array of values into a range.",
                inputs=[
                    wb_param, ws_param,
                    ParamSpec(id="range", label="Range", type="range",
                              required=True,
                              help="Anchor cell or full range, e.g. A1 or A1:C3."),
                    ParamSpec(id="values", label="Values", type="list",
                              required=True,
                              help="2-D array of cell values to write."),
                ],
                output_type="any", destructive=True,
                fn=_write_range,
            ),
            ConnectorOp(
                op_id="excel.export_pdf", host="excel", kind="action",
                label="Export PDF",
                description="Export a workbook or worksheet to PDF.",
                inputs=[
                    wb_param, ws_param,
                    ParamSpec(id="output_path", label="Output path",
                              type="file", default="",
                              help="Target .pdf path. Empty = next to the file."),
                ],
                output_type="any", destructive=True,
                fn=_export_pdf,
            ),
        ]


register(ExcelConnector())
