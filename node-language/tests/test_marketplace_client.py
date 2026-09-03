"""Marketplace client (app/marketplace_client.py) — install + uninstall +
listing tests.

Network is fully mocked via a fake `urllib.request.urlopen`. The crypto
path uses a real Ed25519 keypair so the signature math is exercised end
to end — we only fake the wire transport.
"""
from __future__ import annotations

import base64
import io
import json
import sys
import zipfile
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_ROOT))

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


# ---------------------------------------------------------------------------
# Helpers — build a real Ed25519-signed zip + a fake HTTP layer.
# ---------------------------------------------------------------------------
def _make_zip(files: dict[str, bytes]) -> bytes:
    """Build an in-memory zip with the given path -> contents map."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, body in files.items():
            zf.writestr(name, body)
    return buf.getvalue()


def _sign(priv, payload: bytes) -> str:
    return base64.b64encode(priv.sign(payload)).decode("ascii")


def _pub_b64(priv) -> str:
    return base64.b64encode(priv.public_key().public_bytes_raw()).decode("ascii")


class FakeResponse:
    """Minimal urllib-style response object — supports `.read()`,
    `.getheaders()`, `.status`, and the context-manager protocol."""

    def __init__(self, body: bytes, headers: dict, status: int = 200):
        self._body = body
        self._headers = headers
        self.status = status

    def read(self):
        return self._body

    def getheaders(self):
        return list(self._headers.items())

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeURLOpen:
    """Drop-in for urllib.request.urlopen. Routes by path."""

    def __init__(self):
        # path -> callable(req) returning a FakeResponse
        self.routes: dict[str, callable] = {}

    def __call__(self, req, timeout=None):
        # `req` is a urllib.request.Request; `.full_url` is the URL it'll fetch.
        url = req.full_url
        for prefix, handler in self.routes.items():
            if prefix in url:
                return handler(req)
        raise AssertionError(f"unexpected URL: {url}")


@pytest.fixture
def isolate_install(tmp_path, monkeypatch):
    """Redirect the install root to a temp dir so we never touch %APPDATA%."""
    monkeypatch.setenv("ARCHHUB_MARKETPLACE_DIR", str(tmp_path / "install"))
    yield tmp_path / "install"


@pytest.fixture
def fake_urlopen(monkeypatch):
    """Install a route-based fake urlopen for the duration of the test."""
    fake = FakeURLOpen()
    import marketplace_client
    monkeypatch.setattr(marketplace_client.cloud_client, "current_token",
                        lambda: "fake-token")
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    return fake


# ---------------------------------------------------------------------------
# install_pack — happy path
# ---------------------------------------------------------------------------
class TestInstall:
    def test_install_writes_to_expected_path(self, isolate_install,
                                              fake_urlopen):
        import marketplace_client as mc
        priv = Ed25519PrivateKey.generate()
        pub = _pub_b64(priv)
        zip_bytes = _make_zip({
            "skill1.archhub-workflow.json": b'{"id":"s1","name":"S1"}',
            "skill2.archhub-workflow.json": b'{"id":"s2","name":"S2"}',
            "readme.md": b"hello",
        })
        sig = _sign(priv, zip_bytes)

        # Detail endpoint — what install_pack hits first.
        def detail(req):
            return FakeResponse(
                json.dumps({
                    "id": "pk_abc",
                    "slug": "demo",
                    "title": "Demo",
                    "version": "0.1.0",
                    "manifest": {"slug": "demo"},
                }).encode("utf-8"),
                {"Content-Type": "application/json"},
            )

        # Download — returns zip + signature/pubkey headers.
        def download(req):
            return FakeResponse(
                zip_bytes,
                {
                    "Content-Type": "application/zip",
                    "X-Pack-Signature": sig,
                    "X-Pack-Pubkey": pub,
                    "X-Pack-Id": "pk_abc",
                },
            )

        fake_urlopen.routes["/marketplace/packs/pk_abc/download"] = download
        fake_urlopen.routes["/marketplace/packs/pk_abc"] = detail

        out = mc.install_pack("pk_abc")
        assert out["status"] == "ok", out
        assert out["pack_id"] == "pk_abc"
        assert out["version"] == "0.1.0"
        # 2 *.archhub-workflow.json files in the zip.
        assert out["skill_count"] == 2
        installed = Path(out["path"])
        assert installed.exists()
        assert (installed / "skill1.archhub-workflow.json").exists()
        assert (installed / "skill2.archhub-workflow.json").exists()
        # Marker file present.
        marker = installed / ".archhub_pack.json"
        assert marker.exists()
        data = json.loads(marker.read_text(encoding="utf-8"))
        assert data["pack_id"] == "pk_abc"
        assert data["version"] == "0.1.0"
        assert data["source"] == "marketplace"

    def test_install_rejects_signature_mismatch(self, isolate_install,
                                                  fake_urlopen):
        """Bad signature + wrong pubkey → install refuses + nothing on disk."""
        import marketplace_client as mc
        priv = Ed25519PrivateKey.generate()
        # Sign with priv but echo a DIFFERENT public key in the header.
        other_pub = _pub_b64(Ed25519PrivateKey.generate())
        zip_bytes = _make_zip({"a.archhub-workflow.json": b'{"id":"a"}'})
        sig = _sign(priv, zip_bytes)

        def detail(req):
            return FakeResponse(
                json.dumps({
                    "id": "pk_bad", "slug": "bad",
                    "title": "Bad", "version": "0.1.0",
                    "manifest": {"slug": "bad"},
                }).encode("utf-8"),
                {"Content-Type": "application/json"},
            )

        def download(req):
            return FakeResponse(
                zip_bytes,
                {"Content-Type": "application/zip",
                 "X-Pack-Signature": sig,
                 "X-Pack-Pubkey": other_pub},
            )

        fake_urlopen.routes["/marketplace/packs/pk_bad/download"] = download
        fake_urlopen.routes["/marketplace/packs/pk_bad"] = detail

        out = mc.install_pack("pk_bad")
        assert out["status"] == "error"
        assert "signature mismatch" in out["error"]
        # Nothing was unzipped.
        assert not (isolate_install / "pk_bad").exists()

    def test_install_rejects_bytes_payload_with_wrong_pubkey(
            self, isolate_install, fake_urlopen):
        """Spec: 'fake bytes payload + mismatched pubkey' → reject."""
        import marketplace_client as mc
        priv = Ed25519PrivateKey.generate()
        other_priv = Ed25519PrivateKey.generate()
        zip_bytes = b"this is not even a real zip"
        sig = _sign(priv, zip_bytes)

        def detail(req):
            return FakeResponse(
                json.dumps({
                    "id": "pk_x", "slug": "x",
                    "title": "X", "version": "0.1.0",
                    "manifest": {},
                }).encode("utf-8"),
                {"Content-Type": "application/json"},
            )

        def download(req):
            return FakeResponse(
                zip_bytes,
                {"X-Pack-Signature": sig,
                 "X-Pack-Pubkey": _pub_b64(other_priv)},
            )

        fake_urlopen.routes["/marketplace/packs/pk_x/download"] = download
        fake_urlopen.routes["/marketplace/packs/pk_x"] = detail

        out = mc.install_pack("pk_x")
        assert out["status"] == "error"
        assert "signature mismatch" in out["error"]

    def test_install_idempotent_on_same_version(self, isolate_install,
                                                  fake_urlopen):
        import marketplace_client as mc
        priv = Ed25519PrivateKey.generate()
        pub = _pub_b64(priv)
        zip_bytes = _make_zip(
            {"s.archhub-workflow.json": b'{"id":"s","name":"S"}'},
        )
        sig = _sign(priv, zip_bytes)

        def detail(req):
            return FakeResponse(
                json.dumps({
                    "id": "pk_idem", "slug": "idem",
                    "title": "Idem", "version": "0.1.0",
                    "manifest": {},
                }).encode("utf-8"),
                {"Content-Type": "application/json"},
            )

        download_count = {"n": 0}

        def download(req):
            download_count["n"] += 1
            return FakeResponse(
                zip_bytes,
                {"X-Pack-Signature": sig, "X-Pack-Pubkey": pub},
            )

        fake_urlopen.routes["/marketplace/packs/pk_idem/download"] = download
        fake_urlopen.routes["/marketplace/packs/pk_idem"] = detail

        first = mc.install_pack("pk_idem")
        assert first["status"] == "ok"
        assert download_count["n"] == 1
        second = mc.install_pack("pk_idem")
        assert second["status"] == "ok"
        # Same version → no second download.
        assert second.get("idempotent") is True
        assert download_count["n"] == 1


# ---------------------------------------------------------------------------
# list_installed
# ---------------------------------------------------------------------------
class TestListInstalled:
    def test_returns_metadata_for_each_pack(self, isolate_install):
        import marketplace_client as mc
        # Manually drop two pack dirs into the install root so we don't
        # have to mock the network just to populate state.
        for pid, ver in [("pk_one", "0.1.0"), ("pk_two", "0.3.0")]:
            d = isolate_install / pid
            d.mkdir(parents=True, exist_ok=True)
            (d / "a.archhub-workflow.json").write_text('{"id":"a"}',
                                                       encoding="utf-8")
            (d / ".archhub_pack.json").write_text(
                json.dumps({
                    "pack_id": pid, "version": ver,
                    "title": f"Pack {pid}", "slug": pid,
                    "signature": "x", "pubkey": "y",
                    "manifest": {"slug": pid},
                    "source": "marketplace",
                }), encoding="utf-8",
            )
        out = mc.list_installed()
        assert len(out) == 2
        ids = {p["pack_id"] for p in out}
        assert ids == {"pk_one", "pk_two"}
        for p in out:
            assert p["source"] == "marketplace"
            assert p["skill_count"] == 1
            assert "path" in p


# ---------------------------------------------------------------------------
# uninstall_pack
# ---------------------------------------------------------------------------
class TestUninstall:
    def test_removes_dir(self, isolate_install):
        import marketplace_client as mc
        target = isolate_install / "pk_gone"
        target.mkdir(parents=True)
        (target / "x.archhub-workflow.json").write_text("{}",
                                                        encoding="utf-8")
        out = mc.uninstall_pack("pk_gone")
        assert out["status"] == "ok"
        assert out["removed"] is True
        assert not target.exists()

    def test_uninstall_missing_is_noop(self, isolate_install):
        import marketplace_client as mc
        out = mc.uninstall_pack("pk_never_installed")
        assert out["status"] == "ok"
        assert out["removed"] is False


# ---------------------------------------------------------------------------
# list_packs (browse)
# ---------------------------------------------------------------------------
class TestListPacks:
    def test_passes_through_response(self, isolate_install, fake_urlopen):
        import marketplace_client as mc

        def browse(req):
            return FakeResponse(
                json.dumps({
                    "packs": [
                        {"id": "pk_a", "slug": "a", "title": "A",
                         "version": "0.1.0", "status": "approved"},
                    ],
                    "next_cursor": None,
                }).encode("utf-8"),
                {"Content-Type": "application/json"},
            )

        fake_urlopen.routes["/marketplace/packs"] = browse
        out = mc.list_packs(query="dim")
        assert out["packs"][0]["slug"] == "a"
        assert out["next_cursor"] is None


# ---------------------------------------------------------------------------
# upload_pack — author flow
# ---------------------------------------------------------------------------
class TestUploadPack:
    def test_posts_multipart(self, tmp_path, fake_urlopen):
        import marketplace_client as mc
        # Write the four artifact files.
        zip_path = tmp_path / "pack.zip"
        zip_path.write_bytes(_make_zip(
            {"s.archhub-workflow.json": b'{"id":"s"}'}))
        sig_path = tmp_path / "sig.txt"
        sig_path.write_text("c2lnbmF0dXJl", encoding="utf-8")   # 'signature'
        pub_path = tmp_path / "pub.txt"
        pub_path.write_text("cHVia2V5", encoding="utf-8")        # 'pubkey'
        man_path = tmp_path / "manifest.json"
        man_path.write_text(
            json.dumps({"slug": "uploaded", "title": "Uploaded",
                        "version": "0.1.0"}),
            encoding="utf-8")

        captured = {}

        def upload(req):
            captured["url"] = req.full_url
            captured["content_type"] = req.get_header("Content-type", "")
            captured["body"] = req.data
            return FakeResponse(
                json.dumps({
                    "pack_id": "pk_uploaded",
                    "slug": "uploaded",
                    "version": "0.1.0",
                    "status": "pending_review",
                }).encode("utf-8"),
                {"Content-Type": "application/json"},
            )

        fake_urlopen.routes["/marketplace/packs"] = upload
        out = mc.upload_pack(str(zip_path), str(sig_path),
                             str(pub_path), str(man_path))
        assert out["pack_id"] == "pk_uploaded"
        assert out["status"] == "pending_review"
        assert "multipart/form-data" in captured["content_type"]
        # All four field names appear in the body.
        body = captured["body"]
        assert b'name="pack_zip"' in body
        assert b'name="signature"' in body
        assert b'name="pubkey"' in body
        assert b'name="manifest"' in body
