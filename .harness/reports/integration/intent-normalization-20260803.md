# AIENGINE-006 Shared Intent Normalization Evidence

Date: 2026-08-03
Status: PASS
Runtime ranking change: NONE

## Outcome

`matching-intent-command-v1.0`, `matching-intent-result-v1.0`, and
`intent-normalization-v1.0` provide one pure-engine boundary for natural-language queries and
canonical Excel/profile data. Both sources produce the same semantic buckets:

- `MUST`: explicit mandatory conditions
- `PREFER`: soft interests and visit goals
- `EXCLUDE`: explicit negative conditions
- `UNKNOWN`: known profile fields whose value has not been confirmed
- `UNRESOLVED`: text with no unique published ontology interpretation

This unit does not change `execute_matching`, the weighted-v1 score, candidate eligibility,
public APIs, database schema, or any active web UI.

## Safety boundaries

- Only assignable codes from published ontology `1.0.0` can enter resolved buckets.
- Korean labels and approved synonyms are deterministic evidence; published English/code tokens
  are supported without inventing a separate vocabulary.
- Ambiguous terms retain all published candidates. `OEM` and `수출` are not guessed.
- Explicit negation such as `막걸리 제외` produces `EXCLUDE`, not a zero similarity signal.
- Excel/profile `UNKNOWN` remains a knowledge state and has no false/zero value.
- Email and phone patterns are redacted before normalization, provider calls, and fingerprints;
  result objects and command representations do not echo raw query text.
- Optional AI output must match the strict `intent-proposal-v1.0` JSON Schema and published
  ontology. Valid items remain `VALIDATED_PROPOSAL_ONLY` and cannot enter resolved buckets.

## Regression fixture

Fixture: `tests/fixtures/matching/intent-normalization.v1.json`

Seven scenarios cover Korean synonym resolution, canonical Excel code input, English ontology
token input, ambiguous abbreviation, Korean negation, ambiguous Korean label, and explicit Excel
UNKNOWN. The natural-language, English-token, and Excel variants for takju have the identical
semantic signature:

`12649726ae37633a7e0983c2188b39531bb2cf55d7c94c0d4ff8ded85519ee7a`

Reproducibility fingerprints:

- Fixture input: `10fb464cf4d2aa897c6a3da0fb7ffae16949c8a8c83adbf7fe71c2ef544172ce`
- Evaluation result: `7ed32b25340dca4566cb0708b0c482e721f06d9bee4f5f881c728c15fe1e6309`

## Verification

- Focused facade/evaluator: 38 passed
- Root suite: 62 passed
- Backend suite: 197 passed, 2 skipped
- Ruff: PASS
- `compileall`: PASS
- `pip check`: PASS
- `git diff --check`: PASS

The two skipped backend tests remain the existing PostgreSQL integration skips. The attached
benchmark's kiosk-specific recommendations were not implemented because CR-009 excludes dedicated
kiosk development; the common engine remains usable by all four active web channels.

## Next gate

AIENGINE-007 may project only confirmed resolved intent into retrieval and Hard Filter plans.
UNKNOWN, UNRESOLVED, and proposal-only items must remain outside eligibility and numeric scoring,
and the current weighted-v1 published rank remains authoritative.
