"""Merge per-file junit reports into the one report the court reads.

Tests are run one file at a time so a single hanging module cannot take the
whole measurement down. This stitches the parts back into one document; a file
that produced no part is simply absent, and its court stays NOT JUDGED.
"""
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
PARTS = HERE / "junit-parts"
OUT = HERE / "junit-tests_replica.xml"


def main() -> int:
    suite = ET.Element("testsuite", name="pytest")
    totals = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    parts = sorted(PARTS.glob("*.xml"))
    for part in parts:
        try:
            tree = ET.parse(part)
        except ET.ParseError:
            print("  UNREADABLE %s" % part.name)
            continue
        for case in tree.iter("testcase"):
            suite.append(case)
            totals["tests"] += 1
            if case.find("failure") is not None:
                totals["failures"] += 1
            elif case.find("error") is not None:
                totals["errors"] += 1
            elif case.find("skipped") is not None:
                totals["skipped"] += 1
    for k, v in totals.items():
        suite.set(k, str(v))
    root = ET.Element("testsuites", name="pytest tests")
    root.append(suite)
    ET.ElementTree(root).write(OUT, encoding="utf-8", xml_declaration=True)
    print("MERGED %d part(s) -> %s" % (len(parts), OUT.name))
    print("  tests %(tests)d  failures %(failures)d  errors %(errors)d  skipped %(skipped)d" % totals)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
