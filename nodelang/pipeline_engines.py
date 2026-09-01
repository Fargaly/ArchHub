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

    path = str(feeds.get("in") or params.get("image_path") or "").strip()
    if not path:
        raise ValueError("no image path; set image_path or wire a file in")
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

    path = str(feeds.get("in") or params.get("file_path") or "").strip()
    if not path:
        raise ValueError("no file path; set file_path or wire a file in")
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


PIPELINE_ENGINES = {
    "vision.sketch_lines": sketch_lines,
    "cad.read_lines": cad_lines,
    "lines.watch": watch_lines,
    "revit.sessions": revit_sessions,
    "revit.build_walls": revit_build_walls,
}

__all__ = ["PIPELINE_ENGINES"]
