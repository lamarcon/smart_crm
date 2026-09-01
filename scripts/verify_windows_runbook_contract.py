"""Validate the Windows installation runbook's safety and cutover contract."""

from __future__ import annotations

import argparse
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNBOOK = ROOT / "deploy" / "windows-apache" / "README.md"


class ContractError(RuntimeError):
    pass


def runbook_contract(text: str) -> int:
    required = [
        ('sc2030.brbots.com', "Domínio de corte ausente."),
        ('git pull --ff-only origin main', "Instalação Git não é fast-forward-only."),
        ('py -3.12 -m venv .venv', "Virtualenv Python 3.12 ausente."),
        ('-m pip install .', "Instalação de dependências ausente."),
        ('C:\\ProgramData\\SmartCRM\\server.env', "Segredo externo ausente."),
        ("listen_addresses = 'localhost'", "PostgreSQL não está restrito ao localhost."),
        ('CREATE ROLE smartcrm LOGIN;', "Criação do papel PostgreSQL ausente."),
        ('CREATE DATABASE smartcrm OWNER smartcrm', "Criação do banco ausente."),
        ('-m alembic upgrade head', "Migração Alembic ausente."),
        ('install-scheduled-task.ps1', "Registro da tarefa Windows ausente."),
        ('http://127.0.0.1:8080/health', "Health local ausente."),
        ('_acme-challenge.sc2030.brbots.com', "Renovação PunchSalad por DNS ausente."),
        ('x509 -checkend 604800', "Gate de validade TLS ausente."),
        ('Get-FileHash "$tls\\certificate-public.der", "$tls\\key-public.der"', "Correspondência certificado/chave ausente."),
        ('httpd.exe" -t', "Validação Apache ausente."),
        ('curl.exe -I https://sc2030.brbots.com/', "Teste 401 ausente."),
        ('curl.exe --user crm-homologacao https://sc2030.brbots.com/health', "Health HTTPS autenticado ausente."),
        ('{"status":"ok","database":"ok"}', "Payload saudável exato ausente."),
        ('pg_dump.exe', "Backup PostgreSQL ausente."),
        ('git merge --ff-only origin/main', "Atualização Git não é fast-forward-only."),
        ('Stop-ScheduledTask -TaskName SmartCRM', "Parada controlada ausente."),
        ('Copy-Item "$backup\\httpd.conf"', "Rollback Apache ausente."),
        ('Não apague o banco.', "Proteção do banco no rollback ausente."),
        ('Nunca use `git add .`', "Proteção contra staging amplo ausente."),
        ('Não use `-k`/`--insecure`', "UAT permite ignorar TLS."),
    ]
    for token, message in required:
        if token not in text:
            raise ContractError(message)
    forbidden = [
        ('SMART_CRM_DB_PASSWORD=smartcrm', "Runbook contém senha padrão."),
        ('SSLCertificateKeyFile "C:/Apps', "Runbook coloca chave dentro do clone."),
        ('git reset --hard', "Runbook contém reset destrutivo."),
        ('0.0.0.0:8080', "Runbook publica o runtime do CRM."),
    ]
    for token, message in forbidden:
        if token in text:
            raise ContractError(message)
    return len(required) + len(forbidden)


def self_test(valid: str) -> None:
    assert runbook_contract(valid) == 29
    mutations = [
        valid.replace("listen_addresses = 'localhost'", "listen_addresses = '*'"),
        valid.replace("-m alembic upgrade head", "-m alembic current"),
        valid.replace("x509 -checkend 604800", "x509 -noout"),
        valid.replace("git merge --ff-only origin/main", "git reset --hard origin/main"),
    ]
    for mutation in mutations:
        try:
            runbook_contract(mutation)
        except ContractError:
            pass
        else:
            raise AssertionError("Mutação insegura do runbook não detectada.")
    print("windows runbook verifier self-test: PASS (4/4 killed)")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    text = RUNBOOK.read_text(encoding="utf-8")
    if args.self_test:
        self_test(text)
        return 0
    count = runbook_contract(text)
    print(f"windows runbook contract: {count} passed, 0 failed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ContractError, OSError) as error:
        print(f"windows runbook contract: FAIL - {error}")
        raise SystemExit(1)
