"""node_lang — a REAL, running node-language interpreter (prototype, not the public live model).

The agreed laws, made executable:
  - Everything is a node. A node's value is computed from the nodes feeding it.
  - A GROUP is a node whose value is the LIVE result of the nodes inside it
    (grouping-runs-as-node). Nodes are built from nodes, down to primitives.
  - It RUNS: editing a node recomputes only what depends on it (incremental).
  - Sessions: a graph saves/loads as JSON (a domain, or the whole grand map).
  - History: immutable snapshots + revert (the history tree).

No UI here. This is the engine that makes the map WORK; the map renders FROM it next.
"""
import json


class Graph:
    def __init__(self):
        self.nodes = {}        # id -> {kind, params, inputs}
        self._cache = {}       # id -> value (memo)
        self.evals = 0         # count of real computations (proves incremental)

    def add(self, nid, kind, params=None, inputs=None):
        self.nodes[nid] = {"kind": kind, "params": dict(params or {}), "inputs": list(inputs or [])}
        return nid

    def _consumers(self, nid):
        """Every node that reads nid — via inputs, or ANY param that holds a node id
        (members / elements / targets / out / ref / accent ...). So edits propagate."""
        out = []
        for m, n in self.nodes.items():
            if nid in n["inputs"]:
                out.append(m); continue
            hit = False
            for val in n["params"].values():
                if isinstance(val, list) and nid in val:
                    hit = True; break
                if isinstance(val, str) and val == nid:
                    hit = True; break
            if hit:
                out.append(m)
        return out

    def _invalidate(self, nid):
        if nid in self._cache:
            del self._cache[nid]
        for d in self._consumers(nid):
            if d in self._cache:
                self._invalidate(d)

    def set_param(self, nid, key, val):
        self.nodes[nid]["params"][key] = val
        self._invalidate(nid)

    def set_status(self, nid, status):
        self.set_param(nid, "status", status)

    def remove(self, nid):
        """Delete a node and scrub it from every param list / input that referenced it."""
        self._invalidate(nid)
        self.nodes.pop(nid, None)
        for n in self.nodes.values():
            n["inputs"] = [i for i in n["inputs"] if i != nid]
            for k, val in list(n["params"].items()):
                if isinstance(val, list):
                    n["params"][k] = [x for x in val if x != nid]

    def wire(self, dst, src):
        if src not in self.nodes[dst]["inputs"]:
            self.nodes[dst]["inputs"].append(src)
        self._invalidate(dst)

    def group(self, gid, member_ids, out_id, x=0, y=0):
        self.add(gid, "group", params={"members": list(member_ids), "out": out_id, "_x": x, "_y": y})
        return gid

    def state(self):
        """The whole running graph + live values — what a UI renders and the AI reads."""
        return {"nodes": [dict(id=i, kind=n["kind"], params=n["params"],
                               inputs=n["inputs"], value=self.eval(i))
                          for i, n in self.nodes.items()]}

    def eval(self, nid):
        if nid in self._cache:
            return self._cache[nid]
        n = self.nodes[nid]; k = n["kind"]; p = n["params"]; ins = n["inputs"]
        self.evals += 1
        if k == "const":
            v = p["value"]
        elif k == "sum":
            v = sum(self.eval(i) for i in ins)
        elif k == "status_score":                       # primitive: status -> a number
            v = {"live": 1.0, "partial": 0.5}.get(p.get("status"), 0.0)
        elif k == "avg":                                 # primitive: mean of inputs
            vals = [self.eval(i) for i in ins]
            v = (sum(vals) / len(vals)) if vals else 0.0
        elif k == "mul":                                 # primitive: input x factor
            v = (self.eval(ins[0]) * p.get("factor", 1)) if ins else 0
        elif k == "ref":                                 # primitive: read another node
            v = self.eval(p["ref"])
        elif k == "group":                               # GROUP RUNS: value = its output subgraph
            _ov = self.eval(p["out"])
            v = round(_ov) if isinstance(_ov, (int, float)) else _ov
        elif k == "accent":                              # a UI parameter node (the app colour)
            v = p.get("color", "#d97757")
        elif k == "ui_element":                          # a UI element, as a node
            v = {"type": p.get("type", "button"), "label": p.get("label", "")}
        elif k == "ui_render":                           # the UI, COMPUTED from its element nodes
            accent = self.eval(p["accent"])
            els = [self.eval(e) for e in p.get("elements", [])]
            btns = "".join(
                '<button style="background:%s;color:#1a0e08;border:0;border-radius:6px;'
                'padding:7px 13px;margin:4px;font-family:Inter,sans-serif;font-size:13px">%s</button>'
                % (accent, e["label"]) for e in els)
            v = '<div style="background:#15151a;padding:12px;border-radius:9px;display:inline-block">%s</div>' % btns
        elif k == "watcher":                             # takes session params -> an editable view of them
            v = [{"id": t, "params": dict(self.nodes[t]["params"])} for t in p.get("targets", [])]
        elif k == "host_write":                          # EFFECTFUL: frozen by default -> dry-run preview only
            target = p.get("target"); value = p.get("value")
            would = {"action": "write", "target": target, "value": value}
            if p.get("frozen", True) or not p.get("apply", False):
                # frozen (default) OR not applied: touch NOTHING, return what it WOULD do
                v = {"dry_run": True, "applied": False, "would": would}
            else:
                # unfrozen AND apply: perform the real side effect (revertible via History)
                with open(target, "w", encoding="utf-8") as fh:
                    fh.write("" if value is None else str(value))
                v = {"dry_run": False, "applied": True, "wrote": would}
        elif k == "proposal":                            # AI proposal: pending change, does NOT mutate target
            v = {"target_node": p.get("target_node"), "key": p.get("key"),
                 "val": p.get("val"), "status": p.get("status", "pending")}
        elif k == "secret_ref":                          # SECRET: holds an op:// reference, returns the REFERENCE
            v = p.get("ref")                             # never the resolved secret (see _resolve_secret)
        elif k == "live_count":                          # DOMAIN value (§3 grouping-runs), REAL not arithmetic:
            # count how many member nodes are actually LIVE/working NOW — a real
            # host node that returned real data, a probe with ok, a brain node
            # that recalled, a status node that is 'live'. Not an average of
            # incompatible values (that was the §15 toy that crashed on dicts).
            live = 0
            for i in ins:
                mv = self.eval(i)
                if isinstance(mv, dict):
                    if mv.get("ok") is True or "facts" in mv or ("host_error" not in mv
                       and "host_unreachable" not in mv and "brain_unreachable" not in mv):
                        live += 1
                elif isinstance(mv, (int, float)):
                    if mv >= 1.0:      # a real count (>0 elements) or status 'live'==1.0
                        live += 1
                elif mv:
                    live += 1
            v = {"live_nodes": live, "total": len(ins)}
        elif k == "host_read":                           # LIVE effectful primitive (SPEC §6): drive a REAL host
            # broker (revit-mcp /exec) and return the REAL result from the real
            # model NOW. Read-only query; the node's value IS real work.
            import urllib.request as _u, json as _j
            port = p.get("port"); code = p.get("code", "")
            try:
                body = _j.dumps({"code": code}).encode()
                req = _u.Request("http://localhost:%s/exec" % port, data=body,
                                 method="POST", headers={"Content-Type": "application/json"})
                with _u.urlopen(req, timeout=45) as r:
                    out = _j.loads(r.read().decode())
                v = out.get("result") if out.get("status") == "ok" else {"host_error": out.get("error", out)}
            except Exception as ex:
                v = {"host_unreachable": "%s:%r" % (port, ex)}
        elif k == "brain_read":                          # LIVE: hit the REAL brain daemon, return real recall
            import urllib.request as _u, json as _j
            prompt = p.get("prompt", "")
            try:
                body = _j.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                 "params": {"name": "brain.context", "arguments": {"prompt": prompt}}}).encode()
                req = _u.Request("http://127.0.0.1:8473/mcp", data=body, method="POST",
                                 headers={"Content-Type": "application/json",
                                          "Accept": "application/json, text/event-stream"})
                with _u.urlopen(req, timeout=20) as r:
                    txt = r.read().decode()
                data = None
                for line in txt.splitlines():
                    if line.startswith("data:"):
                        data = _j.loads(line[5:].strip()); break
                res = (data or {}).get("result", {}) if data else {}
                content = res.get("content", [{}])
                inj = _j.loads(content[0].get("text", "{}")) if content else {}
                v = {"facts": len(inj.get("facts", [])), "skills": len(inj.get("skills", [])),
                     "ok": True}
            except Exception as ex:
                v = {"brain_unreachable": repr(ex)}
        elif k == "probe":                               # LIVE: a real check on the real machine (SPEC §16)
            import urllib.request as _u, os as _o
            kind2 = p.get("kind"); spec = p.get("spec", {})
            try:
                if kind2 == "http_ok":
                    want = int(spec.get("status", 200))
                    try:
                        with _u.urlopen(spec.get("url", ""), timeout=8) as r:
                            v = {"ok": r.getcode() == want, "code": r.getcode()}
                    except _u.HTTPError as he:
                        v = {"ok": he.code == want, "code": he.code}
                elif kind2 == "file_exists":
                    v = {"ok": _o.path.exists(spec.get("path", ""))}
                else:
                    v = {"ok": False, "detail": "unknown probe"}
            except Exception as ex:
                v = {"ok": False, "detail": repr(ex)}
        elif k in ("iterate", "map"):                    # LIST map: over -> [op(x) for x in list]
            src = self._as_list(p.get("over"))           # node id producing a list, OR a literal list
            op = p.get("op", "id")                       # named unary op (pure): id/inc/double/neg/status_score
            v = [self._unary(op, x) for x in src]
        elif k in ("aggregate", "reduce"):               # LIST fold: over -> one value
            src = self._as_list(p.get("over"))
            op = p.get("op", "sum")                       # sum|count|collect|max|min|avg
            if op == "count":
                v = len(src)
            elif op == "collect":
                v = list(src)
            elif op == "sum":
                v = sum(src)
            elif op == "max":
                v = max(src) if src else None
            elif op == "min":
                v = min(src) if src else None
            elif op == "avg":
                v = (sum(src) / len(src)) if src else 0.0
            else:
                v = None
        else:
            v = None
        self._cache[nid] = v
        return v

    def _as_list(self, over):
        """Resolve an 'over' param to a real list: a node id whose value is a list,
        a literal list (possibly of node ids), or an inline literal list of values."""
        if isinstance(over, str) and over in self.nodes:
            val = self.eval(over)
            return list(val) if isinstance(val, (list, tuple)) else [val]
        if isinstance(over, (list, tuple)):
            return [self.eval(x) if isinstance(x, str) and x in self.nodes else x for x in over]
        return [] if over is None else [over]

    def _unary(self, op, x):
        """A pure named unary op applied to one element (no graph mutation)."""
        if op in ("id", None):
            return x
        if op == "inc":
            return x + 1
        if op == "double":
            return x * 2
        if op == "neg":
            return -x
        if op == "status_score":
            return {"live": 1.0, "partial": 0.5}.get(x, 0.0)
        return x

    def approve_proposal(self, pid):
        """Approve a pending proposal node: apply it to the target via set_param, flip status='applied'.
        Until approved, a proposal NEVER mutates its target (the AI never silently mutates the graph)."""
        p = self.nodes[pid]["params"]
        if p.get("status") == "applied":
            return False
        self.set_param(p["target_node"], p["key"], p["val"])   # the only place a proposal touches the target
        self.set_param(pid, "status", "applied")
        return True

    def _resolve_secret(self, nid):
        """Resolve a secret_ref to its real value AT RUN TIME only. Deliberately NOT used by
        eval/state/to_session — the resolved value never enters the graph, a session, or history."""
        import os, subprocess
        ref = self.nodes[nid]["params"].get("ref", "")
        env = os.environ.get(ref.replace("op://", "").replace("/", "_").upper())
        if env is not None:
            return env
        try:                                              # op:// resolves via the 1Password CLI if present
            return subprocess.check_output(["op", "read", ref], text=True).strip()
        except Exception:
            return None

    def to_session(self):
        # deep copy so a snapshot can never be mutated by later edits to the graph
        return {"schema": "node_lang/1", "nodes": json.loads(json.dumps(self.nodes))}

    @classmethod
    def from_session(cls, data):
        g = cls()
        g.nodes = json.loads(json.dumps(data["nodes"]))
        return g


class _Frozen(dict):
    """A committed snapshot: APPEND-ONLY. Once committed it cannot be rewritten in place."""
    _sealed = False

    def _seal(self):
        object.__setattr__(self, "_sealed", True)
        return self

    def __setitem__(self, k, v):
        if self._sealed:
            raise TypeError("history snapshot is append-only: a committed version cannot be mutated")
        super().__setitem__(k, v)

    def __delitem__(self, k):
        if self._sealed:
            raise TypeError("history snapshot is append-only: a committed version cannot be mutated")
        super().__delitem__(k)


class History:
    """The history tree: APPEND-ONLY immutable snapshots, revert to any."""
    def __init__(self):
        self.versions = []

    def commit(self, graph, label):
        snap = _Frozen({"label": label,
                        "session": json.loads(json.dumps(graph.to_session()))})
        self.versions.append(snap._seal())             # sealed: cannot be rewritten after the fact
        return len(self.versions) - 1

    def revert(self, graph, idx):
        v = self.versions[idx]
        # deep-copy OUT of the snapshot so revert never mutates the committed version
        graph.nodes = json.loads(json.dumps(v["session"]["nodes"]))
        graph._cache = {}
        return v["label"]
