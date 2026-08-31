# Server Staging Deployment Revalidation

**Date**: 2026-08-31
**Spec**: `.specs/features/server-staging-deployment/spec.md`
**Diff range**: `23a5ab1..e913843`
**Verifier**: independent sub-agent (author != verifier)
**Result**: FAIL

---

## Revalidation Verdict

The static deployment package is ready for controlled Linux-server UAT. The
previous secret-path and diff-hygiene gaps are fixed. The overall verdict remains
FAIL because SRV-05 requires a real running PostgreSQL/migration/CRM stack and an
exact `/health` response; the local Docker daemon is unavailable and no server
runtime evidence was supplied.

## Spec-Anchored Acceptance Criteria

| Requirement | Spec-defined outcome | Evidence | Status |
| --- | --- | --- | --- |
| SRV-01 | A complete environment renders without a default database password. | `scripts/verify_server_config.py:40` validates a 64-character hexadecimal password; `scripts/verify_server_config.py:87` renders the Compose model. `--example` returned 10 passed / 0 failed and Compose config exited 0 with a disposable value. | PASS |
| SRV-02 | PostgreSQL has no host-published port. | `scripts/verify_server_config.py:58` asserts `not postgres.get("ports")`; the 10-check rendered-model gate passed. | PASS |
| SRV-03 | Alembic upgrades to head before the documented CRM start. | `scripts/verify_server_config.py:66` asserts the exact migration command; `deploy/server/RUNBOOK.md:87` through `deploy/server/RUNBOOK.md:98` order PostgreSQL, migration, then CRM. | PASS |
| SRV-04 | CRM binds to loopback by default. | `scripts/verify_server_config.py:61` through `scripts/verify_server_config.py:64` assert host IP `127.0.0.1` and target port 8000. | PASS |
| SRV-05 | Live loopback `/health` returns exactly `{"status":"ok","database":"ok"}` after migration. | `deploy/server/RUNBOOK.md:98` documents the request and `deploy/server/RUNBOOK.md:101` through `deploy/server/RUNBOOK.md:105` document the expected value, but no live response exists. Docker reported no server/daemon. Evidence-or-zero applies. | FAIL |
| SRV-06 | Missing or placeholder secret is rejected before start. | `compose.server.yaml:9` and `compose.server.yaml:25` require the password; `scripts/verify_server_config.py:42` through `scripts/verify_server_config.py:47` reject placeholder/invalid values. | PASS |
| SRV-07 | Update is fast-forward-only and preceded by backup. | `deploy/server/RUNBOOK.md:178` through `deploy/server/RUNBOOK.md:195` create the dump/SHA/hash; lines 210-214 require the backup before `git merge --ff-only`. | PASS |
| SRV-08 | Rollback returns to the recorded SHA without deleting the PostgreSQL volume. | `deploy/server/RUNBOOK.md:224` through `deploy/server/RUNBOOK.md:244` switch to `OLD_SHA`, rebuild only the CRM, preserve the volume and prohibit `down -v`. | PASS |
| SRV-09 | Public access requires HTTPS and Basic Auth. | `deploy/server/nginx-smart-crm.conf.example:12` through `deploy/server/nginx-smart-crm.conf.example:14` redirect HTTP; lines 18-26 enable TLS and Basic Auth; line 31 proxies to loopback. | PASS |

**Coverage**: 8/9 acceptance criteria evidenced; SRV-05 remains unverified.

## Corrective Changes Rechecked

| Check | Evidence | Status |
| --- | --- | --- |
| Canonical secret location | `deploy/server/README.md:9` through `deploy/server/README.md:25`, `deploy/server/RUNBOOK.md:41` through `deploy/server/RUNBOOK.md:64`, and `deploy/server/.env.server.example:1` use `/etc/smart-crm/server.env`. | PASS |
| Every operational Compose command has the external env file | Static assertion over `deploy/server/README.md` and `deploy/server/RUNBOOK.md` found zero operational `docker compose` commands lacking `--env-file /etc/smart-crm/server.env`. The informational `docker compose version` check is intentionally excluded. | PASS |
| Shell environment loading uses the external file | `deploy/server/RUNBOOK.md:111` and `deploy/server/RUNBOOK.md:183` use `. /etc/smart-crm/server.env`; the old `./.env.server` source pattern is absent from both tracked installation documents. | PASS |
| No manual table creation | `deploy/server/README.md:3` through `deploy/server/README.md:5` and `deploy/server/RUNBOOK.md:81` through `deploy/server/RUNBOOK.md:90` delegate schema creation to Alembic. | PASS |
| Diff hygiene | `git diff --check 23a5ab1..e913843` exited 0. | PASS |

## Gate Check

| Gate | Outcome |
| --- | --- |
| Bundled Python `scripts/verify_server_config.py --self-test` | PASS, exit 0 |
| Bundled Python `scripts/verify_server_config.py --example` | PASS, 10 passed / 0 failed |
| Bundled Python `-m compileall -q app scripts/verify_server_config.py` | PASS, exit 0 |
| Compose render with disposable 64-hex password | PASS, exit 0 |
| Operational Compose `--env-file` documentation assertion | PASS, zero offending commands |
| Legacy shell-source pattern assertion | PASS, zero matches |
| `git diff --check 23a5ab1..e913843` | PASS, exit 0 |
| Docker runtime availability | FAIL, client installed but daemon/server unavailable |

## Discrimination Sensor

`scripts/verify_server_config.py:132` through
`scripts/verify_server_config.py:148` mutate in-memory copies of the valid model.
The re-run killed all three behavior-level faults:

1. PostgreSQL port 5432 published: killed.
2. CRM binding changed to `0.0.0.0`: killed.
3. Migration changed from `upgrade head` to `current`: killed.

**Sensor outcome**: 3/3 killed. The real-tree porcelain before and after the
gate remained unchanged.

## Remaining Gap and Fix Task

### Server runtime UAT

- **Cause**: no Docker daemon/server was available during independent validation.
- **Action**: after explicit authorization for the target Linux server, clone the
  recorded SHA, create `/etc/smart-crm/server.env`, run PostgreSQL, run
  `alembic upgrade head`, start CRM and capture `docker compose ps`,
  `alembic current`, the table list and loopback `/health` output.
- **Done when**: `/health` is exactly `{"status":"ok","database":"ok"}`,
  PostgreSQL exposes no host port, CRM exposes only loopback, and the deployed
  SHA is recorded.
- **Priority**: Blocker for a PASS verdict, but not a static packaging defect.

## Workspace Hygiene Note

`deploy/server/INSTALL.md` is a pre-existing untracked draft that still contains
the obsolete repository-root `.env.server` procedure. It is outside the verified
commit range and will not move through Git unless explicitly added. It must remain
untracked or be removed before any broad staging command such as `git add .`.

## Summary

**Static package**: PASS.

**Feature verdict**: FAIL pending SRV-05 runtime evidence.

The package can now be pushed and installed for private staging after explicit
authorization. It must not be declared fully verified or opened for real client
data until the server runtime UAT succeeds.
