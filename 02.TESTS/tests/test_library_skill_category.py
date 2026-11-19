"""V22GCOURT: a saved node type keeps the category chosen in the Save as node type dialog."""
from nodelang.library_engines import LIBRARY_PRESENTATION, _saved_category


def test_the_chosen_category_is_kept_where_the_design_files_it_and_an_unknown_one_is_a_skill():
    assert _saved_category('Checks') == 'governance'
    assert _saved_category('Files') == 'file'
    assert _saved_category('Project') == 'input'
    assert _saved_category('Skills: yours') == 'skill'
    assert _saved_category('logic') == 'logic', 'a Library category id is kept as it is'
    assert _saved_category('Not a category') == 'skill'
    assert _saved_category(None) == 'skill'
    assert {_saved_category(word) for word in ('Checks', 'Files', 'Project', 'Scripts', 'Skills: yours')} <= {c for c, _ in LIBRARY_PRESENTATION}


def test_the_served_library_keeps_each_saved_skill_in_its_own_category_whatever_the_load_order(monkeypatch):
    from nodelang import session_files
    def skill(identity, category):
        return {'path': identity + '.archhub', 'skill': {'id': identity, 'title': identity, 'nodes': [], 'wires': [],
                                                          'properties': {'nodeType': {'category': category, 'public': []}}}}
    rows = [skill('checks-skill', 'Checks'), skill('files-skill', 'Files')]
    for order in (rows, rows[::-1]):
        monkeypatch.setattr(session_files, 'load_skills', lambda order=order: list(order))
        served = {item['id']: item['cat'] for item in session_files.catalogue() if item['id'].startswith('skill:')}
        assert served['skill:checks-skill'] == 'governance' and served['skill:files-skill'] == 'file', served
