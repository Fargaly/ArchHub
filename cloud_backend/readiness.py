"""Read-only capability evidence for the node-native resource graph."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import config
import db


def _status(ok: bool, reason: str, **public: Any) -> dict[str, Any]:
    return {"ok": bool(ok), "reason": reason, **public}


def _database_status() -> dict[str, Any]:
    try:
        with db.connect() as con:
            row = con.execute("SELECT 1").fetchone()
        ok = bool(row and row[0] == 1)
        return _status(ok, "query_ok" if ok else "query_invalid", engine="sqlite")
    except Exception:
        return _status(False, "query_failed", engine="sqlite")


def _storage_status() -> dict[str, Any]:
    try:
        data_dir = Path(config.DATA_DIR).expanduser().resolve()
        database = Path(config.DATABASE_URL).expanduser()
        if not database.is_absolute():
            database = (Path.cwd() / database).resolve()
        replicas = Path(config.REPLICAS_ROOT).expanduser()
        if not replicas.is_absolute():
            replicas = (Path.cwd() / replicas).resolve()
        available = data_dir.is_dir()
        database_parent = database.parent.is_dir()
        replicas_parent = replicas.parent.is_dir()
        ok = available and database_parent and replicas_parent
        return _status(
            ok, "storage_available" if ok else "storage_unavailable",
            persistence="fly_volume" if config._on_fly() else "local_filesystem",
            database_parent_available=database_parent,
            replica_parent_available=replicas_parent,
        )
    except Exception:
        return _status(False, "storage_check_failed", persistence="unknown")


def _billing_status() -> dict[str, Any]:
    provider = config.BILLING_PROVIDER
    pricing = config.public_pricing()
    products = all(bool(tier.get("price_id_configured"))
                   for tier in pricing.get("tiers", []))
    if provider == "polar":
        credentials = bool(config.POLAR_ACCESS_TOKEN and config.POLAR_WEBHOOK_SECRET)
    else:
        credentials = bool(config.STRIPE_SECRET_KEY and config.STRIPE_WEBHOOK_SECRET)
    ok = products and credentials
    return _status(ok, "configured" if ok else "configuration_incomplete",
                   provider=provider, products_configured=products,
                   credentials_configured=credentials)


def _email_status() -> dict[str, Any]:
    configured = bool(config.RESEND_API_KEY and config.FROM_EMAIL)
    return _status(configured, "configured" if configured else "configuration_incomplete",
                   provider="resend", sender_configured=bool(config.FROM_EMAIL))


def _website_status() -> dict[str, Any]:
    from urllib.parse import urlsplit
    configured = any(
        urlsplit(origin).scheme == "https" and urlsplit(origin).netloc == "archhub.io"
        for origin in config.WEBSITE_RETURN_ORIGINS
    )
    return _status(configured, "configured" if configured else "configuration_incomplete",
                   origin="https://archhub.io" if configured else None)


def capability_report() -> dict[str, Any]:
    """Return bounded non-sensitive evidence; never raises and never mutates."""
    capabilities = {
        "database": _database_status(),
        "persistent_storage": _storage_status(),
        "billing": _billing_status(),
        "email": _email_status(),
        "website_publication": _website_status(),
    }
    return {
        "format": "archhub-capability-readiness-v1",
        "ready": all(item["ok"] for item in capabilities.values()),
        "capabilities": capabilities,
    }


__all__ = ["capability_report"]
