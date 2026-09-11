# Always Visible Custom Fields Validation

**Verdict**: PASS ✅
**Date**: 2026-09-11
**Spec**: `.specs/features/always-visible-custom-fields/spec.md`
**Diff range**: `004f57e..e6c48c6`
**Verifier**: independent sub-agent (author ≠ verifier)

---

## Task Completion

| Task | Status | Notes |
| --- | --- | --- |
| Inline implementation | ✅ Done | The diff changes only the feature spec, shared drawer behavior, and regression assertions. |

## Spec-Anchored Acceptance Criteria

| Requirement | Spec-defined outcome | `file:line` + assertion | Result |
| --- | --- | --- | --- |
| AVCF-01: opening a Lead, Contact, Company, or Deal record shows Campos adicionais | The tab is visible for all four entity types. | `tests/ui-prototype.spec.cjs:692` defines all four records and `tests/ui-prototype.spec.cjs:699` iterates them; `tests/ui-prototype.spec.cjs:708` asserts `customFieldsTab.isVisible() === true`. Implementation: `app/static/index.html:1824` sets `customTab.hidden = false` and `app/static/index.html:1826` keeps the tab list visible. | ✅ PASS |
| AVCF-02: an empty custom-fields panel shows the exact empty state and disables addition controls | Text is `Nenhum campo adicional visível.`; selector and add button are disabled. | `tests/ui-prototype.spec.cjs:711` matches the exact empty-state text; `tests/ui-prototype.spec.cjs:712` and `tests/ui-prototype.spec.cjs:713` assert both controls disabled. Implementation: `app/static/index.html:1889`, `app/static/index.html:1891`, `app/static/index.html:1896`, `app/static/index.html:1897`. | ✅ PASS |
| AVCF-03: an open Deal shows Informações, Campos adicionais, and Orçamentos | The three named tabs are simultaneously present. | `tests/ui-prototype.spec.cjs:1470` asserts the exact ordered labels `['Informações', 'Campos adicionais', 'Orçamentos']`; `tests/ui-prototype.spec.cjs:715` independently asserts three visible tabs. Implementation: `app/static/index.html:1824`, `app/static/index.html:1825`, `app/static/index.html:1826`. | ✅ PASS |
| AVCF-04: hiding the last custom field keeps Campos adicionais selected and shows the empty state | The custom tab remains visible and selected; the exact empty-state text replaces the field. | `tests/ui-prototype.spec.cjs:1782` selects the tab, `tests/ui-prototype.spec.cjs:1786` hides the last field, `tests/ui-prototype.spec.cjs:1795` asserts visibility, `tests/ui-prototype.spec.cjs:1796` asserts `aria-selected === 'true'`, and `tests/ui-prototype.spec.cjs:1797` matches the empty text. Implementation: `app/static/index.html:1927`, `app/static/index.html:1930`, `app/static/index.html:1932`, `app/static/index.html:1934`. | ✅ PASS |
| AVCF-05: after all module fields are hidden globally, another record still exposes the tab | Reopening a different record in the same module keeps Campos adicionais visible. | `tests/ui-prototype.spec.cjs:1732` through `tests/ui-prototype.spec.cjs:1738` cover two records after global hiding; `tests/ui-prototype.spec.cjs:1802` through `tests/ui-prototype.spec.cjs:1805` reopen a second record and assert the tab visible. Implementation: `app/static/index.html:1824` and `app/static/index.html:1826`. | ✅ PASS |

**Status**: 5/5 requirements match precise spec outcomes. No spec-precision gaps.

## Discrimination Sensor

The sensor used detached worktree `D:\Develop_CRM_Project\.verify-worktrees\avcf-sensor` at `e6c48c6`. The real worktree was never mutated and `git stash` was not used.

| Mutation | File:line | Behavior-level fault | Killed? |
| --- | --- | --- | --- |
| 1 | `app/static/index.html:1824` | Changed `customTab.hidden = false` to `true`, hiding Campos adicionais on drawer open. | ✅ Killed by `tests/ui-prototype.spec.cjs:508` and `tests/ui-prototype.spec.cjs:708`. |
| 2 | `app/static/index.html:1934` | Replaced `setDrawerTab(drawerActiveTab)` with `setDrawerTab('info')`, forcing navigation away after the last field is hidden. | ✅ Killed by `tests/ui-prototype.spec.cjs:1796`; mutant gate ended with 68 passed and 1 failed. |
| 3 | `app/static/index.html:1896` | Forced the empty-state selector enabled with `select.disabled = false`. | ✅ Killed by `tests/ui-prototype.spec.cjs:712`. |

**Sensor depth**: lightweight, 3 targeted mutations.
**Result**: 3/3 killed, PASS ✅.
**Isolation check**: the scratch server was stopped and the detached worktree was removed. Real-tree porcelain before and after was identical: only pre-existing untracked `.specs/features/crm-mvp/tasks.md` and `RUNBOOK_DEPLOY_WINDOWS_SERVER_2016.md` remained.

## Interactive UAT

Not performed. The feature is a small, deterministic visibility/state transition whose observable outcomes are fully exercised through Playwright against the running application.

## Code Quality

| Principle | Status |
| --- | --- |
| Minimum code and no unnecessary abstraction | ✅ Four obsolete conditional visibility branches were replaced by unconditional visibility. |
| Surgical changes | ✅ Production change is limited to `app/static/index.html`; spec and focused assertions are the only other diff entries. |
| No scope creep | ✅ No persistence schema, creation flow, or unrelated behavior changed. |
| Matches existing patterns | ✅ Reuses `renderDrawerCustomFields`, `setDrawerTab`, existing empty-state copy, and existing Playwright style. |
| Test integrity | ✅ Test count stayed at 69 before and after; no skips were added and no assertions were weakened. |
| Spec-anchored outcomes | ✅ 5/5 requirements have exact behavioral assertions. |
| Every changed test maps to a requirement | ✅ Drawer visibility/empty state maps to AVCF-01/02/03; global-hide and last-field assertions map to AVCF-04/05. |
| Documented guidelines | ✅ `README.md` full gate guidance checked; TLC `references/coding-principles.md` applied. |

## Edge Cases

- [x] All fields hidden globally: the tab stays visible on two records and persisted values/individual visibility remain unchanged (`tests/ui-prototype.spec.cjs:1732`, `tests/ui-prototype.spec.cjs:1742`, `tests/ui-prototype.spec.cjs:1743`).
- [x] Last visible field hidden from the drawer: the active tab remains selected and the empty state appears (`tests/ui-prototype.spec.cjs:1794`, `tests/ui-prototype.spec.cjs:1796`, `tests/ui-prototype.spec.cjs:1797`).
- [x] Empty module: selector and add button remain disabled (`tests/ui-prototype.spec.cjs:712`, `tests/ui-prototype.spec.cjs:713`).

## Gate Check

- **Gate command**: `$env:SMART_CRM_TEST_URL='http://127.0.0.1:8080/'; node tests/ui-prototype.spec.cjs`
- **Result**: 69 passed, 0 failed, 0 skipped.
- **Test count before feature**: 69.
- **Test count after feature**: 69.
- **Delta**: 0 test cases; focused assertions were added to existing cases.
- **Failures**: none.

## Requirement Traceability

| Requirement | Spec status | Validation status |
| --- | --- | --- |
| AVCF-01 | Implemented | ✅ Verified |
| AVCF-02 | Implemented | ✅ Verified |
| AVCF-03 | Implemented | ✅ Verified |
| AVCF-04 | Implemented | ✅ Verified |
| AVCF-05 | Implemented | ✅ Verified |

## Summary

**Overall**: ✅ Ready

The implementation satisfies all 5 requirements. The full UI gate passes, all 3 targeted mutants are killed, and the real-tree baseline is unchanged after sensor cleanup. No fix tasks or lessons are required.
