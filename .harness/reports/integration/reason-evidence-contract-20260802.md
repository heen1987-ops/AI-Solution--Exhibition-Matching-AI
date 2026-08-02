# AIENGINE-004 deterministic reason/evidence contract

## Verdict

PASS. The common engine now owns deterministic reason-claim admission for catalog search,
general visitors, buyers, reciprocal matching, and Hard Filter exclusions. A claim is omitted unless
both an allowlisted scored/state signal and at least one nonblank adapter-provided `evidence_ref`
exist. Template rendering cannot introduce a new fact or reason code.

## Published boundary

- New immutable contracts: `matching-engine-command-v1.1` and
  `matching-engine-result-v1.1`.
- `matching-engine-command-v1.0` remains accepted only without reason evidence and returns the
  historical v1.0 result contract. It fails closed if v1.1 evidence is supplied.
- `reason-claim-v1.0` records reason code, sorted evidence refs, source score/search/filter
  components, contribution, and a canonical SHA-256 claim fingerprint.
- The result fingerprint now covers generated reason claims. The score calculation fingerprint
  remains separate and unchanged.
- LLM/provider, FastAPI, SQLAlchemy, network, and database imports remain outside the pure facade.

## Benchmark alignment

The supplied exhibition-personalization benchmark was applied as an engine constraint:

- Hard Filter remains before ranking.
- Visitor, buyer, and reciprocal explanations use different allowlisted score/state mappings.
- Semantic reasons require an actual VECTOR recall channel plus approved-summary evidence.
- Reciprocal claims use both directional contributions; imbalance claims use both directional
  score fingerprints.
- Runtime explanation rendering consumes facade claims. Raw feature ranking remains only as a
  compatibility path for isolated callers that have no score provenance.
- No learned reranker, online retraining, or event-time policy promotion was introduced.

## Golden Set change

The legacy fixture `explanations` entries are now treated as adapter evidence bindings. The
evaluator sends them into the facade and validates the generated `ReasonClaim` output, including
expected code coverage, evidence presence, source components, and fingerprints. Removing one
evidence binding produces `EXPLANATION_GROUNDING_VIOLATION`.

## Verification

- Root tests: `45 passed`.
- API tests: `184 passed, 2 skipped`.
- Focused Ruff: PASS.
- `pip check`: PASS.
- `git diff --check`: PASS (line-ending notices only).
- Golden Set: 3/3 PASS; explanation violations 0.

The two skipped tests still require the existing PostgreSQL integration configuration. Existing
Starlette/FastAPI deprecation warnings are unrelated to this unit.
