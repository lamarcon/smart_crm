# Multiempresa Seguro Design

**Spec:** .specs/features/secure-multitenancy/spec.md
**Status:** Approved

---

## Decision and Approaches

A solução escolhida é uma aplicação central com um plano de controle central e um PostgreSQL de negócio exclusivo por empresa. A rota pública localiza a empresa para o login; depois do login, somente a sessão opaca central pode determinar qual banco será usado.

| Approach | Benefits | Risks / Cost | Verdict |
| -------- | -------- | ------------ | ------- |
| Central app + central control plane + database per tenant | Isolamento físico de usuários e dados; uma UI/API; tenant pode mover de servidor; falha de um banco fica localizada | Frota Alembic, muitos pools, rede/TLS, segredos e provisionamento distribuído | **Chosen by user** |
| Full app + database per tenant | Menor roteamento dinâmico e isolamento máximo de runtime | Deploy, monitoramento, portas e versões repetidos; cookies no mesmo domínio por caminho ficam mais complexos | Viável para requisito regulatório futuro |
| Shared database/schema + scoped queries + RLS | Operação e migração mais simples; menos conexões | Maior blast radius e disciplina contínua de chaves/filtros | Rejeitado para este produto |

A decisão AD-005 registra a escolha. AD-003 continua válida para FastAPI, SQLAlchemy 2, Psycopg 3 e Alembic. AD-004 continua válida para o primeiro tenant: o PostgreSQL 11 atual permanece como seu banco de negócio, e um database de controle separado pode começar na mesma instância.

---

## Architecture Overview

~~~mermaid
flowchart TD
    U[Browser] --> G[Apache HTTPS]
    G --> A[FastAPI central]
    A --> L[Public locator and login]
    L --> C[(Control PostgreSQL)]
    L --> R[TenantDatabaseRouter]
    R --> S[SecretProvider]
    R --> DA[(PostgreSQL tenant A)]
    R --> DB[(PostgreSQL tenant B)]
    R --> DC[(PostgreSQL tenant C)]
    A --> Q[Opaque session resolver]
    Q --> C
    Q --> R
    R --> I[Database identity guard]
    I --> P[Principal and policy]
    P --> W[Workspace service/repository]
~~~

### Trust boundaries

~~~text
Untrusted before login:
  host/path slug, email, password, IP metadata

Trusted directory:
  control tenant_id -> slug/status/secret_ref/profile_version

Trusted after login:
  cookie digest -> central session -> control tenant_id + user_id + auth_version

Only database selector:
  control tenant_id from a valid central session

Tenant database validation:
  tenant_identity.control_tenant_id must equal session tenant_id
  tenant_identity.workspace_id becomes transaction RLS context

Authorization:
  active tenant user loaded from selected database + server policy
~~~

The browser never supplies a connection profile, DSN, database name, trusted workspace, role or effective user. The slug is allowed to select a candidate tenant only for pre-authentication; a session is created only after credentials succeed in that tenant database.

---

## Request Flows

### Locate and login

1. GET / returns the public locator.
2. POST /api/auth/locate normalizes a slug or same-origin URL and queries only the control directory.
3. GET /{slug} renders the tenant login shell without creating a session.
4. POST /api/auth/login accepts slug, email and password.
5. The auth service locks central throttle buckets and resolves the candidate tenant by slug.
6. TenantDatabaseRouter receives the control tenant_id, loads its server-side secret reference and obtains a tenant engine.
7. The identity guard verifies tenant_identity before the auth repository looks up the normalized email.
8. The service always runs one Argon2id verification, including a dummy hash for unknown/failing subjects.
9. After tenant/user/status/schema checks, the control database stores only the session digest and linkage metadata.
10. The response sets the secure cookie and no-store headers.

A failed control DB, tenant DB, identity, TLS or schema check produces the same public login failure. No candidate ever falls back to the current database or another tenant.

### Protected request

1. The dependency reads only the __Host-smartcrm_session cookie and hashes it.
2. The control repository locks/loads an active session, validates TTL and resolves tenant status.
3. TenantDatabaseRouter uses session.tenant_id; route/body/header values never enter this call.
4. The tenant session opens with bounded timeout, verifies identity and sets transaction-local workspace context.
5. The principal loader reads the current active user from that tenant database and compares auth_version.
6. AuthorizationPolicy applies the server-side role and record visibility.
7. WorkspaceService reads or reconciles only the selected database under explicit workspace_id and RLS.
8. The API returns no-store and canonical session metadata.

### Snapshot read and save

The existing snapshot API remains during this feature.

Read:
1. Lock/read workspace inside the selected tenant database.
2. Build the canonical snapshot.
3. Filter Leads and Deals according to the principal.
4. Return tenant/user metadata separately; never serialize hashes, secrets or session tokens.

Save:
1. Reject tenant, role and currentUser identity fields as authority.
2. Load canonical state in the selected tenant database.
3. Validate which submitted records/actions the principal may mutate.
4. Merge authorized visible changes with invisible canonical records.
5. Validate references in the merged state.
6. Reconcile in one tenant transaction using optimistic workspace versioning.
7. RLS and explicit workspace predicates fail closed if scope is absent.

---

## Code Reuse Analysis

### Existing Components to Leverage

| Component | Location | How to Use |
| --------- | -------- | ---------- |
| App factory and static mount | app/main.py | Add auth dependencies/routes and tenant SPA route before the catch-all static mount. |
| Current DB session pattern | app/database.py | Split configuration/bootstrap from tenant sessions while preserving SQLAlchemy 2 transaction style. |
| Workspace service/version lock | app/services/workspace.py | Require Principal/TenantSession instead of hard-coded default. |
| Snapshot reconciler | app/repositories/workspace.py | Preserve serialization and restore logic after making every lookup explicitly workspace-scoped. |
| ORM entities | app/models.py | Keep business model lineage; add auth fields, tenant identity and missing workspace markers needed for RLS. |
| Schema validation | app/schemas.py | Reuse merged-state reference validation and add auth contracts. |
| Existing migration chain | migrations/ | Remain the tenant-database migration lineage. |
| Backend fixtures | tests/backend/ | Extend with separate control and two-tenant-database fixtures. |
| Browser harness | tests/ui-prototype.spec.cjs | Add locator/login/logout and storage/cookie scenarios. |
| Offline builder | scripts/build-offline-package.ps1 | Include new wheel, control migrations and admin/fleet commands. |
| Apache example | deploy/windows-apache/httpd-sc2030.conf.example | Preserve reverse proxy and prepare app auth cutover. |

### Integration Points

| System | Integration Method |
| ------ | ------------------ |
| Control PostgreSQL | Static server-side DSN; contains no tenant business/user/password-hash data. |
| Tenant PostgreSQL | Dynamic SQLAlchemy engine obtained only from trusted control tenant_id. |
| Secret storage | SecretProvider interface; DPAPI-backed provider in production and environment-backed provider in tests/dev. |
| Apache | Same origin proxies /, /{slug} and /api to 127.0.0.1:8080. |
| Alembic | Existing tenant lineage plus independent control lineage and fleet preflight/orchestration. |

---

## Components and Interfaces

### Control database boundary

- **Purpose:** Own tenant directory, session digests, throttles and security audit.
- **Location:** app/control_database.py, app/control_models.py, app/control_repositories.py
- **Interfaces:** control_session_scope(), find_tenant_by_slug(), load_session_by_digest(), update_throttle(), append_security_event()
- **Dependencies:** One configured CONTROL_DATABASE_URL.
- **Rule:** No ORM relationship or query joins the control database to a tenant database.

### SecretProvider

- **Purpose:** Resolve an opaque secret_ref into connection properties without exposing them to the control database, logs or API.
- **Location:** app/security/secrets.py
- **Interfaces:** get_database_secret(secret_ref), put_database_secret(secret_ref, secret), delete_database_secret(secret_ref)
- **Production:** DPAPI encryption bound to the Windows service account plus restrictive filesystem ACL.
- **Tests/dev:** In-memory or environment reference provider; values never committed.
- **Rotation:** Updating profile_version invalidates only that tenant engine.

### TenantDatabaseRouter

- **Purpose:** Map trusted control tenant_id to an isolated SQLAlchemy engine/session.
- **Location:** app/tenant_database.py
- **Interfaces:** get_engine(tenant_id), tenant_session_scope(tenant_id), invalidate(tenant_id), health(tenant_id)
- **Inputs:** Only control tenant_id or resolved SessionContext; never slug/DSN from an API payload.
- **Pool policy:** Lazy bounded cache keyed by tenant_id + profile_version, configurable pool_size/max_overflow/timeouts, LRU disposal of idle engines.
- **Failure:** Never returns a default engine and never retries on a different tenant.

### Database identity guard

- **Purpose:** Detect registry mistakes, stale pools or connection substitution before business SQL.
- **Location:** app/tenant_database.py
- **Contract:** Load the single tenant_identity row outside tenant RLS, compare control_tenant_id and supported schema contract, then set local workspace context.
- **Failure:** Abort transaction, invalidate the affected engine, emit a redacted event and return temporary unavailability.

### Password and session security

- **Purpose:** Hash/verify Argon2id, issue CSPRNG opaque tokens, digest tokens and evaluate TTL.
- **Location:** app/security/passwords.py, app/security/sessions.py
- **Interfaces:** hash_password(), verify_password(), verify_or_dummy(), new_session_token(), digest_session_token(), session_is_active()
- **Dependencies:** Fixed Argon2-compatible package with CPython 3.11 x64 wheel.

### Authentication service

- **Purpose:** Coordinate central throttling/directory/session with tenant-local user verification.
- **Location:** app/services/auth.py
- **Interfaces:** locate_tenant(), login(), current_session(), logout(), revoke_user_sessions()
- **Concurrency:** Central row locks serialize account+tenant and IP throttle buckets.
- **Revocation:** Tenant user auth_version is compared on every protected request.

### Principal dependency and policy

- **Purpose:** Produce immutable Principal(control_tenant_id, workspace_id, user_id, role, team_id, auth_version) and enforce actions.
- **Location:** app/auth.py, app/policies.py
- **Interfaces:** require_principal(), require_tenant_route(), can_read_record(), can_mutate_record(), require_admin()
- **Rule:** API input can identify a target record but cannot define identity, role, workspace or connection.

### Tenant-scoped workspace service and repository

- **Purpose:** Replace fixed default access with explicit principal and selected TenantSession.
- **Location:** app/services/workspace.py, app/repositories/workspace.py
- **Rule:** No constructor/method has a default tenant; no session.get by global ID for tenant-owned records.
- **Protection:** Explicit workspace predicates, role policy, RLS and authorized projection/merge.

### Administrative and fleet CLI

- **Purpose:** Register connection profiles, migrate/activate default, provision/resume tenants, manage credentials/sessions and inspect/migrate the fleet.
- **Location:** app/admin_cli.py
- **Interfaces:** register-tenant, activate-default, resume-provisioning, set-user-password, revoke-user-sessions, fleet-preflight, fleet-migrate
- **Rule:** No public HTTP equivalent; secrets use hidden input; migration needs explicit tenant selection and operator confirmation.
- **Idempotency:** Each step records state/checkpoint; rerun does not duplicate tenant identity or first admin.

### Windows deployment adapter

- **Purpose:** Start the central factory with an exact external environment contract, keep control and tenant migrations separate, and preserve a side-by-side rollback path.
- **Location:** deploy/manual-windows-pg11/*.ps1, deploy/manual-windows-pg11/LEIA-ME.md
- **Runtime contract:** `app.server:create_central_app` receives only the control DSN, DPAPI directory, HTTPS origin and bounded pool settings; the tenant DSN is resolved from `secret_ref` after authentication.
- **Migration contract:** the web startup never upgrades schemas. An approved operator applies `alembic-control.ini` to `smartcrm_control`, then applies `alembic.ini` only to the explicitly selected existing tenant database and verifies both exact revisions.
- **Identity contract:** the scheduled task requires the dedicated `SmartCRMService` identity, and tenant secrets are provisioned by the same identity because DPAPI is user-bound.
- **Release contract:** each bundle is extracted to `C:\brbots\apps\smart-crm-<SHA>`; the previous immutable directory remains available until UAT and rollback retention end.

### Tenant-aware frontend shell

- **Purpose:** Provide locator/login/logout, immutable identity and tenant/user-namespaced UI preferences.
- **Location:** app/static/index.html
- **Interfaces:** initializeRoute(), locateTenant(), login(), loadSession(), logout(), tenantStorageKey()
- **Rule:** No commercial snapshot or authorization state persists in Web Storage.

---

## Data Models

### Control database: control_tenants

| Field | Contract |
| ----- | -------- |
| id | UUID primary key, stable and never derived from slug |
| slug | normalized unique path identifier |
| display_name | public tenant label returned only after successful locate |
| status | provisioning, active, inactive or failed |
| secret_ref | opaque reference; never DSN or password |
| profile_version | increments on connection change/secret rotation |
| expected_tenant_revision | application-supported tenant schema revision |
| last_error_code | redacted operational code, nullable |
| timestamps | created, updated and activated times |

### Control database: auth_sessions

| Field | Contract |
| ----- | -------- |
| token_digest | SHA-256 primary key; raw token never stored |
| tenant_id | FK to control_tenants |
| user_id | tenant-local user ID |
| auth_version | version observed at login |
| created_at / last_seen_at | TTL basis |
| idle_expires_at / absolute_expires_at | 30 minutes / 12 hours |
| revoked_at / reason | server-side revocation |
| correlation_digest | non-secret audit correlation |

Indexes cover active expiry cleanup and tenant/user revocation. No role snapshot is authoritative.

### Control database: login_throttles

Composite key by bucket_type + subject_digest. The account digest includes normalized tenant slug and email; the IP bucket stores a keyed digest rather than raw IP when practical. Row locking serializes attempts.

### Control database: security_events

Append-only event ID, event type, tenant/user when known, correlation digest, redacted outcome and timestamp. It excludes password, token, cookie, DSN, host credentials and commercial payloads.

### Tenant database: tenant_identity

| Field | Contract |
| ----- | -------- |
| singleton_key | constant primary key enforcing one configured identity row |
| control_tenant_id | unique UUID matching control plane |
| workspace_id | existing business workspace key; default is preserved for first tenant |
| schema_contract | supported identity/schema format |
| created_at | audit timestamp |

This table is readable before RLS context and contains no commercial data. Activation refuses a second or mismatched identity.

### Tenant database: crm_users auth fields

normalized_email is unique within the database/workspace. password_hash is nullable for legacy users, auth_enabled defaults false, auth_version starts at zero, and account status gates login. Password hashes never leave the tenant database.

### Business rows and RLS

- Every tenant-owned table has a non-null workspace_id, including current child tables that lack it.
- Existing IDs remain primary keys because a database contains one tenant; identical IDs across databases are valid.
- Parent/child validation includes workspace where needed to prevent inconsistent rows inside a tenant database.
- Services and repositories always bind workspace_id explicitly.
- Each authenticated transaction sets smartcrm.workspace_id transaction-locally.
- Policies use both USING and WITH CHECK and every tenant-owned table uses ENABLE plus FORCE ROW LEVEL SECURITY.
- The runtime role is tested, and missing context returns zero rows or an error.
- Referential integrity is not treated as proof of RLS; application validation remains mandatory.

---

## Alembic and Fleet Strategy

- migrations/ remains the tenant-database lineage so the current production history is preserved.
- migrations_control/ and alembic-control.ini own only control tables.
- The app declares an exact supported control revision and tenant revision/range.
- Startup validates control revision. A tenant is eligible only when its identity and revision are compatible.
- Web requests never run upgrade.
- fleet-preflight checks selected/all tenants concurrently with a bounded worker count and redacted per-tenant output.
- fleet-migrate requires explicit tenant IDs/slugs, confirmed backup evidence and confirmation; it records each outcome independently and stops activating a failed tenant.
- A failed tenant migration cannot block already compatible tenants.
- Production execution, backups and server changes remain outside plan approval.

---

## Provisioning State Machine

~~~mermaid
stateDiagram-v2
    [*] --> provisioning: register tenant + secret reference
    provisioning --> provisioning: validate connection / migrate / create admin / retry
    provisioning --> active: identity + revision + admin + hash verified
    provisioning --> failed: non-retryable validation
    failed --> provisioning: corrected profile + explicit resume
    active --> inactive: administrative disable
    inactive --> active: successful revalidation
~~~

There is no claim of atomicity across databases. Safety comes from state gating and idempotency:

1. Create or reuse a control row in provisioning.
2. Store/resolve the secret through SecretProvider.
3. Connect with TLS and verify or initialize tenant_identity.
4. Apply the tenant migration only through the separately authorized migration step; the administrative command verifies the exact revision and never upgrades it.
5. Bind/create the first administrator and hash the hidden password in the tenant transaction.
6. Re-read identity, revision and administrator.
7. Mark active in a short control transaction.
8. On failure, remain non-active with a redacted checkpoint; retry resumes the earliest incomplete step.

For the existing database, pre/post counts and reference checks run before active. Business records never cross database boundaries.

---

## API and Error Contracts

| Route | Access | Contract |
| ----- | ------ | -------- |
| GET / | Public | Tenant locator only. |
| GET /{slug} | Public/session-aware | Login or app shell; reserved paths excluded. |
| POST /api/auth/locate | Public throttled | Normalize identifier; generic not-found behavior. |
| POST /api/auth/login | Public throttled | Verify in resolved tenant DB and set cookie. |
| GET /api/auth/session | Session | Resolve tenant DB user and return immutable identity. |
| POST /api/auth/logout | Session/anonymous-safe | Revoke digest and expire cookie. |
| Existing /api/workspace routes | Session | Use router from session; no tenant parameter. |
| Tenant/admin/fleet commands | No HTTP route | Local CLI only. |

Protected errors use stable envelopes: 401 unauthenticated, 403 forbidden, 404 record_not_found, 409 version_conflict and 503 tenant_unavailable. Cross-tenant IDs collapse to the same 404 as absent IDs. Login collapses directory, connection, schema and credential failures to the generic login message while detailed redacted codes go only to operations logs.

---

## Error Handling Strategy

| Scenario | Handling | User impact |
| -------- | -------- | ----------- |
| Unknown tenant/email, wrong password or inactive state | Dummy/real Argon2 path and generic response | Same login message |
| Control DB unavailable | Fail closed; no session or routing | Temporary service unavailable |
| One tenant DB unavailable | Invalidate only its engine; no fallback | That tenant receives temporary unavailability |
| Identity mismatch | Abort before business SQL and audit | Tenant unavailable; no leaked identity detail |
| Schema incompatible | Reject login/request and mark operational alert | Tenant unavailable pending migration |
| Route/session mismatch | 403 and no tenant switch | User stays bound to own session |
| Cross-database/absent ID | Query only selected DB and return 404 | No existence oracle |
| Missing RLS context | Forced policy returns no rows/error | Request fails closed |
| Provisioning partial failure | Remain non-active and resume checkpoint | No partial tenant can log in |
| Concurrent save | Workspace row lock/version conflict | One succeeds; one receives 409 |
| Secret rotation | Increment profile_version and dispose tenant engine | New connections use new secret |

---

## Security Decisions

| Decision | Choice | Rationale |
| -------- | ------ | --------- |
| Tenant authority | Central session only after login | URL/body/header cannot switch a database |
| Business-data boundary | Dedicated database per tenant | Limits blast radius and supports independent movement/backup |
| Misrouting defense | tenant_identity + explicit workspace + forced RLS | Detects incorrect registry/pool/context |
| User/password ownership | Tenant database | Control DB cannot authenticate users by itself or expose all hashes |
| Session ownership | Central control database | Supports opaque cookie, revocation and horizontally scaled app nodes |
| Connection secrets | Opaque ref + DPAPI SecretProvider | Avoids plaintext DSNs/passwords in control DB |
| Unknown-subject timing | Dummy Argon2 verification | Reduces enumeration by response timing |
| CSRF | SameSite Strict + Origin check | Protects cookie-authenticated mutations |
| Browser storage | UI preferences only, tenant/user namespaced | Web Storage never grants access or holds commercial snapshot |
| Migration | Explicit fleet command outside requests | Prevents surprise schema changes and broad failure |

---

## Risks & Concerns

| Concern | Location | Impact | Mitigation |
| ------- | -------- | ------ | ---------- |
| Workspace fixed as default | app/services/workspace.py:130 | Cannot route a trusted tenant | Require Principal and TenantSession in every service call |
| Repository silently defaults to default | app/repositories/workspace.py:75 | Wrong-scope access is easy | Remove default and require workspace argument |
| ID-only session.get paths | app/repositories/workspace.py:196,246,270 | May touch wrong workspace if a database is misprovisioned | Explicit workspace predicates plus negative tests |
| Child rows lack workspace_id | app/models.py:193,201,209,221 | RLS cannot cover them directly | Add/backfill non-null workspace_id |
| Anonymous workspace routes | app/main.py:68-86 | Full read/write without auth | Require session principal on every route |
| Full snapshot accepted from browser | app/main.py:80, app/services/workspace.py:156 | Authorization bypass and invisible-row deletion | Server projection, action policy and canonical merge |
| Profile selector changes currentUserId | app/static/index.html:385,1371,2585 | Client-side impersonation | Replace with immutable session identity |
| Global commercial localStorage keys | app/static/index.html:545,835 | Cross-tenant/user data residue | Remove snapshots and namespace UI preferences |
| Single global SQLAlchemy engine | app/database.py | Cannot isolate databases and may fallback accidentally | Split control engine from no-default tenant router |
| Database count grows with customers | architecture | File descriptors, pools and memory can grow unbounded | Lazy bounded LRU engines and per-tenant limits |
| Remote PostgreSQL 11 | deployment constraint | Unsupported version and network/TLS exposure | Minimum-compatible SQL, TLS verify, allowlist and upgrade roadmap |
| Shared PostgreSQL 11 cluster | discovered production constraint | A global loopback bind would interrupt `DW_CMS`/`DW_PRODUTOS`; a broad listener could expose Smart CRM databases | Preserve the listener, require first-match `pg_hba.conf` loopback allow + remote reject rules only for `smartcrm`/`smartcrm_control`, and gate migration on deterministic validation |
| Multi-database provisioning is non-atomic | architecture | Partial onboarding state | Non-active state machine, checkpoints and idempotent retry |
| Fleet schema drift | operations | Some tenants may run incompatible code | Version gate, preflight and explicit per-tenant outcomes |
| Central control DB is shared dependency | architecture | Its outage blocks all sessions | Minimal schema, health/backup, fail closed; HA deferred |
| Table owner can bypass RLS | PostgreSQL 11 behavior | Defense-in-depth could be illusory | FORCE RLS and integration tests under runtime role |
| Apache shared Basic Auth | deploy/windows-apache/httpd-sc2030.conf.example:38 | Double login and shared credential | Remove only in separately authorized cutover |
| Current inspection host lacks runnable PostgreSQL/test runtime | local environment | Baseline evidence is incomplete | Require runnable dev dependencies and two-database gate before Execute completion |

---

## Migration of Existing Default

1. Obtain verified backup and maintenance window before any production action.
2. Create the control database and apply only control migrations.
3. Register the first control tenant in provisioning with an operator-supplied slug and secret reference to the existing business database.
4. Capture pre-migration counts, checksums and referential probes in the existing database.
5. Apply tenant migration: auth fields, tenant_identity, missing workspace_id columns, indexes and RLS.
6. Backfill child workspace_id from parent chains and preserve every default business row.
7. Initialize tenant_identity with the control tenant UUID and workspace_id default.
8. Bind/create the first administrator and Argon2id password without changing unrelated users.
9. Verify post-migration counts/checksums, identity, RLS and schema revision.
10. Mark the control tenant active only after all checks pass.
11. Perform login, role, cross-database, cookie and rollback UAT.
12. Remove Apache Basic Auth only in a separately authorized cutover.

Plan approval authorizes none of these production actions.

---

## Test Strategy

### Unit

- Slug/URL parsing, reserved paths and generic errors.
- Argon2id hashing, dummy verification and password bounds.
- Opaque tokens, digests, idle/absolute TTL and revocation.
- Throttle windows/locks.
- Router accepts only SessionContext/control tenant ID and has no default.
- Engine cache isolation, LRU disposal, secret rotation and no fallback.
- Role/action/record policy matrix.
- Provisioning transition/idempotency rules.

### PostgreSQL integration

Use one control database and two physically distinct tenant databases. They may share a test server process, but not a database.

- Same public IDs and emails with different hashes/data in tenant A/B.
- Login for A cannot authenticate against B.
- Session A always selects A despite forged slug/body/header/DSN.
- Swapped registry profiles are rejected by tenant_identity.
- Missing RLS context returns no business rows; wrong context cannot write.
- Reads, updates, deletes and restores never change the other database.
- Tenant B outage does not invalidate A pool/session.
- Control and tenant Alembic upgrade from current schema; counts/checksums preserved.
- Partial provisioning resumes without duplicate tenant/admin.
- Concurrent throttles and workspace versions serialize correctly.

### API/browser

- Locator, canonical tenant route, generic login failures and no open redirect.
- Cookie flags, no token in response/storage, logout/expiry/revocation.
- 401/403/404/409/503 stable behavior.
- Five-role matrix and fabricated direct requests.
- No profile selector or commercial localStorage.
- Tenant/user namespaced UI preferences.
- Browser route mismatch cannot switch session or connection.

### Offline/deployment

- Argon2 wheel and all modules install offline on CPython 3.11 x64.
- Both Alembic lineages and CLI entry points are packaged.
- Config examples contain placeholders only.
- Fleet preflight output is redacted.
- Apache proxy keeps one origin and supports tenant paths.

---

## References

- OWASP Password Storage Cheat Sheet: Argon2id and parameter benchmarking.
- OWASP Authentication Cheat Sheet: generic failures and login throttling.
- OWASP Session Management Cheat Sheet: opaque CSPRNG IDs, server-side state and cookie flags.
- PostgreSQL 11 Row Security Policies: owner bypass, FORCE RLS and policy behavior.
- SQLAlchemy 2 engine/session APIs and Psycopg 3 PostgreSQL connection parameters.
- Microsoft DPAPI documentation for machine/service-account-bound secret protection.
