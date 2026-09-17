"""Fail-closed transport policy for tenant PostgreSQL database URLs."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_GENERIC_ERROR = "database transport is not permitted"


class DatabaseTransportSecurityError(ValueError):
    """Raised without echoing connection details when transport is unsafe."""


def _single_query_value(query: Mapping[str, Any], key: str) -> str | None:
    value = query.get(key)
    if not isinstance(value, str) or not value.strip():
        return None
    return value


def validate_tenant_database_url(
    database_url: str,
    *,
    allow_insecure_loopback: bool = False,
) -> str:
    """Return a tenant DSN only when its transport policy is explicit and safe."""

    try:
        url = make_url(database_url)
        if url.get_backend_name() != "postgresql":
            raise DatabaseTransportSecurityError(_GENERIC_ERROR)
        host = (url.host or "").casefold().rstrip(".")
        sslmode = _single_query_value(url.query, "sslmode")
        sslrootcert = _single_query_value(url.query, "sslrootcert")
        if sslmode == "verify-full" and sslrootcert is not None:
            return database_url
        if allow_insecure_loopback and host in _LOOPBACK_HOSTS:
            return database_url
    except DatabaseTransportSecurityError:
        raise
    except (ArgumentError, TypeError, ValueError):
        pass
    raise DatabaseTransportSecurityError(_GENERIC_ERROR)
