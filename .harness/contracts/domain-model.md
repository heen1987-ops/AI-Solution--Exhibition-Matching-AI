# Domain Model (CTR-001)

상태: **CONFIRMED** (이 문서가 CTR-001의 완성본이다).

## 0. 이 문서의 목적, 근거, 사용 방법

이 문서는 "백주대간 AI 매칭·탐색 서비스"의 단일 도메인 모델 레퍼런스다. 두 종류의 근거를 대조해 만들었다.

- **A) 목표 도메인 모델(무엇을 만들어야 하는가)**: `docs/redesign-v2/00-master-spec-v1.md`, `01-module-split-plan.md`, `04-integration-roadmap.md`, `web/W-1`~`W-10`, `kiosk/K-1`~`K-8`, `common/C-1`~`C-8` (26개 문서 전체 읽음).
- **B) 실제 구현(무엇이 이미 있는가)**: `backend/app/models/{identity,profile,exhibitor,matching,meeting,consent,core,ontology_refs}.py`, `backend/app/db/base.py`(스키마 상수 목록), `backend/alembic/versions/*.py`(0001~0008 마이그레이션 체인).

**핵심 결론(26개 문서를 관통하는 한 문장)**: 이번 재설계는 대부분 "기존 스키마 재발견·재계량(recalibration)"이지, 새 스키마 설계가 아니다. 진짜 신규 스키마가 필요한 영역은 정확히 두 곳이다 - **(1) `profile.saved_recommendable`**(관심 저장, W-8 §4)과 **(2) 신규 `ai` 스키마 6개 테이블**(업체정보 AI 구조화·임베딩, C-2/C-4). 그 외 모든 엔티티는 기존 테이블을 그대로 재사용하거나(REUSED_AS_IS), 값 목록·API 매핑 등 좁은 범위의 조정만 필요하다(REUSED_WITH_CAVEAT).

**상태 라벨 정의**:
- `REUSED_AS_IS`: 기존 테이블/컬럼을 변경 없이 그대로 쓴다.
- `REUSED_WITH_CAVEAT`: 기존 테이블은 그대로 두되, 사용 범위 축소·API 레이어 매핑·값 목록 확장 등 코드 레벨 조정이 필요하다.
- `NEW_REQUIRED`: 이번 재설계로 신규 테이블(또는 신규 스키마)이 필요하다.

**소비자**: CTR-002(OpenAPI 초안)가 이 문서의 엔드포인트별 요청/응답 엔티티 매핑에 직접 의존한다. CTR-006(`saved_recommendable` 마이그레이션)은 §4의 확정 스키마를 그대로 구현한다. BACKEND/USER_WEB/KIOSK/ADMIN/AI_SEARCH 트랙은 각자 담당 화면·엔드포인트가 어느 테이블에 대응하는지 이 문서에서 찾는다.

**이 문서가 다루지 않는 것**: 실제 마이그레이션 코드, OpenAPI 스펙, 서비스 계층 구현. 이 문서는 참조 문서이지 구현이 아니다(AGENTS.md §11 "계획만 반복" 금지와는 별개로, CTR-001의 acceptance는 문서 산출물이다).

### 0.1 스키마 목록 (`backend/app/db/base.py`)

`core`, `identity`, `profile`, `ontology`, `exhibition`, `matching`, `interaction`, `ai`, `integration`, `privacy`, `audit`, `quality`, `analytics` - 13개 스키마 상수가 이미 정의되어 있다. 이 중 `ai`/`integration`/`quality`/`analytics`는 상수만 있고 **아직 테이블이 하나도 구현되지 않았다** - `ai`는 §11에서 신규 테이블이 필요하다고 확정하고, `integration`/`quality`/`analytics`는 이번 CTR-001 범위(26개 W/K/C 문서)에서 참조하는 엔티티가 없어 이 문서에서 다루지 않는다.

### 0.2 마이그레이션 체인 (참고용)

`0001_create_schemas` → `0002_ontology` → `0003_foundation`(core/exhibition 기본 골격, profile.user_account/role/user_role/guest_session/consent_policy/user_consent, identity.*, privacy.*, audit.audit_log) → `0004_profile_domain`(profile.user_profile 등 5+2 테이블) → `0005_exhibition`(exhibitor.py 전체) → `0006_matching` → `0007_meeting` → `0008_widen_recommended_action`(matching.match_result.recommended_action CHECK 확장). CTR-006이 만들 `saved_recommendable` 마이그레이션은 `0008_widen_recommended_action` 이후에 연결되어야 한다.

---

## 1. 테넌트·행사 경계 (core / exhibition)

| 항목 | 내용 |
| --- | --- |
| 엔티티 | `core.Tenant`, `exhibition.Event`, `exhibition.EventDay`, `exhibition.EventZone` |
| 실재 위치 | `backend/app/models/core.py` |
| 결정 문서 | 마스터 스펙 §6(데이터 모델 목록)이 전제하는 최상위 경계. W/K/C 문서 전체가 이 4개 테이블을 이미 존재하는 것으로 가정하고 그 위에 설계한다(직접 재설계 대상은 아니지만 모든 tenant/event 스코프 FK의 근거) - 명시적으로는 `docs/redesign-v2/kiosk/K-5-map-location-qr.md` §1("`exhibition.event_zone` 참조")이 EventZone을 직접 인용한다. |
| 핵심 필드/제약 | `Tenant.status IN ('ACTIVE','SUSPENDED')`. `Event.event_status IN ('PREPARING','OPEN','CLOSED')`, `start_date <= end_date`, `current_taxonomy_version_id` FK(온톨로지 버전 고정 - 행사마다 다른 분류체계 버전을 쓸 수 있음). `EventZone`은 `parent_zone_id` 자기참조(계층 구조), 좌표(`coordinate_x/y`)는 있지만 §56 "정밀 위치추적" 제외 원칙에 따라 실제 사용은 zone 단위(K-5 §2)로 한정. |
| 상태 | `REUSED_AS_IS` |

---

## 2. 사용자 식별·역할·게스트 세션 (identity / profile)

### 2.1 계정·식별정보·인증수단

| 항목 | 내용 |
| --- | --- |
| 엔티티 | `profile.UserAccount`, `identity.UserIdentity`, `identity.AuthenticationMethod` |
| 실재 위치 | `backend/app/models/identity.py` |
| 결정 문서 | `docs/redesign-v2/web/W-1-scope-and-user-types.md` §1(사용자 유형 표), §3(GUEST_WEB과 지속 프로파일 없음 경계) |
| 핵심 필드/제약 | `UserAccount.authentication_state IN ('PHONE_VERIFIED','ACCOUNT_AUTHENTICATED')`(주의: W-1이 API로 노출하는 3분류 `GUEST\|PHONE_VERIFIED\|ACCOUNT_AUTHENTICATED`와 다르다 - GUEST는 이 컬럼의 값이 아니라 "user_account 행이 없음"으로 표현되는 BFF 합성값). `account_status IN ('ACTIVE','SUSPENDED','WITHDRAWN')`. `UserIdentity`는 이름·전화·이메일을 `*_enc`(암호화)+`*_hmac`(조회용) 쌍으로만 저장 - 평문 컬럼 없음. `AuthenticationMethod.method_type IN ('PHONE_OTP','EMAIL','SOCIAL')`. |
| 상태 | `REUSED_AS_IS` |

### 2.2 역할

| 항목 | 내용 |
| --- | --- |
| 엔티티 | `profile.Role`, `profile.UserRole` |
| 실재 위치 | `backend/app/models/identity.py` |
| 결정 문서 | `docs/redesign-v2/web/W-1-scope-and-user-types.md` §6-3, `W-8-api-and-db-changes.md` §2~3, `W-9-admin-operations.md` §1, `common/C-6-privacy-and-authorization.md` §1 |
| 핵심 필드/제약 | `Role.role_code IN ('VISITOR','BUYER','EXHIBITOR','OPERATOR','ADMIN')` - 마스터 스펙의 `EXHIBITOR_ADMIN`/`EVENT_ADMIN`/`DATA_REVIEWER`와 이름이 다르다. **최종 결정(W-8 §2, W-9 §1, C-6 §1)**: DB 값은 바꾸지 않고 API 응답 레이어에서만 매핑한다(`VISITOR→GENERAL_REGISTERED`, `EXHIBITOR→EXHIBITOR_ADMIN`, `OPERATOR→EVENT_ADMIN`). `DATA_REVIEWER`는 별도 `role_code`를 신설하지 않고 `EVENT_ADMIN`(`OPERATOR`) 내부의 서비스 계층 권한 스코프 상수로 처리한다(테이블 변경 없음, C-6 §1) - 즉 `role_code_allowed` CHECK 확장 마이그레이션은 **불필요**로 최종 재분류됐다(W-8 §1이 "중간 우선순위"로 남긴 항목을 W-9/C-6이 대체). `UserRole`은 `(tenant_id, event_id, user_id, role_id, exhibitor_id)` partial unique(활성 역할 중복 방지), `exhibitor_id`는 `(tenant_id, exhibitor_id)` 복합 FK로 `exhibition.exhibitor` 경계를 강제. |
| 상태 | `REUSED_WITH_CAVEAT` (API 레이어 매핑 코드만 신규 - `04-integration-roadmap.md` 2단계 2-A/2-C) |

### 2.3 게스트 세션

| 항목 | 내용 |
| --- | --- |
| 엔티티 | `profile.GuestSession` |
| 실재 위치 | `backend/app/models/identity.py` |
| 결정 문서 | `docs/redesign-v2/kiosk/K-1-service-scope.md` §0~1(entry_channel 3분할이 이미 웹/키오스크 분리를 예견), §4(자동 세션 초기화), §5(QR 인계); `K-5-map-location-qr.md` §5(`entry_code`를 QR 인계 토큰으로 재사용) |
| 핵심 필드/제약 | `entry_channel IN ('QR','WEB','KIOSK')` - `KIOSK`=`KIOSK_GUEST`, `QR`=키오스크에서 인계된 `GUEST_WEB`, `WEB`=웹에서 직접 방문한 `GUEST_WEB`. 이름·연락처 컬럼이 **아예 없음**(개인정보 저장 자리 자체가 없는 구조) - `session_token_hmac`(원문 토큰 미저장), `entry_code`(nullable, QR 인계 토큰 값으로 재사용), `expires_at`(TTL, 정확한 초 단위는 K-8에서 미확정), `converted_user_id`/`converted_at`(회원 전환 이력). |
| 상태 | `REUSED_AS_IS` (QR 인계 프로토콜은 신규 테이블 없이 기존 `entry_code` 컬럼 재사용으로 확정 - K-5 §5) |

---

## 3. 사용자 프로파일 (profile)

| 항목 | 내용 |
| --- | --- |
| 엔티티 | `profile.UserProfile`, `profile.ProfileAttribute`, `profile.InferredPreference`, `profile.ProfileVersion`, `profile.VisitSession`, `profile.ContextProfile`, `profile.BuyerNeed` |
| 실재 위치 | `backend/app/models/profile.py` |
| 결정 문서 | `docs/redesign-v2/web/W-4-profile-model.md`(전체) - 마스터 스펙 §9~10/§34 하위 항목(등록정보/관심분야/방문목적/바이어 거래조건/사용자 수정 정보/행사 내 제한적 행동정보) 순서를 그대로 매핑. `W-2-user-journey.md` §1-3~1-5(여정 단계). |
| 핵심 필드/제약 | `UserProfile.user_type IN ('GENERAL_VISITOR','BUYER')`(마스터 스펙 `GENERAL_REGISTERED`/`BUYER_REGISTERED`와 API 레이어 매핑만, DB 값 불변 - W-4 §1), `profile_status IN ('DRAFT','COMPLETE','INACTIVE')`, `num_nonnulls(user_id, guest_session_id) = 1`(게스트/회원 상호배타), `completeness_score`(0~100, 진행률 지표로 재사용 - W-2 §1-3), `row_version`(낙관적 동시성). `ProfileAttribute.source_type` 11종 중 웹 모듈은 **5종만 채운다**(`USER_SELECTED`/`USER_EDITED`/`REGISTRATION`/`BEHAVIOR_SINGLE`/`AI_EXTRACTED` - W-4 §2, §5에서 최초 4종을 5종으로 정정), 나머지 6종은 스키마에서 제거하지 않고 미사용으로 남긴다. `requirement_level IN ('REQUIRED','PREFERRED','ACCEPTABLE','EXCLUDED')` - "명시적 제외"(§34.1 4대 행동 중 하나)는 `EXCLUDED` 값으로 표현하고 별도 테이블 불필요(W-4 §6). "방문목적"은 별도 테이블이 아니라 `ProfileAttribute.attribute_code`가 `GOAL.*`/`BIZ_GOAL.*` 접두어를 갖는 행으로 표현(W-4 §3, 신규 테이블 불필요). `VisitSession.session_status IN ('PLANNED','ACTIVE','COMPLETED','CANCELLED')`가 W-2 §1-5의 여정 전이(행사 전=PLANNED, 개인화 홈 진입=ACTIVE)와 그대로 대응. `BuyerNeed`는 1:1 확장(`profile_id` PK=FK), `business_email_verified`/`company_verified`가 W-9 §4의 "바이어 검증" 화면이 토글하는 필드. |
| GUEST_WEB 예외 | `GUEST_WEB`(`guest_session_id` 소유)에는 `InferredPreference`/`ProfileAttribute`의 `EXPLICIT`/`CONFIRMED` 관심사를 쌓지 않는다(W-1 §3, W-4 §6) - 회원 전환 이후부터 반영 시작. 게스트→회원 전환 시 **위치·방문세션 데이터(`VisitSession`/`ContextProfile`)는 FK 승계, 관심 신호(`InferredPreference`)는 승계하지 않는다**(W-8 §6 최종 결정, `04-integration-roadmap.md` 2단계 2-D) - 승계할 신호 자체가 애초에 없기 때문. |
| 상태 | `REUSED_AS_IS`(스키마 자체는 무변경) + `REUSED_WITH_CAVEAT`(서비스 정책상 사용 범위 축소 - `source_type` 5종 한정, GUEST_WEB 미기록 규칙 등은 코드 레벨 구현) |

---

## 4. 관심 업체 저장 (profile.saved_recommendable) — 신규

| 항목 | 내용 |
| --- | --- |
| 엔티티 | `profile.saved_recommendable` |
| 실재 위치 | **NEW — 아직 생성되지 않음.** `CTR-006`(`backend/alembic/versions/**`, `backend/app/models/profile.py`)이 이 마이그레이션을 담당한다. |
| 결정 문서 | 스키마 공백 최초 확인: `docs/redesign-v2/web/W-2-user-journey.md` §1-7. 필드 미결정 반복: `W-3-screen-ia.md` §3, `W-4-profile-model.md` §6/§7-2. **최종 확정**: `W-8-api-and-db-changes.md` §4. 마이그레이션 실행 항목: `04-integration-roadmap.md` 1단계 1-A. |
| 확정 스키마(W-8 §4 그대로) | `saved_recommendable_id UUID PK`, `profile_id UUID FK → profile.user_profile.profile_id`, `recommendable_id UUID FK → exhibition.recommendable.recommendable_id`, `saved_at TIMESTAMPTZ`, `saved_context_json JSONB NULL`(저장 시점 zone/검색어 등, 선택적 - 나중에 컨텍스트를 안 남기기로 결정해도 되돌릴 수 있도록 nullable로 시작), `UNIQUE(profile_id, recommendable_id)`(중복 저장 방지, 저장/해제 토글 UI 전제). |
| 소비 화면/API | S-4(관심목록), S-5(부스·업체 상세의 "저장" 버튼), S-6(바이어 매칭의 "업체 비교" - 별도 테이블 없이 이 테이블에 저장된 항목을 나란히 조회, W-7 §4). API: `POST/GET/DELETE /saved-recommendables`(W-8 §5, `04-integration-roadmap.md` 4단계 4-A). |
| GUEST_WEB 접근 | 불가 - "지속 프로파일 없음" 원칙(W-1 §3)에 따라 회원 전환 전에는 이 테이블에 쓰지 않는다(W-3 §1 S-4 정의). |
| 상태 | `NEW_REQUIRED` (CTR-006 담당, P0, 다른 여러 화면·기능이 이 테이블에 의존하므로 우선순위 최상단 - W-10 §5 "1. profile.saved_recommendable 마이그레이션 - 다른 항목 대부분이 이 테이블에 의존") |

---

## 5. 온톨로지 (ontology)

| 항목 | 내용 |
| --- | --- |
| 엔티티 | `ontology.taxonomy_version`, `ontology.concept`, `ontology.concept_revision`(+ `src/meet_ai/ontology/catalog.py`의 `concept_type`/`concept_synonym`/`resolve_synonym()`) |
| 실재 위치 | `backend/app/models/ontology_refs.py`(ORM에서 FK 해석용 최소 브릿지 - 실제 DDL은 `db/migrations/0001_ontology.sql`이 정본이며 Alembic autogenerate에서 의도적으로 제외됨, `info={"migration_managed_externally": True}`), `src/meet_ai/ontology/catalog.py`(온톨로지 카탈로그 정본) |
| 결정 문서 | `docs/redesign-v2/common/C-3-ontology.md`(전체) - "C-1/C-2와 반대로 여기는 이미 성숙한 자산" §0. `K-6-i18n-accessibility.md` §1(다국어 유사어), §4(고유명사는 번역 대상 아님). |
| 핵심 필드/제약 | `concept`는 `(concept_id, concept_code)` UNIQUE(다른 도메인 테이블이 `(taxonomy_version_id, concept_id)` 복합 FK + `(concept_id, attribute_code)` 복합 FK 두 겹으로 이 정본을 참조하는 패턴이 exhibitor.py/profile.py 전역에서 반복됨 - "모든 업무 테이블은 개념 참조 시 `(taxonomy_version_id, concept_id)`를 함께 FK로 둔다"는 규칙, exhibitor.py 모듈 docstring 인용). `concept_synonym`은 `locale`/`synonym_text`/`normalized_text`/`approval_status`로 다국어 유사어 지원 - K-6 §1의 한국어+영어 지원 요구를 스키마 변경 없이 데이터 추가만으로 충족. 마스터 스펙 §6의 6개 카테고리(산업/기술/제품·서비스/활용목적/바이어 거래유형/유사어)는 전부 기존 `attribute_code` 접두어(`CATEGORY.*`/`USE.*`/`SERVICE.*`/`GOAL.*`+`BIZ_GOAL.*`/`TRADE.*`+`BUYER.*`)로 이미 커버됨(C-3 §1) - 신규 `concept_type` 불필요. |
| 상태 | `REUSED_AS_IS` |

---

## 6. 참가업체·부스·제품·거래조건 (exhibition)

마스터 스펙 §6은 7개 플랫 테이블만 제시하지만 실제로는 20개 세분화 테이블이 이미 구현되어 있다(`C-1-exhibitor-booth-data-model.md` §0~1). 아래는 그 매핑이다.

| 마스터 스펙 §6 개념 | 실재 테이블(`exhibition` 스키마) | 결정 문서 | 핵심 필드/제약 |
| --- | --- | --- | --- |
| `exhibitor` | `Exhibitor` + `ExhibitorBusinessType` | C-1 §1 | `master_approval_status IN ('DRAFT','APPROVED','REJECTED')`(C-2/C-4의 승인 게이트 트리거), `data_completeness_percent`(0~100), `business_type_*`/`region_*`는 온톨로지 복합 FK. 복수 유형(08 4.2절)은 `ExhibitorBusinessType`으로 정규화. |
| `event_participation` | `ExhibitorParticipation` + `ParticipationCategory` | C-1 §1 | `participation_status IN ('APPLIED','APPROVED','CANCELLED')`. 업체(`Exhibitor`)와 행사 참가가 분리되어 재참가 구조 지원. |
| `booth` | `Booth` + `BoothStatusHistory` + `BoothQr` | C-1 §1, §3 | `operating_status IN ('OPEN','PAUSED','CLOSED')`, `congestion_level IN ('LOW','MEDIUM','HIGH','UNKNOWN')`, `row_version`(낙관적 동시성). **`BoothQr`(부스 부착 정적 QR, 부스 상세로 이동)과 K-5의 "키오스크 화면 동적 QR"(모바일 인계)은 서로 다른 기능** - 이름 혼동 주의(C-1 §3). |
| `product_service` | `Product` + `EventProduct` + `ProductAttribute` + `ProductImage` | C-1 §1 | `Product`(상시 마스터) vs `EventProduct`(행사별 가격·재고·시음·판매 상태) 분리 - "상시정보와 행사정보 분리" 원칙(08 2.2절). `tasting_status`/`purchase_status`/`inventory_status` 등 3종 상태. `ProductAttribute.review_status`가 `APPROVED`가 되기 전에는 매칭·검색 근거로 쓰지 않음. |
| `exhibitor_interest` | `ExhibitorProfile` + `ProductProfile` + `SupplyProfileAttribute` | C-1 §1 | 업체·제품의 온톨로지 개념 연결(관심분야 태깅), 08 27절 "공급 프로파일". `approval_status IN ('DRAFT','SUBMITTED','APPROVED','REJECTED')`(4단계, `master_approval_status`보다 세분화). |
| `public_trade_condition` | `TradeCondition` + `TradeConditionTerm` | C-1 §1 | `oem_status`/`private_label_status`/`export_status IN ('YES','NO','CONDITIONAL','NEGOTIABLE','UNKNOWN')`(08 2.4절 "미등록과 불가능 분리" - boolean이 아니라 5단계). 지역·채널·국가는 `TradeConditionTerm`으로 정규화. |
| `booth_status`(운영상태) | `BoothStatusHistory` | C-1 §1 | append-only, `context_reranker.py`가 이미 소비. |
| (스펙에 명시 안 됨) | `SupplyCapability` / `ExhibitorBuyerPreference` | C-1 §1("누락 항목의 재발견") | §57 Buyer Match Score의 capacity/buyer_type/channel/region 컴포넌트 근거 - 마스터 스펙 §6 목록엔 없지만 §57 요구를 위해 반드시 필요. `ExhibitorBuyerPreference`는 `buyer_type`/`channel`/`region` 중 최소 1개 온톨로지 차원 필수. |
| (별도 담당자 개념) | `ExhibitorStaff` + `StaffTopic` | 08 13절(C-1이 db-erd 12.4로 인용) | 담당자는 업체가 아니라 "행사 참가" 단위에 연결(행사마다 다른 담당자 배정 가능). `staff_topic`(상담 전문분야)이 없으면 적합해도 추천 순위 낮춤(매칭엔진 책임). |
| (프로그램) | `Program` | db-erd 13.2(C-1 범위 밖이나 동일 스키마) | `status IN ('PLANNED','OPEN','CLOSED','CANCELLED')`. |

**상태**: 전부 `REUSED_AS_IS` - C-1 §0의 결론대로 "재설계가 아니라 매핑 작업"이다.

---

## 7. 추천 대상 레지스트리 (exhibition.recommendable)

| 항목 | 내용 |
| --- | --- |
| 엔티티 | `exhibition.Recommendable` |
| 실재 위치 | `backend/app/models/matching.py` (스키마는 `exhibition`) |
| 결정 문서 | `docs/redesign-v2/common/C-1-exhibitor-booth-data-model.md` §2("마스터 스펙 §6에 대응 개념 없음 - 구현 세부사항이라 상위 스펙에 안 나온 것으로 해석, 그대로 유지"), `common/C-4-search-recommendation-engine.md` §4(승인 게이트) |
| 핵심 필드/제약 | `object_type IN ('BOOTH','EVENT_PRODUCT','EXHIBITOR','PROGRAM')`, `num_nonnulls(booth_id, event_product_id, participation_id, program_id) = 1`(정확히 하나의 대상), 각 FK 컬럼에 partial unique(대상당 recommendable 1개). **미승인 업체 차단 최종 결정(C-4 §4)**: 사후 비활성 플래그가 아니라 **사전 등록 게이트** - `master_approval_status = 'APPROVED'`인 업체·제품만 애초에 레지스트리 행을 생성한다. 승인이 철회되면 소프트 삭제(비활성화)로 처리. |
| 소비처 | `profile.saved_recommendable`(§4)이 FK로 참조, `matching.match_result`/`matching.filter_result`가 FK로 참조, K-4의 검색 결과도 궁극적으로 이 ID를 반환. |
| 상태 | `REUSED_AS_IS`(테이블 자체) + `REUSED_WITH_CAVEAT`(등록 게이트 로직은 C-2의 `ai.content_approval`이 확정되는 시점에 서비스 계층이 새로 연동해야 함 - `04-integration-roadmap.md` 3단계 3-F) |

---

## 8. 매칭·추천 정책과 결과 (matching)

| 항목 | 내용 |
| --- | --- |
| 엔티티 | `matching.MatchPolicyVersion`, `matching.MatchWeight`, `matching.FilterRule`, `matching.RecommendationSession`, `matching.MatchResult`, `matching.MatchReason`, `matching.FilterResult` |
| 실재 위치 | `backend/app/models/matching.py` |
| 결정 문서 | `docs/redesign-v2/web/W-5-recommendation-logic.md`(전체), `common/C-4-search-recommendation-engine.md` §1~2 |
| 핵심 필드/제약 | `MatchPolicyVersion`: `(tenant_id, event_id, user_type)`당 `status='ACTIVE'` 정책 최대 1개(partial unique). `FilterResult.result IN ('PASS','FAIL','UNKNOWN','CONDITIONAL_PASS','MANUAL_REVIEW','TEMPORARY_BLOCK','POLICY_BLOCK','USER_EXCLUDED')`(8종 - CTR-004 오류코드 매핑의 근거 어휘). `MatchResult.recommended_action`은 `0008_widen_recommended_action` 마이그레이션으로 CONSUMER 7종 + BUYER/EXHIBITOR 3종(`REQUEST_INFORMATION`/`CONFIRM_TRADE_CONDITION`/`DO_NOT_PUSH`) 합집합 10종을 허용하도록 이미 확장됨. |
| **재계량 결정(W-5, 신규 스키마 아님)** | 기존 `src/meet_ai/scoring/engine.py`의 `CONSUMER_SCORE_V1`/`BUYER_SCORE_V1`을 그대로 재사용하되 §57 비율로 **가중치만 재조정**(`ScoringPolicy.weights`, 코드 변경 - `04-integration-roadmap.md` 2단계 2-B). 컴포넌트 재그룹(예: price/moq/capacity를 order_scale로 합치기)은 **하지 않는다** - 계산은 세분화된 채로, 표시만 마스터 스펙 어휘에 맞춘다(W-5 §3). `current_query`(웹의 실시간 검색결과 반영) 컴포넌트는 `feature_builder.py`에 **신규 추가 필요**(코드 변경, C-4 선행 필요 - `04-integration-roadmap.md` 3단계 3-E). |
| **키오스크 전용 신규 정책(코드, 테이블 아님)** | `KIOSK_SEARCH_SCORE_V1`(0.45 Semantic + 0.30 Keyword + 0.15 Category + 0.05 Data Quality + 0.05 Booth Availability) - 웹의 `CONSUMER_SCORE_V1`을 변형한 것이 아니라 **완전히 별개의 신규 `ScoringPolicy` 객체**(C-4 §2, `04-integration-roadmap.md` 3단계 3-D). `MatchPolicyVersion`/`MatchWeight` 테이블 구조 자체는 무변경 - 새 `policy_version` 행 + `match_weight` 행들만 데이터로 추가하면 된다. |
| **검색 레이어 결정** | RRF(후보 검색, C-4 책임)와 가중합(점수 계산, W-5/K-4 책임)은 **서로 다른 레이어라 공존**한다(대체 관계 아님) - C-4 §1 최종 결정. |
| 상태 | `REUSED_AS_IS`(테이블 스키마) + `REUSED_WITH_CAVEAT`(가중치 재조정·신규 정책 데이터·`current_query` 컴포넌트는 코드/데이터 변경, AI_SEARCH 트랙 담당) |

---

## 9. 상담(간단 바이어 매칭) — interaction.meeting 계열

| 항목 | 내용 |
| --- | --- |
| 실재 위치 | `backend/app/models/meeting.py` (schema=`interaction`, 7개 테이블 이미 구현됨) |
| 결정 문서 | `docs/redesign-v2/web/W-7-buyer-matching-consultation.md`(전체) - PROJECT_SCOPE.md의 "이번 재설계에서 확정된 축소" 항목과 동일 결정. |

### 9.1 MVP에 노출 (3개) - `REUSED_AS_IS`

| 테이블 | 역할 | 핵심 제약 |
| --- | --- | --- |
| `interaction.Meeting` | 상담 요청 루트 | `status IN (10종: REQUESTED/VIEWED/COUNTER_PROPOSED/CONFIRMED/COMPLETED/FOLLOW_UP/REJECTED/CANCELLED_BY_BUYER/CANCELLED_BY_EXHIBITOR/NO_SHOW)` - 웹 화면(S-6)은 이 중 `REQUESTED`→`CONFIRMED` 또는 `REJECTED`/`CANCELLED_*` 두 갈래만 노출(W-7 §1), 어휘 자체는 변경하지 않음(다른 소비자 대비). `message_enc`(암호화 저장, 평문 컬럼 없음). |
| `interaction.MeetingStatusHistory` | 상태 변경 이력 | append-only, `previous_status`/`new_status` 둘 다 위 10종 CHECK. |
| `interaction.MeetingContactShare` | 연락처 공유 | **"`accepted_at`만으로 연락처를 공개하지 않는다 - `meeting.status = CONFIRMED`와 `disclosed` 권한 검사를 함께 적용한다"**(기존 코드 주석, W-7 §3이 그대로 재확인 - AGENTS.md §8 "상담 수락 전 연락처 비공개" 원칙의 스키마 근거). `consent_policy_id` FK → `profile.consent_policy`(W-6 §4의 `BUYER_CONTACT_SHARE` 목적과 연동). 동의 철회 시에도 이미 `disclosed_at`이 찍힌 건은 소급 삭제하지 않음(W-7 §3). |

### 9.2 MVP에서 노출하지 않음, 삭제도 하지 않음 (4개)

| 테이블 | 제외 사유 |
| --- | --- |
| `AvailabilitySlot` | §56 "대규모 상담장 자동배정" 제외 대상 - "요청→수락"만으로 충분(W-7 §2) |
| `MeetingSlotRequest` | 위와 동일(슬롯이 없으면 슬롯 요청도 불필요) |
| `MeetingOutcome` | §56 "장기 거래 CRM"(영업 리드 추적) 제외 대상 |
| `FollowUpAction` | 위와 동일(후속 조치 CRM) |

**중요**: `04-integration-roadmap.md` §8이 명시하듯 "이번 재설계로 스키마에서 실제로 삭제되는 것은 없다" - 이 4개는 API·화면 노출만 안 할 뿐 스키마·모델 파일에서 제거하지 않는다. BACKEND/USER_WEB 트랙은 이 4개 테이블에 대한 CRUD 엔드포인트/화면을 만들지 않아야 한다(PROJECT_SCOPE.md "이번 재설계에서 확정된 축소" 항목과 정확히 일치).

**상태**: 3개 `REUSED_AS_IS`(API 노출 대상) / 4개 `REUSED_WITH_CAVEAT`(스키마 유지, API·화면 노출 범위만 축소).

---

## 10. 동의·개인정보 권리·감사 (profile / privacy / audit)

| 항목 | 내용 |
| --- | --- |
| 엔티티 | `profile.ConsentPolicy`, `profile.UserConsent`, `privacy.PrivacyRequest`, `privacy.RetentionPolicy`, `privacy.DeletionJob`, `audit.AuditLog` |
| 실재 위치 | `backend/app/models/consent.py` |
| 결정 문서 | `docs/redesign-v2/web/W-6-information-delivery-policy.md` §4(수신동의 목적 3종 확정), `common/C-6-privacy-and-authorization.md` §2(웹 동의 재확인), §6(로그·감사 이원 체계) |
| 핵심 필드/제약 | `ConsentPolicy.purpose`는 자유 문자열(CHECK 없음) - 웹 모듈이 쓰는 표준값 3개를 **서비스 정책으로 고정**: `EVENT_INFO_NOTIFICATION`(행사정보 알림), `PERSONALIZED_RECOMMENDATION`(개인화 추천 - 철회 시 콜드스타트/무프로파일 검색 경로로 폴백, W-6 §4), `BUYER_CONTACT_SHARE`(연락처 공유, §9.1 `MeetingContactShare`와 연동). `UserConsent`는 불변 이력(과거 행을 UPDATE하지 않음), `num_nonnulls(user_id, guest_session_id) = 1`. `PrivacyRequest.request_type IN ('ACCESS','EXPORT','CORRECT','DELETE','WITHDRAW')`. `AuditLog`는 append-only(updated_at/row_version 없음), `actor_role`은 FK가 아니라 행위 시점 스냅샷 문자열. **로그 이원 체계(C-6 §6)**: AI 호출은 `ai.ai_execution_log`(§11, 신규) 전용, 그 외 데이터 변경(승인·역할배정 등)은 기존 `audit.audit_log` 재사용 - 신규 통합 로그 테이블은 만들지 않는다. |
| 상태 | `REUSED_AS_IS` (테이블은 이미 `0003_foundation` 마이그레이션에서 전부 생성됨 - `privacy`/`audit` 스키마도 이미 구현되어 있다는 점에 주의: C-2 §0가 "ai 스키마처럼 아직 없다"고 서술한 것과 달리 `privacy`/`audit`는 이미 존재) |

---

## 11. 신규 `ai` 스키마 — 업체정보 AI 구조화·임베딩 (NEW)

| 항목 | 내용 |
| --- | --- |
| 엔티티 | `ai.source_document`, `ai.extracted_attribute`, `ai.content_approval`, `ai.ai_execution_log`, `ai.embedding_document`, `ai.embedding_vector` |
| 실재 위치 | **NEW — 스키마 상수(`SCHEMA_AI = "ai"`)만 존재, 테이블은 하나도 구현되지 않음.** `backend/app/models/*.py` 전체에 대응 모델 파일 없음(C-2 §0에서 명시적으로 확인: "이전 세션에서 vector/behavior/popularity 검색이 `ai.object_embedding` 등 인프라 부재로 막혀 있다고 확인한 것과 같은 공백"). |
| 결정 문서 | `docs/redesign-v2/common/C-2-content-collection-ai-structuring.md` §0~2(4개 테이블 설계), `common/C-4-search-recommendation-engine.md` §3(임베딩 2개 테이블 + pgvector 확장). 실행 항목: `04-integration-roadmap.md` 1단계 1-B/1-C(병렬 가능, 선행 의존성 없음). |
| 신규 테이블 설계 (C-2 §2 그대로) | `ai.source_document`(참가신청서·업체소개·제품자료 원본 - 문서 유형, 업체/제품 FK, 저장 위치), `ai.extracted_attribute`(AI 추출 속성 후보 - `attribute_code`/`value`/`confidence`/상태 `PENDING`\|`CONFIRMED`\|`REJECTED`, `ontology.concept`와 동일 코드 체계 공유 - 업체 전용 하위 집합 없음, C-3 §2에서 재확인), `ai.content_approval`(운영자 승인 이력 - `approved_by`/`approved_at`/전후 `master_approval_status`, 승인 확정 시 서비스 로직이 `exhibition.exhibitor.master_approval_status`를 갱신), `ai.ai_execution_log`(AI 호출 로그 - 모델·프롬프트 버전, 입력 참조, 실행시간, 성공/실패). |
| 임베딩 (C-4 §3) | `ai.embedding_document` / `ai.embedding_vector` - pgvector 확장 활성화 필요(마스터 스펙 §5 기술스택에 이미 명시, 전용 벡터DB 도입 아님 - PROJECT_SCOPE.md 제외범위 "전용 벡터 데이터베이스" 원칙과 정합). 업체·제품 설명 텍스트 임베딩 + 자연어 질의 임베딩 코사인 유사도 비교용. **재계산 트리거 결정(C-5 §2)**: 즉시 동기 재계산이 아니라, `content_approval` 확정 시 비동기 워커(RQ/Celery) 큐잉 - 잡 완료 전까지는 이전 임베딩으로 검색 지속(짧은 지연 허용). |
| 흐름 | 참가신청서 업로드(`source_document`) → AI 추출(`extracted_attribute` PENDING, 동시에 `ai_execution_log` 기록) → 업체 확인(CONFIRMED/REJECTED) → 운영자 승인(`content_approval` 생성, `Exhibitor.master_approval_status = APPROVED`) → 승인된 속성만 `Recommendable` 레지스트리 등록 게이트(§7) 통과. |
| 상태 | `NEW_REQUIRED` — CTR 트랙 소관은 아니고(`.harness/locks.yaml`상 `backend/app/services/matching/**`, `src/meet_ai/scoring/**`는 AI_SEARCH 소유, 신규 `ai` 스키마 마이그레이션은 CONTRACTS 소유 `backend/alembic/versions/**`에 해당하므로 후속 CTR 태스크(현재 backlog에 전용 태스크 미배정 - CTR-002/003 이후 필요 시 신규 태스크로 등록 권장)가 담당해야 함 |

---

## 12. 자연어 검색 채널 (신규, 테이블 아님 — 참고용)

이 문서의 엔티티 정의는 아니지만 §8/§11과 직결되어 다른 트랙이 혼동하지 않도록 명시한다.

- **키워드 검색(FTS)**: PostgreSQL Full-Text Search를 `exhibition.Product`/`exhibition.Exhibitor`의 기존 텍스트 컬럼에 적용 - 신규 테이블 불필요, 인덱스만 추가(C-4 §3).
- **벡터 검색**: §11의 `ai.embedding_document`/`ai.embedding_vector`에 의존.
- **자연어 의도 추출**: LLM 호출 1회 → concept_id 목록, 실행 결과는 `ai.ai_execution_log`에 기록(§11).
- 이 3채널은 기존 `reciprocal_rank_fusion`(candidate_generator.py)에 새 채널로 추가되는 것이지, 후보 검색 프레임워크 자체를 재설계하는 것이 아니다(K-4 §0, C-4 §1).

---

## 13. 엔티티 상태 요약표 (빠른 조회용)

| # | 엔티티 | 스키마.테이블 | 상태 | 1차 결정 문서 |
| --- | --- | --- | --- | --- |
| 1 | 테넌트 | `core.tenant` | REUSED_AS_IS | K-5 §1 |
| 2 | 행사/일자/구역 | `exhibition.event`, `event_day`, `event_zone` | REUSED_AS_IS | K-5 §1 |
| 3 | 계정/식별정보/인증수단 | `profile.user_account`, `identity.user_identity`, `identity.authentication_method` | REUSED_AS_IS | W-1 §1, §3 |
| 4 | 역할 | `profile.role`, `profile.user_role` | REUSED_WITH_CAVEAT | W-8 §2~3, W-9 §1, C-6 §1 |
| 5 | 게스트 세션 | `profile.guest_session` | REUSED_AS_IS | K-1 §0~1, §5 |
| 6 | 사용자 프로파일 일체 | `profile.user_profile`, `profile_attribute`, `inferred_preference`, `profile_version`, `visit_session`, `context_profile`, `buyer_need` | REUSED_AS_IS/CAVEAT | W-4 전체 |
| 7 | **관심 업체 저장** | `profile.saved_recommendable` | **NEW_REQUIRED** | W-8 §4 (CTR-006) |
| 8 | 온톨로지 | `ontology.taxonomy_version/concept/concept_revision` | REUSED_AS_IS | C-3 §0~1 |
| 9 | 업체·제품·부스·거래조건(20개) | `exhibition.*`(§6 표) | REUSED_AS_IS | C-1 §0~1 |
| 10 | 추천 대상 레지스트리 | `exhibition.recommendable` | REUSED_AS_IS/CAVEAT | C-1 §2, C-4 §4 |
| 11 | 매칭 정책·결과 | `matching.*`(7테이블) | REUSED_AS_IS/CAVEAT | W-5 전체, C-4 §1~2 |
| 12 | 상담(3테이블 노출) | `interaction.meeting`, `meeting_status_history`, `meeting_contact_share` | REUSED_AS_IS | W-7 §1 |
| 13 | 상담(4테이블 비노출) | `interaction.availability_slot`, `meeting_slot_request`, `meeting_outcome`, `follow_up_action` | REUSED_WITH_CAVEAT(비노출) | W-7 §2 |
| 14 | 동의/개인정보권리/감사 | `profile.consent_policy/user_consent`, `privacy.*`, `audit.audit_log` | REUSED_AS_IS | W-6 §4, C-6 §2·6 |
| 15 | **AI 구조화·승인·로그** | `ai.source_document/extracted_attribute/content_approval/ai_execution_log` | **NEW_REQUIRED** | C-2 §2 |
| 16 | **임베딩** | `ai.embedding_document/embedding_vector` | **NEW_REQUIRED** | C-4 §3 |

---

## 14. 이 문서가 확정하지 않는 것 (다른 트랙/문서로 이관)

- 정확한 API 요청/응답 스키마(경로·파라미터·상태코드) → **CTR-002**(OpenAPI 초안)가 담당. 이 문서의 §4/§7/§9/§11 표에 나열한 엔드포인트 목록(`04-integration-roadmap.md` 4단계)이 CTR-002의 입력이다.
- `matching.filter_result.result` 8종 값을 실제 HTTP 오류코드로 매핑하는 작업 → **CTR-004**.
- `src/meet_ai/ontology/catalog.v1.json`의 `concept_type` 체계를 계약 형식으로 요약 → **CTR-003**.
- `ScoringPolicy.weights` 실제 수치 변경, `current_query`/`KIOSK_SEARCH_SCORE_V1` 실제 구현 → AI_SEARCH 트랙(AIS-GROUP-001, Wave 2).
- `ai.*` 6개 테이블·pgvector 확장의 실제 Alembic 마이그레이션 코드 → 아직 backlog에 전용 태스크가 없음(§11 참고, 이번 CTR-001 산출물이 이 공백을 명시적으로 드러낸 것 - 다음 CONTRACTS 웨이브에서 신규 태스크로 등록 권장).
- `profile.saved_recommendable`의 실제 마이그레이션 코드 → **CTR-006**(이미 backlog에 존재, 이 문서 §4가 그 입력).
