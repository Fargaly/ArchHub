"""Canonical host ids and backwards-compatible aliases.

Host ids are contract surfaces: connector registration, host detection,
tool dispatch, and bridge calls must all resolve the same live host even
when an older caller uses a short legacy name.
"""
from __future__ import annotations


HOST_ALIASES: dict[str, str] = {
    "acad": "autocad",
}


def canonical_host(host: str | None) -> str:
    """Return the canonical host id for a user/caller supplied host name."""
    key = str(host or "").strip().lower()
    return HOST_ALIASES.get(key, key)


def host_lookup_names(host: str | None) -> tuple[str, ...]:
    """Return the canonical host plus any aliases that should resolve to it."""
    canonical = canonical_host(host)
    names = [canonical]
    names.extend(
        alias for alias, target in HOST_ALIASES.items()
        if target == canonical and alias not in names
    )
    return tuple(names)


def canonical_op_id(op_id: str | None) -> str:
    """Canonicalize the host prefix of a connector op id.

    Examples:
      acad.list_layers -> autocad.list_layers
      revit.list_views -> revit.list_views
    """
    raw = str(op_id or "").strip()
    host, sep, verb = raw.partition(".")
    if not sep:
        return raw
    return f"{canonical_host(host)}.{verb}"
