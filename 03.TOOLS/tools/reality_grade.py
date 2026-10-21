"""Grade the grand map against REALITY, not typed labels.

Each map node becomes a probe node (nodelang.core) derived from its
evidence_ref: file: -> file_exists (+ py_compile for .py), http -> http_ok,
anything with no checkable artifact -> UNVERIFIABLE = not proven = false
(anti-false-green: no evidence is not 'done'). Prints the honest built-% per
domain + total, next to the typed-label fiction. Every value is a live check.
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nodelang.core import Store

TYPED_WEIGHT = {'live': 1.0, 'partial': 0.5, 'planned': 0.25, 'vision': 0.0}


def _private_inputs(workspace_root=None, map_path=None):
    root = workspace_root or os.environ.get('ARCHHUB_WORKSPACE_ROOT')
    source = map_path or os.environ.get('ARCHHUB_GRAND_MAP_PATH')
    if not root or not source:
        raise RuntimeError(
            'ARCHHUB_WORKSPACE_ROOT and ARCHHUB_GRAND_MAP_PATH are required; '
            'private evidence is never embedded in the public product tree')
    return os.path.abspath(root), os.path.abspath(source)


def probe_for(store, ev, workspace_root):
    ev = (ev or '').strip()
    if ev.startswith('file:'):
        p = os.path.join(workspace_root, ev[5:].replace('/', os.sep))
        kind = 'py_compile' if p.endswith('.py') else 'file_exists'
        spec = {'path': p}
        return store.add('op', 'probe', floor={'op': 'probe', 'kind': kind, 'spec': spec}), True
    if ev.startswith('http'):
        return store.add('op', 'probe',
                         floor={'op': 'probe', 'kind': 'http_ok', 'spec': {'url': ev}}), True
    return None, False   # no checkable artifact -> unverifiable


def main(workspace_root=None, map_path=None):
    root, source = _private_inputs(workspace_root, map_path)
    doms = json.load(open(source, encoding='utf-8'))
    s = Store()
    total = proven = verifiable = 0
    typed_sum = 0.0
    print('%-14s %6s  %6s  %6s   %s' % ('domain', 'typed%', 'real%', 'nodes', 'proven/verifiable'))
    print('-' * 66)
    for d in doms:
        dn = dp = dv = 0
        dtyped = 0.0
        for n in d['nodes']:
            dn += 1
            dtyped += TYPED_WEIGHT.get(n['status'], 0.0)
            pid, checkable = probe_for(s, n.get('evidence_ref'), root)
            if checkable:
                dv += 1
                r = s.pull(pid)
                if r.get('ok'):
                    dp += 1
        total += dn
        proven += dp
        verifiable += dv
        typed_sum += dtyped
        print('%-14s %5.1f%%  %5.1f%%  %6d   %d/%d' %
              (d['key'], 100 * dtyped / dn, 100 * dp / dn, dn, dp, dv))
    print('-' * 66)
    print('TOTAL          %5.1f%%  %5.1f%%  %6d   %d proven, %d verifiable, %d no-evidence' %
          (100 * typed_sum / total, 100 * proven / total, total,
           proven, verifiable, total - verifiable))
    print()
    print('typed%% = the OLD fiction (average of typed labels).')
    print('real%%  = proven by a live check on the real artifact NOW. no evidence = not proven.')
    print('note: file_exists is an UPPER bound (file present != feature complete);')
    print('      the honest built number is at or below real%%.')


if __name__ == '__main__':
    main()
