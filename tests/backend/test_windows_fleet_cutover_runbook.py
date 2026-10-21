from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNBOOK = PROJECT_ROOT / "RUNBOOK_DEPLOY_WINDOWS_SERVER_2016.md"


def read_runbook() -> str:
    return RUNBOOK.read_text(encoding="utf-8")


def test_fleet_section_supersedes_the_legacy_single_database_cutover() -> None:
    text = read_runbook()

    assert "## 7.6 Cutover multiempresa: plano de controle e frota de bancos" in text
    assert "Esta seção substitui o fluxo de banco único" in text


def test_change_set_names_control_default_and_remote_databases_explicitly() -> None:
    text = read_runbook()

    assert "control_database" in text
    assert "tenant_default" in text
    assert "tenant_remote" in text
    assert "Nenhum banco pode entrar no conjunto por descoberta automática." in text


def test_every_selected_database_requires_explicit_authorization() -> None:
    text = read_runbook()

    assert "authorized_by" in text
    assert "change_ticket" in text
    assert "Autorização ausente para qualquer linha bloqueia toda migração." in text


def test_every_selected_database_requires_verified_backup_and_restore_rehearsal() -> None:
    text = read_runbook()

    assert "Cada banco selecionado, inclusive o banco de controle" in text
    assert "backup_sha256" in text
    assert "pg_restore --list" in text
    assert "restore_rehearsal=passed" in text


def test_evidence_and_fleet_output_are_redacted() -> None:
    text = read_runbook()

    assert "Nunca registrar DSN, usuário, senha ou conteúdo DPAPI." in text
    assert "tenant_id, slug, status, revision, identity e code" in text
    assert "secret_ref opaco" in text


def test_control_and_tenant_migration_lineages_are_separate_and_ordered() -> None:
    text = read_runbook()

    assert "c01a5d8e4f20" in text
    assert "c7f3a9d8e2b1" in text
    assert "f6b1d3a8c2e4" in text
    assert "A linhagem tenant desta release avança da revisão do funil personalizável" in text
    assert "alembic-control.ini" in text
    assert "Todos os backups e ensaios devem estar verdes antes da primeira migração." in text


def test_default_tenant_migration_never_copies_commercial_data() -> None:
    text = read_runbook()

    assert "A migração de default nunca copia dados comerciais para outro banco." in text
    assert "Não usar pg_dump/pg_restore, COPY, INSERT SELECT ou exportação/importação" in text
    assert "contagens antes/depois" in text


def test_tenant_identity_must_match_the_control_directory() -> None:
    text = read_runbook()

    assert "tenant_identity.control_tenant_id" in text
    assert "workspace_id='default'" in text
    assert "identity_mismatch" in text


def test_rls_is_verified_with_runtime_role_and_wrong_context() -> None:
    text = read_runbook()

    assert "relrowsecurity=true" in text
    assert "relforcerowsecurity=true" in text
    assert "smartcrm.workspace_id" in text
    assert "contexto ausente ou incorreto" in text


def test_uat_proves_cross_tenant_isolation_for_mutations_and_restore() -> None:
    text = read_runbook()

    assert "mesmo ID público nos tenants A e B" in text
    assert "leitura, criação, alteração, exclusão e restauração" in text
    assert "indisponibilidade do tenant B não muda o roteamento do tenant A" in text


def test_per_tenant_rollback_never_redirects_to_another_tenant_database() -> None:
    text = read_runbook()

    assert "Rollback de um tenant nunca redireciona para o banco de outro tenant." in text
    assert "somente o secret_ref do tenant afetado" in text
    assert "tenant_identity" in text


def test_failed_tenant_is_isolated_without_fleet_wide_rollback() -> None:
    text = read_runbook()

    assert "Falha de um tenant não autoriza rollback em massa." in text
    assert "Os demais tenants permanecem nos próprios bancos" in text
    assert "failed ou inactive" in text


def test_activation_and_basic_auth_cutover_require_recorded_uat() -> None:
    text = read_runbook()

    assert "Ativar cada tenant somente depois" in text
    assert "resultado UAT por tenant" in text
    assert "Basic Auth continua ativa até um corte separado e explicitamente autorizado." in text


def test_no_execution_checklist_targets_activity_head_without_shared_database_changes() -> None:
    text = read_runbook()

    assert "migração tenant `f6b1d3a8c2e4`" in text
    assert "target `f6b1d3a8c2e4`" in text
    assert "`DW_CMS`, `DW_PRODUTOS`, listener PostgreSQL e regras HBA globais permanecem fora da mudança" in text
    assert "conta dedicada `SmartCRMService`" in text
