from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from argon2 import extract_parameters

from app.security.passwords import (
    ABSOLUTE_SESSION_TTL,
    ARGON2_MEMORY_COST,
    ARGON2_PARALLELISM,
    ARGON2_TIME_COST,
    IDLE_SESSION_TTL,
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
    PasswordPolicyError,
    digest_session_token,
    hash_password,
    new_session_expiry,
    new_session_token,
    session_is_active,
    verify_or_dummy,
    verify_password,
)


NOW = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)


def test_password_hash_uses_argon2id_with_unique_salts() -> None:
    first = hash_password("correct horse battery staple")
    second = hash_password("correct horse battery staple")

    assert first.startswith("$argon2id$")
    assert second.startswith("$argon2id$")
    assert first != second
    parameters = extract_parameters(first)
    assert parameters.memory_cost == ARGON2_MEMORY_COST == 65_536
    assert parameters.time_cost == ARGON2_TIME_COST == 3
    assert parameters.parallelism == ARGON2_PARALLELISM == 4


@pytest.mark.parametrize("length", [MIN_PASSWORD_LENGTH, MAX_PASSWORD_LENGTH])
def test_password_policy_accepts_inclusive_bounds(length: int) -> None:
    password = "x" * length

    assert verify_password(hash_password(password), password) is True


@pytest.mark.parametrize("length", [MIN_PASSWORD_LENGTH - 1, MAX_PASSWORD_LENGTH + 1])
def test_password_policy_rejects_outside_bounds(length: int) -> None:
    with pytest.raises(PasswordPolicyError, match="12 to 128"):
        hash_password("x" * length)


def test_password_is_not_truncated_before_hashing() -> None:
    password = "x" * MAX_PASSWORD_LENGTH
    encoded = hash_password(password)

    assert verify_password(encoded, password) is True
    assert verify_password(encoded, password[:-1]) is False


def test_password_verification_rejects_wrong_or_malformed_hash() -> None:
    encoded = hash_password("correct horse battery staple")

    assert verify_password(encoded, "wrong password value") is False
    assert verify_password("not-an-argon2-hash", "correct horse battery staple") is False


def test_unknown_subject_runs_dummy_verification(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []

    def record_verify(encoded_hash: str, password: str) -> bool:
        calls.append((encoded_hash, password))
        return False

    monkeypatch.setattr("app.security.passwords.verify_password", record_verify)

    assert verify_or_dummy(None, "correct horse battery staple") is False
    assert len(calls) == 1
    assert calls[0][0].startswith("$argon2id$")
    assert calls[0][1] == "correct horse battery staple"


def test_known_subject_uses_supplied_hash_once(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []

    def record_verify(encoded_hash: str, password: str) -> bool:
        calls.append((encoded_hash, password))
        return True

    monkeypatch.setattr("app.security.passwords.verify_password", record_verify)

    assert verify_or_dummy("$argon2id$known", "correct horse battery staple") is True
    assert calls == [("$argon2id$known", "correct horse battery staple")]


def test_session_token_has_at_least_128_bits_and_is_not_reused() -> None:
    first = new_session_token()
    second = new_session_token()

    assert len(first) >= 22
    assert first != second


def test_session_digest_is_sha256_and_does_not_contain_token() -> None:
    token = new_session_token()
    digest = digest_session_token(token)

    assert len(digest) == 64
    assert digest == digest_session_token(token)
    assert token not in digest


def test_session_expiry_matches_idle_and_absolute_limits() -> None:
    expiry = new_session_expiry(NOW)

    assert IDLE_SESSION_TTL == timedelta(minutes=30)
    assert ABSOLUTE_SESSION_TTL == timedelta(hours=12)
    assert expiry.idle_expires_at == NOW + timedelta(minutes=30)
    assert expiry.absolute_expires_at == NOW + timedelta(hours=12)


def test_active_session_requires_both_expiry_windows() -> None:
    assert session_is_active(
        now=NOW,
        idle_expires_at=NOW + timedelta(seconds=1),
        absolute_expires_at=NOW + timedelta(seconds=1),
        revoked_at=None,
    ) is True

    assert session_is_active(
        now=NOW,
        idle_expires_at=NOW,
        absolute_expires_at=NOW + timedelta(hours=1),
        revoked_at=None,
    ) is False
    assert session_is_active(
        now=NOW,
        idle_expires_at=NOW + timedelta(minutes=1),
        absolute_expires_at=NOW,
        revoked_at=None,
    ) is False


def test_revoked_session_is_inactive_before_expiry() -> None:
    assert session_is_active(
        now=NOW,
        idle_expires_at=NOW + timedelta(minutes=30),
        absolute_expires_at=NOW + timedelta(hours=12),
        revoked_at=NOW - timedelta(seconds=1),
    ) is False


def test_session_time_helpers_require_aware_utc_datetimes() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        new_session_expiry(datetime(2026, 9, 14, 12, 0))

    with pytest.raises(ValueError, match="timezone-aware"):
        session_is_active(
            now=datetime(2026, 9, 14, 12, 0),
            idle_expires_at=NOW,
            absolute_expires_at=NOW,
            revoked_at=None,
        )
