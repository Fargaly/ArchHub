"""Direct test of the Stage 2 C# scaffold against Revit MCP — no LLM
in the loop. If this passes we know the scaffold itself is correct;
the LLM-generation step is the failure point and needs a different
prompt strategy. Cleans up after itself."""
import json
import urllib.request

BASE = "http://localhost:48884"

CREATE_CSHARP = r"""
var levels = new FilteredElementCollector(Doc).OfClass(typeof(Level))
    .Cast<Level>().ToList();
ViewFamilyType planType = new FilteredElementCollector(Doc)
    .OfClass(typeof(ViewFamilyType)).Cast<ViewFamilyType>()
    .First(v => v.ViewFamily == ViewFamily.FloorPlan);
var existingPlanNames = new HashSet<string>(
    new FilteredElementCollector(Doc).OfClass(typeof(ViewPlan))
        .Cast<ViewPlan>().Where(v => !v.IsTemplate).Select(v => v.Name));
int created = 0; int skipped = 0;
var madeNames = new List<string>();
foreach (var lvl in levels) {
    string name = "ArchHubTest - " + lvl.Name + " - Plan";
    if (existingPlanNames.Contains(name)) { skipped++; continue; }
    var v = ViewPlan.Create(Doc, planType.Id, lvl.Id);
    v.Name = name;
    created++;
    madeNames.Add(name);
}
result = new { created = created, skipped = skipped, names = madeNames };
"""

CLEANUP_CSHARP = r"""
var victims = new FilteredElementCollector(Doc).OfClass(typeof(ViewPlan))
    .Cast<ViewPlan>().Where(v => !v.IsTemplate && v.Name.StartsWith("ArchHubTest - "))
    .ToList();
var names = victims.Select(v => v.Name).ToList();
foreach (var v in victims) Doc.Delete(v.Id);
result = new { deleted = victims.Count, names = names };
"""


def call(code, tx_name):
    req = urllib.request.Request(
        BASE + "/exec",
        data=json.dumps({"code": code, "transaction_name": tx_name}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def main():
    print("=== CREATE ===")
    res = call(CREATE_CSHARP, "ArchHubTest: stage 2 plans")
    print(json.dumps(res, indent=2)[:800])
    print()
    print("=== CLEANUP ===")
    res = call(CLEANUP_CSHARP, "ArchHubTest: cleanup")
    print(json.dumps(res, indent=2)[:800])


if __name__ == "__main__":
    main()
