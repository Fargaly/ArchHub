"""opencode CLI runtime definition; OpenDesign declarative adapter shape."""
DEFINITION = {'id': 'opencode', 'label': 'OpenCode', 'executables': ('opencode',), 'session_environment': ('OPENCODE_SESSION_ID',), 'stream_arguments': ('run', '--format', 'json')}


def server_password_environment(base):
    """base plus a fresh random OPENCODE_SERVER_PASSWORD (F20, CVE-2026-22812 class): any local OpenCode server started
    from this environment answers only a client holding it. The value lives only in that child's environment; it is
    never logged, stored or shown. A password the person already set is kept."""
    import secrets
    env = dict(base)
    if not env.get('OPENCODE_SERVER_PASSWORD'):
        env.update(OPENCODE_SERVER_USERNAME='opencode', OPENCODE_SERVER_PASSWORD=secrets.token_urlsafe(32))
    return env