from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from uvicorn.importer import import_from_string

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
    dispose_calls: int = 0

    @contextmanager
    def session_scope(self):
        yield FakeSession(self.revision, self.failure)

    def dispose(self) -> None:
        self.dispose_calls += 1
        self.disposed = True


class CountingRouter:
    def __init__(self):
        self.health_calls = 0
        self.disposed = False
        self.dispose_calls = 0

    def health(self, _tenant_id) -> bool:  # noqa: ANN001
        self.health_calls += 1
        raise AssertionError("global health must not probe a tenant")

    def dispose(self) -> None:
        self.dispose_calls += 1
        self.disposed = True


def runtime_with(control: FakeControlDatabase, router: CountingRouter | None = None):
    return CentralRuntime(
        control_database=control,
        tenant_router=router or CountingRouter(),
        auth_service=object(),
    )


def test_documented_uvicorn_factory_target_resolves_and_bootstraps(monkeypatch) -> None:
    readme = (Path(__file__).parents[2] / "README.md").read_text(encoding="utf-8")
    command = next(line for line in readme.splitlines() if "python -m uvicorn " in line)
    target = command.split()[3]
    runtime = runtime_with(FakeControlDatabase())
    bootstrap_calls: list[None] = []

    def fake_bootstrap() -> CentralRuntime:
        bootstrap_calls.append(None)
        return runtime

    monkeypatch.setattr("app.server.bootstrap_runtime", fake_bootstrap)

    factory = import_from_string(target)
    application = factory()

    assert target == "app.server:create_central_app"
    assert application.state.central_runtime is runtime
    assert bootstrap_calls == [None]


def test_documented_uvicorn_factory_lifespan_disposes_router_and_control(
    monkeypatch,
) -> None:
    readme = (Path(__file__).parents[2] / "README.md").read_text(encoding="utf-8")
    command = next(line for line in readme.splitlines() if "python -m uvicorn " in line)
    target = command.split()[3]
    control = FakeControlDatabase()
    router = CountingRouter()
    runtime = runtime_with(control, router)

    monkeypatch.setattr("app.server.bootstrap_runtime", lambda: runtime)

    factory = import_from_string(target)

    with TestClient(factory()) as client:
        assert client.app.state.central_runtime is runtime
        assert router.dispose_calls == 0
        assert control.dispose_calls == 0

    assert router.dispose_calls == 1
    assert control.dispose_calls == 1
    assert router.disposed is True
    assert control.disposed is True


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


@pytest.mark.parametrize(
    ("setting", "expected"),
    [(None, False), ("", False), ("0", False), ("true", False), (" 1", False), ("1", True)],
)
def test_runtime_uses_strict_local_loopback_environment_setting(
    monkeypatch, setting: str | None, expected: bool
) -> None:
    if setting is None:
        monkeypatch.delenv("SMART_CRM_ALLOW_INSECURE_TENANT_LOOPBACK", raising=False)
    else:
        monkeypatch.setenv("SMART_CRM_ALLOW_INSECURE_TENANT_LOOPBACK", setting)

    runtime = bootstrap_runtime(
        control_database=FakeControlDatabase(),
        secret_provider=InMemorySecretProvider(),
    )

    assert runtime.tenant_router._settings.allow_insecure_loopback is expected


def test_runtime_uses_documented_bounded_tenant_pool_environment(monkeypatch) -> None:
    values = {
        "SMART_CRM_TENANT_MAX_CACHED_ENGINES": "7",
        "SMART_CRM_TENANT_POOL_SIZE": "3",
        "SMART_CRM_TENANT_MAX_OVERFLOW": "4",
        "SMART_CRM_TENANT_POOL_TIMEOUT_SECONDS": "2.5",
        "SMART_CRM_TENANT_CONNECT_TIMEOUT_SECONDS": "6",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)

    runtime = bootstrap_runtime(
        control_database=FakeControlDatabase(),
        secret_provider=InMemorySecretProvider(),
    )
    settings = runtime.tenant_router._settings

    assert settings.max_cached_engines == 7
    assert settings.pool_size == 3
    assert settings.max_overflow == 4
    assert settings.pool_timeout == 2.5
    assert settings.connect_timeout == 6


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("SMART_CRM_TENANT_MAX_CACHED_ENGINES", "0"),
        ("SMART_CRM_TENANT_POOL_SIZE", "not-a-number"),
        ("SMART_CRM_TENANT_MAX_OVERFLOW", "-1"),
        ("SMART_CRM_TENANT_POOL_TIMEOUT_SECONDS", "0"),
        ("SMART_CRM_TENANT_CONNECT_TIMEOUT_SECONDS", "-3"),
    ],
)
def test_invalid_tenant_pool_environment_blocks_bootstrap_without_detail(
    monkeypatch, name: str, value: str
) -> None:
    monkeypatch.setenv(name, value)

    with pytest.raises(RuntimeBootstrapError) as captured:
        bootstrap_runtime(
            control_database=FakeControlDatabase(),
            secret_provider=InMemorySecretProvider(),
        )

    assert str(captured.value) == "central runtime unavailable"
    assert name not in repr(captured.value)
    assert value not in repr(captured.value)


def test_absent_tenant_pool_environment_retains_bounded_defaults(monkeypatch) -> None:
    names = (
        "SMART_CRM_TENANT_MAX_CACHED_ENGINES",
        "SMART_CRM_TENANT_POOL_SIZE",
        "SMART_CRM_TENANT_MAX_OVERFLOW",
        "SMART_CRM_TENANT_POOL_TIMEOUT_SECONDS",
        "SMART_CRM_TENANT_CONNECT_TIMEOUT_SECONDS",
    )
    for name in names:
        monkeypatch.delenv(name, raising=False)

    runtime = bootstrap_runtime(
        control_database=FakeControlDatabase(),
        secret_provider=InMemorySecretProvider(),
    )
    settings = runtime.tenant_router._settings

    assert settings.max_cached_engines == 16
    assert settings.pool_size == 2
    assert settings.max_overflow == 2
    assert settings.pool_timeout == 5.0
    assert settings.connect_timeout == 3


def test_runtime_default_expected_origin_remains_production(monkeypatch) -> None:
    captured: dict = {}

    def fake_create_http_app(**kwargs):  # noqa: ANN003, ANN202
        captured.update(kwargs)
        return FastAPI()

    monkeypatch.delenv("SMART_CRM_EXPECTED_ORIGIN", raising=False)
    monkeypatch.setattr("app.server.create_http_app", fake_create_http_app)

    create_app(runtime=runtime_with(FakeControlDatabase()))

    assert captured["auth_settings"].expected_origin == "https://sc2030.brbots.com"


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
