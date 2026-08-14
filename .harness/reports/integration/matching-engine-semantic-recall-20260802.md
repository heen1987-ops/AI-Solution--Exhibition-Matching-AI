# AIENGINE-001 Common Matching Engine — Profile Semantic Recall

Date: 2026-08-02

Decision: DECISION-008

Gate: Wave 2 / G2_FEATURE_COMPLETE remains in progress

## Outcome

The shared recommendation pipeline now performs real profile-to-catalog semantic candidate recall.
The previous `ai.object_embedding` existence check always returned an empty vector channel even after
AISEARCH-002 had deployed model lineage, catalog embeddings, and filtered pgvector HNSW search.

`PROFILE_SEMANTIC_RECALL_V1` now:

1. builds a deterministic, versioned profile query from the published ontology;
2. calls the existing fail-soft embedding and SUMMARY pgvector adapter;
3. maps participation hits to exhibitor/booth/product candidates;
4. caps each participation at three vector-recalled objects;
5. records semantic score, model version, and profile-input fingerprint; and
6. passes the expanded pool to the unchanged Hard Filter and deterministic rank pipeline.

## Engine boundary

- Semantic similarity is recall-only and cannot admit an ineligible object or alter a final score.
- The stage-10 Hard Filter evaluation ID remains mandatory before B2C/B2B scoring.
- Published scoring weights, missing-signal renormalization, reciprocal matching, context reranking,
  slate policy, grounded explanation, and persistence contracts are unchanged.
- Candidate ordering uses stable score/type/object-ID tie-breaks. Product-rich participations cannot
  consume the whole vector pool.
- When semantic search is disabled or its provider/pgvector channel is unavailable, the engine keeps
  structured, popularity, interest, and exploration recall. The feature remains opt-in by default.

## Privacy boundary

Embedding input contains only catalog-owned ontology codes and public Korean labels plus their
requirement level/goal priority, taxonomy version, engine version, and audience type. It excludes:

- profile, user, guest-session, visit-session, tenant, and event identifiers;
- `raw_context` and all other free-form user text;
- unknown/arbitrary codes and EXCLUDED preferences;
- confidence/source metadata; and
- numeric buyer constraints such as price, MOQ, or capacity.

Personalized recommendation consent is validated before profile resolution. Query text and vectors
are not logged by the embedding adapter.

## Verification

- Focused semantic/recommendation tests: `30 passed`.
- Full backend suite: `178 passed, 2 skipped`.
- Root deterministic scoring and ontology suite: `24 passed`.
- Targeted Ruff format/import/lint and `git diff --check`: pass.
- Unit coverage proves deterministic input ordering/fingerprints, privacy allowlisting, no provider
  call for empty profiles, adapter delegation, candidate-generator wiring, participation caps,
  provenance, and the invariant that semantic recall does not mutate final score.

The two skipped backend tests require explicitly configured live PostgreSQL. Real provider,
pgvector ANN/exact recall, latency, and cost measurements remain the existing G3 operational checks.

## Next engine task

AIENGINE-002 will add a versioned general-visitor/buyer/reciprocal golden set and offline evaluator for
Recall@K, NDCG@K, Hard Filter violations, concentration, deterministic fingerprints, and semantic
fallback regression. Service-surface work such as favorites stays deferred while this engine evidence
is established.
