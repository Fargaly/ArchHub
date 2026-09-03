"""Generate the node-native CDE overlay from Grand Map domain rules."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .map_import import load_map, resolve_map_path


ROOT = '10.PRODUCT/13.NODE-LANGUAGE/'
DOMAIN_TARGETS = {
    'ui': (['nodelang/application.py', 'nodelang/ui_runtime.py'],
           'tests_replica/test_node_native_application.py'),
    'canvas': (['nodelang/application.py', 'nodelang/ui_runtime.py'],
               'tests_replica/test_node_native_application.py'),
    'nodes': (['nodelang/core.py', 'nodelang/laws_structure.py',
               'nodelang/laws_relation.py', 'nodelang/laws_surface.py'],
              'tests_replica/test_forcing_one_table.py'),
    'models': (['nodelang/domains/models.py'], 'tests_domains/test_models.py'),
    'brain': (['nodelang/governance_probe.py', 'nodelang/application.py'],
              'tests_replica/test_governance_probe_nodes.py'),
    'connectors': (['nodelang/domains/connectors.py', 'nodelang/core.py'],
                   'tests_domains/test_connectors.py'),
    'sessions': (['nodelang/domains/sessions.py', 'nodelang/persistence.py',
                  'nodelang/laws_surface.py',
                  'nodelang/application_server.py'],
                 'tests_replica/test_application_persistence.py'),
    'selfext': (['nodelang/domains/selfext.py'], 'tests_domains/test_selfext.py'),
    'website': (['nodelang/website.py'], 'tests_replica/test_node_native_website.py'),
    'users': (['nodelang/domains/users.py'], 'tests_domains/test_users.py'),
    'monetization': (['nodelang/domains/monetization.py'],
                     'tests_domains/test_monetization.py'),
    'cockpit': (['nodelang/application.py', 'nodelang/domains/cockpit.py'],
                'tests_domains/test_cockpit.py'),
    'cloud': (['nodelang/domains/cloud.py'], 'tests_domains/test_cloud.py'),
    'community': (['nodelang/domains/community.py'],
                  'tests_domains/test_community.py'),
    'orchestration': (['nodelang/domains/orchestration.py'],
                      'tests_domains/test_orchestration.py'),
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
