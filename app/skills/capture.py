"""Capture a chat conversation as a Skill.

Wraps `chat_to_workflow` with skill-metadata authoring: takes the chat
history that produced a useful result, asks the LLM to fill out the
metadata (intent, keywords, when_to_use, examples), and saves it as a
discoverable Skill.

The generated metadata is editable — the LLM is a starting point, not
the final voice. The save path is the Skill library (see library.save_skill).
"""
from __future__ import annotations

import json
import re
from typing import Optional

from workflows.chat_to_workflow import chat_to_workflow

from .library import save_skill
from .metadata import SkillMeta, SCOPE_USER


_FAST_MODEL_PREFERENCES = (
    "anthropic:claude-haiku-4-5-20251001",
    "openai:gpt-4o-mini",
    "google:gemini-2.0-flash",
)


def _pick_metadata_model(router) -> str:
    """Pick the cheapest available fast model. Falls back to 'auto' so the
    router can route to whatever the user has configured (e.g. Ollama)."""
    providers = set(router.configured_providers())
    for model_id in _FAST_MODEL_PREFERENCES:
        provider, _, _ = model_id.partition(":")
        if provider in providers:
            return model_id
    return "auto"


_META_SYSTEM = """\
You are summarising a successful chat conversation as a reusable Skill in
ArchHub. Output STRICT JSON only — no prose, no code fences. Schema:

{
  "name":         "short human title (2-5 words)",
  "intent":       "one sentence describing what this Skill does",
  "keywords":     ["3-8 lower-case match terms"],
  "when_to_use":  "one sentence: when an architect should pick this Skill",
  "tags":         ["taxonomy: revit | autocad | blender | speckle | annotation | render | parameters"],
  "requires":     ["connector ids that must be active: revit | autocad | blender | max | speckle"]
}

Rules:
- Keywords are lower-case single words or short phrases the matcher will
  check against a user prompt. Include verbs and nouns the architect would
  naturally type.
- Tags pick from the taxonomy above only.
- requires lists only connector families that the chat actually invoked.
- Be terse. No filler. JSON only.
"""


def _extract_first_json(text: str) -> Optional[dict]:
    """Pull the first {...} block from text, parse it. Tolerant of code fences."""
    if not text:
        return None
    # Strip code fences if any
    text = re.sub(r"```(?:json)?\s*", "", text)
    text = text.replace("```", "")
    # Find first balanced { ... }
    depth = 0
    start = -1
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                blob = text[start:i + 1]
                try:
                    return json.loads(blob)
                except Exception:
                    return None
    return None


def _field(m, name: str, default=""):
    """Read `name` from either an object attribute or a dict key."""
    if hasattr(m, name):
        return getattr(m, name)
    if isinstance(m, dict):
        return m.get(name, default)
    return default


def _summarise_history(history: list) -> str:
    """Compact text summary of the chat for the metadata LLM."""
    lines: list[str] = []
    for m in history[-12:]:                 # last 12 turns is plenty
        role = _field(m, "role", "")
        content = _field(m, "content", "") or ""
        invs = _field(m, "tool_invocations", []) or []
        if role == "user":
            lines.append(f"USER: {content[:400]}")
        elif role == "assistant":
            lines.append(f"ASSISTANT: {content[:400]}")
            for inv in invs:
                d = inv.to_dict() if hasattr(inv, "to_dict") else inv
                tool_name = d.get("tool_name", "?") if isinstance(d, dict) else "?"
                lines.append(f"  TOOL: {tool_name}")
    return "\n".join(lines)


def capture_chat_as_skill(
    history: list,
    *,
    router,
    requested_name: Optional[str] = None,
    scope: str = SCOPE_USER,
    author: str = "",
):
    """Capture chat → Workflow + auto-authored SkillMeta. Save and return.

    Returns (workflow, skill_meta, save_path).
    Raises RuntimeError if the LLM cannot produce valid metadata JSON.
    """
    summary = _summarise_history(history)
    # Prepend the metadata-authoring instructions to the user message because
    # LLMRouter.complete owns the system prompt. This keeps the schema rules
    # in front of the model regardless of provider.
    user_prompt = (
        f"{_META_SYSTEM}\n\n"
        f"Conversation transcript:\n{summary}\n\n"
        f"Produce the Skill metadata JSON now."
    )
    msgs = [{"role": "user", "content": user_prompt}]
    # Prefer the cheapest available model; fall back to whatever the router
    # auto-routes to when Haiku is not configured. This keeps capture working
    # for users on local Ollama or non-Anthropic providers.
    model = _pick_metadata_model(router)
    resp = router.complete(msgs, model=model)
    meta_dict = _extract_first_json(resp.text or "")
    if not meta_dict:
        raise RuntimeError(
            "Could not extract metadata JSON from LLM response. "
            f"Raw output (first 200 chars): {(resp.text or '')[:200]!r}"
        )

    name = requested_name or meta_dict.get("name") or "Untitled Skill"
    examples: list[dict] = []
    first_user = next(
        (getattr(m, "content", None) or m.get("content", "")
         for m in history
         if (getattr(m, "role", None) or m.get("role", "")) == "user"),
        "",
    )
    if first_user:
        examples = [{"prompt": first_user[:200], "expected_outcome": meta_dict.get("intent", "")}]

    meta = SkillMeta(
        intent=meta_dict.get("intent", ""),
        keywords=list(meta_dict.get("keywords") or []),
        when_to_use=meta_dict.get("when_to_use", ""),
        examples=examples,
        tags=list(meta_dict.get("tags") or []),
        requires=list(meta_dict.get("requires") or []),
        author=author,
        scope=scope,
    )

    wf = chat_to_workflow(history, name=name, description=meta.intent)
    path = save_skill(wf, meta)
    return wf, meta, path
