"""Settings > Providers shows what is on this machine, not a story.

The tab showed 'ant-****e2af  $23.84 this month', 'sk-****8e1b', 'or-****9c4d
$2.14 this month': invented keys and invented spend, typed into a fixture in
2025 and shown to the founder as his account. Nothing here is invented: a
cloud provider is keyed (with the place the key came from) or has no key, a
local runtime is running or not, and there is no spend figure because nothing
on this machine measures one.
"""
from __future__ import annotations

from pathlib import Path

from nodelang import model_router

ROOT = Path(__file__).resolve().parents[1]


def test_rows_say_keyed_or_no_key_with_the_source():
    rows = model_router.provider_rows(
        environ={"OPENROUTER_API_KEY": "or-live"},
        secrets_loader=lambda name: "",
        cloud_session=None,
        local_probe=lambda host, port: port == 11434,
    )
    by = {r["id"]: r for r in rows}
    assert by["openrouter"]["state"] == "keyed" and by["openrouter"]["source"] == "environment"
    assert by["cloud"]["state"] == "no key" and by["cloud"]["sets"] == "ARCHHUB_CLOUD_TOKEN"
    assert by["ollama"]["state"] == "running" and by["lmstudio"]["state"] == "not running"
    for row in rows:
        assert "usage" not in row and "$" not in str(row), row


def test_a_key_from_the_secrets_store_names_the_store():
    rows = model_router.provider_rows(
        environ={}, secrets_loader=lambda name: "k" if name == "openrouter" else "",
        cloud_session=None, local_probe=lambda h, p: False)
    by = {r["id"]: r for r in rows}
    assert by["openrouter"]["state"] == "keyed" and by["openrouter"]["source"] == "secrets store"


def test_the_route_is_declared_served_and_session_bound():
    app = (ROOT / "nodelang" / "universal_application.py").read_text(encoding="utf-8")
    assert '("GET", "/api/universal/providers", "read"),' in app
    server = (ROOT / "nodelang" / "application_server.py").read_text(encoding="utf-8")
    assert "if parsed.path == '/api/universal/providers':" in server
    block = server[server.index("if parsed.path == '/api/universal/providers':"):]
    block = block[:block.index("if parsed.path == '/api/universal/models':")]
    assert "self._browser_session_binding()" in block and "provider_rows(" in block
    assert '("GET", "/api/universal/providers"),' in server


def test_the_studio_reads_the_route_and_holds_no_invented_key_or_spend():
    raw = (ROOT / "nodelang" / "studio" / "studio-lm.jsx").read_text(encoding="utf-8", errors="replace")
    # code only: a comment that names the old fixture is not the old fixture
    jsx = chr(10).join(line for line in raw.split(chr(10)) if not line.lstrip().startswith("//"))
    providers = jsx[jsx.index("const SettingsProviders"):jsx.index("const SettingsProviders") + 6000]
    assert "/api/universal/providers" in providers
    for invented in ("$23.84", "$2.14", "ant-", "sk-•", "or-•", "k7Fq2xBn91LmZ0aTvR", "this month"):
        assert invented not in jsx, invented
    assert "'3 keys'" not in jsx
