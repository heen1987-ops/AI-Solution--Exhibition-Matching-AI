# AIENGINE-004 handoff

## Delivered

- Versioned v1.1 matching command/result reason-evidence contract.
- Deterministic allowlisted claims for score contributions, catalog signals, reciprocal state, and
  Hard Filter exclusions.
- Evidence-required fail-closed behavior and per-claim/result fingerprints.
- Backend catalog/directional adapter inputs for the same evidence contract.
- Runtime template projection from facade claims without LLM-authored facts.
- Golden evaluator v1.2 validation of facade-generated claims.

## Compatibility

- v1.0 commands remain executable when no reason evidence is present.
- Published score policies and score calculation fingerprints were not changed.
- Public HTTP and database contracts were not changed.

## Next engine unit

AIENGINE-005 should add a shadow-only RRF hybrid-fusion evaluator and explicit UNKNOWN/missing-signal
cases before any proposal to replace the published catalog weighted score. Do not promote RRF,
learned reranking, or online learning without labeled non-inferiority evidence and a versioned
contract decision.
