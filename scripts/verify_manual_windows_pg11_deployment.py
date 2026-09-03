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
    scripts = "\n".join(path.read_text(encoding="utf-8") for path in deploy.glob("*.ps1"))
    passed: set[str] = set()

    _require("smart-crm-manual-pg11-" in builder and ".sha256" in builder, "MPG-01", "versioned ZIP or digest output missing", passed)
    _require(all(token in builder for token in ("app", "migrations", "alembic.ini", "wheelhouse", "win_amd64", "cp311")), "MPG-02", "runtime allowlist or Windows wheel target missing", passed)
    allowlist = builder.partition("RUNTIME_PATHS")[2].partition(")")[0]
    _require(all(token not in allowlist for token in (".git", ".specs", ".venv", "tests")), "MPG-03", "forbidden path included in runtime allowlist", passed)
    _require("Get-FileHash" in integrity and "throw \"Hash invalido" in integrity, "MPG-04", "integrity failure gate missing", passed)
    python_guard = install.index("sys.version_info[:2] == (3,11)")
    venv_action = install.index("-m venv")
    _require(python_guard < venv_action and "struct.calcsize('P') * 8 == 64" in install, "MPG-05", "Python 3.11 x64 is not gated before venv creation", passed)
    _require("--no-index" in install and "--find-links" in install, "MPG-06", "offline-only pip flags missing", passed)
    _require(all(token in env_example for token in ("SMART_CRM_DB_NAME=smartcrm", "SMART_CRM_DB_USER=smartcrm", "SMART_CRM_DB_HOST=127.0.0.1", "SMART_CRM_DB_PORT=5432", "REPLACE_WITH_64_HEX_CHARACTERS")), "MPG-07", "database environment contract mismatch", passed)
    _require(not re.search(r"(?i)\b(?:Stop|Restart|Set|Remove)-Service\b|ALTER\s+SYSTEM|pg_ctl", scripts), "MPG-08", "PG11 service mutation command found", passed)
    _require("-m alembic upgrade head" in initialize and "CREATE TABLE" not in scripts, "MPG-09", "Alembic-only schema creation contract missing", passed)
    _require('--host "127.0.0.1"' in start and '--port "8080"' in start, "MPG-10", "loopback Uvicorn binding missing", passed)
    _require("LOCAL GATE: PASS" in initialize and "http://127.0.0.1:8080/health" in initialize and "Apache permanece inalterado" in initialize, "MPG-11", "health gate before Apache missing", passed)
    _require("Get-NetTCPConnection -State Listen -LocalPort 5432" in install, "MPG-12", "PostgreSQL listener is not checked before migration", passed)
    _require("\\du smartcrm" in readme and "\\l smartcrm" in readme and "não a recrie nem apague" in readme, "MPG-13", "existing role/database validation guidance missing", passed)
    _require("Migracao Alembic falhou. Apache permanece inalterado." in initialize, "MPG-14", "migration failure does not block Apache", passed)
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
    print("manual Windows PostgreSQL 11 deployment: PASS (14/14 requirements)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
