from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import zipfile

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = PROJECT_ROOT / ".github/workflows/release-windows-pg11.yml"
STAGER = PROJECT_ROOT / "deploy/manual-windows-pg11/stage-github-release.ps1"
POWERSHELL = (
    Path(os.environ.get("WINDIR", r"C:\Windows"))
    / "System32/WindowsPowerShell/v1.0/powershell.exe"
)


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


def powershell_literal(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def run_stager(expression: str) -> subprocess.CompletedProcess[str]:
    command = f". {powershell_literal(STAGER)}; {expression}"
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


def release_metadata(**overrides) -> dict:
    tag = overrides.pop("tag_name", "v0.3.0")
    zip_name = f"smart-crm-manual-pg11-{tag}.zip"
    value = {
        "tag_name": tag,
        "draft": False,
        "prerelease": False,
        "assets": [
            {
                "name": zip_name,
                "browser_download_url": f"https://github.com/lamarcon/smart_crm/releases/download/{tag}/{zip_name}",
            },
            {
                "name": f"{zip_name}.sha256",
                "browser_download_url": f"https://github.com/lamarcon/smart_crm/releases/download/{tag}/{zip_name}.sha256",
            },
        ],
    }
    value.update(overrides)
    return value


def metadata_expression(tmp_path: Path, metadata: dict, expected_tag: str = "v0.3.0") -> str:
    path = tmp_path / "release.json"
    path.write_text(json.dumps(metadata), encoding="utf-8")
    return (
        f"$m = Get-Content -LiteralPath {powershell_literal(path)} -Raw | ConvertFrom-Json; "
        f"Assert-SmartCrmReleaseMetadata -Metadata $m -ExpectedTag {powershell_literal(expected_tag)} "
        "| ConvertTo-Json -Compress"
    )


def create_minimal_release_archive(tmp_path: Path, *, tamper: bool = False) -> Path:
    staging = tmp_path / "package"
    deploy = staging / "deploy/manual-windows-pg11"
    deploy.mkdir(parents=True)
    shutil.copy2(
        PROJECT_ROOT / "deploy/manual-windows-pg11/test-package-integrity.ps1",
        deploy,
    )
    (staging / "payload.txt").write_text("expected", encoding="utf-8")
    builder.write_manifest(staging)
    if tamper:
        (staging / "payload.txt").write_text("tampered", encoding="utf-8")
    archive = tmp_path / "smart-crm-manual-pg11-v0.3.0.zip"
    builder.create_deterministic_zip(staging, archive)
    return archive


def write_archive_digest(archive: Path, digest_path: Path | None = None) -> Path:
    path = digest_path or archive.with_name(f"{archive.name}.sha256")
    path.write_text(f"{builder.sha256(archive)}  {archive.name}\n", encoding="ascii")
    return path


def local_release_overrides(
    tmp_path: Path,
    archive: Path,
    digest: Path,
    metadata: dict | None = None,
) -> str:
    release = metadata or release_metadata()
    metadata_path = tmp_path / "release.json"
    metadata_path.write_text(json.dumps(release), encoding="utf-8")
    zip_url = release["assets"][0]["browser_download_url"]
    digest_url = release["assets"][1]["browser_download_url"]
    return (
        "function Get-SmartCrmPublicRelease { param([string]$ReleaseTag) "
        f"Get-Content -LiteralPath {powershell_literal(metadata_path)} -Raw | ConvertFrom-Json "
        "}; "
        "function Invoke-WebRequest { param([string]$Uri, [string]$OutFile, "
        "[switch]$UseBasicParsing) "
        f"if ($Uri -eq {powershell_literal(zip_url)}) {{ "
        f"Copy-Item -LiteralPath {powershell_literal(archive)} -Destination $OutFile "
        f"}} elseif ($Uri -eq {powershell_literal(digest_url)}) {{ "
        f"Copy-Item -LiteralPath {powershell_literal(digest)} -Destination $OutFile "
        "} else { throw 'URL inesperada no teste' } }; "
    )


def assert_preserved_failure_state(
    apps_root: Path,
    download_root: Path,
    release_marker: Path,
    env_marker: Path,
) -> None:
    assert not (apps_root / "smart-crm-v0.3.0").exists()
    assert release_marker.read_text(encoding="utf-8") == "release anterior"
    assert env_marker.read_text(encoding="utf-8") == "configuracao preservada"
    assert not list(apps_root.glob("*.staging-*"))
    assert not list(download_root.glob("release-*"))


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


def test_release_workflow_provisions_postgresql_for_the_full_cross_platform_gate() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "quality:\n    runs-on: ubuntu-latest" in workflow
    assert "image: postgres:17-alpine" in workflow
    assert "POSTGRES_USER: smartcrm" in workflow
    assert "POSTGRES_PASSWORD: smartcrm_local_dev" in workflow
    assert "POSTGRES_DB: smartcrm_test" in workflow
    assert 'pg_isready -U smartcrm -d smartcrm_test' in workflow
    assert "--ignore=tests/backend/test_github_release_delivery.py" in workflow
    assert "--ignore=tests/backend/test_manual_windows_pg11_outcomes.py" in workflow


def test_release_job_waits_for_quality_and_runs_windows_only_contracts() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "release:\n    needs: quality\n    runs-on: windows-2022" in workflow
    assert "Run Windows deployment tests" in workflow
    assert "tests/backend/test_github_release_delivery.py" in workflow
    assert "tests/backend/test_manual_windows_pg11_deployment.py" in workflow
    assert "tests/backend/test_manual_windows_pg11_outcomes.py" in workflow
    assert workflow.index("Run Windows deployment tests") < workflow.index(
        "Build and verify the offline bundle"
    )


def test_release_workflow_matches_tag_to_canonical_application_version() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "from app.version import APP_VERSION" in workflow
    assert '$expectedTag = "v$appVersion"' in workflow
    assert "$env:GITHUB_REF_NAME -ne $expectedTag" in workflow
    assert workflow.index("Verify tag matches the application version") < workflow.index(
        "Run backend tests with PostgreSQL"
    )


def test_release_workflow_starts_the_ui_server_before_browser_tests() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "SMART_CRM_TEST_URL: http://localhost:8080/" in workflow
    assert (
        "python -m uvicorn app.main:create_app --factory "
        "--host 127.0.0.1 --port 8080"
    ) in workflow
    assert "curl --fail --silent --show-error http://localhost:8080/" in workflow
    assert "trap 'kill \"$server_pid\" 2>/dev/null || true' EXIT" in workflow
    assert workflow.index("python -m uvicorn") < workflow.index("pnpm test")


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


@pytest.mark.parametrize("tag", ["", "0.3.0", "v01.2.3", "v1.2", "v1.2.3/other"])
def test_stager_rejects_non_semantic_or_path_like_tags(tag: str) -> None:
    result = run_stager(f"Assert-SmartCrmReleaseTag -Value {powershell_literal(tag)}")

    assert result.returncode != 0
    assert "formato vX.Y.Z" in (result.stdout + result.stderr)


def test_stager_accepts_exact_public_release_metadata(tmp_path: Path) -> None:
    result = run_stager(metadata_expression(tmp_path, release_metadata()))

    assert result.returncode == 0, result.stderr
    parsed = json.loads(result.stdout)
    assert parsed["Tag"] == "v0.3.0"
    assert parsed["ZipAsset"]["name"] == "smart-crm-manual-pg11-v0.3.0.zip"
    assert parsed["DigestAsset"]["name"] == "smart-crm-manual-pg11-v0.3.0.zip.sha256"


@pytest.mark.parametrize(
    "metadata, expected_tag",
    [
        (release_metadata(draft=True), "v0.3.0"),
        (release_metadata(prerelease=True), "v0.3.0"),
        (release_metadata(tag_name="v0.3.1"), "v0.3.0"),
        (release_metadata(assets=[]), "v0.3.0"),
        (
            release_metadata(
                assets=release_metadata()["assets"]
                + [
                    {
                        "name": "unexpected.txt",
                        "browser_download_url": "https://github.com/lamarcon/smart_crm/releases/download/v0.3.0/unexpected.txt",
                    }
                ]
            ),
            "v0.3.0",
        ),
    ],
)
def test_stager_rejects_unpublished_mismatched_or_ambiguous_metadata(
    tmp_path: Path, metadata: dict, expected_tag: str
) -> None:
    result = run_stager(metadata_expression(tmp_path, metadata, expected_tag))

    assert result.returncode != 0


def test_stager_requires_digest_for_exact_archive_name_and_bytes(tmp_path: Path) -> None:
    archive = tmp_path / "smart-crm-manual-pg11-v0.3.0.zip"
    archive.write_bytes(b"release")
    digest = tmp_path / f"{archive.name}.sha256"
    digest.write_text(f"{builder.sha256(archive)}  {archive.name}\n", encoding="ascii")
    expression = (
        f"Assert-SmartCrmArchiveDigest -ArchivePath {powershell_literal(archive)} "
        f"-DigestPath {powershell_literal(digest)}"
    )

    result = run_stager(expression)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == builder.sha256(archive)


@pytest.mark.parametrize(
    "digest_text",
    [
        "not-a-digest\n",
        f"{'0' * 64}  other.zip\n",
        f"{'0' * 64} smart-crm-manual-pg11-v0.3.0.zip\n",
    ],
)
def test_stager_rejects_malformed_mismatched_or_wrong_digest(
    tmp_path: Path, digest_text: str
) -> None:
    archive = tmp_path / "smart-crm-manual-pg11-v0.3.0.zip"
    archive.write_bytes(b"release")
    digest = tmp_path / f"{archive.name}.sha256"
    digest.write_text(digest_text, encoding="ascii")

    result = run_stager(
        f"Assert-SmartCrmArchiveDigest -ArchivePath {powershell_literal(archive)} "
        f"-DigestPath {powershell_literal(digest)}"
    )

    assert result.returncode != 0


def test_stager_promotes_valid_archive_only_after_internal_manifest_passes(
    tmp_path: Path,
) -> None:
    archive = create_minimal_release_archive(tmp_path)
    apps_root = tmp_path / "apps"

    result = run_stager(
        f"Install-SmartCrmReleaseArchive -ArchivePath {powershell_literal(archive)} "
        f"-ReleaseTag 'v0.3.0' -DestinationRoot {powershell_literal(apps_root)} "
        "| Select-Object -ExpandProperty FullName"
    )

    final_root = apps_root / "smart-crm-v0.3.0"
    assert result.returncode == 0, result.stderr
    assert Path(result.stdout.strip()) == final_root
    assert (final_root / "payload.txt").read_text(encoding="utf-8") == "expected"
    assert not list(apps_root.glob("*.staging-*"))


def test_stager_never_overwrites_existing_release_directory(tmp_path: Path) -> None:
    archive = create_minimal_release_archive(tmp_path)
    apps_root = tmp_path / "apps"
    final_root = apps_root / "smart-crm-v0.3.0"
    final_root.mkdir(parents=True)
    marker = final_root / "keep.txt"
    marker.write_text("untouched", encoding="utf-8")

    result = run_stager(
        f"Install-SmartCrmReleaseArchive -ArchivePath {powershell_literal(archive)} "
        f"-ReleaseTag 'v0.3.0' -DestinationRoot {powershell_literal(apps_root)}"
    )

    assert result.returncode != 0
    assert marker.read_text(encoding="utf-8") == "untouched"
    assert not list(apps_root.glob("*.staging-*"))


def test_stager_removes_only_temporary_directory_after_manifest_failure(
    tmp_path: Path,
) -> None:
    archive = create_minimal_release_archive(tmp_path, tamper=True)
    apps_root = tmp_path / "apps"
    existing = apps_root / "smart-crm-v0.2.0"
    existing.mkdir(parents=True)
    marker = existing / "keep.txt"
    marker.write_text("untouched", encoding="utf-8")
    env_marker = tmp_path / "server.env"
    env_marker.write_text("configuracao preservada", encoding="utf-8")

    result = run_stager(
        f"Install-SmartCrmReleaseArchive -ArchivePath {powershell_literal(archive)} "
        f"-ReleaseTag 'v0.3.0' -DestinationRoot {powershell_literal(apps_root)}"
    )

    assert result.returncode != 0
    assert not (apps_root / "smart-crm-v0.3.0").exists()
    assert marker.read_text(encoding="utf-8") == "untouched"
    assert env_marker.read_text(encoding="utf-8") == "configuracao preservada"
    assert not list(apps_root.glob("*.staging-*"))


def test_stager_api_failure_happens_before_final_or_temporary_directory(
    tmp_path: Path,
) -> None:
    apps_root = tmp_path / "apps"
    download_root = tmp_path / "downloads"
    expression = (
        "function Get-SmartCrmPublicRelease { param([string]$ReleaseTag) "
        "throw 'GitHub indisponivel no teste' }; "
        f"Invoke-SmartCrmReleaseStaging -ReleaseTag 'v0.3.0' "
        f"-DestinationRoot {powershell_literal(apps_root)} "
        f"-TemporaryRoot {powershell_literal(download_root)}"
    )

    result = run_stager(expression)

    assert result.returncode != 0
    assert "GitHub indisponivel no teste" in (result.stdout + result.stderr)
    assert not (apps_root / "smart-crm-v0.3.0").exists()
    assert not download_root.exists()


def test_stager_download_failure_preserves_release_and_configuration(
    tmp_path: Path,
) -> None:
    apps_root = tmp_path / "apps"
    previous = apps_root / "smart-crm-v0.2.0"
    previous.mkdir(parents=True)
    release_marker = previous / "keep.txt"
    release_marker.write_text("release anterior", encoding="utf-8")
    env_marker = tmp_path / "server.env"
    env_marker.write_text("configuracao preservada", encoding="utf-8")
    download_root = tmp_path / "downloads"
    metadata_path = tmp_path / "release.json"
    metadata_path.write_text(json.dumps(release_metadata()), encoding="utf-8")
    expression = (
        "function Get-SmartCrmPublicRelease { param([string]$ReleaseTag) "
        f"Get-Content -LiteralPath {powershell_literal(metadata_path)} -Raw | ConvertFrom-Json "
        "}; function Invoke-WebRequest { throw 'download interrompido no teste' }; "
        f"Invoke-SmartCrmReleaseStaging -ReleaseTag 'v0.3.0' "
        f"-DestinationRoot {powershell_literal(apps_root)} "
        f"-TemporaryRoot {powershell_literal(download_root)}"
    )

    result = run_stager(expression)

    assert result.returncode != 0
    assert "download interrompido no teste" in (result.stdout + result.stderr)
    assert_preserved_failure_state(
        apps_root, download_root, release_marker, env_marker
    )


def test_stager_hash_failure_preserves_release_and_configuration(tmp_path: Path) -> None:
    archive = create_minimal_release_archive(tmp_path)
    digest = tmp_path / f"{archive.name}.sha256"
    digest.write_text(f"{'0' * 64}  {archive.name}\n", encoding="ascii")
    apps_root = tmp_path / "apps"
    previous = apps_root / "smart-crm-v0.2.0"
    previous.mkdir(parents=True)
    release_marker = previous / "keep.txt"
    release_marker.write_text("release anterior", encoding="utf-8")
    env_marker = tmp_path / "server.env"
    env_marker.write_text("configuracao preservada", encoding="utf-8")
    download_root = tmp_path / "downloads"
    expression = local_release_overrides(tmp_path, archive, digest) + (
        f"Invoke-SmartCrmReleaseStaging -ReleaseTag 'v0.3.0' "
        f"-DestinationRoot {powershell_literal(apps_root)} "
        f"-TemporaryRoot {powershell_literal(download_root)}"
    )

    result = run_stager(expression)

    assert result.returncode != 0
    assert_preserved_failure_state(
        apps_root, download_root, release_marker, env_marker
    )


def test_stager_extraction_failure_preserves_release_and_configuration(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "smart-crm-manual-pg11-v0.3.0.zip"
    archive.write_bytes(b"arquivo que nao e zip")
    digest = write_archive_digest(archive)
    apps_root = tmp_path / "apps"
    previous = apps_root / "smart-crm-v0.2.0"
    previous.mkdir(parents=True)
    release_marker = previous / "keep.txt"
    release_marker.write_text("release anterior", encoding="utf-8")
    env_marker = tmp_path / "server.env"
    env_marker.write_text("configuracao preservada", encoding="utf-8")
    download_root = tmp_path / "downloads"
    expression = local_release_overrides(tmp_path, archive, digest) + (
        f"Invoke-SmartCrmReleaseStaging -ReleaseTag 'v0.3.0' "
        f"-DestinationRoot {powershell_literal(apps_root)} "
        f"-TemporaryRoot {powershell_literal(download_root)}"
    )

    result = run_stager(expression)

    assert result.returncode != 0
    assert_preserved_failure_state(
        apps_root, download_root, release_marker, env_marker
    )


def test_stager_reports_exact_final_identity_without_secret_values(tmp_path: Path) -> None:
    archive = create_minimal_release_archive(tmp_path)
    digest = write_archive_digest(archive)
    apps_root = tmp_path / "apps"
    download_root = tmp_path / "downloads"
    secret_sentinel = "nao-pode-aparecer-no-log"
    metadata = release_metadata()
    for asset in metadata["assets"]:
        asset["browser_download_url"] += f"?token={secret_sentinel}"
    expression = local_release_overrides(tmp_path, archive, digest, metadata) + (
        f"$result = Invoke-SmartCrmReleaseStaging -ReleaseTag 'v0.3.0' "
        f"-DestinationRoot {powershell_literal(apps_root)} "
        f"-TemporaryRoot {powershell_literal(download_root)}; "
        "$result | ConvertTo-Json -Compress"
    )

    result = run_stager(expression)

    assert result.returncode == 0, result.stderr
    parsed = json.loads(result.stdout)
    assert parsed == {
        "Tag": "v0.3.0",
        "Sha256": builder.sha256(archive),
        "ReleaseRoot": str(apps_root / "smart-crm-v0.3.0"),
    }
    assert secret_sentinel not in (result.stdout + result.stderr)
    source = STAGER.read_text(encoding="utf-8")
    assert 'Write-Output "RELEASE_STAGED=PASS"' in source


def test_concurrent_staging_has_exactly_one_winner_and_no_residue(
    tmp_path: Path,
) -> None:
    archive = create_minimal_release_archive(tmp_path)
    apps_root = tmp_path / "apps"
    gate = tmp_path / "go.signal"
    processes: list[subprocess.Popen[str]] = []
    ready_files = [tmp_path / f"ready-{index}.signal" for index in range(2)]
    for ready in ready_files:
        expression = (
            f"[IO.File]::WriteAllText({powershell_literal(ready)}, 'ready'); "
            f"while (-not (Test-Path -LiteralPath {powershell_literal(gate)})) {{ "
            "Start-Sleep -Milliseconds 10 }; "
            f"Install-SmartCrmReleaseArchive -ArchivePath {powershell_literal(archive)} "
            f"-ReleaseTag 'v0.3.0' -DestinationRoot {powershell_literal(apps_root)} "
            "| Select-Object -ExpandProperty FullName"
        )
        command = f". {powershell_literal(STAGER)}; {expression}"
        processes.append(
            subprocess.Popen(
                [
                    str(POWERSHELL),
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    command,
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        )

    deadline = time.monotonic() + 10
    while not all(path.exists() for path in ready_files):
        if time.monotonic() >= deadline:
            for process in processes:
                process.kill()
            pytest.fail("processos concorrentes nao chegaram ao ponto de sincronizacao")
        time.sleep(0.01)
    gate.write_text("go", encoding="ascii")
    results = [process.communicate(timeout=30) for process in processes]
    returncodes = [process.returncode for process in processes]

    assert sum(code == 0 for code in returncodes) == 1, results
    assert sum(code != 0 for code in returncodes) == 1, results
    final_root = apps_root / "smart-crm-v0.3.0"
    assert (final_root / "payload.txt").read_text(encoding="utf-8") == "expected"
    assert not list(apps_root.glob("*.staging-*"))


def test_stager_source_has_no_cutover_or_secret_mutation_commands() -> None:
    source = STAGER.read_text(encoding="utf-8")

    assert "https://api.github.com/repos/$script:SmartCrmRepository/releases/tags/" in source
    assert '$script:SmartCrmRepository = "lamarcon/smart_crm"' in source
    assert "Authorization" not in source
    for forbidden in (
        "Start-ScheduledTask",
        "Register-ScheduledTask",
        "Set-ScheduledTask",
        "alembic",
        "psql",
        "PGPASSWORD",
        "Set-Content",
    ):
        assert forbidden not in source
