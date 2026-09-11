# Production Contact Company Profile Validation

**Date**: 2026-09-11
**Spec**: `.specs/features/production-contact-company-profile/spec.md`
**Diff range**: `2ae8d5c..426115c`
**Verifier**: independent sub-agent (author != verifier)
**Verdict**: PASS

---

## Task Completion

| Scope | Status | Notes |
| --- | --- | --- |
| Inline execution | PASS | The feature has no `tasks.md`; all seven requirements are marked Implemented in `.specs/features/production-contact-company-profile/spec.md:61`. |

## Spec-Anchored Acceptance Criteria

| Requirement | Spec-defined outcome | `file:line` + assertion/evidence | Result |
| --- | --- | --- | --- |
| PCCP-01 | While the workspace is ready, the status strip is hidden in every screen. | `tests/ui-prototype.spec.cjs:2082` iterates the application destinations and `tests/ui-prototype.spec.cjs:2084` asserts `isVisible() === false`; `app/static/index.html:852` applies the ready-state rule to the shared strip. | PASS |
| PCCP-02 | The document title is exactly `Smart CRM`, and the lateral `Ambiente local` notice is absent. | `tests/ui-prototype.spec.cjs:2085` asserts zero exact `Ambiente local` matches, `tests/ui-prototype.spec.cjs:2086` rejects demonstration/local copy, and `tests/ui-prototype.spec.cjs:2088` asserts the exact title; implementation at `app/static/index.html:7` and absence after the navigation at `app/static/index.html:375`. | PASS |
| PCCP-03 | For an empty or unavailable database, the status strip remains visible with the corresponding guidance. | The empty-workspace path is exercised from `tests/ui-prototype.spec.cjs:257` through the read-only/bootstrap assertions at `tests/ui-prototype.spec.cjs:265`; its guidance is set at `app/static/index.html:972`. The unavailable path directly asserts visibility and exact guidance at `tests/ui-prototype.spec.cjs:2093` and `tests/ui-prototype.spec.cjs:2094`; degraded rendering is selected at `app/static/index.html:982`. | PASS |
| PCCP-04 | Opening a Contact linked to a registered Company shows that Company's name, segment, city, and phone. | `tests/ui-prototype.spec.cjs:657` opens the Contact; `tests/ui-prototype.spec.cjs:663`, `tests/ui-prototype.spec.cjs:664`, `tests/ui-prototype.spec.cjs:665`, and `tests/ui-prototype.spec.cjs:666` assert `Arkos Estética`, `Médico e Hospitalar`, `São Paulo / SP`, and `(11) 3456-7788`; rendering is at `app/static/index.html:1854`. | PASS |
| PCCP-05 | A Contact whose Company name has no matching registration shows that name and `Cadastro não localizado`. | `tests/ui-prototype.spec.cjs:670` injects `Empresa sem cadastro`; `tests/ui-prototype.spec.cjs:677` and `tests/ui-prototype.spec.cjs:678` assert both exact outcomes; fallback rendering is at `app/static/index.html:1850`. | PASS |
| PCCP-06 | A Contact without a Company shows `Nenhuma empresa vinculada`. | `tests/ui-prototype.spec.cjs:682` removes the Company and `tests/ui-prototype.spec.cjs:689` asserts the exact empty-state text; rendering is at `app/static/index.html:1845`. | PASS |
| PCCP-07 | Company matching ignores case and surrounding whitespace. | `tests/ui-prototype.spec.cjs:653` supplies `  arkos estética  `, while `tests/ui-prototype.spec.cjs:663` through `tests/ui-prototype.spec.cjs:666` assert the canonical Company's four values; normalization and lookup are implemented at `app/static/index.html:1477` and `app/static/index.html:1481`. | PASS |

**Status**: 7/7 acceptance criteria match the spec-defined outcomes; 0 spec-precision gaps.

## Discrimination Sensor

| Mutation | File:line | Behavior-level fault | Gate result | Killed? |
| --- | --- | --- | --- | --- |
| 1 | `app/static/index.html:852` | Replaced ready-only hiding with `workspaceStatus.hidden = false`, leaving the strip visible in ready state. | `tests/ui-prototype.spec.cjs:2084` failed; 68 passed, 1 failed. | PASS - killed |
| 2 | `app/static/index.html:1849` | Replaced normalized `relatedRecord` lookup with exact string equality. | `tests/ui-prototype.spec.cjs:663` failed for `  arkos estética  `; 68 passed, 1 failed. | PASS - killed |
| 3 | `app/static/index.html:1846` | Changed `Nenhuma empresa vinculada` to `Sem empresa vinculada`. | `tests/ui-prototype.spec.cjs:689` failed; 68 passed, 1 failed. | PASS - killed |

**Sensor depth**: lightweight, three targeted mutations in a detached temporary worktree served on a separate local port.

**Result**: 3/3 killed - PASS.

**Isolation evidence**: the real-tree baseline and post-cleanup `git status --porcelain` were identical:

```text
?? .specs/features/crm-mvp/tasks.md
?? RUNBOOK_DEPLOY_WINDOWS_SERVER_2016.md
```

No real implementation or test file was modified by the sensor. The temporary server was stopped and the scratch worktree was removed.

## Edge Cases

- [x] Case-only and surrounding-whitespace differences resolve the registered Company (`tests/ui-prototype.spec.cjs:653`, asserted at `tests/ui-prototype.spec.cjs:663`).

## Gate Check

- **Gate command**: `$env:SMART_CRM_TEST_URL='http://127.0.0.1:8080/'; node tests/ui-prototype.spec.cjs`
- **Result**: 69 passed, 0 failed, 0 skipped (exit code 0).
- **Test count before feature (`2ae8d5c`)**: 68.
- **Test count after feature (`426115c`)**: 69.
- **Delta**: +1 regression scenario.
- **Assertion integrity**: the prior demonstration-banner assertion was replaced by stricter ready-state absence, exact production title, forbidden-copy, and unavailable-state assertions; no in-scope assertion was weakened.

## Code Quality

| Principle | Status | Evidence |
| --- | --- | --- |
| Minimum code / no speculative abstraction | PASS | One shared summary renderer is invoked from the existing drawer flow at `app/static/index.html:1819` and implemented at `app/static/index.html:1837`. |
| Surgical changes / no scope creep | PASS | Diff surface is limited to the feature spec, `app/static/index.html`, and `tests/ui-prototype.spec.cjs`. Copy changes remove the requested demonstration/local presentation. |
| Matches existing patterns | PASS | Uses the existing `relatedRecord` and `escapeHTML` patterns; normalized lookup is centralized at `app/static/index.html:1477`. |
| Spec-anchored assertions | PASS | Exact title, exact fallback texts, and all four registered-company fields are asserted at `tests/ui-prototype.spec.cjs:651` through `tests/ui-prototype.spec.cjs:690`. |
| Per-layer coverage | PASS | This is a single-file browser UI feature; the full browser regression gate covers ready, degraded, linked, unmatched, empty, and normalized-name outcomes. |
| Every new test is claimed | PASS | The two PCCP scenarios map only to PCCP-01 through PCCP-07. |
| Documented guidelines | PASS | No feature-specific quality guideline was present; strong project defaults and the mandatory verifier protocol were applied. |

## Interactive UAT

Not performed. The feature is small and its observable UI outcomes are fully deterministic in the browser regression gate; interactive UAT is reserved for complex user-facing behavior.

## Summary

**Overall**: PASS - ready for completion.

- **Spec-anchored check**: 7/7 ACs matched, 0 precision gaps.
- **Gate**: 69 passed, 0 failed, 0 skipped.
- **Sensor**: 3/3 mutants killed.
- **Ranked gaps**: none.
- **Lessons**: none recorded because this is a clean PASS with no grounded validation signal.
