"""Datasets: fields, records and cells on the canvas (Ping's Penpot rev1036, founder 2026-10-28).

A field is a column (its schema), a record is a row, a cell is one typed value.
It extends the typed parameters of node_params rather than adding a second model:
  dataset node  type 'data.dataset'; node.paramDefs are its FIELDS (same entries, same coerce);
                node.records = [{id, cells: {field_id: value}}]. A node's own params are the
                one-record case of the same thing.
                The dataset has one typed output socket per field ('field:<id>', door.width -> Number[]).
  field node    type 'data.field'; input 'column' wired from a dataset field socket, output 'values'.
                The WIRE is the binding: delete it and the field node is unbound, wire another
                field and it reads that one. It holds NO values, so every consumer references
                dataset.field and never a copy.
Editing a cell changes the dataset; the solve follows its wires to the field nodes and everything
downstream of them (Filter, Convert, ...) at once.
"""
from __future__ import annotations

from uuid import uuid4

from .node_params import coerce, default, definition, socket_type

DATASET_ENGINE = 'data.dataset'
FIELD_ENGINE = 'data.field'
LIMITS = {'fields': 64, 'records': 10000}
TYPE_LABEL = {'number': 'Number', 'integer': 'Integer', 'text': 'Text', 'bool': 'Boolean', 'choice': 'Choice',
              'date': 'Date', 'file': 'File', 'folder': 'Folder', 'object': 'Object', 'list': 'List'}


def _dataset(document, ref):
    found = [n for n in document['nodes'] if n['type'] == DATASET_ENGINE and (n['id'] == ref or n.get('title') == ref)]
    if len(found) != 1:
        raise ValueError('Name exactly one dataset: %s' % ref)
    found[0].setdefault('paramDefs', [])  # a Dataset placed from the Library starts empty
    found[0].setdefault('records', [])
    return found[0]


def _field_nodes(document, dataset_id, field=None):
    return [w['to']['node'] for w in document['wires'] if w['from']['node'] == dataset_id
            and w['from']['socket'].startswith('field:') and field in (None, w['from']['socket'][6:])]


def new_dataset(document, title, x=0.0, y=0.0):
    node = {'id': str(uuid4()), 'type': DATASET_ENGINE, 'item': DATASET_ENGINE, 'title': str(title).strip()[:80] or 'Dataset',
            'params': {}, 'paramDefs': [], 'records': [], 'position': {'x': float(x), 'y': float(y)}}
    document['nodes'].append(node)
    return [node['id']]


def add_field(document, dataset_ref, name, kind, value=None, **limits):
    """+Field: a typed column; every existing record gets the value (or the type's default)."""
    from .node_params import add_param
    dataset = _dataset(document, dataset_ref)
    if len(dataset['paramDefs']) >= LIMITS['fields']:
        raise ValueError('A dataset holds at most %d fields.' % LIMITS['fields'])
    add_param(document, dataset['id'], name, kind, value, **limits)  # same naming, typing and limits as a parameter
    entry = dataset['paramDefs'][-1]
    first = dataset['params'].pop(entry['id'])  # a dataset's values live in its records only
    for record in dataset['records']:
        record['cells'][entry['id']] = first
    return [dataset['id']]


def add_record(document, dataset_ref, cells=None):
    """+Record: one row; named cells are typed by their field, the rest take the field default."""
    dataset = _dataset(document, dataset_ref)
    if not dataset['paramDefs']:
        raise ValueError('Add a field before the first record.')
    if len(dataset['records']) >= LIMITS['records']:
        raise ValueError('A dataset holds at most %d records.' % LIMITS['records'])
    cells = dict(cells or {})
    unknown = set(cells) - {d['id'] for d in dataset['paramDefs']}
    if unknown:
        raise ValueError('Unknown fields: %s' % ', '.join(sorted(unknown)))
    row = {d['id']: coerce(d['type'], cells[d['id']], d) if d['id'] in cells else default(d) for d in dataset['paramDefs']}
    dataset['records'].append({'id': str(uuid4()), 'cells': row})
    return [dataset['id'], *_field_nodes(document, dataset['id'])]


def _record(dataset, record):
    if isinstance(record, int) or str(record).isdigit():
        index = int(record)
        if not 0 <= index < len(dataset['records']):
            raise ValueError('Record %s is outside 0..%d.' % (record, len(dataset['records']) - 1))
        return dataset['records'][index]
    found = [r for r in dataset['records'] if r['id'] == record]
    if not found:
        raise ValueError('Record is absent: %s' % record)
    return found[0]


def set_cell(document, dataset_ref, record, field, value):
    """Edit one cell (type-checked by its field); returns what must re-solve."""
    dataset = _dataset(document, dataset_ref)
    entry = definition(dataset, field)
    _record(dataset, record)['cells'][field] = coerce(entry['type'], value, entry)
    return [dataset['id'], *_field_nodes(document, dataset['id'], field)]


def expose_field(document, dataset_ref, field):
    """A field as a node: the whole column as one typed list, read from the dataset."""
    dataset = _dataset(document, dataset_ref)
    entry = definition(dataset, field)
    node = {'id': str(uuid4()), 'type': FIELD_ENGINE, 'item': FIELD_ENGINE, 'title': dataset['title'] + '.' + field,
            'params': {'type': entry['type']},
            'position': {'x': dataset['position']['x'] + 380, 'y': dataset['position']['y'] + 90 * len(_field_nodes(document, dataset['id']))}}
    document['nodes'].append(node)
    document['wires'].append({'id': str(uuid4()), 'from': {'node': dataset['id'], 'socket': 'field:' + field},
                              'to': {'node': node['id'], 'socket': 'column'}})
    return [node['id']]


def outputs(node, feeds):
    if node['type'] == FIELD_ENGINE:
        if 'column' not in feeds:
            raise ValueError('Unbound: wire a dataset field into column.')
        values = list(feeds['column'])
        return {'values': values}, '%s · %s[] · %d' % (node.get('title', ''), label(node['params'].get('type')), len(values))
    records = node.get('records', [])
    columns = {'field:' + d['id']: [r['cells'].get(d['id']) for r in records] for d in node.get('paramDefs', [])}
    return {'records': [dict(r['cells']) for r in records], **columns}, '%d fields · %d records' % (len(columns), len(records))


def label(kind):
    return TYPE_LABEL.get(kind, 'Any')


def ports(node):
    if node['type'] == FIELD_ENGINE:
        kind = node['params'].get('type')
        return {'source': [{'id': 'values', 'type': 'list', 'label': label(kind) + '[]', 'of': socket_type(kind)}],
                'target': [{'id': 'column', 'type': 'list', 'label': 'column'}]}
    return {'source': [{'id': 'records', 'type': 'list', 'label': 'Record[]'}]
            + [{'id': 'field:' + d['id'], 'type': 'list', 'label': '%s · %s[]' % (d['name'], label(d['type'])), 'of': socket_type(d['type'])}
               for d in node.get('paramDefs', [])], 'target': []}


CATALOGUE_ITEM = {'id': DATASET_ENGINE, 'cat': 'input', 'title': 'Dataset', 'sub': 'Fields, records and typed cells',
                  'engine': DATASET_ENGINE, 'params': {}, 'ports': {'source': [{'id': 'records', 'type': 'list'}], 'target': []}}
FIELD_ITEM = {'id': FIELD_ENGINE, 'cat': 'input', 'title': 'Field', 'sub': 'One dataset column as a typed list',
              'engine': FIELD_ENGINE, 'params': {'type': 'any'}, 'hidden': True,
              'ports': {'source': [{'id': 'values', 'type': 'list'}], 'target': [{'id': 'column', 'type': 'list'}]}}
