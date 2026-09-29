from __future__ import annotations

import inspect
import os
import uuid
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.models import (
    Company,
    Contact,
    CrmUser,
    Deal,
    DealAssistant,
    DealStageHistory,
    Lead,
    LeadAssistant,
    Notification,
    Quote,
)
from app.policies import PrincipalScope
from app.repositories.workspace import WorkspaceRepository, WorkspaceScopeError
from app.schemas import WorkspaceState
from app.services.workspace import WorkspaceService
from tests.backend.test_repository import sample_state


ROOT = Path(__file__).resolve().parents[2]
TEST_DATABASE_URL = os.getenv(
    "SMART_CRM_TEST_DATABASE_URL",
    "postgresql+psycopg://smartcrm:smartcrm_local_dev@127.0.0.1:5432/smartcrm_test",
)
TENANT_HEAD = "c7f3a9d8e2b1"
WORKSPACE_ID = "default"


@dataclass(frozen=True)
class PhysicalTenantPair:
    dsn_a: str
    dsn_b: str


def _dsn_for(database_name: str) -> str:
    return make_url(TEST_DATABASE_URL).set(database=database_name).render_as_string(
        hide_password=False
    )


def _tenant_config(connection) -> Config:  # noqa: ANN001
    config = Config(str(ROOT / "alembic.ini"))
    config.attributes["connection"] = connection
    return config


def _migrate_tenant(dsn: str) -> None:
    engine = create_engine(dsn)
    try:
        with engine.connect() as connection:
            command.upgrade(_tenant_config(connection), TENANT_HEAD)
            connection.execute(
                text(
                    "INSERT INTO tenant_identity "
                    "(singleton_key, control_tenant_id, workspace_id, schema_contract) "
                    "VALUES ('identity', :tenant_id, 'default', 'tenant-v1')"
                ),
                {"tenant_id": uuid.uuid4()},
            )
            connection.commit()
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def physical_tenant_pair() -> PhysicalTenantPair:
    suffix = uuid.uuid4().hex
    names = (f"repository_tenant_a_{suffix}", f"repository_tenant_b_{suffix}")
    admin_url = make_url(TEST_DATABASE_URL).set(database="postgres")
    admin_engine = create_engine(
        admin_url,
        isolation_level="AUTOCOMMIT",
        poolclass=NullPool,
    )
    try:
        with admin_engine.connect() as connection:
            for database_name in names:
                connection.execute(text(f'CREATE DATABASE "{database_name}"'))
        pair = PhysicalTenantPair(*(_dsn_for(name) for name in names))
        _migrate_tenant(pair.dsn_a)
        _migrate_tenant(pair.dsn_b)
        yield pair
    finally:
        with admin_engine.connect() as connection:
            for database_name in names:
                connection.execute(
                    text(
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                        "WHERE datname = :database_name AND pid <> pg_backend_pid()"
                    ),
                    {"database_name": database_name},
                )
                connection.execute(text(f'DROP DATABASE IF EXISTS "{database_name}"'))
        admin_engine.dispose()


@contextmanager
def scoped_repository(
    dsn: str,
    *,
    expected_workspace_id: str = WORKSPACE_ID,
    context_workspace_id: str = WORKSPACE_ID,
):
    engine = create_engine(dsn)
    session = Session(bind=engine, expire_on_commit=False)
    try:
        session.execute(
            text("SELECT set_config('smartcrm.workspace_id', :workspace_id, true)"),
            {"workspace_id": context_workspace_id},
        )
        yield WorkspaceRepository(session, expected_workspace_id), session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        engine.dispose()


def tenant_state(marker: str) -> dict:
    state = deepcopy(sample_state())
    state["users"][0]["name"] = f"user-{marker}"
    state["leads"][0]["name"] = f"lead-{marker}"
    state["contacts"][0]["name"] = f"contact-{marker}"
    state["companies"][0]["name"] = f"company-{marker}"
    state["deals"][0]["title"] = f"deal-{marker}"
    state["deals"][0]["quotes"][0]["description"] = f"quote-{marker}"
    state["notifications"][0]["text"] = f"notification-{marker}"
    return state


@pytest.fixture
def isolated_repositories(physical_tenant_pair: PhysicalTenantPair) -> PhysicalTenantPair:
    for dsn, marker in (
        (physical_tenant_pair.dsn_a, "a"),
        (physical_tenant_pair.dsn_b, "b"),
    ):
        with scoped_repository(dsn) as (repository, _session):
            repository.reconcile(WorkspaceState.model_validate(tenant_state(marker)))
    return physical_tenant_pair


ENTITY_CASES = (
    ("users", CrmUser, "u-1", "name"),
    ("leads", Lead, "L-2", "name"),
    ("contacts", Contact, "C-1", "name"),
    ("companies", Company, "E-1", "name"),
    ("deals", Deal, "N-1", "title"),
    ("quotes", Quote, "Q-1", "description"),
    ("notifications", Notification, "NT-1", "text"),
)


def _omit_record(state: dict, module: str, record_id: str) -> None:
    if module == "quotes":
        state["deals"][0]["quotes"] = []
    else:
        state[module] = [record for record in state[module] if record["id"] != record_id]


def test_repository_rejects_missing_workspace_context(
    physical_tenant_pair: PhysicalTenantPair,
) -> None:
    engine = create_engine(physical_tenant_pair.dsn_a)
    session = Session(bind=engine)
    try:
        session.execute(text("RESET smartcrm.workspace_id"))
        with pytest.raises(WorkspaceScopeError, match="workspace context unavailable"):
            WorkspaceRepository(session, WORKSPACE_ID)
    finally:
        session.close()
        engine.dispose()


def test_repository_rejects_principal_workspace_mismatch(
    physical_tenant_pair: PhysicalTenantPair,
) -> None:
    with pytest.raises(WorkspaceScopeError, match="workspace context mismatch"):
        with scoped_repository(
            physical_tenant_pair.dsn_a,
            expected_workspace_id="forged-workspace",
        ):
            pytest.fail("mismatched workspace must fail before yielding")


def test_repository_has_no_identity_map_lookup_bypass() -> None:
    source = inspect.getsource(WorkspaceRepository)

    assert ".session.get(" not in source


@pytest.mark.parametrize(("module", "model", "record_id", "field"), ENTITY_CASES)
def test_reads_identical_ids_only_from_selected_physical_database(
    isolated_repositories: PhysicalTenantPair,
    module: str,
    model,
    record_id: str,
    field: str,
) -> None:
    del model, record_id, field
    with scoped_repository(isolated_repositories.dsn_a) as (repository_a, _session_a):
        state_a = repository_a.read_active().model_dump(by_alias=True, exclude_none=True)
    with scoped_repository(isolated_repositories.dsn_b) as (repository_b, _session_b):
        state_b = repository_b.read_active().model_dump(by_alias=True, exclude_none=True)

    if module == "quotes":
        value_a = state_a["deals"][0]["quotes"][0]["description"]
        value_b = state_b["deals"][0]["quotes"][0]["description"]
    else:
        field_name = "title" if module == "deals" else "text" if module == "notifications" else "name"
        value_a = state_a[module][0][field_name]
        value_b = state_b[module][0][field_name]
    assert value_a.endswith("-a")
    assert value_b.endswith("-b")


@pytest.mark.parametrize(("module", "model", "record_id", "field"), ENTITY_CASES)
def test_write_in_tenant_a_never_updates_tenant_b(
    isolated_repositories: PhysicalTenantPair,
    module: str,
    model,
    record_id: str,
    field: str,
) -> None:
    changed = tenant_state("a")
    if module == "quotes":
        changed["deals"][0]["quotes"][0]["description"] = "changed-a"
    else:
        target = next(item for item in changed[module] if item["id"] == record_id)
        payload_field = "title" if module == "deals" else "text" if module == "notifications" else "name"
        target[payload_field] = "changed-a"
    with scoped_repository(isolated_repositories.dsn_a) as (repository_a, _session_a):
        repository_a.reconcile(WorkspaceState.model_validate(changed))

    with scoped_repository(isolated_repositories.dsn_b) as (_repository_b, session_b):
        row_b = session_b.scalar(
            select(model).where(
                model.workspace_id == WORKSPACE_ID,
                model.id == record_id,
            )
        )
        assert getattr(row_b, field).endswith("-b")


@pytest.mark.parametrize(("module", "model", "record_id", "field"), ENTITY_CASES)
def test_delete_in_tenant_a_never_soft_deletes_tenant_b(
    isolated_repositories: PhysicalTenantPair,
    module: str,
    model,
    record_id: str,
    field: str,
) -> None:
    del field
    reduced = tenant_state("a")
    _omit_record(reduced, module, record_id)
    with scoped_repository(isolated_repositories.dsn_a) as (repository_a, _session_a):
        repository_a.reconcile(WorkspaceState.model_validate(reduced))

    with scoped_repository(isolated_repositories.dsn_b) as (_repository_b, session_b):
        row_b = session_b.scalar(
            select(model).where(
                model.workspace_id == WORKSPACE_ID,
                model.id == record_id,
            )
        )
        assert row_b.deleted_at is None


@pytest.mark.parametrize(("module", "model", "record_id", "field"), ENTITY_CASES)
def test_restore_in_tenant_a_never_restores_tenant_b(
    isolated_repositories: PhysicalTenantPair,
    module: str,
    model,
    record_id: str,
    field: str,
) -> None:
    del field
    for dsn, marker in (
        (isolated_repositories.dsn_a, "a"),
        (isolated_repositories.dsn_b, "b"),
    ):
        reduced = tenant_state(marker)
        _omit_record(reduced, module, record_id)
        with scoped_repository(dsn) as (repository, _session):
            repository.reconcile(WorkspaceState.model_validate(reduced))

    with scoped_repository(isolated_repositories.dsn_a) as (repository_a, _session_a):
        assert repository_a.restore_record(module, record_id) is True

    with scoped_repository(isolated_repositories.dsn_b) as (_repository_b, session_b):
        row_b = session_b.scalar(
            select(model).where(
                model.workspace_id == WORKSPACE_ID,
                model.id == record_id,
            )
        )
        assert row_b.deleted_at is not None


@pytest.mark.parametrize(
    ("child_model", "mutate"),
    [
        (LeadAssistant, lambda state: state["leads"][0].update(assistants=[])),
        (DealAssistant, lambda state: state["deals"][0].update(assistants=[])),
        (DealStageHistory, lambda state: state["deals"][0].update(stageHistory=[])),
    ],
)
def test_reference_reconcile_in_tenant_a_never_deletes_tenant_b_children(
    isolated_repositories: PhysicalTenantPair,
    child_model,
    mutate,
) -> None:
    changed = tenant_state("a")
    mutate(changed)
    with scoped_repository(isolated_repositories.dsn_a) as (repository_a, _session_a):
        repository_a.reconcile(WorkspaceState.model_validate(changed))

    with scoped_repository(isolated_repositories.dsn_b) as (_repository_b, session_b):
        assert session_b.scalar(select(func.count()).select_from(child_model)) == 1


def test_workspace_service_save_in_one_physical_database_never_changes_the_other(
    physical_tenant_pair: PhysicalTenantPair,
) -> None:
    service = WorkspaceService()
    tenant_ids = (uuid.uuid4(), uuid.uuid4())
    for dsn, tenant_id, marker in (
        (physical_tenant_pair.dsn_a, tenant_ids[0], "a"),
        (physical_tenant_pair.dsn_b, tenant_ids[1], "b"),
    ):
        admin = PrincipalScope(
            tenant_id=tenant_id,
            workspace_id=WORKSPACE_ID,
            user_id="u-1",
            role="Administrador",
            team_id=None,
            auth_version=1,
        )
        with scoped_repository(dsn) as (_repository, session):
            service.bootstrap(
                session,
                admin,
                WorkspaceState.model_validate(tenant_state(marker)),
            )

    admin_a = PrincipalScope(
        tenant_id=tenant_ids[0],
        workspace_id=WORKSPACE_ID,
        user_id="u-1",
        role="Administrador",
        team_id=None,
        auth_version=1,
    )
    with scoped_repository(physical_tenant_pair.dsn_a) as (_repository, session_a):
        projected_a = service.load(session_a, admin_a).state
        projected_a.leads[0]["name"] = "service-changed-a"
        service.save(session_a, admin_a, 1, projected_a)

    admin_b = PrincipalScope(
        tenant_id=tenant_ids[1],
        workspace_id=WORKSPACE_ID,
        user_id="u-1",
        role="Administrador",
        team_id=None,
        auth_version=1,
    )
    with scoped_repository(physical_tenant_pair.dsn_b) as (_repository, session_b):
        loaded_b = service.load(session_b, admin_b)
        assert loaded_b.version == 1
        assert loaded_b.state.leads[0]["name"] == "lead-b"
