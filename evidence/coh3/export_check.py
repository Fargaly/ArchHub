"""Regenerate the public seed export and record exact release handoff evidence."""
import hashlib
from html import unescape
import json
from pathlib import Path
import re
import struct
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from nodelang import site_export
from nodelang.cell_accounts import BETA_OFFER


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


offer = dict(BETA_OFFER)
store, registry = site_export._build_public_seed_application(site_export.website_offer(offer))
payload = site_export.write_public_site(store, registry, ROOT / 'public_site', offer=offer,
    offer_sha256=site_export.offer_digest(offer), origin='https://archhub.io')
assert len(payload['routes']) == 18
assert len([key for key in payload['routes'] if '/docs/tutorial-' in key]) == 6
failures = []
links = []
for route, page in payload['routes'].items():
    site_export.validate_public_claims(page['html'])
    actual = ROOT / 'public_site/dist' / page['output_path']
    assert actual.read_text(encoding='utf-8') == page['html'], route
    for link in re.findall(r'(?:href|src)="(/[^"#]*)"', page['html']):
        target = ROOT / 'public_site/dist' / link.lstrip('/')
        if link.endswith('/'):
            target /= 'index.html'
        if not target.is_file():
            failures.append((route, link))
        links.append(link)
for name, record in payload['files'].items():
    actual = ROOT / 'public_site/dist' / name
    assert digest(actual) == record['sha256'], name
    assert actual.stat().st_size == record['bytes'], name
for name, contents in payload['assets'].items():
    assert (ROOT / 'public_site/dist' / name).read_text(encoding='utf-8') == contents
assert not failures, failures
capture = ROOT / '../rig2/gate-he41d56asocial3-232226/03_rail_Home.png'
source = ROOT / 'nodelang/data/website/tutorials/home-templates.png'
assert capture.read_bytes() == source.read_bytes()
assert struct.unpack('>II', source.read_bytes()[16:24]) == (1496, 959)
current = site_export.documentation_pages()['getting-started'][2]
assert all(word in current for word in ('Home', 'System graph', 'Connections', 'BABOOM', 'Instagram', 'Start', 'Edit'))
assert 'Goose is running' not in current
source_paths = [path for path in (
    'nodelang/site_export.py', 'nodelang/cell_website.py', 'nodelang/application_server.py',
    'nodelang/base_universal_catalogue.py', 'nodelang/library_engines.py',
    'nodelang/universal_pipeline.py', 'nodelang/social_connections.py', 'nodelang/universal_application.py')]
inputs = {'source_sha256': {path: digest(ROOT / path) for path in source_paths},
          'documentation_build_id': site_export.documentation_build_id(),
          'offer': offer, 'offer_sha256': site_export.offer_digest(offer),
          'screenshot_input': str(capture), 'screenshot_input_sha256': digest(capture),
          'screenshot_export': 'assets/tutorials/home-templates.png',
          'screenshot_export_sha256': digest(source)}
(ROOT / 'evidence/coh3/export-inputs.json').write_text(json.dumps(inputs, indent=2) + '\n')
result = {'format': payload['format'], 'routes': len(payload['routes']),
          'tutorials': 6, 'export_sha256': payload['export_sha256'],
          'site_export_file_sha256': digest(ROOT / 'public_site/site-export.json'),
          'banned_claims': 'PASS', 'banned_phrases': list(site_export.BANNED_PUBLIC_CLAIMS),
          'local_links_checked': len(links), 'missing_links': failures,
          'pages': [{'route': key, 'output': page['output_path'],
                     'title': unescape(re.search(r'<title>(.*?)</title>', page['html']).group(1))}
                    for key, page in payload['routes'].items()],
          'download': payload['download'], 'screenshot_sha256': digest(source)}
(ROOT / 'evidence/coh3/export-check.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps({key: value for key, value in result.items() if key not in ('pages', 'banned_phrases', 'download')}))
