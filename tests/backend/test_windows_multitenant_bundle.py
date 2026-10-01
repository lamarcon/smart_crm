from __future__ import annotations

import importlib.util
import zipfile
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_builder():
    path = PROJECT_ROOT / "scripts/build_manual_windows_pg11_bundle.py"
    spec = importlib.util.spec_from_file_location("multitenant_bundle_builder", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


builder = load_builder()


def write_valid_wheels(staging: Path, _python: str = "python") -> None:
    wheelhouse = staging / "wheelhouse"
    wheelhouse.mkdir(parents=True, exist_ok=True)
    (wheelhouse / "argon2_cffi-25.1.0-py3-none-any.whl").write_bytes(b"argon2")
    (wheelhouse / "argon2_cffi_bindings-25.1.0-cp39-abi3-win_amd64.whl").write_bytes(b"bindings")


def test_runtime_collection_contains_both_lineages_and_admin_fleet_modules() -> None:
    files = {path.as_posix() for path in builder.collect_runtime_files(PROJECT_ROOT)}

    assert "migrations/env.py" in files
    assert "migrations_control/env.py" in files
    assert "alembic.ini" in files
    assert "alembic-control.ini" in files
    assert {"app/admin_cli.py", "app/fleet.py", "app/server.py"} <= files


def test_runtime_collection_excludes_real_secrets_and_local_state() -> None:
    files = {path.as_posix() for path in builder.collect_runtime_files(PROJECT_ROOT)}

    assert not any(path.endswith(("server.env", ".bin", ".key")) for path in files)
    assert not any(path.startswith((".git/", ".specs/", ".venv/", "tests/")) for path in files)


def test_wheel_contract_accepts_argon2_cp311_windows_x64_set(tmp_path: Path) -> None:
    write_valid_wheels(tmp_path)

    builder.validate_wheelhouse(tmp_path / "wheelhouse")


def test_wheel_contract_rejects_missing_argon2_distribution(tmp_path: Path) -> None:
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    (wheelhouse / "argon2_cffi_bindings-25.1.0-cp39-abi3-win_amd64.whl").write_bytes(b"bindings")

    with pytest.raises(RuntimeError, match="argon2-cffi wheel"):
        builder.validate_wheelhouse(wheelhouse)


def test_wheel_contract_rejects_non_windows_argon2_binding(tmp_path: Path) -> None:
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    (wheelhouse / "argon2_cffi-25.1.0-py3-none-any.whl").write_bytes(b"argon2")
    (wheelhouse / "argon2_cffi_bindings-25.1.0-cp39-abi3-manylinux_x86_64.whl").write_bytes(b"wrong")

    with pytest.raises(RuntimeError, match="CPython 3.11 x64"):
        builder.validate_wheelhouse(wheelhouse)


def test_build_fails_before_archive_when_argon2_wheel_is_missing(tmp_path: Path) -> None:
    def incomplete_wheels(staging: Path, _python: str) -> None:
        wheelhouse = staging / "wheelhouse"
        wheelhouse.mkdir()
        (wheelhouse / "fastapi-0.116.1-py3-none-any.whl").write_bytes(b"fastapi")

    with pytest.raises(RuntimeError, match="argon2-cffi wheel"):
        builder.build(
            PROJECT_ROOT,
            tmp_path,
            version="missing-wheel",
            wheel_downloader=incomplete_wheels,
        )

    assert not (tmp_path / "smart-crm-manual-pg11-missing-wheel.zip").exists()
    assert not (tmp_path / "smart-crm-manual-pg11-missing-wheel.zip.sha256").exists()


def test_bundle_contains_multitenant_runtime_manifest_and_no_real_secret(tmp_path: Path) -> None:
    archive, digest_file = builder.build(
        PROJECT_ROOT,
        tmp_path,
        version="multitenant",
        wheel_downloader=write_valid_wheels,
    )

    with zipfile.ZipFile(archive) as bundle:
        names = set(bundle.namelist())
        assert {
            "MANIFEST.sha256",
            "migrations/env.py",
            "migrations_control/env.py",
            "alembic.ini",
            "alembic-control.ini",
            "app/admin_cli.py",
            "app/fleet.py",
            "app/server.py",
            "migrations/versions/c7f3a9d8e2b1_add_customizable_deal_pipeline.py",
        } <= names
        assert not any(name.endswith(("server.env", ".bin", ".key")) for name in names)
        manifest = bundle.read("MANIFEST.sha256").decode("utf-8")
        assert "migrations_control/env.py" in manifest
        assert "migrations/versions/c7f3a9d8e2b1_add_customizable_deal_pipeline.py" in manifest
        assert "app/fleet.py" in manifest
        assert "argon2_cffi_bindings-25.1.0-cp39-abi3-win_amd64.whl" in manifest
    assert digest_file.read_text(encoding="ascii") == f"{builder.sha256(archive)}  {archive.name}\n"


def test_offline_installer_uses_only_wheelhouse_and_pinned_requirements() -> None:
    installer = (PROJECT_ROOT / "deploy/manual-windows-pg11/install-offline.ps1").read_text(encoding="utf-8")

    assert "--no-index --find-links $wheelhouse -r $requirements" in installer
    assert "requirements-runtime.txt" in installer
    assert "pip install" in installer
    assert "http://" not in installer
    assert "https://" not in installer
