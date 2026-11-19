"""R224: the Decision score node ranks wired options with TOPSIS and re-solves on edit."""
import pytest

OPTIONS = [{'name': 'A', 'cost': 250, 'area': 120}, {'name': 'B', 'cost': 200, 'area': 100},
           {'name': 'C', 'cost': 300, 'area': 150}]
CRITERIA = [{'field': 'cost', 'weight': 1, 'direction': 'minimize'},
            {'field': 'area', 'weight': 1, 'direction': 'maximize'}]


def _score(method, rows=OPTIONS, criteria=CRITERIA):
    from nodelang.library_engines import weighted_valuation
    out, _ = weighted_valuation({'method': method}, {'in': rows, 'criteria': criteria})
    return out['out']


def test_topsis_ranks_and_closeness_is_between_zero_and_one():
    ranked = _score('TOPSIS')
    assert [r['rank'] for r in ranked] == [1, 2, 3]
    assert all(0 <= r['score'] <= 1 for r in ranked)
    # Hand-computed TOPSIS for A: vector norms 438.75 / 216.56, d+ 0.0897, d- 0.0734, closeness 0.450.
    a = next(r for r in ranked if r['name'] == 'A')
    assert abs(a['score'] - 0.450) < 0.002


def test_weights_change_the_winner():
    cheap = [{'field': 'cost', 'weight': 9, 'direction': 'minimize'}, {'field': 'area', 'weight': 1, 'direction': 'maximize'}]
    big = [{'field': 'cost', 'weight': 1, 'direction': 'minimize'}, {'field': 'area', 'weight': 9, 'direction': 'maximize'}]
    assert _score('TOPSIS', criteria=cheap)[0]['name'] == 'B'
    assert _score('TOPSIS', criteria=big)[0]['name'] == 'C'


def test_old_files_keep_weighted_sum_and_bad_method_is_refused():
    from nodelang.library_engines import weighted_valuation
    old, _ = weighted_valuation({'criteria': CRITERIA}, {'in': OPTIONS})
    assert old['out'] == _score('Weighted sum')
    with pytest.raises(ValueError, match='Choose one of'):
        _score('Magic')


def test_wired_method_overrides_params():
    from nodelang.library_engines import weighted_valuation
    out, _ = weighted_valuation({'method': 'Weighted sum'}, {'in': OPTIONS, 'criteria': CRITERIA, 'method': 'TOPSIS'})
    assert out['out'] == _score('TOPSIS')


def test_node_is_pure_and_library_card_offers_the_method_choice():
    from nodelang.canvas_documents import is_pure
    from nodelang.library_engines import library_catalogue
    assert is_pure('research.weighted')
    card = next(i for g in library_catalogue() for i in g['items'] if i['id'] == 'research_valuation')
    assert card['title'] == 'Decision score' and card['params']['method'] == 'TOPSIS'
    assert next(d for d in card['paramDefs'] if d['id'] == 'method')['options'] == ['TOPSIS', 'Weighted sum']


def _placed(item_id, engine):
    """A node as canvas.add_node places it: the catalogue card's params and paramDefs."""
    from nodelang.library_engines import library_catalogue
    card = next(i for g in library_catalogue() for i in g['items'] if i['id'] == item_id)
    return {'id': 'n', 'type': engine, 'item': item_id, 'title': card['title'], 'params': dict(card['params']),
            'paramDefs': [dict(d) for d in card['paramDefs']], 'position': {'x': 0, 'y': 0}}


def test_method_sets_promotes_and_exposes_as_a_typed_choice():
    from nodelang import node_params
    from nodelang.library_engines import LIBRARY_ITEM_ENGINES
    # Every declared definition carries its name and type, wherever a node copies it from.
    for d in LIBRARY_ITEM_ENGINES['research_valuation']['paramDefs']:
        assert d['name'] and d['type'] in node_params.TYPES
    doc = {'nodes': [_placed('research_valuation', 'research.weighted')], 'wires': [], 'groups': [], 'notes': []}
    node_params.set_value(doc, 'n', 'method', 'Weighted sum')
    assert doc['nodes'][0]['params']['method'] == 'Weighted sum'
    with pytest.raises(ValueError, match='Choose one of'):
        node_params.set_value(doc, 'n', 'method', 'Magic')
    made = node_params.promote(doc, 'n', 'method')
    param = next(n for n in doc['nodes'] if n['id'] == made[0])
    assert param['params']['type'] == 'choice' and param['title'] == 'Method'
    # The exposed Parameter node writes its owner's one value, still held to the choices.
    node_params.set_value(doc, param['id'], 'value', 'TOPSIS')
    assert doc['nodes'][0]['params']['method'] == 'TOPSIS'
    with pytest.raises(ValueError, match='Choose one of'):
        node_params.set_value(doc, param['id'], 'value', 'Magic')
    sockets = {p['id']: p['type'] for p in node_params.ports(doc['nodes'][0], {})['target']}
    assert sockets['param:method'] == 'string'
