"""Forcing for the public website as a projection of the application graph."""
from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nodelang.application import build_archhub_application  # noqa: E402
from nodelang.application_server import ApplicationServer  # noqa: E402
from nodelang.core import relation_sources, relation_targets, validate_store  # noqa: E402
from nodelang.ui_runtime import activate_ui, project_document  # noqa: E402


@pytest.fixture(scope='module')
def website():
    return build_archhub_application()


def test_website_is_a_session_node_wired_to_application(website):
    store, reg = website
    web = reg['website']
    session = store.nodes[web['session']]
    assert session['kind'] == 'session'
    assert session['title'] == 'ArchHub Website'
    assert web['session'] in store.nodes[reg['app']]['body']['inner']
    relation = store.nodes[web['app_relation']]
    assert relation_sources(store.nodes, relation)[0]['node_id'] == reg['app']
    assert relation_targets(store.nodes, relation)[0]['node_id'] == web['session']
    assert validate_store(store) is True


def test_website_hero_is_the_live_product_graph_not_a_static_mockup(website):
    store, reg = website
    page = project_document(store, reg['app'], reg['website']['ui_root'])
    assert 'class="website-root"' in page
    assert 'class="website-hero"' in page
    assert 'The built environment, operated as a living graph.' in page
    assert 'One graph. Every domain.' in page
    assert len(reg['website']['preview_cards']) == 6
    assert page.count('data-relation=') >= 6
    assert 'height:min(900px,92vh)' in page
    assert '12.PRODUCTION' not in page


def test_website_domain_action_enters_same_application_graph(website):
    store, reg = build_archhub_application()
    node_id, card = next(iter(reg['website']['preview_cards'].items()))
    activate_ui(store, card)
    assert store.pull(reg['mode']) == 'workspace'
    assert store.pull(reg['focus']) == node_id


def test_http_server_serves_the_universal_app_and_website_lenses(website):
    store, reg = build_archhub_application()
    server = ApplicationServer(
        store=store, registry=reg, allow_legacy_mutations=True
    ).start()
    try:
        app = urllib.request.urlopen(urllib.request.Request(
            server.url + '/',
            headers={'X-ArchHub-Session': server.browser_session_token},
        ), timeout=10).read().decode('utf-8')
        web = urllib.request.urlopen(server.url + '/website', timeout=10).read().decode('utf-8')
        assert 'class="archhub-app"' in app
        assert 'class="site-shell"' in web
        assert 'class="archhub-app"' not in web
        assert 'One persistent operating graph' in web
        for route, expected in (
                ('/website/features', 'Everything is connected through one graph'),
                ('/website/pricing', 'Commercial release is not active'),
                ('/website/changelog', 'Revision evidence, not progress theatre'),
                ('/website/security', 'Security is an authority chain'),
                ('/website/community', 'Community federation is not connected'),
                ('/website/signin', 'Public account access is not enabled')):
            page = urllib.request.urlopen(server.url + route, timeout=10).read().decode('utf-8')
            assert expected in page
    finally:
        server.close()


def test_every_public_route_is_a_wired_page_node(website):
    store, reg = website
    web = reg['website']
    assert set(web['routes']) == {
        '/website', '/website/features', '/website/pricing', '/website/changelog',
        '/website/security', '/website/community', '/website/signin'}
    assert len(web['route_relations']) == 6
    assert all(store.nodes[rid]['kind'] == 'wire'
               for rid in web['route_relations'].values())
