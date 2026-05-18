"""Composer slash-command parser — Python side.

The JSX `FloatingComposer` in `studio-lm.jsx` calls into this parser
(via the bridge slot `parse_composer_command`) when the user types
text that starts with one of:

    /wire        — add an edge to LM_GRAPH.wires
    /freeze      — toggle node.frozen
    /delete      — remove a node + its incident wires
    /rename      — rename a node
    /duplicate   — clone + offset
    /properties  — open the node's property modal
    /connect     — alias of /wire (sometimes more natural)
    /disconnect  — remove a specific wire by endpoints
    /            — bare slash: open the inline help

The parser is pure data — it returns a typed action-descriptor dict
that either JSX or Python can apply. This keeps the rules in one place
and lets us pin behaviour with unit tests on the Python side without
ever touching JS.

Action descriptor shape (always JSON-friendly):

    {
      "command":  "wire" | "freeze" | "delete" | "rename" |
                  "duplicate" | "properties" | "disconnect" | "help",
      "ok":       bool,                # parser thinks the args are valid
      "error":    str,                 # populated when ok=False
      "summary":  str,                 # one-line UI status, always set
      # command-specific fields below…
    }

Each command keeps any extra args under sensible keys (`src_node`,
`src_port`, `dst_node`, `dst_port` for wire/disconnect; `node_id` +
`new_title` for rename; etc.). The agent applying the action is free
to consult the descriptor and decide whether to splice LM_GRAPH on
the JS side or call a Python helper like `add_wire`.
"""
from __future__ import annotations

import re
from typing import Any, Optional


# ── token shapes ───────────────────────────────────────────────────
_ENDPOINT_RE = re.compile(
    r"""^\s*
        (?P<node>[A-Za-z0-9_\-]+)
        \s*\.\s*
        (?P<port>[A-Za-z0-9_\-]+)
        \s*$""",
    re.VERBOSE,
)

# Recognise the wire-arrow in several forms — the founder uses "→", but
# `->`, "=>", and "to" all show up in practice.
_WIRE_SEP_RE = re.compile(r"\s*(?:→|->|=>|\bto\b)\s*", re.IGNORECASE)

# Every command we recognise, with the bare-slash-help fallback included.
COMMANDS = (
    "wire", "freeze", "delete", "rename",
    "duplicate", "properties", "connect", "disconnect",
    "createnode",
    # Founder demand 2026-05-14: explicit slash form of "ping <host>" so
    # `/ping outlook` spawns the host pair the same way "ping outlook"
    # (no slash) already does. Without a slash, ambiguous freeform like
    # bare `/ping` lands here too — handled below by re-routing through
    # detect_intent against the remainder.
    "ping",
)

# /createnode key=value parser — quoted values support spaces.
_KV_RE = re.compile(
    r"""(?P<key>[A-Za-z_][A-Za-z0-9_]*)
        \s*=\s*
        (?P<val>"[^"]*"|'[^']*'|[^\s]+)""",
    re.VERBOSE,
)


def _parse_kv(rest: str) -> dict:
    """Parse `type=x cat=y inputs=a,b outputs=c` into a dict. Values
    wrapped in quotes are unquoted. Comma-separated lists are split."""
    out: dict = {}
    for m in _KV_RE.finditer(rest or ""):
        key = m.group("key").lower()
        val = m.group("val")
        if (val.startswith('"') and val.endswith('"')) or (
                val.startswith("'") and val.endswith("'")):
            val = val[1:-1]
        if key in ("inputs", "outputs"):
            out[key] = [v.strip() for v in val.split(",") if v.strip()]
        else:
            out[key] = val
    return out

# ── natural-language intent detection ──────────────────────────────
# Hosts the composer knows how to spawn on the canvas. These map to
# `host.<family>` node types and are recognised as substrings (case-
# insensitive) of any whitespace-separated word in the composer text.
HOST_FAMILIES = (
    "revit", "autocad", "max", "blender", "rhino", "speckle",
    "outlook", "lmstudio", "antigravity", "word", "excel",
    "powerpoint", "photoshop", "illustrator", "indesign", "teams",
    "notion", "dropbox",
)

# Verbs that signal a host-directed intent ("ping outlook",
# "list walls in revit", "what's in my outlook"). When any of these
# co-occur with a known host family we treat the line as a natural-
# language host-chat intent rather than plain chat.
INTENT_VERBS = (
    "ping", "info", "list", "open", "save", "render", "build",
    "draft", "send", "search", "find", "summarise", "summarize",
    "show", "describe", "explain", "what", "where", "how",
)

# Tokeniser for intent detection: splits on any run of non-alnum chars,
# preserving apostrophes-as-glue inside a single token (so "what's"
# stays one word).
_INTENT_TOKEN_RE = re.compile(r"[a-z0-9']+")


def detect_intent(raw: str) -> Optional[dict]:
    """Return a natural-language intent descriptor, or None.

    The composer treats any line that names a known host family AND
    either starts with that family or pairs it with a known verb as
    a `host_chat` intent. The caller then spawns the host node on the
    canvas, wires a fresh conversation node, and streams the chat.

    Shape on match:
        {"kind": "host_chat", "family": "outlook",
         "verb": "ping" | None, "remainder": "..."}

    Returns None when the line is plain chat (no host name) or when
    a host is named without any intent-verb cue and isn't the leading
    token (avoids false-positives like "I bought outlook a coffee").
    """
    if not raw:
        return None
    text = raw.strip().lower()
    if not text:
        return None
    tokens = _INTENT_TOKEN_RE.findall(text)
    if not tokens:
        return None
    # ── 1. find a host family in the tokens
    host: Optional[str] = None
    host_index: int = -1
    for idx, tok in enumerate(tokens):
        for fam in HOST_FAMILIES:
            if fam in tok:
                host = fam
                host_index = idx
                break
        if host:
            break
    if not host:
        return None
    # ── 2. find a verb in the tokens
    # We also strip a trailing apostrophe-clitic (e.g. "what's" → "what")
    # so contractions match the INTENT_VERBS list cleanly.
    verb: Optional[str] = None
    verb_index: int = -1
    for idx, tok in enumerate(tokens):
        if idx == host_index:
            continue
        base = tok.split("'", 1)[0]
        if tok in INTENT_VERBS:
            verb = tok
            verb_index = idx
            break
        if base and base in INTENT_VERBS:
            verb = base
            verb_index = idx
            break
    # ── 3. accept iff host leads, OR a verb co-occurs
    if verb is None and host_index != 0:
        return None
    # ── 4. compute the remainder — tokens that aren't the host name
    rem_tokens = [t for i, t in enumerate(tokens) if i != host_index]
    remainder = " ".join(rem_tokens).strip()
    return {
        "kind": "host_chat",
        "family": host,
        "verb": verb,
        "remainder": remainder,
    }

HELP_LINES = (
    ("/wire host.port → other.port",
        "Add a wire between two ports."),
    ("/freeze [node-id]",
        "Pause cooking on the focused node (or a named one)."),
    ("/delete [node-id]",
        "Delete the focused node and its incident wires."),
    ("/rename <new title>",
        "Rename the focused node."),
    ("/duplicate [node-id]",
        "Clone the focused node beside the original."),
    ("/properties",
        "Open the focused node's property panel."),
    ("/disconnect host.port → other.port",
        "Remove a specific wire."),
    ("/createnode type=… cat=… inputs=a,b outputs=x,y",
        "Open the new-node modal pre-filled with these fields."),
)


def _parse_endpoint(token: str) -> Optional[tuple[str, str]]:
    """`"host.revit.opened_doc"` → not valid (two dots). Use one dot."""
    if not token:
        return None
    m = _ENDPOINT_RE.match(token)
    if not m:
        return None
    return (m.group("node"), m.group("port"))


def _split_wire_args(rest: str) -> Optional[tuple[str, str]]:
    """Split the args of `/wire`: returns `(src, dst)` or None."""
    if not rest:
        return None
    parts = _WIRE_SEP_RE.split(rest, maxsplit=1)
    if len(parts) != 2:
        return None
    return (parts[0].strip(), parts[1].strip())


def parse_composer_command(raw: str,
                            focused_node_id: Optional[str] = None) -> dict:
    """Parse a single composer line.

    Args:
        raw: The full composer text, e.g. `"/wire revit.view → ai_intent.ctx"`.
        focused_node_id: The node currently focused on the canvas (used
            as the implicit target for `/freeze`, `/delete`, `/rename`,
            `/duplicate`, and `/properties` when no node id is given).

    Returns:
        An action descriptor (see module docstring). When the input
        doesn't start with `/` or the command isn't recognised,
        returns `{"command": "_passthrough", "ok": True, ...}` so the
        caller knows to fall back to the LLM round-trip path.
    """
    text = (raw or "").strip()
    if not text.startswith("/"):
        # Natural-language intent: e.g. "ping outlook", "outlook inbox".
        # When detected, we return a `spawn_host_chat` action so the JSX
        # side can spawn the host node + conv node + wire them up.
        intent = detect_intent(text)
        if intent is not None:
            return {
                "command":   "spawn_host_chat",
                "ok":         True,
                "family":     intent["family"],
                "verb":       intent["verb"],
                "remainder":  intent["remainder"],
                "original":   text,
                "summary":    f"Spawn {intent['family']} host + send chat",
            }
        return {
            "command": "_passthrough",
            "ok":       True,
            "summary":  "(no command — send as chat)",
            "raw":      text,
        }

    body = text[1:]
    # Bare slash → help. Anything else, split into verb + rest.
    if not body.strip():
        return {
            "command": "help",
            "ok":       True,
            "summary":  "Available commands:",
            "lines":    [{"cmd": l[0], "desc": l[1]} for l in HELP_LINES],
        }

    bits = body.split(None, 1)
    verb = bits[0].strip().lower()
    rest = bits[1].strip() if len(bits) > 1 else ""

    if verb not in COMMANDS:
        return {
            "command": "help",
            "ok":       False,
            "error":    f"unknown command: /{verb}",
            "summary":  f"unknown /{verb} — try / for help",
            "lines":    [{"cmd": l[0], "desc": l[1]} for l in HELP_LINES],
        }

    if verb == "ping":
        # /ping outlook   → spawn_host_chat for outlook
        # /ping           → re-run detect_intent on whatever the user typed
        # /ping anything  → fall through to detect_intent on the remainder
        target = rest.strip().lower()
        intent = detect_intent(target) if target else None
        if not intent:
            # Try bare /ping w/o args — if a host family token appears
            # anywhere in `rest`, accept it.
            tokens = _INTENT_TOKEN_RE.findall(target)
            fam = next((t for t in tokens
                         for f in HOST_FAMILIES if f in t and (fam := f)), None) \
                  if tokens else None
            if fam is None:
                # Just enumerate host families as a help line.
                return {
                    "command": "help",
                    "ok":       False,
                    "error":    "ping needs a host name",
                    "summary":  "try /ping outlook (or any host)",
                    "lines":    [{"cmd": f"/ping {f}", "desc": f"Spawn {f} host + chat"}
                                  for f in HOST_FAMILIES],
                }
            return {
                "command":   "spawn_host_chat",
                "ok":         True,
                "family":     fam,
                "verb":       "ping",
                "remainder":  target,
                "original":   raw,
                "summary":    f"Spawn {fam} host + chat",
            }
        return {
            "command":   "spawn_host_chat",
            "ok":         True,
            "family":     intent["family"],
            "verb":       intent.get("verb") or "ping",
            "remainder":  intent.get("remainder") or "",
            "original":   raw,
            "summary":    f"Spawn {intent['family']} host + chat",
        }

    if verb in ("wire", "connect"):
        pair = _split_wire_args(rest)
        if not pair:
            return {
                "command": "wire",
                "ok":       False,
                "error":    "wire needs `src-node.port → dst-node.port`",
                "summary":  "missing endpoints",
            }
        src = _parse_endpoint(pair[0])
        dst = _parse_endpoint(pair[1])
        if not src or not dst:
            return {
                "command": "wire",
                "ok":       False,
                "error":    "endpoints must be `node.port`",
                "summary":  "bad endpoints",
            }
        return {
            "command":  "wire",
            "ok":       True,
            "src_node": src[0], "src_port": src[1],
            "dst_node": dst[0], "dst_port": dst[1],
            "summary":  f"wire {src[0]}.{src[1]} → {dst[0]}.{dst[1]}",
        }

    if verb == "disconnect":
        pair = _split_wire_args(rest)
        if not pair:
            return {
                "command": "disconnect",
                "ok":       False,
                "error":    "disconnect needs `src-node.port → dst-node.port`",
                "summary":  "missing endpoints",
            }
        src = _parse_endpoint(pair[0])
        dst = _parse_endpoint(pair[1])
        if not src or not dst:
            return {
                "command": "disconnect",
                "ok":       False,
                "error":    "endpoints must be `node.port`",
                "summary":  "bad endpoints",
            }
        return {
            "command":  "disconnect",
            "ok":       True,
            "src_node": src[0], "src_port": src[1],
            "dst_node": dst[0], "dst_port": dst[1],
            "summary":  f"disconnect {src[0]}.{src[1]} → {dst[0]}.{dst[1]}",
        }

    if verb == "freeze":
        node_id = rest.strip() or focused_node_id or ""
        if not node_id:
            return {
                "command": "freeze",
                "ok":       False,
                "error":    "no node id and no focused node",
                "summary":  "freeze needs a target",
            }
        return {
            "command": "freeze",
            "ok":       True,
            "node_id":  node_id,
            "summary":  f"freeze {node_id}",
        }

    if verb == "delete":
        node_id = rest.strip() or focused_node_id or ""
        if not node_id:
            return {
                "command": "delete",
                "ok":       False,
                "error":    "no node id and no focused node",
                "summary":  "delete needs a target",
            }
        return {
            "command": "delete",
            "ok":       True,
            "node_id":  node_id,
            "summary":  f"delete {node_id}",
        }

    if verb == "rename":
        new_title = rest.strip()
        if not new_title:
            return {
                "command": "rename",
                "ok":       False,
                "error":    "rename needs a new title",
                "summary":  "rename to what?",
            }
        if not focused_node_id:
            return {
                "command": "rename",
                "ok":       False,
                "error":    "no focused node",
                "summary":  "focus a node first",
            }
        return {
            "command":   "rename",
            "ok":         True,
            "node_id":    focused_node_id,
            "new_title":  new_title,
            "summary":    f"rename {focused_node_id} → {new_title}",
        }

    if verb == "duplicate":
        node_id = rest.strip() or focused_node_id or ""
        if not node_id:
            return {
                "command": "duplicate",
                "ok":       False,
                "error":    "no node id and no focused node",
                "summary":  "duplicate needs a target",
            }
        return {
            "command":  "duplicate",
            "ok":       True,
            "node_id":  node_id,
            "offset":   {"x": 30, "y": 30},
            "summary":  f"duplicate {node_id}",
        }

    if verb == "properties":
        node_id = rest.strip() or focused_node_id or ""
        if not node_id:
            return {
                "command": "properties",
                "ok":       False,
                "error":    "no node id and no focused node",
                "summary":  "properties needs a target",
            }
        return {
            "command":  "properties",
            "ok":       True,
            "node_id":  node_id,
            "summary":  f"open properties for {node_id}",
        }

    if verb == "createnode":
        # All fields optional — JSX opens a modal pre-filled with whatever
        # the user supplied. `cat` is an alias for `category` so the
        # founder can type either.
        kv = _parse_kv(rest)
        type_name = kv.get("type", "")
        category = kv.get("category") or kv.get("cat") or ""
        inputs = kv.get("inputs") or []
        outputs = kv.get("outputs") or []
        display_name = kv.get("display_name") or kv.get("name") or type_name
        return {
            "command":     "createnode",
            "ok":          True,
            "type":        type_name,
            "category":    category,
            "display_name": display_name,
            "inputs":      inputs,
            "outputs":     outputs,
            "summary":     f"new node {type_name or '?'}"
                            + (f" [{category}]" if category else ""),
        }

    # Shouldn't reach here — `verb in COMMANDS` is checked above.
    return {
        "command": "help",
        "ok":       False,
        "error":    f"unhandled command: /{verb}",
        "summary":  "(internal) parser fell through",
        "lines":    [{"cmd": l[0], "desc": l[1]} for l in HELP_LINES],
    }


def apply_action(graph: dict, action: dict) -> dict:
    """Apply a parsed action to a graph dict in-place-friendly fashion.

    Returns a new graph dict (input not mutated) with the action
    applied. Unsupported / not-ok actions return the graph unchanged.

    Currently implements graph-side actions: wire, disconnect, freeze,
    delete, rename, duplicate. `properties` is a JSX-only action (it
    just emits an event) — applying it via this function is a no-op.
    """
    import copy as _copy
    if not action or not action.get("ok"):
        return _copy.deepcopy(graph)
    cmd = action.get("command")
    g = _copy.deepcopy(graph)
    nodes_by_id = {n.get("id"): n for n in (g.get("nodes") or [])
                    if n.get("id")}

    if cmd == "wire":
        # Defer to subgraph.add_wire so the rules stay in one place.
        # add_wire raises ValueError on unknown nodes / ports / cycle /
        # duplicate — apply_action must never raise, so we wrap and
        # return the unchanged graph (with summary annotation) instead.
        try:
            from . import subgraph as _sg
            return _sg.add_wire(g,
                                  action["src_node"], action["src_port"],
                                  action["dst_node"], action["dst_port"])
        except Exception as ex:
            # Annotate the unchanged graph so callers can surface the
            # reason in the UI without us bubbling an exception up.
            g["_wire_refused"] = f"wire refused: {ex}"
            return g

    if cmd == "disconnect":
        wires = g.get("wires") or g.get("edges") or []
        keep: list[dict] = []
        for w in wires:
            if "from" in w and "to" in w:
                f = w["from"]; t = w["to"]
            elif "src_node" in w:
                f = [w["src_node"], w["src_port"]]
                t = [w["dst_node"], w["dst_port"]]
            else:
                keep.append(w); continue
            if (f[0] == action["src_node"] and f[1] == action["src_port"]
                    and t[0] == action["dst_node"]
                    and t[1] == action["dst_port"]):
                continue
            keep.append(w)
        if "wires" in g:
            g["wires"] = keep
        else:
            g["edges"] = keep
        return g

    if cmd == "freeze":
        nid = action.get("node_id")
        n = nodes_by_id.get(nid)
        if n is not None:
            n["frozen"] = not bool(n.get("frozen"))
        return g

    if cmd == "delete":
        nid = action.get("node_id")
        g["nodes"] = [n for n in (g.get("nodes") or [])
                       if n.get("id") != nid]
        for key in ("wires", "edges"):
            if key in g:
                wires = []
                for w in g[key]:
                    if "from" in w and "to" in w:
                        if w["from"][0] == nid or w["to"][0] == nid:
                            continue
                    elif "src_node" in w:
                        if w["src_node"] == nid or w["dst_node"] == nid:
                            continue
                    wires.append(w)
                g[key] = wires
        return g

    if cmd == "rename":
        n = nodes_by_id.get(action.get("node_id"))
        if n is not None:
            n["title"] = action["new_title"]
            n["label"] = action["new_title"]
        return g

    if cmd == "duplicate":
        n = nodes_by_id.get(action.get("node_id"))
        if n is None:
            return g
        import uuid as _uuid
        clone = _copy.deepcopy(n)
        clone["id"] = f"{n.get('id', 'node')}_copy_{_uuid.uuid4().hex[:6]}"
        off = action.get("offset") or {"x": 30, "y": 30}
        clone["x"] = float(n.get("x", 0)) + float(off.get("x", 30))
        clone["y"] = float(n.get("y", 0)) + float(off.get("y", 30))
        # Workflow shape also keeps `position`. Update both for safety.
        if isinstance(n.get("position"), dict):
            pos = dict(n["position"])
            pos["x"] = float(pos.get("x", 0)) + float(off.get("x", 30))
            pos["y"] = float(pos.get("y", 0)) + float(off.get("y", 30))
            clone["position"] = pos
        g.setdefault("nodes", []).append(clone)
        return g

    # properties + help + _passthrough — no graph change.
    return g
