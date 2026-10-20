# Validation: Histórico Operacional de Negócios e Empresas V1 — PASS

**Date**: 2026-10-20
**Spec**: `.specs/features/deal-company-activity-history/spec.md`
**Diff range**: `a78dca9^..95b453d`
**Candidate release**: `0.3.0`
**Tenant schema head**: `e1c4a7b9d2f6`
**Verifier**: independent sub-agent (author != verifier)
**Production state**: local candidate only; no upload, production migration, cutover or rollback was executed.

---

## Task Completion

| Task group | Status | Notes |
| --- | --- | --- |
| T1–T18 | Done | Implementation commits are present in the declared diff range. |
| T19 | Done | Independent verifier report recorded PASS; author closeout updated task, traceability and success-criteria status. |

## Spec-Anchored Acceptance Criteria

Every numbered criterion is covered below. Assertions target the spec-defined value or state; no spec-precision gap was found.

| Criterion | Spec-defined outcome | `file:line` + assertion expression | Result |
| --- | --- | --- | --- |
| HIST-01.1–01.2 | Newest-first Deal timeline with immutable event metadata and São Paulo display time | `tests/backend/test_activity_api.py:255` — categories are returned in canonical order; `tests/ui-prototype.spec.cjs:1633` — exact first/last IDs `['52','3']`; `tests/ui-prototype.spec.cjs:1634` — rendered time matches `/19\/10\/2026.*12:52/`; `tests/ui-prototype.spec.cjs:1635` — UTC `15:52` is rejected | PASS |
| HIST-01.3–01.4 | Movement persists original/target stage IDs and names, including administrative source/actor | `tests/backend/test_workspace_service.py:522` — exact movement detail dictionary; `tests/backend/test_workspace_service.py:520`–`521` — actor is `u-1` / `Ana`; `tests/backend/test_pipeline_service.py:656` — transfer produces movement plus automation categories | PASS |
| HIST-01.5–01.6 | Category filtering and stable opaque cursor beyond 50 events | `tests/backend/test_activity_api.py:259`–`275` — opaque cursor, second page and exact automation filter; `tests/ui-prototype.spec.cjs:1636`–`1645` — loads 52 and returns only automation cards | PASS |
| HIST-01.7 | Missing, hidden or foreign Deal is indistinguishable as not found | `tests/backend/test_activity_service.py:230` — `test_hidden_missing_and_foreign_deals_share_generic_not_found`; `tests/backend/test_activity_api.py:325` — API response parity for hidden/missing subjects | PASS |
| HIST-02.1–02.4 | Stage/automation effects and events commit atomically; rollback leaves no success event | `tests/backend/test_workspace_service.py:517`–`522` — one history row and one movement event with exact details; `tests/backend/test_deal_automation.py:184`–`195` — assignment, two notifications and exactly one matching event; `tests/backend/test_deal_automation.py:278`–`283` — outer rollback restores assignment and leaves zero side effects | PASS |
| HIST-02.5–02.6 | Failure is redacted and retry is idempotent | `tests/backend/test_deal_automation.py:240`–`252` — safe failure code/actions and unchanged assignee; `tests/backend/test_deal_automation.py:170` and `194` — retry returns the original result and only one event exists | PASS |
| HIST-02.7 | Historical names survive later stage rename | `tests/backend/test_workspace_service.py:547`–`548` — after both stages are renamed, stored `fromStageName` remains `Em Contato` and `toStageName` remains the original captured name | PASS |
| HIST-03.1–03.2 | Valid trimmed observation creates one server-owned event | `tests/backend/test_activity_service.py:256`–`268` — exact category, session actor, server timestamp, workspace and plain-text details | PASS |
| HIST-03.3–03.4 | Invalid length returns validation failure; view-only user cannot write | `tests/backend/test_activity_service.py:280`–`285` — invalid texts raise and event count stays zero; `tests/backend/test_activity_service.py:341`–`346` — mutation forbidden and event count stays zero; `tests/backend/test_activity_api.py:369`–`370` — stable HTTP 422 envelope | PASS |
| HIST-03.5–03.7 | No update/delete surface; corrections append; retry returns original | `tests/backend/test_activity_service.py:303`–`307` — retry keeps same ID and one row; `tests/backend/test_activity_service.py:327`–`330` — correction order is new then original and update/delete methods do not exist | PASS |
| HIST-04.1–04.2 | Desktop uses wide two-column drawer while existing fields remain usable | `tests/ui-prototype.spec.cjs:1529` — `HIST-04` wide accessible shell test; `tests/ui-prototype.spec.cjs:1623` — existing Save action remains visible | PASS |
| HIST-04.3 | Loading, empty and error states do not disable Deal data | `tests/ui-prototype.spec.cjs:1666` — `HIST-04 mantém os campos utilizáveis durante erro e retry vazio` | PASS |
| HIST-04.4–04.5 | Mobile stacks without horizontal scroll and preserves keyboard/Escape/focus behavior | `tests/ui-prototype.spec.cjs:1609` — mobile stacking test; `tests/ui-prototype.spec.cjs:1621`–`1623` — vertical order, no horizontal overflow and visible Save action; `tests/ui-prototype.spec.cjs:1529` — accessible drawer lifecycle | PASS |
| HIST-04.6 | Successful observation appears at the top without full reload | `tests/ui-prototype.spec.cjs:1681` — Deal observation test asserts immediate, escaped, idempotent and reload-persistent item | PASS |
| HIST-05.1–05.2 | Company summary includes only visible active Deals and exact counts/Decimal sums | `tests/backend/test_company_deals.py:196`–`207` — exact total, open/won/lost counts, amounts, rows and responsible; `tests/backend/test_company_deals.py:226`–`229` — summary and list share visibility scope | PASS |
| HIST-05.3–05.4 | Rename preserves semantic bucket; company/value/semantic mutations recalculate canonically | `tests/backend/test_company_deals.py:287`–`289` — renamed label still has semantic `won` and count 1; `tests/backend/test_company_deals.py:294` — canonical recalculation test | PASS |
| HIST-05.5–05.6 | Linked list exposes required fields and nested Deal navigation returns to Company | `tests/backend/test_company_api.py:400`–`406` — exact visible active rows and totals; `tests/ui-prototype.spec.cjs:1800`–`1817` — Company → Deal → Company navigation restores tab/context | PASS |
| HIST-05.7–05.8 | Empty state is zeroed; deleted/foreign data is excluded | `tests/backend/test_company_deals.py:238`–`248` — zero items/amounts and deleted/missing/hidden Company returns no summary; `tests/backend/test_company_api.py:403`–`406` — deleted Deal absent | PASS |
| HIST-06.1–06.3 | Company creation/change/observation events carry actor/time, before/after values and immutability | `tests/backend/test_workspace_service.py:624`–`646` — exact creation/update events, field list, before/after and actor; `tests/backend/test_company_api.py:353`–`356` — idempotent Company observation with canonical actor/text | PASS |
| HIST-06.4–06.5 | Linked Deal events are not copied and no-op saves create no empty event | `tests/backend/test_activity_repository.py:258` — Company timeline excludes linked Deal events; `tests/backend/test_workspace_service.py:616` and `624` — no-op increments workspace operation but event list remains exactly the two real Company mutations | PASS |
| HIST-06.6 | Confidential custom field content is persistently redacted | `tests/backend/test_workspace_service.py:636`–`645` — stored change has `before=None`, `after=None`, `redacted=True` and serialized details contain neither secret; `tests/ui-prototype.spec.cjs:1830`–`1831` — UI shows `conteúdo redigido` and not secret values | PASS |
| HIST-06.7 | Company timeline is newest-first and cursor-paginated past 50 | `tests/backend/test_company_api.py:310`–`328` — no-store first/second pages, opaque cursor and exact filter; `tests/ui-prototype.spec.cjs:1827`–`1841` — 50 then 52 cards with `cursor-50` | PASS |
| HIST-07.1–07.3 | Events stay in selected tenant/workspace, forged ownership is rejected, RLS is enabled and forced | `tests/backend/test_activity_repository.py:188` and `271` — missing/foreign workspace rejected/hidden; `tests/backend/test_authorization.py:356` — compiled Deal predicate contains `deals.workspace_id = 'default'`; `tests/backend/test_tenant_migration_security.py:590` and `600`–`623` — RLS is enabled/forced and fails closed | PASS |
| HIST-07.4–07.6 | Soft-delete preserves audit while operational reads hide it; migration is additive and unavailable sources fail closed | `tests/backend/test_company_deals.py:246` and `tests/backend/test_company_api.py:406` — deleted records excluded operationally; `tests/backend/test_tenant_migration_security.py:667`–`684` — downgrade removes only feature schema and preserves prior pipeline schema; `tests/backend/test_company_api.py:494` — dependency failure is redacted, closed and no-store | PASS |
| HIST-07.7 | Fleet migration remains explicit, selected-only and does not publish failed revision | `tests/backend/test_fleet.py:265`–`266` — only selected tenant is probed; `tests/backend/test_fleet.py:368`–`370` — only explicitly selected tenant migrates; `tests/backend/test_fleet.py:483`–`490` — post-check failure keeps previous control revision and redacts result | PASS |
| HIST-08.1 | Backend exposes canonical `0.3.0` read-only without cache | `tests/backend/test_api.py:178`–`181` — exact JSON, `Cache-Control: no-store` and security headers | PASS |
| HIST-08.2–08.3 | Authenticated sidebar shows `v0.3.0`; metadata failure is non-blocking and invents no version | `tests/ui-prototype.spec.cjs:884` and `891` — success and failure behavior tests | PASS |
| HIST-08.4–08.5 | Package metadata and offline bundle use/include the canonical version source and UI | `tests/backend/test_windows_multitenant_bundle.py:97`–`101` — pyproject dynamic version resolves `APP_VERSION == '0.3.0'`; package contract includes application/static sources in the same test module | PASS |

**Spec-anchored status**: 8/8 requirements and all 54 numbered acceptance criteria matched a precise spec outcome; 0 evidence gaps; 0 spec-precision gaps.

## Edge Cases

| Edge case | Evidence | Result |
| --- | --- | --- |
| Equal timestamps tie-break by event ID | `tests/backend/test_activity_repository.py:222` — 51+ equal-timestamp keyset test asserts deterministic pages | PASS |
| Deactivated actor remains a historical snapshot | `tests/backend/test_activity_service.py:256`–`268` — event actor is stored from server-owned snapshot, independent of later lookup | PASS |
| Archived/renamed stage keeps historical name | `tests/backend/test_workspace_service.py:547`–`548` | PASS |
| Null Deal value sums as zero without row mutation | `tests/backend/test_company_deals.py:191`–`207` | PASS |
| Zero-valued buckets keep correct counts | `tests/backend/test_company_deals.py:260`–`263` | PASS |
| HTML/script observation renders as text | `tests/backend/test_activity_service.py:266`; `tests/ui-prototype.spec.cjs:1681` | PASS |
| Concurrent observation does not overwrite entity | `tests/backend/test_activity_service.py:288`–`307` — idempotent append leaves one event and preserves workspace version behavior | PASS |
| Multi-recipient automation produces one execution event | `tests/backend/test_deal_automation.py:189`–`195` — two notifications, one event | PASS |
| Company summary reloads canonical server state | `tests/backend/test_company_deals.py:294`; `tests/ui-prototype.spec.cjs:1800` | PASS |

## Gate Check

| Gate | Evidence | Result |
| --- | --- | --- |
| Full backend regression | Author run: `.venv\\Scripts\\python.exe -m pytest --basetemp .pytest-tmp tests/backend -q` | PASS — 785 passed, 0 failed, 6 warnings, 187.09 s |
| Full browser regression | Author run: `node tests/ui-prototype.spec.cjs` against the local candidate | PASS — 122 passed, 0 failed |
| Compose acceptance | Author run with `PYTHONUTF8=1`: `.venv\\Scripts\\python.exe scripts\\verify_demo.py` | PASS — 75 passed, 0 failed; head `e1c4a7b9d2f6` |
| Targeted final backend recheck | Verifier run: two corrected workspace tests plus explicit workspace-predicate test | PASS — 3 passed in 4.12 s |
| Targeted final browser recheck | Verifier run: HIST-01 timezone and HIST-06 redaction flows | PASS — 2 passed, 0 failed |
| Python syntax | Verifier run: `.venv\\Scripts\\python.exe -m compileall -q app` | PASS |
| Compose structure | Verifier run: `docker compose config --quiet` | PASS |
| Spec structure | Verifier run: TLC `validate_spec.py --strict` | PASS — 0 errors, 0 warnings |
| Task structure | Verifier run: TLC `validate_tasks.py --strict` | PASS — 0 errors, 0 warnings |
| Diff hygiene | Verifier run: `git diff --check a78dca9^..95b453d` | PASS |

**Test count before feature/version closeout**: backend 784, browser 120.
**Test count after feature**: backend 785, browser 122.
**Delta**: backend +1, browser +2.
**Removed or skipped tests**: none reported or found in the feature diff.
**Harness note**: an earlier Compose console reader used Windows `cp1252` for Docker UTF-8 output; the same cached gate passed with `PYTHONUTF8=1`. This was a console-decoding issue, not an application/database failure.

## Discrimination Sensor

Mutations were applied only in the detached worktree `.local/activity-verifier-sensor` at `95b453d`. The worktree was removed afterward. Real-tree `git status --porcelain` matched the captured baseline exactly.

| Mutation | File:line | Expected discriminator | Result |
| --- | --- | --- | --- |
| Disable `redactInHistory` branch (`if ...` → `if False`) | `app/services/activity.py:221` | `tests/backend/test_workspace_service.py:636` exact redacted payload and `:644`–`:645` absence of both secrets | KILLED |
| Corrupt captured destination stage name (`toStageName` → `MUTATED`) | `app/services/activity.py:149` | `tests/backend/test_workspace_service.py:522` exact stage snapshot and `:547`–`:548` post-rename preservation | KILLED |
| Format timeline in UTC instead of `America/Sao_Paulo` | `app/static/index.html:2631` | `tests/ui-prototype.spec.cjs:1634` expects `12:52` and `:1635` rejects `15:52` | KILLED |

**Sensor depth**: lightweight, highest-risk corrected behaviors.
**Sensor result**: 3/3 killed — PASS.

The prior authoring sensor also reported four killed behavior mutants: activity append/idempotency, server billing automation condition, explicit workspace predicate and semantic Company grouping. The workspace-predicate mutant initially survived because RLS independently hid foreign rows; `tests/backend/test_authorization.py:345`–`356` now discriminates the application-layer predicate directly.

## Code Quality

| Principle | Status |
| --- | --- |
| Minimum code / no features beyond approved V1 | PASS |
| Surgical changes and no unrelated refactor | PASS |
| Existing patterns for repositories, services, schemas and routes | PASS |
| Append-only/auditable domain behavior | PASS |
| Spec-anchored assertions are exact and non-shallow | PASS |
| Domain, route, PostgreSQL integration and browser layers are represented | PASS |
| Every in-scope test maps to a requirement, edge case or task done-when | PASS |
| Project guidance followed: `README.md`, `pyproject.toml`, `package.json`, feature spec/design/tasks | PASS |

## Deployment Checklist — Not Executed

1. Record approved release commit, ZIP SHA-256, selected tenant set and maintenance-window authorization.
2. Back up and verify `server.env`, scheduled-task XML, active `pg_hba.conf`, `smartcrm_control` and each selected tenant database.
3. Upload the signed offline package side by side and verify checksum/package integrity before extraction.
4. Install into the release-local virtual environment and run validate-only configuration gates without changing the active task.
5. Run fleet preflight and migrate only explicitly selected tenants from `c7f3a9d8e2b1` to `e1c4a7b9d2f6` after backup confirmation.
6. Cut over the scheduled task to the new side-by-side release using `SmartCRMService`, preserving the previous task XML and release folder.
7. Run local/public health, login/logout, sidebar version, Deal timeline/observation, Company totals/history and role-isolation UAT.
8. On failure, restore the previous scheduled task and environment. Restore a database only from the verified matching backup when the migration itself requires it.

## Final Summary

**Overall**: PASS — ready to close local validation and prepare a release package.
**Spec-anchored check**: 8/8 requirements, all numbered criteria matched; 0 gaps.
**Sensor**: 3/3 final corrective mutants killed; isolated worktree removed.
**Gate**: full author regressions green; independent targeted, syntax, Compose-structure and TLC structural gates green.
**Ranked gaps**: none.
**Deployment authorization**: this report does not authorize or execute production deployment.
