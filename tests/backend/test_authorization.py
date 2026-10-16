from __future__ import annotations

import os
from uuid import uuid4
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.models import Deal, DealAssistant
from app.policies import (
    Action,
    PrincipalScope,
    RecordScope,
    can_mutate_record,
    can_perform_action,
    can_read_record,
    deal_visibility_predicate,
)


TENANT_ID = uuid4()
ROOT = Path(__file__).resolve().parents[2]
TEST_DATABASE_URL = os.getenv(
    "SMART_CRM_TEST_DATABASE_URL",
    "postgresql+psycopg://smartcrm:smartcrm_local_dev@127.0.0.1:5432/smartcrm_test",
)
TENANT_HEAD = "e1c4a7b9d2f6"


def principal(role: str, *, user_id: str = "u-current", team_id: str = "team-a") -> PrincipalScope:
    return PrincipalScope(
        tenant_id=TENANT_ID,
        workspace_id="default",
        user_id=user_id,
        role=role,
        team_id=team_id,
        auth_version=1,
    )


@pytest.mark.parametrize(
    "role",
    ["Administrador", "Gestor", "Vendedor", "Assistente", "Faturamento"],
)
@pytest.mark.parametrize("module", ["contacts", "companies"])
def test_all_current_roles_read_and_mutate_tenant_wide_records(role: str, module: str) -> None:
    subject = principal(role)
    record = RecordScope(responsible_id="u-other", assistant_ids=(), team_id="team-b")

    assert can_read_record(subject, module, record) is True
    assert can_mutate_record(subject, module, record) is True


@pytest.mark.parametrize("module", ["leads", "deals"])
def test_administrator_reads_and_mutates_any_business_record(module: str) -> None:
    subject = principal("Administrador")
    record = RecordScope(responsible_id="u-other", assistant_ids=(), team_id="team-b")

    assert can_read_record(subject, module, record) is True
    assert can_mutate_record(subject, module, record) is True


@pytest.mark.parametrize("module", ["leads", "deals"])
def test_manager_scope_is_the_record_team(module: str) -> None:
    subject = principal("Gestor")

    assert can_read_record(
        subject,
        module,
        RecordScope(responsible_id="u-other", assistant_ids=(), team_id="team-a"),
    ) is True
    assert can_mutate_record(
        subject,
        module,
        RecordScope(responsible_id="u-current", assistant_ids=("u-current",), team_id="team-b"),
    ) is False


@pytest.mark.parametrize("role", ["Vendedor", "Assistente", "Faturamento"])
@pytest.mark.parametrize("module", ["leads", "deals"])
def test_individual_roles_use_responsible_or_assistant_scope(role: str, module: str) -> None:
    subject = principal(role)
    responsible = RecordScope(responsible_id="u-current", assistant_ids=(), team_id="team-b")
    assisted = RecordScope(responsible_id="u-other", assistant_ids=("u-current",), team_id="team-b")
    unrelated = RecordScope(responsible_id="u-other", assistant_ids=("u-third",), team_id="team-a")

    assert can_read_record(subject, module, responsible) is True
    assert can_mutate_record(subject, module, assisted) is True
    assert can_read_record(subject, module, unrelated) is False
    assert can_mutate_record(subject, module, unrelated) is False


@pytest.mark.parametrize(
    "action",
    [
        Action.MANAGE_USERS,
        Action.MANAGE_FIELDS,
        Action.IMPORT_DATA,
        Action.RESET_WORKSPACE,
        Action.RESTORE_DELETED,
        Action.MANAGE_PIPELINE,
    ],
)
def test_administrative_actions_are_admin_only(action: Action) -> None:
    assert can_perform_action(principal("Administrador"), action) is True
    assert can_perform_action(principal("Gestor"), action) is False
    assert can_perform_action(principal("Vendedor"), action) is False
    assert can_perform_action(principal("Assistente"), action) is False
    assert can_perform_action(principal("Faturamento"), action) is False


@pytest.mark.parametrize("action", [Action.READ, Action.CREATE, Action.UPDATE, Action.DELETE])
@pytest.mark.parametrize(
    "role",
    ["Administrador", "Gestor", "Vendedor", "Assistente", "Faturamento"],
)
def test_current_roles_have_explicit_business_action_outcomes(role: str, action: Action) -> None:
    assert can_perform_action(principal(role), action) is True


@pytest.mark.parametrize("forged_role", ["admin", "ADMINISTRADOR", "Owner", "", "Gestor "])
def test_forged_or_unknown_roles_are_denied(forged_role: str) -> None:
    subject = principal(forged_role)
    record = RecordScope(responsible_id="u-current", assistant_ids=("u-current",), team_id="team-a")

    assert can_perform_action(subject, Action.READ) is False
    assert can_read_record(subject, "contacts", record) is False
    assert can_mutate_record(subject, "leads", record) is False


@pytest.mark.parametrize("module", ["users", "notifications", "unknown", "", "workspace"])
def test_unspecified_record_modules_fail_closed(module: str) -> None:
    subject = principal("Administrador")
    record = RecordScope(responsible_id="u-current", assistant_ids=(), team_id="team-a")

    assert can_read_record(subject, module, record) is False
    assert can_mutate_record(subject, module, record) is False


def _tenant_config(connection) -> Config:  # noqa: ANN001
    config = Config(str(ROOT / "alembic.ini"))
    config.file_config
    config.config_file_name = None
    config.attributes["connection"] = connection
    return config


@pytest.fixture(scope="module")
def authorization_database_url() -> str:
    database_name = f"authorization_{uuid4().hex}"
    admin_url = make_url(TEST_DATABASE_URL).set(database="postgres")
    tenant_url = make_url(TEST_DATABASE_URL).set(database=database_name)
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    tenant_engine = None
    try:
        with admin_engine.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{database_name}"'))
        tenant_engine = create_engine(tenant_url, poolclass=NullPool)
        with tenant_engine.connect() as connection:
            command.upgrade(_tenant_config(connection), TENANT_HEAD)
            connection.commit()
        with Session(tenant_engine) as session, session.begin():
            _seed_visibility_records(session)
        yield tenant_url.render_as_string(hide_password=False)
    finally:
        if tenant_engine is not None:
            tenant_engine.dispose()
        with admin_engine.connect() as connection:
            connection.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :database_name AND pid <> pg_backend_pid()"
                ),
                {"database_name": database_name},
            )
            connection.execute(text(f'DROP DATABASE IF EXISTS "{database_name}"'))
        admin_engine.dispose()


def _seed_visibility_records(session: Session) -> None:
    session.execute(text("SELECT set_config('smartcrm.workspace_id', 'default', true)"))
    session.execute(
        text(
            "INSERT INTO teams (id, workspace_id, name) VALUES "
            "('team-a', 'default', 'A'), ('team-b', 'default', 'B')"
        )
    )
    for user_id in ("u-current", "u-other", "u-third"):
        session.execute(
            text(
                "INSERT INTO crm_users "
                "(id, workspace_id, team_id, name, email, job_title, role, status, payload) "
                "VALUES (:id, 'default', 'team-a', :id, :email, '', 'Vendedor', 'Ativo', '{}'::jsonb)"
            ),
            {"id": user_id, "email": f"{user_id}@example.test"},
        )
    session.execute(
        text(
            "INSERT INTO companies "
            "(id, workspace_id, owner_id, name, city, segment, phone, payload) "
            "VALUES ('company', 'default', 'u-current', 'Company', '', '', '', '{}'::jsonb)"
        )
    )
    stage = session.execute(
        text(
            "SELECT p.id AS pipeline_id, s.id AS stage_id, s.name AS stage_name "
            "FROM deal_pipelines p JOIN deal_pipeline_stages s "
            "ON s.pipeline_id = p.id AND s.workspace_id = p.workspace_id "
            "WHERE p.workspace_id = 'default' AND p.is_default ORDER BY s.position LIMIT 1"
        )
    ).one()
    deals = (
        ("d-team", "u-other", "team-a"),
        ("d-responsible", "u-current", "team-b"),
        ("d-assistant", "u-other", "team-b"),
        ("d-unrelated", "u-other", "team-b"),
    )
    for deal_id, responsible_id, team_id in deals:
        session.execute(
            text(
                "INSERT INTO deals "
                "(id, workspace_id, company_id, responsible_id, team_id, title, company_text, "
                "contact_text, amount, stage, pipeline_id, stage_id, payload) "
                "VALUES (:id, 'default', 'company', :responsible, :team, :id, 'Company', '', 1, "
                ":stage, :pipeline, :stage_id, '{}'::jsonb)"
            ),
            {
                "id": deal_id,
                "responsible": responsible_id,
                "team": team_id,
                "stage": stage.stage_name,
                "pipeline": stage.pipeline_id,
                "stage_id": stage.stage_id,
            },
        )
    session.execute(
        text(
            "INSERT INTO deal_assistants (workspace_id, deal_id, user_id, position) VALUES "
            "('default', 'd-assistant', 'u-current', 0), "
            "('default', 'd-unrelated', 'u-third', 0)"
        )
    )


@pytest.mark.parametrize(
    "role,team_id",
    [
        ("Administrador", "team-b"),
        ("Gestor", "team-a"),
        ("Vendedor", "team-b"),
        ("Assistente", "team-b"),
        ("Faturamento", "team-b"),
    ],
)
def test_sql_deal_visibility_matches_python_policy_for_every_role(
    authorization_database_url: str,
    role: str,
    team_id: str,
) -> None:
    engine = create_engine(authorization_database_url, poolclass=NullPool)
    principal_scope = principal(role, team_id=team_id)
    try:
        with Session(engine) as session, session.begin():
            session.execute(text("SELECT set_config('smartcrm.workspace_id', 'default', true)"))
            sql_ids = set(
                session.scalars(
                    select(Deal.id).where(deal_visibility_predicate(principal_scope))
                ).all()
            )
            expected_ids: set[str] = set()
            for deal in session.scalars(select(Deal).order_by(Deal.id)):
                assistant_ids = tuple(
                    session.scalars(
                        select(DealAssistant.user_id).where(
                            DealAssistant.workspace_id == deal.workspace_id,
                            DealAssistant.deal_id == deal.id,
                        )
                    ).all()
                )
                if can_read_record(
                    principal_scope,
                    "deals",
                    RecordScope(
                        responsible_id=deal.responsible_id,
                        assistant_ids=assistant_ids,
                        team_id=deal.team_id,
                    ),
                ):
                    expected_ids.add(deal.id)

            assert sql_ids == expected_ids
    finally:
        engine.dispose()


@pytest.mark.parametrize("role", ["admin", "Owner", "", "Gestor "])
def test_sql_deal_visibility_fails_closed_for_forged_roles(
    authorization_database_url: str,
    role: str,
) -> None:
    engine = create_engine(authorization_database_url, poolclass=NullPool)
    try:
        with Session(engine) as session, session.begin():
            session.execute(text("SELECT set_config('smartcrm.workspace_id', 'default', true)"))
            forged = principal(role, user_id="d-responsible", team_id="team-a")
            assert session.scalars(
                select(Deal.id).where(deal_visibility_predicate(forged))
            ).all() == []
    finally:
        engine.dispose()


def test_sql_deal_visibility_requires_principal_and_workspace_scope(
    authorization_database_url: str,
) -> None:
    with pytest.raises(TypeError, match="principal scope is required"):
        deal_visibility_predicate(None)  # type: ignore[arg-type]

    engine = create_engine(authorization_database_url, poolclass=NullPool)
    try:
        with Session(engine) as session, session.begin():
            session.execute(text("SELECT set_config('smartcrm.workspace_id', 'default', true)"))
            foreign_scope = PrincipalScope(
                tenant_id=TENANT_ID,
                workspace_id="foreign",
                user_id="u-current",
                role="Administrador",
                team_id=None,
                auth_version=1,
            )
            assert session.scalars(
                select(Deal.id).where(deal_visibility_predicate(foreign_scope))
            ).all() == []
    finally:
        engine.dispose()
