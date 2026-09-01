# Windows Apache Deployment Context

**Gathered:** 2026-09-01
**Spec:** `.specs/features/windows-apache-deployment/spec.md`
**Status:** Approved by direct user decisions

## Feature Boundary

Prepare a Git-based native Windows deployment for the Smart CRM on the existing
Apache host at `sc2030.brbots.com`. The package stops before remote deployment,
certificate-account operations or production-data release.

## Implementation Decisions

### Host and domain

- Use the existing Windows server and Apache 2.4.
- Use `sc2030.brbots.com`; its DNS already resolves to `200.98.200.206`.
- Replace only the discontinued application's virtual host after all gates pass.

### Runtime and persistence

- Install Python 3.12 and PostgreSQL 17 natively on Windows.
- Bind PostgreSQL and Uvicorn to localhost only.
- Use Alembic for all CRM table creation and schema changes.
- Use a Windows Scheduled Task as SYSTEM for startup and failure restarts.

### HTTPS and access boundary

- Renew the expired certificate through the existing PunchSalad process.
- Keep certificate and private key outside Git under
  `C:/ProgramData/SmartCRM/tls`.
- Keep Basic Auth enabled until individual server-side CRM authentication exists.
- Preserve a public ACME challenge directory for certificate renewal.

### Agent's Discretion

- Exact PowerShell function decomposition and log-file naming.
- Exact Apache timeout values within the existing 25 MB request limit.

### Declined / Undiscussed Gray Areas → Assumptions

- Apache installation path defaults to `C:/Apache24`; the runbook explains how
  to substitute the actual path.
- PostgreSQL installation path defaults to
  `C:/Program Files/PostgreSQL/17`; the runbook explains how to discover it.
- The existing Apache service account is retained and receives read-only access
  to the private key.

## Specific References

- Existing public endpoint: `sc2030.brbots.com`.
- Public inspection on 2026-09-01 showed Apache 2.4.62 Win64, HTTP 200, HTTPS
  503 and an expired certificate.

## Deferred Ideas

- Automated ACME renewal on the Windows host.
- Individual user authentication and authorization inside the CRM.
