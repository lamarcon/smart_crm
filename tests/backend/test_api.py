from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.auth import ResolvedPrincipal
from app.main import create_app
from app.policies import PrincipalScope
from app.schemas import PersistedCounts, WorkspaceReferenceError, WorkspaceState
from app.services.auth import SessionContext
from app.services.workspace import (
    WorkspaceAlreadyInitialized,
    WorkspaceAuthorizationError,
    WorkspaceConflict,
    WorkspaceLoad,
    WorkspaceNotInitialized,
    WorkspaceRecordNotFound,
    WorkspaceRestoreConflict,
    WorkspaceResult,
    WorkspaceStageConflict,
)


STATE_DATA = {
    "users": [{"id": "u-1", "name": "Ana", "email": "ana@test"}],
    "leads": [],
    "contacts": [],
    "companies": [],
    "deals": [],
    "notifications": [],
    "customFieldSchemas": {
        "leads": [],
        "contacts": [],
        "companies": [],
        "deals": [],
    },
    "moduleFieldSettings": {},
    "ui": {},
}
COUNTS = {
    "users": 1,
    "leads": 0,
    "contacts": 0,
    "companies": 0,
    "deals": 0,
    "quotes": 0,
    "notifications": 0,
    "customFields": 0,
}


def result(version: int = 1) -> WorkspaceResult:
    return WorkspaceResult(
        version=version,
        state=WorkspaceState.model_validate(STATE_DATA),
        counts=PersistedCounts.model_validate(COUNTS),
    )


@dataclass
class FakeDatabase:
    available: bool = True

    def check_database(self) -> bool:
        return self.available


@dataclass
class FakeService:
    loaded: WorkspaceLoad = field(
        default_factory=lambda: WorkspaceLoad(False, 0, None)
    )
    failure: Exception | None = None
    calls: list[tuple] = field(default_factory=list)

    def _return(self, call: tuple, value):  # noqa: ANN001
        self.calls.append(call)
        if self.failure is not None:
            raise self.failure
        return value

    def load(self, _session, _principal) -> WorkspaceLoad:  # noqa: ANN001
        return self._return(("load",), self.loaded)

    def bootstrap(self, _session, _principal, state: WorkspaceState) -> WorkspaceResult:  # noqa: ANN001
        return self._return(("bootstrap", state), result())

    def save(self, _session, _principal, version: int, state: WorkspaceState) -> WorkspaceResult:  # noqa: ANN001
        return self._return(("save", version, state), result(version + 1))

    def reset(self, _session, _principal, version: int, state: WorkspaceState) -> WorkspaceResult:  # noqa: ANN001
        return self._return(("reset", version, state), result(version + 1))

    def list_deleted(self, _session, _principal, module: str) -> list[dict]:  # noqa: ANN001
        return self._return(("list_deleted", module), [{"id": "L-old"}])

    def restore(self, _session, _principal, version: int, module: str, record_id: str) -> WorkspaceResult:  # noqa: ANN001
        return self._return(
            ("restore", version, module, record_id), result(version + 1)
        )


TEST_SESSION_CONTEXT = SessionContext(
    principal=PrincipalScope(
        tenant_id=uuid4(),
        workspace_id="default",
        user_id="u-1",
        role="Administrador",
        team_id="team-a",
        auth_version=1,
    ),
    tenant_slug="cliente-a",
    tenant_display_name="Cliente A",
    user_name="Ana",
    email="ana@example.test",
    token_digest="d" * 64,
)


async def authenticated_admin():
    yield ResolvedPrincipal(
        context=TEST_SESSION_CONTEXT,
        tenant_session=object(),
    )


@pytest.fixture
def client_factory(tmp_path: Path):
    (tmp_path / "index.html").write_text(
        "<!doctype html><title>Smart CRM route test</title>", encoding="utf-8"
    )

    def make(
        *,
        service: FakeService | None = None,
        database: FakeDatabase | None = None,
    ) -> tuple[TestClient, FakeService]:
        fake_service = service or FakeService()
        app = create_app(
            database_instance=database or FakeDatabase(),
            workspace_service=fake_service,
            static_dir=tmp_path,
            principal_dependency=authenticated_admin,
        )
        return TestClient(app, raise_server_exceptions=False), fake_service

    return make


def assert_security_headers(response) -> None:  # noqa: ANN001
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["content-security-policy"] == "default-src 'self' 'unsafe-inline'"


def test_health_reports_database_ok_with_security_headers(client_factory) -> None:
    client, _service = client_factory()

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["cache-control"] == "no-store"
    assert_security_headers(response)


def test_version_reports_canonical_release_without_cache(client_factory) -> None:
    client, _service = client_factory()

    response = client.get("/api/version")

    assert response.status_code == 200
    assert response.json() == {"version": "0.3.1"}
    assert response.headers["cache-control"] == "no-store"
    assert_security_headers(response)


def test_database_unavailable_degrades_health_but_keeps_root_available(
    client_factory,
) -> None:
    client, _service = client_factory(database=FakeDatabase(False))

    health = client.get("/health")
    root = client.get("/")

    assert health.status_code == 503
    assert health.json() == {"status": "degraded"}
    assert health.headers["cache-control"] == "no-store"
    assert root.status_code == 200
    assert "Smart CRM route test" in root.text
    assert_security_headers(root)


def test_load_returns_uninitialized_workspace(client_factory) -> None:
    client, _service = client_factory()

    response = client.get("/api/workspace")

    assert response.status_code == 200
    assert response.json() == {"initialized": False, "version": 0, "state": None}


def test_load_returns_initialized_workspace_state(client_factory) -> None:
    loaded = WorkspaceLoad(True, 4, WorkspaceState.model_validate(STATE_DATA))
    client, _service = client_factory(service=FakeService(loaded=loaded))

    response = client.get("/api/workspace")

    assert response.status_code == 200
    assert response.json() == {
        "initialized": True,
        "version": 4,
        "state": STATE_DATA,
    }


def test_bootstrap_returns_created_version_counts_and_canonical_state(
    client_factory,
) -> None:
    client, service = client_factory()

    response = client.post("/api/workspace/bootstrap", json={"state": STATE_DATA})

    assert response.status_code == 201
    assert response.json() == {"version": 1, "counts": COUNTS, "state": STATE_DATA}
    assert service.calls[0][0] == "bootstrap"


def test_repeated_bootstrap_returns_conflict_and_current_version(client_factory) -> None:
    client, _service = client_factory(
        service=FakeService(failure=WorkspaceAlreadyInitialized(7))
    )

    response = client.post("/api/workspace/bootstrap", json={"state": STATE_DATA})

    assert response.status_code == 409
    assert response.json()["error"]["currentVersion"] == 7
    assert set(response.json()["error"]) == {"code", "message", "currentVersion"}


def test_bootstrap_reference_error_returns_422_with_stable_path(client_factory) -> None:
    client, _service = client_factory(
        service=FakeService(
            failure=WorkspaceReferenceError(
                "leads[0].responsibleId", "Usuário referenciado não existe"
            )
        )
    )

    response = client.post("/api/workspace/bootstrap", json={"state": STATE_DATA})

    assert response.status_code == 422
    assert response.json()["error"]["path"] == "leads[0].responsibleId"
    assert response.json()["error"]["message"] == "Usuário referenciado não existe"


def test_bootstrap_rejects_content_length_over_25mb_before_service(client_factory) -> None:
    client, service = client_factory()

    response = client.post(
        "/api/workspace/bootstrap",
        content=b"{}",
        headers={"content-length": str(25 * 1024 * 1024 + 1)},
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"
    assert service.calls == []


def test_bootstrap_rejects_stream_over_25mb_before_service(client_factory) -> None:
    client, service = client_factory()

    def body():
        for _ in range(26):
            yield b"x" * (1024 * 1024)

    response = client.post("/api/workspace/bootstrap", content=body())

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"
    assert service.calls == []


def test_save_returns_incremented_version_counts_and_canonical_state(
    client_factory,
) -> None:
    client, service = client_factory()

    response = client.put(
        "/api/workspace", json={"version": 3, "state": STATE_DATA}
    )

    assert response.status_code == 200
    assert response.json() == {"version": 4, "counts": COUNTS, "state": STATE_DATA}
    assert service.calls[0][0:2] == ("save", 3)


def test_stale_save_returns_409_with_current_version(client_factory) -> None:
    client, _service = client_factory(
        service=FakeService(failure=WorkspaceConflict(8))
    )

    response = client.put(
        "/api/workspace", json={"version": 3, "state": STATE_DATA}
    )

    assert response.status_code == 409
    assert response.json()["error"]["currentVersion"] == 8


def test_invalid_save_body_uses_structured_422_path(client_factory) -> None:
    client, service = client_factory()

    response = client.put(
        "/api/workspace", json={"version": -1, "state": STATE_DATA}
    )

    assert response.status_code == 422
    assert response.json()["error"]["path"] == "body.version"
    assert service.calls == []


def test_reset_returns_one_new_version(client_factory) -> None:
    client, service = client_factory()

    response = client.post(
        "/api/workspace/reset", json={"version": 5, "state": STATE_DATA}
    )

    assert response.status_code == 200
    assert response.json()["version"] == 6
    assert response.json()["state"] == STATE_DATA
    assert service.calls[0][0:2] == ("reset", 5)


def test_reset_before_bootstrap_returns_conflict(client_factory) -> None:
    client, _service = client_factory(
        service=FakeService(failure=WorkspaceNotInitialized("não inicializado"))
    )

    response = client.post(
        "/api/workspace/reset", json={"version": 0, "state": STATE_DATA}
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "workspace_not_initialized"


def test_list_deleted_returns_requested_module_records(client_factory) -> None:
    client, service = client_factory()

    response = client.get("/api/workspace/deleted?module=leads")

    assert response.status_code == 200
    assert response.json() == {"module": "leads", "records": [{"id": "L-old"}]}
    assert service.calls == [("list_deleted", "leads")]


def test_list_deleted_rejects_unknown_module_before_service(client_factory) -> None:
    client, service = client_factory()

    response = client.get("/api/workspace/deleted?module=unknown")

    assert response.status_code == 422
    assert response.json()["error"]["path"] == "query.module"
    assert service.calls == []


def test_restore_returns_incremented_version_and_state(client_factory) -> None:
    client, service = client_factory()

    response = client.post(
        "/api/workspace/restore",
        json={"version": 2, "module": "leads", "id": "L-old"},
    )

    assert response.status_code == 200
    assert response.json()["version"] == 3
    assert response.json()["state"] == STATE_DATA
    assert service.calls == [("restore", 2, "leads", "L-old")]


def test_restore_missing_record_returns_404(client_factory) -> None:
    client, _service = client_factory(
        service=FakeService(failure=WorkspaceRecordNotFound("missing"))
    )

    response = client.post(
        "/api/workspace/restore",
        json={"version": 2, "module": "leads", "id": "missing"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "record_not_found"


def test_restore_uniqueness_conflict_returns_409(client_factory) -> None:
    client, _service = client_factory(
        service=FakeService(failure=WorkspaceRestoreConflict("duplicate"))
    )

    response = client.post(
        "/api/workspace/restore",
        json={"version": 2, "module": "users", "id": "u-old"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "restore_conflict"


def test_database_failure_returns_503_with_correlated_error_id(
    client_factory, caplog: pytest.LogCaptureFixture
) -> None:
    failure = OperationalError("SELECT secret", {}, RuntimeError("password=hidden"))
    client, _service = client_factory(service=FakeService(failure=failure))

    with caplog.at_level(logging.ERROR, logger="smart-crm-api"):
        response = client.get("/api/workspace")

    error = response.json()["error"]
    assert response.status_code == 503
    assert error["code"] == "database_unavailable"
    assert UUID(error["errorId"]).version == 4
    assert error["errorId"] in caplog.text
    assert "password=hidden" not in response.text


def test_unexpected_failure_returns_500_and_logs_same_uuid_without_leaking(
    client_factory, caplog: pytest.LogCaptureFixture
) -> None:
    client, _service = client_factory(
        service=FakeService(failure=RuntimeError("internal secret"))
    )

    with caplog.at_level(logging.ERROR, logger="smart-crm-api"):
        response = client.get("/api/workspace")

    error = response.json()["error"]
    assert response.status_code == 500
    assert error["code"] == "persistence_error"
    assert UUID(error["errorId"]).version == 4
    assert error["errorId"] in caplog.text
    assert "internal secret" not in response.text


def test_workspace_authorization_failure_returns_stable_403(client_factory) -> None:
    client, _service = client_factory(
        service=FakeService(
            loaded=WorkspaceLoad(True, 1, WorkspaceState.model_validate(STATE_DATA)),
            failure=WorkspaceAuthorizationError("record is outside principal scope"),
        )
    )

    response = client.put(
        "/api/workspace",
        json={"version": 1, "state": STATE_DATA},
    )

    assert response.status_code == 403
    assert response.json() == {
        "error": {"code": "forbidden", "message": "Acesso negado."}
    }
    assert "record is outside principal scope" not in response.text


def test_workspace_stage_conflict_returns_stable_409(client_factory) -> None:
    client, _service = client_factory(
        service=FakeService(failure=WorkspaceStageConflict(7))
    )

    response = client.put("/api/workspace", json={"version": 7, "state": STATE_DATA})

    assert response.status_code == 409
    assert response.json()["error"] == {
        "code": "stage_configuration_changed",
        "message": "Configuração de etapas foi alterada.",
        "currentVersion": 7,
    }
