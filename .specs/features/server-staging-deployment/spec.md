# Server Staging Deployment Specification

## Problem Statement

The CRM needs a reproducible path from the Git repository to the current server. The installation must start the existing application and PostgreSQL without exposing the database or the anonymous CRM API directly to the internet.

## Goals

- [ ] Install and update the CRM from Git with Docker Compose.
- [ ] Create the database schema through versioned Alembic migrations.
- [ ] Expose the current CRM only through a protected HTTPS reverse proxy.
- [ ] Document verification, backup, update and rollback commands.

## Out of Scope

| Feature | Reason |
| --- | --- |
| Productive per-user authentication and authorization | Tracked by `crm-mvp`; the current deployment receives only a shared perimeter password. |
| WordPress and Bitrix24 integrations | They are not implemented in the current application. |
| Automatic remote deployment | Push and server access require separate explicit authorization. |
| Using existing external PostgreSQL | The initial package uses a private PostgreSQL container to avoid host-network ambiguity. |

## Assumptions & Open Questions

| Assumption / decision | Chosen default | Rationale | Confirmed? |
| --- | --- | --- | --- |
| Server operating system | Linux with Docker Engine and Compose plugin | Matches the container runtime and manual Git workflow. | n |
| Source transport | GitHub `origin`, branch `main`, deployed by immutable commit SHA | The repository already has the configured remote and SHA rollback is deterministic. | y |
| PostgreSQL location | Private Compose service with named volume | Avoids publishing port 5432 and manual host `pg_hba.conf` changes. | n |
| Public entrypoint | Nginx HTTPS with Basic Auth, proxying to `127.0.0.1:8080` | Provides a temporary shared perimeter until real application login exists. | n |
| Data classification | Fictitious or staging data only | The application does not yet enforce per-user authorization. | y |
| Secret handling | Root-owned `.env.server` with mode 600, never committed | Keeps database credentials out of Git and Docker build context. | n |
| Remaining implicit dimensions | N/A for this packaging scope | Domain concurrency and state transitions stay unchanged; Compose restart and migration failure are covered. | n |

**Open questions:** none - unconfirmed infrastructure details are explicit assumptions that can be overridden on the server.

## User Stories

### P1: Install the CRM from Git ⭐ MVP

**User Story**: As the server administrator, I want to clone a commit and run documented commands so the current CRM becomes available without copying application files manually.

**Why P1**: A reproducible Git installation is required before staging can begin.

**Acceptance Criteria**:

1. [SRV-01] WHEN the administrator fills every required value in `.env.server` THEN the server Compose configuration SHALL render without a default database password.
2. [SRV-02] WHILE the server stack is running the PostgreSQL service SHALL have no host-published port.
3. [SRV-03] WHEN the administrator runs the migration service THEN Alembic SHALL upgrade the target database to the current head before the CRM service starts.
4. [SRV-04] WHILE the CRM service is running its host port SHALL bind to `127.0.0.1` by default.
5. [SRV-05] WHEN the administrator checks `/health` through loopback THEN the CRM SHALL return `{"status":"ok","database":"ok"}` after PostgreSQL is healthy and migrated.
6. [SRV-06] IF a required secret is absent THEN Docker Compose SHALL reject the configuration before starting a container.
7. [SRV-07] WHEN the administrator follows the documented update procedure THEN Git SHALL use fast-forward-only retrieval and the database SHALL be backed up before migration.
8. [SRV-08] WHEN the administrator follows the documented rollback procedure THEN the application SHALL return to a recorded commit without deleting the PostgreSQL volume.
9. [SRV-09] WHILE the current anonymous CRM API is deployed the public reverse proxy SHALL require HTTPS and a shared Basic Auth credential.

**Independent Test**: Render the Compose model using the example environment, assert network/secret/migration invariants, start the stack on a Linux Docker host, run migration, and compare the exact health payload.

## Edge Cases

- IF `.env.server` contains a placeholder database password THEN the verifier SHALL fail with a nonzero exit code.
- IF migration fails THEN the CRM SHALL not be started by the documented procedure.
- IF a new commit is incompatible THEN rollback SHALL reuse the existing named volume and restore from the pre-migration backup when schema rollback is required.
- IF Nginx Basic Auth is absent THEN the documentation SHALL state that the CRM must remain accessible only through VPN or loopback.

## Requirement Traceability

| Requirement ID | Story | Phase | Status |
| --- | --- | --- | --- |
| SRV-01 | P1: Git installation | Execute | Implementing |
| SRV-02 | P1: Git installation | Execute | Implementing |
| SRV-03 | P1: Git installation | Execute | Implementing |
| SRV-04 | P1: Git installation | Execute | Implementing |
| SRV-05 | P1: Git installation | Execute | Implementing |
| SRV-06 | P1: Git installation | Execute | Implementing |
| SRV-07 | P1: Git installation | Execute | Implementing |
| SRV-08 | P1: Git installation | Execute | Implementing |
| SRV-09 | P1: Git installation | Execute | Implementing |

**Coverage:** 9 requirements, 9 mapped to the four-step inline execution plan, 0 unmapped.

## Success Criteria

- [ ] A clean Linux server can clone one commit, create `.env.server`, migrate and start the CRM using only documented commands.
- [ ] PostgreSQL is unreachable from host/public ports and CRM listens only on loopback by default.
- [ ] Missing/placeholder secrets and unsafe bindings are rejected before deployment.
- [ ] Update and rollback preserve the database volume and include a pre-migration backup.

