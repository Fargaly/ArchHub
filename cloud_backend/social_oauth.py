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
from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse

import config
import db


router = APIRouter()
_TTL = 600
_LOCK = threading.Lock()
_STATES: dict[str, dict] = {}
_GRANTS: dict[str, dict] = {}
_SCOPES = {
    "linkedin": "openid profile w_member_social",
    "meta": "pages_show_list pages_read_engagement pages_manage_posts pages_manage_engagement instagram_basic instagram_content_publish instagram_manage_comments",
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
    "instagram": "pages_show_list pages_read_engagement instagram_basic instagram_content_publish instagram_manage_comments",
    "facebook": "pages_show_list pages_read_engagement pages_manage_posts pages_manage_engagement",
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


_exchange: Callable[[str, str, str, str], dict] | None = None
_profile: Callable[[str, str], dict] | None = None
_pages: Callable[[str], dict] | None = None
_instagram: Callable[[str, str], dict] | None = None
_whatsapp: Callable[[str], dict] | None = None


def _whatsapp_profile(token: str) -> dict:
    client_id, secret, _redirect = _client("whatsapp")
    debug = _get_json("https://graph.facebook.com/v25.0/debug_token?" + urllib.parse.urlencode({"input_token": token}), client_id + "|" + secret)
    discovered = {}
    for scope in debug.get("data", {}).get("granular_scopes", []):
        if scope.get("scope") != "whatsapp_business_management":
            continue
        for business_id in scope.get("target_ids", []):
            if not _GRAPH_ID.fullmatch(str(business_id)):
                continue
            phones = _get_json("https://graph.facebook.com/v25.0/" + str(business_id) + "/phone_numbers?fields=id,display_phone_number,verified_name", token).get("data", [])
            for phone in phones:
                if isinstance(phone, dict) and _GRAPH_ID.fullmatch(str(phone.get("id", ""))):
                    discovered[str(phone["id"])] = phone
    if len(discovered) == 1:
        phone_id, phone = next(iter(discovered.items()))
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
            **({"publish_blocker": review, "review_state": "pending" if pending else "unverified"} if review else {})}


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
        params.update(config_id=_setting("WHATSAPP_EMBEDDED_SIGNUP_CONFIG_ID"), override_default_response_type="true",
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
    answer = {"ok": True, "provider": provider, "account_id": record["account_id"],
              "name": record.get("name", ""), "access_token": grant_payload["access_token"]}
    if provider in _META_NETWORKS:
        answer["pages"] = grant_payload.get("pages", [])
        answer["page_secrets"] = grant_payload.get("page_secrets", {})
    return answer
