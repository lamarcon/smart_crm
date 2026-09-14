from __future__ import annotations

import hashlib
import hmac
import os

import pytest

from app.security.secrets import (
    CRYPTPROTECT_LOCAL_MACHINE,
    CRYPTPROTECT_UI_FORBIDDEN,
    DpapiFileSecretProvider,
    DpapiProtector,
    EnvironmentSecretProvider,
    InMemorySecretProvider,
    SecretNotFoundError,
    SecretProtectionError,
    SecretReferenceError,
)


class IdentityProtector:
    def __init__(self, identity: bytes) -> None:
        self.identity = identity

    def protect(self, plaintext: bytes) -> bytes:
        signature = hmac.new(self.identity, plaintext, hashlib.sha256).digest()
        return signature + bytes(value ^ self.identity[0] for value in plaintext)

    def unprotect(self, ciphertext: bytes) -> bytes:
        signature, encrypted = ciphertext[:32], ciphertext[32:]
        plaintext = bytes(value ^ self.identity[0] for value in encrypted)
        if not hmac.compare_digest(signature, hmac.new(self.identity, plaintext, hashlib.sha256).digest()):
            raise SecretProtectionError("secret cannot be decrypted by this service identity")
        return plaintext


def test_in_memory_provider_round_trips_without_exposing_values() -> None:
    provider = InMemorySecretProvider()

    provider.put_database_secret("tenant-a", "postgresql://user:password@db/a")

    assert provider.get_database_secret("tenant-a") == "postgresql://user:password@db/a"
    assert "password" not in repr(provider)


def test_in_memory_provider_reports_missing_reference() -> None:
    provider = InMemorySecretProvider()

    with pytest.raises(SecretNotFoundError, match="tenant-missing"):
        provider.get_database_secret("tenant-missing")


def test_in_memory_provider_rotates_existing_reference() -> None:
    provider = InMemorySecretProvider({"tenant-a": "first"})

    provider.put_database_secret("tenant-a", "second")

    assert provider.get_database_secret("tenant-a") == "second"


def test_in_memory_provider_deletes_reference() -> None:
    provider = InMemorySecretProvider({"tenant-a": "value"})

    provider.delete_database_secret("tenant-a")

    with pytest.raises(SecretNotFoundError):
        provider.get_database_secret("tenant-a")


def test_environment_provider_resolves_only_the_named_reference(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SMART_CRM_TENANT_SECRET_TENANT_A", "tenant-a-secret")
    monkeypatch.setenv("SMART_CRM_TENANT_SECRET_TENANT_B", "tenant-b-secret")
    provider = EnvironmentSecretProvider()

    assert provider.get_database_secret("tenant-a") == "tenant-a-secret"
    assert "tenant-b-secret" not in repr(provider)


def test_environment_provider_is_read_only() -> None:
    provider = EnvironmentSecretProvider()

    with pytest.raises(TypeError, match="read-only"):
        provider.put_database_secret("tenant-a", "secret")
    with pytest.raises(TypeError, match="read-only"):
        provider.delete_database_secret("tenant-a")


def test_dpapi_file_provider_persists_only_ciphertext(tmp_path) -> None:
    provider = DpapiFileSecretProvider(tmp_path, protector=IdentityProtector(b"A"))
    plaintext = "postgresql://user:plain-password@db/tenant"

    provider.put_database_secret("tenant-a", plaintext)

    stored = (tmp_path / "tenant-a.bin").read_bytes()
    assert plaintext.encode() not in stored
    assert provider.get_database_secret("tenant-a") == plaintext


def test_dpapi_file_provider_rejects_wrong_service_identity(tmp_path) -> None:
    writer = DpapiFileSecretProvider(tmp_path, protector=IdentityProtector(b"A"))
    reader = DpapiFileSecretProvider(tmp_path, protector=IdentityProtector(b"B"))
    writer.put_database_secret("tenant-a", "protected")

    with pytest.raises(SecretProtectionError):
        reader.get_database_secret("tenant-a")


def test_dpapi_file_provider_rejects_corrupted_ciphertext(tmp_path) -> None:
    provider = DpapiFileSecretProvider(tmp_path, protector=IdentityProtector(b"A"))
    provider.put_database_secret("tenant-a", "protected")
    (tmp_path / "tenant-a.bin").write_bytes(b"corrupted")

    with pytest.raises(SecretProtectionError):
        provider.get_database_secret("tenant-a")


def test_secret_reference_cannot_escape_provider_root(tmp_path) -> None:
    provider = DpapiFileSecretProvider(tmp_path, protector=IdentityProtector(b"A"))

    with pytest.raises(SecretReferenceError):
        provider.put_database_secret("../tenant-a", "secret")
    with pytest.raises(SecretReferenceError):
        provider.get_database_secret("tenant/a")


def test_native_dpapi_uses_current_user_scope_and_detects_tampering() -> None:
    assert CRYPTPROTECT_UI_FORBIDDEN & CRYPTPROTECT_LOCAL_MACHINE == 0
    if os.name != "nt":
        with pytest.raises(OSError, match="Windows"):
            DpapiProtector()
        return
    protector = DpapiProtector()
    ciphertext = protector.protect(b"service-bound-secret")

    assert protector.flags == CRYPTPROTECT_UI_FORBIDDEN
    assert protector.flags & CRYPTPROTECT_LOCAL_MACHINE == 0
    assert protector.unprotect(ciphertext) == b"service-bound-secret"
    with pytest.raises(SecretProtectionError):
        protector.unprotect(ciphertext[:-1] + bytes([ciphertext[-1] ^ 1]))
