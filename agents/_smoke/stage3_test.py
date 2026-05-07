"""Stage 3 — schedules. Three sub-scripts:
  A. Inspect schedule + Mark state (read-only)
  B. Auto-number empty Marks (D-001, W-001, R-001) — write
  C. Cleanup: revert any new Marks we wrote
"""
import json
import urllib.request

BASE = "http://localhost:48884"

INSPECT = r"""
var doors = new FilteredElementCollector(Doc).OfCategory(BuiltInCategory.OST_Doors)
    .WhereElementIsNotElementType().ToElements();
var windows = new FilteredElementCollector(Doc).OfCategory(BuiltInCategory.OST_Windows)
    .WhereElementIsNotElementType().ToElements();
var rooms = new FilteredElementCollector(Doc).OfCategory(BuiltInCategory.OST_Rooms)
    .WhereElementIsNotElementType().ToElements();

int doorsBlankMark = 0, windowsBlankMark = 0, roomsBlankNumber = 0;
foreach (var d in doors) {
    var p = d.get_Parameter(BuiltInParameter.ALL_MODEL_MARK);
    if (p != null && string.IsNullOrEmpty(p.AsString())) doorsBlankMark++;
}
foreach (var w in windows) {
    var p = w.get_Parameter(BuiltInParameter.ALL_MODEL_MARK);
    if (p != null && string.IsNullOrEmpty(p.AsString())) windowsBlankMark++;
}
foreach (var r in rooms) {
    var p = r.get_Parameter(BuiltInParameter.ROOM_NUMBER);
    if (p != null && string.IsNullOrEmpty(p.AsString())) roomsBlankNumber++;
}

result = new {
    doors = doors.Count, doors_blank_mark = doorsBlankMark,
    windows = windows.Count, windows_blank_mark = windowsBlankMark,
    rooms = rooms.Count, rooms_blank_number = roomsBlankNumber,
};
"""

WRITE = r"""
// Auto-number first 3 BLANK marks of each. Filter before taking.
var prefix = "AHTEST-";
int doorsTouched = 0, windowsTouched = 0, roomsTouched = 0;

var blankDoors = new FilteredElementCollector(Doc)
    .OfCategory(BuiltInCategory.OST_Doors).WhereElementIsNotElementType()
    .Cast<Element>().Where(el => {
        var p = el.get_Parameter(BuiltInParameter.ALL_MODEL_MARK);
        return p != null && !p.IsReadOnly && string.IsNullOrEmpty(p.AsString());
    }).Take(3).ToList();
foreach (var d in blankDoors) {
    var p = d.get_Parameter(BuiltInParameter.ALL_MODEL_MARK);
    doorsTouched++;
    p.Set(prefix + "D-" + doorsTouched.ToString("D3"));
}

var blankWindows = new FilteredElementCollector(Doc)
    .OfCategory(BuiltInCategory.OST_Windows).WhereElementIsNotElementType()
    .Cast<Element>().Where(el => {
        var p = el.get_Parameter(BuiltInParameter.ALL_MODEL_MARK);
        return p != null && !p.IsReadOnly && string.IsNullOrEmpty(p.AsString());
    }).Take(3).ToList();
foreach (var w in blankWindows) {
    var p = w.get_Parameter(BuiltInParameter.ALL_MODEL_MARK);
    windowsTouched++;
    p.Set(prefix + "W-" + windowsTouched.ToString("D3"));
}

var blankRooms = new FilteredElementCollector(Doc)
    .OfCategory(BuiltInCategory.OST_Rooms).WhereElementIsNotElementType()
    .Cast<Element>().Where(el => {
        var p = el.get_Parameter(BuiltInParameter.ROOM_NUMBER);
        return p != null && !p.IsReadOnly && string.IsNullOrEmpty(p.AsString());
    }).Take(3).ToList();
foreach (var r in blankRooms) {
    var p = r.get_Parameter(BuiltInParameter.ROOM_NUMBER);
    roomsTouched++;
    p.Set(prefix + "R-" + roomsTouched.ToString("D3"));
}

result = new {
    doors_touched = doorsTouched,
    windows_touched = windowsTouched,
    rooms_touched = roomsTouched,
};
"""

CLEANUP = r"""
var prefix = "AHTEST-";
int reverted = 0;

foreach (var d in new FilteredElementCollector(Doc)
    .OfCategory(BuiltInCategory.OST_Doors).WhereElementIsNotElementType()) {
    var p = d.get_Parameter(BuiltInParameter.ALL_MODEL_MARK);
    if (p != null && !p.IsReadOnly && (p.AsString() ?? "").StartsWith(prefix)) {
        p.Set(""); reverted++;
    }
}
foreach (var w in new FilteredElementCollector(Doc)
    .OfCategory(BuiltInCategory.OST_Windows).WhereElementIsNotElementType()) {
    var p = w.get_Parameter(BuiltInParameter.ALL_MODEL_MARK);
    if (p != null && !p.IsReadOnly && (p.AsString() ?? "").StartsWith(prefix)) {
        p.Set(""); reverted++;
    }
}
foreach (var r in new FilteredElementCollector(Doc)
    .OfCategory(BuiltInCategory.OST_Rooms).WhereElementIsNotElementType()) {
    var p = r.get_Parameter(BuiltInParameter.ROOM_NUMBER);
    if (p != null && !p.IsReadOnly && (p.AsString() ?? "").StartsWith(prefix)) {
        p.Set(""); reverted++;
    }
}

result = new { reverted = reverted };
"""


def call(code, tx):
    req = urllib.request.Request(
        BASE + "/exec",
        data=json.dumps({"code": code, "transaction_name": tx}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def main():
    print("=== INSPECT ===")
    print(json.dumps(call(INSPECT, "AHTEST: stage3 inspect"), indent=2))
    print()
    print("=== WRITE (touch first 3 of each) ===")
    print(json.dumps(call(WRITE, "AHTEST: stage3 write"), indent=2))
    print()
    print("=== CLEANUP ===")
    print(json.dumps(call(CLEANUP, "AHTEST: stage3 cleanup"), indent=2))


if __name__ == "__main__":
    main()
