"""gemini CLI runtime definition; OpenDesign declarative adapter shape."""
DEFINITION = {'id': 'gemini', 'label': 'Gemini', 'executables': ('gemini',), 'session_environment': ('GEMINI_SESSION_ID',), 'stream_arguments': ('--output-format', 'stream-json')}
