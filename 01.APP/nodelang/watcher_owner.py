"""Source-bound Watcher drafts and annotations in the admitted application graph."""
import hashlib
import json
import math
from types import SimpleNamespace

from .cell_protocols import prepare_append_relation_members
from .universal_cell import Cell, InvalidCell

PREFIX = "app:watcher-proposal:"
SCALE_MM = 15.0


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def _number(value):
    if type(value) not in (int, float) or not math.isfinite(value) or abs(value) > 10000000:
        raise InvalidCell("Watcher coordinates must be finite numbers within the drawing budget")
    return value


def _point(value):
    if type(value) is not dict or set(value) != {"x", "y"}:
        raise InvalidCell("A drawing point needs x and y")
    return {key:_number(value[key]) for key in ("x", "y")}


class WatcherOwner:
    def __init__(self, api):
        self.api = api
        self.root = api.root + ":watcher:" + _digest([api.scope, api.binding.subject_root])

    def _node(self, create=False):
        from .canvas_graph_owner import CanvasOwner
        from .universal_pipeline import create_engine_node
        api = self.api
        api.admit()
        ops = CanvasOwner(api.owner.universal_store, api.owner.universal_registry, api.binding.context)
        found = [node['id'] for node in ops.canvas()['nodes']
                 if ops._rows(None,node['id']).get('watcher_owner',{}).get('value') == self.root]
        if len(found) > 1:
            raise InvalidCell('Watcher owner is ambiguous; reconcile its existing nodes')
        if found:
            return ops, found[0]
        if not create:
            return ops, None
        api.guard()
        node = create_engine_node(api.owner.universal_store, api.owner.universal_registry,
            title='Watcher', engine='lines.watch', properties={'watcher_owner':self.root},
            authentication_context=api.binding.context)
        return ops, node['root']

    def _read(self, root):
        cell = self.api.admit().cells.get(root)
        return json.loads(cell.atom) if cell else None

    def _save(self, root, value, parent, *, state=None, record_limit: int = 65536):
        from . import universal_application as app
        api = self.api
        store, registry = api.owner.universal_store, api.owner.universal_registry
        records = [(root, value)] + ([(self.root, state)] if state is not None else [])
        encoded = [(key, json.dumps(record, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode())
                   for key, record in records]
        if any(len(value) > record_limit for _, value in encoded):
            raise InvalidCell("Watcher record exceeds 64 KiB; existing content is unchanged")
        _, node = self._node(create=True)
        parent = node if parent == api.root else parent
        snapshot = api.admit()
        cells = [Cell(key, parent, api.binding.subject_root, value) for key, value in encoded]
        if all(snapshot.cells.get(cell.id) == cell for cell in cells):
            return
        patch = prepare_append_relation_members(snapshot, parent,
            tuple((registry.roles["member"], cell.id) for cell in cells if cell.id not in snapshot.cells))
        view, context = app._view_session_for_context(registry, api.binding.context)
        api.guard()
        app._commit_universal_user_change(store, registry, view, context, snapshot,
            route=api.route, command_name="catalog.configure", authorization_scope_root=api.root,
            create=(*patch.create, *(cell for cell in cells if cell.id not in snapshot.cells)),
            replace=(*patch.replace, *(cell for cell in cells if cell.id in snapshot.cells)))

    def _state(self):
        return self._read(self.root) or {"source":None, "pendingY":None, "proposal":None,
            "proposals":[], "annotations":[], "applied":False}

    def read(self):
        state = self._state()
        source = state["source"] or {}
        element = source.get("element") or {}
        start, end = element.get("start", [0, 0]), element.get("end", [0, 0])
        selected = [a for a in state["annotations"] if a["source"] == self._binding(source)]
        return {"owner":self.root, "host":source.get("host", ""), "view":source.get("view", ""),
            "views":source.get("views", []), "elementId":element.get("id", ""),
            "elementLabel":element.get("label", ""), "sourceRevision":element.get("revision", ""),
            "document":source.get("document", ""), "wallY":start[1],
            "pendingY":state["pendingY"] if state["pendingY"] is not None else start[1],
            "lengthMm":element.get("lengthMm", 0), "thicknessMm":element.get("thicknessMm", 0),
            "appliedLengthMm":element.get("lengthMm", 0), "appliedThicknessMm":element.get("thicknessMm", 0),
            "marks":[a for a in selected if a["kind"] == "mark"],
            "comments":[{**a, "y":a["y"]+(start[1]-a["anchorY"] if a["element"] == element.get("id") else 0)} for a in selected if a["kind"] == "comment"],
            "dimensions":[a for a in selected if a["kind"] == "dimension"],
            "geometry":{"outline":[], "walls":[[*start, *end]] if element else [], "doors":[], "tags":[]},
            "proposal":state["proposal"], "applied":state["applied"],
            "status":"loaded" if element else "Select one source wall or line in the host",
            "showDimensions":True, "dimensionAlignment":"Aligned", "mask":next((a["bounds"] for a in reversed(selected) if a.get("tool") == "Mask"), None)}

    @staticmethod
    def _binding(source):
        return {key:source.get(key) for key in ("host", "instance", "document", "view")}

    def _source(self, state):
        if not state["source"] or not state["source"].get("element"):
            raise InvalidCell("Select one wall or line in the source program, then choose its host")
        return state["source"]

    def _draft(self, state):
        if state["proposal"]:
            raise InvalidCell("Discard the current proposal before changing its source or edit")

    def set_host(self, host):
        from .host_brokers import watcher_read
        if host not in {"Revit", "AutoCAD"}:
            raise InvalidCell("Choose Revit or AutoCAD for source geometry")
        state = self._state()
        self._draft(state)
        if state["pendingY"] is not None:
            raise InvalidCell("Discard pending geometry before changing source")
        source = watcher_read(host)
        state.update(source=source, pendingY=None, applied=False)
        self._save(self.root, state, self.api.root)
        return self.read()

    def set_view(self, view):
        from .host_brokers import watcher_read
        state = self._state()
        source = self._source(state)
        self._draft(state)
        if type(view) is not str or view not in source["views"] or state["pendingY"] is not None:
            raise InvalidCell("Choose an available view after discarding pending geometry")
        state["source"] = watcher_read(source["host"], instance=source["instance"], view=view,
                                        document=source["document"], element=source["element"]["id"])
        self._save(self.root, state, self.api.root)
        return self.read()

    def edit(self, y):
        y = _number(y)
        state = self._state()
        source = self._source(state)
        self._draft(state)
        masks = [a["bounds"] for a in state["annotations"] if a.get("tool") == "Mask" and a["source"] == self._binding(source)]
        if masks:
            bounds = masks[-1]
            shift = y-source["element"]["start"][1]
            for point in (source["element"]["start"], source["element"]["end"]):
                if (not bounds["x"] <= point[0] <= bounds["x"]+bounds["w"] or
                        not all(bounds["y"] <= value <= bounds["y"]+bounds["h"] for value in (point[1], point[1]+shift))):
                    raise InvalidCell("The edited element would leave your mask")
        # shortcut: offset editing only; add typed length/type edits with their own host validation.
        state.update(pendingY=y if y != source["element"]["start"][1] else None, applied=False)
        self._save(self.root, state, self.api.root)
        return self.read()

    def annotate(self, kind, values):
        state = self._state()
        source = self._source(state)
        if type(values) is not dict:
            raise InvalidCell("Annotation inputs must be named values")
        row = {"id":self.root + ":annotation:" + self.api.request_id, "kind":kind,
            "source":self._binding(source), "element":source["element"]["id"],
            "revision":source["element"]["revision"], "anchorY":source["element"]["start"][1], "author":self.api.binding.subject_root}
        if kind == "dimension":
            if set(values) != {"from", "to"}:
                raise InvalidCell("A dimension needs its two endpoints")
            start, end = _point(values["from"]), _point(values["to"])
            distance = math.hypot(end["x"]-start["x"], end["y"]-start["y"]) * SCALE_MM
            if distance < 1:
                raise InvalidCell("Choose two different points")
            row.update({"from":start, "to":end, "valueMm":distance})
        elif kind == "mark":
            if (set(values) != {"tool", "points"} or values["tool"] not in {"Sketch", "Mark", "Mask"}
                    or type(values["points"]) is not list or not 2 <= len(values["points"]) <= 2000):
                raise InvalidCell("A sketch or mark needs 2-2000 points")
            row.update(tool=values["tool"], points=[_point(p) for p in values["points"]])
            if row["tool"] == "Mask":
                self._draft(state)
                if state["pendingY"] is not None:
                    raise InvalidCell("Discard the pending geometry before changing its mask")
                xs, ys = [p["x"] for p in row["points"]], [p["y"] for p in row["points"]]
                if max(xs) == min(xs) or max(ys) == min(ys):
                    raise InvalidCell("A mask needs a nonzero rectangular area")
                row["bounds"] = {"x":min(xs), "y":min(ys), "w":max(xs)-min(xs), "h":max(ys)-min(ys)}
        else:
            if (set(values) != {"text", "x", "y", "element"} or type(values["text"]) is not str
                    or not values["text"].strip() or len(values["text"]) > 2000
                    or values["element"] != row["element"]):
                raise InvalidCell("A comment needs text and the selected source element")
            row.update(text=values["text"].strip(), **_point({"x":values["x"], "y":values["y"]}))
        old = next((a for a in state["annotations"] if a["id"] == row["id"]), None)
        if old and old != row:
            raise InvalidCell("This annotation request already names another value")
        if not old:
            state["annotations"].append(row)
            self._save(self.root, state, self.api.root)
        return self.read()

    def propose(self):
        state = self._state()
        source = self._source(state)
        if state["proposal"]:
            return self.card(state["proposal"])
        from .desktop_owner import DesktopOwner
        desktop = DesktopOwner(self.api)
        root = desktop._state()['proposal']
        if root:
            plan = desktop.proposal(root)
            if (plan['status'] in {'pending', 'executing', 'unconfirmed'} and plan['payload']['action'] == 'move'
                    and plan['payload']['payload']['source'] == source):
                raise InvalidCell('This offset already has a desktop approval; decide that card first')
        if state["pendingY"] is None:
            raise InvalidCell("Edit a source wall or line before proposing a change")
        payload = {"source":source, "offsetMm":(state["pendingY"]-source["element"]["start"][1])*SCALE_MM}
        root = PREFIX + _digest([self.root, self.api.request_id])
        if self._read(root) is not None:
            raise InvalidCell("This proposal request already names a closed transaction; use a fresh request identity")
        proposal = {"owner":self.root, "payload":payload, "input_digest":_digest(payload), "status":"pending"}
        # The proposal is sealed before linking; an interrupted link creates no executable card.
        self._save(root, proposal, self.api.root)
        state["proposal"] = root
        state["proposals"].append(root)
        self._save(self.root, state, self.api.root)
        return self.card(root)

    def proposal(self, root):
        state = self._state()
        if type(root) is not str or root not in state["proposals"]:
            raise InvalidCell("This proposal belongs to another Watcher or account")
        return self._read(root)

    def card(self, root):
        proposal = self.proposal(root)
        source = proposal["payload"]["source"]
        element = source["element"]
        review = self._read(root + ":approval-review") or {"status":"pending", "rows":[], "rubric":{}, "events":[]}
        rows = review["rows"] or [{"element":element["id"], "before":str(element["start"]),
            "after":str(proposal["payload"]["offsetMm"]) + " mm offset"}]
        return {**review, "rows":rows, "id":root, "delegation":root, "work":self.root,
            "input_digest":proposal["input_digest"], "approvalKind":"watcher", "kind":"qc",
            "title":"Move " + element["label"], "elementId":element["id"],
            "sourceRevision":element["revision"], "status":review["status"] if proposal["status"] == "pending" else proposal["status"],
            "revision":self.api.owner.universal_store.revision}

    def reviews(self):
        return [self.card(root) for root in self._state()["proposals"]]

    def discard(self):
        state = self._state()
        if state["proposal"]:
            root = state["proposal"]
            proposal = self.proposal(root)
            if proposal["status"] in {"executing", "unconfirmed"}:
                raise InvalidCell("Host outcome needs reconciliation; discard cannot undo an uncertain write")
            if proposal["status"] == "approved":
                state.update(source=proposal["readback"], pendingY=None, proposal=None, applied=True)
                self._save(self.root, state, self.api.root)
                return self.read()
            proposal["status"] = "declined"
            state.update(pendingY=None, proposal=None)
            self._save(root, proposal, self.api.root, state=state)
        else:
            state.update(pendingY=None)
            self._save(self.root, state, self.api.root)
        return self.read()

    def decide(self, root, digest, decision):
        from .host_brokers import watcher_read, watcher_write
        proposal = self.proposal(root)
        if (decision not in {"approve", "deny"} or digest != proposal["input_digest"]
                or digest != _digest(proposal["payload"])):
            raise InvalidCell("Review the exact source revision and change before deciding")
        if proposal["status"] == "approved" and decision == "approve":
            return self.card(root)
        state = self._state()
        if state["proposal"] != root or proposal["status"] != "pending":
            raise InvalidCell("This Watcher proposal is closed or needs reconciliation")
        if decision == "deny":
            self.discard()
            return self.card(root)
        source = proposal["payload"]["source"]
        current = watcher_read(source["host"], instance=source["instance"], view=source["view"],
            document=source["document"], element=source["element"]["id"])
        if current != source:
            raise InvalidCell("Source revision changed; discard and review a fresh edit")
        proposal["status"] = "executing"
        self._save(root, proposal, self.api.root)
        try:
            watcher_write(proposal["payload"])
            actual = watcher_read(source["host"], instance=source["instance"], view=source["view"],
                document=source["document"], element=source["element"]["id"])
            expected = source["element"]
            result = actual.get("element") or {}
            shift = proposal["payload"]["offsetMm"]/SCALE_MM
            if (self._binding(actual) != self._binding(source) or result.get("id") != expected["id"]
                    or any(not math.isclose(result.get(key, float("nan")), expected[key], abs_tol=0.001)
                           for key in ("lengthMm", "thicknessMm"))
                    or any(len(result.get(key, [])) != 2 or
                           not math.isclose(result[key][0], expected[key][0], abs_tol=0.001) or
                           not math.isclose(result[key][1], expected[key][1]+shift, abs_tol=0.001)
                           for key in ("start", "end"))):
                raise InvalidCell("Host readback differs from the approved wall position")
        except Exception:
            proposal["status"] = "unconfirmed"
            self._save(root, proposal, self.api.root)
            raise
        proposal.update(status="approved", readback=actual)
        state.update(source=actual, pendingY=None, proposal=None, applied=True)
        self._save(root, proposal, self.api.root, state=state)
        return self.card(root)


def approval_context(api, root):
    owner = WatcherOwner(api)
    proposal = owner.proposal(root)
    registry = api.owner.universal_registry
    delegation = SimpleNamespace(root_id=root, permission_root=root, work_root=owner._node()[1],
        input_digest=proposal["input_digest"], expires_at=float("inf"))
    lifecycle = "requested" if proposal["status"] == "pending" else "granted" if proposal["status"] == "approved" else "revoked"
    permission = SimpleNamespace(lifecycle_root=registry.adapter_protocol.states[lifecycle], user_root=api.binding.subject_root)
    return api.admit(), "watcher", delegation, permission, {"interfaces":{"title":{"value":owner.card(root)["title"]}}}
