"""Validate the Windows Apache public-edge contract without loading Apache."""

from __future__ import annotations

import argparse
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VHOST = ROOT / "deploy" / "windows-apache" / "httpd-sc2030.conf.example"


class ContractError(RuntimeError):
    pass


def require(text: str, token: str, message: str) -> None:
    if token not in text:
        raise ContractError(message)


def reject(text: str, token: str, message: str) -> None:
    if token in text:
        raise ContractError(message)


def apache_contract(text: str) -> int:
    checks = [
        ('<VirtualHost *:80>', "Virtual host HTTP ausente."),
        ('<VirtualHost *:443>', "Virtual host HTTPS ausente."),
        ('ServerName sc2030.brbots.com', "Hostname público incorreto."),
        ('Alias "/.well-known/acme-challenge/"', "Alias ACME ausente."),
        ('Require all granted', "Desafio ACME não está público."),
        ('RewriteCond %{REQUEST_URI} !^/\\.well-known/acme-challenge/', "Redirecionamento não exclui ACME."),
        ('[R=301,L,NE]', "Redirecionamento HTTPS não é 301."),
        ('SSLCertificateFile "C:/ProgramData/SmartCRM/tls/sc2030.brbots.com-fullchain.pem"', "Cadeia TLS externa ausente."),
        ('SSLCertificateKeyFile "C:/ProgramData/SmartCRM/tls/sc2030.brbots.com-privkey.pem"', "Chave TLS externa ausente."),
        ('ProxyRequests Off', "Forward proxy não está desabilitado."),
        ('ProxyPass "/api/" "http://127.0.0.1:8080/api/"', "Proxy reservado da API ausente."),
        ('ProxyPassReverse "/api/" "http://127.0.0.1:8080/api/"', "Proxy reverso reservado da API ausente."),
        ('Root / and /{tenant-slug} use the same central application.', "Rotas de tenant não estão documentadas no proxy central."),
        ('ProxyPass "/" "http://127.0.0.1:8080/"', "Proxy não aponta ao loopback do CRM."),
        ('ProxyPassReverse "/" "http://127.0.0.1:8080/"', "Proxy reverso ausente."),
        ('RequestHeader set X-Forwarded-Proto "https"', "Protocolo encaminhado ausente."),
        ('CUTOVER GATE', "Gate de corte do Basic Auth ausente."),
        ('authorized UAT', "UAT autorizado não é pré-condição do corte."),
        ('AuthType Basic', "Basic Auth ausente."),
        ('AuthUserFile "C:/ProgramData/SmartCRM/apache/.htpasswd-smart-crm"', "Arquivo de credenciais externo ausente."),
        ('Require valid-user', "Acesso autenticado não é obrigatório."),
        ('LimitRequestBody 26214400', "Limite de 25 MB ausente."),
    ]
    for token, message in checks:
        require(text, token, message)
    reject(text, "0.0.0.0:8080", "Proxy aponta para binding público.")
    reject(text, "ProxyRequests On", "Forward proxy foi habilitado.")
    reject(text, "deploy/windows-apache/tls", "Material TLS foi colocado no clone.")
    reject(text.lower(), "postgresql://", "DSN de banco exposto no proxy.")
    reject(text.lower(), "database_url", "Configuração de banco exposta no proxy.")
    reject(text.lower(), "db_password", "Senha de banco exposta no proxy.")
    reject(text, ":5432", "Porta de banco exposta no proxy.")
    reject(text, ":5433", "Porta de banco exposta no proxy.")
    if text.count("ServerName sc2030.brbots.com") != 2:
        raise ContractError("O hostname deve aparecer nos dois virtual hosts.")
    api_proxy = text.index('ProxyPass "/api/" "http://127.0.0.1:8080/api/"')
    tenant_catch_all = text.index('ProxyPass "/" "http://127.0.0.1:8080/"')
    if api_proxy >= tenant_catch_all:
        raise ContractError("Mapeamento reservado da API deve preceder o catch-all de tenant.")
    return len(checks) + 10


def self_test(valid: str) -> None:
    assert apache_contract(valid) == 32
    mutations = [
        valid.replace("ServerName sc2030.brbots.com", "ServerName old.example", 1),
        valid.replace("http://127.0.0.1:8080/", "http://0.0.0.0:8080/"),
        valid.replace("ProxyRequests Off", "ProxyRequests On"),
        valid.replace("AuthType Basic", "AuthType Disabled"),
    ]
    for mutation in mutations:
        try:
            apache_contract(mutation)
        except ContractError:
            pass
        else:
            raise AssertionError("Mutação Apache insegura não detectada.")
    print("windows apache verifier self-test: PASS (4/4 killed)")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    text = VHOST.read_text(encoding="utf-8")
    if args.self_test:
        self_test(text)
        return 0
    count = apache_contract(text)
    print(f"windows apache contract: {count} passed, 0 failed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ContractError, OSError) as error:
        print(f"windows apache contract: FAIL - {error}")
        raise SystemExit(1)
