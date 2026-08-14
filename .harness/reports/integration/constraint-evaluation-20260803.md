# AIENGINE-008 verified candidate constraint evaluation

Date: 2026-08-03
Status: PASS
Published contracts: `constraint-evaluation-result-v1.0`, `constraint-evaluation-v1.0`

## Outcome

The common engine now evaluates projected MUST/EXCLUDE constraints against explicit, verified
candidate observations before any score call. The result is exactly one of `ELIGIBLE`,
`FILTERED_OUT`, or `INFORMATION_REQUIRED`. Only a fully `ELIGIBLE` result can be converted to the
existing scoring `EligibilityDecision`.

This task does not change the published weighted-v1 formula, retrieval order, API responses,
database schema, stored recommendations, or active web surfaces.

## Deterministic policy

- `ONTOLOGY_MATCH` uses the published ontology graph and directional match policy.
- `DERIVED_BAND_MATCH` derives the published alcohol-percentage band before matching.
- `TRADE_STATUS` treats `YES` as a match and `NO` as a mismatch; `CONDITIONAL` and `NEGOTIABLE`
  require more information.
- `UNKNOWN`, `MISSING`, `STALE`, and absent observations are `INFORMATION_REQUIRED` for both MUST
  and EXCLUDE constraints. None becomes pass, mismatch, false, or zero.
- A proven violation makes the overall result `FILTERED_OUT`, while each information-required
  constraint remains present in the per-constraint decisions.
- Projection contract, policy, capability, ontology, ranking state, and fingerprints are
  revalidated before evaluation.

## Privacy and provenance

Results include only the candidate opaque reference, concept/operator decision, state, stable
reason codes, opaque evidence references, and canonical fingerprints. Raw natural-language query
text and candidate ontology/numeric/trade field values are not returned. Non-known observations
are rejected if they carry any value.

## Fixture evidence

Fixture: `tests/fixtures/matching/constraint-evaluation.v1.json`
Scenarios: 14
Fixture SHA-256: `d1cb093cc1b4d2ea34f3001691d7c2c6c81ec749e8680b7c029a1d58a0a87c44`
Canonical result-set SHA-256: `61acc5b1384b510158e2a5b8ebd19cad3ec76f1daab1cf6d9ce2a8c6512d46f2`

Coverage includes ontology MUST match/mismatch, ontology EXCLUDE present/absent, unknown, absent,
explicit missing, stale, derived alcohol band, OEM YES/NO/CONDITIONAL/NEGOTIABLE, and an unbound
hard requirement.

## Verification

- Focused facade and constraint tests: `30 passed`
- Root deterministic suite: `72 passed`
- Backend regression: `197 passed, 2 skipped`
- Touched-file Ruff: PASS
- Python compileall: PASS
- `pip check`: PASS
- `git diff --check`: PASS

The two backend skips require the existing migrated PostgreSQL integration environment. A broad
repository Ruff scan reported 117 pre-existing findings outside this task's changed paths; this
task introduced no touched-file Ruff findings.

## Promotion boundary

The evaluator is a pure engine contract in this task. AIENGINE-009 must add canonical runtime
candidate-observation mapping and shadow parity evidence against the existing Hard Filter. Any
enforcement difference or published-ranking change requires a separate versioned promotion
decision.
