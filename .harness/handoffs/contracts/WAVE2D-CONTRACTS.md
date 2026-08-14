# WAVE2D-CONTRACTS handoff — document-structuring pipeline

Track: CONTRACTS-STRUCTURING (WAVE 2D)
Status: contract defined, **no app code implemented yet** (out of scope for this task — contracts
only, per task instruction "Do not touch app code, contracts only").
Deliverables: this file + [.harness/contracts/document-structuring.md](../../contracts/document-structuring.md)
(the consumable snapshot — read that one for the actual enum/shape/endpoint definitions; this file
is the narrative/rationale/handoff).

## What this defines

The contract for the pipeline: exhibitor uploads a document → AI extracts candidate attributes →
exhibitor reviews/confirms → operator reviews/approves → approved, publication-eligible attributes
become available to feed the existing search/recommendation index (via the existing
`ExhibitorProfile`/`Product`/`TradeCondition`/§27 supply-profile `approval_status` gates already in
`apps/api/app/models/exhibitor.py` and enforced in `apps/api/app/api/v1/routers/partner.py` — this
pipeline does not add a second independent publication path).

Covers, per the task's explicit scope:
1. Document status machine (15 statuses, explicit transition table)
2. Document type enum (7 types) — `PRICE_LIST` defaults to non-public visibility
3. Extracted-attribute review-status enum (8 statuses)
4. Fact-type enum (5 values) with the binding publication-eligibility rule
5. Visibility enum (5 tiers)
6. Evidence object shape
7. Extracted-attribute JSON shape
8. Endpoint paths (exhibitor-facing on `partner.py`, operator-facing on a new `admin.py`)

## Prior art checked before writing this (per the mandatory "check for prior art" rule)

- `apps/api/app/api/v1/routers/partner.py` — existing exhibitor-facing router (profile/product/
  trade-condition/buyer-preference/submit). No document/extraction endpoints exist yet. This
  contract extends it rather than proposing a parallel router.
- `apps/api/app/models/ai.py` — `ai.model_version` (provider-neutral model registry) and
  `ai.ai_run` (append-only validated AI invocation record, already has
  `task_type IN ('ATTRIBUTE_EXTRACTION', 'EXPLANATION', 'EMBEDDING')` and
  `validation_status IN ('VALID', 'INVALID', 'REVIEW', 'FAILED')`). The new `extracted_attribute`
  table this contract implies should FK to `ai.ai_run.ai_run_id`, not duplicate its provenance
  fields (model/prompt version, cost, latency already live there).
- `apps/api/app/services/ingestion.py` — existing idempotent upsert pattern for source-system data
  (`hash_payload` sha256-of-sorted-JSON convention). Reused the same "plain hash for change
  detection, not security" convention for `evidence_hash` in §6 of the contract, for consistency.
- `docs/08-exhibitor-product-profile-model.md` §10.3 — an **existing, separate** verification state
  machine (`SELF_DECLARED → DOCUMENT_SUBMITTED → OPERATOR_REVIEWED → VERIFIED/EXPIRED/REJECTED`)
  for certificate/award verification. This is a different, narrower state machine than the one this
  contract defines (it tracks the *credibility of a claim*, not the *lifecycle of an uploaded file
  through parsing/extraction*). The contract explicitly does not replace or merge with it —
  `CERTIFICATE` documents in this pipeline's `document_type` enum feed evidence *into* that existing
  §10.3 state machine rather than owning it.
- `docs/08-exhibitor-product-profile-model.md` §14–16 — the existing common attribute-field shape
  (`attribute_code`, `value`, `source_type`, `verification_status`, `confidence`, `visibility`,
  `evidence_id`, ...) and the data-source code list (§15: `EXHIBITOR_ENTERED`, `AI_EXTRACTED`,
  `DOCUMENT_VERIFIED`, etc.) and confidence baseline table (§16.1). The new `fact_type` enum in this
  contract is a narrower, extraction-pipeline-specific classification layered on top of — not a
  replacement for — the existing broader `source_type` vocabulary in §15. Implementers should expect
  to map `fact_type` → `source_type` when writing an approved value back into an existing §14-style
  attribute row (e.g. `AI_INFERRED` + `APPROVED_BY_OPERATOR` → `source_type='AI_EXTRACTED'`, later
  possibly `DOCUMENT_VERIFIED` semantics if it corroborates a certificate).
- `apps/api/app/models/exhibitor.py` — confirmed `ProductImage.approval_status` and other
  `REVIEW_STATUSES`/`MASTER_APPROVAL_STATUSES` constants already follow a `CheckConstraint`-backed
  enum pattern (`f"approval_status IN ({_in_list(...)})"`) — the new tables this contract implies
  should follow the same DB-level CHECK-constraint convention, not just Pydantic validation.
- `.harness/decisions.md` DECISION-004 — the 259-concept ontology catalog
  (`src/meet_ai/ontology/catalog.v1.json`) is canonical; `concept_codes` in the extracted-attribute
  shape (§7) must validate against it, never invent new codes.
- `.harness/contracts/error-codes.yaml` — existing catalog/format; this contract references it but
  does not edit it (editing is BACKEND's job at implementation time, when the actual router code
  determines which error codes it throws — this contract only *names* one illustrative code,
  `EXTRACTIONS_PENDING_REVIEW`, as a suggestion, not a commitment).
- Grepped `docs/` for any existing "document/structuring/extraction/ai-review" contract — found only
  scattered mentions (§10.3 verification, `evidence_id`/`evidence_text` field names in
  `docs/08-exhibitor-product-profile-model.md` and `docs/frontend-backend-ai-interface-spec.md`) but
  no prior full pipeline contract. This is genuinely new ground, not a duplicate of existing work.

## Decisions made (Blocker Score < 7, applied a reversible default per the standing instruction)

1. **Where `partner_document`/`extracted_attribute` tables live (schema name).** Left open in §8 of
   the contract snapshot — deferred to whoever authors the actual Alembic migration, since it
   composes with `ai.model_version`/`ai.ai_run` either way and picking `document` vs. reusing `ai`
   as the schema name doesn't change any of the enum/shape contracts above it. Reversible, low
   impact, no privacy/security dimension → did not escalate.
2. **`{id}` discriminator on `/admin/ai-review/{id}/approve|reject|request-changes`.** The task's
   endpoint list gives one `{id}` path shape but two plausible referents (an `extraction_id` for
   granular per-attribute approval, or a `document_id` for the exhibitor-review→operator-review
   document-level gate in §1). Documented both readings in §9 rather than picking one, since an
   implementer will discover which is more ergonomic once the actual review-queue UI shape is
   known (a per-document bulk-approve vs. per-attribute fine-grained approve are both defensible
   and not mutually exclusive — an implementation could support both). Not a blocker: either choice
   is reversible at the API-versioning level before anything consumes it.
3. **`entity_reference` polymorphism style.** Chose *not* to route extracted-attribute entity
   references through `exhibition.recommendable` (the existing polymorphic registry pattern used by
   `matching.py`), specifically because `recommendable` is a registry of *approved, matchable*
   entities and this pipeline necessarily references pre-approval draft entities (a product that
   hasn't been approved yet can still have documents/extractions attached to it). Recorded as an
   explicit deliberate exception per AGENTS.md's "record any deliberate exception in the relevant
   design document before implementing it" — recorded here and in §7 of the contract snapshot,
   before any implementation exists.
4. **`fact_type='UNKNOWN'` row-creation policy.** The task's own enum list includes `UNKNOWN` as a
   value, but AGENTS.md says "Unknown stays UNKNOWN, never silently coerced" — read together, this
   means the enum member must *exist* for schema completeness/defensive coding, but the contract
   recommends implementers default to *omitting* the attribute row entirely rather than manufacturing
   an explicit `UNKNOWN` row for every schema field the AI didn't find anything for (which would be
   noisy and is not what "never silently coerced" is protecting against). Documented as a
   recommendation, not a hard requirement, in §4, since the task didn't specify this level of detail
   and either choice is compatible with the stated invariant.
5. **No new Alembic migration authored.** The task scope is contracts-only ("Do not touch app
   code"); creating a migration would be implementing the model, which is explicitly out of scope
   for this track/wave. Left as a TODO for the BACKEND track that eventually implements this
   contract — noted at the top of `document-structuring.md`.

None of the above met Blocker Score ≥ 7 (no high-impact + hard-to-reverse + privacy/security-risk
combination with zero evidence in existing docs), so none required stopping for user input; all are
recorded per the standing assumption-logging convention (mirroring `.harness/assumptions.md`'s
format, though not added to that shared file since these are contract-drafting judgment calls, not
project-wide assumptions another track would need to discover independently — they're self-contained
within this handoff and the contract snapshot itself).

## What the next implementer (BACKEND track, future wave) needs to do

1. Run `alembic heads` first to find the current chain tip, then author a new migration creating
   `partner_document` and `extracted_attribute` tables (or whatever schema-qualified names are
   chosen per open item #1 above) matching §1–§7 of `document-structuring.md`, with DB-level
   `CheckConstraint`s for every enum (matching the existing `exhibitor.py` convention).
2. Extend `apps/api/app/schemas/partner.py` with request/response models for the five
   exhibitor-facing endpoints in §9.
3. Extend `apps/api/app/api/v1/routers/partner.py` with those five endpoints, reusing the existing
   `get_actor_user_id` / `_require_exhibitor_access` pattern already in that file.
4. Check whether an `apps/api/app/api/v1/routers/admin.py` already exists (another WAVE 2D/2E
   track may have created one for the `BACKEND-007` 관리자API work referenced in
   `.harness/state.json`'s `active_tasks`) before creating a new one for the four operator-facing
   endpoints in §9 — this is exactly the kind of prior-art collision the standing rule warns about.
5. Wire an async worker job (`apps/worker/app/jobs/document_processing.py`, per `apps/worker`'s
   flat-layout convention once that app exists) for the `VALIDATING`→`VALID`/`QUARANTINED` and
   `PARSING`→`PARSED`/`OCR_REQUIRED` and `EXTRACTING`→`EXTRACTED` async steps — none of those
   transitions should happen synchronously inside a request handler.
6. Add whatever error codes the real implementation throws to `.harness/contracts/error-codes.yaml`
   (this task did not edit that file — out of scope — but flagged one illustrative code name,
   `EXTRACTIONS_PENDING_REVIEW`, as a suggestion in §9 of the contract).
7. Re-verify DECISION-004's 259-concept catalog validation is actually enforced wherever
   `concept_codes` gets written (application-level validation, since a bare string array can't carry
   a DB FK the way `(taxonomy_version_id, concept_id)` composite refs do elsewhere in this codebase
   — worth flagging to whoever implements this that `concept_codes` in §7 is a weaker-guarantee field
   than the rest of the schema's ontology references, by design, since extraction proposals are
   drafts and don't get a DB FK until normalized).

## Absolute prohibitions — explicit confirmation

- Did not edit `apps/api/app/api/v1/api.py`. ✅ (not touched)
- Did not edit `apps/api/app/models/__init__.py`. ✅ (not touched)
- Did not edit `apps/user-web/lib/api-client.ts` or `apps/user-web/lib/types.ts`. ✅ (not touched)
- Did not edit any other track's owned paths — only wrote to this track's two owned paths
  (`.harness/contracts/document-structuring.md`, `.harness/handoffs/contracts/WAVE2D-CONTRACTS.md`).
  ✅
- No app code touched at all (models/schemas/routers/services/migrations) — contracts only, as
  instructed. ✅
- No new ontology concept codes invented — the contract only references the existing 259-concept
  catalog by name/convention, does not add codes to it. ✅
- Kiosk/anonymous-data, contact-info-gating, and AI-hallucination-prevention invariants are all
  explicitly re-stated and bound into this contract (§10 of `document-structuring.md`) rather than
  silently assumed. ✅
- Small-group statistics suppression rule: not applicable to this contract (no aggregate/statistics
  surface defined here).
