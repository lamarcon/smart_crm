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
| Tenant repository | PostgreSQL integration | Two databases, identical IDs, all mutations/restores and forced RLS | tests/backend/test_repository.py | python -m pytest -p no:cacheprovider --basetemp .pytest-tmp tests/backend/test_repository.py -q |
| Workspace/auth API | integration | All routes and happy/anonymous/forbidden/forged/CSRF/503 paths | tests/backend/test_api.py | python -m pytest -p no:cacheprovider --basetemp .pytest-tmp tests/backend/test_api.py -q |
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

**Status:** Pending

**What:** Add cookie-only session resolution, route binding, tenant session lifecycle and Origin checks.
**Where:** app/auth.py
**Depends on:** T13
**Reuses:** FastAPI dependencies and configured expected origin.
**Requirement:** MT-02, MT-03, MT-04, MT-06
**Tools:** MCP official FastAPI/Starlette docs if needed; Skill tlc-spec-driven.

**Done when:**

- [ ] Alternate token locations are rejected and principal comes from central session plus current tenant user.
- [ ] Route mismatch cannot remap; unsafe methods require exact HTTPS Origin.
- [ ] Tests add at least 12 malformed/expired/revoked cookie, forged-source, route and Origin cases.
- [ ] Full gate passes.

**Tests:** unit + API integration
**Gate:** full
**Commit:** feat(auth): resolve cookie principal securely

### T15: Protect auth and workspace routes

**Status:** Pending

**What:** Wire locator/login/session/logout and require principals on every workspace endpoint.
**Where:** app/main.py
**Depends on:** T14
**Reuses:** App factory, exception handlers and static mount ordering.
**Requirement:** MT-01, MT-02, MT-03, MT-04, MT-06
**Tools:** MCP NONE; Skill tlc-spec-driven.

**Done when:**

- [ ] Tenant SPA route is safe; cookie/no-store headers match spec.
- [ ] Anonymous, forbidden and unavailable cases return stable 401/403/503.
- [ ] Tests add at least 20 happy/failure/logout/CSRF/forged tenant-DSN-role/404/503 route cases.
- [ ] Full gate passes.

**Tests:** API integration
**Gate:** full
**Commit:** feat(api): protect tenant authentication routes

### T16: Scope every repository path

**Status:** Pending

**What:** Remove fixed/default scope and tenant-qualify every read, reconcile, delete and restore in the selected database.
**Where:** app/repositories/workspace.py
**Depends on:** T15
**Reuses:** Existing serialization/reconciliation.
**Requirement:** MT-03, MT-04, MT-07
**Tools:** MCP NONE; Skill tlc-spec-driven.

**Done when:**

- [ ] No tenant-owned session.get or unqualified ID lookup remains.
- [ ] Every write binds principal workspace and missing/wrong RLS context fails closed.
- [ ] Tests add at least 18 two-database negative read/write/delete/restore/reference cases.
- [ ] Full gate proves the non-target database unchanged.

**Tests:** PostgreSQL integration
**Gate:** full
**Commit:** fix(tenancy): scope all repository operations

### T17: Enforce authorized snapshot projection and merge

**Status:** Pending

**What:** Replace default service calls with principal-based projection and canonical authorized save merge.
**Where:** app/services/workspace.py
**Depends on:** T16
**Reuses:** Existing row lock, version conflict and reference validation.
**Requirement:** MT-03, MT-04, MT-07
**Tools:** MCP NONE; Skill tlc-spec-driven.

**Done when:**

- [ ] Service requires principal/TenantSession, filters reads and preserves invisible canonical rows.
- [ ] Non-admin privileged changes fail without partial write.
- [ ] Tests add at least 20 role/record/version/forged identity/cross-database cases.
- [ ] Phase 2 Build gate passes.

**Tests:** unit + PostgreSQL + API integration
**Gate:** build
**Commit:** feat(workspace): authorize snapshot projection and merge

### T18: Provision and resume tenants

**Status:** Pending

**What:** Implement local register, activate-default, resume, set-password and revoke commands with hidden inputs.
**Where:** app/admin_cli.py
**Depends on:** T17
**Reuses:** Control states, SecretProvider, router and hasher.
**Requirement:** MT-01, MT-02, MT-05, MT-07
**Tools:** MCP NONE; Skill tlc-spec-driven.

**Done when:**

- [ ] No HTTP provisioning exists and only fully verified tenant/admin becomes active.
- [ ] Failure remains non-active with redacted checkpoint and idempotent resume.
- [ ] Default activation never copies commercial data.
- [ ] Tests add at least 14 hidden-input, duplicate, partial-failure, resume, count and revocation cases.
- [ ] Full gate passes.

**Tests:** PostgreSQL integration
**Gate:** full
**Commit:** feat(admin): provision tenant databases safely

### T19: Preflight and migrate an explicit fleet

**Status:** Pending

**What:** Implement redacted identity/revision health and explicitly selected per-tenant Alembic execution.
**Where:** app/fleet.py
**Depends on:** T18
**Reuses:** Router health, control directory and tenant lineage.
**Requirement:** MT-05, MT-06, MT-07
**Tools:** MCP official Alembic docs if needed; Skill tlc-spec-driven.

**Done when:**

- [ ] Output is independent/redacted per tenant.
- [ ] Migration requires selection, backup acknowledgement and confirmation; requests never migrate.
- [ ] Tests add at least 12 mixed-version, mismatch, outage, selection, cancellation and partial-failure cases.
- [ ] Full gate passes.

**Tests:** PostgreSQL integration
**Gate:** full
**Commit:** feat(ops): add tenant fleet preflight and migration

### T20: Add locator, login and logout UI

**Status:** Pending

**What:** Implement root locator and /{slug} login/app-shell using cookie credentials only.
**Where:** app/static/index.html
**Depends on:** T19
**Reuses:** Existing single-file styles and fetch helper.
**Requirement:** MT-01, MT-02, MT-03, MT-06
**Tools:** MCP NONE; Skill tlc-spec-driven.

**Done when:**

- [ ] Locator/login routes and generic failures match spec.
- [ ] Fetch never reads/writes a token and logout clears in-memory UI.
- [ ] Browser suite adds at least 12 locator, login, error, route, cookie and logout scenarios.
- [ ] Full gate passes.

**Tests:** browser e2e
**Gate:** full
**Commit:** feat(ui): add tenant database login flow

### T21: Remove identity switching and commercial cache

**Status:** Pending

**What:** Replace profile selector with immutable server identity and keep only namespaced UI preferences.
**Where:** app/static/index.html
**Depends on:** T20
**Reuses:** Existing role labels/renderers.
**Requirement:** MT-02, MT-03, MT-04
**Tools:** MCP NONE; Skill tlc-spec-driven.

**Done when:**

- [ ] No control/local value changes effective identity or role.
- [ ] Commercial snapshots/credentials/session authority are absent from Web Storage.
- [ ] Tests add at least 12 identity, direct-action, storage and two-tenant preference scenarios.
- [ ] Full gate passes.

**Tests:** browser e2e
**Gate:** full
**Commit:** fix(ui): remove impersonation and tenant cache

### T22: Bootstrap the central runtime safely

**Status:** Pending

**What:** Validate control revision and expose redacted health without eagerly opening every tenant.
**Where:** app/server.py
**Depends on:** T21
**Reuses:** Existing Uvicorn/health behavior.
**Requirement:** MT-03, MT-05, MT-06, MT-07
**Tools:** MCP NONE; Skill tlc-spec-driven.

**Done when:**

- [ ] Missing/incompatible control DB blocks startup without secrets; tenant engines stay lazy.
- [ ] Health exposes no host/database/role/DSN/error detail.
- [ ] Tests add at least 8 control-failure, lazy-start, mixed-health and redaction cases.
- [ ] Phase 3 Build gate passes.

**Tests:** unit + API integration
**Gate:** build
**Commit:** feat(runtime): bootstrap central tenant router

### T23: Define safe Windows environment inputs

**Status:** Pending

**What:** Add control DSN, secret store, expected origin and pool/timeout placeholders.
**Where:** deploy/manual-windows-pg11/server.env.example
**Depends on:** T22
**Reuses:** Existing allowlist/local bind.
**Requirement:** MT-02, MT-03, MT-05, MT-06
**Tools:** MCP NONE; Skill tlc-spec-driven.

**Done when:**

- [ ] No tenant DSN/password/token is plaintext and defaults preserve local bind/secure origin.
- [ ] Contract tests add at least 6 required-key, placeholder, allowlist and forbidden-secret assertions.
- [ ] Build gate passes.

**Tests:** contract
**Gate:** build
**Commit:** chore(windows): configure central tenant runtime

### T24: Package both migration lineages

**Status:** Pending

**What:** Include Argon2 wheel, control/tenant migrations and admin/fleet modules in the offline bundle.
**Where:** scripts/build_manual_windows_pg11_bundle.py
**Depends on:** T23
**Reuses:** Existing wheel-only/SHA-256 workflow.
**Requirement:** MT-01, MT-05, MT-06
**Tools:** MCP NONE; Skill tlc-spec-driven.

**Done when:**

- [ ] Missing wheel/source contract fails before packaging and bundle has no real secret.
- [ ] Tests add at least 8 content, hash, offline-install and missing-wheel assertions.
- [ ] Build gate passes without production deployment.

**Tests:** contract + outcome
**Gate:** build
**Commit:** build(windows): package multitenant control and fleet

### T25: Prepare Apache tenant paths

**Status:** Pending

**What:** Preserve one reverse proxy and document Basic Auth removal only at cutover.
**Where:** deploy/windows-apache/httpd-sc2030.conf.example
**Depends on:** T24
**Reuses:** Existing TLS virtual host/proxy.
**Requirement:** MT-01, MT-02, MT-06
**Tools:** MCP official Apache docs if needed; Skill tlc-spec-driven.

**Done when:**

- [ ] Root, /{slug} and /api proxy to 127.0.0.1:8080 without database exposure.
- [ ] Tests add at least 6 proxy-order, reserved-path, auth-transition and no-secret assertions.
- [ ] Build gate passes and no server is changed.

**Tests:** contract
**Gate:** build
**Commit:** docs(apache): prepare central tenant routes

### T26: Document fleet cutover and rollback

**Status:** Pending

**What:** Add control/default/remote database backup, migration, UAT and per-tenant rollback gates.
**Where:** RUNBOOK_DEPLOY_WINDOWS_SERVER_2016.md
**Depends on:** T25
**Reuses:** Existing PostgreSQL 11 runbook/integrity scripts.
**Requirement:** MT-03, MT-05, MT-06, MT-07
**Tools:** MCP NONE; Skill tlc-spec-driven.

**Done when:**

- [ ] Every selected database requires verified backup and explicit authorization.
- [ ] Default checks never copy business data; rollback never redirects to another database.
- [ ] Tests add at least 10 gate/redaction/identity/RLS/rollback assertions.
- [ ] Build gate passes without server commands.

**Tests:** contract
**Gate:** build
**Commit:** docs(windows): add database fleet cutover gates

### T27: Document the multi-database model

**Status:** Pending

**What:** Document control boundary, local three-database tests, provisioning and limitations.
**Where:** README.md
**Depends on:** T26
**Reuses:** Existing development/PostgreSQL sections.
**Requirement:** MT-01, MT-03, MT-05, MT-06
**Tools:** MCP NONE; Skill tlc-spec-driven.

**Done when:**

- [ ] Docs separate control metadata from tenant users/data and explain revisions/no-auto-migrate.
- [ ] Local setup uses control, tenant A and tenant B databases and notes PostgreSQL 11 risk.
- [ ] Contract tests add at least 5 command/safety assertions.
- [ ] Phase 4 Build gate passes with final totals.
- [ ] Fresh Verifier runs spec evidence and discrimination sensor before validate_state passes.

**Tests:** contract + full regression
**Gate:** build
**Commit:** docs(tenancy): document isolated tenant databases

## Phase Execution Map

```
Phase 1: T1 → T2 → T3 → T4 → T5 → T6 → T7 → T8 → T9
Phase 2: T9 → T10 → T11 → T12 → T13 → T14 → T15 → T16 → T17
Phase 3: T17 → T18 → T19 → T20 → T21 → T22
Phase 4: T22 → T23 → T24 → T25 → T26 → T27
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

## Requirement Coverage

| Requirement | Tasks | Evidence target |
| ----------- | ----- | --------------- |
| MT-01 Locate/login | T1,T3-T6,T10-T15,T18,T20 | Tenant-local credentials and generic failures |
| MT-02 Central session | T3,T6,T10-T15,T18,T20-T23 | Cookie, digest, TTL, revocation and no-token |
| MT-03 Database isolation | T5,T7-T9,T13-T17,T20-T26 | Two DBs, forged routing and RLS |
| MT-04 Authorization | T12,T14-T17,T21 | Role/action/record matrix |
| MT-05 Migration/provisioning | T1-T8,T18-T19,T22-T24,T26-T27 | Default preservation, checkpoints and fleet |
| MT-06 Operation | T3-T6,T9,T13-T15,T19,T22-T27 | Redaction, health, package and runbook |
| MT-07 Edge/concurrency | T5-T10,T13-T19,T22,T26 | Locks, outage, mismatch, retry and rollback |

**Coverage:** 7 requirement groups, 27 mapped tasks, 0 unmapped.

## Approval Gate Before Execute

1. User approves or overrides every Confirmed? n default in spec.md.
2. User approves spec.md, context.md, design.md and tasks.md.
3. User confirms tools: tlc-spec-driven for all tasks; local filesystem/shell/tests; web only for official docs where noted.
4. Because 27 tasks exceed one batch, user chooses sequential phase-batch sub-agents or inline execution.
5. Runnable local environment establishes backend/browser baseline before T1.
6. Deploy, push, remote tenant connection, production backup/migration and server changes always require separate explicit authorization.
