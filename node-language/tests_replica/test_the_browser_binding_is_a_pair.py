"""Every browser-session call site unpacks the pair it returns.

_browser_session_binding() answers (binding, token). Three GET routes read
it as one object and called binding.context, so every request to them died
with AttributeError: 'tuple' object has no attribute 'context' - on the
founder's machine, in a shipped build (2026-09-07). One line of source, one
court: a call site that does not unpack fails here.
"""
from __future__ import annotations

import re
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / "nodelang" / "application_server.py"


def test_every_call_site_unpacks_the_binding_and_its_token():
    text = SERVER.read_text(encoding="utf-8")
    offenders = []
    for number, line in enumerate(text.splitlines(), 1):
        if "_browser_session_binding(" not in line or line.lstrip().startswith(("#", "def ")):
            continue
        stripped = line.strip()
        if stripped.startswith("def _browser_session_binding"):
            continue
        assigns = "=" in stripped.split("self._browser_session_binding")[0]
        if not assigns:
            # a bare call for its side effect (it raises when unauthenticated)
            continue
        target = stripped.split("=")[0].strip()
        if target.endswith(chr(92)):
            target = target[:-1].strip()
        if "," not in target:
            offenders.append("%d: %s" % (number, stripped[:100]))
    assert not offenders, (
        "it answers (binding, token); unpack both: " + " | ".join(offenders))


def test_the_three_browser_reads_ask_the_graph_and_survive_the_unpack():
    text = SERVER.read_text(encoding="utf-8")
    for path in ("/api/universal/providers", "/api/universal/cloud-session",
                 "/api/universal/cloud-signin"):
        start = text.index("parsed.path == '%s'" % path)
        block = text[start:start + 900]
        assert "binding, _session_token = self._browser_session_binding()" in block, path
        assert "require_universal_http_route(" in block, path
        assert "binding.context" in block, path
