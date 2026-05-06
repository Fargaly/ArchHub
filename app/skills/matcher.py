"""SkillMatcher — rank Skills against a user prompt.

Two tiers:
  1. Cheap keyword/lexical score — fast, no LLM, deterministic.
  2. Optional LLM rerank — when the top scores are tied or low, send the
     top-N candidates to a small model (Haiku) for a final pick.

v0.7 ships tier 1 only. Tier 2 is wired but off by default; flip
`use_llm_rerank=True` once Haiku quota is comfortable.

Returns MatchResult list sorted by score (high first).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from .library import list_skills


@dataclass
class MatchResult:
    skill_id: str
    name: str
    intent: str
    score: float                       # 0.0 .. 1.0
    why: str                           # short explanation: "matched 'wall', 'dimension'"
    requires: list[str]
    examples: list[dict]


_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z\-]+")


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(text or "")}


def _stems(tok: str) -> set[str]:
    """Return cheap morphological variants of a token: as-is, +/- trailing
    's', and the bare verb stem for common -ing/-ed forms. Avoids a real
    stemmer dependency while catching plural/singular and tense mismatches."""
    out = {tok}
    if tok.endswith("s") and len(tok) > 3:
        out.add(tok[:-1])
    else:
        out.add(tok + "s")
    if tok.endswith("ing") and len(tok) > 5:
        out.add(tok[:-3])
    if tok.endswith("ed") and len(tok) > 4:
        out.add(tok[:-2])
    return out


def _keyword_score(prompt_toks: set[str], skill: dict) -> tuple[float, list[str]]:
    """Score = weighted overlap with keywords + intent + name + tags.

    Tokens are matched against a cheap stem set so "labels" hits the
    keyword "label" and "dimensioning" hits "dimension".
    """
    if not prompt_toks:
        return 0.0, []

    keyword_toks = {k.lower() for k in (skill.get("keywords") or [])}
    intent_toks = _tokens(skill.get("intent", ""))
    name_toks = _tokens(skill.get("name", ""))
    tag_toks = {t.lower() for t in (skill.get("tags") or [])}

    matched: set[str] = set()
    score = 0.0
    for tok in prompt_toks:
        variants = _stems(tok)
        if variants & keyword_toks:
            score += 3.0; matched.add(tok)
        elif variants & tag_toks:
            score += 2.0; matched.add(tok)
        elif variants & name_toks:
            score += 1.5; matched.add(tok)
        elif variants & intent_toks:
            score += 1.0; matched.add(tok)

    # Normalise: max possible if every prompt token hit a keyword
    max_score = 3.0 * len(prompt_toks)
    norm = min(1.0, score / max_score) if max_score > 0 else 0.0
    return norm, sorted(matched)


def _usage_boost(skill_id: str) -> float:
    """Multiplicative score boost based on how often this Skill has been
    used and how reliably. Range roughly [0.85, 1.30].

    Rationale: a Skill that the firm runs daily and succeeds 95% of the
    time should outrank a brand-new one with the same keyword score. A
    Skill that fails most of the time should be demoted, not silently
    surfaced. The boost is multiplicative so it shifts ordering when
    keyword scores are close, but never overrides a clearly-better
    keyword match.
    """
    try:
        from .usage import get_usage
        u = get_usage(skill_id) or {}
    except Exception:
        return 1.0
    runs = int(u.get("runs") or 0)
    if runs == 0:
        return 1.0
    successes = int(u.get("successes") or 0)
    success_rate = successes / runs

    # Frequency: log-scaled so a Skill with 3 runs gets a small boost,
    # 30 runs gets a bigger one, 300 runs hits the cap.
    import math
    freq_boost = min(0.20, 0.06 * math.log1p(runs))

    # Reliability: > 80% success → small positive contribution; < 50% →
    # noticeable demotion. Linear inside that band.
    if success_rate >= 0.80:
        rel_boost = 0.10 * (success_rate - 0.80) / 0.20    # 0..0.10
    elif success_rate >= 0.50:
        rel_boost = 0.0
    else:
        rel_boost = -0.15 * (0.50 - success_rate) / 0.50    # -0.15..0

    return 1.0 + freq_boost + rel_boost


def match_skills(
    prompt: str,
    *,
    top_k: int = 3,
    min_score: float = 0.15,
    active_connectors: Optional[set[str]] = None,
    use_llm_rerank: bool = False,
    router=None,
) -> list[MatchResult]:
    """Return top_k Skills ranked for the prompt. Filters out skills whose
    `requires` connectors are not currently active (if active_connectors
    given). Final ranking blends keyword score with usage history: Skills
    that the user runs successfully get a multiplicative boost; Skills
    that fail more than 50% of the time are demoted.
    """
    prompt_toks = _tokens(prompt)
    skills = list_skills()
    if active_connectors is not None:
        skills = [
            s for s in skills
            if not s.get("requires") or all(r in active_connectors for r in s["requires"])
        ]

    scored: list[MatchResult] = []
    for s in skills:
        keyword, matched = _keyword_score(prompt_toks, s)
        if keyword < min_score:
            continue
        score = keyword * _usage_boost(s["id"])
        why = f"matched: {', '.join(matched)}" if matched else "weak match"
        scored.append(MatchResult(
            skill_id=s["id"], name=s["name"], intent=s["intent"],
            score=score, why=why,
            requires=list(s.get("requires") or []),
            examples=list(s.get("examples") or []),
        ))

    scored.sort(key=lambda m: m.score, reverse=True)
    top = scored[:top_k]

    if use_llm_rerank and router is not None and len(top) > 1:
        top = _llm_rerank(prompt, top, router)

    return top


_RERANK_MODEL_PREFERENCES = (
    "anthropic:claude-haiku-4-5-20251001",
    "openai:gpt-4o-mini",
    "google:gemini-2.0-flash",
)


def _pick_rerank_model(router) -> str:
    """Choose the cheapest rerank model the router can actually run.
    Falls back to 'auto' for local/Ollama setups."""
    try:
        providers = set(router.configured_providers())
    except Exception:
        return "auto"
    for model_id in _RERANK_MODEL_PREFERENCES:
        if model_id.partition(":")[0] in providers:
            return model_id
    return "auto"


def _llm_rerank(prompt: str, candidates: list[MatchResult], router) -> list[MatchResult]:
    """Ask a fast small model to reorder the top candidates."""
    listing = "\n".join(
        f"{i+1}. {c.name} — {c.intent}" for i, c in enumerate(candidates)
    )
    history = [{
        "role": "user",
        "content": (
            "Pick the single best skill for the user's prompt. Respond with "
            "ONLY the number (1, 2, 3, ...). If none fit well, respond with 0.\n\n"
            f"User prompt:\n{prompt}\n\nCandidate skills:\n{listing}"
        ),
    }]
    try:
        resp = router.complete(history, model=_pick_rerank_model(router))
        first = (resp.text or "").strip().split()
        idx = int(first[0]) if first else 0
        if 1 <= idx <= len(candidates):
            picked = candidates[idx - 1]
            return [picked] + [c for c in candidates if c.skill_id != picked.skill_id]
    except Exception:
        pass
    return candidates
