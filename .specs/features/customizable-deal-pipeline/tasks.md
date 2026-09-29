# Funil de Negócios Personalizável V1 — Tasks

## Execution Protocol (MANDATORY -- do not skip)

Implement these tasks with the `tlc-spec-driven` skill: **activate it by name and follow its Execute flow and Critical Rules.** The skill is the source of truth for the per-task cycle, atomic commits, adequacy review and independent Verifier.

**If the skill cannot be activated, STOP and tell the user — do not proceed without it.**

---

**Design**: `.specs/features/customizable-deal-pipeline/design.md`  
**Status**: Approved

---

## Test Coverage Matrix

> Generated from `README.md`, `pyproject.toml`, `package.json`, 9 sampled backend/browser test files and the feature spec. Guidelines found: `README.md`, `pyproject.toml`, `package.json`; no separate `AGENTS.md` or coverage threshold was found, so strong defaults apply.

| Code Layer | Required Test Type | Coverage Expectation | Location Pattern | Run Command |
| ---------- | ------------------ | -------------------- | ---------------- | ----------- |
| SQLAlchemy/Pydantic models | unit | Constraints, aliases and every validation boundary in PIPE-02 | `tests/backend/test_models.py`, `tests/backend/test_schemas.py` | `.venv\Scripts\python.exe -m pytest tests/backend/test_models.py tests/backend/test_schemas.py -q` |
| Alembic tenant schema/RLS | PostgreSQL integration | Upgrade, data preservation, backfill, unknown-stage abort, RLS, idempotent head and isolated downgrade | `tests/backend/test_migrations.py`, `tests/backend/test_tenant_migration_security.py` | `.venv\Scripts\python.exe -m pytest tests/backend/test_migrations.py tests/backend/test_tenant_migration_security.py -q` |
| Pipeline repository/service | PostgreSQL integration | All branches 1:1 to PIPE-01..PIPE-06; every listed edge case; transaction rollback evidence | `tests/backend/test_pipeline_repository.py`, `tests/backend/test_pipeline_service.py` | `.venv\Scripts\python.exe -m pytest tests/backend/test_pipeline_repository.py tests/backend/test_pipeline_service.py -q` |
| Authorization/API | API + PostgreSQL integration | Every route: happy path, 401/403, 409, 422, route/tenant forgery and failure path | `tests/backend/test_pipeline_api.py`, `tests/backend/test_authorization.py` | `.venv\Scripts\python.exe -m pytest tests/backend/test_pipeline_api.py tests/backend/test_authorization.py -q` |
| Workspace compatibility | PostgreSQL integration | Canonical stage IDs, stale/archived rejection, payload/history synchronization and snapshot conflict | `tests/backend/test_repository.py`, `tests/backend/test_workspace_service.py` | `.venv\Scripts\python.exe -m pytest tests/backend/test_repository.py tests/backend/test_workspace_service.py -q` |
| Frontend registry/admin UX | browser e2e | Dynamic read model, all editor actions, permissions, semantic regressions, transfer modal, conflict and history | `tests/ui-prototype.spec.cjs` | `pnpm test` |
| Fleet/package/runbook | unit + contract integration | Explicit tenant selection, target revision, rollback compatibility, offline package and unchanged shared PostgreSQL boundary | `tests/backend/test_fleet.py`, `tests/backend/test_windows_multitenant_bundle.py`, `tests/backend/test_manual_windows_pg11_outcomes.py` | `.venv\Scripts\python.exe -m pytest tests/backend/test_fleet.py tests/backend/test_windows_multitenant_bundle.py tests/backend/test_manual_windows_pg11_outcomes.py -q` |
| Documentation/spec artifacts | structural + full regression | Validators, complete regression gate and independent Verifier | `.specs/features/customizable-deal-pipeline`, `README.md`, deployment runbook | build gate + TLC validators |

## Gate Check Commands

> Generated from repository commands in `README.md`, `pyproject.toml` and `package.json`; confirm before Execute.

| Gate Level | When to Use | Command |
| ---------- | ----------- | ------- |
| Quick | Unit-only changes | `.venv\Scripts\python.exe -m pytest tests/backend/test_models.py tests/backend/test_schemas.py tests/backend/test_authorization.py -q` |
| Full | PostgreSQL/API/browser integration | `.venv\Scripts\python.exe -m pytest tests/backend -q` followed by `pnpm test` |
| Build | Phase completion, migration, packaging or docs | `.venv\Scripts\python.exe -m compileall -q app`; `docker compose config --quiet`; `.venv\Scripts\python.exe -m pytest tests/backend -q`; `pnpm test`; `.venv\Scripts\python.exe scripts/verify_demo.py` |

---

## Execution Plan

Phases execute sequentially. Each task receives its tests in the same atomic commit.

### Phase 1: Domain and tenant schema

```text
T1 → T2 → T3
```

### Phase 2: Transactional backend and API

```text
T3 → T4 → T5 → T6 → T7
```

### Phase 3: Dynamic frontend and administration

```text
T7 → T8 → T9 → T10
```

### Phase 4: Operations and release readiness

```text
T10 → T11 → T12
```

---

## Task Breakdown

### T1: Define pipeline domain models and contracts

**Status**: ✅ Complete

**What**: Add SQLAlchemy entities and strict request/response schemas for pipelines, stages, audit events and stable stage references.  
**Where**: `app/models.py`  
**Depends on**: None  
**Reuses**: Existing `Base`, timestamp mixins, aliases and strict Pydantic conventions.  
**Requirement**: PIPE-01, PIPE-02, PIPE-05

**Tools**:

- MCP: NONE
- Skill: `tlc-spec-driven`

**Done when**:

- [x] Models express workspace/pipeline/stage relationships, semantic checks and immutable identity fields from design.
- [x] Schemas enforce name, color, semantic, position, transfer and pagination bounds.
- [x] Unit tests map to every validation boundary and stable camelCase contract.
- [x] Quick gate passes with at least 12 new assertions and no prior test removed/skipped.

**Tests**: unit  
**Gate**: quick  
**Commit**: `feat(pipeline): define pipeline domain contracts`

### T2: Add additive tenant migration and legacy backfill

**Status**: ✅ Complete

**What**: Create the next Alembic revision with new tables, stable legacy mapping, deal/history IDs, constraints, indexes and RLS.  
**Where**: `migrations/versions/<new_revision>_add_customizable_deal_pipeline.py`  
**Depends on**: T1  
**Reuses**: Tenant migration and forced-RLS patterns from revision `a4c9d2e7f1b6`.  
**Requirement**: PIPE-01, PIPE-04, PIPE-07

**Tools**:

- MCP: NONE
- Skill: `tlc-spec-driven`

**Done when**:

- [x] Upgrade seeds the nine approved stages with preserved order/color/semantics and backfills every deal/history reference.
- [x] Unknown stage, missing backfill or invalid count aborts before the new head is published.
- [x] New tenant tables have forced RLS with both `USING` and `WITH CHECK`.
- [x] Additive schema keeps legacy text columns and supports isolated downgrade tests.
- [x] Migration/security tests include preservation fingerprints and at least 14 new assertions.
- [x] Build gate passes with no prior test removed/skipped.

**Tests**: PostgreSQL integration  
**Gate**: build  
**Commit**: `feat(pipeline): migrate tenant pipeline schema`

### T3: Implement the tenant-scoped pipeline repository

**Status**: ✅ Complete

**What**: Add repository operations for canonical reads, row locks, deal counts, transfers and append-only audit writes.  
**Where**: `app/repositories/pipeline.py`  
**Depends on**: T2  
**Reuses**: Workspace repository scope verification and session-level RLS context.  
**Requirement**: PIPE-01, PIPE-03, PIPE-05

**Tools**:

- MCP: NONE
- Skill: `tlc-spec-driven`

**Done when**:

- [x] Every query includes workspace scope and cannot access a foreign pipeline/stage.
- [x] Transfer updates relational IDs, legacy name, packed record and movement history for active and soft-deleted deals.
- [x] Audit writes exclude commercial payloads and no update/delete method exists.
- [x] Integration tests cover missing RLS context, foreign workspace IDs, rollback and canonical ordering with at least 12 new assertions.
- [x] Full gate passes with no prior test removed/skipped.

**Tests**: PostgreSQL integration  
**Gate**: full  
**Commit**: `feat(pipeline): add tenant scoped pipeline repository`

### T4: Implement versioned pipeline configuration service

**Status**: ✅ Complete

**What**: Add normalized diff/validation and versioned create, rename, color, reorder and initial-stage operations.  
**Where**: `app/services/pipeline.py`  
**Depends on**: T3  
**Reuses**: Principal scope, workspace conflict pattern and repository transactions.  
**Requirement**: PIPE-02, PIPE-06

**Tools**:

- MCP: NONE
- Skill: `tlc-spec-driven`

**Done when**:

- [x] Service enforces all name/color/count/type/default/minimum invariants before writes.
- [x] Existing semantic type, UUID and system key cannot be altered.
- [x] Stale pipeline version returns the stable conflict and causes zero writes.
- [x] Successful non-transfer update increments pipeline version exactly once and appends one coherent audit event.
- [x] Tests cover every validation branch and concurrent/retry path with at least 18 new assertions.
- [x] Full gate passes with no prior test removed/skipped.

**Tests**: unit + PostgreSQL integration  
**Gate**: full  
**Commit**: `feat(pipeline): add versioned pipeline configuration service`

### T5: Add atomic archive, transfer and semantic effects

**What**: Extend the service with archive/transfer orchestration, semantic `wonAt` rules and atomic audit.  
**Where**: `app/services/pipeline.py`  
**Depends on**: T4  
**Reuses**: Repository row locks and existing deal movement history representation.  
**Requirement**: PIPE-03, PIPE-04, PIPE-05, PIPE-06

**Tools**:

- MCP: NONE
- Skill: `tlc-spec-driven`

**Done when**:

- [ ] Empty-stage archive works without destination; occupied stage requires valid active destination.
- [ ] All active/deleted deals transfer or none do; workspace version increments only when deals change.
- [ ] `wonAt`, history snapshots, IDs and billing system key follow the spec.
- [ ] Last semantic stage, invalid target and injected database/audit failure roll back fully.
- [ ] Integration tests prove before/after state for every branch with at least 16 new assertions.
- [ ] Build gate passes with no prior test removed/skipped.

**Tests**: PostgreSQL integration  
**Gate**: build  
**Commit**: `feat(pipeline): archive stages with atomic deal transfer`

### T6: Expose authorized pipeline and history APIs

**What**: Add read/update/history routes, `MANAGE_PIPELINE` policy and stable HTTP error mapping.  
**Where**: `app/main.py`  
**Depends on**: T5  
**Reuses**: `resolve_principal`, expected-origin, no-store responses and `require_action`.  
**Requirement**: PIPE-01, PIPE-02, PIPE-05, PIPE-06

**Tools**:

- MCP: NONE
- Skill: `tlc-spec-driven`

**Done when**:

- [ ] Authenticated roles can read active stages; only admin can include archived, update or read audit.
- [ ] 401/403/409/422/503 responses use stable codes and never disclose tenant/DSN details.
- [ ] Forged route, workspace, pipeline and stage identifiers cannot cross tenant scope.
- [ ] API tests cover every route, success, validation, permission, conflict and dependency failure with at least 16 new assertions.
- [ ] Full gate passes with no prior test removed/skipped.

**Tests**: API + PostgreSQL integration  
**Gate**: full  
**Commit**: `feat(pipeline): expose authorized pipeline api`

### T7: Canonicalize workspace deal stages

**What**: Integrate stable stage IDs with generic workspace load/save while preserving legacy names and server-owned history.  
**Where**: `app/services/workspace.py`  
**Depends on**: T6  
**Reuses**: Authorized projection/merge, workspace optimistic concurrency and reconcile flow.  
**Requirement**: PIPE-03, PIPE-04, PIPE-06, PIPE-07

**Tools**:

- MCP: NONE
- Skill: `tlc-spec-driven`

**Done when**:

- [ ] Load returns canonical `pipelineId`, `stageId` and display name for each visible deal.
- [ ] Save accepts only active same-workspace stage IDs and replaces submitted display text with canonical name.
- [ ] Server movement history cannot be erased or forged by the browser.
- [ ] Archived/stale stage and workspace conflict return 409 without modifying records.
- [ ] Repository/service tests cover new, edited, deleted/restored and concurrent deals with at least 14 new assertions.
- [ ] Build gate passes with no prior test removed/skipped.

**Tests**: PostgreSQL integration  
**Gate**: build  
**Commit**: `feat(pipeline): canonicalize workspace stage references`

### T8: Replace frontend stage constants with the pipeline registry

**What**: Load the canonical funil and drive deal lists, forms, Kanban, filters, dashboard, progress and automations by IDs/semantics.  
**Where**: `app/static/index.html`  
**Depends on**: T7  
**Reuses**: Existing renderers, fetch lifecycle, filter engine and movement controller.  
**Requirement**: PIPE-01, PIPE-04

**Tools**:

- MCP: NONE
- Skill: `tlc-spec-driven`

**Done when**:

- [ ] No Negócio behavior depends on visible names; Lead stages remain unchanged.
- [ ] New deals use configured initial ID; won/lost/open and billing use semantics/system key.
- [ ] Renaming seeded stages preserves counts, filters, Kanban, history, undo and billing automation.
- [ ] Missing pipeline blocks dependent actions with visible error and no fixed fallback.
- [ ] Browser tests replace exact-nine assumptions with seeded-default and rename regressions, adding at least 12 assertions without weakening unrelated tests.
- [ ] Build gate passes with no prior test removed/skipped.

**Tests**: browser e2e  
**Gate**: build  
**Commit**: `feat(pipeline): drive deal ui from canonical stages`

### T9: Add the administrator pipeline editor

**What**: Add the Funil de negócios admin page with create, rename, color, semantic type, initial stage and accessible ordering controls.  
**Where**: `app/static/index.html`  
**Depends on**: T8  
**Reuses**: Admin navigation, cards, forms, drag UI, buttons and toast patterns.  
**Requirement**: PIPE-02, PIPE-06

**Tools**:

- MCP: NONE
- Skill: `tlc-spec-driven`

**Done when**:

- [ ] Page is visible only to Administrador and sends one versioned aggregate update.
- [ ] Drag/drop and up/down controls produce the same continuous order.
- [ ] UI validates bounds, protects immutable fields and reports 422 errors at the affected row.
- [ ] HTTP 409 discards no server data and offers an explicit reload.
- [ ] Desktop/mobile browser tests cover every editor action, keyboard alternative, permissions and conflict with at least 14 new assertions.
- [ ] Full gate passes with no prior test removed/skipped.

**Tests**: browser e2e  
**Gate**: full  
**Commit**: `feat(pipeline): add administrator pipeline editor`

### T10: Add transfer confirmation and audit history UI

**What**: Add archive/transfer confirmation, semantic impact summary and paginated administrative history.  
**Where**: `app/static/index.html`  
**Depends on**: T9  
**Reuses**: Existing modal, confirmation, pagination-style lists and feedback components.  
**Requirement**: PIPE-03, PIPE-05, PIPE-06

**Tools**:

- MCP: NONE
- Skill: `tlc-spec-driven`

**Done when**:

- [ ] Empty stage can archive directly; occupied stage modal requires an active different destination.
- [ ] Modal shows total including soft-deleted records and warns when semantic outcome changes.
- [ ] Success refreshes pipeline/workspace versions; failure leaves local state consistent with server.
- [ ] History renders actor, instant, action, before/after and transfer summary 50 at a time.
- [ ] Browser tests cover cancel, each semantic destination, invalid/stale target, rollback feedback and history permission with at least 14 new assertions.
- [ ] Build gate passes with no prior test removed/skipped.

**Tests**: browser e2e  
**Gate**: build  
**Commit**: `feat(pipeline): add stage transfer and audit ui`

### T11: Advance tenant revisions safely in fleet and package flows

**What**: Extend explicit fleet migration/package contracts to target the new head and update control revision only after tenant verification.  
**Where**: `app/fleet.py`  
**Depends on**: T10  
**Reuses**: Existing selected-tenant, backup acknowledgement, identity preflight and offline package gates.  
**Requirement**: PIPE-07

**Tools**:

- MCP: NONE
- Skill: `tlc-spec-driven`

**Done when**:

- [ ] Migration requires explicit tenant, backup acknowledgement, confirmation and valid target revision.
- [ ] Database head and identity are verified before `expected_tenant_revision` advances.
- [ ] Failure leaves the control revision unchanged and reports per-tenant redacted status.
- [ ] Package/runbook contracts preserve release side-by-side, service identity, HBA boundary and application rollback compatibility.
- [ ] Fleet/package tests add at least 14 assertions, including failure injection and untouched unselected tenants.
- [ ] Build gate passes with no prior test removed/skipped.

**Tests**: unit + contract + PostgreSQL integration  
**Gate**: build  
**Commit**: `feat(fleet): support verified tenant revision advancement`

### T12: Publish local release evidence and operator plan

**What**: Update project documentation, traceability and a no-execution deployment checklist after all local gates pass.  
**Where**: `.specs/features/customizable-deal-pipeline/validation.md`  
**Depends on**: T11  
**Reuses**: Existing README verification commands and Windows side-by-side runbook structure.  
**Requirement**: PIPE-01, PIPE-02, PIPE-03, PIPE-04, PIPE-05, PIPE-06, PIPE-07

**Tools**:

- MCP: NONE
- Skill: `tlc-spec-driven`

**Done when**:

- [ ] README describes the dynamic pipeline and current production status accurately.
- [ ] Operator checklist separates backup, upload, preflight, tenant migration, cutover, UAT and rollback; it performs none of them.
- [ ] Spec traceability cites exact test assertions for all requirements.
- [ ] Build gate passes with backend/browser counts not lower than baseline and no skip/deletion.
- [ ] Fresh independent Verifier runs evidence-or-zero plus discrimination sensor and writes PASS to `validation.md`.
- [ ] `validate_state.py` passes; no push, deploy or remote change occurred.

**Tests**: structural + full regression — TLC validators, Build gate and independent Verifier  
**Gate**: build  
**Commit**: `docs(pipeline): publish verified release evidence`

---

## Phase Execution Map

```text
Phase 1 → Phase 2 → Phase 3 → Phase 4

Phase 1: T1 → T2 → T3
Phase 2: T3 → T4 → T5 → T6 → T7
Phase 3: T7 → T8 → T9 → T10
Phase 4: T10 → T11 → T12
```

Execution is sequential. With 12 tasks, Execute must offer task-budgeted sub-agent batches before T1; agents are used only if the user explicitly accepts.

---

## Task Granularity Check

| Task | Single deliverable | Status |
| ---- | ------------------ | ------ |
| T1 | Domain contracts | ✅ Granular |
| T2 | Tenant migration | ✅ Granular |
| T3 | Repository | ✅ Granular |
| T4 | Configuration service | ✅ Granular |
| T5 | Archive/transfer service behavior | ✅ Granular |
| T6 | API surface | ✅ Granular |
| T7 | Workspace canonicalization | ✅ Granular |
| T8 | Frontend registry integration | ✅ Granular |
| T9 | Admin editor | ✅ Granular |
| T10 | Transfer/history UX | ✅ Granular |
| T11 | Fleet revision advancement | ✅ Granular |
| T12 | Release evidence/checklist | ✅ Granular |

---

## Diagram-Definition Cross-Check

| Task | Depends On | Diagram Shows | Status |
| ---- | ---------- | ------------- | ------ |
| T1 | None | Start → T1 | ✅ Match |
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

---

## Test Co-location Validation

| Task | Code Layer Created/Modified | Matrix Requires | Task Says | Status |
| ---- | --------------------------- | --------------- | --------- | ------ |
| T1 | Models/schemas | unit | unit | ✅ OK |
| T2 | Migration/RLS | PostgreSQL integration | PostgreSQL integration | ✅ OK |
| T3 | Repository | PostgreSQL integration | PostgreSQL integration | ✅ OK |
| T4 | Domain service | unit + PostgreSQL integration | unit + PostgreSQL integration | ✅ OK |
| T5 | Transactional service | PostgreSQL integration | PostgreSQL integration | ✅ OK |
| T6 | Policy/routes | API + PostgreSQL integration | API + PostgreSQL integration | ✅ OK |
| T7 | Workspace service/repository | PostgreSQL integration | PostgreSQL integration | ✅ OK |
| T8 | Frontend behavior | browser e2e | browser e2e | ✅ OK |
| T9 | Admin UI | browser e2e | browser e2e | ✅ OK |
| T10 | Transfer/audit UI | browser e2e | browser e2e | ✅ OK |
| T11 | Fleet/package | unit + contract + PostgreSQL integration | unit + contract + PostgreSQL integration | ✅ OK |
| T12 | Documentation/validation | structural + full regression | structural + full regression | ✅ OK |

---

## Requirement Coverage

| Requirement | Tasks | Evidence target |
| ----------- | ----- | --------------- |
| PIPE-01 | T1,T2,T3,T6,T8,T12 | Tenant-scoped canonical read and dynamic UI |
| PIPE-02 | T1,T4,T6,T9,T12 | Validated admin-only customization |
| PIPE-03 | T3,T5,T7,T10,T12 | Atomic archive/transfer and rollback |
| PIPE-04 | T2,T5,T7,T8,T12 | Name-independent semantics and legacy preservation |
| PIPE-05 | T1,T3,T4,T5,T6,T10,T12 | Append-only audit and admin history |
| PIPE-06 | T4,T5,T6,T7,T9,T10,T12 | Pipeline/workspace optimistic concurrency |
| PIPE-07 | T2,T7,T11,T12 | Additive migration, fleet revision and operator safety |

**Coverage:** 7 requirements, 12 mapped tasks, 0 unmapped.

---

## Approval Gate Before Execute

1. User approves `spec.md`, `context.md`, `design.md` and this `tasks.md`.
2. User confirms `tlc-spec-driven` plus local filesystem/shell/tests as the tools for all tasks; no external plugin is required.
3. Because 12 tasks exceed one batch, user chooses sequential phase-batch sub-agents or inline execution before T1.
4. Baseline backend/browser counts are recaptured before modifying code.
5. Push, deploy, production backup/migration, task scheduler and server changes remain forbidden without explicit separate authorization.
