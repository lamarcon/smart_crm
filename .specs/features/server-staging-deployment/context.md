# Server Staging Deployment Context

**Gathered:** 2026-08-31
**Spec:** `.specs/features/server-staging-deployment/spec.md`
**Status:** Approved by direct user request

## Feature Boundary

Package the current CRM for a manual Git-based installation on the existing server. Deliver Compose, secrets template, validation, HTTPS reverse-proxy example and an operator runbook. Do not push or deploy remotely in this feature.

## Implementation Decisions

### Data and runtime

- PostgreSQL runs as a private Compose service with a named volume.
- Alembic migration is an explicit one-shot command before starting the CRM.
- The CRM binds to loopback and keeps its non-root, read-only container baseline.

### Access boundary

- Nginx provides HTTPS and temporary shared Basic Auth.
- The current deployment is staging/private and must not receive real client data.
- Real users, permissions and audit remain in the productive CRM feature.

### Git workflow

- The server clones the existing GitHub `origin`.
- Updates use `git fetch --prune` and `git merge --ff-only origin/main`.
- The operator records the deployed SHA and creates a database backup before migration.

### Agent's Discretion

- File names, Compose project name, health intervals and runbook structure.

### Declined / Undiscussed Gray Areas → Assumptions

- Linux distribution is not known; commands target Debian/Ubuntu conventions where a package-manager example is necessary.
- Domain and certificate paths are placeholders because the server hostname is not known.
- External PostgreSQL is deferred; the private Compose database is the safer zero-ambiguity default.

## Specific References

- Git remote: `https://github.com/lamarcon/smart_crm.git`.
- Current application port: container `8000`, local host `8080`.

## Deferred Ideas

- Existing external PostgreSQL profile.
- Automated CI/CD deployment.
- Real application authentication and authorization.
