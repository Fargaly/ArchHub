"""THE APP, SELF-HOSTED FROM THE FULL GRAND MAP (SPEC section 10 UI-from-nodes,
section 11 live properties, section 14 the map evolves into the language IN PLACE).

Not a hand-built ui subset anymore. This imports the WHOLE grand map through the
ONE authority -- `nodelang.map_import.import_grand_map` (282 value nodes + 855
param NODES + 309 wire NODES + 15 domain groups + one session, validate_store
True) -- and then builds the app's UI as `kind='ui'` nodes IN THE SAME one table,
BOUND to those imported nodes:

  * the theme (accent) IS the `ui_design_tokens.accent` PARAM NODE -- edit it and
    the whole app recolors through the properties panel.
  * every domain renders as a section; every map node renders as a card whose
    STATUS is bound to its value node (live from the graph) and whose PARAMS are
    bound to its param nodes (the 855, shown as real rows).

`render(store, root)` is a pure walk of the one table -> HTML. There is no
template and no second source: the page IS the nodes, and the nodes ARE the map.
Edit any node through POST /edit -> the page recomputes (dirty-propagation).
"""
import sys, os, re, json, threading, webbrowser
import html as _html
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from nodelang.core import Store, validate_store
from nodelang.laws_surface import ui_element, render
from nodelang.map_import import import_grand_map, load_map

REVIT = 48885


def build():
    s = Store()
    reg = import_grand_map(s)                 # THE authority: full parametric+wired map
    data = load_map()
    P, V = reg['params'], reg['values']
    meta = {n['id']: n for d in data for n in d['nodes']}   # static labels (title/cat)

    # -- theme: the accent IS a real param node of ui_design_tokens -----------
    accent_pid = P.get('ui_design_tokens', {}).get('accent')
    if accent_pid is None:                    # fallback: mint one so the app still themes
        accent_pid = s.add('param', 'accent', floor={'op': 'value', 'value': '#d97757'})

    # -- one live host stat, wired as a node in the SAME table ----------------
    walls = s.add('op', 'revit-walls',
                  floor={'op': 'host', 'port': REVIT,
                         'code': 'result=new FilteredElementCollector(Doc)'
                                 '.OfCategory(BuiltInCategory.OST_Walls)'
                                 '.WhereElementIsNotElementType().ToElementIds().Count;'})

    def properties_panel(map_id):
        snap = watcher_snapshot(s, {'reg': reg, 'meta': meta}, map_id)
        rows = [ui_element(s, 'div', cls='wmeta', children=[
            ui_element(s, 'span', text='status node %s: ' % snap['value_node']['id']),
            ui_element(s, 'span', bind=snap['value_node']['id'])])]
        for name, pid in P.get(map_id, {}).items():
            rows.append(ui_element(s, 'form', cls='properties-form wrow',
                                   attrs={'data-param-node': pid},
                                   children=[
                ui_element(s, 'input', attrs={'type': 'hidden',
                                              'name': 'node_id',
                                              'value': pid}),
                ui_element(s, 'label', text='%s - param - %s' % (name, pid)),
                ui_element(s, 'input',
                           attrs={'name': 'value', 'value': {'$bind': pid}}),
                ui_element(s, 'button', text='apply',
                           attrs={'type': 'submit'})]))
        return ui_element(s, 'aside', cls='properties',
                          attrs={'data-panel-node': map_id},
                          children=[
            ui_element(s, 'h2', text=snap['title']),
            ui_element(s, 'div', cls='wid',
                       text='%s - %s - history %s' % (
                           snap['map_id'], snap['cat'], snap['history_count'])),
        ] + rows)

    # -- a map node -> its clickable surface (status/params bound live) -------
    def card(map_id):
        m = meta[map_id]
        kids = [ui_element(s, 'div', cls='nk', text=str(m.get('cat', ''))),
                ui_element(s, 'div', cls='nt', text=str(m.get('title', map_id))),
                ui_element(s, 'span', cls='nstat', bind=V[map_id])]   # LIVE status
        for k, pid in P.get(map_id, {}).items():
            kids.append(ui_element(s, 'div', cls='prow', children=[
                ui_element(s, 'span', cls='pk', text='%s: ' % k),
                ui_element(s, 'span', cls='pv', bind=pid)]))          # LIVE param value
        return ui_element(s, 'a', cls='ncard', title=map_id, children=kids,
                          attrs={'href': '/?watch=' + map_id})

    # -- the body: 15 domain sections over the whole map ---------------------
    sections = []
    for d in data:
        cards = [card(n['id']) for n in d['nodes']]
        sections.append(ui_element(s, 'div', cls='dom', children=[
            ui_element(s, 'div', cls='domh',
                       text='%s  ·  %d nodes' % (d['title'], len(d['nodes']))),
            ui_element(s, 'div', cls='cards', children=cards)]))

    rail = ui_element(s, 'div', cls='rail', children=[
        ui_element(s, 'div', cls='rlogo', children=[ui_element(s, 'span', text='A')]),
        ui_element(s, 'div', cls='ri', text='home'),
        ui_element(s, 'div', cls='ri', text='map'),
        ui_element(s, 'div', cls='ri', text='brain')])
    top = ui_element(s, 'div', cls='top', children=[
        ui_element(s, 'div', cls='brand', children=[
            ui_element(s, 'span', text='ARCH'),
            ui_element(s, 'span', text='HUB', cls='hb')]),
        ui_element(s, 'div', cls='pill', text='app self-hosted from the grand map'),
        ui_element(s, 'div', cls='chip', children=[
            ui_element(s, 'span', text='live revit walls: '),
            ui_element(s, 'span', bind=walls)])])
    body = ui_element(s, 'div', cls='body', children=sections)
    main = ui_element(s, 'div', cls='main', children=[top, body])
    root = ui_element(s, 'div', cls='app', title='nl_ui_app_is_graph',
                      children=[rail, main])
    panels = {map_id: properties_panel(map_id) for map_id in V}
    validate_store(s)
    return s, root, {'accent': accent_pid, 'reg': reg, 'meta': meta,
                     'panels': panels}


CSS = """*{{box-sizing:border-box}}body{{margin:0;background:#0e0e11;color:#ece8e0;
font-family:Inter,system-ui,sans-serif;height:100vh;overflow:hidden}}
.app{{display:flex;height:100vh}}
.rail{{width:56px;background:#101015;border-right:1px solid #26262e;display:flex;
flex-direction:column;align-items:center;gap:15px;padding:15px 0}}
.rlogo span{{display:flex;width:30px;height:30px;align-items:center;justify-content:center;
background:{acc};color:#1a0e08;border-radius:8px;font-weight:800;font-family:'Instrument Serif',serif}}
.rail .ri{{font-size:9px;color:#5e574f;letter-spacing:.5px}}
.main{{flex:1;display:flex;flex-direction:column;overflow:hidden;padding-right:360px}}
.top{{display:flex;align-items:center;gap:14px;padding:15px 22px;border-bottom:1px solid #1c1c23}}
.brand{{font-family:'Instrument Serif',Georgia,serif;font-size:24px}}
.brand .hb{{color:{acc}}}
.pill{{background:#1c1c23;border:1px solid #26262e;border-radius:9px;padding:7px 12px;font-size:12px;color:#9b938a}}
.chip{{margin-left:auto;background:#171a17;border:1px solid #2c3a2c;border-radius:9px;
padding:7px 12px;font-size:12px;color:#7ec18e}}
.body{{flex:1;overflow:auto;padding:6px 22px 30px}}
.dom{{margin-top:18px}}
.domh{{font-family:'Instrument Serif',serif;font-size:19px;color:#ece8e0;
padding:6px 0 10px;border-bottom:1px solid #1c1c23;position:sticky;top:0;background:#0e0e11}}
.cards{{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:10px;padding-top:12px}}
.ncard{{display:block;text-decoration:none;color:inherit;background:#15151a;
border:1px solid #26262e;border-radius:11px;padding:12px 13px}}
.ncard:hover{{border-color:{acc}}}
.ncard.selected{{border-color:{acc};box-shadow:inset 0 0 0 1px {acc}}}
.nk{{font-size:8px;letter-spacing:1px;color:#5e574f;text-transform:uppercase}}
.nt{{font-size:12px;font-weight:700;color:#ece8e0;margin:4px 0 5px}}
.nstat{{display:inline-block;font-size:10px;color:{acc};border:1px solid #2c2c34;
border-radius:5px;padding:1px 7px;text-transform:uppercase;letter-spacing:.5px}}
.prow{{display:flex;gap:4px;font-size:10px;margin-top:5px;color:#7d766c}}
.prow .pk{{color:#5e574f}}
.prow .pv{{color:#c8c1b6}}
.properties{{position:fixed;right:0;top:0;width:360px;height:100vh;overflow:auto;
background:#121217;border-left:1px solid #2c2c34;padding:18px 16px;z-index:10}}
.properties h2{{font-size:14px;margin:0 0 4px;color:#ece8e0}}
.properties .wid{{font-size:10px;color:#696158;word-break:break-all;margin-bottom:10px}}
.properties .wrow{{border-top:1px solid #22222a;padding:9px 0}}
.properties label{{display:block;font-size:10px;color:#8f877e;margin-bottom:4px}}
.properties input{{width:100%;background:#0e0e11;color:#ece8e0;border:1px solid #2c2c34;
border-radius:7px;padding:7px 8px;font-size:12px}}
.properties button{{margin-top:6px;background:{acc};border:0;border-radius:7px;color:#1a0e08;
font-weight:800;font-size:11px;padding:7px 9px;cursor:pointer}}
.properties .wmeta{{font-size:11px;color:#b8afa5;margin-top:8px}}
[data-node]{{}}"""


WATCHER_JS = """
<script>
document.addEventListener('submit', async (event) => {
  const form = event.target.closest('.properties-form');
  if (!form) return;
  event.preventDefault();
  const nodeId = form.querySelector('[name=node_id]').value;
  const value = form.querySelector('[name=value]').value;
  await fetch('/edit', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({node_id: nodeId, value})
  });
  location.reload();
});
</script>
"""


def _acc_hex(raw):
    m = re.search(r'#[0-9a-fA-F]{6}', str(raw))
    return m.group(0) if m else '#d97757'


def _history_count(store):
    return sum(1 for n in store.nodes.values() if n['kind'] == 'history')


def watcher_snapshot(store, ids, map_id):
    reg = ids['reg']
    meta = ids.get('meta', {})
    if map_id not in reg['values']:
        raise KeyError('unknown map node %r' % map_id)
    value_id = reg['values'][map_id]
    value_node = store.nodes[value_id]
    params = {}
    for name, pid in reg['params'].get(map_id, {}).items():
        pnode = store.nodes[pid]
        params[name] = {
            'id': pid,
            'kind': pnode['kind'],
            'value': store.pull(pid),
        }
    return {
        'map_id': map_id,
        'title': meta.get(map_id, {}).get('title', map_id),
        'cat': meta.get(map_id, {}).get('cat', ''),
        'history_count': _history_count(store),
        'value_node': {
            'id': value_id,
            'kind': value_node['kind'],
            'value': store.pull(value_id),
        },
        'params': params,
    }


def apply_watcher_edit(store, node_id, value):
    if node_id not in store.nodes:
        raise KeyError('unknown node %r' % node_id)
    if store.nodes[node_id]['kind'] not in ('param', 'value'):
        raise ValueError('watcher edits param/value nodes only, got %r'
                         % store.nodes[node_id]['kind'])
    store.apply_op({'op': 'set', 'id': node_id,
                    'path': ['body', 'floor', 'value'],
                    'value': value, 'actor': 'watcher'})
    validate_store(store)
    return {'ok': True, 'node_id': node_id, 'value': store.pull(node_id),
            'history_count': _history_count(store)}


def _select_card(html, watch):
    if not watch:
        return html
    escaped = _html.escape(str(watch), quote=True)
    target = 'class="ncard" href="/?watch=%s"' % escaped
    selected = 'class="ncard selected" href="/?watch=%s"' % escaped
    return html.replace(target, selected, 1)


def _properties_html(store, ids, watch):
    panel = ids.get('panels', {}).get(watch)
    return render(store, panel) if panel else ''


def render_page(store, root, ids, watch=None):
    acc = _acc_hex(store.pull(ids['accent']))   # the app's color IS the tokens param node
    body = _select_card(render(store, root), watch)
    return ('<!doctype html><meta charset=utf-8>'
            '<title>ArchHub self-hosted from the grand map</title>'
            '<style>%s</style>%s%s%s' % (
                CSS.format(acc=acc), body,
                _properties_html(store, ids, watch), WATCHER_JS))


def serve(open_browser=True):
    s, root, ids = build()

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            query = urllib.parse.parse_qs(parsed.query)
            watch = (query.get('watch') or [None])[0]
            b = render_page(s, root, ids, watch=watch).encode('utf-8')
            self.send_response(200); self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(b))); self.end_headers(); self.wfile.write(b)
        def do_POST(self):
            if urllib.parse.urlparse(self.path).path != '/edit':
                self.send_response(404); self.end_headers(); return
            n = int(self.headers.get('Content-Length') or 0)
            p = json.loads(self.rfile.read(n).decode('utf-8'))
            apply_watcher_edit(s, p['node_id'], p['value'])
            self.send_response(200); self.end_headers(); self.wfile.write(b'{"ok":true}')

    httpd = ThreadingHTTPServer(('127.0.0.1', 8481), H)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return s, root, ids, httpd


if __name__ == '__main__':
    s, root, ids, httpd = serve()
    print('app self-hosted from the FULL grand map: %d one-table nodes. '
          'http://127.0.0.1:8481' % len(s.nodes))
    print('accent param node =', ids['accent'], '(edit it -> whole app recolors)')
    webbrowser.open('http://127.0.0.1:8481')
    import time
    try:
        while True: time.sleep(3600)
    except KeyboardInterrupt:
        httpd.shutdown()
