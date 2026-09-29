"""Provision and serve the authenticated local Compose acceptance fixture."""

from __future__ import annotations

import os
import re
import select
import socket
import socketserver
import threading
from datetime import datetime, timezone
from uuid import UUID

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from app.security.passwords import hash_password
from app.security.secrets import EnvironmentSecretProvider
from app.server import bootstrap_runtime, create_app as create_runtime_app


TENANT_ID = UUID("28c87ae3-16cc-5bbc-bc80-2da9f5acbd6e")
TENANT_SLUG = "compose-tenant"
TENANT_SECRET_REF = "compose-tenant"
TENANT_SCHEMA_CONTRACT = "tenant-v1"
WORKSPACE_ID = "default"
ADMIN_ID = "verify-user-1"
ADMIN_EMAIL = "verify-compose@smartcrm.local"
ADMIN_PASSWORD = "compose-only-password"
_DATABASE_NAME = re.compile(r"[a-z][a-z0-9_]{0,62}\Z")
_PROXY_SERVER: socketserver.ThreadingTCPServer | None = None
_PROXY_LOCK = threading.Lock()


def _required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"compose fixture requires {name}")
    return value


def _database_name(name: str) -> str:
    value = _required(name)
    if not _DATABASE_NAME.fullmatch(value):
        raise RuntimeError(f"compose fixture received invalid {name}")
    return value


def _ensure_database(admin_url: str, database_name: str) -> None:
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            exists = connection.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :database_name"),
                {"database_name": database_name},
            )
            if exists is None:
                connection.exec_driver_sql(f'CREATE DATABASE "{database_name}"')
    finally:
        engine.dispose()


def _upgrade(config_path: str, database_url: str, environment_name: str) -> None:
    previous = os.environ.get(environment_name)
    os.environ[environment_name] = database_url
    try:
        command.upgrade(Config(config_path), "head")
    finally:
        if previous is None:
            os.environ.pop(environment_name, None)
        else:
            os.environ[environment_name] = previous


def _seed_tenant(database_url: str) -> None:
    password_hash = hash_password(ADMIN_PASSWORD)
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text("SELECT set_config('smartcrm.workspace_id', :workspace_id, true)"),
                {"workspace_id": WORKSPACE_ID},
            )
            connection.execute(
                text(
                    "INSERT INTO tenant_identity "
                    "(singleton_key, control_tenant_id, workspace_id, schema_contract) "
                    "VALUES ('identity', :tenant_id, :workspace_id, :schema_contract) "
                    "ON CONFLICT (singleton_key) DO UPDATE SET "
                    "control_tenant_id = EXCLUDED.control_tenant_id, "
                    "workspace_id = EXCLUDED.workspace_id, "
                    "schema_contract = EXCLUDED.schema_contract"
                ),
                {
                    "tenant_id": TENANT_ID,
                    "workspace_id": WORKSPACE_ID,
                    "schema_contract": TENANT_SCHEMA_CONTRACT,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO crm_users "
                    "(id, workspace_id, name, email, normalized_email, password_hash, "
                    "auth_enabled, auth_version, job_title, role, status, payload) "
                    "VALUES (:id, :workspace_id, :name, :email, :email, :password_hash, "
                    "true, 0, :job_title, 'Administrador', 'Ativo', CAST(:payload AS jsonb)) "
                    "ON CONFLICT (id) DO UPDATE SET "
                    "name = EXCLUDED.name, email = EXCLUDED.email, "
                    "normalized_email = EXCLUDED.normalized_email, "
                    "password_hash = EXCLUDED.password_hash, auth_enabled = true, "
                    "job_title = EXCLUDED.job_title, role = 'Administrador', "
                    "status = 'Ativo', deleted_at = NULL"
                ),
                {
                    "id": ADMIN_ID,
                    "workspace_id": WORKSPACE_ID,
                    "name": "Verificador Compose",
                    "email": ADMIN_EMAIL,
                    "password_hash": password_hash,
                    "job_title": "Administrador",
                    "payload": '{"position":0,"record":{}}',
                },
            )
    finally:
        engine.dispose()


def _seed_control(database_url: str, tenant_revision: str) -> None:
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO control_tenants "
                    "(id, slug, display_name, status, secret_ref, profile_version, "
                    "expected_tenant_revision, activated_at) "
                    "VALUES (:id, :slug, :display_name, 'active', :secret_ref, 1, "
                    ":revision, :activated_at) "
                    "ON CONFLICT (id) DO UPDATE SET "
                    "slug = EXCLUDED.slug, display_name = EXCLUDED.display_name, "
                    "status = 'active', secret_ref = EXCLUDED.secret_ref, "
                    "expected_tenant_revision = EXCLUDED.expected_tenant_revision, "
                    "activated_at = COALESCE(control_tenants.activated_at, EXCLUDED.activated_at)"
                ),
                {
                    "id": TENANT_ID,
                    "slug": TENANT_SLUG,
                    "display_name": "Compose Tenant",
                    "secret_ref": TENANT_SECRET_REF,
                    "revision": tenant_revision,
                    "activated_at": datetime.now(timezone.utc),
                },
            )
    finally:
        engine.dispose()


def provision() -> None:
    """Create only the two dedicated local databases and idempotent fixture rows."""

    admin_url = _required("SMART_CRM_COMPOSE_ADMIN_DATABASE_URL")
    control_name = _database_name("SMART_CRM_COMPOSE_CONTROL_DB_NAME")
    tenant_name = _database_name("SMART_CRM_COMPOSE_TENANT_DB_NAME")
    control_url = _required("SMART_CRM_CONTROL_DATABASE_URL")
    tenant_url = _required("SMART_CRM_DATABASE_URL")

    _ensure_database(admin_url, control_name)
    _ensure_database(admin_url, tenant_name)
    _upgrade("alembic-control.ini", control_url, "SMART_CRM_CONTROL_DATABASE_URL")
    _upgrade("alembic.ini", tenant_url, "SMART_CRM_DATABASE_URL")
    _seed_tenant(tenant_url)
    tenant_engine = create_engine(tenant_url)
    try:
        with tenant_engine.connect() as connection:
            tenant_revision = str(
                connection.scalar(text("SELECT version_num FROM alembic_version"))
            )
    finally:
        tenant_engine.dispose()
    _seed_control(control_url, tenant_revision)


class _ProxyHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        target_host = _required("SMART_CRM_COMPOSE_PROXY_HOST")
        target_port = int(_required("SMART_CRM_COMPOSE_PROXY_PORT"))
        try:
            upstream = socket.create_connection((target_host, target_port), timeout=3)
        except OSError:
            return
        with upstream:
            peers = (self.request, upstream)
            while True:
                readable, _writable, _exceptional = select.select(peers, (), peers, 5)
                if not readable:
                    continue
                for source in readable:
                    try:
                        chunk = source.recv(65536)
                    except OSError:
                        return
                    if not chunk:
                        return
                    target = upstream if source is self.request else self.request
                    try:
                        target.sendall(chunk)
                    except OSError:
                        return


class _ThreadingProxy(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def _start_proxy() -> None:
    global _PROXY_SERVER
    with _PROXY_LOCK:
        if _PROXY_SERVER is not None:
            return
        port = int(_required("SMART_CRM_COMPOSE_PROXY_LISTEN_PORT"))
        server = _ThreadingProxy(("127.0.0.1", port), _ProxyHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        _PROXY_SERVER = server


def create_app():  # noqa: ANN201 - Uvicorn factory contract
    """Create the real central app with a Linux-safe, local-only secret provider."""

    _start_proxy()
    runtime = bootstrap_runtime(secret_provider=EnvironmentSecretProvider())
    return create_runtime_app(runtime=runtime)


if __name__ == "__main__":
    provision()
