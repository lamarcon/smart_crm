"""Validate the Python 3.11 runtime contract without installing dependencies."""

from __future__ import annotations

import argparse
import ast
from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
RUNTIME_TREES = (ROOT / "app", ROOT / "migrations")


class ContractError(RuntimeError):
    pass


def compatibility_contract(pyproject_text: str, sources: dict[str, str]) -> int:
    metadata = tomllib.loads(pyproject_text)["project"]
    if metadata.get("requires-python") != ">=3.11,<3.13":
        raise ContractError("Projeto não declara suporte exato a Python 3.11 e 3.12.")

    dependencies = metadata.get("dependencies", [])
    if not dependencies or any("==" not in dependency for dependency in dependencies):
        raise ContractError("Dependências de runtime não estão fixadas.")

    for path, source in sources.items():
        try:
            ast.parse(source, filename=path, feature_version=(3, 11))
        except SyntaxError as error:
            raise ContractError(f"Sintaxe incompatível com Python 3.11: {path}") from error

    return 2 + len(sources)


def read_sources() -> dict[str, str]:
    sources: dict[str, str] = {}
    for tree in RUNTIME_TREES:
        for path in sorted(tree.rglob("*.py")):
            sources[path.relative_to(ROOT).as_posix()] = path.read_text(encoding="utf-8")
    return sources


def self_test(pyproject_text: str, sources: dict[str, str]) -> None:
    expected = 2 + len(sources)
    assert compatibility_contract(pyproject_text, sources) == expected
    mutations = [
        (pyproject_text.replace(">=3.11,<3.13", ">=3.12,<3.13"), sources),
        (pyproject_text.replace(">=3.11,<3.13", ">=3.11,<3.14"), sources),
        (pyproject_text, {**sources, "app/python312_only.py": "type Alias = int\n"}),
    ]
    for mutated_metadata, mutated_sources in mutations:
        try:
            compatibility_contract(mutated_metadata, mutated_sources)
        except ContractError:
            pass
        else:
            raise AssertionError("Mutação de compatibilidade não detectada.")
    print("python compatibility verifier self-test: PASS (3/3 killed)")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    pyproject_text = PYPROJECT.read_text(encoding="utf-8")
    sources = read_sources()
    if args.self_test:
        self_test(pyproject_text, sources)
        return 0
    count = compatibility_contract(pyproject_text, sources)
    print(f"python 3.11 compatibility contract: {count} passed, 0 failed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ContractError, OSError, tomllib.TOMLDecodeError) as error:
        print(f"python 3.11 compatibility contract: FAIL - {error}")
        raise SystemExit(1)
