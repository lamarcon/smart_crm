"""Build the self-contained Windows CPython 3.11/PostgreSQL 11 bundle."""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_PATHS = (
    Path("app"),
    Path("migrations"),
    Path("deploy/manual-windows-pg11"),
    Path("alembic.ini"),
    Path("requirements-runtime.txt"),
)
IGNORED_PARTS = {"__pycache__", ".pytest_cache"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def collect_runtime_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for relative in RUNTIME_PATHS:
        source = root / relative
        if not source.exists():
            raise FileNotFoundError(f"required runtime path missing: {relative}")
        candidates = [source] if source.is_file() else source.rglob("*")
        for candidate in candidates:
            if not candidate.is_file():
                continue
            candidate_relative = candidate.relative_to(root)
            if any(part in IGNORED_PARTS for part in candidate_relative.parts):
                continue
            if candidate.suffix in {".pyc", ".pyo"}:
                continue
            files.append(candidate_relative)
    return sorted(files, key=lambda item: item.as_posix())


def copy_runtime(root: Path, staging: Path) -> None:
    for relative in collect_runtime_files(root):
        target = staging / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / relative, target)


def download_windows_wheels(staging: Path, python: str = sys.executable) -> None:
    wheelhouse = staging / "wheelhouse"
    wheelhouse.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            python,
            "-m",
            "pip",
            "download",
            "--disable-pip-version-check",
            "--only-binary=:all:",
            "--platform",
            "win_amd64",
            "--python-version",
            "311",
            "--implementation",
            "cp",
            "--abi",
            "cp311",
            "--dest",
            str(wheelhouse),
            "--requirement",
            str(staging / "requirements-runtime.txt"),
        ],
        check=True,
    )
    downloaded = sorted(wheelhouse.iterdir())
    if not downloaded or any(item.suffix != ".whl" for item in downloaded):
        raise RuntimeError("wheelhouse must contain binary wheels only")


def write_manifest(staging: Path) -> Path:
    manifest = staging / "MANIFEST.sha256"
    lines = []
    for path in sorted(staging.rglob("*")):
        if path.is_file() and path != manifest:
            relative = path.relative_to(staging).as_posix()
            lines.append(f"{sha256(path)}  {relative}\n")
    manifest.write_text("".join(lines), encoding="utf-8", newline="\n")
    return manifest


def verify_manifest(staging: Path) -> None:
    manifest = staging / "MANIFEST.sha256"
    expected: dict[str, str] = {}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        digest, separator, relative = line.partition("  ")
        if separator != "  " or len(digest) != 64 or not relative:
            raise ValueError("invalid manifest line")
        expected[relative] = digest
    actual = {
        path.relative_to(staging).as_posix(): sha256(path)
        for path in staging.rglob("*")
        if path.is_file() and path != manifest
    }
    if actual != expected:
        raise ValueError("package content does not match MANIFEST.sha256")


def create_deterministic_zip(staging: Path, archive: Path) -> None:
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(item for item in staging.rglob("*") if item.is_file()):
            relative = path.relative_to(staging).as_posix()
            info = zipfile.ZipInfo(relative, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            bundle.writestr(info, path.read_bytes())


def git_version(root: Path) -> str:
    git = shutil.which("git")
    if git is None:
        fallback = Path(r"C:\Program Files\Git\cmd\git.exe")
        if fallback.is_file():
            git = str(fallback)
    if git is None:
        raise RuntimeError("Git is required only on the build machine to label the bundle")
    return subprocess.check_output(
        [git, "-c", f"safe.directory={root.as_posix()}", "rev-parse", "--short=8", "HEAD"],
        cwd=root,
        text=True,
    ).strip()


def build(root: Path, output_dir: Path, python: str = sys.executable) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    version = git_version(root)
    archive = output_dir / f"smart-crm-manual-pg11-{version}.zip"
    digest_file = output_dir / f"{archive.name}.sha256"
    with tempfile.TemporaryDirectory(prefix="smart-crm-pg11-", dir=output_dir) as temp:
        staging = Path(temp)
        copy_runtime(root, staging)
        download_windows_wheels(staging, python)
        write_manifest(staging)
        verify_manifest(staging)
        create_deterministic_zip(staging, archive)
    digest_file.write_text(f"{sha256(archive)}  {archive.name}\n", encoding="ascii", newline="\n")
    return archive, digest_file


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "dist")
    args = parser.parse_args()
    archive, digest_file = build(args.root.resolve(), args.output_dir.resolve())
    print(archive)
    print(digest_file)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
