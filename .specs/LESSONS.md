# LESSONS - auto-maintained by scripts/lessons.py

> Machine-owned. Do NOT hand-edit. Changes are overwritten on the next `lessons.py` write.
> Canonical state lives in `.specs/lessons.json`. Edit lessons only via the script.
> promote_threshold=2 distinct features · window_days=45 · quarantine_threshold=2

## Confirmed (load these at Specify/Design)

Corroborated across multiple features. Safe to apply as guidance.

_none_

## Candidates (under observation - do NOT load as guidance yet)

Seen once or not yet corroborated. Tracked, not trusted.

### L-001 - Include behavior-level UI tests in the Full gate so automation condition mutants fail
- signal: `surviving_mutant` · recurrence: 1 feature(s) · scope: `ui-tests` · harmful: 0
- features: ui-prototype
- evidence: validation.md mutation 2 (ui-tests)
- last seen: 2026-08-17T20:30:29Z

### L-002 - Persist executable browser assertions for every interactive acceptance criterion before closing a UI feature
- signal: `ac_gap` · recurrence: 1 feature(s) · scope: `ui-tests` · harmful: 0
- features: ui-prototype
- evidence: DEMO-03-DEMO-16 (ui-tests)
- last seen: 2026-08-17T20:30:29Z

### L-003 - Seed an off-team record when testing role-based visibility boundaries
- signal: `ac_gap` · recurrence: 1 feature(s) · scope: `permissions` · harmful: 0
- features: ui-prototype
- evidence: DEMO-14 (permissions)
- last seen: 2026-08-17T20:30:29Z

### L-004 - Assert every required conjunct with its own observable outcome before marking an acceptance criterion covered
- signal: `ac_gap` · recurrence: 1 feature(s) · scope: `browser-e2e` · harmful: 0
- features: ui-crm-workspace
- evidence: .specs/features/ui-crm-workspace/validation.md:33 (browser-e2e)
- last seen: 2026-08-18T21:03:27Z

### L-005 - Assert the complete allowed set and exercise every required behavior branch for configurable operators and fields
- signal: `ac_gap` · recurrence: 1 feature(s) · scope: `filters` · harmful: 0
- features: ui-crm-workspace
- evidence: .specs/features/ui-crm-workspace/validation.md:49 (filters)
- last seen: 2026-08-18T21:03:28Z

### L-006 - Assert every spec-defined persisted payload field by exact name and value against the approved data model
- signal: `ac_gap` · recurrence: 1 feature(s) · scope: `state-payloads` · harmful: 0
- features: ui-crm-workspace
- evidence: .specs/features/ui-crm-workspace/validation.md:106 (state-payloads)
- last seen: 2026-08-18T21:03:29Z

## Quarantined (failed when applied - ignore)

A confirmed lesson that recurred alongside failure. Kept for the maintainer to review.

_none_
