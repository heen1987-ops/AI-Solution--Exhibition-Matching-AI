# AIENGINE-005 Hybrid RRF Shadow Evidence

Date: 2026-08-02
Status: PASS
Promotion status: PROHIBITED

## Outcome

`hybrid-rrf-shadow-command-v1.0`, `hybrid-rrf-shadow-result-v1.0`, and
`hybrid-rrf-shadow-evaluator-v1.0` evaluate deterministic reciprocal-rank fusion over
STRUCTURED, KEYWORD/BM25, and VECTOR candidate ranks. The implementation is isolated from
`execute_matching`; it cannot replace the published weighted-v1 score or ranking.

When VECTOR is `UNAVAILABLE` or `NOT_INVOKED`, the shadow result uses the published
weighted-v1 ranking exactly and emits no fabricated RRF score. Candidate absence from an
individual channel is recorded as a null channel rank. Business `UNKNOWN` and `MISSING`
signals remain separate named diagnostics and are never coerced to zero, false, or mismatch.

## Labeled fixture result

Fixture: `tests/fixtures/matching/hybrid-rrf-shadow.v1.json`

| Metric | weighted-v1 | RRF shadow | Delta |
|---|---:|---:|---:|
| Average Recall@K | 0.777778 | 0.888889 | +0.111111 |
| Average NDCG@K | 0.795522 | 0.947609 | +0.152087 |

The VECTOR-available natural-language scenario improved Recall@3 from 0.666667 to 1.0
and NDCG@3 from 0.386566 to 0.842828. Both fallback scenarios retained their published
order and metrics exactly. All UNKNOWN/MISSING preservation and shadow-promotion gates pass.

Reproducibility fingerprints:

- Fixture input: `a405a746454b45521647fca7007e711212b88e85ae1fcc82161358286ad4a0be`
- Evaluation result: `d03eaa9c1598e93cdb4c1392cd89c38362fa7ba214fed1ebce7c6364a1773f05`

## Verification

- Focused facade/evaluator: 30 passed
- Root suite: 54 passed
- Backend suite: 197 passed, 2 skipped
- Existing matching golden set: 3/3 PASS; Recall@3 1.0, NDCG@3 1.0
- Ruff: PASS
- `compileall`: PASS
- `pip check`: PASS
- `git diff --check`: PASS

The two skipped backend tests remain the pre-existing PostgreSQL integration skips. No public
API, database schema, runtime ranking policy, provider call, or UI behavior changed.

## Promotion gate

This evidence is suitable only for further shadow collection. Production promotion requires a
separate approved, versioned contract decision with a larger judged set, runtime shadow telemetry,
privacy review, and rollback criteria.
