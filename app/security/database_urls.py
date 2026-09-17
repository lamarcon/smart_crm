"""Fail-closed transport policy for tenant PostgreSQL database URLs."""

from __future__ import annotations

import os

from collections.abc import Mapping
from typing import Any

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


INSECURE_TENANT_LOOPBACK_ENV = "SMART_CRM_ALLOW_INSECURE_TENANT_LOOPBACK"
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_GENERIC_ERROR = "database transport is not permitted"


class DatabaseTransportSecurityError(ValueError):
    """Raised without echoing connection details when transport is unsafe."""


def insecure_tenant_loopback_enabled(
    environ: Mapping[str, str] | None = None,
) -> bool:
    """Enable insecure tenant loopback only for the exact local opt-in literal."""

    source = os.environ if environ is None else environ
    return source.get(INSECURE_TENANT_LOOPBACK_ENV) == "1"


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
