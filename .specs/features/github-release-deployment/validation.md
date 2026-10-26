# Validation: GitHub Release Deployment - PASS ✅

**Verdict**: PASS ✅
**Date**: 2026-10-26
**Spec**: `.specs/features/github-release-deployment/spec.md`
**Diff range**: `44e95cf3a8905dcbdb59849f2199b47ca45c9a89..b7bdc7439f7bf0e26e72336a605f6ce96559bd93`
**Verifier**: independent re-verifier (author != verifier)

The full backend and browser gates pass. All 16 release requirements retain outcome-level evidence. Both mandatory behavior mutations are killed. The repaired DBP-10 test now proves the conflict path performs a canonical reload and updates browser-rendered state.

---

## Task Completion

| Scope | Status | Evidence |
| ----- | ------ | -------- |
| T1-T6 from `tasks.md` | ✅ Done | Every task checkbox is complete and the release workflow, builder, stager, runbook, evidence hardening, and clean-database fixture are present. |
| `5ed7392` deterministic conflict setup | ✅ Done | The test no longer waits for a transient lead that the conflict response discards. |
| `6a419d3` v0.3.3 release identity | ✅ Done | Canonical version and exact-value assertions are `0.3.3`. |
| `b7bdc74` canonical conflict reload assertion | ✅ Done | DBP-10 asserts the additional workspace GET and browser-rendered canonical lead state. |

No task is blocked or partial.

---

## Spec-Anchored Acceptance Criteria

| Requirement / criterion | Spec-defined outcome | `file:line` + assertion expression | Result |
| ----------------------- | -------------------- | ---------------------------------- | ------ |
| GRD-01 / Publish AC1 | The pushed tag equals `v` + `APP_VERSION` before artifacts are created. | `tests/backend/test_github_release_delivery.py:245` - `assert "from app.version import APP_VERSION" in workflow`; `:246-250` assert exact expected-tag construction, mismatch gate, and ordering before tests. | ✅ PASS |
| GRD-02 / Publish AC2 | Backend and UI tests run before publication. | `tests/backend/test_github_release_delivery.py:232-239` assert the release job depends on quality and Windows tests precede build; `:268-275` assert backend and UI precede build and publication. | ✅ PASS |
| GRD-03 / Publish AC3 | The builder emits the exact versioned ZIP and SHA-256 names and digest content. | `tests/backend/test_github_release_delivery.py:168-170` - exact archive name, digest name, and `f"{builder.sha256(archive)}  {archive.name}\n"`. | ✅ PASS |
| GRD-04 / Publish AC4 | Validation, test, or build failure prevents publication. | `tests/backend/test_github_release_delivery.py:248-250` and `:268-275` assert version/test/build/publish order in fail-fast jobs. | ✅ PASS |
| GRD-05 / Publish AC5 | The existing tag gets exactly the ZIP and digest without overwrite. | `tests/backend/test_github_release_delivery.py:278-283` assert exact asset variables, `--verify-tag`, and absence of clobber/upload; `:289-291` assert existing-release rejection precedes create. | ✅ PASS |
| GRD-06 / Stage AC1 | The stager uses the public `lamarcon/smart_crm` tag endpoint without a token. | `tests/backend/test_github_release_delivery.py:633-635` assert the exact tag endpoint/repository and `"Authorization" not in source`. | ✅ PASS |
| GRD-07 / Stage AC2 | Draft, prerelease, tag mismatch, missing assets, or ambiguous assets fail before extraction. | `tests/backend/test_github_release_delivery.py:312-338` drives every invalid metadata class through metadata validation and asserts `result.returncode != 0`. | ✅ PASS |
| GRD-08 / Stage AC3 | Digest filename and SHA-256 exactly match the downloaded ZIP. | `tests/backend/test_github_release_delivery.py:341-354` asserts the returned hash equals `builder.sha256(archive)`; `:357-378` rejects malformed, wrong-name, and wrong-hash digests. | ✅ PASS |
| GRD-09 / Stage AC4 | Extraction occurs in staging, the internal manifest passes, then the directory is promoted. | `tests/backend/test_github_release_delivery.py:393-397` assert exact final path/payload and no staging residue; `:435-439` assert a bad manifest creates no final directory and preserves existing state. | ✅ PASS |
| GRD-10 / Stage AC5 | A pre-existing final directory blocks staging without modification. | `tests/backend/test_github_release_delivery.py:413-415` assert non-zero exit, unchanged marker, and no staging residue. | ✅ PASS |
| GRD-11 / Stage AC6 | Failures clean only temporary state and preserve releases/configuration; no task/database/secret mutation occurs. | `tests/backend/test_github_release_delivery.py:153-157` define exact preservation assertions used at `:489-491`, `:515-517`, and `:543-545`; `:435-439` cover manifest failure; `:630-645` reject cutover/database/secret mutation commands. | ✅ PASS |
| GRD-12 / Stage AC7 | Success reports exact tag, hash, and final path without secrets. | `tests/backend/test_github_release_delivery.py:566-575` assert the exact result object, secret-sentinel absence, and `RELEASE_STAGED=PASS`. | ✅ PASS |
| GRD-13 / Invalid tag edge | Unsafe/path-like tags fail before paths or URLs are formed. | `tests/backend/test_github_release_delivery.py:195-203` assert builder rejection before output creation; `:294-299` assert invalid stager tags fail with the required format error. | ✅ PASS |
| GRD-14 / GitHub unavailable edge | API failure occurs before final or temporary directory creation. | `tests/backend/test_github_release_delivery.py:455-460` assert non-zero exit, the API error, no final directory, and no download root. | ✅ PASS |
| GRD-15 / Invalid digest edge | Malformed, mismatched, or wrong-name digest fails before extraction. | `tests/backend/test_github_release_delivery.py:357-378` assert all three invalid digest classes return non-zero. | ✅ PASS |
| GRD-16 / Concurrency edge | Two preparations produce exactly one winner, one intact final directory, and no residue. | `tests/backend/test_github_release_delivery.py:623-627` assert one zero exit, one non-zero exit, exact payload, and no staging directory. | ✅ PASS |

**Status**: ✅ 16/16 criteria match the spec-defined outcomes; 0 uncovered criteria and 0 spec-precision gaps.

### v0.3.3 Diff Evidence

- `app/version.py:3` sets `APP_VERSION = "0.3.3"`.
- `tests/backend/test_api.py:179` asserts `response.json() == {"version": "0.3.3"}`.
- `tests/backend/test_windows_multitenant_bundle.py:101` asserts `APP_VERSION == "0.3.3"`.
- `tests/backend/test_windows_multitenant_bundle.py:141` asserts the packaged source contains `APP_VERSION = "0.3.3"`.
- `tests/ui-prototype.spec.cjs:888-889` assert footer text `v0.3.3` and accessible label `Versão instalada 0.3.3`.
- `tests/ui-prototype.spec.cjs:1188-1195` record the pre-conflict GET count, wait for the rendered canonical lead, assert one additional workspace GET, and assert the conflicting local lead is absent.

---

## Discrimination Sensor

Both mutations ran only in detached scratch worktree `release-v033-reverify-sensor` at `b7bdc74`. The worktree, temporary pytest directories, browser, and Uvicorn processes were removed after the runs.

| Mutation | Production file:line | Fault | Focused evidence | Result |
| -------- | -------------------- | ----- | ---------------- | ------ |
| 1 | `app/static/index.html:1361` | Replaced `await loadCanonicalWorkspace()` with a no-op while retaining the success toast. | Focused DBP-10 failed at `tests/ui-prototype.spec.cjs:1193`: the rendered canonical lead never appeared (`0 passed, 1 failed`, exit 1). | ✅ Killed |
| 2 | `app/version.py:3` | Changed canonical version `0.3.3` to `0.3.2`. | `tests/backend/test_api.py:179` failed on API payload `0.3.2 != 0.3.3`; `tests/backend/test_windows_multitenant_bundle.py:101` failed on imported version `0.3.2 != 0.3.3` (`2 failed`, exit 1). | ✅ Killed |

**Sensor depth**: lightweight, 2 targeted behavior mutations.
**Result**: 2/2 killed, 0 survived - PASS ✅.
**Isolation**: real-tree porcelain before and after sensor cleanup is identical: only `.specs/features/github-release-deployment/validation.md` is modified. Ports 18086 and 18087 are clear, and the scratch worktree no longer exists.

---

## Interactive UAT

Not performed. This is an infrastructure/release feature; the workflow, PowerShell, API, packaging, and browser automation provide the required evidence.

---

## Code Quality

| Principle | Status | Evidence |
| --------- | ------ | -------- |
| Minimum code | ✅ | The diff updates one canonical version and strengthens the existing conflict test with one request counter and browser-state assertions. |
| Surgical changes | ✅ | Diff range changes 5 files with 15 insertions and 13 deletions. |
| No scope creep | ✅ | No push, tag, GitHub Release, deploy, production database action, migration, or cutover occurred. |
| Matches patterns | ✅ | Version remains centralized in `app/version.py`; tests use existing pytest and Playwright helpers. |
| Spec-anchored outcome check | ✅ | 16/16 release criteria assert the required value, state, ordering, or preservation outcome. |
| Payload/conjunction rule | ✅ | Asset identity, preservation, final identity, rendered state, request count, and secret absence are asserted by value/state. |
| Per-layer coverage expectation | ✅ | Builder/workflow contracts, PowerShell happy/error/concurrency paths, API/bundle version, and browser behavior are exercised. |
| Every test is claimed | ✅ | Release tests map to GRD-01..16; changed API/bundle/UI assertions map to the v0.3.3 release identity and DBP-10 regression gate required by GRD-02/04. |
| Test discrimination | ✅ | Both required mutations are killed at the expected assertion boundary. |
| Test integrity | ✅ | No test was deleted or skipped; the diff retains 830 backend and 122 UI tests. |
| Documented guidelines | ✅ | `pyproject.toml`, `package.json`, `README.md`, and `.specs/features/github-release-deployment/tasks.md:16`; no `AGENTS.md` exists. |

---

## Edge Cases

- [x] Invalid/path-like tags are rejected before output creation.
- [x] GitHub/API failure creates no final or temporary directory.
- [x] Digest format, name, and bytes are validated before extraction.
- [x] Failure paths preserve prior release/configuration and remove residue.
- [x] Existing final directory remains unchanged.
- [x] Concurrent staging produces exactly one winner.
- [x] DBP-10 detects removal of the canonical conflict reload and asserts browser-rendered canonical state.
- [x] Exact v0.3.3 API and bundle assertions detect a version rollback.

---

## Gate Check

- **Backend command**: `D:\Develop_CRM_Project\.venv\Scripts\python.exe -m pytest -q --basetemp D:\Develop_CRM_Project\.verify-worktrees\release-v033-reverify-tmp\backend-valid`
- **Backend result**: 830 passed, 0 failed, 0 skipped; 6 warnings; 214.68 s; exit 0.
- **UI command**: worktree-bound Uvicorn on `127.0.0.1:18086`, then `SMART_CRM_TEST_URL=http://localhost:18086/ pnpm test`.
- **UI result**: 122 passed, 0 failed; exit 0.
- **Build total**: 952 passed, 0 failed, 0 skipped.
- **Test count before diff**: 830 backend + 122 UI = 952.
- **Test count after diff**: 830 backend + 122 UI = 952.
- **Delta**: 0 test definitions; assertions were strengthened, not weakened.
- **Skipped tests**: none.
- **Diff hygiene**: `git diff --check 44e95cf3a8905dcbdb59849f2199b47ca45c9a89..HEAD` exited 0.
- **Excluded diagnostic run**: the initial sandboxed pytest attempt could not complete local fixtures and is not counted. The same focused API test passed immediately with approved local access before the full valid gate.

---

## Requirement Traceability

| Requirement | Spec status | Validation status |
| ----------- | ----------- | ----------------- |
| GRD-01..GRD-16 | Verified | ✅ Verified |

The verifier did not modify `spec.md`, code, or tests.

---

## Summary

**Overall**: ✅ Ready

**Spec-anchored check**: 16/16 release criteria matched; 0 spec-precision gaps.
**Gate**: 952 passed, 0 failed, 0 skipped.
**Sensor**: 2 mutations injected, 2 killed, 0 survived.

**What works**: version `0.3.3` is canonical across API, packaged runtime, UI, and workflow tag derivation; publication and server staging remain fail-closed; DBP-10 now proves the canonical reload at both network and rendered-state boundaries.

**Issues found**: none.

**Next step**: none within verification. Any push, tag, GitHub Release, deployment, migration, or production action still requires separate explicit authorization.
