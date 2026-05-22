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
              category="utility", description="desc"):
    return json.dumps({
        "slug": slug, "title": title, "version": version,
        "category": category, "description": description,
        "readme": "Hello, world.",
    })


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
