# Manual Windows PostgreSQL 11 Deployment Validation

**Verdict**: PASS
**Date**: 2026-09-03
**Spec**: `.specs/features/manual-windows-pg11-deployment/spec.md`
**Diff range**: `a9e44ee^..1968812`
**Artifact**: `dist/smart-crm-manual-pg11-19688125.zip`
**Verifier**: independent sub-agent (author != verifier)

---

## Spec-Anchored Acceptance Criteria

| Requirement | Spec-defined outcome | `file:line` + assertion | Result |
| --- | --- | --- | --- |
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

**Status**: 14/14 criteria match the spec-defined outcome. No spec-precision gap remains.

## Discrimination Sensor

The sensor ran in temporary worktree `.verify-manual-pg11-worktree` at `19688125`. The real tree was never mutated.

| Mutation | File:line | Description | Result |
| --- | --- | --- | --- |
| 1 | `scripts/build_manual_windows_pg11_bundle.py:115` | Disabled manifest mismatch rejection. | KILLED: 1 failed, 13 passed |
| 2 | `deploy/manual-windows-pg11/deployment-policy.ps1:18` | Bypassed the missing IPv4 listener guard. | KILLED: 2 failed, 12 passed |
| 3 | `deploy/manual-windows-pg11/deployment-policy.ps1:67` | Changed health acceptance from AND to OR. | KILLED: 2 failed, 12 passed |

**Sensor depth**: lightweight, three targeted behavior mutations.
**Result**: 3/3 killed. PASS.
**Isolation**: real-tree porcelain before and after cleanup was identical: `?? .specs/features/crm-mvp/tasks.md` and `?? .specs/features/manual-windows-pg11-deployment/validation.md`. Scratch removed.

## Edge Cases

- PostgreSQL missing, IPv6-only, or publicly bound: PASS at `tests/backend/test_manual_windows_pg11_outcomes.py:109` through line 111.
- Existing role/database: PASS at `scripts/verify_manual_windows_pg11_deployment.py:54`.
- Alembic failure before publication: PASS at `tests/backend/test_manual_windows_pg11_outcomes.py:156` through line 161.

## Gate Check

- Dedicated gate: 14 passed, 0 failed, 0 skipped in 6.06s.
- Feature tests: 0 before `a9e44ee^`; 14 after `1968812`; delta +14.
- Python compile gate: PASS.
- PowerShell parser gate: PASS for every deployment `.ps1`.
- Bundle verifier: PASS, 14/14 requirements.
- Artifact: 46 entries, 20 wheels; binary wheels are `cp311-cp311-win_amd64` and the rest are universal.
- External SHA-256: PASS, `ec8c0aeb34de17df08ff259ccda63db79cdcf5ee5a0b2fefaa4c0b53abb757bc`.
- `git diff --check a9e44ee^..1968812`: PASS.

## Code Quality

| Principle | Status |
| --- | --- |
| Minimum code, surgical diff, no scope creep | PASS |
| Matches project patterns | PASS |
| Spec-anchored outcomes | PASS: 14/14 |
| Non-shallow coverage | PASS: 3/3 mutants killed |
| Every test maps to a requirement or independent test | PASS |
| Guidelines | `tlc-spec-driven/references/coding-principles.md` applied |

## Requirement Traceability Result

MPG-01 through MPG-14: Implementing -> Verified.

## Summary

**Overall**: PASS, ready for the destination-server UAT required by the spec.

**Spec-anchored check**: 14/14.
**Sensor**: 3/3 killed.
**Gate**: 14 passed.

The offline artifact, integrity controls, runtime/database safety policies, migration/publication ordering, and local health gate are verified. Production readiness still depends on the explicitly out-of-scope UAT on the destination Windows Server.
