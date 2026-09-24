"""A confirmed cockpit offer edit reaches the one offer record and is republished at once."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from nodelang.cell_accounts import (
    apply_offer_command, declare_offer, ensure_accounts, parse_offer_command,
    published_offer, read_offer,
)
from nodelang.cloud_relay import CloudRelay
from nodelang.universal_cell import CellStore

FOUNDER = "founder@example.test"
MAP_SCRIPT = 'window.ATLAS_MAP = {"domains":[],"nodes":[],"wires":[]}; window.ATLAS_LIVE = true;'


class _Cloud(BaseHTTPRequestHandler):
    tasks, results, maps = [], [], []

    def log_message(self, *_a):
        pass

    def _json(self, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if self.path.endswith("/agent-tasks/claim"):
            return self._json({"ok": True, "task": _Cloud.tasks.pop(0) if _Cloud.tasks else None})
        if self.path.endswith("/result"):
            _Cloud.results.append(json.loads(raw))
            return self._json({"ok": True})
        if self.path == "/founder/map-state":
            _Cloud.maps.append(json.loads(raw))
            return self._json({"ok": True})
        return self._json({"ok": False})


def _run(directive, account, kind="app-execute"):
    store = CellStore()
    ensure_accounts(store, founder_email=FOUNDER)
    declare_offer(store, founder_account=FOUNDER)
    _Cloud.tasks[:] = [{"id": "t1", "kind": kind, "directive": directive}]
    _Cloud.results[:] = []
    _Cloud.maps[:] = []
    executed = []

    def offer_command(utterance, execute):
        if parse_offer_command(utterance) is None:
            return None
        return apply_offer_command(store, utterance, founder_account=account, execute=execute)

    server = HTTPServer(("127.0.0.1", 0), _Cloud)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    relay = CloudRelay(
        base_url="http://127.0.0.1:%d" % server.server_port, token="t",
        respond=lambda utterance: {},
        execute=lambda utterance: executed.append(utterance) or {"kind": "done", "summary": "done"},
        map_script=lambda: MAP_SCRIPT, hosts=lambda: [],
        offer=lambda: published_offer(store.snapshot()), offer_command=offer_command,
    )
    try:
        out = relay.poll_once()
    finally:
        server.shutdown()
    return store, out, executed


def test_the_founder_edit_changes_the_record_and_republishes_it():
    store, out, executed = _run('set offer public-label to "Free while in beta"', FOUNDER)
    assert out["ok"] is True and "Free while in beta" in out["result"]
    assert executed == [], "the offer command never reaches BABOOM"
    assert read_offer(store.snapshot())["public-label"] == "Free while in beta"
    assert _Cloud.maps and _Cloud.maps[-1]["offer"]["public_label"] == "Free while in beta"


def test_a_non_owner_edit_is_refused_and_nothing_is_republished():
    store, out, executed = _run('set offer public-label to "Free while in beta"', "colleague@example.com")
    assert out["ok"] is False and "only a founder" in out["result"]
    assert _Cloud.results[-1]["ok"] is False
    assert read_offer(store.snapshot())["public-label"] == "Free during beta"
    assert _Cloud.maps == [] and executed == []


def test_a_price_in_the_label_is_refused():
    store, out, executed = _run('set offer public-label to "$19/mo"', FOUNDER)
    assert out["ok"] is False and "price" in out["result"]
    assert read_offer(store.snapshot())["public-label"] == "Free during beta"
    assert _Cloud.maps == [] and executed == []


def test_other_words_still_go_to_baboom():
    _store, out, executed = _run("tell codex: hi", FOUNDER)
    assert executed == ["tell codex: hi"] and out["ok"] is True