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
from nodelang.cell_website import PUBLIC_WEBSITE_ROUTES  # noqa: E402
from nodelang.ui_runtime import project_document  # noqa: E402


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


def test_legacy_website_is_only_references_to_canonical_publication(website):
    store, reg = website
    page = project_document(store, reg['app'], reg['website']['ui_root'])
    for route in PUBLIC_WEBSITE_ROUTES:
        assert 'href="%s"' % route in page
    assert 'website-hero' not in page
    assert 'website-graph-card' not in page
    assert 'The built environment, operated as a living graph.' not in page
    assert 'preview_cards' not in reg['website']


def test_share_omits_retired_mock_website_preview_and_export(website):
    store, reg = website
    page = project_document(store, reg['app'], reg['ui_root'])
    assert 'Preview website' not in page
    assert 'Export website graph' not in page
    assert 'website-hero' not in store.pull(store.nodes[reg['app']]['params']['stylesheet'])


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
        with urllib.request.urlopen(server.url + '/assets/tutorials/home-templates.png', timeout=10) as capture:
            assert capture.headers.get_content_type() == 'image/png'
            assert capture.read() == (Path(__file__).parents[1] / 'nodelang/data/website/tutorials/home-templates.png').read_bytes()
        assert 'Drafted, not generated.' in web
        # The Grand Map domain grid came off the public home on
        # 2026-09-17; the design the home answers to has no such
        # section and nothing replaced it.
        assert 'site-domain-card' not in web
        assert 'The Grand Map' not in web
        for route, expected in (
                ('/website/features', 'One canvas. Every tool you already use.'),
                ('/website/pricing', 'Free during beta'),
                ('/website/changelog', 'Released builds, not intentions'),
                ('/website/security', 'Nothing runs without a reason you can see'),
                ('/website/community', 'Share with your firm, on your terms'),
                ('/website/signin', 'Sign in from the desktop app')):
            page = urllib.request.urlopen(server.url + route, timeout=10).read().decode('utf-8')
            assert expected in page
    finally:
        server.close()


def test_every_public_route_is_a_wired_page_node(website):
    store, reg = website
    web = reg['website']
    assert set(web['routes']) == set(PUBLIC_WEBSITE_ROUTES)
    assert len(web['route_relations']) == len(PUBLIC_WEBSITE_ROUTES) - 1
    assert all(store.nodes[rid]['kind'] == 'wire'
               for rid in web['route_relations'].values())
