# UI Prototype Validation — FAIL ❌

**Date**: 2026-08-17  
**Spec**: `.specs/features/ui-prototype/spec.md`  
**Diff range**: `5462aba..HEAD` (`7a5df6b`)  
**Verifier**: independent sub-agent (author ≠ verifier)

The implementation is not ready to verify. The mandatory Build gate passes, but the feature has no persisted browser-behavior tests for 15 of 16 acceptance criteria. A deliberate break in the Faturando automation survives the declared Full gate.

---

## Task Completion

| Task | Recorded status | Verification result |
| --- | --- | --- |
| T1 | ✅ Complete | Server self-test passes. |
| T2 | ✅ Complete | ❌ UI behavior is not covered by executable assertions; a DEMO-12 mutant survives. |
| T3 | ✅ Complete | Image builds and runs as the non-root `smartcrm` user. |
| T4 | ✅ Complete | Compose config, startup, health, and root HTTP probes pass. |
| T5 | ✅ Complete | README commands and limitations match the running service. |

---

## Spec-Anchored Acceptance Criteria

Evidence-or-zero is applied literally: implementation code or an ad hoc browser observation does not replace a checked-in `file:line` assertion. The browser smoke run found no console warnings/errors and confirmed the current seeded UI at desktop and 390×844, but those observations are not regression tests.

| Criterion | Spec-defined outcome | `file:line` + assertion evidence | Result |
| --- | --- | --- | --- |
| DEMO-01 | `docker compose up --build` exposes `/` on `localhost:8080`. | Port wiring exists at `compose.yaml:10`; the verifier observed HTTP 200 from `/`. No checked-in assertion starts Compose and asserts host port/root availability. | ❌ GAP |
| DEMO-02 | Running service returns a healthy response without PostgreSQL or an external service. | `app/server.py:95` — `assert response.status == HTTPStatus.OK`; `app/server.py:96` — `assert health == {"status": "ok", "service": "smart-crm-demo"}`. `compose.yaml:3` declares the sole service. | ✅ PASS |
| DEMO-03 | First open seeds enough fictitious data for every included module. | Seed data exists at `app/static/index.html:322`, but there is no assertion for first-open state or per-module record sufficiency. | ❌ GAP |
| DEMO-04 | Sidebar exposes Dashboard, Leads, Contatos, Empresas, Negócios, and Notificações. | Markup exists at `app/static/index.html:236`; browser smoke observed all six destinations. No test asserts the six labels and navigation outcomes. | ❌ GAP |
| DEMO-05 | Search/filter changes visible records without page reload. | Filtering is implemented at `app/static/index.html:462`, `app/static/index.html:484`, and `app/static/index.html:708`. No test asserts before/after records and unchanged navigation state. | ❌ GAP |
| DEMO-06 | Create/edit/delete updates the list and related indicators. | Mutation/render paths exist at `app/static/index.html:572`, `app/static/index.html:597`, and `app/static/index.html:419`. No test asserts all three CRUD operations and indicator deltas. | ❌ GAP |
| DEMO-07 | Reload restores previously manipulated local browser state. | `localStorage` load/save exists at `app/static/index.html:370` and `app/static/index.html:380`. No test mutates, reloads, and asserts restored values. | ❌ GAP |
| DEMO-08 | Restore replaces local state with the original fictitious data. | Reset exists at `app/static/index.html:680`. No test asserts the restored state equals the original seed after mutation. | ❌ GAP |
| DEMO-09 | Lead stages are exactly Em contato, Lead descartado, and Lead convertido, with no “Nome” stage. | The stage array is at `app/static/index.html:307`; browser smoke observed the seeded Lead UI. No assertion checks the exact set and forbidden stage. | ❌ GAP |
| DEMO-10 | Converting a Lead closes it as converted and creates a new Negócio in Em Contato. | Conjunction is implemented at `app/static/index.html:604` through `app/static/index.html:615`. No test asserts both the Lead state and new Negócio payload. | ❌ GAP |
| DEMO-11 | Negócios expose the nine approved functional stages. | The nine values are at `app/static/index.html:308`; browser smoke observed all nine pipeline labels. No assertion checks exact membership/order/count. | ❌ GAP |
| DEMO-12 | Entering Faturando assigns a Faturamento member and creates a notification. | Implementation is at `app/static/index.html:626` through `app/static/index.html:641`. No assertion checks both responsibility and notification payload. Mutation `stage === 'Faturando'` → `stage === 'Nunca'` survived the Full gate. | ❌ GAP |
| DEMO-13 | Quote inputs recalculate `quantity × unit price − discount` and accept optional PDF selection. | Calculation/save paths are at `app/static/index.html:654` through `app/static/index.html:674`. No test asserts the computed value or with/without-PDF payload. | ❌ GAP |
| DEMO-14 | Switching profiles filters Leads/Negócios by responsibility, team, or Assistant participation. | Seller/Assistant filtering is implemented at `app/static/index.html:387`; browser smoke observed different seeded counts. The Gestor branch returns all records unconditionally at `app/static/index.html:389`, contradicting the Vendas CMS team rule at `.specs/features/ui-prototype/design.md:66`; no off-team assertion detects it. | ❌ FAIL |
| DEMO-15 | A persistent notice states that data are fictitious and local. | Banner markup exists at `app/static/index.html:249`; browser smoke observed it. No test asserts visibility across every view/state. | ❌ GAP |
| DEMO-16 | Reduced width keeps navigation and primary actions usable. | Responsive rules are at `app/static/index.html:197`; browser smoke at 390×844 observed the menu, opened navigation, and visible “Novo Lead” action. No checked-in viewport assertion protects the behavior. | ❌ GAP |

**Status**: ❌ 1/16 ACs have spec-matching executable assertion evidence. No spec-precision gaps were found; the failures are implementation/coverage gaps.

---

## Discrimination Sensor

The sensor ran in detached worktree `7a5df6b` under an isolated temporary directory. The real worktree was never mutated.

| Mutation | File:line | Description | Relevant gate | Result |
| --- | --- | --- | --- | --- |
| 1 | `app/server.py:38` | Changed health status from `ok` to `degraded`. | Python self-test | ✅ Killed by `app/server.py:96`. |
| 2 | `app/static/index.html:631` | Changed the Faturando automation condition to an unreachable stage. | Full gate: Python self-test + extracted JavaScript syntax check | ❌ Survived; both checks exited zero. |

**Sensor depth**: lightweight, 2 targeted behavior-level mutations  
**Result**: 1/2 killed — FAIL ❌  
**Isolation evidence**: real-tree porcelain before and after was identical: `?? app/__pycache__/server.cpython-312.pyc`. The temporary worktree was removed, and `git worktree list` again contained only the main worktree.

---

## Runtime Browser Smoke

| Check | Result | Details |
| --- | --- | --- |
| Initial page | ✅ | Title loaded from `http://localhost:8080/`; no console warnings/errors. |
| Navigation | ✅ | Six destinations observed. |
| Deal pipeline | ✅ | Nine stage labels observed. |
| Demo warning | ✅ | Persistent banner visible on the loaded UI. |
| Role seed behavior | ⚠️ | Visible Lead rows: Admin 5, Gestor 5, Paula 2, Vitor 3, Assistente 2. No off-team seed distinguishes Admin from Gestor. |
| Mobile 390×844 | ✅ smoke only | Mobile menu and primary “Novo Lead” action visible; sidebar navigation usable after opening. |

These are verifier observations, not persisted assertions, so they do not raise an AC from GAP to PASS.

---

## Code Quality

| Principle | Status |
| --- | --- |
| Minimum/cohesive code for a disposable prototype | ✅ |
| Surgical diff limited to feature artifacts, server, UI, container, and README | ✅ |
| No unrelated scope creep found in `5462aba..HEAD` | ✅ |
| Matches the approved dependency-free/local-only design | ✅ |
| Spec-anchored outcome assertions | ❌ 15 ACs lack checked-in assertion evidence. |
| Per-layer coverage expectation | ❌ Browser state/domain behaviors have no executable outcome tests. |
| Payload/conjunction rule | ❌ Conversion, Faturando, and quote payloads are not asserted. |
| Every existing self-test maps to an AC or task Done-when | ✅ Health, root delivery, and traversal map to DEMO-01/02 and T1. |
| Documented project guidelines | ✅ `.specs/features/ui-prototype/tasks.md` and design were followed structurally; the promised browser coverage was not persisted. |

---

## Edge Cases

- [ ] Corrupted `localStorage` falls back to seed data (`app/static/index.html:370`), but no test asserts recovery.
- [ ] Restore after local mutation is implemented (`app/static/index.html:680`), but no test asserts exact replacement.
- [ ] Non-PDF selection is rejected (`app/static/index.html:665`), but no test asserts the rejection and unchanged quote state.
- [ ] Faturando responsibility and both notification paths (`app/static/index.html:631`) lack outcome assertions.
- [ ] Gestor visibility after a deal transfers to the Faturamento team is incorrect/unprotected (`app/static/index.html:389`).

---

## Gate Check

- **Declared Full gate**: containerized `python app/server.py --self-test`, followed by inline JavaScript extraction and containerized `node --check -`.
- **Mandatory Build gate**: `docker compose config`; `docker compose build`; `docker compose up -d`; HTTP probes for `/health` and `/`.
- **Result**: 9 checks passed, 0 failed, 0 skipped (3 Python self-test scenarios, 1 JavaScript syntax check, 5 Build/runtime checks).
- **Container evidence**: service `smart-crm-demo-crm-1` was `healthy`; `/health` returned `{"status":"ok","service":"smart-crm-demo"}`; `/` returned HTTP 200.
- **Host-tool note**: host `python` and `node` were not on PATH, so the same declared checks ran inside official Python/Node containers. This does not affect the Docker-only user startup path.
- **Test count before feature**: 0 executable test cases found at `5462aba`.
- **Test count after feature**: 3 server self-test scenarios; no persisted UI behavior tests.
- **Delta**: +3 server scenarios, +0 UI behavior tests.
- **Skipped tests**: none.
- **Failures**: none in the declared gate; the surviving sensor mutant proves the gate is insufficient for DEMO-03 through DEMO-16.

---

## Ranked Gaps and Fix Plans

### 1. Browser behavior has no discriminating regression suite — Blocker

- **Affected criteria**: DEMO-03 through DEMO-16.
- **Root cause**: the Full gate checks only server behavior and JavaScript syntax. `tasks.md` names “structural + browser smoke” but no checked-in browser tests or equivalent DOM-state assertions exist.
- **Fix task**: add a deterministic browser test layer that maps one-to-one to every UI AC. Assert exact list contents, CRUD/indicator deltas, reload persistence, reset equality, exact pipeline stages, conversion payload, Faturando assignment+notification, quote totals/PDF metadata, all profile visibility branches, banner persistence, and mobile navigation/actions.
- **Verify**: all UI tests pass; re-run the Faturando mutant and at least one persistence/role mutant, and confirm each is killed.

### 2. Gestor visibility ignores team scope — Major

- **Affected criterion**: DEMO-14.
- **Root cause**: `app/static/index.html:389` treats Administrador and Gestor identically, while `.specs/features/ui-prototype/design.md:66` limits Gestor to Vendas CMS.
- **Fix task**: model/derive record team and restrict Gestor to Vendas CMS. Cover a Faturamento-owned deal and an off-team record; keep Administrador unrestricted.
- **Verify**: an exact role-visibility test proves Admin sees all, Gestor sees Vendas CMS only, sellers see responsible/assistant records, and Assistant sees participating records only.

### 3. Compose accessibility is verified only ad hoc — Major

- **Affected criterion**: DEMO-01.
- **Root cause**: no checked-in gate script asserts the Compose-published host port and root response.
- **Fix task**: add a repeatable build-gate script/test that starts Compose, waits for healthy state, asserts the exact health payload, and asserts HTTP 200 plus the expected app marker at `localhost:${SMART_CRM_PORT:-8080}/`.
- **Verify**: the script exits non-zero for a wrong port, missing root document, unhealthy container, or wrong health payload.

### 4. Current browser smoke is not reviewable evidence — Major

- **Affected criteria**: DEMO-03–DEMO-11 and DEMO-13–DEMO-16.
- **Root cause**: results were recorded as task prose rather than executable assertions with stable expected values.
- **Fix task**: persist the tests and include their command in the Full gate; report assertion-level `file:line` evidence for each AC on re-verification.
- **Verify**: every criterion has a checked-in `file:line` assertion, and no criterion relies only on implementation lines or a manual note.

---

## Requirement Traceability Result

| Requirement | Previous status | Verifier status |
| --- | --- | --- |
| DEMO-01 | Complete | ❌ Needs Fix |
| DEMO-02 | Complete | ✅ Verified |
| DEMO-03 | Complete | ❌ Needs Fix |
| DEMO-04 | Complete | ❌ Needs Fix |
| DEMO-05 | Complete | ❌ Needs Fix |
| DEMO-06 | Complete | ❌ Needs Fix |
| DEMO-07 | Complete | ❌ Needs Fix |
| DEMO-08 | Complete | ❌ Needs Fix |
| DEMO-09 | Complete | ❌ Needs Fix |
| DEMO-10 | Complete | ❌ Needs Fix |
| DEMO-11 | Complete | ❌ Needs Fix |
| DEMO-12 | Complete | ❌ Needs Fix |
| DEMO-13 | Complete | ❌ Needs Fix |
| DEMO-14 | Complete | ❌ Needs Fix |
| DEMO-15 | Complete | ❌ Needs Fix |
| DEMO-16 | Complete | ❌ Needs Fix |

This table records the verifier outcome only. `spec.md` was not modified because the verifier's authorized write scope is limited to this report.

---

## Summary

**Overall**: FAIL ❌ — Not Ready

**Spec-anchored check**: 1/16 ACs matched by executable assertion evidence; 0 spec-precision gaps.  
**Sensor**: 1/2 mutations killed; the DEMO-12 mutant survived.  
**Gate**: 9 checks passed, 0 failed, 0 skipped.  
**What works now**: Docker/Compose packaging, health endpoint, static delivery, current seeded navigation, nine visible deal stages, persistent warning, and mobile smoke behavior.  
**Issues found**: UI outcomes are not regression-tested, Gestor team visibility is incorrect/unprotected, and the declared Full gate cannot detect broken Faturando automation.  
**Lessons**: not written because the verifier was explicitly restricted to modifying only `validation.md`; the orchestrator should distill the surviving-mutant lesson after routing fix tasks.  
**Next step**: implement the ranked fix tasks, then dispatch a fresh independent verifier and rerun the sensor.
