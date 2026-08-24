"""Build and verify the Docker Compose deployment of the Smart CRM demo."""

from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PORT = int(os.environ.get("SMART_CRM_PORT", "8080"))
BASE_URL = f"http://127.0.0.1:{PORT}"
DB_NAME = os.environ.get("SMART_CRM_DB_NAME", "smartcrm_test")
DB_USER = os.environ.get("SMART_CRM_DB_USER", "smartcrm")


def compose(*arguments: str) -> None:
    command = ["docker", "compose", *arguments]
    print(f"+ {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def compose_output(*arguments: str, env: dict[str, str] | None = None) -> str:
    command = ["docker", "compose", *arguments]
    print(f"+ {' '.join(command)}", flush=True)
    completed = subprocess.run(
        command,
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return completed.stdout.strip()


def postgres(*arguments: str) -> str:
    return compose_output("exec", "-T", "postgres", *arguments)


def fetch(path: str, timeout: float = 3) -> tuple[int, bytes]:
    request = urllib.request.Request(f"{BASE_URL}{path}", headers={"User-Agent": "smart-crm-verifier/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.status, response.read()


def wait_for_health(seconds: int = 30) -> tuple[int, bytes]:
    deadline = time.monotonic() + seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            return fetch("/health")
        except (OSError, urllib.error.URLError) as error:
            last_error = error
            time.sleep(0.5)
    raise AssertionError(f"/health não respondeu em {seconds}s: {last_error}")


def wait_for_postgres(seconds: int = 30) -> None:
    deadline = time.monotonic() + seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            postgres("pg_isready", "-U", DB_USER, "-d", DB_NAME)
            return
        except subprocess.CalledProcessError as error:
            last_error = error
            time.sleep(0.5)
    raise AssertionError(f"PostgreSQL não ficou pronto em {seconds}s: {last_error}")


def compose_services() -> dict[str, dict[str, object]]:
    output = compose_output("ps", "--format", "json")
    try:
        payload = json.loads(output)
        rows = payload if isinstance(payload, list) else [payload]
    except json.JSONDecodeError:
        rows = [json.loads(line) for line in output.splitlines() if line.strip()]
    return {str(row["Service"]): row for row in rows}


def wait_for_services_healthy(seconds: int = 30) -> dict[str, dict[str, object]]:
    deadline = time.monotonic() + seconds
    last_services: dict[str, dict[str, object]] = {}
    while time.monotonic() < deadline:
        last_services = compose_services()
        if all(
            last_services.get(service, {}).get("State") == "running"
            and last_services.get(service, {}).get("Health") == "healthy"
            for service in ("crm", "postgres")
        ):
            return last_services
        time.sleep(0.5)
    raise AssertionError(f"serviços não ficaram saudáveis em {seconds}s: {last_services}")


def main() -> int:
    compose("config", "--quiet")
    config = json.loads(compose_output("config", "--format", "json"))
    assert "postgres" in config["services"], "serviço postgres ausente"
    database = config["services"]["postgres"]
    assert database["image"] == "postgres:17-alpine", database["image"]
    assert any(volume.get("source") == "postgres_data" and volume.get("target") == "/var/lib/postgresql/data" for volume in database["volumes"]), database["volumes"]
    assert any(port.get("host_ip") == "127.0.0.1" and int(port.get("target")) == 5432 for port in database["ports"]), database["ports"]
    override_env = {
        **os.environ,
        "SMART_CRM_DB_NAME": "smartcrm_override_test",
        "SMART_CRM_DB_USER": "smartcrm_override_user",
        "SMART_CRM_DB_PASSWORD": "smartcrm_override_password",
        "SMART_CRM_DB_PORT": "55432",
    }
    override = json.loads(compose_output("config", "--format", "json", env=override_env))["services"]["postgres"]
    assert override["environment"]["POSTGRES_DB"] == "smartcrm_override_test", override["environment"]
    assert override["environment"]["POSTGRES_USER"] == "smartcrm_override_user", override["environment"]
    assert override["environment"]["POSTGRES_PASSWORD"] == "smartcrm_override_password", override["environment"]
    assert any(port.get("host_ip") == "127.0.0.1" and str(port.get("published")) == "55432" for port in override["ports"]), override["ports"]
    compose("build")
    compose("up", "-d")

    health_status, health_body = wait_for_health()
    assert health_status == 200, f"health status inesperado: {health_status}"
    health = json.loads(health_body)
    assert health == {"status": "ok", "service": "smart-crm-demo"}, health

    root_status, root_body = fetch("/")
    assert root_status == 200, f"root status inesperado: {root_status}"
    page = root_body.decode("utf-8")
    assert "Smart CRM — Ambiente de demonstração" in page
    assert "Ambiente de demonstração — dados fictícios" in page

    wait_for_postgres()
    services = wait_for_services_healthy()
    for service in ("crm", "postgres"):
        assert services[service]["State"] == "running", services[service]
        assert services[service]["Health"] == "healthy", services[service]

    identity = postgres("psql", "-X", "-U", DB_USER, "-d", DB_NAME, "-Atqc", "SELECT current_database() || '|' || current_user")
    assert identity == f"{DB_NAME}|{DB_USER}", identity
    probe_sql = "CREATE TABLE IF NOT EXISTS _smartcrm_test_probe (id integer PRIMARY KEY); INSERT INTO _smartcrm_test_probe (id) VALUES (1) ON CONFLICT DO NOTHING; SELECT count(*) FROM _smartcrm_test_probe;"
    assert postgres("psql", "-X", "-U", DB_USER, "-d", DB_NAME, "-Atqc", probe_sql).splitlines()[-1] == "1"
    compose("restart", "postgres")
    wait_for_postgres()
    persisted = postgres("psql", "-X", "-U", DB_USER, "-d", DB_NAME, "-Atqc", "SELECT count(*) FROM _smartcrm_test_probe")
    assert persisted == "1", persisted

    print(f"compose acceptance: 17 passed, 0 failed ({BASE_URL}; PostgreSQL {DB_NAME})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
