"""Rendered public truth, catalogue coverage and metadata stamp courts."""
import re
from html import unescape
import pytest
from nodelang import site_export
from nodelang.base_universal_catalogue import BASE_CATALOGUE
from nodelang.cell_accounts import BETA_OFFER
from nodelang.map_import import PUBLIC_MAP_PATH
from nodelang.universal_application import build_universal_application

BANNED = (
    "hides it to the system tray", "needs an add-in this build does not install",
    "this build does not install the add-in", "save any thread as a skill",
    "nothing happens that you can't see, trace, or undo", "tower-a",
    "plotted on friday", "manual restarts", "median recovery",
    "x hides to tray", "no revit add-in installed", "undo anything",
)

@pytest.fixture(scope='module')
def export():
    store, registry = build_universal_application(PUBLIC_MAP_PATH)
    offer = dict(BETA_OFFER)
    return site_export.build_site_export(store, registry, offer=offer,
        offer_sha256=site_export.offer_digest(offer), origin='https://archhub.io')

def test_rendered_public_pages_never_claim_unimplemented_features(export):
    for route, record in export['routes'].items():
        text = unescape(re.sub('<[^>]+>', ' ', record['html'])).lower()
        for phrase in BANNED:
            assert phrase not in text, (route, phrase)

def test_every_base_catalogue_entry_has_generated_documentation():
    docs = site_export.project_documentation()
    assert [(n['title'], n['detail']) for n in docs['nodes']] == [
        (n['name'], n['description']) for n in BASE_CATALOGUE]
    assert all(n['id'] and n['category'] for n in docs['nodes'])

def test_docs_stamp_changes_from_metadata_not_a_literal(tmp_path):
    (tmp_path / 'BUILD_ID').write_text('20991231-2359-abcdef0', encoding='utf-8')
    assert site_export.documentation_build_id(tmp_path) == '20991231-2359-abcdef0'
    pages = site_export.documentation_pages(build_id=site_export.documentation_build_id(tmp_path), host_artifacts={})
    assert all('20991231-2359-abcdef0' in body for _, _, body in pages.values())
    assert all('20260916-2130-e733a13' not in body for _, _, body in pages.values())

def test_docs_header_and_body_share_the_metadata_stamp(export):
    stamp = site_export.documentation_build_id()
    for route, record in export['routes'].items():
        if '/docs/' not in route:
            continue
        page = record['html']
        assert '<span class="site-ver">%s</span>' % stamp in page
        assert 'Documentation build %s' % stamp in page
        assert 'build %s' % stamp in page

@pytest.mark.parametrize('phrase', BANNED)
def test_banned_claim_admission_refuses_each_phrase(phrase):
    with pytest.raises(site_export.SiteExportError, match='untrue public claim'):
        site_export.validate_public_claims('<p>%s</p>' % phrase)


def test_build_stamp_uses_release_build_metadata_when_id_file_is_absent(tmp_path):
    import json
    (tmp_path / 'BUILD_METADATA.json').write_text(json.dumps({
        'format': 1, 'build_id': '20991230-2358-abcdef1', 'built_at': '2099-12-30T23:58:00Z'
    }), encoding='utf-8')
    assert site_export.documentation_build_id(tmp_path) == '20991230-2358-abcdef1'


def test_connector_docs_use_reviewed_index_and_never_infer_a_live_host():
    text = site_export.connector_docs_markdown({'revit': {'2099': {'reviewed': True}},
                                              'max': {'reviewed': True, 'script': 'reviewed.py'}})
    assert 'Reviewed artifacts: 2099' in text
    assert 'Reviewed startup script' in text
    assert 'connected' not in text.lower()


@pytest.mark.parametrize('document', [
    '<p>Save <b>any</b> thread as a skill</p>',
    '<p>Save any\nthread as a skill</p>',
])
def test_public_claim_admission_normalizes_rendered_markup_and_whitespace(document):
    with pytest.raises(site_export.SiteExportError, match='untrue public claim'):
        site_export.validate_public_claims(document)

# COH3 owns these additions: generated tutorial/asset and claim-admission courts.
def test_six_tutorials_follow_the_installed_starter_catalogue(export):
    from nodelang.universal_pipeline import _usage_starters
    from html import escape
    starters = _usage_starters()
    tutorials = {route: record for route, record in export['routes'].items()
                 if '/docs/tutorial-' in route}
    assert len(tutorials) == len(starters) == 6
    for item, title, _, children in starters:
        record = tutorials['/website/docs/tutorial-' + item.removeprefix('tpl-')]
        assert escape(title.replace('\u2192', 'to')) in record['html']
        assert '<img ' in record['html']
        for child in children:
            assert escape(child['title']) in record['html']
        if item in ('tpl-cad-inventory', 'tpl-titleblocks'):
            from nodelang.clean_host_catalogue_source import HOST_OPERATION_RECORDS
            operation = children[0]['params']['operation']
            description = next(row['description'] for row in HOST_OPERATION_RECORDS if row['op_id'] == operation)
            assert escape(description) in record['html']
        image = re.search(r'<img [^>]*src="/([^\"]+)"', record['html']).group(1)
        assert image in export['files']
        source = site_export._brand_bytes(image)
        import hashlib
        assert hashlib.sha256(source).hexdigest() == export['files'][image]['sha256']


@pytest.mark.parametrize('document', [
    '<p>Bring <b>your own</b> key</p>',
    '<p>Paste your API key</p>',
    '<p>Goose is running</p>',
])
def test_new_unproven_release_claims_are_refused(document):
    with pytest.raises(site_export.SiteExportError, match='untrue public claim'):
        site_export.validate_public_claims(document)


def test_goose_docs_version_follows_selected_package_metadata_without_running_it(tmp_path):
    import json
    pin = tmp_path / 'packaging/windows/goose-pin.json'
    pin.parent.mkdir(parents=True)
    pin.write_text(json.dumps({'version': '9.8.7'}))
    assert site_export.documentation_goose_version(tmp_path) == '9.8.7'
    pin.unlink()
    manifest = tmp_path / 'runtime/goose/manifest.json'
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({'version': '6.5.4'}))
    assert site_export.documentation_goose_version(tmp_path) == '6.5.4'
    manifest.write_text(json.dumps({'version': 'unsafe markup'}))
    assert site_export.documentation_goose_version(tmp_path) == 'unavailable'


def test_source_docs_never_borrow_a_different_installations_metadata(tmp_path, monkeypatch):
    import json
    source = tmp_path / 'selected-source' / 'nodelang' / 'site_export.py'
    source.parent.mkdir(parents=True)
    foreign = tmp_path / 'other-installation' / 'ArchHub'
    foreign.mkdir(parents=True)
    (foreign / 'BUILD_ID').write_text('19990101-0000-abcdef0')
    (foreign / 'HOST_ARTIFACTS.json').write_text(json.dumps({'schema': 'archhub-host-artifacts-index/v1', 'revit': {'2099': {'reviewed': True}}}))
    runtime = foreign / 'runtime/goose'
    runtime.mkdir(parents=True)
    (runtime / 'manifest.json').write_text(json.dumps({'version': '1.2.3'}))
    monkeypatch.setattr(site_export, '__file__', str(source))
    monkeypatch.setenv('LOCALAPPDATA', str(foreign.parent))
    assert site_export.documentation_build_id() == 'unavailable'
    assert site_export.documentation_host_artifacts() == {}
    assert site_export.documentation_goose_version() == 'unavailable'
