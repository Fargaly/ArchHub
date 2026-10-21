"""opencode CLI runtime definition; OpenDesign declarative adapter shape."""
DEFINITION = {'id': 'opencode', 'label': 'OpenCode', 'executables': ('opencode',), 'session_environment': ('OPENCODE_SESSION_ID',), 'stream_arguments': ('run', '--format', 'json')}
