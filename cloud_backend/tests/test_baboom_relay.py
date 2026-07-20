"""End-to-end courts for BABOOM's device-bound metadata relay."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils
from fastapi.testclient import TestClient

import baboom_relay
import db
import main


BABOOM_TOOLING_ROOT = os.environ.get("ARCHHUB_BABOOM_TOOLING_ROOT", "").strip()
BaboomRelayClient = None
if BABOOM_TOOLING_ROOT:
    root = Path(BABOOM_TOOLING_ROOT).expanduser().resolve()
    if root.is_dir() and str(root) not in sys.path:
        sys.path.insert(0, str(root))
    try:
        from baboom.relay import BaboomRelayClient
    except Exception:
        BaboomRelayClient = None


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": "Bearer " + token}


def _user(suffix: str) -> tuple[dict, str]:
    user = db.get_or_create_user("baboom+%s@example.com" % suffix)
    return user, db.issue_token(user["id"])


def _jwk(key: ec.EllipticCurvePrivateKey) -> dict[str, str]:
    numbers = key.public_key().public_numbers()
    return {
        "kty": "EC", "crv": "P-256",
        "x": _b64(numbers.x.to_bytes(32, "big")),
        "y": _b64(numbers.y.to_bytes(32, "big")),
    }


def _raw_signature(key: ec.EllipticCurvePrivateKey, digest: bytes) -> str:
    der = key.sign(digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
    r, s = utils.decode_dss_signature(der)
    return _b64(r.to_bytes(32, "big") + s.to_bytes(32, "big"))


def _enroll(
    client: TestClient,
    token: str,
    device_id: str,
    *,
    recipient_public_jwk: dict[str, str] | None = None,
) -> tuple[ec.EllipticCurvePrivateKey, dict[str, str]]:
    key = ec.generate_private_key(ec.SECP256R1())
    public = _jwk(key)
    challenge = client.post(
        "/v1/baboom/devices/challenge",
        headers=_headers(token), json={
            "device_id": device_id,
            "public_jwk": public,
            "recipient_public_jwk": recipient_public_jwk,
        },
    )
    assert challenge.status_code == 200, challenge.text
    issued = challenge.json()
    user = db.user_for_token(token)
    payload = baboom_relay.enrollment_challenge_payload(
        user_id=user["id"], challenge_id=issued["challenge_id"],
        challenge=issued["challenge"], device_id=device_id,
        thumbprint=issued["thumbprint"],
        recipient_thumbprint=str(issued.get("recipient_thumbprint") or ""),
    )
    complete = client.post(
        "/v1/baboom/devices/complete", headers=_headers(token), json={
            "device_id": device_id, "public_jwk": public,
            "recipient_public_jwk": recipient_public_jwk,
            "challenge_id": issued["challenge_id"], "challenge": issued["challenge"],
            "signature": _raw_signature(key, hashlib.sha256(payload).digest()),
        },
    )
    assert complete.status_code == 200, complete.text
    return key, public


def _dpop(key: ec.EllipticCurvePrivateKey, public: dict[str, str], token: str, nonce: str, method: str, path: str, *, jti: str | None = None) -> str:
    header = {"alg": "ES256", "jwk": public, "typ": "dpop+jwt"}
    claims = {
        "ath": _b64(hashlib.sha256(token.encode("ascii")).digest()),
        "htm": method.upper(), "htu": "http://localhost" + path,
        "iat": int(time.time()), "jti": jti or secrets.token_urlsafe(18),
        "nonce": nonce,
    }
    encoded_header = _b64(json.dumps(header, sort_keys=True, separators=(",", ":")).encode("ascii"))
    encoded_claims = _b64(json.dumps(claims, sort_keys=True, separators=(",", ":")).encode("ascii"))
    der = key.sign((encoded_header + "." + encoded_claims).encode("ascii"), ec.ECDSA(hashes.SHA256()))
    r, s = utils.decode_dss_signature(der)
    return encoded_header + "." + encoded_claims + "." + _b64(r.to_bytes(32, "big") + s.to_bytes(32, "big"))


def _request(client: TestClient, token: str, device_id: str, key, public, method: str, path: str, *, body: dict | None = None, replay: str | None = None):
    if replay is None:
        nonce = client.post(
            "/v1/baboom/nonces", headers=_headers(token), json={"device_id": device_id},
        )
        assert nonce.status_code == 200, nonce.text
        proof = _dpop(key, public, token, nonce.json()["nonce"], method, path)
    else:
        proof = replay
    headers = {
        **_headers(token), "X-Baboom-Device": device_id, "DPoP": proof,
    }
    return client.request(method, path, headers=headers, json=body), proof


class _TestClientTransport:
    def __init__(self, client: TestClient) -> None:
        self.client = client

    def request(self, method, url, *, headers, payload, timeout):
        response = self.client.request(
            method,
            urlsplit(url).path,
            headers=dict(headers),
            json=dict(payload) if payload is not None else None,
        )
        return response.status_code, response.json()


class _TestSigner:
    def __init__(self) -> None:
        self.key = ec.generate_private_key(ec.SECP256R1())
        public_jwk = _jwk(self.key)
        self.reference = SimpleNamespace(
            public_jwk=public_jwk,
            thumbprint=_b64(hashlib.sha256(
                json.dumps(public_jwk, sort_keys=True, separators=(",", ":")).encode("ascii")
            ).digest()),
        )

    def sign_digest(self, digest: bytes) -> bytes:
        der = self.key.sign(digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
        r, s = utils.decode_dss_signature(der)
        return r.to_bytes(32, "big") + s.to_bytes(32, "big")

    def dpop_proof(self, *, http_method, target_uri, access_token, nonce) -> bytes:
        header = {"alg": "ES256", "jwk": self.reference.public_jwk, "typ": "dpop+jwt"}
        claims = {
            "ath": _b64(hashlib.sha256(access_token.encode("ascii")).digest()),
            "htm": http_method.upper(), "htu": target_uri,
            "iat": int(time.time()), "jti": secrets.token_urlsafe(18), "nonce": nonce,
        }
        protected = _b64(json.dumps(header, sort_keys=True, separators=(",", ":")).encode("ascii"))
        body = _b64(json.dumps(claims, sort_keys=True, separators=(",", ":")).encode("ascii"))
        der = self.key.sign((protected + "." + body).encode("ascii"), ec.ECDSA(hashes.SHA256()))
        r, s = utils.decode_dss_signature(der)
        return (protected + "." + body + "." + _b64(r.to_bytes(32, "big") + s.to_bytes(32, "big"))).encode("ascii")


class _TestRecipient:
    def __init__(self) -> None:
        self.key = ec.generate_private_key(ec.SECP256R1())
        public_jwk = _jwk(self.key)
        self.reference = SimpleNamespace(
            public_jwk=public_jwk,
            thumbprint=_b64(hashlib.sha256(
                json.dumps(public_jwk, sort_keys=True, separators=(",", ":")).encode("ascii")
            ).digest()),
        )


def test_device_proof_relay_delivers_only_metadata_and_receipts():
    with TestClient(main.app, base_url="http://localhost") as client:
        _user_row, token = _user("owner")
        source_key, source_jwk = _enroll(client, token, "workstation-a")
        target_key, target_jwk = _enroll(client, token, "laptop-b")
        command_id = hashlib.sha256(b"relay-command").hexdigest()
        payload = {
            "command_id": command_id, "target_device_id": "laptop-b",
            "summary": "Review the active BIM task and prepare a draft",
            "payload_digest": hashlib.sha256(b"full task stays local").hexdigest(),
            "created_at": time.time(),
            "expires_at": time.time() + 600,
        }
        submitted, proof = _request(
            client, token, "workstation-a", source_key, source_jwk,
            "POST", "/v1/baboom/commands", body=payload,
        )
        assert submitted.status_code == 200, submitted.text
        assert submitted.json()["state"] == "queued"
        # A consumed nonce/proof cannot be replayed to duplicate the command.
        replayed, _ = _request(
            client, token, "workstation-a", source_key, source_jwk,
            "POST", "/v1/baboom/commands", body=payload, replay=proof,
        )
        assert replayed.status_code == 401

        listed, _ = _request(
            client, token, "laptop-b", target_key, target_jwk,
            "GET", "/v1/baboom/commands",
        )
        assert listed.status_code == 200, listed.text
        assert listed.json()["commands"][0]["payload_digest"] == payload["payload_digest"]
        assert "full task stays local" not in json.dumps(listed.json())

        claimed, _ = _request(
            client, token, "laptop-b", target_key, target_jwk,
            "POST", "/v1/baboom/commands/%s/claim" % command_id,
        )
        assert claimed.status_code == 200, claimed.text
        assert claimed.json()["state"] == "claimed"
        settled, _ = _request(
            client, token, "laptop-b", target_key, target_jwk,
            "POST", "/v1/baboom/commands/%s/settle" % command_id,
            body={"succeeded": True, "outcome_code": "draft-ready"},
        )
        assert settled.status_code == 200, settled.text
        assert settled.json()["state"] == "completed"
        assert settled.json()["outcome_code"] == "draft-ready"
        # The source can recover the target receipt without being allowed to
        # inspect another device's incoming queue.
        sent, _ = _request(
            client, token, "workstation-a", source_key, source_jwk,
            "GET", "/v1/baboom/commands/sent",
        )
        assert sent.status_code == 200, sent.text
        assert sent.json()["commands"][0]["state"] == "completed"


def test_relay_rejects_bearer_only_secret_summary_and_wrong_device():
    with TestClient(main.app, base_url="http://localhost") as client:
        _user_row, token = _user("owner2")
        source_key, source_jwk = _enroll(client, token, "workstation-a")
        target_key, target_jwk = _enroll(client, token, "laptop-b")
        same_key = client.post(
            "/v1/baboom/devices/challenge",
            headers=_headers(token),
            json={
                "device_id": "invalid-key-reuse",
                "public_jwk": source_jwk,
                "recipient_public_jwk": source_jwk,
            },
        )
        assert same_key.status_code == 403
        command_id = hashlib.sha256(b"relay-command-2").hexdigest()
        payload = {
            "command_id": command_id, "target_device_id": "laptop-b",
            "summary": "Inspect the workshop state",
            "payload_digest": hashlib.sha256(b"metadata only").hexdigest(),
            "created_at": time.time(),
            "expires_at": time.time() + 600,
        }
        bearer_only = client.post("/v1/baboom/commands", headers=_headers(token), json=payload)
        assert bearer_only.status_code == 401
        malformed = client.get(
            "/v1/baboom/commands",
            headers={**_headers(token), "X-Baboom-Device": "workstation-a", "DPoP": "not-a-jws"},
        )
        assert malformed.status_code == 401
        submitted, _ = _request(
            client, token, "workstation-a", source_key, source_jwk,
            "POST", "/v1/baboom/commands", body=payload,
        )
        assert submitted.status_code == 200, submitted.text
        wrong_claim, _ = _request(
            client, token, "workstation-a", source_key, source_jwk,
            "POST", "/v1/baboom/commands/%s/claim" % command_id,
        )
        assert wrong_claim.status_code == 409
        secret_payload = dict(payload)
        secret_payload["command_id"] = hashlib.sha256(b"relay-command-3").hexdigest()
        secret_payload["summary"] = "token=must-not-enter-relay"
        secret, _ = _request(
            client, token, "workstation-a", source_key, source_jwk,
            "POST", "/v1/baboom/commands", body=secret_payload,
        )
        assert secret.status_code == 403

        nonce = client.post(
            "/v1/baboom/nonces", headers=_headers(token), json={"device_id": "workstation-a"},
        )
        assert nonce.status_code == 200
        query_bound = _dpop(
            source_key, source_jwk, token, nonce.json()["nonce"], "GET",
            "/v1/baboom/commands?not-allowed=1",
        )
        query_proof = client.get(
            "/v1/baboom/commands",
            headers={**_headers(token), "X-Baboom-Device": "workstation-a", "DPoP": query_bound},
        )
        assert query_proof.status_code == 401

        _other_user, other_token = _user("other")
        other_key, other_jwk = _enroll(client, other_token, "laptop-b")
        other_list, _ = _request(
            client, other_token, "laptop-b", other_key, other_jwk,
            "GET", "/v1/baboom/commands",
        )
        assert other_list.status_code == 200
        assert other_list.json()["commands"] == []


def test_companion_client_enrolls_with_server_bound_payload_and_recovers_receipts():
    if BaboomRelayClient is None:
        import pytest
        pytest.skip("ARCHHUB_BABOOM_TOOLING_ROOT not configured")
    with TestClient(main.app, base_url="http://localhost") as client:
        _user_row, token = _user("client")
        transport = _TestClientTransport(client)
        source = BaboomRelayClient(
            base_url="http://localhost",
            token_provider=lambda: token,
            signer=_TestSigner(),
            device="workstation-a",
            transport=transport,
        )
        target_custody = _TestSigner()
        target = BaboomRelayClient(
            base_url="http://localhost",
            token_provider=lambda: token,
            signer=_TestSigner(),
            recipient_key=_TestRecipient(),
            universal_custody_signer=target_custody,
            device="laptop-b",
            transport=transport,
        )
        assert source.enroll()["status"] == "active"
        assert target.enroll()["status"] == "active"
        command_id = hashlib.sha256(b"companion-client-command").hexdigest()
        submitted = source.submit_command(
            command_id=command_id,
            target_device_id="laptop-b",
            summary="Remote handoff 123456789abc; full brief remains on source device.",
            payload_digest=hashlib.sha256(b"not transmitted").hexdigest(),
            created_at=time.time(),
            expires_at=time.time() + 600,
        )
        assert submitted.state == "queued"
        assert target.list_incoming()[0].command_id == command_id
        recipient = source.recipient_key_for("laptop-b")
        assert recipient["recipient_thumbprint"] == target.recipient_key.reference.thumbprint
        assert recipient["universal_device_thumbprint"] == target_custody.reference.thumbprint
        ciphertext = b"client-transport-encrypted-brief-tag"
        envelope = {
            "version": 1,
            "ephemeral_public_jwk": _jwk(ec.generate_private_key(ec.SECP256R1())),
            "recipient_thumbprint": recipient["recipient_thumbprint"],
            "salt": _b64(secrets.token_bytes(32)),
            "nonce": _b64(secrets.token_bytes(12)),
            "ciphertext": _b64(ciphertext),
            "ciphertext_digest": hashlib.sha256(ciphertext).hexdigest(),
        }
        assert source.put_encrypted_brief(command_id, envelope)["status"] == "stored"
        assert target.claim(command_id).state == "claimed"
        assert target.fetch_encrypted_brief(command_id) == envelope
        assert target.settle(command_id, succeeded=True, outcome_code="draft-ready").state == "completed"
        assert source.list_sent()[0].state == "completed"


def test_relay_rejects_a_universal_custody_signature_from_another_key():
    with TestClient(main.app, base_url="http://localhost") as client:
        _user_row, token = _user("custody-proof")
        relay_key = ec.generate_private_key(ec.SECP256R1())
        relay_jwk = _jwk(relay_key)
        custody_key = ec.generate_private_key(ec.SECP256R1())
        custody_jwk = _jwk(custody_key)
        challenge = client.post(
            "/v1/baboom/devices/challenge",
            headers=_headers(token),
            json={
                "device_id": "custody-device",
                "public_jwk": relay_jwk,
                "universal_device_public_jwk": custody_jwk,
            },
        )
        assert challenge.status_code == 200, challenge.text
        issued = challenge.json()
        user = db.user_for_token(token)
        payload = baboom_relay.enrollment_challenge_payload(
            user_id=user["id"], challenge_id=issued["challenge_id"],
            challenge=issued["challenge"], device_id="custody-device",
            thumbprint=issued["thumbprint"],
            recipient_thumbprint=str(issued.get("recipient_thumbprint") or ""),
            universal_device_thumbprint=str(issued["universal_device_thumbprint"]),
        )
        wrong_custody_key = ec.generate_private_key(ec.SECP256R1())
        body = {
            "device_id": "custody-device",
            "public_jwk": relay_jwk,
            "universal_device_public_jwk": custody_jwk,
            "challenge_id": issued["challenge_id"],
            "challenge": issued["challenge"],
            "signature": _raw_signature(relay_key, hashlib.sha256(payload).digest()),
            "universal_device_signature": _raw_signature(
                wrong_custody_key, hashlib.sha256(payload).digest()
            ),
        }
        rejected = client.post(
            "/v1/baboom/devices/complete", headers=_headers(token), json=body,
        )
        assert rejected.status_code == 401

        body["universal_device_signature"] = _raw_signature(
            custody_key, hashlib.sha256(payload).digest()
        )
        completed = client.post(
            "/v1/baboom/devices/complete", headers=_headers(token), json=body,
        )
        assert completed.status_code == 200, completed.text
        with db.connect() as con:
            row = con.execute(
                "SELECT universal_device_thumbprint FROM baboom_devices "
                "WHERE owner_user_id=? AND device_id=?",
                (user["id"], "custody-device"),
            ).fetchone()
        assert row["universal_device_thumbprint"] == issued["universal_device_thumbprint"]


def test_encrypted_brief_is_ciphertext_only_target_claimed_and_source_revocable():
    with TestClient(main.app, base_url="http://localhost") as client:
        _user_row, token = _user("encrypted-brief")
        source_key, source_jwk = _enroll(client, token, "workstation-a")
        recipient_private = ec.generate_private_key(ec.SECP256R1())
        recipient_jwk = _jwk(recipient_private)
        target_key, target_jwk = _enroll(
            client, token, "laptop-b", recipient_public_jwk=recipient_jwk,
        )
        command_id = hashlib.sha256(b"encrypted-brief-command").hexdigest()
        task_digest = hashlib.sha256(b"brief remains ciphertext-only").hexdigest()
        command = {
            "command_id": command_id,
            "target_device_id": "laptop-b",
            "summary": "Remote handoff e2e-ciphertext; recipient brief available.",
            "payload_digest": task_digest,
            "created_at": time.time(),
            "expires_at": time.time() + 600,
        }
        submitted, _ = _request(
            client, token, "workstation-a", source_key, source_jwk,
            "POST", "/v1/baboom/commands", body=command,
        )
        assert submitted.status_code == 200, submitted.text
        recipient_key, _ = _request(
            client, token, "workstation-a", source_key, source_jwk,
            "GET", "/v1/baboom/devices/laptop-b/recipient-key",
        )
        assert recipient_key.status_code == 200, recipient_key.text
        assert recipient_key.json()["recipient_public_jwk"] == recipient_jwk
        recipient_thumbprint = recipient_key.json()["recipient_thumbprint"]
        ciphertext = b"ciphertext-only-brief-with-authentication-tag"
        envelope = {
            "version": 1,
            "ephemeral_public_jwk": _jwk(ec.generate_private_key(ec.SECP256R1())),
            "recipient_thumbprint": recipient_thumbprint,
            "salt": _b64(secrets.token_bytes(32)),
            "nonce": _b64(secrets.token_bytes(12)),
            "ciphertext": _b64(ciphertext),
            "ciphertext_digest": hashlib.sha256(ciphertext).hexdigest(),
        }
        stored, _ = _request(
            client, token, "workstation-a", source_key, source_jwk,
            "PUT", "/v1/baboom/commands/%s/brief" % command_id, body=envelope,
        )
        assert stored.status_code == 200, stored.text
        assert stored.json()["ciphertext_digest"] == envelope["ciphertext_digest"]
        prefetched, _ = _request(
            client, token, "laptop-b", target_key, target_jwk,
            "GET", "/v1/baboom/commands/%s/brief" % command_id,
        )
        assert prefetched.status_code == 200, prefetched.text
        assert prefetched.json()["envelope"] == envelope
        claimed, _ = _request(
            client, token, "laptop-b", target_key, target_jwk,
            "POST", "/v1/baboom/commands/%s/claim" % command_id,
        )
        assert claimed.status_code == 200, claimed.text
        fetched, _ = _request(
            client, token, "laptop-b", target_key, target_jwk,
            "GET", "/v1/baboom/commands/%s/brief" % command_id,
        )
        assert fetched.status_code == 200, fetched.text
        assert fetched.json()["envelope"] == envelope
        source_read, _ = _request(
            client, token, "workstation-a", source_key, source_jwk,
            "GET", "/v1/baboom/commands/%s/brief" % command_id,
        )
        assert source_read.status_code == 409
        late_revoke, _ = _request(
            client, token, "workstation-a", source_key, source_jwk,
            "DELETE", "/v1/baboom/commands/%s/brief" % command_id,
        )
        assert late_revoke.status_code == 409
        with db.connect() as con:
            row = con.execute(
                "SELECT ciphertext FROM baboom_briefs WHERE command_id=?", (command_id,)
            ).fetchone()
        assert row["ciphertext"] == envelope["ciphertext"]
        assert "brief remains ciphertext-only" not in row["ciphertext"]

        revocable_id = hashlib.sha256(b"revocable-brief-command").hexdigest()
        replacement = dict(command, command_id=revocable_id)
        replacement["created_at"] = time.time()
        replacement["expires_at"] = time.time() + 600
        submitted, _ = _request(
            client, token, "workstation-a", source_key, source_jwk,
            "POST", "/v1/baboom/commands", body=replacement,
        )
        assert submitted.status_code == 200, submitted.text
        stored, _ = _request(
            client, token, "workstation-a", source_key, source_jwk,
            "PUT", "/v1/baboom/commands/%s/brief" % revocable_id, body=envelope,
        )
        assert stored.status_code == 200, stored.text
        revoked, _ = _request(
            client, token, "workstation-a", source_key, source_jwk,
            "DELETE", "/v1/baboom/commands/%s/brief" % revocable_id,
        )
        assert revoked.status_code == 200, revoked.text
        claimed, _ = _request(
            client, token, "laptop-b", target_key, target_jwk,
            "POST", "/v1/baboom/commands/%s/claim" % revocable_id,
        )
        assert claimed.status_code == 200, claimed.text
        revoked_fetch, _ = _request(
            client, token, "laptop-b", target_key, target_jwk,
            "GET", "/v1/baboom/commands/%s/brief" % revocable_id,
        )
        assert revoked_fetch.status_code == 409
