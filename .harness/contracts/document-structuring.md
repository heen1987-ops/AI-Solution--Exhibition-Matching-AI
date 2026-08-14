# Contract: exhibitor-document → AI-extraction → review → search-index pipeline

> Task: CONTRACTS-STRUCTURING (WAVE 2D). Contracts only — no `apps/**` code was touched by this
> task. Source grounding: `AGENTS.md` mandatory invariants (esp. #5 "store provenance, evidence
> references, review state" and #7 "AI output is a proposal"), `docs/08-exhibitor-product-profile-model.md`
> §14–16 (common attribute fields, data-source codes, confidence baseline table) and §10.3
> (existing `SELF_DECLARED → DOCUMENT_SUBMITTED → OPERATOR_REVIEWED → VERIFIED/EXPIRED/REJECTED`
> certification-verification state machine, which this contract's document/extraction pipeline is
> modeled after but does **not** replace), `PROJECT_SCOPE.md` module 3 ("exhibitor-content AI
> structuring, approval workflow"), and the existing `apps/api/app/api/v1/routers/partner.py` /
> `apps/api/app/models/ai.py` (`ai.model_version`, `ai.ai_run`) prior art.
>
> This file is a snapshot for other tracks to consume without reading the full handoff narrative.
> The rationale, open questions, and integration notes live in
> [.harness/handoffs/contracts/WAVE2D-CONTRACTS.md](../handoffs/contracts/WAVE2D-CONTRACTS.md).
> **Not yet implemented** — no migration, model, schema, or router exists for this pipeline yet.
> A future BACKEND track task must implement this against
> `apps/api/app/models/document.py` (new), `apps/api/app/schemas/document.py` (new),
> `apps/api/app/api/v1/routers/partner.py` (extend) and a new `apps/api/app/api/v1/routers/admin.py`
> (or extend an existing admin router if one lands first), plus an Alembic migration chained onto
> the current head (`alembic heads` — verify before authoring).

## 1. Document status machine

Enum: `document_status`

| Status | Meaning | Entered from |
|---|---|---|
| `UPLOADED` | Binary stored (object storage), row created, not yet validated | (initial) |
| `VALIDATING` | Async virus scan / MIME / size / page-count check running | `UPLOADED` |
| `VALID` | Passed validation, queued for parsing | `VALIDATING` |
| `QUARANTINED` | Failed validation (malware, disallowed MIME, corrupt) — never processed further, never downloadable by anyone but an operator investigating it | `VALIDATING` |
| `PARSING` | Text/layout extraction running (PDF/DOCX/image OCR pipeline) | `VALID`, `OCR_REQUIRED` |
| `PARSED` | Raw text + page/section structure available | `PARSING` |
| `OCR_REQUIRED` | Parser detected an image-only page range that needs OCR before extraction can proceed | `PARSING` |
| `EXTRACTING` | AI attribute-extraction run in flight (`ai.ai_run` with `task_type='ATTRIBUTE_EXTRACTION'`) | `PARSED` |
| `EXTRACTED` | AI run finished; `extracted_attribute` rows created with `review_status='PROPOSED'` | `EXTRACTING` |
| `EXHIBITOR_REVIEW` | Exhibitor is confirming/editing/rejecting proposed attributes | `EXTRACTED` |
| `OPERATOR_REVIEW` | Exhibitor finished their pass (or the document type/attribute mix requires operator review regardless — see fact_type rule in §4); operator is confirming/rejecting | `EXHIBITOR_REVIEW` |
| `APPROVED` | Operator approved; document itself is cleared, but this does **not** mean every attribute is published — see §4 fact_type/visibility rules per attribute | `OPERATOR_REVIEW` |
| `PUBLISHED` | At least one attribute derived from this document has reached a public-eligible `review_status` and been written to the search/recommendation index | `APPROVED` |
| `REJECTED` | Operator rejected the document (e.g. wrong document type, unreadable, fabricated-looking) | `OPERATOR_REVIEW` |
| `PROCESSING_FAILED` | Unrecoverable pipeline error (parser crash, AI run `validation_status='FAILED'`, timeout) — always re-triable back to the step that failed | `VALIDATING`, `PARSING`, `EXTRACTING` |
| `DELETED` | Soft-deleted by exhibitor or operator (right-to-delete / retention policy). Binary is purged from object storage on a retention job; row and provenance trail are retained per `docs/frontend-backend-ai-interface-spec.md` privacy invariants | any status except `QUARANTINED` mid-scan |

### Allowed transitions

```text
UPLOADED        -> VALIDATING
VALIDATING      -> VALID | QUARANTINED
VALID           -> PARSING
PARSING         -> PARSED | OCR_REQUIRED | PROCESSING_FAILED
OCR_REQUIRED    -> PARSING            # after OCR sub-step completes, re-enter PARSING
PARSED          -> EXTRACTING
EXTRACTING      -> EXTRACTED | PROCESSING_FAILED
EXTRACTED       -> EXHIBITOR_REVIEW
EXHIBITOR_REVIEW -> OPERATOR_REVIEW
OPERATOR_REVIEW -> APPROVED | REJECTED | EXHIBITOR_REVIEW   # "request changes" bounces back
APPROVED        -> PUBLISHED
PROCESSING_FAILED -> VALIDATING | PARSING | EXTRACTING       # manual/automatic retry re-enters the step that failed
QUARANTINED     -> (terminal; operator-only manual deletion path, out of scope for this contract)
REJECTED        -> (terminal, but exhibitor may re-upload a new document — new row, not a transition)
* -> DELETED     # from any non-QUARANTINED, non-DELETED status
```

Invariants:
- `PUBLISHED` is only reachable via `APPROVED`; nothing may write to the search/recommendation
  index from any earlier status (enforces AGENTS.md invariant: "unapproved exhibitor data never
  reaches public search/recommendation/kiosk results").
- `PROCESSING_FAILED` always records which prior status it failed from (`failed_from_status`
  field) so a retry job knows which step to re-run.
- A document may be re-submitted for a fresh AI pass (e.g. exhibitor edited underlying facts and
  re-uploads) — this creates a **new** `partner_document` row referencing the same
  `exhibitor_id`/`document_type`; it does not rewind an existing row's status backward except via
  the explicit `OPERATOR_REVIEW -> EXHIBITOR_REVIEW` "request changes" edge.

## 2. Document type enum

Enum: `document_type`

| Code | Meaning | Default visibility tier (see §5) |
|---|---|---|
| `COMPANY_PROFILE` | 회사소개서 — general company narrative, history, capability overview | `PUBLIC` (once attributes are approved) |
| `PRODUCT_CATALOG` | 제품 카탈로그 — multi-product listing | `PUBLIC` |
| `PRODUCT_SPECIFICATION` | 개별 제품 스펙시트 (맛/향/도수/원재료 등) | `PUBLIC` |
| `TRADE_INFORMATION` | 거래조건 관련 문서 (MOQ, 가격표 성격이 아닌 일반 거래조건 서술) | `REGISTERED_USER` |
| `CERTIFICATE` | 인증서/수상 증빙 — feeds `docs/08-exhibitor-product-profile-model.md` §10.3 verification state, not this document's own status machine | `PUBLIC` (the *fact* "certified" is public; the certificate *file* stays `OPERATOR_ONLY`) |
| `BROCHURE` | 브로슈어/홍보자료 | `PUBLIC` |
| `PRICE_LIST` | 가격표 — **defaults to a non-public visibility tier** per this track's explicit instruction | `VERIFIED_BUYER` (never `PUBLIC` by default; an operator may explicitly widen a specific attribute's visibility, but the *document type default* stays non-public) |

`PRICE_LIST`'s non-public default is a deliberate exception to "approved docs are public" — pricing
is commercially sensitive and export/wholesale price ranges already have a dedicated structured
field (`exhibition.trade_condition.wholesale_price_min_amount/max_amount`) with its own
`approval_status` gate in `partner.py`. Free-text price-list documents feed AI-extracted attributes
that corroborate or propose values for that structured field, but the source *document* itself
should not be publicly downloadable.

## 3. Extracted-attribute review-status enum

Enum: `extraction_review_status`

| Status | Meaning |
|---|---|
| `PROPOSED` | AI produced this value; nobody has looked at it yet |
| `CONFIRMED_BY_EXHIBITOR` | Exhibitor reviewed and accepted the value as-is |
| `MODIFIED_BY_EXHIBITOR` | Exhibitor reviewed and edited the value before accepting (original AI proposal retained in `proposed_value`; edited value goes in `normalized_value` — see §7 shape) |
| `REJECTED_BY_EXHIBITOR` | Exhibitor says this is wrong / not applicable; excluded from operator review and from publication |
| `APPROVED_BY_OPERATOR` | Operator confirmed the value is publication-eligible at its `visibility` tier |
| `REJECTED_BY_OPERATOR` | Operator overrides an exhibitor confirmation (e.g. contradicts other evidence, looks fabricated, violates the "AI must never assert a value the source text does not contain" invariant) |
| `CONFLICTED` | Two or more extractions (same `entity_reference` + `attribute_code`, different `document_id` or a different AI run) disagree and neither has been resolved yet — blocks auto-publication regardless of individual review_status until an operator picks a winner or marks both `SUPERSEDED` |
| `SUPERSEDED` | A newer extraction (new document version, new AI run, or manual correction) replaces this row; kept for audit/provenance, never used for publication or re-review |

### Allowed transitions

```text
PROPOSED -> CONFIRMED_BY_EXHIBITOR | MODIFIED_BY_EXHIBITOR | REJECTED_BY_EXHIBITOR
PROPOSED -> CONFLICTED                # detected automatically when a colliding proposal appears
CONFIRMED_BY_EXHIBITOR | MODIFIED_BY_EXHIBITOR -> APPROVED_BY_OPERATOR | REJECTED_BY_OPERATOR
CONFLICTED -> APPROVED_BY_OPERATOR | REJECTED_BY_OPERATOR | SUPERSEDED   # operator resolves manually
* -> SUPERSEDED                        # newer extraction/correction arrives; not user-facing, system-driven
```

`REJECTED_BY_EXHIBITOR` is terminal for that row (the exhibitor's own document, their own call —
an operator does not need to re-litigate a rejection the exhibitor themselves made unless they
independently pull the same fact from another approved source, which is a new row).

## 4. Fact-type enum and publication eligibility rule

Enum: `fact_type`

| Code | Meaning | Publication rule |
|---|---|---|
| `SOURCE_FACT` | Directly, literally present in the source document text at the cited `evidence` span (e.g. document says "알코올 도수 40%" and `proposed_value` is exactly `40`) | Eligible for publication once `review_status` reaches `CONFIRMED_BY_EXHIBITOR`/`MODIFIED_BY_EXHIBITOR` **and** `APPROVED_BY_OPERATOR` — no extra scrutiny beyond the normal two-step review |
| `SELF_DECLARED` | Exhibitor typed the value directly into a form field (not derived from a document at all) | Same as `SOURCE_FACT` — reuses `docs/08-exhibitor-product-profile-model.md` §15 `EXHIBITOR_ENTERED`/`EXHIBITOR_CONFIRMED` semantics; included here for schema completeness even though it does not originate from this document pipeline |
| `AI_INFERRED` | AI derived/paraphrased/categorized a value that is not a literal quote (e.g. mapping free text to an ontology concept code, summarizing "단맛이 적고 깔끔한 맛" into a taste concept, inferring an implied trade capability) | **Requires explicit confirmation + approval** — must pass through `EXHIBITOR_REVIEW` (cannot be silently auto-confirmed) and `OPERATOR_REVIEW` with the operator UI surfacing the `evidence` span so a human can judge the inference, not just the literal text. The operator's review queue (`GET /admin/ai-review`, §9) MUST be filterable/sortable to surface `AI_INFERRED` rows first. |
| `CALCULATED` | Derived deterministically from other already-approved structured fields (e.g. completeness score inputs), not from free text at all | Not itself operator-reviewable (no evidence span); publication eligibility inherits from its inputs. Included for schema completeness / consistency with `ai.ai_run.task_type` conventions; the document-structuring pipeline in this contract does not currently produce `CALCULATED` rows. |
| `UNKNOWN` | AI explicitly could not determine a value the schema asked for | **Never** eligible for publication and never coerced to a boolean/enum default. Enforces AGENTS.md: "Unknown stays UNKNOWN, never silently coerced to YES or NO." A row with `fact_type='UNKNOWN'` should generally not even be created unless the schema needs an explicit "AI looked and found nothing" marker (e.g. to suppress a duplicate future extraction attempt) — implementers should default to omitting the attribute rather than emitting an `UNKNOWN` row, except where the consuming schema requires an explicit absence marker. |

Binding rule (repeated from the task instruction, load-bearing): **only `SOURCE_FACT` and
`SELF_DECLARED` are eligible for publication without extra operator scrutiny.** `AI_INFERRED`
always requires the full exhibitor-confirm + operator-approve path — an `AI_INFERRED` row must
never reach `review_status='APPROVED_BY_OPERATOR'` by any path that skips
`EXHIBITOR_REVIEW`/`OPERATOR_REVIEW` (e.g. no bulk-approve shortcut may apply to `AI_INFERRED`
rows).

## 5. Visibility enum

Enum: `attribute_visibility`

| Code | Who can see it | Notes |
|---|---|---|
| `PUBLIC` | Anonymous kiosk visitors, unauthenticated web visitors, everyone | Default for most approved company/product attributes |
| `REGISTERED_USER` | Any authenticated web user (general visitor or buyer), not anonymous kiosk | e.g. `TRADE_INFORMATION` narrative content |
| `VERIFIED_BUYER` | Authenticated users with a verified buyer role/profile | e.g. `PRICE_LIST`-derived attributes, detailed trade capability |
| `MEETING_ACCEPTED` | Only counterparties in an `interaction.meeting_request` with `status='ACCEPTED'` (and the existing contact-share-consent gates in `meetings.py`) | Reserved for anything approaching contact/negotiation detail; this pipeline should rarely need this tier since business-contact info is out of scope for document extraction, but it exists for completeness (e.g. a document that happens to mention a direct contact channel must never be extracted at a looser tier) |
| `OPERATOR_ONLY` | Operators/admins only | Certificate/price-list source files themselves (§2), `QUARANTINED` documents, `REJECTED_BY_OPERATOR` extraction rows kept for audit |

Visibility is set **per extracted attribute**, not just per document — an operator may approve one
attribute from a `COMPANY_PROFILE` document at `PUBLIC` while leaving another at a tighter tier if
its content warrants it (e.g. the document mentions an internal production capacity number that
the exhibitor didn't intend to publish verbatim). The document's own default (§2 table) is only the
*starting* visibility a newly `PROPOSED` extraction inherits, not a ceiling the operator cannot
override in either direction — but operators tightening visibility does not itself require
re-review; operators *widening* visibility beyond the document-type default requires the row to be
at `APPROVED_BY_OPERATOR` already.

## 6. Evidence object shape

Every extracted attribute must carry an `evidence` object so a reviewer can jump straight to the
source. This also satisfies AGENTS.md invariant #5 ("store provenance, evidence references").

```json
{
  "document_id": "uuid",
  "page_number": 3,
  "section_title": "제품 특징",
  "text_start": 128,
  "text_end": 171,
  "evidence_text": "지역 쌀을 증류하여 만든 전통 소주, 단맛이 적고 깔끔한 맛",
  "evidence_hash": "sha256:9f2c...ab"
}
```

| Field | Type | Notes |
|---|---|---|
| `document_id` | UUID | FK to `partner_document.document_id` |
| `page_number` | integer, nullable | 1-based; `null` for non-paginated formats (plain text) or when OCR could not determine page boundaries |
| `section_title` | string, nullable | Best-effort heading/section the span falls under, from parser structure detection; `null` if the parser found no heading |
| `text_start` | integer | 0-based character offset into the document's *parsed plain-text* representation (not the original binary) |
| `text_end` | integer | Exclusive end offset; `text_end > text_start` always |
| `evidence_text` | string | The literal quoted span — for `AI_INFERRED` rows this is the literal text the inference was drawn *from*, not a paraphrase; the paraphrase itself lives in `proposed_value` |
| `evidence_hash` | string | `"sha256:" + hex digest` of `evidence_text` (UTF-8), following the same plain-hash-for-change-detection convention as `services/ingestion.py`'s `hash_payload` — used to detect when a document's underlying parsed text changes and invalidate/re-flag evidence spans that no longer match |

`evidence_hash` mismatch handling: if a document is re-parsed (e.g. improved OCR pass) and the
recomputed hash for an existing evidence span's `[text_start, text_end)` no longer matches
`evidence_hash`, the extraction row must be flagged (`review_status` moved to `CONFLICTED` is the
simplest reuse of the existing enum rather than adding a tenth status) rather than silently kept.

## 7. Extracted-attribute JSON shape

This is the payload shape for `GET /partner/documents/{id}/extractions` list items, the body of
`PATCH /partner/extractions/{id}`, and the row shape backing `admin.ai-review` queue items.

```json
{
  "extraction_id": "uuid",
  "entity_type": "PRODUCT",
  "entity_reference": "uuid",
  "attribute_code": "PRODUCT.TASTE.SWEETNESS",
  "proposed_value": "단맛이 적음",
  "normalized_value": {"concept_id": "uuid", "taxonomy_version_id": "uuid"},
  "concept_codes": ["ALCOHOL.TASTE.LOW_SWEETNESS"],
  "fact_type": "AI_INFERRED",
  "confidence": 0.62,
  "review_status": "PROPOSED",
  "visibility": "PUBLIC",
  "evidence": {
    "document_id": "uuid",
    "page_number": 3,
    "section_title": "제품 특징",
    "text_start": 128,
    "text_end": 171,
    "evidence_text": "단맛이 적고 깔끔한 맛",
    "evidence_hash": "sha256:9f2c...ab"
  }
}
```

| Field | Type | Notes |
|---|---|---|
| `extraction_id` | UUID | Primary key |
| `entity_type` | enum: `EXHIBITOR` \| `PRODUCT` \| `TRADE_CONDITION` \| `CERTIFICATE` | What kind of business entity this attribute attaches to; mirrors existing entities in `apps/api/app/models/exhibitor.py`, does not invent new ones |
| `entity_reference` | UUID | FK to the entity row (`exhibitor.exhibitor_id`, `exhibition.product.product_id`, etc.) depending on `entity_type` — polymorphic, not a DB-level FK constraint (same pattern risk as any polymorphic ref; unlike `matching.recommendable` this is intentionally *not* routed through that registry because it references pre-approval draft entities the recommendable registry should never see) |
| `attribute_code` | string | Ontology-adjacent attribute code. Must resolve against either (a) the canonical 259-concept catalog (`concept_codes`, below) for taste/aroma/usage/category-type attributes, or (b) an existing named column/JSON key on the target entity (e.g. `alcohol_percentage`, `min_order_quantity`) for structured scalar fields. Never a free-invented code. |
| `proposed_value` | string \| number \| boolean \| object | The AI's raw proposal, always kept even after edits |
| `normalized_value` | object \| scalar, nullable | The value in the shape the target column/ontology reference actually expects (e.g. `{concept_id, taxonomy_version_id}` for an ontology-backed attribute, a plain number for `alcohol_percentage`). `null` until normalization succeeds; an extraction with `normalized_value = null` cannot progress past `EXHIBITOR_REVIEW`'s confirm action into a form that would write structured data (confirming a null-normalized row is still just a review-status change, not a publish) |
| `concept_codes` | array of string, nullable | Zero or more codes from `src/meet_ai/ontology/catalog.v1.json` (DECISION-004 — the 259-concept catalog is canonical). Empty/`null` for attributes that are plain scalars, not ontology concepts |
| `fact_type` | enum (§4) | |
| `confidence` | number 0.0–1.0 | Model-reported confidence; combine with `docs/08-exhibitor-product-profile-model.md` §16.1 baseline table downstream, do not treat this field alone as the final trust score |
| `review_status` | enum (§3) | |
| `visibility` | enum (§5) | |
| `evidence` | object (§6) | |

Additional row-level fields not shown in the illustrative JSON above (present on the DB row / full
API representation, omitted from the example for readability): `document_id` (denormalized from
`evidence.document_id` for indexing), `ai_run_id` (FK to `ai.ai_run.ai_run_id` — links every
extraction back to the exact model version/prompt version that produced it, per `ai.py`'s existing
provenance pattern), `created_at`, `reviewed_by_exhibitor_user_id`/`reviewed_at`,
`reviewed_by_operator_user_id`/`reviewed_at`, `superseded_by_extraction_id` (nullable self-FK, set
when `review_status='SUPERSEDED'`).

## 8. Entity relationship summary (informative — implementer designs the actual columns)

```text
exhibition.exhibitor (existing)
  └─< partner_document (new: document_id, exhibitor_id, document_type, status, storage_key, ...)
        └─< ai.ai_run (existing: task_type='ATTRIBUTE_EXTRACTION', input_reference_id=document_id)
              └─< extracted_attribute (new: extraction_id, ai_run_id, document_id, entity_type,
                                        entity_reference, attribute_code, ..., per §7)
```

`partner_document` and `extracted_attribute` are new tables; they belong under the `ai` or a new
`document` Postgres schema per implementer judgment — this contract does not mandate the schema
name, only the field/enum shapes above, since schema-naming is a CONTRACTS/BACKEND implementation
decision at migration-authoring time, not something this track should freeze prematurely without
seeing how it composes with `ai.model_version`/`ai.ai_run`.

## 9. Endpoints (paths only — request/response bodies derive from §1–§7 shapes above)

All paths below assume the existing `apps/api/app/api/v1/routers/<domain>.py` convention
(ASSUMPTION-003) and the existing no-own-prefix pattern used by `partner.py` (final path is
`<API_V1_PREFIX>/...`, no `router = APIRouter(prefix=...)`).

### Exhibitor-facing — extend `apps/api/app/api/v1/routers/partner.py`

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/partner/documents` | Upload a new document (`document_type`, `exhibitor_id`, binary) → creates row in `UPLOADED` |
| `GET` | `/partner/documents` | List the exhibitor's own documents (filter by `document_type`, `status`) |
| `DELETE` | `/partner/documents/{id}` | Soft-delete → `DELETED` transition (§1); only from a non-`QUARANTINED` status, and only the owning exhibitor or an operator |
| `POST` | `/partner/documents/{id}/process` | Explicitly (re-)trigger the parse→extract pipeline from `VALID`/`PARSED`/`PROCESSING_FAILED`; most of the time this should happen automatically on upload, but this endpoint exists for manual retry and for re-running extraction after the exhibitor edits underlying source data |
| `GET` | `/partner/documents/{id}/extractions` | List `extracted_attribute` rows for this document, shape per §7 |
| `PATCH` | `/partner/extractions/{id}` | Exhibitor edits `normalized_value` before confirming (produces `review_status='MODIFIED_BY_EXHIBITOR'` when combined with confirm, or is a plain edit that stays `PROPOSED` until confirm is called separately — implementer's choice, but must not silently flip to `CONFIRMED_BY_EXHIBITOR` on a bare `PATCH`) |
| `POST` | `/partner/extractions/{id}/confirm` | Exhibitor confirms (`PROPOSED`/`MODIFIED_BY_EXHIBITOR` → `CONFIRMED_BY_EXHIBITOR`) or rejects (`REJECTED_BY_EXHIBITOR`) — request body carries the decision, this single endpoint covers both per the task's endpoint list (do not split into a separate reject endpoint) |
| `POST` | `/partner/extractions/submit-review` | Batch-submit: moves the parent document(s) from `EXHIBITOR_REVIEW` → `OPERATOR_REVIEW` once the exhibitor has dispositioned every `PROPOSED` row (blocks with `VALIDATION_FAILED` / a dedicated `EXTRACTIONS_PENDING_REVIEW` error code — add to `.harness/contracts/error-codes.yaml` at implementation time — if any row is still `PROPOSED`) |

### Operator-facing — new `apps/api/app/api/v1/routers/admin.py` (or an existing admin router, if
one lands first from another track — check before creating a duplicate, per the standing "check
for prior art" rule)

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/admin/ai-review` | Queue of documents/extractions in `OPERATOR_REVIEW`, filterable by `fact_type` (must support surfacing `AI_INFERRED` first per §4), `document_type`, `exhibitor_id` |
| `POST` | `/admin/ai-review` | (as listed in the task's endpoint set) — reserved for operator-initiated review actions that aren't tied to one existing extraction/document id, e.g. bulk re-queue; exact semantics left to the implementer since the task only specifies the path, not payload |
| `POST` | `/admin/ai-review/{id}/approve` | `review_status → APPROVED_BY_OPERATOR` for an extraction, or document `OPERATOR_REVIEW → APPROVED` for a document-level id — implementer decides whether `{id}` is an `extraction_id` or `document_id` (or supports both with a discriminator), but the AI_INFERRED gate in §4 applies either way |
| `POST` | `/admin/ai-review/{id}/reject` | → `REJECTED_BY_OPERATOR` / document `REJECTED` |
| `POST` | `/admin/ai-review/{id}/request-changes` | Document `OPERATOR_REVIEW → EXHIBITOR_REVIEW` bounce-back (§1); should carry an operator comment field so the exhibitor knows what to fix (field name/shape left to implementer) |

## 10. Cross-cutting bindings to existing invariants

- No row may reach the search/recommendation index (kiosk or web) unless its document is
  `PUBLISHED` **and** the specific attribute's `review_status ∈ {APPROVED_BY_OPERATOR}` **and**
  its `visibility` tier matches or is looser than the requesting surface's clearance.
- `PRICE_LIST` documents and any attribute they produce must never default to `PUBLIC` (binding
  instruction from the task; see §2, §5).
- `AI_INFERRED` attributes must never skip exhibitor+operator confirmation (§4).
- `UNKNOWN`/absent values must never be coerced to a concrete YES/NO or a default enum member
  anywhere in this pipeline.
- Ontology concept codes in `concept_codes` (§7) must validate against the canonical 259-concept
  catalog (DECISION-004) — no ad hoc codes.
- This pipeline produces **draft/proposal data** only until `APPROVED`; nothing here bypasses the
  existing `ExhibitorProfile.approval_status` / `Product.master_approval_status` /
  `TradeCondition.approval_status` gates already enforced in `partner.py` — an approved extraction
  feeds *into* those existing fields' values (or into their §27 supply-profile companions in
  `exhibitor.py`), it does not add a second independent path to publication.
