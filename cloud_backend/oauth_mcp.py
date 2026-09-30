"""OAuth for the public MCP door (MCP authorization 2026-07-28), so Gemini Spark and
Notion connect to https://api.archhub.io/mcp as the founder's ACCOUNT.

One identity source: the verified Google sign-in (google_auth). This module reuses
only that verified identity; it never mints a desktop code or an ah_live_ token.

Every grant is bound to client_id, the exact redirect_uri, an S256 challenge, the
resource (this cloud's /mcp) and its scopes, and to the user Google verified: mcp:read
always, and mcp:workshop when the client asks for it (the client then takes part in the
founder's Workshop as its own agent; the consent page says so before Approve).
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
import ipaddress
import json
import logging
import os
import re
import secrets
import sqlite3
import time
import urllib.parse
from typing import Optional

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

import config
import db

router = APIRouter()

SCOPE = 'mcp:read'
# The founder's Workshop, as this client's own agent (brain_mcp WORKSHOP_TOOLS):
# read and post Workshop messages and claim Work there. Asked for, never implied.
WORKSHOP_SCOPE = 'mcp:workshop'
SCOPES = (SCOPE, WORKSHOP_SCOPE)
ACCESS_TTL = 3600
REFRESH_TTL = 30 * 24 * 3600
CODE_TTL = 300
PENDING_TTL = 600
ACCESS_PREFIX = 'ah_mcp_at_'
REFRESH_PREFIX = 'ah_mcp_rt_'
MAX_CLIENTS = 10000
MAX_PENDING = 500              # live requests of clients the founder has not approved
MAX_PENDING_ALL = 5000         # every live request: the storage ceiling
MAX_PENDING_PER_CLIENT = 5     # per client, per caller address
MAX_PENDING_PER_ADDRESS = 20   # per caller address (an IPv4 address, an IPv6 /64)
MAX_PENDING_PER_NETWORK = 100  # per caller network (an IPv4 /24, an IPv6 /48)
MAX_STATE = 512
MAX_FOUNDER_LANE = 20          # live requests in the founder's own lane, per founder account
MAX_VERIFIED_PER_EMAIL = 2     # live Google-verified requests per signed-in account
MAX_ENDED = 10000              # tombstones kept for ended sign-ins; the oldest go first
FOUNDER_LANE_TTL = 180 * 24 * 3600
CONSENT_COOKIE = '__Host-archhub_mcp_consent'
FOUNDER_COOKIE = '__Host-archhub_mcp_founder'

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
    network        TEXT NOT NULL DEFAULT '-',
    approved       INTEGER NOT NULL DEFAULT 0,
    verified_email TEXT,
    continue_hash  TEXT,
    lane           TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS oauth_ended (
    id            TEXT PRIMARY KEY,
    redirect_uri  TEXT NOT NULL,
    state         TEXT NOT NULL,
    expires_at    INTEGER NOT NULL,
    continue_hash TEXT
);
CREATE TABLE IF NOT EXISTS oauth_lane_epochs (
    email TEXT PRIMARY KEY,
    epoch INTEGER NOT NULL
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
        # A table made before these columns existed gains them.
        _add_column(con, 'network', "network TEXT NOT NULL DEFAULT '-'")
        _add_column(con, 'lane', "lane TEXT NOT NULL DEFAULT ''")
        _add_column(con, 'continue_hash', 'continue_hash TEXT', table='oauth_ended')


def _add_column(con, name: str, ddl: str, *, table: str = 'oauth_pending') -> None:
    """ALTER once. Two first requests after a deploy may both see the column
    missing; the second ALTER then fails and finds it present, which is fine.
    Any other failure is still an error."""
    if name in {row[1] for row in con.execute('PRAGMA table_info(%s)' % table)}:
        return
    try:
        con.execute('ALTER TABLE %s ADD COLUMN %s' % (table, ddl))
    except sqlite3.OperationalError:
        if name not in {row[1] for row in con.execute('PRAGMA table_info(%s)' % table)}:
            raise


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
    return 'Bearer resource_metadata="%s", scope="%s"' % (resource_metadata_url(), ' '.join(SCOPES))


def _error(error: str, description: str, status: int = 400) -> JSONResponse:
    return JSONResponse({'error': error, 'error_description': description}, status_code=status,
                        headers={'Cache-Control': 'no-store', 'Pragma': 'no-cache'})


# -- discovery ---------------------------------------------------------------
@router.get('/.well-known/oauth-protected-resource')
@router.get('/.well-known/oauth-protected-resource/mcp')
def protected_resource() -> dict:
    return {'resource': mcp_resource(), 'authorization_servers': [issuer()],
            'scopes_supported': list(SCOPES), 'bearer_methods_supported': ['header']}


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
        'scopes_supported': list(SCOPES),
        'authorization_response_iss_parameter_supported': True,
    }


# -- registration ------------------------------------------------------------
_AUTHORITY = re.compile(r'(?:[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?|\[[0-9A-Fa-f:.]{2,45}\])(?::[0-9]{1,5})?')


def _redirect_allowed(uri: object) -> bool:
    """Exact https redirects, or a native client's loopback; no wildcard, no fragment."""
    if type(uri) is not str or not uri or len(uri) > 2048 or any(c in uri for c in '*#\\@'):
        return False
    # Browsers read a backslash as a slash and drop userinfo, so
    # https://evil.example\@spark.example/cb lands on evil.example. Neither is
    # ever legitimate in a redirect; nor is whitespace or a control character.
    if any(ord(c) <= 0x20 or ord(c) == 0x7f or not c.isascii() for c in uri):
        return False
    try:
        parts = urllib.parse.urlsplit(uri)
        userinfo = parts.username is not None or parts.password is not None
    except ValueError:                 # e.g. https://[zz]/cb
        return False
    if userinfo:
        return False
    # The authority is written into the consent page's CSP (form-action), so it is a
    # bare host[:port] and nothing else: no ; , quotes or anything a policy parses.
    if not _AUTHORITY.fullmatch(parts.netloc):
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
    asked = set((scope or SCOPE).split())
    if asked - set(SCOPES):
        return fail('invalid_scope', 'only mcp:read and mcp:workshop are offered')
    # mcp:read always; mcp:workshop only when asked, and the page names it.
    granted = ' '.join(name for name in SCOPES if name == SCOPE or name in asked)
    # Consent first (MCP "confused deputy"): nothing goes to Google, and no code can
    # ever reach this client's redirect, until the person in THIS browser approves
    # this client by name on ArchHub's own page.
    # The request is bound to THIS browser here, before any page is shown: the
    # consent POST must carry this cookie, so a pending/csrf pair scraped by someone
    # else is worthless in anyone else's browser.
    pending, csrf, browser = secrets.token_urlsafe(24), secrets.token_urlsafe(24), secrets.token_urlsafe(32)
    address, network = _address(request)
    lane = founder_lane(request)
    with db.connect() as con:
        _end_expired(con)
        if lane:
            # The founder's own browser (proven by the signed lane cookie minted when
            # one of his sign-ins completed): his requests are counted only against
            # his own lane, never against any shared ceiling or any address, network
            # or client share, and nothing but his own newer requests ever evicts them.
            live = con.execute('SELECT COUNT(*) FROM oauth_pending WHERE lane = ?', (lane,)).fetchone()[0]
            if live >= MAX_FOUNDER_LANE and not _evict_oldest(con, ' WHERE lane = ?', (lane,)):
                return _error('temporarily_unavailable', 'too many unfinished authorizations; retry shortly', 503)
            con.execute('INSERT INTO oauth_pending (id, client_id, redirect_uri, code_challenge, state, scope, '
                        'resource, expires_at, csrf_hash, browser_hash, address, network, lane) '
                        'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                        (pending, client_id, redirect_uri, code_challenge, state, granted, mcp_resource(),
                         int(time.time()) + PENDING_TTL, _hash(csrf), _hash(browser), address, network, lane))
            page = _consent_page(client, redirect_uri, pending, csrf, granted)
            page.set_cookie(CONSENT_COOKIE, pending + '.' + browser, max_age=PENDING_TTL, path='/',
                            secure=True, httponly=True, samesite='lax')
            return page
        # Every live request counts, approved or not: approving one's own requests
        # frees nothing. Only a client the FOUNDER has approved (his Spark, his
        # Notion) stands outside the shared pool; any other account's approval is
        # free to obtain and buys nothing. A client's share is counted per caller
        # address, so knowing a public client_id cannot lock that client out.
        #
        # Everyone else shares: the caller's own shares (per client and address,
        # per address, per network) refuse when full; the shared ceilings never
        # refuse while any request outside the founder's lane is there to make
        # room, verified or not: the oldest one goes (never-approved first, then
        # unverified, then verified). Anyone can file, approve and even finish
        # Google on requests naming any client, so no such request is protected.
        known_sql, founders = _founder_approval_sql('?')
        known = con.execute('SELECT ' + known_sql, (client_id,) + founders).fetchone()[0]
        own = [(" WHERE lane = '' AND client_id = ? AND address = ?", (client_id, address), MAX_PENDING_PER_CLIENT),
               (" WHERE lane = '' AND address = ?", (address,), MAX_PENDING_PER_ADDRESS),
               (" WHERE lane = '' AND network = ?", (network,), MAX_PENDING_PER_NETWORK)]
        for where, args, cap in own:
            if con.execute('SELECT COUNT(*) FROM oauth_pending' + where, args).fetchone()[0] >= cap:
                return _error('temporarily_unavailable', 'too many unfinished authorizations; retry shortly', 503)
        shared = [(" WHERE lane = ''", (), MAX_PENDING_ALL)]
        if not known:
            pool_sql, founders = _founder_approval_sql('oauth_pending.client_id')
            shared.append((" WHERE lane = '' AND NOT " + pool_sql, founders, MAX_PENDING))
        for where, args, cap in shared:
            if con.execute('SELECT COUNT(*) FROM oauth_pending' + where, args).fetchone()[0] >= cap:
                if not _evict_oldest(con, where, args):
                    return _error('temporarily_unavailable', 'too many unfinished authorizations; retry shortly', 503)
        con.execute('INSERT INTO oauth_pending (id, client_id, redirect_uri, code_challenge, state, scope, resource, '
                    'expires_at, csrf_hash, browser_hash, address, network) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                    (pending, client_id, redirect_uri, code_challenge, state, granted, mcp_resource(),
                     int(time.time()) + PENDING_TTL, _hash(csrf), _hash(browser), address, network))
    page = _consent_page(client, redirect_uri, pending, csrf, granted)
    page.set_cookie(CONSENT_COOKIE, pending + '.' + browser, max_age=PENDING_TTL, path='/',
                    secure=True, httponly=True, samesite='lax')
    return page


def _evict_oldest(con, where: str, args: tuple) -> bool:
    """Make room: end the oldest request `where` selects (never-approved first, then
    not yet verified, then verified). Clicking Approve needs no sign-in and finishing
    Google needs only some Google account, so neither buys a stranger's request
    protection; the founder's are protected by his lane, not by their state. The
    ended request leaves a tombstone so its person is told, not left hanging."""
    row = con.execute('SELECT id, redirect_uri, state, expires_at, continue_hash FROM oauth_pending' + where +
                      ' ORDER BY approved ASC, verified_email IS NOT NULL, expires_at ASC, rowid ASC LIMIT 1',
                      args).fetchone()
    if row is None:
        return False
    _tombstone(con, row)
    return con.execute('DELETE FROM oauth_pending WHERE id = ?', (row['id'],)).rowcount == 1


def _tombstone(con, row) -> None:
    """Remember an ended request long enough to tell its person; keep at most MAX_ENDED."""
    con.execute('INSERT OR REPLACE INTO oauth_ended (id, redirect_uri, state, expires_at, continue_hash) '
                'VALUES (?, ?, ?, ?, ?)',
                (row['id'], row['redirect_uri'], row['state'], int(row['expires_at']) + PENDING_TTL,
                 row['continue_hash']))
    over = con.execute('SELECT COUNT(*) FROM oauth_ended').fetchone()[0] - MAX_ENDED
    if over > 0:
        con.execute('DELETE FROM oauth_ended WHERE id IN (SELECT id FROM oauth_ended '
                    'ORDER BY expires_at ASC, rowid ASC LIMIT ?)', (over,))


def _end_expired(con) -> None:
    """Expired requests end with a tombstone; tombstones themselves expire."""
    now = int(time.time())
    for row in con.execute('SELECT id, redirect_uri, state, expires_at, continue_hash FROM oauth_pending '
                           'WHERE expires_at < ?',
                           (now,)).fetchall():
        _tombstone(con, row)
    con.execute('DELETE FROM oauth_pending WHERE expires_at < ?', (now,))
    con.execute('DELETE FROM oauth_ended WHERE expires_at < ?', (now,))


_ENDED_PAGE = ('<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width">'
               '<title>Sign-in ended</title>'
               '<body style="font-family:system-ui,sans-serif;max-width:34rem;margin:3rem auto;padding:0 1rem">'
               '<h1 style="font-size:1.3rem">This sign-in has ended</h1>'
               '<p>It expired, was already used, or was started in another browser. Nothing was shared. '
               'Start again from your app (for example, connect ArchHub again in Spark or Notion).</p></body>')


def ended_response(pending_id: str, *, continue_secret: str = ''):
    """What a person sees when their sign-in is gone: back to their app with
    error=access_denied when the request is known (by its id on Google's callback,
    or by its continue value after Google), else a plain explanation."""
    _ensure()
    with db.connect() as con:
        if continue_secret:
            row = con.execute('SELECT * FROM oauth_ended WHERE continue_hash = ? AND expires_at >= ?',
                              (_hash(continue_secret), int(time.time()))).fetchone()
        else:
            row = con.execute('SELECT * FROM oauth_ended WHERE id = ? AND expires_at >= ?',
                              (pending_id or '', int(time.time()))).fetchone()
    if row is not None and _redirect_allowed(row['redirect_uri']):
        return RedirectResponse(_client_url(row['redirect_uri'], error='access_denied',
                                            error_description='the sign-in expired; start again',
                                            state=row['state'], iss=issuer()), status_code=302)
    return HTMLResponse(_ENDED_PAGE, status_code=400,
                        headers={**_PAGE_HEADERS, 'Content-Security-Policy': "default-src 'none'; style-src 'unsafe-inline'"})


# -- the founder's lane ----------------------------------------------------------------------
def _lane_key() -> bytes:
    """The lane cookie's own HMAC key: the Google client secret under a label no other
    use shares. With Google unconfigured there is no secret, so no lane key at all."""
    import google_auth
    if not config.google_login_enabled():
        raise ValueError('no lane without Google sign-in configured')
    secret = google_auth._state_secret()
    if not secret:
        raise ValueError('no lane without a server secret')
    return hashlib.sha256(b'archhub-mcp-founder-lane|' + secret).digest()


def _lane_epoch(email: str) -> int:
    with db.connect() as con:
        row = con.execute('SELECT epoch FROM oauth_lane_epochs WHERE email = ?', (email,)).fetchone()
    return int(row[0]) if row else 0


def revoke_founder_lanes(email: str) -> int:
    """End every lane cookie minted so far for `email` (server-side); returns the new epoch."""
    _ensure()
    email = (email or '').strip().lower()
    with db.connect() as con:
        con.execute('INSERT INTO oauth_lane_epochs (email, epoch) VALUES (?, 1) '
                    'ON CONFLICT(email) DO UPDATE SET epoch = epoch + 1', (email,))
        return int(con.execute('SELECT epoch FROM oauth_lane_epochs WHERE email = ?', (email,)).fetchone()[0])


def founder_lane_cookie(email: str) -> str:
    body = base64.urlsafe_b64encode(json.dumps({'e': email, 'x': int(time.time()) + FOUNDER_LANE_TTL,
                                                'n': _lane_epoch(email)},
                                               separators=(',', ':')).encode()).decode().rstrip('=')
    return body + '.' + hmac.new(_lane_key(), body.encode(), hashlib.sha256).hexdigest()


def founder_lane(request: Request) -> str:
    """The founder account this browser proved it is, or ''.

    The cookie is minted only when a sign-in Google verified for a founder email
    completes in this browser, is signed with the server's state secret, and is
    re-checked on every use against the configured founder emails and suspension.
    """
    body, _, mac = request.cookies.get(FOUNDER_COOKIE, '').partition('.')
    if not body or not body.isascii() or not mac.isascii():
        return ''                      # compare_digest refuses non-ASCII text: that is no lane
    try:
        key = _lane_key()
    except ValueError:
        return ''
    if not hmac.compare_digest(mac, hmac.new(key, body.encode(), hashlib.sha256).hexdigest()):
        return ''
    try:
        claims = json.loads(base64.urlsafe_b64decode(body + '=' * (-len(body) % 4)))
        email, expires, epoch = str(claims['e']).strip().lower(), int(claims['x']), int(claims.get('n', 0))
    except Exception:
        return ''
    if expires < int(time.time()) or email not in config.founder_emails():
        return ''
    if epoch != _lane_epoch(email):
        return ''                      # revoke_founder_lanes ended every earlier cookie
    user = db.get_user_by_email(email)
    if user is None or user.get('suspended_at'):
        return ''
    return email


def _founder_approval_sql(client_ref: str) -> tuple:
    """SQL true when a live founder account approved the client `client_ref` names.

    The founder is config.founder_emails() (the FOUNDER_EMAIL deployment secrets);
    none configured means no client is reserved.
    """
    founders = tuple(sorted(config.founder_emails()))
    if not founders:
        return '0', ()
    return ('EXISTS (SELECT 1 FROM oauth_approvals a JOIN users u ON u.id = a.user_id WHERE a.client_id = %s '
            'AND u.suspended_at IS NULL AND lower(u.email) IN (%s))' % (client_ref, ','.join('?' * len(founders))),
            founders)


def _address(request: Request) -> tuple:
    """The caller's (address, network), for the caps.

    Fly-Client-IP is read only when this process runs on Fly (FLY_APP_NAME), where
    Fly's proxy sets it from the connection and overwrites any value a client sent;
    anywhere else the header is the caller's own claim and the socket peer is used.
    IPv6 is counted per /64 (one subscriber) and per /48 (one site); IPv4 per
    address and per /24. Behind carrier-grade NAT many people share one IPv4
    address, and so share its 20; that is the price of counting addresses at all.
    """
    raw = request.headers.get('fly-client-ip', '') if os.environ.get('FLY_APP_NAME') else ''
    raw = raw.strip() or (request.client.host if request.client else '')
    try:
        ip = ipaddress.ip_address(raw)
    except ValueError:
        return '-', '-'
    if ip.version == 6 and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if ip.version == 6:
        return (str(ipaddress.ip_network('%s/64' % ip, strict=False)),
                str(ipaddress.ip_network('%s/48' % ip, strict=False)))
    return str(ip), str(ipaddress.ip_network('%s/24' % ip, strict=False))


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


def _consent_page(client: dict, redirect_uri: str, pending: str, csrf: str,
                  scope: str = SCOPE) -> HTMLResponse:
    name = html.escape(client.get('client_name') or 'An unnamed application')
    host = html.escape(urllib.parse.urlsplit(redirect_uri).hostname or '')
    workshop = ('<p><b>Workshop:</b> for the founder, it will also join the Workshop as its own '
                'agent: read its messages, post messages and claim Work there. It cannot run '
                'anything on the desktop.</p>') if WORKSHOP_SCOPE in scope.split() else ''
    body = (
        '<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width">'
        '<title>Allow access to ArchHub?</title>'
        '<body style="font-family:system-ui,sans-serif;max-width:34rem;margin:3rem auto;padding:0 1rem">'
        '<h1 style="font-size:1.3rem">Allow <b>%s</b> to read your ArchHub?</h1>'
        '<p>It will send you back to <b>%s</b> and may read your ArchHub brain and, for the founder, '
        'your desktop hosts (read only). Approve only if you just started this from that application.</p>'
        '%s<form method=post action="/oauth/consent">'
        '<input type=hidden name=pending value="%s"><input type=hidden name=csrf value="%s">'
        '<button name=decision value=approve>Approve</button> '
        '<button name=decision value=deny>Deny</button></form></body>'
    ) % (name, host, workshop, html.escape(pending), html.escape(csrf))
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


def google_verified(pending_id: str, email: str, *, consent_cookie: str) -> str:
    """Google verified `email` for an approved request; record it server-side, once.

    Only in the browser that approved: `consent_cookie` is that browser's cookie as
    it arrived on Google's callback. A leaked Google `state` finished in another
    browser (the attacker's account onto the victim's request, or the victim's
    account onto the attacker's) records nothing.

    The continue URL carries one opaque single-use value and nothing else: no email,
    no request id. It is honoured only together with the cookie of the browser that
    approved, and a presentation from any other browser burns the request.
    """
    _ensure()
    held, _, browser = (consent_cookie or '').partition('.')
    if not pending_id or held != pending_id or not browser:
        raise ValueError('this browser did not approve this application')
    secret = secrets.token_urlsafe(32)
    with db.connect() as con:
        taken = con.execute('UPDATE oauth_pending SET verified_email = ?, continue_hash = ? WHERE id = ? '
                            'AND browser_hash = ? AND approved = 1 AND verified_email IS NULL AND expires_at >= ?',
                            (email, _hash(secret), pending_id, _hash(browser), int(time.time()))).rowcount
        if taken:
            # One account holds at most MAX_VERIFIED_PER_EMAIL requests on the continue
            # step; a newer one ends its oldest, so no account can pile them up.
            while con.execute('SELECT COUNT(*) FROM oauth_pending WHERE verified_email = ?',
                              (email,)).fetchone()[0] > MAX_VERIFIED_PER_EMAIL:
                if not _evict_oldest(con, ' WHERE verified_email = ? AND id != ?', (email, pending_id)):
                    break
    if not taken:
        raise ValueError('unknown, unapproved, expired or already verified authorization request')
    return issuer() + '/oauth/continue?' + urllib.parse.urlencode({'c': secret})


@router.get('/oauth/continue')
def continue_authorization(request: Request, c: str = ''):
    try:
        target, email = finish_authorization(c, request)
    except ValueError:
        return ended_response('', continue_secret=c)
    answer = RedirectResponse(target, status_code=302, headers={'Referrer-Policy': 'no-referrer'})
    answer.delete_cookie(CONSENT_COOKIE, path='/', secure=True, httponly=True, samesite='lax')
    if email in config.founder_emails():
        # This browser just completed a founder sign-in Google verified: from now on
        # its requests use the founder's own lane.
        try:
            answer.set_cookie(FOUNDER_COOKIE, founder_lane_cookie(email), max_age=FOUNDER_LANE_TTL, path='/',
                              secure=True, httponly=True, samesite='lax')
        except ValueError:
            pass                       # no server secret: no lane, the sign-in itself stands
    return answer


def finish_authorization(continue_secret: str, request: Request) -> tuple:
    """The browser that approved this client returns from Google; mint its code, once.
    Returns (the client redirect carrying the code, the verified email)."""
    _ensure()
    with db.connect() as con:
        row = con.execute('SELECT * FROM oauth_pending WHERE continue_hash = ?',
                          (_hash(continue_secret or ''),)).fetchone() if continue_secret else None
        if row is None:
            raise ValueError('unknown or already used sign-in')
        if int(row['expires_at']) < int(time.time()):
            # It expired between Google and now: leave the same tombstone an expiry
            # sweep would, so the person is sent back to their app, not left hanging.
            _tombstone(con, row)
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
    return (_client_url(grant['redirect_uri'], code=code, state=grant['state'], iss=issuer()),
            str(grant['verified_email']).strip().lower())


# -- access log ----------------------------------------------------------------
_SECRET_QUERY_PATHS = ('/oauth/', '/v1/auth/google/callback', '/auth/return')


class _RedactSecretQueries(logging.Filter):
    """uvicorn's access line carries the full path with its query string; on the
    OAuth, Google-callback and desktop-return paths that query holds one-time
    values (?c=, ?code=, ?state=), so the line keeps the path and drops the query."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str):
            path, mark, _ = args[2].partition('?')
            if mark and path.startswith(_SECRET_QUERY_PATHS):
                record.args = args[:2] + (path + '?[redacted]',) + args[3:]
        return True


_ACCESS_FILTER = _RedactSecretQueries()


def install_access_log_redaction() -> None:
    access = logging.getLogger('uvicorn.access')
    if _ACCESS_FILTER not in access.filters:
        access.addFilter(_ACCESS_FILTER)


install_access_log_redaction()


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
        client = con.execute('SELECT client_name FROM oauth_clients WHERE client_id = ?',
                             (held['client_id'],)).fetchone()
    if not user:
        return None
    # Which client holds this token, and what it was granted: the Workshop tools
    # act as THIS client's own agent, and only with mcp:workshop.
    return {**dict(user), 'mcp_client': {
        'client_id': held['client_id'], 'client_name': (client['client_name'] if client else '') or '',
        'scopes': [name for name in SCOPES if name in held['scope'].split()]}}