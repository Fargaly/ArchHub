"""One public account projection over the existing cloud broker and custody.

No OAuth protocol or credential store lives here. Settings and the Connections
node use the same browser routes, and only provider-confirmed callbacks enroll.
"""
from __future__ import annotations

from . import cloud_social_oauth as broker
from . import model_router, social_custody

NETWORKS = {
    "instagram": "Instagram", "facebook": "Facebook", "linkedin": "LinkedIn",
    "whatsapp": "WhatsApp Business", "x": "X", "tiktok": "TikTok",
}


def _provider(provider):
    if type(provider) is not str or provider not in NETWORKS:
        raise ValueError("Choose a supported social network")
    return provider


def _matches(provider, account):
    if provider in ("instagram", "facebook"):
        prefix = "social-meta-ig-" if provider == "instagram" else "social-meta-page-"
        return account.get("provider") == "meta" and account.get("vault_entry", "").startswith(prefix)
    return account.get("provider") == provider


def connection(provider, *, accounts=None, attempt=None):
    provider = _provider(provider)
    row = {"provider": provider, "name": NETWORKS[provider], "state": "not_connected",
           "display_name": "", "blocker": ""}
    if accounts is None:
        accounts = model_router.list_social_credentials()["items"]
    held = [account for account in accounts if _matches(provider, account)]
    verified = [account for account in held if account.get("account_binding") == "provider-verified"]
    if verified:
        account = verified[0]
        row.update(state="connected", account_id=account["account_id"],
                   display_name=account.get("display_name") or account["account_id"],
                   custody_provider=account["provider"], vault_entry=account["vault_entry"])
    elif held:
        row.update(state="blocked", blocker="Reconnect through provider sign-in to verify this account")
    current = attempt if attempt is not None else broker.current_status(provider)
    phase = current.get("phase", "idle")
    if phase == "select_account":
        row.update(state="choosing", accounts=current.get("accounts", []))
    elif phase == "ready":
        row.update(state="ready")
    elif phase in ("starting", "waiting", "opening", "exchanging"):
        row.update(state="connecting")
    elif phase == "failed":
        row.update(state="blocked", blocker=current.get("error") or "Provider sign-in failed")
    config = broker.status(provider)
    row["can_connect"] = config.get("state") in ("saved", "configured")
    blocker = config.get("blocker")
    if not blocker and config.get("state") not in ("saved", "configured"):
        blocker = "ArchHub cloud connection status unavailable"
    if blocker:
        row.update(state="blocked", blocker=blocker)
    row["review_state"] = config.get("review_state", "")
    publish_blocker = config.get("publish_blocker")
    row["publish_blocker"] = publish_blocker or ""
    if publish_blocker and not blocker:
        row["blocker"] = publish_blocker
        if row["state"] == "not_connected":
            row["state"] = "blocked"
    return row


def rows():
    accounts = model_router.list_social_credentials()["items"]
    return [connection(provider, accounts=accounts) for provider in NETWORKS]


def start(provider):
    provider = _provider(provider)
    # The broker refuses missing configuration before opening any browser.
    return connection(provider, attempt=broker.start(provider))


def cancel(provider):
    provider = _provider(provider)
    attempt = broker._CURRENT.get(provider)
    if attempt is not None:
        attempt.cancel()
    return connection(provider)


def finish(owner, body, *, require_admission):
    if type(body) is not dict or not {"provider"} <= set(body) <= {"provider", "account_id"}:
        raise ValueError("Provider sign-in finish accepts only a discovered account")
    provider = _provider(body["provider"])
    require_admission()
    current = broker.current_status(provider)
    if "account_id" in body:
        choices = {item["id"]: item for item in current.get("accounts", [])}
        if body["account_id"] not in choices:
            raise ValueError("Choose an account returned by the provider")
        display = choices[body["account_id"]].get("name", "")
        account_id, credential = broker.take_verified_account(provider, body["account_id"])
    else:
        display = current.get("name") or current.get("username") or ""
        account_id, credential = broker.take_verified(provider)
    custody_provider = "meta" if provider in ("instagram", "facebook") else provider
    prefix = {"instagram": "social-meta-ig-", "facebook": "social-meta-page-"}.get(provider, "social-" + provider + "-")
    vault_entry = prefix + account_id.rsplit(":", 1)[-1]
    saved = social_custody.enroll_social_account(owner, {
        "provider": custody_provider, "account_id": account_id, "vault_entry": vault_entry,
        "token": credential, "display_name": str(display or account_id)[:256]},
        require_admission=require_admission, verified=True)
    credential = None
    if saved.get("ok") is not True:
        return {"provider": provider, "name": NETWORKS[provider], "state": "blocked",
                "blocker": saved.get("error", "Saved credential reference needs confirmation")}
    return connection(provider)
