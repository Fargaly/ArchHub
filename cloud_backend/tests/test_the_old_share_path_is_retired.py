"""Court: the old community share path is retired (2026-09-29).

POST /v1/memory/facts/{id}/promote copied a fact into the collective table and
GET /v1/memory/collective listed every row to any signed-in user -- no review.
A fact marked visibility=shared_public was also returned to every other user's
search. The only way a fact reaches other members is now the reviewed
Community Brain (ADGR-0004). Both routes answer 410 and say where sharing went;
another user's fact never comes back from a search, whatever its visibility.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    import main
    with TestClient(main.app) as c:
        yield c


def _member(email):
    import db
    user = db.get_or_create_user(email)
    return user, {"Authorization": "Bearer " + db.issue_token(user["id"])}


def test_promote_and_collective_answer_gone_and_point_at_publish(client):
    _, h = _member("retired-a@studio.test")
    for method, path in (("POST", "/v1/memory/facts/1/promote"), ("GET", "/v1/memory/collective")):
        answer = client.request(method, path, headers=h, json={} if method == "POST" else None)
        assert answer.status_code == 410, (path, answer.text)
        assert "brain-publish" in answer.text


def test_signed_out_the_retired_routes_still_refuse_first(client):
    assert client.get("/v1/memory/collective").status_code in (401, 403)
    assert client.post("/v1/memory/facts/1/promote", json={}).status_code in (401, 403)


def test_another_users_public_fact_never_comes_back_from_search(client):
    import db
    owner, a = _member("retired-owner@studio.test")
    _, b = _member("retired-reader@studio.test")
    db.insert_memory_fact(user_id=owner["id"], text="Kestrel parapet flashing detail",
                          visibility="shared_public")
    theirs = client.get("/v1/memory/facts", params={"q": "Kestrel"}, headers=b).json()["results"]
    assert theirs == [], theirs
    mine = client.get("/v1/memory/facts", params={"q": "Kestrel"}, headers=a).json()["results"]
    assert [row["text"] for row in mine] == ["Kestrel parapet flashing detail"]


def test_the_studio_documents_no_promote_route():
    from pathlib import Path
    jsx = (Path(__file__).resolve().parents[2] / "nodelang" / "studio" / "studio-lm.jsx").read_text(encoding="utf-8")
    assert "/v1/brain/promote" not in jsx