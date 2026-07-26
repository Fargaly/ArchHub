# -*- coding: utf-8 -*-
"""LEAF: the USER (browser UI) and the AI both drive the SAME graph over HTTP.

This REUSES the existing engine + live server unchanged:
  - node_lang.Graph  : the running, incremental, memoized graph engine.
  - server.py        : the ONE Graph in one process, GET /graph + POST /add /set /wire /group /del,
                       serving index.html (the browser UI is a VIEW that polls /graph).

The browser UI (index.html) reads GET /graph and writes the SAME POST endpoints this
script writes. So "the UI" and "the AI" are the same wire into the same in-process Graph.
This leaf plays BOTH roles over HTTP and proves the one graph re-runs for both:

  1) UI-side read   : GET /graph -> n_sum value (what the browser renders) = 8.
  2) AI-side write  : POST /set {n_a.value=99} -> the one graph re-runs -> n_sum = 102.
                      (a value the browser's next /graph poll would render — same graph.)
  3) AI-side add    : POST /add {const 7} -> a brand-new AI node, visible in shared /graph.
  4) AI-side group  : POST /group {n_a,n_b} -> a 'group' node (grouping-runs-as-node),
                      visible in the same shared state the UI renders.

Run:  python leaf_both_drive_one_graph_over_http.py [PORT]
It launches server.py itself on the given port, drives it, prints REAL output, and exits.
You can also point it at an already-running server with --port-only (no launch).
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))


def _http(base, path, body=None):
    url = base + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    with urllib.request.urlopen(url, data, timeout=5) as r:
        return json.load(r)


def _wait_up(base, tries=40):
    for _ in range(tries):
        try:
            _http(base, "/graph")
            return True
        except Exception:
            time.sleep(0.25)
    return False


def n_sum_value(base):
    """What the UI renders for n_sum: read straight from the shared /graph state."""
    st = _http(base, "/graph")
    return [n["value"] for n in st["nodes"] if n["id"] == "n_sum"][0]


def run(port, launch=True):
    base = "http://127.0.0.1:%d" % port
    proc = None
    try:
        if launch:
            env = dict(os.environ, PYTHONIOENCODING="utf-8")
            proc = subprocess.Popen(
                [sys.executable, os.path.join(HERE, "server.py"), str(port)],
                cwd=HERE, env=env,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        if not _wait_up(base):
            print("SERVER_NOT_UP on", base)
            return 1

        # 1) UI-side READ of the one graph (the seed program: const 5 + const 3 -> sum)
        v0 = n_sum_value(base)

        # 2) AI-side WRITE -> the SAME graph re-runs (99 + 3 = 102)
        _http(base, "/set", {"id": "n_a", "key": "value", "val": 99})
        v1 = n_sum_value(base)
        set_changed = (v1 != v0)

        # 3) AI-side ADD -> a new node appears in the shared state the UI renders
        ai_id = _http(base, "/add", {"kind": "const", "params": {"value": 7}})["id"]

        # 4) AI-side GROUP -> grouping-runs-as-node, visible in the same state
        _http(base, "/group", {"ids": ["n_a", "n_b"]})

        st = _http(base, "/graph")
        ids = [n["id"] for n in st["nodes"]]
        groups = [n for n in st["nodes"] if n["kind"] == "group"]
        ai_present = ai_id in ids
        group_present = bool(groups)

        ok = (v0 == 8 and v1 == 102 and ai_present and group_present)

        print("SET_CHANGED", set_changed, "before", v0, "after", v1)
        print("AI_NODE_PRESENT", ai_present, "id", ai_id)
        print("GROUP_PRESENT", group_present, "group_id", (groups[0]["id"] if groups else None))
        print("BOTH_DRIVE_OK n_sum", v0, "->", v1,
              "ai_node", ai_present, "group", group_present)
        return 0 if ok else 1
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()


if __name__ == "__main__":
    args = [a for a in sys.argv[1:]]
    launch = "--port-only" not in args
    args = [a for a in args if a != "--port-only"]
    port = int(args[0]) if args else 8779
    sys.exit(run(port, launch=launch))
