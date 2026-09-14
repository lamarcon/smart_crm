> **Superseded on 2026-09-14:** preserved only as history. The approved candidate is tasks.md and uses one PostgreSQL database per tenant.

---

# Multiempresa Seguro Tasks

## Execution Protocol (MANDATORY -- do not skip)

Implement these tasks with the `tlc-spec-driven` skill: **activate it by name and follow its Execute flow and Critical Rules.** Do not search for skill files by filesystem path. The skill is the source of truth for the full flow, including per-task gates, atomic commits, sub-agent offer, independent Verifier and discrimination sensor.

**If the skill cannot be activated, STOP and tell the user. Do not proceed without it.**

---

**Design:** `.specs/features/secure-multitenancy/design.md`
**Status:** Draft awaiting approval

**Baseline evidence:** 91 backend test functions and 69 browser scenarios were discovered. They were not executed during planning because Docker/PostgreSQL were stopped and the available Python runtime had no `pytest`. No task may claim a green baseline until the approved execution environment runs it.

---

## Test Coverage Matrix

> Generated from `pyproject.toml`, `package.json`, `README.md`, current tests and the spec. Guidelines found: `pyproject.toml` pytest settings, `package.json` scripts, `README.md` full gate, `scripts/verify_python_compatibility.py`, deployment contract verifiers. No `AGENTS.md`, lint command or coverage percentage gate was found; strong defaults apply.

| Code Layer | Required Test Type | Coverage Expectation | Location Pattern | Run Command |
| ---------- | ------------------ | -------------------- | ---------------- | ----------- |
| Password/session/auth service | unit + integration | Every branch and auth AC, including dummy hash, expiry, revocation, concurrency and generic failures | `tests/backend/test_security.py`, `tests/backend/test_auth_service.py` | `python -m pytest -p no:cacheprovider tests/backend/test_security.py tests/backend/test_auth_service.py -q` |
| Authorization policy | unit | 1:1 role/outcome matrix for every protected collection and privileged field | `tests/backend/test_authorization.py` | `python -m pytest -p no:cacheprovider tests/backend/test_authorization.py -q` |
| Repository/data access | PostgreSQL integration | Two tenants, identical IDs, all read/write/delete/restore paths, missing tenant context and RLS | `tests/backend/test_repository.py`, `tests/backend/test_auth_repository.py` | `python -m pytest -p no:cacheprovider tests/backend/test_repository.py tests/backend/test_auth_repository.py -q` |
| Workspace/auth API | integration | Every route: success, anonymous, forbidden, invalid, cross-tenant, CSRF/origin and error paths | `tests/backend/test_api.py` | `python -m pytest -p no:cacheprovider tests/backend/test_api.py -q` |
| Models/schemas/migrations | unit + PostgreSQL integration | Every constraint, composite FK, preservation count/checksum, upgrade/idempotence and isolated downgrade | `tests/backend/test_models.py`, `tests/backend/test_schemas.py`, `tests/backend/test_migrations.py` | `python -m pytest -p no:cacheprovider tests/backend/test_models.py tests/backend/test_schemas.py tests/backend/test_migrations.py -q` |
| Admin CLI | integration | Create/activate/set-password/revoke happy path, duplicates, hidden secret and full rollback | `tests/backend/test_admin.py` | `python -m pytest -p no:cacheprovider tests/backend/test_admin.py -q` |
| Frontend route/auth/cache | browser e2e | Locator, invalid tenant, login, cookie-only session, immutable profile, logout, route mismatch and tenant/user preference isolation | `tests/ui-prototype.spec.cjs` | `pnpm test` |
| Windows/Apache/offline package | contract + outcome | Exact env allowlist, secure cookie/origin config, wheel availability, Apache transition and no production mutation | `tests/backend/test_manual_windows_pg11_*.py`, `scripts/verify_windows_*.py` | `python -m pytest -p no:cacheprovider tests/backend/test_manual_windows_pg11_deployment.py tests/backend/test_manual_windows_pg11_outcomes.py -q` |
| Dependency/config/docs only | build/contract | Exact pinned manifests, Python 3.11 parse, Compose config and documentation/source contract | manifests and existing verifier scripts | Build gate only |

## Gate Check Commands

> Generated from repository commands. PostgreSQL-backed gates require the local development database to be running. No deployment or remote command is part of these gates.

| Gate Level | When to Use | Command |
| ---------- | ----------- | ------- |
| Quick | Pure unit task | `python -m pytest -p no:cacheprovider <task test file> -q` |
| Full | Repository, migration, API, CLI or browser task | `docker compose up -d postgres`<br>`python -m pytest -p no:cacheprovider tests/backend -q`<br>`pnpm test` |
| Build | Phase completion and dependency/deployment tasks | `python -m compileall -q app migrations`<br>`python scripts/verify_python_compatibility.py`<br>`docker compose config --quiet`<br>`python -m pytest -p no:cacheprovider tests/backend -q`<br>`pnpm test`<br>`python scripts/verify_windows_runbook_contract.py`<br>`python scripts/verify_windows_apache_contract.py` |

The Build gate records the actual total collected/passed tests. It must never fall below the 91 backend functions and 69 browser scenarios discovered during planning, plus the tests added by completed tasks.

---

## Execution Plan

Phases and tasks run sequentially. Each phase ends with the Build gate before the next phase starts.

### Phase 1: Tenant-aware persistence foundation

```text
T1 -> T2 -> T3 -> T4 -> T5 -> T6
```

### Phase 2: Authentication and authorization core

```text
T6 -> T7
T7 -> T8 -> T9 -> T10 -> T11 -> T12 -> T13
```

### Phase 3: Protected workspace, provisioning and frontend

```text
T13 -> T14
T14 -> T15 -> T16 -> T17
```

### Phase 4: Offline Windows and operator contracts

```text
T17 -> T18
T18 -> T19 -> T20 -> T21 -> T22 -> T23
```

---

## Task Breakdown

### T1: Pin the authentication dependency in project metadata

**What:** Add the selected Argon2id library with an exact version and supported Python metadata.
**Where:** `pyproject.toml`
**Depends on:** None
**Reuses:** Existing exact-version dependency convention.
**Requirement:** MT-02, MT-05

**Tools:**

- MCP: official web documentation only if the pinned version must be rechecked
- Skill: `tlc-spec-driven`

**Done when:**

- [ ] The dependency is exact-pinned and supports CPython 3.11 on Windows x64.
- [ ] Dependency metadata and compatibility verifier tests include at least 1 new assertion.
- [ ] Build gate passes with no test deletion.

**Tests:** none for config; build/contract gate
**Gate:** build
**Commit:** `build(auth): pin argon2 password dependency`

### T2: Mirror the authentication dependency in runtime requirements

**What:** Keep the offline runtime manifest exactly aligned with project metadata.
**Where:** `requirements-runtime.txt`
**Depends on:** T1
**Reuses:** Existing wheel-only bundle input.
**Requirement:** MT-05

**Tools:**

- MCP: NONE
- Skill: `tlc-spec-driven`

**Done when:**

- [ ] Runtime and project dependency pins match exactly.
- [ ] A manifest parity assertion detects removal or version drift.
- [ ] Build gate passes with no test deletion.

**Tests:** none for config; build/contract gate
**Gate:** build
**Commit:** `build(auth): align offline runtime dependencies`

### T3: Define tenant-aware and authentication models

**What:** Add workspace directory/auth tables and make every tenant-owned identity/reference express tenant scope.
**Where:** `app/models.py`
**Depends on:** T2
**Reuses:** Existing SQLAlchemy 2 declarative and naming convention.
**Requirement:** MT-02, MT-03, MT-05, MT-06

**Tools:**

- MCP: NONE
- Skill: `tlc-spec-driven`

**Done when:**

- [ ] Workspace, user auth fields, sessions, throttle and audit models match the design.
- [ ] Tenant entities and child references include tenant-aware constraints.
- [ ] Password/session secrets are excluded from payload serialization by model separation.
- [ ] Model tests add at least 8 assertions covering tables, keys, constraints, indexes and secret fields.
- [ ] Full gate passes with no test deletion.

**Tests:** unit + integration
**Gate:** full
**Commit:** `feat(tenancy): define tenant aware auth models`

### T4: Migrate the existing default workspace without data loss

**What:** Add one Alembic revision that backfills tenant identity, child scopes, composite references and forced RLS in dependency order.
**Where:** `migrations/versions/<revision>_secure_multitenancy.py`
**Depends on:** T3
**Reuses:** Isolated-schema Alembic test fixture and named constraints.
**Requirement:** MT-03, MT-05, MT-07

**Tools:**

- MCP: official PostgreSQL 11 docs for DDL/RLS semantics
- Skill: `tlc-spec-driven`

**Done when:**

- [ ] Upgrade preserves `workspaces.id='default'`, every existing row, payload and relationship.
- [ ] Child workspace backfills prove zero orphans before NOT NULL/foreign keys.
- [ ] Tenant policies use direct row predicates with `USING` and `WITH CHECK` and are forced.
- [ ] Migration tests add at least 8 scenarios for preservation, identical IDs after upgrade, idempotent head, policy metadata, failure rollback and isolated downgrade.
- [ ] Full gate passes with exact pre/post count evidence.

**Tests:** PostgreSQL integration
**Gate:** full
**Commit:** `feat(tenancy): migrate default workspace securely`

### T5: Set fail-closed tenant context per transaction

**What:** Extend the database boundary to apply a transaction-local PostgreSQL tenant setting only from a trusted principal.
**Where:** `app/database.py`
**Depends on:** T4
**Reuses:** Existing commit/rollback/close guarantees.
**Requirement:** MT-03, MT-07

**Tools:**

- MCP: official PostgreSQL 11 docs
- Skill: `tlc-spec-driven`

**Done when:**

- [ ] Authenticated scopes call `set_config(..., true)` inside the transaction.
- [ ] Anonymous/auth lookup scopes cannot accidentally access tenant-owned business rows.
- [ ] Rollback and pooled connection reuse cannot leak a prior tenant context.
- [ ] Database tests add at least 4 scenarios for set, unset, rollback and connection reuse.
- [ ] Full gate passes with no test deletion.

**Tests:** PostgreSQL integration
**Gate:** full
**Commit:** `feat(database): bind tenant context to transactions`

### T6: Eliminate ID-only and default-tenant repository access

**What:** Require a workspace ID and tenant-qualify every read, upsert, delete, restore and relationship operation.
**Where:** `app/repositories/workspace.py`
**Depends on:** T5
**Reuses:** Existing reconciler and round-trip behavior.
**Requirement:** MT-03, MT-07

**Tools:**

- MCP: NONE
- Skill: `tlc-spec-driven`

**Done when:**

- [ ] Repository construction without workspace scope is impossible.
- [ ] No `session.get(model, public_id)` remains for a tenant-owned entity.
- [ ] Every child delete/upsert contains tenant scope.
- [ ] Two-tenant tests add at least 12 negative cases covering load, reconcile, soft delete, restore, quotes, assistants, history, fields, filters and preferences with identical IDs.
- [ ] Full gate passes and tenant B remains byte-equivalent after every tenant A mutation.

**Tests:** PostgreSQL integration
**Gate:** full
**Commit:** `fix(repository): scope every operation by tenant`

### T7: Add strict authentication and tenant schemas

**What:** Define bounded locator, login, session and principal response contracts without accepting protected tenant authority.
**Where:** `app/schemas.py`
**Depends on:** T6
**Reuses:** Existing Pydantic alias and structured validation patterns.
**Requirement:** MT-01, MT-02, MT-03

**Tools:**

- MCP: NONE
- Skill: `tlc-spec-driven`

**Done when:**

- [ ] Slug/URL, e-mail, password and cookie-adjacent inputs have explicit bounds.
- [ ] Protected workspace requests expose no tenant/user/role authorization field.
- [ ] Response schemas cannot serialize password hash or raw session token.
- [ ] Schema tests add at least 5 boundary and invalid-input cases.
- [ ] Quick gate passes with no test deletion.

**Tests:** unit
**Gate:** quick
**Commit:** `feat(auth): define bounded authentication contracts`

### T8: Implement Argon2id and opaque-token primitives

**What:** Implement security settings, password hashing, dummy verification, secure token generation and digesting.
**Where:** `app/security.py`
**Depends on:** T7
**Reuses:** Environment configuration style from `app/database.py`.
**Requirement:** MT-01, MT-02, MT-05

**Tools:**

- MCP: official FastAPI/OWASP docs
- Skill: `tlc-spec-driven`

**Done when:**

- [ ] Hash output identifies Argon2id and meets approved minimum parameters.
- [ ] Password input is never logged, returned or stored by the utility.
- [ ] Session tokens contain at least 128 bits of CSPRNG entropy and only digests are persistable.
- [ ] Security tests add at least 10 cases including verify, wrong password, rehash, dummy path, bounds, uniqueness and settings fail-closed.
- [ ] Quick gate passes with no test deletion.

**Tests:** unit
**Gate:** quick
**Commit:** `feat(auth): add argon2id and opaque session primitives`

### T9: Persist login throttles and server sessions

**What:** Add the authentication repository with locked throttle buckets and session lifecycle queries.
**Where:** `app/repositories/auth.py`
**Depends on:** T8
**Reuses:** SQLAlchemy transaction and explicit-query conventions.
**Requirement:** MT-01, MT-02, MT-06, MT-07

**Tools:**

- MCP: NONE
- Skill: `tlc-spec-driven`

**Done when:**

- [ ] Tenant/user lookup is normalized and session lookup uses token digest only.
- [ ] Account, IP and locator buckets serialize concurrent failures.
- [ ] Expired/revoked/auth-version-mismatched sessions never resolve.
- [ ] Repository tests add at least 12 cases including concurrent threshold, TTL, revocation and unknown digests.
- [ ] Full gate passes with no test deletion.

**Tests:** PostgreSQL integration
**Gate:** full
**Commit:** `feat(auth): persist throttles and sessions`

### T10: Implement constant-shape authentication lifecycle

**What:** Orchestrate locator, login, session resolution, logout and user-wide revocation.
**Where:** `app/services/auth.py`
**Depends on:** T9
**Reuses:** Typed service-exception pattern.
**Requirement:** MT-01, MT-02, MT-06, MT-07

**Tools:**

- MCP: official OWASP authentication/session guidance
- Skill: `tlc-spec-driven`

**Done when:**

- [ ] Invalid tenant, email, password and status take the dummy/real hash path and produce one public error.
- [ ] Login success atomically resets counters, creates session and records a secret-free audit event.
- [ ] Logout is idempotent; password/profile/status changes revoke old auth versions.
- [ ] Service tests add at least 12 outcome cases and assert exact repository calls and public messages.
- [ ] Full gate passes with no test deletion.

**Tests:** unit + integration
**Gate:** full
**Commit:** `feat(auth): enforce login and session lifecycle`

### T11: Resolve immutable principals and protect unsafe requests

**What:** Add FastAPI dependencies for cookie-only principal resolution, role requirements and Origin validation.
**Where:** `app/auth.py`
**Depends on:** T10
**Reuses:** App-factory injection used in `tests/backend/test_api.py`.
**Requirement:** MT-02, MT-03, MT-04, MT-06

**Tools:**

- MCP: official OWASP session guidance
- Skill: `tlc-spec-driven`

**Done when:**

- [ ] Only the configured cookie is accepted as a session carrier.
- [ ] Missing, malformed, expired and revoked sessions return the same `401` envelope and clear the cookie.
- [ ] Unsafe cross-origin requests fail before service invocation.
- [ ] API tests add at least 8 dependency cases including URL/body/header token rejection.
- [ ] Full gate passes with no test deletion.

**Tests:** API integration
**Gate:** full
**Commit:** `feat(auth): require cookie principals and trusted origin`

### T12: Enforce the server-side role policy

**What:** Project visible snapshots and authorize/merge candidate changes from immutable principals.
**Where:** `app/authorization.py`
**Depends on:** T11
**Reuses:** Current UI visibility outcomes as test expectations.
**Requirement:** MT-04, MT-07

**Tools:**

- MCP: NONE
- Skill: `tlc-spec-driven`

**Done when:**

- [ ] Admin, manager, seller, assistant and billing matrices match the approved spec.
- [ ] Non-admin snapshots omit unauthorized Leads/Deals and own only their preferences/notifications.
- [ ] Forged user/profile/config/admin changes return forbidden.
- [ ] Merge preserves every invisible canonical record and rejects cross-tenant references.
- [ ] Authorization tests add at least 15 cases, one per role/action branch and edge case.
- [ ] Quick gate passes with no test deletion.

**Tests:** unit
**Gate:** quick
**Commit:** `feat(authz): enforce workspace role policy`

### T13: Expose tenant locator and cookie-session routes

**What:** Wire public auth routes, protected dependencies, cookie flags, no-store headers and tenant SPA fallback.
**Where:** `app/main.py`
**Depends on:** T12
**Reuses:** Current error envelope, middleware, app factory and static directory injection.
**Requirement:** MT-01, MT-02, MT-03, MT-04, MT-06

**Tools:**

- MCP: NONE
- Skill: `tlc-spec-driven`

**Done when:**

- [ ] `/`, `/{slug}`, locate, login, session and logout contracts match the design.
- [ ] Every `/api/workspace*` route requires a principal and never accepts tenant authority.
- [ ] Cookie attributes are exact and protected responses send `Cache-Control: no-store`.
- [ ] Reserved/static/API paths cannot be consumed as tenant slugs.
- [ ] API tests add at least 15 cases for routing, generic failures, cookies, no-store, anonymous/forbidden and slug/session mismatch.
- [ ] Full gate passes with no test deletion.

**Tests:** API integration
**Gate:** full
**Commit:** `feat(api): add tenant login and protect workspace routes`

### T14: Apply authorization to versioned workspace operations

**What:** Replace fixed-workspace service methods with principal-scoped load, projection, authorized merge and tenant-safe restore.
**Where:** `app/services/workspace.py`
**Depends on:** T13
**Reuses:** Existing locks, version conflicts, validation and result counts.
**Requirement:** MT-03, MT-04, MT-07

**Tools:**

- MCP: NONE
- Skill: `tlc-spec-driven`

**Done when:**

- [ ] Every method receives trusted principal scope and locks only that workspace.
- [ ] Load/result use server projection; save validates and reconciles the authorized merge.
- [ ] Bootstrap/reset/restore/deleted/import-related state is admin-only.
- [ ] Two-tenant service/API tests add at least 15 negative cases for read, write, delete, restore, version conflict and each role.
- [ ] Full gate passes with exact unchanged-other-tenant assertions.

**Tests:** PostgreSQL + API integration
**Gate:** full
**Commit:** `fix(workspace): enforce tenant and role on operations`

### T15: Provide transactional tenant administration

**What:** Add a local CLI for create-tenant, activate-default, set-user-password and revoke-user-sessions.
**Where:** `app/admin.py`
**Depends on:** T14
**Reuses:** Database transaction, shared password hasher and auth revocation.
**Requirement:** MT-05, MT-06

**Tools:**

- MCP: NONE
- Skill: `tlc-spec-driven`

**Done when:**

- [ ] Password input uses `getpass` and never appears in args, stdout, logs or persisted plaintext.
- [ ] Default activation preserves internal ID/data and atomically assigns slug/name/admin/hash/status.
- [ ] Duplicate/invalid input rolls back the full command.
- [ ] No HTTP tenant-creation route exists.
- [ ] CLI tests add at least 8 cases including captured output, duplicate rollback and existing/new admin binding.
- [ ] Full gate passes with no test deletion.

**Tests:** PostgreSQL integration
**Gate:** full
**Commit:** `feat(admin): provision tenants and first admins safely`

### T16: Add tenant locator, login and logout UI states

**What:** Add the public locator/login flow and authenticated route state without exposing a token to JavaScript.
**Where:** `app/static/index.html`
**Depends on:** T15
**Reuses:** Current CSS system, dialogs, toast and responsive layout.
**Requirement:** MT-01, MT-02, MT-06

**Tools:**

- MCP: browser automation through existing Playwright harness
- Skill: `tlc-spec-driven`

**Done when:**

- [ ] `/` accepts slug/same-origin URL and `/{slug}` shows tenant login.
- [ ] Login uses same-origin fetch and generic failure; password is cleared after submit.
- [ ] Session state comes from `/api/auth/session`; logout clears in-memory state and returns to login.
- [ ] No script reads/writes the session cookie or token.
- [ ] Browser suite adds at least 8 scenarios for locator, validation, login success/failure, route mismatch, refresh and logout.
- [ ] Full gate passes with no test deletion.

**Tests:** browser e2e
**Gate:** full
**Commit:** `feat(ui): add tenant login and logout flow`

### T17: Remove profile impersonation and commercial local cache

**What:** Replace the profile selector with immutable session identity and namespace UI-only preferences by tenant/user.
**Where:** `app/static/index.html`
**Depends on:** T16
**Reuses:** Current render/filter/view preference functions.
**Requirement:** MT-03, MT-04, MT-06

**Tools:**

- MCP: browser automation through existing Playwright harness
- Skill: `tlc-spec-driven`

**Done when:**

- [ ] `currentUserId` cannot be changed by UI or Web Storage.
- [ ] The profile selector and change handler are removed; identity is read-only.
- [ ] Commercial snapshots are not persisted; UI preferences use tenant/user-namespaced keys.
- [ ] Forged/stale cache never unlocks a control or changes visible records.
- [ ] Existing 69 UI scenarios are updated without weakening outcomes and at least 10 new cache/identity/role-negative scenarios pass.
- [ ] Full gate passes with no test deletion.

**Tests:** browser e2e
**Gate:** full
**Commit:** `fix(ui): remove impersonation and tenant data cache`

### T18: Verify Argon2 wheels in the offline bundle

**What:** Extend the deterministic bundle builder to assert all new dependencies resolve to CPython 3.11 Windows x64 wheels.
**Where:** `scripts/build_manual_windows_pg11_bundle.py`
**Depends on:** T17
**Reuses:** Existing `--only-binary`, platform, ABI and manifest checks.
**Requirement:** MT-05, MT-07

**Tools:**

- MCP: package index only during the explicitly authorized bundle-build step
- Skill: `tlc-spec-driven`

**Done when:**

- [ ] Bundle validation detects missing, source-only or wrong-platform Argon2 artifacts.
- [ ] No online install path is introduced on the server.
- [ ] Bundle tests add at least 4 dependency/wheel mutations.
- [ ] Build gate passes with no test deletion.

**Tests:** unit + packaging contract
**Gate:** build
**Commit:** `build(windows): verify offline argon2 wheels`

### T19: Add secure auth runtime settings to the Windows launcher

**What:** Load and validate origin/cookie/TTL settings while preserving loopback-only runtime and secret handling.
**Where:** `deploy/manual-windows-pg11/start-smart-crm.ps1`
**Depends on:** T18
**Reuses:** Current environment allowlist and fail-fast validation.
**Requirement:** MT-02, MT-05, MT-06

**Tools:**

- MCP: NONE
- Skill: `tlc-spec-driven`

**Done when:**

- [ ] Production origin is exactly `https://sc2030.brbots.com` and secure cookies cannot be disabled in production mode.
- [ ] TTL/throttle bounds reject unsafe values before Uvicorn starts.
- [ ] Secrets remain outside Git and are removed from process environment on exit.
- [ ] PowerShell contract tests add at least 4 valid/invalid settings cases.
- [ ] Build gate passes with no test deletion.

**Tests:** deployment contract
**Gate:** build
**Commit:** `fix(windows): validate secure auth runtime settings`

### T20: Document the auth environment contract

**What:** Add non-secret secure authentication settings and placeholders required by the launcher.
**Where:** `deploy/manual-windows-pg11/server.env.example`
**Depends on:** T19
**Reuses:** Existing external secret file contract.
**Requirement:** MT-02, MT-05

**Tools:**

- MCP: NONE
- Skill: `tlc-spec-driven`

**Done when:**

- [ ] Example contains exact origin, secure-cookie, TTL and throttle keys with safe defaults.
- [ ] No real password, session token or tenant credential is present.
- [ ] Contract tests add at least 2 parity/secret assertions.
- [ ] Build gate passes with no test deletion.

**Tests:** deployment contract
**Gate:** build
**Commit:** `docs(windows): define secure auth environment`

### T21: Prepare Apache for path tenants and app authentication

**What:** Preserve proxying for `/{slug}`, security headers and a documented Basic-Auth transition without changing a server.
**Where:** `deploy/manual-windows-pg11/httpd-sc2030.conf.example`
**Depends on:** T20
**Reuses:** Existing TLS, HSTS, ACME exception and loopback ProxyPass.
**Requirement:** MT-01, MT-02, MT-05

**Tools:**

- MCP: official Apache docs if syntax must be rechecked
- Skill: `tlc-spec-driven`

**Done when:**

- [ ] Root, tenant paths and `/api` proxy unchanged to `127.0.0.1:8080`.
- [ ] Shared Basic Auth removal is explicit for cutover and cannot be mistaken for an automatic deployment.
- [ ] Forwarded HTTPS/origin behavior required for Secure cookie validation is documented.
- [ ] Apache contract tests add at least 4 assertions for routes, headers, Basic transition and loopback.
- [ ] Build gate passes with no test deletion.

**Tests:** deployment contract
**Gate:** build
**Commit:** `docs(apache): prepare tenant path authentication`

### T22: Add migration and provisioning gates to the offline runbook

**What:** Document backup, Alembic, default activation, first admin, count/checksum, UAT and rollback steps without executing them.
**Where:** `deploy/manual-windows-pg11/LEIA-ME.md`
**Depends on:** T21
**Reuses:** Current local gate, backup/rollback and no-service-restart policy.
**Requirement:** MT-05, MT-06, MT-07

**Tools:**

- MCP: NONE
- Skill: `tlc-spec-driven`

**Done when:**

- [ ] Runbook requires verified backup before migration and explicit operator values for default tenant/admin.
- [ ] Pre/post counts, tenant isolation probes, login/logout and cookie checks are exact.
- [ ] It states that production migration, Apache edit, restart and deploy require separate authorization.
- [ ] Runbook contract tests add at least 2 failure-order assertions.
- [ ] Build gate passes with no test deletion.

**Tests:** documentation contract
**Gate:** build
**Commit:** `docs(windows): add multitenant cutover gates`

### T23: Replace prototype security warnings with the real operating model

**What:** Document tenant URLs, login/session behavior, local setup, admin provisioning and remaining limitations.
**Where:** `README.md`
**Depends on:** T22
**Reuses:** Existing development, verification and PostgreSQL sections.
**Requirement:** MT-01, MT-02, MT-03, MT-04, MT-05, MT-06

**Tools:**

- MCP: NONE
- Skill: `tlc-spec-driven`

**Done when:**

- [ ] README no longer describes the profile selector or anonymous API as current behavior.
- [ ] Local insecure-cookie exception, if retained for development, is explicitly impossible in production mode.
- [ ] Admin commands contain placeholders and hidden prompts, never example plaintext passwords.
- [ ] Final Build gate passes and records exact backend/UI counts.
- [ ] Independent Verifier runs spec-anchored checks and discrimination mutations before completion.

**Tests:** none for prose; build/contract gate
**Gate:** build
**Commit:** `docs(readme): document secure multitenancy`

---

## Phase Execution Map

```text
Phase 1: T1 -> T2 -> T3 -> T4 -> T5 -> T6
                                      |
Phase 2:                             T7 -> T8 -> T9 -> T10 -> T11 -> T12 -> T13
                                                                            |
Phase 3:                                                                   T14 -> T15 -> T16 -> T17
                                                                                                    |
Phase 4:                                                                                           T18 -> T19 -> T20 -> T21 -> T22 -> T23
```

Each task depends on its immediate predecessor. Cross-phase dependencies are T7 on T6, T14 on T13 and T18 on T17. There is no parallel execution inside a phase.

---

## Task Granularity Check

| Task | Scope | Status |
| ---- | ----- | ------ |
| T1 | One dependency manifest | OK |
| T2 | One runtime manifest | OK |
| T3 | One declarative model module | OK, cohesive schema model |
| T4 | One Alembic revision | OK, atomic migration |
| T5 | One transaction boundary | OK |
| T6 | One repository module | OK, cohesive tenant scoping |
| T7 | One schema module | OK |
| T8 | One security utility module | OK |
| T9 | One auth repository | OK |
| T10 | One auth service | OK |
| T11 | One dependency module | OK |
| T12 | One authorization policy | OK |
| T13 | One API composition module | OK |
| T14 | One workspace service | OK |
| T15 | One admin CLI module | OK |
| T16 | One frontend auth state in monolith | OK, one user-facing slice |
| T17 | One frontend identity/cache state in monolith | OK, separate reversible slice |
| T18 | One bundle builder | OK |
| T19 | One launcher | OK |
| T20 | One env template | OK |
| T21 | One Apache template | OK |
| T22 | One offline runbook | OK |
| T23 | One project README | OK |

---

## Diagram-Definition Cross-Check

| Task | Depends On (task body) | Diagram Shows | Status |
| ---- | ---------------------- | ------------- | ------ |
| T1 | None | Start | Match |
| T2 | T1 | T1 -> T2 | Match |
| T3 | T2 | T2 -> T3 | Match |
| T4 | T3 | T3 -> T4 | Match |
| T5 | T4 | T4 -> T5 | Match |
| T6 | T5 | T5 -> T6 | Match |
| T7 | T6 | T6 -> T7 | Match |
| T8 | T7 | T7 -> T8 | Match |
| T9 | T8 | T8 -> T9 | Match |
| T10 | T9 | T9 -> T10 | Match |
| T11 | T10 | T10 -> T11 | Match |
| T12 | T11 | T11 -> T12 | Match |
| T13 | T12 | T12 -> T13 | Match |
| T14 | T13 | T13 -> T14 | Match |
| T15 | T14 | T14 -> T15 | Match |
| T16 | T15 | T15 -> T16 | Match |
| T17 | T16 | T16 -> T17 | Match |
| T18 | T17 | T17 -> T18 | Match |
| T19 | T18 | T18 -> T19 | Match |
| T20 | T19 | T19 -> T20 | Match |
| T21 | T20 | T20 -> T21 | Match |
| T22 | T21 | T21 -> T22 | Match |
| T23 | T22 | T22 -> T23 | Match |

---

## Test Co-location Validation

| Task | Code Layer Created/Modified | Matrix Requires | Task Says | Status |
| ---- | --------------------------- | --------------- | --------- | ------ |
| T1 | Dependency config | build/contract | build/contract | OK |
| T2 | Runtime config | build/contract | build/contract | OK |
| T3 | Models | unit + integration | unit + integration | OK |
| T4 | Migration | PostgreSQL integration | PostgreSQL integration | OK |
| T5 | Database boundary | PostgreSQL integration | PostgreSQL integration | OK |
| T6 | Workspace repository | PostgreSQL integration | PostgreSQL integration | OK |
| T7 | Schemas | unit | unit | OK |
| T8 | Security utility | unit | unit | OK |
| T9 | Auth repository | PostgreSQL integration | PostgreSQL integration | OK |
| T10 | Auth service | unit + integration | unit + integration | OK |
| T11 | Auth dependency | API integration | API integration | OK |
| T12 | Authorization policy | unit | unit | OK |
| T13 | API/routes | API integration | API integration | OK |
| T14 | Workspace service | PostgreSQL + API integration | PostgreSQL + API integration | OK |
| T15 | Admin CLI | PostgreSQL integration | PostgreSQL integration | OK |
| T16 | Frontend auth | browser e2e | browser e2e | OK |
| T17 | Frontend identity/cache | browser e2e | browser e2e | OK |
| T18 | Bundle builder | unit + packaging contract | unit + packaging contract | OK |
| T19 | Windows launcher | deployment contract | deployment contract | OK |
| T20 | Env template | deployment contract | deployment contract | OK |
| T21 | Apache template | deployment contract | deployment contract | OK |
| T22 | Offline runbook | documentation contract | documentation contract | OK |
| T23 | README | build/contract | build/contract | OK |

---

## Requirement-to-Task Traceability

| Requirement | Tasks | Planned Evidence |
| ----------- | ----- | ---------------- |
| MT-01 Tenant locator/login | T7, T8, T9, T10, T13, T16 | Schema, timing, throttle, route and browser tests |
| MT-02 Opaque session | T3, T7-T11, T13, T16, T19-T20 | Model, crypto, lifecycle, cookie and runtime tests |
| MT-03 Tenant isolation | T3-T6, T11-T14, T17 | Identical-ID negative tests, scoped SQL, RLS and forged request tests |
| MT-04 Server authorization | T11-T14, T16-T17 | Role matrix, projection/merge, API 403 and immutable identity tests |
| MT-05 Migration/provisioning | T1-T4, T8, T15, T18-T23 | Preservation/checksum, CLI rollback, wheel and runbook gates |
| MT-06 Secure operations | T3, T9-T11, T13, T15-T17, T19-T23 | Audit/no-store/logout/revocation/log-secret tests |
| MT-07 Edge cases/concurrency | T4-T6, T9-T14, T18, T22 | Concurrent lock/version tests, missing RLS context and fail-fast package/migration tests |

**Coverage:** 7 requirement groups, 7 mapped, 0 unmapped.

---

## Execute Entry Gate

Before T1 starts:

1. The user approves or overrides every `Confirmed? n` default in `spec.md`.
2. `spec.md`, `context.md`, `design.md` and `tasks.md` statuses change to Approved in one documentation commit.
3. Proposed project-level decisions are appended section-safely to `.specs/STATE.md`; the existing Handoff is not overwritten.
4. The current dirty files `.specs/features/crm-mvp/tasks.md` and `RUNBOOK_DEPLOY_WINDOWS_SERVER_2016.md` remain untouched.
5. The local dev dependencies and PostgreSQL baseline are made runnable; the 91 backend and 69 UI baseline is executed and recorded.
6. `validate_tasks.py` is run fresh.
7. With 23 tasks, the skill requires an offer to use sequential task-batch sub-agents before execution. No agent is dispatched without the user's confirmation.
8. No push, deploy, production DB migration, Apache edit or server action is authorized by plan approval.
