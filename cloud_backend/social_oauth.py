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
import re
import secrets
import threading
import time
import urllib.parse
import urllib.request
from typing import Callable

from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import RedirectResponse

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
_META_PAGES = "https://graph.facebook.com/v25.0/me/accounts?fields=id,name,access_token,tasks&limit=25"
_GRAPH_ID = re.compile(r"[0-9]{1,32}(?:_[0-9]{1,32})?")


class SocialOAuthError(RuntimeError):
    pass


def _provider(provider: str) -> str:
    if provider not in ("linkedin", "meta"):
        raise HTTPException(status_code=404, detail="unknown_social_provider")
    return provider


def _secret() -> bytes:
    key = (config.SOCIAL_OAUTH_STATE_SECRET or config.GOOGLE_OAUTH_CLIENT_SECRET
           or config.LINKEDIN_OAUTH_CLIENT_SECRET or config.META_OAUTH_APP_SECRET)
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
    return config.social_oauth_enabled(provider)


def _client(provider: str) -> tuple[str, str, str]:
    if provider == "linkedin":
        client = (config.LINKEDIN_OAUTH_CLIENT_ID, config.LINKEDIN_OAUTH_CLIENT_SECRET,
                  config.LINKEDIN_OAUTH_REDIRECT)
    else:
        client = (config.META_OAUTH_APP_ID, config.META_OAUTH_APP_SECRET, config.META_OAUTH_REDIRECT)
    if not config.social_oauth_redirect_allowed(provider, client[2]):
        raise SocialOAuthError("redirect_not_allowed")
    return client


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


def exchange_and_profile(provider: str, code: str) -> dict:
    client_id, client_secret, redirect = _client(provider)
    exchange = _exchange or (lambda p, c, cid, secret: _post_form(_TOKEN[p], {
        "grant_type": "authorization_code", "code": c, "redirect_uri": redirect,
        "client_id": cid, "client_secret": secret}))
    payload = exchange(provider, code, client_id, client_secret)
    token = payload.get("access_token")
    if not isinstance(token, str) or not token:
        raise SocialOAuthError("token_exchange_failed")
    read_profile = _profile or (lambda p, t: _get_json(_PROFILE[p], t))
    who = read_profile(provider, token)
    raw_id = who.get("sub") if provider == "linkedin" else who.get("id")
    if not isinstance(raw_id, str) or not raw_id:
        raise SocialOAuthError("provider_account_missing")
    account_id = "urn:li:person:" + raw_id if provider == "linkedin" else raw_id
    result = {"provider": provider, "account_id": account_id,
              "name": str(who.get("name") or "")[:120],
              "access_token": token}
    if provider == "meta":
        public_pages, page_secrets = _meta_pages(token)
        result.update({"pages": public_pages, "page_secrets": page_secrets})
    return result


@router.get("/oauth/{provider}/status")
def status(provider: str, authorization: str | None = Header(None)) -> dict:
    provider = _provider(provider)
    _bearer(authorization)
    return {"ok": True, "provider": provider,
            "state": "configured" if configured(provider) else "missing"}


@router.get("/oauth/{provider}/start")
def start(provider: str, authorization: str | None = Header(None),
          x_archhub_device_session: str = Header(""),
          return_url: str = Query(""),
          nonce: str = Query("")) -> dict:
    provider = _provider(provider)
    user = _bearer(authorization)
    if not configured(provider):
        raise HTTPException(status_code=503, detail={"error": "social_oauth_unconfigured"})
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
    state = _sign({"n": nonce, "uid": user["id"], "p": provider,
                   "d": device, "exp": record["expires_at"]})
    url = _AUTHORIZE[provider] + "?" + urllib.parse.urlencode({
        "response_type": "code", "client_id": client_id, "redirect_uri": redirect,
        "state": state, "scope": _SCOPES[provider]})
    return {"ok": True, "provider": provider, "auth_url": url}


@router.get("/oauth/{provider}/callback")
def callback(provider: str, code: str = "", state: str = "", error: str = "") -> RedirectResponse:
    provider = _provider(provider)
    if error:
        raise HTTPException(status_code=400, detail={"error": "social_oauth_denied"})
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
        grant = exchange_and_profile(provider, code)
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
    except SocialOAuthError as exc:
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
    if provider == "meta":
        answer["pages"] = grant_payload.get("pages", [])
        answer["page_secrets"] = grant_payload.get("page_secrets", {})
    return answer
