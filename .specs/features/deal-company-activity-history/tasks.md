# Histórico Operacional de Negócios e Empresas V1 — Tasks

## Execution Protocol (MANDATORY -- do not skip)

Implement these tasks with the `tlc-spec-driven` skill: **activate it by name and follow its Execute flow and Critical Rules.** The skill is the source of truth for the per-task cycle, atomic commits, adequacy review and independent Verifier.

**If the skill cannot be activated, STOP and tell the user — do not proceed without it.**

---

**Design**: `.specs/features/deal-company-activity-history/design.md`  
**Status**: Approved

---

## Test Coverage Matrix

> Generated from `README.md`, `pyproject.toml`, `package.json`, the feature spec/design and 8 sampled backend/browser test areas. Guidelines found: `README.md`, `pyproject.toml`, `package.json`; no separate `AGENTS.md`, `CONTRIBUTING.md` or numeric coverage threshold was found, so strong defaults apply.

| Code Layer | Required Test Type | Coverage Expectation | Location Pattern | Run Command |
| ---------- | ------------------ | -------------------- | ---------------- | ----------- |
| SQLAlchemy/Pydantic contracts | unit | Subject check, immutable metadata, typed details, cursor/category enums, observation bounds and aliases | `tests/backend/test_models.py`, `tests/backend/test_schemas.py` | `.venv\Scripts\python.exe -m pytest --basetemp .local/pytest-activity tests/backend/test_models.py tests/backend/test_schemas.py -q` |
| Alembic tenant schema/RLS/backfill | PostgreSQL integration | Upgrade, stage/company backfill, dedupe, indexes, forced RLS, preservation fingerprint and isolated downgrade | `tests/backend/test_migrations.py`, `tests/backend/test_tenant_migration_security.py` | `.venv\Scripts\python.exe -m pytest --basetemp .local/pytest-activity tests/backend/test_migrations.py tests/backend/test_tenant_migration_security.py -q` |
| Activity repository/service | unit + PostgreSQL integration | Append-only writes, keyset order/filtering, idempotency, authorization, redaction, rollback and no cross-tenant access | `tests/backend/test_activity_repository.py`, `tests/backend/test_activity_service.py` | `.venv\Scripts\python.exe -m pytest --basetemp .local/pytest-activity tests/backend/test_activity_repository.py tests/backend/test_activity_service.py -q` |
| Company Deal read model | unit + PostgreSQL integration | Visibility parity, active-only list, exact Decimal totals, open/won/lost semantics, stage rename and empty state | `tests/backend/test_company_deals.py`, `tests/backend/test_authorization.py` | `.venv\Scripts\python.exe -m pytest --basetemp .local/pytest-activity tests/backend/test_company_deals.py tests/backend/test_authorization.py -q` |
| Workspace/pipeline/automation integration | PostgreSQL integration | Movement/history parity, Company diffs, billing success/failure, retry dedupe, normal and bulk paths, full rollback | `tests/backend/test_workspace_service.py`, `tests/backend/test_pipeline_service.py` | `.venv\Scripts\python.exe -m pytest --basetemp .local/pytest-activity tests/backend/test_workspace_service.py tests/backend/test_pipeline_service.py -q` |
| Activity and Company APIs | API + PostgreSQL integration | Happy path, 401/403/404/422/503, exact Origin, no-store, forged IDs, pagination and response contracts | `tests/backend/test_activity_api.py`, `tests/backend/test_company_api.py` | `.venv\Scripts\python.exe -m pytest --basetemp .local/pytest-activity tests/backend/test_activity_api.py tests/backend/test_company_api.py -q` |
| Tenant isolation | multi-database PostgreSQL integration | Same IDs in separate databases, missing RLS context, forged workspace/tenant and fail-closed dependency behavior | `tests/backend/test_repository_tenant_scope.py`, `tests/backend/test_tenant_router.py` | `.venv\Scripts\python.exe -m pytest --basetemp .local/pytest-activity tests/backend/test_repository_tenant_scope.py tests/backend/test_tenant_router.py -q` |
| Deal/Company frontend | browser e2e | Wide responsive drawer, filters, cursor paging, observation retry/reload, exact summaries, nested Deal navigation, keyboard and failure states | `tests/ui-prototype.spec.cjs` | `pnpm test` |
| Fleet/package/runbook | unit + contract integration | New tenant head, explicit selected tenant, package manifest, PostgreSQL 11 compatibility and unchanged shared-database boundary | `tests/backend/test_fleet.py`, `tests/backend/test_windows_multitenant_bundle.py`, `tests/backend/test_manual_windows_pg11_outcomes.py` | `.venv\Scripts\python.exe -m pytest --basetemp .local/pytest-activity tests/backend/test_fleet.py tests/backend/test_windows_multitenant_bundle.py tests/backend/test_manual_windows_pg11_outcomes.py -q` |
| Documentation/spec artifacts | structural + full regression | TLC validators, requirement evidence, discrimination mutants and fresh independent Verifier | `.specs/features/deal-company-activity-history`, `README.md`, deployment runbook | build gate + TLC validators |

## Gate Check Commands

> Generated from repository commands in `README.md`, `pyproject.toml` and `package.json`; recapture the baseline before Execute.

| Gate Level | When to Use | Command |
| ---------- | ----------- | ------- |
| Quick | Contract or isolated policy changes | `.venv\Scripts\python.exe -m pytest --basetemp .local/pytest-activity tests/backend/test_models.py tests/backend/test_schemas.py tests/backend/test_authorization.py -q` |
| Full | Repository/service/API/browser behavior | `.venv\Scripts\python.exe -m pytest --basetemp .local/pytest-activity tests/backend -q` followed by `pnpm test` |
| Build | Migration, phase completion, package or release evidence | `.venv\Scripts\python.exe -m compileall -q app`; `docker compose config --quiet`; `.venv\Scripts\python.exe -m pytest --basetemp .local/pytest-activity tests/backend -q`; `pnpm test`; `.venv\Scripts\python.exe scripts/verify_demo.py` |
| Structural | Before approval and after every specification change | `python C:\Users\luizf\.codex\skills\tlc-spec-driven\scripts\validate_spec.py .specs/features/deal-company-activity-history --root . --strict`; `python C:\Users\luizf\.codex\skills\tlc-spec-driven\scripts\validate_tasks.py .specs/features/deal-company-activity-history --root . --strict` |

---

## Execution Plan

Phases execute sequentially. Every implementation task includes its tests in the same atomic commit.

### Phase 1: Contracts and tenant persistence

```text
T1 → T2 → T3 → T4
```

### Phase 2: Transactional backend and APIs

```text
T5 → T6 → T7 → T8 → T9 → T10 → T11 → T12
```

### Phase 3: Wide Deal and Company experience

```text
T13 → T14 → T15 → T16
```

### Phase 4: Fleet readiness and independent evidence

```text
T17 → T18
```

---

## Task Breakdown

### Phase 1: Contracts and tenant persistence

#### T1: Define the append-only activity model

**Status**: Complete

**What**: Add `CrmActivityEvent` with typed subject FKs, actor snapshot, safe details, deterministic dedupe and immutable ordering fields.  
**Where**: `app/models.py`  
**Depends on**: None  
**Reuses**: Existing `Base`, workspace scope, named constraints, UUID relationships and timezone-aware timestamp conventions.  
**Requirement**: HIST-01, HIST-02, HIST-03, HIST-06, HIST-07

**Tools**:

- MCP: NONE
- Local: `apply_patch`, shell test runner
- Skill: `tlc-spec-driven`

**Done when**:

- [x] The table enforces exactly one Deal/Company subject, valid category/type fields and a unique workspace dedupe key.
- [x] Both subject indexes order by workspace, subject, occurrence time descending and ID descending.
- [x] Actor name remains a snapshot even if the user later changes or is deactivated.
- [x] No update/delete helper or soft-delete column is introduced for events.
- [x] Model tests prove every constraint/index/type and the quick gate passes without removing or skipping prior tests.

**Tests**: unit — extend `tests/backend/test_models.py`  
**Gate**: quick  
**Commit**: `feat(activity): define append only event model`

#### T2: Define strict activity and Company Deal contracts

**Status**: Complete

**What**: Add response, filter, cursor, observation and Company Deal summary/list schemas with fixed money serialization.  
**Where**: `app/schemas.py`  
**Depends on**: T1  
**Reuses**: Existing strict camelCase Pydantic base models, validation error paths and pipeline semantic types.  
**Requirement**: HIST-01, HIST-03, HIST-05, HIST-06

**Tools**:

- MCP: NONE
- Local: `apply_patch`, shell test runner
- Skill: `tlc-spec-driven`

**Done when**:

- [x] Category filters accept only movement, automation and observation values.
- [x] Observation text trims to 1..4,000 characters and requires a UUID idempotency key.
- [x] Cursor and page size contracts cap each page at 50 and reject malformed cursors.
- [x] Monetary totals serialize as exact two-decimal strings and list items expose canonical stage semantics.
- [x] Schema tests cover every boundary/alias and the quick gate passes without weakening prior assertions.

**Tests**: unit — extend `tests/backend/test_schemas.py`  
**Gate**: quick  
**Commit**: `feat(activity): define timeline api contracts`

#### T3: Add the tenant activity migration and historical backfill

**Status**: Complete

**What**: Create the next additive tenant Alembic revision with the activity table, RLS, indexes and deterministic Deal/Company backfill.  
**Where**: `migrations/versions/<new_revision>_add_crm_activity_events.py`  
**Depends on**: T2  
**Reuses**: Forced-RLS policy and PostgreSQL 11-compatible migration patterns from the current tenant head `c7f3a9d8e2b1`.  
**Requirement**: HIST-01, HIST-06, HIST-07

**Tools**:

- MCP: NONE
- Local: `apply_patch`, PostgreSQL integration runner
- Skill: `tlc-spec-driven`

**Done when**:

- [x] Upgrade creates the table, exactly-one-subject constraint, unique dedupe constraint, covering indexes and forced workspace RLS.
- [x] Every existing stage-history row becomes one movement event with historical timestamp/snapshots and deterministic legacy dedupe key.
- [x] Every existing Company receives one migration-labelled creation event without claiming a human actor.
- [x] Upgrade preserves all pre-existing fingerprints; repeat upgrade is idempotent; isolated downgrade removes only the new feature schema.
- [x] Missing scope and cross-workspace operations fail closed in migration/security tests.
- [x] Build gate passes without touching the control schema, shared DW databases or global PostgreSQL configuration.

**Tests**: PostgreSQL integration — extend `tests/backend/test_migrations.py` and `tests/backend/test_tenant_migration_security.py` in this same task  
**Gate**: build  
**Commit**: `feat(activity): migrate tenant activity history`

#### T4: Implement the tenant-scoped activity repository

**Status**: Complete

**What**: Add append, idempotent lookup and filtered keyset paging for Deal and Company activity streams.  
**Where**: `app/repositories/activity.py`  
**Depends on**: T3  
**Reuses**: Workspace context verification, SQLAlchemy session transactions and repository RLS conventions.  
**Requirement**: HIST-01, HIST-02, HIST-03, HIST-06, HIST-07

**Tools**:

- MCP: NONE
- Local: `apply_patch`, PostgreSQL integration runner
- Skill: `tlc-spec-driven`

**Done when**:

- [x] Append accepts only server-built typed event data and returns the prior row for the same dedupe key.
- [x] Deal and Company queries require workspace plus subject identity and order by `(occurred_at DESC, id DESC)`.
- [x] Category filters and opaque timestamp/ID cursors cannot skip or duplicate equal-timestamp rows.
- [x] The repository exposes no event update/delete path.
- [x] Integration tests cover dedupe, 51+ items, equal timestamps, foreign workspace, missing RLS and rollback.
- [x] Full gate passes without removing or skipping prior tests.

**Tests**: PostgreSQL integration — add `tests/backend/test_activity_repository.py`  
**Gate**: full  
**Commit**: `feat(activity): add tenant scoped event repository`

### Phase 2: Transactional backend and APIs

#### T5: Implement activity read and observation services

**Status**: Complete

**What**: Orchestrate canonical entity lookup, record authorization, cursor handling and immutable observation creation.  
**Where**: `app/services/activity.py`  
**Depends on**: T4  
**Reuses**: `PrincipalScope`, current record policies, typed service errors and request transaction boundaries.  
**Requirement**: HIST-01, HIST-03, HIST-06, HIST-07

**Tools**:

- MCP: NONE
- Local: `apply_patch`, shell/PostgreSQL test runner
- Skill: `tlc-spec-driven`

**Done when**:

- [x] Read uses the entity's existing visibility rule and returns generic not-found for missing, hidden or foreign records.
- [x] Observation write uses mutation permission and derives tenant, workspace, actor and time only from server context.
- [x] Repeating a request UUID returns the original event without incrementing workspace version or duplicating data.
- [x] No edit/delete service exists; correction is represented by a new observation.
- [x] Tests cover every role, valid/empty/oversized/HTML text, retry, unavailable database and immutable reload.
- [x] Full gate passes without weakening existing authorization tests.

**Tests**: unit + PostgreSQL integration — add `tests/backend/test_activity_service.py`  
**Gate**: full  
**Commit**: `feat(activity): add timeline and observation service`

#### T6: Add a reusable SQL record-visibility predicate

**Status**: Complete

**What**: Express the existing Python Deal visibility rules as one SQL predicate for safe aggregate/list queries.  
**Where**: `app/policies.py`  
**Depends on**: T5  
**Reuses**: `can_read_record`, role/team/responsible/assistant semantics and existing action policy map.  
**Requirement**: HIST-05, HIST-07

**Tools**:

- MCP: NONE
- Local: `apply_patch`, PostgreSQL test runner
- Skill: `tlc-spec-driven`

**Done when**:

- [x] The SQL predicate implements the same Deal visibility as `can_read_record` for every supported role.
- [x] It always includes workspace scope and cannot be used without a bound principal.
- [x] Parity tests compare Python and SQL results for responsible, team, assistant, foreign-team and admin cases.
- [x] Forged IDs and missing scope reveal neither row existence nor aggregate values.
- [x] Quick and targeted PostgreSQL gates pass without changing unrelated permissions.

**Tests**: unit + PostgreSQL integration — extend `tests/backend/test_authorization.py`  
**Gate**: quick  
**Commit**: `feat(auth): add sql deal visibility predicate`

#### T7: Implement the Company Deal read model

**Status**: Complete

**What**: Query visible active Deals for one Company and derive exact total/open/won/lost quantities and values plus the canonical list.  
**Where**: `app/repositories/company_deals.py`  
**Depends on**: T6  
**Reuses**: Deal/stage canonical relationships, semantic types, Decimal money and the SQL visibility predicate.  
**Requirement**: HIST-05, HIST-07

**Tools**:

- MCP: NONE
- Local: `apply_patch`, PostgreSQL integration runner
- Skill: `tlc-spec-driven`

**Done when**:

- [x] Aggregation includes only active visible Deals linked to the requested active Company/workspace.
- [x] Total and semantic buckets return exact Decimal sums with null amount treated as zero only for aggregation.
- [x] List returns title, canonical stage label/semantic, responsible and amount in deterministic order.
- [x] Stage rename does not change buckets; moving Company/value/semantic does; soft-deleted/foreign Deals never contribute.
- [x] Empty, all-zero, all-semantic and role-restricted cases are covered in integration tests.
- [x] Full gate passes without browser-derived totals.

**Tests**: PostgreSQL integration — add `tests/backend/test_company_deals.py`  
**Gate**: full  
**Commit**: `feat(company): add linked deal summary repository`

#### T8: Move billing automation into a server executor

**Status**: Planned

**What**: Implement one server-owned Deal automation executor that applies billing reassignment/notification and returns a safe execution result.  
**Where**: `app/services/deal_automation.py`  
**Depends on**: T7  
**Reuses**: Pipeline `system_key=billing`, current responsible/notification behavior and activity dedupe conventions.  
**Requirement**: HIST-02, HIST-07

**Tools**:

- MCP: NONE
- Local: `apply_patch`, PostgreSQL test runner
- Skill: `tlc-spec-driven`

**Done when**:

- [ ] Billing behavior no longer depends on a visible stage name or a browser-only side effect.
- [ ] One execution returns rule key/name, success/failure and a whitelisted action summary suitable for one activity event.
- [ ] Missing billing target records failure without reassignment and without secrets, stack traces or raw payloads.
- [ ] A deterministic execution key prevents duplicate notifications/events on retry.
- [ ] Tests cover success, no-op, failure, multiple recipients and injected rollback.
- [ ] Full gate passes before the client-side implementation is removed in T14.

**Tests**: unit + PostgreSQL integration — add `tests/backend/test_deal_automation.py`  
**Gate**: full  
**Commit**: `feat(automation): execute billing transitions on server`

#### T9: Collect Deal and Company activities during workspace save

**Status**: Planned

**What**: Integrate canonical before/after collection, legacy stage-history dual-write, automation execution and Company change events into workspace save.  
**Where**: `app/services/workspace.py`  
**Depends on**: T8  
**Reuses**: Existing authorized projection/merge, optimistic workspace version, repository reconcile and server-owned stage history.  
**Requirement**: HIST-02, HIST-06, HIST-07

**Tools**:

- MCP: NONE
- Local: `apply_patch`, PostgreSQL integration runner
- Skill: `tlc-spec-driven`

**Done when**:

- [ ] Each confirmed stage transition dual-writes one legacy history row and one movement event in the same transaction.
- [ ] Billing state, notification and one automation event commit atomically after canonical stage validation.
- [ ] Company creation/change emits only whitelisted own fields with before/after values; no-op creates no event.
- [ ] Browser-submitted history, actor, tenant, timestamp or activity fields cannot be persisted.
- [ ] Any reconcile/activity/automation failure rolls back workspace version, commercial rows, notifications and events together.
- [ ] Workspace tests cover normal save, retry, undo semantics, Company diff/redaction and full rollback; build gate passes.

**Tests**: PostgreSQL integration — extend `tests/backend/test_workspace_service.py`  
**Gate**: build  
**Commit**: `feat(activity): collect workspace deal and company events`

#### T10: Emit activities during administrative stage transfers

**Status**: Planned

**What**: Integrate the shared transition/automation activity writer into bulk archive-and-transfer operations.  
**Where**: `app/services/pipeline.py`  
**Depends on**: T9  
**Reuses**: Existing row locks, transfer results, pipeline audit and workspace-version transaction.  
**Requirement**: HIST-01, HIST-02, HIST-07

**Tools**:

- MCP: NONE
- Local: `apply_patch`, PostgreSQL integration runner
- Skill: `tlc-spec-driven`

**Done when**:

- [ ] Every transferred active or soft-deleted Deal receives one movement event with administrative actor and stage snapshots.
- [ ] Eligible targets run the same server automation executor as ordinary save and emit at most one automation event per Deal.
- [ ] Pipeline audit, Deal state/history, notifications, activity events and workspace version are one transaction.
- [ ] Retry and injected failure prove deterministic dedupe and zero partial writes.
- [ ] Existing archive/semantic/soft-delete behavior remains green and the build gate passes.

**Tests**: PostgreSQL integration — extend `tests/backend/test_pipeline_service.py`  
**Gate**: build  
**Commit**: `feat(activity): record bulk pipeline transfers`

#### T11: Expose Deal activity and observation APIs

**Status**: Planned

**What**: Add authorized Deal timeline GET and observation POST routes with stable contracts and failure mapping.  
**Where**: `app/main.py`  
**Depends on**: T10  
**Reuses**: Principal dependency, exact-Origin checks, `no-store`, validation/error envelope and tenant session transaction.  
**Requirement**: HIST-01, HIST-03, HIST-07

**Tools**:

- MCP: NONE
- Local: `apply_patch`, API/PostgreSQL test runner
- Skill: `tlc-spec-driven`

**Done when**:

- [ ] `GET /api/deals/{deal_id}/activities` supports category, limit and opaque cursor.
- [ ] `POST /api/deals/{deal_id}/observations` requires exact Origin and returns original event for an idempotent retry.
- [ ] Routes return stable 401/403/404/422/503 envelopes, `no-store` and no tenant/entity metadata leaks.
- [ ] Client-supplied actor/workspace/tenant/timestamp fields are rejected or ignored by strict contracts.
- [ ] API tests cover every route branch, permissions, pagination, forgery and database failure; full gate passes.

**Tests**: API + PostgreSQL integration — add `tests/backend/test_activity_api.py`  
**Gate**: full  
**Commit**: `feat(activity): expose deal timeline api`

#### T12: Expose Company activities and linked Deal APIs

**Status**: Planned

**What**: Add Company history GET, observation POST and linked-Deal summary/list GET routes.  
**Where**: `app/main.py`  
**Depends on**: T11  
**Reuses**: Activity service, Company Deal repository, Deal API error mapping and visibility rules.  
**Requirement**: HIST-03, HIST-05, HIST-06, HIST-07

**Tools**:

- MCP: NONE
- Local: `apply_patch`, API/PostgreSQL test runner
- Skill: `tlc-spec-driven`

**Done when**:

- [ ] `GET /api/companies/{company_id}/activities` and `POST /api/companies/{company_id}/observations` match Deal timeline semantics.
- [ ] `GET /api/companies/{company_id}/deals` returns exact summary plus only visible active Deal rows.
- [ ] Hidden/missing/foreign Company and Deal data are indistinguishable through status, totals and timing-insensitive response shape.
- [ ] Company history never copies linked Deal movement/automation events.
- [ ] API tests cover empty/full summaries, all roles, semantic rename, soft delete, forgery and dependency failure; build gate passes.

**Tests**: API + PostgreSQL integration — add `tests/backend/test_company_api.py`  
**Gate**: build  
**Commit**: `feat(company): expose history and linked deals api`

### Phase 3: Wide Deal and Company experience

#### T13: Add the wide responsive entity drawer shell

**Status**: Planned

**What**: Expand only Deal and Company drawers into a large accessible workspace while preserving Lead/Contact behavior.  
**Where**: `app/static/index.html`  
**Depends on**: T12  
**Reuses**: Existing drawer lifecycle, close/Escape/focus handling, cards, tabs and responsive breakpoints.  
**Requirement**: HIST-04, HIST-05, HIST-06

**Tools**:

- MCP: NONE
- Local: `apply_patch`, Playwright runner
- Skill: `tlc-spec-driven`

**Done when**:

- [ ] Desktop Deal/Company width is `min(1600px, calc(100vw - 32px))` and uses the approved high-density layout.
- [ ] Deal uses data-left/activity-right columns; Company exposes Informações, Negócios and Histórico areas.
- [ ] Narrow view stacks or tabs content without page-level horizontal scrolling.
- [ ] Existing fields, custom fields, quotes, close button, Escape and focus restoration remain functional.
- [ ] Browser tests cover desktop/mobile, keyboard, Lead/Contact unchanged and no inaccessible hidden content.
- [ ] Full gate passes without an unrelated frontend refactor.

**Tests**: browser e2e — extend `tests/ui-prototype.spec.cjs`  
**Gate**: full  
**Commit**: `feat(ui): add wide responsive crm drawer`

#### T14: Add the Deal activity timeline experience

**Status**: Planned

**What**: Render Deal movement/automation/observation timeline with filters, loading states, paging and immutable observation composer.  
**Where**: `app/static/index.html`  
**Depends on**: T13  
**Reuses**: Existing authenticated fetch wrapper, toast/error states, escape helper and canonical save lifecycle.  
**Requirement**: HIST-01, HIST-02, HIST-03, HIST-04

**Tools**:

- MCP: NONE
- Local: `apply_patch`, Playwright runner
- Skill: `tlc-spec-driven`

**Done when**:

- [ ] Timeline loads only for the currently open Deal and ignores late responses from a prior record.
- [ ] All/movement/automation/observation filters and cursor `Carregar mais` preserve newest-first order.
- [ ] Loading, empty, error/retry and 51+ event states are distinct while Deal fields remain usable.
- [ ] Observation double-click/retry creates one escaped plain-text item at the top and survives reload.
- [ ] Stage movement into billing shows server-confirmed responsible, notification and exactly one automation event; browser-owned billing mutation is removed.
- [ ] Browser tests include keyboard/mobile/failure paths and a mutant disabling server automation fails; build gate passes.

**Tests**: browser e2e — extend `tests/ui-prototype.spec.cjs`  
**Gate**: build  
**Commit**: `feat(ui): add deal activity timeline`

#### T15: Add the Company linked-Deal dashboard

**Status**: Planned

**What**: Render Company summary cards and the visible linked-Deal list, with nested navigation into the Deal drawer.  
**Where**: `app/static/index.html`  
**Depends on**: T14  
**Reuses**: Company tabs, money formatter, semantic labels, responsive cards and entity drawer navigation.  
**Requirement**: HIST-05

**Tools**:

- MCP: NONE
- Local: `apply_patch`, Playwright runner
- Skill: `tlc-spec-driven`

**Done when**:

- [ ] Cards show total and exact quantity/value for em andamento, ganhos and perdidos from the API response.
- [ ] Linked list shows title, canonical stage, semantic status, responsible and value, including a normal empty state.
- [ ] Selecting a Deal opens its detailed drawer and closing/back navigation restores the originating Company context.
- [ ] Rename, value/company/semantic move and soft-delete refresh show canonical server results rather than local recomputation.
- [ ] Browser tests cover zero, mixed semantics, restricted visibility, nested navigation and a semantic-grouping mutant; full gate passes.

**Tests**: browser e2e — extend `tests/ui-prototype.spec.cjs`  
**Gate**: full  
**Commit**: `feat(ui): add company deal dashboard`

#### T16: Add the Company history experience

**Status**: Planned

**What**: Render Company creation/change/observation history with immutable composer, filters/states and cursor paging.  
**Where**: `app/static/index.html`  
**Depends on**: T15  
**Reuses**: Deal timeline components and request-generation guard without duplicating activity logic.  
**Requirement**: HIST-03, HIST-06

**Tools**:

- MCP: NONE
- Local: `apply_patch`, Playwright runner
- Skill: `tlc-spec-driven`

**Done when**:

- [ ] Company history displays creation, whitelisted before/after changes and observations with actor/time.
- [ ] No-op saves and linked Deal movement/automation do not create Company history cards.
- [ ] Observation rendering is escaped, immutable, idempotent and immediately visible after success.
- [ ] Loading, empty, error/retry, paging, narrow layout and keyboard behavior match the Deal timeline.
- [ ] Browser tests cover reload, correction note, late response, 51+ items and absence of Deal-event duplication; build gate passes.

**Tests**: browser e2e — extend `tests/ui-prototype.spec.cjs`  
**Gate**: build  
**Commit**: `feat(ui): add company activity history`

### Phase 4: Fleet readiness and independent evidence

#### T17: Advance the supported tenant revision safely

**Status**: Planned

**What**: Update fleet verification and package contracts to recognize the new tenant head only after explicit migration verification.  
**Where**: `app/fleet.py`  
**Depends on**: T16  
**Reuses**: Explicit selected-tenant migration, backup acknowledgement, identity preflight and side-by-side offline package gates.  
**Requirement**: HIST-07

**Tools**:

- MCP: NONE
- Local: `apply_patch`, shell/PostgreSQL/package test runner
- Skill: `tlc-spec-driven`

**Done when**:

- [ ] Fleet migration targets the new tenant head only for explicitly selected tenants and confirms schema/identity before updating control metadata.
- [ ] Failure leaves expected revision unchanged and reports a redacted per-tenant outcome.
- [ ] Offline package includes the migration and changed runtime/static files with valid manifest integrity.
- [ ] PostgreSQL 11, HBA isolation, `DW_CMS`, `DW_PRODUTOS`, service identity and side-by-side rollback boundaries remain unchanged.
- [ ] Fleet/package/runbook tests include unselected tenant and failure injection; build gate passes.
- [ ] No upload, push, production migration, task-scheduler or server change is performed.

**Tests**: unit + contract + PostgreSQL integration — extend fleet/package/runbook backend tests in this same task  
**Gate**: build  
**Commit**: `feat(fleet): support activity history tenant head`

#### T18: Publish traceable local release evidence

**Status**: Planned

**What**: Record complete local evidence, requirement traceability and a no-execution deployment/rollback checklist after all gates pass.  
**Where**: `.specs/features/deal-company-activity-history/validation.md`  
**Depends on**: T17  
**Reuses**: README verification commands, Windows side-by-side runbook, TLC validators and evidence-or-zero Verifier process.  
**Requirement**: HIST-01, HIST-02, HIST-03, HIST-04, HIST-05, HIST-06, HIST-07

**Tools**:

- MCP: NONE
- Local: shell test runner, Git diff inspection
- Skill: `tlc-spec-driven`

**Done when**:

- [ ] README accurately describes Deal/Company history, current local-only status and excluded V1 tasks/metrics.
- [ ] Every requirement and edge case cites exact automated evidence; backend/browser counts are not below baseline and no test was removed/skipped/weakened.
- [ ] Build and Structural gates pass; feature-specific state is complete even if the previously documented unrelated Apache validation remains unresolved.
- [ ] Behavior-level mutants for activity append, server billing automation, tenant predicate and semantic Company grouping each cause the expected test failure.
- [ ] A fresh independent Verifier (not the author) runs adequacy, discrimination and evidence-or-zero checks and records PASS.
- [ ] Deployment checklist separates backup, upload, migration, cutover, UAT and rollback but executes none of them.

**Tests**: structural + full regression — TLC validators, Build gate, discrimination sensor and independent Verifier  
**Gate**: build  
**Commit**: `docs(activity): publish verified release evidence`

---

## Phase Execution Map

```text
Phase 1: T1 → T2 → T3 → T4
Phase 2: T5 → T6 → T7 → T8 → T9 → T10 → T11 → T12
Phase 3: T13 → T14 → T15 → T16
Phase 4: T17 → T18
```

Cross-phase entry dependencies are T5 on T4, T13 on T12 and T17 on T16. Execution remains sequential. With 18 tasks, Execute must offer task-budgeted phase batches before T1; agents are used only if the user explicitly accepts.

---

## Task Granularity Check

| Task | Single deliverable | Status |
| ---- | ------------------ | ------ |
| T1 | Activity SQLAlchemy model | Granular |
| T2 | Activity/API Pydantic contracts | Granular |
| T3 | Tenant migration/backfill/RLS | Granular |
| T4 | Activity repository | Granular |
| T5 | Activity service | Granular |
| T6 | SQL visibility predicate | Granular |
| T7 | Company Deal read model | Granular |
| T8 | Server automation executor | Granular |
| T9 | Workspace activity integration | Granular |
| T10 | Bulk-transfer activity integration | Granular |
| T11 | Deal activity APIs | Granular |
| T12 | Company activity/Deal APIs | Granular |
| T13 | Wide responsive drawer shell | Granular |
| T14 | Deal timeline UI | Granular |
| T15 | Company Deal dashboard UI | Granular |
| T16 | Company history UI | Granular |
| T17 | Fleet/package revision | Granular |
| T18 | Validation evidence/checklist | Granular |

---

## Diagram-Definition Cross-Check

| Task | Depends On | Diagram Shows | Status |
| ---- | ---------- | ------------- | ------ |
| T1 | None | Start | Match |
| T2 | T1 | T1 → T2 | Match |
| T3 | T2 | T2 → T3 | Match |
| T4 | T3 | T3 → T4 | Match |
| T5 | T4 | Cross-phase entry | Match |
| T6 | T5 | T5 → T6 | Match |
| T7 | T6 | T6 → T7 | Match |
| T8 | T7 | T7 → T8 | Match |
| T9 | T8 | T8 → T9 | Match |
| T10 | T9 | T9 → T10 | Match |
| T11 | T10 | T10 → T11 | Match |
| T12 | T11 | T11 → T12 | Match |
| T13 | T12 | Cross-phase entry | Match |
| T14 | T13 | T13 → T14 | Match |
| T15 | T14 | T14 → T15 | Match |
| T16 | T15 | T15 → T16 | Match |
| T17 | T16 | Cross-phase entry | Match |
| T18 | T17 | T17 → T18 | Match |

---

## Test Co-location Validation

| Task | Code Layer Created/Modified | Matrix Requires | Task Says | Status |
| ---- | --------------------------- | --------------- | --------- | ------ |
| T1 | Model | unit | unit | OK |
| T2 | Schemas | unit | unit | OK |
| T3 | Migration/RLS | PostgreSQL integration | PostgreSQL integration | OK |
| T4 | Repository | PostgreSQL integration | PostgreSQL integration | OK |
| T5 | Domain service | unit + PostgreSQL integration | unit + PostgreSQL integration | OK |
| T6 | Authorization predicate | unit + PostgreSQL integration | unit + PostgreSQL integration | OK |
| T7 | Company read model | PostgreSQL integration | PostgreSQL integration | OK |
| T8 | Automation service | unit + PostgreSQL integration | unit + PostgreSQL integration | OK |
| T9 | Workspace transaction | PostgreSQL integration | PostgreSQL integration | OK |
| T10 | Pipeline transaction | PostgreSQL integration | PostgreSQL integration | OK |
| T11 | Deal routes | API + PostgreSQL integration | API + PostgreSQL integration | OK |
| T12 | Company routes | API + PostgreSQL integration | API + PostgreSQL integration | OK |
| T13 | Drawer layout | browser e2e | browser e2e | OK |
| T14 | Deal timeline | browser e2e | browser e2e | OK |
| T15 | Company Deal dashboard | browser e2e | browser e2e | OK |
| T16 | Company history | browser e2e | browser e2e | OK |
| T17 | Fleet/package | unit + contract + PostgreSQL integration | unit + contract + PostgreSQL integration | OK |
| T18 | Documentation/validation | structural + full regression | structural + full regression | OK |

---

## Requirement Coverage

| Requirement | Tasks | Evidence target |
| ----------- | ----- | --------------- |
| HIST-01 | T1,T2,T3,T4,T5,T10,T11,T14,T18 | Tenant-scoped Deal timeline, filters and stable cursor |
| HIST-02 | T1,T4,T8,T9,T10,T14,T18 | Atomic movement/automation activities and server billing behavior |
| HIST-03 | T1,T2,T4,T5,T11,T12,T14,T16,T18 | Immutable idempotent Deal/Company observations |
| HIST-04 | T13,T14,T18 | Wide accessible responsive Deal workspace |
| HIST-05 | T2,T6,T7,T12,T13,T15,T18 | Exact visible Company Deal totals and list |
| HIST-06 | T1,T3,T4,T5,T9,T12,T13,T16,T18 | Company own change/observation history without Deal duplication |
| HIST-07 | T1,T3,T4,T5,T6,T7,T8,T9,T10,T11,T12,T17,T18 | Tenant isolation, RLS, redaction, migration and fleet safety |

**Coverage:** 7 requirements, 18 mapped tasks, 0 unmapped.

---

## Approval Gate Before Execute

1. User approves `spec.md`, `context.md`, `design.md` and this `tasks.md`.
2. User confirms `tlc-spec-driven` plus local filesystem/shell/PostgreSQL/Playwright as the tools for all tasks; no external plugin is required.
3. Because 18 tasks exceed one batch, user chooses sequential phase-batch sub-agents or inline execution before T1.
4. Baseline backend/browser counts and current dirty-worktree files are recaptured before modifying code.
5. Push, deploy, production backup/migration, task scheduler and server changes remain forbidden without explicit separate authorization.
