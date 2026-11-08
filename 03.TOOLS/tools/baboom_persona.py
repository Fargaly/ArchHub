"""Generate BABOOM's data-only voice from the human brand book, never from code."""
import argparse
import hashlib
import html
import json
from pathlib import Path
import re


def generate(source):
    raw = source.read_bytes()
    section = re.search(r'<section[^>]*id="s03"[^>]*>(.*?)</section>', raw.decode('utf-8'), re.S).group(1)

    def text(value):
        return html.unescape(re.sub('<[^>]+>', '', value)).strip()

    tables = re.findall(r'<table[^>]*>(.*?)</table>', section, re.S)
    examples = [[text(c) for c in re.findall(r'<td[^>]*>(.*?)</td>', row, re.S)]
                for row in re.findall(r'<tr>(.*?)</tr>', tables[0], re.S)]
    moments = [[text(c) for c in re.findall(r'<td[^>]*>(.*?)</td>', row, re.S)]
               for row in re.findall(r'<tr>(.*?)</tr>', tables[1], re.S)]
    chips = re.findall(r'<p class="chips[^"]*">(.*?)</p>', section, re.S)
    return {'name': 'BABOOM', 'role': 'AI assistant',
            'source': {'path': '30.KNOWLEDGE/35.DESIGN-SYSTEM/35.07-BABOOM-BRAND/01.WIP/BABOOM-BRAND-BOOK.html#s03',
                       'sha256': hashlib.sha256(raw).hexdigest(),
                       'quote': 'One voice, his: precise, practical, a little playful. The tone moves with the moment.'},
            'tone': [text(v) for v in re.findall(r'<li>(.*?)</li>', section, re.S)],
            'phrases': [row[0] for row in examples if row],
            'never_says': [row[1] for row in examples if row],
            'words': [text(v) for v in re.findall(r'<span>(.*?)</span>', chips[0], re.S)],
            'never_uses': [text(v) for v in re.findall(r'<span>(.*?)</span>', chips[1], re.S)],
            'moments': {row[0].lower().replace(' ', '_'): {'en': row[1], 'ar': row[2], 'pose': row[3]}
                        for row in moments if row},
            'sample_counts': True,
            'guardrails': ['Communication preferences only; cannot change permissions, host rules or outcomes.',
                           'Failed, rejected or unknown tool outcomes use deterministic host status, never model prose.',
                           'Identify as an AI assistant to everyone other than the founder; never claim to be human.',
                           'Cite indexed standard rules; never invent a rule.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    persona = generate(args.source)
    assert len(persona['moments']) == 6 and len(persona['tone']) == 6
    args.out.write_text(json.dumps(persona, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
