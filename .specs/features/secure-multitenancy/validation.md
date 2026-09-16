# Multiempresa Seguro Validation

## Validation: Multiempresa Seguro - FAIL ❌

**Verdict:** FAIL ❌
**Date:** 2026-09-16
**Spec:** `.specs/features/secure-multitenancy/spec.md`
**Diff range:** `6962ca5..526ac18`
**Verifier:** independent sub-agent (author ≠ verifier)

---

## Task Completion

| Task | Status | Notes |
| ---- | ------ | ----- |
| T1-T7 | ⚠️ Partial artifact | Commits e gates existem, mas os itens `Done when` permanecem desmarcados em `tasks.md`. |
| T8-T26 | ✅ Done | Commits atômicos e evidência de gate presentes. |
| T27 | ⚠️ In Progress | Documentação e gate passaram; a verificação independente encontrou gaps. |

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
| MT-02.7 | Mudança de senha, perfil, status ou auth_version revoga sessões anteriores | Senha está coberta em `tests/backend/test_admin.py:313-318`; porém `app/repositories/workspace.py:273-274` altera perfil/status sem incrementar `auth_version` nem revogar sessões | ❌ GAP |
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
| MT-06.1 | Login/logout/bloqueio/revogação/misrouting/negação geram auditoria redigida | Só login/logout estão instrumentados em `app/services/auth.py:202,316,397`; não há eventos para revogação, identity mismatch/roteamento ou 401/403 de autorização | ❌ GAP |
| MT-06.2 | API protegida sem sessão retorna 401 estável sem workspace | `tests/backend/test_auth_api.py:264-266` | ✅ PASS |
| MT-06.3 | Perfil insuficiente retorna 403 estável sem oráculo | `tests/backend/test_auth_api.py:284-286` | ✅ PASS |
| MT-06.4 | Login/logout/session/workspace sempre enviam no-store | Sessão/logout/workspace: `tests/backend/test_auth_api.py:231,244`, `tests/backend/test_api.py:168`; nenhum teste afirma `no-store` no login bem-sucedido | ❌ COVERAGE GAP |
| MT-06.5 | Tenant não ativo/incompatível nega login e sessões | `tests/backend/test_auth_service.py:177-179,238-248`; `tests/backend/test_tenant_router.py:269-286` | ✅ PASS |
| MT-06.6 | Preflight relata conectividade/identidade/revisão sem segredo | `tests/backend/test_fleet.py:123-158,185-197` | ✅ PASS |
| MT-06.7 | Migração exige seleção/backup/confirmação e isola resultados | `tests/backend/test_fleet.py:213-221,234-260` | ✅ PASS |

**Status:** 47/50 critérios com evidência suficiente; 2 gaps funcionais e 1 gap de cobertura.

## Confirmed Security Decision Gap

O requisito confirmado de TLS com validação de certificado para PostgreSQL remoto não é imposto pelo runtime. `app/tenant_database.py:151-159`, `app/admin_cli.py:117,146` e `app/fleet.py:85-90` aceitam a string de conexão do segredo e configuram apenas timeout/pool. Não há validação de `sslmode=verify-full`, CA/hostname ou equivalente. A documentação menciona TLS, mas nenhum teste impede registrar ou abrir um DSN remoto sem TLS.

## Edge Cases

| Edge case | Evidence | Result |
| --------- | -------- | ------ |
| Slug host externo/barra/caractere/reservado/>63 é rejeitado | `tests/backend/test_schemas.py:256-257`; `tests/ui-prototype.spec.cjs:436-441` | ✅ |
| Cookie ausente/malformado/expirado/revogado/desconhecido retorna 401 e é apagado | `tests/backend/test_auth.py:114-142` cobre 401, mas não há `Set-Cookie` de expiração; `app/auth.py:98-100` apenas lança erro | ❌ |
| Throttle concorrente não ultrapassa limite | `tests/backend/test_control_repository.py:216-218`; `tests/backend/test_auth_service.py:319-321` | ✅ |
| Saves concorrentes conflitam por versão | suíte backend completa; `tests/backend/test_workspace_service.py` cobre conflito de versão | ✅ |
| Referência ausente reverte transação | `tests/backend/test_schemas.py:103-105`; testes transacionais do workspace | ✅ |
| RLS sem contexto retorna zero/erro | `tests/backend/test_tenant_migration_security.py:214,245-247` | ✅ |
| Dois tenants no mesmo perfil são detectados | `tests/backend/test_tenant_router.py:248-254` | ✅ |
| Falha de pool afeta só um tenant | `tests/backend/test_tenant_router.py:302-307,393-396` | ✅ |
| Wheel Argon2 ausente falha antes do bundle | `tests/backend/test_windows_multitenant_bundle.py:55-74` | ✅ |
| Inconsistência aborta antes de ativar | `tests/backend/test_admin.py:211-222,271-293` | ✅ |

## Discrimination Sensor

As mutações foram aplicadas apenas no worktree temporário `D:\Develop_CRM_Project_verifier_sensor_20260916_01`, removido após os testes. O porcelain do worktree principal antes/depois permaneceu igual.

| # | File:line | Mutation | Killed? |
| - | --------- | -------- | ------- |
| M1 | `app/security/passwords.py:34` | Argon2id → Argon2i | ✅ `test_security.py` |
| M2 | `app/main.py:363,392` | Cookie `Secure=True` → `False` | ✅ `test_auth_api.py` |
| M3 | `app/tenant_database.py:191` | Bypass do tenant identity guard | ✅ `test_tenant_router.py` |
| M4 | `app/policies.py:60` | Ações administrativas liberadas a todos | ✅ `test_authorization.py` |
| M5 | `migrations/versions/a4c9d2e7f1b6_secure_multitenancy_tenant_database.py:137` | Remove FORCE RLS | ✅ `test_tenant_migration_security.py` |
| M6 | `app/repositories/workspace.py:85` | Reintroduz fallback `workspace=default` | ✅ `test_repository_tenant_scope.py` |
| M7 | `app/services/auth.py:28` | Limite IP 30 → 31 | ✅ `test_auth_service.py` |
| M8 | `app/security/passwords.py:25` | TTL ocioso 30 → 31 minutos | ✅ `test_security.py` e `test_auth_service.py` |

**Sensor depth:** P0-full manual, 8 mutações.
**Sensor verdict:** 8/8 killed, 0 survived. PASS ✅

## Gate Check

- **Build:** `python -m compileall -q app migrations migrations_control`; compatibility; Compose; backend; browser; runbook; Apache.
- **Gate totals:** 503 backend passed, 0 failed, 0 skipped; 93 browser passed, 0 failed; Python 3.11 contract 26/26; runbook 41/41; Apache 32/32; Compose válido.
- **Warnings:** 2 (Starlette deprecation e Pydantic alias), sem falha.
- **Before feature:** 97 backend e 69 browser.
- **After feature:** 503 backend e 93 browser.
- **Delta:** +406 backend, +24 browser.
- **Structural validators:** `validate_spec` 0/0; `validate_tasks` 0/0.

## Code Quality

| Principle | Status |
| --------- | ------ |
| Minimum/surgical code and no unrelated scope | ✅ |
| Physical database isolation, explicit workspace and forced RLS | ✅ |
| Session/cookie core and role policy | ⚠️ Revocation and invalid-cookie cleanup incomplete |
| Redacted security observability | ❌ Missing required event classes |
| Remote database TLS contract | ❌ Not enforced |
| Spec-anchored outcome check | ❌ 47/50; one edge failure |
| Every in-scope test is claimed | ✅ |
| Documented guidelines | ✅ `pyproject.toml`, `README.md`, feature design/tasks |

## Interactive UAT

Não executado. A feature é user-facing, mas o protocolo para no gate automatizado FAIL. O UAT de locator/login/logout/identidade deverá ocorrer após corrigir e reverificar os gaps.

## Fix Plans

### Fix 1: Expirar cookie inválido em toda resposta 401 de sessão

- **Root cause:** o resolver lança `HTTPException` sem permitir que a resposta expire o cookie recebido.
- **Fix task:** centralizar a resposta unauthenticated com `Set-Cookie` de expiração e as mesmas flags `__Host-`; cobrir cookie malformado, desconhecido, expirado e revogado.
- **Priority:** Major.

### Fix 2: Revogar sessões em mudanças de perfil/status

- **Root cause:** o reconciliador atualiza `CrmUser.role` e `status`, mas não incrementa `auth_version` nem aciona a revogação central.
- **Fix task:** detectar mudanças de estado de autenticação, incrementar `auth_version`, revogar todas as sessões do tenant/user e testar upgrade/downgrade/inativação sem janela de autoridade antiga.
- **Priority:** Blocker.

### Fix 3: Completar auditoria de segurança

- **Root cause:** somente login/logout/provisioning escrevem `security_events`.
- **Fix task:** emitir eventos redigidos para revogação, identity mismatch/falha de roteamento e negações 401/403, com tenant/user quando conhecidos e digest de correlação; testar ausência de token, senha e DSN.
- **Priority:** Major.

### Fix 4: Impor TLS verificado para PostgreSQL remoto

- **Root cause:** router/admin/fleet aceitam qualquer DSN resolvido pelo secret provider.
- **Fix task:** validar perfil de conexão remoto antes de criar engine, exigir certificado/hostname verificado e permitir somente o modo local explicitamente configurado para desenvolvimento/testes.
- **Priority:** Blocker.

### Fix 5: Fechar cobertura de `no-store`

- **Root cause:** o middleware implementa o header, mas o login bem-sucedido não tem asserção spec-derived.
- **Fix task:** adicionar asserção de `Cache-Control: no-store` para login bem-sucedido e manter as existentes para logout/session/workspace.
- **Priority:** Minor.

### Fix 6: Reconciliar checklist T1-T7

- **Root cause:** `Status: Complete` diverge dos itens `Done when` desmarcados.
- **Fix task:** confirmar evidência já existente e corrigir somente o estado documental, sem reescrever commits.
- **Priority:** Minor.

## Requirement Traceability Update

| Requirement | Previous | Verification result |
| ----------- | -------- | ------------------- |
| MT-01 | Implementing | ✅ Evidence complete |
| MT-02 | Implementing | ❌ Needs Fix (revocation) |
| MT-03 | Implementing | ❌ Needs Fix (confirmed TLS decision) |
| MT-04 | Implementing | ✅ Evidence complete |
| MT-05 | Implementing | ✅ Evidence complete |
| MT-06 | Implementing | ❌ Needs Fix (audit/no-store coverage) |
| MT-07 | Implementing | ❌ Needs Fix (invalid-cookie edge) |

`spec.md` não foi marcado Verified e T27 permanece In Progress.

## Summary

**Overall:** ❌ Not Ready

**Spec-anchored check:** 47/50 ACs matched; 2 functional gaps, 1 coverage gap, 1 failed edge and 1 confirmed security-decision gap.
**Sensor:** 8/8 mutations killed.
**Gate:** 503 backend + 93 browser passed.

O isolamento físico, o guard de identidade, o workspace explícito, a RLS, Argon2id, o cookie endurecido, as políticas de perfil, o provisionamento e a frota estão demonstrados. A feature não pode ser concluída até corrigir revogação por perfil/status, limpeza do cookie inválido, auditoria obrigatória e TLS remoto, depois repetir a verificação independente e o UAT.
