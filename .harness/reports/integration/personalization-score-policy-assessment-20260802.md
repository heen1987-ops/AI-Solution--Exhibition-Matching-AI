# AISEARCH-003 Personalization Score Policy Assessment

Date: 2026-08-02

Decision: `RETAIN_CONSUMER_SCORE_V1`

Future replacement status: `CHANGE_REQUEST_REQUIRED`

## Scope

This assessment compares the published `consumer-score-v1.0` and separated
`context-rerank-v1.0` policies with the simplified web personalization formula in
`docs/vibe-coding-master-spec-v1.md` section 34. It does not compare or alter the buyer and
reciprocal policies.

## Structural comparison

| Section 34 input | Current executable source | Compatibility |
|---|---|---|
| User Interest Match | category, sensory, price, alcohol, service, usage | No single equivalent; collapsing removes dimension-level evidence |
| Current Query Match | No field in `RecommendationRequest` | Missing contract and feature source |
| Visit Goal Match | `goal` | Directly available |
| Explicit Behavior Match | `behavior` plus context `recent_behavior` | Semantics overlap but are not the same published signal |
| Data Quality | `trust` | Close proxy, but current trust can include more than completeness |
| Booth Availability | context `operational_availability` | Already applied after base relevance; moving it would double count or change stage ownership |

The current public recommendation request has only `recommendation_type`, `context`, and `limit`.
It accepts no query text or query-match score. Profile semantic similarity is intentionally a
recall-only channel and is not a final-score component.

## Golden-set compatibility

The visitor Golden Set contains these published inputs:

```text
alcohol, behavior, category, goal, price, sensory, service, trust, usage
```

It does not contain a separately judged current-query signal or booth-availability signal.
Inventing a mapping would make a numeric comparison reproducible but not valid. Therefore the
section-34 candidate is `NOT_COMPARABLE` on the current fixture rather than being reported as better
or worse.

The facade-backed current baseline remains:

- 3/3 scenarios PASS;
- Recall@3 1.0;
- NDCG@3 1.0;
- fallback Recall@3 0.666667; and
- Hard Filter, decision/reason, and explanation violations 0.

## Decision rationale

The simplified formula is not a weight-only patch. Applying it would require all of the following:

1. a new query-bearing recommendation contract or an explicitly separate search-to-recommendation
   handoff;
2. a privacy and retention rule for query-derived signals;
3. a published aggregation rule for the six current interest dimensions;
4. a decision to keep availability in context or move it, never both;
5. explicit behavior-event eligibility and time-decay semantics;
6. a new immutable `consumer-score-v2` policy and DB seed/binding;
7. a labeled v2 Golden Set containing every new input; and
8. shadow evaluation demonstrating non-inferior relevance, safety, diversity, and subgroup behavior.

Those prerequisites affect AI behavior, input semantics, persistence, and possibly OpenAPI. Under
the frozen-contract rules they require an approved Change Request. No such evidence or approved CR
exists, so the safe executable decision is to retain `consumer-score-v1.0` and
`context-rerank-v1.0` unchanged.

## Regression guard

`apps/api/tests/test_personalization_policy_boundary.py` now fails if an unreviewed change:

- replaces the published consumer-v1 dimensions;
- adds query/current-query scoring to the recommendation request implicitly; or
- removes operational availability from the separate context policy.

This guard does not prohibit a future v2. It forces that work to update the versioned contract,
fixtures, and decision evidence intentionally.

## Result

`AISEARCH-003` is complete with a retain decision. No production formula, OpenAPI schema, database
schema, or runtime score changed.

## Verification

- Personalization boundary plus policy-seed/scoring pipeline: `10 passed`.
- Root deterministic engine/evaluator suite: `42 passed`.
- Full backend suite: `183 passed, 2 skipped`.
- Facade-backed Golden Set: `PASS`, Recall@3 `1.0`, NDCG@3 `1.0`, aggregate result fingerprint
  `e9a3db60a421a50a049a6071e6cf0c3e3d98ad0bf94ca09ff4331ec836fec365`.
- Harness JSON/YAML, API-project Ruff/format, and `git diff --check`: pass.
