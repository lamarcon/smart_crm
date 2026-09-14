"""Password hashing and opaque-session primitives."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
from secrets import token_urlsafe

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from argon2.low_level import Type


MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 128

ARGON2_TIME_COST = 3
ARGON2_MEMORY_COST = 65_536
ARGON2_PARALLELISM = 4
ARGON2_HASH_LENGTH = 32
ARGON2_SALT_LENGTH = 16

SESSION_TOKEN_BYTES = 32
IDLE_SESSION_TTL = timedelta(minutes=30)
ABSOLUTE_SESSION_TTL = timedelta(hours=12)

_PASSWORD_HASHER = PasswordHasher(
    time_cost=ARGON2_TIME_COST,
    memory_cost=ARGON2_MEMORY_COST,
    parallelism=ARGON2_PARALLELISM,
    hash_len=ARGON2_HASH_LENGTH,
    salt_len=ARGON2_SALT_LENGTH,
    type=Type.ID,
)
_DUMMY_PASSWORD_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$k6sM9wc0CS5hDN+Rcsi+pw$"
    "JFEnWMiw8wbMkDQHpJ066UxQ2rdyo/3C2INlaMQMlaE"
)


class PasswordPolicyError(ValueError):
    """Raised when a new password falls outside the supported bounds."""


@dataclass(frozen=True)
class SessionExpiry:
    idle_expires_at: datetime
    absolute_expires_at: datetime


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("session timestamps must be timezone-aware")


def _validate_new_password(password: str) -> None:
    if not isinstance(password, str) or not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
        raise PasswordPolicyError("password must contain 12 to 128 characters")


def hash_password(password: str) -> str:
    """Hash a bounded password with Argon2id and a fresh random salt."""

    _validate_new_password(password)
    return _PASSWORD_HASHER.hash(password)


def verify_password(encoded_hash: str, password: str) -> bool:
    """Verify without leaking malformed hashes through exceptions."""

    try:
        return _PASSWORD_HASHER.verify(encoded_hash, password)
    except (InvalidHashError, VerificationError, TypeError):
        return False


def verify_or_dummy(encoded_hash: str | None, password: str) -> bool:
    """Always perform one Argon2id verification for known and unknown subjects."""

    return verify_password(encoded_hash or _DUMMY_PASSWORD_HASH, password)


def new_session_token() -> str:
    """Return a URL-safe opaque token backed by 256 random bits."""

    return token_urlsafe(SESSION_TOKEN_BYTES)


def digest_session_token(token: str) -> str:
    """Return the only representation that may be stored server-side."""

    return sha256(token.encode("utf-8")).hexdigest()


def new_session_expiry(now: datetime) -> SessionExpiry:
    _require_aware(now)
    return SessionExpiry(
        idle_expires_at=now + IDLE_SESSION_TTL,
        absolute_expires_at=now + ABSOLUTE_SESSION_TTL,
    )


def session_is_active(
    *,
    now: datetime,
    idle_expires_at: datetime,
    absolute_expires_at: datetime,
    revoked_at: datetime | None,
) -> bool:
    _require_aware(now)
    _require_aware(idle_expires_at)
    _require_aware(absolute_expires_at)
    if revoked_at is not None:
        _require_aware(revoked_at)
        return False
    return now < idle_expires_at and now < absolute_expires_at
