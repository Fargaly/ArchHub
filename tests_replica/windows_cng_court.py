"""Strict cleanup helper for isolated Windows CNG court keys only."""
from __future__ import annotations

import ctypes

import nodelang.windows_cng_signing_provider as cng


def delete_court_key(key_name: str) -> None:
    if not str(key_name).startswith("ArchHub.Court."):
        raise ValueError("refusing to delete a non-court Windows CNG key")
    api = cng._api()
    provider = api.open_provider(cng._PROVIDERS[cng.SOFTWARE_PROVIDER_ID][0])
    key = None
    try:
        key = api.handle_type()
        status = api.library.NCryptOpenKey(
            provider,
            ctypes.byref(key),
            str(key_name),
            0,
            cng._NCRYPT_SILENT_FLAG,
        )
        if api.code(status) == cng._NTE_BAD_KEYSET:
            return
        api.require("open isolated court key for cleanup", status)
        api.require(
            "delete isolated court key",
            api.library.NCryptDeleteKey(key, 0),
        )
        key = None
    finally:
        if key is not None:
            api.free(key)
        api.free(provider)


__all__ = ["delete_court_key"]
