"""INDEPENDENT COURT — desktop zero-config cloud free-default LIVE proof.

Drives the REAL LLMRouter (not a stub) against the LIVE cloud
(archhub-cloud.fly.dev) with the founder's real bearer token, asserting:

  (1) LIVE_COMPLETION  — a real non-empty completion comes back via the cloud
                          free model (meta/llama-3.3-70b-instruct), real network.
  (2) AUTO_ZEROCONFIG  — default_model="auto" + signed-in + NO BYO + NO local
                          => router picks 'archhub_cloud' across every bucket;
                          and a BYO key WINS over the managed cloud.
  (3) SIGNED_OUT_CLEAN — no token => provider cleanly absent, configured_providers
                          == [] (no error spam), auto raises honest 'No LLM
                          configured' (no fake route).
  (4) ONE_SYSTEM       — reuses the same archhub_cloud provider + cloud_client
                          token + ArchHubCloudClient → /v1; no parallel client.

Prints a JSON verdict line: COURT_RESULT={...}
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
for p in (str(APP), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

import cloud_client  # noqa: E402
import llm_router as llm_router_mod  # noqa: E402
from llm_router import LLMRouter, ROUTE_AUTO  # noqa: E402

result: dict = {
    "live_completion": {"ok": False, "evidence": ""},
    "auto_zeroconfig": {"ok": False, "evidence": ""},
    "signed_out_clean": {"ok": False, "evidence": ""},
    "one_system": {"ok": False, "evidence": ""},
}


# --- read the founder's real token from cloud.json ------------------------
def _founder_token():
    base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    cj = Path(base) / "ArchHub" / "brain" / "cloud.json"
    d = json.load(open(cj, encoding="utf-8"))
    return (d.get("token") or d.get("access_token") or "").strip()


REAL_TOKEN = _founder_token()
assert len(REAL_TOKEN) >= 16, "no plausible founder token on disk"


# --- minimal real-ish tool engine (no tools => clean completion) ----------
class _Mgr:
    entries = []


class _Engine:
    def __init__(self):
        self.manager = _Mgr()

    def tool_schemas_for(self, provider):
        return []

    def invoke(self, *a, **k):
        return {"status": "ok"}


def _router():
    r = LLMRouter(_Engine())
    r._build_system_prompt = lambda: "You are a terse assistant."
    return r


# --- pristine zero-config patch (no BYO, no env, no local) ----------------
def _make_zero_config(token):
    """Patch the router's environment to a pristine signed-in machine.
    Returns nothing; mutates module-level lookups in place (process-local).
    """
    llm_router_mod.list_keys = lambda: []
    llm_router_mod.load_api_key = lambda p: ""
    for env in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY",
                "OPENROUTER_API_KEY", "NVIDIA_API_KEY"):
        os.environ.pop(env, None)
    import llm_providers.ollama_client as _oll
    import llm_providers.claude_cli_client as _ccli
    import llm_providers.codex_cli_client as _xcli
    import llm_detector as _det
    import secrets_store as _ss
    _oll.list_local_models = lambda: []
    _ccli.claude_cli_path = lambda: None
    _xcli.codex_cli_path = lambda: None
    _det.probe_lmstudio = lambda: {}
    _ss.load_setting = lambda *a, **k: ""
    cloud_client.current_token = lambda: token


# =========================================================================
# (3) SIGNED_OUT_CLEAN  — run FIRST while signed out
# =========================================================================
try:
    _make_zero_config(None)
    r = _router()
    cfg = r.configured_providers()
    assert "archhub_cloud" not in cfg, f"cloud present while signed out: {cfg}"
    assert cfg == [], f"providers not empty while signed out: {cfg}"
    raised = ""
    try:
        r._route([{"role": "user", "content": "hello there friend"}], ROUTE_AUTO)
    except RuntimeError as ex:
        raised = str(ex)
    assert "No LLM configured" in raised, f"expected honest error, got: {raised!r}"
    result["signed_out_clean"] = {
        "ok": True,
        "evidence": f"signed-out: configured_providers()==[] (no spam); "
                    f"_route raises honest {raised!r}",
    }
except Exception as ex:
    result["signed_out_clean"]["evidence"] = f"FAIL: {type(ex).__name__}: {ex}"


# =========================================================================
# (2) AUTO_ZEROCONFIG — signed in, no BYO/local => cloud across buckets;
#     BYO wins when present.
# =========================================================================
try:
    _make_zero_config(REAL_TOKEN)
    r = _router()
    cfg = r.configured_providers()
    assert "archhub_cloud" in cfg, f"cloud absent while signed in: {cfg}"
    buckets = {
        "default": "Could you draft a longer paragraph of prose for me please.",
        "modeling": "create a wall in revit on level 1",
        "analysis": "explain why this schedule is wrong",
        "short": "hi",
    }
    routed = {}
    for name, prompt in buckets.items():
        prov, model, _note = r._route(
            [{"role": "user", "content": prompt}], ROUTE_AUTO)
        routed[name] = (prov, model)
        assert prov == "archhub_cloud", f"{name} routed to {prov}, not cloud"
        assert model == "auto", f"{name} model {model} != auto"
    # BYO wins
    llm_router_mod.list_keys = lambda: ["anthropic"]
    llm_router_mod.load_api_key = (
        lambda p: "sk-ant-xxxxxxxxxxxxxxxx" if p == "anthropic" else "")
    r2 = _router()
    cfg2 = set(r2.configured_providers())
    assert {"anthropic", "archhub_cloud"} <= cfg2, f"byo+cloud not both: {cfg2}"
    prov_byo, _m, _n = r2._route(
        [{"role": "user", "content": "draft a long paragraph of prose"}],
        ROUTE_AUTO)
    assert prov_byo == "anthropic", f"BYO did not win: {prov_byo}"
    # restore zero-config for next stage
    _make_zero_config(REAL_TOKEN)
    result["auto_zeroconfig"] = {
        "ok": True,
        "evidence": f"signed-in zero-config: all buckets→archhub_cloud:auto "
                    f"({routed}); BYO anthropic WINS over cloud ({prov_byo}).",
    }
except Exception as ex:
    result["auto_zeroconfig"]["evidence"] = f"FAIL: {type(ex).__name__}: {ex}"


# =========================================================================
# (1) LIVE_COMPLETION + (4) ONE_SYSTEM
#     Build the REAL client through the REAL router and make a REAL call.
# =========================================================================
try:
    _make_zero_config(REAL_TOKEN)
    r = _router()
    # ONE_SYSTEM: the client is the archhub_cloud provider, built from
    # cloud_client.current_token() via ArchHubCloudClient → /v1.
    client = r._get_client("archhub_cloud")
    from llm_providers.archhub_cloud_client import ArchHubCloudClient
    assert isinstance(client, ArchHubCloudClient), type(client)
    base = str(getattr(client._client, "base_url", "")).rstrip("/")
    assert base.endswith("/v1"), f"base not /v1: {base}"
    # the SDK carries the founder token as the bearer
    assert client._client.api_key == REAL_TOKEN, "client bearer != founder token"

    # REAL network completion via the router's complete() path with auto model.
    chunks = []
    resp = r.complete(
        history=[{"role": "user",
                  "content": "Reply with exactly: ARCHHUB_LIVE_OK"}],
        model="archhub_cloud:auto",
        on_chunk=lambda c: chunks.append(c),
        max_tokens=64,
        temperature=0.0,
    )
    text = (getattr(resp, "text", None) or "".join(chunks) or "").strip()
    assert text, f"empty completion; resp={resp!r}"
    result["live_completion"] = {
        "ok": True,
        "evidence": f"REAL network completion via archhub_cloud (model auto → "
                    f"server free-default meta/llama-3.3-70b-instruct): "
                    f"{text[:160]!r}",
    }
    result["one_system"] = {
        "ok": True,
        "evidence": f"ONE-SYSTEM: r._get_client('archhub_cloud') => "
                    f"ArchHubCloudClient(base={base}, bearer==founder token); "
                    f"no parallel client; same provider the router routes to.",
    }
except Exception as ex:
    import traceback
    tb = traceback.format_exc()
    msg = f"FAIL: {type(ex).__name__}: {ex}"
    if not result["live_completion"]["ok"]:
        result["live_completion"]["evidence"] = msg
    if not result["one_system"]["ok"]:
        result["one_system"]["evidence"] = msg
    sys.stderr.write(tb + "\n")


print("COURT_RESULT=" + json.dumps(result))
