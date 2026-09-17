# Multiempresa Seguro Validation

## Validation: Multiempresa Seguro - PASS ✅

**Verdict:** PASS ✅
**Date:** 2026-09-17 (independent revalidation T37)
**Spec:** `.specs/features/secure-multitenancy/spec.md`
**Diff range:** `b8d677d..b493f22` (correction T37); implementation lineage remains `6962ca5..b493f22`
**Verifier:** independent sub-agent (author ≠ verifier)

---

## Task Completion

| Task | Status | Notes |
| ---- | ------ | ----- |
| T1-T26 | ✅ Done | Commits, checklists reconciliados e evidência de gate presentes. |
| T27 | ✅ Done | Documentação, full gate, Fresh Verifier e validate_state concluídos. |
| T28-T35 | ✅ Done | Correções de revogação, TLS, auditoria, cookies, no-store, tenant shell e opt-in local estrito verificadas. |
| T36-T37 | ✅ Done | Factory e teste persistido de lifecycle verificados; o mutante de shutdown/dispose foi morto. |

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

**Status:** ✅ 50/50 critérios funcionais e todos os edge cases com evidência suficiente.

## Confirmed Security Decisions Rechecked

A política de transporte agora falha fechada em `app/security/database_urls.py`: host remoto exige `sslmode=verify-full` e `sslrootcert`; parâmetros duplicados são rejeitados; loopback inseguro depende de opt-in explícito e somente o literal `SMART_CRM_ALLOW_INSECURE_TENANT_LOOPBACK=1` o habilita nos caminhos reais. Router, administração e frota chamam o mesmo parser/validador antes de `create_engine`. `tests/backend/test_database_urls.py`, `test_tenant_router.py`, `test_admin.py`, `test_server.py` e `test_fleet.py` passaram; as mutações que relaxaram o literal, removeram consumidores ou aceitaram host remoto foram mortas.

## Edge Cases

| Edge case | Evidence | Result |
| --------- | -------- | ------ |
| Slug host externo/barra/caractere/reservado/>63 é rejeitado | `tests/backend/test_schemas.py:256-257`; `tests/ui-prototype.spec.cjs:436-441` | ✅ |
| Cookie ausente não inventa header; cookie malformado/expirado/revogado/desconhecido retorna 401 e é apagado em toda superfície | `tests/backend/test_auth_api.py:181-211` prova `/{slug}`: sem cookie 200/no header e quatro estados inválidos com 401 + flags; `tests/backend/test_auth.py:164-207` e `test_auth_api.py:271-296` cobrem dependency/API | ✅ |
| Throttle concorrente não ultrapassa limite | `tests/backend/test_control_repository.py:216-218`; `tests/backend/test_auth_service.py:319-321` | ✅ |
| Saves concorrentes conflitam por versão | suíte backend completa; `tests/backend/test_workspace_service.py` cobre conflito de versão | ✅ |
| Referência ausente reverte transação | `tests/backend/test_schemas.py:103-105`; testes transacionais do workspace | ✅ |
| RLS sem contexto retorna zero/erro | `tests/backend/test_tenant_migration_security.py:214,245-247` | ✅ |
| Dois tenants no mesmo perfil são detectados | `tests/backend/test_tenant_router.py:248-254` | ✅ |
| Falha de pool afeta só um tenant | `tests/backend/test_tenant_router.py:302-307,393-396` | ✅ |
| Wheel Argon2 ausente falha antes do bundle | `tests/backend/test_windows_multitenant_bundle.py:55-74` | ✅ |
| Inconsistência aborta antes de ativar | `tests/backend/test_admin.py:211-222,271-293` | ✅ |

## Discrimination Sensor

As mutações foram aplicadas somente no worktree temporário `D:\Develop_CRM_Project_verifier_sensor_r3`, restauradas individualmente e o worktree foi removido. O principal permaneceu restrito aos untracked conhecidos.

| # | Mutation focused on final correction and retained controls | Corrective test that killed it | Result |
| - | --------------------------------------------------------- | ------------------------------ | ------ |
| M1 | Tenant shell volta a responder 401 sem expirar cookie | `test_tenant_shell_expires_invalid_received_cookie` (4 falhas) | ✅ Killed |
| M2 | Helper compartilhado deixa de expirar cookie recebido | Matrizes tenant shell + auth API (8 falhas) | ✅ Killed |
| M3 | Helper inventa `Set-Cookie` quando cookie está ausente | `test_missing_cookie_is_401_without_auth_lookup` | ✅ Killed |
| M4 | `auth_version += 1` → `+= 0` em perfil/status | `test_access_change_increments_auth_version_once_and_queues_revocation` (3 falhas) | ✅ Killed |
| M5 | TLS remoto aceita `sslmode=require` | `test_remote_database_requires_verify_full_and_root_ca` | ✅ Killed |
| M6 | Identity mismatch é auditado como routing genérico | `test_swapped_profile_is_rejected_before_business_sql` | ✅ Killed |

**Sensor depth:** P0-full manual, 6 mutações válidas, incluindo a remoção exata do fix T34 e controles críticos anteriores.
**Sensor verdict:** 6/6 killed, 0 survived. PASS ✅

## Gate Check

- **Build:** `python -m compileall -q app migrations migrations_control`; compatibility; Compose; backend; browser; runbook; Apache.
- **Gate totals:** 556 backend passed, 0 failed, 0 skipped; 93 browser passed, 0 failed; Python 3.11 contract 27/27; runbook 41/41; Apache 32/32; Compose válido.
- **Warnings:** 2 (Starlette deprecation e Pydantic alias), sem falha.
- **Before feature:** 97 backend e 69 browser.
- **After corrections/extensions:** 556 backend e 93 browser.
- **Delta from baseline:** +459 backend, +24 browser.
- **Structural validators after T37 closure:** `validate_spec` 0/0; `validate_tasks --strict` 0/0; `validate_state` 0/0.

## Code Quality

| Principle | Status |
| --------- | ------ |
| Minimum/surgical code and no unrelated scope | ✅ |
| Physical database isolation, explicit workspace and forced RLS | ✅ |
| Session/cookie core and role policy | ✅ Revogação e limpeza uniformes em dependency, API e tenant shell |
| Redacted security observability | ✅ Revogação, routing/identity e 401/403 cobertos |
| Remote database TLS contract | ✅ `verify-full` + CA; loopback somente opt-in |
| Spec-anchored outcome check | ✅ 50/50 ACs e todos os edge cases |
| Every in-scope test is claimed | ✅ |
| Documented guidelines | ✅ `pyproject.toml`, `README.md`, feature design/tasks |

## Interactive UAT

O fluxo user-facing foi exercitado localmente por 93 cenários browser, incluindo locator, rota tenant, login, sessão, identidade imutável, cache namespaced e logout. O UAT humano no ambiente de destino permanece gate operacional do cutover e não foi executado porque deploy/produção estão fora do escopo autorizado desta validação.

## Resolved Gap

T34 centralizou a rejeição da tenant shell no mesmo `unauthenticated_error(request)` usado pelas APIs. A matriz independente confirmou: sem cookie → 200/no `Set-Cookie`; malformed/unknown/expired/revoked → 401 e cookie `__Host-` expirado com todos os atributos endurecidos. Não restaram gaps de implementação na rodada T34.

## Post-PASS Extension Verification — T35

| T35 criterion | Independent evidence | Result |
| ------------- | -------------------- | ------ |
| Ausente ou qualquer valor diferente de `1` mantém deny | `app/security/database_urls.py:14,23-29`; `tests/backend/test_admin.py:150-164`; `tests/backend/test_server.py:123-136`; `tests/backend/test_fleet.py:121-146` | ✅ PASS |
| Literal `1` habilita somente loopback | `app/security/database_urls.py:53-55`; `tests/backend/test_admin.py:166-174`; `tests/backend/test_database_urls.py:58-63` | ✅ PASS |
| Host remoto continua exigindo `verify-full` + CA | `app/security/database_urls.py:53`; `tests/backend/test_admin.py:177-190`; `tests/backend/test_fleet.py:151-172` | ✅ PASS |
| Admin, server router e fleet default propagam o parser central | `app/admin_cli.py:449`; `app/server.py:86`; `app/fleet.py:62-70,98`; testes targeted T35 84/84 | ✅ PASS |
| README limita ao setup local e remove a variável ao fim | `README.md:84,92,104`; `tests/backend/test_readme_multidatabase.py:60-66` | ✅ PASS |

O gate completo após T35 passou com 554 testes backend, 93 browser, compatibilidade Python 27/27, runbook 41/41, Apache 32/32, Compose válido e `compileall` limpo. O sensor independente em worktree scratch matou 7/7 mutações: parser permissivo, literal trocado, propagação removida em server/admin/fleet, host remoto liberado pelo opt-in e cleanup do README removido. O worktree scratch foi restaurado e removido; nenhum arquivo rastreado do principal foi alterado pelo sensor.

## Post-PASS Extension Verification — T36/T37

| T36 criterion | Independent evidence | Result |
| ------------- | -------------------- | ------ |
| Target extraído do README resolve pelo importador real do Uvicorn | `tests/backend/test_server.py:71-87` usa `import_from_string(target)` e compara o target exato | ✅ PASS |
| Factory é zero-arg e retorna a aplicação central | `app/server.py:134-137`; `tests/backend/test_server.py:84-88` chama `factory()` e verifica `central_runtime` | ✅ PASS |
| Wrapper delega ao bootstrap/create_app sem bypass | `app/server.py:137`; `tests/backend/test_server.py:78-89` verifica uma chamada ao bootstrap e o runtime retornado | ✅ PASS |
| Control plane inválido falha fechado | `tests/backend/test_server.py:117-139` verifica mensagem genérica e descarte em falha; sonda independente chamou o factory sem configuração e recebeu `central runtime unavailable` | ✅ PASS |
| Shutdown preserva `CentralRuntime.dispose()` para router e control | `tests/backend/test_server.py:92-114` resolve o target público, entra/sai de `TestClient(factory())`, mantém ambos em zero durante uso e afirma separadamente uma chamada + estado disposed após shutdown | ✅ PASS |

### T36 Initial Discrimination Sensor (historical FAIL)

As mutações foram aplicadas somente no worktree temporário `D:\Develop_CRM_Project_verifier_sensor_t36`, restauradas individualmente e o worktree foi removido. O porcelain do principal permaneceu igual ao baseline.

| # | Mutation | Corrective test/result | Result |
| - | -------- | ---------------------- | ------ |
| M1 | Remove o atributo `create_central_app` | Importador real não encontra o atributo | ✅ Killed |
| M2 | Faz o target do README divergir para `app.server:create_app` | Testes de server e contrato README falham | ✅ Killed |
| M3 | Wrapper deixa de chamar `create_app` e retorna FastAPI vazio | Estado `central_runtime` ausente | ✅ Killed |
| M4 | Factory passa a exigir parâmetro | Chamada zero-arg levanta `TypeError` | ✅ Killed |
| M5 | Wrapper ignora bootstrap e chama `create_http_app` diretamente | Estado/runtime e chamada de bootstrap ausentes | ✅ Killed |
| M6 | Remove o handler de shutdown/dispose | `tests/backend/test_server.py`: 17 passed | ❌ Survived |

**Sensor verdict:** 5/6 killed, 1 survived. FAIL ❌

### T37 Revalidation Sensor — PASS

| # | Mutation | Assertion that killed it | Result |
| - | -------- | ------------------------ | ------ |
| R1 | Remove exatamente `application.add_event_handler("shutdown", active_runtime.dispose)` | `tests/backend/test_server.py:111` detecta `router.dispose_calls == 0` | ✅ Killed |
| R2 | Remove somente `tenant_router.dispose()` | `tests/backend/test_server.py:111,113` | ✅ Killed |
| R3 | Remove somente `control_database.dispose()` | `tests/backend/test_server.py:112,114` | ✅ Killed |
| R4 | Move dispose de shutdown para startup | `tests/backend/test_server.py:108-109` exige zero durante uso | ✅ Killed |
| R5 | Bypassa runtime central e chama `create_http_app()` | `tests/backend/test_server.py:107` exige o runtime injetado | ✅ Killed |

**Sensor verdict:** 5/5 killed, 0 survived. PASS ✅

T37 fechou o único gap do relatório `b8d677d`: o teste persistido usa o alvo extraído do README, o importador real do Uvicorn, a factory pública e o lifespan do TestClient. Router e control são verificados separadamente antes e depois do shutdown.

## Requirement Traceability Update

| Requirement | Previous status | T37 verification result |
| ----------- | --------------- | ----------------------- |
| MT-01 | Verified | ✅ Retained |
| MT-02 | Verified | ✅ Retained |
| MT-03 | Verified | ✅ Retained |
| MT-04 | Verified | ✅ Retained |
| MT-05 | Implementing | ✅ Verified |
| MT-06 | Implementing | ✅ Verified |
| MT-07 | Verified | ✅ Retained |

`spec.md` volta a marcar MT-05 e MT-06 como Verified; `tasks.md` fecha após a revalidação matar o antigo M6.

## Summary

**Overall:** ✅ Ready

**Spec-anchored check:** 50/50 listed ACs and every listed edge matched.
**Sensor:** T37 matou 5/5; o antigo M6 agora é discriminado.
**Gate:** 556 backend + 93 browser passed; compatibility 27/27, runbook 41/41 and Apache 32/32.

O factory resolve pelo importador real, é zero-arg, delega ao bootstrap e falha fechado. T37 protege o lifecycle de shutdown com asserções independentes para router e control; o mutante antes sobrevivente agora morre. Nenhum gap permanece nesta revalidação.
