"""AWS KMS HMAC custody courts for shared Universal runtime signing."""
from __future__ import annotations

import hashlib
import hmac
import os

import pytest

import nodelang.cell_secret_keys as cell_secret_keys
from nodelang.cell_secret_keys import SigningKeyError


_KEY_ID = "archhub.local.relationship-authority"
_ARN_V1 = (
    "arn:aws:kms:me-central-1:111122223333:"
    "key/11111111-1111-1111-1111-111111111111"
)
_ARN_V2 = (
    "arn:aws:kms:me-central-1:111122223333:"
    "key/22222222-2222-2222-2222-222222222222"
)


class _InvalidMac(Exception):
    pass


class _FakeKmsClient:
    class exceptions:
        KMSInvalidMacException = _InvalidMac

    def __init__(self):
        self._secrets = {
            _ARN_V1: b"1" * 32,
            _ARN_V2: b"2" * 32,
        }
        self.requests = []

    def generate_mac(self, **request):
        self.requests.append(("generate", dict(request)))
        secret = self._secrets[request["KeyId"]]
        mac = hmac.new(secret, request["Message"], hashlib.sha256).digest()
        return {
            "KeyId": request["KeyId"],
            "Mac": mac,
            "MacAlgorithm": request["MacAlgorithm"],
        }

    def verify_mac(self, **request):
        self.requests.append(("verify", dict(request)))
        secret = self._secrets[request["KeyId"]]
        expected = hmac.new(
            secret,
            request["Message"],
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(expected, request["Mac"]):
            raise _InvalidMac("invalid")
        return {
            "KeyId": request["KeyId"],
            "MacValid": True,
            "MacAlgorithm": request["MacAlgorithm"],
        }


def _provider_type():
    provider_type = getattr(
        cell_secret_keys,
        "AwsKmsHmacSigningKeyProvider",
        None,
    )
    assert provider_type is not None, "AWS KMS HMAC provider is not implemented"
    return provider_type


def test_kms_provider_uses_versioned_nonexporting_mac_capability():
    client = _FakeKmsClient()
    provider = _provider_type()(
        {_KEY_ID: {1: _ARN_V1, 2: _ARN_V2}},
        client=client,
    )
    payload = bytes(range(256)) * 64

    assert provider.current_reference(_KEY_ID).version == 2
    signature = provider.sign(_KEY_ID, 1, payload)
    assert len(signature) == 64
    assert provider.verify(_KEY_ID, 1, payload, signature) is True
    assert provider.verify(_KEY_ID, 2, payload, signature) is False
    assert not hasattr(provider, "resolve")
    assert not hasattr(provider, "current")

    expected_message = (
        b"ArchHub/aws-kms-hmac-provider/v1\x00"
        + hashlib.sha256(payload).digest()
    )
    assert client.requests[0] == (
        "generate",
        {
            "KeyId": _ARN_V1,
            "Message": expected_message,
            "MacAlgorithm": "HMAC_SHA_256",
        },
    )


def test_kms_provider_fails_closed_for_unknown_keys_versions_and_signatures():
    provider = _provider_type()(
        {_KEY_ID: {1: _ARN_V1}},
        client=_FakeKmsClient(),
    )
    with pytest.raises(SigningKeyError, match="unknown"):
        provider.current_reference("unknown")
    with pytest.raises(SigningKeyError, match="unknown"):
        provider.sign(_KEY_ID, 2, b"payload")
    assert provider.verify(_KEY_ID, 1, b"payload", "not-hex") is False
    assert provider.verify(_KEY_ID, 1, b"payload", "00" * 32) is False


def test_kms_provider_requires_exact_arns_and_never_renders_provider_errors():
    provider_type = _provider_type()
    with pytest.raises(SigningKeyError, match="ARN"):
        provider_type({_KEY_ID: {1: "alias/not-an-arn"}}, client=object())

    class FailingClient:
        def generate_mac(self, **_request):
            raise RuntimeError("AWS_SECRET_ACCESS_KEY=never-render")

    provider = provider_type(
        {_KEY_ID: {1: _ARN_V1}},
        client=FailingClient(),
    )
    with pytest.raises(SigningKeyError) as captured:
        provider.sign(_KEY_ID, 1, b"payload")
    assert "never-render" not in str(captured.value)
    assert "AWS_SECRET_ACCESS_KEY" not in str(captured.value)


@pytest.mark.skipif(
    not os.environ.get("ARCHHUB_TEST_AWS_KMS_HMAC_KEY_ARN"),
    reason="real AWS KMS HMAC key ARN and workload identity are not configured",
)
def test_real_aws_kms_hmac_round_trip_through_workload_identity():
    key_arn = os.environ["ARCHHUB_TEST_AWS_KMS_HMAC_KEY_ARN"]
    provider = _provider_type()({_KEY_ID: {1: key_arn}})
    payload = os.urandom(8192)

    signature = provider.sign(_KEY_ID, 1, payload)

    assert provider.verify(_KEY_ID, 1, payload, signature) is True
    assert provider.verify(_KEY_ID, 1, payload + b"x", signature) is False
