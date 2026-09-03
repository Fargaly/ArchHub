"""Public ArchHub website built from the same universal node graph."""
from __future__ import annotations

from .laws_surface import ui_element
from .ui_runtime import connect_ui_action, connect_ui_binding, connect_ui_child


WEBSITE_CSS = r"""
.website-root{width:100%;min-height:100vh;background:var(--bg);color:var(--ink);overflow:auto}.website-nav{height:62px;display:flex;align-items:center;padding:0 5vw;border-bottom:1px solid var(--line);position:absolute;z-index:20;left:0;right:0;top:0}.website-wordmark{font-family:'Architects Daughter','Segoe Print',cursive;font-size:22px;text-transform:uppercase}.website-wordmark strong{color:var(--accent);font-weight:400}.website-nav-spacer{flex:1}.website-nav-link{border:1px solid var(--line);border-radius:5px;background:var(--bg-panel);color:var(--ink);padding:7px 12px;cursor:pointer}.website-hero{height:min(900px,92vh);min-height:620px;position:relative;overflow:hidden;background:var(--bg-canvas);border-bottom:1px solid var(--line)}.website-graph{position:absolute;inset:0;opacity:.72}.website-graph-lines{position:absolute;inset:0;width:100%;height:100%;pointer-events:none}.website-graph-line{stroke:var(--accent);stroke-width:1.2;stroke-opacity:.35}.website-graph-card{position:absolute;width:190px;min-height:94px;border:1px solid var(--line);border-radius:6px;background:var(--bg-panel);color:var(--ink);padding:11px;text-align:left;box-shadow:0 6px 24px rgba(0,0,0,.3);cursor:pointer}.website-graph-card:hover{border-color:var(--accent)}.website-graph-label{font-family:ui-monospace,monospace;font-size:9px;color:var(--ink-muted);letter-spacing:.12em;text-transform:uppercase}.website-graph-title{font-family:'Instrument Serif',Georgia,serif;font-size:18px;margin-top:7px}.website-graph-value{font-family:ui-monospace,monospace;font-size:10px;color:var(--ok);margin-top:12px}.website-hero-copy{position:absolute;z-index:10;left:7vw;top:22%;max-width:620px;text-shadow:0 2px 22px var(--bg-deep)}.website-eyebrow{font-family:ui-monospace,monospace;font-size:10px;letter-spacing:.18em;color:var(--accent);text-transform:uppercase}.website-h1{font-family:'Architects Daughter','Segoe Print',cursive;font-size:64px;line-height:1;text-transform:uppercase;margin:16px 0 18px}.website-h1 strong{color:var(--accent);font-weight:400}.website-lede{font-family:'Instrument Serif',Georgia,serif;font-size:24px;line-height:1.3;max-width:560px}.website-body{font-size:14px;color:var(--ink-soft);line-height:1.6;max-width:540px;margin-top:14px}.website-cta{margin-top:24px;border:1px solid var(--accent);border-radius:5px;background:var(--accent);color:white;padding:10px 16px;cursor:pointer;font-weight:600}.website-next{min-height:48vh;padding:56px 7vw 80px}.website-section-kicker{font-family:ui-monospace,monospace;font-size:9px;letter-spacing:.18em;color:var(--accent);text-transform:uppercase}.website-section-title{font-family:'Instrument Serif',Georgia,serif;font-size:36px;margin:10px 0 24px}.website-domain-grid{display:grid;grid-template-columns:repeat(3,minmax(220px,1fr));gap:1px;background:var(--line);border:1px solid var(--line)}.website-domain-row{background:var(--bg-panel);padding:12px 14px;display:flex;justify-content:space-between;gap:12px}.website-domain-name{font-size:13px}.website-domain-value{font-family:ui-monospace,monospace;font-size:10px;color:var(--ok)}@media(max-width:900px){.website-hero-copy{top:18%;left:6vw;right:6vw}.website-h1{font-size:46px}.website-lede{font-size:21px}.website-graph{opacity:.32}.website-domain-grid{grid-template-columns:1fr}.website-graph-card{transform:scale(.8)}}
"""

WEBSITE_CSS += r"""
.website-page{width:100%;min-height:100vh;background:var(--bg);color:var(--ink);overflow:auto}.website-page-main{padding:116px 7vw 80px;max-width:1240px;margin:0 auto}.website-page-title{font-family:'Instrument Serif',Georgia,serif;font-size:48px;line-height:1.05;margin:0 0 14px}.website-page-lede{font-size:18px;line-height:1.55;color:var(--ink-soft);max-width:760px}.website-page-grid{display:grid;grid-template-columns:repeat(3,minmax(220px,1fr));gap:1px;background:var(--line);border:1px solid var(--line);margin-top:36px}.website-page-card{background:var(--bg-panel);padding:18px;min-height:150px}.website-page-card h2{font-family:'Instrument Serif',Georgia,serif;font-size:23px;margin:0 0 9px}.website-page-card p{color:var(--ink-soft);line-height:1.55;margin:0}.website-status{margin-top:14px;font-family:ui-monospace,monospace;font-size:9px;color:var(--warn);letter-spacing:.08em;text-transform:uppercase}.website-nav-anchor{color:var(--ink-soft);text-decoration:none;padding:7px 8px;font-size:11px}.website-nav-anchor:hover{color:var(--accent)}@media(max-width:900px){.website-page-grid{grid-template-columns:1fr}.website-page-title{font-size:38px}.website-nav-anchor{display:none}}
.website-wordmark{color:var(--ink);text-decoration:none}.website-graph{opacity:.58}.website-hero-copy{max-width:540px}@media(max-width:900px){.website-graph{opacity:.24}.website-graph-card{display:none}}
"""


def _el(store, tag, title, *, text=None, cls=None, attrs=None, style=None):
    return ui_element(store, tag, text=text, title=title, cls=cls,
                      attrs=attrs, style=style)


def _children(store, parent, *children):
    for order, child in enumerate(children):
        connect_ui_child(store, parent, child, order=order)


def _action(store, ui_id, operation, title):
    action = store.add('op', title, floor={'op': 'value', 'value': operation})
    connect_ui_action(store, ui_id, action)
    return action


def _website_nav(store, links):
    nav = _el(store, 'nav', 'Website navigation', cls='website-nav')
    wordmark = _el(store, 'a', 'Website wordmark', cls='website-wordmark',
                   attrs={'href': '/website'})
    word_arch = _el(store, 'span', 'Website Arch', text='Arch')
    word_hub = _el(store, 'strong', 'Website Hub', text='Hub')
    _children(store, wordmark, word_arch, word_hub)
    connect_ui_child(store, nav, wordmark, order=0)
    for order, (label, href) in enumerate(links, 1):
        link = _el(store, 'a', 'Website nav: ' + label, text=label,
                   cls='website-nav-anchor', attrs={'href': href})
        connect_ui_child(store, nav, link, order=order)
    spacer = _el(store, 'div', 'Website navigation spacer', cls='website-nav-spacer')
    connect_ui_child(store, nav, spacer, order=90)
    open_app = _el(store, 'a', 'Website open app', text='Open app',
                   cls='website-nav-link', attrs={'href': '/'})
    connect_ui_child(store, nav, open_app, order=100)
    return nav, open_app


def _content_page(store, route, title_text, lede_text, cards, links):
    route_param = store.add('param', 'page route',
                            floor={'op': 'value', 'value': route})
    title_param = store.add('param', 'page title',
                            floor={'op': 'value', 'value': title_text})
    lede_param = store.add('param', 'page lede',
                           floor={'op': 'value', 'value': lede_text})
    root = _el(store, 'div', 'Website page: ' + route, cls='website-page')
    nav, _open_app = _website_nav(store, links)
    main = _el(store, 'main', 'Website page content', cls='website-page-main')
    heading = _el(store, 'h1', 'Website page heading', cls='website-page-title')
    lede = _el(store, 'p', 'Website page introduction', cls='website-page-lede')
    connect_ui_binding(store, title_param, heading, 'text')
    connect_ui_binding(store, lede_param, lede, 'text')
    grid = _el(store, 'section', 'Website page grid', cls='website-page-grid')
    card_groups = []
    for order, card_data in enumerate(cards):
        card_title = store.add('param', 'card title',
                               floor={'op': 'value', 'value': card_data['title']})
        card_body = store.add('param', 'card body',
                              floor={'op': 'value', 'value': card_data['body']})
        card_status = store.add('param', 'card status',
                                floor={'op': 'value', 'value': card_data['status']})
        card = _el(store, 'article', 'Website content card', cls='website-page-card')
        card_h = _el(store, 'h2', 'Website content card title')
        card_p = _el(store, 'p', 'Website content card body')
        status = _el(store, 'div', 'Website content card status', cls='website-status')
        connect_ui_binding(store, card_title, card_h, 'text')
        connect_ui_binding(store, card_body, card_p, 'text')
        connect_ui_binding(store, card_status, status, 'text')
        _children(store, card, card_h, card_p, status)
        connect_ui_child(store, grid, card, order=order)
        card_groups.append(store.add(
            'group', 'Website content record',
            inner=[card_title, card_body, card_status, card],
            params={'title': card_title, 'body': card_body, 'status': card_status}))
    _children(store, main, heading, lede, grid)
    _children(store, root, nav, main)
    page = store.add(
        'group', 'Website route: ' + route,
        inner=[route_param, title_param, lede_param] + card_groups + [root],
        params={'route': route_param, 'title': title_param, 'lede': lede_param})
    return {'page': page, 'ui_root': root, 'route': route_param,
            'title': title_param, 'lede': lede_param, 'cards': card_groups}


def build_website(store, *, grand, mode_param, focus_param, app_id):
    links = [
        ('Features', '/website/features'), ('Pricing', '/website/pricing'),
        ('Changelog', '/website/changelog'), ('Security', '/website/security'),
        ('Community', '/website/community'), ('Sign in', '/website/signin'),
    ]
    root = _el(store, 'div', 'ArchHub public website', cls='website-root')
    nav, open_app = _website_nav(store, links)
    open_operation = [
        {'op': 'set', 'id': mode_param, 'path': ['body', 'floor', 'value'],
         'value': 'home'},
        {'op': 'set', 'id': focus_param, 'path': ['body', 'floor', 'value'],
         'value': grand['session']},
    ]
    _action(store, open_app, open_operation, 'Open application')

    hero = _el(store, 'section', 'Website hero', cls='website-hero')
    graph = _el(store, 'div', 'Website live graph', cls='website-graph')
    lines = _el(store, 'svg', 'Website relation projections', cls='website-graph-lines',
                attrs={'viewBox': '0 0 1200 700', 'preserveAspectRatio': 'none'})
    copy = _el(store, 'div', 'Website hero copy', cls='website-hero-copy')
    eyebrow = _el(store, 'div', 'Website eyebrow', text='ONE GRAPH / EVERY DOMAIN',
                  cls='website-eyebrow')
    h1 = _el(store, 'h1', 'Website title', cls='website-h1')
    h1_arch = _el(store, 'span', 'Website title Arch', text='Arch')
    h1_hub = _el(store, 'strong', 'Website title Hub', text='Hub')
    lede = _el(store, 'div', 'Website lede',
               text='The built environment, operated as a living graph.', cls='website-lede')
    body = _el(store, 'p', 'Website description',
               text='Design, data, geometry, governance, AI, delivery, and operations remain visible, parametric, and connected through one universal node language.',
               cls='website-body')
    cta = _el(store, 'button', 'Website primary action', text='Enter ArchHub',
              cls='website-cta', attrs={'type': 'button', 'data-navigate': '/'})
    _children(store, h1, h1_arch, h1_hub)
    _children(store, copy, eyebrow, h1, lede, body, cta)
    _action(store, cta, open_operation, 'Enter application')

    preview_domains = list(grand['domains'].items())[:6]
    coords = [(760, 92), (1010, 110), (850, 270), (1080, 330),
              (740, 500), (1010, 520)]
    preview_cards = {}
    for order, ((key, node_id), (x, y)) in enumerate(zip(preview_domains, coords)):
        card = _el(store, 'button', 'Website graph node: ' + key,
                   cls='website-graph-card',
                   attrs={'type': 'button', 'data-navigate': '/'},
                   style={'left': '%dpx' % x, 'top': '%dpx' % y})
        label = _el(store, 'div', 'Website graph kind', text='DOMAIN',
                    cls='website-graph-label')
        title = _el(store, 'div', 'Website graph title', text=key,
                    cls='website-graph-title')
        value = _el(store, 'div', 'Website graph value', cls='website-graph-value')
        connect_ui_binding(store, node_id, value, 'text', value_format='percent')
        _children(store, card, label, title, value)
        connect_ui_child(store, graph, card, order=order + 1)
        _action(store, card, [
            {'op': 'set', 'id': mode_param, 'path': ['body', 'floor', 'value'],
             'value': 'workspace'},
            {'op': 'set', 'id': focus_param, 'path': ['body', 'floor', 'value'],
             'value': node_id},
        ], 'Open domain in application')
        preview_cards[node_id] = card
    for order, relation_id in enumerate(grand['map_wires'][:6]):
        line = _el(store, 'line', 'Website cable projection', cls='website-graph-line',
                   attrs={'x1': 170 + order * 120, 'y1': 150 + (order % 2) * 280,
                          'x2': 930 - order * 100, 'y2': 340,
                          'data-relation': relation_id})
        connect_ui_child(store, lines, line, order=order)
    connect_ui_child(store, graph, lines, order=0)
    _children(store, hero, graph, copy)

    next_section = _el(store, 'section', 'Website domains section', cls='website-next')
    section_kicker = _el(store, 'div', 'Website section kicker', text='THE OPERATING GRAPH',
                         cls='website-section-kicker')
    section_title = _el(store, 'h2', 'Website section title', text='One graph. Every domain.',
                        cls='website-section-title')
    domain_grid = _el(store, 'div', 'Website domain grid', cls='website-domain-grid')
    for order, (key, node_id) in enumerate(grand['domains'].items()):
        row = _el(store, 'div', 'Website domain: ' + key, cls='website-domain-row')
        name = _el(store, 'span', 'Website domain name', text=key, cls='website-domain-name')
        value = _el(store, 'span', 'Website domain value', cls='website-domain-value')
        connect_ui_binding(store, node_id, value, 'text', value_format='percent')
        _children(store, row, name, value)
        connect_ui_child(store, domain_grid, row, order=order)
    _children(store, next_section, section_kicker, section_title, domain_grid)
    _children(store, root, nav, hero, next_section)

    route_specs = {
        '/website/features': (
            'Everything is a node.',
            'The application, data, logic, relations, parameters, hosts, and governance remain inspectable parts of one operating graph.',
            [
                {'title': 'Universal nodes', 'body': 'Values, operations, groups, parameters, interfaces, proposals, history, and secrets references compose without feature-specific node kinds.', 'status': 'RUNNING IN THE NODE RUNTIME'},
                {'title': 'Relations carry behavior', 'body': 'Endpoints, payload descriptors, guards, transforms, presentation, encoding, and encryption are editable relation nodes.', 'status': 'AUTHORITATIVE WIRES'},
                {'title': 'AEC without a ceiling', 'body': 'Geometry, BIM, documents, images, agents, and future domains use typed payload envelopes rather than a closed product catalogue.', 'status': 'CONNECTOR COVERAGE IN PROGRESS'},
            ]),
        '/website/pricing': (
            'Pricing', 'Commercial plans are published only from the governed monetization graph.',
            [
                {'title': 'Solo', 'body': 'One professional workspace with bring-your-own AI keys.', 'status': 'PLAN GRAPH BUILT / CHECKOUT FROZEN'},
                {'title': 'Studio', 'body': 'Shared operating graphs, governance, and collaboration for design teams.', 'status': 'PLAN GRAPH BUILT / CHECKOUT FROZEN'},
                {'title': 'Firm', 'body': 'Organisation controls, private deployment, identity, and coordinated agent capacity.', 'status': 'PLAN GRAPH BUILT / CHECKOUT FROZEN'},
            ]),
        '/website/changelog': (
            'Changelog', 'Release evidence will be generated from signed product revisions and their completed courts.',
            [{'title': 'Node-native runtime', 'body': 'Universal kernel, parametric Grand Map, desktop host, Brain governance, connectors, sessions, model routing, and orchestration are running locally.', 'status': 'WIP / NOT A SIGNED RELEASE'}]),
        '/website/security': (
            'Security and governance', 'Privacy boundaries and effects are enforced as executable graph constraints.',
            [
                {'title': 'Privacy tiers', 'body': 'Public, internal, confidential, and secret data have explicit storage and publication boundaries.', 'status': 'T0-T3 POLICY ACTIVE'},
                {'title': 'Frozen effects', 'body': 'External writes remain inert until an audited gate explicitly permits execution.', 'status': 'DENY BY DEFAULT'},
                {'title': 'Secret references', 'body': 'Credentials remain outside the graph; nodes carry references to protected stores only.', 'status': 'RAW SECRETS REJECTED'},
            ]),
        '/website/community': (
            'Community', 'Membership, consent, moderation, provenance, reputation, marketplace, and federation are governed by the Community node graph.',
            [{'title': 'Community graph', 'body': 'The authority is built. External federation and public contributor claims remain frozen until hosts, evidence, and approval are connected.', 'status': 'GRAPH BUILT / NETWORK NOT CONNECTED'}]),
        '/website/signin': (
            'Sign in', 'The Users and Cloud authentication graphs are built; credential handling remains outside the graph.',
            [{'title': 'Account gateway', 'body': 'The gateway will accept credentials only after an external identity provider and timestamped authorization evidence are connected.', 'status': 'AUTHORITY BUILT / PROVIDER NOT CONNECTED'}]),
    }
    route_pages = {
        route: _content_page(store, route, title, lede, cards, links)
        for route, (title, lede, cards) in route_specs.items()
    }

    root_param = store.add('param', 'website root',
                           floor={'op': 'reference', 'target': root})
    route_param = store.add('param', 'website route',
                            floor={'op': 'value', 'value': '/website'})
    privacy_param = store.add('param', 'website graph privacy tier',
                              floor={'op': 'value', 'value': 'T1 INTERNAL'})
    publication_param = store.add('param', 'website publication tier',
                                  floor={'op': 'value', 'value': 'T0 PUBLIC'})
    route_params = {'route:' + route: store.add(
        'param', 'website route root: ' + route,
        floor={'op': 'reference', 'target': page['ui_root']})
        for route, page in route_pages.items()}
    website = store.add('session', 'ArchHub Website',
                        inner=[root] + [page['page'] for page in route_pages.values()],
                        params={'ui_root': root_param, 'route': route_param,
                                'privacy_tier': privacy_param,
                                'publication_tier': publication_param,
                                **route_params})
    route_relations = {}
    for route, page in route_pages.items():
        route_relations[route] = store.relation([
            {'role': 'source', 'direction': 'out', 'node_id': page['page'],
             'port_id': 'page', 'cardinality': 'one'},
            {'role': 'target', 'direction': 'in', 'node_id': website,
             'port_id': route, 'cardinality': 'one'},
        ], title='Website route membership')
    app_relation = store.relation([
        {'role': 'source', 'direction': 'out', 'node_id': app_id,
         'port_id': 'product', 'cardinality': 'one'},
        {'role': 'target', 'direction': 'in', 'node_id': website,
         'port_id': 'public_surface', 'cardinality': 'one'},
    ], title='Application publishes website')
    routes = {'/website': root}
    routes.update({route: page['ui_root'] for route, page in route_pages.items()})
    return {'session': website, 'ui_root': root, 'routes': routes,
            'route_pages': route_pages, 'route_relations': route_relations,
            'preview_cards': preview_cards, 'open_app': open_app, 'cta': cta,
            'app_relation': app_relation}
