# Banco PostgreSQL local para testes - Validation

## Validation: PASS

**Verdict**: PASS ✅
**Date**: 2026-08-24
**Spec**: `.specs/features/postgres-test-database/spec.md`
**Diff range**: `a347b3a..cda35fc`
**Implementation commits**: `6931c94`, `2a10ade`, `cda35fc`
**Verifier**: independent sub-agent (author != verifier)

---

## Task Completion

No formal `tasks.md` exists for this medium-sized feature. The implementation and both test-strengthening commits are complete.

| Task | Status | Notes |
| --- | --- | --- |
| Implicit implementation | ✅ Done | PostgreSQL service and acceptance gate landed in `6931c94`. |
| Override coverage correction | ✅ Done | Exact NAME, USER, PASSWORD and PORT assertions landed in `2a10ade`. |
| Default publication correction | ✅ Done | Exact default published port assertion landed in `cda35fc`. |
| Independent verification | ✅ Done | All gates passed and both required mutants were killed. |

---

## Spec-Anchored Acceptance Criteria

| Criterion | Spec-defined outcome | `file:line` + assertion expression | Result |
| --- | --- | --- | --- |
| AC1: Compose starts `crm` and `postgres` healthy | Both services are running and healthy after `docker compose up -d`. | `scripts/verify_demo.py:122` calls `compose("up", "-d")`; `scripts/verify_demo.py:136-139` obtains both services and asserts `State == "running"` and `Health == "healthy"`. The gate passed 17/17. | ✅ PASS |
| AC2: PostgreSQL exposes `smartcrm_test` to `smartcrm` | SQL identity is exactly `smartcrm_test\|smartcrm` under defaults. | `scripts/verify_demo.py:141-142` queries `current_database()` and `current_user`, then asserts `identity == f"{DB_NAME}\|{DB_USER}"`; defaults are fixed at `scripts/verify_demo.py:17-18`. | ✅ PASS |
| AC3: default publication is only `127.0.0.1:5432` | The published binding must conjunctively have `host_ip == 127.0.0.1`, container `target == 5432` and host `published == 5432`. | `scripts/verify_demo.py:108` asserts all three exact values in one predicate. Mutant M2 changed only the published default to `55433` and this assertion failed with host `127.0.0.1`, target `5432`, published `55433`. | ✅ PASS |
| AC4: NAME, USER, PASSWORD and PORT override defaults | One rendered override payload must equal NAME `smartcrm_override_test`, USER `smartcrm_override_user`, PASSWORD `smartcrm_override_password` and published PORT `55432`; the port remains loopback-only. | `scripts/verify_demo.py:111-114` supplies all four distinct values together. `scripts/verify_demo.py:117-119` asserts exact DB, user and password values. `scripts/verify_demo.py:120` asserts exact `host_ip == "127.0.0.1"` and `published == "55432"`. M1 independently killed a broken NAME mapping. | ✅ PASS |
| AC5: exactly one probe row survives PostgreSQL restart | The probe count is exactly `1` before and after restarting only `postgres`. | `scripts/verify_demo.py:143-144` creates/inserts idempotently and asserts the final pre-restart line `== "1"`; `scripts/verify_demo.py:145` restarts only postgres; `scripts/verify_demo.py:147-148` re-queries and asserts `persisted == "1"`. | ✅ PASS |
| AC6: CRM remains functional in `localStorage` without PostgreSQL | A browser reload preserves one created lead both visibly and in stored browser state; the full CRM regression remains green. | `tests/ui-prototype.spec.cjs:18` reads `localStorage`; `tests/ui-prototype.spec.cjs:732-737` creates `Lead Persistente`, reloads, asserts one visible result and asserts the lead in stored state. The Node gate passed 52/52. | ✅ PASS |

**Status**: ✅ 6/6 ACs match precise spec-defined outcomes with `file:line` evidence.
**Spec precision**: 0 gaps.

---

## Payload and Conjunction Rule

AC3 passes the conjunction rule at `scripts/verify_demo.py:108`: host address, container target and published host port are asserted together. AC4 passes it at `scripts/verify_demo.py:111-120`: all four override inputs are supplied in one environment and all four rendered outcomes are compared by exact value. The password is asserted by payload value, not merely by occurrence.

---

## Edge Cases

| Edge case | Evidence | Result |
| --- | --- | --- |
| Existing volume remains idempotent with exactly one probe row | `scripts/verify_demo.py:143` uses `INSERT ... ON CONFLICT DO NOTHING`; `scripts/verify_demo.py:144` and `scripts/verify_demo.py:148` each assert the count `== "1"`. The 17/17 gate passed against the existing named volume. | ✅ PASS |
| PostgreSQL timeout at 30 seconds fails with diagnostics | `scripts/verify_demo.py:63` defines the exact 30-second default; `scripts/verify_demo.py:73` raises `AssertionError(f"PostgreSQL não ficou pronto em {seconds}s: {last_error}")`. A deterministic in-memory probe forced `pg_isready` failure and asserted both the `30s` prefix and command detail; it passed. | ✅ PASS |
| `SMART_CRM_DB_PORT=55432` renders only `127.0.0.1:55432` | `scripts/verify_demo.py:114` supplies `55432`; `scripts/verify_demo.py:120` conjunctively asserts `host_ip == "127.0.0.1"` and `published == "55432"`. | ✅ PASS |

---

## Gate Check

| Gate | Result |
| --- | --- |
| Bundled Python `scripts/verify_demo.py` | ✅ `compose acceptance: 17 passed, 0 failed` |
| Bundled Node `tests/ui-prototype.spec.cjs` | ✅ `UI regression: 52 passed, 0 failed` |
| `docker compose exec -T crm python app/server.py --self-test` | ✅ `server self-test: ok` |
| TLC `validate_spec.py .specs/features/postgres-test-database/spec.md` | ✅ 0 errors, 0 warnings |
| `git diff --check a347b3a..cda35fc` | ✅ exit 0, no findings |

- Counted runtime checks after feature: 69 (17 Compose acceptance + 52 UI).
- Failed runtime checks: 0.
- Skipped runtime checks: 0.
- The initial host command through the Windows Store `python` alias did not start the Python gate. The recorded 17/17 result came from the bundled Codex Python runtime.

---

## Discrimination Sensor

The sensor used detached temporary worktrees inside the workspace. It changed only scratch `compose.yaml` files. It did not use `git stash`, did not run `docker compose down -v` and did not mutate the real tree.

| Mutation | Mutated location | Behavior fault | Result |
| --- | --- | --- | --- |
| M1 | `compose.yaml:21` | Replaced the `SMART_CRM_DB_NAME` mapping with constant `smartcrm_test`, so the NAME override was ignored. | ✅ Killed at `scripts/verify_demo.py:117`; exit 1 showed the exact expected-versus-rendered payload mismatch before build/up. |
| M2 | `compose.yaml:25` | Changed the default published host port from `5432` to `55433` while retaining host `127.0.0.1` and target `5432`. | ✅ Killed at `scripts/verify_demo.py:108`; exit 1 showed published `55433` before build/up. |

- **Sensor depth**: lightweight, 2 required targeted configuration mutations.
- **Result**: ✅ 2/2 killed, 0 survived.
- **Baseline raw porcelain**: `?? .specs/features/postgres-test-database/validation.md`.
- **Baseline normalized porcelain**: empty after consistently excluding the pre-existing untracked validation report.
- **After cleanup raw porcelain**: the same single untracked validation report.
- **After cleanup normalized porcelain**: empty, identical to baseline.
- **Scratch cleanup**: both temporary worktrees were removed; `git worktree list` contains only the real worktree.
- One setup trial for M1 was excluded: its patch did not apply, so the unchanged gate ran and passed. Both counted sensor runs had their scratch diffs explicitly confirmed before execution.

---

## Code Quality

| Principle | Status | Evidence |
| --- | --- | --- |
| Minimum code and surgical changes | ✅ | The diff is limited to the feature spec/context, Compose wiring, verifier and user documentation. |
| No scope creep | ✅ | `README.md:81` keeps the CRM on `localStorage`; no application-to-database integration was added. |
| Matches project patterns | ✅ | `scripts/verify_demo.py` extends the existing deployment verifier directly. |
| Spec-anchored outcomes | ✅ | Every AC has an exact asserted value/state and `file:line` evidence. |
| Payload/conjunction rule | ✅ | AC3 and AC4 assert every required field together and by exact value. |
| Per-layer coverage | ✅ | Compose configuration, live PostgreSQL behavior, persistence and UI regression are all covered at their relevant layer. |
| Tests are claimed | ✅ | In-scope checks map to an AC, listed edge case or existing CRM regression. |
| Documented guidelines | ✅ | `.specs/features/postgres-test-database/spec.md` and TLC `references/coding-principles.md` were applied. |

---

## Requirement Traceability

The verifier did not edit `spec.md` because this assignment permits only `validation.md` writes.

| Requirement | Spec status | Independently validated status |
| --- | --- | --- |
| PGTEST-01 | Verified | ✅ Verified: AC1, AC2 and AC3 pass. |
| PGTEST-02 | Verified | ✅ Verified: AC5 and persistence edge pass. |
| PGTEST-03 | Verified | ✅ Verified: AC4 and custom-port edge pass. |

---

## Lessons

Clean PASS: no failed AC, surviving mutant, spec-precision gap, gate failure or `SPEC_DEVIATION`. No lesson was recorded.

---

## Summary

**Overall**: ✅ Ready
**Spec-anchored check**: 6/6 ACs matched; 0 spec-precision gaps.
**Edges**: 3/3 handled with evidence.
**Gate**: 69 runtime checks passed, 0 failed, 0 skipped; self-test and structural gates passed.
**Sensor**: 2 mutations, 2 killed, 0 survived.
**Next step**: none. The feature satisfies the spec and is ready.
