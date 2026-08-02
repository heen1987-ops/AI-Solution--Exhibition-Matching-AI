# AIENGINE-007 Intent Projection Evidence

Date: 2026-08-03
Status: PASS
Runtime ranking change: NONE

## Outcome

`intent-projection-result-v1.0`, `intent-projection-v1.0`, and
`candidate-capability-v1.0` convert the confirmed output of AIENGINE-006 into a deterministic plan:

- `PREFER` → structured ontology candidate-recall feature only
- verifiable `MUST` → `REQUIRE_MATCH` Hard Filter constraint
- verifiable `EXCLUDE` → `FORBID_MATCH` Hard Filter constraint
- unbound or scope-restricted hard conditions → `INFORMATION_REQUIRED`
- UNKNOWN, UNRESOLVED, and model proposal → deferred diagnostic only

The module does not call candidate retrieval, `execute_matching`, `score_catalog_search`, or any
other score/rank path. `WEIGHTED_V1_UNCHANGED` is emitted as a contract invariant.

## Capability and privacy boundaries

Public catalog bindings contain only public product/category/sensory/use/service fields. Supply
region, distribution channel, trade type, and OEM/PB/export status require
`VERIFIED_BUYER_CATALOG`. A public request carrying a buyer-only condition receives
`CATALOG_SCOPE_RESTRICTED`; the private field is not projected into public retrieval.

Every emitted constraint fixes both `unknown_outcome` and `missing_outcome` to
`INFORMATION_REQUIRED`. This prevents a future adapter from treating absent candidate information
as a pass, mismatch, or numeric zero. Candidate observation evaluation itself is intentionally the
next isolated engine unit.

## Regression fixture

Fixture: `tests/fixtures/matching/intent-projection.v1.json`

Seven scenarios cover:

- natural-language and Excel takju preference parity
- natural-language and Excel buyer OEM-MUST parity
- a MUST with no verifiable candidate field
- buyer-only condition submitted to public scope
- explicit public product exclusion

Parity plan fingerprints:

- Public takju preference: `f54b0e5656735d4f513755b6c9e8575355d866adcab00f9996a51467e0c8eca6`
- Buyer OEM required: `adc22ba9a2a1cef75c0430857267d29429d29a5c4a544c37ffd10d8ef5018935`

Reproducibility fingerprints:

- Fixture SHA-256: `69bd20cf5c488fc0c9960d0fddc927420ae26a40cee080a9b3545468485741ed`
- Combined plan result: `91275ef4f56d36d3af32d9c644c189ef6bdf87115a7f193c0ede7f4a566ba8be`

## Verification

- Focused facade: 25 passed
- Root suite: 67 passed
- Backend suite: 197 passed, 2 skipped
- Ruff: PASS
- `compileall`: PASS
- `pip check`: PASS
- `git diff --check`: PASS

The two skipped backend tests remain the existing PostgreSQL integration skips. No public API,
database schema, active web UI, candidate result, score formula, or published rank changed.

## Next gate

AIENGINE-008 will accept only verified candidate observations and produce one of ELIGIBLE,
FILTERED_OUT, or INFORMATION_REQUIRED. Only ELIGIBLE may become the existing immutable
`EligibilityDecision` consumed by scoring.
