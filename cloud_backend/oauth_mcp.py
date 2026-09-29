"""OAuth for the public MCP door (MCP authorization 2026-07-28), so Gemini Spark and
Notion connect to https://api.archhub.io/mcp as the founder's ACCOUNT.

One identity source: the verified Google sign-in (google_auth). This module reuses
only that verified identity; it never mints a desktop code or an ah_live_ token.

Every grant is bound to client_id, the exact redirect_uri, an S256 challenge, the
resource (this cloud's /mcp) and the scope mcp:read, and to the user Google verified.
Codes, access tokens and refresh tokens are stored as sha256 only. A code or a
refresh token is consumed by one conditional UPDATE, so two concurrent redemptions
cannot both succeed; a replay of either revokes the whole token family. Access
tokens live one hour and are accepted only by /mcp.

Dynamic Client Registration (RFC 7591) is the registration path here. The spec
prefers Client ID Metadata Documents (SHOULD) and keeps DCR as MAY; CIMD is the
known gap until a real client needs it.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import secrets
import time
import urllib.parse
from typing import Optional

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

import config
import db

router = APIRouter()

SCOPE = 'mcp:read'
ACCESS_TTL = 3600
REFRESH_TTL = 30 * 24 * 3600
CODE_TTL = 300
PENDING_TTL = 600
ACCESS_PREFIX = 'ah_mcp_at_'
REFRESH_PREFIX = 'ah_mcp_rt_'
MAX_CLIENTS = 10000
MAX_PENDING = 500
MAX_PENDING_PER_CLIENT = 20
MAX_PENDING_PER_ADDRESS = 20
MAX_STATE = 512
CONSENT_COOKIE = '__Host-archhub_mcp_consent'

SCHEMA = '''
CREATE TABLE IF NOT EXISTS oauth_clients (
    client_id     TEXT PRIMARY KEY,
    redirect_uris TEXT NOT NULL,
    client_name   TEXT NOT NULL DEFAULT '',
    created_at    INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS oauth_pending (
    id             TEXT PRIMARY KEY,
    client_id      TEXT NOT NULL,
    redirect_uri   TEXT NOT NULL,
    code_challenge TEXT NOT NULL,
    state          TEXT NOT NULL,
    scope          TEXT NOT NULL,
    resource       TEXT NOT NULL,
    expires_at     INTEGER NOT NULL,
    csrf_hash      TEXT NOT NULL,
    browser_hash   TEXT NOT NULL,
    address        TEXT NOT NULL,
    approved       INTEGER NOT NULL DEFAULT 0,
    verified_email TEXT,
    continue_hash  TEXT
);
CREATE TABLE IF NOT EXISTS oauth_approvals (
    user_id     TEXT NOT NULL,
    client_id   TEXT NOT NULL,
    approved_at INTEGER NOT NULL,
    PRIMARY KEY (user_id, client_id)
);
CREATE TABLE IF NOT EXISTS oauth_codes (
    code_hash      TEXT PRIMARY KEY,
    family         TEXT NOT NULL,
    client_id      TEXT NOT NULL,
    user_id        TEXT NOT NULL,
    redirect_uri   TEXT NOT NULL,
    code_challenge TEXT NOT NULL,
    scope          TEXT NOT NULL,
    resource       TEXT NOT NULL,
    expires_at     INTEGER NOT NULL,
    consumed_at    INTEGER
);
CREATE TABLE IF NOT EXISTS oauth_tokens (
    token_hash  TEXT PRIMARY KEY,
    kind        TEXT NOT NULL,
    family      TEXT NOT NULL,
    client_id   TEXT NOT NULL,
    user_id     TEXT NOT NULL,
    scope       TEXT NOT NULL,
    resource    TEXT NOT NULL,
    expires_at  INTEGER NOT NULL,
    consumed_at INTEGER
);
CREATE TABLE IF NOT EXISTS oauth_families (
    family     TEXT PRIMARY KEY,
    revoked_at INTEGER
);
'''


def _ensure() -> None:
    with db.connect() as con:
        con.executescript(SCHEMA)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def issuer() -> str:
    return config.PUBLIC_URL.rstrip('/')


def mcp_resource() -> str:
    return issuer() + '/mcp'


def resource_metadata_url() -> str:
    return issuer() + '/.well-known/oauth-protected-resource'


def challenge_header() -> str:
    """WWW-Authenticate for an unauthenticated /mcp call: where to find the server."""
    return 'Bearer resource_metadata="%s", scope="%s"' % (resource_metadata_url(), SCOPE)


def _error(error: str, description: str, status: int = 400) -> JSONResponse:
    return JSONResponse({'error': error, 'error_description': description}, status_code=status,
                        headers={'Cache-Control': 'no-store', 'Pragma': 'no-cache'})


# -- discovery ---------------------------------------------------------------
@router.get('/.well-known/oauth-protected-resource')
@router.get('/.well-known/oauth-protected-resource/mcp')
def protected_resource() -> dict:
    return {'resource': mcp_resource(), 'authorization_servers': [issuer()],
            'scopes_supported': [SCOPE], 'bearer_methods_supported': ['header']}


@router.get('/.well-known/oauth-authorization-server')
def authorization_server() -> dict:
    return {
        'issuer': issuer(),
        'authorization_endpoint': issuer() + '/oauth/authorize',
        'token_endpoint': issuer() + '/oauth/token',
        'registration_endpoint': issuer() + '/oauth/register',
        'response_types_supported': ['code'],
        'grant_types_supported': ['authorization_code', 'refresh_token'],
        'code_challenge_methods_supported': ['S256'],
        'token_endpoint_auth_methods_supported': ['none'],
        'scopes_supported': [SCOPE],
        'authorization_response_iss_parameter_supported': True,
    }


# -- registration ------------------------------------------------------------
def _redirect_allowed(uri: object) -> bool:
    """Exact https redirects, or a native client's loopback; no wildcard, no fragment."""
    if type(uri) is not str or not uri or len(uri) > 2048 or any(c in uri for c in '*#\\@'):
        return False
    # Browsers read a backslash as a slash and drop userinfo, so
    # https://evil.example\@spark.example/cb lands on evil.example. Neither is
    # ever legitimate in a redirect; nor is whitespace or a control character.
    if any(ord(c) <= 0x20 or ord(c) == 0x7f or not c.isascii() for c in uri):
        return False
    parts = urllib.parse.urlsplit(uri)
    if parts.username is not None or parts.password is not None:
        return False
    if parts.scheme == 'https' and parts.hostname:
        return True
    return parts.scheme == 'http' and parts.hostname in ('127.0.0.1', 'localhost', '::1')


@router.post('/oauth/register')
async def register(request: Request):
    try:
        body = await request.json()
    except Exception:
        return _error('invalid_client_metadata', 'body is not JSON')
    uris = body.get('redirect_uris') if isinstance(body, dict) else None
    if not isinstance(uris, list) or not 0 < len(uris) <= 10 or not all(map(_redirect_allowed, uris)):
        return _error('invalid_redirect_uri', 'exact https (or loopback http) redirect URIs are required')
    if body.get('token_endpoint_auth_method', 'none') != 'none':
        return _error('invalid_client_metadata', 'only public clients (token_endpoint_auth_method none)')
    name = body.get('client_name') if isinstance(body.get('client_name'), str) else ''
    _ensure()
    client_id = 'mcp_client_' + secrets.token_urlsafe(18)
    now = int(time.time())
    with db.connect() as con:
        if con.execute('SELECT COUNT(*) FROM oauth_clients').fetchone()[0] >= MAX_CLIENTS:
            # Anonymous registrations can never lock out a client someone approved:
            # the oldest client that was never approved and never issued a code goes.
            stale = con.execute(
                'SELECT client_id FROM oauth_clients c WHERE NOT EXISTS (SELECT 1 FROM oauth_approvals a '
                'WHERE a.client_id = c.client_id) AND NOT EXISTS (SELECT 1 FROM oauth_codes o '
                'WHERE o.client_id = c.client_id) ORDER BY created_at ASC LIMIT 1').fetchone()
            if stale is None:
                return _error('invalid_client_metadata', 'registration capacity reached')
            con.execute('DELETE FROM oauth_pending WHERE client_id = ?', (stale[0],))
            con.execute('DELETE FROM oauth_clients WHERE client_id = ?', (stale[0],))
        con.execute('INSERT INTO oauth_clients (client_id, redirect_uris, client_name, created_at) VALUES (?, ?, ?, ?)',
                    (client_id, json.dumps(uris), name[:200], now))
    return JSONResponse({'client_id': client_id, 'client_id_issued_at': now, 'redirect_uris': uris,
                         'client_name': name[:200], 'token_endpoint_auth_method': 'none',
                         'grant_types': ['authorization_code', 'refresh_token'], 'response_types': ['code']},
                        status_code=201)


def _client(client_id: str) -> Optional[dict]:
    _ensure()
    with db.connect() as con:
        row = con.execute('SELECT * FROM oauth_clients WHERE client_id = ?', (client_id or '',)).fetchone()
    if row is None:
        return None
    client = dict(row)
    client['redirect_uris'] = json.loads(client['redirect_uris'])
    return client


def _client_url(redirect_uri: str, **params) -> str:
    params = {key: value for key, value in params.items() if value}
    separator = '&' if urllib.parse.urlsplit(redirect_uri).query else '?'
    return redirect_uri + separator + urllib.parse.urlencode(params)


# -- authorization -----------------------------------------------------------
@router.get('/oauth/authorize')
def authorize(request: Request, response_type: str = '', client_id: str = '', redirect_uri: str = '',
              code_challenge: str = '', code_challenge_method: str = '', state: str = '',
              scope: str = '', resource: str = ''):
    client = _client(client_id)
    # An unknown client or an unregistered redirect is never redirected to.
    if client is None or redirect_uri not in client['redirect_uris'] or not _redirect_allowed(redirect_uri):
        return _error('invalid_request', 'unknown client or unregistered redirect_uri')
    if len(state) > MAX_STATE:
        return _error('invalid_request', 'state is longer than %d characters' % MAX_STATE)

    def fail(error: str, text: str) -> RedirectResponse:
        return RedirectResponse(_client_url(redirect_uri, error=error, error_description=text,
                                            state=state, iss=issuer()), status_code=302)

    if response_type != 'code':
        return fail('unsupported_response_type', 'response_type must be code')
    if code_challenge_method != 'S256' or not 43 <= len(code_challenge) <= 128:
        return fail('invalid_request', 'PKCE with S256 is required')
    if resource and resource != mcp_resource():
        return fail('invalid_target', 'unknown resource')
    if set((scope or SCOPE).split()) - {SCOPE}:
        return fail('invalid_scope', 'only mcp:read is offered')
    # Consent first (MCP "confused deputy"): nothing goes to Google, and no code can
    # ever reach this client's redirect, until the person in THIS browser approves
    # this client by name on ArchHub's own page.
    # The request is bound to THIS browser here, before any page is shown: the
    # consent POST must carry this cookie, so a pending/csrf pair scraped by someone
    # else is worthless in anyone else's browser.
    pending, csrf, browser = secrets.token_urlsafe(24), secrets.token_urlsafe(24), secrets.token_urlsafe(32)
    address = _address(request)
    with db.connect() as con:
        con.execute('DELETE FROM oauth_pending WHERE expires_at < ?', (int(time.time()),))
        for where, args, cap in (('', (), MAX_PENDING), (' AND client_id = ?', (client_id,), MAX_PENDING_PER_CLIENT),
                                 (' AND address = ?', (address,), MAX_PENDING_PER_ADDRESS)):
            if con.execute('SELECT COUNT(*) FROM oauth_pending WHERE approved = 0' + where, args).fetchone()[0] >= cap:
                return _error('temporarily_unavailable', 'too many unfinished authorizations; retry shortly', 503)
        con.execute('INSERT INTO oauth_pending (id, client_id, redirect_uri, code_challenge, state, scope, resource, '
                    'expires_at, csrf_hash, browser_hash, address) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                    (pending, client_id, redirect_uri, code_challenge, state, SCOPE, mcp_resource(),
                     int(time.time()) + PENDING_TTL, _hash(csrf), _hash(browser), address))
    page = _consent_page(client, redirect_uri, pending, csrf)
    page.set_cookie(CONSENT_COOKIE, pending + '.' + browser, max_age=PENDING_TTL, path='/',
                    secure=True, httponly=True, samesite='lax')
    return page


def _address(request: Request) -> str:
    """The caller's address. Fly's edge overwrites Fly-Client-IP, so it cannot be forged there."""
    return (request.headers.get('fly-client-ip') or (request.client.host if request.client else '') or '-')[:64]


def _this_browser(request: Request, pending_id: str) -> str:
    """The browser secret this request's cookie holds for `pending_id`, or ''."""
    held, _, browser = request.cookies.get(CONSENT_COOKIE, '').partition('.')
    return browser if pending_id and held == pending_id else ''


_PAGE_HEADERS = {'X-Frame-Options': 'DENY', 'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer'}
GOOGLE_ORIGIN = 'https://accounts.google.com'


def _page_policy(redirect_uri: str) -> str:
    """form-action also governs the POST's redirect: Approve goes to Google, Deny to the client."""
    parts = urllib.parse.urlsplit(redirect_uri)
    return ("default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'; "
            "form-action 'self' %s %s://%s" % (GOOGLE_ORIGIN, parts.scheme, parts.netloc))


def _consent_page(client: dict, redirect_uri: str, pending: str, csrf: str) -> HTMLResponse:
    name = html.escape(client.get('client_name') or 'An unnamed application')
    host = html.escape(urllib.parse.urlsplit(redirect_uri).hostname or '')
    body = (
        '<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width">'
        '<title>Allow access to ArchHub?</title>'
        '<body style="font-family:system-ui,sans-serif;max-width:34rem;margin:3rem auto;padding:0 1rem">'
        '<h1 style="font-size:1.3rem">Allow <b>%s</b> to read your ArchHub?</h1>'
        '<p>It will send you back to <b>%s</b> and may read your ArchHub brain and, for the founder, '
        'your desktop hosts (read only). Approve only if you just started this from that application.</p>'
        '<form method=post action="/oauth/consent">'
        '<input type=hidden name=pending value="%s"><input type=hidden name=csrf value="%s">'
        '<button name=decision value=approve>Approve</button> '
        '<button name=decision value=deny>Deny</button></form></body>'
    ) % (name, host, html.escape(pending), html.escape(csrf))
    return HTMLResponse(body, headers={**_PAGE_HEADERS, 'Content-Security-Policy': _page_policy(redirect_uri)})


@router.post('/oauth/consent')
def consent(request: Request, pending: str = Form(''), csrf: str = Form(''), decision: str = Form('')):
    """The person's own Approve or Deny, only from the browser the request was shown in."""
    import google_auth
    _ensure()
    browser = _this_browser(request, pending)
    with db.connect() as con:
        row = con.execute('SELECT * FROM oauth_pending WHERE id = ?', (pending or '',)).fetchone()
        grant = dict(row) if row else None
        if (grant is None or grant['approved'] or grant['expires_at'] < int(time.time())
                or not hmac.compare_digest(grant['csrf_hash'], _hash(csrf or ''))
                or not browser or not hmac.compare_digest(grant['browser_hash'], _hash(browser))):
            return _error('invalid_request', 'this authorization request is unknown, expired, already decided '
                                             'or was not opened in this browser')
        if decision != 'approve':
            con.execute('DELETE FROM oauth_pending WHERE id = ?', (pending,))
            return RedirectResponse(_client_url(grant['redirect_uri'], error='access_denied',
                                                state=grant['state'], iss=issuer()), status_code=302)
        taken = con.execute('UPDATE oauth_pending SET approved = 1 WHERE id = ? AND approved = 0',
                            (pending,)).rowcount
    if not taken:
        return _error('invalid_request', 'this authorization request was already decided')
    try:
        url = google_auth.build_authorization_url(mcp_grant=pending)
    except google_auth.GoogleLoginUnconfigured:
        return _error('temporarily_unavailable', 'Google sign-in is not configured', 503)
    return RedirectResponse(url, status_code=302)


def google_verified(pending_id: str, email: str) -> str:
    """Google verified `email` for an approved request; record it server-side, once.

    The continue URL carries one opaque single-use value and nothing else: no email,
    no request id. It is honoured only together with the cookie of the browser that
    approved, and a presentation from any other browser burns the request.
    """
    _ensure()
    secret = secrets.token_urlsafe(32)
    with db.connect() as con:
        taken = con.execute('UPDATE oauth_pending SET verified_email = ?, continue_hash = ? WHERE id = ? '
                            'AND approved = 1 AND verified_email IS NULL AND expires_at >= ?',
                            (email, _hash(secret), pending_id or '', int(time.time()))).rowcount
    if not taken:
        raise ValueError('unknown, unapproved, expired or already verified authorization request')
    return issuer() + '/oauth/continue?' + urllib.parse.urlencode({'c': secret})


@router.get('/oauth/continue')
def continue_authorization(request: Request, c: str = ''):
    try:
        target = finish_authorization(c, request)
    except ValueError as refused:
        return _error('access_denied', str(refused))
    answer = RedirectResponse(target, status_code=302, headers={'Referrer-Policy': 'no-referrer'})
    answer.delete_cookie(CONSENT_COOKIE, path='/', secure=True, httponly=True, samesite='lax')
    return answer


def finish_authorization(continue_secret: str, request: Request) -> str:
    """The browser that approved this client returns from Google; mint its code, once."""
    _ensure()
    with db.connect() as con:
        row = con.execute('SELECT * FROM oauth_pending WHERE continue_hash = ?',
                          (_hash(continue_secret or ''),)).fetchone() if continue_secret else None
        if row is None:
            raise ValueError('unknown or already used sign-in')
        # One presentation only: whoever presents it, the request is spent.
        taken = con.execute('DELETE FROM oauth_pending WHERE id = ?', (row['id'],)).rowcount
    browser = _this_browser(request, row['id'])
    if not taken or not browser or not hmac.compare_digest(row['browser_hash'], _hash(browser)):
        raise ValueError('this browser did not approve this application')
    grant = dict(row)
    if not grant['approved'] or not grant['verified_email'] or grant['expires_at'] < int(time.time()):
        raise ValueError('authorization request expired or incomplete')
    user = db.get_or_create_user(grant['verified_email'])
    if user.get('suspended_at'):
        raise ValueError('this account is suspended')
    with db.connect() as con:
        con.execute('INSERT INTO oauth_approvals (user_id, client_id, approved_at) VALUES (?, ?, ?) '
                    'ON CONFLICT(user_id, client_id) DO UPDATE SET approved_at = excluded.approved_at',
                    (user['id'], grant['client_id'], int(time.time())))
    code = secrets.token_urlsafe(32)
    family = secrets.token_hex(16)
    with db.connect() as con:
        con.execute('INSERT INTO oauth_families (family, revoked_at) VALUES (?, NULL)', (family,))
        con.execute('INSERT INTO oauth_codes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)',
                    (_hash(code), family, grant['client_id'], user['id'], grant['redirect_uri'],
                     grant['code_challenge'], grant['scope'], grant['resource'], int(time.time()) + CODE_TTL))
    return _client_url(grant['redirect_uri'], code=code, state=grant['state'], iss=issuer())


# -- tokens ------------------------------------------------------------------
def _revoke(con, family: str) -> None:
    con.execute('UPDATE oauth_families SET revoked_at = ? WHERE family = ? AND revoked_at IS NULL',
                (int(time.time()), family))


def _issue(con, *, family: str, client_id: str, user_id: str, scope: str, resource: str) -> Optional[dict]:
    """Tokens for an account that may still sign in; None (and the family revoked) otherwise."""
    if con.execute('SELECT 1 FROM users WHERE id = ? AND suspended_at IS NULL', (user_id,)).fetchone() is None:
        _revoke(con, family)
        return None
    now = int(time.time())
    access, refresh = ACCESS_PREFIX + secrets.token_urlsafe(32), REFRESH_PREFIX + secrets.token_urlsafe(32)
    for value, kind, ttl in ((access, 'access', ACCESS_TTL), (refresh, 'refresh', REFRESH_TTL)):
        con.execute('INSERT INTO oauth_tokens VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)',
                    (_hash(value), kind, family, client_id, user_id, scope, resource, now + ttl))
    return {'access_token': access, 'token_type': 'Bearer', 'expires_in': ACCESS_TTL,
            'refresh_token': refresh, 'scope': scope}


def _pkce_ok(verifier: str, challenge: str) -> bool:
    if not 43 <= len(verifier or '') <= 128:
        return False
    digest = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode('ascii', 'replace')).digest())
    return secrets.compare_digest(digest.rstrip(b'=').decode('ascii'), challenge)


@router.post('/oauth/token')
def token(grant_type: str = Form(''), code: str = Form(''), redirect_uri: str = Form(''),
          client_id: str = Form(''), code_verifier: str = Form(''), refresh_token: str = Form(''),
          resource: str = Form('')):
    _ensure()
    now = int(time.time())
    if resource and resource != mcp_resource():
        return _error('invalid_target', 'unknown resource')
    with db.connect() as con:
        if grant_type == 'authorization_code':
            digest = _hash(code or '')
            row = con.execute('SELECT * FROM oauth_codes WHERE code_hash = ?', (digest,)).fetchone()
            if row is None:
                return _error('invalid_grant', 'unknown code')
            grant = dict(row)
            taken = con.execute('UPDATE oauth_codes SET consumed_at = ? WHERE code_hash = ? AND consumed_at IS NULL',
                                (now, digest)).rowcount
            if not taken:
                _revoke(con, grant['family'])  # a replayed code revokes everything it issued
                return _error('invalid_grant', 'code already used')
            if (grant['expires_at'] < now or grant['client_id'] != client_id
                    or grant['redirect_uri'] != redirect_uri or not _pkce_ok(code_verifier, grant['code_challenge'])):
                return _error('invalid_grant', 'code, client, redirect_uri or verifier does not match')
            answer = _issue(con, family=grant['family'], client_id=client_id, user_id=grant['user_id'],
                            scope=grant['scope'], resource=grant['resource'])
        elif grant_type == 'refresh_token':
            digest = _hash(refresh_token or '')
            row = con.execute('SELECT * FROM oauth_tokens WHERE token_hash = ? AND kind = ?',
                              (digest, 'refresh')).fetchone()
            if row is None:
                return _error('invalid_grant', 'unknown refresh token')
            held = dict(row)
            taken = con.execute('UPDATE oauth_tokens SET consumed_at = ? WHERE token_hash = ? AND consumed_at IS NULL',
                                (now, digest)).rowcount
            if not taken:
                _revoke(con, held['family'])  # a replayed refresh token revokes the family
                return _error('invalid_grant', 'refresh token already used')
            revoked = con.execute('SELECT revoked_at FROM oauth_families WHERE family = ?',
                                  (held['family'],)).fetchone()
            if held['expires_at'] < now or held['client_id'] != client_id or (revoked and revoked[0]):
                return _error('invalid_grant', 'refresh token expired, revoked or for another client')
            answer = _issue(con, family=held['family'], client_id=client_id, user_id=held['user_id'],
                            scope=held['scope'], resource=held['resource'])
        else:
            return _error('unsupported_grant_type', 'authorization_code or refresh_token')
        if answer is None:
            return _error('invalid_grant', 'this account is suspended')
    return JSONResponse(answer, headers={'Cache-Control': 'no-store', 'Pragma': 'no-cache'})


def user_for_access_token(value: str) -> Optional[dict]:
    """The account behind an MCP access token, only for this resource and mcp:read."""
    if type(value) is not str or not value.startswith(ACCESS_PREFIX):
        return None
    _ensure()
    with db.connect() as con:
        row = con.execute(
            'SELECT t.* FROM oauth_tokens t JOIN oauth_families f ON f.family = t.family '
            'WHERE t.token_hash = ? AND t.kind = ? AND f.revoked_at IS NULL', (_hash(value), 'access')).fetchone()
        if row is None:
            return None
        held = dict(row)
        if (held['expires_at'] < int(time.time()) or held['resource'] != mcp_resource()
                or SCOPE not in held['scope'].split()):
            return None
        # A suspended account authenticates nowhere, as in db.user_for_token.
        user = con.execute('SELECT * FROM users WHERE id = ? AND suspended_at IS NULL', (held['user_id'],)).fetchone()
    return dict(user) if user else None