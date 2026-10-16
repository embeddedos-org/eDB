# SPDX-License-Identifier: MIT
"""Unit tests for AES-256-GCM field encryption (issue #88 coverage drive).

Covers edb/security/encryption.py — the data-at-rest counterpart to
the audit-log slice: key handling (generated, raw bytes, password
derived via PBKDF2), round trips, nonce uniqueness, tamper and
wrong-key failure, and the dict-field helpers' contract (only named
string fields are touched, undecryptable values are left as-is).
"""

import base64

import pytest
from cryptography.exceptions import InvalidTag

from edb.security.encryption import EncryptionManager


class TestKeyHandling:
    def test_generated_key_is_256_bit(self):
        mgr = EncryptionManager()
        assert len(mgr.key) == EncryptionManager.KEY_SIZE == 32

    def test_generated_keys_are_random(self):
        assert EncryptionManager().key != EncryptionManager().key

    def test_raw_bytes_key_round_trip(self):
        key = bytes(range(32))
        mgr = EncryptionManager(key)
        assert mgr.key == key
        assert mgr.decrypt(mgr.encrypt("secret")) == "secret"

    def test_same_key_decrypts_across_instances(self):
        key = EncryptionManager().key
        token = EncryptionManager(key).encrypt("shared")
        assert EncryptionManager(key).decrypt(token) == "shared"

    def test_invalid_key_length_refused(self):
        with pytest.raises(ValueError):
            EncryptionManager(b"too-short")


class TestRoundTrip:
    def test_round_trip(self):
        mgr = EncryptionManager()
        assert mgr.decrypt(mgr.encrypt("hello world")) == "hello world"

    def test_empty_and_unicode_round_trip(self):
        mgr = EncryptionManager()
        assert mgr.decrypt(mgr.encrypt("")) == ""
        text = "données sensibles — 機密"
        assert mgr.decrypt(mgr.encrypt(text)) == text

    def test_nonce_uniqueness(self):
        mgr = EncryptionManager()
        one, two = mgr.encrypt("same plaintext"), mgr.encrypt("same plaintext")
        assert one != two  # fresh random nonce per encryption
        assert mgr.decrypt(one) == mgr.decrypt(two) == "same plaintext"

    def test_password_derived_round_trip(self):
        mgr = EncryptionManager("correct horse battery staple")
        token = mgr.encrypt("password-protected")
        assert mgr.decrypt(token) == "password-protected"

    def test_password_ciphertext_carries_its_salt(self):
        # A second manager with the same password must be able to
        # decrypt: the salt travels with the ciphertext.
        token = EncryptionManager("pw").encrypt("portable")
        assert EncryptionManager("pw").decrypt(token) == "portable"

    def test_wrong_password_fails(self):
        token = EncryptionManager("right").encrypt("nope")
        with pytest.raises(InvalidTag):
            EncryptionManager("wrong").decrypt(token)


class TestTamperResistance:
    def test_wrong_key_fails(self):
        token = EncryptionManager().encrypt("integrity")
        with pytest.raises(InvalidTag):
            EncryptionManager().decrypt(token)

    def test_tampered_ciphertext_fails(self):
        mgr = EncryptionManager()
        raw = bytearray(base64.b64decode(mgr.encrypt("integrity")))
        raw[-1] ^= 0x01
        with pytest.raises(InvalidTag):
            mgr.decrypt(base64.b64encode(bytes(raw)).decode("utf-8"))

    def test_garbage_input_fails(self):
        mgr = EncryptionManager()
        with pytest.raises(Exception):
            mgr.decrypt("!!! not base64 !!!")


class TestDictFields:
    def test_encrypt_dict_fields_touches_only_named_strings(self):
        mgr = EncryptionManager()
        data = {"name": "alice", "ssn": "123-45-6789", "visits": 3}
        out = mgr.encrypt_dict_fields(data, ["ssn", "visits", "missing"])
        assert out["name"] == "alice"
        assert out["visits"] == 3  # non-string values are left alone
        assert out["ssn"] != "123-45-6789"
        assert mgr.decrypt(out["ssn"]) == "123-45-6789"
        assert data["ssn"] == "123-45-6789"  # caller's dict not mutated

    def test_decrypt_dict_fields_round_trip(self):
        mgr = EncryptionManager()
        data = {"secret": "shh", "plain": "visible"}
        enc = mgr.encrypt_dict_fields(data, ["secret"])
        dec = mgr.decrypt_dict_fields(enc, ["secret", "plain"])
        assert dec == data

    def test_decrypt_dict_fields_leaves_undecryptable_values(self):
        mgr = EncryptionManager()
        data = {"secret": "not-a-ciphertext"}
        out = mgr.decrypt_dict_fields(data, ["secret"])
        assert out["secret"] == "not-a-ciphertext"  # warning path, no raise
