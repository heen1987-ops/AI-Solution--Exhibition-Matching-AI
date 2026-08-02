# Run Log

## 2026-08-02 — WAVE 0 Bootstrap

- 하네스 디렉터리 구조 생성(`.harness/contracts`, `handoffs/{7개 트랙}`, `reports/{5개 영역}`)
- `AGENTS.md`에 하네스 규칙 병합(기존 ChatGPT 스레드 참조·불변조건은 보존)
- `PROJECT_SCOPE.md` 신규 작성
- `.harness/state.json`, `backlog.yaml`(28개 작업), `locks.yaml`(7개 트랙 소유권),
  `quality-gates.yaml`(4개 게이트 현황), `assumptions.md`(2건), `decisions.md`(3건),
  `risks.md`(5건), `expansion-candidates.md`(2건) 작성
- 기존 구현(backend/ 48엔드포인트·15마이그레이션, frontend/ 20라우트 빌드검증)을 소급 DONE
  처리 — 실제 코드 변경 없음, 상태 기록만
- 다음 작업으로 CONTRACT-002(비공식 계약을 .harness/contracts/**로 승격) 선정 —
  KIOSK-001은 CONTRACT-003(API 경로 조정)에 막혀 있고, CONTRACT-003은 CONTRACT-002에 막혀 있다

FND-001 완료. ARCHITECTURE.md(FND-002)는 다음 사이클로 이월.

## 2026-08-02 — CONTRACT-002

- backend/를 재설치(pip install -e .)해 동시작업 반영 최신화 → 실제 FastAPI 앱에서
  openapi() 스키마 추출, .harness/contracts/openapi.json 저장 (51개 경로)
- .harness/contracts/domain-model.md 작성 (15개 모델 파일 → 스키마 매핑, 공통 컨벤션,
  RISK-005 참조)
- .harness/contracts/error-codes.yaml 작성 (grep 기반, 25개 이상 오류코드 수집 — 완전하지 않음)
- .harness/contracts/ontology.yaml 작성 (259개 개념 카탈로그 메타데이터 스냅샷)
- **중요 발견**: 온톨로지 이중화 문제 — 기존 259개 개념 카탈로그(주류 도메인 특화)와
  재설계 문서 §30 예시 코드(일반 산업박람회용으로 보임)가 다른 도메인처럼 보임.
  CONTRACT-003을 진행하기 전에 사용자 확인 필요(Blocker Score >= 7 판정) — 자동 진행하지 않음.

## 2026-08-02 — 온톨로지 결정 확인 + CONTRACT-003

- 사용자 확인: 기존 259개 개념 카탈로그 유지, 재설계 §30 코드는 템플릿 예시로 폐기 (DECISION-004)
- CONTRACT-003: 재설계 §40과 실제 51개 엔드포인트 대조 완료 (DECISION-005)
  - 네이밍 차이 3건은 기존 유지로 확정
  - 진짜 기능 공백 발견: 공개 업체·부스 조회/검색 API 없음(BACKEND-008 신설, KIOSK-002 최우선 블로커),
    관심목록 API 없음(BACKEND-009 신설)
- G1_CONTRACT_FREEZE 사실상 통과 — contract_status를 FROZEN으로 갱신

## 2026-08-02 — DECISION-006: pnpm+apps/* 모노레포 전환

- backend/ -> apps/api, frontend/ -> apps/user-web 물리 이동 (git mv 아님, 다수 미추적
  파일 때문에 plain mv 사용 — git add는 아직 안 함, 커밋 요청 없었음)
- pnpm-workspace.yaml 신규, 루트 package.json을 워크스페이스 루트로 전환
- 하드코딩 경로 버그 2건 발견·수정(alembic DDL 파일 경로, pytest ROOT 상수) — 상세는 DECISION-006
- 재검증: 백엔드 51 라우트/15마이그레이션(86테이블)/pytest 87+1skip 전부 통과,
  프런트 typecheck 0에러/build 21라우트 통과
- AGENTS.md, PROJECT_SCOPE.md, .harness/locks.yaml, .harness/backlog.yaml(owned_paths),
  README.md, apps/api/README.md, apps/user-web/README.md 경로 참조 갱신
- run-log.md/decisions.md/assumptions.md/risks.md/expansion-candidates.md 등 과거 로그성
  기록은 당시 사실을 그대로 보존(append-only 원칙) — ASSUMPTION-001만 SUPERSEDED 주석 추가

## 2026-08-02 — WAVE 2 공개검색·키오스크 수직 슬라이스

- BACKEND-008 완료: 공개 행사/업체/제품/부스/지도 7개 GET과 익명 검색 POST/GET을
  `/api/v1`에 등록. 승인·활성 필터, 온톨로지 구조화 필터, PostgreSQL FTS, 키워드 fallback,
  WEB/KIOSK 채널별 Redis 검색 세션을 구현했다.
- BACKEND-006 완료: 60~120초 Redis TTL 익명 키오스크 세션, 검색, 서명·만료 QR 발급,
  서버측 handoff 레코드 해시 결합 검증, 게스트 resolve, 명시 종료 API를 구현했다.
  `kiosk.kiosk_session`/`kiosk.kiosk_qr_handoff`에는 PII 컬럼이 없고 Alembic 단일 head는
  `0016_kiosk_session`이다.
- KIOSK-001~004 완료: 별도 `apps/kiosk` Next.js 앱에 K00~K10, 4개 언어, 화면 키보드,
  자연어/카테고리 검색, 결과, 업체상세, 부스지도, QR, 무결과·네트워크 오류·세션종료 화면을
  연결했다. QR 게스트 도착점은 `apps/user-web/app/kiosk-handoff`로 구현했다.
- 계약 갱신: `.harness/contracts/openapi.json` 66경로, domain-model 93테이블,
  error-codes 공개검색·키오스크 항목으로 갱신. G1_CONTRACT_FREEZE를 PASSED로 기록했다.
- 검증: backend pytest 148 passed/2 skipped, 변경범위 Ruff 통과, Alembic single head 확인,
  kiosk Vitest 3 passed + typecheck + production build(12 페이지), user-web typecheck +
  production build(20 페이지), harness JSON/YAML/OpenAPI 파싱 통과.
- 로컬 제약: Google Drive 동기화 경로의 pnpm symlink/rename이 반복 실패해, 잠금파일은
  `pnpm --lockfile-only` 해석 결과를 사용하고 Next.js 검증은 깨끗한 임시 디렉터리 npm 설치로
  수행했다. CI/일반 로컬 디스크에서는 표준 pnpm 명령으로 재검증할 수 있다.

## 2026-08-02 — Canonical root materialization and verification

- Materialized the live project snapshot at `G:/내 드라이브/CODE/Meet AI` while preserving
  `.claude/` and excluding linked-worktree metadata, dependencies, virtual environments, and caches.
- Initialized an independent Git boundary at the requested root on
  `codex/backju-ontology-ai-gateway`; the parent Google Drive repository is no longer selected.
- Fixed four monorepo path/version defects: pytest `../../src`, API editable-install `../..`,
  exhibition DDL output root `parents[3]`, and the live PostgreSQL test head `0016_kiosk_session`.
- Fixed the stale `lib/` ignore rule and restored 19 required `apps/{user-web,kiosk,admin}/lib`
  modules that contain API clients, shared types, auth state, and kiosk session logic.
- Rebuilt the pnpm lock against the active supply-chain policy (Rollup `4.62.3`) and limited
  dependency install scripts to `esbuild` and `unrs-resolver`.
- Evidence: backend `148 passed, 2 skipped`; root/AI `177 passed`; Alembic single head;
  ontology 259 concepts; OpenAPI exact snapshot match (66 paths, 171 schemas); kiosk Vitest
  `3 passed`; all three apps typecheck and production-build (12/13/20 pages); frozen pnpm install
  passes supply-chain verification.
- Remaining external checks: live PostgreSQL/Redis and pgvector semantic retrieval. Full-repo Ruff
  also retains pre-existing style/FastAPI-rule debt and is not a G3-green signal yet.

## 2026-08-02 — AISEARCH-002 pgvector semantic catalog search

- Approved CR-004 / DECISION-007 for the frozen embedding contract: OpenAI
  `text-embedding-3-small`, 512 dimensions, cosine similarity, and an active-row HNSW index.
- Added migration `0017_object_embedding`, immutable model-version lineage, approved-public-only
  backfill, validated provider responses, semantic top-K candidate union, and the shared kiosk/web
  deterministic scorer with fail-soft keyword/FTS/category fallback.
- Verification: backend `163 passed, 2 skipped`; aggregate `340 passed, 2 skipped` plus 12
  subtests; Alembic upgrade/downgrade SQL compile; one head; 94 ORM tables; OpenAPI exact at 66
  paths/171 schemas; targeted Ruff F/I and dependency checks green.
- Live PostgreSQL/pgvector and provider smoke tests remain G3 operational checks because the local
  Docker service is stopped. Semantic search remains opt-in and disabled by default.

## 2026-08-02 — AISEARCH-002 final hardening and verification

- Closed the final fail-soft boundaries: event OPEN validation now precedes paid provider I/O;
  structured, vector, and semantic-hydration queries use savepoints; CJK free text retains the
  semantic channel.
- Changed ANN recall to a literal-predicate SUMMARY-only partial HNSW index. Participation SUMMARY
  vectors include approved product text, and hydration samples fan-out round-robin while preserving
  an independent FTS window.
- Backfill now enforces conservative per-input/request byte limits, commits inactive provider
  batches for retry reuse, validates immutable model lineage, and rechecks the source snapshot
  before atomic activation.
- Final evidence: backend `172 passed, 2 skipped`; root/AI/API aggregate `349 passed, 2 skipped`
  plus `12 subtests`; Alembic upgrade/downgrade SQL compile; one head; 94 ORM tables; OpenAPI exact
  at 66 paths/171 schemas; targeted Ruff F/I/format and `pip check` green.
- Live PostgreSQL/pgvector, real-provider backfill, exact-vs-ANN relevance, latency/cost, and public
  search gateway/WAF rate limiting remain G3 checks. The semantic channel stays disabled by default.

## 2026-08-02 — AISEARCH-002 harness closeout audit

- Preserved the original append-only risk entries and recorded dated updates instead of replacing
  their historical text. RISK-005 is now consistently resolved in both the risk register and domain
  contract.
- Added explicit CONTRACT-006 → BACKEND-010 authentication/RBAC/MFA delivery steps and connected
  BACKEND-007/ADMIN-001 to that unblock path. QA-001 is blocked until its FND-002 architecture
  snapshot dependency is complete.
- Corrected stale KIOSK/ADMIN section labels and kept the completed Wave 2 QA-003 audit inside the
  Wave 2 section. CONTRACT-005 remains the next recommended task.

## 2026-08-02 — AISEARCH-002 source-freshness closeout

- Closed aggregate-SUMMARY freshness fail-open behavior: changes to embedded source fields,
  approval boundaries, and recommendable membership now deactivate the participation's active
  catalog vectors. `BEFORE STATEMENT` triggers acquire a short global catalog advisory lock before
  row changes and FK cascades; final backfill shares that lock and rechecks its exact source snapshot
  before activation, so qualifying-row phantoms cannot be reactivated stale and managed source-write
  lock order remains consistent.
- Product/company names are embedded before descriptions, and the remaining byte budget is shared
  fairly across descriptions so an oversized first product cannot erase later product names.
- Final evidence: backend `174 passed, 2 skipped`; root/AI/API aggregate `351 passed, 2 skipped`
  plus `12 subtests`; targeted Ruff F/I/format, Alembic upgrade/downgrade SQL, OpenAPI 66/171,
  ORM 94 tables, dependency and harness checks pass.
- Live PostgreSQL trigger/concurrency behavior remains part of the already-open G3 isolated-stack
  validation; semantic search is still disabled by default.

## 2026-08-02 — living roadmap alignment checkpoint

- Re-read `chatgpt-conversation://6a6c5792-ca44-83ee-ad67-b02c77ba7f7b`. Its recent sequence is the
  long-range roadmap: Wave 2D document structuring, Wave 2E operations analytics, Wave 3 release
  validation, production/pilot, and evidence-driven v1.1A through v1.1D.
- The repository remains at Wave 2 / `G2_FEATURE_COMPLETE` in progress (70%), with
  `CONTRACT-005` as the next task. Later conversational Waves are not treated as completed entry
  conditions and will not be started early.
- Added a durable `AGENTS.md` rule requiring every implementation unit to compare the newest
  roadmap turns with harness state, frozen contracts, and handoffs before changing product behavior.

## 2026-08-02 — AIENGINE-001 common matching-engine semantic recall

- Applied the user's engine-first direction as DECISION-008: web, kiosk, and admin/platform work
  remain consumers of the common engine; CONTRACT-005 favorites is deferred and AIENGINE-002 is next.
- Replaced the recommendation candidate generator's vector no-op with the deployed SUMMARY pgvector
  scorer. A deterministic `PROFILE_SEMANTIC_RECALL_V1` query contains only canonical ontology codes,
  public Korean labels, requirement level, priority, taxonomy version, and audience type.
- Excluded profile/user identifiers, raw context, unknown/free-form codes, EXCLUDED values, confidence,
  and numeric trade conditions from provider input. The request validator still requires active
  personalized-recommendation consent before the profile reaches this stage.
- Semantic similarity only expands the candidate pool. Existing Hard Filter, B2C/B2B/reciprocal
  scoring, context, slate, explanation, and persistence policies were not changed. Each vector hit
  retains input fingerprint/model version/score, with a three-object-per-participation cap and stable
  tie-breaking; disabled/provider/pgvector failures keep structured fallback.
- Verification: targeted semantic/recommendation tests `30 passed`; full backend `178 passed, 2
  skipped`; root deterministic scoring/ontology `24 passed`; targeted Ruff and diff checks pass.
  Live PostgreSQL/provider behavior remains part of the existing G3 operational validation.

## 2026-08-02 — AIENGINE-002 golden set and offline evaluator

- Published `matching-golden-set-v1` as a packaged JSON Schema plus a checked-in baseline covering
  general visitor, buyer-to-exhibitor, and reciprocal matching. Each candidate fixes expected and
  observed eligibility, recall channels, score inputs, relevance grade, allowed explanation codes,
  and evidence references.
- Added the provider/DB-independent `matching-evaluator-v1.0`. It recalculates scores only through
  the published deterministic policies and reports Recall@K, NDCG@K, structured fallback recall,
  Hard Filter admission/reason mismatches, explanation grounding, exhibitor concentration/HHI, and
  stable input/scenario/result fingerprints.
- The evaluator fails closed on policy/taxonomy drift, unknown recall channels, ineligible candidate
  admission, missing/unapproved explanation evidence, fallback regression, ranking regression, and
  concentration threshold breaches. `python -m meet_ai.evaluation` returns nonzero on regression.
- Baseline: three scenarios PASS; Recall@3 `1.0`; NDCG@3 `1.0`; fallback Recall@3 `0.666667`;
  Hard Filter, filter-decision, and explanation violations `0`; max exhibitor share `0.333333`.
- Verification: root scoring/ontology/evaluation `35 passed`; backend `178 passed, 2 skipped`;
  targeted Ruff, JSON parsing, editable package data, module CLI, and `pip check` pass. The generated
  Windows console-wrapper executable was blocked by local Application Control, so the portable
  `python -m` invocation is the verified local command.
- This is a deterministic regression baseline, not a claim of production relevance. Human-judged
  event data, real provider/pgvector recall, latency, cost, and ANN-vs-exact checks remain G3 work.

## 2026-08-02 — AIENGINE-003 common matching-engine facade

- Published provider/DB-independent `matching-engine-command-v1.0` and
  `matching-engine-result-v1.0` contracts for catalog search, general visitor, buyer-to-exhibitor,
  and reciprocal modes. The facade owns policy selection, eligibility exclusion, stable ranking,
  version provenance, and canonical input/result fingerprints.
- Moved the frozen kiosk search coefficients into the pure engine and changed kiosk, directional,
  and reciprocal backend adapters to call the facade. Existing Hard Filter, missing-signal
  renormalization, reciprocal caps, grades, statuses, actions, and public API contracts are unchanged.
- Upgraded the offline evaluator to `matching-evaluator-v1.1`; every golden scenario is now one
  facade command and records engine contract/input/result fingerprints. Baseline remains 3/3 PASS,
  Recall@3 1.0, NDCG@3 1.0, fallback Recall@3 0.666667, with zero filter/explanation violations.
- Verification: root `42 passed`; backend `180 passed, 2 skipped`; focused facade/evaluator `18
  passed`; focused backend adapter/scoring/search `17 passed`; compileall, pip check, and diff check
  pass. Live PostgreSQL/provider behavior remains deferred to the existing G3 operational checks.
- AISEARCH-003 is next for a change-controlled decision on the redesign's simplified formula. No
  published formula was changed in this unit.

## 2026-08-02 — AISEARCH-003 section-34 personalization policy decision

- Compared the simplified section-34 web formula with the executable `consumer-score-v1.0`, the
  recommendation request contract, feature builder, context reranker, and facade-backed Golden Set.
- Chose `RETAIN_CONSUMER_SCORE_V1`. Current-query match has no recommendation input or judged
  feature, while booth availability already belongs to `context-rerank-v1.0`; immediate replacement
  would require invented proxies and would risk double weighting runtime availability.
- Classified a future section-34 replacement as `consumer-score-v2` requiring an approved Change
  Request, query privacy/retention contract, explicit interest aggregation, single ownership of
  availability, versioned DB policy binding, labeled v2 fixture, and shadow non-inferiority evidence.
- Added a regression boundary proving consumer-v1 dimensions, the no-query recommendation contract,
  and separate context availability remain intact. No runtime formula, API, database, or public
  result changed.
- Added `AIENGINE-004` as the next engine-first task: deterministic generated reason claims and
  evidence grounding in the common facade, followed by facade-generated explanation evaluation.

## 2026-08-02 — AIENGINE-004 deterministic reason/evidence contract

- Applied the supplied exhibition-personalization benchmark at the common-engine boundary: the
  engine, not an LLM or UI template, now admits reason claims from allowlisted score contributions,
  catalog signals, reciprocal state, and Hard Filter results.
- Published backward-compatible `matching-engine-command/result-v1.1` and
  `reason-claim-v1.0`. Claims require adapter evidence and carry source components plus canonical
  fingerprints; v1.0 rejects v1.1 evidence rather than silently changing.
- Runtime explanation templates project facade claims. Golden evaluator v1.2 now treats fixture
  explanations as evidence bindings and validates generated claims; deleting evidence fails the
  grounding gate.
- Verification: root `45 passed`; backend `184 passed, 2 skipped`; focused Ruff, `pip check`, and
  diff check PASS; Golden Set 3/3 PASS with zero explanation violations.
- AIENGINE-005 is next for shadow-only RRF hybrid fusion and explicit UNKNOWN/missing-signal
  evaluation. No published score formula, public API, database schema, or online learning changed.

## 2026-08-02 — BACKEND-011 Excel-based matching input

- Applied the user's file-first direction at the engine input boundary. Published
  `meet-ai-excel-import-v1.0` with `사전등록자` and `참여기업` sheets plus a guide, the complete
  259-concept code list, and natural-language search examples.
- Added `POST /api/v1/admin/imports/excel`; it defaults to non-mutating dry-run and converts valid
  rows into the existing visitor/exhibitor import schemas. Persisted data therefore continues
  through the same approval, public-index, Hard Filter, and common matching-facade boundaries.
- Added fail-closed XLSX validation for size, ZIP expansion, macros, formulas, hidden input sheets,
  exact headers, duplicate IDs, booleans, timestamps, row limits, and ontology type/assignability.
  Row errors do not echo source cell values or direct identifiers.
- The existing `/api/v1/search` remains the natural-language path; no parallel scoring formula was
  introduced. Focused parser/API tests pass `7/7`; the generated workbook was rendered and all five
  sheets were visually inspected before publication.

## 2026-08-02 — BACKEND-012 preregistrant Top-N XLSX export

- Added `POST /api/v1/admin/imports/excel/matches` with a maximum of 100 unique opaque source IDs
  and Top 1–10. Each source ID resolves to its canonical imported profile and executes the existing
  `EXHIBITOR` recommendation orchestrator; raw workbook rows are never scored directly.
- Consent, age confirmation, event state, approved catalog retrieval, Hard Filter, common scoring
  facade, deterministic reasons, and result persistence remain unchanged. Missing or ineligible
  profiles are isolated into the status sheet without automatic condition relaxation.
- Published `meet-ai-batch-match-export-v1.0` with summary formulas, ranked public exhibitor results,
  safe reason/evidence fields, policy and ranking versions, eligibility IDs, score fingerprints, and
  per-profile status. Direct identity and raw profile fields are absent.
- Fixed the CR-007 persisted Excel import job types to use the database-allowed `VISITOR_IMPORT` and
  `EXHIBITOR_IMPORT` values; added a regression test for `dry_run=false`.
- Focused import/export tests pass `13/13`. The example workbook formula scan returned zero errors,
  all three sheets were rendered and visually inspected, full backend passed `197` with `2` skipped,
  and root deterministic engine/ontology tests passed `45`.

## 2026-08-02 — AIENGINE-005 hybrid RRF shadow and UNKNOWN boundary

- Added pure `hybrid-rrf-shadow-command/result-v1.0` execution, isolated from the published
  matching facade. Equal-weight RRF uses deterministic candidate-ID tie breaking and canonical
  input/result fingerprints.
- VECTOR `UNAVAILABLE` and `NOT_INVOKED` fail back to the exact weighted-v1 published order with
  null RRF scores; no remaining-channel renormalization or public rank mutation occurs.
- Candidate absence in a recall channel remains a null rank. Named UNKNOWN and MISSING business
  signals remain distinct diagnostics and are covered by reproducibility tests.
- Added evaluator-v1.0 and a three-scenario labeled fixture. Average Recall@K improved from
  `0.777778` to `0.888889`; average NDCG@K improved from `0.795522` to `0.947609`; fallback order,
  state preservation, and promotion-prohibited gates all pass.
- Verification: focused `30 passed`; root `54 passed`; backend `197 passed, 2 skipped`; existing
  golden set 3/3 PASS; Ruff, compileall, pip check, and diff check PASS.
- AIENGINE-006 is next for a shared deterministic intent contract across natural-language queries
  and canonical Excel profiles. RRF production promotion remains change-controlled.

## 2026-08-02 — CR-009 web-first pivot and GUEST_WEB search

- Rechecked the living product-roadmap conversation. Applied the explicit decision that the event
  has no dedicated intermediate kiosks and the service should be install-free, mobile-web first.
- Approved CR-009 and replaced the canonical scope with four active channels:
  REGISTERED_WEB, GUEST_WEB, BUYER_WEB, and ADMIN_PARTNER_WEB.
- Completed FND-002 with a current repository architecture snapshot. Root scripts now exclude the
  inactive `backju-kiosk` package while retaining its source/API/data compatibility for reversible,
  separately versioned cleanup.
- Implemented `/explore` over the existing public approved-catalog `/api/v1/search` WEB channel.
  Anonymous browsing no longer creates a profile session, and missing event UUID configuration
  fails closed before an invalid request.
- Verified frozen install plus active user/admin lint, root typecheck, and production builds in a clean
  NTFS workspace. `/explore` prerenders successfully. Browser inspection confirmed the labeled
  search form, landmarks, 390 px geometry, configuration error boundary, and zero console errors.
- Root deterministic tests passed `54`; backend passed `197` with the two existing PostgreSQL
  integration skips.
- The next engine task remains AIENGINE-006: one deterministic intent contract for natural-language
  queries and canonical Excel profiles.

## 2026-08-03 — AIENGINE-006 shared natural-language and Excel intent

- Rechecked the living roadmap and applied the supplied personalization benchmark at the common
  engine boundary, with its kiosk assumptions replaced by the approved GUEST_WEB scope.
- Published `matching-intent-command/result-v1.0` and `intent-normalization-v1.0`. Natural language
  and canonical Excel/profile codes now converge on deterministic MUST/PREFER/EXCLUDE buckets plus
  explicit UNKNOWN and UNRESOLVED states.
- Resolution is limited to the published, assignable 259-concept ontology. Korean labels and
  approved synonyms resolve; English ontology tokens resolve; ambiguous acronyms and labels retain
  their candidate codes without guessing. Explicit Korean/English negation maps to EXCLUDE.
- Email and phone patterns are redacted before provider calls and fingerprints. Optional model
  output is validated against `intent-proposal-v1.0` and the published ontology but remains
  proposal-only, never a Hard Filter or score input.
- Seven regression scenarios cover Korean, English, acronym, negation, ambiguity, Excel parity, and
  UNKNOWN. Verification: fixture PASS; focused 38 passed; root 62 passed; backend 197 passed/2
  skipped; Ruff, compileall, pip check, and diff check PASS.
- AIENGINE-007 is next: project confirmed intent into retrieval and Hard Filter plans without
  changing the published weighted-v1 order.

## 2026-08-03 — AIENGINE-007 intent retrieval/filter projection

- Published `intent-projection-result-v1.0`, `intent-projection-v1.0`, and
  `candidate-capability-v1.0` as a pure plan boundary after intent normalization and before any
  retrieval, Hard Filter decision, or score call.
- Confirmed PREFER codes become `STRUCTURED_ONTOLOGY` recall-only features. Confirmed MUST and
  EXCLUDE codes become REQUIRE_MATCH/FORBID_MATCH constraints only when a versioned candidate field
  binding exists.
- Public catalog plans do not project verified-buyer trade fields. Restricted or unbound hard
  conditions become INFORMATION_REQUIRED instead of automatic pass or silent relaxation.
- Every constraint fixes UNKNOWN and MISSING outcomes to INFORMATION_REQUIRED. Intent UNKNOWN,
  UNRESOLVED, and validated model proposals remain deferred and never become retrieval features,
  filter mismatches, or numeric zeroes.
- Seven fixture scenarios cover natural/Excel plan parity, public preference, buyer OEM MUST,
  unbound MUST, public-scope restriction, and explicit EXCLUDE. Verification: focused facade 25
  passed; root 67 passed; backend 197 passed/2 skipped; Ruff, compileall, pip check, and diff check
  PASS.
- AIENGINE-008 is next: evaluate constraints against verified candidate observations and admit
  scoring only for fully eligible candidates.

## 2026-08-03 — AIENGINE-008 verified candidate constraint evaluation

- Published `constraint-evaluation-result-v1.0` and `constraint-evaluation-v1.0` after intent
  projection and before the existing scoring facade.
- Candidate observations carry an explicit KNOWN/UNKNOWN/MISSING/STALE state and mode-specific
  ontology, numeric, or trade-status values. Non-known observations cannot carry values.
- ONTOLOGY_MATCH uses the published catalog graph, DERIVED_BAND_MATCH uses the published alcohol
  band policy, and TRADE_STATUS preserves CONDITIONAL/NEGOTIABLE as INFORMATION_REQUIRED.
- MUST and EXCLUDE never auto-pass on unknown, missing, stale, or absent observations. Only a fully
  ELIGIBLE evaluation converts to the existing `EligibilityDecision`; filtered and information-
  required results fail closed at the scoring admission boundary.
- Evaluation results expose reason codes, opaque evidence refs, and canonical fingerprints but not
  raw observed business values. Projection-plan fingerprints are revalidated before evaluation.
- Fourteen fixture scenarios pass. Verification: focused facade 30 passed; root 72 passed; backend
  197 passed/2 skipped; touched Ruff, compileall, pip check, and diff check PASS. Repository-wide
  Ruff still reports 117 pre-existing findings outside this task's changed paths.
- AIENGINE-009 is next: map canonical runtime candidates into observations and compare this evaluator
  with the existing Hard Filter in shadow before any enforcement change.

## 2026-08-03 — AIENGINE-009 candidate observation adapter and runtime shadow

- Published `candidate-observation-adapter-v1.0` and `hard-filter-shadow-v1.0` beside the existing
  runtime Hard Filter. Shadow enforcement is explicitly false.
- Confirmed profile MUST/PREFER/EXCLUDE values reuse the AIENGINE-006/007 intent contracts. Only
  requested approved public fields and approved buyer supply fields become observations.
- Candidate category, taste, aroma, usage, feature, service, alcohol band, channel, region, trade
  type, and OEM/PB/export status map to the AIENGINE-008 three-state evaluator.
- Shadow comparisons emit privacy-minimized PARITY, SAFETY_GAP, DIVERGENCE, NOT_COMPARABLE,
  NOT_APPLICABLE, or ADAPTER_ERROR results with stable reason codes and fingerprints.
- Seven fixed OEM scenarios prove YES/NO parity and preserve UNKNOWN/MISSING/STALE/CONDITIONAL/
  NEGOTIABLE as information-required safety gaps. Public EXCLUDE, unapproved data, malformed
  observations, deterministic ordering, value omission, and synthetic divergence are also covered.
- Verification: focused 21 passed; root 72 passed; backend 211 passed/2 skipped; touched Ruff,
  compileall, pip check, JSON/YAML, and diff check PASS. A 150-candidate local diagnostic run took
  approximately 55 ms; this is evidence only, not a production performance guarantee.
- AIENGINE-010 is next: aggregate versioned shadow quality metrics and define a promotion gate.

## 2026-08-03 — AIENGINE-010 constraint shadow quality gate

- Published `constraint-shadow-gate-command/result-v1.0` and
  `constraint-shadow-promotion-gate-v1.0` as a pure aggregate boundary over AIENGINE-009 results.
- The runtime adapter counts only privacy-safe states and stable safety-gap reason codes. Candidate
  references and observed values do not enter the gate; identical retry fingerprints are removed
  from the eligible runtime sample and reported separately.
- Any DIVERGENCE or ADAPTER_ERROR returns FAIL. At least 1,000 unique comparable results, exact-
  policy regression evidence, rollback evidence, and safety-gap review evidence are required for
  PASS. NOT_COMPARABLE and NOT_APPLICABLE stay visible but do not inflate the sample.
- PASS means only `change_request_ready=true`. `enforcement_allowed=false` remains immutable, the
  legacy Hard Filter stays authoritative, and weighted-v1/API/database/persisted rank are unchanged.
- Six fixed scenarios cover pass, divergence, adapter error, small sample, missing gap review, and
  non-comparable inflation. Verification: focused 25 passed; root 72 passed; backend 219 passed/2
  skipped; Ruff, compileall, pip check, and diff check PASS.
- No production sample or approved enforcement Change Request exists. FND-003 CI automation is the
  next safe unit before a later change-controlled enforcement proposal.

## 2026-08-03 — FND-003 common GitHub CI

- Published a read-only GitHub Actions workflow for pull requests, `main`, and manual dispatch.
- Engine/API job installs both editable Python packages, checks fatal Ruff categories and package
  consistency, then runs the 72-test common engine suite and 219-test backend suite.
- Active-web job uses pnpm 9.15.0 with the frozen lock, then runs root lint, typecheck, tests, and
  production builds. Root filters cover user-web/admin and exclude the inactive kiosk package.
- Clean NTFS reproduction passed frozen install, active lint/typecheck/test, admin 13-route build,
  and user-web 21-route build. Backend passed 219/2 skipped after reproducing the Ubuntu LF Git blob;
  a Windows-only global autocrlf byte-hash mismatch required no source or contract change.
- The newest living roadmap requests a mobile My Event HTML surface and Kakao notification entry.
  This remains aligned with web-first scope, but personal links/delivery are deferred until the
  authentication/session and notification contracts are frozen. CONTRACT-006 is next.

## 2026-08-03 — CONTRACT-006 authentication, scoped RBAC, and administrator MFA contract

- Published approved CR-006 and OpenAPI 0.2.0. The browser boundary is an opaque server-managed
  `__Host-meet_ai_session` cookie; service integrations use allowlisted asymmetric JWTs of at most
  ten minutes. Guest continuity remains separate and cannot authorize protected roles.
- Added five authentication route contracts for one-time personal-link exchange, session read/revoke,
  MFA enrollment/challenge, and verification, plus three security schemes and ten Auth schemas.
- Froze immutable tenant/event/user/role principal claims, resource-scoped EVENT_ADMIN,
  DATA_REVIEWER, and EXHIBITOR_ADMIN capabilities, 12-hour absolute sessions, stricter admin idle
  limits, fresh-MFA requirements, contact-disclosure non-override, and generic 401/403 behavior.
- Personal links are opaque, digest-stored, single-use, and at most 15 minutes. Kakao/email are
  delivery channels only. Magic-link plus TOTP is explicitly not AAL2; user-verifying multi-factor
  WebAuthn is preferred and TOTP needs an independent different primary factor.
- Deprecated caller identity headers now have a fail-closed transition: the compatibility adapter
  defaults off, cannot assert AAL2, and is forbidden in production. Before G3, spoofing tests must
  prove headers cannot alter the principal or scope.
- The current identity model cannot persist WebAuthn/TOTP/recovery state. BACKEND-010 ownership was
  expanded to a reviewed 0018 migration, credential/session model, router registration, dependency,
  and tests; the task is READY but no implementation claim has been made.
- Verification: JSON references and 73 error-code entries parsed; contract invariants passed; root
  72 tests passed; API 219 tests passed with 2 skipped; `git diff --check` passed.
- BACKEND-010 is next. Personal My Event HTML and Kakao sending remain downstream of its verified
  session principal and a separate notification delivery contract.

## 2026-08-03 — BACKEND-010 and ADMIN-001 verified authentication foundation

- Implemented 0018 persistence for digest-only personal links and sessions, explicit scoped role
  grants, WebAuthn/TOTP authenticators, short-lived challenges, and one-time recovery codes. Secret
  values use keyed digests or AES-GCM authenticated encryption; contact/message encryption now
  fails closed on tampering or legacy plaintext.
- Added one-time personal-link exchange, session read/revoke, MFA enrollment/challenge/verification,
  RS256 service JWT validation, shared role/fresh-MFA dependencies, and OpenAPI security schemes.
  Magic-link plus TOTP is not treated as AAL2.
- Removed caller-provided identity headers from protected profile, recommendation, partner, meeting,
  and Excel import boundaries. Browser-cookie mutations require an allowlisted Origin and a
  session-bound CSRF token; guest continuity remains a separate non-authenticating cookie.
- Replaced the admin localStorage role switcher with server session projection, opaque-link exchange,
  WebAuthn enrollment/step-up, logout, and role-scoped navigation. Kiosk remains excluded from the
  active workspace and no kiosk feature was added.
- Upgraded active Next/React dependencies and patched PostCSS, Sharp, and esbuild. Production pnpm
  audit reports no known vulnerabilities.
- Verification: common engine 72 passed; API 236 passed/2 skipped; auth-focused 17 passed; active
  web 5 passed, lint/typecheck/build PASS on clean NTFS; Alembic has one head and the full offline
  upgrade renders successfully; fatal Ruff, pip check, and diff check PASS. The two PostgreSQL
  integration tests remain skipped because POSTGRES_TEST_DATABASE_URL is not configured.
- BACKEND-007 is now READY. Live PostgreSQL, production WebAuthn RP/origin, and deployment key
  rotation validation remain release-gate work rather than inferred success.

## 2026-08-03 — Authentication remediation and web session entry

- Approved CR-010 and added public `POST /api/v1/sessions`. It atomically creates a web guest
  session, minimal general-visitor profile, and visit session; the raw credential is emitted only
  as a Secure/HttpOnly guest cookie. Dedicated kiosk entry is rejected.
- Added `/e/{eventSlug}/my` for Kakao/email personal-link exchange. It uses no-referrer/no-index
  metadata, removes the opaque token from browser history, and restores CSRF only from the verified
  HttpOnly browser session.
- Fixed the BACKEND-010 review blockers: TOTP enrollment secrets no longer enter JSONB, future role
  grants are inactive, EXHIBITOR_ADMIN remains available at AAL1, EVENT_ADMIN/DATA_REVIEWER remain
  dormant until AAL2, and personal-link resend revokes prior unconsumed same-path links. Redis
  limits exchange attempts by HMAC-derived token, account, and network dimensions and fails closed.
- User-web unsafe authenticated requests now attach the runtime-only, session-bound CSRF token and
  accept direct frozen auth responses as well as success envelopes.
- Replaced the active phone-OTP controls, whose provider and abuse contract do not exist, with the
  approved personal-link guidance. General visitors still start an anonymous matching profile or
  enter approved-catalog search without login.
- Verification: common engine 72 passed; API 246 passed/2 skipped; active web 7 tests total,
  lint/typecheck, admin 15-route build, and user-web 21-route build PASS on clean NTFS. Touched
  Ruff/format, compileall, OpenAPI 74-path reference validation, and diff check PASS. Full-repo Ruff
  still reports pre-existing style debt outside the changed files. Live PostgreSQL tests remain the
  same two environment-gated skips.

## 2026-08-03 — DELIVERY-001 persisted recommendation delivery and My Event surface

- Approved CR-011 and froze the calculation-versus-delivery boundary. `POST /recommendations`
  continues to calculate and persist; the new `GET /home` only reads the newest owned `ACTIVE`
  snapshot and cannot invoke the orchestrator, LLM, or a notification provider.
- Missing snapshots fail explicitly with retryable `RECOMMENDATION_NOT_READY`. Expired results are
  exposed as stale and invalidated results remain ineligible, preserving reproducibility and making
  refresh scheduling a separate operation.
- Replaced the personal-link route's hidden menu landing with the shared mobile My Event dashboard.
  It now exposes up to ten recommendation cards and grounded reason text together with saved-company,
  meeting, schedule, search, and map entry points. Cards retain save/detail/eligible meeting actions,
  hide numeric score, and record “관심 없음” through `RECOMMENDATION_DISMISSED`. `/home` reuses the
  same component.
- Kakao/email/SMS remain future access-link delivery adapters only. No provider integration and no
  dedicated kiosk capability were added.
- Verification: common engine 72 passed; API 248 passed/2 skipped; user web 5 passed, typecheck,
  lint, and 21-route production build PASS on clean NTFS; touched Ruff, OpenAPI 75-path local-ref
  validation, and diff check PASS. The two PostgreSQL integration tests remain environment-gated.

## 2026-08-03 — NOTIFY-001 Alimtalk-first informational delivery foundation

- Approved CR-012 after rechecking the living product conversation and current official Kakao
  Business guidance. Alimtalk is the primary access-link channel, SMS is failure fallback, email is
  last-resort backup, and the mobile My Event web remains the actual product.
- Added Alembic 0019 and published `integration.notification_delivery`, append-only
  `notification_attempt`, and transactional `outbox_event`. The Outbox payload contains only the
  notification ID; contact values and provider bodies are never stored there.
- Added idempotent recommendation-ready enqueue. It issues the existing single-use personal link,
  stores the URL only as AEAD ciphertext, and inserts the delivery plus Outbox in the caller's
  transaction. Rank/catalog drift is not an approved trigger.
- Added provider-neutral bounded rendering and dispatch policy. A successful Alimtalk stops the
  chain; failure proceeds to SMS and then email. Provider exceptions become allowlisted codes and
  raw responses are not persisted. No production provider implementation or credentials exist.
- Added SKIP LOCKED claims, expiring worker leases, append-only retry sequences, and first-click
  attribution during personal-link exchange without another tracking token.
- Verification: notification-focused 9 passed; API 257 passed/2 PostgreSQL environment skips;
  common engine 72 passed; touched Ruff, compileall, pip check, Alembic single head/full offline
  upgrade, harness parse, and diff check PASS.
