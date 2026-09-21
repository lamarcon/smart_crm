# Multiempresa Seguro Validation

## Validation: Multiempresa Seguro - PASS ✅

**Verdict:** PASS ✅
**Date:** 2026-09-21
**Spec:** `.specs/features/secure-multitenancy/spec.md`
**Diff range:** `18f5a7d1..a3342fc`
**Verifier:** independent sub-agent (author ≠ verifier)

---

## Fresh Verification Scope

1. **P2 AC13 / T45:** o PostgreSQL 11 compartilhado preserva listener e bancos fora do escopo, mas `smartcrm`/`smartcrm_control` só passam com as quatro primeiras regras `host` exatas — allow IPv4/IPv6 loopback e reject IPv4/IPv6 remoto (`deployment-policy.ps1:15-45`).
2. **Fail-fast operacional:** o mesmo gate ocorre antes de criar a venv (`install-offline.ps1:46-54,70-72`) e antes das duas linhagens Alembic (`initialize-and-test.ps1:16-24,38-48`).
3. **Modo dedicado retido:** sem `-SharedPostgres`, exige IPv4 loopback e rejeita qualquer listener fora de `127.0.0.1`/`::1` (`deployment-policy.ps1:63-68`).

---

## Task Completion

| Task | Status | Notes |
| --- | --- | --- |
| T1-T38 | ✅ Retained | Build completo sem regressão: 586 backend e 93 browser. |
| T39 | ✅ Verified | Todos os limites documentados, inclusive `max_overflow=0`, falham fechado com mensagem genérica no bootstrap. |
| T40 | ✅ Verified | Factory central, loopback, ausência de fallback, placeholder, omissão e limites inválidos cobertos sem vazamento. |
| T41 | ✅ Verified | Credencial `SmartCRMService` obrigatória, sem default `SYSTEM`; mesma identidade DPAPI documentada. |
| T42 | ✅ Verified | Linhagens/revisões control e tenant separadas e confirmadas antes da publicação; startup web sem Alembic. |
| T43 | ✅ Verified | Contrato lado a lado, preservação e onboarding BRBots passam. |
| T44 | ✅ Verified | F1/F2 fechados; focais, gate e sensor independente passam. |
| T45 | ✅ Verified | Cluster compartilhado preservado; HBA Smart CRM fechado, ordenado e comprovado antes de instalação/migrações. |

---

## Spec-Anchored Acceptance Criteria

### P1 — Localizar e autenticar

| AC | Outcome e asserção exata | Result |
| --- | --- | --- |
| 1 | `tests/ui-prototype.spec.cjs:414` — `tenantLocator.isVisible() === true`; `tests/backend/test_schemas.py:243` — `request.slug == expected` | ✅ |
| 2 | `tests/backend/test_auth_api.py:170-172` — `status_code == 200` e cookie ausente | ✅ |
| 3 | `tests/backend/test_auth_service.py:188-192` — tenants/users A e B e chamadas exatas do router | ✅ |
| 4 | `tests/backend/test_auth_api.py:217-219` — 401, envelope genérico exato, sem cookie | ✅ |
| 5 | `tests/backend/test_security.py:34-36` — prefixo `$argon2id$` e hashes distintos | ✅ |
| 6 | `tests/backend/test_security.py:80-82` — retorno falso e uma verificação dummy | ✅ |
| 7 | `tests/backend/test_auth_service.py:299-300` — contador 5 e bloqueio de 15 minutos | ✅ |
| 8 | `tests/backend/test_auth_service.py:284` — `("ip", 30)`; `test_control_repository.py:193-195` — bloqueio/janela | ✅ |

### P1 — Sessão opaca

| AC | Outcome e asserção exata | Result |
| --- | --- | --- |
| 1 | `tests/backend/test_security.py:102-111` — entropia/unicidade/digest; `test_auth_service.py:257-261` — só digest e vínculo | ✅ |
| 2 | `tests/backend/test_control_models.py:63-64` — tenant/user/auth_version presentes, credencial/role ausentes | ✅ |
| 3 | `tests/backend/test_auth_api.py:200-202` — Secure, HttpOnly, Strict, Path=/, sem Domain | ✅ |
| 4 | `tests/backend/test_auth.py:157-184` — header/query/body alternativos retornam 401 sem router | ✅ |
| 5 | `tests/backend/test_security.py:119-131` — idle 30 min e absoluto 12 h | ✅ |
| 6 | `tests/backend/test_auth_api.py:240-244` — revogação e `Max-Age=0` | ✅ |
| 7 | `tests/backend/test_repository.py:128-190`; `test_auth.py:140-165` — auth_version e revogação somente após commit | ✅ |
| 8 | `tests/backend/test_auth.py:228-243` — Origin HTTPS exata em método inseguro | ✅ |

### P1 — Roteamento e isolamento

| AC | Outcome e asserção exata | Result |
| --- | --- | --- |
| 1 | `tests/backend/test_auth.py:102-106` — principal deriva de sessão e usuário tenant | ✅ |
| 2 | `tests/backend/test_auth_api.py:302-305` — router recebe somente `TENANT_ID` | ✅ |
| 3 | `tests/backend/test_auth.py:200-204`; `test_schemas.py:302` — inputs forjados sem autoridade | ✅ |
| 4 | `tests/backend/test_tenant_router.py:248-253` — mismatch antes de consulta comercial | ✅ |
| 5 | `tests/backend/test_tenant_router.py:248-254` — falha, invalida pool, sem fallback | ✅ |
| 6 | `tests/backend/test_repository_tenant_scope.py:187-208` — contexto explícito obrigatório | ✅ |
| 7 | `tests/backend/test_tenant_router.py:367-369`; `test_tenant_migration_security.py:189-205` — contexto + RLS FORCE/USING/WITH CHECK | ✅ |
| 8 | `tests/backend/test_tenant_router.py:227-228` — IDs iguais isolados por banco | ✅ |
| 9 | `tests/backend/test_repository_tenant_scope.py:261,285,316,338,388-389` — outro banco inalterado | ✅ |
| 10 | `tests/backend/test_auth_api.py:336-339` — rota divergente retorna 403 sem router | ✅ |
| 11 | `tests/backend/test_auth_api.py:314-316`; `test_tenant_router.py:302-307` — 503 sem fallback | ✅ |

### P1 — Autorização

| AC | Outcome e asserção exata | Result |
| --- | --- | --- |
| 1 | `tests/ui-prototype.spec.cjs:524-526` — identidade backend exibida e imutável | ✅ |
| 2 | `tests/ui-prototype.spec.cjs:524`; `test_workspace_authorization.py:257` — estado local não troca identidade | ✅ |
| 3 | `tests/backend/test_authorization.py:94-98` — ações administrativas somente Admin | ✅ |
| 4 | `tests/backend/test_authorization.py:57-68` — Gestor limitado à equipe | ✅ |
| 5 | `tests/backend/test_authorization.py:77-80` — perfis operacionais por responsabilidade/assistência | ✅ |
| 6 | `tests/backend/test_auth_api.py:284-286` — 403 e serviço não chamado | ✅ |
| 7 | `tests/backend/test_workspace_authorization.py:133-147` — projeção remove invisíveis | ✅ |
| 8 | `tests/backend/test_workspace_authorization.py:159-173` — merge preserva invisíveis canônicos | ✅ |

### P1 — Preservação e provisionamento

| AC | Outcome e asserção exata | Result |
| --- | --- | --- |
| 1 | `tests/backend/test_tenant_migration_security.py:149-163` — contagens/payloads/vínculos preservados | ✅ |
| 2 | `tests/backend/test_admin.py:167-174,196-200` — banco atual registrado e contagens iguais | ✅ |
| 3 | `tests/backend/test_admin.py:155-174` — provisioning até identidade/schema/admin/hash | ✅ |
| 4 | `tests/backend/test_admin.py:211-252` — falha não ativa e resume sem duplicar | ✅ |
| 5 | `tests/backend/test_admin.py:395-413` — entrada oculta e sem segredo em output | ✅ |
| 6 | `tests/backend/test_admin.py:421`; `test_fleet.py:314` — endpoint público inexistente | ✅ |
| 7 | `tests/backend/test_windows_multitenant_bundle.py:49-74,92-119` — wheels CPython 3.11 x64 e PG11 | ✅ |
| 8 | `tests/backend/test_server.py:143-162`; `test_admin.py:211-222` — schema incompatível bloqueia sem auto-migrate | ✅ |

### P2 — Operação segura

| AC | Outcome e asserção exata | Result |
| --- | --- | --- |
| 1 | `tests/backend/test_auth_service.py:386-426`; `test_tenant_router.py:205-300`; `test_auth_api.py:289-406` — eventos/linkage/redaction | ✅ |
| 2 | `tests/backend/test_auth_api.py:264-266` — 401 estável sem workspace | ✅ |
| 3 | `tests/backend/test_auth_api.py:284-286` — 403 estável sem oráculo | ✅ |
| 4 | `tests/backend/test_auth_api.py:200-286` — `Cache-Control == "no-store"` | ✅ |
| 5 | `tests/backend/test_auth_service.py:177-179,238-248`; `test_tenant_router.py:269-286` — estados não ativos/incompatíveis negados | ✅ |
| 6 | `tests/backend/test_fleet.py:123-158,185-197` — preflight por tenant e redigido | ✅ |
| 7 | `tests/backend/test_fleet.py:213-260` — seleção/backup/confirmação/resultados independentes | ✅ |
| 8 | `tests/backend/test_server.py:210-214,217-240` prova propagação e rejeição de zero; `test_manual_windows_pg11_outcomes.py:223-235,281-288,329-336` prova factory/loopback/sem fallback e `max_overflow=0` rejeitado. | ✅ |
| 9 | Placeholder/redação: `tests/backend/test_manual_windows_pg11_outcomes.py:291-302`; omissão/redação: `:305-316`; limite zero antes do Uvicorn: `:329-336`. | ✅ |
| 10 | `tests/backend/test_manual_windows_pg11_outcomes.py:223-259,276-278` — comandos/revisões exatos, ordem e `"alembic" not in start.lower()` | ✅ |
| 11 | `tests/backend/test_manual_windows_pg11_outcomes.py:345-356` — credencial obrigatória, SmartCRMService, sem SYSTEM, mesma identidade DPAPI | ✅ |
| 12 | `tests/backend/test_manual_windows_pg11_deployment.py:130-142` — diretório versionado, não sobrescrever, git pull proibido, dados BRBots e onboarding interativo | ✅ |
| 13 | `tests/backend/test_manual_windows_pg11_outcomes.py:168-177` mantém o modo dedicado estrito; `:180-208` exige HBA compartilhado exato e rejeita ausência/reordenação/enfraquecimento; `:211-223` exige o gate antes da venv e Alembic; `test_manual_windows_pg11_deployment.py:145-156` preserva `DW_CMS`/`DW_PRODUTOS`, reload sem restart e parâmetros compartilhados. | ✅ |

**Status:** ✅ 56/56 ACs passaram com outcome spec-anchored e evidência `file:line`.

---

## Edge Cases and Regression

Os dez edge cases anteriores permanecem cobertos. Evidências principais: slug `test_schemas.py:256-257`; cookie `test_auth_api.py:181-211`; throttle `test_control_repository.py:216-218`; conflito `test_workspace_service.py`; referência/rollback `test_schemas.py:103-105`; RLS `test_tenant_migration_security.py:214,245-247`; identidade/pool `test_tenant_router.py:248-307,393-396`; wheel `test_windows_multitenant_bundle.py:55-74`; ativação `test_admin.py:211-293`.

Nenhum teste foi removido ou enfraquecido no diff. A contagem cresceu de 566 backend antes da extensão operacional para 586; o baseline original da feature era 97 backend e 69 browser.

---

## Discrimination Sensor

Worktree isolado T45: `D:\Develop_CRM_Project\.verifier-worktrees\secure-multitenancy-t45-a3342fc` (removido). Nenhuma mutação ocorreu no worktree real.

| # | Mutação comportamental | Assert que matou | Resultado |
| --- | --- | --- | --- |
| T45-M1 | Remove o reject remoto IPv4 da factory HBA | `tests/backend/test_manual_windows_pg11_outcomes.py:205`: `assert valid.returncode == 0` falhou porque a factory deixou de corresponder ao bloco seguro | ✅ Killed |
| T45-M2 | Inverte as duas regras loopback iniciais na factory HBA | `tests/backend/test_manual_windows_pg11_outcomes.py:205`: o HBA canônico deixou de ser aceito | ✅ Killed |
| T45-M3 | Remove o gate HBA de `initialize-and-test.ps1`, permitindo alcançar Alembic sem a prova | `tests/backend/test_manual_windows_pg11_outcomes.py:219`: `assert "-SharedPostgres" in initialize` falhou | ✅ Killed |

**Sensor depth:** AC13/T45, 3 mutações comportamentais independentes no scratch.
**Sensor verdict:** 3/3 killed, 0 survived. PASS ✅

Após restauração, os quatro casos focais passaram. O scratch e seu diretório pai foram removidos. Antes da edição autorizada deste relatório, o porcelain real voltou exatamente ao baseline:

```text
?? .pytest-tmp/
?? .specs/features/crm-mvp/tasks.md
?? .venv/
?? smart_crm_demo.egg-info/
```

---

## Gate Check

- **Build:** `.venv\Scripts\python.exe -m compileall -q app migrations migrations_control`; compatibilidade; Compose; backend; browser; runbook; Apache.
- **Result:** 586 backend passed, 0 failed, 0 skipped; 93 browser passed, 0 failed; Python 3.11 27/27; Windows runbook 41/41; Apache 32/32; Compose válido; compileall limpo.
- **Warnings:** 2 dependências (Starlette/Pydantic), sem falha.
- **Package verifier:** `scripts/verify_manual_windows_pg11_deployment.py` — 19/19.
- **PowerShell parser:** PASS em todos os `deploy/manual-windows-pg11/*.ps1`.
- **Structural:** `validate_spec` 0 erros/0 warnings; `validate_tasks` 0 erros/7 warnings de granularidade em T39-T45.

---

## Code Quality

| Principle | Status |
| --- | --- |
| Mudanças cirúrgicas e sem deploy/push/produção | ✅ |
| Factory central e ausência de tenant fallback no startup | ✅ |
| Linhagens control/tenant e revisão exata | ✅ |
| Conta dedicada e DPAPI side-by-side | ✅ |
| Release versionada e onboarding BRBots | ✅ |
| Limites iguais à spec | ✅ `max_overflow=0` rejeitado no backend e wrapper |
| Per-layer coverage / todos os ramos do AC9 | ✅ omissão, placeholder e limites inválidos |
| PostgreSQL compartilhado sem regressão dos bancos legados | ✅ listener/DW preservados; HBA Smart CRM fail-closed |
| Guidelines | ✅ `coding-principles.md`, `tasks.md`, `pyproject.toml` |

---

## T45 Revalidation

- **Shared mode:** wildcard só passa com `-SharedPostgres` e as quatro primeiras regras host exatas; HBA ausente, reordenado ou enfraquecido falha.
- **Dedicated mode:** mantém exigência de IPv4 loopback e rejeição de binding público.
- **Ordering:** o gate antecede criação da venv, migração control e migração tenant.
- **Preservation:** o runbook não altera listener/regras dos bancos legados, usa backup + `pg_reload_conf()` sem restart e exige UAT remoto antes/depois.
- **New gaps:** nenhum.

---

## Lessons Distilled

Nenhuma lição nova: a verificação T45 passou limpa e não revelou falha real. As lições anteriores permanecem preservadas sem duplicação.

---

## Summary

**Overall:** ✅ Ready

**Spec-anchored check:** 56/56 ACs; 0 gaps.
**Sensor:** T45 matou 3/3 mutações comportamentais.
**Gate:** 586 backend + 93 browser + compatibilidade 27/27 + pacote 19/19 + runbook 41/41 + Apache 32/32.

P2 AC13/T45 está verificado sem regressão. A extensão operacional está pronta para fechamento documental; nenhum deploy, push ou acesso de produção foi executado.
