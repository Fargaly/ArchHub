"""Real authenticated-encryption forcing for relation processing groups."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest
from cryptography.exceptions import InvalidTag

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nodelang import (  # noqa: E402
    Store,
    build_aead_stage,
    build_json_codec_stage,
    set_relation_stage,
    validate_store,
)


KEY = bytes(range(32))
KEY_REF = 'op://archhub/tests/relation-key'
AAD = 'relation:native-test'


def _resolver(expected_key=KEY):
    def resolve(ref):
        assert ref == KEY_REF
        return expected_key
    return resolve


def _encrypted_fixture():
    store = Store(secret_resolver=_resolver())
    source_value = {'kind': 'geometry', 'vertices': [[0, 0, 0], [1, 0, 0]], 'units': 'm'}
    source = store.add('value', 'source', floor={'op': 'value', 'value': source_value})
    target = store.add('op', 'encrypted sink', floor={'op': 'merge', 'fn': 'first'})
    relation = store.wire(source, target)
    encode = build_json_codec_stage(store, 'json_encode')
    encrypt = build_aead_stage(store, 'encrypt', KEY_REF, aad=AAD)
    set_relation_stage(store, relation, 'encode', encode, mode='map')
    set_relation_stage(store, relation, 'encrypt', encrypt, mode='map')
    encrypted = store.pull(relation)
    return store, relation, source_value, encrypted


def _decrypt(store, encrypted):
    source = store.add('value', 'ciphertext', floor={'op': 'value', 'value': encrypted})
    target = store.add('op', 'plain sink', floor={'op': 'merge', 'fn': 'first'})
    relation = store.wire(source, target)
    decrypt = build_aead_stage(store, 'decrypt', KEY_REF, aad=AAD)
    decode = build_json_codec_stage(store, 'json_decode')
    set_relation_stage(store, relation, 'decrypt', decrypt, mode='map')
    set_relation_stage(store, relation, 'decode', decode, mode='map')
    return store.pull(relation)


def test_aes_gcm_stages_execute_round_trip_and_key_never_enters_graph():
    store, relation, original, encrypted = _encrypted_fixture()
    assert encrypted['algorithm'] == 'AES-GCM'
    assert encrypted['ciphertext'] and encrypted['nonce']
    assert encrypted != original

    decrypt_store = Store(secret_resolver=_resolver())
    assert _decrypt(decrypt_store, encrypted) == original
    assert validate_store(store) is True
    assert validate_store(decrypt_store) is True

    serialized = json.dumps(store.dump(), sort_keys=True)
    assert KEY.hex() not in serialized
    assert repr(KEY) not in serialized
    assert KEY_REF in serialized                    # reference is visible, key is not


def test_wrong_key_and_tamper_are_rejected():
    _store, _relation, _original, encrypted = _encrypted_fixture()
    wrong = Store(secret_resolver=_resolver(bytes(reversed(range(32)))))
    with pytest.raises(InvalidTag):
        _decrypt(wrong, encrypted)

    tampered = copy.deepcopy(encrypted)
    text = tampered['ciphertext']
    tampered['ciphertext'] = ('A' if text[0] != 'A' else 'B') + text[1:]
    with pytest.raises(InvalidTag):
        _decrypt(Store(secret_resolver=_resolver()), tampered)


def test_missing_secret_resolver_fails_closed():
    _store, _relation, _original, encrypted = _encrypted_fixture()
    with pytest.raises(RuntimeError, match='no external secret resolver'):
        _decrypt(Store(), encrypted)
