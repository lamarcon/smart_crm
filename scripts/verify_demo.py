"""Build and verify the PostgreSQL-backed Smart CRM Compose deployment."""

from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from copy import deepcopy
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PORT = int(os.environ.get("SMART_CRM_PORT", "8080"))
BASE_URL = f"http://127.0.0.1:{PORT}"
DB_NAME = os.environ.get("SMART_CRM_DB_NAME", "smartcrm_test")
DB_USER = os.environ.get("SMART_CRM_DB_USER", "smartcrm")
EXPECTED_HEAD = "9f7a2c31d5e8"


class Checks:
    def __init__(self) -> None:
        self.passed = 0

    def equal(self, actual: Any, expected: Any, label: str) -> None:
        assert actual == expected, f"{label}: esperado {expected!r}, recebido {actual!r}"
        self.passed += 1

    def true(self, condition: bool, label: str) -> None:
        assert condition, label
        self.passed += 1


def run(*command: str, env: dict[str, str] | None = None) -> str:
    print(f"+ {' '.join(command)}", flush=True)
    completed = subprocess.run(
        command,
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    if completed.stderr.strip():
        print(completed.stderr.strip(), flush=True)
    return completed.stdout.strip()


def compose(*arguments: str, env: dict[str, str] | None = None) -> str:
    return run("docker", "compose", *arguments, env=env)


def postgres(sql: str) -> str:
    return compose(
        "exec",
        "-T",
        "postgres",
        "psql",
        "-X",
        "-v",
        "ON_ERROR_STOP=1",
        "-U",
        DB_USER,
        "-d",
        DB_NAME,
        "-Atqc",
        sql,
    )


def request(
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    timeout: float = 6,
) -> tuple[int, bytes]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"User-Agent": "smart-crm-verifier/2.0"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    api_request = urllib.request.Request(
        f"{BASE_URL}{path}", data=body, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(api_request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def request_json(
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    status, body = request(path, method=method, payload=payload)
    return status, json.loads(body)


def wait_for_health(
    expected_status: int = 200, seconds: int = 45
) -> tuple[int, dict[str, Any]]:
    deadline = time.monotonic() + seconds
    last_result: object = None
    while time.monotonic() < deadline:
        try:
            status, payload = request_json("/health")
            last_result = (status, payload)
            if status == expected_status:
                return status, payload
        except (OSError, ValueError, urllib.error.URLError) as error:
            last_result = error
        time.sleep(0.5)
    raise AssertionError(
        f"/health não atingiu HTTP {expected_status} em {seconds}s: {last_result}"
    )


def compose_services() -> dict[str, dict[str, Any]]:
    output = compose("ps", "--format", "json")
    try:
        payload = json.loads(output)
        rows = payload if isinstance(payload, list) else [payload]
    except json.JSONDecodeError:
        rows = [json.loads(line) for line in output.splitlines() if line.strip()]
    return {str(row["Service"]): row for row in rows}


def wait_for_services_healthy(seconds: int = 45) -> dict[str, dict[str, Any]]:
    deadline = time.monotonic() + seconds
    services: dict[str, dict[str, Any]] = {}
    while time.monotonic() < deadline:
        services = compose_services()
        if all(
            services.get(name, {}).get("State") == "running"
            and services.get(name, {}).get("Health") == "healthy"
            for name in ("crm", "postgres")
        ):
            return services
        time.sleep(0.5)
    raise AssertionError(f"serviços não ficaram saudáveis: {services}")


def seed_state() -> dict[str, Any]:
    return {
        "currentUserId": "verify-user-1",
        "users": [
            {
                "id": "verify-user-1",
                "name": "Verificador Compose",
                "email": "verify-compose@smartcrm.local",
                "jobTitle": "Administrador",
                "role": "Administrador",
                "team": "Qualidade",
                "status": "Ativo",
                "invitedAt": None,
            }
        ],
        "leads": [
            {
                "id": "verify-lead-1",
                "name": "Lead de verificação",
                "company": "Empresa de verificação",
                "stage": "Em contato",
                "responsibleId": "verify-user-1",
                "assistants": [],
            }
        ],
        "companies": [
            {
                "id": "verify-company-1",
                "name": "Empresa de verificação",
                "city": "São Paulo",
                "segment": "Teste",
                "phone": "",
                "ownerId": "verify-user-1",
            }
        ],
        "contacts": [
            {
                "id": "verify-contact-1",
                "name": "Contato de verificação",
                "company": "Empresa de verificação",
                "companyId": "verify-company-1",
                "email": "",
                "phone": "",
                "role": "Comprador",
            }
        ],
        "deals": [
            {
                "id": "verify-deal-1",
                "title": "Negócio de verificação",
                "company": "Empresa de verificação",
                "companyId": "verify-company-1",
                "contact": "Contato de verificação",
                "contactId": "verify-contact-1",
                "amount": 100,
                "stage": "Em Contato",
                "responsibleId": "verify-user-1",
                "stageChangedById": "verify-user-1",
                "assistants": [],
                "quotes": [
                    {
                        "id": "verify-quote-1",
                        "description": "Item de verificação",
                        "quantity": 1,
                        "unitPrice": 100,
                        "discount": 0,
                        "total": 100,
                        "state": "Enviado",
                    }
                ],
            }
        ],
        "notifications": [
            {
                "id": "verify-notification-1",
                "userId": "verify-user-1",
                "text": "Verificação Compose",
                "detail": "",
                "time": "Agora",
                "read": False,
            }
        ],
        "customFieldSchemas": {
            "leads": [],
            "contacts": [],
            "companies": [],
            "deals": [],
        },
        "moduleFieldSettings": {
            module: {"hiddenStandardFields": [], "hiddenCustomFieldKeys": []}
            for module in ("leads", "contacts", "companies", "deals")
        },
        "ui": {
            "savedFilters": [],
            "viewModesByUser": {"verify-user-1": {"leads": "list"}},
            "dashboardScopeByUser": {"verify-user-1": "all"},
        },
    }


def state_counts(state: dict[str, Any]) -> dict[str, int]:
    schemas = state.get("customFieldSchemas") or {}
    return {
        "users": len(state.get("users") or []),
        "leads": len(state.get("leads") or []),
        "contacts": len(state.get("contacts") or []),
        "companies": len(state.get("companies") or []),
        "deals": len(state.get("deals") or []),
        "quotes": sum(len(deal.get("quotes") or []) for deal in state.get("deals") or []),
        "notifications": len(state.get("notifications") or []),
        "customFields": sum(
            len(schemas.get(module) or [])
            for module in ("leads", "contacts", "companies", "deals")
        ),
    }


def sql_counts() -> dict[str, int]:
    sql = """
        SELECT json_build_object(
          'users', (SELECT count(*) FROM crm_users WHERE workspace_id = 'default' AND deleted_at IS NULL),
          'leads', (SELECT count(*) FROM leads WHERE workspace_id = 'default' AND deleted_at IS NULL),
          'contacts', (SELECT count(*) FROM contacts WHERE workspace_id = 'default' AND deleted_at IS NULL),
          'companies', (SELECT count(*) FROM companies WHERE workspace_id = 'default' AND deleted_at IS NULL),
          'deals', (SELECT count(*) FROM deals WHERE workspace_id = 'default' AND deleted_at IS NULL),
          'quotes', (SELECT count(*) FROM quotes q JOIN deals d ON d.id = q.deal_id WHERE d.workspace_id = 'default' AND q.deleted_at IS NULL),
          'notifications', (SELECT count(*) FROM notifications WHERE workspace_id = 'default' AND deleted_at IS NULL),
          'customFields', (SELECT count(*) FROM custom_field_definitions WHERE workspace_id = 'default' AND deleted_at IS NULL)
        )::text
    """
    return {key: int(value) for key, value in json.loads(postgres(sql)).items()}


def mutation_marker(state: dict[str, Any]) -> tuple[dict[str, Any], str, str]:
    changed = deepcopy(state)
    users = changed.setdefault("users", [])
    if not users:
        users.append(seed_state()["users"][0])
    user_id = users[0]["id"]
    ui = changed.setdefault("ui", {})
    scopes = ui.setdefault("dashboardScopeByUser", {})
    previous = scopes.get(user_id, "all")
    marker = "leads" if previous == "all" else "all"
    scopes[user_id] = marker
    return changed, user_id, marker


def marker_is_present(state: dict[str, Any], user_id: str, marker: str) -> bool:
    return (
        ((state.get("ui") or {}).get("dashboardScopeByUser") or {}).get(user_id)
        == marker
    )


def main() -> int:
    checks = Checks()
    compose("config", "--quiet")
    config = json.loads(compose("config", "--format", "json"))
    database = config["services"]["postgres"]
    crm = config["services"]["crm"]
    checks.equal(database["image"], "postgres:17-alpine", "imagem PostgreSQL")
    checks.true(
        any(
            volume.get("source") == "postgres_data"
            and volume.get("target") == "/var/lib/postgresql/data"
            for volume in database["volumes"]
        ),
        "volume PostgreSQL nomeado ausente",
    )
    checks.true(
        any(
            port.get("host_ip") == "127.0.0.1"
            and int(port.get("target")) == 5432
            for port in database["ports"]
        ),
        "porta PostgreSQL não está limitada ao loopback",
    )
    checks.true(
        "@postgres:5432/" in crm["environment"]["SMART_CRM_DATABASE_URL"],
        "CRM não usa o hostname interno do PostgreSQL",
    )
    checks.equal(crm["environment"]["SMART_CRM_TEST_MODE"], "0", "modo normal")
    checks.equal(
        crm["depends_on"]["postgres"]["condition"],
        "service_healthy",
        "dependência PostgreSQL",
    )
    checks.true(
        bool(crm["depends_on"]["postgres"]["restart"]),
        "CRM não reinicia com a dependência",
    )

    override_env = {
        **os.environ,
        "SMART_CRM_DB_NAME": "smartcrm_override_test",
        "SMART_CRM_DB_USER": "smartcrm_override_user",
        "SMART_CRM_DB_PASSWORD": "smartcrm_override_password",
        "SMART_CRM_DB_PORT": "55432",
    }
    override = json.loads(compose("config", "--format", "json", env=override_env))
    checks.equal(
        override["services"]["postgres"]["environment"]["POSTGRES_DB"],
        "smartcrm_override_test",
        "override do nome do banco",
    )
    checks.true(
        "smartcrm_override_user:smartcrm_override_password@postgres:5432/smartcrm_override_test"
        in override["services"]["crm"]["environment"]["SMART_CRM_DATABASE_URL"],
        "overrides não chegaram à URL interna",
    )

    compose("build")
    compose("up", "-d")
    status, health = wait_for_health()
    checks.equal(status, 200, "health inicial")
    checks.equal(health, {"status": "ok", "database": "ok"}, "payload de health")
    root_status, root_body = request("/")
    checks.equal(root_status, 200, "raiz")
    checks.true(
        "Smart CRM — Ambiente de demonstração" in root_body.decode("utf-8"),
        "página principal não foi servida",
    )
    services = wait_for_services_healthy()
    checks.equal(services["crm"]["Health"], "healthy", "saúde do CRM")
    checks.equal(services["postgres"]["Health"], "healthy", "saúde do PostgreSQL")
    checks.true(int(compose("exec", "-T", "crm", "id", "-u")) != 0, "CRM roda como root")

    image_head = compose("exec", "-T", "crm", "alembic", "heads").split()[0]
    database_head = postgres("SELECT version_num FROM alembic_version")
    checks.equal(image_head, EXPECTED_HEAD, "head Alembic da imagem")
    checks.equal(database_head, EXPECTED_HEAD, "head Alembic do banco")

    probe_sql = """
        CREATE TABLE IF NOT EXISTS _smartcrm_test_probe (id integer PRIMARY KEY);
        INSERT INTO _smartcrm_test_probe (id) VALUES (1) ON CONFLICT DO NOTHING;
        SELECT count(*) FROM _smartcrm_test_probe;
    """
    probe_count = int(postgres(probe_sql).splitlines()[-1])
    checks.true(probe_count >= 1, "probe PostgreSQL não foi preservado")

    load_status, workspace = request_json("/api/workspace")
    checks.equal(load_status, 200, "carga inicial do workspace")
    if not workspace["initialized"]:
        bootstrap_status, bootstrap = request_json(
            "/api/workspace/bootstrap",
            method="POST",
            payload={"state": seed_state()},
        )
        checks.equal(bootstrap_status, 201, "bootstrap em banco vazio")
        workspace = {
            "initialized": True,
            "version": bootstrap["version"],
            "state": bootstrap["state"],
        }
    else:
        checks.true(workspace["version"] > 0, "workspace existente sem versão")
    checks.true(workspace["initialized"], "workspace não inicializado")

    changed, marker_user, marker = mutation_marker(workspace["state"])
    save_status, saved = request_json(
        "/api/workspace",
        method="PUT",
        payload={"version": workspace["version"], "state": changed},
    )
    checks.equal(save_status, 200, "mutação pela API")
    checks.equal(saved["version"], workspace["version"] + 1, "incremento de versão")
    checks.true(
        marker_is_present(saved["state"], marker_user, marker),
        "mutação não voltou no estado canônico",
    )
    checks.equal(saved["counts"], state_counts(saved["state"]), "contagens da API")
    checks.equal(sql_counts(), saved["counts"], "contagens SQL")
    checks.equal(
        int(postgres("SELECT version FROM workspaces WHERE id = 'default'")),
        saved["version"],
        "versão SQL",
    )

    compose("up", "-d", "--force-recreate", "crm")
    wait_for_health()
    recreated_status, recreated = request_json("/api/workspace")
    checks.equal(recreated_status, 200, "carga após recriar CRM")
    checks.equal(recreated["version"], saved["version"], "versão após recriar CRM")
    checks.true(
        marker_is_present(recreated["state"], marker_user, marker),
        "mutação não sobreviveu à recriação do CRM",
    )

    compose("restart", "postgres")
    wait_for_services_healthy()
    checks.equal(
        int(postgres("SELECT count(*) FROM _smartcrm_test_probe")),
        probe_count,
        "probe após restart do PostgreSQL",
    )
    restart_status, restarted = request_json("/api/workspace")
    checks.equal(restart_status, 200, "API após restart do PostgreSQL")
    checks.equal(restarted["version"], saved["version"], "versão após restart PostgreSQL")

    compose("stop", "postgres")
    degraded_status, degraded = wait_for_health(503)
    checks.equal(degraded_status, 503, "health degradado")
    checks.equal(
        degraded,
        {"status": "degraded", "database": "unavailable"},
        "payload degradado",
    )
    unavailable_status, unavailable = request_json("/api/workspace")
    checks.equal(unavailable_status, 503, "API com banco indisponível")
    error_id = unavailable["error"].get("errorId", "")
    checks.true(bool(error_id), "erro de banco sem errorId")
    checks.true(error_id in compose("logs", "--no-color", "crm"), "errorId ausente do log")
    degraded_root_status, _body = request("/")
    checks.equal(degraded_root_status, 200, "raiz durante indisponibilidade")

    compose("start", "postgres")
    recovered_status, recovered = wait_for_health(200)
    checks.equal(recovered_status, 200, "health recuperado")
    checks.equal(recovered, {"status": "ok", "database": "ok"}, "payload recuperado")
    recovered_load_status, recovered_workspace = request_json("/api/workspace")
    checks.equal(recovered_load_status, 200, "API recuperada")
    checks.equal(recovered_workspace["version"], saved["version"], "versão recuperada")
    checks.true(
        marker_is_present(recovered_workspace["state"], marker_user, marker),
        "mutação não sobreviveu à recuperação",
    )
    checks.equal(
        int(postgres("SELECT count(*) FROM _smartcrm_test_probe")),
        probe_count,
        "probe após recuperação",
    )
    final_services = wait_for_services_healthy()
    checks.true(
        all(final_services[name]["Health"] == "healthy" for name in ("crm", "postgres")),
        "serviços não terminaram saudáveis",
    )

    print(
        f"compose acceptance: {checks.passed} passed, 0 failed "
        f"({BASE_URL}; PostgreSQL {DB_NAME}; Alembic {EXPECTED_HEAD})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
