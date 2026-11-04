from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
POWERSHELL = Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
POLICY = PROJECT_ROOT / "deploy/manual-windows-pg11/deployment-policy.ps1"
START = PROJECT_ROOT / "deploy/manual-windows-pg11/start-smart-crm.ps1"
FLEET_RUNNER = PROJECT_ROOT / "deploy/manual-windows-pg11/run-fleet-migration.ps1"
FLEET_TASK_INVOKER = PROJECT_ROOT / "deploy/manual-windows-pg11/invoke-fleet-migration-task.ps1"
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
    values["SMART_CRM_SMTP_HOST"] = "smtp.example.test"
    values["SMART_CRM_SMTP_USERNAME"] = "crm@example.test"
    values["SMART_CRM_SMTP_FROM_ADDRESS"] = "crm@example.test"
    return values


TEST_SMTP_PASSWORD = "senha-smtp-ficticia-2026"
EXAMPLE_SMTP_SECRET = r"C:\ProgramData\SmartCRM\service-secrets\smtp-password.bin"


def write_service_secret(
    path: Path, payload: bytes, *, protect: bool = True, broad_acl: bool = False
) -> None:
    from app.security.secrets import DpapiProtector

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(DpapiProtector().protect(payload) if protect else payload)
    owner = f"{os.environ['USERDOMAIN']}\\{os.environ['USERNAME']}"
    grants = [f"{owner}:F"] + (["*S-1-5-32-545:R"] if broad_acl else [])
    subprocess.run(
        ["icacls", str(path), "/inheritance:r", "/grant:r", *grants],
        check=True,
        capture_output=True,
    )


def run_start_validation(
    tmp_path: Path,
    values: dict[str, str],
    *,
    secret: bytes | None = TEST_SMTP_PASSWORD.encode(),
    protect: bool = True,
    broad_acl: bool = False,
    extra_args: tuple[str, ...] = (),
) -> subprocess.CompletedProcess[str]:
    secret_file = tmp_path / "service-secrets" / "smtp-password.bin"
    values = dict(values)
    if values.get("SMART_CRM_SMTP_PASSWORD_SECRET_FILE") == EXAMPLE_SMTP_SECRET:
        values["SMART_CRM_SMTP_PASSWORD_SECRET_FILE"] = str(secret_file)
    if secret is not None:
        write_service_secret(secret_file, secret, protect=protect, broad_acl=broad_acl)
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
            "-SmtpPasswordSecretFile",
            str(secret_file),
            "-ValidateOnly",
            *extra_args,
        ],
        text=True,
        capture_output=True,
        check=False,
    )


def write_fleet_runner_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    app_root = tmp_path / "smart-crm-v0.3.4"
    python = app_root / ".venv/Scripts/python.exe"
    python.parent.mkdir(parents=True)
    python.write_bytes(b"")
    env_file = tmp_path / "server.env"
    env_file.write_text(
        "SMART_CRM_DB_NAME=smartcrm\n"
        "SMART_CRM_CONTROL_DATABASE_URL="
        "postgresql+psycopg://control:must-not-leak@127.0.0.1/control\n"
        r"SMART_CRM_TENANT_SECRET_STORE=C:\ProgramData\SmartCRM\tenant-secrets"
        "\nSMART_CRM_ALLOW_INSECURE_TENANT_LOOPBACK=1\n",
        encoding="utf-8",
    )
    return app_root, env_file, tmp_path / "evidence.json"


def run_fleet_runner(
    app_root: Path,
    env_file: Path,
    evidence: Path,
    *,
    migration_exit_code: int,
    migration_output: str,
    migration_error: str = "",
) -> subprocess.CompletedProcess[str]:
    invoker = (
        "$invoker={ param($FilePath,$ArgumentList,$WorkingDirectory) "
        "if ($ArgumentList[-1] -eq 'heads') { "
        "return [pscustomobject]@{ExitCode=0;StdOut='a8d4e6f2b1c9 (head)';StdErr=''} }; "
        "if (-not $env:SMART_CRM_CONTROL_DATABASE_URL -or "
        "-not $env:SMART_CRM_TENANT_SECRET_STORE -or "
        "$env:SMART_CRM_ALLOW_INSECURE_TENANT_LOOPBACK -ne '1') { "
        "throw 'runtime environment missing' }; "
        f"return [pscustomobject]@{{ExitCode={migration_exit_code};"
        f"StdOut={powershell_literal(migration_output)};"
        f"StdErr={powershell_literal(migration_error)}}} }}; "
    )
    command = (
        "$env:SMART_CRM_CONTROL_DATABASE_URL='parent-control'; "
        "$env:SMART_CRM_TENANT_SECRET_STORE='parent-store'; "
        "$env:SMART_CRM_ALLOW_INSECURE_TENANT_LOOPBACK='parent-loopback'; "
        + invoker
        + f"& {powershell_literal(str(FLEET_RUNNER))} "
        f"-AppRoot {powershell_literal(str(app_root))} "
        f"-EnvFile {powershell_literal(str(env_file))} "
        "-TenantSlug 'brbots' "
        f"-EvidencePath {powershell_literal(str(evidence))} "
        "-BackupAcknowledged -NativeProcessInvoker $invoker; "
        "if ($env:SMART_CRM_CONTROL_DATABASE_URL -ne 'parent-control' -or "
        "$env:SMART_CRM_TENANT_SECRET_STORE -ne 'parent-store' -or "
        "$env:SMART_CRM_ALLOW_INSECURE_TENANT_LOOPBACK -ne 'parent-loopback') { "
        "throw 'runner environment leaked' }"
    )
    return subprocess.run(
        [
            str(POWERSHELL),
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            command,
        ],
        text=True,
        capture_output=True,
        check=False,
    )


def run_fleet_task_invoker(tmp_path: Path, scenario: str) -> subprocess.CompletedProcess[str]:
    app_root = tmp_path / "smart-crm-v0.3.4"
    runner = app_root / "deploy/manual-windows-pg11/run-fleet-migration.ps1"
    python = app_root / ".venv/Scripts/python.exe"
    runner.parent.mkdir(parents=True)
    python.parent.mkdir(parents=True)
    runner.write_text("# fixture\n", encoding="utf-8")
    python.write_bytes(b"")
    env_file = tmp_path / "server.env"
    env_file.write_text("SMART_CRM_DB_NAME=smartcrm\n", encoding="utf-8")
    evidence_dir = tmp_path / "evidence"
    harness = tmp_path / "invoke-harness.ps1"
    harness.write_text(
        rf"""
$ErrorActionPreference = "Stop"
$global:scenario = {powershell_literal(scenario)}
$global:started = $false
$global:registered = $false
$global:unregistered = $false
$global:stopped = $false
$global:action = $null
$global:taskName = $null

function New-ScheduledTaskAction {{
    param($Execute, $Argument, $WorkingDirectory)
    return [pscustomobject]@{{Execute=$Execute;Arguments=$Argument;WorkingDirectory=$WorkingDirectory}}
}}
function New-ScheduledTaskSettingsSet {{
    param([switch]$StartWhenAvailable, $ExecutionTimeLimit, $MultipleInstances)
    return [pscustomobject]@{{ExecutionTimeLimit=$ExecutionTimeLimit}}
}}
function Register-ScheduledTask {{
    param($TaskName, $Action, $Settings, $User, $Password, $RunLevel, $Description, [switch]$Force)
    $global:registered = $true
    $global:action = $Action
    $global:taskName = $TaskName
    $global:registeredUser = $User
}}
function Start-ScheduledTask {{
    param($TaskName)
    $global:started = $true
    if ($global:scenario -eq 'timeout') {{ return }}
    $arguments = $global:action.Arguments
    if ($arguments -notmatch '-EvidencePath\s+"([^"]+)"') {{ throw 'evidence path missing' }}
    $path = $Matches[1]
    if ($global:scenario -eq 'malformed') {{
        [IO.File]::WriteAllText($path, '{{bad json', (New-Object Text.UTF8Encoding($false)))
        return
    }}
    $arguments -match '-AppRoot\s+"([^"]+)"' | Out-Null
    $release = $Matches[1]
    $arguments -match '-TenantSlug\s+"([^"]+)"' | Out-Null
    $tenant = $Matches[1]
    $failed = $global:scenario -eq 'failure'
    $payload = [ordered]@{{
        schemaVersion=1
        releasePath=$release
        targetRevision='a8d4e6f2b1c9'
        tenants=@([ordered]@{{
            slug=$tenant
            succeeded=(-not $failed)
            code=$(if ($failed) {{'migration_failed'}} else {{'migrated'}})
        }})
        exitCode=$(if ($failed) {{7}} else {{0}})
    }}
    [IO.File]::WriteAllText(
        $path,
        ($payload | ConvertTo-Json -Depth 4),
        (New-Object Text.UTF8Encoding($false))
    )
}}
function Get-ScheduledTask {{
    param($TaskName)
    if ($global:scenario -eq 'timeout' -and $global:started) {{
        return [pscustomobject]@{{State='Running'}}
    }}
    return [pscustomobject]@{{State='Ready'}}
}}
function Get-ScheduledTaskInfo {{
    param($TaskName)
    if (-not $global:started) {{
        return [pscustomobject]@{{LastRunTime=[datetime]::MinValue;LastTaskResult=267011}}
    }}
    $result = if ($global:scenario -eq 'failure') {{7}} else {{0}}
    return [pscustomobject]@{{LastRunTime=[datetime]::UtcNow;LastTaskResult=$result}}
}}
function Stop-ScheduledTask {{ param($TaskName); $global:stopped = $true }}
function Unregister-ScheduledTask {{
    param($TaskName, [switch]$Confirm)
    $global:unregistered = $true
}}
function icacls {{ $global:LASTEXITCODE = 0 }}

$secure = New-Object Security.SecureString
foreach ($character in 'fixture-only'.ToCharArray()) {{ $secure.AppendChar($character) }}
$secure.MakeReadOnly()
$user = if ($global:scenario -eq 'wrong_user') {{'HOST\Other'}} else {{'HOST\SmartCRMService'}}
$credential = New-Object Management.Automation.PSCredential($user, $secure)
$threw = $false
try {{
    & {powershell_literal(str(FLEET_TASK_INVOKER))} `
        -AppRoot {powershell_literal(str(app_root))} `
        -EnvFile {powershell_literal(str(env_file))} `
        -TenantSlug 'brbots' `
        -EvidenceDirectory {powershell_literal(str(evidence_dir))} `
        -ServiceCredential $credential `
        -BackupAcknowledged `
        -TimeoutSeconds 0.03 `
        -PollMilliseconds 1
}}
catch {{
    $threw = $true
}}

if ($global:scenario -eq 'success') {{
    if ($threw -or -not $global:registered -or -not $global:unregistered) {{ exit 41 }}
    if ($global:registeredUser -ne 'HOST\SmartCRMService') {{ exit 42 }}
    exit 0
}}
if ($global:scenario -eq 'wrong_user') {{
    if (-not $threw -or $global:registered) {{ exit 43 }}
    exit 9
}}
if (-not $threw -or -not $global:registered -or -not $global:unregistered) {{ exit 44 }}
if ($global:scenario -eq 'timeout' -and -not $global:stopped) {{ exit 45 }}
exit 9
""",
        encoding="utf-8",
    )
    return subprocess.run(
        [
            str(POWERSHELL),
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(harness),
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
        "SMART_CRM_SMTP_HOST": "REPLACE_WITH_SMTP_HOST",
        "SMART_CRM_SMTP_PORT": "587",
        "SMART_CRM_SMTP_USERNAME": "REPLACE_WITH_SMTP_USERNAME",
        "SMART_CRM_SMTP_FROM_ADDRESS": "REPLACE_WITH_SMTP_FROM_ADDRESS",
        "SMART_CRM_SMTP_TLS_MODE": "starttls",
        "SMART_CRM_SMTP_TIMEOUT_SECONDS": "10",
        "SMART_CRM_SMTP_PASSWORD_SECRET_FILE": r"C:\ProgramData\SmartCRM\service-secrets\smtp-password.bin",
    }
    assert '$envPath = Join-Path $programData "server.env"' in install
    assert '$programData = "C:\\ProgramData\\SmartCRM"' in install
    assert "-ControlPassword $controlPassword" in install
    assert "tenant-secrets" in install
    assert "SmartCRMService" in install
    assert "serviceSid" in install


def test_environment_parser_preserves_windows_paths_and_embedded_equals(tmp_path: Path):
    env_file = tmp_path / "server.env"
    env_file.write_text(
        "# comentario\n"
        r"SMART_CRM_TENANT_SECRET_STORE=C:\ProgramData\SmartCRM\tenant-secrets"
        "\nSMART_CRM_TEST_VALUE=one=two=three\n",
        encoding="utf-8",
    )
    result = run_policy(
        f"$settings=Read-SmartCrmEnvironment -Path {powershell_literal(str(env_file))} "
        "-AllowedKeys @('SMART_CRM_TENANT_SECRET_STORE','SMART_CRM_TEST_VALUE'); "
        "@($settings['SMART_CRM_TENANT_SECRET_STORE'],$settings['SMART_CRM_TEST_VALUE']) "
        "| ConvertTo-Json -Compress"
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == [
        r"C:\ProgramData\SmartCRM\tenant-secrets",
        "one=two=three",
    ]


def test_environment_parser_rejects_duplicate_and_invalid_keys_without_values(
    tmp_path: Path,
):
    secret = "must-not-appear-in-errors"
    duplicate = tmp_path / "duplicate.env"
    duplicate.write_text(
        f"SMART_CRM_PORT=8080\nSMART_CRM_PORT={secret}\n", encoding="utf-8"
    )
    invalid = tmp_path / "invalid.env"
    invalid.write_text(f"NOT_ALLOWED={secret}\n", encoding="utf-8")

    duplicate_result = run_policy(
        f"Read-SmartCrmEnvironment -Path {powershell_literal(str(duplicate))} "
        "-AllowedKeys @('SMART_CRM_PORT') | Out-Null"
    )
    invalid_result = run_policy(
        f"Read-SmartCrmEnvironment -Path {powershell_literal(str(invalid))} "
        "-AllowedKeys @('SMART_CRM_PORT') | Out-Null"
    )

    assert duplicate_result.returncode != 0
    assert invalid_result.returncode != 0
    assert secret not in duplicate_result.stdout + duplicate_result.stderr
    assert secret not in invalid_result.stdout + invalid_result.stderr


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
        "-m", "alembic", "-c", "alembic-control.ini", "upgrade", "d5f0a8c3e7b2"
    ]
    assert json.loads(control_current.stdout) == [
        "-m", "alembic", "-c", "alembic-control.ini", "current"
    ]
    assert json.loads(tenant_upgrade.stdout) == [
        "-m", "alembic", "-c", "alembic.ini", "upgrade", "f6b1d3a8c2e4"
    ]
    assert json.loads(tenant_current.stdout) == [
        "-m", "alembic", "-c", "alembic.ini", "current"
    ]
    assert json.loads(uvicorn.stdout) == ["-m", "uvicorn", "app.server:create_central_app", "--factory", "--host", "127.0.0.1", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips", "127.0.0.1"]


def test_initializer_uses_fleet_then_verified_cutover_without_direct_tenant_alembic():
    deployment = PROJECT_ROOT / "deploy/manual-windows-pg11"
    initialize = (deployment / "initialize-and-test.ps1").read_text(encoding="utf-8")
    start = (deployment / "start-smart-crm.ps1").read_text(encoding="utf-8")
    readme = (deployment / "LEIA-ME.md").read_text(encoding="utf-8")
    ordered_tokens = [
        "Get-SmartCrmControlAlembicUpgradeArguments",
        "Get-SmartCrmControlAlembicCurrentArguments",
        "invoke-fleet-migration-task.ps1",
        "Export-ScheduledTask",
        "Stop-ScheduledTask",
        "Wait-SmartCrmPortReleased",
        "install-scheduled-task.ps1",
        "Assert-SmartCrmScheduledTaskTarget",
        "Wait-SmartCrmReleaseReady",
        "LOCAL GATE: PASS",
    ]

    assert all(token in initialize for token in ordered_tokens)
    assert [initialize.index(token) for token in ordered_tokens] == sorted(
        initialize.index(token) for token in ordered_tokens
    )
    assert "$env:SMART_CRM_CONTROL_DATABASE_URL" in initialize
    assert "Assert-SmartCrmAlembicRevision" in initialize
    assert "d5f0a8c3e7b2" in initialize
    assert "Get-SmartCrmTenantAlembicUpgradeArguments" not in initialize
    assert "Get-SmartCrmTenantAlembicCurrentArguments" not in initialize
    assert "SMART_CRM_DATABASE_URL" not in initialize
    assert "ConvertFrom-StringData" not in initialize
    assert "[string]$TenantSlug" in initialize
    assert "[string]$ExpectedVersion" in initialize
    assert "[switch]$BackupAcknowledged" in initialize
    assert "Register-ScheduledTask" in initialize
    assert "-Xml" in initialize
    assert "recovery" in initialize.lower()
    assert "$previousTaskXml" in initialize
    assert "Start-ScheduledTask -TaskName $TaskName" in initialize
    assert "a tarefa anterior foi restaurada" in initialize
    assert "Use o XML preservado em $recoveryPath" in initialize
    assert readme.count("initialize-and-test.ps1") == 1
    assert "UPDATE control_tenants" not in readme
    assert "nao altere `expected_tenant_revision` manualmente" in readme
    assert "alembic" not in start.lower()


def test_pipeline_release_preserves_side_by_side_identity_hba_and_rollback_contract():
    deploy = PROJECT_ROOT / "deploy/manual-windows-pg11"
    readme = (deploy / "LEIA-ME.md").read_text(encoding="utf-8")
    policy = POLICY.read_text(encoding="utf-8")

    assert "C:\\brbots\\apps\\smart-crm-<SHA>" in readme
    assert "Nao sobrescreva a release ativa" in readme
    assert "SmartCRMService" in readme
    assert "host smartcrm,smartcrm_control all 0.0.0.0/0 reject" in policy
    assert "restaure a tarefa anterior" in readme
    assert "Rollback de um tenant nunca redireciona para o banco de outro tenant." in readme
    assert "a8d4e6f2b1c9" in readme


def test_alembic_revision_gate_rejects_wrong_or_unheaded_revision():
    valid = run_policy(
        "Assert-SmartCrmAlembicRevision -Output @('d5f0a8c3e7b2 (head)') "
        "-ExpectedRevision 'd5f0a8c3e7b2' -DatabaseLabel 'controle'"
    )
    wrong = run_policy(
        "Assert-SmartCrmAlembicRevision -Output @('revision-errada (head)') "
        "-ExpectedRevision 'd5f0a8c3e7b2' -DatabaseLabel 'controle'"
    )
    unheaded = run_policy(
        "Assert-SmartCrmAlembicRevision -Output @('d5f0a8c3e7b2') "
        "-ExpectedRevision 'd5f0a8c3e7b2' -DatabaseLabel 'controle'"
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


def test_release_readiness_requires_health_ok_and_exact_version():
    valid = run_policy(
        "$health=[pscustomobject]@{status='ok'}; "
        "$version=[pscustomobject]@{version='0.3.4'}; "
        "Assert-SmartCrmReleaseReadiness -Health $health -Version $version "
        "-ExpectedVersion '0.3.4'"
    )
    bad_health = run_policy(
        "$health=[pscustomobject]@{status='bad'}; "
        "$version=[pscustomobject]@{version='0.3.4'}; "
        "Assert-SmartCrmReleaseReadiness -Health $health -Version $version "
        "-ExpectedVersion '0.3.4'"
    )
    wrong_version = run_policy(
        "$health=[pscustomobject]@{status='ok'}; "
        "$version=[pscustomobject]@{version='0.3.3'}; "
        "Assert-SmartCrmReleaseReadiness -Health $health -Version $version "
        "-ExpectedVersion '0.3.4'"
    )
    missing_version = run_policy(
        "$health=[pscustomobject]@{status='ok'}; $version=[pscustomobject]@{}; "
        "Assert-SmartCrmReleaseReadiness -Health $health -Version $version "
        "-ExpectedVersion '0.3.4'"
    )

    assert valid.returncode == 0, valid.stdout + valid.stderr
    assert bad_health.returncode != 0
    assert wrong_version.returncode != 0
    assert missing_version.returncode != 0


def test_release_readiness_wait_covers_success_and_timeout():
    success = run_policy(
        "$script:calls=0; $request={ param($uri) $script:calls += 1; "
        "if ($uri -like '*/health') { return [pscustomobject]@{status='ok'} }; "
        "return [pscustomobject]@{version='0.3.4'} }; "
        "Wait-SmartCrmReleaseReady -ExpectedVersion '0.3.4' "
        "-TimeoutSeconds 1 -PollMilliseconds 1 -Request $request"
    )
    wrong_version = run_policy(
        "$request={ param($uri) if ($uri -like '*/health') { "
        "return [pscustomobject]@{status='ok'} }; "
        "return [pscustomobject]@{version='0.3.3'} }; "
        "Wait-SmartCrmReleaseReady -ExpectedVersion '0.3.4' "
        "-TimeoutSeconds 0.02 -PollMilliseconds 1 -Request $request"
    )

    assert success.returncode == 0, success.stdout + success.stderr
    assert wrong_version.returncode != 0
    assert "0.3.4" in wrong_version.stdout + wrong_version.stderr


def test_port_release_helper_covers_release_and_timeout():
    released = run_policy(
        "$script:attempts=0; $probe={ param($port) $script:attempts += 1; "
        "return $script:attempts -lt 3 }; "
        "Wait-SmartCrmPortReleased -Port 8080 -TimeoutSeconds 1 "
        "-PollMilliseconds 1 -Probe $probe"
    )
    timeout = run_policy(
        "$probe={ param($port) return $true }; "
        "Wait-SmartCrmPortReleased -Port 8080 -TimeoutSeconds 0.02 "
        "-PollMilliseconds 1 -Probe $probe"
    )

    assert released.returncode == 0, released.stdout + released.stderr
    assert timeout.returncode != 0
    assert "8080" in timeout.stdout + timeout.stderr


def test_scheduled_task_target_requires_service_user_and_immutable_release_action():
    valid_task = (
        "$task=[pscustomobject]@{"
        "Principal=[pscustomobject]@{UserId='HOST\\SmartCRMService'};"
        "Actions=@([pscustomobject]@{Execute='PowerShell.exe';"
        "Arguments='-NoProfile -File \"C:\\brbots\\apps\\smart-crm-v0.3.4\\deploy\\manual-windows-pg11\\start-smart-crm.ps1\" "
        "-AppRoot \"C:\\brbots\\apps\\smart-crm-v0.3.4\"';"
        "WorkingDirectory='C:\\brbots\\apps\\smart-crm-v0.3.4'})};"
    )
    valid = run_policy(
        valid_task
        + "Assert-SmartCrmScheduledTaskTarget -Task $task "
        "-ExpectedUser 'HOST\\SmartCRMService' "
        "-ExpectedAppRoot 'C:\\brbots\\apps\\smart-crm-v0.3.4'"
    )
    wrong_user = run_policy(
        valid_task
        + "Assert-SmartCrmScheduledTaskTarget -Task $task "
        "-ExpectedUser 'HOST\\OtherUser' "
        "-ExpectedAppRoot 'C:\\brbots\\apps\\smart-crm-v0.3.4'"
    )
    wrong_release = run_policy(
        valid_task
        + "Assert-SmartCrmScheduledTaskTarget -Task $task "
        "-ExpectedUser 'HOST\\SmartCRMService' "
        "-ExpectedAppRoot 'C:\\brbots\\apps\\smart-crm-v0.3.5'"
    )

    assert valid.returncode == 0, valid.stdout + valid.stderr
    assert wrong_user.returncode != 0
    assert wrong_release.returncode != 0


def test_windows_powershell_51_keeps_native_stderr_in_log_without_stopping(tmp_path):
    log_path = tmp_path / "smart-crm.log"
    expression = (
        "$ErrorActionPreference='Stop'; "
        "$arguments=@('/d','/c','echo uvicorn-info 1>&2'); "
        f"$code=Invoke-SmartCrmLoggedProcess -FilePath $env:ComSpec "
        f"-ArgumentList $arguments -LogPath {powershell_literal(str(log_path))}; "
        "if ($code -ne 0) { exit 9 }; Write-Output 'runtime-continued'"
    )

    result = run_policy(expression)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "runtime-continued" in result.stdout
    assert "uvicorn-info" in log_path.read_text(encoding="utf-16")


def test_native_process_capture_uses_exit_code_instead_of_stderr():
    success = run_policy(
        "$result=Invoke-SmartCrmNativeProcess -FilePath $env:ComSpec "
        "-ArgumentList @('/d','/c','echo informational 1>&2 & exit /b 0'); "
        "$result | ConvertTo-Json -Compress"
    )
    failure = run_policy(
        "$result=Invoke-SmartCrmNativeProcess -FilePath $env:ComSpec "
        "-ArgumentList @('/d','/c','echo failed 1>&2 & exit /b 7'); "
        "$result | ConvertTo-Json -Compress"
    )

    assert success.returncode == 0, success.stdout + success.stderr
    success_payload = json.loads(success.stdout)
    failure_payload = json.loads(failure.stdout)
    assert success_payload["ExitCode"] == 0
    assert "informational" in success_payload["StdErr"]
    assert failure_payload["ExitCode"] == 7
    assert "failed" in failure_payload["StdErr"]


def test_fleet_runner_writes_atomic_redacted_success_evidence(tmp_path: Path):
    app_root, env_file, evidence = write_fleet_runner_fixture(tmp_path)

    result = run_fleet_runner(
        app_root,
        env_file,
        evidence,
        migration_exit_code=0,
        migration_output="brbots code=migrated",
        migration_error="informational stderr",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(evidence.read_text(encoding="utf-8-sig"))
    assert payload == {
        "schemaVersion": 1,
        "releasePath": str(app_root),
        "targetRevision": "a8d4e6f2b1c9",
        "tenants": [
            {"slug": "brbots", "succeeded": True, "code": "migrated"}
        ],
        "exitCode": 0,
    }
    assert "must-not-leak" not in evidence.read_text(encoding="utf-8-sig")
    assert list(tmp_path.glob("evidence.json.*.tmp")) == []


def test_fleet_runner_failure_is_nonzero_with_valid_redacted_evidence(tmp_path: Path):
    app_root, env_file, evidence = write_fleet_runner_fixture(tmp_path)

    result = run_fleet_runner(
        app_root,
        env_file,
        evidence,
        migration_exit_code=7,
        migration_output="brbots code=migration_failed",
        migration_error="postgresql://user:plain-secret@host/database",
    )

    assert result.returncode != 0
    payload = json.loads(evidence.read_text(encoding="utf-8-sig"))
    assert payload["releasePath"] == str(app_root)
    assert payload["targetRevision"] == "a8d4e6f2b1c9"
    assert payload["tenants"] == [
        {"slug": "brbots", "succeeded": False, "code": "migration_failed"}
    ]
    assert payload["exitCode"] == 7
    combined = evidence.read_text(encoding="utf-8-sig") + result.stdout + result.stderr
    assert "plain-secret" not in combined
    assert "must-not-leak" not in combined
    assert list(tmp_path.glob("evidence.json.*.tmp")) == []


def test_fleet_runner_contract_has_no_plaintext_credential_parameter():
    runner = FLEET_RUNNER.read_text(encoding="utf-8")

    assert "[PSCredential]" not in runner
    assert "Password" not in runner
    assert "Read-SmartCrmEnvironment" in runner
    assert "SMART_CRM_CONTROL_DATABASE_URL" in runner
    assert "SMART_CRM_TENANT_SECRET_STORE" in runner
    assert "SMART_CRM_ALLOW_INSECURE_TENANT_LOOPBACK" in runner
    assert "finally" in runner
    assert "Move-Item" in runner
    assert "ConvertTo-Json" in runner


def test_fleet_task_invoker_registers_validates_and_removes_one_shot_task(
    tmp_path: Path,
):
    result = run_fleet_task_invoker(tmp_path, "success")

    assert result.returncode == 0, result.stdout + result.stderr
    evidence_files = list((tmp_path / "evidence").rglob("*.json"))
    assert len(evidence_files) == 1
    payload = json.loads(evidence_files[0].read_text(encoding="utf-8-sig"))
    assert payload["releasePath"] == str(tmp_path / "smart-crm-v0.3.4")
    assert payload["tenants"] == [
        {"slug": "brbots", "succeeded": True, "code": "migrated"}
    ]


@pytest.mark.parametrize("scenario", ["timeout", "malformed", "failure"])
def test_fleet_task_invoker_failure_paths_cleanup_and_fail(
    tmp_path: Path, scenario: str
):
    result = run_fleet_task_invoker(tmp_path, scenario)

    assert result.returncode == 9, result.stdout + result.stderr


def test_fleet_task_invoker_rejects_non_service_identity_before_registration(
    tmp_path: Path,
):
    result = run_fleet_task_invoker(tmp_path, "wrong_user")

    assert result.returncode == 9, result.stdout + result.stderr


def test_fleet_task_invoker_contract_is_unique_finite_and_secret_free():
    invoker = FLEET_TASK_INVOKER.read_text(encoding="utf-8")

    assert "[PSCredential]$ServiceCredential" in invoker
    assert '"SmartCRMService"' in invoker
    assert "[guid]::NewGuid" in invoker
    assert "run-fleet-migration.ps1" in invoker
    assert "Get-ScheduledTaskInfo" in invoker
    assert "TimeoutSeconds" in invoker
    assert "Unregister-ScheduledTask" in invoker
    assert "finally" in invoker
    assert "icacls" in invoker
    assert "SMART_CRM_DB_PASSWORD" not in invoker


def test_start_script_uses_the_powershell_51_safe_logged_process_helper():
    start = START.read_text(encoding="utf-8")

    assert "Invoke-SmartCrmLoggedProcess" in start
    assert "& $python @uvicornArguments *>> $logPath" not in start


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


# --- T14: SMTP configuration and DPAPI secret ------------------------------

SMTP_SECRET_KEY = "SMART_CRM_SMTP_PASSWORD_SECRET_FILE"


def smtp_values(**changes: str) -> dict[str, str]:
    values = valid_server_environment()
    values.update(changes)
    return values


def test_environment_example_declares_smtp_keys_without_password():
    example = ENV_EXAMPLE.read_text(encoding="utf-8")
    keys = {line.split("=", 1)[0] for line in example.splitlines() if line and not line.startswith("#")}

    assert {
        "SMART_CRM_SMTP_HOST",
        "SMART_CRM_SMTP_PORT",
        "SMART_CRM_SMTP_USERNAME",
        "SMART_CRM_SMTP_FROM_ADDRESS",
        "SMART_CRM_SMTP_TLS_MODE",
        "SMART_CRM_SMTP_TIMEOUT_SECONDS",
        SMTP_SECRET_KEY,
    } <= keys
    assert "SMART_CRM_SMTP_PASSWORD" not in keys
    assert (
        r"SMART_CRM_SMTP_PASSWORD_SECRET_FILE=C:\ProgramData\SmartCRM\service-secrets\smtp-password.bin"
        in example
    )


def test_windows_startup_exports_smtp_settings_and_reads_the_dpapi_secret(tmp_path: Path):
    result = run_start_validation(tmp_path, smtp_values())

    assert result.returncode == 0, result.stdout + result.stderr
    assert "smart crm environment: VALID" in result.stdout
    assert TEST_SMTP_PASSWORD not in result.stdout + result.stderr
    start = START.read_text(encoding="utf-8")
    assert "Get-SmartCrmSmtpEnvironmentKeys" in start


@pytest.mark.parametrize(
    ("changes", "fragment"),
    [
        ({"SMART_CRM_SMTP_HOST": "REPLACE_WITH_SMTP_HOST"}, "SMART_CRM_SMTP_HOST"),
        ({"SMART_CRM_SMTP_HOST": "smtp exemplo"}, "SMART_CRM_SMTP_HOST"),
        ({"SMART_CRM_SMTP_PORT": "0"}, "SMART_CRM_SMTP_PORT"),
        ({"SMART_CRM_SMTP_PORT": "porta"}, "SMART_CRM_SMTP_PORT"),
        ({"SMART_CRM_SMTP_USERNAME": ""}, "SMART_CRM_SMTP_USERNAME"),
        ({"SMART_CRM_SMTP_USERNAME": "REPLACE_WITH_SMTP_USERNAME"}, "placeholder"),
        ({"SMART_CRM_SMTP_FROM_ADDRESS": "sem-arroba"}, "SMART_CRM_SMTP_FROM_ADDRESS"),
        ({"SMART_CRM_SMTP_TLS_MODE": "none"}, "SMART_CRM_SMTP_TLS_MODE"),
        ({"SMART_CRM_SMTP_TLS_MODE": "STARTTLS"}, "SMART_CRM_SMTP_TLS_MODE"),
        ({"SMART_CRM_SMTP_TIMEOUT_SECONDS": "0"}, "SMART_CRM_SMTP_TIMEOUT_SECONDS"),
        ({"SMART_CRM_SMTP_TIMEOUT_SECONDS": "120"}, "SMART_CRM_SMTP_TIMEOUT_SECONDS"),
        ({SMTP_SECRET_KEY: r"C:\Temp\smtp-password.bin"}, SMTP_SECRET_KEY),
    ],
)
def test_windows_startup_rejects_invalid_or_insecure_smtp_before_uvicorn(
    tmp_path: Path, changes: dict[str, str], fragment: str
):
    result = run_start_validation(tmp_path, smtp_values(**changes))
    output = result.stdout + result.stderr

    assert result.returncode != 0
    assert fragment in output
    assert "smart crm environment: VALID" not in output
    assert TEST_SMTP_PASSWORD not in output


def test_windows_startup_rejects_missing_smtp_key(tmp_path: Path):
    values = smtp_values()
    values.pop("SMART_CRM_SMTP_FROM_ADDRESS")

    result = run_start_validation(tmp_path, values)

    assert result.returncode != 0
    assert "SMART_CRM_SMTP_FROM_ADDRESS" in result.stdout + result.stderr


def test_windows_startup_rejects_plaintext_smtp_password_without_echoing_it(tmp_path: Path):
    values = smtp_values(SMART_CRM_SMTP_PASSWORD="senha-em-texto-puro-123")

    result = run_start_validation(tmp_path, values)
    output = result.stdout + result.stderr

    assert result.returncode != 0
    assert "set-smtp-password.ps1" in output
    assert "senha-em-texto-puro-123" not in output


@pytest.mark.parametrize("secret", [None, b"not-a-dpapi-blob"])
def test_windows_startup_rejects_missing_or_undecryptable_smtp_secret(
    tmp_path: Path, secret
):  # noqa: ANN001
    result = run_start_validation(tmp_path, smtp_values(), secret=secret, protect=False)
    output = result.stdout + result.stderr

    assert result.returncode != 0
    assert "DPAPI" in output
    assert "smart crm environment: VALID" not in output


def test_skip_secret_decryption_still_requires_the_restricted_file(tmp_path: Path):
    skipped = run_start_validation(
        tmp_path, smtp_values(), secret=b"not-a-dpapi-blob", protect=False,
        extra_args=("-SkipSecretDecryption",),
    )
    missing = run_start_validation(
        tmp_path / "missing", smtp_values(), secret=None, extra_args=("-SkipSecretDecryption",)
    )

    assert skipped.returncode == 0, skipped.stdout + skipped.stderr
    assert missing.returncode != 0


def test_windows_startup_rejects_a_secret_readable_by_all_users(tmp_path: Path):
    result = run_start_validation(tmp_path, smtp_values(), broad_acl=True)

    assert result.returncode != 0
    assert "ACL" in result.stdout + result.stderr


def test_smoke_option_cannot_be_combined_with_validate_only(tmp_path: Path):
    result = run_start_validation(
        tmp_path, smtp_values(), extra_args=("-SmtpSmokeTo", "responsavel@example.test")
    )

    assert result.returncode != 0
    assert "-SmtpSmokeTo" in result.stdout + result.stderr


def test_smtp_upgrade_preserves_existing_lines_byte_for_byte(tmp_path: Path):
    legacy = tmp_path / "server.env"
    original_lines = [
        "# comentario original",
        "SMART_CRM_DB_PASSWORD=" + "a" * 64,
        r"SMART_CRM_TENANT_SECRET_STORE=C:\ProgramData\SmartCRM\tenant-secrets",
        "SMART_CRM_CONTROL_DATABASE_URL=postgresql+psycopg://c:%5Cx%3Dy@127.0.0.1:5432/smartcrm_control?connect_timeout=5",
    ]
    legacy.write_text("\n".join(original_lines) + "\n", encoding="utf-8")

    result = run_policy(
        f"@(Add-SmartCrmSmtpEnvironmentLines -Path {powershell_literal(str(legacy))} "
        "-SmtpHost 'smtp.example.test' -Username 'crm@example.test' "
        "-FromAddress 'crm@example.test' -TlsMode 'implicit_tls' -Port '465') | ConvertTo-Json -Compress"
    )

    assert result.returncode == 0, result.stdout + result.stderr
    lines = json.loads(result.stdout)
    assert lines[: len(original_lines)] == original_lines
    added = dict(line.split("=", 1) for line in lines[len(original_lines):] if line and not line.startswith("#"))
    assert added == {
        "SMART_CRM_SMTP_HOST": "smtp.example.test",
        "SMART_CRM_SMTP_PORT": "465",
        "SMART_CRM_SMTP_USERNAME": "crm@example.test",
        "SMART_CRM_SMTP_FROM_ADDRESS": "crm@example.test",
        "SMART_CRM_SMTP_TLS_MODE": "implicit_tls",
        "SMART_CRM_SMTP_TIMEOUT_SECONDS": "10",
        SMTP_SECRET_KEY: r"C:\ProgramData\SmartCRM\service-secrets\smtp-password.bin",
    }


def test_smtp_upgrade_refuses_a_file_that_already_has_smtp(tmp_path: Path):
    configured = tmp_path / "server.env"
    configured.write_text("SMART_CRM_SMTP_HOST=smtp.example.test\n", encoding="utf-8")

    result = run_policy(
        f"Add-SmartCrmSmtpEnvironmentLines -Path {powershell_literal(str(configured))} "
        "-SmtpHost 'smtp.example.test' -Username 'crm' -FromAddress 'crm@example.test' | Out-Null"
    )

    assert result.returncode != 0
    assert "SMTP" in result.stdout + result.stderr


def test_policy_secret_helpers_round_trip_with_python_dpapi(tmp_path: Path):
    from app.security.secrets import read_dpapi_secret_file

    secret_file = tmp_path / "smtp-password.bin"
    result = run_policy(
        "$bytes=[Text.Encoding]::UTF8.GetBytes('senha-ficticia-ç-2026'); "
        f"[IO.File]::WriteAllBytes({powershell_literal(str(secret_file))}, "
        "(Protect-SmartCrmServiceSecret -Plaintext $bytes))"
    )

    assert result.returncode == 0, result.stderr
    assert read_dpapi_secret_file(str(secret_file)) == "senha-ficticia-ç-2026"


def test_runbook_documents_smtp_staging_smoke_cutover_rollback_and_rotation():
    readme = (PROJECT_ROOT / "deploy/manual-windows-pg11/LEIA-ME.md").read_text(encoding="utf-8")
    section = readme.split("## 5.1. Configurar o SMTP", 1)[1].split("\n## ", 1)[0]

    for required in (
        "### Staging",
        "### Smoke test SMTP",
        "### Corte",
        "### Rollback",
        "### Rotacao da senha SMTP",
        "set-smtp-password.ps1",
        "Add-SmartCrmSmtpEnvironmentLines",
        "-SmtpSmokeTo",
        "smtp smoke: PASS",
        "runas /user:NOME-DO-SERVIDOR\\SmartCRMService",
        "server.env.pre-smtp",
    ):
        assert required in section, required
    assert "ConvertFrom-StringData" not in readme
    assert "SMART_CRM_SMTP_PASSWORD=" not in readme


def test_initializer_validates_without_decrypting_as_administrator():
    initializer = (PROJECT_ROOT / "deploy/manual-windows-pg11/initialize-and-test.ps1").read_text(encoding="utf-8")
    install = (PROJECT_ROOT / "deploy/manual-windows-pg11/install-offline.ps1").read_text(encoding="utf-8")

    assert "-SkipSecretDecryption" in initializer
    assert "-SkipSecretDecryption" in install
    assert '$serviceSecretDirectory = Join-Path $programData "service-secrets"' in install
    assert 'icacls $serviceSecretDirectory /inheritance:r' in install
