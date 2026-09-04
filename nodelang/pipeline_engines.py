"""Effect engines: what a wired pipeline node DOES when the graph runs.

The stem evaluator stays pure -- these are the injected effects, and the
entry point that boots the server decides they exist (the same law as the
clean host invoker: a runtime given no engines can refuse honestly, one
that acquired a default could touch a machine nobody chose).

Every engine takes (parameters, feeds) and returns (outputs, display):
outputs feed the wires; display is the one line the node card shows.
Lines travel as lists of [x1, y1, x2, y2] in millimetres.
"""
from __future__ import annotations

import json
from typing import Mapping


def _local_input_path(path: str, *, label: str) -> str:
    """An input file the graph names must be a local file, never a UNC share.

    A graph is data anyone can hand you; a UNC path in it makes this process
    authenticate to a remote SMB host (NTLM credential leak) and read whatever
    sits there. Local drives only, and the file must exist.
    """
    text = str(path or "").strip()
    if not text:
        raise ValueError("no %s; set it or wire a file in" % label)
    if text.startswith(("\\\\", "//")) or text.upper().startswith(("\\\\?\\UNC", "SMB:", "FILE:")):
        raise ValueError("%s must be a local file, not a network share" % label)
    import os as _os
    if not _os.path.isfile(text):
        raise ValueError("%s does not exist: %s" % (label, text))
    return text


def _lines_of(value: object) -> list:
    if isinstance(value, str):
        value = json.loads(value or "[]")
    if not isinstance(value, list):
        raise ValueError("lines input is not a list")
    return value


def sketch_lines(params: Mapping[str, object], feeds: Mapping[str, object]):
    """Sketch image -> straight line segments (OpenCV, deterministic)."""
    import cv2
    import numpy

    path = _local_input_path(feeds.get("in") or params.get("image_path"), label="image_path")
    image = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise ValueError("could not read image: %s" % path)
    scale = float(params.get("mm_per_pixel") or 10.0)
    blurred = cv2.GaussianBlur(image, (5, 5), 0)
    edges = cv2.Canny(blurred, 50, 150)
    segments = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=numpy.pi / 180.0,
        threshold=int(params.get("threshold") or 60),
        minLineLength=int(params.get("min_length") or 40),
        maxLineGap=int(params.get("max_gap") or 8),
    )
    lines = []
    for row in (segments if segments is not None else ()):
        x1, y1, x2, y2 = (float(v) for v in row[0])
        lines.append([x1 * scale, y1 * scale, x2 * scale, y2 * scale])
    return {"out": lines}, "%d lines from %s" % (
        len(lines), path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1])


def cad_lines(params: Mapping[str, object], feeds: Mapping[str, object]):
    """DXF file -> the same line segments the sketch engine emits."""
    import ezdxf

    path = _local_input_path(feeds.get("in") or params.get("file_path"), label="file_path")
    wanted_layer = str(params.get("layer") or "").strip()
    document = ezdxf.readfile(path)
    lines = []
    for entity in document.modelspace():
        kind = entity.dxftype()
        if wanted_layer and entity.dxf.layer != wanted_layer:
            continue
        if kind == "LINE":
            s, e = entity.dxf.start, entity.dxf.end
            lines.append([s.x, s.y, e.x, e.y])
        elif kind == "LWPOLYLINE":
            points = list(entity.get_points("xy"))
            for a, b in zip(points, points[1:]):
                lines.append([a[0], a[1], b[0], b[1]])
            if entity.closed and len(points) > 2:
                lines.append([points[-1][0], points[-1][1],
                              points[0][0], points[0][1]])
    return {"out": lines}, "%d lines from %s" % (
        len(lines), path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1])


def watch_lines(params: Mapping[str, object], feeds: Mapping[str, object]):
    """Pass the lines through and show what flowed -- the founder's eyes."""
    lines = _lines_of(feeds.get("in"))
    xs = [v for line in lines for v in (line[0], line[2])]
    ys = [v for line in lines for v in (line[1], line[3])]
    extent = ""
    if lines:
        extent = " · %.1fm x %.1fm" % (
            (max(xs) - min(xs)) / 1000.0, (max(ys) - min(ys)) / 1000.0)
    return {"out": lines}, "%d lines%s" % (len(lines), extent)


def revit_sessions(params: Mapping[str, object], feeds: Mapping[str, object]):
    """Every Revit session listening right now, or the honest zero."""
    from .clean_revit_adapter import live_sessions

    sessions = live_sessions()
    if not sessions:
        return {"out": []}, "no Revit session is listening"
    label = ", ".join(
        "%s:%s" % (s.get("document") or "no document", s["port"])
        for s in sessions)
    return {"out": sessions}, "%d session(s): %s" % (len(sessions), label)


_BUILD_WALLS = """
var data = %s;
var levelName = %s;
double heightMm = %s;
Level level = null;
foreach (Level lv in new FilteredElementCollector(Doc).OfClass(typeof(Level)))
    if (level == null || lv.Name == levelName) { if (lv.Name == levelName || level == null) level = lv; }
if (level == null) throw new Exception("no level in the model");
var built = new List<int>();
using (var t = new Transaction(Doc, "ArchHub build walls")) {
    t.Start();
    foreach (var seg in data) {
        double x1 = seg[0] / 304.8, y1 = seg[1] / 304.8;
        double x2 = seg[2] / 304.8, y2 = seg[3] / 304.8;
        if (Math.Abs(x2-x1) < 1e-6 && Math.Abs(y2-y1) < 1e-6) continue;
        var line = Line.CreateBound(new XYZ(x1, y1, 0), new XYZ(x2, y2, 0));
        var wall = Wall.Create(Doc, line, level.Id, false);
        var hp = wall.get_Parameter(BuiltInParameter.WALL_USER_HEIGHT_PARAM);
        if (hp != null) hp.Set(heightMm / 304.8);
        built.Add(wall.Id.IntegerValue);
    }
    t.Commit();
}
result = built;
"""


def revit_build_walls(params: Mapping[str, object],
                      feeds: Mapping[str, object]):
    """Build one wall per wired line segment inside the live session."""
    from .clean_revit_adapter import _call, _session_for, live_sessions

    lines = _lines_of(feeds.get("in"))
    if not lines:
        raise ValueError("no lines are wired in; nothing to build")
    sessions = [s for s in live_sessions() if s.get("revit_version")]
    wanted = str(params.get("session") or "").strip()
    if not wanted:
        listed = ", ".join(
            "%s (%s)" % (s["port"], s.get("document") or "no document")
            for s in sessions) or "none listening"
        raise ValueError(
            "set the session parameter to the Revit port to build into"
            " -- live: %s" % listed)
    session = _session_for(wanted, sessions)
    script = _BUILD_WALLS % (
        json.dumps([[float(v) for v in line[:4]] for line in lines]),
        json.dumps(str(params.get("level") or "")),
        json.dumps(float(params.get("height_mm") or 3000.0)),
    )
    answer = _call(session["port"], "/exec", {
        "code": script, "transaction_name": "ArchHub build walls"})
    if answer.get("status") != "ok":
        raise ValueError("Revit refused: %s" % answer.get("error"))
    built = answer.get("result") or []
    return {"out": built}, "built %d walls on %s" % (
        len(built), session.get("document") or session["port"])




def _brain_call(tool: str, arguments: Mapping[str, object]) -> object:
    """One tools/call against the live brain daemon; SSE frame or JSON."""
    import urllib.request

    body = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": tool, "arguments": dict(arguments)},
    }).encode("utf-8")
    request = urllib.request.Request(
        "http://127.0.0.1:8473/mcp", data=body,
        headers={"Content-Type": "application/json",
                 "Accept": "application/json, text/event-stream"},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        raw = response.read().decode("utf-8")
    payload = None
    for line in raw.splitlines():
        if line.startswith("data: "):
            payload = json.loads(line[6:])
    if payload is None:
        payload = json.loads(raw)
    if payload.get("error"):
        raise ValueError("brain refused: %s" % payload["error"].get("message"))
    content = (payload.get("result") or {}).get("content") or []
    texts = [item.get("text", "") for item in content
             if item.get("type") == "text"]
    return chr(10).join(texts)


def brain_recall(params: Mapping[str, object], feeds: Mapping[str, object]):
    """Ask the live brain for context on a prompt -- the founder's memory."""
    prompt = str(feeds.get("in") or params.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("set the prompt parameter or wire text in")
    answer = str(_brain_call("brain.context", {"prompt": prompt}))
    lines = [line for line in answer.splitlines() if line.strip()]
    return {"out": answer}, (
        "%d context line(s) for %r" % (len(lines), prompt[:32])
    )


def brain_facts(params: Mapping[str, object], feeds: Mapping[str, object]):
    """How many facts the live brain holds right now."""
    answer = str(_brain_call("brain.list_facts", {}))
    count = answer.count(chr(10)) + 1 if answer.strip() else 0
    return {"out": answer}, "%d fact row(s) in the brain" % count




def revit_read(params: Mapping[str, object], feeds: Mapping[str, object]):
    """Run one declared Revit read against a chosen session."""
    from .clean_revit_adapter import invoke, live_sessions

    op = str(params.get("operation") or "revit.list_walls").strip()
    sessions = [s for s in live_sessions() if s.get("revit_version")]
    if not sessions:
        raise ValueError("no Revit session is listening")
    answer = invoke(op, {"instance": str(params.get("session") or "").strip()})
    rows = answer.get("result") or []
    return {"out": rows}, "%d row(s) from %s" % (len(rows), op)


def cad_lines_from_host(params: Mapping[str, object],
                        feeds: Mapping[str, object]):
    """Read line work from the LIVE AutoCAD session, not a file."""
    from .clean_revit_adapter import _call, live_sessions

    acad = [
        s for s in live_sessions()
        if isinstance(s.get("document"), dict)
        and s["document"].get("acad_version")
    ]
    if not acad:
        raise ValueError("no AutoCAD session is listening")
    layer = str(params.get("layer") or "").strip()
    script = """
var rows = new List<Dictionary<string,object>>();
var db = Doc.Database;
using (var tr = db.TransactionManager.StartTransaction()) {
    var bt = (BlockTable)tr.GetObject(db.BlockTableId, OpenMode.ForRead);
    var ms = (BlockTableRecord)tr.GetObject(bt[BlockTableRecord.ModelSpace], OpenMode.ForRead);
    foreach (ObjectId id in ms) {
        var ent = tr.GetObject(id, OpenMode.ForRead) as Entity;
        if (ent == null) continue;
        var ln = ent as Line;
        if (ln == null) continue;
        rows.Add(new Dictionary<string,object>{
            {"x1", ln.StartPoint.X}, {"y1", ln.StartPoint.Y},
            {"x2", ln.EndPoint.X}, {"y2", ln.EndPoint.Y},
            {"layer", ent.Layer}
        });
    }
    tr.Commit();
}
result = rows;
"""
    answer = _call(acad[-1]["port"], "/exec", {
        "code": script, "transaction_name": "ArchHub read lines"})
    if answer.get("status") != "ok":
        raise ValueError("AutoCAD refused: %s" % answer.get("error"))
    lines = []
    for row in (answer.get("result") or []):
        if layer and str(row.get("layer") or "") != layer:
            continue
        lines.append([
            float(row["x1"]), float(row["y1"]),
            float(row["x2"]), float(row["y2"]),
        ])
    return {"out": lines}, "%d lines from the live drawing" % len(lines)


def connector_status(params: Mapping[str, object],
                     feeds: Mapping[str, object]):
    """One connector's real state, as a node on the canvas."""
    wanted = str(params.get("connector") or "").strip().casefold()
    catalogue = probe_connectors()
    if wanted:
        catalogue = [c for c in catalogue if c["id"] == wanted]
        if not catalogue:
            raise ValueError("no connector named %r" % wanted)
    live = [c for c in catalogue if c["state"] in ("connected", "listening")]
    return (
        {"out": catalogue},
        "%d/%d live · %s" % (
            len(live), len(catalogue),
            ", ".join("%s %s" % (c["name"], c["state"]) for c in catalogue[:4]),
        ),
    )




def _skill_description(text: str) -> str:
    """The front-matter description, including a YAML folded or literal block.

    A description written as "description: >" continues on the indented
    lines below it; reading only the first line rendered one of the five
    binding laws as a lone ">" in the composed thinking chain.
    """
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if not line.startswith("description:"):
            continue
        head = line.split(":", 1)[1].strip()
        if head and head not in (">", "|", ">-", "|-"):
            return head[:240]
        parts = []
        for continuation in lines[index + 1:]:
            if continuation.strip() == "" and not parts:
                continue
            if continuation.startswith((chr(32), chr(9))):
                parts.append(continuation.strip())
            else:
                break
        return " ".join(parts)[:240]
    return ""


def skills_catalogue(params: Mapping[str, object], feeds: Mapping[str, object]):
    """Every skill this machine holds, as one list any agent can read.

    The shared library: Claude's skills, Codex's skills, and anything the
    brain has minted -- one answer, one shape, so an agent mounting
    ArchHub on ANY machine asks one node instead of hunting folders.
    """
    import os
    from pathlib import Path

    wanted = str(params.get("match") or "").strip().casefold()
    home = Path(os.path.expanduser("~"))
    shipped = Path(__file__).resolve().parents[1] / "skills"
    found = []
    seen = set()
    # The founder's live folders first (his own edits win on his own desk),
    # then the library the installer ships, so a colleague's machine holds
    # the same skills he has.
    for root, source in (
        (home / ".claude" / "skills", "claude"),
        (home / ".codex" / "skills", "codex"),
        (shipped / "claude", "claude"),
        (shipped / "codex", "codex"),
    ):
        if not root.is_dir():
            continue
        for entry in sorted(root.iterdir()):
            manifest = entry / "SKILL.md"
            if not manifest.is_file():
                continue
            if (source, entry.name) in seen:
                continue
            seen.add((source, entry.name))
            text = manifest.read_text(encoding="utf-8", errors="replace")
            description = _skill_description(text)
            record = {
                "name": entry.name, "source": source,
                "description": description,
                "path": str(manifest),
            }
            if wanted and wanted not in (
                entry.name + " " + description
            ).casefold():
                continue
            found.append(record)
    return (
        {"out": found},
        "%d skill(s)%s" % (
            len(found), " matching %r" % wanted if wanted else "",
        ),
    )


def skill_read(params: Mapping[str, object], feeds: Mapping[str, object]):
    """One skill's full instructions, ready to hand to any agent."""
    name = str(params.get("skill") or "").strip()
    if not name:
        raise ValueError("set the skill parameter to a skill name")
    catalogue, _ = skills_catalogue({"match": name}, {})
    entries = catalogue["out"]
    if not entries:
        raise ValueError("no skill named %r on this machine" % name)
    exact = [e for e in entries if e["name"].casefold() == name.casefold()]
    chosen = (exact or entries)[0]
    from pathlib import Path

    body = Path(chosen["path"]).read_text(encoding="utf-8", errors="replace")
    return (
        {"out": body},
        "%s/%s · %d chars" % (chosen["source"], chosen["name"], len(body)),
    )


def thinking_chain(params: Mapping[str, object], feeds: Mapping[str, object]):
    """The founder's skills, composed into ONE ordered thinking algorithm.

    Not a pile of separate documents: the binding laws first, then the
    method skills in the order they must be obeyed, then the domain
    skills that apply to the work at hand. This is the single text an
    agent mounts to inherit how the founder works.
    """
    catalogue, _ = skills_catalogue({}, {})
    entries = {e["name"]: e for e in catalogue["out"]}
    topic = str(params.get("topic") or "").strip().casefold()
    # The spine: laws that bind EVERY agent, in the order they apply.
    spine = [
        "ship-discipline", "solution-only", "ponytail",
        "agent-failure-rca", "graphify",
    ]
    stages = []
    for name in spine:
        entry = entries.get(name)
        if entry is None:
            continue
        stages.append({
            "stage": "law", "name": name,
            "description": entry["description"],
        })
    for name, entry in sorted(entries.items()):
        if name in spine:
            continue
        haystack = (name + " " + entry["description"]).casefold()
        if topic and topic not in haystack:
            continue
        stages.append({
            "stage": "domain", "name": name,
            "description": entry["description"],
        })
    laws = [s for s in stages if s["stage"] == "law"]
    lines = ["THINKING CHAIN%s" % (" for %r" % topic if topic else "")]
    lines.append("")
    lines.append("BINDING LAWS (in order, every agent, every task):")
    for index, item in enumerate(laws, 1):
        lines.append("  %d. %s -- %s" % (index, item["name"],
                                         item["description"][:150]))
    lines.append("")
    lines.append("APPLICABLE SKILLS:")
    for item in stages:
        if item["stage"] == "law":
            continue
        lines.append("  - %s: %s" % (item["name"], item["description"][:120]))
    return (
        {"out": chr(10).join(lines)},
        "%d law(s) + %d skill(s) composed" % (
            len(laws), len(stages) - len(laws),
        ),
    )


PIPELINE_ENGINES = {
    "vision.sketch_lines": sketch_lines,
    "cad.read_lines": cad_lines,
    "cad.host_lines": cad_lines_from_host,
    "lines.watch": watch_lines,
    "revit.sessions": revit_sessions,
    "revit.read": revit_read,
    "revit.build_walls": revit_build_walls,
    "brain.recall": brain_recall,
    "brain.facts": brain_facts,
    "connector.status": connector_status,
    "skills.catalogue": skills_catalogue,
    "skills.read": skill_read,
    "skills.thinking_chain": thinking_chain,
}



def probe_connectors():
    """Every connector the design names, each with its REAL state now.

    connected = answering a live handshake; listening = a port is open;
    installed = present on this machine but not attached; absent = not
    found. Nothing is guessed and nothing is hidden.
    """
    import os
    import socket
    import subprocess

    found = []

    def port_open(port, host="127.0.0.1", timeout=0.15):
        probe = socket.socket()
        probe.settimeout(timeout)
        try:
            return probe.connect_ex((host, port)) == 0
        finally:
            probe.close()

    from .clean_revit_adapter import live_sessions
    revit = []
    acad = []
    try:
        for session in live_sessions():
            document = session.get("document")
            if isinstance(document, dict) and document.get("acad_version"):
                acad.append(session)
            else:
                revit.append(session)
    except Exception:
        pass
    # Every row says whether the product can DRIVE the host, not only see it.
    # A row with no drive is never shown green: the founder's rule is that
    # nothing appears that is not wired.
    found.append({
        "id": "revit", "name": "Revit", "drive": "revit.build_walls",
        "state": "connected" if revit else "absent",
        "detail": (
            "%d session(s)" % len(revit) if revit
            else "no session listening on 48884-48899"
        ),
    })
    found.append({
        "id": "autocad", "name": "AutoCAD", "drive": "cad.host_lines",
        "state": "connected" if acad else "absent",
        "detail": (
            "%d session(s)" % len(acad) if acad
            else "no session listening"
        ),
    })
    found.append({
        "id": "rhino", "name": "Rhino", "drive": "",
        "state": "reachable" if port_open(9879) else "absent",
        "detail": (
            "bridge on :9879 · no wire in this build"
            if port_open(9879)
            else "bridge not running · no wire in this build"
        ),
    })
    appdata = os.environ.get("APPDATA", "")
    speckle_installed = bool(appdata) and os.path.isdir(
        os.path.join(appdata, "Speckle")
    )
    found.append({
        "id": "speckle", "name": "Speckle", "drive": "",
        "state": "installed" if speckle_installed else "absent",
        "detail": (
            "Manager installed · no wire in this build"
            if speckle_installed else "Manager not found"
        ),
    })
    # Outlook, Dropbox and Blender used to be reported CONNECTED from a
    # tasklist string match -- a process being open is not a connection,
    # and nothing in the runtime can drive any of them. They are not
    # listed until a wire exists.
    return found


__all__ = ["PIPELINE_ENGINES", "probe_connectors"]
