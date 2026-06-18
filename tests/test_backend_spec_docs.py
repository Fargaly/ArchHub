from pathlib import Path


def test_backend_spec_documents_live_user_database():
    spec = Path("docs/BACKEND_SPEC.md").read_text(encoding="utf-8")
    lowered = spec.lower()

    assert "not yet built" not in lowered
    for table in (
        "users",
        "tokens",
        "companies",
        "company_members",
        "company_invites",
        "credit_grants",
    ):
        assert table in spec
