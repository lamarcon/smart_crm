from __future__ import annotations

from uuid import UUID

import pytest

from app.fleet import FleetMigrationResult, FleetPreflightResult
from app.fleet_cli import main


TENANT_ID = UUID("0704e2f5-38f2-440d-9ef2-1d9e91a77508")


class FakeFleetService:
    def __init__(self) -> None:
        self.preflight_calls: list[list[str]] = []
        self.migrate_calls: list[dict[str, object]] = []
        self.preflight_results = [
            FleetPreflightResult(
                TENANT_ID,
                "brbots",
                "active",
                True,
                True,
                "a8d4e6f2b1c9",
                True,
                "ready",
            )
        ]
        self.migration_results = [
            FleetMigrationResult(TENANT_ID, "brbots", True, "migrated")
        ]

    def packaged_head(self) -> str:
        return "a8d4e6f2b1c9"

    def preflight(self, selectors):  # noqa: ANN001, ANN201
        self.preflight_calls.append(list(selectors))
        return self.preflight_results

    def migrate(self, selectors, **kwargs):  # noqa: ANN001, ANN003, ANN201
        self.migrate_calls.append({"selectors": list(selectors), **kwargs})
        return self.migration_results


@pytest.mark.parametrize(
    "argv",
    [
        ["preflight"],
        ["migrate", "--backup-acknowledged", "--confirmed"],
        ["migrate", "--tenant", "brbots", "--confirmed"],
        ["migrate", "--tenant", "brbots", "--backup-acknowledged"],
    ],
)
def test_cli_rejects_incomplete_request_before_service_creation(
    argv: list[str], capsys
) -> None:  # noqa: ANN001
    factory_calls: list[bool] = []

    exit_code = main(argv, service_factory=lambda: factory_calls.append(True))

    assert exit_code == 2
    assert factory_calls == []
    output = capsys.readouterr()
    assert "tenant database url" not in (output.out + output.err).lower()


def test_preflight_uses_only_explicit_selection_and_redacted_formatter(capsys) -> None:  # noqa: ANN001
    service = FakeFleetService()

    exit_code = main(
        ["preflight", "--tenant", "brbots"],
        service_factory=lambda: service,
    )

    assert exit_code == 0
    assert service.preflight_calls == [["brbots"]]
    output = capsys.readouterr().out
    assert "brbots status=active" in output
    assert "revision=a8d4e6f2b1c9" in output
    assert "postgresql" not in output


def test_migrate_uses_packaged_head_and_accepts_only_success_codes(capsys) -> None:  # noqa: ANN001
    service = FakeFleetService()
    service.migration_results = [
        FleetMigrationResult(TENANT_ID, "brbots", True, "migrated"),
        FleetMigrationResult(TENANT_ID, "already", True, "already_current"),
    ]

    exit_code = main(
        [
            "migrate",
            "--tenant",
            "brbots",
            "--tenant",
            "already",
            "--backup-acknowledged",
            "--confirmed",
        ],
        service_factory=lambda: service,
    )

    assert exit_code == 0
    assert service.migrate_calls == [
        {
            "selectors": ["brbots", "already"],
            "target_revision": "a8d4e6f2b1c9",
            "backup_acknowledged": True,
            "confirmed": True,
        }
    ]
    output = capsys.readouterr().out
    assert output.splitlines() == [
        "brbots code=migrated",
        "already code=already_current",
    ]


def test_migrate_failure_returns_nonzero_without_leaking_exception_text(capsys) -> None:  # noqa: ANN001
    service = FakeFleetService()
    service.migration_results = [
        FleetMigrationResult(TENANT_ID, "brbots", False, "migration_failed")
    ]

    exit_code = main(
        [
            "migrate",
            "--tenant",
            "brbots",
            "--backup-acknowledged",
            "--confirmed",
        ],
        service_factory=lambda: service,
    )

    assert exit_code == 1
    output = capsys.readouterr().out
    assert output == "brbots code=migration_failed\n"
    assert "postgresql" not in output


def test_unexpected_cli_failure_is_stable_and_redacted(capsys) -> None:  # noqa: ANN001
    def broken_factory():  # noqa: ANN202
        raise RuntimeError("postgresql://user:plain-secret@host/database")

    exit_code = main(
        ["preflight", "--tenant", "brbots"],
        service_factory=broken_factory,
    )

    assert exit_code == 3
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == "fleet operation failed\n"
    assert "plain-secret" not in output.err
