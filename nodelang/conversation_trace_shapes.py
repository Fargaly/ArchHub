"""Pure trace identity rules shared by retention and closed-state Setup."""


def _trace_family_descriptor(identifier):
    """A trace shape is narrower than a family prefix; controls stay graph."""
    prefixes = ('app:deliberation-payload:', 'app:deliberation:',
                'app:agent-session:', 'app:workshop:', 'app:baboom-session:')
    prefix = next((value for value in prefixes if identifier.startswith(value)), None)
    if prefix is None:
        return None, False
    if identifier in tuple('app:agent-session:founder:' + role for role in
            ('view-receipt', 'scope-receipt', 'close-receipt')):
        return 'app:agent-session:founder', False
    for marker in (':view-receipt', ':scope-receipt', ':close-receipt', ':entry:'):
        position = identifier.find(marker, len(prefix))
        if position < 0:
            continue
        suffix = identifier[position + len(marker):]
        if marker == ':entry:':
            token, separator, tail = suffix.partition(':')
            if not token:
                return identifier, False
            suffix = ':' + tail if separator else ''
        if suffix in ('', ':revision', ':evaluated-at', ':context-expires-at',
                      ':policy-digest', ':reason', ':resolver-revision', ':resolver-evaluated-at'):
            return identifier[:position], True
        kind, separator, number = suffix[1:].partition(':')
        if suffix.startswith(':') and separator and kind in ('chain', 'incidence') and number.isascii() and number.isdecimal():
            return identifier[:position], True
        return identifier, False
    root, separator, number = identifier.partition(':chain:')
    if separator and number.isascii() and number.isdecimal():
        return root, True
    return identifier, False
