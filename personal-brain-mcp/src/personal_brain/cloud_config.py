"""Personal cloud-sync config + identity (Brain personal cross-device sync).

The PERSONAL (USER-scope) brain syncs across this user's devices through the
EXISTING ArchHub cloud (archhub-cloud.fly.dev) — per-user, private. This
module is the single place that resolves:

  * `cloud_base_url` — where the cloud lives (default
    https://archhub-cloud.fly.dev)
  * `token`          — the signed-in user's bearer token (identifies the
                       user; per-user isolation is enforced server-side)
  * `user_id` / `email` — cached identity from /v1/me (informational)

Resolution order (first non-empty wins), for BOTH base url + token:
  1. environment  — ARCHHUB_CLOUD_URL / ARCHHUB_CLOUD_TOKEN
  2. config file  — %APPDATA%/ArchHub/brain/cloud.json (Windows) /
                    ~/.local/share/archhub/brain/cloud.json (POSIX),
                    co-located with brain.db so the two move together.

Hard rule (BRAIN-FIRST + ANTI-LIE): if NO token resolves, personal sync is
INERT — `is_signed_in()` is False, the worker no-ops + logs, the daemon
never crashes + never blocks. The token is the ONLY gate.

This module touches NO secrets beyond the bearer token itself (which is the
user's own session token, stored locally — never synced anywhere). It does
not import the heavy worker / privacy stack so it stays cheap to import from
the CLI + the daemon boot path.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


# The deployed ArchHub cloud. Overridable via ARCHHUB_CLOUD_URL or the
# `cloud_base_url` key in cloud.json — e.g. to point at a local dev backend.
DEFAULT_CLOUD_BASE_URL = "https://archhub-cloud.fly.dev"

# Environment overrides (highest precedence).
ENV_CLOUD_URL = "ARCHHUB_CLOUD_URL"
ENV_CLOUD_TOKEN = "ARCHHUB_CLOUD_TOKEN"


def default_cloud_config_path() -> Path:
    """Location of cloud.json — co-located with brain.db.

    Mirrors `storage.default_brain_path()` so the personal-sync config lives
    in the SAME directory as the brain it syncs (%APPDATA%/ArchHub/brain on
    Windows, ~/.local/share/archhub/brain on POSIX).
    """
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", str(Path.home() / "AppData/Roaming")))
        return base / "ArchHub" / "brain" / "cloud.json"
    base = Path(os.environ.get("XDG_DATA_HOME",
                               str(Path.home() / ".local" / "share")))
    return base / "archhub" / "brain" / "cloud.json"


def _normalise_base_url(url: str) -> str:
    """Strip a trailing slash so we can append `/v1/...` cleanly."""
    return (url or "").strip().rstrip("/")


@dataclass
class CloudConfig:
    """Resolved personal-sync configuration + identity.

    `token` is the bearer that identifies the signed-in user. `is_signed_in`
    is the single gate the worker + CLI consult — no token → inert.
    """

    base_url: str = DEFAULT_CLOUD_BASE_URL
    token: str = ""
    user_id: str = ""
    email: str = ""
    display_name: str = ""
    # Where each value came from — for diagnostics / health.
    token_source: str = "none"      # env | file | none
    url_source: str = "default"     # env | file | default
    config_path: str = ""

    @property
    def is_signed_in(self) -> bool:
        """True only when a non-empty bearer token resolved. The ONLY gate."""
        return bool((self.token or "").strip())

    def sync_url(self) -> str:
        return f"{_normalise_base_url(self.base_url)}/v1/brain/sync"

    def me_url(self) -> str:
        return f"{_normalise_base_url(self.base_url)}/v1/me"

    def register_url(self) -> str:
        return f"{_normalise_base_url(self.base_url)}/v1/auth/register"

    def exchange_url(self) -> str:
        return f"{_normalise_base_url(self.base_url)}/v1/auth/exchange"

    def auth_header(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def redacted(self) -> dict[str, Any]:
        """A log-safe view — never exposes the raw token."""
        tok = (self.token or "").strip()
        return {
            "base_url": _normalise_base_url(self.base_url),
            "signed_in": self.is_signed_in,
            "token_present": bool(tok),
            "token_fingerprint": (tok[:6] + "…" + tok[-4:]) if len(tok) > 12 else ("set" if tok else ""),
            "user_id": self.user_id,
            "email": self.email,
            "token_source": self.token_source,
            "url_source": self.url_source,
            "config_path": self.config_path,
        }


def _read_config_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def load_cloud_config(path: Optional[str | Path] = None) -> CloudConfig:
    """Resolve the personal-sync config from env + cloud.json.

    Never raises — a missing / corrupt file yields an inert (signed-out)
    config so the daemon boot path is crash-proof.
    """
    cfg_path = Path(path) if path else default_cloud_config_path()
    file_data = _read_config_file(cfg_path)

    # base_url: env > file > default
    env_url = (os.environ.get(ENV_CLOUD_URL) or "").strip()
    file_url = (file_data.get("cloud_base_url") or file_data.get("base_url") or "").strip()
    if env_url:
        base_url, url_source = env_url, "env"
    elif file_url:
        base_url, url_source = file_url, "file"
    else:
        base_url, url_source = DEFAULT_CLOUD_BASE_URL, "default"

    # token: env > file
    env_token = (os.environ.get(ENV_CLOUD_TOKEN) or "").strip()
    file_token = (file_data.get("token") or file_data.get("access_token") or "").strip()
    if env_token:
        token, token_source = env_token, "env"
    elif file_token:
        token, token_source = file_token, "file"
    else:
        token, token_source = "", "none"

    return CloudConfig(
        base_url=base_url,
        token=token,
        user_id=str(file_data.get("user_id") or "").strip(),
        email=str(file_data.get("email") or "").strip(),
        display_name=str(file_data.get("display_name") or "").strip(),
        token_source=token_source,
        url_source=url_source,
        config_path=str(cfg_path),
    )


def save_cloud_config(
    *,
    base_url: Optional[str] = None,
    token: Optional[str] = None,
    user_id: Optional[str] = None,
    email: Optional[str] = None,
    display_name: Optional[str] = None,
    path: Optional[str | Path] = None,
) -> Path:
    """Persist (merge) the personal-sync config to cloud.json atomically.

    Only the keys you pass are updated; existing values are preserved. Writes
    via tmp + os.replace so a crash mid-write can't corrupt the file. Returns
    the path written.

    Best-effort restricts the file to owner-only perms on POSIX (the token is
    sensitive). On Windows the %APPDATA% dir is already per-user.
    """
    cfg_path = Path(path) if path else default_cloud_config_path()
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    current = _read_config_file(cfg_path)

    if base_url is not None:
        current["cloud_base_url"] = _normalise_base_url(base_url)
    if token is not None:
        current["token"] = token.strip()
    if user_id is not None:
        current["user_id"] = user_id.strip()
    if email is not None:
        current["email"] = email.strip()
    if display_name is not None:
        current["display_name"] = display_name.strip()

    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", delete=False,
        dir=str(cfg_path.parent),
        prefix=cfg_path.name + ".", suffix=".tmp",
    ) as f:
        json.dump(current, f, indent=2, sort_keys=True)
        tmp_name = f.name
    os.replace(tmp_name, cfg_path)

    # Best-effort tighten perms on POSIX (token is a credential).
    if os.name != "nt":
        try:
            os.chmod(cfg_path, 0o600)
        except OSError:
            pass
    return cfg_path


def clear_cloud_token(path: Optional[str | Path] = None) -> bool:
    """Remove the token (sign-out) while keeping base_url + cached identity.

    Returns True if a token was present and is now cleared.
    """
    cfg_path = Path(path) if path else default_cloud_config_path()
    current = _read_config_file(cfg_path)
    had = bool((current.get("token") or current.get("access_token") or "").strip())
    current.pop("token", None)
    current.pop("access_token", None)
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", delete=False,
        dir=str(cfg_path.parent),
        prefix=cfg_path.name + ".", suffix=".tmp",
    ) as f:
        json.dump(current, f, indent=2, sort_keys=True)
        tmp_name = f.name
    os.replace(tmp_name, cfg_path)
    if os.name != "nt":
        try:
            os.chmod(cfg_path, 0o600)
        except OSError:
            pass
    return had
