"""ResolverRegistry — references-only secret resolution for ArchHub.

Per BRAIN-FIRST + ANTI-LIE mandates: secret VALUES never live in brain
memory or in this registry's alias file. Only REFERENCES like
`op://<vault>/<item>/<field>` are stored; the registry walks resolvers
at tool-call time and returns the resolved value to the caller (e.g.
`secrets_store.load_api_key`).

Supported reference schemes (in priority order):
  * op://<vault>/<item>/<field> — 1Password CLI (`op read`)
  * wcm://<target>              — Windows Credential Manager (via keyring)
  * env://<VAR>                 — environment variable
  * file://<absolute-path>      — read a file's first line (warns)
  * inline:<...>                — inline literal (deprecated, warns)

UI (Settings → Secrets, agent-3-owned) reads `available()` to render
"1Password not installed" badges and `last4()` to render the safe
trailing-4 suffix. Never call these to render the full value.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Storage layout: aliases.json maps human alias → reference. Never values.
# ---------------------------------------------------------------------------
APP_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ArchHub"
SECRETS_DIR = APP_DIR / "secrets"
ALIASES_FILE = SECRETS_DIR / "aliases.json"


def _ensure_dir() -> None:
    SECRETS_DIR.mkdir(parents=True, exist_ok=True)


def _last4(value: str) -> str:
    """Render a safe ...xxxx suffix for UI display. Never the full value."""
    if not value:
        return "...(empty)"
    tail = value[-4:] if len(value) >= 4 else value
    return f"...{tail}"


# ---------------------------------------------------------------------------
# Individual resolvers
# ---------------------------------------------------------------------------
class _BaseResolver:
    name: str = "base"
    prefix: str = ""

    def available(self) -> bool:  # pragma: no cover - overridden
        return True

    def resolve(self, ref: str, timeout_s: float = 3.0) -> Optional[str]:  # pragma: no cover - overridden
        raise NotImplementedError

    def last4(self, value: str) -> str:
        return _last4(value)


class OnePasswordResolver(_BaseResolver):
    """1Password CLI resolver. Requires `op` binary on PATH."""

    name = "1password"
    prefix = "op://"

    def available(self) -> bool:
        if shutil.which("op") is None:
            return False
        try:
            res = subprocess.run(
                ["op", "--version"],
                capture_output=True,
                timeout=2.0,
                check=False,
            )
            return res.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    def resolve(self, ref: str, timeout_s: float = 3.0) -> Optional[str]:
        if not ref.startswith(self.prefix):
            return None
        if shutil.which("op") is None:
            return None
        try:
            res = subprocess.run(
                ["op", "read", ref],
                capture_output=True,
                timeout=timeout_s,
                check=False,
            )
            if res.returncode != 0:
                return None
            out = res.stdout.decode("utf-8", errors="replace").strip()
            return out or None
        except (OSError, subprocess.SubprocessError):
            return None


class WindowsCredentialManagerResolver(_BaseResolver):
    """Windows Credential Manager via `keyring`. Falls back to None if
    keyring isn't importable. Reference form: `wcm://<target>` where the
    target may be a plain name or `<service>/<account>`."""

    name = "wcm"
    prefix = "wcm://"

    def _keyring(self):
        try:
            import keyring  # type: ignore
            return keyring
        except Exception:
            return None

    def available(self) -> bool:
        return self._keyring() is not None

    def resolve(self, ref: str, timeout_s: float = 3.0) -> Optional[str]:
        if not ref.startswith(self.prefix):
            return None
        kr = self._keyring()
        if kr is None:
            return None
        target = ref[len(self.prefix):]
        if not target:
            return None
        service, _, account = target.partition("/")
        if not account:
            # Treat the whole target as service name + "ArchHub" account
            service, account = "ArchHub", service
        try:
            v = kr.get_password(service, account)
            return v if v else None
        except Exception:
            return None


class EnvVarResolver(_BaseResolver):
    """`env://VAR` — process environment lookup."""

    name = "env"
    prefix = "env://"

    def available(self) -> bool:
        return True

    def resolve(self, ref: str, timeout_s: float = 3.0) -> Optional[str]:
        if not ref.startswith(self.prefix):
            return None
        var = ref[len(self.prefix):].strip()
        if not var:
            return None
        v = os.environ.get(var)
        return v if v else None


class FileResolver(_BaseResolver):
    """`file://<abs-path>` — read a file's stripped contents. Warns: this
    bypasses the OS keystore and is not recommended for production keys."""

    name = "file"
    prefix = "file://"

    def available(self) -> bool:
        return True

    def resolve(self, ref: str, timeout_s: float = 3.0) -> Optional[str]:
        if not ref.startswith(self.prefix):
            return None
        path_str = ref[len(self.prefix):].strip()
        if not path_str:
            return None
        sys.stderr.write(
            f"[resolver_registry] WARNING: file:// resolver is not "
            f"recommended for production keys ({path_str})\n"
        )
        try:
            return Path(path_str).read_text(encoding="utf-8").strip() or None
        except (OSError, UnicodeDecodeError):
            return None


class InlineResolver(_BaseResolver):
    """`inline:<value>` — deprecated; included only so the UI can warn
    on legacy refs migrated from the obfuscated secrets.dat."""

    name = "inline"
    prefix = "inline:"

    def available(self) -> bool:
        return True

    def resolve(self, ref: str, timeout_s: float = 3.0) -> Optional[str]:
        if not ref.startswith(self.prefix):
            return None
        sys.stderr.write(
            "[resolver_registry] WARNING: inline: resolver is deprecated; "
            "migrate to op:// / wcm:// / env:// asap\n"
        )
        return ref[len(self.prefix):] or None


# ---------------------------------------------------------------------------
# The registry itself
# ---------------------------------------------------------------------------
class ResolverRegistry:
    """Walks a fixed-priority list of resolvers, dispatching by prefix.

    Priority (high → low): 1password, wcm, env, file, inline. Higher
    priority resolvers win when an alias's reference matches their
    prefix; resolvers do NOT race — each ref string has exactly one
    eligible resolver.
    """

    DEFAULT_ORDER = (
        OnePasswordResolver,
        WindowsCredentialManagerResolver,
        EnvVarResolver,
        FileResolver,
        InlineResolver,
    )

    def __init__(self, resolvers: Optional[list] = None):
        if resolvers is None:
            self._resolvers = [cls() for cls in self.DEFAULT_ORDER]
        else:
            self._resolvers = list(resolvers)

    # --- resolution ---------------------------------------------------
    def resolve(self, ref: str, timeout_s: float = 3.0) -> dict:
        """Resolve `ref` and return a dict.

        Success: {"value": str, "resolver": str, "last4": "...xxxx"}
        Failure: {"error": str}
        """
        if not ref or not isinstance(ref, str):
            return {"error": "empty or non-string reference"}
        for r in self._resolvers:
            if ref.startswith(r.prefix):
                v = r.resolve(ref, timeout_s=timeout_s)
                if v is None:
                    return {
                        "error": f"{r.name} resolver could not resolve {ref!r}"
                    }
                return {
                    "value": v,
                    "resolver": r.name,
                    "last4": r.last4(v),
                }
        return {"error": f"no resolver matches reference prefix in {ref!r}"}

    # --- aliases ------------------------------------------------------
    @staticmethod
    def _aliases_path() -> Path:
        # Recompute each call so tests that monkeypatch LOCALAPPDATA win.
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ArchHub"
        return base / "secrets" / "aliases.json"

    def _load_aliases(self) -> dict:
        p = self._aliases_path()
        if not p.exists():
            return {}
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_aliases(self, data: dict) -> None:
        p = self._aliases_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")

    def register_alias(self, alias: str, ref: str) -> None:
        """Map a human alias (e.g. "anthropic") to a reference. Refuses
        to store a plain value masquerading as a reference."""
        if not alias or not isinstance(alias, str):
            raise ValueError("alias must be a non-empty string")
        if not ref or not isinstance(ref, str):
            raise ValueError("ref must be a non-empty string")
        if not any(ref.startswith(cls.prefix) for cls in self.DEFAULT_ORDER):
            raise ValueError(
                f"ref {ref!r} does not match any known resolver prefix; "
                "aliases must point to references, not raw values"
            )
        data = self._load_aliases()
        data[alias] = ref
        self._save_aliases(data)

    def get_alias(self, alias: str) -> Optional[str]:
        return self._load_aliases().get(alias)

    def list_aliases(self) -> dict:
        return self._load_aliases()

    def resolve_alias(self, alias: str, timeout_s: float = 3.0) -> dict:
        """Look up an alias and resolve it. Single call for callers
        (e.g. `secrets_store.load_api_key`)."""
        ref = self.get_alias(alias)
        if not ref:
            return {"error": f"no alias registered for {alias!r}"}
        return self.resolve(ref, timeout_s=timeout_s)

    # --- introspection (for UI badges) -------------------------------
    def resolver_status(self) -> dict:
        return {r.name: {"prefix": r.prefix, "available": r.available()}
                for r in self._resolvers}
