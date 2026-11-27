"""Before/after: compare the everything crawl of the installed build with the crawl of a candidate.

    python -B 03.TOOLS/tools/real_app_check/crawl_compare.py <installed crawl.json> <candidate crawl.json> [--removed <json>] [--out <json>]

A control that worked on the installed build (did its action, opened a place, a dialog or a menu) fails the
candidate when, on the candidate, it is gone, dead, raises an error, opens a retired standalone page, or is covered.
A surface that opened on the installed build and does not open on the candidate fails it too. A control removed on
purpose is named in --removed ({"<key>": "<why>"}) and reported as removed, never silently. Exit 1 on any regression.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

WORKED = {'did-its-action', 'did-its-action(stubbed-effect)', 'opened-a-design-place', 'opened-dialog-or-menu'}
BROKEN = {'DEAD', 'error', 'opened-a-standalone-page', 'NOT-FOUND', 'COVERED'}


def key_of(surface: str, size: str, row: dict) -> str:
    """The crawl's own key, or the same identity for rows recorded before keys existed."""
    if row.get('key'):
        return row['key']
    name = re.sub(r'\d+([.:,]\d+)*', '#', str(row.get('name', '')))
    return '|'.join([surface, size, name, row.get('design') or '', str(row.get('nth', 0))])


def inventory(crawl: dict) -> tuple[dict, dict]:
    surfaces, controls = {}, {}
    for block in crawl.get('all', []):
        where = (block['surface'], block['size'])
        surfaces[where] = block.get('opened', True)
        for row in block.get('rows', []):
            if row.get('name'):
                controls[key_of(*where, row)] = row
    return surfaces, controls


def compare(installed: dict, candidate: dict, removed: dict | None = None) -> dict:
    removed = removed or {}
    before_surfaces, before = inventory(installed)
    after_surfaces, after = inventory(candidate)
    regressions, removed_on_purpose, fixed = [], [], []
    for where, opened in before_surfaces.items():
        if opened and not after_surfaces.get(where, False):
            regressions.append({'key': '|'.join(where), 'was': 'opened', 'now': 'surface gone' if where not in after_surfaces else 'does not open'})
    for key, row in before.items():
        if row.get('cls') not in WORKED:
            continue
        now = after.get(key)
        if key in removed:
            removed_on_purpose.append({'key': key, 'why': removed[key]})
        elif now is None:
            if after_surfaces.get(tuple(key.split('|')[:2])):  # its surface opened: the control itself is gone
                regressions.append({'key': key, 'was': row['cls'], 'now': 'gone'})
        elif now.get('cls') not in WORKED:
            regressions.append({'key': key, 'was': row['cls'], 'now': now['cls'], 'why': now.get('why') or now.get('status') or '', 'shot': now.get('shot', '')})
    for key, row in after.items():
        if row.get('cls') in WORKED and before.get(key, {}).get('cls') in BROKEN:
            fixed.append({'key': key, 'was': before[key]['cls'], 'now': row['cls']})
    return {'pass': not regressions, 'controls_installed': len(before), 'controls_candidate': len(after),
            'worked_installed': sum(r.get('cls') in WORKED for r in before.values()),
            'worked_candidate': sum(r.get('cls') in WORKED for r in after.values()),
            'regressions': regressions, 'removed_on_purpose': removed_on_purpose, 'fixed': fixed}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('installed', type=Path)
    parser.add_argument('candidate', type=Path)
    parser.add_argument('--removed', type=Path, help='JSON {"<control key>": "<why it was removed on purpose>"}')
    parser.add_argument('--out', type=Path)
    args = parser.parse_args(argv)
    read = lambda path: json.loads(path.read_text(encoding='utf-8'))
    result = compare(read(args.installed), read(args.candidate), read(args.removed) if args.removed else None)
    if args.out:
        args.out.write_text(json.dumps(result, indent=1), encoding='utf-8')
    print('BEFORE/AFTER %s: installed %d controls (%d worked), candidate %d controls (%d worked), %d regressions, %d removed on purpose, %d fixed'
          % ('PASS' if result['pass'] else 'FAIL', result['controls_installed'], result['worked_installed'], result['controls_candidate'],
             result['worked_candidate'], len(result['regressions']), len(result['removed_on_purpose']), len(result['fixed'])))
    for row in result['regressions']:
        print('REGRESSION %s: was %s, now %s %s' % (row['key'], row['was'], row['now'], row.get('why', '')))
    return 0 if result['pass'] else 1


if __name__ == '__main__':
    sys.exit(main())
