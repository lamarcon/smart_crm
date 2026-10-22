from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = PROJECT_ROOT / ".github/workflows/release-windows-pg11.yml"


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


def test_release_workflow_is_tag_only_and_uses_minimum_release_permission() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert 'tags:\n      - "v*"' in workflow
    assert "workflow_dispatch" not in workflow
    assert "contents: write" in workflow
    assert "GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}" in workflow
    assert "PERSONAL_ACCESS_TOKEN" not in workflow


def test_release_workflow_matches_tag_to_canonical_application_version() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "from app.version import APP_VERSION" in workflow
    assert '$expectedTag = "v$appVersion"' in workflow
    assert "$env:GITHUB_REF_NAME -ne $expectedTag" in workflow
    assert workflow.index("Verify tag matches the application version") < workflow.index(
        "Run backend tests"
    )


def test_release_workflow_tests_before_build_and_publishes_exact_assets() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    backend = workflow.index("python -m pytest -q")
    ui = workflow.index("pnpm test")
    build = workflow.index("python scripts/build_manual_windows_pg11_bundle.py")
    publish = workflow.index("gh release create")

    assert backend < build
    assert ui < build
    assert build < publish
    assert "--version $env:GITHUB_REF_NAME" in workflow
    assert 'python scripts/verify_manual_windows_pg11_deployment.py --bundle $zip' in workflow
    assert '$zip = "dist/smart-crm-manual-pg11-$env:GITHUB_REF_NAME.zip"' in workflow
    assert '$digest = "$zip.sha256"' in workflow
    assert "gh release create $env:GITHUB_REF_NAME `\n              $zip `\n              $digest `" in workflow
    assert "--verify-tag" in workflow
    assert "--clobber" not in workflow
    assert "gh release upload" not in workflow


def test_release_workflow_refuses_to_replace_an_existing_release() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "gh release view $env:GITHUB_REF_NAME" in workflow
    assert "already exists and will not be overwritten" in workflow
    assert workflow.index("gh release view") < workflow.index("gh release create")
