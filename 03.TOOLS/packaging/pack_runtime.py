"""Pack the connector's pure-Python runtime as two zips read by zipimport (as zipapp, PyInstaller
and Python's own embeddable distribution do with python3XY.zip).

Every connector start used to open and stat hundreds of files (the MCP SDK, pydantic, jsonschema,
httpx, anyio... and the standard library). On a machine where each file access costs milliseconds
that alone took 2.8-4.3 s; from two zips it takes about 1.1 s. Native extension modules (.pyd) stay
files on the normal path; package data files (JSON schemas, certificates) travel inside the zip.

    python pack_runtime.py --out <app>/packed
writes site.zip, stdlib.zip and stamp.json (the interpreter they were built for). nodelang adds
them to sys.path only in a connector process and only when the stamp matches the interpreter.
"""
from __future__ import annotations

import argparse
import json
import site
import sys
import sysconfig
import zipfile
from pathlib import Path

PACK_NODE = {'id': 'runtime.pack', 'params': {'stdlib_skip': ['site-packages', 'test', 'idlelib', 'tkinter',
                                                              'turtledemo', 'ensurepip', '__pycache__']}}


def _native(folder):
    return any(folder.rglob('*.pyd')) or any(folder.rglob('*.so'))


def pack_site(site_packages, out):
    written = []
    with zipfile.PyZipFile(out, 'w') as archive:
        for entry in sorted(Path(site_packages).iterdir()):
            if entry.name.endswith(('.dist-info', '.egg-info')) or entry.name.startswith(('__pycache__', '_distutils')):
                continue
            if entry.is_dir() and (entry / '__init__.py').exists() and not _native(entry):
                archive.writepy(str(entry))
                for data in entry.rglob('*'):
                    if data.is_file() and data.suffix not in ('.py', '.pyc') and '__pycache__' not in data.parts:
                        archive.write(data, data.relative_to(site_packages).as_posix())
                written.append(entry.name)
            elif entry.is_file() and entry.suffix == '.py':
                archive.writepy(str(entry))
                written.append(entry.name)
    return written


def pack_stdlib(out):
    library = Path(sysconfig.get_paths()['stdlib'])
    skip = set(PACK_NODE['params']['stdlib_skip'])
    with zipfile.PyZipFile(out, 'w') as archive:
        for entry in sorted(library.iterdir()):
            if entry.name in skip:
                continue
            if (entry.is_dir() and (entry / '__init__.py').exists()) or entry.suffix == '.py':
                archive.writepy(str(entry))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--out', required=True)
    parser.add_argument('--site-packages', default=next(p for p in site.getsitepackages() if p.endswith('site-packages')))
    args = parser.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    packed = pack_site(Path(args.site_packages), out / 'site.zip')
    pack_stdlib(out / 'stdlib.zip')
    (out / 'stamp.json').write_text(json.dumps({'python': sys.version, 'hexversion': sys.hexversion,
                                                'packages': packed}, indent=1), encoding='utf-8')
    print('packed %d site entries and the standard library into %s' % (len(packed), out))
    return 0


if __name__ == '__main__':
    sys.exit(main())
