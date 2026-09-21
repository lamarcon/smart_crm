from __future__ import annotations

import importlib.util
import zipfile
from pathlib import Path
import tomllib

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MANUAL_README = PROJECT_ROOT / "deploy/manual-windows-pg11/LEIA-ME.md"


def load_script(name: str):
    path = PROJECT_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


builder = load_script("build_manual_windows_pg11_bundle")
verifier = load_script("verify_manual_windows_pg11_deployment")


def copy_contract_fixture(target_root: Path) -> None:
    deploy = target_root / "deploy/manual-windows-pg11"
    deploy.mkdir(parents=True)
    for source in (PROJECT_ROOT / "deploy/manual-windows-pg11").iterdir():
        if source.is_file():
            (deploy / source.name).write_bytes(source.read_bytes())
    (target_root / "scripts").mkdir()
    (target_root / "scripts/build_manual_windows_pg11_bundle.py").write_bytes(
        (PROJECT_ROOT / "scripts/build_manual_windows_pg11_bundle.py").read_bytes()
    )
    (target_root / "requirements-runtime.txt").write_bytes(
        (PROJECT_ROOT / "requirements-runtime.txt").read_bytes()
    )


def test_runtime_allowlist_contains_required_files_and_excludes_local_state():
    files = {path.as_posix() for path in builder.collect_runtime_files(PROJECT_ROOT)}

    assert "app/main.py" in files
    assert "migrations/env.py" in files
    assert "alembic.ini" in files
    assert "requirements-runtime.txt" in files
    assert "deploy/manual-windows-pg11/install-offline.ps1" in files
    assert not any(path.startswith((".git/", ".specs/", ".venv/", "tests/")) for path in files)
    assert not any(path.endswith(("server.env", ".pyc", ".pyo")) for path in files)


def test_manifest_rejects_missing_modified_and_extra_files(tmp_path: Path):
    (tmp_path / "app").mkdir()
    target = tmp_path / "app/main.py"
    target.write_text("correct", encoding="utf-8")
    builder.write_manifest(tmp_path)
    builder.verify_manifest(tmp_path)

    target.write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError, match="does not match"):
        builder.verify_manifest(tmp_path)
    target.write_text("correct", encoding="utf-8")
    (tmp_path / "unexpected.txt").write_text("extra", encoding="utf-8")
    with pytest.raises(ValueError, match="does not match"):
        builder.verify_manifest(tmp_path)


def test_archive_is_deterministic_and_contains_manifest(tmp_path: Path):
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "runtime.txt").write_text("same bytes", encoding="utf-8")
    builder.write_manifest(staging)
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"

    builder.create_deterministic_zip(staging, first)
    builder.create_deterministic_zip(staging, second)

    assert builder.sha256(first) == builder.sha256(second)
    with zipfile.ZipFile(first) as archive:
        assert set(archive.namelist()) == {"MANIFEST.sha256", "runtime.txt"}


def test_source_contract_covers_every_spec_requirement():
    passed = verifier.verify_source(PROJECT_ROOT)

    assert passed == verifier.REQUIREMENTS


def test_source_contract_rejects_online_pip_install(tmp_path: Path):
    copy_contract_fixture(tmp_path)
    install = tmp_path / "deploy/manual-windows-pg11/install-offline.ps1"
    install.write_text(install.read_text(encoding="utf-8").replace("--no-index", ""), encoding="utf-8")

    with pytest.raises(AssertionError, match="MPG-06"):
        verifier.verify_source(tmp_path)


def test_source_contract_rejects_postgresql_service_restart(tmp_path: Path):
    copy_contract_fixture(tmp_path)
    install = tmp_path / "deploy/manual-windows-pg11/install-offline.ps1"
    with install.open("a", encoding="utf-8") as stream:
        stream.write("\nRestart-Service postgresql-x64-11\n")

    with pytest.raises(AssertionError, match="MPG-08"):
        verifier.verify_source(tmp_path)


def test_source_contract_rejects_missing_control_revision_gate(tmp_path: Path):
    copy_contract_fixture(tmp_path)
    initialize = tmp_path / "deploy/manual-windows-pg11/initialize-and-test.ps1"
    initialize.write_text(
        initialize.read_text(encoding="utf-8").replace(
            "Get-SmartCrmControlAlembicCurrentArguments",
            "Get-UnreviewedControlRevision",
        ),
        encoding="utf-8",
    )

    with pytest.raises(AssertionError, match="MPG-15"):
        verifier.verify_source(tmp_path)


def test_brbots_cutover_is_versioned_preserves_data_and_keeps_secrets_interactive():
    text = MANUAL_README.read_text(encoding="utf-8")

    assert "smart-crm-<SHA>" in text
    assert "Nao sobrescreva a release ativa" in text
    assert "git pull" in text and "proibido" in text
    assert "O database `smartcrm` permanece" in text
    assert "tenant da BRBots" in text
    assert "`smartcrm_control` contem somente" in text
    assert "nao copie dados comerciais" in text
    assert 'register-tenant brbots --display-name "brbots"' in text
    assert "--secret-ref brbots-db --expected-revision a4c9d2e7f1b6" in text
    assert "activate-default brbots --admin-email lfmarcon@brbots.com" in text
    assert '--admin-name "Luiz Felipe"' in text
    assert "senhas sao solicitadas interativamente" in text
    assert "autorizacao de producao separada" in text


def test_shared_postgres_runbook_preserves_remote_databases_and_gates_smartcrm_hba():
    text = MANUAL_README.read_text(encoding="utf-8")

    assert "`DW_CMS`" in text
    assert "`DW_PRODUTOS`" in text
    assert "nao recebem migracao" in text
    assert "host smartcrm,smartcrm_control all 127.0.0.1/32 md5" in text
    assert "host smartcrm,smartcrm_control all 0.0.0.0/0 reject" in text
    assert "pg_reload_conf" in text
    assert "nao reinicia o PostgreSQL" in text
    assert "-SharedPostgres" in text
    assert "-PgHbaPath" in text


def test_runtime_dependencies_match_project_dependencies():
    project = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project_dependencies = set(project["project"]["dependencies"])
    runtime_dependencies = {
        line.strip() for line in (PROJECT_ROOT / "requirements-runtime.txt").read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    assert runtime_dependencies == project_dependencies
