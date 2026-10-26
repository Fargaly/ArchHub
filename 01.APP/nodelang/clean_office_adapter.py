"""Reach the desktop applications that are already open, or say none is.

One bridge for the family that speaks COM. Word, Excel and PowerPoint
differ only in what they call the thing they hold open -- Documents,
Workbooks, Presentations -- so the difference is a table here rather than
three modules that repeat each other.

Reads attach to existing hosts. Only an authenticated owner run with
excel.open's show parameter enabled may explicitly open a workbook.
"""
from __future__ import annotations

import re
import json
import os
import shutil
import tempfile
import threading
import time
from datetime import date, time as datetime_time, timedelta
from pathlib import Path
import zipfile
import xml.etree.ElementTree as ET
from typing import Mapping


# One specification drives the executable catalogue, library and wire types.
COORDINATION_NODES = {'outlook.search': {'engine': 'outlook.search',
                    'title': 'Search correspondence',
                    'params': {'folders': ['inbox', 'sent'],
                               'since': '',
                               'keywords': [],
                               'include_body': False,
                               'include_attachments': False,
                               'limit': 100,
                               'scan_limit': 1000,
                               'store_id': ''},
                    'outputs': {'out': 'list'}},
 'outlook.read_thread': {'engine': 'outlook.read_thread',
                         'title': 'Read correspondence thread',
                         'params': {'folders': ['inbox', 'sent'],
                                    'conversation_id': '',
                                    'message_id': '',
                                    'store_id': '',
                                    'include_body': True,
                                    'include_attachments': True,
                                    'limit': 100,
                                    'scan_limit': 1000},
                         'outputs': {'out': 'list'}},
 'library.draft_email': {'engine': 'library.draft_email',
                         'title': 'Email draft',
                         'params': {'to': '',
                                    'cc': '',
                                    'subject': '',
                                    'body': '',
                                    'body_format': 'text',
                                    'attachments': [],
                                    'reply_to': '',
                                    'forward_of': '',
                                    'store_id': '',
                                    'signature': '',
                                    'signature_dir': '',
                                    'subject_case': 'UPPER',
                                    'show': False},
                         'outputs': {'out': 'object'}},
 'excel.read_table': {'engine': 'excel.read_table',
                      'title': 'Read comment tables',
                      'params': {'path': '',
                                 'sheets': [],
                                 'header_row': 1,
                                 'id_column_regex': '(?i)^(id|no\\.?|ref(?:erence)?|comment\\s*(?:id|no\\.?))$',
                                 'id_regex': '',
                                 'text_column': '',
                                 'data_only': True},
                      'outputs': {'out': 'list', 'rows': 'list', 'tables': 'list'}},
 'excel.build_workbook': {'engine': 'excel.build_workbook',
                          'title': 'Build coordination workbook',
                          'params': {'path': '',
                                     'sheets': [],
                                     'columns': [],
                                     'rows': [],
                                     'validation': {},
                                     'formulas': {},
                                     'images': [],
                                     'filters': True,
                                     'wrap': True,
                                     'overwrite': False,
                                     'grant': {}},
                          'outputs': {'out': 'string', 'file': 'string', 'attachments': 'list'}},
 'excel.write_cells': {'engine': 'excel.write_cells',
                       'title': 'Update workbook cells',
                       'params': {'path': '',
                                  'cells': [],
                                  'retry_count': 3,
                                  'retry_seconds': 0.2,
                                  'shared': False,
                                  'grant': {}},
                       'outputs': {'out': 'string', 'file': 'string'}},
 'excel.share_workbook': {'engine': 'excel.share_workbook',
                          'title': 'Share coordination workbook',
                          'params': {'path': '', 'destination': '', 'overwrite': False, 'grant': {}},
                          'outputs': {'out': 'string', 'file': 'string'}},
 'excel.open': {'engine': 'excel.open',
                'title': 'Show workbook',
                'params': {'path': '', 'show': False},
                'outputs': {'out': 'object'}},
 'pdf.extract_text': {'engine': 'pdf.extract_text',
                      'title': 'Read PDF pages',
                      'params': {'path': '', 'pages': []},
                      'outputs': {'out': 'list'}},
 'pdf.snip': {'engine': 'pdf.snip',
              'title': 'Clip PDF evidence',
              'params': {'path': '',
                         'page': 1,
                         'phrase': '',
                         'occurrence': 1,
                         'margin': 20,
                         'dpi': 144,
                         'image_cell': 'D2',
                         'output': '',
                         'overwrite': False,
                         'grant': {}},
              'outputs': {'out': 'object', 'file': 'string', 'images': 'list'}}}
for _operation, _label, _reference in (
    ('outlook.reply_draft', 'Reply draft', 'reply_to'),
    ('outlook.forward_draft', 'Forward draft', 'forward_of'),
):
    _defaults = dict(COORDINATION_NODES['library.draft_email']['params'])
    _defaults.update(message_id='', **{_reference: ''})
    COORDINATION_NODES[_operation] = {'engine': _operation, 'title': _label, 'params': _defaults, 'outputs': {'out': 'object'}}


def coordination_catalogue():
    entries = []
    for spec in COORDINATION_NODES.values():
        engine, label, defaults, outputs = spec['engine'], spec['title'], spec['params'], spec['outputs']
        interfaces, parameters = {}, {}
        for name, default in defaults.items():
            kind = ('boolean' if isinstance(default, bool) else 'integer' if isinstance(default, int)
                    else 'number' if isinstance(default, float) else 'list' if isinstance(default, list)
                    else 'object' if isinstance(default, dict) else 'string')
            parameters[name] = {'type': kind, 'editor': 'text', 'default': default}
            interfaces[name] = {'direction': 'input', 'type': kind}
        interfaces['in'] = {'direction': 'input', 'type': 'string' if engine == 'library.draft_email' else 'object'}
        interfaces.update({name: {'direction': 'output', 'type': kind} for name, kind in outputs.items()})
        entries.append({'name': label, 'engine': engine, 'category': 'Office',
                        'description': label, 'parameters': parameters, 'interfaces': interfaces})
    return tuple(entries)


def coordination_arguments(operation, params, feeds):
    if operation in ('library.draft_email', 'outlook.reply_draft', 'outlook.forward_draft') and any(
            str(name).casefold() in ('send', 'send_now', 'auto_send') for name in (*params, *feeds)):
        raise ValueError('draft-only: sending is not supported')
    defaults = COORDINATION_NODES[operation]['params']
    params = {name: params.get(name, default) for name, default in defaults.items()}
    for name in defaults:
        if name in feeds and feeds[name] is not None:
            params[name] = feeds[name]
        value = params[name]
        if isinstance(value, str) and isinstance(defaults[name], (list, dict, bool)):
            params[name] = json.loads(value)
        expected = type(defaults[name])
        if expected in (list, dict, bool) and type(params[name]) is not expected:
            raise ValueError('%s must be %s' % (name, expected.__name__))
        if expected in (int, float):
            if isinstance(params[name], bool):
                raise ValueError('%s must be numeric' % name)
            params[name] = expected(params[name])
    if 'path' in defaults and not str(params['path']).strip():
        raise ValueError('set path')
    return params


def coordination_write_request(operation, arguments):
    return {'operation': operation, **{k: v for k, v in arguments.items()
                                      if k not in ('grant', 'file_grant', 'permit')}}


def _authorize_coordination_write(operation, arguments, destination, *, owner_admitted=False):
    from .nodeslib_v2_engines import _require_file_grant, _digest_payload
    if arguments.get('grant'):
        _require_file_grant({**arguments, 'path': str(destination)}, operation='write_file',
                            input_digest=_digest_payload(coordination_write_request(operation, arguments)))
        return
    if not owner_admitted:
        raise ValueError('Office output requires this account owner Canvas run or a verified file grant')
    # Canvas already authenticates the account; its private registered workspace
    # is admitted by the SAME signed/current registry used by all host actions.
    from .workspace_roots_catalogue import read_registered_roots, root_bound_registration
    roots, _pin = read_registered_roots()
    wanted = Path(destination).resolve()
    for identity, entry in roots.items():
        base = Path(entry['path']).resolve()
        if wanted != base and wanted.is_relative_to(base):
            logical = 'workspace-roots/%s/%s' % (identity, wanted.relative_to(base).as_posix())
            _container, _digest, current = root_bound_registration(logical)
            if current.get('privacy') != 'private':
                raise ValueError('Office output requires a private registered project workspace')
            current_base = Path(current['path']).resolve()
            if wanted == current_base or not wanted.is_relative_to(current_base):
                raise ValueError('registered project workspace changed before the write')
            return
    raise ValueError('Office output is outside a registered project workspace')


def _atomic_office_output(path, writer, *, overwrite):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(suffix=path.suffix, dir=path.parent)
    os.close(descriptor)
    try:
        writer(temporary)
        if overwrite:
            os.replace(temporary, path)
        else:
            # Hard-link publication is atomic and refuses an existing destination.
            os.link(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _excel_open_book(path):
    try:
        app = _running('Excel.Application', 'excel')
    except OfficeUnreachable as unavailable:
        import logging
        logging.getLogger(__name__).debug('Excel unavailable; using closed workbook adapter: %s', unavailable)
        return None
    wanted = os.path.normcase(str(Path(path).resolve()))
    for index in range(1, int(app.Workbooks.Count) + 1):
        book = app.Workbooks.Item(index)
        if os.path.normcase(str(Path(str(book.FullName)).resolve())) == wanted:
            return book
    return None


def _read_comment_tables(params):
    import openpyxl
    book = openpyxl.load_workbook(params['path'], read_only=True, data_only=params['data_only'])
    tables, combined = [], []
    try:
        for sheet in book:
            if params['sheets'] and sheet.title not in params['sheets']:
                continue
            values = sheet.iter_rows(min_row=int(params['header_row']), values_only=True)
            columns = [str(v).strip() if v is not None else '' for v in next(values, ())]
            if not any(columns):
                continue
            if len([c for c in columns if c]) != len(set(c for c in columns if c)):
                raise ValueError('duplicate table column names: ' + sheet.title)
            id_column = next((c for c in columns if re.search(params['id_column_regex'], c)), '')
            rows = [{c: v.isoformat() if isinstance(v, (date, datetime_time)) else str(v) if isinstance(v, timedelta) else v
                     for c, v in zip(columns, row) if c} for row in values if any(v is not None for v in row)]
            if params['id_regex']:
                if not id_column:
                    raise ValueError('ID column not found: ' + sheet.title)
                rows = [r for r in rows if re.search(params['id_regex'], str(r.get(id_column) or ''))]
            text_column = params['text_column'] or next((c for c in columns if re.search(r'(?i)comment|description|remark|text', c)), '')
            if not text_column:
                candidates = [c for c in columns if c and c != id_column]
                text_column = max(candidates, key=lambda c: sum(len(str(r.get(c) or '')) for r in rows)) if candidates else ''
            tables.append({'sheet': sheet.title, 'columns': columns, 'id_column': id_column,
                           'text_column': text_column, 'rows': rows})
            combined.extend(rows)
    finally:
        book.close()
    return {'out': combined, 'rows': combined, 'tables': tables}


def _build_coordination_workbook(params, *, owner_admitted=False):
    import openpyxl
    from openpyxl.styles import Alignment, Font
    from openpyxl.worksheet.datavalidation import DataValidation
    from openpyxl.drawing.image import Image
    from openpyxl.utils import get_column_letter
    path = Path(params['path'])
    _authorize_coordination_write('excel.build_workbook', params, path, owner_admitted=owner_admitted)
    if path.suffix.lower() != '.xlsx':
        raise ValueError('new workbook must be .xlsx')
    book = openpyxl.Workbook()
    book.remove(book.active)
    sheets = params['sheets'] or [{'name': 'Tracker', 'columns': params['columns'], 'rows': params['rows'],
                               'validation': params['validation'], 'formulas': params['formulas'], 'images': params['images']}]
    for spec in sheets:
        sheet = book.create_sheet(spec['name'])
        columns = spec.get('columns') or params['columns']
        rows = spec.get('rows', params['rows'])
        if not columns and rows and isinstance(rows[0], Mapping):
            columns = list(rows[0])
        if not columns:
            raise ValueError('workbook sheet needs columns')
        sheet.append(columns)
        for row in rows:
            values = [row.get(c) for c in columns] if isinstance(row, Mapping) else row
            sheet.append(values)
            # Text from correspondence is data, never an executable formula.
            for cell in sheet[sheet.max_row]:
                if isinstance(cell.value, str):
                    cell.data_type = 's'
        for cell in sheet[1]:
            if isinstance(cell.value, str):
                cell.data_type = 's'
            cell.font = Font(bold=True)
        for row in sheet:
            for cell in row:
                cell.alignment = Alignment(wrap_text=params['wrap'], vertical='top')
        sheet.freeze_panes = 'A2'
        if params['filters']:
            sheet.auto_filter.ref = 'A1:%s%d' % (get_column_letter(len(columns)), sheet.max_row)
        for col in range(1, len(columns) + 1):
            sheet.column_dimensions[get_column_letter(col)].width = 28
        for cells, choices in spec.get('validation', params['validation']).items():
            validation = DataValidation(type='list', formula1='"' + ','.join(choices) + '"', allow_blank=True)
            validation.error, validation.showErrorMessage = 'Choose a listed status', True
            sheet.add_data_validation(validation)
            validation.add(cells)
        for cell, formula in spec.get('formulas', params['formulas']).items():
            if not str(formula).startswith('='):
                raise ValueError('summary formula must start with =')
            sheet[cell] = formula
        for image in spec.get('images', params['images']):
            sheet.add_image(Image(image['path']), image['cell'])
    try:
        _atomic_office_output(path, book.save, overwrite=params['overwrite'])
    finally:
        book.close()
    return {'out': str(path), 'file': str(path), 'attachments': [str(path)]}


def _write_coordination_cells(params, *, owner_admitted=False):
    import openpyxl
    from openpyxl.styles import PatternFill
    from openpyxl.drawing.image import Image
    path = Path(params['path'])
    _authorize_coordination_write('excel.write_cells', params, path, owner_admitted=owner_admitted)
    retry_count, delay = int(params['retry_count']), float(params['retry_seconds'])
    if not 0 <= retry_count <= 10 or not 0 <= delay <= 5:
        raise ValueError('retry budget out of range')
    for change in params['cells']:
        _a1_cell(change['cell'])
        if 'fill' in change and not re.fullmatch(r'[0-9a-fA-F]{6}|[0-9a-fA-F]{8}', str(change['fill']).lstrip('#')):
            raise ValueError('fill must be RGB or ARGB hex')
        if 'image' in change and not Path(change['image']).is_file():
            raise ValueError('cell image does not exist')
    for attempt in range(retry_count + 1):
        opened = _excel_open_book(path)
        if params['shared'] and opened is None:
            raise OfficeUnreachable('shared workbook must already be open in Excel')
        if opened is not None:
            for change in params['cells']:
                sheet = opened.Worksheets.Item(change.get('sheet') or 1)
                cell = sheet.Range(change['cell'])
                if 'text' in change:
                    cell.NumberFormat = '@'
                    cell.Value2 = str(change['text'])
                if 'fill' in change:
                    color = str(change['fill']).lstrip('#')[-6:]
                    cell.Interior.Color = int.from_bytes(bytes.fromhex(color), 'little')
                if 'image' in change:
                    sheet.Shapes.AddPicture(str(Path(change['image']).resolve()), False, True,
                                            cell.Left, cell.Top, -1, -1)
            opened.Save()
            for change in params['cells']:
                if 'text' in change and str(opened.Worksheets.Item(change.get('sheet') or 1).Range(change['cell']).Value2) != str(change['text']):
                    raise OfficeUnreachable('Excel cell readback differs from requested text')
            return {'out': str(path), 'file': str(path)}
        try:
            # openpyxl cannot round-trip these parts; only the existing Excel
            # host may edit such a file, so no package content is silently lost.
            with zipfile.ZipFile(path) as archive:
                for name in archive.namelist():
                    if (name.startswith(('xl/activeX/', 'xl/slicers/', 'xl/threadedComments/', 'customXml/'))
                            or name.lower().endswith(('.vml', '.wmf', '.emf', '.svg'))):
                        raise OfficeUnreachable('open this workbook in Excel to preserve its unsupported drawing or extension content')
                    if name.startswith('xl/') and name.endswith('.xml'):
                        root = ET.fromstring(archive.read(name))
                        if any(node.tag.rsplit('}', 1)[-1] in ('sp', 'grpSp', 'cxnSp', 'extLst') for node in root.iter()):
                            raise OfficeUnreachable('open this workbook in Excel to preserve its unsupported drawing or extension content')
            # Keep embedded pictures, macros and external links in supported workbooks.
            book = openpyxl.load_workbook(path, keep_vba=path.suffix.lower() == '.xlsm', keep_links=True)
            try:
                for change in params['cells']:
                    sheet = book[change.get('sheet') or book.sheetnames[0]]
                    cell = sheet[change['cell']]
                    if 'text' in change:
                        cell.value, cell.data_type = str(change['text']), 's'
                    if 'fill' in change:
                        cell.fill = PatternFill('solid', fgColor=str(change['fill']).lstrip('#'))
                    if 'image' in change:
                        sheet.add_image(Image(change['image']), change['cell'])
                _atomic_office_output(path, book.save, overwrite=True)
            finally:
                book.close()
            return {'out': str(path), 'file': str(path)}
        except PermissionError:
            if attempt == retry_count:
                raise
            time.sleep(delay)
    raise OfficeUnreachable('workbook write was not confirmed')


_PDF_LOCK = threading.Lock()


def _pdf_coordination(operation, params, *, owner_admitted=False):
    import pypdfium2 as pdfium
    with _PDF_LOCK, pdfium.PdfDocument(params['path']) as document:
        if operation == 'pdf.extract_text':
            pages = params['pages'] or list(range(1, len(document) + 1))
            rows = []
            for number in pages:
                if not 1 <= int(number) <= len(document):
                    raise ValueError('PDF page out of range')
                page = document[int(number) - 1]
                text = page.get_textpage()
                try:
                    rows.append({'page': int(number), 'text': text.get_text_bounded(), 'path': params['path']})
                finally:
                    text.close()
                    page.close()
            return {'out': rows}
        number, dpi, margin = int(params['page']), int(params['dpi']), float(params['margin'])
        if not 1 <= number <= len(document) or not 36 <= dpi <= 600 or not 0 <= margin <= 500:
            raise ValueError('PDF page/dpi/margin out of range')
        if not params['phrase'] or int(params['occurrence']) < 1:
            raise ValueError('set phrase and positive occurrence')
        page = document[number - 1]
        text = page.get_textpage()
        search = text.search(params['phrase'])
        try:
            hit = None
            for _ in range(int(params['occurrence'])):
                hit = search.get_next()
                if hit is None:
                    raise ValueError('phrase not found on PDF page')
            boxes = list(text.get_rect(i) for i in range(text.count_rects(*hit)))
            left = max(0, min(b[0] for b in boxes) - margin)
            bottom = max(0, min(b[1] for b in boxes) - margin)
            right = min(page.get_width(), max(b[2] for b in boxes) + margin)
            top = min(page.get_height(), max(b[3] for b in boxes) + margin)
            output = Path(params['output'])
            _authorize_coordination_write(operation, params, output, owner_admitted=owner_admitted)
            if output.exists() and not params['overwrite']:
                raise FileExistsError(str(output))
            output.parent.mkdir(parents=True, exist_ok=True)
            bitmap = page.render(scale=dpi / 72, crop=(left, bottom, page.get_width() - right, page.get_height() - top))
            try:
                image = bitmap.to_pil()
                try:
                    _atomic_office_output(output, lambda temporary: image.save(temporary, format='PNG'), overwrite=params['overwrite'])
                finally:
                    image.close()
            finally:
                bitmap.close()
            return {'file': str(output), 'images': [{'path': str(output), 'cell': params['image_cell']}], 'out': {'file': str(output), 'page': number,
                    'phrase': params['phrase'], 'bounds': [left, bottom, right, top], 'path': params['path']}}
        finally:
            search.close()
            text.close()
            page.close()


def coordination_invoke(operation, params, *, owner_admitted=False):
    """Typed Office/PDF actions at the existing adapter boundary."""
    if operation == 'excel.read_table':
        return _read_comment_tables(params)
    if operation == 'excel.build_workbook':
        return _build_coordination_workbook(params, owner_admitted=owner_admitted)
    if operation == 'excel.write_cells':
        return _write_coordination_cells(params, owner_admitted=owner_admitted)
    if operation == 'excel.share_workbook':
        target = Path(params['destination'])
        _authorize_coordination_write(operation, params, target, owner_admitted=owner_admitted)
        _atomic_office_output(target, lambda temporary: shutil.copyfile(params['path'], temporary), overwrite=params['overwrite'])
        return {'out': str(target), 'file': str(target)}
    if operation == 'excel.open':
        if Path(params['path']).suffix.lower() not in ('.xlsx', '.xlsm', '.xlsb', '.xls', '.csv', '.xltx', '.xltm'):
            raise ValueError('excel.open requires a workbook file')
        if not params['show']:
            return {'out': {'path': params['path'], 'opened': False}}
        if not owner_admitted:
            raise ValueError('show workbook requires this account owner Canvas run')
        if not Path(params['path']).is_file():
            raise FileNotFoundError(params['path'])
        os.startfile(str(Path(params['path']).resolve()))
        return {'out': {'path': params['path'], 'opened': True}}
    if operation in ('pdf.extract_text', 'pdf.snip'):
        return _pdf_coordination(operation, params, owner_admitted=owner_admitted)
    raise OfficeUnreachable('unsupported coordination operation: ' + operation)


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
    "excel.read_range": ("excel", "workbook", "range"),
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


def _a1_cell(cell: str) -> tuple[int, int]:
    match = re.fullmatch(r"([A-Za-z]+)([1-9][0-9]*)", cell.strip())
    if not match:
        raise OfficeUnreachable("Excel range must use A1 notation")
    col = 0
    for ch in match.group(1).upper():
        col = col * 26 + ord(ch) - 64
    return int(match.group(2)), col


def _range_bounds(value: object) -> tuple[int, int, int, int]:
    text = str(value or "").strip()
    if not text:
        raise OfficeUnreachable("set Excel range")
    parts = text.split(":", 1)
    start = _a1_cell(parts[0])
    end = _a1_cell(parts[-1])
    r1, c1 = min(start[0], end[0]), min(start[1], end[1])
    r2, c2 = max(start[0], end[0]), max(start[1], end[1])
    return r1, c1, r2, c2


def _read_xlsx_range(path: object, sheet: object, wanted_range: object) -> dict[str, object]:
    file = str(path or "").strip()
    if not file:
        raise OfficeUnreachable("set Excel fixture file")
    if str(file).startswith(("\\\\", "//")):
        raise OfficeUnreachable("Excel fixture file must be local")
    r1, c1, r2, c2 = _range_bounds(wanted_range)
    wanted_sheet = str(sheet or "Sheet1").strip() or "Sheet1"
    cells: dict[tuple[int, int], str] = {}
    with zipfile.ZipFile(file) as zf:
        workbook = ET.fromstring(zf.read("xl/workbook.xml"))
        ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
              "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
        sheet_id = None
        for node in workbook.findall(".//m:sheet", ns):
            if node.attrib.get("name") == wanted_sheet:
                sheet_id = node.attrib.get("{%s}id" % ns["r"])
                break
        if sheet_id is None:
            raise OfficeUnreachable("worksheet not found: %s" % wanted_sheet)
        rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
        target = None
        for rel in rels:
            if rel.attrib.get("Id") == sheet_id:
                target = rel.attrib.get("Target")
                break
        if not target:
            raise OfficeUnreachable("worksheet relationship missing")
        worksheet = ET.fromstring(zf.read("xl/" + target.lstrip("/")))
        for cell in worksheet.findall(".//m:c", ns):
            ref = cell.attrib.get("r", "")
            try:
                row, col = _a1_cell(ref)
            except OfficeUnreachable:
                continue
            inline = cell.find(".//m:t", ns)
            cells[(row, col)] = "" if inline is None or inline.text is None else inline.text
    rows = [[cells.get((row, col), "") for col in range(c1, c2 + 1)] for row in range(r1, r2 + 1)]
    return {"host": "excel", "workbook": file, "sheet": wanted_sheet, "range": str(wanted_range), "rows": rows, "count": len(rows)}


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


def invoke(op_id: str, arguments: Mapping[str, object], *, owner_admitted=False) -> dict:
    """Carry out one declared read against an already-open application."""
    if op_id in COORDINATION_NODES:
        return coordination_invoke(op_id, arguments, owner_admitted=owner_admitted)
    if op_id == "excel.read_range":
        return _read_xlsx_range(arguments.get("file"), arguments.get("sheet"), arguments.get("range"))

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
