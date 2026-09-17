from __future__ import annotations

import pytest

from app.security.database_urls import (
    DatabaseTransportSecurityError,
    validate_tenant_database_url,
)


REMOTE = "postgresql+psycopg://tenant:top-secret@db.example.test/tenant"


@pytest.mark.parametrize(
    "query",
    [
        "",
        "?sslmode=require&sslrootcert=C%3A%5Cca%5Croot.crt",
        "?sslmode=verify-ca&sslrootcert=C%3A%5Cca%5Croot.crt",
        "?sslmode=verify-full",
    ],
)
def test_remote_database_requires_verify_full_and_root_ca(query: str) -> None:
    with pytest.raises(DatabaseTransportSecurityError, match="database transport is not permitted") as raised:
        validate_tenant_database_url(REMOTE + query)

    assert "top-secret" not in str(raised.value)
    assert "db.example.test" not in str(raised.value)


def test_remote_database_accepts_verified_certificate_and_hostname() -> None:
    secured = REMOTE + "?sslmode=verify-full&sslrootcert=C%3A%5Cca%5Croot.crt"

    assert validate_tenant_database_url(secured) == secured


@pytest.mark.parametrize(
    "query",
    [
        "?sslmode=verify-full&sslmode=disable&sslrootcert=C%3A%5Cca%5Croot.crt",
        "?sslmode=verify-full&sslrootcert=C%3A%5Cca%5Cone.crt&sslrootcert=C%3A%5Cca%5Ctwo.crt",
    ],
)
def test_duplicate_tls_parameters_cannot_downgrade_validation(query: str) -> None:
    with pytest.raises(DatabaseTransportSecurityError, match="database transport is not permitted"):
        validate_tenant_database_url(REMOTE + query)


def test_insecure_loopback_requires_explicit_development_opt_in() -> None:
    local = "postgresql+psycopg://tenant:local@127.0.0.1:5432/tenant"

    with pytest.raises(DatabaseTransportSecurityError, match="database transport is not permitted"):
        validate_tenant_database_url(local)

    assert validate_tenant_database_url(local, allow_insecure_loopback=True) == local


def test_loopback_opt_in_does_not_allow_insecure_remote_hosts() -> None:
    with pytest.raises(DatabaseTransportSecurityError, match="database transport is not permitted"):
        validate_tenant_database_url(REMOTE, allow_insecure_loopback=True)


def test_non_postgresql_urls_fail_closed_without_echoing_secret() -> None:
    database_url = "mysql://tenant:top-secret@db.example.test/tenant"

    with pytest.raises(DatabaseTransportSecurityError, match="database transport is not permitted") as raised:
        validate_tenant_database_url(database_url)

    assert "top-secret" not in str(raised.value)
