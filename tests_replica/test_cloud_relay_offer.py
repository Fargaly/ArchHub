"""The cockpit reads the offer the app holds: one published form, nothing when undeclared."""
import json

from nodelang.cloud_relay import CloudRelay

MAP_SCRIPT = 'window.ATLAS_MAP = {"domains":[],"nodes":[],"wires":[]}; window.ATLAS_LIVE = true;'
BODY = '{"domains":[],"nodes":[],"wires":[]}'
OFFER = {"revision": 7, "sha256": "a" * 64, "availability": "free-during-beta",
         "pricing_visible": False, "public_label": "Free during beta"}


def _relay(offer, **extra):
    return CloudRelay(base_url="https://fixture.invalid", token="fixture",
                      respond=lambda utterance: {}, execute=lambda utterance: {},
                      map_script=lambda: MAP_SCRIPT, hosts=lambda: [], offer=offer, **extra)


def _model(relay):
    return json.loads(relay._with_control(BODY))


def test_a_declared_offer_is_published_in_its_one_form():
    model = _model(_relay(lambda: dict(OFFER, secret="stays home")))
    assert model["offer"] == OFFER
    assert "control" in model


def test_no_offer_key_when_nothing_is_declared():
    assert "offer" not in _model(_relay(lambda: None))
    assert "offer" not in _model(_relay(None))


def test_a_failing_or_malformed_offer_never_breaks_the_push():
    def closed():
        raise RuntimeError("store closed")
    assert "offer" not in _model(_relay(closed))
    assert "offer" not in _model(_relay(lambda: {"availability": "free-during-beta"}))
    assert "offer" not in _model(_relay(lambda: dict(OFFER, pricing_visible="false")))
    assert "offer" not in _model(_relay(lambda: dict(OFFER, sha256="short")))


def test_the_relay_pushes_the_offer_to_the_cloud():
    sent = []

    class Answer:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b"{}"

    def opener(request, timeout):
        sent.append(json.loads(request.data.decode("utf-8")))
        return Answer()

    _relay(lambda: OFFER, opener=opener).push_map(force=True)
    assert sent and sent[-1]["offer"] == OFFER