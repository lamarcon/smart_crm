from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
README = PROJECT_ROOT / "README.md"


def read_readme() -> str:
    return README.read_text(encoding="utf-8")


def test_readme_separates_control_metadata_from_tenant_users_and_business_data() -> None:
    text = read_readme()

    assert "## Modelo multiempresa: plano de controle e bancos dedicados" in text
    assert "O banco de controle armazena somente" in text
    assert "Nunca armazena usuários, hashes de senha, workspaces ou dados comerciais de tenants." in text
    assert "Cada banco tenant armazena seus próprios usuários, hashes Argon2id, workspace e dados comerciais." in text


def test_local_setup_names_exactly_one_control_and_two_tenant_databases() -> None:
    text = read_readme()

    assert "smartcrm_control_local" in text
    assert "smartcrm_tenant_a_local" in text
    assert "smartcrm_tenant_b_local" in text
    assert "controle + tenant A + tenant B" in text


def test_readme_documents_both_migration_lineages_with_exact_revisions() -> None:
    text = read_readme()

    assert "python -m alembic -c alembic-control.ini upgrade c01a5d8e4f20" in text
    assert "python -m alembic -c alembic.ini upgrade a4c9d2e7f1b6" in text
    assert "$env:SMART_CRM_CONTROL_DATABASE_URL = $controlUrl" in text
    assert "$env:SMART_CRM_DATABASE_URL = $tenantAUrl" in text
    assert "$env:SMART_CRM_DATABASE_URL = $tenantBUrl" in text


def test_runtime_startup_never_runs_migrations_automatically() -> None:
    text = read_readme()

    assert "O runtime nunca executa upgrade no startup nem durante requests." in text
    assert "current deve confirmar c01a5d8e4f20" in text
    assert "current deve confirmar a4c9d2e7f1b6" in text
    assert "app.server:create_central_app --factory --host 127.0.0.1 --port 8080" in text


def test_provisioning_is_local_prompted_and_has_no_public_registration() -> None:
    text = read_readme()

    assert "python -m app.admin_cli register-tenant cliente-a" in text
    assert "python -m app.admin_cli activate-default cliente-a" in text
    assert "senhas e DSNs são digitados em prompts" in text
    assert "não existe cadastro público de empresa ou primeiro administrador" in text


def test_local_loopback_opt_in_is_explicit_scoped_and_removed() -> None:
    text = read_readme()

    assert '$env:SMART_CRM_ALLOW_INSECURE_TENANT_LOOPBACK = "1"' in text
    assert "somente neste setup local de três bancos" in text
    assert "não autoriza PostgreSQL remoto sem verify-full e CA" in text
    assert "Remove-Item Env:SMART_CRM_ALLOW_INSECURE_TENANT_LOOPBACK -ErrorAction SilentlyContinue" in text


def test_multidatabase_negative_test_command_uses_isolated_basetemp() -> None:
    text = read_readme()

    assert "pytest --basetemp .pytest-tmp" in text
    assert "test_repository_tenant_scope.py" in text
    assert "test_tenant_router.py" in text
    assert "test_fleet.py" in text


def test_postgresql_11_eol_risk_is_not_hidden_by_local_postgresql_17() -> None:
    text = read_readme()

    assert "PostgreSQL 11 está EOL desde 09/11/2023" in text
    assert "PostgreSQL 17 local não elimina esse risco" in text
    assert "compatibilidade mínima continua sendo PostgreSQL 11" in text


def test_local_commands_are_explicitly_non_production_and_keep_secrets_out_of_browser() -> None:
    text = read_readme()

    assert "Não execute estes comandos contra produção." in text
    assert "O navegador nunca recebe DSN, senha de banco ou secret_ref." in text
    assert "Nenhum comando desta seção faz deploy" in text
