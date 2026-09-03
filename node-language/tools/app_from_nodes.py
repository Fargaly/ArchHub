"""THE ARCHHUB APP, BUILT FROM NODES (SPEC section 10 self-hosting, section 11
the Watcher). This is not a picture of the app and not a dashboard about the
project: it is a real ArchHub surface whose every element is a ui NODE in the
ONE table, rendered from the graph, with LIVE data flowing through host + probe
nodes (real Revit model, real cloud health), and editable in place -- edit a
node, the app changes (the Watcher). No JSX. The page IS the nodes.
"""
import sys, os, json, glob, threading, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from nodelang.core import Store, validate_store
from nodelang.laws_surface import ui_element, render

REVIT = 48886                          # a live, responsive Revit 2023 session
SESS_DIR = os.path.join(os.environ.get('LOCALAPPDATA', ''), 'ArchHub', 'sessions')

# ArchHub's real look — the app's stylesheet (its tokens), served with the nodes.
CSS = """
:root{--bg:#0e0e11;--panel:#15151a;--soft2:#1c1c23;--line:#26262e;--ink:#ece8e0;
--soft:#9b938a;--muted:#5e574f;--acc:#d97757;--grn:#7ec18e;}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font-family:Inter,system-ui,sans-serif;height:100vh;overflow:hidden}
.app{display:flex;flex-direction:column;height:100vh}
.top{display:flex;align-items:center;gap:14px;padding:14px 20px}
.logo{font-family:'Instrument Serif',Georgia,serif;font-size:26px;letter-spacing:.5px}
.logo .h{color:var(--acc)}
.pill{background:var(--soft2);border:1px solid var(--line);border-radius:9px;
padding:8px 13px;font-size:12px;color:var(--soft)}
.pill .a{color:var(--acc);font-weight:700}
.chip{background:#171a17;border:1px solid #2c3a2c;border-radius:8px;padding:7px 11px;
font-size:11px;color:var(--grn)}
.chip.warn{background:#1c1c23;border-color:var(--line);color:var(--soft)}
.spacer{flex:1}
.sesshdr{display:flex;align-items:center;gap:10px;padding:6px 22px 12px;font-size:13px;color:var(--soft)}
.sesshdr .n{font-family:'Instrument Serif',serif;font-size:22px;color:var(--ink)}
.newc{margin-left:auto;background:var(--acc);color:#1a0e08;border-radius:8px;
padding:7px 13px;font-size:12px;font-weight:700}
.grid{flex:1;overflow:auto;padding:4px 22px 16px;display:grid;
grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:12px;align-content:start}
.card{background:var(--panel);border:1px solid var(--line);border-radius:11px;padding:13px 15px;min-height:82px}
.card:hover{border-color:var(--acc)}
.card .st{font-size:9px;letter-spacing:1px;color:var(--muted)}
.card .ti{font-size:12px;font-weight:700;margin:5px 0 4px}
.card .sn{font-size:11px;color:var(--soft)}
.composer{margin:0 22px 14px;background:var(--panel);border:1px solid var(--acc);
border-radius:12px;padding:13px 16px;font-size:13px;color:var(--soft)}
.statusbar{display:flex;gap:18px;padding:9px 22px;border-top:1px solid var(--line);
font-size:11px;color:var(--muted);background:#0e0e11}
.statusbar .g{color:var(--grn)}
.statusbar .v{color:var(--ink)}
[data-node]{}
"""


def read_session_count():
    try:
        return len(glob.glob(os.path.join(SESS_DIR, '*.json')))
    except Exception:
        return 0


def build():
    s = Store()
    # ---- LIVE DATA NODES: real values flow into the UI through these --------
    sess_n = s.add('value', 'session-count',
                   floor={'op': 'value', 'value': read_session_count()})
    walls = s.add('op', 'revit-walls',
                  floor={'op': 'host', 'port': REVIT,
                         'code': 'var c=new FilteredElementCollector(Doc)'
                                 '.OfCategory(BuiltInCategory.OST_Walls)'
                                 '.WhereElementIsNotElementType().ToElementIds().Count;'
                                 'result=c;'})
    model = s.add('op', 'revit-model',
                  floor={'op': 'host', 'port': REVIT, 'code': 'result=Doc.Title;'})
    cloud = s.add('op', 'cloud',
                  floor={'op': 'probe', 'kind': 'http_ok',
                         'spec': {'url': 'https://archhub-cloud.fly.dev/healthz',
                                  'status': 200}})

    def card(st, ti, sn):
        return ui_element(s, 'div', cls='card', children=[
            ui_element(s, 'div', text=st, cls='st'),
            ui_element(s, 'div', text=ti, cls='ti'),
            ui_element(s, 'div', text=sn, cls='sn')])

    top = ui_element(s, 'div', cls='top', children=[
        ui_element(s, 'div', cls='logo', children=[
            ui_element(s, 'span', text='ARCH'),
            ui_element(s, 'span', text='HUB', cls='h')]),
        ui_element(s, 'div', cls='pill', children=[
            ui_element(s, 'span', text='Auto (router picks)')]),
        ui_element(s, 'div', cls='chip', text='brain · ready'),
        ui_element(s, 'div', cls='chip', text='Signed in'),
        ui_element(s, 'div', cls='chip warn', children=[
            ui_element(s, 'span', text='live model: '),
            ui_element(s, 'span', bind=model)]),
    ])
    hdr = ui_element(s, 'div', cls='sesshdr', children=[
        ui_element(s, 'span', text='Sessions', cls='n'),
        ui_element(s, 'span', bind=sess_n),
        ui_element(s, 'span', text='· CLICK TO OPEN'),
        ui_element(s, 'div', text='+ new canvas', cls='newc')])
    grid = ui_element(s, 'div', cls='grid', children=[
        card('IDLE', 'Sample facade assembly', 'parametric edge detail complete'),
        card('IDLE', 'Sample coordination audit', '408 synthetic rows reconciled'),
        card('IDLE', 'Sample residential model', 'curtain-wall sheets fixed'),
        card('LIVE', 'BA-649 quantities', 'driven from nodes below')])
    composer = ui_element(s, 'div', cls='composer',
                          text='Start a new session…  (Enter to send · Shift+Enter = new line)')
    statusbar = ui_element(s, 'div', cls='statusbar', children=[
        ui_element(s, 'span', cls='g', text='● server'),
        ui_element(s, 'span', children=[
            ui_element(s, 'span', text='revit walls: '),
            ui_element(s, 'span', bind=walls, cls='v')]),
        ui_element(s, 'span', children=[
            ui_element(s, 'span', text='sessions: '),
            ui_element(s, 'span', bind=sess_n, cls='v')]),
        ui_element(s, 'span', children=[
            ui_element(s, 'span', text='cloud healthz ok: '),
            ui_element(s, 'span', bind=cloud, cls='v')]),
        ui_element(s, 'span', cls='g', text='● healthy')])
    root = ui_element(s, 'div', cls='app', title='archhub-home',
                      children=[top, hdr, grid, composer, statusbar])
    validate_store(s)
    return s, root


def serve():
    s, root = build()
    page = lambda: ('<!doctype html><meta charset=utf-8>'
                    '<title>ArchHub — built from nodes</title><style>%s</style>%s'
                    % (CSS, render(s, root)))

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_GET(self):
            b = page().encode('utf-8')
            self.send_response(200); self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(b))); self.end_headers(); self.wfile.write(b)
        def do_POST(self):
            n = int(self.headers.get('Content-Length') or 0)
            p = json.loads(self.rfile.read(n).decode('utf-8'))
            s.apply_op({'op': 'set', 'id': p['node_id'],
                        'path': ['body', 'floor', 'value'], 'value': p['value'], 'actor': 'watcher'})
            self.send_response(200); self.end_headers(); self.wfile.write(b'{"ok":true}')

    httpd = ThreadingHTTPServer(('127.0.0.1', 8479), H)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return s, root, httpd


if __name__ == '__main__':
    s, root, httpd = serve()
    print('ArchHub home built from', len(s.nodes), 'nodes.  http://127.0.0.1:8479')
    print('every element is a ui node in the one table; walls/model/cloud are live.')
    webbrowser.open('http://127.0.0.1:8479')
    import time
    try:
        while True: time.sleep(3600)
    except KeyboardInterrupt:
        httpd.shutdown()
