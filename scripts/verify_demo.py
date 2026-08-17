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


def compose(*arguments: str) -> None:
    command = ["docker", "compose", *arguments]
    print(f"+ {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


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


def main() -> int:
    compose("config", "--quiet")
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

    print(f"compose acceptance: 7 passed, 0 failed ({BASE_URL})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
