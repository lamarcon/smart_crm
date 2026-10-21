"""Verify source and generated bundle contracts for the manual PG11 deployment."""

from __future__ import annotations

import argparse
import hashlib
import re
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = {
    "MPG-01", "MPG-02", "MPG-03", "MPG-04", "MPG-05", "MPG-06", "MPG-07",
    "MPG-08", "MPG-09", "MPG-10", "MPG-11", "MPG-12", "MPG-13", "MPG-14",
    "MPG-15", "MPG-16", "MPG-17", "MPG-18", "MPG-19",
}


def _require(condition: bool, requirement: str, message: str, passed: set[str]) -> None:
    if not condition:
        raise AssertionError(f"{requirement}: {message}")
    passed.add(requirement)


def verify_source(root: Path) -> set[str]:
    deploy = root / "deploy/manual-windows-pg11"
    install = (deploy / "install-offline.ps1").read_text(encoding="utf-8")
    start = (deploy / "start-smart-crm.ps1").read_text(encoding="utf-8")
    initialize = (deploy / "initialize-and-test.ps1").read_text(encoding="utf-8")
    integrity = (deploy / "test-package-integrity.ps1").read_text(encoding="utf-8")
    readme = (deploy / "LEIA-ME.md").read_text(encoding="utf-8")
    builder = (root / "scripts/build_manual_windows_pg11_bundle.py").read_text(encoding="utf-8")
    env_example = (deploy / "server.env.example").read_text(encoding="utf-8")
    requirements = (root / "requirements-runtime.txt").read_text(encoding="utf-8")
    policy = (deploy / "deployment-policy.ps1").read_text(encoding="utf-8")
    scripts = "\n".join(path.read_text(encoding="utf-8") for path in deploy.glob("*.ps1"))
    passed: set[str] = set()

    _require("smart-crm-manual-pg11-" in builder and ".sha256" in builder, "MPG-01", "versioned ZIP or digest output missing", passed)
    _require(all(token in builder for token in ("app", "migrations", "alembic.ini", "wheelhouse", "win_amd64", "cp311")), "MPG-02", "runtime allowlist or Windows wheel target missing", passed)
    allowlist = builder.partition("RUNTIME_PATHS")[2].partition(")")[0]
    _require(all(token not in allowlist for token in (".git", ".specs", ".venv", "tests")), "MPG-03", "forbidden path included in runtime allowlist", passed)
    _require("Get-FileHash" in integrity and "throw \"Hash invalido" in integrity and install.index("test-package-integrity.ps1") < install.index("-m venv"), "MPG-04", "integrity failure gate missing or runs after installation", passed)
    python_guard = install.index("platform.python_implementation()")
    venv_action = install.index("-m venv")
    _require(python_guard < venv_action and "Assert-SmartCrmRuntimeFacts" in install and '$Implementation -ne "CPython"' in policy and "$Major -ne 3" in policy and "$Minor -ne 11" in policy and "$Bits -ne 64" in policy, "MPG-05", "CPython 3.11 x64 is not gated before venv creation", passed)
    _require("--no-index" in install and "--find-links" in install, "MPG-06", "offline-only pip flags missing", passed)
    _require(all(token in env_example for token in ("SMART_CRM_DB_NAME=smartcrm", "SMART_CRM_DB_USER=smartcrm", "SMART_CRM_DB_HOST=127.0.0.1", "SMART_CRM_DB_PORT=5432", "REPLACE_WITH_64_HEX_CHARACTERS")) and '"C:\\ProgramData\\SmartCRM"' in install and "New-SmartCrmEnvironmentLines" in install, "MPG-07", "database environment or external-secret contract mismatch", passed)
    _require(not re.search(r"(?i)\b(?:Stop|Restart|Set|Remove)-Service\b|ALTER\s+SYSTEM|pg_ctl", scripts), "MPG-08", "PG11 service mutation command found", passed)
    _require(all(token in policy for token in (
        '"alembic-control.ini", "upgrade", "c01a5d8e4f20"',
        '"alembic.ini", "upgrade", "e1c4a7b9d2f6"',
    )) and all(token in initialize for token in (
        "Get-SmartCrmControlAlembicUpgradeArguments",
        "Get-SmartCrmTenantAlembicUpgradeArguments",
    )) and "CREATE TABLE" not in scripts, "MPG-09", "separate Alembic-only schema migration contract missing", passed)
    _require(
        '"--host", "127.0.0.1", "--port", "8080"' in policy
        and "Get-SmartCrmUvicornArguments" in start
        and "Invoke-SmartCrmLoggedProcess" in start
        and "-ArgumentList $uvicornArguments" in start,
        "MPG-10",
        "loopback Uvicorn binding or PowerShell 5.1-safe launcher missing",
        passed,
    )
    _require('$Health.status -eq "ok" -and $Health.database -eq "ok"' in policy and "Test-SmartCrmHealth -Health $health" in initialize and "LOCAL GATE: PASS" in initialize, "MPG-11", "exact health gate before Apache missing", passed)
    _require('$_.LocalAddress -eq "127.0.0.1"' in policy and "$ipv4Loopback.Count -eq 0" in policy and "Assert-SmartCrmPostgresListeners -Listeners $listeners" in install, "MPG-12", "exact IPv4 PostgreSQL listener gate missing", passed)
    _require("\\du smartcrm" in readme and "\\l smartcrm" in readme and "nao a recrie nem apague" in readme, "MPG-13", "existing role/database validation guidance missing", passed)
    _require("Assert-SmartCrmCommandSucceeded" in initialize and initialize.index("Assert-SmartCrmCommandSucceeded") < initialize.index("install-scheduled-task.ps1") and not re.search(r"(?i)httpd\.exe|apache.*restart", initialize), "MPG-14", "migration failure does not block publication", passed)
    _require(all(token in initialize for token in (
        "Get-SmartCrmControlAlembicCurrentArguments",
        "Get-SmartCrmTenantAlembicCurrentArguments",
        "Assert-SmartCrmAlembicRevision",
        "c01a5d8e4f20",
        "e1c4a7b9d2f6",
    )) and "alembic" not in start.lower(), "MPG-15", "exact revisions are not verified separately before publication or web startup runs migrations", passed)
    _require(all(token in readme for token in (
        "smart-crm-<SHA>",
        "Nao sobrescreva a release ativa",
        "`git pull` e proibido",
        "autorizacao de producao separada",
    )), "MPG-16", "side-by-side release or separate production authorization missing", passed)
    _require(all(token in readme for token in (
        "O database `smartcrm` permanece",
        "tenant da BRBots",
        "`smartcrm_control` contem somente",
        'register-tenant brbots --display-name "brbots"',
        "activate-default brbots --admin-email lfmarcon@brbots.com",
        '--admin-name "Luiz Felipe"',
    )), "MPG-17", "BRBots data-preservation or administrative onboarding contract missing", passed)
    _require(all(token in env_example for token in (
        "SMART_CRM_CONTROL_DATABASE_URL=REPLACE_WITH_CONTROL_DATABASE_URL",
        "SMART_CRM_TENANT_SECRET_STORE=C:\\ProgramData\\SmartCRM\\tenant-secrets",
        "SMART_CRM_ALLOW_INSECURE_TENANT_LOOPBACK=1",
    )) and all(token in install for token in (
        "-ControlPassword $controlPassword",
        "serviceSid",
        "tenant-secrets",
        "SmartCRMService",
    )), "MPG-18", "complete central environment or SmartCRMService ACL contract missing", passed)
    _require(all(token in policy for token in (
        "Get-SmartCrmSharedPostgresHbaRules",
        "Assert-SmartCrmSharedPostgresHba",
        "host smartcrm,smartcrm_control all 127.0.0.1/32 md5",
        "host smartcrm,smartcrm_control all 0.0.0.0/0 reject",
    )) and all(token in install for token in (
        "-SharedPostgres:$SharedPostgres",
        "-PgHbaPath",
        "Assert-SmartCrmPostgresListeners",
    )) and install.index("Assert-SmartCrmPostgresListeners") < install.index("-m venv")
       and all(token in initialize for token in (
        "-SharedPostgres:$SharedPostgres",
        "-PgHbaPath",
        "Assert-SmartCrmPostgresListeners",
    )) and initialize.index("Assert-SmartCrmPostgresListeners") < initialize.index("Get-SmartCrmControlAlembicUpgradeArguments")
       and all(token in readme for token in (
        "`DW_CMS`",
        "`DW_PRODUTOS`",
        "nao recebem migracao",
        "pg_reload_conf",
        "-SharedPostgres",
        "-PgHbaPath",
    )) and all(database not in (policy + install + initialize) for database in ("DW_CMS", "DW_PRODUTOS")),
        "MPG-19", "shared PostgreSQL HBA boundary or out-of-scope database preservation missing", passed)
    _require(all("==" in line for line in requirements.splitlines() if line.strip()), "MPG-02", "runtime dependency is not pinned", passed)
    return passed


def verify_bundle(bundle_path: Path) -> set[str]:
    passed: set[str] = set()
    with zipfile.ZipFile(bundle_path) as bundle:
        names = set(bundle.namelist())
        _require("MANIFEST.sha256" in names and any(name.startswith("wheelhouse/") and name.endswith(".whl") for name in names), "MPG-02", "manifest or wheelhouse missing from ZIP", passed)
        forbidden = [name for name in names if name.startswith((".git/", ".specs/", ".venv/", "tests/")) or name.endswith(("server.env", ".key", "privkey.pem"))]
        _require(not forbidden, "MPG-03", f"forbidden ZIP entries: {forbidden}", passed)
        manifest_lines = bundle.read("MANIFEST.sha256").decode("utf-8").splitlines()
        expected = {}
        for line in manifest_lines:
            digest, separator, relative = line.partition("  ")
            if separator != "  ":
                raise AssertionError("MPG-04: invalid manifest line")
            expected[relative] = digest
        actual = {
            name: hashlib.sha256(bundle.read(name)).hexdigest()
            for name in names
            if name != "MANIFEST.sha256" and not name.endswith("/")
        }
        _require(actual == expected, "MPG-04", "ZIP contents do not match internal manifest", passed)
    return passed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--bundle", type=Path)
    args = parser.parse_args()
    passed = verify_source(args.root.resolve())
    if args.bundle:
        passed.update(verify_bundle(args.bundle.resolve()))
    missing = REQUIREMENTS - passed
    if missing:
        raise AssertionError(f"requirements without evidence: {sorted(missing)}")
    print("manual Windows PostgreSQL 11 deployment: PASS (19/19 requirements)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
