from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_builder():
    path = PROJECT_ROOT / "scripts/build_manual_windows_pg11_bundle.py"
    spec = importlib.util.spec_from_file_location("github_release_bundle_builder", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


builder = load_builder()


def fake_wheel_downloader(staging: Path, _python: str) -> None:
    wheelhouse = staging / "wheelhouse"
    wheelhouse.mkdir()
    (wheelhouse / "fake_dependency-1.0.0-cp311-cp311-win_amd64.whl").write_bytes(b"wheel")
    (wheelhouse / "argon2_cffi-25.1.0-py3-none-any.whl").write_bytes(b"wheel")
    (wheelhouse / "argon2_cffi_bindings-25.1.0-cp39-abi3-win_amd64.whl").write_bytes(
        b"wheel"
    )


def test_tag_version_creates_exact_release_asset_names(tmp_path: Path) -> None:
    archive, digest = builder.build(
        PROJECT_ROOT,
        tmp_path,
        version="v0.3.0",
        wheel_downloader=fake_wheel_downloader,
    )

    assert archive.name == "smart-crm-manual-pg11-v0.3.0.zip"
    assert digest.name == "smart-crm-manual-pg11-v0.3.0.zip.sha256"
    assert digest.read_text(encoding="ascii") == f"{builder.sha256(archive)}  {archive.name}\n"


def test_missing_version_uses_git_short_sha(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(builder, "git_version", lambda _root: "cafebabe")

    archive, digest = builder.build(
        PROJECT_ROOT,
        tmp_path,
        wheel_downloader=fake_wheel_downloader,
    )

    assert archive.name == "smart-crm-manual-pg11-cafebabe.zip"
    assert digest.name == "smart-crm-manual-pg11-cafebabe.zip.sha256"


@pytest.mark.parametrize(
    "unsafe_version",
    ["", "../v0.3.0", "v0/3/0", "v0\\3\\0", " v0.3.0", "v0.3.0 ", "v0..3", "a" * 65],
)
def test_unsafe_version_is_rejected_before_output_directory_creation(
    unsafe_version: str, tmp_path: Path
) -> None:
    output_dir = tmp_path / "dist"

    with pytest.raises(ValueError, match="safe release identifier"):
        builder.build(
            PROJECT_ROOT,
            output_dir,
            version=unsafe_version,
            wheel_downloader=fake_wheel_downloader,
        )

    assert not output_dir.exists()
