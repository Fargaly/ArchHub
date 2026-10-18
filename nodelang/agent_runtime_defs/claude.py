"""claude CLI runtime definition; OpenDesign declarative adapter shape."""
DEFINITION = {'id': 'claude', 'label': 'Claude Code', 'executables': ('claude', 'claude-code'), 'session_environment': ('CLAUDE_CODE_SESSION_ID', 'CLAUDE_SESSION_ID'), 'stream_arguments': ('--print', '--verbose', '--input-format', 'stream-json', '--output-format', 'stream-json')}
