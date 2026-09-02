# Windows Apache Deployment Specification

## Problem Statement

The Smart CRM must replace the discontinued application at
`sc2030.brbots.com` on the existing Windows server. The current Apache endpoint
uses an expired certificate and the Linux/Nginx deployment package does not
match this host.

## Goals

- [ ] Provide a reproducible native Windows installation from Git.
- [ ] Serve the CRM through the existing Apache HTTPS endpoint.
- [ ] Keep PostgreSQL, Uvicorn and all secrets unreachable from public ports.

## Out of Scope

| Feature | Reason |
| --- | --- |
| Remote server changes | Require separate authorization and server access. |
| PunchSalad account operation | Requires the user's external account and certificate renewal action. |
| Individual CRM authentication | Belongs to the productive CRM security roadmap. |
| Automated ACME renewal | Manual PunchSalad renewal is the selected first-cut process. |
| Linux/Nginx deployment removal | It remains a valid alternative for another host. |

## Assumptions & Open Questions

| Assumption / decision | Chosen default | Rationale | Confirmed? |
| --- | --- | --- | --- |
| Public hostname | `sc2030.brbots.com` | Explicit user decision. | yes |
| Server platform | Existing Windows host with Apache 2.4 | Explicit user decision and public endpoint evidence. | yes |
| Application runtime | Existing Python 3.11 at `C:/brbots/python/python.exe`, with a project virtual environment bound to `127.0.0.1:8080` | Reuses the supported runtime already installed on the server. | yes |
| Database runtime | Native PostgreSQL 17 on `127.0.0.1:5433`, installed beside the existing PostgreSQL 11 on port 5432 | Keeps the unsupported PostgreSQL 11 untouched while isolating the CRM on a supported database version. | yes |
| Process supervision | Windows Scheduled Task running as SYSTEM with restart-on-failure | Uses a built-in Windows facility and avoids a third-party service wrapper. | assumed |
| External access | Apache Basic Auth in front of the current anonymous CRM | Prevents public anonymous access during staging. | assumed |
| Certificate files | PEM certificate chain and separate private key stored under `C:/ProgramData/SmartCRM/tls` | Keeps private material outside Git and follows Apache separation guidance. | assumed |

**Open questions:** none - all unresolved technical choices have documented defaults.

## User Stories

### P1: Install the CRM on the existing Windows host

**User Story**: As the server operator, I want a Git-based native Windows
installation so that the CRM can replace the discontinued application without
changing the host platform.

**Why P1**: This is the required path to begin controlled server staging.

**Acceptance Criteria**:

1. WHEN the operator prepares the host THEN the installation procedure SHALL verify Python 3.11 at `C:/brbots/python/python.exe`, create the project virtual environment from that executable and install the locked project dependencies.
2. WHEN the operator creates the PostgreSQL role and database THEN the procedure SHALL run PostgreSQL 17 on `127.0.0.1:5433` and apply `alembic upgrade head` without manual `CREATE TABLE` statements.
3. WHILE the CRM runtime is active the application SHALL listen only on `127.0.0.1:8080`.
4. IF the external environment file is absent or its password is not exactly 64 hexadecimal characters THEN the startup script SHALL exit nonzero before starting Uvicorn.
5. WHEN Windows starts THEN the Smart CRM scheduled task SHALL start the runtime as SYSTEM and configure at least five one-minute restart attempts.
6. WHILE PostgreSQL 11 remains installed on port 5432 the installation procedure SHALL leave its service, configuration and data directory unchanged.

**Independent Test**: Parse the PowerShell scripts, validate their security
contract, and run the startup script with invalid fixtures without starting the
application.

### P1: Publish through Apache HTTPS

**User Story**: As the client tester, I want to open the CRM at
`https://sc2030.brbots.com` so that I can use the staged application through the
existing public address.

**Why P1**: Apache is the only public entry point on the existing server.

**Acceptance Criteria**:

1. WHILE the Windows deployment is enabled the Apache virtual host SHALL use `sc2030.brbots.com` on ports 80 and 443.
2. WHEN an HTTP request is not an ACME challenge THEN Apache SHALL redirect it to the same HTTPS URL with status 301.
3. WHEN Apache receives an HTTPS CRM request THEN it SHALL reverse proxy the request to `http://127.0.0.1:8080/` with forward proxy mode disabled.
4. WHILE the CRM is exposed through Apache the virtual host SHALL require Basic Auth for application paths and leave only `/.well-known/acme-challenge/` public.
5. WHILE TLS is enabled Apache SHALL load a PEM certificate chain and a separate private key from `C:/ProgramData/SmartCRM/tls`.
6. IF the certificate for `sc2030.brbots.com` is expired THEN the cutover procedure SHALL stop before enabling the CRM virtual host.

**Independent Test**: Validate the Apache configuration contract, parse the
active certificate dates during server UAT, and confirm unauthenticated HTTPS is
401 while authenticated `/health` returns the exact healthy payload.

## Edge Cases

- IF Apache cannot connect to `127.0.0.1:8080` THEN the rollback procedure SHALL restore the backed-up Apache configuration before client access is announced.
- IF `alembic upgrade head` exits nonzero THEN the installation procedure SHALL keep the old Apache virtual host active.
- IF the renewed certificate and private key do not match THEN `httpd.exe -t` SHALL fail the pre-cutover gate and Apache SHALL not restart.
- IF any secret or private key appears in Git status THEN the installation procedure SHALL stop before commit or push.
- IF port 5433 is already occupied THEN the installation procedure SHALL stop before installing or configuring PostgreSQL 17.

## Requirement Traceability

| Requirement ID | Story | Phase | Status |
| --- | --- | --- | --- |
| WAD-01 | Native Windows installation | Execute | Verified |
| WAD-02 | Local PostgreSQL and Alembic | Execute | Implementing |
| WAD-03 | Loopback-only Uvicorn | Execute | Implementing |
| WAD-04 | External secret rejection | Execute | Implementing |
| WAD-05 | Scheduled startup and restart | Execute | Implementing |
| WAD-06 | Fixed Apache hostname | Execute | Implementing |
| WAD-07 | HTTP redirect with public ACME path | Execute | Implementing |
| WAD-08 | Reverse proxy without forward proxy | Execute | Implementing |
| WAD-09 | Basic Auth perimeter | Execute | Implementing |
| WAD-10 | Separate external TLS files | Execute | Implementing |
| WAD-11 | Expired-certificate cutover block | Execute | Implementing |
| WAD-12 | Rollback on failed health | Execute | Implementing |
| WAD-13 | Preserve existing PostgreSQL 11 | Execute | Verified |

**Coverage:** 13 total, 13 mapped to the inline execution plan, 0 unmapped.

## Success Criteria

- [ ] Static configuration gates pass with zero unsafe public bindings or tracked secrets.
- [ ] Server UAT records an authenticated response of `{"status":"ok","database":"ok"}` from `https://sc2030.brbots.com/health`.
- [ ] Unauthenticated access returns HTTP 401 and the ACME challenge path remains publicly reachable.
