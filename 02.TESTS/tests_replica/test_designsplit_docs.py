"""The guide route uses the repository's existing documentation, without a graph."""
from nodelang.nograph_server import r_documentation


def test_documentation_opens_existing_guide_and_spec_glossary():
    from nodelang.site_export import project_documentation
    result = r_documentation(None, None)
    assert result['tutorials'] == project_documentation()['tutorials']
    assert next(page for page in result['tutorials'] if page['id'] == 'getting-started')['text']
    terms = {entry['term']: entry['definition'] for entry in result['glossary']}
    assert '.archhub' in terms['Document']
    assert 'connection point' in terms['Socket']
    assert all(terms.values())


def test_glossary_uses_the_selected_flat_package(monkeypatch, tmp_path):
    from pathlib import Path
    from nodelang import nograph_server
    expected = r_documentation(None, None)['glossary']
    spec = Path(nograph_server.__file__).resolve().parents[2] / '04.DOCS' / 'SPEC.md'
    package = tmp_path / 'selected'
    (package / 'docs').mkdir(parents=True)
    (package / 'docs' / 'SPEC.md').write_bytes(spec.read_bytes())
    monkeypatch.setattr(nograph_server, '__file__', str(package / 'nodelang' / 'nograph_server.py'))
    assert r_documentation(None, None)['glossary'] == expected
