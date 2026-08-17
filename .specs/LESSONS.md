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

## Quarantined (failed when applied - ignore)

A confirmed lesson that recurred alongside failure. Kept for the maintainer to review.

_none_
