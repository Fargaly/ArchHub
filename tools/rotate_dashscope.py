"""Rotate the DashScope API key — the founder-only credential step, automated
down to a single paste.

WHY: the DashScope key was de-inlined from .claude.json to an op:// reference
(resolved at MCP launch by archhub_mcp_server._resolve_secret_env via
personal_brain.secret_resolver: op-CLI -> Windows Credential Manager / keyring
-> OP_<VAULT>_<ITEM>_<FIELD> env). With the op CLI absent on this machine, the
resolver reads Windows Credential Manager (WinVaultKeyring) at
service "archhub/dashscope", field "api_key". Rotation therefore means: (1) the
FOUNDER regenerates the key in the Alibaba DashScope console (a login + console
action only they can do), then (2) this script stores the NEW value into that
same Credential Manager slot so the next MCP launch resolves it — and reminds
you to revoke the OLD (leaked) key in the console.

SECURITY: this script NEVER prints the key, and the human pastes it via a
no-echo getpass prompt — Claude never sees or handles the value. It only writes
to the local OS credential store the resolver already reads. Idempotent + safe
to re-run.

USAGE (founder, after regenerating in the console):
    python tools/rotate_dashscope.py            # paste the new key at the prompt
    python tools/rotate_dashscope.py --verify   # just check what resolves now (no write)
    python tools/rotate_dashscope.py --balance  # print the live account balance (no write)

The op:// reference (op://archhub/dashscope/api_key) and all code stay unchanged;
only the stored VALUE rotates.

BALANCE (FIN-05): DashScope's sk- key reads NO billing data — spend lives in
Alibaba's BSS OpenAPI (QueryAccountBalance), which needs a RAM AccessKey pair.
``--balance`` calls the real ``dashscope.balance`` connector op: it prints the
live AvailableAmount + Currency when the AccessKey resolves (op://archhub/aliyun/
access_key_id + access_key_secret), or the precise reason it cannot — so the
DashScope balance becomes a captured figure, never a guess. To store the
AccessKey pair into the same Credential Manager the resolver reads:
    python -c "import keyring;keyring.set_password('archhub/aliyun','access_key_id','<AK_ID>')"
    python -c "import keyring;keyring.set_password('archhub/aliyun','access_key_secret','<AK_SECRET>')"
(paste via a no-echo prompt in practice; never on the argv of a logged shell).
"""
from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

# The canonical reference the app + MCP resolve. Keyring maps it to
# service="<vault>/<item>" field="<field>" — see secret_resolver._try_keyring.
OP_REF = "op://archhub/dashscope/api_key"
KEYRING_SERVICE = "archhub/dashscope"   # "<vault>/<item>"
KEYRING_FIELD = "api_key"               # "<field>"

# Make personal_brain.secret_resolver importable so --verify exercises the REAL
# resolution path the MCP uses (not a reimplementation).
_BRAIN_SRC = Path(__file__).resolve().parent.parent / "personal-brain-mcp" / "src"
if _BRAIN_SRC.is_dir() and str(_BRAIN_SRC) not in sys.path:
    sys.path.insert(0, str(_BRAIN_SRC))


def _fingerprint(value: str) -> str:
    """A non-revealing fingerprint: first 3 chars + length. Never the value."""
    if not value:
        return "<empty>"
    return f"{value[:3]}…(len {len(value)})"


def _resolve_now() -> str | None:
    """Resolve via the REAL resolver the MCP uses (op CLI -> keyring -> env)."""
    try:
        from personal_brain.secret_resolver import resolve_secret
        return resolve_secret(OP_REF)
    except Exception as ex:  # resolver not importable in this env
        print(f"  (secret_resolver unavailable: {type(ex).__name__}: {ex})")
        # Fall back to a direct keyring read so --verify still works.
        try:
            import keyring
            return keyring.get_password(KEYRING_SERVICE, KEYRING_FIELD)
        except Exception:
            return None


def _verify() -> int:
    cur = _resolve_now()
    if cur:
        print(f"resolves OK: {OP_REF} -> {_fingerprint(cur)} "
              f"(via op-CLI / Credential Manager / env, resolver order)")
        return 0
    print(f"NOTHING resolves for {OP_REF} — the MCP would have no DashScope key. "
          f"Run this script without --verify to store one.")
    return 1


def _balance() -> int:
    """Print the live DashScope/Model-Studio account balance via the REAL
    connector op (Alibaba BSS QueryAccountBalance). Captures the figure the
    sk- key cannot read; on missing AccessKey it prints the precise reason —
    never a fabricated number. The value itself is shown (the founder needs
    the receipt); secrets are never printed."""
    # Make the connector importable (it lives under app/connectors).
    app_dir = Path(__file__).resolve().parent.parent / "app"
    if app_dir.is_dir() and str(app_dir) not in sys.path:
        sys.path.insert(0, str(app_dir))
    try:
        from connectors.dashscope_connector import _balance as balance_op
    except Exception as ex:
        print(f"could not load the dashscope connector: "
              f"{type(ex).__name__}: {ex}", file=sys.stderr)
        return 2
    res = balance_op()
    if res.ok:
        v = res.value or {}
        print(f"DashScope account balance: {v.get('available')} "
              f"{v.get('currency')}")
        if v.get("credit") is not None:
            print(f"  credit line: {v.get('credit')} {v.get('currency')}")
        print(f"  (via Alibaba BSS QueryAccountBalance @ "
              f"{v.get('billing_base')}, request {v.get('request_id')})")
        return 0
    print(f"balance unavailable: {res.error}")
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Rotate the DashScope API key value.")
    ap.add_argument("--verify", action="store_true",
                    help="only show what currently resolves (no write)")
    ap.add_argument("--balance", action="store_true",
                    help="print the live account balance via the real "
                         "dashscope.balance op (no write)")
    args = ap.parse_args()

    if args.balance:
        return _balance()
    if args.verify:
        return _verify()

    try:
        import keyring
    except Exception:
        print("ERROR: the `keyring` package is not importable, so the new key "
              "cannot be stored in Windows Credential Manager. Install it "
              "(`pip install keyring`) or store the value manually.",
              file=sys.stderr)
        return 2

    print("Rotate DashScope key — steps:")
    print("  1. In the Alibaba DashScope console, CREATE a new API key.")
    print("  2. Paste it below (input is hidden — it is NOT echoed or logged).")
    print(f"  3. This stores it at Credential Manager '{KEYRING_SERVICE}' / "
          f"'{KEYRING_FIELD}' — the slot {OP_REF} resolves to.")
    print("  4. After verifying, REVOKE the old key in the console.\n")

    old = _resolve_now()
    if old:
        print(f"current stored value: {_fingerprint(old)}")

    new_key = getpass.getpass("Paste the NEW DashScope API key (hidden): ").strip()
    if not new_key:
        print("No key entered — aborted, nothing changed.")
        return 1
    if len(new_key) < 20:
        print(f"That looks too short ({len(new_key)} chars) for a DashScope key "
              f"— aborted to avoid storing a typo. Re-run and paste the full key.")
        return 1
    confirm = getpass.getpass("Paste it again to confirm (hidden): ").strip()
    if confirm != new_key:
        print("The two entries did not match — aborted, nothing changed.")
        return 1

    keyring.set_password(KEYRING_SERVICE, KEYRING_FIELD, new_key)

    # Verify it round-trips through the REAL resolver.
    got = _resolve_now()
    if got == new_key:
        print(f"\nStored + verified: {OP_REF} -> {_fingerprint(got)}.")
        print("The new key takes effect on the NEXT archhub MCP launch "
              "(restart the MCP / the app to pick it up).")
        print("DON'T FORGET: revoke the OLD key in the DashScope console so the "
              "leaked value is dead.")
        return 0
    print("\nStored, but the resolver did NOT read it back (it may be using the "
          "op CLI or an OP_* env var ahead of Credential Manager). Check "
          "`python tools/rotate_dashscope.py --verify` and your resolver order.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
