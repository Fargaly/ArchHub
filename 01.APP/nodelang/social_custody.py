"""Social credential custody: one protected record binds a token to its provider account.

The only custody is this runtime's DPAPI-protected secrets.dat, read through
model_router.protected_credential_entry. A social entry's value is one JSON
record {"format", "provider", "account_id", "token"} to be written by explicit
enrollment (format 1, operator-declared), or the same plus "account_binding"
(format 2) when the provider itself named the account at sign-in.
Operator-declared identity is not provider-verified identity, and
social_account_binding reports which one a record is, from the record itself.
The resolver checks provider and account_id against the same record
whose token it returns, so replacement between the verifier and the resolver can
never dispatch another account's credential. No environment variable, credential
alias or unprotected legacy fallback is consulted, and nothing resolved is written anywhere.
"""
from __future__ import annotations

import hmac
import json

from .social_connectors import _VAULT_ENTRY

SOCIAL_CREDENTIAL_FORMAT = "archhub-social-credential-1"
SOCIAL_VERIFIED_FORMAT = "archhub-social-credential-2"
_RECORD_FIELDS = frozenset({"format", "provider", "account_id", "token"})
_VERIFIED_FIELDS = _RECORD_FIELDS | {"account_binding"}
_BINDINGS = frozenset({"provider-verified", "operator-declared"})
_PROVIDERS = frozenset({"linkedin", "meta", "whatsapp", "x", "tiktok"})




def _unique(pairs):
    record = {}
    for key, value in pairs:
        if key in record:
            raise ValueError("social credential record repeats a field")
        record[key] = value
    return record


def _bound_token(provider, account_id, vault_entry):
    """One protected read: the binding check and the token come from the same record."""
    return _bound_record(provider, account_id, vault_entry)[0]


def _bound_record(provider, account_id, vault_entry):
    """(token, account_binding) of the record bound to this provider account."""
    from .model_router import protected_credential_entry

    if (type(vault_entry) is not str or not vault_entry.startswith("social-")
            or not _VAULT_ENTRY.fullmatch(vault_entry)
            or type(provider) is not str or provider not in _PROVIDERS
            or type(account_id) is not str or not 1 <= len(account_id) <= 256):
        raise ValueError("social credential binding request is invalid")
    raw = protected_credential_entry(vault_entry)
    if type(raw) is not str or len(raw) > 32768:
        raise ValueError("social credential record is invalid or too large")
    try:
        record = json.loads(raw, object_pairs_hook=_unique)
    except ValueError:
        raise
    except Exception:
        raise ValueError("social credential record is unreadable") from None
    token = record.get("token") if type(record) is dict else None
    fields = set(record) if type(record) is dict else set()
    if (type(record) is not dict
            or not ((fields == _RECORD_FIELDS and record["format"] == SOCIAL_CREDENTIAL_FORMAT)
                    or (fields in (_VERIFIED_FIELDS, _VERIFIED_FIELDS | {"display_name"})
                        and record["format"] == SOCIAL_VERIFIED_FORMAT
                        and record["account_binding"] in _BINDINGS
                        and ("display_name" not in record or
                             (type(record["display_name"]) is str and 1 <= len(record["display_name"]) <= 256
                              and not any(ord(c) < 32 for c in record["display_name"])))))
            or type(record["provider"]) is not str or type(record["account_id"]) is not str
            or type(token) is not str or not 1 <= len(token) <= 16384
            or any(ord(char) < 33 or ord(char) > 126 for char in token)):
        raise ValueError("social credential record is not a bound account record")
    if not (hmac.compare_digest(record["provider"].encode("utf-8"), provider.encode("utf-8"))
            and hmac.compare_digest(record["account_id"].encode("utf-8"), account_id.encode("utf-8"))):
        raise ValueError("social credential is bound to another provider account")
    return token, record.get("account_binding", "operator-declared")


def social_credential(*, provider, account_id, vault_entry):
    """SocialHttpHost credential_resolver: binding check and token from one record read."""
    return _bound_token(provider, account_id, vault_entry)


def social_account_binding(*, provider, account_id, vault_entry):
    """"provider-verified" or "operator-declared", read from the bound record; never the token."""
    return _bound_record(provider, account_id, vault_entry)[1]


def social_account_binding_verifier(*, provider, account_id, vault_entry):
    """Early admission check against the same custody; never returns the credential."""
    try:
        _bound_token(provider, account_id, vault_entry)
    except Exception:
        return False
    return True


def enroll_social_account(owner, body, *, require_admission, verified=False):
    from .model_router import save_social_credential
    return save_social_credential(body, before_replace=require_admission, verified=verified)


def remove_local_social_account(owner, body, *, require_admission):
    from .model_router import revoke_social_credential
    return revoke_social_credential(body, before_replace=require_admission)
