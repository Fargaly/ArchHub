"""Shipped Studio text is real UTF-8: no cp1252 double-decoded sequences such as 'â€¦' or 'Â·'."""
import re
from pathlib import Path

STUDIO = Path(__file__).resolve().parents[2] / '01.APP' / 'nodelang' / 'studio'
# UTF-8 bytes of … — ’ “ · é etc. read as cp1252 start with these pairs.
MOJIBAKE = re.compile('â€|Â[ -¿]|Ã[\u0080-¿‘-›]')


def test_studio_sources_have_no_mojibake():
    found = []
    for path in sorted(STUDIO.rglob('*')):
        if path.suffix not in {'.js', '.jsx', '.css', '.html', '.json'} or 'vendor' in path.parts:
            continue
        for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            for match in MOJIBAKE.finditer(line):
                found.append(f'{path.relative_to(STUDIO)}:{number}: {match.group()!r}')
    assert not found, 'Mojibake in shipped Studio text:\n' + '\n'.join(found[:40])
