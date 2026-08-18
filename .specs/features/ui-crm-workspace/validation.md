# ui-crm-workspace Validation

**Verdict**: FAIL ❌
**Date**: 2026-08-18
**Spec**: `.specs/features/ui-crm-workspace/spec.md`
**Diff range**: `915821a1a3b1550521eccb68a5d916da42377618..3c40148`
**Verifier**: independent sub-agent, second iteration (author != verifier)

The implementation, Build gate, and discrimination sensor pass. Evidence-or-zero proves 34 of 36 acceptance criteria completely. BOARD-03 lacks Deal-column evidence, DASH-04 lacks evidence that Empresa is available, and the required inverted money-range failure path is untested. The feature is not ready until all three gaps are closed.

---

## Task Completion

| Task | Recorded status | Verification result |
| --- | --- | --- |
| T1 | Complete | Spec/design/tasks exist and map all 36 ACs. |
| T2 | Complete | Normalization passes; `stageHistory` now uses the approved payload. |
| T3 | Complete | 6/6 drawer ACs have exact assertion evidence. |
| T4 | Complete | 12/12 filter ACs have AC evidence; one implicit numeric-range error branch remains untested. |
| T5 | Complete | 9/10 board ACs have complete evidence; BOARD-03 proves only Leads. |
| T6 | Complete | 7/8 dashboard ACs have complete evidence; DASH-04 omits Empresa. |
| T7 | Complete | Build gate passes with 41 browser cases and 7 Compose checks. |
| T8 | Complete | Most prior gaps are closed, but its 36/36 evidence claim is not substantiated. |

## Spec-Anchored Acceptance Criteria

Evidence-or-zero is applied to every required outcome. Shared implementation does not replace an assertion for an uncovered module or field.

### Drawer

| AC | Spec-defined outcome | `file:line` + assertion evidence | Result |
| --- | --- | --- | --- |
| DRAWER-01 | Four primary names open the right drawer with current data. | `tests/ui-prototype.spec.cjs:161-180` iterates all modules and asserts open state, heading, value, ID, and right geometry. | ✅ PASS |
| DRAWER-02 | Desktop keeps source list visible and identifies the record. | `tests/ui-prototype.spec.cjs:176-181` asserts ID, right placement, and source visibility. | ✅ PASS |
| DRAWER-03 | Save updates, closes, and refreshes active view. | `tests/ui-prototype.spec.cjs:148-152` asserts the rendered new name and closed drawer. | ✅ PASS |
| DRAWER-04 | Unchanged Cancel closes without state mutation. | `tests/ui-prototype.spec.cjs:168-186` captures state, cancels each module, asserts closure, and deep-compares state. | ✅ PASS |
| DRAWER-05 | Dirty close asks before discard. | `tests/ui-prototype.spec.cjs:189-202` dismisses/accepts confirmation and proves no persisted mutation. | ✅ PASS |
| DRAWER-06 | At 390 px drawer is full width and actions are accessible. | `tests/ui-prototype.spec.cjs:205-214` asserts width 390 and visible Save/Cancel. | ✅ PASS |

### Filters

| AC | Spec-defined outcome | `file:line` + assertion evidence | Result |
| --- | --- | --- | --- |
| FILTER-01 | Panel shows defaults, saved filters, and Add field. | `tests/ui-prototype.spec.cjs:233-240` asserts heading, action, and exact defaults. | ✅ PASS |
| FILTER-02 | Add/remove changes only filter form. | `tests/ui-prototype.spec.cjs:241-246` asserts field appearance/removal and deep-equal data. | ✅ PASS |
| FILTER-03 | Free text searches name, ID, responsible, and relationships. | Name: `tests/ui-prototype.spec.cjs:129-135`; responsible/ID/contact: `tests/ui-prototype.spec.cjs:217-230`. | ✅ PASS |
| FILTER-04 | Different fields combine with AND. | `tests/ui-prototype.spec.cjs:249-265` asserts the sole match, exclusion, count, and stable URL. | ✅ PASS |
| FILTER-05 | Multiple same-field values combine with OR. | `tests/ui-prototype.spec.cjs:277-290` selects two stages and asserts both exact Deals. | ✅ PASS |
| FILTER-06 | Date offers/executes any, exact, before, after, between. | `tests/ui-prototype.spec.cjs:293-311` covers set and four behaviors; between at `tests/ui-prototype.spec.cjs:256-264`. | ✅ PASS |
| FILTER-07 | Money offers/executes exact, greater, less, between. | `tests/ui-prototype.spec.cjs:314-335` asserts exact set and each result count. | ✅ PASS |
| FILTER-08 | Responsible + range + stage update count without reload. | `tests/ui-prototype.spec.cjs:249-265` asserts combined output, footer count, and URL. | ✅ PASS |
| FILTER-09 | New named filter persists config for current user/module. | `tests/ui-prototype.spec.cjs:368-382` asserts name/user/scope/filter/ISO `updatedAt`; reload at `tests/ui-prototype.spec.cjs:393-396`. | ✅ PASS |
| FILTER-10 | Reopen restores and delete removes preset. | `tests/ui-prototype.spec.cjs:388-399` asserts restored record, reload persistence, and deletion. | ✅ PASS |
| FILTER-11 | Reset clears values and restores defaults. | `tests/ui-prototype.spec.cjs:384-387` asserts exact defaults and empty stage/text values. | ✅ PASS |
| FILTER-12 | Permission visibility constrains filtered results. | `tests/ui-prototype.spec.cjs:419-427` asserts zero hidden results/count, retained data, and filter state. | ✅ PASS |

### Board

| AC | Spec-defined outcome | `file:line` + assertion evidence | Result |
| --- | --- | --- | --- |
| BOARD-01 | Leads and Deals switch List/Kanban. | Deals: `tests/ui-prototype.spec.cjs:430-440`; Leads: `tests/ui-prototype.spec.cjs:546-554`; List: `tests/ui-prototype.spec.cjs:443-449`. | ✅ PASS |
| BOARD-02 | List shows segmented bar, progress, current label. | `tests/ui-prototype.spec.cjs:443-449` asserts nine segments, label, and one current segment. | ✅ PASS |
| BOARD-03 | Kanban groups every fixed stage and shows each count for Leads and Deals. | `tests/ui-prototype.spec.cjs:452-460` asserts all Lead labels/counts only. No assertion checks nine Deal Kanban labels/counts; `tests/ui-prototype.spec.cjs:686-691` is a List filter. | ❌ GAP |
| BOARD-04 | Common Deal transition applies immediately and offers Undo. | `tests/ui-prototype.spec.cjs:463-478` asserts change, invokes Undo, and observes restoration. | ✅ PASS |
| BOARD-05 | Undo restores prior stage and data. | `tests/ui-prototype.spec.cjs:471-478` asserts payload/stage; `tests/ui-prototype.spec.cjs:481-499` proves responsible/notifications rollback and single-use Undo. | ✅ PASS |
| BOARD-06 | Faturando and all closing stages require confirmation. | Faturando: `tests/ui-prototype.spec.cjs:481-499`; all closures: `tests/ui-prototype.spec.cjs:502-517`. | ✅ PASS |
| BOARD-07 | Discard requires non-empty reason. | `tests/ui-prototype.spec.cjs:527-536` proves empty rejection and valid persistence. | ✅ PASS |
| BOARD-08 | Conversion closes Lead and creates Deal in Em Contato. | `tests/ui-prototype.spec.cjs:538-543` and full payload at `tests/ui-prototype.spec.cjs:670-683`. | ✅ PASS |
| BOARD-09 | Both modules preserve filters and last view. | Deals: `tests/ui-prototype.spec.cjs:430-440`; Leads: `tests/ui-prototype.spec.cjs:546-557`. | ✅ PASS |
| BOARD-10 | Narrow Kanban scrolls and keeps card actions operable. | `tests/ui-prototype.spec.cjs:520-543` asserts overflow and operates discard/conversion. | ✅ PASS |

### Dashboard

| AC | Spec-defined outcome | `file:line` + assertion evidence | Result |
| --- | --- | --- | --- |
| DASH-01 | Offers Todos, Leads, Negócios. | `tests/ui-prototype.spec.cjs:560-565` asserts exact labels. | ✅ PASS |
| DASH-02 | Todos allows responsible, team, period. | `tests/ui-prototype.spec.cjs:565-566` asserts exact defaults; visibility at `tests/ui-prototype.spec.cjs:613-616`. | ✅ PASS |
| DASH-03 | Leads allows stage, origin, segment, creation date. | `tests/ui-prototype.spec.cjs:567-570` asserts defaults and addable Origin/Segment. | ✅ PASS |
| DASH-04 | Deals allows stage, responsible, contact, company, value, creation/stage-change/won dates. | `tests/ui-prototype.spec.cjs:571-577` asserts all except `Empresa`. Implementation declares it at `app/static/index.html:434`, but evidence-or-zero requires a test assertion. | ❌ GAP |
| DASH-05 | Filters recalculate indicators, Pipeline, movements. | `tests/ui-prototype.spec.cjs:580-596` asserts value, stage, included Deal, excluded Lead. | ✅ PASS |
| DASH-06 | Responsible + period + stage stay active and show combined slice. | `tests/ui-prototype.spec.cjs:584-602` asserts output and reopened active controls. | ✅ PASS |
| DASH-07 | Reset restores profile-visible indicators. | `tests/ui-prototype.spec.cjs:605-623` captures, changes, resets, and restores manager value/scope. | ✅ PASS |
| DASH-08 | Manager limits indicators and responsible options to team. | `tests/ui-prototype.spec.cjs:605-616` asserts exact Lead/Deal indicators and three options. | ✅ PASS |

**AC status**: 34/36 fully matched, 2/36 gaps, 0 spec-precision gaps.

## Edge Cases and Implicit Dimensions

| Case | Evidence | Result |
| --- | --- | --- |
| Empty result shows empty state, zero count, editable criteria. | `tests/ui-prototype.spec.cjs:267-274`. | ✅ PASS |
| Incompatible saved field is ignored with warning. | `tests/ui-prototype.spec.cjs:402-416`. | ✅ PASS |
| Profile change removes hidden data from List/Kanban/indicators without deletion. | List/data: `tests/ui-prototype.spec.cjs:419-427`; Kanban/indicator/data: `tests/ui-prototype.spec.cjs:626-641`. | ✅ PASS |
| Faturamento Undo restores responsible/notifications and is single-use. | `tests/ui-prototype.spec.cjs:481-499`. | ✅ PASS |
| Restore demo resets full data/UI state. | `tests/ui-prototype.spec.cjs:652-660`. | ✅ PASS |
| Empty filter name is rejected. | `tests/ui-prototype.spec.cjs:338-345`. | ✅ PASS |
| Same-name preset updates one record and has `updatedAt`. | `tests/ui-prototype.spec.cjs:355-365`. | ✅ PASS |
| Inverted date and money ranges are rejected. | Date only: `tests/ui-prototype.spec.cjs:347-353`. Generic code exists at `app/static/index.html:896-905`, but no assertion exercises inverted money. | ❌ GAP |

## Payload and Conjunction Audit

| Payload | Evidence | Result |
| --- | --- | --- |
| Drawer composite outcomes | `tests/ui-prototype.spec.cjs:148-214`. | ✅ PASS |
| SavedFilter | `tests/ui-prototype.spec.cjs:338-382` asserts update plus name/user/scope/filter/ISO `updatedAt`. | ✅ PASS |
| Stage history | `tests/ui-prototype.spec.cjs:469-475` asserts exact `{from,to,at,byId}` keys/values/time; code at `app/static/index.html:1273`. | ✅ PASS |
| Converted Deal | `tests/ui-prototype.spec.cjs:670-683` asserts Lead stage and Deal relationship/stage/responsible/assistants/team. | ✅ PASS |
| Faturamento automation/rollback | `tests/ui-prototype.spec.cjs:481-499` and `tests/ui-prototype.spec.cjs:694-707`. | ✅ PASS |

## Discrimination Sensor

Mutations ran in detached worktree `D:\Develop_CRM_Project\.verifier-sensor-ui-crm-workspace-v2` on port 18082. No real-tree mutation or stash occurred.

| Mutation | Scratch source | Fault | Result |
| --- | --- | --- | --- |
| M1 | `app/static/index.html:740` | Cross-field `every(...)` changed to `some(...)` (AND→OR). | ✅ Killed: 34 passed, 7 failed. |
| M2 | `app/static/index.html:1308` | Removed `Faturando` from protected stages. | ✅ Killed: BOARD-06 failed; 39 passed, 2 failed, including one incidental DRAWER-06 visibility failure. |
| M3 | `app/static/index.html:1273` | Renamed history key `at` to `changedAt`. | ✅ Killed: exact payload assertion failed; 40 passed, 1 failed. |

**Sensor depth**: lightweight, 3 high-risk mutations.
**Result**: 3/3 killed, 0 survived, PASS ✅.
**Isolation**: real porcelain baseline `""`; scratch removed; final porcelain `""`; exact match.

## Gate Check

- **Build command**: `python scripts/verify_demo.py`; `pnpm test`.
- **Runtime note**: `python`/`node` aliases are absent from PATH. The unchanged scripts ran through bundled Python/Node executables; alias-only attempts failed before repository code executed.
- **Compose**: 7 passed, 0 failed.
- **Browser**: 41 passed, 0 failed, 0 skipped.
- **Total**: 48 passed, 0 failed, 0 skipped.
- **Browser count**: 15 before, 41 after, delta +26.

## Code Quality

| Principle | Status | Evidence |
| --- | --- | --- |
| No scope creep / surgical changes | ✅ | Diff is limited to feature artifacts, README, prototype, tests, and generated lessons. |
| Approved architecture/payloads | ✅ | `SavedFilter.updatedAt` and `{from,to,at,byId}` match `.specs/features/ui-crm-workspace/design.md:184` and `.specs/features/ui-crm-workspace/design.md:208`. |
| No feature-orphaned wrappers | ✅ | Prior `discardLead`, `changeDealStage`, and `data-deal-stage` paths were removed. |
| Test integrity | ✅ | Browser count increased 15→41; no skips or weakened assertions found. |
| Spec-anchored outcome check | ❌ | BOARD-03 and DASH-04 lack complete assertion evidence. |
| Per-layer coverage | ❌ | Inverted money-range validation has no browser assertion. |
| Every test is claimed | ✅ | Cases map to ACs, edges, implicit dimensions, normalization, or regression. |
| Senior-engineer approval | ❌ | Green gates/sensor do not override two AC gaps and one required error-path gap. |

## Ranked Gaps and Fix Plans

1. **Major: prove DASH-04 Empresa availability.** Extend `tests/ui-prototype.spec.cjs:571-577` to assert `Empresa` in Deal add-field options.
2. **Major: prove BOARD-03 for Deals.** Assert all nine Deal Kanban labels and all nine rendered counts.
3. **Major: cover inverted monetary intervals.** Select Deal `amount` + `between`, enter start > end, then assert the exact warning, open/editable panel, and unchanged persisted filters/records.

## Requirement Traceability Update

The verifier did not modify `spec.md`; this report is the validation authority.

- **Verified (34)**: DRAWER-01–DRAWER-06, FILTER-01–FILTER-12, BOARD-01, BOARD-02, BOARD-04–BOARD-10, DASH-01–DASH-03, DASH-05–DASH-08.
- **Needs fix (2)**: BOARD-03, DASH-04.

## Interactive UAT

Not performed. UAT cannot change the FAIL while automated evidence gaps remain.

## Summary

**Overall**: ❌ Not Ready

- **Spec-anchored check**: 34/36 ACs matched; 2 gaps; 0 spec-precision gaps.
- **Gate**: 48/48 deterministic checks passed, 0 skipped.
- **Sensor**: 3/3 mutants killed; real-tree porcelain preserved.
- **Code quality**: FAIL due BOARD-03, DASH-04, and inverted monetary-range coverage.
- **Next step**: close the three ranked gaps, then run a third fresh independent verification.
