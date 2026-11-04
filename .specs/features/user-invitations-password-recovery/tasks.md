# Convites de usuários e recuperação de senha — Tasks

## Execution Protocol (MANDATORY -- do not skip)

Implement these tasks with the `tlc-spec-driven` skill: **activate it by name and follow its Execute flow and Critical Rules.** Do not search for skill files by filesystem path. The skill is the source of truth for the full flow (per-task cycle, sub-agent delegation, adequacy review, Verifier, discrimination sensor).

**If the skill cannot be activated, STOP and tell the user - do not proceed without it.**

---

**Design**: `.specs/features/user-invitations-password-recovery/design.md`  
**Status**: Implemented (T1–T14) — awaiting owner review, merge, release and Windows deployment

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

- [x] Existing hash, `auth_enabled`, `auth_version`, normalized email and protected status survive workspace updates.
- [x] Allowed profile fields still update without breaking references.
- [x] Pending/cancelled/inactive users cannot be made assignable through a crafted snapshot.
- [x] Repository tests prove protected-field preservation and normal profile editing.
- [x] Quick gate passes with no test deletion.

**Tests**: integration — extend `tests/backend/test_repository.py` and `tests/backend/test_workspace_service.py`.  
**Gate**: quick  
**Commit**: `fix(users): preserve server managed account fields`

**Evidence**: 14 new PostgreSQL tests (13 in `test_repository.py`, 1 in `test_workspace_service.py`). They prove: a crafted administrator snapshot cannot change `password_hash`, `auth_enabled`, `auth_version`, `normalized_email` or the e-mail of an account with a server identity, and server-managed keys (`passwordHash`, `authEnabled`, `authVersion`, `normalizedEmail`, tokens, delivery state) are neither persisted in the payload nor returned in the snapshot (SEC-02); name, job title, role and team still update, and legacy roster users without a server identity keep an editable e-mail; the only status change a snapshot may make is `Ativo` → `Inativo` (existing deactivation with `auth_version` increment and session revocation), so `Pendente`, `Cancelado` and `Inativo` accounts cannot be made assignable and active accounts cannot be put into an invitation state (INV-10); `invited_at` is server-owned; users created by `AccountAccessService` (empty payload) are read from their columns, pass reference validation and appear after browser-created users, and columns win over a stale payload after a server re-invitation (INVUI-01); a pending invitee absent from a stale administrator snapshot is not soft-deleted, since only `cancel_invitation` ends an invitation. Mutation checks on status protection, e-mail protection, pending soft-delete exclusion, column overlay, key filtering and `invited_at` ownership were all detected. Reactivation (`Inativo` → `Ativo`) is no longer possible through the snapshot and has no route in the approved design (T10/T11); it needs an owner decision. New users are still created through the snapshot until T12 replaces the simulated invitation. No test was deleted, weakened or skipped.

**Windows gate**: full backend suite on Windows 11 with Docker PostgreSQL 17 passed with 935 tests (921 after T8 + 14 new), 6 pre-existing warnings.

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

- [x] All request fields have explicit bounds and normalized email/slug behavior.
- [x] Password and confirmation require equality and accept exactly 8–128 characters.
- [x] Public response models contain no token, hash, DSN or internal availability detail.
- [x] Login and new-account validation use the same password bounds.
- [x] Boundary and redaction unit tests pass.
- [x] Quick gate passes with no test deletion.

**Tests**: unit — extend `tests/backend/test_schemas.py` and `tests/backend/test_security.py`.  
**Gate**: quick  
**Commit**: `feat(api): define account access contracts`

**Evidence**: `MIN_PASSWORD_LENGTH` is now 8 in `app/security/passwords.py` and is the single source for `hash_password`, `LoginRequest`, the new acceptance/reset contracts and the service check. New contracts: `InvitationCreateRequest` (camelCase, trimmed name/job title 1–255, optional team 1–255 with blank → none, normalized e-mail ≤ 254, closed role list, server-managed fields forbidden), `AccountUserResponse`, `InvitationResponse` (`deliveryStatus` pending/sent/failed only, no failure code), `UserAccessResponse`, `AccountActionTokenRequest` (normalized slug, token 1–512), `InvitationAcceptRequest`/`PasswordResetRequest` (8–128, equal confirmation, no trimming), `ForgotPasswordRequest` and `ForgotPasswordResponse` (only the approved message) and `AccountActionViewResponse` (company name and e-mail only). The public messages and the token bound now live in `app/schemas.py` and the service imports them, so the API and service cannot drift. 68 new unit tests; two existing boundary tests were updated from the old 12-character minimum to the approved 8 (11 → 7 rejected, 12 → 8 accepted), none removed. Mutation checks on the minimum length, confirmation equality, blank-team normalization, login bounds and a leaked response field were all detected.

**Windows gate**: full backend suite on Windows 11 with Docker PostgreSQL 17 passed with 1003 tests (935 after T9 + 68 new), 6 pre-existing warnings.

---

### T11: Expose and wire account-access routes

**What**: Add authenticated invitation routes and public invitation/reset routes, inject the service into the app factory and preserve origin/cookie protections.  
**Where**: `app/main.py`  
**Depends on**: T10  
**Reuses**: `create_app` dependency injection, principal resolver, expected-origin check and standard error payloads  
**Requirement**: INV-01, INV-04, INV-05, INV-08, INV-09, ACCEPT-01, ACCEPT-02, ACCEPT-04, RESET-01, RESET-04, RESET-06, SEC-03, SEC-04, SEC-07

> Owner decisions (2026-11-03): SEC-03/SEC-04 also apply to administrative invitation sends (`invite_account`/`invite_ip`, 429 without e-mail), and `Inativo` → `Ativo` gets its own administrative reactivation route, because T9 removed that transition from the workspace snapshot.

**Tools**:

- MCP: NONE
- Skill: `tlc-spec-driven`

**Done when**:

- [x] Every route in the approved design delegates business rules to `AccountAccessService`.
- [x] Administrative routes reject missing/non-admin sessions and invalid origin before side effects.
- [x] Forgot-password always returns the approved 202 response.
- [x] Inspect/consume routes use tenant slug plus POST body token and never accept token query parameters.
- [x] Runtime construction injects the real router, control database, SMTP sender and service.
- [x] Integration tests cover every route's success, validation, authorization, invalid token, limit and dependency-failure paths.
- [x] Invitation and resend sends are limited to 5 per account and 30 per IP in 15 minutes and answer 429 without token or e-mail (SEC-03/SEC-04).
- [x] `POST /api/users/{user_id}/reactivate` lets only an Administrador move `Inativo` → `Ativo`, increments `auth_version` once and is audited.
- [x] Full gate passes with no test deletion.

**Tests**: integration — create `tests/backend/test_account_access_api.py` and extend server factory tests.  
**Gate**: full  
**Commit**: `feat(api): expose account invitation endpoints`

**Evidence**: Routes: `POST /api/users/invitations` (201), `POST /api/users/{id}/invitation/resend`, `POST /api/users/{id}/invitation/cancel`, `POST /api/users/{id}/reactivate`, `POST /api/auth/invitations/inspect`, `POST /api/auth/invitations/accept` (204), `POST /api/auth/password/forgot` (202), `POST /api/auth/password/reset/inspect`, `POST /api/auth/password/reset` (204), plus `GET /{slug}/accept-invite` and `GET /{slug}/reset-password` shells (no session read, `no-store`). Administrative routes authenticate through the new `CookiePrincipalResolver.authenticate` (origin → alternate-session rejection → cookie session → `MANAGE_USERS`) without opening a tenant session, so a request never holds two tenant connections from the pool of 2+2; every check runs before the service is called. Service errors map to stable codes (403 `forbidden`, 409 `account_active`/`account_inactive`/`invitation_not_pending`/`account_not_inactive`, 422, 429 `rate_limited` with `Retry-After: 900`, 503 `tenant_unavailable`/`database_unavailable`) without internal detail; responses carry the server-confirmed row (`AccountUserResponse`) and `deliveryStatus` only. Public routes require the expected origin, reject any query string with the single `invalid_link` answer, and map a missing/oversized/malformed token or slug or any extra field to that same answer; only password problems are explained (422 `password_mismatch`/`invalid_password`). Forgot-password answers 202 with the approved message for every body, including malformed ones, and runs the lookup and SMTP call as a background task after the response, so neither the answer nor its timing depends on the account or the mail server. Service additions: invitation limits through a new `ControlRepository.admit_account_action_request` shared with recovery (lock, check, then count; the 5th/30th request is still sent, the 6th/31st is held and audited as `invitation.rate_limited`); `reactivate_user`; `account_user`; teams resolved by name (`team_id_for_name`) and created on demand; and invitations now match legacy roster users without `normalized_email` case-insensitively, so an existing account is never duplicated or turned into a 500. Runtime: `bootstrap_runtime` builds `AccountAccessService` with the real control database, tenant router and SMTP sender; SMTP settings come from `SMART_CRM_SMTP_*` with the password read only from the DPAPI file, a plaintext `SMART_CRM_SMTP_PASSWORD` or partial/invalid settings stop startup with the generic bootstrap error, and with no SMTP key at all an `UnconfiguredMailSender` makes every delivery fail as `smtp_not_configured` (strict deployment validation is T14). Tests: 179 new (154 in `test_account_access_api.py`, of which 10 run end to end on PostgreSQL with real login, invitation, acceptance, recovery, session revocation, both limits, legacy users and reactivation; 7 in `test_server.py`; 18 in `test_mail.py`); the T6 control-repository stub gained the admission method. Mutation checks on the role check, query rejection, forgot-password 202 for invalid bodies, invitation admission, reactivation version increment and state check, legacy matching, token-error redaction and plaintext SMTP password rejection were all detected. No test was deleted, weakened or skipped.

**Windows gate**: full backend suite on Windows 11 with Docker PostgreSQL 17 passed with 1182 tests (1003 after T10 + 179 new), 7 warnings: the 6 pre-existing ones plus one more of the same Pydantic/FastAPI alias kind for `jobTitle`; UI regression with the installed Chrome passed 122/122 scenarios.

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

- [x] Footer no longer claims invitations are simulated.
- [x] Create/resend/cancel render only server-confirmed user and delivery states.
- [x] Failed SMTP clearly keeps Pendente and offers retry without claiming delivery.
- [x] Non-admin controls are absent/disabled consistently with server authorization.
- [x] Active assignee lists continue excluding Pendente, Inativo and Cancelado.
- [x] Desktop and mobile E2E scenarios cover success, failure, resend and cancel.
- [x] Full gate passes and UI scenario count remains at least 122 plus the new cases.

**Tests**: e2e — extend `tests/ui-prototype.spec.cjs` with invitation administration scenarios.  
**Gate**: full  
**Commit**: `feat(ui): connect user invitations to api`

**Evidence**: `Usuários e permissões` now calls `POST /api/users/invitations`, `.../invitation/resend`, `.../invitation/cancel` and `.../reactivate`; the row is replaced with the server's `AccountUserResponse` and merged into both the local and the last confirmed workspace state, so an API action never triggers a snapshot write. The simulated create/resend/cancel/accept code and the `Simular aceitação` button were removed; the footer reads `Convites enviados por e-mail · links válidos por 48 horas`. Delivery is shown per row from the server answer (`Convite enviado` / `E-mail não enviado`) and in the toast; a failed send keeps `Pendente`, says the e-mail was not sent and offers `Reenviar`. Server errors (409 active/inactive account, 429 limit, 422) are shown in the dialog without creating a local row. Inactive users get `Reativar`; `Desativar` stays a snapshot change and every other status transition is refused locally (server-owned since T9). Non-administrators have no navigation entry and the action functions return without any request. Editing profile fields still goes through the snapshot. Tests: `ADM-03` was rewritten for the real flow (same intent: invite, re-invite of a pending e-mail instead of the simulated duplicate error, resend, edit, deactivate, cancel, re-invite of a cancelled e-mail) and 6 new scenarios were added (invite success, SMTP failure + resend, server-rule errors, cancel + reactivate, mobile invite/resend/cancel without horizontal scroll, non-admin). The old `Perfil de usuário` option checks matched no element and always passed; they now use the real responsible-user option list (`fieldHTML(..., 'user', ...)`), which proves Pendente, Inativo and Cancelado users are not assignable and a reactivated user is. Mutation checks on the snapshot-free merge, the failed-delivery note, the delivery toast, the server-owned status rule, the footer, the reactivation button and the dialog error were all detected.

**Windows gate**: full backend suite passed with 1182 tests, same 7 warnings as after T11 (no backend change); UI regression with the installed Chrome passed 128/128 scenarios (122 + 6 new).

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

- [x] Login shows `Esqueci minha senha` only after the tenant is known.
- [x] Forgot-password displays exactly the generic approved confirmation.
- [x] Invite/reset pages read token from the URL fragment, immediately remove it with `history.replaceState` and POST it only in JSON.
- [x] Forms cover loading, mismatch, bounds, success and uniform invalid-link states accessibly.
- [x] Success returns to the tenant login without creating a session.
- [x] Desktop/mobile E2E covers complete invite and reset flows, replay and invalid links.
- [x] Full gate passes and UI scenario count remains at least 122 plus the new cases.

**Tests**: e2e — extend `tests/ui-prototype.spec.cjs` with public invite/reset scenarios.  
**Gate**: full  
**Commit**: `feat(ui): add invitation and password recovery pages`

**Evidence**: The tenant login (`/{slug}`) now offers `Esqueci minha senha`, which opens a recovery card (pre-filled with the typed e-mail) that POSTs `{slug, email}` to `/api/auth/password/forgot` and, on 202, shows exactly `Se o e-mail existir, enviaremos as instruções.`; a non-202 answer shows a retry error instead of the confirmation. The locator at `/` has no recovery action. `/{slug}/accept-invite` and `/{slug}/reset-password` read `#token=` from the fragment, remove it from the address bar and history with `history.replaceState` before any request, keep it only in memory and send it only in JSON bodies (`inspect`, then `accept`/`reset`); these pages never call `/api/auth/session` or `/api/auth/login`. States: `Verificando o link...` with `aria-busy`, a form showing company and e-mail with focus on the password, client checks for 8–128 characters and equal confirmation (no request when they fail), server password errors kept in the form, and one `Este link é inválido ou expirou.` state for a missing, wrong, replayed or cancelled link. Success clears the token and the form, replaces the URL with `/{slug}` and shows the login with `Conta ativada...` or `Senha alterada...`, without creating a session. 10 new scenarios (recovery confirmation and network failure, locator without recovery, full acceptance with fragment removal and no token in any URL or Web Storage, invalid link, link without token, replay, loading state, mobile reset with no horizontal scroll, server password error). Mutation checks on fragment removal, token in a query string, a session read after success or on the public page, client password checks, the recovery message, the loading state and replay handling were all detected.

**Windows gate**: full backend suite passed with 1182 tests (no backend change), 7 warnings as after T11; UI regression with the installed Chrome passed 138/138 scenarios (128 after T12 + 10 new).


**Follow-up fix (after T14, branch `ai2/fix-public-link-hashchange`)**: a local end-to-end run against the real API (throwaway PostgreSQL tenant and control schema, file-backed mail sender, Chrome) passed invite, resend, replaced-link rejection, acceptance, replay rejection, sign-in, recovery with a generic answer and no mail for an unknown address, session revocation, old-password rejection and cancellation. It also found that opening a second link in a tab already on the public page only changed the fragment and kept the old state; the page now reacts to `hashchange` the same way as on load. One new UI scenario; UI regression 139/139.

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

- [x] Non-secret SMTP settings are validated and exported to runtime; plaintext password is rejected from `server.env`.
- [x] A documented command stores the password in the fixed DPAPI file with restricted ACL under `SmartCRMService`.
- [x] Validate-only fails before cutover for missing/invalid SMTP config, unreadable DPAPI secret or insecure TLS mode.
- [x] Environment generator/upgrade preserves existing production values and adds SMTP keys without `ConvertFrom-StringData` path escaping.
- [x] Package-integrity, deployment outcome, bundle and startup tests cover success and safe failure.
- [x] Runbook includes staging, SMTP smoke test, cutover, rollback and secret rotation without printing secrets.
- [x] Build gate passes; generated bundle verifies and no active task/database is changed by staging.

**Tests**: integration — extend `tests/backend/test_manual_windows_pg11_deployment.py`, `test_manual_windows_pg11_outcomes.py` and `test_windows_multitenant_bundle.py`.  
**Gate**: build  
**Commit**: `feat(deploy): configure smtp secrets for windows`

**Evidence**: `server.env.example`, the allowlist (`Get-SmartCrmEnvironmentAllowedKeys` + `Get-SmartCrmSmtpEnvironmentKeys`) and the runtime export now carry `SMART_CRM_SMTP_HOST/PORT/USERNAME/FROM_ADDRESS/TLS_MODE/TIMEOUT_SECONDS/PASSWORD_SECRET_FILE`. `start-smart-crm.ps1` refuses `SMART_CRM_SMTP_PASSWORD` with a pointer to `set-smtp-password.ps1` (value never echoed), requires every SMTP key, rejects `REPLACE_WITH_*` placeholders, non-DNS hosts, invalid ports, sender without `@`, any TLS mode other than exactly `starttls`/`implicit_tls`, timeouts outside (0, 60] and any secret path other than `C:\ProgramData\SmartCRM\service-secrets\smtp-password.bin`, and `Assert-SmartCrmServiceSecretReadable` rejects a missing file, an ACL granting Everyone/Authenticated Users/Users, and a blob that does not DPAPI-decrypt to a non-empty value for the current account. `-SkipSecretDecryption` (only with `-ValidateOnly`) is used by `install-offline.ps1` and `initialize-and-test.ps1`, which run as Administrator; the decryption check runs as `SmartCRMService` during staging (runbook) and again at service startup, where the Python runtime fails closed and the initializer's health gate rolls the cutover back. New `set-smtp-password.ps1` (must run as `SmartCRMService`) reads the password twice at hidden prompts, protects it with DPAPI CurrentUser, writes it atomically into `service-secrets` (created by the installer with SYSTEM/Administrators/service-only ACL) and proves it decrypts. `New-SmartCrmEnvironmentLines` adds SMTP placeholders for new installs (the installer then skips validation and points to section 5.1) and `Add-SmartCrmSmtpEnvironmentLines` returns the existing file byte for byte plus the SMTP keys, refusing a file that already has SMTP. `-SmtpSmokeTo` runs the new `python -m app.mail_cli smoke` with the validated environment and prints only `smtp smoke: PASS` or a failure code. `LEIA-ME.md` gains section 5.1 (staging, smoke test, cutover with `server.env.pre-smtp` backup, rollback, rotation), replaces the `ConvertFrom-StringData` snippet in 3.1 with `Read-SmartCrmEnvironment`, and states that the tenant lineage now ends at `b4e2c9a7d6f1` (`account_action_tokens`); the fleet runner already targets the packaged head. The DPAPI file reader moved to `app.security.secrets.read_dpapi_secret_file` and is shared by the runtime and the CLI; PowerShell and Python DPAPI blobs are proven interchangeable. The bundle requires `app/mail_cli.py`, the `b4e2c9a7d6f1` migration and `set-smtp-password.ps1`; the source verifier gained MPG-20. Tests: 34 new (26 in `test_manual_windows_pg11_outcomes.py`, 6 in `test_mail.py`, 1 in `test_secrets.py`, 1 in `test_windows_multitenant_bundle.py`); the start-validation helper now writes a DPAPI test secret with a restricted ACL, and the exact environment-generator test and the reviewed key allowlist in `test_windows_multitenant_env.py` now expect the SMTP keys (and assert the password key is absent) — no test was removed or weakened. Mutation checks on the TLS-mode rule, the plaintext-password message, DPAPI decryption, the ACL check, the pinned secret path, placeholder rejection and the byte-preserving upgrade were all detected (placeholder rejection only after adding a username-placeholder case, because the host placeholder is also caught by the DNS rule).

**Build gate**: full backend suite on Windows 11 with Docker PostgreSQL 17 passed with 1216 tests (1182 after T13 + 34 new), 7 warnings as after T11 — the first run had 1 failure (the reviewed allowlist test did not yet list the SMTP keys); after updating it, that file and the deployment contract tests were rerun and passed; UI regression with the installed Chrome passed 138/138; `python scripts/build_manual_windows_pg11_bundle.py --version v0.3.3` produced `dist/smart-crm-manual-pg11-v0.3.3.zip`, `verify_manual_windows_pg11_deployment.py --bundle` passed 20/20 and the extracted bundle's `test-package-integrity.ps1` passed; nothing was staged on a server and no task, database or production `server.env` was touched.

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
