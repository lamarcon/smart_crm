# Manual Windows PostgreSQL 11 Deployment Validation

**Verdict**: PASS
**Date**: 2026-09-03
**Spec**: `.specs/features/manual-windows-pg11-deployment/spec.md`
**Diff range**: `b1c2979..357113f`
**Artifact**: `dist/smart-crm-manual-pg11-357113f7.zip`
**Verifier**: independent sub-agent (author != verifier)

---

## Spec-Anchored Acceptance Criteria

| Requirement | Spec-defined outcome | `file:line` + assertion | Result |
| --- | --- | --- | --- |
| Deployment path goal | The offline bundle is extracted and operated from `C:\brbots\apps\smart-crm`. | `.specs/features/manual-windows-pg11-deployment/spec.md:9` defines the exact path. `tests/backend/test_manual_windows_pg11_outcomes.py:164` defines the expected default, line 172 asserts it in all three server scripts, line 173 asserts it in the manual, and line 174 rejects the former path. | PASS |
| MPG-01 | Commit-versioned ZIP and matching SHA-256. | `tests/backend/test_manual_windows_pg11_outcomes.py:53` asserts the ZIP name; lines 54-55 assert digest filename and exact content. | PASS |
| MPG-02 | Complete runtime payload and compatible Windows CPython 3.11 x64 wheels. | `tests/backend/test_manual_windows_pg11_outcomes.py:58` through line 64 assert all payload classes and a `cp311-cp311-win_amd64` wheel. | PASS |
| MPG-03 | No Git/spec/venv/tests/caches/TLS keys or secret `server.env` in ZIP. | `tests/backend/test_manual_windows_pg11_deployment.py:49` through line 50 and `tests/backend/test_manual_windows_pg11_outcomes.py:65` assert exclusions; `scripts/verify_manual_windows_pg11_deployment.py:66` rejects secret/key entries. | PASS |
| MPG-04 | Missing, modified, or extra files exit non-zero before install. | `tests/backend/test_manual_windows_pg11_deployment.py:61` and line 65 assert modified/extra rejection; `tests/backend/test_manual_windows_pg11_outcomes.py:85` asserts missing-file non-zero; line 86 asserts ordering before venv. | PASS |
| MPG-05 | Only CPython 3.11 x64 passes, before venv mutation. | `tests/backend/test_manual_windows_pg11_outcomes.py:97` through line 99 assert valid CPython and reject PyPy, 3.12, and 32-bit; `scripts/verify_manual_windows_pg11_deployment.py:46` asserts pre-venv ordering. | PASS |
| MPG-06 | Offline pip uses wheelhouse and `--no-index`. | `tests/backend/test_manual_windows_pg11_deployment.py:96` expects MPG-06 after removing `--no-index`; `deploy/manual-windows-pg11/install-offline.ps1:55` uses `--no-index --find-links`. | PASS |
| MPG-07 | Exact database config and external 64-hex secret. | `tests/backend/test_manual_windows_pg11_outcomes.py:121` through line 131 assert the complete environment and `C:\ProgramData\SmartCRM\server.env` location; `deploy/manual-windows-pg11/deployment-policy.ps1:29` enforces 64 hex. | PASS |
| MPG-08 | No PostgreSQL service stop/restart/remove/reconfiguration. | `tests/backend/test_manual_windows_pg11_deployment.py:106` rejects injected `Restart-Service`; `scripts/verify_manual_windows_pg11_deployment.py:49` rejects mutation/reconfiguration commands. | PASS |
| MPG-09 | Exact Alembic upgrade and no manual `CREATE TABLE`. | `tests/backend/test_manual_windows_pg11_outcomes.py:138` asserts `["-m","alembic","upgrade","head"]`; `scripts/verify_manual_windows_pg11_deployment.py:50` asserts integration and absence of `CREATE TABLE`. | PASS |
| MPG-10 | Uvicorn only on `127.0.0.1:8080`. | `tests/backend/test_manual_windows_pg11_outcomes.py:139` asserts the complete Uvicorn vector; `deploy/manual-windows-pg11/start-smart-crm.ps1:68` invokes it. | PASS |
| MPG-11 | Only exact health `{"status":"ok","database":"ok"}` permits publication. | `tests/backend/test_manual_windows_pg11_outcomes.py:148` asserts all four truth-table cases; lines 159-161 assert pre-publication ordering and no Apache mutation. | PASS |
| MPG-12 | Exact IPv4 listener `127.0.0.1:5432` required. | `tests/backend/test_manual_windows_pg11_outcomes.py:108` through line 111 accept IPv4 loopback and reject none, IPv6-only, and public binding; `deploy/manual-windows-pg11/install-offline.ps1:33` invokes the policy before venv. | PASS |
| MPG-13 | Existing role/database ownership is checked without recreation/deletion. | `tests/backend/test_manual_windows_pg11_deployment.py:88` reaches `scripts/verify_manual_windows_pg11_deployment.py:54`, which requires `\du smartcrm`, `\l smartcrm`, and the do-not-recreate/delete guidance. | PASS |
| MPG-14 | Alembic failure blocks publication and leaves Apache unchanged. | `tests/backend/test_manual_windows_pg11_outcomes.py:156` through line 161 assert non-zero with the blocking message, pre-publication ordering, and no Apache mutation/restart. | PASS |

**Status**: The affected deployment-path goal and 14/14 numbered criteria match the spec-defined outcomes. No spec-precision gap remains.

## Discrimination Sensor

The sensor ran in a temporary detached worktree at `357113f`. The real tree was never mutated.

| Mutation | File:line | Description | Result |
| --- | --- | --- | --- |
| 1 | `deploy/manual-windows-pg11/start-smart-crm.ps1:3` | Changed the default from `C:\brbots\apps\smart-crm` back to `C:\Apps\smart-crm`. | KILLED: `tests/backend/test_manual_windows_pg11_outcomes.py:172` failed, 1 targeted test failed as expected |


**Sensor depth**: lightweight, one targeted behavior mutation for the changed path.
**Result**: 1/1 killed. PASS.
**Isolation**: real-tree porcelain before and after cleanup was identical: `?? .specs/features/crm-mvp/tasks.md`. Scratch removed.

## Edge Cases

- PostgreSQL missing, IPv6-only, or publicly bound: PASS at `tests/backend/test_manual_windows_pg11_outcomes.py:109` through line 111.
- Existing role/database: PASS at `scripts/verify_manual_windows_pg11_deployment.py:54`.
- Alembic failure before publication: PASS at `tests/backend/test_manual_windows_pg11_outcomes.py:156` through line 161.

## Gate Check

- Dedicated gate: 15 passed, 0 failed, 0 skipped in 5.51s.
- Environmental retry: the first run used the inaccessible global pytest temp directory and produced 9 passes plus 6 setup errors; the isolated `--basetemp` rerun passed all 15 tests.
- Feature tests: 14 at `b1c2979`; 15 at `357113f`; delta +1.
- PowerShell parser gate: PASS for all 6 deployment `.ps1` files.
- Bundle verifier: PASS, 14/14 requirements.
- Artifact: 46 entries, 20 wheels; binary wheels are `cp311-cp311-win_amd64` and the rest are universal.
- Bundle path check: PASS. The manual contains the new path 3 times, each of the 3 default-bearing scripts contains it once, and none contains `C:\Apps\smart-crm`.
- External SHA-256: PASS, `99298d68f96deca121eb9a47280433104018894b2f8f07d7e4bb7242f46395ec`.
- `git diff --check b1c2979..357113f`: PASS.

## Code Quality

| Principle | Status |
| --- | --- |
| Minimum code, surgical diff, no scope creep | PASS |
| Matches project patterns | PASS |
| Spec-anchored outcomes | PASS: affected path goal plus 14/14 numbered criteria |
| Non-shallow coverage | PASS: 1/1 path mutant killed |
| Every test maps to a requirement or independent test | PASS |
| Guidelines | `tlc-spec-driven/references/coding-principles.md` applied |

## Requirement Traceability Result

MPG-01 through MPG-14: Implementing -> Verified.

## Summary

**Overall**: PASS, ready for the destination-server UAT required by the spec.

**Spec-anchored check**: affected path goal plus 14/14 numbered criteria.
**Sensor**: 1/1 killed.
**Gate**: 15 passed.

The source defaults, manual, specification context, and packaged artifact consistently use `C:\brbots\apps\smart-crm`; the former `C:\Apps\smart-crm` default is rejected by the dedicated test. The offline artifact, integrity controls, runtime/database safety policies, migration/publication ordering, and local health gate remain verified. Production readiness still depends on the explicitly out-of-scope UAT on the destination Windows Server.
