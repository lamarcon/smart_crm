# stage-hover-tooltip Validation

**Verdict**: PASS ✅
**Date**: 2026-08-18
**Spec**: one-line inline acceptance criterion approved by the user
**Diff range**: `6bc6452..52d108b`
**Verifier**: independent sub-agent (author != verifier)

## Spec-Anchored Acceptance Criteria

| Required outcome | Spec-defined outcome | Evidence and assertion | Result |
| --- | --- | --- | --- |
| Highlight | Hovering any deal-stage segment changes its visual treatment. The generic selector covers every deal segment at `app/static/index.html:171`, and all nine segments are rendered through the same mapping at `app/static/index.html:1033`. | `tests/ui-prototype.spec.cjs:463-469` - `segment.hover()` followed by `assert.deepEqual(visual, { background: 'rgb(52, 64, 84)', tooltip: 'Pedido aprovado Consultar', opacity: '1' })`. Existing breadth evidence: `tests/ui-prototype.spec.cjs:453` asserts nine rendered segments. | PASS ✅ |
| Exact tooltip text | The displayed tooltip equals the exact stage name. The renderer copies each mapped stage into `data-stage-tooltip` at `app/static/index.html:1033`; the pseudo-element reads that attribute at `app/static/index.html:172-173`. | `tests/ui-prototype.spec.cjs:461-469` - selects `Pedido aprovado Consultar`, asserts the attribute equals that exact string, then asserts computed `::after` content equals the same string with opacity `1`. | PASS ✅ |
| State unchanged | Hovering does not change the deal's stage. The feature adds only CSS and a render-time data attribute; it adds no hover handler (`app/static/index.html:168-173`, `app/static/index.html:1031-1034`). | `tests/ui-prototype.spec.cjs:470` - `assert.equal((await stateFrom(page)).deals.find(deal => deal.id === 'N-16312').stage, 'Orçamentos enviados')` after hover. | PASS ✅ |

**Coverage**: 3/3 required outcomes match the precise spec outcome. No spec-precision gap.

Keyboard parity is optional in the inline spec. The implementation nevertheless applies the same feedback on `:focus-visible` at `app/static/index.html:171-173`.

## Full Gate

- UI command: `node tests/ui-prototype.spec.cjs` (executed with the installed Codex Node runtime because `node`/`npm` were not on this shell's `PATH`).
- Final UI result: **42 passed, 0 failed, 0 skipped**.
- Server command: `docker compose exec crm python app/server.py --self-test`.
- Server result: **PASS**, including `/health` 200, `/` 200, traversal rejection 403, and `server self-test: ok`.
- Test count before feature (`6bc6452`): 41.
- Test count after feature (`52d108b`): 42.
- Delta: +1 test.
- Stability observation: the first UI run reported 41 passed and one unrelated `DRAWER-06` visibility failure at `tests/ui-prototype.spec.cjs:213`; the immediate full rerun passed 42/42. The feature test passed in both unmutated runs.

## Discrimination Sensor

The sensor used an isolated clone outside the real worktree. Each mutant was built and served in a temporary Docker image. The scratch clone, containers, and temporary image tags were removed afterward.

| Mutation | Scratch target | Expected discriminator | Result |
| --- | --- | --- | --- |
| Replaced every deal tooltip value with `Etapa incorreta`. | `app/static/index.html:1033` | Exact-name assertion at `tests/ui-prototype.spec.cjs:462`. | KILLED ✅: actual `Etapa incorreta` differed from `Pedido aprovado Consultar`. |
| Added a synthetic `mouseenter` side effect that changed the hovered deal stage to `Faturando`. | `app/static/index.html:1033` | Post-hover state assertion at `tests/ui-prototype.spec.cjs:470`. | KILLED ✅: actual `Faturando` differed from `Orçamentos enviados`. |

**Sensor depth**: lightweight, 2 behavior-level mutations.
**Result**: 2/2 killed, 0 survived, PASS ✅.
**Isolation**: real-tree `git status --porcelain=v1` was empty before the sensor and remained empty after scratch cleanup.

## Code Quality

| Principle | Result | Evidence |
| --- | --- | --- |
| Minimum code and no scope creep | PASS ✅ | The diff adds three CSS rules/adjustments, one conditional render attribute, and one browser test in the two required files only. |
| Surgical change | PASS ✅ | `git diff --name-status 6bc6452..52d108b` contains only `app/static/index.html` and `tests/ui-prototype.spec.cjs`. |
| No unnecessary abstraction or flexibility | PASS ✅ | Existing `renderStageProgress` mapping and existing CSS class are extended directly at `app/static/index.html:168-173`, `app/static/index.html:1031-1034`. |
| Matches existing patterns | PASS ✅ | Uses existing stage button data attributes, `escapeHTML`, Playwright locator style, and strict Node assertions. |
| Test integrity | PASS ✅ | No existing test was removed or weakened; count increases from 41 to 42. The new test asserts exact computed values and persisted state at `tests/ui-prototype.spec.cjs:458-470`. |
| Per-layer coverage | PASS ✅ | This is a CSS/render-only browser feature with no route or domain-layer change. Its three UI outcomes are asserted in one focused browser scenario. |
| Tests are claimed by the spec | PASS ✅ | The sole added test maps directly to highlight, exact tooltip text, and unchanged state. |
| Project guidance | PASS ✅ | `README.md:58-64` defines the browser regression workflow; the full browser suite and server self-test were run. Strong defaults from `coding-principles.md` were applied. |

## Summary

**Overall**: Ready ✅

The generic renderer and selectors apply the behavior to every deal-stage segment in list view. The automated test proves a representative segment receives the exact highlight and tooltip text while the persisted deal stage remains unchanged. Full gate passed, and both targeted mutants were killed.
