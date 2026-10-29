"""The daily-work pack: six canvas nodes for an architect's ordinary day (S8).

Founder 2026-10-29 DAILYPACK: title-block QA, revision compare, clash/IDS to
BCF, Arabic OCR, area schedules and meeting minutes, each a node in a
.archhub file under contract C2: typed sockets, a pure / side-effect flag and
a budget. They join canvas_documents.THING_ENGINES, so run_document, solve()
and the Library already carry them; nothing here is a second runner.

Two PDF nodes run in the app on what the installer already ships (pypdfium2,
Pillow, numpy), so they are pure and re-solve on edit. The other four need a
heavy runtime -- IfcOpenShell + ifctester + bcf-client, PaddleOCR's models on
onnxruntime (RapidOCR), whisper.cpp -- which is NOT bundled: the first Run
fetches the exact pinned files, refuses any whose SHA-256 differs, and keeps
them per user under %LOCALAPPDATA%\\ArchHub\\runtimes. Because that first Run
reaches the network, those four wait for Run. Each heavy job runs in its own
interpreter (daily_work_worker.py) and is killed at its budget.

PaddlePaddle publishes no CPython 3.14 wheel, so the PaddleOCR models (PP-OCR
det/cls and the Arabic recogniser) run on onnxruntime through RapidOCR, the
maintained ONNX packaging of the same models.
"""
from __future__ import annotations

import csv
import difflib
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

from . import daily_work_worker  # noqa: E402 - runs as its own interpreter; imported so the app ships it

WORKER = Path(daily_work_worker.__file__)
_RESULT = 'ARCHHUB-RESULT '

# --------------------------------------------------------- pinned runtimes --
# Exact files, exact SHA-256. A pin changes only with a new commit; the folder
# name carries the pin digest so an upgrade never mixes with an old runtime.
_IFC_LOCK = """\
ifctester==0.9.0 --hash=sha256:f7e57615d9c07b616510e55d8adf3cb05df872956ce0e0d46a907101a9968004
bcf-client==0.9.0 --hash=sha256:68915ee2633e9b683ed122a90a7f3fbeca1e4af8a0bf3e0623499d16c616c3f5
xsdata==26.10 --hash=sha256:37a697d60db1396a0431750486744a7e0491fd60669751d95e3ede08f034e0c6
xmlschema==4.3.2 --hash=sha256:cf5c970a30f6ebcb3da35260e694704cc0b6794d8ace46125bb2a95e38ed9307
elementpath==5.1.4 --hash=sha256:5ec8d7bb44b16c98414a6a95e20cb150f3cbfc3cac65edc14773288c7a937376
python-dateutil==2.9.0.post0 --hash=sha256:a8b2bc7bffae282281c8140a97d3aa9c14da0b136dfe83f850eea9a5f7470427
six==1.17.0 --hash=sha256:4721f391ed90541fddacab5acf947aa0d3dc7d27b2e1e8eda2be8970586c3274
pystache==0.6.8 --hash=sha256:7211e000974a6e06bce2d4d5cad8df03bcfffefd367209117376e4527a1c3cb8
"""
_OCR_LOCK = """\
rapidocr==3.10.0 --hash=sha256:2fc34e26cd0f48514804a94f8832283039c7334076bff60768b1fed9ad068050
onnxruntime==1.31.1 --hash=sha256:0a3998e18cb667ef54287556bd62291a788ed235723dd90c83b2294b24e71d81
opencv-python-headless==4.13.0.92 --hash=sha256:77a82fe35ddcec0f62c15f2ba8a12ecc2ed4207c17b0902c7a3151ae29f37fb6
shapely==2.2.0 --hash=sha256:48dd1d961391f314ab7fa8812c86ca2a727bee2bdca1478730eacaea007da18e
pyclipper==1.4.0 --hash=sha256:6c317e182590c88ec0194149995e3d71a979cfef3b246383f4e035f9d4a11826
omegaconf==2.4.0 --hash=sha256:f141a664c777582405e3cc6e0545ecc79429e79f844995b1a6e71c35946a025c
antlr4-python3-runtime==4.13.2 --hash=sha256:fe3835eb8d33daece0e799090eda89719dbccee7aa39ef94eed3818cafa5a7e8
colorlog==6.12.0 --hash=sha256:30d392604e9110045a2c2aeefc27d7a017abbab63f3a8aee594eac0801df784e
tqdm==4.70.1 --hash=sha256:c293e525e6fef9c20e8728fd4612df02a0aa31bb5fe91ecd93e123b1b7bffa73
six==1.17.0 --hash=sha256:4721f391ed90541fddacab5acf947aa0d3dc7d27b2e1e8eda2be8970586c3274
flatbuffers==25.12.19 --hash=sha256:7634f50c427838bb021c2d66a3d1168e9d199b0607e6329399f04846d42e20b4
protobuf==7.36.2 --hash=sha256:a300819d441e078a5608c0d3c709796bb548136058fda017ae51d425b44fd353
python-bidi==0.6.12 --hash=sha256:da6a3d80d6a521bb7d44ed5e7378323b86ff38fa0b6103b6dbd50abbab031145
requests==2.34.2 --hash=sha256:2a0d60c172f83ac6ab31e4554906c0f3b3588d37b5cb939b1c061f4907e278e0
urllib3==2.8.0 --hash=sha256:0cf3cae568d36aa9576b28dfb35f11328f1cb974ca7647d9475ebb86c75ac6e3
charset-normalizer==3.5.2 --hash=sha256:e4e81e09c1578b8df602e3db08b0b3ea0a6947ad612f52bf8dc5ea8d47691f0c
"""
RUNTIMES = {
    'ifc': {'lock': _IFC_LOCK, 'files': [
        {'url': 'https://github.com/IfcOpenShell/IfcOpenShell/releases/download/ifcopenshell-python-0.9.0post1/'
                'ifcopenshell-python-0.9.0post1-py314-win64.zip',
         'sha256': '522a577aa690a2e3ff2dfa63f8f83a7b30c9e54663813b97b0467c856d7d81b9', 'bytes': 43076308,
         'unzip': 'site'}]},
    'ocr': {'lock': _OCR_LOCK, 'files': []},
    'whisper': {'lock': '', 'files': [
        {'url': 'https://github.com/ggml-org/whisper.cpp/releases/download/b5454/whisper-bin-x64.zip',
         'sha256': '6ba69e3482d7826214f90a6a9c84ca07782aec1e1d0c6a7c30c994fd5d816ccb', 'bytes': 8928640,
         'unzip': 'bin'}]},
}
# Multilingual whisper.cpp models (Arabic and English); one is fetched when first picked.
WHISPER_MODELS = {
    'base-q5_1': {'url': 'https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base-q5_1.bin',
                  'sha256': '422f1ae452ade6f30a004d7e5c6a43195e4433bc370bf23fac9cc591f01a8898', 'bytes': 59707625},
    'small-q5_1': {'url': 'https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small-q5_1.bin',
                   'sha256': 'ae85e4a935d7a567bd102fe55afc16bb595bdb618e11b2fc7591bc08120411bb', 'bytes': 190085487},
}


def runtimes_root() -> Path:
    return Path(os.environ['LOCALAPPDATA']) / 'ArchHub' / 'runtimes'


def _pin_digest(spec) -> str:
    return hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()[:12]


def fetch(url: str, sha256: str, size: int, target: Path, *, timeout=60) -> Path:
    """Download one pinned file; a byte count or SHA-256 that differs leaves nothing behind."""
    if target.is_file() and _sha256(target) == sha256:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + '.part')
    digest, held = hashlib.sha256(), 0
    try:
        with urllib.request.urlopen(url, timeout=timeout) as answer, partial.open('wb') as out:
            while True:
                chunk = answer.read(1 << 20)
                if not chunk:
                    break
                held += len(chunk)
                if held > size:
                    raise ValueError('%s is larger than its pin (%d bytes)' % (url, size))
                digest.update(chunk)
                out.write(chunk)
        if digest.hexdigest() != sha256:
            raise ValueError('%s failed its checksum: got %s, pinned %s' % (url, digest.hexdigest(), sha256))
        os.replace(partial, target)
    finally:
        partial.unlink(missing_ok=True)
    return target


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_runtime(name: str, *, budget_s: float = 900) -> Path:
    """The pinned runtime folder, fetched and verified on first use."""
    spec = RUNTIMES[name]
    home = runtimes_root() / ('%s-%s' % (name, _pin_digest(spec)))
    if (home / 'ready.json').is_file():
        return home
    building = home.with_name(home.name + '.building')
    shutil.rmtree(building, ignore_errors=True)
    (building / 'site').mkdir(parents=True)
    for row in spec['files']:
        archive = fetch(row['url'], row['sha256'], row['bytes'], runtimes_root() / 'downloads' / Path(row['url']).name)
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(building / row['unzip'])
        archive.unlink()
    if spec['lock']:
        lock = building / 'lock.txt'
        lock.write_text(spec['lock'], encoding='utf-8')
        # pip's hash mode refuses any wheel whose SHA-256 is not the pinned one.
        done = subprocess.run([sys.executable, '-m', 'pip', 'install', '--disable-pip-version-check', '--no-input',
                               '--no-deps', '--require-hashes', '--only-binary=:all:', '--target', str(building / 'site'),
                               '-r', str(lock)], capture_output=True, text=True, timeout=budget_s,
                              creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if done.returncode:
            shutil.rmtree(building, ignore_errors=True)
            raise RuntimeError('the %s runtime did not install: %s' % (name, (done.stderr or done.stdout)[-400:]))
    (building / 'ready.json').write_text(json.dumps({'pin': spec, 'at': time.time()}), encoding='utf-8')
    shutil.rmtree(home, ignore_errors=True)
    os.replace(building, home)
    return home


def ensure_whisper_model(name: str) -> Path:
    if name not in WHISPER_MODELS:
        raise ValueError('model must be one of %s' % ', '.join(WHISPER_MODELS))
    row = WHISPER_MODELS[name]
    return fetch(row['url'], row['sha256'], row['bytes'], runtimes_root() / 'whisper-models' / Path(row['url']).name)


def run_worker(job: str, args: dict, *, site: Path | None, budget_s: float) -> dict:
    """One heavy job in its own interpreter, stopped at its budget."""
    with tempfile.TemporaryDirectory(prefix='archhub-daily-') as scratch:
        order = Path(scratch) / 'job.json'
        order.write_text(json.dumps({'job': job, 'site': str(site) if site else '', 'args': args}), encoding='utf-8')
        try:
            done = subprocess.run([sys.executable, '-I', str(WORKER), str(order)], capture_output=True, text=True,
                                  encoding='utf-8', errors='replace', timeout=budget_s, cwd=scratch,
                                  creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except subprocess.TimeoutExpired:
            raise TimeoutError('%s ran past its budget of %d s; raise budget_s to allow more' % (job, budget_s))
    line = next((l for l in reversed(done.stdout.splitlines()) if l.startswith(_RESULT)), None)
    if line is None:
        raise RuntimeError('%s stopped without an answer: %s' % (job, (done.stderr or done.stdout)[-600:]))
    answer = json.loads(line[len(_RESULT):])
    if answer.get('error'):
        raise RuntimeError(answer['error'])
    return answer


# ----------------------------------------------------------------- helpers --
def _port(name, kind='any'):
    return {'id': name, 'type': kind}


def _local_file(value, label, suffixes=None) -> Path:
    from .pipeline_engines import _local_input_path
    if isinstance(value, list):
        value = value[0] if value else ''
    path = Path(_local_input_path(str(value or ''), label=label))
    if suffixes and path.suffix.lower() not in suffixes:
        raise ValueError('%s must be %s, not %s' % (label, ' or '.join(suffixes), path.name))
    return path


def _files(value, label) -> list:
    rows = value if isinstance(value, list) else [v for v in re.split(r'[\r\n;]+', str(value or '')) if v.strip()]
    if len(rows) == 1 and Path(str(rows[0]).strip()).is_dir():
        rows = sorted(str(p) for p in Path(str(rows[0]).strip()).glob('*.pdf'))
    if not rows:
        raise ValueError('Wire a PDF, a list of PDFs or a folder, or set %s.' % label)
    return [_local_file(str(row).strip(), label, ('.pdf',)) for row in rows]


def _budget(params, spec) -> float:
    try:
        asked = float(params.get('budget_s') or spec['params']['budget_s'])
    except (TypeError, ValueError):
        asked = spec['params']['budget_s']
    return max(5.0, min(asked, 4 * 3600.0))


def _words(text):
    return [line.strip() for line in text.replace('\r', '\n').split('\n') if line.strip()]


# ------------------------------------------------------ 1 title-block QA --
_REGIONS = {'right': (0.75, 0.0, 1.0, 1.0), 'bottom': (0.0, 0.0, 1.0, 0.25),
            'bottom-right': (0.55, 0.0, 1.0, 0.35), 'all': (0.0, 0.0, 1.0, 1.0)}


def _label_value(lines, label):
    pattern = re.compile(r'(?i)\b' + re.escape(label) + r'\b\s*[:#.\-]?\s*(.*)$')
    for index, line in enumerate(lines):
        found = pattern.search(line)
        if found:
            value = found.group(1).strip()
            if not value and index + 1 < len(lines):
                value = lines[index + 1].strip()  # the value sits under its label in many title blocks
            return value
    return None


def titleblock_qa(params, feeds):
    import pypdfium2 as pdfium
    spec = DAILY_ENGINES['daily.titleblock_qa']
    files = _files(feeds.get('pdf') or params.get('pdf'), 'pdf')
    fields = [f.strip() for f in str(params.get('fields') or '').split(',') if f.strip()]
    region = _REGIONS.get(str(params.get('region') or 'right'), _REGIONS['right'])
    number = re.compile(str(params.get('sheet_number_pattern') or r'\b[A-Z]{1,3}-?\d{2,4}\b'))
    limit = int(float(params.get('max_pages') or spec['params']['max_pages']))
    started, sheets, budget = time.monotonic(), [], _budget(params, spec)
    for path in files:
        document = pdfium.PdfDocument(str(path))
        try:
            for index in range(len(document)):
                if time.monotonic() - started > budget:
                    raise TimeoutError('title-block QA ran past its budget of %d s; raise budget_s' % budget)
                if len(sheets) >= limit:
                    raise ValueError('more than %d sheets; raise max_pages to check them all' % limit)
                page = document[index]
                width, height = page.get_size()
                text_page = page.get_textpage()
                x0, y0, x1, y1 = region
                text = text_page.get_text_bounded(width * x0, height * y0, width * x1, height * y1)
                lines = _words(text)
                values = {label: _label_value(lines, label) for label in fields}
                missing = [label for label, value in values.items() if not value]
                sheet = values.get('Drawing No') or values.get('Sheet No') or ''
                found = number.search(sheet) or number.search(' '.join(lines))
                sheets.append({'file': str(path), 'page': index + 1, 'sheet_number': found.group(0) if found else '',
                               'fields': {k: v or '' for k, v in values.items()}, 'missing': missing})
                text_page.close()
                page.close()
        finally:
            document.close()
    problems = []
    counts = {}
    for row in sheets:
        if not row['sheet_number']:
            problems.append({'file': row['file'], 'page': row['page'], 'issue': 'no sheet number found'})
        counts.setdefault(row['sheet_number'], []).append(row)
        for label in row['missing']:
            problems.append({'file': row['file'], 'page': row['page'], 'issue': 'missing ' + label})
    for value, rows in counts.items():
        if value and len(rows) > 1:
            for row in rows:
                problems.append({'file': row['file'], 'page': row['page'], 'issue': 'duplicate sheet number ' + value})
    for label in [f for f in fields if f.lower() in ('project', 'project name', 'client')]:
        seen = {row['fields'][label] for row in sheets if row['fields'].get(label)}
        if len(seen) > 1:
            problems.append({'file': '', 'page': 0, 'issue': '%s differs across sheets: %s' % (label, ' | '.join(sorted(seen)))})
    for row in sheets:
        row['ok'] = not any(p['page'] == row['page'] and p['file'] == row['file'] for p in problems)
    summary = '%d sheet(s), %d issue(s), %.1f s' % (len(sheets), len(problems), time.monotonic() - started)
    return {'sheets': sheets, 'issues': problems, 'summary': summary}, summary


# ---------------------------------------------------- 2 revision compare --
def _page_image(document, index, scale):
    import numpy
    page = document[index]
    image = page.render(scale=scale, grayscale=True).to_pil().convert('L')
    text_page = page.get_textpage()
    text = text_page.get_text_range()
    text_page.close()
    page.close()
    return numpy.asarray(image, dtype=numpy.int16), _words(text)


def _regions(mask, block):
    """Changed blocks grouped into boxes (pixels), largest first."""
    import numpy
    rows, cols = -(-mask.shape[0] // block), -(-mask.shape[1] // block)
    padded = numpy.zeros((rows * block, cols * block), dtype=bool)
    padded[:mask.shape[0], :mask.shape[1]] = mask
    cells = padded.reshape(rows, block, cols, block).any(axis=(1, 3))
    seen, boxes = numpy.zeros_like(cells), []
    for r, c in zip(*numpy.nonzero(cells)):
        if seen[r, c]:
            continue
        stack, box = [(r, c)], [r, c, r, c]
        seen[r, c] = True
        while stack:
            y, x = stack.pop()
            box = [min(box[0], y), min(box[1], x), max(box[2], y), max(box[3], x)]
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < rows and 0 <= nx < cols and cells[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        stack.append((ny, nx))
        boxes.append([box[1] * block, box[0] * block, (box[3] + 1) * block, (box[2] + 1) * block])
    return sorted(boxes, key=lambda b: -(b[2] - b[0]) * (b[3] - b[1]))


def revision_compare(params, feeds):
    import numpy
    import pypdfium2 as pdfium
    from PIL import Image, ImageDraw
    spec = DAILY_ENGINES['daily.revision_compare']
    old = _local_file(feeds.get('old') or params.get('old'), 'old', ('.pdf',))
    new = _local_file(feeds.get('new') or params.get('new'), 'new', ('.pdf',))
    dpi = max(36.0, min(float(params.get('dpi') or 100), 300.0))
    threshold = int(float(params.get('threshold') or 48))
    limit = int(float(params.get('max_pages') or spec['params']['max_pages']))
    scale = dpi / 72.0
    started, budget = time.monotonic(), _budget(params, spec)
    overlays = Path(os.environ['LOCALAPPDATA']) / 'ArchHub' / 'daily-work' / 'compare' / hashlib.sha256(
        (_sha256(old) + _sha256(new) + repr((dpi, threshold))).encode()).hexdigest()[:16]
    first, second = pdfium.PdfDocument(str(old)), pdfium.PdfDocument(str(new))
    pages, files = [], []
    try:
        count = max(len(first), len(second))
        if count > limit:
            raise ValueError('%d pages; raise max_pages to compare them all' % count)
        for index in range(count):
            if time.monotonic() - started > budget:
                raise TimeoutError('revision compare ran past its budget of %d s; raise budget_s' % budget)
            if index >= len(first) or index >= len(second):
                pages.append({'page': index + 1, 'status': 'added' if index >= len(first) else 'removed',
                              'changed_ratio': 1.0, 'regions': [], 'text_added': [], 'text_removed': []})
                continue
            a, a_text = _page_image(first, index, scale)
            b, b_text = _page_image(second, index, scale)
            height, width = max(a.shape[0], b.shape[0]), max(a.shape[1], b.shape[1])
            pad = lambda m: numpy.pad(m, ((0, height - m.shape[0]), (0, width - m.shape[1])), constant_values=255)
            a, b = pad(a), pad(b)
            mask = numpy.abs(a - b) > threshold
            boxes = _regions(mask, max(4, int(dpi / 12)))
            diff = list(difflib.ndiff(a_text, b_text))
            row = {'page': index + 1, 'status': 'changed' if boxes else 'same',
                   'changed_ratio': round(float(mask.mean()), 6),
                   # PDF points from the page's bottom-left corner, as a reviewer marks up.
                   'regions': [[round(x0 / scale, 1), round((height - y1) / scale, 1), round(x1 / scale, 1),
                                round((height - y0) / scale, 1)] for x0, y0, x1, y1 in boxes[:50]],
                   'text_added': [l[2:] for l in diff if l.startswith('+ ')],
                   'text_removed': [l[2:] for l in diff if l.startswith('- ')]}
            if boxes:
                overlays.mkdir(parents=True, exist_ok=True)
                picture = Image.fromarray(numpy.uint8(155 + (b * 100) // 255)).convert('RGB')  # the new issue, faded
                pen = ImageDraw.Draw(picture)
                for x0, y0, x1, y1 in boxes[:50]:
                    pen.rectangle([x0, y0, x1, y1], outline=(220, 30, 30), width=3)
                target = overlays / ('page-%03d.png' % (index + 1))
                picture.save(target)
                files.append(str(target))
            pages.append(row)
    finally:
        first.close()
        second.close()
    changed = [p['page'] for p in pages if p['status'] != 'same']
    summary = '%d page(s) compared, %d changed%s' % (len(pages), len(changed),
                                                     (': ' + ', '.join(map(str, changed[:20]))) if changed else '')
    return {'pages': pages, 'overlays': files, 'summary': summary}, summary


# ------------------------------------------- 3 clash and IDS check to BCF --
def ifc_check_bcf(params, feeds):
    spec = DAILY_ENGINES['daily.ifc_check_bcf']
    model = _local_file(feeds.get('ifc') or params.get('ifc'), 'ifc', ('.ifc',))
    ids = feeds.get('ids') or params.get('ids')
    ids = str(_local_file(ids, 'ids', ('.ids', '.xml'))) if ids else ''
    target = Path(str(params.get('bcf_path') or model.with_suffix('.bcf')))
    if not target.is_absolute() or str(target).startswith(('\\\\', '//')):
        raise ValueError('bcf_path must be a local absolute path')
    budget = _budget(params, spec)
    site = ensure_runtime('ifc', budget_s=budget) / 'site'
    answer = run_worker('ifc_check', {'ifc': str(model), 'ids': ids, 'bcf': str(target),
                                      'a': str(params.get('clash_a') or 'IfcWall'),
                                      'b': str(params.get('clash_b') or 'IfcColumn, IfcBeam, IfcSlab, IfcDuctSegment, IfcPipeSegment'),
                                      'tolerance': float(params.get('tolerance') or 0.002)}, site=site, budget_s=budget)
    summary = '%d clash(es), %d IDS failure(s), %d BCF topic(s) -> %s' % (
        len(answer['clashes']), len(answer['ids_failures']), answer['topics'], target.name)
    return {'clashes': answer['clashes'], 'ids_failures': answer['ids_failures'], 'bcf': str(target),
            'summary': summary}, summary


# ------------------------------------------------------------ 4 Arabic OCR --
_IMAGES = ('.png', '.jpg', '.jpeg', '.bmp', '.tif', '.tiff', '.webp')


def arabic_ocr(params, feeds):
    import pypdfium2 as pdfium
    spec = DAILY_ENGINES['daily.arabic_ocr']
    source = _local_file(feeds.get('image') or params.get('image'), 'image', _IMAGES + ('.pdf',))
    budget = _budget(params, spec)
    site = ensure_runtime('ocr', budget_s=budget) / 'site'
    with tempfile.TemporaryDirectory(prefix='archhub-ocr-') as scratch:
        pictures = [source]
        if source.suffix.lower() == '.pdf':
            document = pdfium.PdfDocument(str(source))
            try:
                limit = min(len(document), int(float(params.get('max_pages') or spec['params']['max_pages'])))
                pictures = []
                for index in range(limit):
                    picture = Path(scratch) / ('page-%03d.png' % (index + 1))
                    document[index].render(scale=200 / 72).to_pil().save(picture)
                    pictures.append(picture)
            finally:
                document.close()
        answer = run_worker('ocr', {'images': [str(p) for p in pictures], 'lang': str(params.get('lang') or 'arabic'),
                                    'min_score': float(params.get('min_score') or 0.5)}, site=site, budget_s=budget)
    lines = answer['lines']
    text = '\n'.join(row['text'] for row in lines)
    summary = '%d line(s) read from %s' % (len(lines), source.name)
    return {'text': text, 'lines': lines, 'summary': summary}, summary


# --------------------------------------------------------- 5 area schedule --
def _group_rows(rows, group_by, area_field):
    totals, schedule = {}, []
    for raw in rows:
        row = raw if isinstance(raw, dict) else {'name': str(raw)}
        try:
            area = float(str(row.get(area_field, row.get('area', 0)) or 0).replace(',', ''))
        except ValueError:
            raise ValueError('area is not a number on %s: %r' % (row.get('name', '?'), row.get(area_field)))
        key = str(row.get(group_by) or '(none)')
        schedule.append({**row, 'area': round(area, 3), group_by: key})
        totals[key] = round(totals.get(key, 0.0) + area, 3)
    schedule.sort(key=lambda r: (r[group_by], str(r.get('number') or r.get('name') or '')))
    return schedule, totals


def area_schedule(params, feeds):
    spec = DAILY_ENGINES['daily.area_schedule']
    group_by = str(params.get('group_by') or 'level')
    area_field = str(params.get('area_field') or 'area')
    rows = feeds.get('rows')
    if isinstance(rows, str) and rows.strip().startswith('['):
        rows = json.loads(rows)
    if not rows:
        model = _local_file(feeds.get('ifc') or params.get('ifc'), 'ifc', ('.ifc',))
        budget = _budget(params, spec)
        site = ensure_runtime('ifc', budget_s=budget) / 'site'
        rows = run_worker('areas', {'ifc': str(model)}, site=site, budget_s=budget)['spaces']
    schedule, totals = _group_rows(rows, group_by, area_field)
    stream = io.StringIO()
    columns = ['number', 'name', group_by, 'area'] + sorted({k for r in schedule for k in r} - {'number', 'name', group_by, 'area'})
    writer = csv.DictWriter(stream, fieldnames=columns, extrasaction='ignore', lineterminator='\n')
    writer.writeheader()
    writer.writerows(schedule)
    total = round(sum(totals.values()), 3)
    summary = '%d space(s), %s m2 total over %d %s group(s)' % (len(schedule), total, len(totals), group_by)
    return {'schedule': schedule, 'totals': totals, 'total': total, 'csv': stream.getvalue(), 'summary': summary}, summary


# -------------------------------------------------------- 6 meeting minutes --
def _clock(seconds):
    seconds = int(seconds)
    return '%02d:%02d:%02d' % (seconds // 3600, seconds // 60 % 60, seconds % 60)


def meeting_minutes(params, feeds):
    spec = DAILY_ENGINES['daily.meeting_minutes']
    audio = _local_file(feeds.get('audio') or params.get('audio'), 'audio', ('.wav', '.mp3', '.flac', '.ogg'))
    budget = _budget(params, spec)
    home = ensure_runtime('whisper', budget_s=budget)
    model = ensure_whisper_model(str(params.get('model') or 'base-q5_1'))
    binary = next(iter(sorted(home.glob('bin/**/whisper-cli.exe'))), None)
    if binary is None:
        raise RuntimeError('whisper-cli.exe is missing from the whisper.cpp runtime')
    answer = run_worker('whisper', {'binary': str(binary), 'model': str(model), 'audio': str(audio),
                                    'language': str(params.get('language') or 'auto'),
                                    'threads': int(float(params.get('threads') or max(1, (os.cpu_count() or 4) // 2)))},
                        site=None, budget_s=budget)
    segments = answer['segments']
    transcript = ' '.join(s['text'] for s in segments).strip()
    title = str(params.get('title') or audio.stem)
    length = segments[-1]['end'] if segments else 0
    minutes = '\n'.join(['# Minutes: %s' % title, '', 'Recording: %s (%s), transcribed on this machine by whisper.cpp.'
                         % (audio.name, _clock(length)), '', '## Record'] +
                        ['- [%s] %s' % (_clock(s['start']), s['text']) for s in segments])
    summary = '%d segment(s), %s of audio' % (len(segments), _clock(length))
    return {'transcript': transcript, 'segments': segments, 'minutes': minutes, 'summary': summary}, summary


# ------------------------------------------------------------ the contract --
# engine -> sockets (typed), purity, budget, executor. Same shape as THING_ENGINES.
DAILY_ENGINES = {
    'daily.titleblock_qa': {
        'engine': 'daily.titleblock_qa', 'pure': True, 'run': titleblock_qa,
        'in': [_port('pdf', 'path')], 'out': [_port('sheets', 'list'), _port('issues', 'list'), _port('summary', 'string')],
        'title': 'Title-block QA', 'sub': 'Check every sheet\'s title block: fields, sheet numbers, duplicates',
        'params': {'pdf': '', 'fields': 'Project, Drawing No, Revision, Scale, Date, Drawn',
                   'region': 'right', 'sheet_number_pattern': r'\b[A-Z]{1,3}-?\d{2,4}\b', 'max_pages': 500,
                   'budget_s': 60}},
    'daily.revision_compare': {
        'engine': 'daily.revision_compare', 'pure': True, 'run': revision_compare,
        'in': [_port('old', 'path'), _port('new', 'path')],
        'out': [_port('pages', 'list'), _port('overlays', 'list'), _port('summary', 'string')],
        'title': 'Revision compare', 'sub': 'What changed between two issues of a drawing (PDF)',
        'params': {'old': '', 'new': '', 'dpi': 100, 'threshold': 48, 'max_pages': 200, 'budget_s': 120}},
    'daily.ifc_check_bcf': {
        'engine': 'daily.ifc_check_bcf', 'pure': False, 'run': ifc_check_bcf,
        'in': [_port('ifc', 'path'), _port('ids', 'path')],
        'out': [_port('clashes', 'list'), _port('ids_failures', 'list'), _port('bcf', 'path'), _port('summary', 'string')],
        'title': 'Clash + IDS check to BCF', 'sub': 'IfcOpenShell clash and ifctester IDS, issues written as BCF',
        'params': {'ifc': '', 'ids': '', 'bcf_path': '', 'clash_a': 'IfcWall',
                   'clash_b': 'IfcColumn, IfcBeam, IfcSlab, IfcDuctSegment, IfcPipeSegment', 'tolerance': 0.002,
                   'budget_s': 900}},
    'daily.arabic_ocr': {
        'engine': 'daily.arabic_ocr', 'pure': False, 'run': arabic_ocr,
        'in': [_port('image', 'path')], 'out': [_port('text', 'string'), _port('lines', 'list'), _port('summary', 'string')],
        'title': 'Arabic OCR', 'sub': 'Read Arabic or English text from a scan, photo or PDF (PaddleOCR models)',
        'params': {'image': '', 'lang': 'arabic', 'min_score': 0.5, 'max_pages': 20, 'budget_s': 600}},
    'daily.area_schedule': {
        'engine': 'daily.area_schedule', 'pure': False, 'run': area_schedule,
        'in': [_port('ifc', 'path'), _port('rows', 'list')],
        'out': [_port('schedule', 'list'), _port('totals', 'object'), _port('total', 'number'), _port('csv', 'string'),
                _port('summary', 'string')],
        'title': 'Area schedule', 'sub': 'Space areas from an IFC model or wired room rows, totalled by level',
        'params': {'ifc': '', 'group_by': 'level', 'area_field': 'area', 'budget_s': 600}},
    'daily.meeting_minutes': {
        'engine': 'daily.meeting_minutes', 'pure': False, 'run': meeting_minutes,
        'in': [_port('audio', 'path')],
        'out': [_port('minutes', 'string'), _port('transcript', 'string'), _port('segments', 'list'), _port('summary', 'string')],
        'title': 'Meeting minutes', 'sub': 'Transcribe a recording on this machine (whisper.cpp), timestamped',
        'params': {'audio': '', 'title': '', 'model': 'base-q5_1', 'language': 'auto', 'threads': 0, 'budget_s': 3600}},
}

# The budget is the node's own parameters, so the founder can raise it on the card.
for _spec in DAILY_ENGINES.values():
    _spec['budget'] = {'seconds': _spec['params']['budget_s'], 'pages': _spec['params'].get('max_pages')}

# C3 hook: HOOKGUARD binds its one decision function here (decide(payload, vendor) -> {'decision': ...}).
# Until it does, pressing Run is the approval. Every side-effect node passes this gate before it acts.
DECIDE = None


def _gated(engine, run):
    def gated(params, feeds):
        if DECIDE is not None:
            verdict = DECIDE({'tool_name': engine, 'tool_input': dict(params)}, 'archhub-canvas') or {}
            if verdict.get('decision', 'allow') != 'allow':
                raise PermissionError('%s is waiting for approval: %s' % (engine, verdict.get('reason') or verdict['decision']))
        return run(params, feeds)
    return gated


for _engine, _spec in DAILY_ENGINES.items():
    if not _spec['pure']:
        _spec['run'] = _gated(_engine, _spec['run'])


def daily_items():
    """Library cards for the daily-work pack."""
    return [{'id': 'daily:' + engine.split('.', 1)[1], 'cat': 'daily work', 'title': spec['title'], 'sub': spec['sub'],
             'engine': engine, 'params': dict(spec['params']), 'pure': spec['pure'], 'budget': dict(spec['budget']),
             'ports': {'source': list(spec['out']), 'target': list(spec['in'])}}
            for engine, spec in DAILY_ENGINES.items()]
