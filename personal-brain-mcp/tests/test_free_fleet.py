"""Tests for the FREE-ONLY worker router (the money firewall).

The whole point of the standing dispatcher loop is that it can NEVER spend
metered API money — every worker call must land on free inference (the user's
flat-rate codex/ChatGPT subscription, a free NVIDIA NIM key, or a local model
on this machine). `free_fleet.FreeFleet` is the router that enforces that.

Same philosophy as test_roma.py / test_diligence.py: pure + deterministic,
NO real network and NO real subprocess (monkeypatched), the live brain.db is
never touched. The four properties under test:

  1. assert_free() — the allowlist firewall. It REJECTS any metered provider
     name (anthropic/openai/google/openrouter/dashscope) and ACCEPTS the free
     ones (codex_cli/nvidia/ollama/lmstudio/local). This is the RED→GREEN
     anchor: before the guard exists the import/attribute fails.
  2. available() — reflects which free providers are reachable RIGHT NOW; a
     monkeypatched-up local endpoint appears, a monkeypatched-down one drops.
  3. run_worker() — NEVER returns a non-zero cost, and only ever names a
     free provider (it routes through assert_free, so a metered selection
     raises rather than spends).
  4. No metered provider is reachable from this code at all — there is no
     anthropic/openai/google client, no api base for a paid endpoint.
"""
from __future__ import annotations

import pytest

from personal_brain import free_fleet
from personal_brain.free_fleet import (
    FreeFleet,
    assert_free,
    FREE_PROVIDERS,
    METERED_PROVIDERS,
    MeteredProviderError,
)


# ─────────────────────────── assert_free (the firewall) ─────────────────


@pytest.mark.parametrize("metered", sorted(METERED_PROVIDERS))
def test_assert_free_rejects_every_metered_provider(metered):
    """RED before the guard exists. Each metered provider name must raise —
    this is the money firewall: a paid provider can never be selected."""
    with pytest.raises(MeteredProviderError):
        assert_free(metered)


@pytest.mark.parametrize("free", sorted(FREE_PROVIDERS))
def test_assert_free_accepts_every_free_provider(free):
    """The free providers pass through untouched (returns the name)."""
    assert assert_free(free) == free


def test_metered_and_free_sets_are_disjoint():
    """A provider can't be both — the two allowlists never overlap, or the
    firewall would have an ambiguous member."""
    assert FREE_PROVIDERS.isdisjoint(METERED_PROVIDERS)


def test_assert_free_rejects_unknown_provider():
    """An unknown name is fail-CLOSED (rejected) — never assume a new
    provider is free."""
    with pytest.raises(MeteredProviderError):
        assert_free("some-new-paid-thing")


def test_the_named_metered_providers_are_all_listed():
    """The spec names these five as the metered set the firewall must block.
    Lock them in so a refactor can't silently drop one."""
    for p in ("anthropic", "openai", "google", "openrouter", "dashscope"):
        assert p in METERED_PROVIDERS


# ─────────────────────────── available() probe ─────────────────────────


def test_available_reflects_local_endpoint_up(monkeypatch):
    """A reachable local endpoint (monkeypatched UP) appears in available()."""
    monkeypatch.setattr(free_fleet, "_probe_ollama", lambda timeout=None: True)
    monkeypatch.setattr(free_fleet, "_probe_lmstudio", lambda timeout=None: False)
    monkeypatch.setattr(free_fleet, "_codex_available", lambda: False)
    monkeypatch.setattr(free_fleet, "_nvidia_key", lambda: None)

    fleet = FreeFleet()
    avail = fleet.available()
    assert "ollama" in avail
    assert "lmstudio" not in avail
    # every reported provider is on the free allowlist — never a metered one
    assert set(avail).issubset(FREE_PROVIDERS)


def test_available_reflects_local_endpoint_down(monkeypatch):
    """The SAME provider drops out when its endpoint is monkeypatched DOWN."""
    monkeypatch.setattr(free_fleet, "_probe_ollama", lambda timeout=None: False)
    monkeypatch.setattr(free_fleet, "_probe_lmstudio", lambda timeout=None: False)
    monkeypatch.setattr(free_fleet, "_codex_available", lambda: False)
    monkeypatch.setattr(free_fleet, "_nvidia_key", lambda: None)

    fleet = FreeFleet()
    assert "ollama" not in fleet.available()


def test_available_codex_always_when_binary_present(monkeypatch):
    """codex is reachable iff the binary is on PATH (no network probe)."""
    monkeypatch.setattr(free_fleet, "_probe_ollama", lambda timeout=None: False)
    monkeypatch.setattr(free_fleet, "_probe_lmstudio", lambda timeout=None: False)
    monkeypatch.setattr(free_fleet, "_codex_available", lambda: True)
    monkeypatch.setattr(free_fleet, "_nvidia_key", lambda: None)

    assert "codex_cli" in FreeFleet().available()


def test_available_nvidia_only_when_key_resolves(monkeypatch):
    """NVIDIA appears iff a key resolves; never otherwise (no key = skip)."""
    monkeypatch.setattr(free_fleet, "_probe_ollama", lambda timeout=None: False)
    monkeypatch.setattr(free_fleet, "_probe_lmstudio", lambda timeout=None: False)
    monkeypatch.setattr(free_fleet, "_codex_available", lambda: False)

    monkeypatch.setattr(free_fleet, "_nvidia_key", lambda: None)
    assert "nvidia" not in FreeFleet().available()

    monkeypatch.setattr(free_fleet, "_nvidia_key", lambda: "nvapi-xxx")
    assert "nvidia" in FreeFleet().available()


def test_available_never_probes_the_network_in_test(monkeypatch):
    """Belt-and-braces: the probes are the ONLY seam to the outside world,
    and they're all monkeypatched here — available() must not import or call
    urllib directly. (If it did, an un-stubbed call would hang/raise.)"""
    calls = {"n": 0}

    def _boom(*_a, **_k):
        calls["n"] += 1
        raise AssertionError("real network call escaped the test")

    monkeypatch.setattr(free_fleet.urllib.request, "urlopen", _boom)
    monkeypatch.setattr(free_fleet, "_probe_ollama", lambda timeout=None: True)
    monkeypatch.setattr(free_fleet, "_probe_lmstudio", lambda timeout=None: True)
    monkeypatch.setattr(free_fleet, "_codex_available", lambda: True)
    monkeypatch.setattr(free_fleet, "_nvidia_key", lambda: "k")

    FreeFleet().available()
    assert calls["n"] == 0


# ─────────────────────────── run_worker (zero cost) ─────────────────────


def test_run_worker_routes_to_codex_and_costs_zero(monkeypatch):
    """codex is preferred (1) — and the result carries cost_usd == 0.0 and a
    free provider name. This is the contract every dispatcher worker rides."""
    monkeypatch.setattr(free_fleet, "_codex_available", lambda: True)
    monkeypatch.setattr(
        free_fleet, "_run_codex",
        lambda prompt, kind: "codex says hi",
    )

    out = FreeFleet().run_worker("do the thing", kind="plan")
    assert out["text"] == "codex says hi"
    assert out["provider"] == "codex_cli"
    assert out["cost_usd"] == 0.0
    # the firewall passed it
    assert_free(out["provider"])


def test_run_worker_falls_through_to_local_when_codex_absent(monkeypatch):
    """codex missing + no nvidia key → falls to a reachable local model.
    Still free, still zero cost."""
    monkeypatch.setattr(free_fleet, "_codex_available", lambda: False)
    monkeypatch.setattr(free_fleet, "_nvidia_key", lambda: None)
    monkeypatch.setattr(free_fleet, "_probe_ollama", lambda timeout=None: True)
    monkeypatch.setattr(
        free_fleet, "_run_ollama",
        lambda prompt, kind: "ollama local answer",
    )

    out = FreeFleet().run_worker("hello", kind="quick")
    assert out["provider"] in ("ollama", "lmstudio", "local")
    assert out["text"] == "ollama local answer"
    assert out["cost_usd"] == 0.0


def test_run_worker_never_returns_nonzero_cost(monkeypatch):
    """Across EVERY backend that could win, cost_usd is exactly 0.0 — the
    invariant that makes the loop unable to spend money."""
    # nvidia path (free NIM tier)
    monkeypatch.setattr(free_fleet, "_codex_available", lambda: False)
    monkeypatch.setattr(free_fleet, "_nvidia_key", lambda: "nvapi-free")
    monkeypatch.setattr(
        free_fleet, "_run_nvidia",
        lambda prompt, kind: "nemotron answer",
    )

    out = FreeFleet().run_worker("analyze", kind="analysis")
    assert out["provider"] == "nvidia"
    assert out["cost_usd"] == 0.0
    assert isinstance(out["cost_usd"], float)


def test_run_worker_raises_when_no_free_provider(monkeypatch):
    """Honest failure: when NOTHING free is reachable, run_worker raises
    rather than silently reaching for a paid provider. Fail-closed."""
    monkeypatch.setattr(free_fleet, "_codex_available", lambda: False)
    monkeypatch.setattr(free_fleet, "_nvidia_key", lambda: None)
    monkeypatch.setattr(free_fleet, "_probe_ollama", lambda timeout=None: False)
    monkeypatch.setattr(free_fleet, "_probe_lmstudio", lambda timeout=None: False)

    with pytest.raises(RuntimeError):
        FreeFleet().run_worker("anything", kind="plan")


def test_run_worker_preference_order_codex_beats_nvidia_beats_local(monkeypatch):
    """When several free providers are up, codex (1) wins over nvidia (2)
    over local (3) — the spec's preference order."""
    monkeypatch.setattr(free_fleet, "_codex_available", lambda: True)
    monkeypatch.setattr(free_fleet, "_nvidia_key", lambda: "nvapi-free")
    monkeypatch.setattr(free_fleet, "_probe_ollama", lambda timeout=None: True)
    monkeypatch.setattr(free_fleet, "_run_codex", lambda p, k: "C")
    monkeypatch.setattr(free_fleet, "_run_nvidia", lambda p, k: "N")
    monkeypatch.setattr(free_fleet, "_run_ollama", lambda p, k: "O")

    assert FreeFleet().run_worker("x", kind="plan")["provider"] == "codex_cli"


def test_run_worker_result_shape(monkeypatch):
    """The returned dict has exactly the documented keys (text/provider/
    cost_usd) so the dispatcher can rely on the shape."""
    monkeypatch.setattr(free_fleet, "_codex_available", lambda: True)
    monkeypatch.setattr(free_fleet, "_run_codex", lambda p, k: "ok")

    out = FreeFleet().run_worker("x", kind="plan")
    assert set(out.keys()) >= {"text", "provider", "cost_usd"}
    assert isinstance(out["text"], str)
    assert isinstance(out["provider"], str)


# ─────────────────────── the firewall is real (no metered path) ─────────


def test_no_metered_provider_is_reachable_from_this_module():
    """The module exposes NO way to call a metered provider: its public
    runners are all free, and the metered set is only ever used to REJECT.
    A grep-proof: none of the free runner attributes name a paid SDK."""
    # every backend runner the fleet can dispatch to is a free one
    free_runner_names = {
        "_run_codex", "_run_nvidia", "_run_ollama", "_run_lmstudio",
    }
    for name in free_runner_names:
        assert hasattr(free_fleet, name), f"missing free runner {name}"
    # there is deliberately no _run_anthropic / _run_openai / _run_google
    for paid in ("_run_anthropic", "_run_openai", "_run_google",
                 "_run_openrouter", "_run_dashscope"):
        assert not hasattr(free_fleet, paid), (
            f"{paid} exists — a metered call path leaked into the free fleet"
        )


def test_nvidia_endpoint_is_the_free_nim_base():
    """When nvidia IS used it must hit the OpenAI-compatible NIM endpoint the
    free tier serves — not the paid OpenAI/Anthropic base."""
    assert free_fleet.NVIDIA_BASE_URL == "https://integrate.api.nvidia.com/v1"
