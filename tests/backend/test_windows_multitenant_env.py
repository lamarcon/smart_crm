from __future__ import annotations

from pathlib import Path, PureWindowsPath


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_EXAMPLE = PROJECT_ROOT / "deploy/manual-windows-pg11/server.env.example"


def example_values() -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        assert separator == "=", f"invalid environment line: {raw_line}"
        assert key not in values, f"duplicate environment key: {key}"
        values[key] = value
    return values


def test_multitenant_environment_declares_required_runtime_inputs() -> None:
    values = example_values()

    assert {
        "SMART_CRM_CONTROL_DATABASE_URL",
        "SMART_CRM_TENANT_SECRET_STORE",
        "SMART_CRM_EXPECTED_ORIGIN",
        "SMART_CRM_TENANT_MAX_CACHED_ENGINES",
        "SMART_CRM_TENANT_POOL_SIZE",
        "SMART_CRM_TENANT_MAX_OVERFLOW",
        "SMART_CRM_TENANT_POOL_TIMEOUT_SECONDS",
        "SMART_CRM_TENANT_CONNECT_TIMEOUT_SECONDS",
    } <= values.keys()


def test_control_database_url_is_an_explicit_placeholder_not_a_real_dsn() -> None:
    value = example_values()["SMART_CRM_CONTROL_DATABASE_URL"]

    assert value == "REPLACE_WITH_CONTROL_DATABASE_URL"
    assert "postgresql" not in value.lower()
    assert "@" not in value


def test_dpapi_secret_store_is_external_to_the_application_tree() -> None:
    value = example_values()["SMART_CRM_TENANT_SECRET_STORE"]
    path = PureWindowsPath(value)

    assert path.is_absolute()
    assert str(path).lower().startswith("c:\\programdata\\smartcrm\\")
    assert "brbots\\apps" not in str(path).lower()


def test_expected_origin_is_the_single_secure_public_origin() -> None:
    assert example_values()["SMART_CRM_EXPECTED_ORIGIN"] == "https://sc2030.brbots.com"


def test_tenant_pool_and_timeout_defaults_are_bounded_positive_numbers() -> None:
    values = example_values()

    assert int(values["SMART_CRM_TENANT_MAX_CACHED_ENGINES"]) == 16
    assert int(values["SMART_CRM_TENANT_POOL_SIZE"]) == 2
    assert int(values["SMART_CRM_TENANT_MAX_OVERFLOW"]) == 2
    assert float(values["SMART_CRM_TENANT_POOL_TIMEOUT_SECONDS"]) == 5.0
    assert int(values["SMART_CRM_TENANT_CONNECT_TIMEOUT_SECONDS"]) == 3


def test_runtime_remains_bound_to_loopback() -> None:
    values = example_values()

    assert values["SMART_CRM_BIND_IP"] == "127.0.0.1"
    assert values["SMART_CRM_PORT"] == "8080"


def test_versioned_environment_contains_no_tenant_dsn_password_or_token() -> None:
    values = example_values()
    forbidden_names = {
        "SMART_CRM_TENANT_DATABASE_URL",
        "SMART_CRM_TENANT_DB_PASSWORD",
        "SMART_CRM_SESSION_TOKEN",
    }

    assert forbidden_names.isdisjoint(values)
    assert values["SMART_CRM_DB_PASSWORD"] == "REPLACE_WITH_64_HEX_CHARACTERS"
    assert not any("postgresql://" in value.lower() for value in values.values())
    assert not any("token" in key.lower() for key in values)


def test_environment_key_allowlist_rejects_unreviewed_inputs() -> None:
    values = example_values()
    expected = {
        "SMART_CRM_DB_NAME",
        "SMART_CRM_DB_USER",
        "SMART_CRM_DB_PASSWORD",
        "SMART_CRM_DB_HOST",
        "SMART_CRM_DB_PORT",
        "SMART_CRM_BIND_IP",
        "SMART_CRM_PORT",
        "SMART_CRM_CONTROL_DATABASE_URL",
        "SMART_CRM_TENANT_SECRET_STORE",
        "SMART_CRM_EXPECTED_ORIGIN",
        "SMART_CRM_TENANT_MAX_CACHED_ENGINES",
        "SMART_CRM_TENANT_POOL_SIZE",
        "SMART_CRM_TENANT_MAX_OVERFLOW",
        "SMART_CRM_TENANT_POOL_TIMEOUT_SECONDS",
        "SMART_CRM_TENANT_CONNECT_TIMEOUT_SECONDS",
    }

    assert set(values) == expected
