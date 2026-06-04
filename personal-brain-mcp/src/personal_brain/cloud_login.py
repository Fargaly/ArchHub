"""CLI: sign in to ArchHub cloud so the PERSONAL brain syncs across devices.

Everything up to the human's email-click is automated:

    python -m personal_brain.cloud_login --email you@studio.com

Flow:
  1. POST /v1/auth/register {email}  → cloud emails a magic-link (202).
  2. The user clicks the magic-link in their inbox (the ONLY manual step —
     a true boundary: it's their sign-in). The link lands on
     /auth/return?code=... in their browser.
  3. We obtain the auth `code` either by:
       • --code <CODE>  : paste it directly (e.g. from the /auth/return URL or
                          a dev console), OR
       • polling        : if the backend exposes a code-pickup, we poll; absent
                          that, we PROMPT for the pasted code (no hang).
  4. POST /v1/auth/exchange {code} → bearer token.
  5. GET /v1/me with the token → user_id / email / plan (identity).
  6. Write token + base_url + identity to cloud.json, and bind the LOCAL brain
     owner (brain_meta) so this device's USER-scope rows are owned by the cloud
     user_id — matching `brain.set_owner`. Personal cloud sync then activates
     on the daemon's next tick (no restart needed — config is re-read per tick).

Resilience: this is a one-shot CLI, not the daemon. It prints clear status and
exits non-zero on failure; it never blocks indefinitely (polling is bounded and
always degrades to a paste prompt).

Sub-commands:
    cloud_login --email <e> [--code <c>] [--base-url <u>] [--db <path>]
    cloud_login login --google [--code <c>]   # Sign in with Google (OAuth)
    cloud_login status            # show current sign-in state (no secrets)
    cloud_login logout            # clear the local token + unbind owner

Sign in with Google (additive — magic-link path unchanged):

    python -m personal_brain.cloud_login login --google

  Generates a PKCE pair (same as the magic-link flow), asks the backend
  for the Google consent URL via /v1/auth/google/start, opens it, and
  finishes via the EXISTING /auth/return + /v1/auth/exchange path — so a
  Google sign-in lands on the SAME account (keyed by email) and the same
  cloud.json token as an emailed magic-link. If the server hasn't been
  configured with Google OAuth credentials yet, /start returns 503 and we
  fall back to telling the user to use --email.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from typing import Any, Optional

from .cloud_config import (
    DEFAULT_CLOUD_BASE_URL,
    clear_cloud_token,
    load_cloud_config,
    save_cloud_config,
)


# brain_meta keys — MUST match server.build_server's account-binding keys so
# the daemon's `resolve_default_owner()` picks up the bound cloud user_id.
_BOUND_OWNER_KEY = "bound_owner_user"
_BOUND_EMAIL_KEY = "bound_owner_email"
_BOUND_NAME_KEY = "bound_owner_display_name"
_BOUND_SET_AT_KEY = "bound_owner_set_at"


def _post_json(url: str, payload: dict[str, Any], *, timeout_s: float = 20.0,
               headers: Optional[dict[str, str]] = None) -> tuple[int, dict[str, Any]]:
    """POST JSON; return (status_code, parsed_body). Tolerates error bodies."""
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as ex:
        raw = ex.read().decode("utf-8", "replace") if ex.fp else ""
        try:
            parsed = json.loads(raw) if raw else {}
        except Exception:
            parsed = {"detail": raw}
        return ex.code, parsed


def _get_json(url: str, *, timeout_s: float = 20.0,
              headers: Optional[dict[str, str]] = None) -> tuple[int, dict[str, Any]]:
    req = urllib.request.Request(url, method="GET")
    req.add_header("Accept", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as ex:
        raw = ex.read().decode("utf-8", "replace") if ex.fp else ""
        try:
            parsed = json.loads(raw) if raw else {}
        except Exception:
            parsed = {"detail": raw}
        return ex.code, parsed


def _extract_code_from_input(raw: str) -> str:
    """Accept either a bare code OR a pasted /auth/return URL and pull `code`."""
    raw = (raw or "").strip()
    if not raw:
        return ""
    if "code=" in raw:
        # e.g. https://.../auth/return?code=ABC123&state=archhub
        try:
            from urllib.parse import urlparse, parse_qs
            qs = parse_qs(urlparse(raw).query)
            if qs.get("code"):
                return qs["code"][0].strip()
        except Exception:
            pass
        # Fallback: substring after code=
        tail = raw.split("code=", 1)[1]
        return tail.split("&", 1)[0].strip()
    return raw


def _prompt_for_code() -> str:
    """Ask the user to paste the code/URL from the magic-link. Bounded — reads
    one line from stdin; if stdin is not a TTY (non-interactive), returns ''."""
    if not sys.stdin or not sys.stdin.isatty():
        return ""
    try:
        sys.stderr.write(
            "\nPaste the sign-in code (or the full /auth/return?code=... URL) "
            "from the magic-link, then press Enter:\n> "
        )
        sys.stderr.flush()
        return _extract_code_from_input(sys.stdin.readline())
    except Exception:
        return ""


def _pkce_pair() -> tuple[str, str]:
    """Generate a PKCE (verifier, challenge) pair — RFC 7636 S256.

    Mirrors the magic-link/browser PKCE shape used elsewhere in ArchHub:
    a 32-byte urlsafe verifier (~43 chars, clears the server's
    _PKCE_VERIFIER_MIN_LEN floor) and its base64url(SHA-256) challenge.
    Used by the Google sign-in path so the desktop holds the verifier
    while only the challenge crosses the wire (in the signed state) — the
    server binds the issued code to the challenge, and the exchange below
    proves possession with the verifier. Identical PKCE contract to the
    magic-link flow; only the front door (Google consent) differs.
    """
    verifier = base64.urlsafe_b64encode(
        secrets.token_bytes(32)).rstrip(b"=").decode("ascii")
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _exchange_with_retries(
    exchange_url: str, code: str, *, code_verifier: str = "",
    attempts: int = 5, delay_s: float = 3.0,
) -> Optional[str]:
    """Exchange a code for a token, retrying briefly.

    The magic-link → code flow has a small window; a freshly pasted code may be
    redeemed immediately, but we retry a few times (bounded, no long wait) to
    absorb a race where the user pastes just before the row is consumable.

    `code_verifier` defaults to "" — the magic-link / browser-direct path
    (the cloud issues those codes with an EMPTY challenge, so an empty
    verifier is exactly right, behaviour UNCHANGED). The Google sign-in
    path passes the PKCE verifier it generated so the server can match it
    against the challenge it bound the code to.
    """
    last_detail = ""
    for i in range(max(1, attempts)):
        status, body = _post_json(
            exchange_url, {"code": code, "code_verifier": code_verifier})
        if status == 200:
            token = (body.get("token") or body.get("access_token") or "").strip()
            if token:
                return token
            last_detail = "200 but no token in response"
        else:
            last_detail = f"{status}: {body.get('detail') or body}"
            # 400 invalid_or_expired won't fix itself by retrying many times,
            # but a brief retry covers the immediate race. Cap the wait.
        if i < attempts - 1:
            time.sleep(min(delay_s, 5.0))
    sys.stderr.write(f"[cloud_login] exchange failed: {last_detail}\n")
    return None


def _bind_local_owner(db_path: Optional[str], user_id: str,
                      email: str, display_name: str) -> bool:
    """Bind the local brain owner to the cloud user_id via brain_meta — the
    same keys `brain.set_owner` writes. Best-effort: a missing/locked db must
    not fail the sign-in (the token in cloud.json is the real gate; binding is
    an optimisation so local USER rows are owned by the cloud id)."""
    try:
        from .storage import BrainStore
        from datetime import datetime, timezone
        store = BrainStore.open(db_path)
        try:
            store.set_meta(_BOUND_OWNER_KEY, user_id)
            store.set_meta(_BOUND_EMAIL_KEY, email or "")
            store.set_meta(_BOUND_NAME_KEY, display_name or "")
            store.set_meta(_BOUND_SET_AT_KEY, datetime.now(timezone.utc).isoformat())
            return True
        finally:
            store.close()
    except Exception as ex:
        sys.stderr.write(
            f"[cloud_login] note: could not bind local owner ({type(ex).__name__}: {ex}); "
            "token still saved — sync will use cloud.json identity.\n"
        )
        return False


def _finish_login(args: argparse.Namespace, *, base_url: str, code: str,
                  code_verifier: str = "", fallback_email: str = "") -> int:
    """Shared tail for BOTH sign-in paths: exchange the code → /v1/me →
    persist token + identity → bind local owner → report.

    `code_verifier` is "" for the magic-link/browser-direct path (codes
    issued with an empty challenge) and the real PKCE verifier for the
    Google path. Everything downstream is identical — Google sign-in and
    magic-link sign-in converge here on the SAME token + cloud.json +
    owner-binding, keyed by the same email-resolved account.
    """
    exchange_url = f"{base_url}/v1/auth/exchange"
    me_url = f"{base_url}/v1/me"

    # Exchange the code for a bearer token (brief bounded retry).
    token = _exchange_with_retries(exchange_url, code,
                                   code_verifier=code_verifier)
    if not token:
        return 1

    # Confirm identity via /v1/me.
    user_id, who_email, plan, display_name = "", fallback_email, "", ""
    status, me = _get_json(me_url, headers={"Authorization": f"Bearer {token}"})
    if status == 200:
        user_id = str(me.get("user_id") or me.get("brain_id") or "").strip()
        who_email = str(me.get("email") or fallback_email).strip()
        plan = str(me.get("plan") or "").strip()
    else:
        sys.stderr.write(
            f"[cloud_login] warning: /v1/me returned {status}; saving token anyway "
            "(sync identifies the user by the token regardless).\n"
        )

    # Persist token + identity to cloud.json + bind local owner.
    cfg_path = save_cloud_config(
        base_url=base_url, token=token,
        user_id=user_id, email=who_email, display_name=display_name,
    )
    bound = _bind_local_owner(args.db, user_id or who_email, who_email, display_name)

    sys.stderr.write(
        "[cloud_login] signed in.\n"
        f"              user_id : {user_id or '(unknown — token still valid)'}\n"
        f"              email   : {who_email}\n"
        f"              plan    : {plan or '(n/a)'}\n"
        f"              config  : {cfg_path}\n"
        f"              owner-bound: {'yes' if bound else 'no (token-only)'}\n"
        "              Personal cross-device sync activates on the daemon's next "
        "tick (~within the sync interval); no restart needed.\n"
    )
    # Machine-readable line on stdout for scripting.
    print(json.dumps({
        "ok": True, "signed_in": True, "user_id": user_id,
        "email": who_email, "plan": plan, "config_path": str(cfg_path),
        "owner_bound": bound,
    }))
    return 0


def cmd_login_google(args: argparse.Namespace) -> int:
    """Sign in with Google. Mirrors the magic-link flow's automation, but
    the front door is Google consent instead of an emailed link.

      1. Generate a PKCE verifier/challenge (same logic as magic-link).
      2. GET /v1/auth/google/start?code_challenge=...&redirect=... →
         {auth_url}; open it with webbrowser.open. The user picks their
         Google account (the ONLY manual step — their sign-in).
      3. Google → our /v1/auth/google/callback → 302 to
         /auth/return?code=... (the SAME surface the magic-link uses).
      4. Accept the pasted /auth/return?code=... (reusing --code parsing
         + the bounded prompt) and exchange it WITH the PKCE verifier.

    No --email needed (Google supplies the identity). A 503 from /start
    means the founder hasn't configured Google OAuth yet — we say so and
    point at the magic-link path, which is unaffected.
    """
    base_url = (args.base_url or "").strip() or DEFAULT_CLOUD_BASE_URL
    base_url = base_url.rstrip("/")
    start_url = f"{base_url}/v1/auth/google/start"

    # 1. PKCE pair — desktop holds the verifier; only the challenge goes
    #    out (the server binds the issued code to it).
    verifier, challenge = _pkce_pair()

    # 2. Ask the backend for the Google consent URL. No loopback server
    #    here, so we leave `redirect` empty → the callback lands on the
    #    browser /auth/return finisher, from which the user copies the
    #    code (identical UX to pasting the magic-link's code).
    status, body = _get_json(
        start_url + "?" + urllib.parse.urlencode({"code_challenge": challenge}),
    )
    if status == 503:
        sys.stderr.write(
            "[cloud_login] Sign in with Google isn't enabled on this server "
            "yet.\n              Use the email magic-link instead:\n"
            f"                python -m personal_brain.cloud_login --email you@studio.com\n"
        )
        return 1
    if status != 200 or not body.get("auth_url"):
        sys.stderr.write(
            f"[cloud_login] could not start Google sign-in ({status}): "
            f"{body.get('detail') or body}\n"
        )
        return 1
    auth_url = str(body["auth_url"])

    # Open the consent screen in the default browser (best-effort — also
    # print it so a headless / no-browser environment can open manually).
    sys.stderr.write(
        "[cloud_login] opening Google sign-in in your browser …\n"
        f"              If it doesn't open, visit:\n              {auth_url}\n"
        "              (Choosing your Google account is the only manual step.)\n"
    )
    try:
        webbrowser.open(auth_url)
    except Exception:
        pass

    # 3/4. Obtain the returned code: pasted via --code, else prompt.
    code = _extract_code_from_input(args.code) if args.code else ""
    if not code:
        code = _prompt_for_code()
    if not code:
        sys.stderr.write(
            "[cloud_login] no code provided. After choosing your Google "
            "account, copy the\n              /auth/return?code=... URL and "
            "re-run:\n              python -m personal_brain.cloud_login login "
            "--google --code <CODE-OR-RETURN-URL>\n"
        )
        return 3

    # Exchange WITH the PKCE verifier — the server matches it against the
    # challenge it bound the Google-minted code to.
    return _finish_login(args, base_url=base_url, code=code,
                         code_verifier=verifier)


def cmd_login(args: argparse.Namespace) -> int:
    # Google sign-in path — opt-in via --google. Leaves the magic-link
    # path below completely unchanged.
    if getattr(args, "google", False):
        return cmd_login_google(args)

    base_url = (args.base_url or "").strip() or DEFAULT_CLOUD_BASE_URL
    base_url = base_url.rstrip("/")
    email = (args.email or "").strip()
    if not email:
        sys.stderr.write("[cloud_login] --email is required\n")
        return 2

    register_url = f"{base_url}/v1/auth/register"

    # 1. Register → trigger the magic-link email.
    sys.stderr.write(f"[cloud_login] requesting magic-link for {email} via {base_url} …\n")
    status, body = _post_json(register_url, {
        "email": email, "code_challenge": "", "redirect": "",
    })
    if status not in (200, 202):
        sys.stderr.write(
            f"[cloud_login] register failed ({status}): {body.get('detail') or body}\n"
        )
        return 1
    sys.stderr.write(
        "[cloud_login] magic-link sent. Open your inbox and click the link.\n"
        "              (That click is the only manual step — your sign-in.)\n"
    )

    # 2/3. Obtain the code: pasted via --code, else prompt (bounded).
    code = _extract_code_from_input(args.code) if args.code else ""
    if not code:
        code = _prompt_for_code()
    if not code:
        sys.stderr.write(
            "[cloud_login] no code provided. After clicking the link, re-run:\n"
            f"              python -m personal_brain.cloud_login --email {email} "
            "--code <CODE-OR-RETURN-URL>\n"
        )
        return 3

    # 4-6. Exchange (empty verifier — browser-direct), /v1/me, persist.
    return _finish_login(args, base_url=base_url, code=code,
                         code_verifier="", fallback_email=email)


def cmd_status(args: argparse.Namespace) -> int:
    cfg = load_cloud_config()
    info = cfg.redacted()
    # Live-verify the token against /v1/me when present (honest status).
    if cfg.is_signed_in:
        status, me = _get_json(cfg.me_url(), headers=cfg.auth_header())
        info["token_valid"] = (status == 200)
        if status == 200:
            info["live_user_id"] = me.get("user_id")
            info["live_plan"] = me.get("plan")
        else:
            info["me_status"] = status
    print(json.dumps({"ok": True, **info}, indent=2))
    return 0


def cmd_logout(args: argparse.Namespace) -> int:
    had = clear_cloud_token()
    # Also unbind the local owner so it reverts to env/OS/'founder'.
    try:
        from .storage import BrainStore
        store = BrainStore.open(args.db)
        try:
            for key in (_BOUND_OWNER_KEY, _BOUND_EMAIL_KEY,
                        _BOUND_NAME_KEY, _BOUND_SET_AT_KEY):
                store.set_meta(key, "")
        finally:
            store.close()
    except Exception:
        pass
    print(json.dumps({"ok": True, "cleared": had}))
    sys.stderr.write(
        "[cloud_login] signed out — local token cleared, owner unbound. "
        "Personal sync goes inert on the next tick.\n"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="personal_brain.cloud_login",
        description="Sign in to ArchHub cloud for personal cross-device brain sync.",
    )
    parser.add_argument(
        "command", nargs="?", default="login",
        choices=["login", "status", "logout"],
        help="login (default), status, or logout.",
    )
    parser.add_argument("--email", default="", help="Email to sign in with (login).")
    parser.add_argument(
        "--google", action="store_true",
        help="Sign in with Google (OAuth) instead of the email magic-link. "
             "Opens the Google consent screen; no --email needed.",
    )
    parser.add_argument(
        "--code", default="",
        help="Auth code OR the full /auth/return?code=... URL from the "
             "magic-link (or the Google sign-in return).",
    )
    parser.add_argument(
        "--base-url", default="",
        help=f"Cloud base URL. Default: {DEFAULT_CLOUD_BASE_URL} "
             "(or ARCHHUB_CLOUD_URL / cloud.json).",
    )
    parser.add_argument(
        "--db", default=None,
        help="brain.db path for owner-binding. Default: the standard brain path.",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "status":
        return cmd_status(args)
    if args.command == "logout":
        return cmd_logout(args)
    return cmd_login(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
