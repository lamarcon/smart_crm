# ui-crm-workspace Validation

**Verdict**: FAIL ❌
**Date**: 2026-08-18
**Spec**: `.specs/features/ui-crm-workspace/spec.md`
**Diff range**: `915821a1a3b1550521eccb68a5d916da42377618..4995f8714edb2a37168fb1c64592b73236bcab66`
**Verifier**: independent sub-agent (author != verifier)

The deterministic gates and discrimination sensor pass, but evidence-or-zero finds only 15 of 36 acceptance criteria fully asserted. A green runner cannot override the 21 incomplete criteria.

---

## Task Completion

| Task | Recorded status | Verification result |
| --- | --- | --- |
| T1 | Complete | Structural validators pass: 0 errors, 0 warnings. |
| T2 | Complete | Gate passes, but the detailed `stageHistory` payload is not asserted. |
| T3 | Complete | 2/6 drawer ACs have complete assertion evidence. |
| T4 | Complete | 4/12 filter ACs have complete assertion evidence. |
| T5 | Complete | 6/10 board ACs have complete assertion evidence. |
| T6 | Complete | 3/8 dashboard ACs have complete assertion evidence. |
| T7 | Complete | Build gate passes: 7/7 Compose checks and 34/34 browser cases. |

## Spec-Anchored Acceptance Criteria

Evidence-or-zero is applied to every required outcome inside an AC. A row is a gap when an existing test covers only part of a conjunction.

### Drawer

| AC | Spec-defined outcome | `file:line` + assertion evidence | Result |
| --- | --- | --- | --- |
| DRAWER-01 | Clicking each of the four primary names opens the right drawer with that record's current data. | `tests/ui-prototype.spec.cjs:171` `assert.match(await drawer.getAttribute('class'), /open/)`; `tests/ui-prototype.spec.cjs:172` asserts only the entity-type heading. No assertion checks a current field value or right-side geometry. | ❌ GAP |
| DRAWER-02 | Desktop keeps the source list visible and identifies the edited record. | `tests/ui-prototype.spec.cjs:173` `assert.equal(await page.locator(...).isVisible(), true)` proves the list remains visible; `tests/ui-prototype.spec.cjs:172` checks only `Editar Lead/Contato/Empresa/Negócio`, not the record ID/name. | ❌ GAP |
| DRAWER-03 | Saving valid drawer data updates the record, closes the drawer, and refreshes the active view. | `tests/ui-prototype.spec.cjs:151` `assert.equal(...'Lead CRUD Editado'...).count(), 1)` proves update/render. No assertion proves the drawer closed. | ❌ GAP |
| DRAWER-04 | Canceling an unchanged drawer closes it without changing local state. | `tests/ui-prototype.spec.cjs:175` clicks Cancel in the unchanged four-record loop, but there is no assertion on drawer closure or before/after local state. The test at lines 179-193 covers a dirty drawer instead. | ❌ GAP |
| DRAWER-05 | Dirty close asks for confirmation before discard. | `tests/ui-prototype.spec.cjs:187` keeps the drawer open after dismiss; `tests/ui-prototype.spec.cjs:191` closes after accept; `tests/ui-prototype.spec.cjs:192` asserts the persisted name stayed `Larissa Spinola`. | ✅ PASS |
| DRAWER-06 | At 390 px the drawer is full width and Save/Cancel remain accessible. | `tests/ui-prototype.spec.cjs:202` `assert.equal(Math.round(box.width), 390)`; `tests/ui-prototype.spec.cjs:203-204` assert both actions visible. | ✅ PASS |

### Filters

| AC | Spec-defined outcome | `file:line` + assertion evidence | Result |
| --- | --- | --- | --- |
| FILTER-01 | Opening module filters shows default fields, saved filters, and Add field. | `tests/ui-prototype.spec.cjs:224-225` asserts `Filtros salvos` and `Adicionar campo`; no assertion identifies the module's default fields. | ❌ GAP |
| FILTER-02 | Adding/removing a field changes only the filter form, not stored records. | `tests/ui-prototype.spec.cjs:228-230` asserts the field appears then disappears; `tests/ui-prototype.spec.cjs:231` `assert.deepEqual((await stateFrom(page)).leads, before)`. | ✅ PASS |
| FILTER-03 | Free text searches every searchable textual value, including name, ID, responsible, and displayed relationships. | `tests/ui-prototype.spec.cjs:211-216` proves responsible and ID; `tests/ui-prototype.spec.cjs:134-135` proves name. No assertion uses a value unique to a displayed relationship such as contact/company, so the full conjunction is unproved. | ❌ GAP |
| FILTER-04 | Different fields combine with AND and only records satisfying every active criterion remain. | `tests/ui-prototype.spec.cjs:245-247` asserts one exact result, includes Larissa, and excludes João after responsible + stage + date are active. | ✅ PASS |
| FILTER-05 | Multiple values in one field combine with OR. | `tests/ui-prototype.spec.cjs:266-268` asserts exactly the two deals belonging to the two selected stages after the amount criterion. | ✅ PASS |
| FILTER-06 | Date fields offer exact, before, after, between, and any-date operators. | `tests/ui-prototype.spec.cjs:241-243` exercises only `between`; there is no assertion for the five offered operator values or behavior of the other four. | ❌ GAP |
| FILTER-07 | Numeric/money fields offer exact, greater-than, less-than, and between. | `tests/ui-prototype.spec.cjs:263-268` exercises only `gt`; there is no assertion for the four offered operators or behavior of the other three. | ❌ GAP |
| FILTER-08 | Responsible + date range + stage apply together and update the visible count without reload. | `tests/ui-prototype.spec.cjs:245-247` asserts table rows and content. No assertion checks the rendered visible-count footer or unchanged page navigation for this structured-filter flow. | ❌ GAP |
| FILTER-09 | A new named filter persists its complete configuration for current user and module. | `tests/ui-prototype.spec.cjs:279-282` asserts name, `userId`, and `scope`; `tests/ui-prototype.spec.cjs:293` proves the preset name survives reload. The persisted `filter` configuration is never asserted, violating the payload/conjunction rule. | ❌ GAP |
| FILTER-10 | Reopening restores configuration and deleting removes the preset. | `tests/ui-prototype.spec.cjs:287-288` asserts the restored preset returns only Marina; `tests/ui-prototype.spec.cjs:293` finds it after reload; `tests/ui-prototype.spec.cjs:296` asserts zero saved filters after deletion. | ✅ PASS |
| FILTER-11 | Reset clears values and restores module defaults. | `tests/ui-prototype.spec.cjs:284` clicks Reset but immediately loads a preset; no assertion checks cleared values or restored default fields. | ❌ GAP |
| FILTER-12 | Authorization limits the candidate set before active filters calculate results. | `tests/ui-prototype.spec.cjs:546-562` proves unfiltered profile visibility only. No test keeps a filter active while switching to a restricted profile and asserts both filtered output and preserved underlying data. | ❌ GAP |

### Board

| AC | Spec-defined outcome | `file:line` + assertion evidence | Result |
| --- | --- | --- | --- |
| BOARD-01 | Leads and Deals can switch between List and Kanban. | `tests/ui-prototype.spec.cjs:320-326` proves Deals Kanban and persisted view; `tests/ui-prototype.spec.cjs:341-342` proves Leads Kanban; `tests/ui-prototype.spec.cjs:333-335` proves the Deals list renderer. | ✅ PASS |
| BOARD-02 | List displays a segmented stage bar, progress, and current-stage label. | `tests/ui-prototype.spec.cjs:333-335` asserts 9 segments, label `Orçamentos enviados`, and exactly one `.current` segment. | ✅ PASS |
| BOARD-03 | Kanban groups by all fixed stages and shows each column count. | `tests/ui-prototype.spec.cjs:341-344` asserts 3 columns, 5 cards, and only the `Em contato` count. It does not assert fixed column labels or counts for every column. | ❌ GAP |
| BOARD-04 | A common Deal transition applies immediately and offers Undo. | `tests/ui-prototype.spec.cjs:353` asserts immediate stage `Negociação Revisão`; the successful `Desfazer` interaction at line 354 and restored assertion at line 356 prove the offered action. | ✅ PASS |
| BOARD-05 | Undo restores the prior stage and prior data. | `tests/ui-prototype.spec.cjs:356` restores the common stage; `tests/ui-prototype.spec.cjs:373-374` restores both stage and responsible after Faturamento. | ✅ PASS |
| BOARD-06 | Faturando and every closing transition require confirmation before transition/automation. | `tests/ui-prototype.spec.cjs:366` proves canceled Faturando does not transition; `tests/ui-prototype.spec.cjs:370` and `tests/ui-prototype.spec.cjs:510-514` prove confirmed automation payload. No assertion covers canceled/confirmed `Ganho`, `Orçamento Não Aprovado`, or `Analisar falha`. | ❌ GAP |
| BOARD-07 | Discarding a Lead requires a non-empty reason before transition. | `tests/ui-prototype.spec.cjs:388` asserts a supplied reason is stored. No assertion cancels or submits an empty reason and proves the Lead remains in its old stage. | ❌ GAP |
| BOARD-08 | Conversion marks the Lead converted and creates the corresponding Deal in `Em Contato`. | `tests/ui-prototype.spec.cjs:394-395` asserts Lead stage plus new Deal contact/stage; `tests/ui-prototype.spec.cjs:486-490` asserts stage, responsible, assistants, and team payload fields. | ✅ PASS |
| BOARD-09 | Switching List/Kanban preserves filters and the last module view. | `tests/ui-prototype.spec.cjs:320-326` proves query + view persistence only for Deals. There is no equivalent assertion for Leads, although the approved independent test calls for both. | ❌ GAP |
| BOARD-10 | Narrow Kanban scrolls horizontally without hiding primary card actions. | `tests/ui-prototype.spec.cjs:383` asserts `scrollWidth > clientWidth`; subsequent successful card controls at `tests/ui-prototype.spec.cjs:384-395` prove the primary stage actions remain operable. | ✅ PASS |

### Dashboard

| AC | Spec-defined outcome | `file:line` + assertion evidence | Result |
| --- | --- | --- | --- |
| DASH-01 | Dashboard offers scopes Todos, Leads, Negócios. | `tests/ui-prototype.spec.cjs:403` `assert.deepEqual(..., ['Todos', 'Leads', 'Negócios'])`. | ✅ PASS |
| DASH-02 | Todos allows responsible, team, and period filters. | `tests/ui-prototype.spec.cjs:440-441` asserts responsible options only. Team and period controls are not asserted. | ❌ GAP |
| DASH-03 | Leads allows stage, origin, segment, and creation date. | `tests/ui-prototype.spec.cjs:405-406` asserts Origin and Segment only. Stage and creation date are not asserted. | ❌ GAP |
| DASH-04 | Deals allows stage, responsible, contact, company, value, creation date, stage-change date, and won date. | `tests/ui-prototype.spec.cjs:409-412` asserts Contact, Value, stage-change date, and won date only. Stage, responsible, company, and creation date are not asserted. | ❌ GAP |
| DASH-05 | Filters recalculate indicators, Pipeline, and recent movements from matching records. | `tests/ui-prototype.spec.cjs:428-431` asserts exact R$ 19,400 result, Pipeline stage, included movement, and excluded Lead movement. | ✅ PASS |
| DASH-06 | Responsible + period + stage remain active and display their combined slice. | `tests/ui-prototype.spec.cjs:428-431` proves the combined output, but no assertion checks the three criteria remain stored/active after application. | ❌ GAP |
| DASH-07 | Reset restores indicators for the profile-visible set. | `tests/ui-prototype.spec.cjs:446` restores the initial open-deal indicator; `tests/ui-prototype.spec.cjs:448` restores scope `all`. | ✅ PASS |
| DASH-08 | Manager limits both indicators and responsible options to team members. | `tests/ui-prototype.spec.cjs:441` asserts the exact three responsible options. No assertion compares an indicator with the exact manager-visible team set, so the conjunction is incomplete. | ❌ GAP |

**AC status**: 15/36 fully matched, 21/36 gaps, 0 spec-precision gaps.

## Edge Cases

| Edge case | Evidence | Result |
| --- | --- | --- |
| Empty filter result shows empty state, zero count, and keeps criteria editable. | `tests/ui-prototype.spec.cjs:252` asserts only `Nenhum Lead encontrado`; zero footer count and editable criteria are not asserted. | ❌ GAP |
| Incompatible saved field is ignored and an adjustment warning appears. | `tests/ui-prototype.spec.cjs:311-313` asserts the exact warning, absent unknown field, and intact Lead data. | ✅ PASS |
| Profile change removes a hidden record from List, Kanban, and indicators without deleting local data. | `tests/ui-prototype.spec.cjs:548-562` covers List rows only; Kanban, Dashboard indicators, and retained local record are not asserted together. | ❌ GAP |
| Faturamento Undo restores the responsible change. | `tests/ui-prototype.spec.cjs:373-374` restores both `Em Contato` and `u-paula`. | ✅ PASS |
| Restore demo resets data, default filters/views, and incompatible presets. | `tests/ui-prototype.spec.cjs:466` `assert.deepEqual(restored, original)` compares the full normalized state, including UI defaults and saved filters; line 467 proves the added Lead was removed. | ✅ PASS |

Additional implicit-dimension gaps: empty filter names, inverted date/value ranges, same-name filter update, a second unavailable Undo, and rollback of Faturamento notifications have no direct assertion evidence.

## Payload and Conjunction Audit

| Payload/conjunction | Evidence | Result |
| --- | --- | --- |
| Converted Deal | `tests/ui-prototype.spec.cjs:486-490` asserts converted Lead stage plus Deal stage, responsible, assistants, and team; Deal lookup at line 485 binds contact and company. | ✅ PASS |
| Faturamento automation | `tests/ui-prototype.spec.cjs:510-514` separately asserts stage, responsible, team, and both notification payloads (`userId`, exact text, Deal ID in detail). | ✅ PASS |
| Quote regression payload | `tests/ui-prototype.spec.cjs:525`, `tests/ui-prototype.spec.cjs:529-530`, and `tests/ui-prototype.spec.cjs:541-542` assert displayed total, persisted total, and both empty/present PDF values. | ✅ PASS |
| SavedFilter | `tests/ui-prototype.spec.cjs:279-282` asserts name/user/scope but not `filter`; implementation at `app/static/index.html:860` persists the unasserted configuration. | ❌ GAP |
| Stage history | Test `tests/ui-prototype.spec.cjs:112` asserts only `Array.isArray(deal.stageHistory)`. Design specifies `{from,to,at,byId}` at `.specs/features/ui-crm-workspace/design.md:208`, while implementation stores `{from,to,changedAt,changedById}` at `app/static/index.html:1272`. | ❌ DESIGN MISMATCH |
| SavedFilter timestamp | Design requires `updatedAt` at `.specs/features/ui-crm-workspace/design.md:184`; new/update paths at `app/static/index.html:858-860` never write it. | ❌ DESIGN MISMATCH |

## Discrimination Sensor

The real tree was clean before the sensor. Mutations ran in detached worktree `D:\Develop_CRM_Project\.verifier-sensor-ui-crm-workspace`, served by its own Python server on port 18081; the real test runner targeted that scratch URL. The scratch was removed without `git stash`.

| Mutation | Scratch file:line | Behavior fault | Result |
| --- | --- | --- | --- |
| M1 | `app/static/index.html:732` | `every(...)` to `some(...)`, changing cross-field AND to OR. | ✅ Killed: 29 passed, 5 failed; filter/dashboard assertions failed. |
| M2 | `app/static/index.html:1306` | Removed `Faturando` from protected Deal stages. | ✅ Killed: BOARD-06 failed on canceled transition (`Faturando` instead of `Em Contato`); run total 32 passed, 2 failed. The second failure was incidental DRAWER-06 visibility. |
| M3 | `app/static/index.html:1313` | Undo cloned current state instead of the pre-transition snapshot. | ✅ Killed: BOARD-04/05 and BOARD-06 restoration assertions failed; 32 passed, 2 failed. |

**Sensor depth**: lightweight, 3 high-risk behavior-level mutations.
**Result**: 3/3 killed, 0 survived, PASS ✅.
**Isolation**: real `git status --porcelain=v1` baseline `""`; after scratch removal `""`; exact match.

## Gate Check

- **Build command from tasks.md**: `python scripts/verify_demo.py`; `pnpm test`
- **Environment note**: `python` and `node` aliases were absent from PATH. The same scripts ran through the bundled Python/Node runtimes; no repository file changed.
- **Compose integration**: 7 passed, 0 failed.
- **Browser regression**: 34 passed, 0 failed, 0 skipped.
- **Total deterministic checks**: 41 passed, 0 failed, 0 skipped.
- **Browser count before feature**: 15.
- **Browser count after feature**: 34.
- **Delta**: +19 cases.
- **Structural**: `validate_spec.py` 0 errors/0 warnings; `validate_tasks.py` 0 errors/0 warnings.

## Code Quality

| Principle | Status | Evidence |
| --- | --- | --- |
| No feature beyond requested scope | ✅ | Diff is limited to feature artifacts, README, the approved self-contained prototype, and its browser suite. |
| Surgical changes | ✅ | Seven changed files correspond to planning, implementation, regression, and delivery documentation. |
| Matches approved architecture | ❌ | `StageMetadata` and `SavedFilter` payload shapes diverge from `.specs/features/ui-crm-workspace/design.md:184` and `.specs/features/ui-crm-workspace/design.md:208` without a `SPEC_DEVIATION`. |
| Minimum code / no orphaned feature code | ❌ | `discardLead` at `app/static/index.html:1255` has no caller; legacy `changeDealStage` at `app/static/index.html:1320` is retained only behind the now-unproduced `data-deal-stage` listener at `app/static/index.html:1410`. |
| Test integrity | ✅ | Test count increased 15→34; no skip markers; existing payload assertions were preserved or strengthened. |
| Spec-anchored outcome check | ❌ | 21 ACs lack one or more required assertion outcomes. |
| Per-layer coverage expectation | ❌ | Listed edge/error branches and grouped operator/field conjunctions are incomplete. |
| Every in-scope test is claimed | ✅ | New cases map to current ACs/edge cases/T2 normalization; prior 15 cases map to T7's explicit full-regression requirement. |
| Project guidelines followed | ✅ | `README.md`, `package.json`, `.specs/features/ui-prototype/tasks.md`, and strong defaults were reviewed as declared by `tasks.md`. |
| Senior-engineer approval | ❌ | Green gates and good mutation discrimination do not compensate for incomplete AC assertions and two undocumented design payload mismatches. |

## Ranked Gaps and Fix Plans

1. **Major: complete the 21 partially/uncovered ACs.** Add explicit, spec-derived assertions for every missing conjunct: drawer data/identity/close/cancel state; default fields; relationship search; all date/number operators; visible count; SavedFilter configuration; reset; permission-before-filter; full Kanban columns; all closing guards; rejected empty discard reason; Leads view persistence; complete Dashboard fields/active state/manager indicators.
2. **Major: complete edge and failure-path coverage.** Assert empty-state count/editability, profile-change behavior across List/Kanban/Dashboard without data deletion, inverted intervals, empty filter name, same-name preset update, notification rollback, and single-use Undo.
3. **Major: resolve design payload mismatches.** Either implement `SavedFilter.updatedAt` and `{from,to,at,byId}` exactly as designed, or formally amend the approved design/spec and add exact payload assertions. Do not silently retain divergent field names.
4. **Minor: remove feature-orphaned wrappers.** Delete `discardLead`, `changeDealStage`, and the dead `data-deal-stage` listener if no compatibility requirement exists; otherwise document and test that compatibility path.

## Requirement Traceability Update

The verifier did not modify `spec.md`; this report is the validation authority.

- **Verified (15)**: DRAWER-05, DRAWER-06, FILTER-02, FILTER-04, FILTER-05, FILTER-10, BOARD-01, BOARD-02, BOARD-04, BOARD-05, BOARD-08, BOARD-10, DASH-01, DASH-05, DASH-07.
- **Needs fix (21)**: DRAWER-01, DRAWER-02, DRAWER-03, DRAWER-04, FILTER-01, FILTER-03, FILTER-06, FILTER-07, FILTER-08, FILTER-09, FILTER-11, FILTER-12, BOARD-03, BOARD-06, BOARD-07, BOARD-09, DASH-02, DASH-03, DASH-04, DASH-06, DASH-08.

## Interactive UAT

Not performed. This independent automated verification does not substitute for human visual review, but UAT cannot change the current FAIL because 21 ACs lack automated evidence.

## Summary

**Overall**: ❌ Not Ready

- **Spec-anchored check**: 15/36 ACs fully matched; 21 gaps; 0 spec-precision gaps.
- **Gate**: 41/41 deterministic checks passed, 0 skipped.
- **Sensor**: 3/3 mutants killed; real-tree baseline preserved.
- **Code quality**: FAIL due incomplete coverage, two design payload mismatches, and orphaned feature paths.
- **Next step**: turn the ranked gaps into fix tasks, implement without weakening existing tests, then run a fresh independent verification.
