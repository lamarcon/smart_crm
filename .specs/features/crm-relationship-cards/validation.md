# CRM Relationship Cards Validation

**Verdict**: PASS
**Date**: 2026-09-10
**Spec**: `.specs/features/crm-relationship-cards/spec.md`
**Diff range**: `b169506^..b060c50`
**Verifier**: independent sub-agent (author != verifier)

## Task Completion

No `tasks.md` exists for this medium feature. The committed implementation and test fix are present through `b060c50`. All eight numbered requirements and both specified edge cases have exact assertion evidence.

## Spec-Anchored Acceptance Criteria

| Requirement | Spec-defined outcome | `file:line` + assertion | Result |
| --- | --- | --- | --- |
| CRREL-01 | `Novo Empresa` opens the Empresa form with Empresa fields | `tests/ui-prototype.spec.cjs:565` clicks `Novo Empresa`; `tests/ui-prototype.spec.cjs:567` asserts heading `Novo Empresa`; `tests/ui-prototype.spec.cjs:568-572` locates and fills the Empresa fields | PASS |
| CRREL-02 | Saving persists an `E-*` Empresa, lists it, and retains it after rehydration | `tests/ui-prototype.spec.cjs:576` asserts `/^E-\d+$/`; `tests/ui-prototype.spec.cjs:577-580` asserts the exact payload and one visible row; `tests/ui-prototype.spec.cjs:582-586` rehydrates and asserts the persisted name and row | PASS |
| CRREL-03 | Deal list shows Empresa and Contato names plus Empresa city/phone and Contato email/phone | `tests/ui-prototype.spec.cjs:592-595` asserts `Arkos Estética`, `São Paulo / SP · (11) 3456-7788`, `Ana Berclay`, and `ana@arkos.com.br · (11) 3456-7788` | PASS |
| CRREL-04 | Deal Kanban card shows Empresa and Contato names | `tests/ui-prototype.spec.cjs:601-604` switches to Kanban and asserts `Arkos Estética` and `Ana Berclay` in card `N-16312` | PASS |
| CRREL-05 | Contact list shows its Empresa name | `tests/ui-prototype.spec.cjs:608-610` opens Contatos and asserts `Arkos Estética` in Ana Berclay's row | PASS |
| CRREL-06 | Company list shows associated-contact count and names | `tests/ui-prototype.spec.cjs:619-623` asserts `2 contatos`, `Ana Berclay`, and `Contato Normalizado` | PASS |
| CRREL-07 | Missing Deal references retain their supplied names and show `Cadastro não localizado` | `tests/ui-prototype.spec.cjs:597-599` asserts both `Biocare Farmacêutica` and `João Vilela` followed by `Cadastro não localizado` | PASS |
| CRREL-08 | Company without contacts shows zero and `Nenhum contato` | `tests/ui-prototype.spec.cjs:625-632` creates the company and asserts `0 contatos` plus `Nenhum contato` | PASS |

**Status**: 8/8 acceptance criteria match the spec-defined outcomes. No spec-precision gaps were found.

## Edge Cases

| Edge case | `file:line` + assertion | Result |
| --- | --- | --- |
| Relationship lookup ignores case and outer whitespace | `tests/ui-prototype.spec.cjs:615` supplies `  arkos estética  `; `tests/ui-prototype.spec.cjs:621-623` asserts the normalized association count and both names | PASS |
| Empty Empresa or Contato renders `Não informado` | `tests/ui-prototype.spec.cjs:639-640` supplies both empty values; `tests/ui-prototype.spec.cjs:647-648` separately asserts `Empresa Não informado` and `Contato Não informado` | PASS |

## Gate Check

- **Gate command**: `C:\Users\luizf\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe tests/ui-prototype.spec.cjs`
- **Result**: 68 passed, 0 failed, 0 skipped
- **Test count before feature**: 65
- **Test count after feature**: 68
- **Delta**: +3 feature tests
- **Integrity**: the feature diff adds 88 test lines and deletes none; assertions were not weakened
- **Diff hygiene**: `git diff --check b169506^..b060c50` passed

## Discrimination Sensor

The sensor used a detached scratch worktree at `b060c50` and a scratch-only server at `http://127.0.0.1:8091/`. No real implementation file was mutated.

| Mutation | Scratch source | Outcome |
| --- | --- | --- |
| M1: remove only the Deal Empresa empty-name `Não informado` fallback | `app/static/index.html:1486` | KILLED at `tests/ui-prototype.spec.cjs:647`; isolated full gate reported 67 passed, 1 failed |
| M2: change the Empresas create-button entity from `company` to invalid `companies` | `app/static/index.html:1524` | KILLED at `tests/ui-prototype.spec.cjs:567`; dialog heading timed out |
| M3: remove outer-whitespace trimming from relationship normalization | `app/static/index.html:1467` | KILLED at `tests/ui-prototype.spec.cjs:621`; expected `2 contatos`, received `1 contato` |

**Sensor depth**: lightweight, 3 behavior-level mutations
**Result**: 3/3 killed. PASS.

The scratch server was stopped and the detached worktree was removed. Real-worktree porcelain after cleanup exactly matched the pre-sensor baseline:

```text
 M .specs/LESSONS.md
 M .specs/lessons.json
?? .specs/features/crm-mvp/tasks.md
?? .specs/features/crm-relationship-cards/validation.md
?? RUNBOOK_DEPLOY_WINDOWS_SERVER_2016.md
```

## Code Quality

| Check | Result |
| --- | --- |
| No features beyond the requested behavior | PASS |
| No unnecessary abstraction or configurability | PASS |
| Surgical diff limited to feature spec/context, implementation, and tests | PASS |
| Matches existing single-file rendering and Node browser-test patterns | PASS |
| Tests map to all eight acceptance criteria and both listed edge cases | PASS |
| Spec-anchored asserted values match every defined outcome | PASS |
| Browser coverage exercises happy, missing-reference, normalization, empty-value, persistence, list, and Kanban paths | PASS |
| Every added test maps to a requirement or listed edge case | PASS |
| Documented guidelines | `tlc-spec-driven/references/coding-principles.md`; no repository-specific guideline was found in the feature diff | PASS |

## Interactive UAT

Not performed. This medium feature's observable UI behavior is covered by the passing browser gate and the independent mutation sensor.

## Requirement Traceability

| Requirement | Spec status | Independent result |
| --- | --- | --- |
| CRREL-01 through CRREL-08 | Verified | PASS |
| Edge: case and outer whitespace | listed edge case | PASS |
| Edge: empty Empresa or Contato | listed edge case | PASS |

The verifier did not edit `spec.md`; this report records the independent result.

## Ranked Gaps

None.

## Summary

**Overall**: READY. All 8 acceptance criteria and both edge cases have exact assertion evidence. The full gate is green, all 3 targeted mutants were killed, and sensor isolation was preserved.
