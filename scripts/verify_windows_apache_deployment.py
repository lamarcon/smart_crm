"""Validate the native Windows deployment contract without touching a server."""

from __future__ import annotations

import argparse
import copy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SCRIPT = ROOT / "deploy" / "windows-apache" / "start-smart-crm.ps1"
TASK_SCRIPT = ROOT / "deploy" / "windows-apache" / "install-scheduled-task.ps1"
EXAMPLE_ENV = ROOT / "deploy" / "windows-apache" / "server.env.example"


class ContractError(RuntimeError):
    pass


def require(text: str, token: str, message: str) -> None:
    if token not in text:
        raise ContractError(message)


def reject(text: str, token: str, message: str) -> None:
    if token in text:
        raise ContractError(message)


def runtime_contract(files: dict[str, str]) -> int:
    runtime = files["runtime"]
    task = files["task"]
    example = files["example"]
    checks = [
        (runtime, '"^[0-9a-fA-F]{64}$"', "Validação do segredo ausente."),
        (runtime, '$settings.SMART_CRM_DB_HOST -ne "127.0.0.1"', "Banco não está preso ao loopback."),
        (runtime, '$settings.SMART_CRM_BIND_IP -ne "127.0.0.1"', "Aplicação não está presa ao loopback."),
        (runtime, '$settings.SMART_CRM_PORT -ne "8080"', "Porta do CRM não está fixada em 8080."),
        (runtime, "$env:SMART_CRM_DATABASE_URL = $databaseUrl", "URL de banco não é exportada ao processo."),
        (runtime, "app.main:create_app --factory", "Factory FastAPI ausente."),
        (runtime, '--host "127.0.0.1"', "Uvicorn não usa loopback."),
        (task, 'New-ScheduledTaskTrigger -AtStartup', "Trigger de boot ausente."),
        (task, 'New-ScheduledTaskPrincipal -UserId "SYSTEM"', "Tarefa não roda como SYSTEM."),
        (task, '-RestartCount 10', "Política de reinício insuficiente."),
        (task, '-RestartInterval (New-TimeSpan -Minutes 1)', "Intervalo de reinício incorreto."),
        (example, 'SMART_CRM_DB_PASSWORD=REPLACE_WITH_64_HEX_CHARACTERS', "Placeholder de senha ausente."),
        (example, 'SMART_CRM_BIND_IP=127.0.0.1', "Exemplo publica o CRM fora do loopback."),
    ]
    for text, token, message in checks:
        require(text, token, message)
    reject(runtime, '0.0.0.0', "Runtime contém binding público.")
    reject(example, 'SMART_CRM_DB_PASSWORD=smartcrm', "Exemplo contém senha padrão.")
    return len(checks) + 2


def read_runtime_files() -> dict[str, str]:
    return {
        "runtime": RUNTIME_SCRIPT.read_text(encoding="utf-8"),
        "task": TASK_SCRIPT.read_text(encoding="utf-8"),
        "example": EXAMPLE_ENV.read_text(encoding="utf-8"),
    }


def self_test() -> None:
    valid = read_runtime_files()
    assert runtime_contract(valid) == 15
    mutations = []

    public_bind = copy.deepcopy(valid)
    public_bind["runtime"] = public_bind["runtime"].replace(
        '--host "127.0.0.1"', '--host "0.0.0.0"'
    )
    mutations.append(public_bind)

    weak_secret = copy.deepcopy(valid)
    weak_secret["runtime"] = weak_secret["runtime"].replace(
        '"^[0-9a-fA-F]{64}$"', '"^.+$"'
    )
    mutations.append(weak_secret)

    user_task = copy.deepcopy(valid)
    user_task["task"] = user_task["task"].replace(
        'New-ScheduledTaskPrincipal -UserId "SYSTEM"',
        'New-ScheduledTaskPrincipal -UserId "Administrator"',
    )
    mutations.append(user_task)

    for mutation in mutations:
        try:
            runtime_contract(mutation)
        except ContractError:
            pass
        else:
            raise AssertionError("Mutação insegura não detectada.")
    print("windows runtime verifier self-test: PASS (3/3 killed)")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    count = runtime_contract(read_runtime_files())
    print(f"windows runtime contract: {count} passed, 0 failed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ContractError, OSError) as error:
        print(f"windows runtime contract: FAIL - {error}")
        raise SystemExit(1)
