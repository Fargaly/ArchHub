"""BRAINSTORE (D-BRAINSTORE) budget: the one Brain file at realistic scale, on synthetic facts only.

python 03.TOOLS/tools/brain_bench.py 10000 100000
Runs in a throwaway LOCALAPPDATA under the system temp folder and deletes it afterwards; never
reads a real profile. Prints one JSON line per scale: write rate, file size, cold open, query and
correction latency (p50/p95 over 200 queries).
"""
import json
import os
import random
import shutil
import statistics
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / '01.APP'))

WORDS = ('door wall slab ramp core shaft riser sprinkler lobby corridor stair lift parking tower podium '
         'facade glazing mullion beam column screed tile ceiling duct cable tray riser fire exit travel '
         'distance width height clear level basement roof plant room toilet kitchen pantry office meeting '
         'revit sheet view family schedule title block revision cloud comment client consultant mep '
         'structure architecture landscape kerb setback plot area gfa far coverage permit authority').split()


def fact(rng, i):
    words = rng.sample(WORDS, rng.randint(6, 14))
    return '%s is %d mm on level %d (%s)' % (' '.join(words[:4]), rng.randint(100, 9000), rng.randint(0, 40),
                                              ' '.join(words[4:]))


def pct(values, q):
    return round(statistics.quantiles(values, n=100)[q - 1] * 1000, 2)


def run(scale):
    root = Path(tempfile.mkdtemp(prefix='brain-bench-'))
    os.environ['LOCALAPPDATA'] = str(root)
    from nodelang import brain_files
    rng = random.Random(scale)
    try:
        started = time.perf_counter()
        for base in range(0, scale, 1000):
            brain_files.write([{'op': 'add', 'fragment': {'id': 'f%d' % i, 'kind': 'fact', 'text': fact(rng, i)}}
                               for i in range(base, min(scale, base + 1000))])
        write_s = time.perf_counter() - started
        brain_files.close()
        started = time.perf_counter()
        brain_files.call('brain.health', {})
        open_ms = (time.perf_counter() - started) * 1000
        queries, edits = [], []
        for _ in range(200):
            prompt = ' '.join(rng.sample(WORDS, 3))
            started = time.perf_counter()
            brain_files.context(prompt, 8)
            queries.append(time.perf_counter() - started)
        found, stale = 0, 0
        for _ in range(200):
            fid, text = 'f%d' % rng.randrange(scale), fact(rng, 0) + ' corrected %d' % rng.randrange(10**9)
            started = time.perf_counter()
            brain_files.call('brain.edit_fact', {'fragment_id': fid, 'text': text})
            edits.append(time.perf_counter() - started)
            answer = brain_files.context(text, 8)['facts']
            found += any(f['id'] == fid and f['text'] == text for f in answer)
            stale += any(f['id'] == fid and f['text'] != text for f in answer)
        brain_files._db().execute('PRAGMA wal_checkpoint(TRUNCATE)')
        size = sum(p.stat().st_size for p in (root / 'ArchHub' / 'settings').iterdir())
        print(json.dumps({'facts': scale, 'write_facts_per_s': round(scale / write_s), 'file_mb': round(size / 2**20, 1),
                          'cold_open_ms': round(open_ms, 1), 'query_p50_ms': pct(queries, 50),
                          'query_p95_ms': pct(queries, 95), 'correction_p50_ms': pct(edits, 50),
                          'correction_p95_ms': pct(edits, 95), 'corrected_found_top8': '%d/200' % found,
                          'stale_versions_returned': stale}), flush=True)
    finally:
        brain_files.close()
        shutil.rmtree(root, ignore_errors=True)


if __name__ == '__main__':
    for argument in sys.argv[1:] or ['10000']:
        run(int(argument))
