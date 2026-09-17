# Multiempresa Seguro Validation

## Validation: Multiempresa Seguro - FAIL ❌

**Verdict:** FAIL ❌
**Date:** 2026-09-17 (independent revalidation round 2)
**Spec:** `.specs/features/secure-multitenancy/spec.md`
**Diff range:** `ef29191..c6cba90` (corrections T28-T33); implementation lineage remains `6962ca5..c6cba90`
**Verifier:** independent sub-agent (author ≠ verifier)

---

## Task Completion

| Task | Status | Notes |
| ---- | ------ | ----- |
| T1-T26 | ✅ Done | Commits, checklists reconciliados e evidência de gate presentes. |
| T28-T33 | ✅ Done | Correções de revogação, TLS, auditoria, cookie em APIs, no-store e checklists verificadas. |
| T27 | ⚠️ In Progress | Documentação e gate passaram; a revalidação independente ainda encontrou um edge funcional. |

## Spec-Anchored Acceptance Criteria

| Criterion | Spec-defined outcome | `file:line` + assertion | Result |
| --------- | -------------------- | ----------------------- | ------ |
| MT-01.1 | `/` mostra localizador e normaliza identificador | `tests/ui-prototype.spec.cjs:414` - `tenantLocator.isVisible() === true`; `tests/backend/test_schemas.py:243` - `request.slug == expected` | ✅ PASS |
| MT-01.2 | Tenant ativo abre `/{slug}` sem criar sessão | `tests/backend/test_auth_api.py:170` - status 200; `:172` - cookie ausente; `tests/ui-prototype.spec.cjs:423` - login visível | ✅ PASS |
| MT-01.3 | Login verifica usuário somente no banco resolvido | `tests/backend/test_auth_service.py:188-192` - tenant/user A e B e chamadas exatas do router | ✅ PASS |
| MT-01.4 | Toda falha pública usa a mensagem genérica | `tests/backend/test_auth_api.py:217-219` - 401, envelope exato e nenhum cookie | ✅ PASS |
| MT-01.5 | Senha persiste apenas como Argon2id com salt único | `tests/backend/test_security.py:34-36` - prefixo `$argon2id$` e hashes diferentes | ✅ PASS |
| MT-01.6 | Sujeito desconhecido executa hash fictício | `tests/backend/test_security.py:80-82` - resultado falso e uma verificação dummy | ✅ PASS |
| MT-01.7 | Quinta falha conta/tenant bloqueia por 15 min | `tests/backend/test_auth_service.py:299-300` - contador 5 e `blocked_until +15m` | ✅ PASS |
| MT-01.8 | Trigésima falha por IP usa limite 30 | `tests/backend/test_auth_service.py:284` - repositório recebe `("ip", 30)`; `tests/backend/test_control_repository.py:193-195` - limite genérico bloqueia e fixa janela | ✅ PASS |
| MT-02.1 | Token opaco ≥128 bits; só digest SHA-256 é armazenado | `tests/backend/test_security.py:102-111` - entropia/unicidade e digest; `tests/backend/test_auth_service.py:257-261` - só digest/linkage | ✅ PASS |
| MT-02.2 | Sessão liga tenant/user/auth_version sem hash no control | `tests/backend/test_control_models.py:63-64` - campos de vínculo presentes e credenciais/role ausentes | ✅ PASS |
| MT-02.3 | Cookie `__Host-`, Secure, HttpOnly, Strict, `/`, sem Domain | `tests/backend/test_auth_api.py:200-202` - atributos exatos e ausência de Domain | ✅ PASS |
| MT-02.4 | Fontes alternativas de token são rejeitadas | `tests/backend/test_auth.py:157-184` - header/query/body resultam 401 sem abrir router | ✅ PASS |
| MT-02.5 | Expira em 30 min ocioso ou 12 h absoluto | `tests/backend/test_security.py:119-131`; `tests/backend/test_auth_service.py:271-274` - limites exatos | ✅ PASS |
| MT-02.6 | Logout revoga no servidor e expira cookie | `tests/backend/test_auth_api.py:240-244` - revogação e Max-Age=0 com flags | ✅ PASS |
| MT-02.7 | Mudança de senha, perfil, status ou auth_version revoga sessões anteriores | `tests/backend/test_repository.py:128-190` prova incremento/rollback; `tests/backend/test_auth.py:140-165` prova revogação só após commit; `tests/backend/test_auth_service.py:371-426` prova invalidação e auditoria | ✅ PASS |
| MT-02.8 | Método inseguro exige Origin HTTPS exata | `tests/backend/test_auth.py:228-243` e `tests/backend/test_auth_api.py:353-355` | ✅ PASS |
| MT-03.1 | Principal deriva da sessão central e usuário tenant atual | `tests/backend/test_auth.py:102-106` - tenant/user/session imutáveis e router pelo UUID | ✅ PASS |
| MT-03.2 | API seleciona perfil somente por tenant_id da sessão | `tests/backend/test_auth_api.py:302-305` - router recebe somente `TENANT_ID` | ✅ PASS |
| MT-03.3 | tenant/workspace/DSN/user/role do navegador não têm autoridade | `tests/backend/test_auth.py:200-204`; `tests/backend/test_schemas.py:302` | ✅ PASS |
| MT-03.4 | Identidade imutável é verificada antes de SQL comercial | `tests/backend/test_tenant_router.py:248-253` - mismatch falha e nenhuma consulta a `teams` | ✅ PASS |
| MT-03.5 | Mismatch falha fechado, invalida pool e não tenta outro banco | `tests/backend/test_tenant_router.py:248-254` | ✅ PASS |
| MT-03.6 | Toda operação tenant-owned exige workspace explícito | `tests/backend/test_repository_tenant_scope.py:187-208` - contexto ausente/mismatch e ausência de `session.get` | ✅ PASS |
| MT-03.7 | Transação configura workspace e RLS usa USING/WITH CHECK + FORCE | `tests/backend/test_tenant_router.py:367-369`; `tests/backend/test_tenant_migration_security.py:189-205` | ✅ PASS |
| MT-03.8 | IDs iguais em bancos distintos permanecem isolados | `tests/backend/test_tenant_router.py:227-228`; `tests/backend/test_repository_tenant_scope.py:232-233` | ✅ PASS |
| MT-03.9 | ID existente só no outro banco não altera nenhum banco | `tests/backend/test_repository_tenant_scope.py:261,285,316,338,388-389` | ✅ PASS |
| MT-03.10 | Slug de rota divergente rejeita sem remapear | `tests/backend/test_auth_api.py:336-339` - 403 e router não chamado | ✅ PASS |
| MT-03.11 | Banco indisponível retorna 503 sem fallback/cache | `tests/backend/test_auth_api.py:314-316`; `tests/backend/test_tenant_router.py:302-307` | ✅ PASS |
| MT-04.1 | Frontend obtém/exibe identidade imutável do backend | `tests/ui-prototype.spec.cjs:524-526` | ✅ PASS |
| MT-04.2 | Seletor/currentUser local não muda identidade | `tests/ui-prototype.spec.cjs:524`; `tests/backend/test_workspace_authorization.py:257` | ✅ PASS |
| MT-04.3 | Administrador possui ações administrativas só no tenant | `tests/backend/test_authorization.py:94-98` | ✅ PASS |
| MT-04.4 | Gestor restringe Leads/Negócios à equipe | `tests/backend/test_authorization.py:57-68` | ✅ PASS |
| MT-04.5 | Vendedor/Assistente/Faturamento restringem por responsabilidade/assistência | `tests/backend/test_authorization.py:77-80` | ✅ PASS |
| MT-04.6 | Não-admin recebe 403 e não executa ação privilegiada | `tests/backend/test_auth_api.py:284-286` - 403 e serviço não chamado | ✅ PASS |
| MT-04.7 | Projeção remove registros fora da visibilidade | `tests/backend/test_workspace_authorization.py:133-147` | ✅ PASS |
| MT-04.8 | Merge parcial preserva registros invisíveis canônicos | `tests/backend/test_workspace_authorization.py:159-173` | ✅ PASS |
| MT-05.1 | Migração preserva default, linhas, payloads e vínculos | `tests/backend/test_tenant_migration_security.py:149-163` | ✅ PASS |
| MT-05.2 | Ativação registra banco atual e preserva contagens | `tests/backend/test_admin.py:167-174,196-200` | ✅ PASS |
| MT-05.3 | Tenant fica provisioning até identidade/schema/admin/hash válidos | `tests/backend/test_admin.py:155-174` | ✅ PASS |
| MT-05.4 | Falha mantém não ativo e resume sem duplicar | `tests/backend/test_admin.py:211-252` | ✅ PASS |
| MT-05.5 | CLI usa entrada oculta e não imprime segredo | `tests/backend/test_admin.py:395-413` | ✅ PASS |
| MT-05.6 | Não existe endpoint público de provisionamento | `tests/backend/test_admin.py:421`; `tests/backend/test_fleet.py:314` | ✅ PASS |
| MT-05.7 | Pacote offline fixa Argon2 CPython 3.11 x64/PostgreSQL 11 | `tests/backend/test_windows_multitenant_bundle.py:49-74,92-119` | ✅ PASS |
| MT-05.8 | Startup/ativação rejeitam schema incompatível sem auto-migrate | `tests/backend/test_server.py:97-116`; `tests/backend/test_admin.py:211-222` | ✅ PASS |
| MT-06.1 | Login/logout/bloqueio/revogação/misrouting/negação geram auditoria redigida | `tests/backend/test_auth_service.py:386-426`, `tests/backend/test_tenant_router.py:205-233,266-300` e `tests/backend/test_auth_api.py:289-406` provam revogação, routing/identity, 401/403, linkage e redaction | ✅ PASS |
| MT-06.2 | API protegida sem sessão retorna 401 estável sem workspace | `tests/backend/test_auth_api.py:264-266` | ✅ PASS |
| MT-06.3 | Perfil insuficiente retorna 403 estável sem oráculo | `tests/backend/test_auth_api.py:284-286` | ✅ PASS |
| MT-06.4 | Login/logout/session/workspace sempre enviam no-store | `tests/backend/test_auth_api.py:200-220,247-286` e `tests/backend/test_api.py` cobrem login bem-sucedido, sessão, logout e workspace | ✅ PASS |
| MT-06.5 | Tenant não ativo/incompatível nega login e sessões | `tests/backend/test_auth_service.py:177-179,238-248`; `tests/backend/test_tenant_router.py:269-286` | ✅ PASS |
| MT-06.6 | Preflight relata conectividade/identidade/revisão sem segredo | `tests/backend/test_fleet.py:123-158,185-197` | ✅ PASS |
| MT-06.7 | Migração exige seleção/backup/confirmação e isola resultados | `tests/backend/test_fleet.py:213-221,234-260` | ✅ PASS |

**Status:** 50/50 critérios funcionais com evidência suficiente; o edge transversal de limpeza de cookie em `/{slug}` ainda falha.

## Confirmed Security Decisions Rechecked

A política de transporte agora falha fechada em `app/security/database_urls.py`: host remoto exige `sslmode=verify-full` e `sslrootcert`; parâmetros duplicados são rejeitados; loopback inseguro depende de opt-in explícito e os construtores de produção permanecem `False`. Router, administração e frota chamam o mesmo validador antes de `create_engine`. `tests/backend/test_database_urls.py`, `test_tenant_router.py`, `test_admin.py` e `test_fleet.py` passaram; a mutação que aceitou `sslmode=require` foi morta.

## Edge Cases

| Edge case | Evidence | Result |
| --------- | -------- | ------ |
| Slug host externo/barra/caractere/reservado/>63 é rejeitado | `tests/backend/test_schemas.py:256-257`; `tests/ui-prototype.spec.cjs:436-441` | ✅ |
| Cookie ausente não inventa header; cookie malformado/expirado/revogado/desconhecido retorna 401 e é apagado em toda superfície | APIs/dependency passam em `tests/backend/test_auth.py:164-207` e `tests/backend/test_auth_api.py:247-268`; prova independente em `GET /cliente-a` com cookie inválido retornou `401`, `Set-Cookie: None` | ❌ GAP em `/{slug}` |
| Throttle concorrente não ultrapassa limite | `tests/backend/test_control_repository.py:216-218`; `tests/backend/test_auth_service.py:319-321` | ✅ |
| Saves concorrentes conflitam por versão | suíte backend completa; `tests/backend/test_workspace_service.py` cobre conflito de versão | ✅ |
| Referência ausente reverte transação | `tests/backend/test_schemas.py:103-105`; testes transacionais do workspace | ✅ |
| RLS sem contexto retorna zero/erro | `tests/backend/test_tenant_migration_security.py:214,245-247` | ✅ |
| Dois tenants no mesmo perfil são detectados | `tests/backend/test_tenant_router.py:248-254` | ✅ |
| Falha de pool afeta só um tenant | `tests/backend/test_tenant_router.py:302-307,393-396` | ✅ |
| Wheel Argon2 ausente falha antes do bundle | `tests/backend/test_windows_multitenant_bundle.py:55-74` | ✅ |
| Inconsistência aborta antes de ativar | `tests/backend/test_admin.py:211-222,271-293` | ✅ |

## Discrimination Sensor

As mutações válidas foram aplicadas somente no worktree temporário `D:\Develop_CRM_Project_verifier_sensor_r2`, restauradas individualmente e o worktree foi removido. O porcelain do principal antes/depois permaneceu restrito aos untracked conhecidos.

| # | Mutation focused on corrections | Corrective test that killed it | Result |
| - | ------------------------------- | ------------------------------ | ------ |
| M1 | `auth_version += 1` → `+= 0` em mudança de perfil/status | `test_access_change_increments_auth_version_once_and_queues_revocation` (3 falhas) | ✅ Killed |
| M2 | Desabilita revogação após commit | `test_committed_access_changes_revoke_every_changed_user_session` | ✅ Killed |
| M3 | Aceita TLS remoto `sslmode=require` | `test_remote_database_requires_verify_full_and_root_ca` | ✅ Killed |
| M4 | Identity mismatch registrado como routing genérico | `test_swapped_profile_is_rejected_before_business_sql` | ✅ Killed |
| M5 | Não expira cookie inválido nas dependências/APIs | 7 casos malformed/unknown/expired/revoked | ✅ Killed |
| M6 | Inventa expiração quando cookie está ausente | `test_missing_cookie_is_401_without_auth_lookup` | ✅ Killed |
| M7 | Remove `no-store` das respostas `/api/auth` | `test_login_sets_only_hardened_cookie_and_never_returns_token` | ✅ Killed |

**Sensor depth:** P0-full manual, 7 mutações válidas focadas em T28-T32. Quatro invocações preparatórias com seletor/âncora/basetemp incorretos foram descartadas e repetidas corretamente; não contam como kill.
**Sensor verdict:** 7/7 killed, 0 survived. PASS ✅

## Gate Check

- **Build:** `python -m compileall -q app migrations migrations_control`; compatibility; Compose; backend; browser; runbook; Apache.
- **Gate totals:** 529 backend passed, 0 failed, 0 skipped; 93 browser passed, 0 failed; Python 3.11 contract 27/27; runbook 41/41; Apache 32/32; Compose válido.
- **Warnings:** 2 (Starlette deprecation e Pydantic alias), sem falha.
- **Before feature:** 97 backend e 69 browser.
- **After corrections:** 529 backend e 93 browser.
- **Delta from baseline:** +432 backend, +24 browser.
- **Structural validators after report:** `validate_spec` 0/0; `validate_tasks --strict` 0/0; `validate_state` 1 erro esperado porque o veredito é FAIL e a feature permanece aberta.

## Code Quality

| Principle | Status |
| --------- | ------ |
| Minimum/surgical code and no unrelated scope | ✅ |
| Physical database isolation, explicit workspace and forced RLS | ✅ |
| Session/cookie core and role policy | ⚠️ Revogação completa; limpeza ainda falta em `/{slug}` |
| Redacted security observability | ✅ Revogação, routing/identity e 401/403 cobertos |
| Remote database TLS contract | ✅ `verify-full` + CA; loopback somente opt-in |
| Spec-anchored outcome check | ❌ 50/50 ACs, mas um edge transversal ainda falha |
| Every in-scope test is claimed | ✅ |
| Documented guidelines | ✅ `pyproject.toml`, `README.md`, feature design/tasks |

## Interactive UAT

Não executado. A feature é user-facing, mas o protocolo para no gate automatizado FAIL. O UAT de locator/login/logout/identidade deverá ocorrer após corrigir e reverificar os gaps.

## Fix Plan

### Fix 1: Expirar cookie inválido também em `GET /{slug}`

- **Root cause:** `tenant_shell` em `app/main.py` captura `AuthenticationError` e cria `_error(401, ...)` diretamente; esse caminho não reutiliza `_unauthenticated_error`/header endurecido do resolver.
- **Corrective test:** no factory/API test, chamar `GET /cliente-a` com cookie malformado e com gateway simulando unknown/expired/revoked; exigir `401` e `Set-Cookie` com `Max-Age=0`, `Expires`, `Secure`, `HttpOnly`, `SameSite=Strict`, `Path=/` e sem `Domain`. Chamar sem cookie e exigir `200` da tela de login sem `Set-Cookie`.
- **Fix:** extrair uma única rotina pública de expiração/endurecimento para todos os caminhos HTTP que rejeitam cookie recebido, preservando o comportamento público/session-aware sem cookie.
- **Priority:** Major; bloqueia PASS/T27.

Os gaps anteriores de revogação, TLS, auditoria, no-store e checklist estão encerrados por evidência nesta rodada.

## Requirement Traceability Update

| Requirement | Previous | Verification result |
| ----------- | -------- | ------------------- |
| MT-01 | Implementing | ✅ Evidence complete |
| MT-02 | Implementing | ✅ Acceptance criteria evidenced; shared cookie edge remains under MT-07 |
| MT-03 | Implementing | ✅ Evidence complete, including remote TLS |
| MT-04 | Implementing | ✅ Evidence complete |
| MT-05 | Implementing | ✅ Evidence complete |
| MT-06 | Implementing | ✅ Evidence complete |
| MT-07 | Implementing | ❌ Needs Fix (invalid-cookie edge) |

`spec.md` não foi marcado Verified e T27 permanece In Progress.

## Summary

**Overall:** ❌ Not Ready

**Spec-anchored check:** 50/50 listed ACs matched; 1 failed cross-cutting edge case (`GET /{slug}` invalid-cookie cleanup).
**Sensor:** 7/7 valid mutations killed; 0 survived.
**Gate:** 529 backend + 93 browser passed; compatibility 27/27, runbook 41/41 and Apache 32/32.

Os seis gaps da primeira rodada foram corrigidos nas APIs, dependências e operação. A feature ainda não pode ser concluída porque a rota session-aware `GET /{slug}` não apaga um cookie inválido ao responder 401. Após corrigir e adicionar o teste exato, é necessário repetir o gate proporcional, a verificação independente e o UAT.
