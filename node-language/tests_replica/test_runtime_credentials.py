"""Windows custody court for browser capabilities across worker handoff."""
import os

import pytest

from nodelang.cell_secret_keys import SigningKeyError
from nodelang.runtime_credentials import BrowserCredentialVault


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI court")
def test_browser_credentials_survive_restart_without_plaintext_on_disk(tmp_path):
    path = tmp_path / "browser.dpapi"
    first = BrowserCredentialVault(path).load_or_create()
    ciphertext = path.read_bytes()
    assert first.token.encode("utf-8") not in ciphertext
    assert first.csrf_token.encode("utf-8") not in ciphertext
    assert first.custody_id.encode("utf-8") not in ciphertext
    assert BrowserCredentialVault(path).load_or_create() == first


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI court")
def test_browser_credential_custody_rejects_tamper_and_path_substitution(tmp_path):
    path = tmp_path / "browser.dpapi"
    BrowserCredentialVault(path).load_or_create()
    ciphertext = path.read_bytes()
    path.write_bytes(ciphertext[:-1] + bytes((ciphertext[-1] ^ 1,)))
    with pytest.raises(SigningKeyError):
        BrowserCredentialVault(path).load_or_create()

    original = tmp_path / "original.dpapi"
    BrowserCredentialVault(original).load_or_create()
    substituted = tmp_path / "substituted.dpapi"
    substituted.write_bytes(original.read_bytes())
    with pytest.raises(SigningKeyError):
        BrowserCredentialVault(substituted).load_or_create()
