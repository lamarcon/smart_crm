from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.policies import PrincipalScope
from app.repositories.company_deals import CompanyDealRepository


ROOT = Path(__file__).resolve().parents[2]
TEST_DATABASE_URL = os.getenv(
    "SMART_CRM_TEST_DATABASE_URL",
    "postgresql+psycopg://smartcrm:smartcrm_local_dev@127.0.0.1:5432/smartcrm_test",
)
TENANT_HEAD = "f6b1d3a8c2e4"
TENANT_ID = UUID("0704e2f5-38f2-440d-9ef2-1d9e91a77508")


def _tenant_config(connection) -> Config:  # noqa: ANN001
    config = Config(str(ROOT / "alembic.ini"))
    config.file_config
    config.config_file_name = None
    config.attributes["connection"] = connection
    return config


def _principal(role: str, *, user_id: str = "current", team_id: str | None = "team-a") -> PrincipalScope:
    return PrincipalScope(
        tenant_id=TENANT_ID,
        workspace_id="default",
        user_id=user_id,
        role=role,
        team_id=team_id,
        auth_version=1,
    )


def _seed(session: Session) -> None:
    session.execute(text("SELECT set_config('smartcrm.workspace_id', 'default', true)"))
    session.execute(
        text(
            "INSERT INTO teams (id, workspace_id, name) VALUES "
            "('team-a', 'default', 'A'), ('team-b', 'default', 'B')"
        )
    )
    users = (
        ("current", "Current", "team-a"),
        ("manager", "Manager", "team-a"),
        ("other", "Other", "team-b"),
        ("third", "Third", "team-b"),
    )
    for user_id, name, team_id in users:
        session.execute(
            text(
                "INSERT INTO crm_users "
                "(id, workspace_id, team_id, name, email, job_title, role, status, payload) "
                "VALUES (:id, 'default', :team, :name, :email, '', 'Vendedor', 'Ativo', '{}'::jsonb)"
            ),
            {"id": user_id, "team": team_id, "name": name, "email": f"{user_id}@example.test"},
        )
    companies = (
        ("company", "Target", None),
        ("empty", "Empty", None),
        ("zero-company", "Zero", None),
        ("other-company", "Other", None),
        ("deleted-company", "Deleted", "2026-01-01T00:00:00+00:00"),
    )
    for company_id, name, deleted_at in companies:
        session.execute(
            text(
                "INSERT INTO companies "
                "(id, workspace_id, owner_id, name, city, segment, phone, payload, deleted_at) "
                "VALUES (:id, 'default', 'current', :name, '', '', '', '{}'::jsonb, :deleted_at)"
            ),
            {"id": company_id, "name": name, "deleted_at": deleted_at},
        )
    stages = {
        row.semantic_type: row
        for row in session.execute(
            text(
                "SELECT p.id AS pipeline_id, s.id AS stage_id, s.name, s.semantic_type "
                "FROM deal_pipelines p JOIN deal_pipeline_stages s "
                "ON s.pipeline_id = p.id AND s.workspace_id = p.workspace_id "
                "WHERE p.workspace_id = 'default' AND p.is_default "
                "ORDER BY s.position"
            )
        )
        if row.semantic_type not in ()
    }
    deal_rows = (
        ("open-visible", "company", "current", "team-a", Decimal("10.10"), "open", None),
        ("won-assisted", "company", "other", "team-b", Decimal("20.20"), "won", "current"),
        ("lost-team", "company", "other", "team-a", Decimal("30.30"), "lost", None),
        ("open-hidden", "company", "other", "team-b", Decimal("40.40"), "open", None),
        ("deleted-deal", "company", "current", "team-a", Decimal("50.50"), "won", None),
        ("other-company-deal", "other-company", "current", "team-a", Decimal("60.60"), "open", None),
        ("zero-open", "zero-company", "current", "team-a", Decimal("0.00"), "open", None),
        ("zero-won", "zero-company", "current", "team-a", Decimal("0.00"), "won", None),
        ("zero-lost", "zero-company", "current", "team-a", Decimal("0.00"), "lost", None),
    )
    for position, (deal_id, company_id, responsible, team_id, amount, semantic, assistant) in enumerate(deal_rows):
        stage = stages[semantic]
        session.execute(
            text(
                "INSERT INTO deals "
                "(id, workspace_id, company_id, responsible_id, team_id, title, company_text, "
                "contact_text, amount, stage, pipeline_id, stage_id, payload, created_at, deleted_at) "
                "VALUES (:id, 'default', :company, :responsible, :team, :title, 'Target', '', "
                ":amount, :stage, :pipeline, :stage_id, '{}'::jsonb, "
                "TIMESTAMPTZ '2026-01-01 00:00:00+00' + (:position * INTERVAL '1 minute'), "
                ":deleted_at)"
            ),
            {
                "id": deal_id,
                "company": company_id,
                "responsible": responsible,
                "team": team_id,
                "title": deal_id,
                "amount": amount,
                "stage": stage.name,
                "pipeline": stage.pipeline_id,
                "stage_id": stage.stage_id,
                "position": position,
                "deleted_at": (
                    "2026-02-01T00:00:00+00:00" if deal_id == "deleted-deal" else None
                ),
            },
        )
        if assistant:
            session.execute(
                text(
                    "INSERT INTO deal_assistants (workspace_id, deal_id, user_id, position) "
                    "VALUES ('default', :deal, :user, 0)"
                ),
                {"deal": deal_id, "user": assistant},
            )


@pytest.fixture(scope="module")
def company_deals_database_url() -> str:
    database_name = f"company_deals_{uuid4().hex}"
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
            _seed(session)
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


def _summary(database_url: str, principal: PrincipalScope, company_id: str = "company"):
    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with Session(engine) as session, session.begin():
            session.execute(text("SELECT set_config('smartcrm.workspace_id', 'default', true)"))
            return CompanyDealRepository(session).summary(principal, company_id)
    finally:
        engine.dispose()


def test_admin_summary_is_exact_active_canonical_and_deterministic(
    company_deals_database_url: str,
) -> None:
    summary = _summary(company_deals_database_url, _principal("Administrador"))

    assert summary is not None
    assert summary.total_count == 4
    assert (summary.open.count, summary.open.amount) == (2, Decimal("50.50"))
    assert (summary.won.count, summary.won.amount) == (1, Decimal("20.20"))
    assert (summary.lost.count, summary.lost.amount) == (1, Decimal("30.30"))
    assert [row.id for row in summary.items] == [
        "open-hidden",
        "lost-team",
        "won-assisted",
        "open-visible",
    ]
    assert summary.items[-1].responsible_name == "Current"


@pytest.mark.parametrize(
    "principal,expected_ids",
    [
        (_principal("Gestor", user_id="manager"), ["lost-team", "open-visible"]),
        (_principal("Vendedor"), ["won-assisted", "open-visible"]),
        (_principal("Assistente"), ["won-assisted", "open-visible"]),
        (_principal("Faturamento"), ["won-assisted", "open-visible"]),
    ],
)
def test_summary_and_rows_share_the_same_visibility_scope(
    company_deals_database_url: str,
    principal: PrincipalScope,
    expected_ids: list[str],
) -> None:
    summary = _summary(company_deals_database_url, principal)

    assert summary is not None
    assert [row.id for row in summary.items] == expected_ids
    assert summary.total_count == len(expected_ids)
    assert sum(metric.count for metric in (summary.open, summary.won, summary.lost)) == len(expected_ids)


def test_empty_and_hidden_companies_fail_closed_without_leaking_totals(
    company_deals_database_url: str,
) -> None:
    admin = _principal("Administrador")
    empty = _summary(company_deals_database_url, admin, "empty")

    assert empty is not None
    assert empty.total_count == 0
    assert empty.items == []
    assert [empty.open.amount, empty.won.amount, empty.lost.amount] == [
        Decimal("0.00"),
        Decimal("0.00"),
        Decimal("0.00"),
    ]
    assert _summary(company_deals_database_url, admin, "deleted-company") is None
    assert _summary(company_deals_database_url, admin, "missing") is None
    assert _summary(company_deals_database_url, _principal("Owner"), "company") is None


def test_all_semantic_buckets_preserve_zero_counts_and_exact_decimal_totals(
    company_deals_database_url: str,
) -> None:
    summary = _summary(
        company_deals_database_url,
        _principal("Administrador"),
        "zero-company",
    )

    assert summary is not None
    assert summary.total_count == 3
    assert [summary.open.count, summary.won.count, summary.lost.count] == [1, 1, 1]
    assert [summary.open.amount, summary.won.amount, summary.lost.amount] == [
        Decimal("0.00"),
        Decimal("0.00"),
        Decimal("0.00"),
    ]


def test_stage_rename_preserves_semantic_bucket_and_uses_canonical_label(
    company_deals_database_url: str,
) -> None:
    engine = create_engine(company_deals_database_url, poolclass=NullPool)
    try:
        with Session(engine) as session, session.begin():
            session.execute(text("SELECT set_config('smartcrm.workspace_id', 'default', true)"))
            session.execute(
                text(
                    "UPDATE deal_pipeline_stages SET name = 'Ganho renomeado' "
                    "WHERE workspace_id = 'default' AND semantic_type = 'won'"
                )
            )
            summary = CompanyDealRepository(session).summary(_principal("Administrador"), "company")

            assert summary is not None
            won = next(row for row in summary.items if row.id == "won-assisted")
            assert won.stage_name == "Ganho renomeado"
            assert won.semantic_type == "won"
            assert summary.won.count == 1
    finally:
        engine.dispose()


def test_company_amount_and_semantic_changes_recalculate_from_canonical_rows(
    company_deals_database_url: str,
) -> None:
    engine = create_engine(company_deals_database_url, poolclass=NullPool)
    try:
        with Session(engine) as session, session.begin():
            session.execute(text("SELECT set_config('smartcrm.workspace_id', 'default', true)"))
            lost_stage = session.execute(
                text(
                    "SELECT pipeline_id, id, name FROM deal_pipeline_stages "
                    "WHERE workspace_id = 'default' AND semantic_type = 'lost' LIMIT 1"
                )
            ).one()
            session.execute(
                text(
                    "UPDATE deals SET company_id = 'other-company', amount = 99.99, "
                    "pipeline_id = :pipeline, stage_id = :stage_id, stage = :stage "
                    "WHERE id = 'open-visible'"
                ),
                {
                    "pipeline": lost_stage.pipeline_id,
                    "stage_id": lost_stage.id,
                    "stage": lost_stage.name,
                },
            )
            target = CompanyDealRepository(session).summary(_principal("Administrador"), "company")
            moved = CompanyDealRepository(session).summary(_principal("Administrador"), "other-company")

            assert target is not None and target.total_count == 3
            assert target.open.amount == Decimal("40.40")
            assert moved is not None and moved.total_count == 2
            assert moved.lost.amount == Decimal("99.99")
    finally:
        engine.dispose()
