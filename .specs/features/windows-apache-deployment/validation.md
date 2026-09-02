# Validation: Windows Apache Deployment - FAIL

**Result:** FAIL
**Date:** 2026-09-02
**Spec:** `.specs/features/windows-apache-deployment/spec.md`
**Diff range:** `0167a80..ebdf093`
**Verifier:** independent sub-agent (author != verifier)

O pacote local está pronto para staging controlado. Todos os contratos estáticos passaram e o sensor independente matou as três regressões que haviam sobrevivido antes do commit `ebdf093`. O corte remoto continua bloqueado porque não há evidência de TLS renovado nem do UAT no servidor Windows/Apache.

## Task Completion

| Deliverable | Status | Notes |
| --- | --- | --- |
| Especificação e contexto | ✅ Done | `validate_spec`: 0 erros, 0 avisos. |
| Python 3.11 e dependências fixadas | ✅ Static PASS | Executável exato, venv acoplado e pins verificados. |
| PostgreSQL 17/5433 e preservação do PostgreSQL 11 | ✅ Static PASS | Contrato e mutações adversariais aprovados. |
| Runtime Windows, Apache e runbook | ✅ Static PASS | 92 verificações contratuais aprovadas. |
| TLS e UAT no servidor | ❌ Pending | Nenhuma execução remota foi autorizada ou apresentada. |

## Spec-Anchored Acceptance Criteria

| Requirement | Spec-defined outcome | `file:line` + assertion expression | Result |
| --- | --- | --- | --- |
| WAD-01 | Verificar Python 3.11 em `C:/brbots/python/python.exe`, criar o venv com esse executável e instalar dependências fixadas. | `deploy/windows-apache/README.md:101-105` executa o gate 3.11, `$python311 -m venv .venv` e `pip install .`; `pyproject.toml:9-15` define `>=3.11,<3.13` e versões `==`; `scripts/verify_windows_runbook_contract.py:21-24` exige executável, versão, venv acoplado e instalação; `scripts/verify_python_compatibility.py:22-31` exige faixa, pins e AST 3.11. | ✅ PASS estático |
| WAD-02 | PostgreSQL 17 em `127.0.0.1:5433`; Alembic cria o schema. | `deploy/windows-apache/README.md:140,159,192`; `scripts/verify_windows_runbook_contract.py:27,31,34` exige porta, `psql` em 5433 e `alembic upgrade head`. | ✅ PASS estático |
| WAD-03 | Uvicorn somente em `127.0.0.1:8080`. | `deploy/windows-apache/start-smart-crm.ps1:69-78,100-101`; `scripts/verify_windows_apache_deployment.py:37-41,52` exige loopback/8080 e rejeita `0.0.0.0`. | ✅ PASS |
| WAD-04 | Ambiente ausente ou senha diferente de 64 hex encerra antes do Uvicorn. | `deploy/windows-apache/start-smart-crm.ps1:25-26,63-64,100`; execuções `-ValidateOnly` retornaram exit 1 para arquivo ausente e placeholder; `scripts/verify_windows_apache_deployment.py:35` exige a regex exata. | ✅ PASS |
| WAD-05 | Tarefa de boot como SYSTEM com ao menos cinco reinícios de um minuto. | `deploy/windows-apache/install-scheduled-task.ps1:28-33`; `scripts/verify_windows_apache_deployment.py:42-45` exige `AtStartup`, `SYSTEM`, 10 reinícios e intervalo de um minuto. | ✅ PASS estático |
| WAD-06 | Virtual hosts 80/443 usam `sc2030.brbots.com`. | `deploy/windows-apache/httpd-sc2030.conf.example:6-7,24-25`; `scripts/verify_windows_apache_contract.py:29-31,52` exige os dois hosts e duas ocorrências do nome. | ✅ PASS |
| WAD-07 | HTTP deixa ACME público e redireciona o restante com 301. | `deploy/windows-apache/httpd-sc2030.conf.example:13,17-18`; `scripts/verify_windows_apache_contract.py:33-35` exige acesso público, exclusão ACME e `[R=301,L,NE]`. | ✅ PASS estático |
| WAD-08 | HTTPS faz reverse proxy para `127.0.0.1:8080` e desliga forward proxy. | `deploy/windows-apache/httpd-sc2030.conf.example:32,37-38`; `scripts/verify_windows_apache_contract.py:38-40,49-50` exige destino loopback e `ProxyRequests Off`. | ✅ PASS |
| WAD-09 | Basic Auth protege a aplicação; apenas ACME é público. | `deploy/windows-apache/httpd-sc2030.conf.example:13,44,48`; `scripts/verify_windows_apache_contract.py:33,42-44` exige `Require all granted` no ACME e `Require valid-user` na aplicação. | ✅ PASS estático |
| WAD-10 | Apache usa fullchain PEM e chave separada fora do clone. | `deploy/windows-apache/httpd-sc2030.conf.example:29-30`; `scripts/verify_windows_apache_contract.py:36-37,51` exige arquivos distintos sob `C:/ProgramData/SmartCRM/tls`. | ✅ PASS |
| WAD-11 | Certificado expirado bloqueia o corte. | `deploy/windows-apache/README.md:262-263,337-349`; `scripts/verify_windows_runbook_contract.py:38` exige `x509 -checkend 604800`. | ✅ Procedimento; ❌ UAT remoto pendente |
| WAD-12 | Falha restaura a configuração Apache salva antes do anúncio. | `deploy/windows-apache/README.md:400-411`; `scripts/verify_windows_runbook_contract.py:48-50` exige parada, restauração de `httpd.conf` e preservação do banco. | ✅ Procedimento; ❌ ensaio remoto pendente |
| WAD-13 | Serviço, configuração e dados do PostgreSQL 11/5432 permanecem intocados. | `deploy/windows-apache/README.md:35-42,151-159,220-228`; `scripts/verify_windows_runbook_contract.py:30,61-64` exige a proibição e rejeita restart/stop/remove/set-service. | ✅ PASS estático |

**Spec-anchored status:** 13/13 requisitos têm evidência estática precisa. Os resultados remotos de WAD-11/WAD-12 e dos Success Criteria continuam sem prova.

## Gate Check

- `validate_spec.py`: 0 erros, 0 avisos.
- `verify_python_compatibility.py`: 14 passed, 0 failed.
- `verify_windows_apache_deployment.py`: 16 passed, 0 failed.
- `verify_windows_apache_contract.py`: 21 passed, 0 failed.
- `verify_windows_runbook_contract.py`: 41 passed, 0 failed.
- Self-tests dos quatro validadores: 22/22 mutações mortas.
- `compileall` de `app`, `migrations` e `scripts`: PASS.
- Parser PowerShell: 2 passed, 0 failed.
- Rejeição `-ValidateOnly`: arquivo ausente exit 1; senha placeholder exit 1.
- `git diff --check 0167a80..ebdf093`: PASS.
- Runtime local do gate: Python empacotado 3.12.13. O executável Python 3.11 do servidor só pode ser confirmado no UAT do host.

**Static gate:** 92 verificações contratuais aprovadas, 0 falhas, 0 skips.

## Discrimination Sensor

As mutações foram aplicadas somente em strings em memória. O porcelain antes e depois permaneceu exatamente `?? .specs/features/crm-mvp/tasks.md`.

| Mutation | Assertion evidence | Result |
| --- | --- | --- |
| Criar o venv com `py -3.12` | `scripts/verify_windows_runbook_contract.py:23,83` exige `$python311 -m venv .venv`. | ✅ Killed |
| Trocar o `throw` do conflito 5433 por `Write-Warning` | `scripts/verify_windows_runbook_contract.py:28-29,84` exige consulta e interrupção. | ✅ Killed |
| Adicionar `Set-Service postgresql-x64-11 -StartupType Disabled` | `scripts/verify_windows_runbook_contract.py:64,85` rejeita alteração do serviço antigo. | ✅ Killed |

**Sensor depth:** targeted regression recheck
**Sensor outcome:** 3/3 killed - PASS. Com os self-tests: 25/25 tentativas aprovadas, 0 sobreviventes.

## Edge Cases

- ✅ Porta 5433 ocupada bloqueia a instalação: `deploy/windows-apache/README.md:46-48`; contrato em `scripts/verify_windows_runbook_contract.py:28-29`.
- ✅ `psql` aponta ao PostgreSQL 17/5433: `deploy/windows-apache/README.md:159` e `scripts/verify_windows_runbook_contract.py:31`.
- ✅ `pg_dump` usa o binário PostgreSQL 17 e a porta configurada: `deploy/windows-apache/README.md:369-370` e `scripts/verify_windows_runbook_contract.py:44-45`.
- ✅ PostgreSQL 11 permanece separado e comandos de alteração conhecidos são rejeitados em `scripts/verify_windows_runbook_contract.py:30,61-64`.
- ⚠️ Bloqueio TLS e rollback estão documentados, mas não foram ensaiados no host.

## Code Quality

| Principle | Status |
| --- | --- |
| Mudanças limitadas ao runtime Windows solicitado | ✅ |
| Dependências de runtime fixadas | ✅ |
| Assertions correspondem aos resultados exatos da especificação | ✅ |
| Sensor cobre as conjunções críticas corrigidas | ✅ |
| Diretriz aplicada | `tlc-spec-driven/references/coding-principles.md` |

## Interactive UAT

Não executado. Faltam evidências do servidor para certificado válido, `httpd.exe -t`, listeners 5432/5433/8080, HTTP 301 com ACME público, HTTPS 401, `/health` autenticado com `{"status":"ok","database":"ok"}` e rollback real.

## Ranked Gaps and Remediation

1. **Blocker: TLS/UAT remoto ausente.** Renovar o certificado, executar o runbook no Windows e registrar as saídas exigidas antes do corte.
2. **Major: rollback real não ensaiado.** Confirmar a restauração do virtual host antigo sem apagar, alterar ou reutilizar o PostgreSQL 11.

## Summary

**Overall:** FAIL - NOT READY FOR REMOTE CUTOVER

**Local package:** STATIC PASS. O conteúdo e os testes implementam Python 3.11 exato, dependências fixadas, PostgreSQL 17/5433, preservação do PostgreSQL 11, `psql` e `pg_dump` na instância correta e bloqueio por conflito 5433.

**Next step:** levar o pacote ao host para staging controlado, renovar o TLS e executar o UAT. O corte público permanece proibido até essas evidências existirem.
