# Deployment Hardening v0.3.4 Tasks

## Execution Protocol (MANDATORY -- do not skip)

Implement these tasks with the `tlc-spec-driven` skill: **activate it by name and follow its Execute flow and Critical Rules.** Do not search for skill files by filesystem path. The skill is the source of truth for the full flow (per-task cycle, adequacy review, Verifier and discrimination sensor).

**If the skill cannot be activated, STOP and tell the user.**

---

**Design**: `.specs/features/deployment-hardening-v034/design.md`
**Status**: In Progress

---

## Test Coverage Matrix

> Generated from codebase, project guidelines and spec. Guidelines found: `pyproject.toml`, `.github/workflows/release-windows-pg11.yml`, existing backend deployment/fleet/migration tests; no `AGENTS.md` or contributor guide, so strong defaults apply.

| Code Layer | Required Test Type | Coverage Expectation | Location Pattern | Run Command |
| ---------- | ------------------ | -------------------- | ---------------- | ----------- |
| Alembic repair migration | integration | FORCE RLS happy path, idempotent retry, preserved customization, fresh unactivated database, missing identity and payload repair | `tests/backend/test_deployment_repair_migration.py` | `& D:\Develop_CRM_Project\.venv\Scripts\python.exe -m pytest -q tests/backend/test_deployment_repair_migration.py` |
| Admin provisioning service | integration | Creation and resume paths; every payload field and credential exclusion | `tests/backend/test_admin.py` | `& D:\Develop_CRM_Project\.venv\Scripts\python.exe -m pytest -q tests/backend/test_admin.py` |
| Fleet CLI adapter | unit/integration | Argument gates, redacted output, success/failure exit codes and explicit tenant selection | `tests/backend/test_fleet_cli.py` | `& D:\Develop_CRM_Project\.venv\Scripts\python.exe -m pytest -q tests/backend/test_fleet_cli.py tests/backend/test_fleet.py` |
| PowerShell deployment policy | integration | Windows PowerShell 5.1 parser, stderr/exit code, port, task target, health and exact-version branches | `tests/backend/test_manual_windows_pg11_outcomes.py` | `& D:\Develop_CRM_Project\.venv\Scripts\python.exe -m pytest -q tests/backend/test_manual_windows_pg11_outcomes.py` |
| Windows migration/cutover scripts | integration/static contract | Happy path plus timeout, invalid evidence, cleanup, rollback and no false PASS | `tests/backend/test_manual_windows_pg11_outcomes.py` | `& D:\Develop_CRM_Project\.venv\Scripts\python.exe -m pytest -q tests/backend/test_manual_windows_pg11_outcomes.py tests/backend/test_manual_windows_pg11_deployment.py` |
| Offline bundle contract | integration | Required new files, manifest integrity and release verifier | `tests/backend/test_windows_multitenant_bundle.py` | `& D:\Develop_CRM_Project\.venv\Scripts\python.exe -m pytest -q tests/backend/test_windows_multitenant_bundle.py tests/backend/test_github_release_delivery.py` |
| Operator documentation | none | Build gate only; commands must match tested scripts | - | build gate only |

## Gate Check Commands

> Generated from the existing pytest, UI and GitHub release workflow contracts.

| Gate Level | When to Use | Command |
| ---------- | ----------- | ------- |
| Quick | Unit or focused service tests | `& D:\Develop_CRM_Project\.venv\Scripts\python.exe -m pytest -q --basetemp test-results/deploy-hardening tests/backend/test_admin.py tests/backend/test_fleet_cli.py tests/backend/test_fleet.py` |
| Full | Migration or PowerShell integration | `& D:\Develop_CRM_Project\.venv\Scripts\python.exe -m pytest -q --basetemp test-results/deploy-hardening tests/backend/test_deployment_repair_migration.py tests/backend/test_admin.py tests/backend/test_fleet_cli.py tests/backend/test_fleet.py tests/backend/test_manual_windows_pg11_deployment.py tests/backend/test_manual_windows_pg11_outcomes.py tests/backend/test_windows_multitenant_bundle.py` |
| Build | Phase completion or bundle/docs | `& D:\Develop_CRM_Project\.venv\Scripts\python.exe -m pytest -q --basetemp test-results/deploy-hardening; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }; pnpm test` |

---

## Execution Plan

### Phase 1: Tenant data and migration contract

```
T1 → T2 → T3
```

### Phase 2: Service-account migration execution

```
T3 → T4 → T5 → T6
```

### Phase 3: Verified cutover and package

```
T6 → T7 → T8
```

---

## Task Breakdown

### T1: Repair tenant structures under FORCE RLS

**Status**: Complete

**What**: Add a new idempotent Alembic revision that seeds a missing pipeline and completes legacy CRM user payloads in the workspace bound by `tenant_identity`.
**Where**: `migrations/versions/a8d4e6f2b1c9_repair_tenant_deploy_state.py`
**Depends on**: None
**Reuses**: deterministic pipeline/stage contract from `c7f3a9d8e2b1` and `tenant_identity` from `a4c9d2e7f1b6`.
**Requirement**: DEPLOY-02

**Tools**:

- MCP: NONE
- Skill: `tlc-spec-driven`

**Done when**:

- [x] A tenant with FORCE RLS, valid `tenant_identity`, no pipeline and payload `{}` ends with one default pipeline, nine active stages, one default stage and a canonical packed user payload.
- [x] Existing customized pipeline fields and extra user payload fields remain unchanged.
- [x] Re-running the repair produces no duplicates or further state change.
- [x] A fresh unactivated database advances without repair; a tenant with users and missing/mismatched identity fails before cross-workspace writes.
- [x] Migration gate passes with no skipped or deleted tests (`9 passed`).

**Tests**: integration
**Gate**: full

**Commit**: `fix(migrations): repair tenant deployment state under rls`

**Evidence**: `tests/backend/test_deployment_repair_migration.py` plus `tests/backend/test_migrations.py`; executed with `--basetemp test-results/deploy-hardening-t1-full` on 2026-10-29 (`9 passed in 6.75s`).

### T2: Persist canonical first-administrator payloads

**Status**: Complete

**What**: Make administrator creation and provisioning resume write the packed workspace payload from canonical columns in the same transaction.
**Where**: `app/admin_cli.py`
**Depends on**: T1
**Reuses**: packed user record contract from `app/repositories/workspace.py`.
**Requirement**: DEPLOY-03

**Tools**:

- MCP: NONE
- Skill: `tlc-spec-driven`

**Done when**:

- [x] First activation stores exact `position` and `record` fields for id, name, email, job title, role, status and avatar.
- [x] Resume synchronizes those fields without duplicating the user.
- [x] Password and password hash are absent from every payload level.
- [x] Existing provisioning preservation assertions remain green.
- [x] Administrative gate passes with no skipped or deleted tests (`25 passed`).

**Tests**: integration
**Gate**: quick

**Commit**: `fix(admin): persist canonical workspace user payload`

**Evidence**: `tests/backend/test_admin.py`; creation and partial-failure resume scenarios plus the full administrative suite, executed on 2026-10-29 (`25 passed in 12.23s`).

### T3: Expose explicit fleet migration CLI

**Status**: Complete

**What**: Add a non-web CLI that preflights and migrates explicitly selected tenants through `FleetService` with redacted output and deterministic exit codes.
**Where**: `app/fleet_cli.py`
**Depends on**: T2
**Reuses**: `FleetService`, `format_preflight`, `ControlDatabase` and `DpapiFileSecretProvider`.
**Requirement**: DEPLOY-01, DEPLOY-05

**Tools**:

- MCP: NONE
- Skill: `tlc-spec-driven`

**Done when**:

- [x] Empty selection, missing backup acknowledgement or missing confirmation fails before tenant connection.
- [x] Successful results accept only `migrated` and `already_current` and return exit code 0.
- [x] Any tenant failure returns non-zero and identifies only slug/code, never DSN or secret.
- [x] Repeated current migration does not advance `profile_version` again.
- [x] Fleet gate passes with no skipped or deleted tests (`40 passed`).

**Tests**: unit/integration
**Gate**: quick

**Commit**: `feat(fleet): add explicit tenant migration cli`

**Evidence**: `tests/backend/test_fleet_cli.py` and `tests/backend/test_fleet.py`; CLI contract, real selected-schema migration and repeated `already_current`, executed on 2026-10-29 (`40 passed in 15.52s`).

### T4: Harden Windows PowerShell deployment primitives

**Status**: Complete

**What**: Add literal environment parsing, native-process capture, port release, task target and exact release readiness helpers compatible with Windows PowerShell 5.1.
**Where**: `deploy/manual-windows-pg11/deployment-policy.ps1`
**Depends on**: T3
**Reuses**: current HBA, revision, logged-process and health helpers.
**Requirement**: DEPLOY-04, DEPLOY-05

**Tools**:

- MCP: NONE
- Skill: `tlc-spec-driven`

**Done when**:

- [x] Literal `C:\ProgramData` and values containing `=` round-trip without escape interpretation.
- [x] Duplicate/invalid environment keys fail without displaying values.
- [x] Informational stderr with exit code 0 is captured as success; non-zero remains failure.
- [x] Port, task user/action, health and exact-version helpers cover success, timeout and mismatch.
- [x] Full gate passes with no skipped or deleted tests.

**Tests**: integration
**Gate**: full

**Commit**: `fix(deploy): harden powershell deployment gates`

**Evidence**: `tests/backend/test_manual_windows_pg11_outcomes.py` exercises Windows PowerShell 5.1 literal parsing, redacted validation failures, native stderr/exit-code capture, finite port wait, immutable scheduled-task targeting and exact release readiness. The deployment-policy/outcomes gate passed (`37 passed`) and the full backend deployment gate passed with local PostgreSQL (`114 passed in 43.31s`) on 2026-10-29.

### T5: Run fleet migration inside the service identity

**Status**: Complete

**What**: Add the finite service-account script that loads validated runtime settings, calls the fleet CLI and writes redacted atomic evidence.
**Where**: `deploy/manual-windows-pg11/run-fleet-migration.ps1`
**Depends on**: T4
**Reuses**: shared environment/native helpers and `app/fleet_cli.py`.
**Requirement**: DEPLOY-01, DEPLOY-04

**Tools**:

- MCP: NONE
- Skill: `tlc-spec-driven`

**Done when**:

- [x] Script accepts explicit tenant/release/evidence paths and no plaintext credential parameter.
- [x] Required runtime variables exist only for the child process and are cleared in `finally`.
- [x] Evidence is atomically promoted only after a complete result and contains no secret material.
- [x] CLI failure returns non-zero and leaves a valid redacted failure result.
- [x] Full gate passes with no skipped or deleted tests.

**Tests**: integration
**Gate**: full

**Commit**: `feat(deploy): run fleet migration as service account`

**Evidence**: `run-fleet-migration.ps1` loads the complete literal environment allowlist, exports only the control URL, DPAPI store and approved loopback flag at process scope, restores prior values in `finally`, executes the packaged-head and explicit fleet CLI commands through the native-process adapter, and atomically promotes redacted JSON evidence. Focused PowerShell deployment tests passed (`40 passed`) and the full backend deployment gate passed with local PostgreSQL (`117 passed in 48.80s`) on 2026-10-29.

### T6: Coordinate the temporary migration task

**Status**: Complete

**What**: Add the administrative script that registers, starts, waits for and always removes the one-shot `SmartCRMService` migration task.
**Where**: `deploy/manual-windows-pg11/invoke-fleet-migration-task.ps1`
**Depends on**: T5
**Reuses**: dedicated-account validation and Task Scheduler patterns from `install-scheduled-task.ps1`.
**Requirement**: DEPLOY-01, DEPLOY-04

**Tools**:

- MCP: NONE
- Skill: `tlc-spec-driven`

**Done when**:

- [x] Only a qualified `SmartCRMService` credential can register the temporary task.
- [x] Unique task/evidence names are scoped to the release and tenant.
- [x] Success requires exit code 0 and matching evidence tenant/release/result.
- [x] Timeout, malformed evidence and task failure stop/remove the temporary task in `finally`.
- [x] Full gate passes with no skipped or deleted tests.

**Tests**: integration
**Gate**: full

**Commit**: `feat(deploy): coordinate one-shot fleet migration task`

**Evidence**: `invoke-fleet-migration-task.ps1` validates the qualified service identity, creates a release/tenant/operation-scoped evidence directory with a restricted writable ACL, registers a finite one-shot task, requires a fresh zero exit result plus matching redacted evidence, and stops/unregisters the task in `finally`. Simulated Windows PowerShell 5.1 tests cover success, timeout, malformed evidence, task failure and wrong identity; the full backend deployment gate passed with local PostgreSQL (`123 passed in 54.04s`) on 2026-10-29.

### T7: Replace direct tenant Alembic with verified cutover

**Status**: Complete

**What**: Make the initializer use the temporary fleet task, stop the old runtime, verify port release, register the new task, validate exact version and restore the previous task on cutover failure.
**Where**: `deploy/manual-windows-pg11/initialize-and-test.ps1`
**Depends on**: T6
**Reuses**: control migration gate, task installer, new policy helpers and one-shot task invoker.
**Requirement**: DEPLOY-01, DEPLOY-04, DEPLOY-05

**Tools**:

- MCP: NONE
- Skill: `tlc-spec-driven`

**Done when**:

- [x] Initializer contains no direct tenant Alembic command and requires tenant, expected version and backup acknowledgement.
- [x] Control migration and fleet evidence complete before the runtime task changes.
- [x] Existing task is exported, stopped and the port is confirmed free before new registration.
- [x] PASS requires service user, immutable AppRoot action, health `ok` and exact expected version.
- [x] Failure after task replacement restores/starts the exported previous task or reports the preserved recovery artifact.
- [x] Runbook shows the single activation command and omits manual tenant SQL repair.
- [x] Build gate passes with no skipped or deleted tests.

**Tests**: integration
**Gate**: build

**Commit**: `fix(deploy): make windows cutover fleet-aware and verifiable`

**Evidence**: `initialize-and-test.ps1` validates the control head, requires successful one-shot fleet evidence before exporting or stopping the web task, waits for port 8080, validates the scheduled-task identity/action plus exact health/version, and restores the exported XML on cutover failure. PowerShell/runbook tests passed (`47 passed`), the source verifier passed (`19/19 requirements`), and the build gate passed (`858` backend plus `122` UI tests) on 2026-10-29.

### T8: Package and gate the hardened deploy path

**What**: Include the CLI and both migration scripts in the offline bundle and extend release contracts so missing or regressed deploy components block packaging.
**Where**: `scripts/build_manual_windows_pg11_bundle.py`
**Depends on**: T7
**Reuses**: manifest verification and Windows release workflow focused tests.
**Requirement**: DEPLOY-05

**Tools**:

- MCP: NONE
- Skill: `tlc-spec-driven`

**Done when**:

- [ ] Bundle contains `app/fleet_cli.py`, repair migration and both service-account migration scripts.
- [ ] Internal manifest covers every new file and integrity verification passes.
- [ ] Windows release tests execute all deployment regression tests before bundle creation.
- [ ] Full backend and UI gates pass without skipped/deleted tests.
- [ ] No `APP_VERSION`, tag, push, GitHub release or production state is changed.

**Tests**: integration
**Gate**: build

**Commit**: `build(release): package hardened windows deploy path`

---

## Phase Execution Map

```
Phase 1 → Phase 2 → Phase 3

Phase 1: T1 → T2 → T3
Phase 2:             T3 → T4 → T5 → T6
Phase 3:                                  T6 → T7 → T8
```

Execution is strictly sequential.

## Task Granularity Check

| Task | Scope | Status |
| ---- | ----- | ------ |
| T1 | One repair migration | ✅ Granular |
| T2 | One admin payload behavior | ✅ Granular |
| T3 | One fleet CLI adapter | ✅ Granular |
| T4 | One cohesive deployment policy module | ✅ Granular |
| T5 | One finite service runner | ✅ Granular |
| T6 | One temporary-task coordinator | ✅ Granular |
| T7 | One cutover coordinator | ✅ Granular |
| T8 | One bundle contract | ✅ Granular |

## Diagram-Definition Cross-Check

| Task | Depends On (task body) | Diagram Shows | Status |
| ---- | ---------------------- | ------------- | ------ |
| T1 | None | Entry | ✅ Match |
| T2 | T1 | T1 → T2 | ✅ Match |
| T3 | T2 | T2 → T3 | ✅ Match |
| T4 | T3 | T3 → T4 | ✅ Match |
| T5 | T4 | T4 → T5 | ✅ Match |
| T6 | T5 | T5 → T6 | ✅ Match |
| T7 | T6 | T6 → T7 | ✅ Match |
| T8 | T7 | T7 → T8 | ✅ Match |

## Test Co-location Validation

| Task | Code Layer Created/Modified | Matrix Requires | Task Says | Status |
| ---- | --------------------------- | --------------- | --------- | ------ |
| T1 | Alembic repair migration | integration | integration | ✅ OK |
| T2 | Admin provisioning service | integration | integration | ✅ OK |
| T3 | Fleet CLI adapter | unit/integration | unit/integration | ✅ OK |
| T4 | PowerShell deployment policy | integration | integration | ✅ OK |
| T5 | Windows migration runner | integration | integration | ✅ OK |
| T6 | Task Scheduler coordinator | integration | integration | ✅ OK |
| T7 | Cutover coordinator | integration | integration | ✅ OK |
| T8 | Offline bundle contract | integration | integration | ✅ OK |
