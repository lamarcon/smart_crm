# Validation: global-custom-field-visibility - PASS ✅

**Date**: 2026-08-25
**Spec**: `.specs/features/global-custom-field-visibility/spec.md`
**Diff range**: `e18bb89..3d358a0`
**Commits**: `2d5b077`, `ae9e61a`, `3d358a0`
**Verifier**: independent sub-agent (author != verifier)

## Verdict

All six acceptance criteria and all three edge cases match the spec-defined outcomes with direct `file:line` assertions. All required real-tree gates passed. Both behavior mutants were killed in isolated scratch copies, and cleanup restored the real-tree porcelain exactly.

## Task Completion

| Commit | Scope | Status |
| --- | --- | --- |
| `2d5b077` | Module-wide custom visibility and primary coverage | ✅ Done |
| `ae9e61a` | Empty-manager edge coverage | ✅ Done |
| `3d358a0` | Exact post-conditions for the prior evidence gaps | ✅ Done |

No formal `tasks.md` exists. These commits are the completed execution units.

## Spec-Anchored Acceptance Criteria

| AC | Spec-defined outcome | `file:line` + assertion | Result |
| --- | --- | --- | --- |
| AC1 | Manager shows checked when globally visible and unchecked after hiding is saved and the manager is reopened. | `tests/ui-prototype.spec.cjs:1213` - `assert.equal(await globalToggle.isChecked(), true)`; `tests/ui-prototype.spec.cjs:1223` - reopened toggle `isChecked()` equals `false`. | ✅ PASS |
| AC2 | Saving unchecked persists the key and removes the field from both independent-test records and their add selector. | `tests/ui-prototype.spec.cjs:1218` - hidden keys equal `[schema.key]`; `tests/ui-prototype.spec.cjs:1229` - field count `0` in the two-record loop; `tests/ui-prototype.spec.cjs:1230` - option count `0`. | ✅ PASS |
| AC3 | Global hiding preserves every value and exact `visibleCustomFieldKeys`, including after saving while hidden. | `tests/ui-prototype.spec.cjs:1219` and `tests/ui-prototype.spec.cjs:1220` compare complete arrays; `tests/ui-prototype.spec.cjs:1235` and `tests/ui-prototype.spec.cjs:1236` repeat both exact comparisons after save. | ✅ PASS |
| AC4 | Re-showing clears the global list, restores only the individually visible record, and leaves the individually hidden field absent but selectable. | `tests/ui-prototype.spec.cjs:1242` - list `[]`; `tests/ui-prototype.spec.cjs:1246` - value equals `valuesBefore[0]`; `tests/ui-prototype.spec.cjs:1251` - count `0`; `tests/ui-prototype.spec.cjs:1252` - option count `1`. | ✅ PASS |
| AC5 | Individual hiding preserves value, affects only the target, leaves global settings unchanged, and leaves another record visible. | `tests/ui-prototype.spec.cjs:1341` - value `CTR-900`; `tests/ui-prototype.spec.cjs:1342` - target key absent; `tests/ui-prototype.spec.cjs:1343` - global list `[]`; `tests/ui-prototype.spec.cjs:1346` - non-target key present; `tests/ui-prototype.spec.cjs:1349` - non-target rendered count `1`. | ✅ PASS |
| AC6 | Missing legacy `hiddenCustomFieldKeys` normalizes to `[]` without changing records. | `tests/ui-prototype.spec.cjs:104` - legacy name remains `Lead legado preservado`; `tests/ui-prototype.spec.cjs:109` - hidden keys `[]`. | ✅ PASS |

**Acceptance status**: ✅ 6/6 matched; 0 spec-precision gaps.

## Edge Cases

| Edge case | Evidence | Result |
| --- | --- | --- |
| No custom fields shows the exact empty message. | `tests/ui-prototype.spec.cjs:1111` - exact message count equals `1`. | ✅ PASS |
| All globally hidden fields hide the custom tab; an available field keeps it usable. | `tests/ui-prototype.spec.cjs:1231` - tab hidden `true`; `tests/ui-prototype.spec.cjs:1246` - restored value accessible; `tests/ui-prototype.spec.cjs:1252` - individually hidden option count `1`. | ✅ PASS |
| Non-Administrator direct open is rejected and configuration remains exactly unchanged. | `tests/ui-prototype.spec.cjs:1184` snapshots full settings; `tests/ui-prototype.spec.cjs:1188` - direct open `false`; `tests/ui-prototype.spec.cjs:1189` - dialog closed; `tests/ui-prototype.spec.cjs:1190` - post-attempt JSON equals snapshot. | ✅ PASS |

**Edge-case status**: ✅ 3/3 matched.

## Required Gates on the Real Tree

| Gate | Result |
| --- | --- |
| Bundled Node: `node.exe tests/ui-prototype.spec.cjs` | ✅ Exit 0: 53 passed, 0 failed, 0 skipped |
| Python 3.12: `python.exe scripts/verify_demo.py` | ✅ Exit 0: 17 passed, 0 failed |
| `docker compose exec -T crm python app/server.py --self-test` | ✅ Exit 0: `server self-test: ok` |
| TLC `validate_spec.py global-custom-field-visibility --root D:\Develop_CRM_Project` | ✅ Exit 0: 0 errors, 0 warnings |
| `git diff --check e18bb89..3d358a0` | ✅ Exit 0, no output |

UI case count: 52 at `e18bb89`, 53 at `3d358a0`, delta +1. No skips, deleted cases, or weakened feature assertions.

## Discrimination Sensor

Both mutations ran only in disposable file-copy scratches on isolated localhost ports. Real code, tests, Compose state, and volumes were not mutated.

| Mutation | Scratch change | Observed failure | Result |
| --- | --- | --- | --- |
| M1 | `app/static/index.html:1482`: `moduleAvailableCustomFields` ignored `hiddenCustomFieldKeys`. Port 18081. | Completed 52 passed, 1 failed. `tests/ui-prototype.spec.cjs:1229` expected `0`, actual `1`. | ✅ KILLED |
| M2 | `app/static/index.html:1667`: `saveEntity` assigned only `customValues.keys()`. Port 18082. | `FIELDVIS-01` failed at `tests/ui-prototype.spec.cjs:1236`: exact visibility arrays differed. Runner stopped after conclusive kill. | ✅ KILLED |

**Sensor depth**: lightweight, 2 targeted mutations. **Result**: ✅ 2/2 killed, 0 survived.

**Isolation proof**:

- Before: `?? .specs/features/global-custom-field-visibility/validation.md`.
- Scratch servers stopped; scratch directories and temporary worktree metadata removed.
- After cleanup: `?? .specs/features/global-custom-field-visibility/validation.md`.
- Before/after equality: ✅ exact. The preexisting untracked report was handled consistently and is the only authorized real-tree write.

## Code Quality

| Check | Result |
| --- | --- |
| Minimal, surgical diff; no unrelated refactor or scope expansion | ✅ |
| Existing HTML/JavaScript patterns retained | ✅ |
| Payload values and state conjunctions asserted exactly | ✅ |
| All 6 ACs and 3 edges directly mapped; no unclaimed in-scope tests | ✅ |
| TLC `references/validate.md` and `references/coding-principles.md` followed | ✅ |

## Traceability and Lessons

`FIELDVIS-01`, `FIELDVIS-02`, and `FIELDVIS-03` are verified by this report. `spec.md` remains unchanged because this verifier may replace only `validation.md`.

This is a clean PASS: no failed or uncovered AC, surviving mutant, spec-precision gap, gate failure, or `SPEC_DEVIATION`. No new lesson is recorded. Existing L-007, L-008, and L-009 from the prior FAIL remain unchanged.

## Summary

**Overall**: ✅ Ready

**Spec-anchored check**: 6/6 ACs matched; 0 spec-precision gaps.

**Edge cases**: 3/3 matched.

**Gates**: UI 53/53; compose 17/17; self-test, spec validation, and diff check passed.

**Sensor**: 2/2 killed; isolation preserved.

**Ranked gaps**: none.
