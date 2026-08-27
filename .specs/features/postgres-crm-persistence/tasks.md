# Persistência do Smart CRM no PostgreSQL - Tasks

## Execution Protocol (MANDATORY -- do not skip)

Implement these tasks with the `tlc-spec-driven` skill: **activate it by name and follow its Execute flow and Critical Rules.** Do not search for skill files by filesystem path. The skill is the source of truth for the full flow (per-task cycle, sub-agent delegation, adequacy review, Verifier, discrimination sensor).

**If the skill cannot be activated, STOP and tell the user - do not proceed without it.**

---

**Design**: `.specs/features/postgres-crm-persistence/design.md`  
**Status**: Approved

---

## Test Coverage Matrix

> Generated from codebase, project guidelines, and spec - confirm before Execute. Guidelines found: `README.md` (documented Playwright and Compose gates); no AGENTS/CONTRIBUTING/coverage configuration - strong defaults applied. Existing test sample: `tests/ui-prototype.spec.cjs`; environment gate: `scripts/verify_demo.py`.

| Code Layer | Required Test Type | Coverage Expectation | Location Pattern | Run Command |
| --- | --- | --- | --- | --- |
| Schemas and domain validation | unit | All branches; 1:1 mapping for applicable ACs and every listed validation edge | `tests/backend/test_schemas.py` | `python -m pytest tests/backend/test_schemas.py -q` |
| Repository and migrations | integration | Round-trip of every persisted table/value, constraints, rollback, soft delete/restore and migration currentness against PostgreSQL | `tests/backend/test_repository.py`, `test_migrations.py` | `python -m pytest tests/backend -q` |
| Workspace service | integration | All service branches; 1:1 to DBP-02-18 and all concurrency/atomicity edges | `tests/backend/test_workspace_service.py` | `python -m pytest tests/backend/test_workspace_service.py -q` |
| HTTP routes and middleware | integration | Every route: happy path, validation, conflicts, size limit, database failure and error envelope | `tests/backend/test_api.py` | `python -m pytest tests/backend/test_api.py -q` |
| Browser state and business flows | e2e | Preserve all 55 scenarios plus bootstrap, cross-context, conflicts, degraded cache, rollback and recovery | `tests/ui-prototype.spec.cjs` | `pnpm test` |
| Compose and runtime acceptance | integration | Build, health, schema/counts and persistence across app/PostgreSQL restart | `scripts/verify_demo.py` | `python scripts/verify_demo.py` |
| Entity/config/documentation | none | Build/config gate only | `app/models.py`, `pyproject.toml`, `Dockerfile`, `compose.yaml`, `README.md` | build gate only |

## Gate Check Commands

> Generated from codebase - confirm before Execute. The Python test command is introduced by T1; current `pnpm test` and `python scripts/verify_demo.py` are preserved.

| Gate Level | When to Use | Command |
| --- | --- | --- |
| Quick | After schema/domain/service tasks | `python -m pytest tests/backend -q` |
| Full | After API/frontend/integration tasks | Run separately: `python -m pytest tests/backend -q` then `pnpm test` |
| Build | After a phase or config/runtime task | Run separately: `python -m compileall -q app`; `docker compose config --quiet`; `python -m pytest tests/backend -q`; `pnpm test`; `python scripts/verify_demo.py` |

---

## Execution Plan

Phases run sequentially; tasks inside each phase also run sequentially.

### Phase 1: Runtime and schema

```
T1  T2  T3  T4
```

### Phase 2: Persistence core and API

```
T5  T6  T7  T8
```

### Phase 3: Browser integration

```
T9  T10
```

### Phase 4: Container and acceptance

```
T11  T12  T13  T14
```

---

## Task Breakdown

### T1: Define the Python package and test runtime

**Status**: Complete

**What**: Declare pinned-compatible runtime/development dependencies and pytest discovery for FastAPI, SQLAlchemy, Psycopg, Alembic and backend tests.
**Where**: `pyproject.toml`
**Depends on**: None
**Reuses**: Python 3.12 base already declared by `Dockerfile`.
**Requirement**: DBP-01, DBP-19, DBP-20

**Tools**:

- MCP: NONE
- Skill: `tlc-spec-driven`

**Done when**:

- [ ] Runtime and dev dependency groups are reproducible and exclude production credentials.
- [ ] Pytest is configured for `tests/backend`.
- [ ] `python -m compileall -q app` passes.
- [ ] No existing Node test script is changed or removed.

**Tests**: none - entity/config layer.
**Gate**: build
**Commit**: `build(api): define python persistence runtime`

### T2: Create database settings and session boundary

**Status**: Complete

**What**: Implement settings, SQLAlchemy engine/session creation, connection checking and test overrides as one database boundary.
**Where**: `app/database.py`
**Depends on**: T1
**Reuses**: Compose database names and environment variables.
**Requirement**: DBP-11, DBP-19, DBP-20, DBP-23

**Tools**:

- MCP: NONE
- Skill: `tlc-spec-driven`

**Done when**:

- [ ] Database URL is read only from environment/default local settings and secrets are not logged.
- [ ] Sessions rollback and close on exceptions.
- [ ] Engine uses connection pre-ping and is replaceable in tests.
- [ ] At least 4 integration tests cover URL/config, success, unavailable DB and rollback.
- [ ] Quick gate passes with no test deletion.

**Tests**: integration
**Gate**: quick
**Commit**: `feat(api): add database session boundary`

### T3: Define the normalized relational model

**Status**: Complete

**What**: Define SQLAlchemy metadata for workspace, teams, all CRM modules, links, custom fields, external fields, quotes, notifications and durable preferences.
**Where**: `app/models.py`
**Depends on**: T2
**Reuses**: State keys documented in `app/static/index.html:594-725`.
**Requirement**: DBP-01, DBP-12, DBP-13, DBP-14, DBP-15

**Tools**:

- MCP: NONE
- Skill: `tlc-spec-driven`

**Done when**:

- [ ] Every table and relationship from the design exists with named PK/FK/unique/check constraints.
- [ ] Deletable records include `deleted_at`; money uses fixed precision; times use timezone-aware columns.
- [ ] Empty and multi-valued custom fields have a lossless representation.
- [ ] Metadata tests assert table set, constraints and required indexes.
- [ ] Quick gate passes.

**Tests**: integration
**Gate**: quick
**Commit**: `feat(db): define normalized crm model`

### T4: Create the initial Alembic migration

**Status**: Complete

**What**: Add an Alembic environment and one initial revision that creates the normalized schema and singleton uninitialized workspace without touching the existing probe.
**Where**: `migrations/`
**Depends on**: T3
**Reuses**: SQLAlchemy metadata from T3 and existing PostgreSQL volume.
**Requirement**: DBP-01, DBP-18

**Tools**:

- MCP: NONE
- Skill: `tlc-spec-driven`

**Done when**:

- [ ] Upgrade from the current probe-only database reaches Alembic head.
- [ ] Re-running upgrade is idempotent.
- [ ] Downgrade/upgrade is tested in an isolated test database/schema, never against the user's volume.
- [ ] Probe table remains unchanged.
- [ ] At least 4 migration integration tests pass and quick gate is green.

**Tests**: integration
**Gate**: quick
**Commit**: `feat(db): add initial crm migration`

### T5: Define and validate the workspace contract

**Status**: Complete

**What**: Implement Pydantic request/response models plus cross-record validation and exact persisted counts.
**Where**: `app/schemas.py`
**Depends on**: T4
**Reuses**: `normalizeState()`, custom field types and entity keys in the frontend.
**Requirement**: DBP-02, DBP-03, DBP-04, DBP-06, DBP-14, DBP-15

**Tools**:

- MCP: NONE
- Skill: `tlc-spec-driven`

**Done when**:

- [ ] IDs are unique per module and every user/assistant/custom-field reference is validated.
- [ ] All current standard, Bitrix, custom, quote, notification and preference fields round-trip.
- [ ] Invalid reference errors include the stable payload path.
- [ ] Values `""`, `false`, `[]` and duplicate Bitrix headers with occurrence are preserved.
- [ ] Unit tests cover every validation branch and all six validation edge cases; quick gate passes.

**Tests**: unit
**Gate**: quick
**Commit**: `feat(api): validate workspace state contract`

### T6: Implement relational serialization and reconciliation

**Status**: Complete

**What**: Implement reading an active workspace and atomically reconciling one validated state into normalized tables while preserving deleted children.
**Where**: `app/repositories/workspace.py`
**Depends on**: T5
**Reuses**: Models from T3 and ordered arrays from the browser contract.
**Requirement**: DBP-03, DBP-11, DBP-12, DBP-13, DBP-14, DBP-15

**Tools**:

- MCP: NONE
- Skill: `tlc-spec-driven`

**Done when**:

- [ ] Insert/read round-trip is deep-equal for every durable field.
- [ ] Present records reactivate; absent active records receive `deleted_at`; missing records keep child rows.
- [ ] Teams and optional Company/Contact links are deterministic without changing display text.
- [ ] A forced intermediate exception leaves every table/count unchanged.
- [ ] At least 10 integration cases cover all table families, empty values, ordering, soft delete and rollback.
- [ ] Quick gate passes.

**Tests**: integration
**Gate**: quick
**Commit**: `feat(db): reconcile workspace aggregate`

### T7: Implement the versioned workspace service

**Status**: Complete

**What**: Implement bootstrap, load, save, reset, list-deleted and restore transactions with a locked singleton workspace and optimistic version.
**Where**: `app/services/workspace.py`
**Depends on**: T6
**Reuses**: Repository, schemas and database session boundary.
**Requirement**: DBP-02, DBP-03, DBP-04, DBP-05, DBP-08, DBP-10, DBP-11, DBP-12, DBP-13, DBP-18

**Tools**:

- MCP: NONE
- Skill: `tlc-spec-driven`

**Done when**:

- [ ] Bootstrap accepts exactly one concurrent winner and initializes version 1.
- [ ] Save/reset/restore require current version and increment exactly once.
- [ ] Stale versions return a typed conflict without reconciliation.
- [ ] Restore preserves links and detects active uniqueness conflicts.
- [ ] At least 15 integration cases map 1:1 to applicable ACs and concurrency/reset edges.
- [ ] Quick gate passes.

**Tests**: integration
**Gate**: quick
**Commit**: `feat(api): add versioned workspace service`

### T8: Expose the FastAPI and health contracts

**Status**: Complete

**What**: Build the application factory, API routes, 25 MB streaming guard, structured error IDs, security headers and static frontend mount.
**Where**: `app/main.py`
**Depends on**: T7
**Reuses**: Header/static behavior from `app/server.py` and workspace service.
**Requirement**: DBP-03-11, DBP-13, DBP-19, DBP-20, DBP-23

**Tools**:

- MCP: NONE
- Skill: `tlc-spec-driven`

**Done when**:

- [ ] All seven API/health routes match the design contracts.
- [ ] Bootstrap over 25 MB returns 413 before service invocation.
- [ ] Database unavailable returns health/API 503 while `/` still serves the CRM.
- [ ] Unexpected failures return/log the same UUID without leaking internals.
- [ ] Every route has happy, edge and error integration coverage (minimum 16 cases).
- [ ] Full gate passes.

**Tests**: integration
**Gate**: full
**Commit**: `feat(api): expose persistent workspace endpoints`

### T9: Initialize the browser from API or confirmed cache

**What**: Replace synchronous local initialization with API load, confirmed bootstrap dialog/counts, durable/transient merge and read-only fallback.
**Where**: `app/static/index.html`
**Depends on**: T8
**Reuses**: `seedState()`, `normalizeState()`, current render and dialog styles.
**Requirement**: DBP-02, DBP-03, DBP-05, DBP-07, DBP-14, DBP-16, DBP-21

**Tools**:

- MCP: NONE
- Skill: `tlc-spec-driven`, `browser:control-in-app-browser` for visual QA

**Done when**:

- [ ] Workspace is not writable until API initialization finishes.
- [ ] Empty DB shows module counts and only Admin can confirm bootstrap.
- [ ] Initialized DB wins over altered local commercial cache.
- [ ] Failed load uses only last confirmed cache/seed read-only with the exact warning.
- [ ] Browser tests cover bootstrap, DB-wins, cache fallback and no-cache fallback; all prior applicable scenarios remain.
- [ ] Full gate passes with no Playwright test deletion.

**Tests**: e2e
**Gate**: full
**Commit**: `feat(ui): initialize workspace from postgres api`

### T10: Route every durable browser mutation through persistence

**What**: Replace durable `saveState()` calls with one versioned `persistMutation()` per user action, including rollback/conflict, deletion recovery and reset.
**Where**: `app/static/index.html`
**Depends on**: T9
**Reuses**: All existing business mutation functions and toast/undo UI.
**Requirement**: DBP-08, DBP-09, DBP-10, DBP-12, DBP-13, DBP-15, DBP-16, DBP-17, DBP-22

**Tools**:

- MCP: NONE
- Skill: `tlc-spec-driven`, `browser:control-in-app-browser` for visual QA

**Done when**:

- [ ] Create/edit/convert/stage/undo/quote/CSV/users/notifications/fields/preferences persist after reload and second context.
- [ ] Search, selected profile and unsaved filters remain local and never increment workspace version.
- [ ] Each durable action increments version once; nested notification writes do not.
- [ ] Failed writes restore confirmed state and exact error; conflicts reload canonical server state.
- [ ] Deleted records can be listed and recovered with links.
- [ ] Existing 55 tests plus persistence/conflict/rollback/recovery cases pass with no deletion.
- [ ] Full gate passes.

**Tests**: e2e
**Gate**: full
**Commit**: `feat(ui): persist all crm mutations`

### T11: Build the API runtime image

**What**: Install the Python package, copy migrations/static code and run Uvicorn as the unprivileged user while retaining read-only compatibility.
**Where**: `Dockerfile`
**Depends on**: T10
**Reuses**: Existing Python 3.12 image, user, healthcheck and read-only runtime.
**Requirement**: DBP-01, DBP-18, DBP-19, DBP-20

**Tools**:

- MCP: NONE
- Skill: `tlc-spec-driven`

**Done when**:

- [ ] Image installs locked-compatible runtime dependencies before copying frequently changed source.
- [ ] Uvicorn serves `app.main:create_app` without root.
- [ ] Healthcheck accepts only database-ok health.
- [ ] Image contains Alembic revisions and starts read-only with `/tmp` only.
- [ ] Build gate passes.

**Tests**: none - entity/config layer.
**Gate**: build
**Commit**: `build(api): run fastapi persistence image`

### T12: Wire API and PostgreSQL in Compose

**What**: Add database URL, dependency health, test-mode control and restart-safe service configuration without replacing the named PostgreSQL volume.
**Where**: `compose.yaml`
**Depends on**: T11
**Reuses**: Existing `postgres` service, port overrides and volume.
**Requirement**: DBP-18, DBP-19, DBP-20

**Tools**:

- MCP: NONE
- Skill: `tlc-spec-driven`

**Done when**:

- [ ] CRM receives a Psycopg SQLAlchemy URL without exposing it to frontend code.
- [ ] Normal mode has test-only reset disabled.
- [ ] PostgreSQL volume name and loopback port remain unchanged.
- [ ] `docker compose config --quiet` and full build gate pass.

**Tests**: none - entity/config layer.
**Gate**: build
**Commit**: `build(compose): connect crm api to postgres`

### T13: Extend deterministic environment verification

**What**: Verify schema/head, bootstrap or existing data, table counts, API mutation, app recreation, PostgreSQL restart, degraded health and recovery without deleting the volume.
**Where**: `scripts/verify_demo.py`
**Depends on**: T12
**Reuses**: Current Compose helpers, HTTP fetch and probe preservation checks.
**Requirement**: DBP-01, DBP-03, DBP-18, DBP-19, DBP-20, DBP-23

**Tools**:

- MCP: NONE
- Skill: `tlc-spec-driven`

**Done when**:

- [ ] Verification is deterministic whether workspace starts empty or initialized.
- [ ] It compares API counts to direct SQL and preserves the existing probe.
- [ ] It recreates CRM and restarts PostgreSQL without `down -v`.
- [ ] It observes 503 degraded health while DB is stopped, then recovery to 200.
- [ ] Full verification passes and reports exact check count.

**Tests**: integration
**Gate**: full
**Commit**: `test(compose): verify postgres crm persistence`

### T14: Document the persistent test workflow

**What**: Update local instructions, first migration confirmation, DB inspection, backup/reset cautions, failure messages and remaining limitations.
**Where**: `README.md`
**Depends on**: T13
**Reuses**: Existing start, PostgreSQL and verification sections.
**Requirement**: DBP-02, DBP-18, DBP-19, DBP-20, DBP-21, DBP-22

**Tools**:

- MCP: NONE
- Skill: `tlc-spec-driven`

**Done when**:

- [ ] README no longer claims CRM data lives only in localStorage.
- [ ] It explains the one-time Admin confirmation and how to inspect counts safely.
- [ ] It states that `down -v` deletes test data and is never part of normal validation.
- [ ] It documents exact test commands and local-only security limitation.
- [ ] Build gate passes.

**Tests**: none - documentation layer.
**Gate**: build
**Commit**: `docs(readme): explain postgres-backed crm`

---

## Phase Execution Map

```
Phase 1  Phase 2  Phase 3  Phase 4

T1  T2  T3  T4  T5  T6  T7  T8  T9  T10  T11  T12  T13  T14
```

Execution is strictly sequential. With 14 tasks, phase-aligned packing yields multiple batches; sub-agents may be used only after explicit user confirmation.

---

## Task Granularity Check

| Task | Scope | Status |
| --- | --- | --- |
| T1 | one package/config contract | ? Granular |
| T2 | one database boundary | ? Granular |
| T3 | one relational metadata component | ? Granular |
| T4 | one migration environment/revision | ? Cohesive |
| T5 | one workspace schema/validator component | ? Cohesive |
| T6 | one repository component | ? Granular |
| T7 | one service component | ? Granular |
| T8 | one HTTP application component | ? Granular |
| T9 | one browser initialization flow | ? Granular |
| T10 | one browser write-through flow | ? Granular |
| T11 | one image definition | ? Granular |
| T12 | one Compose definition | ? Granular |
| T13 | one verifier script | ? Granular |
| T14 | one document | ? Granular |

---

## Diagram-Definition Cross-Check

| Task | Depends On | Diagram Shows | Status |
| --- | --- | --- | --- |
| T1 | None | start | ? Match |
| T2 | T1 | T1  T2 | ? Match |
| T3 | T2 | T2  T3 | ? Match |
| T4 | T3 | T3  T4 | ? Match |
| T5 | T4 | T4  T5 | ? Match |
| T6 | T5 | T5  T6 | ? Match |
| T7 | T6 | T6  T7 | ? Match |
| T8 | T7 | T7  T8 | ? Match |
| T9 | T8 | T8  T9 | ? Match |
| T10 | T9 | T9  T10 | ? Match |
| T11 | T10 | T10  T11 | ? Match |
| T12 | T11 | T11  T12 | ? Match |
| T13 | T12 | T12  T13 | ? Match |
| T14 | T13 | T13  T14 | ? Match |

---

## Test Co-location Validation

| Task | Layer | Matrix Requires | Task Says | Status |
| --- | --- | --- | --- | --- |
| T1 | config | none | none | ? OK |
| T2 | database boundary | integration | integration | ? OK |
| T3 | entity/schema metadata | integration for constraints | integration | ? OK |
| T4 | migrations | integration | integration | ? OK |
| T5 | domain validation | unit | unit | ? OK |
| T6 | repository | integration | integration | ? OK |
| T7 | service | integration | integration | ? OK |
| T8 | routes/middleware | integration | integration | ? OK |
| T9 | browser initialization | e2e | e2e | ? OK |
| T10 | browser business flows | e2e | e2e | ? OK |
| T11 | Docker config | none | none | ? OK |
| T12 | Compose config | none | none | ? OK |
| T13 | runtime acceptance | integration | integration | ? OK |
| T14 | documentation | none | none | ? OK |

