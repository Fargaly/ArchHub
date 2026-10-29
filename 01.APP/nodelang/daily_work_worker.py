"""Heavy daily-work jobs, each in its own interpreter (see daily_work_nodes.run_worker).

Run as ``python -I daily_work_worker.py job.json``. The job names a pinned
runtime folder that goes first on sys.path; the answer is one line on stdout
prefixed ``ARCHHUB-RESULT``. This file imports nothing from the app, so a
crash or a stray native library in a runtime never reaches the app process.
"""
import json
import os
import subprocess
import sys
import tempfile
import traceback


def ifc_check(args):
    import numpy
    import ifcopenshell
    from ifcopenshell import geom
    from ifcopenshell.util import placement as placements, unit as units
    from bcf.v2.bcfxml import BcfXml
    model = ifcopenshell.open(args['ifc'])
    bcf = BcfXml.create_new('ArchHub check: ' + os.path.basename(args['ifc']))
    scale = units.calculate_unit_scale(model)

    def where(element):
        if getattr(element, 'ObjectPlacement', None):
            return [float(o) * scale for o in placements.get_local_placement(element.ObjectPlacement)[:3, 3]]
        return [0.0, 0.0, 0.0]

    ids_failures = []
    if args['ids']:
        import ifctester.ids
        specs = ifctester.ids.open(args['ids'])
        specs.validate(model)
        for spec in specs.specifications:
            for requirement in spec.requirements:
                for failure in requirement.failures:
                    element = failure['element']
                    row = {'specification': spec.name, 'requirement': requirement.to_string('requirement'),
                           'guid': element.GlobalId, 'type': element.is_a(), 'name': element.Name or '',
                           'reason': str(failure.get('reason') or '')}
                    ids_failures.append(row)
                    topic = bcf.add_topic('IDS: %s %s - %s' % (row['type'], row['name'] or row['guid'], spec.name),
                                          '%s: %s' % (row['requirement'], row['reason']), 'ArchHub')
                    topic.add_viewpoint_from_point_and_guids(numpy.array(where(element)) + 5.0, element.GlobalId)

    def pick(classes):
        out = []
        for name in [c.strip() for c in classes.split(',') if c.strip()]:
            try:
                out.extend(model.by_type(name))
            except RuntimeError:
                raise ValueError('%s is not an IFC class in %s' % (name, model.schema))
        return out

    group_a, group_b = pick(args['a']), pick(args['b'])
    clashes = []
    if group_a and group_b:
        settings = geom.settings()
        settings.set('use-world-coords', True)
        # IfcOpenShell 0.9's default tree (opencascade.brep) answers no clash queries; the triangle BVH tree does.
        tree = geom.tree(backend='opencascade.trianglebvh')
        iterator = geom.iterator(settings, model, max(1, (os.cpu_count() or 2) // 2),
                                              include=list({e.id(): e for e in group_a + group_b}.values()))
        if iterator.initialize():
            while True:
                tree.add_element(iterator.get())
                if not iterator.next():
                    break
        seen = set()
        for clash in tree.clash_intersection_many(group_a, group_b, tolerance=args['tolerance'], check_all=True):
            a, b = clash.a, clash.b
            pair = tuple(sorted((a.GlobalId, b.GlobalId)))
            if a == b or pair in seen:
                continue
            seen.add(pair)
            point = [float(v) for v in clash.p1]
            clashes.append({'a': a.GlobalId, 'a_type': a.is_a(), 'a_name': a.Name or '', 'b': b.GlobalId,
                            'b_type': b.is_a(), 'b_name': b.Name or '', 'point': [round(v, 3) for v in point],
                            'depth': round(float(clash.distance), 4)})
            topic = bcf.add_topic('Clash: %s %s / %s %s' % (a.is_a(), a.Name or '', b.is_a(), b.Name or ''),
                                  'Hard clash, penetration %.3f m at %s' % (abs(float(clash.distance)),
                                                                           [round(v, 2) for v in point]), 'ArchHub')
            topic.add_viewpoint_from_point_and_guids(numpy.array(point) + 5.0, a.GlobalId, b.GlobalId)
    bcf.save_project(args['bcf'])
    return {'clashes': clashes, 'ids_failures': ids_failures, 'topics': len(clashes) + len(ids_failures)}


def areas(args):
    import ifcopenshell
    from ifcopenshell import geom
    from ifcopenshell.util import element as elements, shape as shapes
    model = ifcopenshell.open(args['ifc'])
    settings = geom.settings()
    spaces = []
    for space in model.by_type('IfcSpace'):
        quantities = elements.get_psets(space, qtos_only=True)
        base = quantities.get('Qto_SpaceBaseQuantities') or quantities.get('BaseQuantities') or {}
        area = base.get('NetFloorArea') or base.get('GrossFloorArea')
        source = 'quantity'
        if not area:
            area = shapes.get_footprint_area(geom.create_shape(settings, space).geometry)
            source = 'geometry'
        storey, parent = None, space
        while parent is not None and storey is None:
            parent = elements.get_container(parent) or elements.get_aggregate(parent)
            if parent is not None and parent.is_a('IfcBuildingStorey'):
                storey = parent
        spaces.append({'number': space.Name or '', 'name': space.LongName or space.Name or '', 'guid': space.GlobalId,
                       'level': storey.Name if storey else '', 'area': round(float(area), 3), 'source': source,
                       'department': (elements.get_psets(space).get('Pset_SpaceCommon') or {}).get('Category', '')})
    return {'spaces': spaces}


def ocr(args):
    from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR
    home = os.path.dirname(sys.path[0])
    models = os.path.join(home, 'models')
    os.makedirs(models, exist_ok=True)
    lang = args['lang']
    params = {'Global.model_root_dir': models, 'Global.log_level': 'error', 'Global.text_score': args['min_score']}
    if lang == 'arabic':
        params.update({'Rec.lang_type': LangRec.ARABIC, 'Rec.ocr_version': OCRVersion.PPOCRV5, 'Rec.model_type': ModelType.MOBILE})
    elif lang == 'english':
        params.update({'Rec.lang_type': LangRec.EN, 'Rec.ocr_version': OCRVersion.PPOCRV5, 'Rec.model_type': ModelType.MOBILE})
    else:
        raise ValueError('lang must be arabic or english')
    engine = RapidOCR(params=params)
    lines = []
    for page, image in enumerate(args['images'], 1):
        result = engine(image)
        boxes = result.boxes if result.boxes is not None else []
        for box, text, score in zip(boxes, result.txts or (), result.scores or ()):
            xs, ys = [float(p[0]) for p in box], [float(p[1]) for p in box]
            lines.append({'page': page, 'text': text, 'score': round(float(score), 3),
                          'box': [round(min(xs)), round(min(ys)), round(max(xs)), round(max(ys))]})
    # Reading order: top to bottom, and right to left within a line for Arabic.
    rtl = lang == 'arabic'
    lines.sort(key=lambda r: (r['page'], round(r['box'][1] / 20), -r['box'][2] if rtl else r['box'][0]))
    return {'lines': lines}


def whisper(args):
    with tempfile.TemporaryDirectory(prefix='archhub-whisper-') as scratch:
        stem = os.path.join(scratch, 'out')
        done = subprocess.run([args['binary'], '-m', args['model'], '-f', args['audio'], '-l', args['language'],
                               '-t', str(args['threads']), '-oj', '-of', stem, '-np'], capture_output=True, text=True,
                              encoding='utf-8', errors='replace',
                              creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if done.returncode or not os.path.isfile(stem + '.json'):
            raise RuntimeError('whisper.cpp failed (%s): %s' % (done.returncode, (done.stderr or done.stdout)[-500:]))
        with open(stem + '.json', encoding='utf-8') as stream:
            held = json.load(stream)
    segments = [{'start': row['offsets']['from'] / 1000.0, 'end': row['offsets']['to'] / 1000.0,
                 'text': row['text'].strip()} for row in held.get('transcription', []) if row['text'].strip()]
    return {'segments': segments, 'language': (held.get('result') or {}).get('language', '')}


JOBS = {'ifc_check': ifc_check, 'areas': areas, 'ocr': ocr, 'whisper': whisper}


def main():
    with open(sys.argv[1], encoding='utf-8') as stream:
        order = json.load(stream)
    if order.get('site'):
        sys.path.insert(0, order['site'])
    try:
        answer = JOBS[order['job']](order['args'])
    except Exception as error:  # noqa: BLE001 - every failure goes back to the node card as one line
        traceback.print_exc()
        answer = {'error': '%s: %s' % (type(error).__name__, error)}
    sys.stdout.write('ARCHHUB-RESULT ' + json.dumps(answer) + '\n')


if __name__ == '__main__':
    main()
