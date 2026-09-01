# Validation: Windows Apache Deployment - FAIL

**Result:** FAIL
**Date:** 2026-09-01
**Spec:** `.specs/features/windows-apache-deployment/spec.md`
**Diff range:** `e5da2e9..fcdcbd5`
**Verifier:** independent sub-agent (author != verifier)

O pacote local atende ao contrato estático. O corte em
`sc2030.brbots.com` ainda não está aprovado porque não houve acesso ao
servidor Windows/Apache nem UAT remoto. A observação disponível continua sendo
certificado expirado e HTTPS 503.

## Task Completion

| Task | Status | Notes |
| --- | --- | --- |
| Especificação e contexto | ✅ Done | `validate_spec`: 0 erros, 0 avisos. |
| Runtime Windows e supervisão | ✅ Done | Contrato estático e rejeição de ambiente inválido aprovados. |
| Virtual host Apache | ✅ Done | Contrato estático aprovado. |
| Runbook de instalação e rollback | ✅ Done | Contrato estático aprovado. |
| UAT no servidor | ❌ Pending | Sem acesso remoto, certificado renovado ou PostgreSQL local ativo. |

## Spec-Anchored Acceptance Criteria

| Requirement | Spec-defined outcome | `file:line` + assertion expression | Result |
| --- | --- | --- | --- |
| WAD-01 | Criar virtualenv Python 3.12 e instalar dependências fixadas. | `deploy/windows-apache/README.md:84` - `py -3.12 -m venv .venv`; `scripts/verify_windows_runbook_contract.py:21-22` - exige virtualenv e `-m pip install .`; `pyproject.toml:11-17` fixa versões exatas. | ✅ PASS |
| WAD-02 | PostgreSQL somente local; Alembic cria tabelas sem `CREATE TABLE` manual. | `deploy/windows-apache/README.md:120,128,154-168`; `scripts/verify_windows_runbook_contract.py:24-27` - exige `listen_addresses = 'localhost'`, papel, banco e `-m alembic upgrade head`. | ✅ PASS estático |
| WAD-03 | Uvicorn escuta somente em `127.0.0.1:8080`. | `deploy/windows-apache/start-smart-crm.ps1:69-78,100-104`; `scripts/verify_windows_apache_deployment.py:37-42,51` - exige loopback/8080 e rejeita `0.0.0.0`. | ✅ PASS |
| WAD-04 | Ambiente ausente ou senha diferente de 64 hex encerra antes do Uvicorn. | `deploy/windows-apache/start-smart-crm.ps1:25-27,63-65,81-100`; execução `-ValidateOnly` produziu exit 1 para arquivo ausente e para o placeholder; `scripts/verify_windows_apache_deployment.py:35,75-79` mata senha enfraquecida. | ✅ PASS |
| WAD-05 | Tarefa inicia no boot como SYSTEM com ao menos cinco reinícios de um minuto. | `deploy/windows-apache/install-scheduled-task.ps1:28-35`; `scripts/verify_windows_apache_deployment.py:42-45` - exige `AtStartup`, `SYSTEM`, `RestartCount 10` e intervalo de um minuto. | ✅ PASS estático |
| WAD-06 | Virtual hosts 80/443 usam `sc2030.brbots.com`. | `deploy/windows-apache/httpd-sc2030.conf.example:6-7,24-25`; `scripts/verify_windows_apache_contract.py:29-31,52-53` - exige os dois hosts e exatamente duas ocorrências do hostname. | ✅ PASS |
| WAD-07 | HTTP preserva ACME público e redireciona o restante com 301. | `deploy/windows-apache/httpd-sc2030.conf.example:9-18`; `scripts/verify_windows_apache_contract.py:32-35` - exige Alias público, exclusão ACME e `[R=301,L,NE]`. | ✅ PASS estático |
| WAD-08 | HTTPS usa reverse proxy para loopback e desliga forward proxy. | `deploy/windows-apache/httpd-sc2030.conf.example:32-38`; `scripts/verify_windows_apache_contract.py:38-40,49-50` - exige `ProxyRequests Off`, proxy/reverse proxy em `127.0.0.1:8080` e rejeita binding público. | ✅ PASS |
| WAD-09 | Caminhos do CRM exigem Basic Auth; somente ACME fica público. | `deploy/windows-apache/httpd-sc2030.conf.example:9-14,43-49`; `scripts/verify_windows_apache_contract.py:32-33,42-44` - exige `Require all granted` no ACME e `Require valid-user` na aplicação. | ✅ PASS estático |
| WAD-10 | Apache carrega fullchain PEM e chave separada fora do clone. | `deploy/windows-apache/httpd-sc2030.conf.example:29-30`; `scripts/verify_windows_apache_contract.py:36-37,51` - exige arquivos distintos em `C:/ProgramData/SmartCRM/tls` e rejeita TLS no clone. | ✅ PASS |
| WAD-11 | Certificado expirado bloqueia o corte. | `deploy/windows-apache/README.md:206-207,230-245,293-303`; `scripts/verify_windows_runbook_contract.py:31,65` - exige `x509 -checkend 604800` e mata a remoção do gate. | ✅ PASS do procedimento; UAT pendente |
| WAD-12 | Falha do CRM/proxy restaura a configuração Apache salva. | `deploy/windows-apache/README.md:373-384`; `scripts/verify_windows_runbook_contract.py:39-41` - exige parada controlada, restauração de `httpd.conf` e preservação do banco. | ✅ PASS do procedimento; ensaio pendente |

**Spec-anchored status:** 12/12 requisitos têm evidência estática precisa.
Isso não satisfaz os dois resultados remotos definidos nos Success Criteria.

## Gate Check

- `validate_spec.py`: 0 erros, 0 avisos.
- `verify_windows_apache_deployment.py`: 15 passed, 0 failed.
- `verify_windows_apache_contract.py`: 21 passed, 0 failed.
- `verify_windows_runbook_contract.py`: 29 passed, 0 failed.
- Self-tests dos três validadores: 11/11 mutações mortas.
- `compileall`: PASS.
- Parser PowerShell: 2/2 scripts válidos.
- `git diff --check e5da2e9..fcdcbd5`: PASS.
- Rejeição runtime: ambiente ausente exit 1; senha placeholder exit 1.
- Suíte backend local sem PostgreSQL: 22 passed, 1 warning.
- Primeiro teste PostgreSQL real: 1 failed em
  `tests/backend/test_database.py:29`, pois `database.check_database()` retornou
  `False`; não há PostgreSQL local ativo.

## Discrimination Sensor

| Validator | Mutations | Result |
| --- | ---: | --- |
| Runtime Windows | 3 | 3/3 killed |
| Apache | 4 | 4/4 killed |
| Runbook | 4 | 4/4 killed |

Os sensores operam em cópias in-memory. Eles alteraram binding público,
força do segredo, identidade da tarefa, hostname, destino do proxy, forward
proxy, autenticação, escuta PostgreSQL, migração, validade TLS e estratégia
Git. Todos foram detectados. O porcelain real permaneceu idêntico:
apenas `.specs/features/crm-mvp/tasks.md` já estava untracked e continua fora
do diff.

**Sensor depth:** lightweight infrastructure contract
**Sensor outcome:** 11/11 killed - PASS

## Edge Cases

- ✅ Falha de migração mantém o virtual host antigo: procedimento em
  `deploy/windows-apache/README.md:167-173,297-303`.
- ✅ Certificado/chave divergentes bloqueiam o corte: comparação de hashes e
  `httpd.exe -t` em `deploy/windows-apache/README.md:230-246,293-303`.
- ✅ Segredo ou chave no Git bloqueiam o fluxo: instruções em
  `deploy/windows-apache/README.md:77-78,92-113`.
- ⚠️ Rollback por falha de conectividade está documentado, mas não foi
  ensaiado no servidor.

## Code Quality

| Principle | Status |
| --- | --- |
| Minimum code | ✅ |
| Surgical changes | ✅ |
| No scope creep | ✅ |
| Matches repository patterns | ✅ |
| Assertions match spec-defined tokens/outcomes | ✅ |
| Tests map to WAD requirements or edge cases | ✅ |
| Documented guideline | ✅ `tlc-spec-driven/references/coding-principles.md` |

## Interactive UAT

Não executado. Não houve acesso ao servidor. Não existe evidência para:

1. certificado válido para `sc2030.brbots.com`;
2. `httpd.exe -t` e reinício do Apache no host real;
3. HTTP 301 preservando o challenge ACME;
4. HTTPS sem credenciais retornando 401;
5. HTTPS autenticado `/health` retornando exatamente
   `{"status":"ok","database":"ok"}`;
6. PostgreSQL e Uvicorn escutando somente em loopback no host;
7. rollback real restaurando o aplicativo anterior.

## Ranked Gaps and Remediation

1. **Blocker: certificado expirado e HTTPS 503.** Renovar o certificado pelo
   processo PunchSalad, instalar fullchain/chave fora do Git e executar os gates
   TLS do runbook.
2. **Blocker: UAT remoto sem evidência.** Executar o checklist no Windows/Apache,
   registrar SHA, saídas de `httpd.exe -t`, listeners, 401 e payload exato do
   `/health` autenticado.
3. **Major: rollback não ensaiado.** Antes de anunciar o CRM, simular falha do
   upstream e confirmar a restauração do virtual host salvo sem apagar o banco.

## Requirement Traceability

| Requirements | Previous | Validation result |
| --- | --- | --- |
| WAD-01..WAD-12 | Implementing | Static contract verified; server UAT pending |

## Summary

**Overall:** NOT READY FOR CUTOVER

O conteúdo que será levado por Git está coerente e os gates locais são
discriminantes. A funcionalidade não pode ser declarada concluída porque os
Success Criteria exigem observação do servidor real. O próximo passo é executar
o runbook no host Windows, renovar o TLS e anexar as evidências do UAT.
