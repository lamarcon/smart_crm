from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
POWERSHELL = Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
POLICY = PROJECT_ROOT / "deploy/manual-windows-pg11/deployment-policy.ps1"


def load_builder():
    path = PROJECT_ROOT / "scripts/build_manual_windows_pg11_bundle.py"
    spec = importlib.util.spec_from_file_location("manual_bundle_builder_outcomes", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


builder = load_builder()


def run_policy(expression: str) -> subprocess.CompletedProcess[str]:
    command = f". '{POLICY}'; {expression}"
    return subprocess.run(
        [str(POWERSHELL), "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
        text=True,
        capture_output=True,
        check=False,
    )


def test_builder_creates_versioned_zip_digest_and_complete_windows_payload(tmp_path: Path):
    def fake_downloader(staging: Path, _python: str) -> None:
        wheelhouse = staging / "wheelhouse"
        wheelhouse.mkdir()
        (wheelhouse / "fake_dependency-1.0.0-cp311-cp311-win_amd64.whl").write_bytes(b"wheel")

    archive, digest_file = builder.build(
        PROJECT_ROOT,
        tmp_path,
        python="unused",
        version="deadbeef",
        wheel_downloader=fake_downloader,
    )

    assert archive.name == "smart-crm-manual-pg11-deadbeef.zip"
    assert digest_file.name == "smart-crm-manual-pg11-deadbeef.zip.sha256"
    assert digest_file.read_text(encoding="ascii") == f"{builder.sha256(archive)}  {archive.name}\n"
    with zipfile.ZipFile(archive) as bundle:
        names = set(bundle.namelist())
        assert "app/main.py" in names
        assert "migrations/env.py" in names
        assert "alembic.ini" in names
        assert "requirements-runtime.txt" in names
        assert "deploy/manual-windows-pg11/install-offline.ps1" in names
        assert "MANIFEST.sha256" in names
        assert "wheelhouse/fake_dependency-1.0.0-cp311-cp311-win_amd64.whl" in names
        assert not any(name.startswith((".git/", ".specs/", ".venv/", "tests/")) for name in names)


def test_powershell_integrity_gate_returns_nonzero_for_missing_file_before_install(tmp_path: Path):
    script_dir = tmp_path / "deploy/manual-windows-pg11"
    script_dir.mkdir(parents=True)
    shutil.copy2(PROJECT_ROOT / "deploy/manual-windows-pg11/test-package-integrity.ps1", script_dir)
    payload = tmp_path / "payload.txt"
    payload.write_text("required", encoding="utf-8")
    builder.write_manifest(tmp_path)
    payload.unlink()

    result = subprocess.run(
        [str(POWERSHELL), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script_dir / "test-package-integrity.ps1"), "-AppRoot", str(tmp_path)],
        text=True,
        capture_output=True,
        check=False,
    )
    install = (PROJECT_ROOT / "deploy/manual-windows-pg11/install-offline.ps1").read_text(encoding="utf-8")

    assert result.returncode != 0
    assert install.index("test-package-integrity.ps1") < install.index("-m venv")


def test_runtime_policy_accepts_only_cpython_311_x64():
    valid = run_policy("Assert-SmartCrmRuntimeFacts -Implementation CPython -Major 3 -Minor 11 -Bits 64")
    invalid = [
        run_policy("Assert-SmartCrmRuntimeFacts -Implementation PyPy -Major 3 -Minor 11 -Bits 64"),
        run_policy("Assert-SmartCrmRuntimeFacts -Implementation CPython -Major 3 -Minor 12 -Bits 64"),
        run_policy("Assert-SmartCrmRuntimeFacts -Implementation CPython -Major 3 -Minor 11 -Bits 32"),
    ]

    assert valid.returncode == 0
    assert all(result.returncode != 0 for result in invalid)
    assert all("CPython 3.11 x64" in (result.stdout + result.stderr) for result in invalid)


def test_postgresql_listener_policy_requires_ipv4_loopback_and_rejects_public_binding():
    valid = run_policy("$x=@([pscustomobject]@{LocalAddress='127.0.0.1'}); Assert-SmartCrmPostgresListeners -Listeners $x")
    none = run_policy("Assert-SmartCrmPostgresListeners -Listeners @()")
    ipv6_only = run_policy("$x=@([pscustomobject]@{LocalAddress='::1'}); Assert-SmartCrmPostgresListeners -Listeners $x")
    public = run_policy("$x=@([pscustomobject]@{LocalAddress='127.0.0.1'},[pscustomobject]@{LocalAddress='0.0.0.0'}); Assert-SmartCrmPostgresListeners -Listeners $x")

    assert valid.returncode == 0
    assert none.returncode != 0
    assert ipv6_only.returncode != 0
    assert public.returncode != 0


def test_environment_policy_emits_exact_external_database_contract():
    password = "a" * 64
    result = run_policy(f"@(New-SmartCrmEnvironmentLines -Password '{password}') | ConvertTo-Json -Compress")
    values = dict(line.split("=", 1) for line in json.loads(result.stdout))
    install = (PROJECT_ROOT / "deploy/manual-windows-pg11/install-offline.ps1").read_text(encoding="utf-8")

    assert result.returncode == 0
    assert values == {
        "SMART_CRM_DB_NAME": "smartcrm",
        "SMART_CRM_DB_USER": "smartcrm",
        "SMART_CRM_DB_PASSWORD": password,
        "SMART_CRM_DB_HOST": "127.0.0.1",
        "SMART_CRM_DB_PORT": "5432",
        "SMART_CRM_BIND_IP": "127.0.0.1",
        "SMART_CRM_PORT": "8080",
    }
    assert '$envPath = Join-Path $programData "server.env"' in install
    assert '$programData = "C:\\ProgramData\\SmartCRM"' in install


def test_policy_emits_exact_alembic_and_loopback_uvicorn_commands():
    alembic = run_policy("@(Get-SmartCrmAlembicUpgradeArguments) | ConvertTo-Json -Compress")
    uvicorn = run_policy("@(Get-SmartCrmUvicornArguments) | ConvertTo-Json -Compress")

    assert json.loads(alembic.stdout) == ["-m", "alembic", "upgrade", "head"]
    assert json.loads(uvicorn.stdout) == ["-m", "uvicorn", "app.main:create_app", "--factory", "--host", "127.0.0.1", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips", "127.0.0.1"]


def test_health_policy_rejects_each_partial_failure():
    outcomes = {}
    for status, database in (("ok", "ok"), ("bad", "ok"), ("ok", "bad"), ("bad", "bad")):
        expression = f"$h=[pscustomobject]@{{status='{status}';database='{database}'}}; if (Test-SmartCrmHealth -Health $h) {{ exit 0 }} else {{ exit 9 }}"
        outcomes[(status, database)] = run_policy(expression).returncode

    assert outcomes == {("ok", "ok"): 0, ("bad", "ok"): 9, ("ok", "bad"): 9, ("bad", "bad"): 9}


def test_migration_failure_throws_before_publication_and_apache_is_absent():
    failure = run_policy("Assert-SmartCrmCommandSucceeded -ExitCode 7 -FailureMessage 'migration-blocked'")
    success = run_policy("Assert-SmartCrmCommandSucceeded -ExitCode 0 -FailureMessage 'must-not-throw'")
    initialize = (PROJECT_ROOT / "deploy/manual-windows-pg11/initialize-and-test.ps1").read_text(encoding="utf-8")

    assert failure.returncode != 0
    assert "migration-blocked" in (failure.stdout + failure.stderr)
    assert success.returncode == 0
    assert initialize.index("Assert-SmartCrmCommandSucceeded") < initialize.index("install-scheduled-task.ps1")
    assert "httpd.exe" not in initialize
    assert "Restart-Service" not in initialize

def test_server_app_root_defaults_match_the_existing_brbots_directory():
    expected = '[string]$AppRoot = "C:\\brbots\\apps\\smart-crm"'
    deployment = PROJECT_ROOT / "deploy/manual-windows-pg11"
    scripts = [
        (deployment / name).read_text(encoding="utf-8")
        for name in ("start-smart-crm.ps1", "initialize-and-test.ps1", "install-scheduled-task.ps1")
    ]
    readme = (deployment / "LEIA-ME.md").read_text(encoding="utf-8")

    assert all(expected in script for script in scripts)
    assert "C:\\brbots\\apps\\smart-crm" in readme
    assert "C:\\Apps\\smart-crm" not in readme