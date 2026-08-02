# AIENGINE-010 — Constraint shadow quality gate

Date: 2026-08-03

Status: PASS (implementation); NOT READY (runtime enforcement)

Policy: `constraint-shadow-promotion-gate-v1.0`

## Outcome

The runtime constraint shadow now has a deterministic, privacy-safe aggregate gate. The gate
accepts only state counts, stable safety-gap reason counts, opaque evidence references, and source
policy versions. Candidate IDs, profile fields, observed trade values, contact details, and raw
query text are outside the command contract and the result.

The gate can return `change_request_ready=true`, which means only that its evidence can be taken to
a separate approved Change Request. `enforcement_allowed` is a constant `false`; the legacy Hard
Filter remains authoritative and `weighted-v1` rank is unchanged.

## Gate policy

| Condition | Result |
|---|---|
| Any `DIVERGENCE` | `FAIL` / `DIVERGENCE_PRESENT` |
| Any `ADAPTER_ERROR` | `FAIL` / `ADAPTER_ERROR_PRESENT` |
| Fewer than 1,000 comparable results | `INSUFFICIENT_EVIDENCE` |
| Missing regression evidence | `INSUFFICIENT_EVIDENCE` |
| Missing rollback evidence | `INSUFFICIENT_EVIDENCE` |
| Any safety gap without a review artifact | `INSUFFICIENT_EVIDENCE` |
| All conditions satisfied | `PASS`, Change Request ready, enforcement still disabled |

Comparable results are `PARITY`, `SAFETY_GAP`, `DIVERGENCE`, and `ADAPTER_ERROR`.
`NOT_COMPARABLE` and `NOT_APPLICABLE` remain visible in the aggregate but cannot inflate the
minimum runtime sample. The runtime adapter also de-duplicates identical shadow fingerprints;
retry duplicates are reported separately and cannot inflate the sample.

The minimum of 1,000 comparable decisions is an operational evidence floor, not a statistical
claim. A later Change Request must justify a larger or segmented sample when event, buyer, product,
or constraint distributions require it.

## Evidence required before a later enforcement Change Request

1. A fixed observation window containing at least 1,000 comparable shadow decisions.
2. Zero `DIVERGENCE` and zero `ADAPTER_ERROR` in that window.
3. A versioned full-regression report for the exact source policy versions.
4. A review artifact that groups every `SAFETY_GAP` by stable reason code and records disposition.
5. A versioned rollback runbook reference that restores the legacy Hard Filter as sole authority,
   identifies the feature switch or release reversal, names the responsible operator, and defines
   post-rollback verification.
6. A separate approved Change Request. A gate `PASS` is not that approval.

No production sample or approved enforcement Change Request exists in this implementation unit,
so current enforcement status remains **NOT READY**.

## Fixed fixture evidence

Fixture: `tests/fixtures/matching/constraint-shadow-gate.v1.json`

SHA-256: `8399af15bce0aad618e4645f9316526b59da7eec764636f5e3f5255eb573c08c`

The six scenarios cover a policy pass, divergence failure, adapter-error failure, insufficient
sample/evidence, unreviewed safety gaps, and exclusion of non-comparable rows from the sample floor.
The reference passing result has:

- input fingerprint: `b1a1c6f722c718f806375f38e7921ab8e53a4129c7765c84745f3a5db9ec64bf`
- result fingerprint: `db19316e331980e8bd613f98e3745fda0f4522e6d0dd2e6f3f7af646b385663b`

Reordering state counts, reason counts, source versions, or evidence references produces the same
fingerprints.

## Validation

- Focused adapter/gate tests: `25 passed`
- Root engine tests: `72 passed`
- Backend tests: `219 passed, 2 skipped`
- Ruff on touched Python paths: pass
- Python compile check on touched modules: pass
- `git diff --check`: pass (Git emitted only expected Windows LF/CRLF notices)

The two skipped backend tests are pre-existing optional PostgreSQL integration paths. The warnings
are existing Starlette deprecations and do not affect this gate.
