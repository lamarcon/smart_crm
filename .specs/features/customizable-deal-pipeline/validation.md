# Customizable Deal Pipeline Validation — Cycle 1

**Date**: 2026-10-05
**Spec**: `.specs/features/customizable-deal-pipeline/spec.md`
**Diff range**: `b4999b1..3548741` plus T12 working-tree documentation in `README.md`, `RUNBOOK_DEPLOY_WINDOWS_SERVER_2016.md`, `spec.md`, and `tasks.md`
**Verifier**: independent Verifier, author ≠ verifier
**Result**: PASS
**Verdict**: **PASS**

The implementation satisfies all 47 acceptance criteria and all six listed edge cases. The mandatory gate passed at or above the required counts. Six behavior-level mutants covering transfer integrity, semantics, authorization, concurrency, UI billing automation, and fleet revision publication were killed in an isolated worktree.

## Task completion

| Task | Author status | Independent disposition |
|---|---|---|
| T1 | Complete | Verified by PIPE-01, PIPE-02 and PIPE-05 evidence. |
| T2 | Complete | Verified by PIPE-07 migration evidence. |
| T3 | Complete | Verified by tenant scope, transfer and append-only audit evidence. |
| T4 | Complete | Verified by validation, versioning and concurrency evidence. |
| T5 | Complete | Verified by archive, transfer, semantic and rollback evidence. |
| T6 | Complete | Verified by API authorization and stable error evidence. |
| T7 | Complete | Verified by canonical workspace stage and 409 evidence. |
| T8 | Complete | Verified by ordered dynamic UI and renamed semantic evidence. |
| T9 | Complete | Verified by editor, bounds, role and conflict evidence. |
| T10 | Complete | Verified by transfer/history UI and M5 discrimination. |
| T11 | Complete | Verified by fleet/package evidence and M6 discrimination. |
| T12 | In Progress pending Verifier | The circular pending state was not treated as a defect. This PASS report and successful `validate_state.py` supply the two remaining verifier outcomes; no deploy, push, or remote action occurred. |

## Spec-anchored acceptance criteria

Evidence-or-zero and the payload/conjunction rule were applied independently. Every PASS below cites the exact asserted value or state.

| AC | Spec-defined observable outcome | `file:line` and literal assertion evidence | Result |
|---|---|---|---:|
| PIPE-01.1 | Return only the authenticated session workspace's default pipeline and fail on absent/mismatched scope. | `tests/backend/test_pipeline_api.py:267-273` — `loaded.status_code == 200`, nine ordered active stages; `tests/backend/test_pipeline_repository.py:149-153` — `pytest.raises(PipelineScopeError, match="workspace context ...")`; `:175-176` — pipeline and every stage equal `WORKSPACE_ID`. | PASS |
| PIPE-01.2 | Expose immutable UUID identity plus name, color, position, semantic type, active state and initial marker. | `tests/backend/test_pipeline_api.py:270-273` asserts version/order/active; `tests/backend/test_pipeline_service.py:406-420` asserts name, color, stable id, semantic type, system key, default/initial, new UUID, active and persisted semantic type. | PASS |
| PIPE-01.3 | Use one active order in lists, Kanban, filters, forms, indicators and progress. | `tests/ui-prototype.spec.cjs:2755-2779` compares `expectedIds` and `expectedNames` against dashboard indicators, row progress, list-stage filter, advanced filter, form options and Kanban columns. | PASS |
| PIPE-01.4 | Block stage-dependent deal operations when pipeline load fails and never fall back to fixed stages. | `tests/ui-prototype.spec.cjs:2733-2738` asserts `pipelineReady === 'false'`, visible unavailable error, zero “Novo Negócio”, `openEntityDialog('deal') === false`, and toast. | PASS |
| PIPE-01.5 | Ignore/reject client-supplied tenant/workspace/pipeline authority and use authenticated scope only. | `tests/backend/test_pipeline_api.py:389-406` sends forged `tenantId`, `workspaceId`, `pipelineId` and route id, asserting 422/404; repository mismatch is rejected at `tests/backend/test_pipeline_repository.py:149-153`. | PASS |
| PIPE-02.1 | Only Administrador can open/edit the tenant pipeline; other roles receive 403 and no usable UI. | `tests/backend/test_pipeline_api.py:303-329` parameterizes all four non-admin roles and asserts 403/`forbidden`; `tests/ui-prototype.spec.cjs:2893-2899` asserts absent navigation, hidden page and mutation helpers returning false. | PASS |
| PIPE-02.2 | A valid new stage receives server UUID, chosen semantic type, active state and append position. | `tests/backend/test_pipeline_service.py:413-420` — new stage has non-null id, `semantic_type == "open"`, `active is True`, `position == 9`, and persisted `archived_at is None`. | PASS |
| PIPE-02.3 | Rename/recolor/reorder preserves UUID, semantic type, links, history and system key. | `tests/backend/test_pipeline_service.py:406-410` preserves id/type/key while changing name/color; `:648-657` keeps deal UUID link and historical snapshot names after rename. | PASS |
| PIPE-02.4 | Persist unique continuous integer positions from zero through n−1. | `tests/backend/test_pipeline_service.py:405` — `positions == list(range(10))`; `tests/ui-prototype.spec.cjs:2825` compares payload positions with `Array.from({ length: 10 }, ...)`. | PASS |
| PIPE-02.5 | Accept exactly one active open initial/default stage. | `tests/backend/test_pipeline_service.py:239-245` rejects unknown/non-open default; `:411-412` asserts selected default id and exactly one `initial`. | PASS |
| PIPE-02.6 | Empty, >80 or normalized duplicate name returns HTTP 422 with stable detail and no write. | `tests/backend/test_pipeline_api.py:417-457` covers whitespace-empty, 81 characters and outer-whitespace/case duplicate; asserts 422, exact code/path, and `_database_snapshot(...) == before`. | PASS |
| PIPE-02.7 | Invalid non-`#RRGGBB` color returns 422 and leaves configuration unchanged. | `tests/backend/test_pipeline_api.py:371-379` asserts 422, `validation_error`, `body.stages.0.color`; successful following request with original version at `:397-403` proves the invalid call consumed no version/write. | PASS |
| PIPE-02.8 | A 51st active stage returns 422 and no write. | `tests/backend/test_pipeline_api.py:460-486` builds 51 active stages and asserts 422, `validation_error`, path `body`, and exact database snapshot equality. | PASS |
| PIPE-02.9 | Non-admin update returns 403 with database and audit unchanged. | Route result is asserted at `tests/backend/test_pipeline_api.py:307-329`; service-level zero-write proof at `tests/backend/test_pipeline_service.py:438-463` asserts unchanged pipeline version and audit count zero after authorization failure. | PASS |
| PIPE-03.1 | Empty-stage removal soft-archives without destination or physical deletion, timestamps it and compacts active order. | `tests/backend/test_pipeline_service.py:497-527` asserts absent only from active response, positions `range(8)`, zero transfer, archived object still present with `active is False`, exact `archived_at`, preserved key and audit action. | PASS |
| PIPE-03.2 | Occupied source requires a distinct active destination in the same pipeline. | Service branches at `tests/backend/test_pipeline_service.py:660-732` assert required, self, archived and foreign target codes; API boundary at `tests/backend/test_pipeline_api.py:489-545` asserts 422/code/path/no-write for each. | PASS |
| PIPE-03.3 | Move active and soft-deleted deals and archive source in the same PostgreSQL transaction. | `tests/backend/test_pipeline_service.py:553-570` asserts count 2, active+deleted rows, relational/packed target fields, histories, source absent from active result, exact archive timestamp and preserved source key. Rollback proof is at `:747-787`. | PASS |
| PIPE-03.4 | Bulk transfer history contains source/destination IDs and names, actor and exact instant. | `tests/backend/test_pipeline_service.py:561-567` asserts two rows, both IDs, both names, actor set and `all(history.changed_at == changed_at ...)`. | PASS |
| PIPE-03.5 | Transfer to `won` sets absent relational and packed won timestamp to transfer instant. | `tests/backend/test_pipeline_service.py:557,560` asserts `won_at == changed_at` and exact packed `2026-09-29T18:30:00Z`; repository proof at `tests/backend/test_pipeline_repository.py:225,229`. | PASS |
| PIPE-03.6 | Transfer to open/lost clears relational and packed won timestamp. | `tests/backend/test_pipeline_service.py:623-653` exercises non-won transfer and asserts `deal.won_at is None` and no packed `wonAt`; repository test at `tests/backend/test_pipeline_repository.py:237-258` confirms the same transition. | PASS |
| PIPE-03.7 | Missing, archived, self or foreign destination returns HTTP 422 with stable code/path and zero writes. | `tests/backend/test_pipeline_api.py:489-545` parameterizes all four cases and asserts exact 422, code, path and complete database snapshot equality. | PASS |
| PIPE-03.8 | Removing the last active open, won or lost stage returns 422 and zero writes. | `tests/backend/test_pipeline_api.py:548-571` parameterizes all three semantics and asserts 422, `pipeline_semantic_minimum`, path `stages`, and unchanged snapshot. | PASS |
| PIPE-03.9 | Any transfer/archive/audit failure rolls back every effect. | `tests/backend/test_pipeline_service.py:747-787` injects audit failure and asserts pipeline/workspace versions, source archive, deal relational/packed state, stage history and audit rows all unchanged/zero. | PASS |
| PIPE-04.1 | `won` semantics remain correct after visible rename. | `tests/ui-prototype.spec.cjs:2694-2700` moves by renamed stage UUID, asserts parseable `wonAt`, `{open:false, won:true, lost:false}`, and open count decrement. | PASS |
| PIPE-04.2 | Renamed `open` stage remains included in open semantics/indicators. | `tests/ui-prototype.spec.cjs:2674-2681` proves renamed stage exists and deal semantics are `{open:true, won:false, lost:false}` while initial open count is `5` at `:2668`. | PASS |
| PIPE-04.3 | Renamed `lost` stage is closed, not won, and clears won timestamp. | `tests/ui-prototype.spec.cjs:2705-2711` asserts lost-stage UUID, absent `wonAt`, `{open:false, won:false, lost:true}`, and unchanged open count after won→lost. | PASS |
| PIPE-04.4 | Billing automation follows immutable `systemKey=billing` after rename. | Clean pre-action state at `tests/ui-prototype.spec.cjs:2676-2677` is non-billing/no notification; after move `:2686-2689` asserts responsible becomes `u-billing` and exactly one new billing notification. M5 changed `app/static/index.html:2778` to `not-billing` and this assertion failed at `:2686`. | PASS |
| PIPE-04.5 | New deals use the configured active initial stage UUID and canonical name. | `tests/ui-prototype.spec.cjs:2715-2724` asserts form value `DEAL_STAGE_IDS[0]` and created `{pipelineId, stageId, stage}` equal the renamed configured initial stage. | PASS |
| PIPE-04.6 | Later rename does not rewrite historical display names. | `tests/backend/test_pipeline_service.py:648-657` asserts current deal name is renamed while prior `to_stage` and subsequent `from_stage` retain original source/target names. | PASS |
| PIPE-04.7 | Workspace save with absent/archived stage returns stable 409 and preserves canonical version. | `tests/backend/test_pipeline_service.py:747-762` asserts stale workspace current version; `tests/backend/test_api.py:469-474` asserts 409, `stage_configuration_changed` and current canonical version; service rollback evidence at `:779-787`. | PASS |
| PIPE-05.1 | One successful save appends one event with workspace/tenant, pipeline, result version, actor, UTC instant, actions and before/after. | `tests/backend/test_pipeline_service.py:421-435` asserts one event, `pipeline_id`, result version, actor, UTC offset zero, before/after version and action set; repository scope at `tests/backend/test_pipeline_repository.py:316` asserts `workspace_id == WORKSPACE_ID`. | PASS |
| PIPE-05.2 | Transfer audit includes only source/destination ids/names and count, never commercial payload. | `tests/backend/test_pipeline_service.py:571-578` asserts exact transfer summary and `"record" not in ...`; repository rejects a commercial audit snapshot at `tests/backend/test_pipeline_repository.py:318-330`. | PASS |
| PIPE-05.3 | Rejected or reverted operations append no admin history. | Validation rejection asserts audit zero at `tests/backend/test_pipeline_service.py:736-739`; injected rollback asserts zero at `:786-787`; API snapshot comparisons include `auditCount` at `tests/backend/test_pipeline_api.py:417-590`. | PASS |
| PIPE-05.4 | Admin history is newest-first and paginated in pages of 50 with required context. | `tests/backend/test_pipeline_repository.py:314-315` proves newest/previous order; `tests/backend/test_pipeline_api.py:298-300` rejects limit 51; `tests/ui-prototype.spec.cjs:3017-3035` asserts 50 items, actor/action/before/after/count/date, cursor and return page. | PASS |
| PIPE-05.5 | Non-admin history returns 403 and exposes no metadata. | `tests/backend/test_pipeline_api.py:307-329` asserts 403/`forbidden`; `tests/ui-prototype.spec.cjs:3038-3044` asserts hidden page, zero history elements and zero history requests. | PASS |
| PIPE-05.6 | No API/repository operation edits or deletes audit events. | `tests/backend/test_pipeline_repository.py:333-337` — `"update_audit" not in source` and `"delete_audit" not in source`; route inventory exposes only GET history and aggregate PUT. | PASS |
| PIPE-06.1 | Successful current-version save increments pipeline version exactly once. | `tests/backend/test_pipeline_service.py:402` — `result.pipeline_version == before.pipeline_version + 1`; `:421` one audit; API `tests/backend/test_pipeline_api.py:283-287` asserts resulting version 2 after one save. | PASS |
| PIPE-06.2 | Stale pipeline version returns 409/current version and executes no write. | `tests/backend/test_pipeline_service.py:438-463` asserts conflict code/current version, unchanged pipeline and zero audit; `tests/backend/test_pipeline_api.py:397-403` asserts 409, code and `currentPipelineVersion == 2`. | PASS |
| PIPE-06.3 | Deal transfer increments workspace version once and stale clients get current version. | `tests/backend/test_pipeline_service.py:553-554` asserts transfer count and `workspace_version + 1`; `:747-762` asserts conflict carries baseline workspace version; UI confirms pipeline/workspace versions 2 at `tests/ui-prototype.spec.cjs:2960-2962`. | PASS |
| PIPE-06.4 | Two same-version saves/retry produce one winner, one conflict, one increment and one audit. | `tests/backend/test_pipeline_service.py:466-494` asserts `sorted(outcomes) == ['conflict','saved']`, +1 version, one added stage, one audit, and retry conflict with counts unchanged. | PASS |
| PIPE-07.1 | Migration seeds exact nine legacy stages, order, colors, semantics, keys, version and default. | `tests/backend/test_tenant_migration_security.py:184-207` asserts exact arrays for names/types/colors/positions/keys, version 1, default first id, and nine rows for workspace. | PASS |
| PIPE-07.2 | Migration preserves counts, payloads, values and links while backfilling canonical IDs/history. | `tests/backend/test_tenant_migration_security.py:145-154` compares complete legacy fingerprint and row counts; `:216-229` asserts pipeline/stage IDs, unchanged payload, and history names/IDs. | PASS |
| PIPE-07.3 | Unknown legacy stage aborts before publishing the new Alembic revision. | `tests/backend/test_tenant_migration_security.py:262-274` expects DBAPI error, then asserts old `version_num` and absence of `deal_pipelines`. | PASS |
| PIPE-07.4 | Legacy text columns remain synchronized for application rollback compatibility. | `tests/backend/test_tenant_migration_security.py:232-259` updates legacy `stage`, then asserts canonical stage id/same pipeline and backfilled history IDs while text name remains `Ganho`. | PASS |
| PIPE-07.5 | Fleet advances only the selected tenant's expected revision after head/identity verification. | `tests/backend/test_fleet.py:430-456` asserts selected revision/status/profile become `(TENANT_HEAD,'active',2)`, unselected remains old/1, and both database revisions are exact. M6 bypassing control advance failed at `:449`. | PASS |
| PIPE-07.6 | Missing selection, backup, confirmation, correct prior revision or identity blocks migration. | `tests/backend/test_fleet.py:296-322` parameterizes selection/backup/confirmation/head and asserts no runner calls; identity mismatch at `:374-385` and revision mismatch at `:390-413` also assert no call/control change. | PASS |
| PIPE-07.7 | Tenant migration leaves DW databases, listener and HBA/access rules outside its scope. | `tests/backend/test_manual_windows_pg11_deployment.py:138-156` asserts revision command and DW/HBA boundaries; `tests/backend/test_manual_windows_pg11_outcomes.py:288-331` asserts exact Alembic head and runbook/listener outcomes. | PASS |

**Spec-anchored status**: **47/47 PASS**, zero spec-precision gaps.

## Edge cases

| Edge case | Evidence | Result |
|---|---|---:|
| Duplicate active names differing only by outer whitespace/case | `tests/backend/test_pipeline_api.py:439-457` sends `"  Mesmo Nome  "` and `"mesmo nome"`, then asserts 422, duplicate code/path and unchanged database snapshot. | PASS |
| Archive current initial/default without replacement | `tests/backend/test_pipeline_api.py:574-590` archives `defaultStageId`, then asserts 422, `pipeline_default_stage_invalid`, path `defaultStageId`, and unchanged snapshot. | PASS |
| Soft-deleted deal in archived stage | `tests/backend/test_pipeline_service.py:530-570` seeds active+deleted and asserts both transferred/history-updated before the source archive. | PASS |
| Archive occupied billing stage without reassigning its key | `tests/backend/test_pipeline_service.py:581-613` asserts transfer, archived billing source retains key, active target retains its own key, and no active stage receives `billing`. | PASS |
| Tenant database failure during PUT | `tests/backend/test_pipeline_api.py:635-664` injects OperationalError and asserts redacted 503 `database_unavailable`, no foreign/secret text and exact database snapshot equality. | PASS |
| Forged tenant route/body | `tests/backend/test_pipeline_api.py:389-406` rejects authority fields with 422 and alternate route with 404; dependency failure redaction at `:614-632` exposes neither foreign scope nor secret. | PASS |

**Edge-case status**: **6/6 PASS**.

## Mandatory build gate

| Gate | Command / isolation | Result |
|---|---|---:|
| Python compile | `.venv\Scripts\python.exe -m compileall -q app` | PASS, exit 0 |
| Compose configuration | `docker compose config --quiet` | PASS, exit 0 |
| Backend | `.venv\Scripts\python.exe -m pytest tests/backend -q`, with exclusive local `TEMP`/`TMP=.pytest-tmp\verifier-recheck-3548741` | **666 passed, 0 failed, 0 skipped**, 5 dependency warnings |
| Browser | `pnpm test` | **106 passed, 0 failed, 0 skipped** |
| Compose/demo | `.venv\Scripts\python.exe scripts/verify_demo.py`, with exclusive local temp | **71 passed, 0 failed**, Alembic `c7f3a9d8e2b1` |

Test integrity:

- Backend collection grew from 586 at planning commit `b4999b1` to 666, delta +80.
- Browser named `run(...)` scenarios grew from 69 to 82, delta +13; the runtime gate reports 106 assertions/scenarios passed.
- `git diff --name-status --diff-filter=D b4999b1..3548741 -- tests` returned no deleted test file.
- The feature test diff is additive overall. No skip/disable marker contributed to the accepted counts.
- `git diff --check b4999b1..3548741` returned no whitespace error.

## Discrimination sensor

**Depth**: P0-full manual fault injection, six behavior branches.
**Isolation**: detached worktree `D:/Develop_CRM_Project/.pytest-tmp/verifier-sensor-recheck-3548741` at `3548741`; no `git stash`; each mutation was reverted before the next and the worktree was removed after a clean tracked status.

| Mutant | Fault injected only in scratch | Discriminator | Result |
|---|---|---|---:|
| M1 — deleted transfer | `app/repositories/pipeline.py:209-215`: added `Deal.deleted_at.is_(None)` to omit soft-deleted deals. | `tests/backend/test_pipeline_service.py:553` failed: transfer count expected 2, got 1. | KILLED |
| M2 — won semantics | `app/repositories/pipeline.py:259`: changed semantic comparison `"won"` → `"lost"`. | `tests/backend/test_pipeline_repository.py:225` failed: `all(deal.won_at == changed_at ...)` was false. | KILLED |
| M3 — authorization | `app/policies.py:61`: returned true for `Action.MANAGE_PIPELINE` before the admin-only guard. | `tests/backend/test_authorization.py:96` failed for Gestor; focused result 1 failed, 5 passed. | KILLED |
| M4 — concurrency | `app/services/pipeline.py:153`: disabled version guard with `if False and ...`. | `tests/backend/test_pipeline_service.py:466-494` failed instead of producing exactly one saved/one conflict outcome. | KILLED |
| M5 — billing UI regression | `app/static/index.html:2778`: changed `target.systemKey === 'billing'` → `'not-billing'`. | Against scratch Uvicorn at port 18081, `tests/ui-prototype.spec.cjs:2686` failed because responsible remained `u-paula`; billing tests at `:1627` and `:1857` also failed. The unrelated secure-cookie assertion failed because this isolated server used HTTP; it is not counted as the discriminator. | KILLED |
| M6 — fleet control revision | `app/fleet.py:281-285`: replaced `_advance_control_revision(...)` with `advanced = True`. | `tests/backend/test_fleet.py:449` failed: selected control row remained old revision/profile 1. | KILLED |

The first M5 launch used the harness default `http://localhost:8080` and therefore exercised the already-running real-tree container, not the scratch HTML. It was discarded as invalid. The counted rerun explicitly set `SMART_CRM_TEST_URL=http://127.0.0.1:18081/` to the scratch application and killed M5 at the intended PIPE-UI-01 assertion.

**Sensor result**: **6/6 killed, 0 survived — PASS**.

## Baseline isolation

Before gate/sensor, real-tree `git status --porcelain=v1` hashed to SHA-256 `c5ffa1e3219a0cd19dfd32656c3dea145c1d4926731548239657f88be6fe4523`:

```text
 M .specs/features/customizable-deal-pipeline/spec.md
 M .specs/features/customizable-deal-pipeline/tasks.md
 M README.md
 M RUNBOOK_DEPLOY_WINDOWS_SERVER_2016.md
?? .pytest-tmp/
?? .specs/features/crm-mvp/tasks.md
?? .specs/features/customizable-deal-pipeline/validation.md
?? .venv/
?? smart_crm_demo.egg-info/
```

After removing the scratch worktree and exclusive gate temp directories, the porcelain bytes produced the same SHA-256. `git worktree list --porcelain` contained only the real checkout at `3548741`. The four T12 modifications and four declared pre-existing untracked paths were preserved. Overwriting this report is the only intended real-tree change by the Verifier.

## Code quality

| Check | Result |
|---|---:|
| Minimum code and no unrequested feature | PASS |
| Surgical scope; correction commit changes only tests and lesson bookkeeping | PASS |
| Existing repository/service/API/UI/fleet patterns retained | PASS |
| Tenant and authorization boundaries fail closed | PASS |
| Transaction and optimistic-concurrency outcomes asserted | PASS |
| Payload/conjunction rule satisfied for every AC | PASS |
| Per-layer matrix covers domain, API happy/error/edge, browser and operations | PASS |
| Every new test maps to a listed AC, edge case or prior verifier gap | PASS |
| Project guidance followed (`README.md`, `pyproject.toml`, `package.json`; strong defaults where no separate guideline exists) | PASS |

The correction commit `3548741` is test-only plus the script-owned lesson store. It closes the prior evidence gaps without changing product behavior or weakening earlier assertions. The billing test now begins from a non-billing assignee and proves a newly caused side effect; the corrected scratch sensor killed the exact former M5 mutant.

## Requirement traceability

| Requirement | Prior source status | Verifier disposition |
|---|---|---|
| PIPE-01 | In Progress | Verified, 5/5 ACs |
| PIPE-02 | In Progress | Verified, 9/9 ACs |
| PIPE-03 | In Progress | Verified, 9/9 ACs |
| PIPE-04 | In Progress | Verified, 7/7 ACs |
| PIPE-05 | In Progress | Verified, 6/6 ACs |
| PIPE-06 | In Progress | Verified, 4/4 ACs |
| PIPE-07 | In Progress | Verified, 7/7 ACs |

No spec-precision gap, surviving mutant, failed AC, `SPEC_DEVIATION`, or gate failure remains. This clean PASS creates no new lesson; existing candidate `L-024` remains unchanged.

## Summary

**Overall**: Ready
**Spec-anchored check**: 47/47 ACs matched the precise spec outcome
**Edge cases**: 6/6
**Gate**: 666 backend / 106 browser / 71 compose verifier, zero failures or skips
**Sensor**: 6/6 mutants killed, zero survivors
**Ranked gaps**: none
