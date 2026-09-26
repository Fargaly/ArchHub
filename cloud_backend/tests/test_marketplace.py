"""Marketplace v1 — end-to-end HTTP tests via FastAPI TestClient.

Covers the seven contract points called out in the spec:
  1. Unsigned upload → 400
  2. Signed upload   → 200, status=pending_review
  3. Non-admin /review → 403
  4. Admin /review (approve) → status=approved
  5. GET /packs?verified_only=true returns only approved packs
  6. /download returns the zip + X-Pack-Signature / X-Pack-Pubkey headers
  7. /report inserts a row

Plus a couple of safety nets:
  - Slug collision rejected (409)
  - Bad-signature upload rejected with a sig-specific detail
"""
from __future__ import annotations

import base64
import json

import pytest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    import main
    return TestClient(main.app)


@pytest.fixture
def keypair():
    sk = Ed25519PrivateKey.generate()
    priv = sk
    pub_b64 = base64.b64encode(
        sk.public_key().public_bytes_raw()).decode("ascii")
    return priv, pub_b64


def _sign(priv, zip_bytes: bytes) -> str:
    return base64.b64encode(priv.sign(zip_bytes)).decode("ascii")


@pytest.fixture
def author_token():
    """Create a user + token bypassing the magic-link flow."""
    import db
    u = db.get_or_create_user("author@studio.com")
    return u, db.issue_token(u["id"])


@pytest.fixture
def admin_token():
    import db
    u = db.get_or_create_user("admin@studio.com")
    with db.connect() as con:
        con.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (u["id"],))
    return db.get_user(u["id"]), db.issue_token(u["id"])


@pytest.fixture
def reporter_token():
    import db
    u = db.get_or_create_user("reporter@studio.com")
    return u, db.issue_token(u["id"])


# ---------------------------------------------------------------------------
# Helpers — build a multipart upload payload.
# ---------------------------------------------------------------------------
def _manifest(slug="my.pack", title="My Pack", version="0.1.0",
              category="utility", description="desc", pack_type=None):
    m = {
        "slug": slug, "title": title, "version": version,
        "category": category, "description": description,
        "readme": "Hello, world.",
    }
    if pack_type is not None:
        m["pack_type"] = pack_type
    return json.dumps(m)


def _upload(client, *, token, zip_bytes, signature, pubkey, manifest):
    return client.post(
        "/marketplace/packs",
        headers={"Authorization": f"Bearer {token}"},
        files={"pack_zip": ("pack.zip", zip_bytes, "application/zip")},
        data={"signature": signature, "pubkey": pubkey,
              "manifest": manifest},
    )


# ---------------------------------------------------------------------------
# Schema migration sanity — is_admin column exists.
# ---------------------------------------------------------------------------
def test_is_admin_column_added():
    import db
    db.init_schema()
    db.init_schema()  # call twice — must remain idempotent
    with db.connect() as con:
        cols = [r["name"] for r in
                con.execute("PRAGMA table_info(users)").fetchall()]
    assert "is_admin" in cols


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------
class TestUpload:
    def test_unsigned_upload_rejected(self, client, author_token):
        _, token = author_token
        r = _upload(client, token=token,
                    zip_bytes=b"PK\x03\x04dummy",
                    signature="", pubkey="",
                    manifest=_manifest())
        # Empty signature / pubkey both rejected at 400.
        assert r.status_code == 400, r.text

    def test_signed_upload_accepted(self, client, author_token, keypair):
        priv, pub = keypair
        _, token = author_token
        zip_bytes = b"PK\x03\x04 fake zip body"
        sig = _sign(priv, zip_bytes)
        r = _upload(client, token=token, zip_bytes=zip_bytes,
                    signature=sig, pubkey=pub,
                    manifest=_manifest(slug="signed.pack"))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "pending_review"
        assert body["pack_id"].startswith("pk_")
        assert body["slug"] == "signed.pack"

    def test_tampered_signature_rejected(self, client, author_token, keypair):
        priv, pub = keypair
        _, token = author_token
        zip_bytes = b"PK\x03\x04original"
        sig = _sign(priv, zip_bytes)
        # Send a different payload — signature won't verify.
        tampered = b"PK\x03\x04tampered"
        r = _upload(client, token=token, zip_bytes=tampered,
                    signature=sig, pubkey=pub,
                    manifest=_manifest(slug="tampered.pack"))
        assert r.status_code == 400
        assert "signature_invalid" in r.json().get("detail", "")

    def test_oversize_upload_rejected(self, client, author_token, keypair):
        priv, pub = keypair
        _, token = author_token
        # 10MB + 1 byte
        big = b"\x00" * (10 * 1024 * 1024 + 1)
        sig = _sign(priv, big)
        r = _upload(client, token=token, zip_bytes=big,
                    signature=sig, pubkey=pub,
                    manifest=_manifest(slug="big.pack"))
        assert r.status_code == 413

    def test_slug_collision_returns_409(self, client, author_token, keypair):
        priv, pub = keypair
        _, token = author_token
        zip_bytes = b"PK\x03\x04first"
        sig = _sign(priv, zip_bytes)
        r1 = _upload(client, token=token, zip_bytes=zip_bytes,
                     signature=sig, pubkey=pub,
                     manifest=_manifest(slug="dup.pack"))
        assert r1.status_code == 200
        r2 = _upload(client, token=token, zip_bytes=zip_bytes,
                     signature=sig, pubkey=pub,
                     manifest=_manifest(slug="dup.pack"))
        assert r2.status_code == 409

    def test_upload_requires_auth(self, client, keypair):
        priv, pub = keypair
        zip_bytes = b"PK\x03\x04nope"
        sig = _sign(priv, zip_bytes)
        r = client.post(
            "/marketplace/packs",
            files={"pack_zip": ("p.zip", zip_bytes, "application/zip")},
            data={"signature": sig, "pubkey": pub,
                  "manifest": _manifest(slug="anon.pack")},
        )
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# Review (admin gate)
# ---------------------------------------------------------------------------
class TestReview:
    def _upload_pack(self, client, author_token, keypair, slug):
        priv, pub = keypair
        _, token = author_token
        zip_bytes = b"PK\x03\x04 zipper"
        sig = _sign(priv, zip_bytes)
        r = _upload(client, token=token, zip_bytes=zip_bytes,
                    signature=sig, pubkey=pub,
                    manifest=_manifest(slug=slug))
        assert r.status_code == 200, r.text
        return r.json()["pack_id"]

    def test_non_admin_review_rejected(self, client, author_token, keypair):
        pack_id = self._upload_pack(client, author_token, keypair, "n.pack")
        _, token = author_token
        r = client.post(
            f"/marketplace/packs/{pack_id}/review",
            headers={"Authorization": f"Bearer {token}"},
            json={"decision": "approve", "reason": ""},
        )
        assert r.status_code == 403

    def test_admin_approve_flips_status(self, client, author_token,
                                         admin_token, keypair):
        pack_id = self._upload_pack(client, author_token, keypair, "a.pack")
        _, admin_t = admin_token
        r = client.post(
            f"/marketplace/packs/{pack_id}/review",
            headers={"Authorization": f"Bearer {admin_t}"},
            json={"decision": "approve", "reason": ""},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "approved"

        # Confirm GET detail reflects the new status.
        r2 = client.get(f"/marketplace/packs/{pack_id}")
        assert r2.status_code == 200
        assert r2.json()["status"] == "approved"

    def test_admin_reject_records_reason(self, client, author_token,
                                          admin_token, keypair):
        pack_id = self._upload_pack(client, author_token, keypair, "r.pack")
        _, admin_t = admin_token
        r = client.post(
            f"/marketplace/packs/{pack_id}/review",
            headers={"Authorization": f"Bearer {admin_t}"},
            json={"decision": "reject", "reason": "policy_violation"},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "rejected"


# ---------------------------------------------------------------------------
# Browse
# ---------------------------------------------------------------------------
class TestBrowse:
    def test_verified_only_filters_to_approved(self, client, author_token,
                                                 admin_token, keypair):
        priv, pub = keypair
        _, token = author_token
        _, admin_t = admin_token

        # Pack 1: stays pending.
        z1 = b"PK\x03\x04one"
        _upload(client, token=token, zip_bytes=z1,
                signature=_sign(priv, z1), pubkey=pub,
                manifest=_manifest(slug="pending.pack"))
        # Pack 2: approved.
        z2 = b"PK\x03\x04two"
        r2 = _upload(client, token=token, zip_bytes=z2,
                     signature=_sign(priv, z2), pubkey=pub,
                     manifest=_manifest(slug="approved.pack"))
        pid2 = r2.json()["pack_id"]
        client.post(
            f"/marketplace/packs/{pid2}/review",
            headers={"Authorization": f"Bearer {admin_t}"},
            json={"decision": "approve", "reason": ""},
        )
        # Anonymous browse — only approved.
        r = client.get("/marketplace/packs?verified_only=true")
        assert r.status_code == 200
        slugs = [p["slug"] for p in r.json()["packs"]]
        assert "approved.pack" in slugs
        assert "pending.pack" not in slugs

    def test_search_query_filters(self, client, author_token,
                                    admin_token, keypair):
        priv, pub = keypair
        _, token = author_token
        _, admin_t = admin_token
        for slug, title in [("revit.dim", "Dimension Walls"),
                            ("revit.elev", "Generate Elevations"),
                            ("cad.export", "Export to CAD")]:
            z = (slug + title).encode("ascii")
            r = _upload(client, token=token, zip_bytes=z,
                        signature=_sign(priv, z), pubkey=pub,
                        manifest=_manifest(slug=slug, title=title))
            pid = r.json()["pack_id"]
            client.post(
                f"/marketplace/packs/{pid}/review",
                headers={"Authorization": f"Bearer {admin_t}"},
                json={"decision": "approve", "reason": ""},
            )
        r = client.get("/marketplace/packs?query=revit&verified_only=true")
        assert r.status_code == 200
        slugs = [p["slug"] for p in r.json()["packs"]]
        assert "revit.dim" in slugs
        assert "revit.elev" in slugs
        assert "cad.export" not in slugs


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------
class TestDownload:
    def test_download_returns_zip_and_signature_headers(
            self, client, author_token, admin_token, keypair):
        priv, pub = keypair
        _, token = author_token
        _, admin_t = admin_token
        zip_bytes = b"PK\x03\x04 the actual zip payload bytes"
        sig = _sign(priv, zip_bytes)
        r = _upload(client, token=token, zip_bytes=zip_bytes,
                    signature=sig, pubkey=pub,
                    manifest=_manifest(slug="dl.pack"))
        pack_id = r.json()["pack_id"]
        client.post(
            f"/marketplace/packs/{pack_id}/review",
            headers={"Authorization": f"Bearer {admin_t}"},
            json={"decision": "approve", "reason": ""},
        )

        dr = client.get(f"/marketplace/packs/{pack_id}/download")
        assert dr.status_code == 200
        assert dr.headers["X-Pack-Signature"] == sig
        assert dr.headers["X-Pack-Pubkey"] == pub
        assert dr.headers["content-type"] == "application/zip"
        assert dr.content == zip_bytes

    def test_download_pending_pack_404_for_anon(
            self, client, author_token, keypair):
        priv, pub = keypair
        _, token = author_token
        zip_bytes = b"PK\x03\x04private"
        sig = _sign(priv, zip_bytes)
        r = _upload(client, token=token, zip_bytes=zip_bytes,
                    signature=sig, pubkey=pub,
                    manifest=_manifest(slug="hidden.pack"))
        pack_id = r.json()["pack_id"]
        # Anonymous request — pending pack should 404.
        dr = client.get(f"/marketplace/packs/{pack_id}/download")
        assert dr.status_code == 404


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
class TestReport:
    def test_report_inserts_row(self, client, author_token,
                                  admin_token, keypair, reporter_token):
        priv, pub = keypair
        _, token = author_token
        _, admin_t = admin_token
        _, rep_t = reporter_token
        zip_bytes = b"PK\x03\x04 reportable"
        r = _upload(client, token=token, zip_bytes=zip_bytes,
                    signature=_sign(priv, zip_bytes), pubkey=pub,
                    manifest=_manifest(slug="r.pack"))
        pack_id = r.json()["pack_id"]
        # Approve so it's a public pack.
        client.post(
            f"/marketplace/packs/{pack_id}/review",
            headers={"Authorization": f"Bearer {admin_t}"},
            json={"decision": "approve", "reason": ""},
        )
        rep = client.post(
            f"/marketplace/packs/{pack_id}/report",
            headers={"Authorization": f"Bearer {rep_t}"},
            json={"reason": "Looks malicious"},
        )
        assert rep.status_code == 201
        body = rep.json()
        assert body["pack_id"] == pack_id
        assert body["report_id"] is not None

        # Confirm via DB.
        import db
        with db.connect() as con:
            rows = con.execute(
                "SELECT reason FROM marketplace_reports WHERE pack_id = ?",
                (pack_id,),
            ).fetchall()
        assert len(rows) == 1
        assert rows[0]["reason"] == "Looks malicious"

    def test_report_requires_auth(self, client):
        r = client.post(
            "/marketplace/packs/whatever/report",
            json={"reason": "x"},
        )
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# Community Gallery — schema migration + source/type + voting + promote
# ---------------------------------------------------------------------------
def _publish_approved(client, author_token, admin_token, keypair, *,
                      slug, pack_type=None, source=None):
    """Upload + admin-approve a pack; return its pack_id."""
    priv, pub = keypair
    _, token = author_token
    _, admin_t = admin_token
    z = (slug + (pack_type or "")).encode("ascii")
    data = {"signature": _sign(priv, z), "pubkey": pub,
            "manifest": _manifest(slug=slug, pack_type=pack_type)}
    if source is not None:
        data["source"] = source
    r = client.post(
        "/marketplace/packs",
        headers={"Authorization": f"Bearer {token}"},
        files={"pack_zip": ("pack.zip", z, "application/zip")},
        data=data,
    )
    assert r.status_code == 200, r.text
    pid = r.json()["pack_id"]
    client.post(
        f"/marketplace/packs/{pid}/review",
        headers={"Authorization": f"Bearer {admin_t}"},
        json={"decision": "approve", "reason": ""},
    )
    return pid


def test_gallery_columns_added():
    import db
    db.init_schema()
    db.init_schema()  # idempotent
    with db.connect() as con:
        cols = [r["name"] for r in
                con.execute("PRAGMA table_info(marketplace_packs)").fetchall()]
        vcols = [r["name"] for r in
                 con.execute(
                     "PRAGMA table_info(marketplace_pack_votes)").fetchall()]
    for c in ("source", "pack_type", "up_votes", "down_votes",
              "at_own_risk", "promoted_at", "promoted_by"):
        assert c in cols, c
    assert "voter_user_id" in vcols and "vote" in vcols


class TestGalleryUpload:
    def test_default_source_is_user_and_at_own_risk(
            self, client, author_token, keypair):
        priv, pub = keypair
        _, token = author_token
        z = b"PK\x03\x04 gallery default"
        r = _upload(client, token=token, zip_bytes=z,
                    signature=_sign(priv, z), pubkey=pub,
                    manifest=_manifest(slug="gal.default"))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["source"] == "user"
        assert body["pack_type"] == "skill"
        assert body["at_own_risk"] is True

    def test_pack_type_from_manifest(self, client, author_token, keypair):
        priv, pub = keypair
        _, token = author_token
        z = b"PK\x03\x04 connector pack"
        r = _upload(client, token=token, zip_bytes=z,
                    signature=_sign(priv, z), pubkey=pub,
                    manifest=_manifest(slug="gal.conn", pack_type="connector"))
        assert r.status_code == 200, r.text
        assert r.json()["pack_type"] == "connector"

    def test_invalid_pack_type_rejected(self, client, author_token, keypair):
        priv, pub = keypair
        _, token = author_token
        z = b"PK\x03\x04 bad type"
        r = _upload(client, token=token, zip_bytes=z,
                    signature=_sign(priv, z), pubkey=pub,
                    manifest=_manifest(slug="gal.badtype", pack_type="malware"))
        assert r.status_code == 400
        assert "invalid_pack_type" in r.json().get("detail", "")

    def test_normal_user_cannot_self_tag_agent(
            self, client, author_token, keypair):
        # A non-admin asking for source=agent is silently forced to 'user'.
        priv, pub = keypair
        _, token = author_token
        z = b"PK\x03\x04 sneaky agent"
        r = client.post(
            "/marketplace/packs",
            headers={"Authorization": f"Bearer {token}"},
            files={"pack_zip": ("p.zip", z, "application/zip")},
            data={"signature": _sign(priv, z), "pubkey": pub,
                  "manifest": _manifest(slug="gal.sneaky"),
                  "source": "agent"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["source"] == "user"

    def test_admin_can_publish_agent_source(
            self, client, admin_token, keypair):
        priv, pub = keypair
        _, admin_t = admin_token
        z = b"PK\x03\x04 real agent pack"
        r = client.post(
            "/marketplace/packs",
            headers={"Authorization": f"Bearer {admin_t}"},
            files={"pack_zip": ("p.zip", z, "application/zip")},
            data={"signature": _sign(priv, z), "pubkey": pub,
                  "manifest": _manifest(slug="gal.agent"),
                  "source": "agent"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["source"] == "agent"


class TestGalleryFilters:
    def test_source_filter(self, client, author_token, admin_token, keypair):
        _publish_approved(client, author_token, admin_token, keypair,
                          slug="filt.user")
        _publish_approved(client, author_token, admin_token,
                          keypair, slug="filt.agent")
        # Promote one to official so all three source values exist.
        _, admin_t = admin_token
        off_pid = _publish_approved(client, author_token, admin_token,
                                    keypair, slug="filt.tobeofficial")
        client.post(f"/marketplace/packs/{off_pid}/promote",
                    headers={"Authorization": f"Bearer {admin_t}"})

        r = client.get("/marketplace/packs?source=official&verified_only=true")
        slugs = [p["slug"] for p in r.json()["packs"]]
        assert "filt.tobeofficial" in slugs
        assert "filt.user" not in slugs

        r2 = client.get("/marketplace/packs?source=user&verified_only=true")
        slugs2 = [p["slug"] for p in r2.json()["packs"]]
        assert "filt.user" in slugs2
        assert "filt.tobeofficial" not in slugs2

    def test_pack_type_filter(self, client, author_token, admin_token,
                              keypair):
        _publish_approved(client, author_token, admin_token, keypair,
                          slug="ft.node", pack_type="node")
        _publish_approved(client, author_token, admin_token, keypair,
                          slug="ft.widget", pack_type="widget")
        r = client.get("/marketplace/packs?pack_type=node&verified_only=true")
        slugs = [p["slug"] for p in r.json()["packs"]]
        assert "ft.node" in slugs
        assert "ft.widget" not in slugs

    def test_bad_source_filter_400(self, client):
        r = client.get("/marketplace/packs?source=hax")
        assert r.status_code == 400

    def test_sort_top_orders_by_score(self, client, author_token,
                                      admin_token, reporter_token, keypair):
        _publish_approved(client, author_token, admin_token, keypair,
                          slug="sort.low")
        high = _publish_approved(client, author_token, admin_token, keypair,
                                 slug="sort.high")
        _, rep_t = reporter_token
        # Upvote the 'high' pack.
        client.post(f"/marketplace/packs/{high}/vote",
                    headers={"Authorization": f"Bearer {rep_t}"},
                    json={"vote": 1})
        r = client.get("/marketplace/packs?sort=top&verified_only=true")
        slugs = [p["slug"] for p in r.json()["packs"]]
        assert slugs.index("sort.high") < slugs.index("sort.low")


class TestGalleryVote:
    def test_vote_requires_auth(self, client):
        r = client.post("/marketplace/packs/whatever/vote",
                        json={"vote": 1})
        assert r.status_code == 401

    def test_vote_unknown_pack_404(self, client, reporter_token):
        _, rep_t = reporter_token
        r = client.post("/marketplace/packs/pk_nope/vote",
                        headers={"Authorization": f"Bearer {rep_t}"},
                        json={"vote": 1})
        assert r.status_code == 404

    def test_double_vote_is_one_row(self, client, author_token, admin_token,
                                    reporter_token, keypair):
        pid = _publish_approved(client, author_token, admin_token, keypair,
                                slug="vote.once")
        _, rep_t = reporter_token
        h = {"Authorization": f"Bearer {rep_t}"}
        r1 = client.post(f"/marketplace/packs/{pid}/vote", headers=h,
                         json={"vote": 1})
        assert r1.json()["up_votes"] == 1
        # Voting up AGAIN must not stack — still exactly one up vote, one row.
        r2 = client.post(f"/marketplace/packs/{pid}/vote", headers=h,
                         json={"vote": 1})
        assert r2.json()["up_votes"] == 1
        assert r2.json()["my_vote"] == 1
        import db
        with db.connect() as con:
            n = con.execute(
                "SELECT COUNT(*) AS c FROM marketplace_pack_votes"
                " WHERE pack_id = ?", (pid,)).fetchone()["c"]
        assert n == 1

    def test_vote_flip_up_to_down(self, client, author_token, admin_token,
                                  reporter_token, keypair):
        pid = _publish_approved(client, author_token, admin_token, keypair,
                                slug="vote.flip")
        _, rep_t = reporter_token
        h = {"Authorization": f"Bearer {rep_t}"}
        client.post(f"/marketplace/packs/{pid}/vote", headers=h,
                    json={"vote": 1})
        r = client.post(f"/marketplace/packs/{pid}/vote", headers=h,
                        json={"vote": -1})
        body = r.json()
        assert body["up_votes"] == 0
        assert body["down_votes"] == 1
        assert body["my_vote"] == -1

    def test_vote_clear(self, client, author_token, admin_token,
                        reporter_token, keypair):
        pid = _publish_approved(client, author_token, admin_token, keypair,
                                slug="vote.clear")
        _, rep_t = reporter_token
        h = {"Authorization": f"Bearer {rep_t}"}
        client.post(f"/marketplace/packs/{pid}/vote", headers=h,
                    json={"vote": 1})
        r = client.post(f"/marketplace/packs/{pid}/vote", headers=h,
                        json={"vote": 0})
        body = r.json()
        assert body["up_votes"] == 0 and body["down_votes"] == 0
        assert body["my_vote"] == 0

    def test_my_vote_surfaced_in_detail(self, client, author_token,
                                        admin_token, reporter_token, keypair):
        pid = _publish_approved(client, author_token, admin_token, keypair,
                                slug="vote.detail")
        _, rep_t = reporter_token
        h = {"Authorization": f"Bearer {rep_t}"}
        client.post(f"/marketplace/packs/{pid}/vote", headers=h,
                    json={"vote": 1})
        r = client.get(f"/marketplace/packs/{pid}", headers=h)
        assert r.json()["my_vote"] == 1
        assert r.json()["up_votes"] == 1


class TestGalleryPromote:
    def test_non_admin_promote_403(self, client, author_token, admin_token,
                                   keypair):
        pid = _publish_approved(client, author_token, admin_token, keypair,
                                slug="promo.gate")
        _, token = author_token
        r = client.post(f"/marketplace/packs/{pid}/promote",
                        headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 403

    def test_promote_requires_auth(self, client, author_token, admin_token,
                                   keypair):
        pid = _publish_approved(client, author_token, admin_token, keypair,
                                slug="promo.anon")
        r = client.post(f"/marketplace/packs/{pid}/promote")
        assert r.status_code == 401

    def test_admin_promote_sets_official_clears_risk(
            self, client, author_token, admin_token, keypair):
        pid = _publish_approved(client, author_token, admin_token, keypair,
                                slug="promo.lift")
        _, admin_t = admin_token
        r = client.post(f"/marketplace/packs/{pid}/promote",
                        headers={"Authorization": f"Bearer {admin_t}"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["source"] == "official"
        assert body["at_own_risk"] is False
        # Detail reflects it too.
        d = client.get(f"/marketplace/packs/{pid}")
        assert d.json()["source"] == "official"
        assert d.json()["at_own_risk"] is False


class TestGalleryAdoptWarning:
    def test_download_surfaces_at_own_risk_header(
            self, client, author_token, admin_token, keypair):
        pid = _publish_approved(client, author_token, admin_token, keypair,
                                slug="risk.community")
        dr = client.get(f"/marketplace/packs/{pid}/download")
        assert dr.status_code == 200
        # Community (user) pack -> at-own-risk flag set for the adopt warning.
        assert dr.headers["X-Pack-At-Own-Risk"] == "1"
        assert dr.headers["X-Pack-Source"] == "user"

    def test_official_pack_no_risk_header(
            self, client, author_token, admin_token, keypair):
        pid = _publish_approved(client, author_token, admin_token, keypair,
                                slug="risk.official")
        _, admin_t = admin_token
        client.post(f"/marketplace/packs/{pid}/promote",
                    headers={"Authorization": f"Bearer {admin_t}"})
        dr = client.get(f"/marketplace/packs/{pid}/download")
        assert dr.headers["X-Pack-At-Own-Risk"] == "0"
        assert dr.headers["X-Pack-Source"] == "official"
