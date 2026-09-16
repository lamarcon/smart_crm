from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from app.security.secrets import InMemorySecretProvider
from app.server import (
    CONTROL_SCHEMA_REVISION,
    CentralRuntime,
    RuntimeBootstrapError,
    bootstrap_runtime,
    create_app,
)


class FakeSession:
    def __init__(self, revision: str | None = CONTROL_SCHEMA_REVISION, failure=None):
        self.revision = revision
        self.failure = failure

    def scalar(self, _statement):  # noqa: ANN001
        if self.failure is not None:
            raise self.failure
        return self.revision


@dataclass
class FakeControlDatabase:
    revision: str | None = CONTROL_SCHEMA_REVISION
    failure: Exception | None = None
    disposed: bool = False

    @contextmanager
    def session_scope(self):
        yield FakeSession(self.revision, self.failure)

    def dispose(self) -> None:
        self.disposed = True


class CountingRouter:
    def __init__(self):
        self.health_calls = 0

    def health(self, _tenant_id) -> bool:  # noqa: ANN001
        self.health_calls += 1
        raise AssertionError("global health must not probe a tenant")

    def dispose(self) -> None:
        pass


def runtime_with(control: FakeControlDatabase, router: CountingRouter | None = None):
    return CentralRuntime(
        control_database=control,
        tenant_router=router or CountingRouter(),
        auth_service=object(),
    )


def test_missing_control_configuration_blocks_bootstrap_without_leaking_value() -> None:
    secret = "postgresql://control-user:control-password@control.internal/smartcrm"

    def unavailable_control():
        raise RuntimeError(secret)

    with pytest.raises(RuntimeBootstrapError) as captured:
        bootstrap_runtime(
            control_database_factory=unavailable_control,
            secret_provider=InMemorySecretProvider(),
        )

    assert str(captured.value) == "central runtime unavailable"
    assert secret not in repr(captured.value)


def test_unavailable_control_database_blocks_bootstrap_and_disposes_engine() -> None:
    control = FakeControlDatabase(failure=RuntimeError("host=secret.internal db=control"))

    with pytest.raises(RuntimeBootstrapError, match="^central runtime unavailable$"):
        bootstrap_runtime(control_database=control, secret_provider=InMemorySecretProvider())

    assert control.disposed is True


def test_missing_control_revision_blocks_bootstrap() -> None:
    with pytest.raises(RuntimeBootstrapError, match="^central runtime unavailable$"):
        bootstrap_runtime(
            control_database=FakeControlDatabase(revision=None),
            secret_provider=InMemorySecretProvider(),
        )


def test_incompatible_control_revision_blocks_bootstrap_without_revision_detail() -> None:
    obsolete = "obsolete-secret-revision"

    with pytest.raises(RuntimeBootstrapError) as captured:
        bootstrap_runtime(
            control_database=FakeControlDatabase(revision=obsolete),
            secret_provider=InMemorySecretProvider(),
        )

    assert str(captured.value) == "central runtime unavailable"
    assert obsolete not in repr(captured.value)


def test_compatible_control_revision_builds_router_without_opening_tenant_engine() -> None:
    runtime = bootstrap_runtime(
        control_database=FakeControlDatabase(),
        secret_provider=InMemorySecretProvider(),
    )

    assert runtime.tenant_router.cached_tenant_ids == ()


def test_health_reports_only_redacted_ready_status() -> None:
    with TestClient(create_app(runtime=runtime_with(FakeControlDatabase()))) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["cache-control"] == "no-store"


def test_health_redacts_control_failure_details() -> None:
    secret = "postgresql://role:password@db.internal/control"
    control = FakeControlDatabase(failure=RuntimeError(secret))

    with TestClient(create_app(runtime=runtime_with(control))) as client:
        response = client.get("/health")

    assert response.status_code == 503
    assert response.json() == {"status": "degraded"}
    assert secret not in response.text
    assert all(key not in response.text.lower() for key in ("host", "database", "role", "dsn", "error"))


def test_health_does_not_probe_tenants_when_control_is_ready() -> None:
    router = CountingRouter()

    with TestClient(create_app(runtime=runtime_with(FakeControlDatabase(), router))) as client:
        assert client.get("/health").status_code == 200

    assert router.health_calls == 0


def test_tenant_failure_does_not_change_central_health_or_probe_other_tenants() -> None:
    router = CountingRouter()
    runtime = runtime_with(FakeControlDatabase(), router)

    with TestClient(create_app(runtime=runtime)) as client:
        first = client.get("/health")
        second = client.get("/health")

    assert [first.json(), second.json()] == [{"status": "ok"}, {"status": "ok"}]
    assert router.health_calls == 0


def test_runtime_representation_never_exposes_component_details() -> None:
    runtime = runtime_with(FakeControlDatabase())

    assert repr(runtime) == "CentralRuntime(control=configured, tenant_router=lazy)"
