"""Generate the node-native CDE overlay from Grand Map domain rules."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .map_import import load_map, resolve_map_path


ROOT = '10.PRODUCT/11.ARCHHUB-APP/'
DOMAIN_TARGETS = {
    'ui': (['01.APP/nodelang/application.py', '01.APP/nodelang/ui_runtime.py'],
           '02.TESTS/tests_replica/test_node_native_application.py'),
    'canvas': (['01.APP/nodelang/application.py', '01.APP/nodelang/ui_runtime.py'],
               '02.TESTS/tests_replica/test_node_native_application.py'),
    'nodes': (['01.APP/nodelang/core.py', '01.APP/nodelang/laws_structure.py',
               '01.APP/nodelang/laws_relation.py', '01.APP/nodelang/laws_surface.py'],
              '02.TESTS/tests_replica/test_forcing_one_table.py'),
    'models': (['01.APP/nodelang/domains/models.py'], '02.TESTS/tests_domains/test_models.py'),
    'brain': (['01.APP/nodelang/governance_probe.py', '01.APP/nodelang/application.py'],
              '02.TESTS/tests_replica/test_governance_probe_nodes.py'),
    'connectors': (['01.APP/nodelang/domains/connectors.py', '01.APP/nodelang/core.py'],
                   '02.TESTS/tests_domains/test_connectors.py'),
    'sessions': (['01.APP/nodelang/domains/sessions.py', '01.APP/nodelang/persistence.py',
                  '01.APP/nodelang/laws_surface.py',
                  '01.APP/nodelang/application_server.py'],
                 '02.TESTS/tests_replica/test_application_persistence.py'),
    'selfext': (['01.APP/nodelang/domains/selfext.py'], '02.TESTS/tests_domains/test_selfext.py'),
    'website': (['01.APP/nodelang/cell_website.py', '01.APP/nodelang/site_export.py'], '02.TESTS/tests_replica/test_node_native_website.py'),
    'users': (['01.APP/nodelang/domains/users.py'], '02.TESTS/tests_domains/test_users.py'),
    'monetization': (['01.APP/nodelang/domains/monetization.py'],
                     '02.TESTS/tests_domains/test_monetization.py'),
    'cockpit': (['01.APP/nodelang/application.py', '01.APP/nodelang/domains/cockpit.py'],
                '02.TESTS/tests_domains/test_cockpit.py'),
    'cloud': (['01.APP/nodelang/domains/cloud.py'], '02.TESTS/tests_domains/test_cloud.py'),
    'community': (['01.APP/nodelang/domains/community.py'],
                  '02.TESTS/tests_domains/test_community.py'),
    'orchestration': (['01.APP/nodelang/domains/orchestration.py'],
                      '02.TESTS/tests_domains/test_orchestration.py'),
}


def build_overlay(map_path=None):
    domains = load_map(map_path)
    containers = {}
    for domain in domains:
        key = domain['key']
        targets, test_path = DOMAIN_TARGETS[key]
        allowed = [ROOT + target for target in targets]
        allowed.append(ROOT + test_path)
        for node in domain['nodes']:
            containers[node['id']] = {
                'tier': 'T1',
                'lifecycle_state': 'WIP',
                'suitability_status': 'S0',
                'revision': 'P01',
                'owner': 'founder',
                'checker': 'court',
                'allowed_paths': allowed,
                'gate_kind': 'pytest',
                'gate_spec': {
                    'path': ROOT + test_path,
                    'command': 'python -m pytest %s -q' % test_path,
                },
                'evidence_ref': 'file:' + ROOT + test_path,
                'classification_confidence': 'governed-domain-route',
            }
    return {
        'schema': 'archhub-cde-overlay/v1',
        'source': str(resolve_map_path(map_path)),
        'target_runtime': ROOT.rstrip('/'),
        'containers': containers,
    }


def write_overlay(output, map_path=None):
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(build_overlay(map_path), indent=2) + '\n',
                      encoding='utf-8')
    return output


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('output')
    parser.add_argument('--map', default=None)
    args = parser.parse_args(argv)
    path = write_overlay(args.output, args.map)
    print(path)


if __name__ == '__main__':
    main()
