# Convites de usuários e recuperação de senha — Tasks

## Execution Protocol (MANDATORY -- do not skip)

Implement these tasks with the `tlc-spec-driven` skill: **activate it by name and follow its Execute flow and Critical Rules.** Do not search for skill files by filesystem path. The skill is the source of truth for the full flow (per-task cycle, sub-agent delegation, adequacy review, Verifier, discrimination sensor).

**If the skill cannot be activated, STOP and tell the user - do not proceed without it.**

---

**Design**: `.specs/features/user-invitations-password-recovery/design.md`  
**Status**: In Progress

---

## Test Coverage Matrix

> Generated from codebase, project guidelines, and spec - confirm before Execute. Guidelines found: `pyproject.toml`, `package.json`, `.github/workflows/release-windows-pg11.yml`; no project lint/formatter command is configured, so strong defaults apply to behavioral coverage.

| Code Layer | Required Test Type | Coverage Expectation | Location Pattern | Run Command |
| ---------- | ------------------ | -------------------- | ---------------- | ----------- |
| Domain/service | integration | All branches; 1:1 to the applicable acceptance criteria; every listed edge case | `tests/backend/test_*service.py` | `python -m pytest -q tests/backend` |
| Repository/data access | integration | Locks, uniqueness, RLS, expiry, invalidation, replay and database error paths | `tests/backend/test_*repository.py` | `python -m pytest -q tests/backend` |
| SMTP/security utility | unit | TLS modes, redaction, DPAPI boundary, timeouts and all failure classifications | `tests/backend/test_mail.py`, `tests/backend/test_security.py` | `python -m pytest -q tests/backend` |
| Pydantic schema/validation | unit | Boundary values, normalization and public error-shape invariants | `tests/backend/test_schemas.py` | `python -m pytest -q tests/backend/test_schemas.py` |
| FastAPI route/runtime | integration | Every new route: happy path, authorization, origin, invalid input, limits and dependency failure | `tests/backend/test_account_access_api.py` | `python -m pytest -q tests/backend` |
| Browser UI | e2e | Admin, invite, resend, cancel, accept, reset, error, loading and mobile flows | `tests/ui-prototype.spec.cjs` | `pnpm test` |
| Migration/deployment | integration | Upgrade, RLS, idempotency, allowlist, DPAPI SMTP config, package integrity and safe startup failure | `tests/backend/test_migrations.py`, `tests/backend/test_manual_windows_pg11_*.py`, `tests/backend/test_windows_multitenant_bundle.py` | `python -m pytest -q tests/backend` |
| Plain entity/model declaration | unit | Metadata exposes the designed fields and constraints and contains no raw-secret field | `tests/backend/test_models.py` | `python -m pytest -q tests/backend` |

## Gate Check Commands

> Generated from codebase - confirm before Execute. The baseline before this feature is 859 backend tests and 122 UI scenarios; counts may only increase. No standalone lint/formatter command exists in the repository.

| Gate Level | When to Use | Command |
| ---------- | ----------- | ------- |
| Quick | After backend model, repository, service, utility or schema tasks | `python -m pytest -q tests/backend` |
| Full | After route or browser integration tasks | `python -m pytest -q` followed by `pnpm test` |
| Build | After a phase and after deployment changes | `python -m pytest -q`, `pnpm test`, `python scripts/build_manual_windows_pg11_bundle.py --version v0.3.3`, then `python scripts/verify_manual_windows_pg11_deployment.py --bundle dist/smart-crm-manual-pg11-v0.3.3.zip` |

---

## Execution Plan

Phases are ordered and run sequentially. Every task includes its own tests and atomic Conventional Commit.

### Phase 1: Tenant and Security Foundation

```text
T1 → T2 → T3 → T4 → T5
```

### Phase 2: Account Lifecycle

```text
T5 → T6 → T7 → T8 → T9 → T10
```

### Phase 3: API and Browser Experience

```text
T10 → T11 → T12 → T13
```

### Phase 4: Windows Deployment

```text
T13 → T14
```

---

## Task Breakdown

### T1: Model tenant account-action tokens

**What**: Add the tenant SQLAlchemy entity and invariants for invitation and password-reset token metadata without any raw token field.  
**Where**: `app/models.py`  
**Depends on**: None  
**Reuses**: `CrmUser`, `TimestampMixin`, workspace foreign-key conventions  
**Requirement**: SEC-01, SEC-02, SEC-06

**Tools**:

- MCP: NONE
- Skill: `tlc-spec-driven`

**Done when**:

- [x] `AccountActionToken` contains purpose, digest, expiry, consumption, invalidation and delivery state from the approved design.
- [x] Database constraints reject unsupported purpose/delivery states and the entity contains no raw token or password field.
- [x] Existing model imports and metadata load successfully and metadata assertions cover every designed invariant.
- [x] Quick gate passes without reducing the 859-test backend baseline.

**Tests**: unit — extend `tests/backend/test_models.py` with metadata and no-secret-field assertions.  
**Gate**: quick  
**Commit**: `feat(auth): model tenant account action tokens`

---

### T2: Persist account-action tokens with tenant RLS

**What**: Add the next tenant Alembic migration with table, constraints, indexes, foreign keys and workspace RLS for account-action tokens.  
**Where**: `migrations/versions/`  
**Depends on**: T1  
**Reuses**: current tenant migration RLS and revision-test patterns  
**Requirement**: SEC-01, SEC-06, SEC-07

**Tools**:

- MCP: NONE
- Skill: `tlc-spec-driven`

**Done when**:

- [x] Upgrade from the current tenant head creates the exact schema designed in T1.
- [x] RLS permits only the transaction workspace and prevents cross-workspace reads/writes.
- [x] Digest uniqueness, user lookup indexes and valid state constraints are verified against PostgreSQL.
- [x] Migration integration tests pass and the expected tenant head is updated only through the migration contract.
- [x] Quick gate passes with no test deletion.

**Tests**: integration — update migration tests under `tests/backend/test_migrations.py` for upgrade, constraints and RLS.  
**Gate**: quick  
**Commit**: `feat(migrations): persist tenant account action tokens`

**Execution record**: T1 and T2 were merged into one atomic commit under the task merge-forward rule. Adding the model to `Base.metadata` made the existing migration metadata assertion require the corresponding Alembic table, so neither half had an independently green gate. The combined gate passed with 862 backend tests; no existing assertion was weakened, deleted or skipped.

---

### T3: Add the token repository

**What**: Implement the tenant repository for issuing, locking, invalidating, consuming and recording delivery of account-action tokens.  
**Where**: `app/repositories/account_actions.py`  
**Depends on**: T2  
**Reuses**: SQLAlchemy repository and `TenantDatabaseRouter` transaction patterns  
**Requirement**: INV-01, INV-03, INV-04, INV-05, ACCEPT-04, ACCEPT-06, RESET-02, RESET-06, SEC-06

**Tools**:

- MCP: NONE
- Skill: `tlc-spec-driven`

**Done when**:

- [x] Creating a token invalidates the applicable predecessor under a row lock.
- [x] Lookup accepts only matching purpose, unexpired and unterminated records.
- [x] Concurrent consumption permits exactly one winner.
- [x] Delivery failure invalidates the undelivered token while preserving audit metadata.
- [x] Repository integration tests cover issue, resend, cancel, expiry, replay, cross-purpose and concurrent consume.
- [x] Quick gate passes with no test deletion.

**Tests**: integration — create `tests/backend/test_account_action_repository.py`.  
**Gate**: quick  
**Commit**: `feat(auth): add tenant account action repository`

**Evidence**: 6 focused repository integration tests and the 868-test backend gate passed. Concurrent issue and consume tests prove the row-lock and single-use outcomes; no test was deleted, weakened or skipped.

---

### T4: Generalize central throttling and security events

**What**: Extend the control repository and audit service with generic request buckets and redacted event types for invitation and password recovery.  
**Where**: `app/control_database.py`, `app/control_models.py`, `migrations_control/versions/d5f0a8c3e7b2_expand_account_action_throttle_buckets.py`, packaged control-head wiring and their tests
**Depends on**: T3  
**Reuses**: `LoginThrottle`, `SecurityEvent`, existing login failure limits and correlation digests  
**Requirement**: SEC-02, SEC-03, SEC-04, SEC-05, RESET-01

**Tools**:

- MCP: NONE
- Skill: `tlc-spec-driven`

**Done when**:

- [x] Existing login throttling remains backward compatible.
- [x] Account buckets block at 5/15 minutes and IP buckets at 30/15 minutes with atomic increments.
- [x] Audit interfaces accept only sanitized codes and digests and never accept token/password fields.
- [x] Tests cover window reset, active block, concurrent increments and separate bucket namespaces.
- [x] Quick gate passes with no test deletion.

**Tests**: integration — extend `tests/backend/test_control_repository.py`, `tests/backend/test_control_models.py`, `tests/backend/test_control_migrations.py`, `tests/backend/test_auth_service.py` and packaged control-head tests.
**Gate**: quick  
**Commit**: `feat(security): generalize account action throttling`

**Execution record**: The implementation surface expanded from the planned repository-only change because the existing `LoginThrottle` database CHECK allowed only `account` and `ip`; the designed `invite_*` and `reset_*` namespaces could not be persisted faithfully without a model and control migration change. The correction preserves both login bucket types, advances and packages the control head, and keeps namespaces explicit rather than encoding them into opaque digests. Focused model, migration, repository, audit and packaging tests passed; the full backend gate passed with 876 tests and no deletion, weakening or skip.

---

### T5: Add a secure SMTP delivery adapter

**What**: Implement injectable SMTP delivery and fixed invitation/reset templates with TLS, timeout and redacted failures.  
**Where**: `app/mail.py`  
**Depends on**: T4  
**Reuses**: Python `smtplib`, `EmailMessage`, `DpapiProtector` boundary and current dependency-injection style  
**Requirement**: INV-02, INV-03, RESET-02, RESET-03, SEC-02

**Tools**:

- MCP: NONE
- Skill: `tlc-spec-driven`

**Done when**:

- [x] Adapter supports only `starttls` and `implicit_tls` and rejects unencrypted transport.
- [x] Invitation and reset messages include company identity, plain-text and HTML bodies, and a single action link.
- [x] Exceptions expose stable failure codes without SMTP credentials, token or message body.
- [x] An in-memory sender supports deterministic service and route tests.
- [x] Unit tests cover success, both TLS modes, authentication rejection, recipient rejection, timeout and escaping.
- [x] Quick gate passes with no test deletion.

**Tests**: unit — create `tests/backend/test_mail.py`.  
**Gate**: quick  
**Commit**: `feat(mail): add secure smtp delivery adapter`

**Evidence**: 10 focused unit tests and the 886-test backend gate passed. The tests exercise STARTTLS ordering, implicit TLS, TLS-only configuration, fixed invitation/reset alternatives, HTML and header injection defenses, password-redacted configuration, deterministic capture, and stable redacted authentication, recipient and timeout failures; no test was deleted, weakened or skipped.

---

### T6: Implement the administrative invitation lifecycle

**What**: Implement create, resend and cancel invitation rules with user-state transitions, SMTP result handling and security audit.  
**Where**: `app/services/account_access.py`  
**Depends on**: T5  
**Reuses**: token repository, `TenantDatabaseRouter`, `MailSender`, authorization principals and `SecurityAuditService`  
**Requirement**: INV-01, INV-02, INV-03, INV-04, INV-05, INV-06, INV-07, INV-08, INV-09, INV-10, SEC-05

**Tools**:

- MCP: NONE
- Skill: `tlc-spec-driven`

**Done when**:

- [x] State matrix for new, Pendente, Ativo, Cancelado and Inativo accounts matches the spec.
- [x] Two concurrent invitations for the same normalized email persist one user and at most one valid token.
- [x] SMTP is called only after the first transaction commits and failure returns `deliveryStatus=failed` with user still Pendente.
- [x] Cancel disables authentication and invalidates every live invitation.
- [x] Non-Administrator calls cause no database or SMTP side effect.
- [x] Integration tests map 1:1 to INV-01 through INV-10 and the invitation edge cases.
- [x] Quick gate passes with no test deletion.

**Tests**: integration — create `tests/backend/test_account_access_service.py` with invitation scenarios.  
**Gate**: quick  
**Commit**: `feat(users): implement invitation lifecycle`

**Evidence**: 11 focused PostgreSQL integration tests and the 897-test backend gate passed. The suite proves the complete account-state matrix, delivery only after commit, redacted audit events, failed-delivery invalidation, one live token under concurrent invitations, cancellation, non-administrator zero side effects, administrator-role invitations, and login denial for pending/cancelled accounts. Assignment eligibility remains protected by the existing active-only selector and receives its persistence-boundary regression coverage in T9 and API/UI coverage in T12. No test was deleted, weakened or skipped.

---

### T7: Implement invitation inspection and acceptance

**What**: Extend the account-access service with public inspection and single-use invitation acceptance.  
**Where**: `app/services/account_access.py`  
**Depends on**: T6  
**Reuses**: password hasher, tenant lookup, token repository and `auth_version`  
**Requirement**: ACCEPT-01, ACCEPT-02, ACCEPT-03, ACCEPT-04, ACCEPT-05, ACCEPT-06, SEC-01, SEC-06, SEC-07

**Tools**:

- MCP: NONE
- Skill: `tlc-spec-driven`

**Done when**:

- [x] Inspection exposes only company and invited email for a valid token and creates no session.
- [x] Acceptance atomically consumes the token, stores Argon2id, activates authentication and increments `auth_version` once.
- [x] Invalid password leaves the token usable until its natural end.
- [x] Invalid, expired, replaced, cancelled, replayed and wrong-tenant tokens share one public failure.
- [x] Concurrent acceptance has exactly one success.
- [x] Integration tests map 1:1 to ACCEPT-01 through ACCEPT-06.
- [x] Quick gate passes with no test deletion.

**Tests**: integration — extend `tests/backend/test_account_access_service.py` with acceptance scenarios.  
**Gate**: quick  
**Commit**: `feat(auth): implement invitation acceptance`

**Evidence**: 12 new PostgreSQL integration tests (23 focused tests in total) and the backend gate passed: 909 tests, 857 passed; the only 52 failures are the pre-existing Windows PowerShell suites (`test_github_release_delivery.py`, `test_manual_windows_pg11_outcomes.py`), identical to the 897-test baseline on the same Linux/PostgreSQL 16 runner and requiring the Windows gate. The suite proves inspection returns only company and e-mail without consuming or auditing, acceptance stores Argon2id, activates, consumes once and increments `auth_version` exactly once (including a reused cancelled account), no session is created and the invitee then signs in through login, absent/unknown/expired/used/cancelled-while-open/replaced/unknown-tenant tokens share one public failure without changing the account, wrong-tenant links open only the presented tenant, invalid passwords are rejected before any tenant access and keep the token usable, four concurrent acceptances have exactly one winner, and acceptance locks user before token like cancel/resend. Mutation checks on version increment, user lock, pending-state check, consumption and authentication enablement were all detected. Password bounds reuse `MIN_PASSWORD_LENGTH`/`MAX_PASSWORD_LENGTH`; the 12→8 change and the exact 8-character boundary remain owned by T10. ACCEPT-03 redirection is UI and is completed in T13. No test was deleted, weakened or skipped.

---

### T8: Implement password recovery and session invalidation

**What**: Extend the account-access service with anti-enumeration recovery requests, reset consumption and session invalidation.  
**Where**: `app/services/account_access.py`  
**Depends on**: T7  
**Reuses**: generalized throttling, `AuthService`, `AuthSession`, token repository and audit service  
**Requirement**: RESET-01, RESET-02, RESET-03, RESET-04, RESET-05, RESET-06, SEC-03, SEC-04, SEC-05, SEC-06, SEC-07

**Tools**:

- MCP: NONE
- Skill: `tlc-spec-driven`

**Done when**:

- [x] Existing/non-existing tenant, user state, SMTP failure and throttling have the same public request result.
- [x] Only active enabled users receive a reset token and a new request invalidates its predecessor.
- [x] Reset atomically changes Argon2id hash, consumes once and increments `auth_version` once.
- [x] All central sessions are revoked; `auth_version` independently rejects a stale session if cleanup fails.
- [x] Old password, stale session and replayed/wrong-tenant tokens fail after reset.
- [x] Integration tests map 1:1 to RESET-01 through RESET-06 and both rate limits.
- [x] Quick gate passes with no test deletion.

**Tests**: integration — extend `tests/backend/test_account_access_service.py` and `tests/backend/test_auth_service.py`.  
**Gate**: quick  
**Commit**: `feat(auth): implement password recovery`

**Evidence**: 12 new PostgreSQL integration tests (35 focused tests in total) against a real control schema, so throttling, session creation and revocation run through `ControlRepository` and `AuthService`. They prove: unknown/unavailable tenant, unknown or malformed e-mail, Pendente/Inativo/Cancelado/auth-disabled accounts, SMTP failure and both rate limits all return the same `None` result, create no token or account and keep audit events free of e-mail and raw token (RESET-01, RESET-03); only an Ativo, enabled user receives a 48-hour `/{slug}/reset-password#token=` link and a new request replaces its predecessor (RESET-02); reset stores Argon2id, consumes once, increments `auth_version` once, revokes every central session, creates none, and old password, stale sessions and the replayed link then fail (RESET-04, RESET-05); when central revocation fails twice the reset still completes, the failure is audited and `AuthService.current_session` rejects the stale session through the version mismatch; absent, oversized, unknown, expired, used, replaced, undelivered, invitation-purpose, inactivated-after-request, unknown-tenant and unavailable-tenant links share one public failure without changes (RESET-06, SEC-06); a link presented to another tenant opens only that tenant (SEC-07); invalid passwords are rejected before any tenant access; four concurrent resets have one winner; the 6th request per account and the 31st per IP in 15 minutes are silently not sent, and the account bucket reopens after the window (SEC-03, SEC-04). Mutation checks on the version increment, session revocation, throttle check, account eligibility and revocation retry were all detected. Stale-session rejection is covered through `AuthService` from the account-access suite; `tests/backend/test_auth_service.py` already proves the version-mismatch revocation and needed no change. Delivery is synchronous, so SMTP latency remains observable at the service level; T11 must keep the public 202 independent of it. No test was deleted, weakened or skipped.

**Windows gate**: full backend suite on Windows 11 with Docker PostgreSQL 17 passed with 921 tests (909 after T7 + 12 new), 6 pre-existing warnings, including the PowerShell packaging suites.

---

### T9: Protect server-managed account fields from workspace writes

**What**: Restrict user snapshot reconciliation so browser writes cannot change credentials, access state, normalized identity or invitation metadata.  
**Where**: `app/repositories/workspace.py`  
**Depends on**: T8  
**Reuses**: current reconciliation and soft-delete patterns  
**Requirement**: INV-10, SEC-02, INVUI-01

**Tools**:

- MCP: NONE
- Skill: `tlc-spec-driven`

**Done when**:

- [ ] Existing hash, `auth_enabled`, `auth_version`, normalized email and protected status survive workspace updates.
- [ ] Allowed profile fields still update without breaking references.
- [ ] Pending/cancelled/inactive users cannot be made assignable through a crafted snapshot.
- [ ] Repository tests prove protected-field preservation and normal profile editing.
- [ ] Quick gate passes with no test deletion.

**Tests**: integration — extend `tests/backend/test_repository.py` and `tests/backend/test_workspace_service.py`.  
**Gate**: quick  
**Commit**: `fix(users): preserve server managed account fields`

---

### T10: Define account-access API contracts

**What**: Add validated Pydantic requests/responses for administration, inspection, acceptance, forgot-password and reset-password and align the global password range to 8–128.  
**Where**: `app/schemas.py`  
**Depends on**: T9  
**Reuses**: `AuthContractModel`, email normalization, tenant slug normalization and shared password constants  
**Requirement**: INV-01, ACCEPT-01, ACCEPT-05, RESET-01, RESET-04, INVUI-02, INVUI-05

**Tools**:

- MCP: NONE
- Skill: `tlc-spec-driven`

**Done when**:

- [ ] All request fields have explicit bounds and normalized email/slug behavior.
- [ ] Password and confirmation require equality and accept exactly 8–128 characters.
- [ ] Public response models contain no token, hash, DSN or internal availability detail.
- [ ] Login and new-account validation use the same password bounds.
- [ ] Boundary and redaction unit tests pass.
- [ ] Quick gate passes with no test deletion.

**Tests**: unit — extend `tests/backend/test_schemas.py` and `tests/backend/test_security.py`.  
**Gate**: quick  
**Commit**: `feat(api): define account access contracts`

---

### T11: Expose and wire account-access routes

**What**: Add authenticated invitation routes and public invitation/reset routes, inject the service into the app factory and preserve origin/cookie protections.  
**Where**: `app/main.py`  
**Depends on**: T10  
**Reuses**: `create_app` dependency injection, principal resolver, expected-origin check and standard error payloads  
**Requirement**: INV-01, INV-04, INV-05, INV-09, ACCEPT-01, ACCEPT-02, ACCEPT-04, RESET-01, RESET-04, RESET-06, SEC-07

**Tools**:

- MCP: NONE
- Skill: `tlc-spec-driven`

**Done when**:

- [ ] Every route in the approved design delegates business rules to `AccountAccessService`.
- [ ] Administrative routes reject missing/non-admin sessions and invalid origin before side effects.
- [ ] Forgot-password always returns the approved 202 response.
- [ ] Inspect/consume routes use tenant slug plus POST body token and never accept token query parameters.
- [ ] Runtime construction injects the real router, control database, SMTP sender and service.
- [ ] Integration tests cover every route's success, validation, authorization, invalid token, limit and dependency-failure paths.
- [ ] Full gate passes with no test deletion.

**Tests**: integration — create `tests/backend/test_account_access_api.py` and extend server factory tests.  
**Gate**: full  
**Commit**: `feat(api): expose account invitation endpoints`

---

### T12: Connect user administration to real invitations

**What**: Replace simulated create/resend/cancel behavior in `Usuários e permissões` with the new APIs and delivery-state feedback.  
**Where**: `app/static/index.html`  
**Depends on**: T11  
**Reuses**: current user dialog, table rendering, authorization and error/notice components  
**Requirement**: INVUI-01, INVUI-02, INVUI-03, INV-03, INV-09, INV-10

**Tools**:

- MCP: NONE
- Skill: `tlc-spec-driven`

**Done when**:

- [ ] Footer no longer claims invitations are simulated.
- [ ] Create/resend/cancel render only server-confirmed user and delivery states.
- [ ] Failed SMTP clearly keeps Pendente and offers retry without claiming delivery.
- [ ] Non-admin controls are absent/disabled consistently with server authorization.
- [ ] Active assignee lists continue excluding Pendente, Inativo and Cancelado.
- [ ] Desktop and mobile E2E scenarios cover success, failure, resend and cancel.
- [ ] Full gate passes and UI scenario count remains at least 122 plus the new cases.

**Tests**: e2e — extend `tests/ui-prototype.spec.cjs` with invitation administration scenarios.  
**Gate**: full  
**Commit**: `feat(ui): connect user invitations to api`

---

### T13: Add public invitation and password-recovery screens

**What**: Add forgot-password, invitation acceptance and password reset views that keep raw tokens out of URLs sent to the server.  
**Where**: `app/static/index.html`  
**Depends on**: T12  
**Reuses**: tenant login, public card layout, accessible forms and navigation helpers  
**Requirement**: ACCEPT-01, ACCEPT-03, ACCEPT-04, ACCEPT-05, RESET-01, RESET-05, RESET-06, INVUI-04, INVUI-05, SEC-02

**Tools**:

- MCP: NONE
- Skill: `tlc-spec-driven`

**Done when**:

- [ ] Login shows `Esqueci minha senha` only after the tenant is known.
- [ ] Forgot-password displays exactly the generic approved confirmation.
- [ ] Invite/reset pages read token from the URL fragment, immediately remove it with `history.replaceState` and POST it only in JSON.
- [ ] Forms cover loading, mismatch, bounds, success and uniform invalid-link states accessibly.
- [ ] Success returns to the tenant login without creating a session.
- [ ] Desktop/mobile E2E covers complete invite and reset flows, replay and invalid links.
- [ ] Full gate passes and UI scenario count remains at least 122 plus the new cases.

**Tests**: e2e — extend `tests/ui-prototype.spec.cjs` with public invite/reset scenarios.  
**Gate**: full  
**Commit**: `feat(ui): add invitation and password recovery pages`

---

### T14: Configure SMTP secrets in the Windows release

**What**: Extend the Windows PostgreSQL 11 deployment contract, package and runbook to validate SMTP settings and decrypt the SMTP password under `SmartCRMService`.  
**Where**: `deploy/manual-windows-pg11/`  
**Depends on**: T13  
**Reuses**: strict environment allowlist, DPAPI service-account workflow, offline bundle and side-by-side release gates  
**Requirement**: INV-02, INV-03, RESET-03, SEC-02

**Tools**:

- MCP: NONE
- Skill: `tlc-spec-driven`

**Done when**:

- [ ] Non-secret SMTP settings are validated and exported to runtime; plaintext password is rejected from `server.env`.
- [ ] A documented command stores the password in the fixed DPAPI file with restricted ACL under `SmartCRMService`.
- [ ] Validate-only fails before cutover for missing/invalid SMTP config, unreadable DPAPI secret or insecure TLS mode.
- [ ] Environment generator/upgrade preserves existing production values and adds SMTP keys without `ConvertFrom-StringData` path escaping.
- [ ] Package-integrity, deployment outcome, bundle and startup tests cover success and safe failure.
- [ ] Runbook includes staging, SMTP smoke test, cutover, rollback and secret rotation without printing secrets.
- [ ] Build gate passes; generated bundle verifies and no active task/database is changed by staging.

**Tests**: integration — extend `tests/backend/test_manual_windows_pg11_deployment.py`, `test_manual_windows_pg11_outcomes.py` and `test_windows_multitenant_bundle.py`.  
**Gate**: build  
**Commit**: `feat(deploy): configure smtp secrets for windows`

---

## Phase Execution Map

```text
Phase 1 → Phase 2 → Phase 3 → Phase 4

Phase 1: T1 → T2 → T3 → T4 → T5
Phase 2: T5 → T6 → T7 → T8 → T9 → T10
Phase 3: T10 → T11 → T12 → T13
Phase 4: T13 → T14
```

Execution is strictly sequential. There is no intra-phase parallelism. Phase-boundary references (`T5`, `T10`, `T13`) show the dependency entering the next phase and are not duplicate executions.

---

## Task Granularity Check

| Task | Scope | Status |
| ---- | ----- | ------ |
| T1 | One tenant entity | ✅ Granular |
| T2 | One tenant migration | ✅ Granular |
| T3 | One repository | ✅ Granular |
| T4 | One central throttling/audit capability | ✅ Granular |
| T5 | One mail adapter | ✅ Granular |
| T6 | One administrative invitation lifecycle | ✅ Cohesive |
| T7 | One invitation acceptance lifecycle | ✅ Cohesive |
| T8 | One password recovery lifecycle | ✅ Cohesive |
| T9 | One repository protection boundary | ✅ Granular |
| T10 | One API contract group | ✅ Cohesive |
| T11 | One route group and its factory wiring | ✅ Cohesive |
| T12 | One administration UI flow | ✅ Cohesive |
| T13 | One public UI flow group | ✅ Cohesive |
| T14 | One deployment configuration contract | ✅ Cohesive |

---

## Diagram-Definition Cross-Check

| Task | Depends On (task body) | Diagram Shows | Status |
| ---- | ---------------------- | ------------- | ------ |
| T1 | None | Start at T1 | ✅ Match |
| T2 | T1 | T1 → T2 | ✅ Match |
| T3 | T2 | T2 → T3 | ✅ Match |
| T4 | T3 | T3 → T4 | ✅ Match |
| T5 | T4 | T4 → T5 | ✅ Match |
| T6 | T5 | T5 → T6 | ✅ Match |
| T7 | T6 | T6 → T7 | ✅ Match |
| T8 | T7 | T7 → T8 | ✅ Match |
| T9 | T8 | T8 → T9 | ✅ Match |
| T10 | T9 | T9 → T10 | ✅ Match |
| T11 | T10 | T10 → T11 | ✅ Match |
| T12 | T11 | T11 → T12 | ✅ Match |
| T13 | T12 | T12 → T13 | ✅ Match |
| T14 | T13 | T13 → T14 | ✅ Match |

---

## Test Co-location Validation

| Task | Code Layer Created/Modified | Matrix Requires | Task Says | Status |
| ---- | --------------------------- | --------------- | --------- | ------ |
| T1 | Plain entity | unit | unit | ✅ OK |
| T2 | Migration | integration | integration | ✅ OK |
| T3 | Repository | integration | integration | ✅ OK |
| T4 | Repository/security service | integration | integration | ✅ OK |
| T5 | SMTP utility | unit | unit | ✅ OK |
| T6 | Domain service | integration | integration | ✅ OK |
| T7 | Domain service | integration | integration | ✅ OK |
| T8 | Domain service | integration | integration | ✅ OK |
| T9 | Repository | integration | integration | ✅ OK |
| T10 | Schema | unit | unit | ✅ OK |
| T11 | Routes/runtime | integration | integration | ✅ OK |
| T12 | Browser UI | e2e | e2e | ✅ OK |
| T13 | Browser UI | e2e | e2e | ✅ OK |
| T14 | Deployment | integration | integration | ✅ OK |

---

## Requirement Coverage

| Requirement Group | Tasks |
| ----------------- | ----- |
| INV-01…INV-10 | T3, T5, T6, T9, T10, T11, T12, T14 |
| ACCEPT-01…ACCEPT-06 | T3, T7, T10, T11, T13 |
| RESET-01…RESET-06 | T3, T4, T5, T8, T10, T11, T13, T14 |
| SEC-01…SEC-07 | T1, T2, T3, T4, T5, T6, T7, T8, T9, T13, T14 |
| INVUI-01…INVUI-05 | T9, T10, T12, T13 |

Every spec requirement group is mapped to implementation and co-located verification; no test-only task exists.
