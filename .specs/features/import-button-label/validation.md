# Import Button Label Validation

**Date**: 2026-10-22  
**Spec**: inline requirement supplied for this verification  
**Diff range**: `0ce4ced^..0ce4ced`  
**Verifier**: independent sub-agent (author != verifier)  
**Verdict**: PASS

---

## Scope

On the administrator dashboard, the existing import button must:

- display exactly `⇩ Importar`;
- expose the exact accessible name `Importar`;
- keep the existing import action and open the same Bitrix import dialog;
- leave Bitrix-specific copy inside the dialog unchanged.

## Task Completion

| Task | Status | Notes |
| ---- | ------ | ----- |
| Small inline change | ✅ Done | Commit `0ce4ced` changes only `app/static/index.html` and `tests/ui-prototype.spec.cjs`. |

## Spec-Anchored Acceptance Criteria

| Criterion | Spec-defined outcome | `file:line` + assertion/evidence | Result |
| --------- | -------------------- | -------------------------------- | ------ |
| WHEN an Administrator sees the dashboard toolbar THEN the import button SHALL display only the shortened label while preserving the icon. | Exact visible text `⇩ Importar`. | `app/static/index.html:1890` renders `⇩ Importar`; `tests/ui-prototype.spec.cjs:2528` asserts `assert.equal((await importButton.textContent()).trim(), '⇩ Importar')`. | ✅ PASS |
| WHEN assistive technology identifies the import button THEN its accessible name SHALL be exact. | Exact accessible name `Importar`. | `app/static/index.html:1890` sets `aria-label="Importar"`; `tests/ui-prototype.spec.cjs:2527` locates `getByRole('button', { name: 'Importar', exact: true })`. | ✅ PASS |
| WHEN the import button is activated THEN it SHALL open the same existing import modal. | Existing `open-bitrix-import` action calls `openBitrixImport()`, and the Bitrix dialog becomes visible. | `app/static/index.html:1890` preserves `data-action="open-bitrix-import"`; `app/static/index.html:3829` dispatches it to `openBitrixImport()`; `app/static/index.html:3607` opens `bitrixImportDialog`; `tests/ui-prototype.spec.cjs:2529` clicks the button and `tests/ui-prototype.spec.cjs:2531` asserts the dialog's `CSV de Negócios` control is visible. | ✅ PASS |
| WHEN the label is shortened THEN Bitrix-specific copy inside the modal MAY remain unchanged. | Dialog still identifies Bitrix internally. | `app/static/index.html:669` retains `Importar amostra do Bitrix`; the commit does not change the dialog markup. | ✅ PASS |

**Status**: ✅ 4/4 outcomes are precise and covered.

## Gate Check

- **Positive test environment**: detached temporary worktree at commit `0ce4ced`, served locally from its own copied `app/static/index.html`.
- **Commands**: `SMART_CRM_TEST_FILTER=BITRIX node tests/ui-prototype.spec.cjs` and `SMART_CRM_TEST_FILTER=BCF-03 node tests/ui-prototype.spec.cjs` with `SMART_CRM_TEST_URL=http://127.0.0.1:8765/`.
- **Result**: 4 passed, 0 failed, 0 skipped.
- **Covered flows**: sample import, idempotent reimport, partial invalid import, and additional-field import/filter flow.
- **Diff hygiene**: `git diff 0ce4ced^ 0ce4ced --check` exited 0.
- **Test count before feature**: 122 (`98` `run` + `24` `runAuth`).
- **Test count after feature**: 122 (`98` `run` + `24` `runAuth`).
- **Delta**: 0; an existing import scenario was strengthened with exact visible-text and accessible-name assertions.

## Discrimination Sensor

| Mutation | File:line | Description | Killed? |
| -------- | --------- | ----------- | ------- |
| M1 | `app/static/index.html:1890` | In an isolated temporary worktree only, changed visible text from `⇩ Importar` back to `⇩ Importar Bitrix` while leaving `aria-label="Importar"` intact. | ✅ Killed: `tests/ui-prototype.spec.cjs:2528` failed with actual `⇩ Importar Bitrix` versus expected `⇩ Importar`; mutant run ended with 0 passed, 1 failed and exit code 1. |

**Sensor depth**: lightweight, proportional to the single-label change  
**Result**: 1/1 killed - PASS ✅

The temporary server was stopped and the worktree was removed. The real worktree status hash was `506B072D32153F6620DBEDC97A1EF4BC47497B4F859A260D21ECDE6098CE06EE` both before and after the sensor, proving isolation.

## Code Quality

| Principle | Status | Evidence |
| --------- | ------ | -------- |
| Minimum code | ✅ | One production line and the affected test locators changed. |
| Surgical changes | ✅ | Commit contains two files with no unrelated behavior change. |
| No scope creep | ✅ | Internal Bitrix copy and import mechanics remain unchanged. |
| Matches existing patterns | ✅ | Existing `data-action` dispatch and Playwright role locators are preserved. |
| Spec-anchored outcome check | ✅ | Exact visible and accessible names are asserted. |
| Tests are discriminating | ✅ | M1 was killed by the exact visible-text assertion. |
| Documented guidelines | ✅ | `README.md:269`-`README.md:278` defines the browser gate; targeted execution used the same test runner with its built-in filter. |

## Edge Cases

- [x] The icon remains visible as part of the exact text assertion.
- [x] The accessible name excludes the icon and the removed `Bitrix` suffix.
- [x] The existing import action and modal identity remain unchanged.
- [x] Other import scenarios can still find and activate the button by its new exact accessible name.

## Requirement Traceability

| Requirement | Status |
| ----------- | ------ |
| Inline import-button-label requirement | ✅ Verified |

## Summary

**Overall**: ✅ Ready

**Spec-anchored check**: 4/4 outcomes matched  
**Gate**: 4 passed, 0 failed  
**Sensor**: 1/1 mutation killed  
**Issues found**: none
