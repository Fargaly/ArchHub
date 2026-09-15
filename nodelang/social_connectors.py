"""LinkedIn, Facebook Pages and Instagram through their official APIs.

Pure request preparation and response normalization, the server-side
resolver that rebuilds one request from a Work's graph-held inputs, and a
Work-root tool adapter for the existing native owner. This module never
holds, reads or resolves a credential, never sends a provider request and
authorizes nothing. The ArchHub runtime admits every read and write through
connector delegation -> founder approval -> one-use grant -> execution ->
receipt, and returns the raw provider answer to a normalizer here. Sources
and the runtime constraints still open are listed in docs/social-connectors.md.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import re
import threading
import urllib.parse
from collections.abc import Mapping

LINKEDIN_API = "https://api.linkedin.com"
LINKEDIN_VERSION = "202608"
GRAPH_API = "https://graph.facebook.com/v25.0"
PROVIDER_ORIGINS = {"linkedin": "api.linkedin.com", "meta": "graph.facebook.com"}
MAX_INPUT_BYTES = 256 * 1024  # the bound cell_connector_execution enforces
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_COUNT = 25
TEXT_LIMITS = {"linkedin": 3000, "facebook": 5000, "instagram": 2200}
UNCERTAIN = object()  # executor answer: dispatch may have happened, no response

# operation -> (provider, effect, method, proposed data class). Identity and
# account reads are internal metadata, other reads internal text, and only
# what is published is public text. Root owns the released classes.
OPERATIONS = {
    "linkedin.profile": ("linkedin", "read", "GET", "internal-metadata"),
    "linkedin.post": ("linkedin", "write", "POST", "public-text"),
    "linkedin.comment": ("linkedin", "write", "POST", "public-text"),
    "facebook.pages": ("meta", "read", "GET", "internal-metadata"),
    "facebook.feed": ("meta", "read", "GET", "internal-text"),
    "facebook.comments": ("meta", "read", "GET", "internal-text"),
    "facebook.page_post": ("meta", "write", "POST", "public-text"),
    "facebook.comment": ("meta", "write", "POST", "public-text"),
    "instagram.account": ("meta", "read", "GET", "internal-metadata"),
    "instagram.media": ("meta", "read", "GET", "internal-text"),
    "instagram.comments": ("meta", "read", "GET", "internal-text"),
    "instagram.reply": ("meta", "write", "POST", "public-text"),
    "instagram.container_create": ("meta", "write", "POST", "public-text"),
    "instagram.container_status": ("meta", "read", "GET", "internal-metadata"),
    "instagram.media_publish": ("meta", "write", "POST", "public-text"),
}

_GRAPH_ID = re.compile(r"[0-9]{1,32}(?:_[0-9]{1,32})?")
_LINKEDIN_PERSON = re.compile(r"urn:li:person:[A-Za-z0-9_-]{1,64}")
_LINKEDIN_MEMBER = re.compile(r"[A-Za-z0-9_-]{1,64}")
_LINKEDIN_POST = re.compile(r"urn:li:(?:share|ugcPost|activity):[0-9]{1,32}")
# little text: every reserved character is escaped; '#' stays live only where
# it starts a hashtag word (HashtagElement ::= '#' SINGLE_WORD).
_LITTLE_RESERVED = re.compile(r"([\\|{}@\[\]()<>*_~])")
_LITTLE_BARE_HASH = re.compile(r"#(?!\w)")
_ERROR_CODE = re.compile(r"[A-Za-z0-9._-]{1,64}")
_LIST_FIELDS = frozenset({"tasks"})
_MAX_FIELD_CHARS = 4000
_MAX_LIST_ITEMS = 32
_MAX_HEADERS = 64
_MAX_HEADER_CHARS = 512
_STATE_BY_STATUS = {
    400: "invalid_input", 401: "unauthorized", 403: "forbidden_scope",
    404: "not_found", 422: "invalid_input", 429: "rate_limited",
}


class Refusal(Exception):
    """A named reason an operation did not happen, or may have."""

    def __init__(self, state: str, reason: str, **detail: object) -> None:
        super().__init__(reason)
        self.state = state
        self.reason = reason
        self.detail = detail


def refusal_answer(refusal: Refusal) -> dict:
    return {"ok": False, "state": refusal.state, "reason": refusal.reason, **refusal.detail}


def _ok(**fields: object) -> dict:
    return {"ok": True, "state": "ok", **fields}


@dataclasses.dataclass(frozen=True)
class AccountBinding:
    """Non-secret requested binding; construction does not verify identity.

    account_id names the requested provider identity: the LinkedIn Person
    URN, the Meta user id (facebook.pages) or the Page id (other Meta
    operations). vault_entry is the NAME of a cell_brain_secrets entry, not
    its reference URI; the runtime reads SecretEntry(name, reference, custody)
    and resolves the credential inside custody. Host custody must verify this
    identity against the credential before dispatch. Nothing here resolves
    credentials or proves account ownership.
    """

    provider: str
    account_id: str
    vault_entry: str


@dataclasses.dataclass(frozen=True)
class PreparedRequest:
    """One bounded provider request without authorization, and its commitment."""

    provider: str
    account_id: str
    operation: str
    effect: str
    data_class: str
    method: str
    url: str
    headers: tuple[tuple[str, str], ...]
    body: bytes
    input_digest: str

    @property
    def input_bytes(self) -> int:
        return len(self.body)


# ------------------------------------------------------------------ validation --

def _text(value: object, platform: str, label: str = "text") -> str:
    if not isinstance(value, str) or not value.strip():
        raise Refusal("invalid_input", "%s is required" % label)
    if len(value) > TEXT_LIMITS[platform]:
        raise Refusal("invalid_input", "%s is longer than %d characters"
                      % (label, TEXT_LIMITS[platform]))
    return value


def _graph_id(value: object, label: str) -> str:
    if not isinstance(value, str) or not _GRAPH_ID.fullmatch(value):
        raise Refusal("invalid_input", "%s is not a valid id" % label)
    return value


def _count(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise Refusal("invalid_input", "count must be a whole number")
    return max(1, min(value, MAX_COUNT))


def _https_url(value: object, label: str) -> str:
    parts = urllib.parse.urlsplit(value) if isinstance(value, str) and len(value) <= 2048 else None
    if (parts is None or parts.scheme != "https" or not parts.hostname
            or parts.username is not None or parts.password is not None):
        raise Refusal("invalid_input", "%s must be an https URL without credentials" % label)
    return value


def _check_url(provider: str, url: str) -> None:
    parts = urllib.parse.urlsplit(url)
    try:
        port = parts.port
    except ValueError:
        port = -1
    if (parts.scheme != "https" or parts.hostname != PROVIDER_ORIGINS.get(provider)
            or parts.username is not None or parts.password is not None
            or port is not None or parts.fragment):
        raise Refusal("invalid_input", "URL is outside the provider origin")


def _little(text: str) -> str:
    return _LITTLE_BARE_HASH.sub(r"\\#", _LITTLE_RESERVED.sub(r"\\\1", text))


# ----------------------------------------------------------- prepared requests --

def _commitment(provider: str, account_id: str, operation: str, effect: str, data_class: str,
                method: str, url: str, headers: tuple[tuple[str, str], ...], body: bytes) -> str:
    seed = json.dumps([provider, account_id, operation, effect, data_class, method, url,
                       [list(pair) for pair in headers]], separators=(",", ":"))
    return hashlib.sha256(seed.encode("utf-8") + b"\x00" + body).hexdigest()


def _prepare(binding: object, operation: str, url: str, *, form: Mapping[str, str] | None = None,
             json_body: object = None,
             headers: tuple[tuple[str, str], ...] = ()) -> PreparedRequest:
    contract = OPERATIONS.get(operation)
    if contract is None:
        raise Refusal("invalid_input", "operation is not declared")
    provider, effect, method, data_class = contract
    if not isinstance(binding, AccountBinding) or binding.provider != provider:
        raise Refusal("missing_access", "%s needs a verified %s account binding" % (operation, provider))
    if (not isinstance(binding.account_id, str) or not binding.account_id
            or len(binding.account_id) > 256):
        raise Refusal("missing_access", "the account binding carries no verified account id")
    _check_url(provider, url)
    header_list = list(headers)
    body = b""
    if json_body is not None:
        body = json.dumps(json_body, separators=(",", ":"), sort_keys=True).encode("utf-8")
        header_list.append(("Content-Type", "application/json"))
    elif form is not None:
        body = urllib.parse.urlencode(sorted(dict(form).items())).encode("utf-8")
        header_list.append(("Content-Type", "application/x-www-form-urlencoded"))
    header_list.append(("Accept", "application/json"))
    if any(name.lower() == "authorization" for name, _ in header_list):
        raise Refusal("invalid_input", "a prepared request never carries authorization")
    if len(body) > MAX_INPUT_BYTES:
        raise Refusal("invalid_input", "request body exceeds %d bytes" % MAX_INPUT_BYTES)
    header_tuple = tuple(sorted(header_list))
    digest = _commitment(provider, binding.account_id, operation, effect, data_class, method, url,
                         header_tuple, body)
    return PreparedRequest(provider, binding.account_id, operation, effect, data_class, method,
                           url, header_tuple, body, digest)


def verify_prepared(prepared: object) -> PreparedRequest:
    """Runtime-side recheck. A PreparedRequest object is never authority."""
    if not isinstance(prepared, PreparedRequest):
        raise Refusal("invalid_input", "not a prepared request")
    if OPERATIONS.get(prepared.operation) != (prepared.provider, prepared.effect, prepared.method,
                                             prepared.data_class):
        raise Refusal("invalid_input", "operation, provider, effect, method or data class drifted")
    _check_url(prepared.provider, prepared.url)
    if (not isinstance(prepared.body, bytes) or len(prepared.body) > MAX_INPUT_BYTES
            or not isinstance(prepared.headers, tuple)
            or any(not isinstance(pair, tuple) or len(pair) != 2 for pair in prepared.headers)
            or any(str(name).lower() == "authorization" for name, _ in prepared.headers)):
        raise Refusal("invalid_input", "prepared request shape is invalid")
    expected = _commitment(prepared.provider, prepared.account_id, prepared.operation,
                           prepared.effect, prepared.data_class, prepared.method, prepared.url,
                           prepared.headers, prepared.body)
    if expected != prepared.input_digest:
        raise Refusal("invalid_input", "prepared request commitment does not match")
    return prepared


# --------------------------------------------------------------------- answers --

def _provider_code(data: object) -> object:
    if not isinstance(data, dict):
        return None
    error = data.get("error")
    value = error.get("code") if isinstance(error, dict) else data.get("serviceErrorCode")
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and 0 <= value < 10**9:
        return value
    if isinstance(value, str) and _ERROR_CODE.fullmatch(value):
        return value
    return None


def _decode(prepared: PreparedRequest, status: object, headers: object,
            body: object) -> tuple[dict, dict]:
    """Bounded, redacted decoding of one executor answer."""
    if status is UNCERTAIN:
        if prepared.effect == "write":
            raise Refusal("uncertain", "the request may have reached the provider; "
                          "reconcile before any new attempt", operation=prepared.operation)
        raise Refusal("network_error", "the provider could not be reached")
    # An unusable answer to a write never proves that the write did not happen.
    broken = "uncertain" if prepared.effect == "write" else "provider_error"
    if type(status) is not int or not isinstance(body, bytes) or not isinstance(headers, Mapping):
        raise Refusal(broken, "executor answer is malformed")
    if len(body) > MAX_RESPONSE_BYTES:
        raise Refusal(broken, "response exceeded %d bytes" % MAX_RESPONSE_BYTES)
    if len(headers) > _MAX_HEADERS:
        raise Refusal(broken, "too many response headers")
    try:
        data = json.loads(body.decode("utf-8")) if body.strip() else {}
    except ValueError:
        data = None
    if (prepared.effect == "write" and not 200 <= status < 300
            and status not in {400, 401, 403, 404, 422, 429}):
        raise Refusal("uncertain", "the provider failed after receiving the request; "
                      "reconcile before any new attempt", http_status=status)
    if not 200 <= status < 300:
        raise Refusal(_STATE_BY_STATUS.get(status, "provider_error"),
                      "provider answered HTTP %d" % status,
                      http_status=status, provider_code=_provider_code(data))
    if not isinstance(data, dict):
        raise Refusal(broken, "the provider answer is not a JSON object")
    kept = {}
    for key, value in headers.items():
        if str(key).lower() == "x-restli-id":
            text = str(value)
            if len(text) > _MAX_HEADER_CHARS:
                raise Refusal(broken, "response header exceeds its bound")
            kept["x-restli-id"] = text
    return data, kept


def _clean(name: str, value: object) -> tuple[bool, object]:
    if isinstance(value, (bool, int, float)):
        return True, value
    if isinstance(value, str):
        return True, value[:_MAX_FIELD_CHARS]
    if (name in _LIST_FIELDS and isinstance(value, list) and len(value) <= _MAX_LIST_ITEMS
            and all(isinstance(item, str) and len(item) <= 64 for item in value)):
        return True, list(value)
    return False, None


def _rows(data: dict, fields: tuple[str, ...], limit: int) -> list[dict]:
    """An explicit `data` list is required; only `data: []` is an empty success."""
    rows = data.get("data")
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows[:limit]):
        raise Refusal("provider_error", "the provider answer has no valid data collection")
    cleaned = []
    for row in rows[:limit]:
        kept = {}
        for name in fields:
            if name in row:
                keep, value = _clean(name, row[name])
                if keep:
                    kept[name] = value
        cleaned.append(kept)
    return cleaned


# -------------------------------------------------------------------- LinkedIn --

def _linkedin_headers() -> tuple[tuple[str, str], ...]:
    return (("Linkedin-Version", LINKEDIN_VERSION), ("X-Restli-Protocol-Version", "2.0.0"))


def _linkedin_person(binding: object) -> str:
    person = getattr(binding, "account_id", "")
    if not isinstance(person, str) or not _LINKEDIN_PERSON.fullmatch(person):
        raise Refusal("missing_access", "the LinkedIn binding must carry the runtime-verified Person URN")
    return person


def prepare_linkedin_profile(binding: AccountBinding) -> PreparedRequest:
    return _prepare(binding, "linkedin.profile", LINKEDIN_API + "/v2/userinfo")


def normalize_linkedin_profile(prepared: PreparedRequest, status, headers, body) -> dict:
    data, _ = _decode(prepared, status, headers, body)
    member = data.get("sub")
    if not isinstance(member, str) or not _LINKEDIN_MEMBER.fullmatch(member):
        raise Refusal("provider_error", "LinkedIn returned no member id")
    # Identity only: no author URN is built from `sub` here.
    return _ok(member_id=member, name=str(data.get("name") or "")[:200])


def prepare_linkedin_post(binding: AccountBinding, text: str,
                          visibility: str = "PUBLIC") -> PreparedRequest:
    text = _text(text, "linkedin")
    if visibility not in ("PUBLIC", "CONNECTIONS"):
        raise Refusal("invalid_input", "visibility must be PUBLIC or CONNECTIONS")
    return _prepare(binding, "linkedin.post", LINKEDIN_API + "/rest/posts",
                    headers=_linkedin_headers(), json_body={
                        "author": _linkedin_person(binding),
                        "commentary": _little(text),
                        "visibility": visibility,
                        "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [],
                                         "thirdPartyDistributionChannels": []},
                        "lifecycleState": "PUBLISHED",
                        "isReshareDisabledByAuthor": False,
                    })


def prepare_linkedin_comment(binding: AccountBinding, post_urn: str, text: str) -> PreparedRequest:
    if not isinstance(post_urn, str) or not _LINKEDIN_POST.fullmatch(post_urn):
        raise Refusal("invalid_input", "post_urn must look like urn:li:share:123, "
                      "urn:li:ugcPost:123 or urn:li:activity:123")
    text = _text(text, "linkedin")
    url = LINKEDIN_API + "/rest/socialActions/%s/comments" % urllib.parse.quote(post_urn, safe="")
    return _prepare(binding, "linkedin.comment", url, headers=_linkedin_headers(),
                    json_body={"actor": _linkedin_person(binding), "object": post_urn,
                               "message": {"text": text}})


def normalize_linkedin_created(prepared: PreparedRequest, status, headers, body) -> dict:
    """201 answers for linkedin.post and linkedin.comment: the id is in x-restli-id."""
    if prepared.operation not in ("linkedin.post", "linkedin.comment"):
        raise Refusal("invalid_input", "operation has no LinkedIn created-id answer")
    data, kept = _decode(prepared, status, headers, body)
    created = kept.get("x-restli-id") or str(data.get("id") or "")
    if not created:
        raise Refusal("uncertain", "LinkedIn accepted the request but returned no id; "
                      "reconcile before any new attempt", operation=prepared.operation)
    field = "post_id" if prepared.operation == "linkedin.post" else "comment_id"
    return _ok(**{field: created})


# -------------------------------------------------------------- Facebook Pages --

def _page_id(binding: object) -> str:
    return _graph_id(getattr(binding, "account_id", None), "Page id")


def prepare_facebook_pages(binding: AccountBinding) -> PreparedRequest:
    """Pages the bound Meta user manages. The request never asks for tokens."""
    user_id = _graph_id(getattr(binding, "account_id", None), "Meta user id")
    query = urllib.parse.urlencode({"fields": "id,name,category,tasks", "limit": str(MAX_COUNT)})
    return _prepare(binding, "facebook.pages", GRAPH_API + "/%s/accounts?%s" % (user_id, query))


def normalize_facebook_pages(prepared: PreparedRequest, status, headers, body) -> dict:
    data, _ = _decode(prepared, status, headers, body)
    return _ok(pages=_rows(data, ("id", "name", "category", "tasks"), MAX_COUNT))


def prepare_facebook_feed(binding: AccountBinding, count: int = 10) -> PreparedRequest:
    page_id = _page_id(binding)
    query = urllib.parse.urlencode({"fields": "id,message,created_time,permalink_url",
                                    "limit": str(_count(count))})
    return _prepare(binding, "facebook.feed", GRAPH_API + "/%s/feed?%s" % (page_id, query))


def normalize_facebook_feed(prepared: PreparedRequest, status, headers, body) -> dict:
    data, _ = _decode(prepared, status, headers, body)
    return _ok(posts=_rows(data, ("id", "message", "created_time", "permalink_url"), MAX_COUNT))


def prepare_facebook_comments(binding: AccountBinding, object_id: str,
                              count: int = 10) -> PreparedRequest:
    _page_id(binding)
    object_id = _graph_id(object_id, "object_id")
    query = urllib.parse.urlencode({"fields": "id,message,created_time", "limit": str(_count(count))})
    return _prepare(binding, "facebook.comments", GRAPH_API + "/%s/comments?%s" % (object_id, query))


def normalize_facebook_comments(prepared: PreparedRequest, status, headers, body) -> dict:
    data, _ = _decode(prepared, status, headers, body)
    return _ok(comments=_rows(data, ("id", "message", "created_time"), MAX_COUNT))


def prepare_facebook_post(binding: AccountBinding, message: str, link: str = "") -> PreparedRequest:
    page_id = _page_id(binding)
    form = {"message": _text(message, "facebook", "message")}
    if link:
        form["link"] = _https_url(link, "link")
    return _prepare(binding, "facebook.page_post", GRAPH_API + "/%s/feed" % page_id, form=form)


def prepare_facebook_comment(binding: AccountBinding, object_id: str, message: str) -> PreparedRequest:
    _page_id(binding)
    object_id = _graph_id(object_id, "object_id")
    return _prepare(binding, "facebook.comment", GRAPH_API + "/%s/comments" % object_id,
                    form={"message": _text(message, "facebook", "message")})


_CREATED_FIELD = {
    "facebook.page_post": "post_id",
    "facebook.comment": "comment_id",
    "instagram.reply": "reply_id",
    "instagram.container_create": "container_id",
    "instagram.media_publish": "media_id",
}


def normalize_graph_created(prepared: PreparedRequest, status, headers, body) -> dict:
    """Graph write answers: {"id": ...}. No id after a 2xx is not a success."""
    if prepared.operation not in _CREATED_FIELD:
        raise Refusal("invalid_input", "operation has no created-id answer")
    data, _ = _decode(prepared, status, headers, body)
    created = data.get("id")
    if not isinstance(created, str) or not _GRAPH_ID.fullmatch(created):
        raise Refusal("uncertain", "Meta accepted the request but returned no id; "
                      "reconcile before any new attempt", operation=prepared.operation)
    return _ok(**{_CREATED_FIELD[prepared.operation]: created})


# ------------------------------------------------------------------- Instagram --

_IG_NEXT_STEP = {
    "IN_PROGRESS": "wait",
    "FINISHED": "publish",
    "PUBLISHED": "already_published",
    "ERROR": "failed",
    "EXPIRED": "failed",
}


def prepare_instagram_account(binding: AccountBinding) -> PreparedRequest:
    page_id = _page_id(binding)
    query = urllib.parse.urlencode({"fields": "instagram_business_account"})
    return _prepare(binding, "instagram.account", GRAPH_API + "/%s?%s" % (page_id, query))


def normalize_instagram_account(prepared: PreparedRequest, status, headers, body) -> dict:
    data, _ = _decode(prepared, status, headers, body)
    account = data.get("instagram_business_account")
    ig_user = account.get("id") if isinstance(account, dict) else None
    if not isinstance(ig_user, str) or not _GRAPH_ID.fullmatch(ig_user):
        raise Refusal("missing_access", "this Page has no linked Instagram professional account")
    return _ok(instagram_user_id=ig_user)


def prepare_instagram_media(binding: AccountBinding, ig_user_id: str,
                            count: int = 10) -> PreparedRequest:
    _page_id(binding)
    ig_user_id = _graph_id(ig_user_id, "ig_user_id")
    query = urllib.parse.urlencode({"fields": "id,caption,media_type,permalink,timestamp",
                                    "limit": str(_count(count))})
    return _prepare(binding, "instagram.media", GRAPH_API + "/%s/media?%s" % (ig_user_id, query))


def normalize_instagram_media(prepared: PreparedRequest, status, headers, body) -> dict:
    data, _ = _decode(prepared, status, headers, body)
    return _ok(media=_rows(data, ("id", "caption", "media_type", "permalink", "timestamp"), MAX_COUNT))


def prepare_instagram_comments(binding: AccountBinding, media_id: str,
                               count: int = 10) -> PreparedRequest:
    _page_id(binding)
    media_id = _graph_id(media_id, "media_id")
    query = urllib.parse.urlencode({"fields": "id,text,username,timestamp", "limit": str(_count(count))})
    return _prepare(binding, "instagram.comments", GRAPH_API + "/%s/comments?%s" % (media_id, query))


def normalize_instagram_comments(prepared: PreparedRequest, status, headers, body) -> dict:
    data, _ = _decode(prepared, status, headers, body)
    return _ok(comments=_rows(data, ("id", "text", "username", "timestamp"), MAX_COUNT))


def prepare_instagram_reply(binding: AccountBinding, comment_id: str, message: str) -> PreparedRequest:
    _page_id(binding)
    comment_id = _graph_id(comment_id, "comment_id")
    return _prepare(binding, "instagram.reply", GRAPH_API + "/%s/replies" % comment_id,
                    form={"message": _text(message, "instagram", "message")})


def prepare_instagram_container(binding: AccountBinding, ig_user_id: str, image_url: str,
                                caption: str = "") -> PreparedRequest:
    _page_id(binding)
    ig_user_id = _graph_id(ig_user_id, "ig_user_id")
    form = {"image_url": _https_url(image_url, "image_url")}
    if caption:
        form["caption"] = _text(caption, "instagram", "caption")
    return _prepare(binding, "instagram.container_create", GRAPH_API + "/%s/media" % ig_user_id,
                    form=form)


def prepare_instagram_container_status(binding: AccountBinding, container_id: str) -> PreparedRequest:
    _page_id(binding)
    container_id = _graph_id(container_id, "container_id")
    query = urllib.parse.urlencode({"fields": "status_code"})
    return _prepare(binding, "instagram.container_status",
                    GRAPH_API + "/%s?%s" % (container_id, query))


def normalize_instagram_container_status(prepared: PreparedRequest, status, headers, body) -> dict:
    data, _ = _decode(prepared, status, headers, body)
    code = data.get("status_code")
    if code not in _IG_NEXT_STEP:
        raise Refusal("provider_error", "Instagram returned an unknown container status")
    return _ok(status_code=code, next_step=_IG_NEXT_STEP[code])


def prepare_instagram_media_publish(binding: AccountBinding, ig_user_id: str,
                                    container_id: str) -> PreparedRequest:
    _page_id(binding)
    ig_user_id = _graph_id(ig_user_id, "ig_user_id")
    container_id = _graph_id(container_id, "container_id")
    return _prepare(binding, "instagram.media_publish", GRAPH_API + "/%s/media_publish" % ig_user_id,
                    form={"creation_id": container_id})


# ------------------------------------------------------------ Work-root binding --

_VAULT_ENTRY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_WORK_INPUT_FIELDS = frozenset({"operation", "account_id", "vault_entry", "arguments"})

# Operations whose whole request one Work holds: preparer, required arguments,
# optional arguments, normalizer. instagram.media and image publishing need
# values from earlier admitted steps (linked account, container) that the
# runtime does not record per Work yet, so they are not listed.
WORK_OPERATIONS = {
    "linkedin.profile": (prepare_linkedin_profile, (), (), normalize_linkedin_profile),
    "linkedin.post": (prepare_linkedin_post, ("text",), ("visibility",), normalize_linkedin_created),
    "linkedin.comment": (prepare_linkedin_comment, ("post_urn", "text"), (), normalize_linkedin_created),
    "facebook.pages": (prepare_facebook_pages, (), (), normalize_facebook_pages),
    "facebook.feed": (prepare_facebook_feed, (), ("count",), normalize_facebook_feed),
    "facebook.comments": (prepare_facebook_comments, ("object_id",), ("count",), normalize_facebook_comments),
    "facebook.page_post": (prepare_facebook_post, ("message",), ("link",), normalize_graph_created),
    "facebook.comment": (prepare_facebook_comment, ("object_id", "message"), (), normalize_graph_created),
    "instagram.account": (prepare_instagram_account, (), (), normalize_instagram_account),
    "instagram.comments": (prepare_instagram_comments, ("media_id",), ("count",), normalize_instagram_comments),
    "instagram.reply": (prepare_instagram_reply, ("comment_id", "message"), (), normalize_graph_created),
}


def social_material_from_values(inputs: object) -> tuple[PreparedRequest, bytes]:
    """Rebuild one Work's exact request from its graph-held inputs.

    The same contract runs when the delegation is requested and again before
    the physical call. `raw` covers the whole Work input, including the vault
    entry name; its SHA-256 and length are the delegation input digest and bytes.
    """
    if type(inputs) is not dict or set(inputs) != _WORK_INPUT_FIELDS:
        raise Refusal("invalid_input", "social Work inputs need exactly operation, account_id, "
                      "vault_entry and arguments")
    operation = inputs["operation"]
    entry = WORK_OPERATIONS.get(operation) if type(operation) is str else None
    if entry is None:
        raise Refusal("invalid_input", "operation is not admitted from one Work")
    prepare, required, optional, _ = entry
    arguments = inputs["arguments"]
    if (type(arguments) is not dict or not set(required) <= set(arguments)
            or not set(arguments) <= set(required) | set(optional)):
        raise Refusal("invalid_input", "Work arguments do not match %s" % inputs["operation"])
    if type(inputs["vault_entry"]) is not str or not _VAULT_ENTRY.fullmatch(inputs["vault_entry"]):
        raise Refusal("missing_access", "the Work names no valid vault entry")
    binding = AccountBinding(OPERATIONS[inputs["operation"]][0], inputs["account_id"],
                             inputs["vault_entry"])
    prepared = verify_prepared(prepare(binding, **arguments))
    raw = json.dumps({"inputs": inputs, "request": prepared.input_digest}, separators=(",", ":"),
                     sort_keys=True, ensure_ascii=False).encode("utf-8")
    if len(raw) > MAX_INPUT_BYTES:
        raise Refusal("invalid_input", "Work input exceeds %d bytes" % MAX_INPUT_BYTES)
    return prepared, raw


def social_work_material(store, registry, work_root: str) -> tuple[PreparedRequest, bytes]:
    """Server side: read the Work's `inputs` interface and rebuild its request.

    Same resolver as project execution (existing_workshop_project_execution
    ._material): the governed Work interface target and its value graph. Root
    calls it only after _baboom_execution_work_context admits the Work.
    """
    from . import universal_application as app
    from .cell_value_graph import read_value_graph

    snapshot = store.snapshot()
    inputs = read_value_graph(snapshot, registry.value_graph_protocol,
                              app._governed_work_interface_target(snapshot, registry, work_root, "inputs"))
    material = social_material_from_values(inputs)
    if store.revision != snapshot.revision:
        raise Refusal("invalid_input", "the Work changed while its social request was prepared")
    return material


def normalize_work_answer(prepared: PreparedRequest, status, headers, body) -> dict:
    """Server side: normalize the host's provider answer for the Work's operation."""
    entry = WORK_OPERATIONS.get(verify_prepared(prepared).operation)
    if entry is None:
        raise Refusal("invalid_input", "operation is not admitted from one Work")
    return entry[3](prepared, status, headers, body)


# --------------------------------------------------- native owner tool adapter --

SOCIAL_PREPARE_ROUTE = "/api/universal/social-work-prepare"  # root-owned; not registered yet
SOCIAL_EXECUTE_ROUTE = "/api/universal/social-work-execute"  # root-owned; not registered yet
GRANT_ROUTE = "/api/universal/connector-delegation-grant"
SOCIAL_TOOL_NAMES = ("social.work_prepare", "social.work_execute")
_DIGEST = re.compile(r"[0-9a-f]{64}")
_PREPARED_FIELDS = frozenset({"work", "delegation", "operation", "input_digest", "review_text",
                              "expires_at"})
_OUTCOME_STATE = {"succeeded": "ok", "failed": "failed", "uncertain": "uncertain"}
MAX_WORK_RECORDS = 32  # Works one owner process holds; uncertain ones are never evicted


def _work_root(value: object) -> str:
    if (type(value) is not str or not value.startswith("assembly-instance:")
            or value != value.strip() or len(value.encode("utf-8")) > 512):
        raise Refusal("invalid_input", "work_root must be one exact Work root")
    return value


def _note(value: object) -> str:
    """Descriptive context for the existing approval screen. Never authority."""
    if value is None:
        return ""
    if not isinstance(value, str) or len(value) > 2000:
        raise Refusal("invalid_input", "note must be text of at most 2000 characters")
    return value


def _prepared_answer(answer: object, work_root: str) -> dict:
    if (type(answer) is not dict or not _PREPARED_FIELDS <= set(answer)
            or answer["work"] != work_root
            or type(answer["delegation"]) is not str or not answer["delegation"]
            or type(answer["operation"]) is not str or answer["operation"] not in WORK_OPERATIONS
            or type(answer["input_digest"]) is not str or not _DIGEST.fullmatch(answer["input_digest"])
            or type(answer["review_text"]) is not str or len(answer["review_text"]) > 16000
            or type(answer["expires_at"]) not in (int, float)):
        raise Refusal("runtime_error", "the runtime preparation answer is malformed")
    return {key: answer[key] for key in sorted(_PREPARED_FIELDS)}


def _settled_answer(settled: object, prepared: dict) -> dict:
    """Accept a settled execution only when its outcome and normalized result agree."""
    if (type(settled) is not dict or settled.get("work") != prepared["work"]
            or settled.get("delegation") != prepared["delegation"]
            or settled.get("input_digest") != prepared["input_digest"]
            or type(settled.get("outcome")) is not str or settled["outcome"] not in _OUTCOME_STATE
            or type(settled.get("result")) is not dict
            or (settled["outcome"] != "uncertain" and type(settled.get("receipt")) is not str)
            or len(json.dumps(settled["result"], default=str)) > MAX_RESPONSE_BYTES):
        raise Refusal("uncertain", "the execution answer is malformed; reconcile before any new attempt")
    outcome, result = settled["outcome"], settled["result"]
    if ((outcome == "succeeded" and (result.get("ok") is not True or result.get("state") != "ok"))
            or (outcome == "failed" and (result.get("ok") is not False
                                         or type(result.get("state")) is not str
                                         or result.get("state") in ("ok", "uncertain")))):
        raise Refusal("uncertain", "the execution outcome disagrees with its result; reconcile before "
                      "any new attempt")
    return {"ok": settled["outcome"] == "succeeded", "state": _OUTCOME_STATE[settled["outcome"]],
            "work": prepared["work"], "delegation": prepared["delegation"],
            "receipt": settled.get("receipt"), "result": settled["result"]}


class _SocialWorkAdapter:
    """Per-Work preparation and execution state in this owner process.

    A call reserves its Work atomically before any route call; a concurrent
    call for the same Work is refused. A known pre-dispatch failure releases
    the reservation, a possible dispatch leaves the Work uncertain, and an
    uncertain record is never evicted. This is process-local: it is not the
    runtime's atomic operation-attempt reservation across Works, delegations
    and restarts.
    """

    def __init__(self, control) -> None:
        self._control = control
        self._lock = threading.Lock()
        self._records: dict[str, dict] = {}

    def _reserve(self, work_root: str, allowed: tuple, state: str) -> dict | None:
        with self._lock:
            record = self._records.get(work_root)
            current = None if record is None else record["state"]
            if current == "uncertain":
                raise Refusal("uncertain", "an earlier execution of this Work needs reconciliation; "
                              "no new preparation or grant is requested")
            if current not in allowed:
                if current is None:
                    raise Refusal("not_ready", "prepare this Work and get founder approval first")
                raise Refusal("busy", "another call for this Work is in flight")
            if record is None and len(self._records) >= MAX_WORK_RECORDS:
                idle = next((root for root, held in self._records.items()
                             if held["state"] == "prepared"), None)
                if idle is None:
                    raise Refusal("busy", "this owner process already holds its maximum of active Works")
                self._records.pop(idle)
            self._records[work_root] = {"state": state,
                                        "prepared": None if record is None else record["prepared"]}
            return record

    def _settle(self, work_root: str, record: dict | None) -> None:
        with self._lock:
            if record is None:
                self._records.pop(work_root, None)
            else:
                self._records[work_root] = record

    def prepare(self, work_root: object, note: object) -> dict:
        try:
            work_root, note = _work_root(work_root), _note(note)
            settled = self._reserve(work_root, (None, "prepared"), "preparing")
            try:
                try:
                    with self._control.bound_client() as client:
                        answer = client.request("POST", SOCIAL_PREPARE_ROUTE,
                                                {"root": work_root, "note": note})
                except Exception as error:
                    raise Refusal("runtime_error", "the runtime refused or lost the preparation",
                                  error=type(error).__name__) from None
                prepared = _prepared_answer(answer, work_root)
                settled = {"state": "prepared", "prepared": prepared}
                return _ok(**prepared, next_step="founder_approval")
            finally:
                self._settle(work_root, settled)
        except Refusal as refusal:
            return refusal_answer(refusal)

    def execute(self, work_root: object) -> dict:
        try:
            work_root = _work_root(work_root)
            prepared = self._reserve(work_root, ("prepared",), "granting")["prepared"]
            try:
                with self._control.bound_client() as client:
                    grant = client.request("POST", GRANT_ROUTE, {"delegation": prepared["delegation"]})
                if (type(grant) is not dict or grant.get("delegation") != prepared["delegation"]
                        or type(grant.get("grant")) is not str or type(grant.get("capability")) is not str):
                    raise Refusal("not_granted", "the grant answer is malformed; this call sent no "
                                  "execution request. Prepare the Work again")
            except BaseException as error:
                # Known pre-dispatch outcome: this call never reached the execute route.
                self._settle(work_root, None)
                if isinstance(error, Exception) and not isinstance(error, Refusal):
                    raise Refusal("not_granted", "the grant request failed before this call sent an "
                                  "execution request. Prepare the Work again",
                                  error=type(error).__name__) from None
                raise
            self._settle(work_root, {"state": "executing", "prepared": prepared})
            settled = {"state": "uncertain", "prepared": prepared}
            try:
                try:
                    with self._control.bound_client() as client:
                        answer = client.request("POST", SOCIAL_EXECUTE_ROUTE,
                                                {"grant": grant["grant"], "capability": grant["capability"]})
                except Exception as error:
                    raise Refusal("uncertain", "the execution may have happened; reconcile before any new "
                                  "attempt", error=type(error).__name__) from None
                result = _settled_answer(answer, prepared)
                if result["state"] != "uncertain":
                    settled = None
                return result
            finally:
                self._settle(work_root, settled)
        except Refusal as refusal:
            return refusal_answer(refusal)


def register_social_tools(server, control) -> None:
    """Add the two Work-root social tools to the EXISTING native owner server.

    A tool takes only a Work root (and, to prepare, an optional note). The
    runtime reads operation, account, vault entry and payload from that Work's
    graph-held inputs (social_work_material); no caller supplies an effect
    argument and the argument schema forbids extra fields. The founder
    approves through the existing consent gesture between the two calls.
    The social prepare and execute routes are root-owned and not registered.
    """
    adapter = _SocialWorkAdapter(control)

    @server.tool(name="social.work_prepare")
    def work_prepare(work_root: str, note: str = "") -> dict:
        """Prepare the social request held by this exact Work for founder approval. Posts nothing."""
        return adapter.prepare(work_root, note)

    @server.tool(name="social.work_execute")
    def work_execute(work_root: str) -> dict:
        """Run this Work's approved social request once. Never re-sent; an uncertain run needs reconciliation."""
        return adapter.execute(work_root)

    manager = getattr(server, "_tool_manager", None)
    if manager is not None:
        for tool in manager.list_tools():
            if tool.name in SOCIAL_TOOL_NAMES:
                model = tool.fn_metadata.arg_model
                model.model_config.update(extra="forbid", strict=True)
                model.model_rebuild(force=True)
                tool.parameters = model.model_json_schema(by_alias=True)
