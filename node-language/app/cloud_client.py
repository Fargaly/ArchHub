"""ArchHub Cloud HTTP client — talks to cloud.archhub.io.

Open-core monetization spine. The desktop app stays open-source under
AGPL; users who don't want to bring their own provider keys or
manage a local Ollama can pay a monthly subscription and route every
LLM call through our managed proxy. Same UI, no install friction,
recurring revenue.

This module is the thin HTTP wrapper. It does NOT contain any
provider-specific logic — the proxy at cloud.archhub.io exposes an
OpenAI-compatible Chat Completions endpoint, so the archhub_cloud
LLM client reuses the existing OpenAI wire format.

Endpoints (see docs/BACKEND_SPEC.md for the full contract):

    POST /v1/auth/register        { email } -> 202 (magic link sent)
    POST /v1/auth/exchange        { code, code_verifier } -> { token, expires_at, plan }
    GET  /v1/me                   Authorization: Bearer <token>
                                  -> { email, plan, remaining_messages,
                                       period_end, can_upgrade }
    POST /v1/chat/completions     OpenAI-compatible streaming
    POST /v1/billing/checkout     { tier } -> { url }
    GET  /v1/billing/portal       -> { url }

Token storage — SINGLE SOURCE OF TRUTH (v1.4+):
The bearer token now lives in the SAME file the cross-device personal-sync
daemon (personal-brain-mcp) reads:

    %APPDATA%/ArchHub/brain/cloud.json   (Windows)
    ~/AppData/Roaming/ArchHub/brain/cloud.json  (fallback)

with the daemon's EXACT schema (keys: token, cloud_base_url, user_id, email,
display_name — see personal_brain.cloud_config). Before this, the APP wrote
the token to secrets_store ("archhub_cloud_token") while the daemon ONLY read
cloud.json — so app sign-in never activated cross-device sync. Now the app
writes/reads cloud.json DIRECTLY (the daemon's process is separate and its
package is NOT importable from app/, so we mirror its file format here rather
than importing it). A one-time migration copies any pre-existing
secrets_store token into cloud.json on first read so already-signed-in users
are NOT logged out. We still mirror the legacy secrets_store key on write
(best-effort, cheap) for defensive compatibility, but cloud.json is the
authority for every read.

NEVER log or print the raw token (ANTI-LIE / security): only fingerprints.

Public API
----------
    base_url() -> str
    is_signed_in() -> bool
    current_token() -> str | None
    set_token(token, expires_at=None, *, user_id=None, email=None,
              base_url=None) -> None
    clear_token() -> None
    me() -> dict | None
    register(email: str) -> tuple[bool, str]
    exchange(code: str, verifier: str) -> tuple[bool, dict]
    checkout(tier: str) -> str | None
    portal_url() -> str | None
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

_log = logging.getLogger("archhub.cloud_client")


# Override via env var for staging / local backend during development.
# Backend doesn't have to exist for the client to ship — the UI surfaces
# clear "couldn't reach cloud" errors when calls fail.
#
# Default host: the vanity `cloud.archhub.io` does NOT resolve (DNS NXDOMAIN);
# the LIVE backend is `archhub-cloud.fly.dev` (verified serving the real
# contract: /signin → 200, POST /v1/auth/register → 202 {"status":"accepted"},
# /v1/me → 401, /v1/chat/completions POST-only). This is the single source of
# truth for the cloud base — cloud_auth.py (sign-in URL + /v1/brain/sync),
# bridge.py (brain_cloud_backup, community cloud_relay transport), and every
# other client all read through `base_url()`. Stays overridable via
# ARCHHUB_CLOUD_BASE_URL for staging / a future custom domain.
DEFAULT_BASE = os.environ.get(
    "ARCHHUB_CLOUD_BASE_URL", "https://archhub-cloud.fly.dev"
)

# Legacy secrets-store keys. cloud.json is now the source of truth (see module
# docstring); these are kept ONLY for the one-time migration read + a defensive
# best-effort mirror on write. No live reader consults them independently of
# current_token() — verified by grep across app/.
_TOKEN_KEY = "archhub_cloud_token"
_EXPIRY_KEY = "archhub_cloud_token_expires_at"

# Non-daemon key we add to cloud.json for optional client-side expiry. The
# daemon (personal_brain.cloud_config) ignores unknown keys, so storing this
# alongside its schema is purely additive and never confuses the sync worker.
_CLOUD_EXPIRY_KEY = "token_expires_at"


# ---------------------------------------------------------------------------
# Token plausibility (defense-in-depth).
# A REAL bearer comes from POST /v1/auth/exchange and is ALWAYS long (a JWT or
# opaque session token, 32+ chars). The validator's job is to reject obvious
# JUNK — e.g. the 7-char test sentinel "ah_test" that, before the conftest
# APPDATA-isolation fix, leaked into the developer's real cloud.json and left a
# stub token that makes the app read "not signed in" and silently breaks
# cross-device sync. The check is deliberately CONSERVATIVE: length + non-empty
# ONLY. We never inspect the charset, because a valid opaque token may contain
# arbitrary URL-safe / base64 bytes and we must NEVER reject a real one.
# 16 is a safe floor — well below any real bearer, well above any junk stub.
MIN_TOKEN_LEN = 16


def _is_plausible_token(token) -> bool:
    """True iff `token` is a non-empty str whose stripped length >= MIN_TOKEN_LEN.

    Length + non-empty only — intentionally NO charset check (an opaque bearer
    can be any URL-safe/base64 string, so a charset filter risks rejecting a
    valid token). Used as a gate so junk like "ah_test" (7 chars) is never
    persisted (set_token) nor honoured on read (current_token), while a real
    32+ char bearer always passes.
    """
    if not isinstance(token, str):
        return False
    return len(token.strip()) >= MIN_TOKEN_LEN


def _token_fingerprint(token) -> str:
    """A SAFE-to-log fingerprint of a token: length + last 2 chars only.

    NEVER returns the raw token (security mandate: only fingerprints are
    loggable). For a short/empty token the last-2 reveal is harmless (and the
    only case we log is a REFUSED implausible token, which by definition isn't a
    real credential)."""
    s = token.strip() if isinstance(token, str) else ""
    last2 = s[-2:] if len(s) >= 2 else s
    return f"len={len(s)}, …{last2}"


def base_url() -> str:
    return DEFAULT_BASE.rstrip("/")


# ---------------------------------------------------------------------------
# cloud.json — the daemon's personal-sync config file. We read/write it
# DIRECTLY (the daemon's package isn't importable from app/) in its EXACT
# schema so the APP sign-in and the cross-device sync daemon share ONE token.
# ---------------------------------------------------------------------------
def cloud_json_path() -> Path:
    """Resolve %APPDATA%/ArchHub/brain/cloud.json (the daemon's file).

    Mirrors personal_brain.cloud_config.default_cloud_config_path() on the
    Windows branch — APPDATA, falling back to ~/AppData/Roaming when the env
    var is missing — so both processes resolve the identical path.
    """
    base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(base) / "ArchHub" / "brain" / "cloud.json"


def _read_cloud_json() -> dict:
    """Return the parsed cloud.json dict, or {} if absent / unreadable.

    Never raises — a missing or corrupt file yields {} so callers degrade to
    signed-out, exactly like the daemon's _read_config_file.
    """
    path = cloud_json_path()
    try:
        if not path.exists():
            return {}
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError, ValueError):
        return {}


def _write_cloud_json_atomic(data: dict) -> bool:
    """Write `data` to cloud.json atomically (tmp + os.replace), creating the
    dir. Matches the daemon's writer (indent=2, sort_keys=True) so the file
    stays byte-compatible. Returns True on success, False on failure (never
    raises). On POSIX, best-effort tighten perms to 0o600 (token is sensitive).
    """
    path = cloud_json_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", delete=False,
            dir=str(path.parent),
            prefix=path.name + ".", suffix=".tmp",
        ) as f:
            json.dump(data, f, indent=2, sort_keys=True)
            tmp_name = f.name
        os.replace(tmp_name, path)
        if os.name != "nt":
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
        return True
    except OSError:
        return False


def _migrate_legacy_token_if_needed() -> dict:
    """ONE-TIME migration: if cloud.json has no token but the legacy
    secrets_store key still holds one, copy it (and its expiry) into cloud.json
    so an already-signed-in user is NOT logged out by the storage move.

    Returns the (possibly updated) cloud.json dict. Best-effort: if the write
    fails we still return the in-memory dict so the current call sees the
    migrated token.
    """
    data = _read_cloud_json()
    if (data.get("token") or data.get("access_token") or "").strip():
        return data   # cloud.json already authoritative — nothing to migrate
    try:
        from secrets_store import load_setting
        legacy = load_setting(_TOKEN_KEY)
        legacy_exp = load_setting(_EXPIRY_KEY)
    except Exception:
        return data
    if not legacy:
        return data
    data["token"] = str(legacy)
    try:
        if legacy_exp and float(legacy_exp) > 0:
            data[_CLOUD_EXPIRY_KEY] = float(legacy_exp)
    except (TypeError, ValueError):
        pass
    _write_cloud_json_atomic(data)   # best-effort persist of the migration
    return data


# ---------------------------------------------------------------------------
def current_token() -> Optional[str]:
    """Return the persisted bearer token if present + not expired.

    Reads cloud.json (the daemon's file) as the single source of truth, after
    a one-time migration of any legacy secrets_store token. Honours the
    optional client-side expiry stored under `token_expires_at`.
    """
    data = _migrate_legacy_token_if_needed()
    token = (data.get("token") or data.get("access_token") or "").strip()
    if not token:
        return None
    # DEFENSE-IN-DEPTH / self-heal: a non-empty but IMPLAUSIBLE token (e.g. a
    # leaked 7-char "ah_test" still on disk from before the isolation fix) is
    # treated as ABSENT — the app honestly shows signed-out and never attempts
    # sync with junk. NO side effect here (a getter must not rewrite cloud.json);
    # the developer's file is left untouched and his next real sign-in overwrites
    # the stub.
    if not _is_plausible_token(token):
        return None
    exp = data.get(_CLOUD_EXPIRY_KEY)
    try:
        if exp and float(exp) > 0 and time.time() >= float(exp):
            return None   # expired
    except (TypeError, ValueError):
        pass
    return token or None


def is_signed_in() -> bool:
    return bool(current_token())


def set_token(token: str, expires_at: Optional[float] = None, *,
              user_id: Optional[str] = None, email: Optional[str] = None,
              base_url: Optional[str] = None) -> None:
    """Persist the bearer token (+ optional identity) to cloud.json — the
    daemon's file — so APP sign-in immediately activates cross-device sync.

    Merges into the existing cloud.json (preserving any keys the daemon or a
    prior sign-in wrote), writes atomically, and mirrors the legacy
    secrets_store key best-effort for defensive compatibility. Only the keys
    you pass are updated; identity args left None are untouched.

    DEFENSE-IN-DEPTH: an IMPLAUSIBLE non-empty token (e.g. the 7-char test
    sentinel "ah_test") is REFUSED here — we log a fingerprint-only warning and
    return WITHOUT touching cloud.json or the legacy mirror, so a junk token can
    never clobber an existing good one. Preserved as before: token=None
    (identity-only update) and token=""/whitespace (soft clear) both fall
    through to the normal path.
    """
    # Refuse a non-empty-but-implausible token BEFORE any read/write so it can
    # neither persist nor clobber a prior good token. None (identity-only) and
    # "" / whitespace (soft clear) are NOT refused — they keep their existing
    # behavior below.
    if (token is not None and str(token).strip()
            and not _is_plausible_token(token)):
        _log.warning(
            "cloud_client.set_token: refusing implausible token (%s)",
            _token_fingerprint(token),
        )
        return

    data = _read_cloud_json()
    if token is not None:
        data["token"] = str(token).strip()
        # A fresh token supersedes any stale alternate-key copy.
        data.pop("access_token", None)
    if expires_at:
        try:
            data[_CLOUD_EXPIRY_KEY] = float(expires_at)
        except (TypeError, ValueError):
            data.pop(_CLOUD_EXPIRY_KEY, None)
    else:
        # No expiry given → clear any prior one (treat as non-expiring).
        data.pop(_CLOUD_EXPIRY_KEY, None)
    if user_id is not None:
        data["user_id"] = str(user_id).strip()
    if email is not None:
        data["email"] = str(email).strip()
    if base_url is not None:
        # Store under the daemon's preferred key, normalised (no trailing /).
        data["cloud_base_url"] = str(base_url).strip().rstrip("/")
    _write_cloud_json_atomic(data)

    # Best-effort legacy mirror (cheap; cloud.json remains the authority).
    try:
        from secrets_store import save_setting
        save_setting(_TOKEN_KEY, str(token).strip() if token else "")
        save_setting(_EXPIRY_KEY, float(expires_at) if expires_at else 0.0)
    except Exception:
        pass


def clear_token() -> None:
    """Sign-out: remove the token from cloud.json (which stops the daemon too,
    since the token is its only gate) while preserving base_url + cached
    identity. Also clears the legacy secrets_store mirror.
    """
    data = _read_cloud_json()
    had_token = bool((data.get("token") or data.get("access_token") or "").strip())
    data.pop("token", None)
    data.pop("access_token", None)
    data.pop(_CLOUD_EXPIRY_KEY, None)
    if had_token or data:
        _write_cloud_json_atomic(data)

    # Clear the legacy mirror too so no stale copy lingers.
    try:
        from secrets_store import save_setting
        save_setting(_TOKEN_KEY, "")
        save_setting(_EXPIRY_KEY, 0.0)
    except Exception:
        pass


def logout() -> tuple[bool, str]:
    """Sign out of ArchHub Cloud.

    Contract (server-side /v1/auth/logout built by the cloud-backend agent):
        POST /v1/auth/logout   Authorization: Bearer <token>  ->  200 {ok:true}
    The server deletes/revokes the token so it can't be replayed. We then
    ALWAYS clear the local credential, even if the server call failed —
    being signed out locally is the user's expressed intent, and a stale
    encrypted token left on disk after "Sign out" would be the dishonest
    outcome. Returns (server_ok, human_message):

      • token revoked server-side + cleared locally   -> (True,  "Signed out.")
      • offline / server error, but cleared locally    -> (False, "Signed out
        on this device — couldn't reach ArchHub Cloud to revoke the session.")
      • already signed out (no token)                  -> (True,  "Already
        signed out.")

    The local clear is unconditional so the UI can flip to the signed-out
    state honestly no matter what the network did.
    """
    token = current_token()
    if not token:
        # Nothing to revoke; make sure local state is clean and report honestly.
        clear_token()
        return True, "Already signed out."
    # Best-effort server revoke (Bearer). _request reads the token itself.
    r = _request("POST", "/v1/auth/logout", body={}, auth=True, timeout=10.0)
    # Local clear is unconditional — the user asked to sign out.
    clear_token()
    if r.get("status") == "ok":
        return True, "Signed out."
    if r.get("error") == "unreachable":
        return False, ("Signed out on this device — couldn't reach ArchHub "
                       "Cloud to revoke the session.")
    return False, ("Signed out on this device — the cloud sign-out call "
                   "didn't complete.")


# ---------------------------------------------------------------------------
def _request(method: str, path: str, body: Optional[dict] = None,
              auth: bool = True, timeout: float = 15.0) -> dict:
    """Internal request helper. Returns {status, json|error}."""
    url = f"{base_url()}{path}"
    headers = {"Accept": "application/json",
               "User-Agent": "ArchHub-desktop/1.0"}
    if auth:
        token = current_token()
        if not token:
            return {"status": "error", "error": "not_signed_in"}
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers,
                                    method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(raw) if raw else {}
            except Exception:
                payload = {"raw": raw}
            return {"status": "ok", "json": payload,
                     "http_status": resp.status}
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8", errors="replace")
            err_json = json.loads(err_body) if err_body else {}
        except Exception:
            err_json = {}
        return {"status": "error",
                 "error": f"http_{e.code}",
                 "json": err_json}
    except urllib.error.URLError as e:
        return {"status": "error", "error": "unreachable",
                 "detail": str(e.reason)}
    except Exception as e:
        return {"status": "error", "error": f"{type(e).__name__}",
                 "detail": str(e)}


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def register(email: str) -> tuple[bool, str]:
    """Trigger a magic-link / OTP send. Returns (ok, human_message)."""
    if not email or "@" not in email:
        return False, "Enter a valid email."
    r = _request("POST", "/v1/auth/register",
                  body={"email": email}, auth=False)
    if r["status"] == "ok":
        return True, "Check your inbox for the sign-in link."
    if r["error"] == "unreachable":
        return False, "Couldn't reach ArchHub Cloud — check your internet."
    return False, "Sign-up failed. Try again in a moment."


def exchange(code: str, code_verifier: str) -> tuple[bool, dict]:
    """Exchange a one-time code (from the magic link or browser flow)
    for a bearer token. Returns (ok, payload_or_error_dict)."""
    r = _request("POST", "/v1/auth/exchange", body={
        "code": code, "code_verifier": code_verifier,
    }, auth=False)
    if r["status"] != "ok":
        return False, r
    j = r.get("json") or {}
    token = j.get("token")
    if not token:
        return False, {"error": "no_token_returned"}
    set_token(token, expires_at=j.get("expires_at"))
    return True, j


# ---------------------------------------------------------------------------
# Account info
# ---------------------------------------------------------------------------
def me() -> Optional[dict]:
    """Fetch current user state.

    The server's /v1/me payload (cloud_backend/main.py) returns:
        { user_id, brain_id, email, plan, remaining_messages,
          period_end, can_upgrade }

    `user_id` (= the cloud `users.id`) is the key the desktop uses to BIND
    its LOCAL brain to this account — `cloud_auth._pair_brain` reads it and
    calls `brain.set_owner(user_id, email)` so every owner-defaulted fragment
    is owned by the signed-in account. `brain_id` is the explicit
    account→brain link (== user_id) the cloud /v1/brain/sync replica is keyed
    on. We pass the raw JSON straight through so callers can read any field;
    `me_identity()` is the convenience accessor for the bind path.

    Returns the JSON payload on success, or None when not signed in /
    backend unreachable. Callers handle None as "show sign-in CTA".
    """
    r = _request("GET", "/v1/me")
    if r["status"] != "ok":
        return None
    return r.get("json") or None


def me_identity() -> Optional[dict]:
    """Convenience accessor for the brain-binding path: returns just the
    identity fields the local brain needs — {user_id, email, brain_id} —
    or None when not signed in / cloud unreachable. Reads the NEW `user_id`
    field the server added to /v1/me. Returns None (rather than a dict with
    an empty user_id) when the server didn't surface a user_id, so callers
    can graceful-degrade without binding the brain to a blank owner."""
    info = me() or {}
    uid = info.get("user_id")
    if not uid:
        return None
    return {
        "user_id": str(uid),
        "email": info.get("email") or "",
        "brain_id": info.get("brain_id") or str(uid),
    }


# ---------------------------------------------------------------------------
# Billing
# ---------------------------------------------------------------------------
def checkout(tier: str) -> Optional[str]:
    """Create a Stripe Checkout session for the chosen tier and
    return the checkout URL. Caller opens the URL in the user's
    default browser."""
    r = _request("POST", "/v1/billing/checkout", body={"tier": tier})
    if r["status"] != "ok":
        return None
    j = r.get("json") or {}
    return j.get("url")


def portal_url() -> Optional[str]:
    """Stripe Customer Portal URL — for plan changes / cancel."""
    r = _request("GET", "/v1/billing/portal")
    if r["status"] != "ok":
        return None
    j = r.get("json") or {}
    return j.get("url")


# ---------------------------------------------------------------------------
# Memory / training pipeline (v1.3.3+)
# ---------------------------------------------------------------------------
def memory_capture(*, role: str, content: str, tool_trace: list,
                    intent: Optional[str] = None) -> Optional[dict]:
    """Send one approved chat turn to the training data store.

    The desktop calls this when the user clicks 'Approve for training'
    on an assistant message. The backend stamps it pending-redact and
    queues it for the Judge stage. Returns the persisted row or None
    on auth/network failure (caller can retry from local queue).
    """
    body = {"role": role, "content": content,
            "tool_trace": tool_trace,
            "intent": intent or ""}
    r = _request("POST", "/v1/memory/capture", body=body)
    if r["status"] != "ok":
        return None
    return r.get("json") or None


def memory_stats() -> Optional[dict]:
    """Pull counters for the 4 pipeline stages.

    Shape: {capture_today, redact_clean, judge_queued, train_ready}.
    Returns None when not signed in OR cloud unreachable so the UI
    can render '—' without crashing.
    """
    r = _request("GET", "/v1/memory/stats")
    if r["status"] != "ok":
        return None
    return r.get("json") or None


# ---------------------------------------------------------------------------
# Brain replica sync (Slice-17 cloud fanout)
# ---------------------------------------------------------------------------
def brain_sync(*, delta: dict, since_hlc: str = "",
               community_keys: Optional[list] = None,
               timeout: float = 20.0) -> dict:
    """Push a brain delta to the cloud replica + pull the MERGED delta back.

    This is the single client entry point for the Slice-17 fanout. The body
    matches `cloud_backend/main.brain_sync`:

        POST /v1/brain/sync  Authorization: Bearer <token>
        { since_hlc, delta:{fragments,wiring}, community_keys:[...] }
      → { accepted, rejected, new_hlc, merged:{fragments,wiring,new_hlc},
          firm_keys, community_keys }

    `delta.fragments` SHOULD include USER + FIRM + COMMUNITY scope rows — the
    cloud routes FIRM/COMMUNITY to shared replicas keyed by firm_id /
    community_id so a teammate's / second device's facts converge, while USER
    stays private per account. `community_keys` names the communities this
    device belongs to (the cloud has no membership table for brain-side
    groups — the join-code already authorised the device), so their shared
    replicas are unioned into the merged read.

    Returns the parsed server JSON on success, or
    {"error": <reason>, "detail"?: ...} on auth/network/HTTP failure — the
    caller (bridge.brain_cloud_backup) decides how to surface it. Never
    raises for a transport error; reuses `_request` so the Bearer token +
    error envelope are identical to every other cloud call.
    """
    body: dict = {"since_hlc": since_hlc or "", "delta": delta or {}}
    if community_keys:
        body["community_keys"] = [str(k) for k in community_keys if k]
    r = _request("POST", "/v1/brain/sync", body=body, timeout=timeout)
    if r["status"] != "ok":
        return {"error": r.get("error") or "unreachable",
                "detail": r.get("detail") or r.get("json")}
    return r.get("json") or {}
