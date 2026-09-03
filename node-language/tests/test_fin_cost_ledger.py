"""FIN-07 — a committed project cost ledger must exist.

The gap (FIN-07): ArchHub had no single artifact listing its subscriptions /
renewals / balances. `Financial_Plan.xlsx` is the founder's PERSONAL budget,
not the project's burn, so every audit had to reconstruct spend from Gmail +
live probes. The fix is a committed `docs/COSTS.md` ledger that lists each
service with its purpose, amount, cadence, next-renewal and balance, and flags
at-risk items.

The gate (per the leaf): a committed `docs/COSTS.md` lists each
service/purpose/amount/cadence/next-renewal/balance with at-risk items flagged.

This test goes RED on origin/main (the file does not exist) and GREEN on the
branch. It checks the ledger is real — not an empty stub — by asserting the
required columns are present, that the load-bearing paid services actually have
rows, and that an at-risk flag exists.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
LEDGER = REPO / "docs" / "COSTS.md"


def _read() -> str:
    assert LEDGER.is_file(), (
        "docs/COSTS.md is missing — FIN-07 requires a committed cost ledger "
        "(this is what does not exist on origin/main)."
    )
    return LEDGER.read_text(encoding="utf-8")


def test_cost_ledger_exists_and_nonempty():
    text = _read()
    assert len(text) > 800, "the ledger must be a real ledger, not a stub"


def test_ledger_has_all_required_columns():
    """The leaf names the columns explicitly: service / purpose / amount /
    cadence / next-renewal / balance. All must be present as a table header."""
    text = _read().lower()
    # Locate the markdown table header row.
    header = next((ln for ln in text.splitlines()
                   if ln.strip().startswith("|") and "purpose" in ln), "")
    assert header, "no table header row found in docs/COSTS.md"
    for col in ("service", "purpose", "amount", "cadence",
                "renewal", "balance"):
        assert col in header, f"required column '{col}' missing from the ledger header"


def test_ledger_lists_the_load_bearing_paid_services():
    """A real ledger names the actual services ArchHub pays for — not a
    placeholder. These are the load-bearing ones from the deep dive + go-live
    record (Fly = hosting, Namecheap = domain/email, the prepaid LLM wallets,
    DashScope = image-gen, Resend = email, Stripe = payments)."""
    text = _read().lower()
    for service in ("fly", "namecheap", "anthropic", "openai",
                    "dashscope", "resend", "stripe"):
        assert service in text, (
            f"the cost ledger does not mention '{service}' — it must list the "
            f"real services, reconstructed from the burn, not a template")


def test_ledger_flags_at_risk_items():
    """The gate requires at-risk items to be FLAGGED. There must be an at-risk
    marker AND the genuinely-at-risk facts (the dead DashScope key, the prepaid
    wallets that must stay funded) must be called out."""
    text = _read()
    low = text.lower()
    assert "at-risk" in low or "at risk" in low, \
        "the ledger must flag at-risk items"
    # The specific live risks the deep dive surfaced must be present.
    assert "prepaid" in low, "prepaid-wallet risk must be flagged"
    assert "dashscope" in low and ("dead" in low or "401" in low
                                   or "invalid" in low), \
        "the dead DashScope key (the 🔴 item) must be flagged"


def test_ledger_rows_carry_per_service_fields():
    """Each service row must carry its own amount + cadence + renewal/balance
    cells — i.e. the table has data rows with multiple filled columns, not just
    a header. Assert several rows have the minimum cell count of the 7-column
    table."""
    text = _read()
    data_rows = [ln for ln in text.splitlines()
                 if ln.strip().startswith("|")
                 and "---" not in ln
                 and "purpose" not in ln.lower()]
    # A 7-column markdown row has >=8 pipe characters.
    rich_rows = [ln for ln in data_rows if ln.count("|") >= 7]
    assert len(rich_rows) >= 8, (
        f"expected >=8 fully-populated service rows, found {len(rich_rows)} — "
        f"the ledger must carry per-service amount/cadence/renewal/balance")


def test_ledger_points_at_the_real_dashscope_balance_probe():
    """FIN-07 ties to FIN-05: the ledger must tell the reader how to CAPTURE the
    DashScope balance via the real probe, so the balance becomes a receipt, not
    a guess."""
    text = _read()
    assert "rotate_dashscope.py --balance" in text or \
        "dashscope.balance" in text, \
        "the ledger must reference the real dashscope balance probe (FIN-05)"
