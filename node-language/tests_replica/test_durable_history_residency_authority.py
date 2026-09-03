"""Court for the bounded-memory durable Cell history authority contract."""
from pathlib import Path


ROOT = Path(__file__).parents[1]
AUTHORITY = ROOT / "DURABLE-HISTORY-RESIDENCY-AUTHORITY.md"


def test_history_residency_contract_answers_the_required_questions():
    text = AUTHORITY.read_text(encoding="ascii")

    for section in (
        "## 1. What",
        "## 2. Why",
        "## 3. How",
        "## 4. Who",
        "## 5. When",
        "## 6. Where",
        "## 7. Evidence and courts",
        "## 8. Research basis",
        "## 9. Non-goals",
        "## 10. Release condition",
    ):
        assert section in text
    for required_source in (
        "https://www.sqlite.org/lang_transaction.html",
        "https://www.sqlite.org/queryplanner.html",
        "https://www.sqlite.org/lang_createindex.html",
        "https://www.postgresql.org/docs/current/transaction-iso.html",
        "https://www.postgresql.org/docs/current/sql-declare.html",
    ):
        assert required_source in text


def test_history_residency_contract_preserves_one_append_only_authority():
    text = AUTHORITY.read_text(encoding="ascii")

    for required_law in (
        "No second graph, replay database, semantic cache, copied control plane",
        "The repair changes physical residency only.",
        "Built-in SQLite, PostgreSQL, and witnessed journals must not use",
        "Startup may perform O(history) database reads.",
        "No agent may weaken these boundaries",
        "prune, compact, rewrite, or expire accepted Cell history",
        "change the four-field Cell",
    ):
        assert required_law in text
    assert "claim the application, cloud product, or release complete" in text
