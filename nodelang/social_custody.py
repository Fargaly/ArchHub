"""Social credential custody: one protected record binds a token to its provider account.

The only custody is this runtime's DPAPI-protected secrets.dat, read through
model_router.protected_credential_entry. A social entry's value is one JSON
record {"format", "provider", "account_id", "token"} to be written by explicit
enrollment. Operator-declared identity is not provider-verified identity.
The resolver checks provider and account_id against the same record
whose token it returns, so replacement between the verifier and the resolver can
never dispatch another account's credential. No environment variable, keyring,
alias or legacy fallback is consulted, and nothing resolved is written anywhere.
"""
from __future__ import annotations

import hmac
import json

from .social_connectors import _VAULT_ENTRY
from .universal_cell import InvalidCell

SOCIAL_CREDENTIAL_FORMAT = "archhub-social-credential-1"
_RECORD_FIELDS = frozenset({"format", "provider", "account_id", "token"})
_PROVIDERS = frozenset({"linkedin", "meta"})


def require_social_vault_reference(snapshot, vault_entry):
    """Admit only the graph reference served by this installed custody adapter."""
    from .cell_brain_secrets import read_secret_reference

    if (type(vault_entry) is not str or not vault_entry.startswith("social-")
            or not _VAULT_ENTRY.fullmatch(vault_entry)):
        raise InvalidCell("social vault entry is invalid")
    entry = read_secret_reference(snapshot, vault_entry)
    if (entry.name != vault_entry or entry.custody != "os-keystore"
            or entry.reference != "dpapi://ArchHub/" + vault_entry):
        raise InvalidCell("social vault reference is not served by application custody")
    return entry


def _unique(pairs):
    record = {}
    for key, value in pairs:
        if key in record:
            raise InvalidCell("social credential record repeats a field")
        record[key] = value
    return record


def _bound_token(provider, account_id, vault_entry):
    """One protected read: the binding check and the token come from the same record."""
    from .model_router import protected_credential_entry

    if (type(vault_entry) is not str or not vault_entry.startswith("social-")
            or not _VAULT_ENTRY.fullmatch(vault_entry)
            or type(provider) is not str or provider not in _PROVIDERS
            or type(account_id) is not str or not 1 <= len(account_id) <= 256):
        raise InvalidCell("social credential binding request is invalid")
    raw = protected_credential_entry(vault_entry)
    if type(raw) is not str or len(raw) > 32768:
        raise InvalidCell("social credential record is invalid or too large")
    try:
        record = json.loads(raw, object_pairs_hook=_unique)
    except InvalidCell:
        raise
    except Exception:
        raise InvalidCell("social credential record is unreadable") from None
    token = record.get("token") if type(record) is dict else None
    if (type(record) is not dict or set(record) != _RECORD_FIELDS
            or record["format"] != SOCIAL_CREDENTIAL_FORMAT
            or type(record["provider"]) is not str or type(record["account_id"]) is not str
            or type(token) is not str or not 1 <= len(token) <= 16384
            or any(ord(char) < 33 or ord(char) > 126 for char in token)):
        raise InvalidCell("social credential record is not a bound account record")
    if not (hmac.compare_digest(record["provider"].encode("utf-8"), provider.encode("utf-8"))
            and hmac.compare_digest(record["account_id"].encode("utf-8"), account_id.encode("utf-8"))):
        raise InvalidCell("social credential is bound to another provider account")
    return token


def social_credential(*, provider, account_id, vault_entry):
    """SocialHttpHost credential_resolver: binding check and token from one record read."""
    return _bound_token(provider, account_id, vault_entry)


def social_account_binding_verifier(*, provider, account_id, vault_entry):
    """Early admission check against the same custody; never returns the credential."""
    try:
        _bound_token(provider, account_id, vault_entry)
    except Exception:
        return False
    return True


def enroll_social_account(owner, body, *, require_admission):
    """Caller holds owner and live authorization locks; no secret enters graph.

    Custody replacement and graph commit are different durable boundaries.
    Report a partial outcome if the protected save succeeds but its reference
    cannot be confirmed; never erase that saved credential to simulate rollback.
    """
    from .cell_brain_secrets import admit_secret
    from .model_router import save_social_credential

    store = owner.universal_store
    name = body.get("vault_entry") if type(body) is dict else None
    snapshot = store.snapshot()
    # Refuse an existing differently routed entry before changing custody.
    if type(name) is str and "app:brain:secret-vault:entry:" + name in snapshot.cells:
        require_social_vault_reference(snapshot, name)
    with store.stable_snapshot():
        saved = save_social_credential(body, before_replace=require_admission)
    try:
        require_admission()
        if "app:brain:secret-vault:entry:" + name not in store.snapshot().cells:
            admit_secret(store, name=name, reference="dpapi://ArchHub/" + name,
                         custody="os-keystore")
        require_social_vault_reference(store.snapshot(), name)
    except Exception:
        return {"ok": False, "state": "credential_saved_reference_unconfirmed",
                "error_code": "social_reference_unconfirmed",
                "error": "Credential saved locally, but its graph reference could not be confirmed. Review before retrying.",
                "vault_entry": saved["vault_entry"], "account_binding": "operator-declared"}
    return {**saved, "vault_reference": "dpapi://ArchHub/" + name,
            "revision": store.revision}


def remove_local_social_account(owner, body, *, require_admission):
    """Remove custody bytes while preserving workflow references and history.

    An orphaned enrollment can be removed even if graph admission never finished.
    A present graph reference must still point to this exact custody. This does
    not revoke a provider token or claim that an already dispatched call stopped.
    Caller holds the owner mutation lock and live authorization context.
    """
    from .model_router import revoke_social_credential

    store = owner.universal_store
    name = body.get("vault_entry") if type(body) is dict else None
    with store.stable_snapshot() as snapshot:
        require_admission()
        present = (type(name) is str
                   and "app:brain:secret-vault:entry:" + name in snapshot.cells)
        if present:
            require_social_vault_reference(snapshot, name)
        result = revoke_social_credential(body, before_replace=require_admission)
        return {**result, "graph_reference_retained": present,
                "revision": snapshot.revision}
