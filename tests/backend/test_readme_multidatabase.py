from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
from urllib.parse import urlsplit

from app.auth import AuthSettings


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


def test_documented_local_runtime_origin_matches_tls_uvicorn_command() -> None:
    text = read_readme()
    origin_line = next(
        line for line in text.splitlines() if line.startswith("$env:SMART_CRM_EXPECTED_ORIGIN")
    )
    origin = origin_line.split('"', 2)[1]
    command = next(
        line for line in text.splitlines() if "python -m uvicorn app.server:create_central_app" in line
    )
    tokens = command.split()
    parsed = urlsplit(origin)

    assert parsed.scheme == "https"
    assert parsed.hostname == tokens[tokens.index("--host") + 1]
    assert parsed.port == int(tokens[tokens.index("--port") + 1])
    assert tokens[tokens.index("--ssl-keyfile") + 1] == "$keyPath"
    assert tokens[tokens.index("--ssl-certfile") + 1] == "$certPath"
    assert AuthSettings(expected_origin=origin).expected_origin == origin


def test_documented_local_tls_material_is_temporary_ignored_and_cleaned() -> None:
    text = read_readme()
    gitignore = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()

    assert ".local/" in gitignore
    assert r'$tlsDir = Join-Path $PWD ".local\dev-tls"' in text
    assert '$keyPath = Join-Path $tlsDir "loopback-key.pem"' in text
    assert '$certPath = Join-Path $tlsDir "loopback-cert.pem"' in text
    assert "subjectAltName=IP:127.0.0.1" in text
    assert "--ssl-keyfile $keyPath --ssl-certfile $certPath" in text
    assert "certificado autoassinado é apenas para desenvolvimento local" in text
    assert "aviso de confiança do navegador" in text
    assert "Remove-Item -LiteralPath $tlsDir -Recurse -Force" in text
    assert "Remove-Item Env:SMART_CRM_EXPECTED_ORIGIN -ErrorAction SilentlyContinue" in text


def test_documented_openssl_recipe_generates_loopback_ip_san(tmp_path: Path) -> None:
    text = read_readme()
    openssl = shutil.which("openssl")
    if openssl is None and os.name == "nt":
        program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
        candidate = Path(program_files) / "Git" / "usr" / "bin" / "openssl.exe"
        if candidate.is_file():
            openssl = str(candidate)

    assert openssl is not None
    assert "& $openssl req -x509 -newkey rsa:2048 -sha256 -nodes -days 7" in text
    assert '-addext "subjectAltName=IP:127.0.0.1"' in text

    key_path = tmp_path / "loopback-key.pem"
    cert_path = tmp_path / "loopback-cert.pem"
    subprocess.run(
        [
            openssl,
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-sha256",
            "-nodes",
            "-days",
            "1",
            "-keyout",
            str(key_path),
            "-out",
            str(cert_path),
            "-subj",
            "/CN=127.0.0.1",
            "-addext",
            "subjectAltName=IP:127.0.0.1",
            "-addext",
            "extendedKeyUsage=serverAuth",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    inspected = subprocess.run(
        [openssl, "x509", "-in", str(cert_path), "-noout", "-ext", "subjectAltName"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "IP Address:127.0.0.1" in inspected.stdout


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
