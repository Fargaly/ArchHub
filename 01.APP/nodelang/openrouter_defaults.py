"""Dependency-free OpenRouter defaults shared by desktop and cloud relay."""

FREE_MODELS = (
    "nvidia/nemotron-3.5-lightning:free",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
    "nvidia/nemotron-3.5-super-vl:free",
)

RELAY_PREFERRED_MODELS = (
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    *FREE_MODELS,
)
