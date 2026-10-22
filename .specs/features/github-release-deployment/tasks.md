# GitHub Release Deployment Tasks

## Execution Protocol (MANDATORY -- do not skip)

Implement these tasks with the `tlc-spec-driven` skill: **activate it by name and follow its Execute flow and Critical Rules.** Do not search for skill files by filesystem path. The skill is the source of truth for the full flow (per-task cycle, sub-agent delegation, adequacy review, Verifier, discrimination sensor).

**If the skill cannot be activated, STOP and tell the user - do not proceed without it.**

---

**Design**: `.specs/features/github-release-deployment/design.md`
**Status**: In Progress

---

## Test Coverage Matrix

> Generated from codebase, project guidelines, and spec - confirm before Execute. Guidelines found: `pyproject.toml`, `package.json`, `README.md`; no separate contributor or agent guideline - strong defaults applied.

| Code Layer | Required Test Type | Coverage Expectation | Location Pattern | Run Command |
| ---------- | ------------------ | -------------------- | ---------------- | ----------- |
| Python bundle builder | unit | Every version-validation branch and exact artifact name defined by GRD-01/03/12 | `tests/backend/test_github_release_delivery.py` | `& .\.venv\Scripts\python.exe -m pytest -q --basetemp test-results/github-release-pytest tests/backend/test_github_release_delivery.py` |
| GitHub workflow contract | unit/static contract | Trigger, permission, version gate, test order, build inputs and exactly two release assets from GRD-01..05 | `tests/backend/test_github_release_delivery.py` | `& .\.venv\Scripts\python.exe -m pytest -q --basetemp test-results/github-release-pytest tests/backend/test_github_release_delivery.py` |
| PowerShell staging policy | integration | Happy path plus every metadata, digest, duplicate and cleanup edge case from GRD-06..15 | `tests/backend/test_github_release_delivery.py` | `& .\.venv\Scripts\python.exe -m pytest -q --basetemp test-results/github-release-pytest tests/backend/test_github_release_delivery.py` |
| Operator documentation | none | Build gate verifies referenced commands and full existing suite | - | build gate only |

## Gate Check Commands

> Generated from codebase - confirmed by the approved execution model.

| Gate Level | When to Use | Command |
| ---------- | ----------- | ------- |
| Quick | Unit/static contract task | `& .\.venv\Scripts\python.exe -m pytest -q --basetemp test-results/github-release-pytest tests/backend/test_github_release_delivery.py` |
| Full | PowerShell integration task | `& .\.venv\Scripts\python.exe -m pytest -q --basetemp test-results/github-release-pytest tests/backend/test_github_release_delivery.py tests/backend/test_manual_windows_pg11_deployment.py tests/backend/test_manual_windows_pg11_outcomes.py` |
| Build | Phase completion or docs/config | `& .\.venv\Scripts\python.exe -m pytest -q --basetemp test-results/github-release-pytest; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }; pnpm test` |

---

## Execution Plan

### Phase 1: Versioned build contract

```
T1 → T2
```

### Phase 2: Safe server staging

```
T2 → T3
```

### Phase 3: Operator handoff

```
T3 → T4
```

---

## Task Breakdown

### T1: Accept a safe release tag in the bundle builder

**What**: Add a validated `--version` CLI input while preserving SHA-based local builds.
**Where**: `scripts/build_manual_windows_pg11_bundle.py`
**Depends on**: None
**Reuses**: Existing `build()` and deterministic artifact naming.
**Requirement**: GRD-01, GRD-03, GRD-12

**Tools**:

- MCP: NONE
- Skill: `tlc-spec-driven`

**Done when**:

- [x] Safe semantic tag `v0.3.0` produces the exact tag-based ZIP and digest names.
- [x] Missing `--version` continues using the short Git SHA.
- [x] Empty, path-like and unsafe identifiers fail before any output path is created.
- [x] Quick gate passes with no skipped or deleted tests (`10 passed`).

**Tests**: unit
**Gate**: quick

### T2: Publish tested tag assets with GitHub Actions

**What**: Create the tag-triggered Windows workflow with version, test, build and immutable release gates.
**Where**: `.github/workflows/release-windows-pg11.yml`
**Depends on**: T1
**Reuses**: `pyproject.toml`, `package.json`, bundle builder and GitHub CLI.
**Requirement**: GRD-01, GRD-02, GRD-03, GRD-04, GRD-05

**Tools**:

- MCP: NONE
- Skill: `tlc-spec-driven`

**Done when**:

- [x] Only pushed tags beginning with `v` trigger the workflow.
- [x] The workflow rejects a tag unequal to `v` + `APP_VERSION`.
- [x] Backend and UI tests precede bundle creation.
- [x] `gh release create --verify-tag` receives exactly the ZIP and digest.
- [x] The job has only the repository permission needed to create the release.
- [x] Build gate passes with no skipped or deleted tests (`802 backend + 122 UI`).

**Tests**: unit
**Gate**: build

### T3: Stage a public GitHub Release safely on Windows

**What**: Add the PowerShell 5.1 script that validates release metadata, two hashes and side-by-side promotion.
**Where**: `deploy/manual-windows-pg11/stage-github-release.ps1`
**Depends on**: T2
**Reuses**: Packaged `test-package-integrity.ps1` and current side-by-side directory contract.
**Requirement**: GRD-06, GRD-07, GRD-08, GRD-09, GRD-10, GRD-11, GRD-12, GRD-13, GRD-14, GRD-15

**Tools**:

- MCP: NONE
- Skill: `tlc-spec-driven`

**Done when**:

- [ ] Public release lookup requires an explicit safe semantic tag and no token.
- [ ] Draft, prerelease, tag mismatch, missing or duplicate assets fail before extraction.
- [ ] Digest parsing requires exact SHA-256 and filename and verifies downloaded bytes.
- [ ] Valid fixture promotes only after the packaged manifest verifier passes.
- [ ] Existing final directory and tampered fixture remain unchanged and leave no staging directory.
- [ ] Script source contains no task, Alembic, database or `server.env` mutation.
- [ ] Full gate passes with no skipped or deleted tests.

**Tests**: integration
**Gate**: full

### T4: Document the short release and staging flow

**What**: Add the GitHub release path to the existing production runbook without weakening backup, cutover or rollback gates.
**Where**: `deploy/manual-windows-pg11/LEIA-ME.md`
**Depends on**: T3
**Reuses**: Existing sections 1, 3, 4, 6, 8 and 9.
**Requirement**: GRD-05, GRD-06, GRD-10, GRD-11

**Tools**:

- MCP: NONE
- Skill: `tlc-spec-driven`

**Done when**:

- [ ] Runbook shows how to create/push the approved tag and what GitHub publishes.
- [ ] Server bootstrap downloads the staging script from the same immutable tag.
- [ ] The short staging command is followed by the existing install/cutover gates, not an automatic activation.
- [ ] Runbook states that no GitHub token, Git checkout or production secret belongs in the flow.
- [ ] Build gate passes with no skipped or deleted tests.

**Tests**: none
**Gate**: build

---

## Phase Execution Map

```
Phase 1 → Phase 2 → Phase 3

Phase 1: T1 ------→ T2
Phase 2:             T2 ------→ T3
Phase 3:                         T3 ------→ T4
```

Execution is strictly sequential.

## Task Granularity Check

| Task | Scope | Status |
| ---- | ----- | ------ |
| T1 | One builder CLI contract plus co-located tests | ✅ Granular |
| T2 | One workflow plus co-located contract tests | ✅ Granular |
| T3 | One staging component plus co-located integration tests | ✅ Granular |
| T4 | One runbook update | ✅ Granular |

## Diagram-Definition Cross-Check

| Task | Depends On (task body) | Diagram Shows | Status |
| ---- | ---------------------- | ------------- | ------ |
| T1 | None | Start at T1 | ✅ Match |
| T2 | T1 | T1 → T2 | ✅ Match |
| T3 | T2 | T2 → T3 | ✅ Match |
| T4 | T3 | T3 → T4 | ✅ Match |

## Test Co-location Validation

| Task | Code Layer Created/Modified | Matrix Requires | Task Says | Status |
| ---- | --------------------------- | --------------- | --------- | ------ |
| T1 | Python bundle builder | unit | unit | ✅ OK |
| T2 | GitHub workflow contract | unit/static contract | unit | ✅ OK |
| T3 | PowerShell staging policy | integration | integration | ✅ OK |
| T4 | Operator documentation | none | none | ✅ OK |

