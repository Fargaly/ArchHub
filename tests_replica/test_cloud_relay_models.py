"""The cockpit's model routing is what the app publishes, in one checked form, or nothing.

The router lane publishes through CloudRelay(models=...). The relay passes on only a whole,
valid value; a malformed or failing publisher leaves no key, so the cockpit says "not
published" instead of drawing half a list.
"""
import json

from nodelang.cloud_relay import CloudRelay, published_models_form

MAP = '{"domains":[],"nodes":[],"wires":[]}'
MODELS = {
    "models": [
        {"name": "claude-sonnet-5", "provider": "anthropic", "available": True},
        {"name": "local-llama", "provider": "ollama", "available": False},
    ],
    "routes": [{"task": "compose", "model": "claude-sonnet-5"}],
}


def _control(models):
    relay = CloudRelay(base_url="http://127.0.0.1:9", token="t",
                       respond=lambda utterance: {}, execute=lambda utterance: {},
                       hosts=lambda: [], models=models)
    return json.loads(relay._with_control(MAP))["control"]


def test_a_valid_list_is_published_with_only_its_three_keys_and_its_routes():
    form = published_models_form({
        "models": [dict(MODELS["models"][0], api_key="sk-never", endpoint="https://x")],
        "routes": MODELS["routes"],
    })
    assert form == {"models": [MODELS["models"][0]], "routes": MODELS["routes"]}
    assert published_models_form({"models": []}) == {"models": [], "routes": []}


def test_anything_malformed_publishes_nothing():
    good = MODELS["models"][0]
    for bad in (
        None, [], "models", {"routes": []}, {"models": "claude"},
        {"models": [dict(good, available="yes")]},
        {"models": [{"name": "claude", "provider": "anthropic"}]},
        {"models": [dict(good, name="")]},
        {"models": [dict(good, name="x" * 81)]},
        {"models": [dict(good, provider="p" * 41)]},
        {"models": [good, good]},
        {"models": [good], "routes": [{"task": "compose", "model": "not-published"}]},
        {"models": [good], "routes": [{"task": "compose", "model": good["name"]}] * 2},
        {"models": [dict(good, name="m%d" % i) for i in range(41)]},
    ):
        assert published_models_form(bad) is None, bad


def test_the_push_carries_models_and_routes_only_when_the_app_publishes_them():
    control = _control(lambda: MODELS)
    assert control["models"] == MODELS["models"]
    assert control["routes"] == MODELS["routes"]
    for publisher in (None, lambda: {"models": "broken"}, lambda: 1 / 0):
        control = _control(publisher)
        assert "models" not in control and "routes" not in control
    assert _control(lambda: {"models": []})["models"] == []