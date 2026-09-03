"""Reach the desktop applications that are already open, or say none is.

One bridge for the family that speaks COM. Word, Excel and PowerPoint
differ only in what they call the thing they hold open -- Documents,
Workbooks, Presentations -- so the difference is a table here rather than
three modules that repeat each other.

Every host is attached to, never started. GetActiveObject joins an
application the founder already opened; Dispatch would launch one. Only
the first is admitted, so a runtime that can read your documents cannot
decide to open Excel because someone pressed a button.
"""
from __future__ import annotations

from typing import Mapping


class OfficeUnreachable(RuntimeError):
    """No running application answered, and that is a fact worth recording."""


# host -> (COM identity, the collection it holds open, what one is called)
_HOSTS: dict[str, tuple[str, str, str]] = {
    "word": ("Word.Application", "Documents", "document"),
    "excel": ("Excel.Application", "Workbooks", "workbook"),
    "powerpoint": ("PowerPoint.Application", "Presentations", "presentation"),
}

# Reads that answer with what the application holds open.
_OPEN_READS: dict[str, str] = {
    "word.list_documents": "word",
    "excel.list_workbooks": "excel",
    "powerpoint.list_presentations": "powerpoint",
}

# Reads that answer about the inside of one open item. The named item wins
# when it is named; otherwise the one in front of the founder does, because
# a read that silently picks a different document is worse than one that
# fails.
_INSIDE_READS: dict[str, tuple[str, str, str]] = {
    "excel.list_worksheets": ("excel", "workbook", "worksheets"),
    "powerpoint.list_slides": ("powerpoint", "presentation", "slides"),
    "word.list_paragraphs": ("word", "document", "paragraphs"),
}


def _running(prog_id: str, host: str):
    try:
        import pythoncom
        import win32com.client as client
    except ImportError as exc:
        raise OfficeUnreachable(
            "this runtime has no COM support, so %s cannot be reached" % host
        ) from exc
    pythoncom.CoInitialize()
    try:
        return client.GetActiveObject(prog_id)
    except Exception as exc:  # noqa: BLE001
        raise OfficeUnreachable("no running %s answered" % host) from exc


def _text(value: object) -> str:
    try:
        return str(value)
    except Exception:  # noqa: BLE001
        return ""


def _active_item(application, collection_name: str, wanted: str, noun: str):
    """The item the caller named, or the one the application has in front."""
    collection = getattr(application, collection_name)
    wanted = str(wanted or "").strip().lower()
    names = []
    for index in range(int(collection.Count)):
        item = collection.Item(index + 1)
        name = _text(getattr(item, "Name", ""))
        names.append(name)
        if wanted and wanted in name.lower():
            return item
    if wanted:
        raise OfficeUnreachable(
            "no open %s matches %r; open ones are %s"
            % (noun, wanted, ", ".join(names) or "none")
        )
    if not names:
        raise OfficeUnreachable("no %s is open" % noun)
    return collection.Item(1)


def _rows_inside(host: str, kind: str, item) -> list[dict]:
    if kind == "worksheets":
        sheets = item.Worksheets
        return [{
            "name": _text(getattr(sheets.Item(i + 1), "Name", "")),
            "index": i + 1,
        } for i in range(int(sheets.Count))]
    if kind == "slides":
        slides = item.Slides
        rows = []
        for i in range(int(slides.Count)):
            slide = slides.Item(i + 1)
            title = ""
            try:
                if int(slide.Shapes.HasTitle) == -1:
                    title = _text(slide.Shapes.Title.TextFrame.TextRange.Text)
            except Exception:  # noqa: BLE001
                title = ""
            rows.append({
                "index": i + 1,
                "title": title,
                "shapes": int(getattr(slide.Shapes, "Count", 0) or 0),
            })
        return rows
    if kind == "paragraphs":
        paragraphs = item.Paragraphs
        rows = []
        # A document can hold thousands of paragraphs, and answering with
        # all of them turns one read into a payload nobody asked for. The
        # bound is stated in the answer rather than hidden by it.
        limit = 200
        total = int(paragraphs.Count)
        for i in range(min(total, limit)):
            text = _text(paragraphs.Item(i + 1).Range.Text).strip()
            rows.append({"index": i + 1, "text": text})
        if total > limit:
            rows.append({
                "index": -1,
                "text": "... %d more paragraphs not read" % (total - limit),
            })
        return rows
    raise OfficeUnreachable("this adapter cannot read %s" % kind)


def invoke(op_id: str, arguments: Mapping[str, object]) -> dict:
    """Carry out one declared read against an already-open application."""
    host = _OPEN_READS.get(op_id)
    if host is not None:
        prog_id, collection_name, noun = _HOSTS[host]
        application = _running(prog_id, host)
        collection = getattr(application, collection_name)
        rows = []
        for index in range(int(collection.Count)):
            item = collection.Item(index + 1)
            rows.append({
                "name": _text(getattr(item, "Name", "")),
                "full_name": _text(getattr(item, "FullName", "")),
                "saved": bool(getattr(item, "Saved", True)),
                "read_only": bool(getattr(item, "ReadOnly", False)),
            })
        return {"host": host, noun + "s": rows, "count": len(rows)}

    inside = _INSIDE_READS.get(op_id)
    if inside is None:
        raise OfficeUnreachable(
            "this adapter does not yet carry out %s" % op_id
        )
    host, argument_name, kind = inside
    prog_id, collection_name, noun = _HOSTS[host]
    application = _running(prog_id, host)
    item = _active_item(
        application, collection_name, arguments.get(argument_name), noun
    )
    rows = _rows_inside(host, kind, item)
    return {
        "host": host,
        noun: _text(getattr(item, "Name", "")),
        kind: rows,
        "count": len(rows),
    }


__all__ = ["OfficeUnreachable", "invoke"]
