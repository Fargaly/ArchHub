"""Dependency-free OpenRouter defaults shared by desktop and cloud relay."""

FREE_MODELS = (
    "dots-studio/dots-3-note-preview:free",
    "cohere/north-mini-code:free",
    "nvidia/nemotron-3.5-lightning:free",
)

RELAY_PREFERRED_MODELS = (
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    FREE_MODELS[0],
    "nvidia/nemotron-3.5-super-vl:free",
    *FREE_MODELS[1:],
)
