# AIENGINE-002 Matching Engine Golden Set and Offline Evaluation

Date: 2026-08-02

Gate: Wave 2 / G2_FEATURE_COMPLETE remains in progress

## Published artifacts

- `matching-golden-set-v1` JSON Schema packaged with `meet_ai.evaluation`.
- `backju-matching-gold-v1.0.0` checked-in fixture.
- `matching-evaluator-v1.0` pure Python evaluator and CLI.
- Three required modes: `GENERAL_VISITOR`, `BUYER_TO_EXHIBITOR`, and `RECIPROCAL`.

The evaluator imports the published consumer, buyer, exhibitor, and reciprocal scoring policies. It
does not copy their weights and performs no database, HTTP, embedding, or generative-model call.

## Quality gates

For every scenario the evaluator checks:

- Recall@K and NDCG@K;
- recall retained without the VECTOR channel;
- admission of a gold-ineligible candidate;
- expected versus observed Hard Filter decision and exact reason codes;
- explanation reason allowlisting and non-empty evidence references;
- maximum exhibitor share and HHI in the top K; and
- stable input, score, explanation, scenario, and aggregate fingerprints.

Policy-version drift, ontology-version drift, unknown recall channels, malformed eligibility, and
ambiguous identifiers are rejected before metric calculation. A threshold regression produces a
`FAIL` report and a nonzero CLI exit code unless explicitly run in inspection mode.

## Baseline result

Command:

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
| Maximum exhibitor share per scenario | 0.333333 |
| Exhibitor HHI per scenario | 0.333333 |

Input fingerprint:
`2d58998d49a01e6a4a6f041a1b44b72da493097304513e654eac0dce5a0d61c0`

Result fingerprint:
`08caeccc002d4aaed471395d2827c7775365f1baed5c6093786f15d14e929594`

## Negative controls

Automated tests prove that the gate fails when:

- an expected-ineligible exhibitor is admitted and scored;
- filter decisions or exact reason codes diverge;
- an explanation has no evidence or uses an unapproved reason code;
- structured fallback recall drops beyond the published tolerance;
- policy or taxonomy versions drift; or
- a non-contract recall channel appears.

## Verification

- Root scoring, ontology, and evaluation suite: `35 passed`.
- Full backend suite: `178 passed, 2 skipped`.
- JSON artifacts parse; the schema is present in editable package data.
- Targeted Ruff and `pip check` pass.
- Module CLI passes and emits machine-readable JSON. The generated Windows console-script wrapper was
  blocked by local Application Control; `python -m meet_ai.evaluation` is the verified portable path.

## Evidence boundary and next task

This curated v1 fixture establishes a reproducible regression contract; it does not claim measured
production relevance. Human judgments, live pgvector/provider recall, ANN-versus-exact comparison,
latency, and cost remain explicit G3 operational work.

AIENGINE-003 will now extract a versioned, provider/DB-independent matching command/result facade so
web, kiosk, and platform adapters consume one engine contract instead of owning formulas.
