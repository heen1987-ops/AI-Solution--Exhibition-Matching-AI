# AIENGINE-003 Common Matching Engine Facade

Date: 2026-08-02

Gate: Wave 2 / G2_FEATURE_COMPLETE remains in progress

## Outcome

The matching engine now exposes one provider- and database-independent execution boundary:

- command contract: `matching-engine-command-v1.0`;
- result contract: `matching-engine-result-v1.0`;
- engine version: `matching-engine-v1.0`; and
- modes: `CATALOG_SEARCH`, `GENERAL_VISITOR`, `BUYER_TO_EXHIBITOR`, `RECIPROCAL`.

The facade selects published policies internally. Callers cannot inject weights. Every result retains
the eligibility evaluation ID, taxonomy version, optional model version, selected policy versions,
per-policy calculation fingerprints, a canonical command-input fingerprint, and an aggregate result
fingerprint.

## Safety and determinism

- Unrecalled candidates are excluded as `NOT_RECALLED`.
- Hard Filter failures are returned only in `excluded_candidates` with their exact reason codes and
  never enter a score function.
- Ranked candidates expose the same score on normalized 0..1 and canonical 0..100 scales.
- Ties are resolved by candidate ID.
- Candidate order, component-map order, and recall-channel order do not alter input/result
  fingerprints.
- The pure `src/meet_ai/engine` package imports no FastAPI, SQLAlchemy, provider SDK, or backend
  service module.

## Adapter migration

- Kiosk catalog search now calls the facade's frozen
  `catalog-search-score-v1.0` policy. The existing non-renormalized
  `0.45/0.30/0.15/0.05/0.05` behavior is unchanged.
- General visitor and buyer recommendation adapters translate backend feature maps into one-candidate
  facade commands and retain the existing directional provenance fields.
- Reciprocal matching executes buyer, exhibitor, and reciprocal policies in one facade command and
  retains the existing caps, confidence adjustments, grades, status, and action fields.
- Public HTTP/OpenAPI contracts are unchanged.

## Golden-set contract

`matching-evaluator-v1.1` now executes each scenario as one facade command instead of invoking score
primitives candidate by candidate. Each scenario report records the facade contract version plus
engine input/result fingerprints.

Baseline command:

```text
python -m meet_ai.evaluation tests/fixtures/matching/golden-set.v1.json
```

| Metric | Result |
|---|---:|
| Scenario status | 3 / 3 PASS |
| Average Recall@3 | 1.000000 |
| Average NDCG@3 | 1.000000 |
| Average structured fallback Recall@3 | 0.666667 |
| Hard Filter violations | 0 |
| Filter decision/reason mismatches | 0 |
| Explanation grounding violations | 0 |

Golden-set input fingerprint:
`2d58998d49a01e6a4a6f041a1b44b72da493097304513e654eac0dce5a0d61c0`

Facade-backed evaluation result fingerprint:
`e9a3db60a421a50a049a6071e6cf0c3e3d98ad0bf94ca09ff4331ec836fec365`

## Verification

- Root suite: `42 passed`.
- Backend suite: `180 passed, 2 skipped`.
- Focused facade/evaluator suite: `18 passed`.
- Focused backend engine/scoring/search suite: `17 passed`.
- `python -m compileall` and `pip check`: pass.
- `git diff --check`: pass.

Live PostgreSQL/pgvector and real embedding-provider tests were not run because the local Docker
stack is stopped. This unit changes deterministic execution only; it does not claim production
relevance, latency, or provider availability.

## Next engine decision

`AISEARCH-003` is the next engine-scoped item. It must first decide, through the existing change
control, whether the redesign's simplified formula should replace the currently published policy.
No formula is changed merely because the facade now exists.
