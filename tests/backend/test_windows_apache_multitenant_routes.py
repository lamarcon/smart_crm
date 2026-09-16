from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
VHOST = PROJECT_ROOT / "deploy/windows-apache/httpd-sc2030.conf.example"


def load_verifier():
    path = PROJECT_ROOT / "scripts/verify_windows_apache_contract.py"
    spec = importlib.util.spec_from_file_location("apache_multitenant_contract", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


verifier = load_verifier()


def read_vhost() -> str:
    return VHOST.read_text(encoding="utf-8")


def test_api_proxy_is_explicit_and_precedes_tenant_catch_all() -> None:
    text = read_vhost()

    api = 'ProxyPass "/api/" "http://127.0.0.1:8080/api/"'
    catch_all = 'ProxyPass "/" "http://127.0.0.1:8080/"'
    assert api in text
    assert text.index(api) < text.index(catch_all)


def test_reverse_proxy_preserves_api_and_tenant_path_prefixes() -> None:
    text = read_vhost()

    assert 'ProxyPassReverse "/api/" "http://127.0.0.1:8080/api/"' in text
    assert 'ProxyPassReverse "/" "http://127.0.0.1:8080/"' in text


def test_root_and_tenant_slug_are_documented_as_one_central_app() -> None:
    text = read_vhost()

    assert "Root / and /{tenant-slug} use the same central application." in text
    assert text.count('ProxyPass "/" "http://127.0.0.1:8080/"') == 1


def test_reserved_acme_path_stays_outside_application_redirect() -> None:
    text = read_vhost()

    assert 'Alias "/.well-known/acme-challenge/"' in text
    assert "RewriteCond %{REQUEST_URI} !^/\\.well-known/acme-challenge/" in text


def test_basic_auth_is_retained_with_an_explicit_authorized_cutover_gate() -> None:
    text = read_vhost()

    assert "AuthType Basic" in text
    assert "CUTOVER GATE" in text
    assert "authorized UAT" in text
    assert "Remove this entire <Location" in text


def test_apache_configuration_contains_no_tenant_database_or_secret() -> None:
    lowered = read_vhost().lower()

    for forbidden in ("postgresql://", "5432", "5433", "database_url", "db_password", "cliente-a"):
        assert forbidden not in lowered
    assert "http://127.0.0.1:8080/" in lowered


def test_verifier_rejects_api_mapping_after_the_catch_all() -> None:
    text = read_vhost()
    api_lines = (
        '    ProxyPass "/api/" "http://127.0.0.1:8080/api/" connectiontimeout=5 timeout=60\n'
        '    ProxyPassReverse "/api/" "http://127.0.0.1:8080/api/"\n'
    )
    without_api = text.replace(api_lines, "")
    unsafe = without_api.replace(
        '    ProxyPassReverse "/" "http://127.0.0.1:8080/"\n',
        '    ProxyPassReverse "/" "http://127.0.0.1:8080/"\n' + api_lines,
    )

    with pytest.raises(verifier.ContractError, match="API"):
        verifier.apache_contract(unsafe)




def test_forward_proxy_and_public_application_binding_are_forbidden() -> None:
    text = read_vhost()

    assert "ProxyRequests Off" in text
    assert "ProxyRequests On" not in text
    assert "0.0.0.0:8080" not in text
