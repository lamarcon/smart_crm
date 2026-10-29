"""Explicit, redacted command-line access to tenant fleet operations."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable, Sequence

from app.control_database import ControlDatabase
from app.fleet import FleetOperationError, FleetService, format_preflight
from app.security.secrets import DpapiFileSecretProvider


ServiceFactory = Callable[[], FleetService]
_SUCCESS_CODES = {"migrated", "already_current"}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="smartcrm-fleet")
    commands = parser.add_subparsers(dest="command", required=True)

    preflight = commands.add_parser("preflight")
    preflight.add_argument("--tenant", action="append", default=[])

    migrate = commands.add_parser("migrate")
    migrate.add_argument("--tenant", action="append", default=[])
    migrate.add_argument("--backup-acknowledged", action="store_true")
    migrate.add_argument("--confirmed", action="store_true")
    return parser


def _default_service() -> FleetService:
    secret_store = os.getenv("SMART_CRM_TENANT_SECRET_STORE")
    if not secret_store:
        raise FleetOperationError("tenant secret store is required")
    control_database = ControlDatabase()
    try:
        provider = DpapiFileSecretProvider(secret_store)
        return FleetService(control_database, provider)
    except Exception:
        control_database.dispose()
        raise


def _validate_request(args: argparse.Namespace) -> str | None:
    if not args.tenant:
        return "explicit tenant selection is required"
    if args.command == "migrate" and not args.backup_acknowledged:
        return "verified backup acknowledgement is required"
    if args.command == "migrate" and not args.confirmed:
        return "operator confirmation is required"
    return None


def main(
    argv: Sequence[str] | None = None,
    *,
    service_factory: ServiceFactory = _default_service,
) -> int:
    args = _parser().parse_args(argv)
    validation_error = _validate_request(args)
    if validation_error:
        print(validation_error, file=sys.stderr)
        return 2

    try:
        service = service_factory()
        if args.command == "preflight":
            print(format_preflight(service.preflight(args.tenant)))
            return 0

        results = service.migrate(
            args.tenant,
            target_revision=service.packaged_head(),
            backup_acknowledged=True,
            confirmed=True,
        )
        for result in results:
            print(f"{result.slug} code={result.code}")
        return 0 if all(
            result.succeeded and result.code in _SUCCESS_CODES for result in results
        ) else 1
    except FleetOperationError as error:
        print(f"fleet operation failed: {error}", file=sys.stderr)
        return 2
    except Exception:
        print("fleet operation failed", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
