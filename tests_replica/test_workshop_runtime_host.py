"""The Workshop rail names an agent by the host its runtime catalog names (2026-10-01).

The participant row carried only an opaque session label ("Runtime-30056e23"); the design's rail
reads "name · role · host". The host comes from the graph's runtime catalog, never a client table.
"""
from nodelang.existing_workshop_conversation import workshop_runtime_host
from nodelang.universal_application import _HARNESS_AGENT_RUNTIMES


def test_every_catalogued_runtime_has_its_catalog_name():
    for runtime, label in _HARNESS_AGENT_RUNTIMES:
        assert workshop_runtime_host(runtime) == label
    assert workshop_runtime_host("baboom") == "BABOOM"


def test_an_uncatalogued_runtime_has_no_host_rather_than_a_guess():
    for runtime in ("antigravity-ide", "", None, "claude · local", "CLAUDE"):
        assert workshop_runtime_host(runtime) is None
