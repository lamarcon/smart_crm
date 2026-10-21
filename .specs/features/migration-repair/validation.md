# Migration Repair Validation

**Verdict**: PASS
**Date**: 2026-10-21
**Contract**: AC1-AC5 supplied inline by the orchestrator
**Diff range**: `18741aa..86c18cc`
**Commits in scope**: `855338a`, `a69fc26`, `86c18cc`
**Verifier**: independent sub-agent (author != verifier)

## Task completion

| Commit | Outcome | Status |
| --- | --- | --- |
| `855338a` | Adds the tenant repair revision and its migration coverage. | PASS |
| `a69fc26` | Propagates the repaired tenant head through the Windows installer, bundle, docs, and tests. | PASS |
| `86c18cc` | Seeds and fingerprints an existing custom-field definition across the repair. | PASS |

## Spec-anchored acceptance criteria

| AC | Spec-defined outcome | Evidence (`file:line` + assertion expression) | Result |
| --- | --- | --- | --- |
| AC1 | A database marked `e1c4a7b9d2f6` without `redact_in_history` reaches `f6b1d3a8c2e4`, gains a `boolean NOT NULL DEFAULT false` column, and preserves exactly the existing `custom_field_definitions` records. | `tests/backend/test_migrations.py:96-124` builds the pre-repair schema, inserts a representative row with non-default payload, stamps `e1c4a7b9d2f6`, and asserts `"redact_in_history" not in columns_before`. `tests/backend/test_migrations.py:133-151` asserts `repaired["nullable"] is False`, `str(repaired["default"]).lower() == "false"`, row count `== 1`, `definition_after == definition_before`, the new value `is False`, and `version_num == TENANT_HEAD`. | PASS |
| AC2 | A clean installation in which `e1c4a7b9d2f6` already creates the column upgrades idempotently and finishes at `f6b1d3a8c2e4`. | `migrations/versions/e1c4a7b9d2f6_add_crm_activity_events.py:22-29` creates the column on the clean path. `tests/backend/test_migrations.py:51-68` runs `upgrade head` and asserts the exact tenant head, non-nullability, and default false. `tests/backend/test_migrations.py:82-89` runs `upgrade head` twice and asserts the singleton count and version remain unchanged. | PASS |
| AC3 | The Windows PostgreSQL 11 installer migrates the tenant to exactly `f6b1d3a8c2e4`, verifies exactly that revision, and only then publishes. | `tests/backend/test_manual_windows_pg11_outcomes.py:287-291` asserts the exact upgrade/current argument arrays. `tests/backend/test_manual_windows_pg11_outcomes.py:300-316` asserts upgrade, current, and publish tokens are present in sorted execution order and includes `f6b1d3a8c2e4`. `deploy/manual-windows-pg11/initialize-and-test.ps1:47-58` performs tenant upgrade, checks command success, reads current, asserts revision `f6b1d3a8c2e4`, then invokes `install-scheduled-task.ps1`. | PASS |
| AC4 | The offline ZIP and `MANIFEST.sha256` contain both the `e1c4a7b9d2f6` and `f6b1d3a8c2e4` tenant migrations. | `tests/backend/test_windows_multitenant_bundle.py:127-129` asserts both migration paths are members of the ZIP. `tests/backend/test_windows_multitenant_bundle.py:131-135` asserts both paths occur in `MANIFEST.sha256`. | PASS |
| AC5 | Persistent Compose keeps its named PostgreSQL volume and returns HTTP 200 from authenticated `/api/workspace`. | `scripts/verify_demo.py:338-344` asserts source `postgres_data` at `/var/lib/postgresql/data`. `scripts/verify_demo.py:534-546` recreates only CRM and asserts `recreated_status == 200`, unchanged workspace version/marker, and unchanged probe count. Operational check on 2026-10-21 found PostgreSQL created on 2026-10-19 and CRM recreated on 2026-10-21, while volume `smart-crm-demo-postgres-data` remained mounted RW at `/var/lib/postgresql/data`; database head was `f6b1d3a8c2e4`, health/login returned HTTP 200, and authenticated `/api/workspace` returned HTTP 200 with `initialized=True`, version `30`. | PASS |

**Spec-anchored result**: 5/5 ACs match the exact inline outcomes. No spec-precision gap remains.

## Gate check

- **Command**: `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --basetemp <temp> tests/backend/test_migrations.py tests/backend/test_tenant_migration_security.py tests/backend/test_manual_windows_pg11_deployment.py tests/backend/test_manual_windows_pg11_outcomes.py tests/backend/test_windows_fleet_cutover_runbook.py tests/backend/test_windows_multitenant_bundle.py`
- **Valid isolated result**: `79 passed in 32.87s`, 0 failed, 0 skipped.
- **Database isolation**: dedicated PostgreSQL database `smartcrm_verifier_migration_repair_20261021f`; it was dropped after the gate and verified absent.
- **Environment**: both `SMART_CRM_TEST_DATABASE_URL` and `SMART_CRM_DATABASE_URL` targeted only the disposable database.
- **Test count before feature**: 78 test functions in the six gate files at `18741aa`.
- **Test count after feature**: 79 test functions in the six gate files at `86c18cc`.
- **Delta**: +1.
- **Diff hygiene**: `git diff --check 18741aa..86c18cc` exited zero.
- An initial sandbox run was invalid infrastructure evidence: Windows denied TCP access to PostgreSQL and pytest temp creation. It is excluded from the gate result. The authorized rerun above is the valid gate.

## Discrimination sensor

The sensor ran in a detached temporary worktree at `86c18cc`. Each mutation was restored before the next run. The scratch was clean before removal.

| Mutation | Location | Behavioral fault | Result |
| --- | --- | --- | --- |
| M1 | `migrations/versions/f6b1d3a8c2e4_repair_custom_field_history_redaction.py:25` | Changed `DEFAULT false` to `DEFAULT true`. | KILLED: `tests/backend/test_migrations.py:134` failed with `true != false`. |
| M2 | `deploy/manual-windows-pg11/deployment-policy.ps1:112` | Changed the exact tenant deployment target from `f6b1d3a8c2e4` to `e1c4a7b9d2f6`. | KILLED: `tests/backend/test_manual_windows_pg11_outcomes.py:287-289` failed on the exact argument array. |
| M3 | `migrations/versions/f6b1d3a8c2e4_repair_custom_field_history_redaction.py:20` | Inserted `DELETE FROM custom_field_definitions` before the repair DDL. | KILLED: `tests/backend/test_migrations.py:135` failed with row count `0 != 1`. |

**Sensor depth**: three targeted behavior mutations, including the highest-risk data-integrity fault.
**Sensor result**: 3 injected, 3 killed, 0 survived. PASS.

## Worktree isolation

`git status --porcelain=v1` matched byte-for-byte before and after the sensor. The normalized output SHA-256 was `1ff5457b09014b46a25c649741dcd4e347c86ba424bf05e2aab6be006bb6ad2e` both times.

The preserved pre-existing dirty entries were:

- modified: `.specs/LESSONS.md`, `.specs/lessons.json`, `README.md`, `scripts/compose_fixture.py`, `scripts/verify_demo.py`;
- untracked: `.pytest-final-backend-2/`, `.pytest-final-backend/`, `.pytest-release-head/`, `.pytest-startup-green/`, `.pytest-tmp/`, `.pytest-windows-hotfix-2/`, `.pytest-windows-hotfix/`, `.specs/features/crm-mvp/tasks.md`, `.specs/features/migration-repair/`, `.venv/`, `smart_crm_demo.egg-info/`.

The detached worktree was removed. No stash was created. The disposable database was removed. This report is the only intentional real-tree write by the Verifier.

## Code quality

| Check | Result |
| --- | --- |
| Minimum and surgical implementation | PASS: one idempotent repair revision, exact target propagation, and one focused preservation test. |
| No unrelated abstraction or flexibility | PASS |
| Existing migration and deployment patterns | PASS |
| Spec-anchored outcomes | PASS: every conjunction has a value/state assertion. |
| Payload/conjunction rule | PASS: AC1 checks row count, identity-bound payload equality, new-column value, column shape, and final head. |
| Per-layer coverage | PASS: PostgreSQL migration behavior, PowerShell policy/order, offline bundle contents, and persistent Compose behavior are covered at their relevant layers. |
| Test integrity | PASS: test count increased by one; no skips or weakened assertions were observed in scope. |
| Documented guideline | `tlc-spec-driven/references/coding-principles.md`; all checks pass. |

## Edge cases

- [x] Pre-existing deployment stamped at `e1c4a7b9d2f6` but missing the column.
- [x] Clean path where `e1c4a7b9d2f6` already created the column.
- [x] Repeated `upgrade head`.
- [x] Destructive deletion of existing definitions is detected.
- [x] Wrong Windows deployment target is detected before publish.
- [x] Persistent Compose volume is mounted and authenticated workspace recovery returns 200.

## Interactive UAT

Not applicable. This is a backend, migration, packaging, and deployment-contract change. Automated and operational checks cover the inline contract.

## Traceability and lessons

There is no persisted `.specs/features/migration-repair/spec.md`; the inline AC1-AC5 contract is the source of truth. No spec status file was modified.

No lesson was recorded. The final verdict is a clean PASS, and the pre-existing dirty lesson files were preserved exactly as required.

## Summary

**Overall**: READY

**Spec-anchored check**: 5/5 ACs matched, 0 precision gaps.
**Gate**: 79 passed, 0 failed, 0 skipped.
**Sensor**: 3/3 mutations killed.
**Diff range**: `18741aa..86c18cc` (`855338a`, `a69fc26`, `86c18cc`).

The migration repair now proves both schema correction and exact preservation of existing custom-field definitions. The clean-install path is idempotent, the Windows installer targets and verifies the repaired head before publish, the offline bundle contains both migrations, and the persistent Compose runtime retains its named volume while serving authenticated `/api/workspace` with HTTP 200.
