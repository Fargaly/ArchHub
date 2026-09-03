"""LIVE watcher proof: build a node-UI, serve it, edit a NODE over real HTTP,
watch the served page change — SPEC §10/§11/§5, on the real one-table engine.
No mocks: real TCP server, real HTTP GET/POST, real apply_op + history."""
import sys, os, json, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from nodelang.core import Store
from nodelang.laws_surface import ui_element, render
from nodelang.serve import NodeServer

s = Store()
# floor value nodes + a live sum — same one table
a = s.add('value', 'a', floor={'op': 'value', 'value': 800})
b = s.add('value', 'b', floor={'op': 'value', 'value': 50})
total = s.add('op', 'a+b', floor={'op': 'math', 'fn': '+'})
s.wire(a, total); s.wire(b, total)
# UI nodes (kind='ui') bound to the running total
h1 = ui_element(s, 'h1', text='Total: ')
span = ui_element(s, 'span', bind=total)
root = ui_element(s, 'div', children=[h1, span], title='page')

srv = NodeServer(s, root).start()
try:
    def page():
        return urllib.request.urlopen(srv.url + '/', timeout=10).read().decode()
    before = page()
    print('SERVED URL:', srv.url)
    print('BEFORE:', before)
    req = urllib.request.Request(srv.url + '/edit', method='POST',
        data=json.dumps({'node_id': a, 'param': None, 'value': 4000}).encode(),
        headers={'Content-Type': 'application/json'})
    print('EDIT RESP:', json.loads(urllib.request.urlopen(req, timeout=10).read()))
    after = page()
    print('AFTER :', after)
    hist = [n for n in s.nodes.values() if n['kind'] == 'history']
    print('HISTORY NODES:', len(hist))
    assert '>850</span>' in before, before
    assert '>4050</span>' in after, after
    assert len(hist) >= 1
    print('LIVE WATCHER OK: served page 850 -> 4050 because a NODE changed, over HTTP, with history appended.')
finally:
    srv.stop()
