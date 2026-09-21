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
START = PROJECT_ROOT / "deploy/manual-windows-pg11/start-smart-crm.ps1"
ENV_EXAMPLE = PROJECT_ROOT / "deploy/manual-windows-pg11/server.env.example"

SHARED_POSTGRES_HBA = """\
host smartcrm,smartcrm_control all 127.0.0.1/32 md5
host smartcrm,smartcrm_control all ::1/128 md5
host smartcrm,smartcrm_control all 0.0.0.0/0 reject
host smartcrm,smartcrm_control all ::/0 reject
host all all 0.0.0.0/0 md5
"""


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


def powershell_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def valid_server_environment() -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line and not line.startswith("#"):
            key, value = line.split("=", 1)
            values[key] = value
    values["SMART_CRM_DB_PASSWORD"] = "a" * 64
    values["SMART_CRM_CONTROL_DATABASE_URL"] = (
        "postgresql+psycopg://smartcrm_control:"
        + "b" * 64
        + "@127.0.0.1:5432/smartcrm_control?connect_timeout=5"
    )
    return values


def run_start_validation(
    tmp_path: Path, values: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    app_root = tmp_path / "app"
    python = app_root / ".venv/Scripts/python.exe"
    python.parent.mkdir(parents=True)
    python.write_bytes(b"")
    env_file = tmp_path / "server.env"
    env_file.write_text(
        "\n".join(f"{key}={value}" for key, value in values.items()) + "\n",
        encoding="utf-8",
    )
    return subprocess.run(
        [
            str(POWERSHELL),
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(START),
            "-AppRoot",
            str(app_root),
            "-EnvFile",
            str(env_file),
            "-ValidateOnly",
        ],
        text=True,
        capture_output=True,
        check=False,
    )


def test_builder_creates_versioned_zip_digest_and_complete_windows_payload(tmp_path: Path):
    def fake_downloader(staging: Path, _python: str) -> None:
        wheelhouse = staging / "wheelhouse"
        wheelhouse.mkdir()
        (wheelhouse / "fake_dependency-1.0.0-cp311-cp311-win_amd64.whl").write_bytes(b"wheel")
        (wheelhouse / "argon2_cffi-25.1.0-py3-none-any.whl").write_bytes(b"wheel")
        (
            wheelhouse / "argon2_cffi_bindings-25.1.0-cp39-abi3-win_amd64.whl"
        ).write_bytes(b"wheel")

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


def test_shared_postgresql_listener_requires_exact_leading_smartcrm_hba_rules():
    listeners = "@([pscustomobject]@{LocalAddress='0.0.0.0'},[pscustomobject]@{LocalAddress='::'})"
    valid = run_policy(
        f"$x={listeners}; Assert-SmartCrmPostgresListeners -Listeners $x "
        f"-SharedPostgres -PgHbaText {powershell_literal(SHARED_POSTGRES_HBA)}"
    )
    missing = run_policy(
        f"$x={listeners}; Assert-SmartCrmPostgresListeners -Listeners $x -SharedPostgres"
    )
    reordered_hba = SHARED_POSTGRES_HBA.replace(
        "host smartcrm,smartcrm_control all 127.0.0.1/32 md5\n"
        "host smartcrm,smartcrm_control all ::1/128 md5",
        "host smartcrm,smartcrm_control all ::1/128 md5\n"
        "host smartcrm,smartcrm_control all 127.0.0.1/32 md5",
    )
    reordered = run_policy(
        f"$x={listeners}; Assert-SmartCrmPostgresListeners -Listeners $x "
        f"-SharedPostgres -PgHbaText {powershell_literal(reordered_hba)}"
    )
    weakened = run_policy(
        f"$x={listeners}; Assert-SmartCrmPostgresListeners -Listeners $x "
        "-SharedPostgres -PgHbaText "
        + powershell_literal(SHARED_POSTGRES_HBA.replace("0.0.0.0/0 reject", "0.0.0.0/0 md5"))
    )

    assert valid.returncode == 0, valid.stdout + valid.stderr
    assert missing.returncode != 0
    assert reordered.returncode != 0
    assert weakened.returncode != 0


def test_shared_postgresql_hba_gate_precedes_install_and_both_migrations():
    deploy = PROJECT_ROOT / "deploy/manual-windows-pg11"
    install = (deploy / "install-offline.ps1").read_text(encoding="utf-8")
    initialize = (deploy / "initialize-and-test.ps1").read_text(encoding="utf-8")

    assert "-SharedPostgres" in install
    assert "-PgHbaPath" in install
    assert install.index("Assert-SmartCrmPostgresListeners") < install.index("-m venv")
    assert "-SharedPostgres" in initialize
    assert "-PgHbaPath" in initialize
    assert initialize.index("Assert-SmartCrmPostgresListeners") < initialize.index(
        "Get-SmartCrmControlAlembicUpgradeArguments"
    )


def test_environment_policy_emits_exact_external_database_contract():
    password = "a" * 64
    control_password = "b" * 64
    result = run_policy(
        f"@(New-SmartCrmEnvironmentLines -Password '{password}' "
        f"-ControlPassword '{control_password}') | ConvertTo-Json -Compress"
    )
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
        "SMART_CRM_CONTROL_DATABASE_URL": (
            "postgresql+psycopg://smartcrm_control:"
            f"{control_password}@127.0.0.1:5432/smartcrm_control?connect_timeout=5"
        ),
        "SMART_CRM_TENANT_SECRET_STORE": r"C:\ProgramData\SmartCRM\tenant-secrets",
        "SMART_CRM_EXPECTED_ORIGIN": "https://sc2030.brbots.com",
        "SMART_CRM_TENANT_MAX_CACHED_ENGINES": "16",
        "SMART_CRM_TENANT_POOL_SIZE": "2",
        "SMART_CRM_TENANT_MAX_OVERFLOW": "2",
        "SMART_CRM_TENANT_POOL_TIMEOUT_SECONDS": "5",
        "SMART_CRM_TENANT_CONNECT_TIMEOUT_SECONDS": "3",
        "SMART_CRM_ALLOW_INSECURE_TENANT_LOOPBACK": "1",
    }
    assert '$envPath = Join-Path $programData "server.env"' in install
    assert '$programData = "C:\\ProgramData\\SmartCRM"' in install
    assert "-ControlPassword $controlPassword" in install
    assert "tenant-secrets" in install
    assert "SmartCRMService" in install
    assert "serviceSid" in install


def test_policy_emits_separate_exact_alembic_and_loopback_uvicorn_commands():
    control_upgrade = run_policy(
        "@(Get-SmartCrmControlAlembicUpgradeArguments) | ConvertTo-Json -Compress"
    )
    control_current = run_policy(
        "@(Get-SmartCrmControlAlembicCurrentArguments) | ConvertTo-Json -Compress"
    )
    tenant_upgrade = run_policy(
        "@(Get-SmartCrmTenantAlembicUpgradeArguments) | ConvertTo-Json -Compress"
    )
    tenant_current = run_policy(
        "@(Get-SmartCrmTenantAlembicCurrentArguments) | ConvertTo-Json -Compress"
    )
    uvicorn = run_policy("@(Get-SmartCrmUvicornArguments) | ConvertTo-Json -Compress")

    assert json.loads(control_upgrade.stdout) == [
        "-m", "alembic", "-c", "alembic-control.ini", "upgrade", "c01a5d8e4f20"
    ]
    assert json.loads(control_current.stdout) == [
        "-m", "alembic", "-c", "alembic-control.ini", "current"
    ]
    assert json.loads(tenant_upgrade.stdout) == [
        "-m", "alembic", "-c", "alembic.ini", "upgrade", "a4c9d2e7f1b6"
    ]
    assert json.loads(tenant_current.stdout) == [
        "-m", "alembic", "-c", "alembic.ini", "current"
    ]
    assert json.loads(uvicorn.stdout) == ["-m", "uvicorn", "app.server:create_central_app", "--factory", "--host", "127.0.0.1", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips", "127.0.0.1"]


def test_initializer_migrates_and_verifies_control_then_selected_tenant_before_publish():
    deployment = PROJECT_ROOT / "deploy/manual-windows-pg11"
    initialize = (deployment / "initialize-and-test.ps1").read_text(encoding="utf-8")
    start = (deployment / "start-smart-crm.ps1").read_text(encoding="utf-8")
    ordered_tokens = [
        "Get-SmartCrmControlAlembicUpgradeArguments",
        "Get-SmartCrmControlAlembicCurrentArguments",
        "Get-SmartCrmTenantAlembicUpgradeArguments",
        "Get-SmartCrmTenantAlembicCurrentArguments",
        "install-scheduled-task.ps1",
    ]

    assert all(token in initialize for token in ordered_tokens)
    assert [initialize.index(token) for token in ordered_tokens] == sorted(
        initialize.index(token) for token in ordered_tokens
    )
    assert "$env:SMART_CRM_CONTROL_DATABASE_URL" in initialize
    assert "$env:SMART_CRM_DATABASE_URL" in initialize
    assert "Assert-SmartCrmAlembicRevision" in initialize
    assert "c01a5d8e4f20" in initialize
    assert "a4c9d2e7f1b6" in initialize
    assert "alembic" not in start.lower()


def test_alembic_revision_gate_rejects_wrong_or_unheaded_revision():
    valid = run_policy(
        "Assert-SmartCrmAlembicRevision -Output @('c01a5d8e4f20 (head)') "
        "-ExpectedRevision 'c01a5d8e4f20' -DatabaseLabel 'controle'"
    )
    wrong = run_policy(
        "Assert-SmartCrmAlembicRevision -Output @('revision-errada (head)') "
        "-ExpectedRevision 'c01a5d8e4f20' -DatabaseLabel 'controle'"
    )
    unheaded = run_policy(
        "Assert-SmartCrmAlembicRevision -Output @('c01a5d8e4f20') "
        "-ExpectedRevision 'c01a5d8e4f20' -DatabaseLabel 'controle'"
    )

    assert valid.returncode == 0
    assert wrong.returncode != 0
    assert unheaded.returncode != 0


def test_windows_startup_accepts_complete_central_runtime_environment(tmp_path: Path):
    result = run_start_validation(tmp_path, valid_server_environment())
    start = START.read_text(encoding="utf-8")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "smart crm environment: VALID" in result.stdout
    assert "SMART_CRM_DATABASE_URL" not in start
    assert "SMART_CRM_TEST_MODE" not in start


def test_windows_startup_rejects_control_placeholder_without_disclosing_values(
    tmp_path: Path,
):
    values = valid_server_environment()
    values["SMART_CRM_CONTROL_DATABASE_URL"] = "REPLACE_WITH_CONTROL_DATABASE_URL"

    result = run_start_validation(tmp_path, values)
    output = result.stdout + result.stderr

    assert result.returncode != 0
    assert values["SMART_CRM_CONTROL_DATABASE_URL"] not in output
    assert values["SMART_CRM_DB_PASSWORD"] not in output


def test_windows_startup_rejects_missing_control_url_without_disclosing_values(
    tmp_path: Path,
):
    values = valid_server_environment()
    values.pop("SMART_CRM_CONTROL_DATABASE_URL")

    result = run_start_validation(tmp_path, values)
    output = result.stdout + result.stderr

    assert result.returncode != 0
    assert "SMART_CRM_CONTROL_DATABASE_URL" in output
    assert values["SMART_CRM_DB_PASSWORD"] not in output


def test_windows_startup_rejects_invalid_bounded_pool_before_uvicorn(tmp_path: Path):
    values = valid_server_environment()
    values["SMART_CRM_TENANT_POOL_SIZE"] = "0"

    result = run_start_validation(tmp_path, values)

    assert result.returncode != 0
    assert "SMART_CRM_TENANT_POOL_SIZE" in (result.stdout + result.stderr)


def test_windows_startup_rejects_zero_max_overflow_before_uvicorn(tmp_path: Path):
    values = valid_server_environment()
    values["SMART_CRM_TENANT_MAX_OVERFLOW"] = "0"

    result = run_start_validation(tmp_path, values)

    assert result.returncode != 0
    assert "SMART_CRM_TENANT_MAX_OVERFLOW" in (result.stdout + result.stderr)


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


def test_scheduled_task_requires_dedicated_service_credential_and_dpapi_identity():
    deployment = PROJECT_ROOT / "deploy/manual-windows-pg11"
    install_task = (deployment / "install-scheduled-task.ps1").read_text(
        encoding="utf-8"
    )
    initialize = (deployment / "initialize-and-test.ps1").read_text(encoding="utf-8")
    readme = (deployment / "LEIA-ME.md").read_text(encoding="utf-8")

    assert "[PSCredential]$ServiceCredential" in install_task
    assert "[Parameter(Mandatory = $true)]" in install_task
    assert '"SmartCRMService"' in install_task
    assert '"SYSTEM"' not in install_task
    assert "-User $serviceUser" in install_task
    assert "-Password $servicePassword" in install_task
    assert "[PSCredential]$ServiceCredential" in initialize
    assert "[Parameter(Mandatory = $true)]" in initialize
    assert "-ServiceCredential $ServiceCredential" in initialize
    assert "mesma identidade" in readme
    assert "DPAPI" in readme
    assert "Set-Content" not in install_task

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
