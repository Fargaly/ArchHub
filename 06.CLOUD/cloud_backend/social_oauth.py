"""Server-side social OAuth broker for ArchHub publisher apps.

The desktop Settings screen must never collect app ids, app secrets, tokens, or
redirect URLs. It opens these cloud-owned routes instead. Secrets stay in cloud
config; callbacks return only a short-lived account grant tied to the signed-in
cloud user.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import threading
import time
import urllib.parse
import urllib.error
import urllib.request
from typing import Callable

from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse

import account_sync
import config
import db


router = APIRouter()
_TTL = 600
_LOCK = threading.Lock()
_STATES: dict[str, dict] = {}
_GRANTS: dict[str, dict] = {}
_SCOPES = {
    "linkedin": "openid profile w_member_social",
    "meta": "pages_show_list pages_read_engagement pages_manage_posts pages_manage_engagement instagram_basic instagram_content_publish instagram_manage_comments"
            " pages_manage_metadata pages_messaging instagram_manage_messages",
}
_AUTHORIZE = {
    "linkedin": "https://www.linkedin.com/oauth/v2/authorization",
    "meta": "https://www.facebook.com/v25.0/dialog/oauth",
}
_TOKEN = {
    "linkedin": "https://www.linkedin.com/oauth/v2/accessToken",
    "meta": "https://graph.facebook.com/v25.0/oauth/access_token",
}
_PROFILE = {
    "linkedin": "https://api.linkedin.com/v2/userinfo",
    "meta": "https://graph.facebook.com/v25.0/me?fields=id,name",
}
_META_NETWORKS = frozenset({"meta", "instagram", "facebook"})
_PROVIDERS = frozenset({"linkedin", "meta", "instagram", "facebook", "whatsapp", "x", "tiktok"})
_SCOPES.update({
    "instagram": "pages_show_list pages_read_engagement instagram_basic instagram_content_publish instagram_manage_comments"
                 " pages_manage_metadata instagram_manage_messages",
    "facebook": "pages_show_list pages_read_engagement pages_manage_posts pages_manage_engagement pages_manage_metadata pages_messaging",
    "whatsapp": "business_management whatsapp_business_management whatsapp_business_messaging",
    "x": "tweet.read tweet.write users.read offline.access",
    "tiktok": "user.info.basic,video.publish",
})
for _network in ("instagram", "facebook", "whatsapp"):
    _AUTHORIZE[_network] = _AUTHORIZE["meta"]
    _TOKEN[_network] = _TOKEN["meta"]
    _PROFILE[_network] = _PROFILE["meta"]
_AUTHORIZE.update({"x": "https://x.com/i/oauth2/authorize", "tiktok": "https://www.tiktok.com/v2/auth/authorize/"})
_TOKEN.update({"x": "https://api.x.com/2/oauth2/token", "tiktok": "https://open.tiktokapis.com/v2/oauth/token/"})
_PROFILE.update({"x": "https://api.x.com/2/users/me", "tiktok": "https://open.tiktokapis.com/v2/user/info/?fields=open_id,display_name,avatar_url"})
_PUBLISH_PERMISSIONS = {
    "instagram": ("instagram_content_publish", "instagram_manage_comments"),
    "facebook": ("pages_manage_posts", "pages_manage_engagement"),
    "linkedin": ("w_member_social",),
    "whatsapp": ("whatsapp_business_management", "whatsapp_business_messaging"),
    "x": ("tweet.write",), "tiktok": ("video.publish",),
    "meta": ("pages_manage_posts", "instagram_content_publish"),
}
_META_PAGES = "https://graph.facebook.com/v25.0/me/accounts?fields=id,name,access_token,tasks&limit=25"
_GRAPH_ID = re.compile(r"[0-9]{1,32}(?:_[0-9]{1,32})?")


class SocialOAuthError(RuntimeError):
    pass


def _provider(provider: str) -> str:
    if provider not in _PROVIDERS:
        raise HTTPException(status_code=404, detail="unknown_social_provider")
    return provider


def _secret() -> bytes:
    key = (config.SOCIAL_OAUTH_STATE_SECRET or config.GOOGLE_OAUTH_CLIENT_SECRET
           or config.LINKEDIN_OAUTH_CLIENT_SECRET or config.META_OAUTH_APP_SECRET
           or _setting("X_OAUTH_CLIENT_SECRET") or _setting("TIKTOK_OAUTH_CLIENT_SECRET"))
    return str(key or "archhub-dev-social-oauth").encode("utf-8")


def _fernet() -> Fernet:
    key = base64.urlsafe_b64encode(
        hashlib.sha256(_secret() + b":social-oauth-token-grants").digest()
    )
    return Fernet(key)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    body = _b64(raw)
    mac = _b64(hmac.digest(_secret(), body.encode("ascii"), "sha256"))
    return body + "." + mac


def _unsign(state: str) -> dict:
    try:
        body, mac = state.split(".", 1)
        expected = _b64(hmac.digest(_secret(), body.encode("ascii"), "sha256"))
        if not hmac.compare_digest(mac, expected):
            raise SocialOAuthError("state_signature_mismatch")
        payload = json.loads(_unb64(body).decode("utf-8"))
    except Exception as exc:
        raise SocialOAuthError("invalid_state") from exc
    if not isinstance(payload, dict) or int(payload.get("exp") or 0) < int(time.time()):
        raise SocialOAuthError("expired_state")
    return payload


def _bearer(authorization: str | None) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing_or_invalid_authorization")
    user = db.user_for_token(authorization.split(None, 1)[1].strip())
    if not user:
        raise HTTPException(status_code=401, detail="missing_or_invalid_authorization")
    return user


def _bearer_token(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing_or_invalid_authorization")
    token = authorization.split(None, 1)[1].strip()
    if not db.user_for_token(token):
        raise HTTPException(status_code=401, detail="missing_or_invalid_authorization")
    return token


def _token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _clean_nonce(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{24,256}", value):
        raise SocialOAuthError("invalid_nonce")
    return value


def _clean_device(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{8,256}", value):
        raise SocialOAuthError("invalid_device")
    return value


def _loopback_return_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    if (parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost")
            or not parsed.port or parsed.path != "/oauth/return"):
        raise SocialOAuthError("return_url_not_allowed")
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def configured(provider: str) -> bool:
    client_id, secret, _redirect = _client_values(provider)
    return bool(client_id and secret)


def _setting(name: str, default: str = "") -> str:
    return str(getattr(config, name, os.environ.get(name, default)) or "")


def _client_values(provider: str) -> tuple[str, str, str]:
    if provider in _META_NETWORKS or provider == "whatsapp":
        prefix, identifier = "META", "APP_ID"
    else:
        prefix, identifier = provider.upper(), "CLIENT_KEY" if provider == "tiktok" else "CLIENT_ID"
    redirect = _setting(provider.upper() + "_OAUTH_REDIRECT", config.PUBLIC_URL.rstrip("/") + "/oauth/" + provider + "/callback")
    return (_setting(prefix + "_OAUTH_" + identifier),
            _setting(prefix + "_OAUTH_" + ("APP_SECRET" if prefix == "META" else "CLIENT_SECRET")), redirect)


def _blocker(provider: str) -> str:
    client_id, secret, _redirect = _client_values(provider)
    label = {"x": "X", "tiktok": "TikTok", "whatsapp": "Meta", "instagram": "Meta", "facebook": "Meta", "meta": "Meta", "linkedin": "LinkedIn"}[provider]
    if not client_id:
        return label + " developer app not created (cloud client id missing)"
    if not secret:
        return label + " cloud publisher app secret missing"
    if provider == "whatsapp" and not _setting("WHATSAPP_EMBEDDED_SIGNUP_CONFIG_ID"):
        return "Meta WhatsApp Embedded Signup configuration with coexistence not created"
    pending = _setting(provider.upper() + "_OAUTH_REVIEW_PENDING")
    return label + " app review: " + pending + " pending" if pending else ""


def _review_blocker(provider: str) -> str:
    if _setting(provider.upper() + "_OAUTH_REVIEW_APPROVED").lower() in ("1", "true", "yes"):
        return ""
    label = {"x": "X", "tiktok": "TikTok", "whatsapp": "Meta", "instagram": "Meta", "facebook": "Meta", "meta": "Meta", "linkedin": "LinkedIn"}[provider]
    return label + (" developer app access: " if provider == "x" else " app review: ") + ", ".join(_PUBLISH_PERMISSIONS[provider]) + " approval not verified"


def _permission_failure(provider: str, text: str = "") -> str:
    named = [permission for permission in _SCOPES[provider].replace(",", " ").split() if permission in text]
    permissions = named or list(_PUBLISH_PERMISSIONS[provider])
    # Only our known permission names cross to the desktop, never raw provider
    # descriptions or an exception containing a request URL/credential.
    return provider + " authorization failed; required permission: " + ", ".join(permissions)


def _client(provider: str) -> tuple[str, str, str]:
    client = _client_values(provider)
    if provider in ("linkedin", "meta"):
        allowed = config.social_oauth_redirect_allowed(provider, client[2])
    else:
        defaults = config.PUBLIC_URL.rstrip("/") + "/oauth/" + provider + "/callback"
        allowed_uris = _setting(provider.upper() + "_OAUTH_REDIRECT_ALLOWLIST", _setting("SOCIAL_OAUTH_REDIRECT_ALLOWLIST", defaults))
        allowed = client[2].rstrip("/") in {uri.strip().rstrip("/") for uri in allowed_uris.split(",")}
        parsed = urllib.parse.urlsplit(client[2])
        allowed = allowed and parsed.scheme == "https" and not parsed.username and not parsed.fragment
    if not allowed:
        raise SocialOAuthError("redirect_not_allowed")
    return client


def _pkce(payload: dict) -> str:
    # A per-attempt secret, recoverable after a cloud restart without exposing it
    # in the browser or adding another state/token store.
    identity = json.dumps({key: payload[key] for key in ("n", "uid", "p", "d")}, sort_keys=True).encode()
    return _b64(hmac.digest(_secret(), b"social-pkce:" + identity, "sha256"))


def _post_form(url: str, form: dict, *, timeout: float = 20.0) -> dict:
    data = urllib.parse.urlencode(form).encode("ascii")
    request = urllib.request.Request(url, data=data, method="POST",
                                     headers={"Accept": "application/json",
                                              "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read(65536).decode("utf-8"))


def _get_json(url: str, token: str, *, timeout: float = 20.0) -> dict:
    request = urllib.request.Request(url, headers={"Accept": "application/json",
                                                   "Authorization": "Bearer " + token})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read(65536).decode("utf-8"))


def _post_bearer(url: str, token: str, body: dict | None = None, *, timeout: float = 20.0) -> dict:
    request = urllib.request.Request(url, data=json.dumps(body).encode("utf-8") if body else b"", method="POST",
                                     headers={"Accept": "application/json", "Content-Type": "application/json",
                                              "Authorization": "Bearer " + token})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read(65536).decode("utf-8") or "{}")


_exchange: Callable[[str, str, str, str], dict] | None = None
_profile: Callable[[str, str], dict] | None = None
_pages: Callable[[str], dict] | None = None
_instagram: Callable[[str, str], dict] | None = None
_whatsapp: Callable[[str], dict] | None = None


def _whatsapp_profile(token: str) -> dict:
    client_id, secret, _redirect = _client("whatsapp")
    debug = _get_json("https://graph.facebook.com/v25.0/debug_token?" + urllib.parse.urlencode({"input_token": token}), client_id + "|" + secret)
    discovered, waba = {}, {}
    accounts = [str(target) for scope in debug.get("data", {}).get("granular_scopes", [])
                if scope.get("scope") == "whatsapp_business_management" for target in scope.get("target_ids", [])]
    if not accounts:
        # A returning Meta sign-in ("has been connected to ArchHub") can skip the number step and grant
        # without target ids: the WhatsApp Business accounts are then read through the user's businesses.
        for business in _get_json("https://graph.facebook.com/v25.0/me/businesses?fields=id", token).get("data", []):
            if isinstance(business, dict) and _GRAPH_ID.fullmatch(str(business.get("id", ""))):
                for edge in ("owned_whatsapp_business_accounts", "client_whatsapp_business_accounts"):
                    accounts += [str(row.get("id")) for row in _get_json(
                        "https://graph.facebook.com/v25.0/" + str(business["id"]) + "/" + edge + "?fields=id", token).get("data", [])
                        if isinstance(row, dict)]
    for business_id in dict.fromkeys(accounts):
        if not _GRAPH_ID.fullmatch(str(business_id)):
            continue
        phones = _get_json("https://graph.facebook.com/v25.0/" + str(business_id) + "/phone_numbers?fields=id,display_phone_number,verified_name", token).get("data", [])
        for phone in phones:
            if isinstance(phone, dict) and _GRAPH_ID.fullmatch(str(phone.get("id", ""))):
                discovered[str(phone["id"])] = phone
                waba[str(phone["id"])] = str(business_id)
    if len(discovered) == 1:
        phone_id, phone = next(iter(discovered.items()))
        # Webhooks (messages, coexistence echoes/history) reach the cloud only
        # once the app is subscribed to the customer's WhatsApp Business Account.
        _post_bearer("https://graph.facebook.com/v25.0/" + waba[phone_id] + "/subscribed_apps", token)
        return {"id": phone_id, "name": phone.get("display_phone_number") or phone.get("verified_name", "")}
    if discovered:
        raise SocialOAuthError("whatsapp_multiple_phone_numbers_select_in_embedded_signup")
    raise SocialOAuthError("whatsapp_business_messaging_phone_number_missing")


def _meta_pages(token: str) -> tuple[list[dict], dict[str, dict]]:
    read_pages = _pages or (lambda t: _get_json(_META_PAGES, t))
    body = read_pages(token)
    rows = body.get("data")
    if not isinstance(rows, list):
        raise SocialOAuthError("meta_pages_missing")
    public_pages: list[dict] = []
    secrets_by_page: dict[str, dict] = {}
    for row in rows[:25]:
        if not isinstance(row, dict):
            continue
        page_id, page_token = row.get("id"), row.get("access_token")
        if (not isinstance(page_id, str) or not _GRAPH_ID.fullmatch(page_id)
                or not isinstance(page_token, str) or not page_token
                or any(ord(char) < 33 or ord(char) > 126 for char in page_token)):
            continue
        page = {"id": page_id, "name": str(row.get("name") or page_id)[:120]}
        secret = {"page_token": page_token}
        try:
            read_instagram = _instagram or (
                lambda pid, pt: _get_json(
                    "https://graph.facebook.com/v25.0/%s?%s" % (
                        pid, urllib.parse.urlencode({"fields": "instagram_business_account{id,username}"})),
                    pt))
            account = read_instagram(page_id, page_token).get("instagram_business_account")
            ig_id = account.get("id") if isinstance(account, dict) else None
            if isinstance(ig_id, str) and _GRAPH_ID.fullmatch(ig_id):
                instagram = {"id": ig_id, "username": str(account.get("username") or "")[:120]}
                page["instagram"] = instagram
                secret["instagram"] = instagram
                secret["instagram_token"] = page_token
        except Exception:
            pass
        public_pages.append(page)
        secrets_by_page[page_id] = secret
    if not public_pages:
        raise SocialOAuthError("meta_pages_missing")
    return public_pages, secrets_by_page


def exchange_and_profile(provider: str, code: str, *, verifier: str = "") -> dict:
    client_id, client_secret, redirect = _client(provider)
    def real_exchange(p, c, cid, secret):
        form = {"grant_type": "authorization_code", "code": c, "redirect_uri": redirect,
                "client_key" if p == "tiktok" else "client_id": cid, "client_secret": secret}
        if p == "whatsapp":
            # Embedded Signup's JS SDK returns a business integration code;
            # Meta's code exchange takes app id, app secret and code only.
            form.pop("redirect_uri")
        if p == "x":
            if not verifier:
                raise SocialOAuthError("pkce_verifier_missing")
            # X confidential clients authenticate with HTTP Basic, not a secret
            # in the form body.
            form.pop("client_secret")
            form["code_verifier"] = verifier
            request = urllib.request.Request(_TOKEN[p], data=urllib.parse.urlencode(form).encode("ascii"), headers={
                "Authorization": "Basic " + base64.b64encode((cid + ":" + secret).encode()).decode(),
                "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
            with urllib.request.urlopen(request, timeout=20) as response:
                return json.loads(response.read(65536))
        return _post_form(_TOKEN[p], form)
    exchange = _exchange or real_exchange
    payload = exchange(provider, code, client_id, client_secret)
    token = payload.get("access_token")
    if not isinstance(token, str) or not token:
        raise SocialOAuthError(_permission_failure(provider, json.dumps(payload)))
    if isinstance(payload.get("scope"), str):
        granted = set(payload["scope"].replace(",", " ").split())
        missing = set(_PUBLISH_PERMISSIONS[provider]) - granted
        if missing:
            raise SocialOAuthError(provider + " permission not granted: " + ", ".join(sorted(missing)))
    read_profile = _profile or (lambda p, t: (_whatsapp or _whatsapp_profile)(t) if p == "whatsapp" else _get_json(_PROFILE[p], t))
    who = read_profile(provider, token)
    if provider == "x":
        who = who.get("data", who)
    if provider == "tiktok":
        who = who.get("data", {}).get("user", who)
    raw_id = who.get("sub") if provider == "linkedin" else who.get("open_id") if provider == "tiktok" else who.get("id")
    if not isinstance(raw_id, str) or not raw_id:
        raise SocialOAuthError("provider_account_missing")
    account_id = "urn:li:person:" + raw_id if provider == "linkedin" else raw_id
    result = {"provider": provider, "account_id": account_id,
              "name": str(who.get("username") or who.get("display_name") or who.get("name") or "")[:120],
              "access_token": token}
    # Kept encrypted on the cloud (account_sync) for server-side refresh; never sent to the desktop.
    result.update({key: payload[key] for key in ("refresh_token", "expires_in") if payload.get(key)})
    if provider in _META_NETWORKS:
        public_pages, page_secrets = _meta_pages(token)
        result.update({"pages": public_pages, "page_secrets": page_secrets})
    return result


@router.get("/oauth/{provider}/status")
def status(provider: str, authorization: str | None = Header(None)) -> dict:
    provider = _provider(provider)
    _bearer(authorization)
    blocker = _blocker(provider)
    pending = bool(_setting(provider.upper() + "_OAUTH_REVIEW_PENDING")) and configured(provider)
    review = blocker if pending else _review_blocker(provider) if configured(provider) else ""
    return {"ok": True, "provider": provider,
            "state": "blocked" if configured(provider) and blocker else "configured" if configured(provider) else "missing",
            **({"blocker": blocker} if blocker else {}),
            **({"publish_blocker": review, "review_state": "pending" if pending else "unverified"} if review else {}),
            **(_whatsapp_receive_status() if provider == "whatsapp" else {})}


@router.get("/oauth/{provider}/start")
def start(provider: str, authorization: str | None = Header(None),
          x_archhub_device_session: str = Header(""),
          return_url: str = Query(""),
          nonce: str = Query("")) -> dict:
    provider = _provider(provider)
    user = _bearer(authorization)
    blocker = _blocker(provider)
    if blocker:
        raise HTTPException(status_code=503, detail={"error": "social_oauth_unconfigured", "blocker": blocker})
    try:
        nonce = _clean_nonce(nonce)
        device = _clean_device(x_archhub_device_session)
        desktop_return = _loopback_return_url(return_url)
        client_id, _client_secret, redirect = _client(provider)
    except SocialOAuthError as exc:
        raise HTTPException(status_code=400, detail={"error": str(exc)})
    bearer_token = authorization.split(None, 1)[1].strip()
    record = db.issue_social_oauth_state(
        nonce=nonce,
        user_id=user["id"],
        device_id=device,
        session_digest=_token_digest(bearer_token),
        provider=provider,
        return_url=desktop_return,
        ttl_seconds=_TTL,
    )
    state_payload = {"n": nonce, "uid": user["id"], "p": provider,
                     "d": device, "exp": record["expires_at"]}
    state = _sign(state_payload)
    params = {"response_type": "code", "client_key" if provider == "tiktok" else "client_id": client_id,
              "redirect_uri": redirect, "state": state, "scope": _SCOPES[provider]}
    if provider == "x":
        params.update(code_challenge=_b64(hashlib.sha256(_pkce(state_payload).encode()).digest()), code_challenge_method="S256")
    if provider == "whatsapp":
        params.update(config_id=_setting("WHATSAPP_EMBEDDED_SIGNUP_CONFIG_ID"),
                      extras=json.dumps({"setup": {}, "featureType": "whatsapp_business_app_onboarding", "sessionInfoVersion": "3"}, separators=(",", ":")))
    url = _AUTHORIZE[provider] + "?" + urllib.parse.urlencode(params)
    answer = {"ok": True, "provider": provider, "auth_url": url}
    if provider == "whatsapp":
        answer["browser_url"] = config.PUBLIC_URL.rstrip("/") + "/oauth/whatsapp/embedded?" + urllib.parse.urlencode({"state": state})
    return answer


@router.get("/oauth/whatsapp/embedded", response_class=HTMLResponse)
def whatsapp_embedded(state: str = "") -> HTMLResponse:
    """Cloud-owned SDK kickoff. Only public app config and signed state render."""
    try:
        payload = _unsign(state)
        if payload.get("p") != "whatsapp":
            raise SocialOAuthError("state_mismatch")
        if _blocker("whatsapp"):
            raise SocialOAuthError("whatsapp_embedded_signup_not_configured")
        app_id, _secret_value, redirect = _client("whatsapp")
    except SocialOAuthError as exc:
        raise HTTPException(status_code=400, detail={"error": str(exc)})
    settings = json.dumps({"appId": app_id, "configId": _setting("WHATSAPP_EMBEDDED_SIGNUP_CONFIG_ID"),
                           "callback": redirect, "state": state}, separators=(",", ":")).replace("<", "\\u003c")
    document = """<!doctype html><meta charset="utf-8"><title>Connect WhatsApp Business · ArchHub</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>body{font:16px system-ui;background:#102021;color:#fff;display:grid;place-content:center;min-height:90vh;padding:24px}button{font:inherit;background:#25d366;color:#102021;border:0;border-radius:12px;padding:14px 22px;cursor:pointer}p{max-width:42ch;line-height:1.5}</style>
<h1>Connect WhatsApp Business</h1><p id="status">Opening Meta’s secure sign-in. Your existing WhatsApp Business app stays available.</p>
<button id="continue" type="button" disabled>Continue with Meta</button>
<script>
const settings = SETTINGS;
const button = document.getElementById('continue');
function finish(code, error) {
  const target = new URL(settings.callback);
  target.searchParams.set('state', settings.state);
  if (code) target.searchParams.set('code', code);
  else target.searchParams.set('error', error || 'access_denied');
  window.location.assign(target.href);
}
function connect() {
  if (!window.FB) return;
  document.getElementById('status').textContent = 'Continue in Meta’s secure sign-in. If no window opens, use Continue with Meta.';
  FB.login(function(response) {
    const code = response && response.authResponse && response.authResponse.code;
    if (code) finish(code);
    else if (response && response.status === 'not_authorized') finish('', 'access_denied');
  }, {config_id: settings.configId, response_type: 'code', override_default_response_type: true,
      extras: {setup: {}, featureType: 'whatsapp_business_app_onboarding', sessionInfoVersion: '3'}});
}
button.addEventListener('click', connect);
window.fbAsyncInit = function() {
  FB.init({appId: settings.appId, autoLogAppEvents: false, xfbml: false, version: 'v25.0'});
  button.disabled = false;
  connect();
};
</script><script async defer crossorigin="anonymous" src="https://connect.facebook.net/en_US/sdk.js"></script>""".replace("SETTINGS", settings)
    return HTMLResponse(document, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})


@router.get("/oauth/{provider}/callback")
def callback(provider: str, code: str = "", state: str = "", error: str = "", error_description: str = "") -> RedirectResponse:
    provider = _provider(provider)
    stored = None
    try:
        payload = _unsign(state)
        nonce = payload.get("n")
        uid = payload.get("uid")
        device = payload.get("d")
        if payload.get("p") != provider or not isinstance(nonce, str) or not isinstance(uid, str) or not isinstance(device, str):
            raise SocialOAuthError("state_mismatch")
        stored = db.consume_social_oauth_state(
            nonce=nonce, user_id=uid, device_id=device, provider=provider
        )
        if not stored:
            raise SocialOAuthError("state_invalid")
        if error:
            raise SocialOAuthError(_permission_failure(provider, error_description))
        grant = exchange_and_profile(provider, code, verifier=_pkce(payload) if provider == "x" else "")
        access_token = grant.pop("access_token")
        encrypted_payload = _fernet().encrypt(
            json.dumps({**grant, "access_token": access_token},
                       separators=(",", ":"), sort_keys=True).encode("utf-8")
        ).decode("ascii")
        handle = secrets.token_urlsafe(24)
        issued = db.issue_social_oauth_grant(
            handle=handle,
            user_id=stored["user_id"],
            device_id=stored["device_id"],
            session_digest=stored["session_digest"],
            provider=provider,
            account_id=grant["account_id"],
            name=str(grant.get("name") or ""),
            encrypted_payload=encrypted_payload,
            ttl_seconds=300,
        )
    except (SocialOAuthError, urllib.error.URLError, ValueError, KeyError, TypeError) as exc:
        if stored:
            failure = str(exc) if isinstance(exc, SocialOAuthError) else _permission_failure(provider)
            _LOG.warning("%s sign-in finished without a grant: %s", provider, failure)
            return RedirectResponse(url=stored["return_url"] + "?" + urllib.parse.urlencode({
                "provider": provider, "nonce": nonce, "error": failure}), status_code=302)
        raise HTTPException(status_code=400, detail={"error": str(exc)})
    token = _sign({"kind": "social-grant", "g": handle, "uid": stored["user_id"],
                   "provider": provider, "account_id": grant["account_id"],
                   "exp": issued["expires_at"]})
    return RedirectResponse(
        url=stored["return_url"] + "?" + urllib.parse.urlencode({
            "provider": provider, "grant": token, "account_id": grant["account_id"]}),
        status_code=302)


@router.post("/oauth/{provider}/consume")
def consume(provider: str, body: dict, authorization: str | None = Header(None),
            x_archhub_device_session: str = Header("")) -> dict:
    provider = _provider(provider)
    token = _bearer_token(authorization)
    try:
        device = _clean_device(x_archhub_device_session)
        payload = _unsign(str(body.get("grant") if isinstance(body, dict) else ""))
        handle = payload.get("g")
        if payload.get("kind") != "social-grant" or payload.get("provider") != provider:
            raise SocialOAuthError("grant_invalid")
        if not isinstance(handle, str):
            raise SocialOAuthError("grant_invalid")
        record = db.consume_social_oauth_grant(
            handle=handle,
            user_id=str(payload.get("uid") or ""),
            device_id=device,
            session_digest=_token_digest(token),
            provider=provider,
        )
        if not record:
            raise SocialOAuthError("grant_invalid")
        try:
            grant_payload = json.loads(
                _fernet().decrypt(record["encrypted_payload"].encode("ascii")).decode("utf-8")
            )
        except (InvalidToken, ValueError, TypeError, KeyError) as exc:
            raise SocialOAuthError("grant_invalid") from exc
    except SocialOAuthError as exc:
        raise HTTPException(status_code=400, detail={"error": str(exc)})
    if provider == "whatsapp":
        db.link_whatsapp_number(phone_number_id=record["account_id"], user_id=record["user_id"])
        _request_history_sync(record["account_id"], grant_payload["access_token"])
    account_sync.keep_connection(record["user_id"], provider, record["account_id"], record.get("name", ""), grant_payload)
    answer = {"ok": True, "provider": provider, "account_id": record["account_id"],
              "name": record.get("name", ""), "access_token": grant_payload["access_token"]}
    if provider in _META_NETWORKS:
        answer["pages"] = grant_payload.get("pages", [])
        answer["page_secrets"] = grant_payload.get("page_secrets", {})
        blocker = _link_meta_inbox(provider, record["user_id"], answer["page_secrets"])
        if blocker:
            answer["receive_blocker"] = blocker
    return answer


def _link_meta_inbox(provider: str, user_id: str, page_secrets: object) -> str:
    """Route this grant's Page Messenger and Instagram DMs to the account that consumed it.

    Links each granted Page id (messenger) and Instagram account id (instagram),
    subscribes each Page to the app so Meta sends its message webhooks, and makes
    sure the app-level page/instagram webhooks point here. Best effort: the
    connection stands when Meta refuses; the reason comes back as one line.
    """
    errors = []
    for page_id, secret in (page_secrets.items() if isinstance(page_secrets, dict) else []):
        if not _GRAPH_ID.fullmatch(str(page_id)) or not isinstance(secret, dict):
            continue
        if provider in ("meta", "facebook"):
            db.link_whatsapp_number(phone_number_id=page_id, user_id=user_id, network="messenger")
        instagram = secret.get("instagram") if isinstance(secret.get("instagram"), dict) else {}
        ig_id = instagram.get("id")
        if provider in ("meta", "instagram") and isinstance(ig_id, str) and _GRAPH_ID.fullmatch(ig_id):
            db.link_whatsapp_number(phone_number_id=ig_id, user_id=user_id, network="instagram")
        try:
            # The page token rides in the POST body, never in the URL.
            _post_form("https://graph.facebook.com/v25.0/" + page_id + "/subscribed_apps",
                       {"subscribed_fields": "messages,message_echoes", "access_token": str(secret.get("page_token") or "")})
        except (urllib.error.URLError, OSError, ValueError) as exc:
            _LOG.warning("meta page subscription failed: %s", _graph_error(exc))
            errors.append("Page not subscribed to ArchHub: " + _graph_error(exc))
    return ensure_messaging_webhook() or (errors[0] if errors else "")


# ------------------------------------------------ WhatsApp inbound (webhook) --

_WEBHOOK_FIELDS = frozenset({"messages", "smb_message_echoes", "history"})
_WEBHOOK_MAX_BYTES = 4 * 1024 * 1024


def _app_secret() -> str:
    return _client_values("whatsapp")[1]


def whatsapp_verify_token() -> str:
    """Meta's webhook verify token, derived from the app secret: no extra secret to hold."""
    return hmac.new(_app_secret().encode("utf-8"), b"archhub-whatsapp-webhook-verify",
                    "sha256").hexdigest()


_WEBHOOK_STATE = {"ok": False, "error": ""}
_LOG = logging.getLogger(__name__)


def _graph_error(exc: Exception) -> str:
    """A loggable failure: the HTTP status or error class only, never a URL, token or body text."""
    if isinstance(exc, urllib.error.HTTPError):
        return "Meta answered HTTP %d" % exc.code
    return "Meta could not be reached (" + type(exc).__name__ + ")"


# Meta object -> (callback path, fields). Page Messenger and Instagram DMs share /webhooks/meta.
_WEBHOOK_OBJECTS = {
    "whatsapp_business_account": ("/webhooks/whatsapp", ",".join(sorted(_WEBHOOK_FIELDS))),
    "page": ("/webhooks/meta", "message_echoes,messages"),
    "instagram": ("/webhooks/meta", "messages"),
}
_MESSAGING_STATE = {"ok": False, "error": ""}


def _ensure_webhook(state: dict, objects: tuple, label: str) -> str:
    """Register this cloud as the app's webhook for `objects`; '' when registered, else the reason.

    Idempotent (Meta overwrites the same object subscription); a success is
    remembered for the process, a failure is retried on the next call.
    """
    app_id, secret, _redirect = _client_values("whatsapp")
    if not app_id or not secret:
        return "Meta app id or app secret missing on the cloud"
    with _LOCK:
        if state["ok"]:
            return ""
    error = ""
    for name in objects:
        path, fields = _WEBHOOK_OBJECTS[name]
        try:
            # The app access token rides in the POST body, never in the URL.
            answer = _post_form("https://graph.facebook.com/v25.0/" + urllib.parse.quote(app_id, safe="") + "/subscriptions", {
                "object": name,
                "callback_url": config.PUBLIC_URL.rstrip("/") + path,
                "verify_token": whatsapp_verify_token(),
                "fields": fields,
                "include_values": "true",
                "access_token": app_id + "|" + secret})
            error = "" if answer.get("success") is True else "Meta did not confirm the webhook subscription"
        except (urllib.error.URLError, OSError, ValueError) as exc:
            error = _graph_error(exc)
        if error:
            break
    with _LOCK:
        state.update(ok=not error, error=(label + " webhook not registered: " + error) if error else "")
    if error:
        _LOG.warning("%s webhook registration failed: %s", label, error)
    return state["error"]


def ensure_whatsapp_webhook() -> str:
    return _ensure_webhook(_WEBHOOK_STATE, ("whatsapp_business_account",), "WhatsApp")


def ensure_messaging_webhook() -> str:
    return _ensure_webhook(_MESSAGING_STATE, ("page", "instagram"), "Messenger and Instagram")


def _whatsapp_receive_status() -> dict:
    url = config.PUBLIC_URL.rstrip("/") + "/webhooks/whatsapp"
    blocker = ensure_whatsapp_webhook()
    return {"webhook_url": url, **({"receive_blocker": blocker} if blocker else {})}


def _request_history_sync(phone_number_id: str, token: str) -> None:
    """Coexistence onboarding: ask Meta to send the WhatsApp Business app's contacts
    and chat history (the user approves sharing on the phone). Best effort: the
    connection stands even when Meta refuses or the 24-hour window has passed."""
    url = "https://graph.facebook.com/v25.0/" + phone_number_id + "/smb_app_data"
    for sync_type in ("smb_app_state_sync", "history"):
        try:
            _post_bearer(url, token, {"messaging_product": "whatsapp", "sync_type": sync_type})
        except (urllib.error.URLError, OSError, ValueError) as exc:
            _LOG.warning("whatsapp %s request failed: %s", sync_type, _graph_error(exc))


def _digits(value: object) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())[:32]


def _message_text(message: dict) -> tuple[str, str]:
    kind = str(message.get("type") or "unknown")[:32]
    body = message.get(kind) if isinstance(message.get(kind), dict) else {}
    text = body.get("body") or body.get("caption") or body.get("text") or body.get("title") or ""
    return kind, (str(text) if text else "[" + kind + "]")[:4096]


def whatsapp_rows(payload: object) -> list[dict]:
    """Flatten one Meta webhook body into message rows (owner not yet resolved)."""
    rows: list[dict] = []
    if not isinstance(payload, dict) or payload.get("object") != "whatsapp_business_account":
        return rows
    for entry in payload.get("entry") or []:
        for change in (entry.get("changes") or []) if isinstance(entry, dict) else []:
            if not isinstance(change, dict) or change.get("field") not in _WEBHOOK_FIELDS:
                continue
            value = change.get("value") if isinstance(change.get("value"), dict) else {}
            meta = value.get("metadata") if isinstance(value.get("metadata"), dict) else {}
            number_id, own = str(meta.get("phone_number_id") or ""), _digits(meta.get("display_phone_number"))
            if not _GRAPH_ID.fullmatch(number_id):
                continue
            names = {_digits(c.get("wa_id")): str((c.get("profile") or {}).get("name") or "")[:120]
                     for c in value.get("contacts") or [] if isinstance(c, dict)}
            batch = [(m, None) for m in value.get("messages") or []]
            batch += [(m, "out") for m in value.get("message_echoes") or []]
            for item in value.get("history") or []:
                for thread in (item.get("threads") or []) if isinstance(item, dict) else []:
                    if isinstance(thread, dict):
                        batch += [(m, None) for m in thread.get("messages") or []]
            for message, direction in batch:
                if not isinstance(message, dict) or not message.get("id"):
                    continue
                sender = _digits(message.get("from"))
                direction = direction or ("out" if own and sender == own else "in")
                contact = _digits(message.get("to")) if direction == "out" else sender
                kind, text = _message_text(message)
                try:
                    sent_at = int(message.get("timestamp") or 0)
                except (TypeError, ValueError):
                    sent_at = 0
                rows.append({"phone_number_id": number_id, "wamid": str(message["id"])[:256],
                             "direction": direction, "contact": contact,
                             "contact_name": names.get(contact, ""), "kind": kind,
                             "text": text, "sent_at": sent_at})
    return rows


def messaging_rows(payload: object) -> list[dict]:
    """Flatten one Page Messenger (object=page) or Instagram (object=instagram) webhook body.

    Each row's phone_number_id is the receiving Page or Instagram account id; the
    contact is the other party's Meta-scoped id (Meta sends no name here).
    """
    rows: list[dict] = []
    network = {"page": "messenger", "instagram": "instagram"}.get(
        payload.get("object") if isinstance(payload, dict) else None)
    if not network:
        return rows
    for entry in payload.get("entry") or []:
        account = str(entry.get("id") or "") if isinstance(entry, dict) else ""
        if not _GRAPH_ID.fullmatch(account):
            continue
        for event in entry.get("messaging") or []:
            message = event.get("message") if isinstance(event, dict) else None
            if not isinstance(message, dict) or not message.get("mid"):
                continue  # reads, deliveries, reactions: not messages
            echo = bool(message.get("is_echo"))
            party = event.get("recipient" if echo else "sender")
            contact = str(party.get("id") or "")[:64] if isinstance(party, dict) else ""
            attachments = [a for a in message.get("attachments") or [] if isinstance(a, dict)]
            kind = "text" if message.get("text") else str(attachments[0].get("type") or "unknown")[:32] if attachments else "unknown"
            text = message.get("text")
            try:
                sent_at = int(event.get("timestamp") or 0) // 1000  # Meta sends milliseconds here
            except (TypeError, ValueError):
                sent_at = 0
            rows.append({"phone_number_id": account, "wamid": str(message["mid"])[:256],
                         "direction": "out" if echo else "in", "contact": contact, "contact_name": "",
                         "kind": kind, "text": (str(text) if text else "[" + kind + "]")[:4096],
                         "sent_at": sent_at, "network": network})
    return rows


@router.get("/webhooks/meta", response_class=PlainTextResponse)
@router.get("/webhooks/whatsapp", response_class=PlainTextResponse)
def whatsapp_webhook_verify(mode: str = Query("", alias="hub.mode"),
                            token: str = Query("", alias="hub.verify_token"),
                            challenge: str = Query("", alias="hub.challenge")) -> PlainTextResponse:
    if not _app_secret():
        raise HTTPException(status_code=503, detail="whatsapp_webhook_unconfigured")
    if mode != "subscribe" or not hmac.compare_digest(token, whatsapp_verify_token()):
        raise HTTPException(status_code=403, detail="whatsapp_webhook_verify_refused")
    return PlainTextResponse(challenge[:256])


@router.post("/webhooks/meta")
@router.post("/webhooks/whatsapp")
async def whatsapp_webhook(request: Request) -> dict:
    secret = _app_secret()
    if not secret:
        raise HTTPException(status_code=503, detail="whatsapp_webhook_unconfigured")
    raw = await request.body()
    if len(raw) > _WEBHOOK_MAX_BYTES:
        raise HTTPException(status_code=413, detail="whatsapp_webhook_too_large")
    expected = "sha256=" + hmac.new(secret.encode("utf-8"), raw, "sha256").hexdigest()
    if not hmac.compare_digest(request.headers.get("x-hub-signature-256", ""), expected):
        raise HTTPException(status_code=403, detail="whatsapp_webhook_signature_invalid")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except ValueError:
        raise HTTPException(status_code=400, detail="whatsapp_webhook_invalid_json")
    owners: dict[str, str | None] = {}
    rows = []
    for row in whatsapp_rows(payload) + messaging_rows(payload):
        number = row["phone_number_id"]
        if number not in owners:
            owners[number] = db.whatsapp_number_owner(number)
        if owners[number]:  # a number no ArchHub account connected is dropped
            rows.append({**row, "user_id": owners[number]})
    # Counts only: message text and phone numbers never reach the log.
    return {"ok": True, "stored": db.store_whatsapp_messages(rows) if rows else 0}


@router.post("/oauth/whatsapp/messages")
def whatsapp_messages(body: dict, authorization: str | None = Header(None)) -> dict:
    """The signed-in account's messages. The filter rides in the body: the access log records URLs."""
    user = _bearer(authorization)
    contact, since, limit = body.get("contact", ""), body.get("since", 0), body.get("limit", 50)
    # No network keeps the WhatsApp-only answer older desktops expect; "all" reads every network.
    network = body.get("network", "whatsapp")
    if (not isinstance(contact, str) or len(contact) > 120 or type(since) is not int or since < 0
            or type(limit) is not int or not 1 <= limit <= 200
            or network not in db.META_NETWORKS + ("all",)):
        raise HTTPException(status_code=400, detail="whatsapp_messages_invalid_filter")
    rows = db.list_whatsapp_messages(user_id=user["id"], contact=contact, since=since, limit=limit,
                                     network="" if network == "all" else network)
    return {"ok": True, "messages": rows, "next": rows[-1]["id"] if rows else since}
