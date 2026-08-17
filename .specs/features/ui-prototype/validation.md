# Validation: UI Prototype — PASS ✅

**Date**: 2026-08-17
**Spec**: `.specs/features/ui-prototype/spec.md`
**Diff range**: `5462aba..HEAD` (`28a0cd1`)
**Verifier**: independent sub-agent (author ≠ verifier)
**Re-verification**: fix→re-verify iteration 1

The remediation is ready. The mandatory Build gate passes, all 16 acceptance criteria have spec-matching executable evidence, and both required behavior mutations are killed.

## Task Completion

| Task | Status | Verification |
| --- | --- | --- |
| T1 | ✅ Done | Health/static server implementation remains covered by exact HTTP assertions. |
| T2 | ✅ Done | Interactive UI outcomes are now covered by browser regression tests. |
| T3 | ✅ Done | The Compose verifier builds the image successfully. |
| T4 | ✅ Done | Compose starts the service and the localhost HTTP probes pass. |
| T5 | ✅ Done | The documented default URL and demo limitation markers match the runtime. |
| T6 | ✅ Done | The checked-in Playwright toolchain launches Chrome headless. |
| T7 | ✅ Done | All 15 browser cases pass, including the Gestor boundary. |
| T8 | ✅ Done | The checked-in Compose verifier reports 7 passed checks. |

## Spec-Anchored Acceptance Criteria

| Criterion | Spec-defined outcome | `file:line` + assertion evidence | Result |
| --- | --- | --- | --- |
| DEMO-01 | Compose exposes the root document on `localhost:8080`. | `scripts/verify_demo.py:15` defaults the port to 8080; `scripts/verify_demo.py:44`-`scripts/verify_demo.py:46` require config/build/start success; `scripts/verify_demo.py:54` asserts HTTP 200 and `scripts/verify_demo.py:56` asserts the Smart CRM marker. | ✅ PASS |
| DEMO-02 | The running service returns the exact healthy response without a database or external service. | `scripts/verify_demo.py:49` asserts HTTP 200 and `scripts/verify_demo.py:51` asserts `{"status":"ok","service":"smart-crm-demo"}`; `compose.yaml:3` declares the sole service. | ✅ PASS |
| DEMO-03 | A fresh browser seeds fictitious records for every included data module. | `tests/ui-prototype.spec.cjs:74`-`tests/ui-prototype.spec.cjs:79` assert non-empty Leads, Contatos, Empresas, Negócios, and Notificações in a fresh browser context. | ✅ PASS |
| DEMO-04 | The sidebar provides Dashboard/Visão geral, Leads, Contatos, Empresas, Negócios, and Notificações. | `tests/ui-prototype.spec.cjs:83`-`tests/ui-prototype.spec.cjs:90` assert six destinations and the heading reached by each navigation action. | ✅ PASS |
| DEMO-05 | Search and stage filtering update visible records without leaving the page. | `tests/ui-prototype.spec.cjs:97`-`tests/ui-prototype.spec.cjs:105` assert row-count/content changes for search and filter, while `tests/ui-prototype.spec.cjs:101` asserts the URL is unchanged. | ✅ PASS |
| DEMO-06 | Create, edit, and delete update the Lead list and related count. | `tests/ui-prototype.spec.cjs:108`-`tests/ui-prototype.spec.cjs:122` assert the count delta, edited name, deletion, and restored count. | ✅ PASS |
| DEMO-07 | Reload restores browser-local mutations. | `tests/ui-prototype.spec.cjs:126`-`tests/ui-prototype.spec.cjs:130` create a Lead, reload, and assert it in both the rendered list and persisted state. | ✅ PASS |
| DEMO-08 | Restore replaces mutations with the original fictitious state. | `tests/ui-prototype.spec.cjs:134`-`tests/ui-prototype.spec.cjs:141` mutate the state, restore it, and assert deep equality with the original seed. | ✅ PASS |
| DEMO-09 | Lead stages are exactly Em contato, Lead descartado, and Lead convertido, without “Nome”. | `tests/ui-prototype.spec.cjs:146`-`tests/ui-prototype.spec.cjs:148` assert the exact ordered stage set and absence of “Nome”. | ✅ PASS |
| DEMO-10 | Converting a Lead closes it as converted and creates an Em Contato Negócio. | `tests/ui-prototype.spec.cjs:153`-`tests/ui-prototype.spec.cjs:163` assert the source Lead state plus the new Negócio stage, responsible, assistants, and team. | ✅ PASS |
| DEMO-11 | The Negócio pipeline exposes exactly the nine approved stages. | `tests/ui-prototype.spec.cjs:168`-`tests/ui-prototype.spec.cjs:171` assert exact ordered membership, count nine, and absence of “Nome”. | ✅ PASS |
| DEMO-12 | Entering Faturando assigns a Faturamento member and creates notifications. | `tests/ui-prototype.spec.cjs:180`-`tests/ui-prototype.spec.cjs:186` assert stage, `u-billing`, team, and both exact notification payloads. | ✅ PASS |
| DEMO-13 | Quote inputs calculate quantity × unit price − discount and support optional PDF. | `tests/ui-prototype.spec.cjs:193`-`tests/ui-prototype.spec.cjs:214` assert the displayed/calculated total, a no-PDF quote, and a PDF filename payload. | ✅ PASS |
| DEMO-14 | Profile changes enforce administrator, team-manager, responsible-seller, and assistant visibility. | `tests/ui-prototype.spec.cjs:218`-`tests/ui-prototype.spec.cjs:234` assert exact role counts and the off-team record's exclusion for Gestor and inclusion for Administrador. | ✅ PASS |
| DEMO-15 | The fictitious/local-data warning stays visible. | `tests/ui-prototype.spec.cjs:238`-`tests/ui-prototype.spec.cjs:242` assert banner visibility in all six destinations. | ✅ PASS |
| DEMO-16 | Reduced width preserves usable navigation and the main Lead action. | `tests/ui-prototype.spec.cjs:246`-`tests/ui-prototype.spec.cjs:252` set 390×844, open the mobile menu, navigate, and assert “Novo Lead” remains visible. | ✅ PASS |

**Status**: ✅ 16/16 ACs match precise spec outcomes. No spec-precision gaps were found.

## Discrimination Sensor

The sensor used an external scratch copy of `app/` and `tests/`, served on ports 18081 and 18082. The checked-in test suite was not changed.

| Mutation | Scratch source | Description | Evidence of kill | Killed? |
| --- | --- | --- | --- | --- |
| 1 | `app/static/index.html:636` | Changed `stage === 'Faturando'` to an unreachable stage. | Browser gate exited 1; DEMO-12 failed at `tests/ui-prototype.spec.cjs:183` because `u-paula !== u-billing`. | ✅ Killed |
| 2 | `app/static/index.html:392` | Changed the Gestor team predicate to unconditional visibility. | Browser gate exited 1; DEMO-14 failed at `tests/ui-prototype.spec.cjs:220` because six visible deals did not equal five. | ✅ Killed |

**Sensor depth**: lightweight, 2 targeted behavior-level mutations
**Result**: 2/2 killed — PASS ✅
**Isolation evidence**: the scratch directory was deleted. Real-tree porcelain before and after was identical: `?? .pnpm-store/`.

## Code Quality

| Principle | Status |
| --- | --- |
| Minimum/cohesive implementation for the disposable prototype | ✅ |
| Surgical feature diff with no unrelated production behavior | ✅ |
| No unrequested external services or persistence | ✅ |
| Matches the approved dependency-free/local-only design | ✅ |
| Spec-anchored assertions match all 16 outcomes | ✅ |
| Payload/conjunction rule covers conversion, Faturando, and quotes | ✅ |
| Every checked-in browser case maps to an AC or documented edge case | ✅ |
| No skipped or disabled tests | ✅ |
| Project guidance followed: `design.md`, `tasks.md`, and `coding-principles.md` | ✅ |

## Edge Cases

- [x] Corrupted local storage is replaced with the seed state: `tests/ui-prototype.spec.cjs:255`-`tests/ui-prototype.spec.cjs:260`.
- [x] Restore after mutation reproduces the original state exactly: `tests/ui-prototype.spec.cjs:133`-`tests/ui-prototype.spec.cjs:141`.
- [x] Quote creation covers both absent and present PDF metadata: `tests/ui-prototype.spec.cjs:189`-`tests/ui-prototype.spec.cjs:214`.
- [x] Off-team Faturamento data is excluded from the Gestor view: `tests/ui-prototype.spec.cjs:217`-`tests/ui-prototype.spec.cjs:234`.

## Gate Check

- **Gate commands**: bundled Python `scripts/verify_demo.py`, then bundled pnpm `test`.
- **Compose/runtime result**: 7 passed, 0 failed.
- **Browser result**: 15 passed, 0 failed, 0 skipped.
- **Combined result**: 22 passed, 0 failed, 0 skipped.
- **Runtime**: `http://localhost:8080`; exact health payload and root markers passed.
- **Test count before feature**: 0 checked-in feature tests at `5462aba`.
- **Test count after feature**: 15 browser cases plus the 7-check Compose acceptance gate.
- **Delta**: +22 executable gate checks.

## Interactive UAT

Not performed in this automated independent pass. The 15-case browser suite covers the specified observable behaviors at desktop and 390×844; subjective visual review remains optional product UAT and does not block these acceptance criteria.

## Requirement Traceability Result

| Requirement | Previous status | Verifier status |
| --- | --- | --- |
| DEMO-01 | Implemented — pending re-verification | ✅ Verified |
| DEMO-02 | Verified | ✅ Verified |
| DEMO-03 | Implemented — pending re-verification | ✅ Verified |
| DEMO-04 | Implemented — pending re-verification | ✅ Verified |
| DEMO-05 | Implemented — pending re-verification | ✅ Verified |
| DEMO-06 | Implemented — pending re-verification | ✅ Verified |
| DEMO-07 | Implemented — pending re-verification | ✅ Verified |
| DEMO-08 | Implemented — pending re-verification | ✅ Verified |
| DEMO-09 | Implemented — pending re-verification | ✅ Verified |
| DEMO-10 | Implemented — pending re-verification | ✅ Verified |
| DEMO-11 | Implemented — pending re-verification | ✅ Verified |
| DEMO-12 | Implemented — pending re-verification | ✅ Verified |
| DEMO-13 | Implemented — pending re-verification | ✅ Verified |
| DEMO-14 | Implemented — pending re-verification | ✅ Verified |
| DEMO-15 | Implemented — pending re-verification | ✅ Verified |
| DEMO-16 | Implemented — pending re-verification | ✅ Verified |

This table records the verifier outcome only. `spec.md` was not modified because the verifier's authorized write scope is limited to this report.

## Summary

**Overall**: ✅ Ready

**Spec-anchored check**: 16/16 ACs matched; 0 spec-precision gaps.
**Sensor**: 2/2 mutations killed.
**Gate**: 22 passed, 0 failed, 0 skipped.
**Issues found**: none.
**Lessons**: clean PASS; no new lesson recorded.
**Next step**: no verifier fix task remains.
