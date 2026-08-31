# Server Staging Deployment Validation

**Date**: 2026-08-31
**Spec**: `.specs/features/server-staging-deployment/spec.md`
**Diff range**: `23a5ab1..a12d0cb`
**Verifier**: independent sub-agent (author != verifier)
**Verdict**: FAIL

---

## Task Completion

| Task | Status | Notes |
| --- | --- | --- |
| Specification and deployment context | Done | Requirements SRV-01..SRV-09 are defined. |
| Private Compose stack | Done | PostgreSQL, migration and CRM services render successfully. |
| Deterministic configuration verifier | Done | Positive, rejection and mutation checks pass. |
| Git/Nginx operational runbook | Partial | Procedures exist, but secret-location instructions conflict. |
| Independent server runtime verification | Blocked | Docker daemon is unavailable and no Linux server UAT evidence was supplied. |

## Spec-Anchored Acceptance Criteria

| Criterion | Spec-defined outcome | `file:line` and assertion evidence | Result |
| --- | --- | --- | --- |
| SRV-01 | A complete environment renders without a default database password. | `scripts/verify_server_config.py:40` validates exactly 64 hexadecimal characters; `scripts/verify_server_config.py:87` renders the Compose model; `--example` returned `server deployment config: 10 passed, 0 failed`; Compose config exited 0 with a disposable 64-character value. | PASS |
| SRV-02 | PostgreSQL has no host-published port. | `scripts/verify_server_config.py:58` asserts `not postgres.get("ports")`; the rendered model passed all 10 checks. | PASS |
| SRV-03 | The migration runs `alembic upgrade head` before the documented CRM start. | `scripts/verify_server_config.py:66` asserts the exact command; `deploy/server/README.md:39` through `deploy/server/README.md:41` orders PostgreSQL, migration, then CRM. | PASS |
| SRV-04 | CRM binds to `127.0.0.1` by default and targets container port 8000. | `scripts/verify_server_config.py:61` through `scripts/verify_server_config.py:64` assert the exact host IP and target port; the rendered model passed. | PASS |
| SRV-05 | Live loopback `/health` returns exactly `{"status":"ok","database":"ok"}` after migration. | `deploy/server/RUNBOOK.md:97` documents the request and `deploy/server/RUNBOOK.md:100` through `deploy/server/RUNBOOK.md:104` document the expected payload, but no live response was executed. `docker version` reported no Docker server/daemon. Evidence-or-zero therefore applies. | FAIL |
| SRV-06 | Missing or placeholder secret is rejected before container start. | `compose.server.yaml:9` and `compose.server.yaml:25` use required interpolation; `scripts/verify_server_config.py:42` through `scripts/verify_server_config.py:47` reject placeholders/invalid values. Missing-secret Compose config and placeholder-verifier checks both exited 1 as expected. | PASS |
| SRV-07 | Update is fast-forward-only and preceded by a database backup. | `deploy/server/RUNBOOK.md:177` through `deploy/server/RUNBOOK.md:194` create the dump/SHA/hash; `deploy/server/RUNBOOK.md:209` requires that backup before `git merge --ff-only` at `deploy/server/RUNBOOK.md:213`. | PASS |
| SRV-08 | Rollback returns the application to the recorded SHA without deleting the PostgreSQL volume. | `deploy/server/RUNBOOK.md:223` through `deploy/server/RUNBOOK.md:243` detach to `OLD_SHA`, rebuild only the CRM, preserve the volume and explicitly prohibit `down -v`. | PASS |
| SRV-09 | Public access is HTTPS plus shared Basic Auth. | `deploy/server/nginx-smart-crm.conf.example:12` through `deploy/server/nginx-smart-crm.conf.example:14` redirect HTTP; lines 18-26 enable TLS and Basic Auth; line 31 proxies only to loopback. | PASS |

**Status**: 8/9 acceptance criteria have evidence. SRV-05 has no runtime evidence.

## Discrimination Sensor

The sensor uses in-memory deep copies of the valid model, so it never mutates the real worktree.

| Mutation | File:line | Behavior-level fault | Result |
| --- | --- | --- | --- |
| 1 | `scripts/verify_server_config.py:133` through `scripts/verify_server_config.py:135` | Publish PostgreSQL port 5432. | Killed |
| 2 | `scripts/verify_server_config.py:136` through `scripts/verify_server_config.py:138` | Change CRM host binding to `0.0.0.0`. | Killed |
| 3 | `scripts/verify_server_config.py:139` through `scripts/verify_server_config.py:141` | Replace `alembic upgrade head` with `alembic current`. | Killed |

**Sensor depth**: lightweight, three highest-risk configuration mutations.

**Result**: 3/3 killed. `--self-test` exited 0 with `server config self-test: PASS`. Real-tree porcelain before and after remained the same four pre-existing untracked files outside this feature.

## Edge Cases

- PASS: placeholder and malformed database passwords are rejected by `scripts/verify_server_config.py:40` through `scripts/verify_server_config.py:48`.
- PASS: migration failure is an explicit stop condition before CRM startup in `deploy/server/RUNBOOK.md:92` through `deploy/server/RUNBOOK.md:95`.
- PASS: incompatible schema rollback requires the pre-migration backup and prohibits volume deletion at `deploy/server/RUNBOOK.md:243`.
- PASS: the no-Basic-Auth alternative is restricted to VPN/loopback in `deploy/server/RUNBOOK.md:152` through `deploy/server/RUNBOOK.md:158`.
- FAIL: `deploy/server/README.md:9` through `deploy/server/README.md:25` and `deploy/server/SECURITY.md:3` through `deploy/server/SECURITY.md:11` correctly require `/etc/smart-crm/server.env`, but `deploy/server/.env.server.example:1` and `deploy/server/RUNBOOK.md:41` through `deploy/server/RUNBOOK.md:69` still instruct creating `.env.server` inside the clone. `.gitignore:1` through `.gitignore:7` do not exclude that file. The canonical README warns about the replacement, but the contradictory standalone runbook remains a secret-commit hazard.

## Gate Check

| Gate | Result |
| --- | --- |
| Bundled Python `scripts/verify_server_config.py --self-test` | PASS, exit 0 |
| Bundled Python `scripts/verify_server_config.py --example` | PASS, 10 passed / 0 failed |
| Bundled Python `-m compileall -q app scripts/verify_server_config.py` | PASS, exit 0 |
| Compose config with disposable 64-hex value | PASS, exit 0 |
| Placeholder rejection | PASS, expected exit 1 |
| Missing-secret Compose rejection | PASS, expected exit 1 |
| Docker runtime availability | FAIL, Docker client is installed but the daemon/server is unavailable |
| `git diff --check 23a5ab1..a12d0cb` | FAIL, trailing whitespace/newline findings in `context.md`, `spec.md`, `compose.server.yaml`, the example environment and Nginx example |

No test-count regression was identified in the feature surface. The versioned verifier contributes one positive model contract with 10 assertions, three invalid-secret cases and three behavior-level mutants.

## Code Quality

| Principle | Status |
| --- | --- |
| Minimum/surgical scope | PASS |
| No unrelated implementation changes | PASS |
| Secure network defaults | PASS |
| Spec-anchored outcomes | FAIL: live SRV-05 outcome is unproven |
| Operational documentation consistency | FAIL: repository-root and `/etc` secret instructions conflict |
| Diff hygiene | FAIL: `git diff --check` is nonzero |
| Documented project guidelines | PASS: spec and TLC validation rules applied |

## Fix Plans

### Fix 1: Execute the server runtime UAT

- **Root cause**: the local Docker daemon is unavailable and the target Linux host was not accessed.
- **Fix task**: on the authorized Linux server, use `/etc/smart-crm/server.env`, start PostgreSQL, run the migration, start CRM, capture `docker compose ps`, `alembic current`, the table list and the exact loopback `/health` payload.
- **Done when**: the response is exactly `{"status":"ok","database":"ok"}`, PostgreSQL has no host port, CRM is loopback-only and the deployed SHA is recorded.
- **Priority**: Blocker for marking the deployment verified.

### Fix 2: Make secret handling unambiguous

- **Root cause**: the new canonical README corrected the secret location, but the example comment and full runbook still create an unignored secret inside the clone.
- **Fix task**: update every server command and comment to use `/etc/smart-crm/server.env`; alternatively also ignore `.env.server`, but keeping real secrets outside the clone is preferred. Add a deterministic assertion that no deployment document instructs creating the real secret in the repository.
- **Done when**: all procedures use one external path and the static safety assertion passes.
- **Priority**: Major.

### Fix 3: Clear the diff hygiene gate

- **Root cause**: Markdown hard-break whitespace and final blank lines are reported by `git diff --check`.
- **Fix task**: remove the reported whitespace without changing behavior.
- **Done when**: `git diff --check 23a5ab1..HEAD` exits 0.
- **Priority**: Minor.

## Requirement Traceability Update

| Requirement | Previous | Verification result |
| --- | --- | --- |
| SRV-01 | Implementing | Verified locally |
| SRV-02 | Implementing | Verified locally |
| SRV-03 | Implementing | Verified locally |
| SRV-04 | Implementing | Verified locally |
| SRV-05 | Implementing | Needs server runtime evidence |
| SRV-06 | Implementing | Verified locally |
| SRV-07 | Implementing | Verified by procedure inspection |
| SRV-08 | Implementing | Verified by procedure inspection |
| SRV-09 | Implementing | Verified by configuration inspection |

## Summary

**Overall**: NOT READY TO MARK VERIFIED.

The Git/Compose package is suitable for the next controlled staging step. It is not yet proven running, and the client should not receive real-data access. Complete the Linux-server runtime UAT, consolidate secret instructions and clear the diff gate before changing the feature verdict to PASS.
