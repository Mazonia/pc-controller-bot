import pytest
from fleet_relay import FleetCrypto, get_network_info


def test_crypto_encryption_and_decryption():
    secret = "test-secret-key-12345"
    crypto = FleetCrypto(secret)

    payload = {"cmd": "screenshot", "id": "abc123", "params": {"chat_id": 999}}
    encrypted = crypto.encrypt(payload)

    assert isinstance(encrypted, bytes)
    assert len(encrypted) > 28

    decrypted = crypto.decrypt(encrypted)
    assert decrypted == payload


def test_crypto_different_nonces():
    crypto = FleetCrypto("same-secret")
    payload = {"test": 1}

    enc1 = crypto.encrypt(payload)
    enc2 = crypto.encrypt(payload)

    # Different random 12-byte nonce every time
    assert enc1 != enc2
    assert crypto.decrypt(enc1) == payload
    assert crypto.decrypt(enc2) == payload


def test_crypto_invalid_payload():
    crypto = FleetCrypto("my-secret")
    assert crypto.decrypt(b"short") is None
    assert crypto.decrypt(b"0" * 30) is None


def test_crypto_mismatched_secret():
    crypto1 = FleetCrypto("secret-1")
    crypto2 = FleetCrypto("secret-2")

    encrypted = crypto1.encrypt({"message": "top secret"})
    decrypted = crypto2.decrypt(encrypted)
    assert decrypted is None


def test_get_network_info():
    info = get_network_info()
    assert "ip" in info
    assert "type" in info
    assert isinstance(info["ip"], str)
    assert isinstance(info["type"], str)
