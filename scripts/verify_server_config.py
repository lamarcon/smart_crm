"""Validate the private server Compose contract without starting containers."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = ROOT / "compose.server.yaml"
EXAMPLE_ENV = ROOT / "deploy" / "server" / ".env.server.example"
EXAMPLE_MARKER = "REPLACE_WITH_64_HEX_CHARACTERS"
HEX_PASSWORD = re.compile(r"[0-9a-fA-F]{64}")


class ContractError(RuntimeError):
    pass


def env_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator:
            raise ContractError(f"Linha inválida em {path}: {raw}")
        values[key.strip()] = value.strip()
    return values


def checked_password(values: dict[str, str], *, example: bool) -> str:
    password = values.get("SMART_CRM_DB_PASSWORD", "")
    if example and password == EXAMPLE_MARKER:
        return "0" * 64
    if not HEX_PASSWORD.fullmatch(password):
        raise ContractError(
            "SMART_CRM_DB_PASSWORD deve conter exatamente 64 caracteres hexadecimais."
        )
    return password


def check_model(model: dict[str, Any]) -> int:
    services = model.get("services", {})
    postgres = services.get("postgres", {})
    migrate = services.get("migrate", {})
    crm = services.get("crm", {})
    checks = [
        (set(services) == {"crm", "migrate", "postgres"}, "Serviços inesperados."),
        (not postgres.get("ports"), "PostgreSQL publicou porta no host."),
        (len(crm.get("ports", [])) == 1, "CRM deve publicar uma porta."),
        (
            bool(crm.get("ports"))
            and crm["ports"][0].get("host_ip") == "127.0.0.1"
            and crm["ports"][0].get("target") == 8000,
            "CRM deve bindar 127.0.0.1 e encaminhar para 8000.",
        ),
        (migrate.get("command") == ["alembic", "upgrade", "head"], "Migração incorreta."),
        (crm.get("read_only") is True and migrate.get("read_only") is True, "Runtime gravável."),
        (
            "no-new-privileges:true" in crm.get("security_opt", [])
            and "no-new-privileges:true" in migrate.get("security_opt", []),
            "Novos privilégios não foram bloqueados.",
        ),
        (crm.get("environment", {}).get("SMART_CRM_TEST_MODE") == "0", "Test mode ativo."),
        (
            crm.get("depends_on", {}).get("postgres", {}).get("condition")
            == "service_healthy",
            "CRM não aguarda banco saudável.",
        ),
        (bool(postgres.get("volumes")), "PostgreSQL sem volume persistente."),
    ]
    for passed, message in checks:
        if not passed:
            raise ContractError(message)
    return len(checks)


def compose_model(env_file: Path, password: str) -> dict[str, Any]:
    if shutil.which("docker") is None:
        raise ContractError("Docker CLI não encontrado.")
    environment = os.environ.copy()
    environment["SMART_CRM_DB_PASSWORD"] = password
    command = [
        "docker", "compose", "--env-file", str(env_file),
        "-f", str(COMPOSE_FILE), "--profile", "tools",
        "config", "--format", "json",
    ]
    result = subprocess.run(command, cwd=ROOT, env=environment, capture_output=True, text=True)
    if result.returncode:
        raise ContractError(result.stderr.strip() or result.stdout.strip())
    return json.loads(result.stdout)


def valid_fixture() -> dict[str, Any]:
    return {"services": {
        "postgres": {"volumes": [{"type": "volume"}]},
        "migrate": {
            "command": ["alembic", "upgrade", "head"],
            "read_only": True,
            "security_opt": ["no-new-privileges:true"],
        },
        "crm": {
            "ports": [{"host_ip": "127.0.0.1", "published": "8080", "target": 8000}],
            "read_only": True,
            "security_opt": ["no-new-privileges:true"],
            "environment": {"SMART_CRM_TEST_MODE": "0"},
            "depends_on": {"postgres": {"condition": "service_healthy"}},
        },
    }}


def self_test() -> None:
    assert check_model(valid_fixture()) == 10
    assert checked_password({"SMART_CRM_DB_PASSWORD": "a" * 64}, example=False) == "a" * 64
    for invalid in ("", EXAMPLE_MARKER, "z" * 64):
        try:
            checked_password({"SMART_CRM_DB_PASSWORD": invalid}, example=False)
        except ContractError:
            pass
        else:
            raise AssertionError(f"Segredo inseguro aceito: {invalid!r}")

    mutations = []
    public_db = json.loads(json.dumps(valid_fixture()))
    public_db["services"]["postgres"]["ports"] = [{"target": 5432}]
    mutations.append(public_db)
    public_crm = json.loads(json.dumps(valid_fixture()))
    public_crm["services"]["crm"]["ports"][0]["host_ip"] = "0.0.0.0"
    mutations.append(public_crm)
    wrong_migration = json.loads(json.dumps(valid_fixture()))
    wrong_migration["services"]["migrate"]["command"] = ["alembic", "current"]
    mutations.append(wrong_migration)
    for mutation in mutations:
        try:
            check_model(mutation)
        except ContractError:
            pass
        else:
            raise AssertionError("Modelo inseguro aceito.")
    print("server config self-test: PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env.server")
    parser.add_argument("--example", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    path = EXAMPLE_ENV if args.example else args.env_file.resolve()
    if not path.is_file():
        raise ContractError(f"Arquivo de ambiente não encontrado: {path}")
    password = checked_password(env_values(path), example=args.example)
    count = check_model(compose_model(path, password))
    print(f"server deployment config: {count} passed, 0 failed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ContractError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"server deployment config: FAIL - {error}", file=sys.stderr)
        raise SystemExit(1)
