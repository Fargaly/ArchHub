import json,hashlib
from pathlib import Path
root=Path.cwd(); evidence=root/'05.EVIDENCE'
registry=json.loads((evidence/'acompiler-intents.json').read_text(encoding='utf-8'))
refs=json.loads((evidence/'repo-layout-references.json').read_text(encoding='utf-8'))
assert not refs['errors']
assert sum(refs['scanned_files'].values())==1909
manifest=(evidence/'repo-layout-source-manifest.txt').read_bytes()
measurement=json.loads((evidence/'repo-layout-source-measurement.json').read_text(encoding='utf-8-sig'))
assert hashlib.sha256(manifest).hexdigest()==measurement['manifest_sha256']
rows=manifest.decode().splitlines()[5:]
assert len(rows)==measurement['files']==578
size=0
for line in rows:
    role,native,length,sha=line.split('\t')
    if native.startswith(('nodelang/','app/','bridges/')) or native in {'colleague_setup.py','archhub.ico'}: path=root/'01.APP'/native
    elif native.startswith(('tools/','installer/','packaging/')): path=root/'03.TOOLS'/native
    elif native.startswith('docs/'): path=root/'04.DOCS'/native[5:]
    else: path=root/native
    content=path.read_bytes(); assert len(content)==int(length) and hashlib.sha256(content).hexdigest()==sha, native
    size+=len(content)
assert size==measurement['bytes']
normalized=(evidence/'repo-layout-payload-rows.txt').read_bytes()
assert hashlib.sha256(normalized).hexdigest()==measurement['native_rows_sha256']
assert sorted(normalized.decode().splitlines())==sorted(rows)
for p in evidence.glob('repo-layout-*'):
    assert p.relative_to(root).as_posix() in registry['intents']['NOGRAPH']['scope'], p.name
print('PASS JSON records and NOGRAPH registration')
print('PASS inventory: 1909 text files, zero read errors')
print('PASS source payload: 578 native paths, 22180710 bytes, every SHA matches source')
print('PASS raw manifest SHA and sorted native payload SHA')
print('NOT RUN application tests: Phase 1 evidence only; no product source changed')
