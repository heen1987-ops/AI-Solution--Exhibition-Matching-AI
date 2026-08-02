# Decisions

## DECISION-001 (2026-08-02)

기존 30단계 순차 설계 트랙(1~12단계 완료)을 12단계에서 중단하고, 웹 초개인화/키오스크 검색/
공통 AI플랫폼 3모듈 재설계로 전환한다. 상세: [docs/redesign-web-kiosk-split.md](../docs/redesign-web-kiosk-split.md)

## DECISION-002 (2026-08-02)

병렬개발 하네스(`.harness/`)를 이 저장소에 도입하고, Claude(이 세션)도 오케스트레이터/워커
역할을 함께 수행한다(Codex 전용이 아님) — 사용자 명시적 지시.

## DECISION-003 (2026-08-02)

ASSUMPTION-001, ASSUMPTION-002 참고 — 기존 `backend/`+`frontend/`를 유지하고 신규 트랙만
canonical 경로(`apps/*`)로 만든다.

## DECISION-004 (2026-08-02) — 사용자 확인됨 (Blocker Score >= 7)

기존 259개 개념 온톨로지 카탈로그(`src/meet_ai/ontology/catalog.v1.json`, 백주대간 주류
도메인 특화)를 그대로 유지한다. 재설계 문서(`docs/vibe-coding-master-spec-v1.md` §30)의
`INDUSTRY.MANUFACTURING`/`TECH.AI` 등 예시 코드는 원본 프롬프트 템플릿(범용 산업박람회)에서
가져온 예시일 뿐, 실제 구현 스펙이 아닌 것으로 확정. 앞으로 온톨로지 관련 모든 작업은
259개 카탈로그를 유일한 소스로 취급한다.

## DECISION-006 (2026-08-02) — 사용자 확인됨: pnpm+apps/* 정식 모노레포 전환

`backend/`→`apps/api`, `frontend/`→`apps/user-web` 물리 이동 완료. `pnpm-workspace.yaml`
(`apps/*`, `packages/*`) 추가, 루트 `package.json`을 워크스페이스 루트로 전환(기존 Netlify
Functions 의존성은 유지). ASSUMPTION-001은 이 결정으로 SUPERSEDED.

이동 중 발견·수정한 실제 버그(2건, 둘 다 `Path(__file__).resolve().parents[N]`의 하드코딩된
깊이가 `apps/` 한 단계 추가로 어긋난 것):
- `apps/api/alembic/versions/20260801_0001_0002_ontology.py`, `..._0004_0005_exhibition.py`:
  `parents[3]` → `parents[4]`로 수정(원본 SQL 계약 파일 경로 재계산).
- `apps/api/tests/test_profile_foundation.py`, `test_exhibitor_models.py`: `ROOT` 계산과
  하드코딩된 `"backend"` 문자열 세그먼트를 정리(`APP_ROOT`/`REPO_ROOT`로 분리).

재검증 결과: 백엔드 51개 API 정상 임포트, 15단계 마이그레이션 SQL 컴파일 정상(86 테이블),
pytest 87 passed/1 skipped. 프런트 typecheck 0 에러, `next build` 21개 라우트 정상(로컬 C:
드라이브 사본에서 검증 — Google Drive 경로 이슈는 여전함, RISK-002 참고).

## DECISION-005 (2026-08-02) — CONTRACT-003 API 경로 대조 결과

재설계 문서 §40의 API 경로 목록과 실제 구현된 51개 엔드포인트(`.harness/contracts/openapi.json`)를
대조한 결과, 대부분은 "경로 이름이 다른" 문제가 아니라 "기능 자체가 아직 없는" 진짜 공백이었다.

**네이밍만 다른 것(그대로 둠, 재설계 쪽 이름으로 안 바꿈 — ASSUMPTION-002 연장)**:
- `/me/event-profile` (재설계) ↔ `/profiles/me` (기존, 유지)
- `/buyer/matches` (재설계) ↔ `/recommendations`(user_type=BUYER로 처리, 기존 유지)
- `/events/{id}/registration/sync` (재설계) ↔ `/admin/imports/visitors`(관리자 배치, 기존 유지 — 사용자 자가연동 흐름은 없음, 필요시 별도 검토)

**진짜 기능 공백(신규 작업으로 backlog에 추가)**:
- 공개 업체·부스 목록/상세 조회 API 없음 (`GET /events/{id}/exhibitors`, `GET /booths/{id}` 등) — 지금은 파트너 인증 컨텍스트의 `/exhibitors/{id}/profile`만 있음. 웹·키오스크 모두 필요 → **BACKEND-008**
- 자연어/카테고리 "검색" API 없음 — `/recommendations`는 개인화 추천이지 검색이 아님. 키오스크는 프로파일이 없으므로 검색 전용 엔드포인트가 반드시 필요 → **BACKEND-008**에 포함
- 관심목록(즐겨찾기) API 없음 — `/interactions/batch`로 이벤트는 기록되지만 CRUD가 없음 → **BACKEND-009**
- 관리자 승인/반려/분석 API 없음 (`/admin/exhibitors/{id}/approve` 등) — `/partner/exhibitors/{id}/submit`(제출)까지만 있고 운영자 승인 액션이 없음 → 기존 **BACKEND-007**로 충분히 커버됨(범위 갱신)
- 키오스크 세션 API 전체 없음 → 기존 **BACKEND-006** 그대로

## DECISION-007 (2026-08-02) — CR-004 검색 임베딩 모델·차원·fallback

AISEARCH-002의 의미검색 계약은 공급자 어댑터 뒤의 OpenAI `text-embedding-3-small`,
`dimensions=512`, cosine similarity, pgvector SUMMARY-only HNSW `vector_cosine_ops`로 확정한다. 객체 임베딩은
승인된 공개 카탈로그 텍스트만 사용하고 정확한 `ai.model_version`과 결합한다. 기능은 환경설정으로
명시적으로 활성화하기 전까지 꺼져 있으며, 공급자·DB 선택 채널 장애 시 Semantic 신호만 0으로
낮추고 PostgreSQL FTS·키워드·카테고리 검색을 계속한다. 공개 API 응답 계약은 바꾸지 않는다.

Netlify AI Gateway의 현재 지원 모델 목록에는 embedding 모델이 없으므로 임베딩 요청은 Gateway에
보내지 않는다. 별도 비밀키를 사용하는 직접 공급자 어댑터로 격리하며 질의 원문과 벡터는 로그에
기록하지 않는다. 상세 변경범위와 롤백은
`.harness/handoffs/contracts/change-request-004-object-embedding.md`를 따른다.

### 2026-08-02 hardening note

SUMMARY-only 후보 다양성을 유지하되 집계 원문의 승인 경계가 느슨해지지 않도록, 업체·참가·제품·
행사제품·recommendable membership 변경은 DB trigger로 같은 참가사의 활성 vector를 즉시
비활성화한다. `BEFORE STATEMENT` trigger가 행 변경·FK cascade보다 먼저 짧은 전역 catalog advisory
lock을 획득하고, 최종 백필 활성화는 같은 lock 안에서 최신 snapshot 재검증과 포인터 교체를 같은
transaction에서 수행한다. 입력 한도 안에서는 업체명과 모든 제품명을
설명보다 우선하고 나머지 설명 예산을 소스별로 공정 배분한다.

## DECISION-008 (2026-08-02) — 공통 매칭엔진 우선 개발

사용자 명시 지시에 따라 웹·키오스크·관리 플랫폼은 공통 엔진의 소비자로 두고, 서비스 표면
확장보다 기초 AI 매칭엔진을 우선한다. 따라서 기존 다음 작업이던 `CONTRACT-005` 관심목록은
보류하고, `AIENGINE-001` 프로파일 의미 후보회수 연결 뒤 `AIENGINE-002` 골든셋·오프라인
평가기를 진행한다.

이 우선순위 변경은 현재 게시된 Hard Filter와 B2C/B2B/양면 점수 산식을 바꾸지 않는다.
벡터 유사도는 후보군 재현율만 보강하고, 자격 판정·최종 점수·설명은 기존 결정론적 정책과
계산지문을 유지한다. 향후 재설계 §34 산식 교체는 `AISEARCH-003`의 별도 CR 없이는 적용하지
않는다. 프로파일 임베딩 입력은 개인화 동의가 검증된 요청에서도 식별자·자유문·숫자 조건을
제외하고 게시 온톨로지 코드와 공개 라벨로 최소화한다.

## DECISION-009 (2026-08-02) — §34 웹 개인화 산식은 현 시점 미적용

`AISEARCH-003` 감사 결과 현재 게시된 `consumer-score-v1.0`과
`context-rerank-v1.0`을 유지한다. §34의 `Current Query Match`는 현재 추천 요청·특성 계약에
존재하지 않고, `Booth Availability`는 이미 별도 컨텍스트 재정렬에서 처리된다. 또한 §34의 단일
`User Interest Match`로 교체하면 현재 카테고리·감각·가격·도수·서비스·용도별 근거가 소실된다.

따라서 §34 적용은 단순 가중치 수정이 아니라 입력계약·개인정보 처리·점수 단계·정책 시드·골든셋을
함께 바꾸는 `consumer-score-v2` 변경이다. 별도 승인 Change Request와 새 라벨 평가셋, shadow
비열등성 증거가 생기기 전에는 적용하지 않는다. 현재 Golden Set에 없는 질의·부스가용성 값을
임의 proxy로 만들어 비교하지 않으며, 현 정책 유지 결정을 실패나 미완료로 간주하지 않는다.

상세 근거는
`.harness/reports/integration/personalization-score-policy-assessment-20260802.md`에 기록한다.

## DECISION-010 (2026-08-02) — 추천 이유의 사실 판정은 공통 facade가 소유

추천 이유는 LLM이나 화면 템플릿이 원시 feature를 보고 독자적으로 만들지 않는다. 공통 엔진이
게시된 점수 기여도, 카탈로그 검색 신호, Hard Filter 결과, 양면 적합 상태를 allowlist와 대조하고,
어댑터가 제공한 비어 있지 않은 `evidence_ref`가 있을 때만 `reason-claim-v1.0`을 확정한다.
템플릿 또는 향후 LLM은 확정 claim의 표현만 바꿀 수 있고 코드·사실·근거를 추가할 수 없다.

기존 `matching-engine-command/result-v1.0`은 수정하지 않고 v1.1을 신규 게시한다. v1.0 명령에
근거 입력이 섞이면 실패 처리하며, 점수 계산지문과 reason 지문은 분리한다. Golden Set의 기존
`explanations` 필드는 호환상 유지하되 평가기에서는 기대 출력으로 신뢰하지 않고 어댑터 근거
binding으로만 사용하며 실제 facade 생성 claim을 검증한다. 상세 증거는
`.harness/reports/integration/reason-evidence-contract-20260802.md`를 따른다.

## DECISION-011 (2026-08-02) — XLSX는 공통 매칭엔진 앞단의 입력 어댑터

사전등록자·참여기업 Excel 자료를 별도 점수식이나 별도 정본으로 운영하지 않는다. 게시된
`meet-ai-excel-import-v1.0` 템플릿의 행을 기존 visitor/exhibitor JSON import 계약과 259개
온톨로지 UUID로 정규화한 뒤, 기존 승인·공개범위·Hard Filter·공통 facade를 그대로 사용한다.
브라우저 자유문 검색은 기존 `/api/v1/search`의 질의 해석·검색 경로를 사용한다.

기본 실행은 비저장 `dry_run=true`이고 수식·매크로·미등록 코드·비정상 ZIP을 fail-closed로
차단한다. 연락처와 원문 셀 값은 매칭 입력이나 행 오류 메시지에 포함하지 않는다. Excel로
유입된 참여기업 역시 `APPLIED` 상태이므로 운영 승인 전 검색·추천 대상이 되지 않는다.

## DECISION-012 (2026-08-02) — Excel 일괄 매칭도 웹 추천 파이프라인을 재사용

파일 기반 Top-N 결과를 위해 XLSX 행끼리 별도 유사도나 임시 점수식을 계산하지 않는다. 운영자가
지정한 불투명 `source_record_id`를 정본 프로파일로 해석하고, 사전등록 웹과 동일한 개인화 동의·
연령확인·승인 카탈로그·Hard Filter·공통 matching facade·결정적 설명·결과 저장 단계를 실행한다.

실패한 프로파일의 조건을 자동 완화하지 않고 처리상태 시트에 안정 오류코드를 기록한다. 결과
XLSX에는 불투명 원천 ID와 공개 업체정보, 점수, 근거, 정책 버전, eligibility ID와 지문만 포함하며
이름·전화·이메일·원문 프로파일 속성은 포함하지 않는다. 동기 요청은 100명×Top 10으로 제한하고,
그보다 큰 작업은 인증·worker 운영계약이 준비된 후 별도 비동기 작업으로 확장한다.

## DECISION-013 (2026-08-02) — RRF remains shadow-only

The deterministic `hybrid-rrf-shadow-v1.0` policy combines STRUCTURED, KEYWORD/BM25, and
VECTOR ranks only in offline shadow evaluation. It does not change `execute_matching`, the
published weighted-v1 catalog score, any API response, or stored recommendation rank.

If VECTOR is unavailable or was not invoked, the existing published order is retained exactly;
the engine does not renormalize remaining channels or emit a synthetic zero vector score.
Candidate-level UNKNOWN and MISSING business signals are separate diagnostics and never become
false, zero, or mismatch. Production promotion requires a separate versioned Change Request and
larger labeled plus runtime-shadow evidence. See
`.harness/reports/integration/hybrid-rrf-shadow-20260802.md`.

## DECISION-014 (2026-08-02) — Web-first channels supersede the kiosk split

CR-009 makes `REGISTERED_WEB`, `GUEST_WEB`, `BUYER_WEB`, and `ADMIN_PARTNER_WEB` the only active
MVP/v1.x channels. Dedicated kiosk hardware/runtime/deployment is excluded. QR codes on entrances,
badges, printed maps, and booths open `GUEST_WEB` directly; anonymous search cannot require signup
or profile-session creation.

The implemented kiosk source, API routes, stored records, and `/kiosk-handoff` are not deleted in
this change. They remain inactive compatibility assets until a separate versioned OpenAPI/data
removal decision defines retention and rollback. Default root validation/build excludes
`backju-kiosk`. The matching engine remains channel-independent, and existing score, Hard Filter,
UNKNOWN, approval, evidence, and contact-sharing contracts do not change. See
`.harness/reports/integration/web-first-pivot-20260802.md`.

## DECISION-015 (2026-08-03) — 자연어와 Excel은 하나의 의도 계약으로 수렴

자연어 검색어와 표준 Excel에서 정본화된 프로파일 코드는 별도 점수식이나 별도 의미체계를
사용하지 않는다. 둘 다 `matching-intent-result-v1.0`의 `MUST`, `PREFER`, `EXCLUDE`,
`UNKNOWN`, `UNRESOLVED` 구조로 정규화한다. 자연어는 게시된 온톨로지의 선택 가능한 코드,
라벨, 승인 동의어만 확정하며 `OEM`, `수출`처럼 여러 코드로 해석되는 표현은 후보를 보존한
`UNRESOLVED`로 남긴다.

이메일·전화번호는 정규화·provider 호출·입력지문 전에 치환하고 결과에 원문을 포함하지 않는다.
선택적 LLM adapter의 출력은 `intent-proposal-v1.0` JSON Schema와 게시 온톨로지를 통과해도
`VALIDATED_PROPOSAL_ONLY` 상태일 뿐 Hard Filter나 점수 입력으로 자동 승격되지 않는다. 현재
`weighted-v1` 검색·추천 순위는 변경하지 않는다. 상세 증거는
`.harness/reports/integration/intent-normalization-20260803.md`를 따른다.

## DECISION-016 (2026-08-03) — 확정 의도만 검색·Hard Filter 계획에 투영

`intent-projection-v1.0`은 확정된 `PREFER`를 `STRUCTURED_ONTOLOGY` 후보회수 feature로만
투영하고, 확정된 `MUST`와 `EXCLUDE`만 검증 가능한 후보 필드의 Hard Filter constraint로
투영한다. 이 단계는 검색을 실행하거나 점수·순위·적격성을 계산하지 않는다.

공개 카탈로그에서는 거래지역·유통채널·OEM/PB/수출 등 검증 바이어 전용 필드를 계획에
포함하지 않는다. 해당 조건은 `CATALOG_SCOPE_RESTRICTED`로 보존한다. 검증 필드 바인딩이 없는
필수조건은 `INFORMATION_REQUIRED`이며 자동 적격 처리하지 않는다. constraint의 후보 관측값이
UNKNOWN 또는 MISSING인 경우에도 후속 평가기가 반드시 `INFORMATION_REQUIRED`로 처리하도록
계약에 명시한다. 의도 단계의 UNKNOWN, UNRESOLVED, LLM proposal은 모두 deferred 상태로 남아
검색조건·불일치·0점으로 변환되지 않는다. `weighted-v1` 공개순위는 그대로 유지한다. 상세
증거는 `.harness/reports/integration/intent-projection-20260803.md`를 따른다.

## DECISION-017 (2026-08-03) — Three-state eligibility precedes scoring

`constraint-evaluation-v1.0` evaluates only the hard constraints emitted by the verified intent
projection plan and only against explicit candidate observations. Each observation is `KNOWN`,
`UNKNOWN`, `MISSING`, or `STALE`; trade values `CONDITIONAL` and `NEGOTIABLE` also remain
information-required. These states are never coerced into a pass, mismatch, or numeric zero.

The overall candidate result is `ELIGIBLE`, `FILTERED_OUT`, or `INFORMATION_REQUIRED`. A proven
constraint violation takes precedence in the overall state while every per-constraint diagnostic
is retained. Only a fully `ELIGIBLE` evaluation may become the existing scoring
`EligibilityDecision`. Results expose stable reason codes, opaque evidence references, and
fingerprints, but omit raw query text and observed private field values. The published weighted-v1
formula, public APIs, database schema, and runtime rank are unchanged. Runtime adoption requires
AIENGINE-009 shadow parity evidence. See
`.harness/reports/integration/constraint-evaluation-20260803.md`.

## DECISION-018 (2026-08-03) — Runtime constraint evaluation remains shadow-only

`candidate-observation-adapter-v1.0` maps only fields requested by a verified intent plan. Public
product observations require explicit public approval, and buyer trade observations additionally
require an approved supply profile. Missing, stale, unknown, conditional, and negotiable values
retain their information state. Raw candidate values exist only inside the evaluator input and are
absent from the shadow result.

`hard-filter-shadow-v1.0` runs after the existing Hard Filter decision and classifies the comparison
as `PARITY`, `SAFETY_GAP`, `DIVERGENCE`, `NOT_COMPARABLE`, `NOT_APPLICABLE`, or `ADAPTER_ERROR`.
The legacy decision remains authoritative and the enforcement constant is fixed to false. Current
fixtures intentionally expose safety gaps where the legacy filter passes unknown or non-final trade
conditions, plus a public EXCLUDE condition that legacy filtering does not own. These findings are
evidence for a later promotion decision, not permission to change admission now.

Promotion requires a separate approved Change Request, zero divergence and adapter errors, a
versioned aggregate quality gate, a sufficient runtime sample, regression evidence, and rollback.
The weighted-v1 formula, API response, database schema, persistence, and rank remain unchanged. See
`.harness/reports/integration/runtime-constraint-shadow-20260803.md`.

## DECISION-019 (2026-08-03) — Browser identity is server-derived and mutations are origin-bound

Personal links contain only opaque random material and are consumed once into a Secure/HttpOnly
server session. Browser identity, tenant, event, role, profile, and exhibitor scope are loaded from
that session and database grants; caller-supplied identity headers cannot create or alter a
principal. Service integrations use allowlisted RS256 JWT verification and never issue browser
refresh tokens.

Every unsafe request authenticated by the browser cookie must present both an allowlisted HTTPS
Origin and a CSRF token bound to the current session. MFA success rotates the session token only
after the old session request has passed this check. Magic-link plus TOTP remains AAL1; WebAuthn or
an independently verified different primary factor plus TOTP is required for AAL2. Frontend role
menus are hints only and backend resource-scope checks remain authoritative.

## DECISION-020 (2026-08-03) — Web entry creates continuity before personalization

The active web may create an anonymous guest session without login so the common matching engine
can receive a stable event-scoped profile. `POST /sessions` creates the guest, minimal profile, and
visit session together. The credential is opaque, digest-stored, and available to the browser only
through the Secure/HttpOnly guest cookie; record IDs in the response are references, not credentials.

Preregistered users enter through an opaque, single-use personal link at `/e/{event_slug}/my` and
are mapped server-side. User IDs, contact values, and roles do not appear in the URL. Phone OTP is
not a fallback until its provider, rate-limit, merge-confirmation, and retention contract is approved.
Dedicated kiosk entry remains outside the active web-first scope.

## DECISION-021 (2026-08-03) — Matching calculation and user delivery are separate boundaries

`POST /api/v1/recommendations` and approved batch workers own matching calculation and persistence.
The user-facing `GET /api/v1/home` is a read-only delivery query: it selects the newest owned
`ACTIVE` recommendation snapshot, projects its persisted items and version metadata, and never
invokes the recommendation orchestrator, an LLM, or an external messaging provider. An expired
snapshot may remain visible as stale while an invalidated snapshot is never delivered. If no
snapshot exists, the API returns retryable `RECOMMENDATION_NOT_READY`; a page view cannot
implicitly spend compute or create a new ranking.

Both the normal `/home` route and opaque personal-link `/e/{event_slug}/my` route render the same
mobile-first My Event dashboard. Kakao, SMS, and email remain optional entry adapters that carry a
personal access link, not alternate recommendation products. No provider integration or dedicated
kiosk flow is introduced by this decision; the CR-009 web-first boundary remains authoritative.

## DECISION-022 (2026-08-03) — Alimtalk is the primary doorway, not the product

The mobile My Event web remains the service surface. An approved informational business event may
enqueue one personal-link notification through a transactional Outbox, with channel order fixed to
`KAKAO_ALIMTALK → SMS → EMAIL`. A successful channel stops the chain. Rank movement, ordinary
catalog changes, saved-item changes, searches, and page views never enqueue a message.

The queue stores only pseudonymous business references and an AEAD-encrypted access URL. Phone,
email, name, raw token, and provider request/response bodies are absent from notification and Outbox
records. Channel attempts are append-only and use safe provider IDs/failure codes. Workers use
`SKIP LOCKED` plus expiring leases so a crashed worker does not strand a delivery. Personal-link
exchange records the first click using the link reference; no separate tracking token is added.

Only `INFORMATIONAL` templates are accepted. The initial recommendation-ready template includes
event name, recipient name, factual result count, and one My Event web button; it contains no named
exhibitor, sponsor placement, discount, purchase inducement, or numeric score. Actual external
sending remains disabled until an official Kakao dealer, business channel, approved template codes,
callback authentication/status mapping, SMS/email fallbacks, credentials, and legal/operations
approval are supplied. The Kakao Talk Message API is not used for service notifications.
