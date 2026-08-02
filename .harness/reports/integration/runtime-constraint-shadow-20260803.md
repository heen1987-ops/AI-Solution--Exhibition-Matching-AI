# AIENGINE-009 runtime constraint shadow

Date: 2026-08-03
Status: PASS — SHADOW ONLY
Contracts: `candidate-observation-adapter-v1.0`, `hard-filter-shadow-v1.0`

## Outcome

The runtime candidate payload now has a privacy-minimized adapter into the AIENGINE-008
`CandidateFieldObservation` contract. The three-state evaluator runs beside the existing Hard
Filter and compares decisions without changing the authoritative admission result.

`HARD_FILTER_SHADOW_ENFORCEMENT` is fixed to `False`. This unit changes no weighted-v1 formula,
candidate rank, public API response, database schema, or stored Hard Filter record.

## Mapping boundary

Public observations require explicit public approval. Buyer-only channel, region, trade type, and
OEM/PB/export observations additionally require an approved supply profile. Only fields present in
the projected intent plan are read.

Supported mappings:

- category, taste, aroma, usage, product feature, booth service, alcohol percentage;
- buyer channel, region, trade type;
- OEM, private-label, and export status.

Explicit observation state metadata preserves `UNKNOWN`, `MISSING`, and `STALE`. Trade values
`CONDITIONAL` and `NEGOTIABLE` enter the evaluator as known non-final statuses and produce
`INFORMATION_REQUIRED`. Empty canonical collections are treated conservatively as missing.

## Shadow comparison

- `PARITY`: legacy and projected outcomes agree on an eligible or comparable filtered decision.
- `SAFETY_GAP`: legacy passes while the projected evaluator requires information or finds a
  projected violation.
- `DIVERGENCE`: a comparable legacy rejection is not reproduced.
- `NOT_COMPARABLE`: the legacy rejection is outside the projected intent-constraint scope.
- `NOT_APPLICABLE`: the profile has no projected hard condition.
- `ADAPTER_ERROR`: profile intent or candidate observation fails deterministic validation.

Results contain opaque candidate references, legacy reason codes, projected state, policy
references, and fingerprints. Raw query text and candidate ontology, numeric, or private trade
values are absent.

## Fixture evidence

Fixture: `tests/fixtures/matching/runtime-constraint-shadow.v1.json`
Scenarios: 7
Fixture SHA-256: `d896b5c32cd371214ddd1cd11b8d06822df2521d35fecf538441215dc331b13f`
Canonical result-set SHA-256: `e569d8218d8c189e6e31e347dbaef38b5850d8bc158e11af1dd3477d4d38a00e`

The fixture proves OEM `YES`/`NO` parity and explicit safety gaps for `UNKNOWN`, missing, `STALE`,
`CONDITIONAL`, and `NEGOTIABLE`. Additional tests cover all supported public/buyer field mappings,
public EXCLUDE gaps, unapproved data, invalid observations, deterministic ordering, private-value
omission, not-applicable profiles, and synthetic divergence.

## Verification

- Focused matching adapter and Hard Filter tests: `21 passed`
- Root deterministic suite: `72 passed`
- Backend regression: `211 passed, 2 skipped`
- Touched-file Ruff: PASS
- Python compileall: PASS
- `pip check`: PASS
- Harness JSON/YAML and `git diff --check`: PASS
- Local diagnostic benchmark: 150 candidates, 150 shadow results, approximately 55 ms

The two skipped backend tests require the existing migrated PostgreSQL integration environment.
The local timing is a development-machine observation, not production capacity evidence.

## Promotion boundary

Promotion is blocked in this unit. AIENGINE-010 must aggregate versioned shadow metrics and fail
on any divergence or adapter error. Enabling enforcement later requires a separate approved Change
Request, a sufficient runtime sample, no hard-filter regression, score/rank regression evidence,
and a tested rollback path.
