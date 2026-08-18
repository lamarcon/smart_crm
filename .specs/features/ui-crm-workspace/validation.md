# ui-crm-workspace Validation

**Verdict**: PASS ✅
**Date**: 2026-08-18
**Spec**: `.specs/features/ui-crm-workspace/spec.md`
**Diff range**: `915821a1a3b1550521eccb68a5d916da42377618..9182c1cff4045dba0e7592bfd59b155fe1265e30`
**Verifier**: independent sub-agent, third fresh verification (author != verifier)

The implementation is ready. Evidence-or-zero proves all 36 acceptance criteria against their exact spec outcomes. The Build gate passes with 41 browser cases and 7 Compose checks. Three targeted mutants are killed, including the three gaps from the prior report.

---

## Task Completion

| Task | Recorded status | Independent result |
| --- | --- | --- |
| T1 | Complete | Spec and task structural validators pass with 0 errors and 0 warnings. |
| T2 | Complete | Legacy normalization, ISO metadata, UI defaults, and approved payloads are asserted. |
| T3 | Complete | DRAWER-01–DRAWER-06 have exact browser evidence. |
| T4 | Complete | FILTER-01–FILTER-12 and the required invalid-input branches have exact browser evidence. |
| T5 | Complete | BOARD-01–BOARD-10 have exact browser evidence for Leads and Deals. |
| T6 | Complete | DASH-01–DASH-08 have exact browser evidence. |
| T7 | Complete | Documentation matches the feature; Build gate passes. |
| T8 | Complete | The prior BOARD-03, DASH-04, and inverted-money-range gaps are closed. |

## Spec-Anchored Acceptance Criteria

Every row cites an observable assertion. A shared implementation is not counted as evidence.

### Drawer

| AC | Spec-defined outcome | `file:line` + assertion expression | Result |
| --- | --- | --- | --- |
| DRAWER-01 | Clicking the primary name in all four modules opens the right drawer with current record data. | `tests/ui-prototype.spec.cjs:161-180` iterates Lead, Contact, Company, and Deal; `assert.match(class, /open/)`, `assert.equal(heading, title)`, `assert.equal(inputValue, fieldValue)`, and right-edge geometry. | ✅ PASS |
| DRAWER-02 | Desktop keeps the source list visible and identifies the edited record. | `tests/ui-prototype.spec.cjs:176-181` uses `assert.match(subtitle, new RegExp(id))` and `assert.equal(sourcePage.isVisible(), true)` while the drawer is open. | ✅ PASS |
| DRAWER-03 | Valid save updates the record, closes the drawer, and refreshes the active view. | `tests/ui-prototype.spec.cjs:148-152` saves `Lead CRUD Editado`, then asserts exactly one rendered link and `assert.doesNotMatch(drawer.class, /open/)`. | ✅ PASS |
| DRAWER-04 | Unchanged Cancel closes without changing local state. | `tests/ui-prototype.spec.cjs:168-186` cancels all four unchanged drawers, asserts closure, then `assert.deepEqual(stateAfter, before)`. | ✅ PASS |
| DRAWER-05 | Dirty close requires confirmation before discard. | `tests/ui-prototype.spec.cjs:189-202` dismisses the dialog and proves the drawer stays open, then accepts and proves closure plus unchanged persisted name. | ✅ PASS |
| DRAWER-06 | At 390 px the drawer is full width with Save and Cancel accessible. | `tests/ui-prototype.spec.cjs:205-214` asserts `Math.round(box.width) === 390` and both action buttons visible. | ✅ PASS |

### Filters

| AC | Spec-defined outcome | `file:line` + assertion expression | Result |
| --- | --- | --- | --- |
| FILTER-01 | The panel shows default fields, saved-filter area, and Add field. | `tests/ui-prototype.spec.cjs:233-240` asserts `Filtros salvos`, visible `Adicionar campo`, and exact defaults `['name','stage','responsibleId','createdAt']`. | ✅ PASS |
| FILTER-02 | Adding/removing a field changes only the filter form. | `tests/ui-prototype.spec.cjs:241-246` asserts phone appears then disappears and `assert.deepEqual(leadsAfter, before)`. | ✅ PASS |
| FILTER-03 | Free text searches name, ID, responsible, and displayed relationships. | Name: `tests/ui-prototype.spec.cjs:129-139`; responsible, ID, and linked Contact: `tests/ui-prototype.spec.cjs:217-230`, with exact row counts and record names. | ✅ PASS |
| FILTER-04 | Criteria in different fields combine with AND. | `tests/ui-prototype.spec.cjs:249-265` applies responsible + stage + date and asserts only Larissa is included while João is excluded. | ✅ PASS |
| FILTER-05 | Multiple values in one field combine with OR. | `tests/ui-prototype.spec.cjs:277-290` selects two stages and asserts the two exact matching Deals. | ✅ PASS |
| FILTER-06 | Date offers and executes any, exact, before, after, and between. | `tests/ui-prototype.spec.cjs:293-311` asserts the exact operator set and result count for any/exact/before/after; `tests/ui-prototype.spec.cjs:249-264` executes between. | ✅ PASS |
| FILTER-07 | Money offers and executes exact, greater-than, less-than, and between. | `tests/ui-prototype.spec.cjs:314-333` asserts the exact operator set and result count for all four operators. | ✅ PASS |
| FILTER-08 | Responsible + date range + stage update the visible count without reload. | `tests/ui-prototype.spec.cjs:249-265` asserts the one-record result, footer count, and unchanged URL. | ✅ PASS |
| FILTER-09 | A new named filter persists its configuration for the current user and module. | `tests/ui-prototype.spec.cjs:374-388` asserts name, `u-admin`, `leads`, exact stage criterion, visible field, and ISO `updatedAt`; reload visibility is asserted at `tests/ui-prototype.spec.cjs:399-402`. | ✅ PASS |
| FILTER-10 | Reopen restores and delete removes a saved filter. | `tests/ui-prototype.spec.cjs:394-405` loads the preset, asserts Marina as the sole result, reloads, then asserts `savedFilters.length === 0` after deletion. | ✅ PASS |
| FILTER-11 | Reset clears values and restores module defaults. | `tests/ui-prototype.spec.cjs:390-393` asserts the exact default field list, empty stage selection, and empty text. | ✅ PASS |
| FILTER-12 | Permission visibility is applied before filtering. | `tests/ui-prototype.spec.cjs:425-433` filters as Vitor, asserts zero visible rows/count while the hidden Deal still exists unchanged in state. | ✅ PASS |

### Board

| AC | Spec-defined outcome | `file:line` + assertion expression | Result |
| --- | --- | --- | --- |
| BOARD-01 | Leads and Deals offer List/Kanban switching. | Deals switch and render Kanban at `tests/ui-prototype.spec.cjs:436-446`; Leads switch and render Kanban at `tests/ui-prototype.spec.cjs:556-564`; List rendering is asserted at `tests/ui-prototype.spec.cjs:449-455`. | ✅ PASS |
| BOARD-02 | List shows every stage as segmented progress and labels the current stage. | `tests/ui-prototype.spec.cjs:449-455` asserts 9 stage segments, label `Orçamentos enviados`, and exactly one `.current`. | ✅ PASS |
| BOARD-03 | Kanban groups cards in every fixed stage and shows the count for every column in both modules. | Leads: `tests/ui-prototype.spec.cjs:458-466` asserts 3 columns, all labels, and counts `['3','1','1']`; Deals: `tests/ui-prototype.spec.cjs:467-470` asserts all 9 labels and counts `['1','0','1','1','1','1','1','0','0']`. | ✅ PASS |
| BOARD-04 | A common Deal transition applies immediately and offers Undo. | `tests/ui-prototype.spec.cjs:473-488` selects `Negociação Revisão`, asserts the immediate stage, then finds/clicks `Desfazer`. | ✅ PASS |
| BOARD-05 | Undo restores the prior stage and transition data. | `tests/ui-prototype.spec.cjs:480-488` asserts exact history payload and restored stage; `tests/ui-prototype.spec.cjs:503-509` asserts restored responsible/notifications and single-use Undo. | ✅ PASS |
| BOARD-06 | Faturando and every closing stage require confirmation before mutation and automation. | Faturando dismiss/accept/state/automation rollback: `tests/ui-prototype.spec.cjs:491-509`; Gain and both loss closures dismiss/accept: `tests/ui-prototype.spec.cjs:512-526`. | ✅ PASS |
| BOARD-07 | Discarding a Lead requires a non-empty reason. | `tests/ui-prototype.spec.cjs:537-546` asserts empty input keeps `Em contato` with no reason, while valid input persists `Sem aderência`. | ✅ PASS |
| BOARD-08 | Conversion closes the Lead and creates its Deal in `Em Contato`. | `tests/ui-prototype.spec.cjs:548-553` asserts Lead stage and new Deal; full relationship/responsible/assistants/team payload is asserted at `tests/ui-prototype.spec.cjs:681-694`. | ✅ PASS |
| BOARD-09 | Both modules preserve active filters and the last selected view. | Deals: `tests/ui-prototype.spec.cjs:436-446`; Leads: `tests/ui-prototype.spec.cjs:556-567`; both reload and assert persisted Kanban plus filtered card count/state. | ✅ PASS |
| BOARD-10 | Narrow Kanban scrolls horizontally while card actions stay operable. | `tests/ui-prototype.spec.cjs:530-553` asserts `scrollWidth > clientWidth`, then completes discard and conversion through card controls at 390×844. | ✅ PASS |

### Dashboard

| AC | Spec-defined outcome | `file:line` + assertion expression | Result |
| --- | --- | --- | --- |
| DASH-01 | The filter offers `Todos`, `Leads`, and `Negócios`. | `tests/ui-prototype.spec.cjs:570-575` uses `assert.deepEqual(scopes, ['Todos','Leads','Negócios'])`. | ✅ PASS |
| DASH-02 | `Todos` offers responsible, team, and period. | `tests/ui-prototype.spec.cjs:576` asserts exact default fields `['responsibleId','team','createdAt']`; control visibility is asserted at `tests/ui-prototype.spec.cjs:625-627`. | ✅ PASS |
| DASH-03 | `Leads` offers stage, source, segment, and creation date. | `tests/ui-prototype.spec.cjs:577-580` asserts defaults containing stage/createdAt and addable `Origem` and `Segmento`. | ✅ PASS |
| DASH-04 | `Negócios` offers stage, responsible, contact, company, amount, creation, stage-change, and won dates. | `tests/ui-prototype.spec.cjs:581-588` asserts defaults containing stage/responsible/createdAt and addable `Empresa`, `Contato`, `Valor`, `Data da mudança de etapa`, and `Data de ganho`. | ✅ PASS |
| DASH-05 | Applied filters recalculate indicators, Pipeline, and recent movements. | `tests/ui-prototype.spec.cjs:591-607` asserts `R$ 19.400,00`, Pipeline `Ganho`, movement `Licenças Biocare`, and exclusion of Larissa. | ✅ PASS |
| DASH-06 | Responsible + period + stage stay active and show the combined slice. | `tests/ui-prototype.spec.cjs:595-613` asserts the exact filtered output and reopened values `u-paula`, `Ganho`, and `2026-08-12..2026-08-12`. | ✅ PASS |
| DASH-07 | Reset restores indicators for the profile-visible set. | `tests/ui-prototype.spec.cjs:616-634` captures the manager indicator, changes it, resets it to the original value, and asserts scope `all`. | ✅ PASS |
| DASH-08 | Manager limits indicators and responsible options to the manager's team. | `tests/ui-prototype.spec.cjs:616-627` asserts exact Lead/Deal counts and options `['Marcelo Martins','Paula Pincetta','Vitor Costa']`. | ✅ PASS |

**AC status**: 36/36 fully matched, 0 gaps, 0 spec-precision gaps.

## Edge Cases and Implicit Dimensions

| Case | Evidence | Result |
| --- | --- | --- |
| Empty combination keeps criteria editable and shows empty state plus zero count. | `tests/ui-prototype.spec.cjs:267-274`. | ✅ PASS |
| Incompatible saved field is ignored with an adjustment warning. | `tests/ui-prototype.spec.cjs:408-422`. | ✅ PASS |
| Profile change removes hidden data from List, Kanban, and indicators without deletion. | `tests/ui-prototype.spec.cjs:425-433` and `tests/ui-prototype.spec.cjs:637-652`. | ✅ PASS |
| Faturamento Undo restores responsible, notifications, and single-use state. | `tests/ui-prototype.spec.cjs:491-509`. | ✅ PASS |
| Restore demo resets the complete data and UI state. | `tests/ui-prototype.spec.cjs:663-671` uses `assert.deepEqual(restored, original)`. | ✅ PASS |
| Empty filter name is rejected without persistence. | `tests/ui-prototype.spec.cjs:344-351`. | ✅ PASS |
| Same-name preset updates one entry with the new criterion and ISO `updatedAt`. | `tests/ui-prototype.spec.cjs:361-371`. | ✅ PASS |
| Inverted date range is rejected and the panel stays open. | `tests/ui-prototype.spec.cjs:353-359`. | ✅ PASS |
| Inverted money range `40000..20000` is rejected with the exact warning and the panel stays open. | `tests/ui-prototype.spec.cjs:335-341`. | ✅ PASS |
| Corrupted localStorage restores a valid seed. | `tests/ui-prototype.spec.cjs:787-792`. | ✅ PASS |

## Discrimination Sensor

Mutations ran in detached worktree `D:\Develop_CRM_Project\.verifier-sensor-ui-crm-workspace-v3` against local port 8000. No stash or real-tree mutation occurred.

| Mutation | Scratch source | Fault | Result |
| --- | --- | --- | --- |
| M1 | `app/static/index.html:1046` | Changed every Kanban count from `stageRecords.length` to `stageRecords.length + 1`. | ✅ Killed: BOARD-03 failed at `tests/ui-prototype.spec.cjs:464`; 40 passed, 1 failed. |
| M2 | `app/static/index.html:462` | Changed the Deal field label from `Empresa` to `Organização`. | ✅ Killed: DASH-04 failed at `tests/ui-prototype.spec.cjs:584`; 40 passed, 1 failed. |
| M3 | `app/static/index.html:902` | Disabled rejection of inverted numeric/money ranges. | ✅ Killed: FILTER-07 inverted-money assertion failed at `tests/ui-prototype.spec.cjs:340`; 40 passed, 1 failed. |

**Sensor depth**: lightweight, 3 targeted behavior-level mutations.
**Result**: 3/3 killed, 0 survived, PASS ✅.
**Isolation**: real porcelain baseline `""`; scratch removed; pre-report porcelain `""`; exact match.

## Gate Check

- **Build commands from tasks.md**: `python scripts/verify_demo.py`; `pnpm test`.
- **Compose**: 7 passed, 0 failed.
- **Browser**: 41 passed, 0 failed, 0 skipped.
- **Total**: 48 passed, 0 failed, 0 skipped.
- **Browser count**: 15 before the feature, 41 after, delta +26.
- **Runtime note**: the repository's `pnpm test` launcher could not resolve the absent `node` alias after Compose passed. The unchanged target `tests/ui-prototype.spec.cjs` ran with the runtime-bundled Node and produced the 41/41 result above. No repository file was changed for this environment workaround.
- **Structural gates**: `validate_spec.py` and `validate_tasks.py` each report 0 errors and 0 warnings.

## Code Quality

| Principle | Status | Evidence |
| --- | --- | --- |
| Minimum code / no scope creep | ✅ | Diff is limited to the approved feature artifacts, prototype, browser tests, README, and prior validation lessons. |
| Surgical changes | ✅ | Existing single-file prototype architecture and server/Compose boundaries are preserved. |
| Matches approved design | ✅ | Registry, normalized UI state, typed filters, drawer, board, transition snapshot, and dashboard reuse match `design.md`. |
| Test integrity | ✅ | Browser cases increase 15→41; no skips, disabled tests, deleted cases, or weakened outcome assertions were found. |
| Spec-anchored outcomes | ✅ | 36/36 ACs cite exact observable assertions; 0 spec-precision gaps. |
| Per-layer coverage | ✅ | Browser behavior, state payloads, edge/error branches, static server integration, and Compose acceptance are covered. |
| Every in-scope test is claimed | ✅ | All 41 cases map to an AC, listed edge/implicit dimension, normalization requirement, or preserved DEMO regression. |
| Documented guidelines | ✅ | `README.md`, `package.json`, `tasks.md`, and TLC coding principles were followed. |
| Diff hygiene | ✅ | `git diff --check` reports only four intentional Markdown two-space hard breaks; no executable-file whitespace errors. |
| Senior-engineer approval | ✅ | Build, exact AC evidence, payload audit, error branches, and sensor all pass. |

## Requirement Traceability

The persisted validation report is the verification authority; `spec.md` was not modified by the Verifier.

- **Verified (36)**: DRAWER-01–DRAWER-06, FILTER-01–FILTER-12, BOARD-01–BOARD-10, DASH-01–DASH-08.
- **Needs fix (0)**: none.

## Interactive UAT

Not performed in this independent automated verification. The delegated pass criteria were AC evidence, Build gate, discrimination sensor, isolation, and code quality; all pass.

## Summary

**Overall**: ✅ Ready

- **Spec-anchored check**: 36/36 ACs matched; 0 gaps; 0 spec-precision gaps.
- **Gate**: 48/48 deterministic checks passed, 0 skipped.
- **Sensor**: 3/3 targeted mutants killed; scratch removed; real-tree baseline preserved.
- **Code quality**: PASS.
- **Prior gaps**: BOARD-03 now proves labels/counts for 3 Lead and 9 Deal columns; DASH-04 proves `Empresa` and all other required Deal fields; inverted monetary intervals are rejected and discriminating.
- **Next step**: none. The feature is ready.
