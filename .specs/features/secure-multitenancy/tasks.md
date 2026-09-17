# Multiempresa Seguro Tasks

## Execution Protocol (MANDATORY -- do not skip)

Implement these tasks with the tlc-spec-driven skill and follow its Execute flow and Critical Rules. The skill governs per-task gates, atomic Conventional Commits, the sub-agent offer, independent Verifier and discrimination sensor. If the skill cannot be activated, STOP.

**Design:** .specs/features/secure-multitenancy/design.md
**Status:** In Progress

**Baseline evidence:** 97 backend tests passed and all 20 browser groups covering 69 scenarios passed before T1. Pytest gates use --basetemp .pytest-tmp because the global Windows Temp pytest directory has a broken ACL.

## Test Coverage Matrix

> Generated from pyproject.toml, package.json, README.md, current tests and the spec. Guidelines found there and in existing compatibility/deployment verifiers. No AGENTS.md, lint command or numeric coverage gate was found; strong defaults apply.

| Code Layer | Required Test Type | Coverage Expectation | Location Pattern | Run Command |
| ---------- | ------------------ | -------------------- | ---------------- | ----------- |
| Control models/repository | PostgreSQL integration | Directory, sessions, throttle locks, audit redaction, expiry and cleanup | tests/backend/test_control_*.py | python -m pytest -p no:cacheprovider --basetemp .pytest-tmp tests/backend/test_control_models.py tests/backend/test_control_repository.py -q |
| Secret provider/router | unit + PostgreSQL integration | DPAPI contract, trusted-only routing, identity mismatch, two databases, pools and no fallback | tests/backend/test_secrets.py, tests/backend/test_tenant_router.py | python -m pytest -p no:cacheprovider --basetemp .pytest-tmp tests/backend/test_secrets.py tests/backend/test_tenant_router.py -q |
| Password/session/auth | unit + integration | Every MT-01/MT-02 branch, dummy hash, expiry, revocation, concurrency and outage | tests/backend/test_security.py, tests/backend/test_auth_service.py | python -m pytest -p no:cacheprovider --basetemp .pytest-tmp tests/backend/test_security.py tests/backend/test_auth_service.py -q |
| Authorization policy | unit | Complete role/action/record matrix | tests/backend/test_authorization.py | python -m pytest -p no:cacheprovider --basetemp .pytest-tmp tests/backend/test_authorization.py -q |
| Tenant repository | PostgreSQL integration | Two databases, identical IDs, all mutations/restores and forced RLS | tests/backend/test_repository.py, tests/backend/test_repository_tenant_scope.py | python -m pytest -p no:cacheprovider --basetemp .pytest-tmp tests/backend/test_repository.py tests/backend/test_repository_tenant_scope.py -q |
| Workspace service/auth API | unit + PostgreSQL + API integration | Projection/merge for every role plus happy/anonymous/forbidden/forged/CSRF/version/503 paths | tests/backend/test_workspace_authorization.py, tests/backend/test_workspace_service.py, tests/backend/test_api.py, tests/backend/test_auth_api.py | python -m pytest -p no:cacheprovider --basetemp .pytest-tmp tests/backend/test_workspace_authorization.py tests/backend/test_workspace_service.py tests/backend/test_api.py tests/backend/test_auth_api.py -q |
| Models/schemas/migrations | unit + PostgreSQL integration | Both lineages, identity, preservation, RLS and downgrade | tests/backend/test_models.py, tests/backend/test_schemas.py, tests/backend/test_migrations.py | python -m pytest -p no:cacheprovider --basetemp .pytest-tmp tests/backend/test_models.py tests/backend/test_schemas.py tests/backend/test_migrations.py -q |
| Admin/fleet | integration | Activation, checkpoints/resume, hidden secrets, preflight, selection and independent failures | tests/backend/test_admin.py, tests/backend/test_fleet.py | python -m pytest -p no:cacheprovider --basetemp .pytest-tmp tests/backend/test_admin.py tests/backend/test_fleet.py -q |
| Frontend route/auth/cache | browser e2e | Locator, login, cookie session, immutable profile, logout and namespaced preferences | tests/ui-prototype.spec.cjs | pnpm test |
| Windows/Apache/offline | contract + outcome | Env allowlist, secret placeholders, both migrations, wheels and no production mutation | tests/backend/test_manual_windows_pg11_*.py, scripts/verify_windows_*.py | python -m pytest -p no:cacheprovider --basetemp .pytest-tmp tests/backend/test_manual_windows_pg11_deployment.py tests/backend/test_manual_windows_pg11_outcomes.py -q |
| Dependency/config/docs | build/contract | Exact pins, Python 3.11 parse, Compose and documentation contracts | manifests and verifier scripts | Build gate only |

## Gate Check Commands

| Gate Level | When to Use | Command |
| ---------- | ----------- | ------- |
| Quick | Pure unit task | python -m pytest -p no:cacheprovider --basetemp .pytest-tmp TASK_TEST_FILE -q |
| Full | Repository, migration, API, CLI or browser | docker compose up -d postgres; python -m pytest -p no:cacheprovider --basetemp .pytest-tmp tests/backend -q; pnpm test |
| Build | Phase/config/deployment | python -m compileall -q app migrations migrations_control; python scripts/verify_python_compatibility.py; docker compose config --quiet; python -m pytest -p no:cacheprovider --basetemp .pytest-tmp tests/backend -q; pnpm test; python scripts/verify_windows_runbook_contract.py; python scripts/verify_windows_apache_contract.py |

The Build gate records totals and cannot fall below 91 backend functions and 69 browser scenarios plus tests added by completed tasks.

## Execution Plan

### Phase 1: Control plane and isolated database foundation

```
T1 → T2 → T3 → T4 → T5 → T6 → T7 → T8 → T9
```

### Phase 2: Authentication, authorization and protected workspace

```
T9 → T10 → T11 → T12 → T13 → T14 → T15 → T16 → T17
```

### Phase 3: Provisioning, fleet and browser integration

```
T17 → T18 → T19 → T20 → T21 → T22
```

### Phase 4: Offline Windows and operator contracts

```
T22 → T23 → T24 → T25 → T26 → T27
```

### Phase 5: Independent-validation corrections

```
T27 -> T28 -> T29 -> T30 -> T31 -> T32 -> T33
```

## Task Breakdown

### T1: Pin the Argon2 dependency

**Status:** Complete

**What:** Add an exact-pinned Argon2id-capable library for CPython 3.11 Windows x64.
**Where:** pyproject.toml
**Depends on:** None
**Reuses:** Existing exact-version convention.
**Requirement:** MT-01, MT-02, MT-05
**Tools:** MCP web for official package docs if needed; Skill tlc-spec-driven.

**Done when:**

- [ ] Version/runtime support are exact and compatibility has at least 1 new assertion.
- [ ] Build gate passes with recorded totals and no test deletion.

**Tests:** none for config; build/contract gate
**Gate:** build
**Commit:** build(auth): pin argon2 dependency

### T2: Align the offline runtime manifest

**Status:** Complete

**What:** Mirror the authentication dependency in runtime requirements.
**Where:** requirements-runtime.txt
**Depends on:** T1
**Reuses:** Existing wheel-only bundle input.
**Requirement:** MT-05
**Tools:** MCP NONE; Skill tlc-spec-driven.

**Done when:**

- [ ] Project/runtime pins match and parity has at least 1 drift assertion.
- [ ] Build gate passes.

**Tests:** none for config; build/contract gate
**Gate:** build
**Commit:** build(auth): align offline runtime dependency

### T3: Define control-plane models

**Status:** Complete

**What:** Model tenant directory, opaque sessions, throttles and redacted security events without user hashes/business data.
**Where:** app/control_models.py
**Depends on:** T2
**Reuses:** Existing SQLAlchemy 2 patterns.
**Requirement:** MT-01, MT-02, MT-05, MT-06
**Tools:** MCP NONE; Skill tlc-spec-driven.

**Done when:**

- [ ] Models/indexes match design and cannot store raw token, password, DSN or snapshot.
- [ ] Tests add at least 8 assertions for fields, uniqueness, states and secret exclusions.
- [ ] Full gate passes.

**Tests:** unit + PostgreSQL integration
**Gate:** full
**Commit:** feat(control): define tenant session models

### T4: Create the control Alembic lineage

**Status:** Complete

**What:** Add independent Alembic configuration and initial control migration.
**Where:** migrations_control/
**Depends on:** T3
**Reuses:** Existing migrations/env.py conventions without sharing version history.
**Requirement:** MT-02, MT-05, MT-06
**Tools:** MCP official Alembic docs if needed; Skill tlc-spec-driven.

**Done when:**

- [ ] Control upgrade/downgrade never creates business tables.
- [ ] Tests add at least 5 cases for upgrade, head, constraints, downgrade and lineage separation.
- [ ] Full gate passes.

**Tests:** PostgreSQL integration
**Gate:** full
**Commit:** feat(control): add independent migration lineage

### T5: Implement the server secret provider

**Status:** Complete

**What:** Provide DPAPI-backed connection secrets with test/development substitutes.
**Where:** app/security/secrets.py
**Depends on:** T4
**Reuses:** Environment loading and standard Windows APIs where viable.
**Requirement:** MT-03, MT-05, MT-06, MT-07
**Tools:** MCP web restricted to Microsoft DPAPI docs; Skill tlc-spec-driven.

**Done when:**

- [ ] Production ciphertext is service-identity-bound and only secret_ref crosses module boundaries.
- [ ] Unit tests add at least 8 cases for round-trip, wrong identity/corruption, redaction, missing ref and rotation.
- [ ] Quick gate passes.

**Tests:** unit
**Gate:** quick
**Commit:** feat(security): add tenant secret provider

### T6: Implement the control repository

**Status:** Complete

**What:** Add directory, central sessions, throttle locking, provisioning state and audit operations.
**Where:** app/control_database.py
**Depends on:** T5
**Reuses:** Existing transaction pattern.
**Requirement:** MT-01, MT-02, MT-05, MT-06, MT-07
**Tools:** MCP NONE; Skill tlc-spec-driven.

**Done when:**

- [ ] Control DSN is required with no fallback; session/throttle/state operations are transactional.
- [ ] Tests add at least 10 cases for concurrency, expiry, cleanup, duplicate slug, transitions and redaction.
- [ ] Full gate passes.

**Tests:** PostgreSQL integration
**Gate:** full
**Commit:** feat(control): implement session directory repository

### T7: Add tenant identity and user auth fields

**Status:** Complete

**What:** Extend business ORM with singleton tenant identity, missing workspace markers and secure user auth/version fields.
**Execution note:** T7 criou o esqueleto mínimo da revisão tenant com colunas e marcadores. T8 amplia a mesma revisão com backfill, preservação e RLS; essa divisão mantém cada commit executável sem fundir as duas tarefas.

**Where:** app/models.py
**Depends on:** T6
**Reuses:** Existing entities/workspace keys.
**Requirement:** MT-01, MT-02, MT-03, MT-05
**Tools:** MCP NONE; Skill tlc-spec-driven.

**Done when:**

- [ ] Identity binds control UUID to workspace; legacy auth is disabled with nullable hash.
- [ ] Tests add at least 8 assertions for singleton, uniqueness, version and child scope.
- [ ] Full gate passes.

**Tests:** unit + PostgreSQL integration
**Gate:** full
**Commit:** feat(tenant): add database identity and user credentials

### T8: Migrate the current database as a tenant

**Status:** Complete

**What:** Preserve default data, backfill child scopes and enable forced RLS in the tenant lineage.
**Execution note:** T8 ampliou a revisão tenant iniciada em T7 com preflight, backfill, invariantes NOT NULL, RLS forçado e downgrade. O binding de escrita dos quatro filhos em WorkspaceRepository é a compatibilidade mínima exigida pelas novas invariantes; filtros e lookups permanecem reservados a T16.
**Where:** migrations/versions/secure_multitenancy_tenant_database.py
**Depends on:** T7
**Reuses:** Existing migration fixture/named constraints.
**Requirement:** MT-03, MT-05, MT-07
**Tools:** MCP official PostgreSQL 11 docs; Skill tlc-spec-driven.

**Done when:**

- [x] Upgrade preserves default, row counts, checksums and relationships.
- [x] Every tenant table has forced USING/WITH CHECK RLS after verified backfill.
- [x] Tests add at least 10 preservation, identity, RLS, failure and downgrade cases.
- [x] Full gate passes with pre/post evidence.

**Tests:** PostgreSQL integration
**Gate:** full
**Commit:** feat(tenant): migrate default database securely

### T9: Route tenant database sessions without a default

**Status:** Complete

**What:** Implement trusted tenant_id routing, bounded engines, identity/version guard and fail-closed transactions.
**Execution note:** O gate usa dois bancos PostgreSQL físicos temporários no mesmo servidor de teste. O roteador aceita somente UUID interno, resolve perfil e segredo no servidor, valida tenant_identity e revisão antes de liberar a sessão, configura workspace local à transação e descarta somente engines afetadas por mismatch, outage, rotação ou LRU.
**Where:** app/tenant_database.py
**Depends on:** T8
**Reuses:** SQLAlchemy patterns from app/database.py.
**Requirement:** MT-03, MT-06, MT-07
**Tools:** MCP official SQLAlchemy/Psycopg docs if needed; Skill tlc-spec-driven.

**Done when:**

- [x] API inputs cannot select slug/DSN/profile and no default/fallback engine exists.
- [x] Identity/revision precede business SQL; cache, rotation and invalidation are bounded.
- [x] Tests add at least 14 two-database cases for identical IDs, swapped profiles, outage, LRU and no fallback.
- [x] Phase 1 Build gate passes.

**Tests:** unit + PostgreSQL integration
**Gate:** build
**Commit:** feat(tenancy): add fail closed database router

### T10: Implement password and session primitives

**Status:** Complete

**What:** Add Argon2id verification, dummy path, opaque tokens/digests and TTL logic.
**Execution note:** O perfil Argon2id fixado em 64 MiB, 3 iterações e paralelismo 4 levou 337 ms no runtime local de validação. O módulo usa salt aleatório por hash, verificação fictícia fixa para sujeitos desconhecidos, token de 256 bits e limites de sessão exatos.
**Where:** app/security/passwords.py
**Depends on:** T9
**Reuses:** Standard secrets/hashlib and aware datetimes.
**Requirement:** MT-01, MT-02, MT-07
**Tools:** MCP official library/OWASP docs if needed; Skill tlc-spec-driven.

**Done when:**

- [x] Bounds are 12-128, Argon2id parameters are benchmarked and unknown subjects use dummy verification.
- [x] Token entropy/digest and idle/absolute TTL match the spec.
- [x] Tests add at least 12 cases for hashes, invalid inputs, timing path, token and TTL/revocation edges.
- [x] Quick gate passes: 15 passed.

**Tests:** unit
**Gate:** quick
**Commit:** feat(auth): add password and session primitives

### T11: Define auth API schemas

**Status:** Complete

**What:** Add bounded locator/login/session/error contracts without trusted connection or role inputs.
**Execution note:** Os contratos de autenticação proíbem campos extras, normalizam slug e e-mail no servidor, aceitam somente URL HTTPS do host público com um segmento e expõem sessão sem hash, token ou DSN.
**Where:** app/schemas.py
**Depends on:** T10
**Reuses:** Existing strict Pydantic validation.
**Requirement:** MT-01, MT-02, MT-03, MT-06
**Tools:** MCP NONE; Skill tlc-spec-driven.

**Done when:**

- [x] Slug/URL/email/password bounds and reserved paths are explicit.
- [x] Session output excludes hash, token and DSN; failures share one schema.
- [x] Tests add at least 10 boundary/malicious tenant-DSN-role cases.
- [x] Quick gate passes: 37 passed, 17 cases added.

**Tests:** unit
**Gate:** quick
**Commit:** feat(auth): define secure api contracts

### T12: Encode server authorization

**Status:** Complete

**What:** Implement action/record policies for all five current profiles.
**Execution note:** A política aceita somente os cinco perfis canônicos, falha fechada para papéis e módulos desconhecidos e separa ações administrativas, acesso tenant-wide e escopo por equipe/responsabilidade/assistência.
**Where:** app/policies.py
**Depends on:** T11
**Reuses:** Current canSee behavior only as input, never authority.
**Requirement:** MT-04
**Tools:** MCP NONE; Skill tlc-spec-driven.

**Done when:**

- [x] Every read/mutation/admin action has an explicit outcome.
- [x] Team, responsible/assistant, tenant-wide and admin-only rules match the spec.
- [x] Tests add at least 25 role/action/record cases including forged roles.
- [x] Quick gate passes: 55 passed.

**Tests:** unit
**Gate:** quick
**Commit:** feat(authz): enforce crm role policy

### T13: Coordinate tenant login and central sessions

**Status:** Complete

**What:** Implement directory lookup, tenant-DB user verification, central throttling/session creation and revocation.
**Execution note:** O login resolve apenas o UUID do diretório central, executa Argon2 real ou fictício uma vez por tentativa, registra limites transacionais por conta/IP e persiste somente digest e vínculo da sessão. A renovação relê o usuário no banco tenant, compara auth_version e limita o idle TTL ao prazo absoluto.
**Where:** app/services/auth.py
**Depends on:** T12
**Reuses:** Control repository, router and security primitives.
**Requirement:** MT-01, MT-02, MT-03, MT-06, MT-07
**Tools:** MCP NONE; Skill tlc-spec-driven.

**Done when:**

- [x] Login verifies only the resolved tenant DB and all subject/connection failures are publicly identical.
- [x] Central sessions contain linkage, never hash/role authority; refresh validates user auth_version.
- [x] Tests add at least 16 cases for same email across DBs, outage, limits, concurrency, expiry and revocation.
- [x] Full gate passes: 277 backend and 69 browser scenarios passed.

**Tests:** unit + PostgreSQL integration
**Gate:** full
**Commit:** feat(auth): add tenant database login service

### T14: Resolve immutable cookie principals

**Status:** Complete

**What:** Add cookie-only session resolution, route binding, tenant session lifecycle and Origin checks.
**Execution note:** A dependência aceita somente o cookie opaco, rejeita token alternativo em query/corpo/header, valida Origin exata antes de mutações e abre o banco exclusivamente pelo tenant_id do contexto central. Headers de tenant, DSN, usuário e papel são ignorados como autoridade.
**Where:** app/auth.py
**Depends on:** T13
**Reuses:** FastAPI dependencies and configured expected origin.
**Requirement:** MT-02, MT-03, MT-04, MT-06
**Tools:** MCP official FastAPI/Starlette docs if needed; Skill tlc-spec-driven.

**Done when:**

- [x] Alternate token locations are rejected and principal comes from central session plus current tenant user.
- [x] Route mismatch cannot remap; unsafe methods require exact HTTPS Origin.
- [x] Tests add at least 12 malformed/expired/revoked cookie, forged-source, route and Origin cases.
- [x] Full gate passes: 297 backend and 69 browser scenarios passed.

**Tests:** unit + API integration
**Gate:** full
**Commit:** feat(auth): resolve cookie principal securely

### T15: Protect auth and workspace routes

**Status:** Complete

**What:** Wire locator/login/session/logout and require principals on every workspace endpoint.
**Execution note:** A API agora expõe locator/login/session/logout com Origin exata nas mutações, cookie opaco `__Host-` endurecido e respostas `no-store`. Todas as rotas de workspace exigem o principal imutável resolvido no servidor, aplicam autorização por ação e mantêm o banco selecionado exclusivamente pelo tenant da sessão; slug, tenant, DSN, usuário e papel enviados pelo navegador não remapeiam autoridade.
**Where:** app/main.py
**Depends on:** T14
**Reuses:** App factory, exception handlers and static mount ordering.
**Requirement:** MT-01, MT-02, MT-03, MT-04, MT-06
**Tools:** MCP NONE; Skill tlc-spec-driven.

**Done when:**

- [x] Tenant SPA route is safe; cookie/no-store headers match spec.
- [x] Anonymous, forbidden and unavailable cases return stable 401/403/503.
- [x] Tests add at least 20 happy/failure/logout/CSRF/forged tenant-DSN-role/404/503 route cases: 24 cases added.
- [x] Full gate passes: 321 backend and 69 browser scenarios passed.

**Tests:** API integration
**Gate:** full
**Commit:** feat(api): protect tenant authentication routes

### T16: Scope every repository path

**Status:** Complete

**What:** Remove fixed/default scope and tenant-qualify every read, reconcile, delete and restore in the selected database.
**Execution note:** O repositório deriva o workspace do `current_setting` transacional definido pelo router, rejeita contexto ausente e compara o workspace esperado do principal quando fornecido. Nove lookups por identidade foram substituídos por consultas compostas com workspace, e exclusões de assistentes/histórico agora também incluem o workspace. Os testes usam dois bancos PostgreSQL físicos com IDs comerciais idênticos; um timeout transitório do DBP-10 na primeira UI foi investigado como corrida preexistente de visualização otimista, e a reexecução integral passou 69/69 sem alteração do teste.
**Where:** app/repositories/workspace.py
**Depends on:** T15
**Reuses:** Existing serialization/reconciliation.
**Requirement:** MT-03, MT-04, MT-07
**Tools:** MCP NONE; Skill tlc-spec-driven.

**Done when:**

- [x] No tenant-owned session.get or unqualified ID lookup remains.
- [x] Every write binds principal workspace and missing/wrong RLS context fails closed.
- [x] Tests add at least 18 two-database negative read/write/delete/restore/reference cases: 34 cases added.
- [x] Full gate proves the non-target database unchanged: 355 backend and 69 browser scenarios passed.

**Tests:** PostgreSQL integration
**Gate:** full
**Commit:** fix(tenancy): scope all repository operations

### T17: Enforce authorized snapshot projection and merge

**Status:** Complete

**What:** Replace default service calls with principal-based projection and canonical authorized save merge.
**Execution note:** `WorkspaceService` agora é stateless e exige a `TenantSession` já selecionada mais o `PrincipalScope` imutável em toda operação. O servidor projeta Leads/Negócios por equipe, responsabilidade ou assistência, restringe notificações e preferências ao usuário, mantém Contatos/Empresas tenant-wide e mescla saves autorizados com linhas invisíveis canônicas. Mudanças administrativas, registros fora do escopo e papéis desconhecidos falham com 403 sem escrita parcial; `currentUserId` é removido do snapshot e a identidade permanece somente na sessão autenticada. O Build gate exigiu reconstruir apenas o container CRM local porque a primeira tentativa UI encontrou `ERR_CONNECTION_REFUSED`; com o ambiente saudável, todos os 69 cenários passaram.
**Where:** app/services/workspace.py
**Depends on:** T16
**Reuses:** Existing row lock, version conflict and reference validation.
**Requirement:** MT-03, MT-04, MT-07
**Tools:** MCP NONE; Skill tlc-spec-driven.

**Done when:**

- [x] Service requires principal/TenantSession, filters reads and preserves invisible canonical rows.
- [x] Non-admin privileged changes fail without partial write.
- [x] Tests add at least 20 role/record/version/forged identity/cross-database cases: 59 cases added.
- [x] Phase 2 Build gate passes: compileall; compatibility 24/24; Compose valid; 414 backend; 69 browser; Windows runbook 41/41; Apache 21/21.

**Tests:** unit + PostgreSQL + API integration
**Gate:** build
**Commit:** feat(workspace): authorize snapshot projection and merge

### T18: Provision and resume tenants

**Status:** Complete

**What:** Implement local register, activate-default, resume, set-password and revoke commands with hidden inputs.
**Execution note:** A CLI local mantém o tenant em provisioning até validar revisão, workspace, identidade imutável e primeiro Administrador no banco dedicado. Falhas registram somente checkpoint e código redigidos; retomadas não duplicam tenant, identidade ou administrador. Senhas e segredos entram por prompt oculto, e mudança de senha incrementa auth_version e revoga sessões centrais.
**Where:** app/admin_cli.py
**Depends on:** T17
**Reuses:** Control states, SecretProvider, router and hasher.
**Requirement:** MT-01, MT-02, MT-05, MT-07
**Tools:** MCP NONE; Skill tlc-spec-driven.

**Done when:**

- [x] No HTTP provisioning exists and only fully verified tenant/admin becomes active.
- [x] Failure remains non-active with redacted checkpoint and idempotent resume.
- [x] Default activation never copies commercial data.
- [x] Tests add at least 14 hidden-input, duplicate, partial-failure, resume, count and revocation cases: 17 cases added.
- [x] Full gate passes: 431 backend and 69 browser scenarios passed.

**Tests:** PostgreSQL integration
**Gate:** full
**Commit:** feat(admin): provision tenant databases safely

### T19: Preflight and migrate an explicit fleet

**Status:** Complete

**What:** Implement redacted identity/revision health and explicitly selected per-tenant Alembic execution.
**Execution note:** O preflight abre cada perfil isoladamente, lê somente identidade e revisão e retorna códigos por tenant sem propagar detalhes de conexão. A migração recusa seleção vazia, ausência de backup confirmado ou confirmação operacional; bloqueia identidades divergentes em tenants ativos, processa apenas slugs explícitos e mantém resultados independentes após falha parcial.
**Where:** app/fleet.py
**Depends on:** T18
**Reuses:** Router health, control directory and tenant lineage.
**Requirement:** MT-05, MT-06, MT-07
**Tools:** MCP official Alembic docs if needed; Skill tlc-spec-driven.

**Done when:**

- [x] Output is independent/redacted per tenant.
- [x] Migration requires selection, backup acknowledgement and confirmation; requests never migrate.
- [x] Tests add at least 12 mixed-version, mismatch, outage, selection, cancellation and partial-failure cases: 17 cases added.
- [x] Full gate passes: 448 backend and 69 browser scenarios passed.

**Tests:** PostgreSQL integration
**Gate:** full
**Commit:** feat(ops): add tenant fleet preflight and migration

### T20: Add locator, login and logout UI

**Status:** Complete

**What:** Implement root locator and /{slug} login/app-shell using cookie credentials only.
**Execution note:** A raiz agora exibe somente o localizador; a rota tenant valida a sessão opaca por cookie antes de consultar o workspace e mantém o slug apenas como vínculo, nunca como autoridade. Login e locator usam falha genérica, nenhuma credencial/token é persistida ou enviada em header/query, e logout revoga no backend e limpa o estado sensível em memória.
**Where:** app/static/index.html
**Depends on:** T19
**Reuses:** Existing single-file styles and fetch helper.
**Requirement:** MT-01, MT-02, MT-03, MT-06
**Tools:** MCP NONE; Skill tlc-spec-driven.

**Done when:**

- [x] Locator/login routes and generic failures match spec.
- [x] Fetch never reads/writes a token and logout clears in-memory UI.
- [x] Browser suite adds at least 12 locator, login, error, route, cookie and logout scenarios: 12 cases added.
- [x] Full gate passes: 448 backend and 81 browser scenarios passed.

**Tests:** browser e2e
**Gate:** full
**Commit:** feat(ui): add tenant database login flow

### T21: Remove identity switching and commercial cache

**Status:** Complete

**What:** Replace profile selector with immutable server identity and keep only namespaced UI preferences.
**Execution note:** O frontend agora fixa identidade e perfil a partir de `/api/auth/session`, remove o seletor de personificacao e ignora `currentUserId`/perfil vindos do workspace ou do armazenamento local. O Web Storage retem somente preferencias de UI sob namespace de tenant e usuario; snapshots comerciais legados sao removidos e falhas do banco nao usam seed nem cache comercial.
**Where:** app/static/index.html
**Depends on:** T20
**Reuses:** Existing role labels/renderers.
**Requirement:** MT-02, MT-03, MT-04
**Tools:** MCP NONE; Skill tlc-spec-driven.

**Done when:**

- [x] No control/local value changes effective identity or role.
- [x] Commercial snapshots/credentials/session authority are absent from Web Storage.
- [x] Tests add at least 12 identity, direct-action, storage and two-tenant preference scenarios: 12 cases added.
- [x] Full gate passes: 448 backend and 93 browser scenarios passed.

**Tests:** browser e2e
**Gate:** full
**Commit:** fix(ui): remove impersonation and tenant cache

### T22: Bootstrap the central runtime safely

**Status:** Complete

**What:** Validate control revision and expose redacted health without eagerly opening every tenant.
**Execution note:** O factory central valida a revisao Alembic exata do control antes de criar a aplicacao, compoe autenticacao e roteamento com segredos DPAPI e mantem os engines tenant totalmente lazy. O health consulta somente o control e retorna apenas `ok` ou `degraded`, com `no-store` e sem detalhes de conexao, revisao ou erro.
**Where:** app/server.py
**Depends on:** T21
**Reuses:** Existing Uvicorn/health behavior.
**Requirement:** MT-03, MT-05, MT-06, MT-07
**Tools:** MCP NONE; Skill tlc-spec-driven.

**Done when:**

- [x] Missing/incompatible control DB blocks startup without secrets; tenant engines stay lazy.
- [x] Health exposes no host/database/role/DSN/error detail.
- [x] Tests add at least 8 control-failure, lazy-start, mixed-health and redaction cases: 10 cases added.
- [x] Phase 3 Build gate passes: 458 backend and 93 browser scenarios; compatibility 26, runbook 41 and Apache 21 contracts passed.

**Tests:** unit + API integration
**Gate:** build
**Commit:** feat(runtime): bootstrap central tenant router

### T23: Define safe Windows environment inputs

**Status:** Complete

**What:** Add control DSN, secret store, expected origin and pool/timeout placeholders.
**Execution note:** O modelo externo do Windows agora declara placeholder explicito para o DSN de control, diretorio DPAPI em ProgramData, origem HTTPS unica e limites positivos para cache, pool e timeouts. O arquivo continua preso a 127.0.0.1:8080 e nao contem DSN, senha ou token tenant em texto puro.
**Where:** deploy/manual-windows-pg11/server.env.example
**Depends on:** T22
**Reuses:** Existing allowlist/local bind.
**Requirement:** MT-02, MT-03, MT-05, MT-06
**Tools:** MCP NONE; Skill tlc-spec-driven.

**Done when:**

- [x] No tenant DSN/password/token is plaintext and defaults preserve local bind/secure origin.
- [x] Contract tests add at least 6 required-key, placeholder, allowlist and forbidden-secret assertions: 8 cases added.
- [x] Build gate passes: 466 backend and 93 browser scenarios; compatibility 26, runbook 41 and Apache 21 contracts passed.

**Tests:** contract
**Gate:** build
**Commit:** chore(windows): configure central tenant runtime

### T24: Package both migration lineages

**Status:** Complete

**What:** Include Argon2 wheel, control/tenant migrations and admin/fleet modules in the offline bundle.
**Where:** scripts/build_manual_windows_pg11_bundle.py
**Depends on:** T23
**Reuses:** Existing wheel-only/SHA-256 workflow.
**Requirement:** MT-01, MT-05, MT-06
**Tools:** MCP NONE; Skill tlc-spec-driven.

**Done when:**

- [x] Missing wheel/source contract fails before packaging and bundle has no real secret.
- [x] Tests add at least 8 content, hash, offline-install and missing-wheel assertions: 8 cases added.
- [x] Build gate passes without production deployment: 474 backend and 93 browser scenarios; compatibility 26, runbook 41 and Apache 21 contracts passed.

**Tests:** contract + outcome
**Gate:** build
**Commit:** build(windows): package multitenant control and fleet

### T25: Prepare Apache tenant paths

**Status:** Complete

**What:** Preserve one reverse proxy and document Basic Auth removal only at cutover.
**Where:** deploy/windows-apache/httpd-sc2030.conf.example
**Depends on:** T24
**Reuses:** Existing TLS virtual host/proxy.
**Requirement:** MT-01, MT-02, MT-06
**Tools:** MCP official Apache docs if needed; Skill tlc-spec-driven.

**Done when:**

- [x] Root, /{slug} and /api proxy to 127.0.0.1:8080 without database exposure.
- [x] Tests add at least 6 proxy-order, reserved-path, auth-transition and no-secret assertions: 8 cases added.
- [x] Build gate passes and no server is changed: 482 backend and 93 browser scenarios; compatibility 26, runbook 41 and Apache 32 contracts passed.

**Tests:** contract
**Gate:** build
**Commit:** docs(apache): prepare central tenant routes

### T26: Document fleet cutover and rollback

**Status:** Complete

**What:** Add control/default/remote database backup, migration, UAT and per-tenant rollback gates.
**Where:** RUNBOOK_DEPLOY_WINDOWS_SERVER_2016.md
**Depends on:** T25
**Reuses:** Existing PostgreSQL 11 runbook/integrity scripts.
**Requirement:** MT-03, MT-05, MT-06, MT-07
**Tools:** MCP NONE; Skill tlc-spec-driven.

**Done when:**

- [x] Every selected database requires verified backup and explicit authorization.
- [x] Default checks never copy business data; rollback never redirects to another database.
- [x] Tests add at least 10 gate/redaction/identity/RLS/rollback assertions: 13 cases added.
- [x] Build gate passes without server commands: 495 backend and 93 browser scenarios; compatibility 26, runbook 41 and Apache 32 contracts passed.

**Tests:** contract
**Gate:** build
**Commit:** docs(windows): add database fleet cutover gates

### T27: Document the multi-database model

**Status:** In Progress

**What:** Document control boundary, local three-database tests, provisioning and limitations.
**Where:** README.md
**Depends on:** T26
**Reuses:** Existing development/PostgreSQL sections.
**Requirement:** MT-01, MT-03, MT-05, MT-06
**Tools:** MCP NONE; Skill tlc-spec-driven.

**Done when:**

- [x] Docs separate control metadata from tenant users/data and explain revisions/no-auto-migrate.
- [x] Local setup uses control, tenant A and tenant B databases and notes PostgreSQL 11 risk.
- [x] Contract tests add at least 5 command/safety assertions: 8 cases added.
- [x] Phase 4 Build gate passes with final totals: 503 backend and 93 browser scenarios; compatibility 26, runbook 41 and Apache 32 contracts passed.
- [ ] Fresh Verifier runs spec evidence and discrimination sensor before validate_state passes.

**Tests:** contract + full regression
**Gate:** build
**Commit:** docs(tenancy): document isolated tenant databases

### T28: Revoke sessions after profile or status changes

**Status:** Complete

**What:** Detect tenant-user role/status changes during an authorized workspace transaction, increment auth_version once and revoke that user's central sessions after the tenant commit succeeds.
**Where:** app/repositories/workspace.py, app/services/auth.py, app/auth.py
**Depends on:** T27
**Reuses:** Tenant transaction lifecycle, auth_version validation and central revoke operation.
**Requirement:** MT-02, MT-04, MT-06
**Tools:** MCP NONE; Skill tlc-spec-driven.

**Done when:**

- [x] Role upgrade, downgrade and status change each increment auth_version exactly once in the tenant transaction.
- [x] A successful tenant commit revokes every prior central session for each changed user; rollback performs no eager central revocation and auth_version remains unchanged.
- [x] Tests prove the old session is unusable and unchanged user fields do not revoke sessions.
- [x] Full gate passes without weakening existing tests.


**Tests:** PostgreSQL integration + auth dependency/service
**Gate:** full
**Commit:** fix(auth): revoke sessions on access changes

### T29: Enforce verified TLS for remote PostgreSQL

**Status:** Complete

**What:** Validate server-resolved PostgreSQL connection profiles before router, administration or fleet engines are created, requiring certificate and hostname verification for remote hosts while allowing explicit localhost development.
**Where:** app/security/database_urls.py, app/tenant_database.py, app/admin_cli.py, app/fleet.py
**Depends on:** T28
**Reuses:** Server-side SecretProvider boundary and engine factories.
**Requirement:** MT-03, MT-05, MT-06, MT-07
**Tools:** MCP official Psycopg/PostgreSQL docs only if codebase evidence is insufficient; Skill tlc-spec-driven.

**Done when:**

- [x] Remote PostgreSQL URLs fail closed unless sslmode=verify-full and a root CA is configured; certificate and hostname checks cannot be downgraded by duplicate parameters.
- [x] Loopback development is allowed only by explicit configuration and remains disabled by default in production constructors.
- [x] Router, admin provisioning and fleet preflight/migration share the same validator before create_engine.
- [x] Tests cover remote insecure/verified URLs, localhost explicit allow/deny, redaction and all three callers; full gate passes.

**Tests:** unit + integration
**Gate:** full
**Commit:** fix(database): require verified tls for remote tenants

### T30: Complete redacted security auditing

**Status:** Complete

**What:** Emit central audit events for session revocation, database identity mismatch/routing failure and protected 401/403 denials without secrets.
**Where:** app/services/auth.py, app/tenant_database.py, app/auth.py, app/main.py
**Depends on:** T29
**Reuses:** ControlRepository.append_security_event and request/session correlation digests.
**Requirement:** MT-03, MT-04, MT-06
**Tools:** MCP NONE; Skill tlc-spec-driven.

**Done when:**

- [x] Revocation, identity mismatch/routing failure and every protected 401/403 path append event_id, known tenant/user and a correlation digest.
- [x] Events never contain raw password, cookie/token, DSN, host credential or commercial payload.
- [x] Missing context stays nullable instead of fabricating tenant/user identity, and audit failure cannot grant access.
- [x] Tests assert event types, outcomes, linkage/redaction and denial status; full gate passes.

**Tests:** unit + API + PostgreSQL integration
**Gate:** full
**Commit:** fix(audit): record tenant security denials

### T31: Expire invalid session cookies on 401

**Status:** Pending

**What:** Ensure every protected 401 caused by a received malformed, unknown, expired or revoked session cookie returns an expiration Set-Cookie with the hardened cookie attributes.
**Where:** app/auth.py, app/main.py
**Depends on:** T30
**Reuses:** Existing logout cookie contract and stable unauthenticated envelope.
**Requirement:** MT-02, MT-06, MT-07
**Tools:** MCP NONE; Skill tlc-spec-driven.

**Done when:**

- [ ] Malformed, unknown, expired and revoked received cookies return 401 plus Max-Age=0/Expires, Secure, HttpOnly, SameSite=Strict, Path=/ and no Domain.
- [ ] A request with no cookie remains 401 without inventing a Set-Cookie, and alternate token sources remain rejected.
- [ ] Tests assert the exact response header contract for every edge; full gate passes.

**Tests:** API integration
**Gate:** full
**Commit:** fix(auth): expire invalid session cookies

### T32: Prove no-store on successful login

**Status:** Pending

**What:** Add the missing spec-derived assertion that successful login responses are never cacheable.
**Where:** tests/backend/test_auth_api.py
**Depends on:** T31
**Reuses:** Existing login success API test and contract middleware.
**Requirement:** MT-06
**Tools:** MCP NONE; Skill tlc-spec-driven.

**Done when:**

- [ ] A successful POST /api/auth/login asserts Cache-Control: no-store alongside the secure cookie contract.
- [ ] The test would fail if login stopped receiving no-store, and no production behavior is weakened.
- [ ] Full gate passes.

**Tests:** API integration
**Gate:** full
**Commit:** test(auth): assert login response is not cacheable

### T33: Reconcile early task completion evidence

**Status:** Pending

**What:** Align the T1-T7 Done-when checkboxes with their already committed green gates and evidence, without rewriting implementation history.
**Where:** .specs/features/secure-multitenancy/tasks.md
**Depends on:** T32
**Reuses:** Existing T1-T7 commits, test totals and validation evidence.
**Requirement:** MT-01, MT-02, MT-03, MT-05, MT-06, MT-07
**Tools:** MCP NONE; Skill tlc-spec-driven.

**Done when:**

- [ ] Every T1-T7 Done-when item marked complete has matching committed evidence and no implementation claim is invented.
- [ ] validate_spec and validate_tasks pass; T27 and feature verification remain open for the fresh Verifier.
- [ ] Build gate passes with no test deletion.

**Tests:** structural validators + full regression
**Gate:** build
**Commit:** docs(spec): reconcile foundation task evidence

## Phase Execution Map

```
Phase 1: T1 → T2 → T3 → T4 → T5 → T6 → T7 → T8 → T9
Phase 2: T9 → T10 → T11 → T12 → T13 → T14 → T15 → T16 → T17
Phase 3: T17 → T18 → T19 → T20 → T21 → T22
Phase 4: T22 → T23 → T24 → T25 → T26 → T27
Phase 5: T27 → T28 → T29 → T30 → T31 → T32 → T33
```

Execution is sequential and phase boundaries are batch boundaries. Plan approval permits local implementation/commits only, never push, deploy, remote connection, production migration or server change.

## Task Granularity Check

| Task range | Deliverable | Status |
| ---------- | ----------- | ------ |
| T1-T2 | One manifest each | OK |
| T3-T9 | One model/migration/provider/repository/router boundary each | OK |
| T10-T17 | One security/schema/policy/service/API/repository boundary each | OK |
| T18-T22 | One admin/fleet/UI/runtime boundary each | OK |
| T23-T27 | One config/package/proxy/runbook/doc boundary each | OK |
| T28-T33 | One revocation/TLS/audit/cookie/coverage/evidence boundary each | OK |

Every source task co-locates required tests; there is no deferred test task.

## Diagram-Definition Cross-Check

| Task | Depends On | Diagram Shows | Status |
| ---- | ---------- | ------------- | ------ |
| T1 | None | Start | OK |
| T2 | T1 | T1 → T2 | OK |
| T3 | T2 | T2 → T3 | OK |
| T4 | T3 | T3 → T4 | OK |
| T5 | T4 | T4 → T5 | OK |
| T6 | T5 | T5 → T6 | OK |
| T7 | T6 | T6 → T7 | OK |
| T8 | T7 | T7 → T8 | OK |
| T9 | T8 | T8 → T9 | OK |
| T10 | T9 | T9 → T10 | OK |
| T11 | T10 | T10 → T11 | OK |
| T12 | T11 | T11 → T12 | OK |
| T13 | T12 | T12 → T13 | OK |
| T14 | T13 | T13 → T14 | OK |
| T15 | T14 | T14 → T15 | OK |
| T16 | T15 | T15 → T16 | OK |
| T17 | T16 | T16 → T17 | OK |
| T18 | T17 | T17 → T18 | OK |
| T19 | T18 | T18 → T19 | OK |
| T20 | T19 | T19 → T20 | OK |
| T21 | T20 | T20 → T21 | OK |
| T22 | T21 | T21 → T22 | OK |
| T23 | T22 | T22 → T23 | OK |
| T24 | T23 | T23 → T24 | OK |
| T25 | T24 | T24 → T25 | OK |
| T26 | T25 | T25 → T26 | OK |
| T27 | T26 | T26 → T27 | OK |
| T28 | T27 | T27 → T28 | OK |
| T29 | T28 | T28 → T29 | OK |
| T30 | T29 | T29 → T30 | OK |
| T31 | T30 | T30 → T31 | OK |
| T32 | T31 | T31 → T32 | OK |
| T33 | T32 | T32 → T33 | OK |

## Test Co-location Validation

| Tasks | Code Layer | Matrix Requires | Task Says | Status |
| ----- | ---------- | --------------- | --------- | ------ |
| T1-T2 | Config | Build/contract | Build/contract | OK |
| T3-T4 | Control model/migration | PostgreSQL | Unit/integration | OK |
| T5-T6 | Secret/control repository | Unit + PostgreSQL | Unit/integration | OK |
| T7-T9 | Tenant model/migration/router | Unit + PostgreSQL | Unit/integration | OK |
| T10-T12 | Security/schema/policy | Unit | Unit | OK |
| T13-T15 | Auth service/dependency/API | Unit + API/PostgreSQL | Unit/integration | OK |
| T16-T17 | Repository/service | PostgreSQL + API | PostgreSQL/API | OK |
| T18-T19 | Admin/fleet | PostgreSQL | PostgreSQL | OK |
| T20-T21 | Frontend | Browser e2e | Browser e2e | OK |
| T22 | Runtime/API | Unit + API | Unit/API | OK |
| T23-T27 | Deploy/config/docs | Contract/build | Contract/build/full | OK |
| T28 | Repository/auth lifecycle | PostgreSQL + auth integration | PostgreSQL/auth integration | OK |
| T29 | Secret/router/admin/fleet | Unit + PostgreSQL | Unit/integration | OK |
| T30-T32 | Auth/API/audit | Unit + API/PostgreSQL | Unit/API/PostgreSQL | OK |
| T33 | Spec evidence | Structural/build | Structural/build/full | OK |

## Requirement Coverage

| Requirement | Tasks | Evidence target |
| ----------- | ----- | --------------- |
| MT-01 Locate/login | T1,T3-T6,T10-T15,T18,T20,T33 | Tenant-local credentials and generic failures |
| MT-02 Central session | T3,T6,T10-T15,T18,T20-T23,T28,T31,T33 | Cookie, digest, TTL, revocation and no-token |
| MT-03 Database isolation | T5,T7-T9,T13-T17,T20-T26,T29-T30,T33 | Two DBs, forged routing, verified TLS and RLS |
| MT-04 Authorization | T12,T14-T17,T21,T28,T30 | Role/action/record matrix and denial audit |
| MT-05 Migration/provisioning | T1-T8,T18-T19,T22-T24,T26-T27,T29,T33 | Default preservation, checkpoints and fleet |
| MT-06 Operation | T3-T6,T9,T13-T15,T19,T22-T33 | Redaction, audit, TLS, cache, health, package and runbook |
| MT-07 Edge/concurrency | T5-T10,T13-T19,T22,T26,T29,T31,T33 | Locks, outage, mismatch, retry and rollback |

**Coverage:** 7 requirement groups, 33 mapped tasks, 0 unmapped.

## Approval Gate Before Execute

1. User approves or overrides every Confirmed? n default in spec.md.
2. User approves spec.md, context.md, design.md and tasks.md.
3. User confirms tools: tlc-spec-driven for all tasks; local filesystem/shell/tests; web only for official docs where noted.
4. Because 27 tasks exceed one batch, user chooses sequential phase-batch sub-agents or inline execution.
5. Runnable local environment establishes backend/browser baseline before T1.
6. Deploy, push, remote tenant connection, production backup/migration and server changes always require separate explicit authorization.
