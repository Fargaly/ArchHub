"""Resolve op://vault/item/field secret references at call time.

BRAIN-FIRST mandate: secrets are NEVER stored resolved — only references
travel through brain memory. This resolver turns a reference into a value
at the moment of use, via (in order) the 1Password CLI, then Windows
Credential Manager, then an OP_<VAULT>_<ITEM>_<FIELD> env-var fallback.
Returns None when unresolvable (caller decides whether that's fatal).
"""
from __future__ import annotations

import os
import shutil
import subprocess
from typing import Optional

# 1Password CLI calls get a short timeout so a hung/uninstalled `op`
# can never block a tool call.
_OP_TIMEOUT_S = 5.0


def parse_op_ref(ref: str) -> Optional[tuple[str, str, str]]:
    """Parse an ``op://vault/item/field`` reference into its parts.

    Returns ``(vault, item, field)`` for a well-formed op reference,
    or ``None`` when ``ref`` is not an op reference (or is malformed —
    fewer than three path segments after the scheme).
    """
    if not ref or not isinstance(ref, str):
        return None
    if not ref.startswith("op://"):
        return None
    body = ref[len("op://"):]
    parts = body.split("/")
    if len(parts) < 3:
        return None
    vault, item, field = parts[0], parts[1], parts[2]
    if not vault or not item or not field:
        return None
    return vault, item, field


def _env_name(vault: str, item: str, field: str) -> str:
    """Map an op reference triple to its env-var fallback name:
    ``OP_<VAULT>_<ITEM>_<FIELD>`` — uppercased, ``/`` and ``-`` → ``_``."""

    def _norm(part: str) -> str:
        return part.upper().replace("/", "_").replace("-", "_")

    return f"OP_{_norm(vault)}_{_norm(item)}_{_norm(field)}"


def _try_op_cli(ref: str) -> Optional[str]:
    """Resolve via the 1Password CLI (``op read``). Returns None unless
    ``op`` is on PATH and exits 0 with non-empty stdout."""
    if shutil.which("op") is None:
        return None
    try:
        proc = subprocess.run(
            ["op", "read", ref],
            capture_output=True,
            text=True,
            timeout=_OP_TIMEOUT_S,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    if proc.returncode != 0:
        return None
    value = (proc.stdout or "").strip()
    return value or None


def _try_keyring(vault: str, item: str, field: str) -> Optional[str]:
    """Resolve via Windows Credential Manager (or any platform keyring
    backend) using the ``keyring`` package. Lazy-imported + fully
    guarded so a missing/broken backend is non-fatal."""
    try:
        import keyring  # type: ignore
    except Exception:
        return None
    try:
        value = keyring.get_password(f"{vault}/{item}", field)
    except Exception:
        return None
    if value is None:
        return None
    value = value.strip()
    return value or None


def resolve_secret(ref: str) -> Optional[str]:
    """Resolve a secret reference into its value.

    Resolution order:
      1. If ``ref`` is not an ``op://`` reference, return it unchanged
         (plain passthrough — test/dev convenience; matches the prior
         ``cloud_archive._resolve_secret_ref`` behaviour).
      2. 1Password CLI (``op read``), only if ``op`` is on PATH.
      3. Windows Credential Manager / keyring backend.
      4. Env-var fallback ``OP_<VAULT>_<ITEM>_<FIELD>``.

    Returns ``None`` when ``ref`` is falsy or an op reference that
    cannot be resolved by any path.
    """
    if not ref:
        return None
    parsed = parse_op_ref(ref)
    if parsed is None:
        # Not an op reference (and non-empty) → plain passthrough.
        return ref
    vault, item, field = parsed

    via_cli = _try_op_cli(ref)
    if via_cli is not None:
        return via_cli

    via_keyring = _try_keyring(vault, item, field)
    if via_keyring is not None:
        return via_keyring

    env_val = os.environ.get(_env_name(vault, item, field))
    if env_val:
        return env_val

    return None
