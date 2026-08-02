# 백주 AI 셀파 DB ERD 상세설계 및 테이블 정의서

> 문서 상태: PostgreSQL MVP 구현 기준안 v1.0  
> 기준일: 2026-08-01  
> 인터페이스 기준: [프론트엔드·백엔드·AI 인터페이스 명세](./frontend-backend-ai-interface-spec.md)  
> 매칭 처리 기준: [5단계 AI 매칭엔진 아키텍처](./05-ai-matching-engine-architecture.md)

## 1. 설계 목표

- 관람객·바이어·참가업체·운영 데이터를 이벤트 단위로 격리한다.
- 직접 식별정보와 추천·행동정보를 논리·권한상 분리한다.
- 익명 사용자도 프로파일·추천·저장·방문을 사용할 수 있다.
- 추천 시점의 프로파일, 정책, 모델, 현장상태를 재현한다.
- 제품 마스터와 행사별 가격·재고·시음·판매 상태를 분리한다.
- 추천부터 저장·경로·방문·상담·성과까지 동일 식별자로 연결한다.
- AI 추출값과 사람이 승인한 사실을 분리한다.
- 동의철회·보유기간·삭제 요청을 데이터 구조로 집행한다.
- 향후 다른 주최사와 전시회를 수용하는 멀티테넌시를 지원한다.

## 2. 원안 대비 필수 보정

| 항목 | 구현 기준 |
|---|---|
| 계정 유형 | GUEST·BUYER 등을 한 컬럼에 혼합하지 않고 인증상태와 역할을 분리 |
| 게스트 프로파일 | user_id 또는 guest_session_id 중 정확히 하나를 소유자로 지정 |
| 테넌트 격리 | 업무 테이블에 tenant_id와 event_id를 저장하고 복합 FK·RLS 적용 |
| 제품 상태 | 제품 마스터와 event_product의 현장 가격·재고·시음·판매를 분리 |
| 다형 참조 | object_type + object_id 대신 recommendable 테이블을 FK로 사용 |
| 연락처 공유 | 일반 동의 boolean이 아니라 상담별 공유 항목·문서버전·공개시각 저장 |
| 추천 버전 | 랭킹·설명·정책·택소노미·현장 스냅샷 버전을 각각 보존 |
| 추천 이유 | reason code와 evidence reference를 함께 저장 |
| 상담 슬롯 | 요청시간은 availability_slot FK로 저장하고 확정 시 원자적 점유 |
| 이벤트 PK | 파티션 키를 포함한 복합 PK 사용 |
| QR 중복 | 멱등성 레코드와 방문·부스 잠금으로 5분 중복 방지 |
| 임베딩 | 서로 다른 차원 벡터를 같은 인덱스에 혼합하지 않음 |
| 삭제 | 모든 테이블에 deleted_at을 기계적으로 추가하지 않음 |

## 3. 권장 물리 구성

MVP:

- PostgreSQL: 운영·추천·상담·동의·감사 메타데이터
- Redis: 세션, 속도 제한, 추천 캐시, 부스상태 캐시
- pgvector: 승인된 업체·제품 임베딩
- Object Storage: 업체·제품 이미지와 import 원본
- Outbox Worker: 행동·상담·동기화 이벤트 비동기 발행

확장 시:

- Kafka 또는 관리형 스트림
- 별도 분석 데이터웨어하우스
- OpenSearch 전문검색
- 외부 Append-only 감사 저장소

## 4. 스키마

| 스키마 | 책임 |
|---|---|
| core | 테넌트와 공통 주체 |
| identity | 암호화 식별정보와 인증수단 |
| profile | 계정, 역할, 세션, 동의, 사용자 프로파일 |
| ontology | 버전형 개념·계층·동의어·관계·원천 매핑·미분류 검수 큐 |
| exhibition | 행사, 업체, 제품, 부스, 프로그램 |
| matching | 추천정책, 실행, 결과, 근거 |
| interaction | 저장, 경로, 방문, 피드백, 상담 |
| ai | 모델, 실행, 추출속성, 임베딩 |
| integration | 원천연계, import, 멱등성, outbox |
| privacy | 보유정책, 권리요청, 삭제작업 |
| audit | 관리자·민감정보 접근 감사 |
| quality | 데이터 품질 이슈 |
| analytics | 운영 DB에서 파생한 데이터마트 |

identity와 audit 스키마는 일반 추천 서비스 계정의 직접 조회를 금지한다. 복호화는 별도 서비스 역할을 통해 수행한다.

## 5. 논리 ERD

~~~mermaid
erDiagram
    TENANT ||--o{ EVENT : owns
    EVENT ||--o{ EVENT_DAY : has
    EVENT ||--o{ EVENT_ZONE : contains
    EVENT ||--o{ EXHIBITOR_PARTICIPATION : hosts
    EXHIBITOR ||--o{ EXHIBITOR_PARTICIPATION : joins
    EXHIBITOR ||--o{ PRODUCT : owns
    EXHIBITOR_PARTICIPATION ||--o{ BOOTH : operates
    PRODUCT ||--o{ EVENT_PRODUCT : offered_as
    EVENT ||--o{ EVENT_PRODUCT : offers
    EVENT ||--o{ RECOMMENDABLE : exposes
    RECOMMENDABLE ||--o{ MATCH_RESULT : ranked_as

    USER_ACCOUNT ||--o| USER_IDENTITY : identifies
    USER_ACCOUNT ||--o{ USER_ROLE : assigned
    GUEST_SESSION ||--o{ VISIT_SESSION : starts
    USER_ACCOUNT ||--o{ VISIT_SESSION : attends
    USER_ACCOUNT ||--o{ USER_PROFILE : owns
    GUEST_SESSION ||--o{ USER_PROFILE : owns
    USER_PROFILE ||--o{ PROFILE_VERSION : snapshots
    USER_PROFILE ||--o{ PROFILE_GOAL : contains
    USER_PROFILE ||--o| CONSUMER_PREFERENCE : specializes
    USER_PROFILE ||--o| BUYER_NEED : specializes

    USER_PROFILE ||--o{ RECOMMENDATION_SESSION : drives
    PROFILE_VERSION ||--o{ RECOMMENDATION_SESSION : freezes
    RECOMMENDATION_SESSION ||--o{ MATCH_RESULT : produces
    MATCH_RESULT ||--o{ MATCH_REASON : explains

    VISIT_SESSION ||--o{ CHECK_IN : records
    VISIT_SESSION ||--o{ ROUTE : plans
    USER_PROFILE ||--o{ MEETING : requests
    AVAILABILITY_SLOT ||--o{ MEETING_SLOT_REQUEST : requested
    MEETING ||--o{ MEETING_SLOT_REQUEST : proposes
    MEETING ||--o{ MEETING_STATUS_HISTORY : changes
    MEETING ||--o| MEETING_OUTCOME : concludes
~~~

## 6. 공통 데이터 규칙

### 6.1 기본 키

- 애플리케이션 또는 검증된 DB 함수에서 생성한 UUID v7을 사용한다.
- 전화번호, 이메일, 사업자번호, 외부 사이트 ID를 PK로 쓰지 않는다.
- 외부 URL에 내부 순차번호를 노출하지 않는다.

### 6.2 공통 변경 컬럼

변경 가능한 마스터·업무 테이블:

| 컬럼 | 형식 | 규칙 |
|---|---|---|
| created_at | TIMESTAMPTZ | NOT NULL, now() |
| created_by | UUID | 서비스 주체 가능 |
| updated_at | TIMESTAMPTZ | NOT NULL, now() |
| updated_by | UUID | 서비스 주체 가능 |
| row_version | BIGINT | NOT NULL, 기본 1 |
| deleted_at | TIMESTAMPTZ | 논리삭제가 필요한 테이블만 |

스냅샷, 상태이력, 행동이벤트, 감사로그, outbox에는 updated_at이나 deleted_at을 두지 않는다.

### 6.3 숫자 제약

- confidence, 확률: 0 이상 1 이하
- 완성도·백분율: 0 이상 100 이하
- 가격·수량·대기시간: 0 이상
- min 값은 max 값보다 작거나 같음
- 시간 범위는 시작이 종료보다 빠름

### 6.4 멀티테넌시

- core.tenant를 최상위 소유자로 둔다.
- exhibition.event는 UNIQUE(tenant_id, event_code)를 가진다.
- 이벤트 업무 테이블은 tenant_id와 event_id를 함께 가진다.
- event는 UNIQUE(tenant_id, event_id)를 선언해 복합 FK 대상이 된다.
- API 세션에서 tenant_id를 주입하고 클라이언트 값은 신뢰하지 않는다.
- 파트너·운영자 테이블에는 PostgreSQL RLS를 적용한다.

## 7. core·identity

### 7.1 core.tenant

| 컬럼 | 형식 | 필수 | 설명 |
|---|---|---|---|
| tenant_id | UUID PK | Y | 주최 조직 |
| tenant_code | VARCHAR(50) UQ | Y | 시스템 코드 |
| tenant_name | VARCHAR(200) | Y | 표시명 |
| status | VARCHAR(20) | Y | ACTIVE, SUSPENDED |
| created_at | TIMESTAMPTZ | Y | 생성시각 |

### 7.2 profile.user_account

| 컬럼 | 형식 | 필수 | 설명 |
|---|---|---|---|
| user_id | UUID PK | Y | 가명 사용자 |
| authentication_state | VARCHAR(30) | Y | PHONE_VERIFIED, ACCOUNT_AUTHENTICATED |
| account_status | VARCHAR(20) | Y | ACTIVE, SUSPENDED, WITHDRAWN |
| default_language | VARCHAR(10) | Y | 기본 ko-KR |
| timezone | VARCHAR(50) | Y | 기본 Asia/Seoul |
| last_authenticated_at | TIMESTAMPTZ | N | 마지막 인증 |
| created_at, updated_at | TIMESTAMPTZ | Y | 변경시각 |
| deleted_at | TIMESTAMPTZ | N | 탈퇴 처리 |

GUEST는 계정 상태가 아니라 guest_session으로 표현한다.

### 7.3 identity.user_identity

| 컬럼 | 형식 | 필수 | 설명 |
|---|---|---|---|
| identity_id | UUID PK | Y | 식별정보 키 |
| user_id | UUID FK UQ | Y | user_account |
| name_enc | BYTEA | N | 봉투 암호화 성명 |
| phone_enc | BYTEA | N | 봉투 암호화 전화번호 |
| phone_hmac | BYTEA | N | 정규화 전화번호 HMAC |
| email_enc | BYTEA | N | 암호화 이메일 |
| email_hmac | BYTEA | N | 정규화 이메일 HMAC |
| phone_verified_at | TIMESTAMPTZ | N | 인증시각 |
| email_verified_at | TIMESTAMPTZ | N | 인증시각 |
| retention_expires_at | TIMESTAMPTZ | N | 목적별 계산 결과 |
| created_at, updated_at | TIMESTAMPTZ | Y | 변경시각 |

연령확인은 identity 속성이 아니라 동의·자격 이력에 저장한다. HMAC 키와 암호화 키를 분리하고 KMS/Vault에서 관리한다.

인덱스:

- UNIQUE(user_id)
- UNIQUE(phone_hmac) WHERE phone_hmac IS NOT NULL
- INDEX(retention_expires_at)

### 7.4 identity.authentication_method

| 컬럼 | 형식 | 설명 |
|---|---|---|
| authentication_method_id | UUID PK | 인증수단 |
| user_id | UUID FK | 사용자 |
| method_type | VARCHAR(30) | PHONE_OTP, EMAIL, SOCIAL |
| provider | VARCHAR(100) | 공급자 |
| provider_subject_hmac | BYTEA | 외부 식별자 HMAC |
| last_authenticated_at | TIMESTAMPTZ | 마지막 성공 |
| revoked_at | TIMESTAMPTZ | 폐기 |
| created_at | TIMESTAMPTZ | 생성 |

OTP challenge·실패횟수는 짧은 수명의 Redis 또는 별도 보안 테이블에서 관리하며 인증수단 마스터에 누적하지 않는다.

## 8. 역할·세션

### 8.1 profile.role

role_code: VISITOR, BUYER, EXHIBITOR, OPERATOR, ADMIN.

### 8.2 profile.user_role

| 컬럼 | 형식 | 설명 |
|---|---|---|
| user_role_id | UUID PK | 역할 배정 |
| tenant_id | UUID FK | 테넌트 |
| event_id | UUID FK | 이벤트 스코프, 전역 역할은 NULL |
| user_id | UUID FK | 사용자 |
| role_id | UUID FK | 역할 |
| exhibitor_id | UUID FK | 업체 역할 범위 |
| valid_from, valid_until | TIMESTAMPTZ | 유효기간 |
| granted_by | UUID | 부여자 |
| created_at | TIMESTAMPTZ | 생성 |

부분 유일성으로 동일 활성 역할 중복을 방지한다. EXHIBITOR 역할은 exhibitor_id 필수, OPERATOR는 event_id 필수다.

### 8.3 profile.guest_session

| 컬럼 | 형식 | 설명 |
|---|---|---|
| guest_session_id | UUID PK | 익명 세션 |
| tenant_id, event_id | UUID FK | 행사 |
| session_token_hmac | BYTEA UQ | 원문 토큰 미저장 |
| entry_channel | VARCHAR(20) | QR, WEB, KIOSK |
| entry_code | VARCHAR(100) | 진입 위치 |
| device_type | VARCHAR(30) | MOBILE_WEB 등 |
| language | VARCHAR(10) | 언어 |
| expires_at | TIMESTAMPTZ | 만료 |
| converted_user_id | UUID FK | 인증 전환 대상 |
| converted_at | TIMESTAMPTZ | 전환시각 |
| created_at | TIMESTAMPTZ | 생성 |

### 8.4 profile.visit_session

| 컬럼 | 형식 | 필수 | 설명 |
|---|---|---|---|
| visit_session_id | UUID PK | Y | 방문 단위 |
| tenant_id, event_id | UUID FK | Y | 행사 |
| user_id | UUID FK | N | 인증 사용자 |
| guest_session_id | UUID FK | N | 익명 세션 |
| profile_id | UUID FK | N | 적용 프로파일 |
| visit_date | DATE | Y | 행사 현지 날짜 |
| entry_at, exit_at | TIMESTAMPTZ | N | 입·퇴장 |
| available_minutes | INTEGER | N | 계획 체류 |
| current_zone_id | UUID FK | N | 최근 확인 구역 |
| current_zone_observed_at | TIMESTAMPTZ | N | 위치 확인시각 |
| route_preference | VARCHAR(30) | N | 경로 선호 |
| session_status | VARCHAR(20) | Y | PLANNED, ACTIVE, COMPLETED, CANCELLED |
| created_at, updated_at | TIMESTAMPTZ | Y | 변경시각 |

CHECK num_nonnulls(user_id, guest_session_id) = 1.

remaining_minutes는 현재시각과 계획을 이용해 계산하는 파생값으로 저장하지 않는다. 운영자가 고정 조정값이 필요하면 별도 override 컬럼을 둔다.

## 9. 동의·개인정보 권리

### 9.1 profile.consent_policy

| 컬럼 | 형식 | 설명 |
|---|---|---|
| consent_policy_id | UUID PK | 정책 |
| tenant_id | UUID FK | 조직 |
| event_id | UUID FK | 행사별 정책, 공통이면 NULL |
| purpose | VARCHAR(50) | AGE_CONFIRMATION 등 |
| document_version | VARCHAR(50) | 버전 |
| title, body | TEXT | 표시문 |
| required_for | VARCHAR(50) | AGE_SERVICE, PERSONALIZATION 등 |
| effective_from, effective_until | TIMESTAMPTZ | 유효기간 |
| content_hash | BYTEA | 문서 무결성 |
| created_at | TIMESTAMPTZ | 생성 |

UNIQUE(tenant_id, event_id, purpose, document_version).

### 9.2 profile.user_consent

| 컬럼 | 형식 | 설명 |
|---|---|---|
| consent_id | UUID PK | 선택 이력 |
| tenant_id, event_id | UUID FK | 행사 |
| user_id | UUID FK | 인증 사용자 |
| guest_session_id | UUID FK | 익명 사용자 |
| consent_policy_id | UUID FK | 정책 |
| accepted | BOOLEAN | 선택 |
| source_channel | VARCHAR(20) | WEB, QR, KIOSK |
| ip_hmac | BYTEA | 필요 시 최소 보관 |
| occurred_at | TIMESTAMPTZ | 선택시각 |

CHECK num_nonnulls(user_id, guest_session_id) = 1.

현재 동의는 최신 이력 조회 또는 별도 materialized current 테이블로 계산한다. 과거 행을 update하여 철회를 덮어쓰지 않는다.

목적 예시:

- AGE_CONFIRMATION
- PERSONALIZED_RECOMMENDATION
- BEHAVIOR_PERSONALIZATION
- MARKETING_MESSAGES
- THIRD_PARTY_PROVISION

상담별 연락처 공유는 interaction.meeting_contact_share에 둔다.

### 9.3 privacy.privacy_request

| 컬럼 | 형식 | 설명 |
|---|---|---|
| privacy_request_id | UUID PK | 권리 요청 |
| tenant_id | UUID FK | 테넌트 |
| user_id | UUID FK | 요청자 |
| request_type | VARCHAR(30) | ACCESS, EXPORT, CORRECT, DELETE, WITHDRAW |
| scope_json | JSONB | 대상 목적·이벤트 |
| status | VARCHAR(30) | RECEIVED, VERIFYING, PROCESSING, COMPLETED, REJECTED |
| rejection_reason_code | VARCHAR(50) | 거절 근거 |
| requested_at, due_at, completed_at | TIMESTAMPTZ | 처리기한 |

### 9.4 privacy.retention_policy·deletion_job

retention_policy은 데이터분류, 목적, 시작점, 기간, 파기방법, 법적 보존 예외, 정책버전을 저장한다.

deletion_job은 privacy_request 또는 만료정책을 원인으로 생성하며 테이블별 처리상태, 재시도, 비식별화 결과, 완료시각을 기록한다.

## 10. 사용자 프로파일

### 10.1 profile.user_profile

| 컬럼 | 형식 | 필수 | 설명 |
|---|---|---|---|
| profile_id | UUID PK | Y | 프로파일 |
| tenant_id, event_id | UUID FK | Y | 행사 |
| user_id | UUID FK | N | 인증 소유자 |
| guest_session_id | UUID FK | N | 익명 소유자 |
| user_type | VARCHAR(30) | Y | GENERAL_VISITOR, BUYER |
| profile_status | VARCHAR(20) | Y | DRAFT, COMPLETE, INACTIVE |
| primary_goal_code | VARCHAR(50) | N | 최우선 목적 |
| completeness_percent | NUMERIC(5,2) | Y | 0~100 |
| current_version | INTEGER | Y | 시작 1 |
| created_at, updated_at | TIMESTAMPTZ | Y | 변경시각 |
| deleted_at | TIMESTAMPTZ | N | 논리삭제 |

CHECK num_nonnulls(user_id, guest_session_id) = 1.

부분 유일성:

- 인증: UNIQUE(tenant_id, event_id, user_id, user_type) WHERE deleted_at IS NULL AND user_id IS NOT NULL
- 익명: UNIQUE(tenant_id, event_id, guest_session_id, user_type) WHERE deleted_at IS NULL AND guest_session_id IS NOT NULL

### 10.2 profile.profile_goal

| 컬럼 | 형식 | 설명 |
|---|---|---|
| profile_goal_id | UUID PK | 목적 |
| profile_id | UUID FK | 프로파일 |
| goal_code | VARCHAR(50) | 목적 코드 |
| priority | SMALLINT | 1~3 |
| source | VARCHAR(30) | USER_SELECTED, AI_SUGGESTED, USER_CONFIRMED |
| confidence | NUMERIC(4,3) | 0~1 |
| ai_run_id | UUID FK | AI 제안일 때 |
| evidence_text | TEXT | 최소 원문 근거 |
| created_at | TIMESTAMPTZ | 생성 |

UNIQUE(profile_id, priority). AI_SUGGESTED는 사용자 확정 전 하드 필터로 사용하지 않는다.

### 10.3 profile.consumer_preference

| 컬럼 | 형식 | 설명 |
|---|---|---|
| profile_id | UUID PK/FK | 관람객 프로파일 |
| alcohol_percentage_min, max | NUMERIC(5,2) | 도수 |
| price_min_amount, price_max_amount | BIGINT | 가격 |
| currency | CHAR(3) | KRW |
| purchase_intent | VARCHAR(20) | NONE, POSSIBLE, LIKELY |
| preference_certainty | VARCHAR(20) | KNOWN, UNKNOWN |
| preferred_distance_meters | INTEGER | 거리 |
| avoid_congestion | BOOLEAN | 혼잡 회피 |
| updated_at | TIMESTAMPTZ | 수정 |

### 10.4 profile.preference_item

| 컬럼 | 형식 | 설명 |
|---|---|---|
| preference_item_id | UUID PK | 선호항목 |
| profile_id | UUID FK | 프로파일 |
| taxonomy_version_id, concept_id | UUID 복합 FK | `ontology.concept_revision`의 버전형 개념 |
| preference_level | SMALLINT | 1~5 |
| requirement_level | VARCHAR(20) | REQUIRED, PREFERRED, ACCEPTABLE, EXCLUDED |
| source | VARCHAR(30) | USER, BEHAVIOR, AI |
| confidence | NUMERIC(4,3) | 0~1 |
| valid_from, valid_until | TIMESTAMPTZ | 적용기간 |
| created_at | TIMESTAMPTZ | 생성 |

핵심 주종·맛·활동을 자유 문자열로 저장하지 않고 `ontology.concept_revision`을 참조한다. `UNKNOWN`은 요구수준이 아니라 별도 지식상태이므로 `requirement_level`에 넣지 않는다.

### 10.5 profile.buyer_need

| 컬럼 | 형식 | 설명 |
|---|---|---|
| profile_id | UUID PK/FK | 바이어 프로파일 |
| organization_type | VARCHAR(50) | 조직유형 |
| target_price_min_amount, max_amount | BIGINT | 목표가격 |
| currency | CHAR(3) | 통화 |
| price_basis | VARCHAR(30) | RETAIL_PRICE, WHOLESALE_PRICE |
| monthly_units_min, max | INTEGER | 월 수량 |
| decision_timeline | VARCHAR(30) | 의사결정 |
| business_email_verified | BOOLEAN | 이메일 검증 |
| company_verified | BOOLEAN | 소속 검증 |
| updated_at | TIMESTAMPTZ | 수정 |

### 10.6 profile.buyer_need_item

`taxonomy_version_id`, `concept_id`, `requirement_level`, `priority`, `source`, `confidence`를 저장한다. 필수 지역·채널·제품군과 단순 선호를 구분하고, `(taxonomy_version_id, concept_id)`는 `ontology.concept_revision`을 복합 FK로 참조한다.

### 10.7 profile.profile_version

| 컬럼 | 형식 | 설명 |
|---|---|---|
| profile_version_id | UUID PK | 스냅샷 |
| profile_id | UUID FK | 프로파일 |
| version_number | INTEGER | 버전 |
| snapshot_json | JSONB | 정규화 전체 스냅샷 |
| snapshot_hash | BYTEA | 무결성·중복 |
| change_reason | VARCHAR(30) | USER_UPDATE, FEEDBACK, AI_CONFIRMATION |
| source_interaction_event_id | UUID | 원인 이벤트 |
| created_at | TIMESTAMPTZ | 생성 |

UNIQUE(profile_id, version_number). snapshot_json은 재현용이며 MVP에서 GIN 인덱스를 만들지 않는다.

## 11. 분류체계

정본 계약은 [6단계 매칭 분류체계·온톨로지](./06-matching-ontology.md)와 `db/migrations/0001_ontology.sql`이다. 안정 식별자와 버전별 표현을 분리하여 과거 추천을 재현한다.

### 11.1 ontology.taxonomy_version

`taxonomy_version_id`, `tenant_id`, `semantic_version`, `status(DRAFT, REVIEW, PUBLISHED, RETIRED)`, `default_locale`, `base_version_id`, `checksum`, 작성·발행·폐기 이력을 저장한다. `UNIQUE NULLS NOT DISTINCT(tenant_id, semantic_version)`를 적용한다.

### 11.2 ontology.concept·concept_revision

- `concept`: 불변 `concept_id`, 전역 고유 `concept_code`, `concept_type`, `data_type`, 단위, 폐기·대체 개념을 저장한다.
- `concept_revision`: `(taxonomy_version_id, concept_id)` PK, 동일 버전의 부모 개념, 할당 가능 여부, 상태, 정렬순서, 값 검증 JSON을 저장한다.
- PUBLISHED 또는 RETIRED 버전의 하위 행은 트리거로 변경·삭제를 거부한다. 수정은 새 버전 발행으로 처리한다.

### 11.3 ontology.concept_label·concept_synonym

- `concept_label`: `(taxonomy_version_id, concept_id, locale)`별 표시명·설명·검색어를 관리한다.
- `concept_synonym`: 정규화 문자열, 문맥, 매칭방식, 우선순위, 승인상태와 출처를 관리한다.
- 같은 표현이 복수 개념에 연결될 수 있으므로 해석 결과가 0개 또는 2개 이상이면 자동 확정하지 않고 검수·확인 대상으로 반환한다.

### 11.4 ontology.concept_relation

동일 버전 내 `IS_A`, `RELATED_TO`, `MATCHES_GOAL`, `SIMILAR_TO`, `COMPLEMENTS`, `CONFLICTS_WITH` 관계와 0~1 의미 가중치를 저장한다.

### 11.5 ontology.external_mapping·unknown_term_queue

- `external_mapping`: 원천 시스템의 네임스페이스·코드를 버전형 개념에 연결하고 매핑유형·신뢰도·승인상태·유효기간을 보존한다.
- `unknown_term_queue`: 미분류 표현의 정규화 값과 표본 해시, 발생횟수, 추천 개념, 검수상태를 집계한다. 제한 없는 상담 원문은 저장하지 않는다.

모든 업무 테이블은 개념을 참조할 때 `concept_id`만 저장하지 않고 `(taxonomy_version_id, concept_id)`를 함께 FK로 둔다. API의 `attribute_code`는 표시·교환용이며 DB 정본 식별자는 이 복합키다.

## 12. 행사·업체·제품

### 12.1 exhibition.event

| 컬럼 | 형식 | 설명 |
|---|---|---|
| event_id | UUID PK | 행사 |
| tenant_id | UUID FK | 주최사 |
| event_code | VARCHAR(50) | 코드 |
| event_name | VARCHAR(200) | 행사명 |
| venue_name | VARCHAR(200) | 장소 |
| timezone | VARCHAR(50) | Asia/Seoul |
| start_date, end_date | DATE | 기간 |
| event_status | VARCHAR(20) | PREPARING, OPEN, CLOSED |
| current_taxonomy_version_id | UUID FK | 활성 분류 |
| created_at, updated_at | TIMESTAMPTZ | 변경 |

UNIQUE(tenant_id, event_code), UNIQUE(tenant_id, event_id), CHECK start_date <= end_date.

event_day는 event_date, open_at, close_at, status를 저장하고 UNIQUE(event_id, event_date)를 가진다.

event_zone은 event_id, zone_code, 이름, 층, 좌표, 상위 zone, 유형을 저장한다.

### 12.2 exhibition.exhibitor

업체 마스터다. 승인상태는 행사 참여가 아니라 업체 기본정보 검수 상태를 뜻한다.

| 컬럼 | 형식 | 설명 |
|---|---|---|
| exhibitor_id | UUID PK | 업체 |
| tenant_id | UUID FK | 관리 테넌트 |
| company_name | VARCHAR(200) | 업체명 |
| business_registration_hmac | BYTEA | 중복검사 |
| company_summary | TEXT | 소개 |
| business_type_term_id | UUID FK | 업종 |
| region_term_id | UUID FK | 지역 |
| website_url | TEXT | 홈페이지 |
| master_approval_status | VARCHAR(20) | DRAFT, APPROVED, REJECTED |
| data_completeness_percent | NUMERIC(5,2) | 0~100 |
| current_profile_version | INTEGER | 업체 버전 |
| created_at, updated_at, deleted_at | TIMESTAMPTZ | 변경 |

### 12.3 exhibition.exhibitor_participation

| 컬럼 | 형식 | 설명 |
|---|---|---|
| participation_id | UUID PK | 행사 참가 |
| tenant_id, event_id | UUID FK | 행사 |
| exhibitor_id | UUID FK | 업체 |
| participation_status | VARCHAR(20) | APPLIED, APPROVED, CANCELLED |
| promotion_summary | TEXT | 현장 프로모션 |
| consultation_enabled | BOOLEAN | 상담 |
| approved_at | TIMESTAMPTZ | 승인 |
| created_at, updated_at | TIMESTAMPTZ | 변경 |

UNIQUE(event_id, exhibitor_id).

전시분야는 `participation_category(participation_id, taxonomy_version_id, concept_id)`로 정규화한다.

### 12.4 exhibition.exhibitor_staff

담당자는 참여 단위에 연결한다.

| 컬럼 | 형식 | 설명 |
|---|---|---|
| staff_id | UUID PK | 담당자 |
| participation_id | UUID FK | 행사 참가 |
| user_id | UUID FK | 파트너 계정 |
| display_name | VARCHAR(100) | 공개명 |
| position_name | VARCHAR(100) | 직책 |
| active | BOOLEAN | 활성 |

상담주제는 `staff_topic(staff_id, taxonomy_version_id, concept_id)`로 관리한다.

### 12.5 exhibition.product

| 컬럼 | 형식 | 설명 |
|---|---|---|
| product_id | UUID PK | 제품 마스터 |
| exhibitor_id | UUID FK | 업체 |
| product_name | VARCHAR(200) | 제품명 |
| category_taxonomy_version_id, category_concept_id | UUID 복합 FK | 주종 개념 |
| product_summary | TEXT | 소개 |
| alcohol_percentage | NUMERIC(5,2) | 0~100 |
| main_ingredients_json | JSONB | 초기 원료 |
| production_method | TEXT | 제조법 |
| master_approval_status | VARCHAR(20) | 검수 |
| created_at, updated_at, deleted_at | TIMESTAMPTZ | 변경 |

### 12.6 exhibition.event_product

| 컬럼 | 형식 | 설명 |
|---|---|---|
| event_product_id | UUID PK | 행사 제품 |
| tenant_id, event_id | UUID FK | 행사 |
| participation_id | UUID FK | 참가 |
| product_id | UUID FK | 제품 |
| retail_price_amount | BIGINT | 공개 소비자가 |
| event_price_amount | BIGINT | 현장가 |
| currency | CHAR(3) | KRW |
| tasting_status | VARCHAR(20) | AVAILABLE, PAUSED, ENDED |
| purchase_status | VARCHAR(20) | AVAILABLE, LIMITED, ENDED |
| inventory_status | VARCHAR(20) | AVAILABLE, LOW, SOLD_OUT, UNKNOWN |
| status_observed_at | TIMESTAMPTZ | 최신성 |
| approval_status | VARCHAR(20) | DRAFT, APPROVED, REJECTED |
| created_at, updated_at | TIMESTAMPTZ | 변경 |

UNIQUE(event_id, product_id). 가격·재고·시음 상태는 제품 마스터에 두지 않는다.

### 12.7 product_attribute·product_image

product_attribute:

- product_id
- taxonomy_version_id, concept_id (`ontology.concept_revision` 복합 FK)
- numeric_value 또는 text_value
- source: EXHIBITOR, AI, OPERATOR
- confidence
- review_status: PENDING, APPROVED, REJECTED
- ai_run_id와 evidence reference

product_image:

- product_id
- storage_key
- image_type
- display_order
- alt_text
- approval_status

### 12.8 trade_condition

| 컬럼 | 형식 | 설명 |
|---|---|---|
| trade_condition_id | UUID PK | 거래조건 |
| participation_id | UUID FK | 행사 참가 |
| event_product_id | UUID FK | 제품별, 업체 공통이면 NULL |
| min_order_quantity, max_order_quantity | INTEGER | 수량 |
| monthly_capacity | INTEGER | 생산량 |
| wholesale_price_min_amount, max_amount | BIGINT | 비공개 가격 |
| currency | CHAR(3) | 통화 |
| oem_available, private_label_available | BOOLEAN | 협력 |
| exclusive_distribution_considered | BOOLEAN | 검토 여부 |
| export_available | BOOLEAN | 수출 가능 |
| lead_time_days | INTEGER | 납기 |
| valid_from, valid_until | DATE | 유효기간 |
| approval_status | VARCHAR(20) | 승인 |

지역·채널·국가는 trade_condition_term으로 정규화한다. B2B 민감 컬럼은 공개 제품 API 역할에서 SELECT 권한을 제거한다.

## 13. 부스·프로그램·추천 대상

### 13.1 exhibition.booth

| 컬럼 | 형식 | 설명 |
|---|---|---|
| booth_id | UUID PK | 부스 |
| tenant_id, event_id | UUID FK | 행사 |
| participation_id | UUID FK | 참가 |
| zone_id | UUID FK | 구역 |
| booth_number | VARCHAR(30) | 번호 |
| map_x, map_y | NUMERIC | 좌표 |
| operating_status | VARCHAR(20) | OPEN, PAUSED, CLOSED |
| congestion_level | VARCHAR(20) | LOW, MEDIUM, HIGH, UNKNOWN |
| estimated_wait_minutes | INTEGER | 대기 |
| status_observed_at | TIMESTAMPTZ | 상태 시각 |
| row_version | BIGINT | 동시 수정 |
| created_at, updated_at | TIMESTAMPTZ | 변경 |

UNIQUE(event_id, booth_number).

booth_status_history는 변경 전후 상태, 행위자, 사유, request_id, created_at을 append-only로 저장한다.

booth_qr는 토큰 원문 대신 HMAC, valid_from/until, status, key_version을 저장한다.

### 13.2 exhibition.program

행사·구역, 프로그램명·유형, 시작·종료, 정원, 예약필요, 상태를 저장한다.

### 13.3 exhibition.recommendable

다형 FK를 제거하는 추천대상 레지스트리다.

| 컬럼 | 형식 | 설명 |
|---|---|---|
| recommendable_id | UUID PK | 추천 대상 |
| tenant_id, event_id | UUID FK | 행사 |
| object_type | VARCHAR(20) | BOOTH, EVENT_PRODUCT, EXHIBITOR, PROGRAM |
| booth_id | UUID FK | 선택 |
| event_product_id | UUID FK | 선택 |
| participation_id | UUID FK | 업체 추천 시 |
| program_id | UUID FK | 선택 |
| active | BOOLEAN | 활성 |
| created_at | TIMESTAMPTZ | 생성 |

CHECK num_nonnulls(booth_id, event_product_id, participation_id, program_id) = 1.

각 FK에 부분 UNIQUE를 적용한다. matching, favorite, feedback, route, embedding은 recommendable_id를 참조한다.

## 14. 상담 가능시간과 상담

### 14.1 interaction.availability_slot

| 컬럼 | 형식 | 설명 |
|---|---|---|
| availability_slot_id | UUID PK | 슬롯 |
| tenant_id, event_id | UUID FK | 행사 |
| participation_id | UUID FK | 업체 |
| staff_id | UUID FK | 담당자 |
| booth_id | UUID FK | 장소 |
| topic_term_id | UUID FK | 주제 |
| start_at, end_at | TIMESTAMPTZ | 시간 |
| capacity | SMALLINT | 동시 상담 |
| reserved_count | SMALLINT | 캐시 카운터 |
| status | VARCHAR(20) | OPEN, FULL, BLOCKED |
| row_version | BIGINT | 동시성 |

CHECK start_at < end_at, capacity > 0, 0 <= reserved_count <= capacity.

reserved_count는 meeting reservation 행과 정합성을 정기 검증한다.

### 14.2 interaction.meeting

| 컬럼 | 형식 | 설명 |
|---|---|---|
| meeting_id | UUID PK | 상담 |
| tenant_id, event_id | UUID FK | 행사 |
| buyer_profile_id | UUID FK | 바이어 |
| participation_id | UUID FK | 업체 |
| staff_id, booth_id | UUID FK | 확정 담당·장소 |
| topic_term_id | UUID FK | 주제 |
| message_enc | BYTEA | 민감 자유메모 암호화 |
| status | VARCHAR(30) | REQUESTED, COUNTER_PROPOSED, CONFIRMED 등 |
| confirmed_slot_id | UUID FK | 확정 슬롯 |
| confirmed_start, confirmed_end | TIMESTAMPTZ | 확정 범위 |
| match_result_id | UUID FK | 추천 기원 |
| viewed_at | TIMESTAMPTZ | 업체 확인 |
| row_version | BIGINT | 상태 충돌 |
| created_at, updated_at | TIMESTAMPTZ | 변경 |

### 14.3 meeting_slot_request

meeting_id, availability_slot_id, preference_order, status를 저장한다. 임의 start/end를 중복 저장하지 않는다. 요청 당시 슬롯 스냅샷이 필요하면 snapshot_json을 둔다.

### 14.4 meeting_contact_share

| 컬럼 | 형식 | 설명 |
|---|---|---|
| meeting_contact_share_id | UUID PK | 공유 선택 |
| meeting_id | UUID FK UQ | 상담 |
| consent_policy_id | UUID FK | 문서 |
| shared_fields | JSONB | NAME, PHONE, BUSINESS_EMAIL |
| accepted_at | TIMESTAMPTZ | 선택 |
| disclosed_at | TIMESTAMPTZ | 실제 공개 |
| disclosed_to_user_id | UUID FK | 열람자 |

accepted_at만으로 연락처를 공개하지 않는다. meeting.status = CONFIRMED와 disclosed 권한 검사를 함께 적용한다.

### 14.5 상태·결과

meeting_status_history는 이전·신규 상태, 변경자, 사유코드, request_id를 append-only 저장한다.

meeting_outcome은 QUALIFIED 여부, 결과코드, 예상금액·확률, 암호화 메모, completed_at을 저장한다.

follow_up_action은 action code, 담당자, 예정일, 상태, 완료일을 저장한다.

확정 상담 겹침 방지:

~~~sql
-- btree_gist 사용 시 예시. 실제 상태 enum과 NULL 정책 확정 후 적용.
EXCLUDE USING gist (
  staff_id WITH =,
  tstzrange(confirmed_start, confirmed_end, '[)') WITH &&
)
WHERE (status = 'CONFIRMED' AND staff_id IS NOT NULL);
~~~

바이어 profile에도 같은 시간범위 exclusion을 적용한다. capacity가 2 이상인 슬롯은 슬롯 행 잠금과 reservation count를 함께 사용한다.

## 15. 추천 정책·결과

### 15.1 matching.match_policy_version

tenant_id, event_id, user_type, version, status, effective period를 저장한다. 한 행사·사용자유형에 ACTIVE 정책은 하나만 허용한다.

match_weight는 component, weight, min/max, config를 저장한다.

filter_rule은 code, order, HARD/SOFT, config, active를 저장한다.

정책 활성화는 트랜잭션으로 기존 ACTIVE를 RETIRED 처리한 뒤 수행하고 감사로그를 남긴다.

### 15.2 matching.recommendation_session

| 컬럼 | 형식 | 설명 |
|---|---|---|
| recommendation_session_id | UUID PK | 추천 실행 |
| tenant_id, event_id | UUID FK | 행사 |
| profile_id | UUID FK | 프로파일 |
| profile_version_id | UUID FK | 고정 스냅샷 |
| visit_session_id | UUID FK | 방문 |
| recommendation_type | VARCHAR(20) | BOOTH, PRODUCT, EXHIBITOR, PROGRAM, MIXED |
| policy_version_id | UUID FK | 정책 |
| ranking_model_version_id | UUID FK | 랭킹 |
| explanation_model_version_id | UUID FK | 설명, 템플릿이면 NULL |
| taxonomy_version_id | UUID FK | 분류 |
| context_snapshot | JSONB | 위치·시간·운영상태 버전 |
| consent_snapshot_id | UUID | 당시 동의 |
| candidate_count, filtered_count, result_count | INTEGER | 수량 |
| fallback_strategy | VARCHAR(30) | TEMPLATE, CATEGORY_BROWSE 등 |
| status | VARCHAR(20) | ACTIVE, EXPIRED, INVALIDATED |
| generated_at, expires_at | TIMESTAMPTZ | 유효기간 |
| latency_ms | INTEGER | 지연 |

### 15.3 matching.match_result

| 컬럼 | 형식 | 설명 |
|---|---|---|
| match_result_id | UUID PK | 결과 |
| recommendation_session_id | UUID FK | 세션 |
| recommendable_id | UUID FK | 대상 |
| raw_score, normalized_score | NUMERIC | 내부 점수 |
| rank | INTEGER | 순위 |
| preference_score | NUMERIC | 취향 |
| goal_score | NUMERIC | 목적 |
| trade_score | NUMERIC | 거래 |
| context_score | NUMERIC | 상황 |
| context_policy_version_id | UUID FK | 게시된 상황 재정렬 정책 |
| context_components | JSONB | 관측 구성요소와 명시적 NULL |
| context_effective_weights | JSONB | 누락 제거 후 유효 가중치 |
| context_contributions | JSONB | 구성요소별 가중 기여도 |
| context_input_fingerprint | CHAR(64) | 입력 스냅샷 SHA-256 |
| context_score_fingerprint | CHAR(64) | 계산 결과 SHA-256 |
| context_details | JSONB | 거리·시간·가용성·관측시각 상세 |
| behavior_score | NUMERIC | 행동 |
| diversity_adjustment | NUMERIC | 다양성 |
| trust_score | NUMERIC | 신뢰 |
| recommended_action | VARCHAR(30) | VISIT_NOW 등 |
| created_at | TIMESTAMPTZ | 생성 |

UNIQUE(recommendation_session_id, rank), UNIQUE(recommendation_session_id, recommendable_id).

hard_filter를 통과하지 못한 후보는 match_result에 넣지 않는다. 제외 근거는 filter_result에 저장한다.

상황 재정렬 계보 컬럼은 모두 NULL인 과거 결과 또는 모두 채워진 신규 결과만 허용한다. 신규 추천은 게시된 `CONTEXT_RERANK` 정책과 구성요소·유효 가중치·두 계산 지문을 함께 저장한다.

상담과 경로는 직접 추천 대상이 아니다. `recommended_action`이 REQUEST_MEETING 또는 ADD_TO_ROUTE일 때 후속 요청으로 생성하며 각각 interaction.meeting, interaction.route에 저장한다.

### 15.4 matching.match_reason

| 컬럼 | 형식 | 설명 |
|---|---|---|
| match_reason_id | UUID PK | 이유 |
| match_result_id | UUID FK | 결과 |
| reason_code | VARCHAR(50) | TASTE_MATCH 등 |
| reason_text | VARCHAR(500) | 사용자 문장 |
| evidence_refs | JSONB | 승인 데이터 참조 |
| contribution_score | NUMERIC | 내부 기여 |
| display_order | SMALLINT | 순서 |
| generated_by | VARCHAR(20) | TEMPLATE, LLM |
| ai_run_id | UUID FK | AI 실행 |
| validation_status | VARCHAR(20) | VALID, REJECTED |
| created_at | TIMESTAMPTZ | 생성 |

### 15.5 matching.filter_result

실패한 후보의 rule code, recommendable_id, 정책버전, 최소 details_json을 저장한다. 통과한 모든 규칙을 모든 후보에 기록하면 폭증하므로 최종 후보의 trace 또는 표본만 저장한다.

## 16. 저장·경로·방문·피드백

### 16.1 interaction.favorite

| 컬럼 | 형식 | 설명 |
|---|---|---|
| favorite_id | UUID PK | 저장 |
| tenant_id, event_id | UUID FK | 행사 |
| user_id | UUID FK | 인증 |
| guest_session_id | UUID FK | 익명 |
| recommendable_id | UUID FK | 대상 |
| source | VARCHAR(20) | SEARCH, RECOMMENDATION |
| match_result_id | UUID FK | 기원 |
| created_at | TIMESTAMPTZ | 생성 |
| deleted_at | TIMESTAMPTZ | 해제 |

CHECK num_nonnulls(user_id, guest_session_id) = 1. 인증·익명 각각 활성 partial unique를 적용한다.

### 16.2 interaction.check_in

| 컬럼 | 형식 | 설명 |
|---|---|---|
| check_in_id | UUID PK | 방문 |
| tenant_id, event_id | UUID FK | 행사 |
| visit_session_id | UUID FK | 방문 세션 |
| booth_id | UUID FK | 부스 |
| match_result_id | UUID FK | 추천 기원 |
| check_in_method | VARCHAR(20) | QR, MANUAL, STAFF |
| activities | JSONB | TASTING, PURCHASE 등 |
| qr_id | UUID FK | 검증 QR |
| qr_key_version | INTEGER | 검증 키 |
| client_event_id | UUID | 오프라인 중복 |
| checked_in_at, received_at | TIMESTAMPTZ | 발생·수신 |
| created_at | TIMESTAMPTZ | 생성 |

주체는 visit_session에서 파생하므로 user_id와 guest_session_id를 중복 저장하지 않는다.

5분 중복방지는 트랜잭션 내 visit_session_id + booth_id advisory lock 후 최근 체크인을 조회한다. Idempotency-Key는 integration.idempotency_record에 별도 저장한다.

### 16.3 interaction.feedback

visit_session_id, recommendable_id, match_result_id, rating, positive/negative reason code, 암호화 또는 민감도 검토된 comment, created_at을 저장한다.

원본 피드백은 수정하지 않는다. 프로파일 보정은 preference_adjustment에 별도로 저장하고 상황 원인은 취향 가중치에 적용하지 않는다.

### 16.4 interaction.route·route_item

route는 visit_session, 최적화 유형, 총·이동 시간, 상태, context snapshot을 가진다.

route_item은 route, sequence, recommendable_id 또는 meeting_id, 예정 도착·체류, 실제 도착, 상태를 가진다. CHECK num_nonnulls(recommendable_id, meeting_id) = 1.

## 17. 행동 이벤트

### 17.1 interaction.interaction_event

대량 append-only 테이블이다.

| 컬럼 | 형식 | 설명 |
|---|---|---|
| event_date | DATE | 파티션 키 |
| interaction_event_id | UUID | 이벤트 ID |
| tenant_id, event_id | UUID | 행사 |
| user_id | UUID | 인증 주체 |
| guest_session_id | UUID | 익명 주체 |
| visit_session_id | UUID | 방문 |
| event_type | VARCHAR(60) | 표준 이벤트 |
| recommendable_id | UUID | 대상 |
| recommendation_session_id | UUID | 추천 |
| match_result_id | UUID | 결과 |
| rank_at_event | INTEGER | 당시 순위 |
| screen_code | VARCHAR(30) | 화면 |
| context_json | JSONB | 허용 목록 속성 |
| client_event_id | UUID | 클라이언트 중복 |
| consent_snapshot_id | UUID | 당시 동의 |
| occurred_at, received_at | TIMESTAMPTZ | 시각 |

PRIMARY KEY(event_date, interaction_event_id).

CHECK num_nonnulls(user_id, guest_session_id) <= 1. 서버가 세션에서 주체를 채운다.

파티셔닝:

- MVP·행사 기간: 일 또는 월 RANGE(event_date)
- 기본 파티션으로 잘못된 날짜 격리
- BRIN(received_at)
- (event_date, event_type), (recommendation_session_id), (recommendable_id, occurred_at)

클라이언트 event dedupe는 integration.idempotency_record 또는 비파티션 dedupe 테이블로 처리한다. 파티션 전체의 전역 unique를 가정하지 않는다.

## 18. AI·임베딩

### 18.1 ai.model_version

model_type, provider, model_name, provider_version, 내부 version, config, status, deployed/retired at을 저장한다.

민감한 API 키와 전체 시스템 프롬프트는 config_json에 저장하지 않는다.

### 18.2 ai.ai_run

| 컬럼 | 형식 | 설명 |
|---|---|---|
| ai_run_id | UUID PK | 실행 |
| tenant_id, event_id | UUID | 범위 |
| model_version_id | UUID FK | 모델 |
| task_type | VARCHAR(30) | ATTRIBUTE_EXTRACTION, EXPLANATION |
| input_reference_type, id | 값 | 입력 대상 |
| input_hash | BYTEA | 비식별 입력 해시 |
| schema_version | VARCHAR(30) | JSON 계약 |
| prompt_version | VARCHAR(30) | 템플릿 |
| validated_output_json | JSONB | 검증 결과만 |
| validation_status | VARCHAR(20) | VALID, INVALID, REVIEW |
| latency_ms, token_input, token_output | INTEGER | 사용량 |
| estimated_cost | NUMERIC | 비용 |
| error_code | VARCHAR(50) | 실패 |
| created_at | TIMESTAMPTZ | 실행 |

전체 프롬프트·원문 응답은 기본 보관하지 않는다. 품질검증에 필요하면 별도 암호화 저장소와 짧은 보유정책을 적용한다.

### 18.3 ai.extracted_attribute

recommendable_id 또는 원천 객체, taxonomy_version_id, concept_id, attribute_value, confidence, evidence reference, ai_run_id, review status, reviewer를 저장한다. AI가 제안한 REQUIRED 속성 또는 confidence 0.7 미만 결과는 사용자·운영자 확인 전 확정하지 않는다.

APPROVED만 추천 필터·근거로 사용한다.

### 18.4 ai.object_embedding

| 컬럼 | 형식 | 설명 |
|---|---|---|
| embedding_id | UUID PK | 벡터 |
| tenant_id | UUID FK | 테넌트 경계 |
| event_id | UUID FK | 행사 경계 |
| recommendable_id | UUID FK | 대상 |
| content_type | VARCHAR(30) | SUMMARY, TRADE, PRODUCT |
| content_hash | BYTEA | 변경검사 |
| embedding | VECTOR(512) | 검색 임베딩 v1 고정 차원 |
| model_version_id | UUID FK | 임베딩 모델 |
| language | VARCHAR(10) | 언어 |
| active | BOOLEAN | 활성 |
| created_at | TIMESTAMPTZ | 생성 |

검색 임베딩 v1의 차원은 CR-004에서 512로 확정했다. 차원이 다른 모델은 새 계약과 마이그레이션으로
별도 테이블·컬럼 또는 인덱스 집합을 게시한다.

활성 모델이 하나일 때 HNSW cosine 인덱스를 사용한다. 모델 전환은 새 벡터 백필, 품질검증, 활성 포인터 교체, 구버전 지연삭제 순서로 진행한다.

#### 검색 임베딩 v1 게시 계약 (CR-004)

- 모델 버전: `openai-text-embedding-3-small-512-v1`
- 모델: `text-embedding-3-small`, 공급자 어댑터: `OPENAI_DIRECT`
- 차원: `VECTOR(512)` — 공급자의 `dimensions=512` 출력만 저장하며 애플리케이션에서 임의 절단하지 않는다.
- 거리/점수: cosine distance, `Semantic Relevance = clamp(1 - distance, 0, 1)`
- 인덱스: 활성 `SUMMARY` 행에 한정한 HNSW `vector_cosine_ops`. 검색 SQL은 partial-index
  predicate와 일치하도록 `SUMMARY` 판별자를 SQL literal로 고정한다.
- 실행 요구사항: 데이터베이스 pgvector 0.8.0 이상과 filtered HNSW iterative scan 사용
- 격리: 표의 기본 컬럼에 `tenant_id`, `event_id`를 추가하고
  `(tenant_id, event_id, recommendable_id)` 복합 FK로 공개 추천대상 경계를 강제한다.
- 활성 포인터: `(tenant_id, event_id, recommendable_id, content_type, language)`마다 활성 행 하나
- 언어: 현재 비지역화 카탈로그 스냅샷은 `und`로 백필하고, 검색 시 세션 언어와 `und`를 함께
  조회한다. 언어별 승인 원문이 생긴 경우에만 해당 언어 코드를 별도 활성화한다.
- 입력 범위: 승인된 공개 업체·참가·제품의 공개 설명만 허용하며 사용자 프로파일·연락처·키오스크
  질의 원문은 객체 임베딩 테이블에 저장하지 않는다. 참가 SUMMARY에는 해당 참가사의 승인 제품
  공개 텍스트를 함께 넣어 업체당 언어별 한 행으로 후보 다양성을 보장한다. 업체명·제품명 식별자는
  설명보다 먼저 배치하고, 남은 8,000-byte 예산은 설명 소스별로 공정 배분한다.
- 원본 변경 격리: 업체·참가·제품·행사제품의 임베딩 입력·승인 경계 또는 recommendable membership이
  INSERT/UPDATE/DELETE로 바뀌면 0017의 DB trigger가 같은 참가사의 활성 catalog vector를 즉시
  비활성화한다. 원본 테이블의 `BEFORE STATEMENT` trigger가 행 변경·FK cascade보다 먼저 짧은 전역
  catalog advisory lock을 획득하고, 백필도 같은 lock 안에서 최신 snapshot을 재검증한 뒤 활성화한다.
  승인 전환 phantom이 검증 뒤 발생해도 trigger가 포인터 교체 뒤에 직렬화되어 변경된 원문을 다음
  백필 전까지 fail-closed로 제외한다.
- 장애 정책: 공급자, pgvector 또는 활성 모델이 없으면 semantic만 0으로 두고 FTS·keyword·category
  검색을 계속한다. 벡터 점수는 승인/운영 필터나 최종 결정적 가중식을 우회하지 않는다.

다른 모델 또는 차원으로 전환할 때 기존 벡터를 덮어쓰지 않는다. 새 `model_version`과 저장 계약을
게시하고 비활성 상태로 백필·검증한 뒤 활성 포인터를 원자적으로 교체한다.

## 19. 연계·멱등성·Outbox

### 19.1 integration.source_system

tenant, system_code, 이름, sync_type, active를 저장한다.

### 19.2 integration.external_reference

| 컬럼 | 형식 | 설명 |
|---|---|---|
| external_reference_id | UUID PK | 매핑 |
| source_system_id | UUID FK | 원천 |
| object_type | VARCHAR(30) | USER, EXHIBITOR 등 |
| external_id | VARCHAR(255) | 원천 ID |
| internal_id | UUID | 내부 ID |
| source_updated_at, last_synced_at | TIMESTAMPTZ | 버전 |
| source_payload_hash | BYTEA | 변경검사 |
| sync_status | VARCHAR(20) | SYNCED, FAILED, CONFLICT |

UNIQUE(source_system_id, object_type, external_id).

### 19.3 integration.sync_job·sync_row_error

sync_job은 작업 유형, 대상, checksum, 시작·종료, 전체·성공·실패 수, 상태를 저장한다.

sync_row_error는 행 번호, 외부 ID, 오류코드, 안전하게 마스킹된 메시지, 재처리 상태를 저장한다.

### 19.4 integration.idempotency_record

| 컬럼 | 형식 | 설명 |
|---|---|---|
| idempotency_record_id | UUID PK | 레코드 |
| tenant_id | UUID | 테넌트 |
| principal_fingerprint | BYTEA | 인증 주체 HMAC |
| method, route | VARCHAR | 요청 |
| idempotency_key | UUID | 키 |
| request_hash | BYTEA | 본문 |
| response_status | INTEGER | 응답 |
| response_reference | UUID | 생성 리소스 |
| locked_until, expires_at | TIMESTAMPTZ | 동시성·만료 |
| created_at | TIMESTAMPTZ | 생성 |

UNIQUE(tenant_id, principal_fingerprint, method, route, idempotency_key).

### 19.5 integration.outbox_event

aggregate type/id, tenant/event, event type, schema version, payload, dedupe key, status, attempt count, next_attempt_at, created/published at을 저장한다.

업무 트랜잭션과 같은 DB 트랜잭션에서 insert한다. 발행 worker는 SKIP LOCKED로 가져간다.

## 20. 감사·품질·분석

### 20.1 audit.audit_log

append-only:

- tenant_id, event_id
- actor_user_id, actor_role
- action_type: VIEW, CREATE, UPDATE, DELETE, EXPORT, APPROVE
- resource_type/id
- before_hash, after_hash
- reason_code, request_id, ip_hmac
- occurred_at

필수 감사:

- 식별정보·바이어 연락처 조회
- export
- 업체·제품 승인
- 정책·가중치 변경
- 추천 수동 개입
- 부스 운영상태 변경
- 개인정보 삭제

DB 역할은 UPDATE·DELETE를 금지하고 외부 WORM 또는 주기적 hash chain으로 변조 탐지를 강화한다.

### 20.2 quality.data_quality_issue

tenant/event, recommendable 또는 원천 객체, issue code, severity, detected_by, status, resolution note, 생성·해결시각을 저장한다.

업체 완성도는 계산 근거 버전과 함께 저장한다. 낮은 완성도는 신뢰도 점수에 반영하되 임의 차별이 되지 않도록 구성요소를 운영자에게 제공한다.

### 20.3 analytics

analytics는 운영 테이블의 소스 오브 트루스가 아니다.

- fact_recommendation: 노출·열기·저장·체크인·상담 전환
- fact_meeting: 요청·확정·완료·유효리드
- dim_exhibitor: 업체·지역·제품군·구역·완성도

지표 분모와 중복정의:

- 추천 열기율 = 추천 열기 / 실제 뷰포트 노출
- 방문전환율 = 추천 기원 체크인 / 추천 열기
- 상담요청률 = 상담요청 / 바이어 업체상세 조회
- 상담완료율 = 완료 / 확정
- 유효리드율 = 유효리드 / 완료

## 21. 핵심 인덱스

~~~sql
CREATE INDEX idx_profile_user_event
ON profile.user_profile (tenant_id, event_id, user_id)
WHERE deleted_at IS NULL;

CREATE INDEX idx_profile_guest_event
ON profile.user_profile (tenant_id, event_id, guest_session_id)
WHERE deleted_at IS NULL;

CREATE INDEX idx_event_product_filter
ON exhibition.event_product
  (event_id, approval_status, inventory_status, tasting_status, purchase_status);

CREATE INDEX idx_product_category
ON exhibition.product (category_taxonomy_version_id, category_concept_id)
WHERE deleted_at IS NULL AND master_approval_status = 'APPROVED';

CREATE INDEX idx_booth_live
ON exhibition.booth (event_id, operating_status, congestion_level);

CREATE INDEX idx_match_session_rank
ON matching.match_result (recommendation_session_id, rank);

CREATE INDEX idx_match_target
ON matching.match_result (recommendable_id, created_at DESC);

CREATE INDEX idx_meeting_buyer_time
ON interaction.meeting (buyer_profile_id, confirmed_start)
WHERE status = 'CONFIRMED';

CREATE INDEX idx_meeting_staff_time
ON interaction.meeting (staff_id, confirmed_start)
WHERE status = 'CONFIRMED';
~~~

JSONB GIN은 실제 쿼리가 확인된 snapshot·context 컬럼에만 추가한다. 쓰기비용 때문에 일괄 적용하지 않는다.

## 22. 트랜잭션 경계

### 22.1 상담 확정

한 트랜잭션:

1. meeting row version 검사
2. availability_slot 잠금
3. capacity 검사
4. 바이어·담당자·이동시간 충돌 검사
5. meeting CONFIRMED
6. slot reserved_count 증가
7. 상태이력과 contact disclosure 조건 생성
8. outbox insert

### 22.2 QR 체크인

한 트랜잭션:

1. idempotency record 선점
2. QR HMAC·행사·기간·상태 검사
3. visit_session·booth 잠금 키 획득
4. 5분 중복 검사
5. check_in insert
6. 추천 전환 연결
7. outbox insert
8. idempotency 결과 확정

### 22.3 프로파일 수정

한 트랜잭션:

1. If-Match row_version 검사
2. 프로파일·세부속성 수정
3. version_number 증가
4. profile_version snapshot 생성
5. 기존 recommendation_session INVALIDATED
6. outbox insert

## 23. 캐시

예시 키:

~~~text
session:guest:{guest_session_id}
session:user:{user_id}
profile:{profile_id}:v{version}
recommendation:{recommendation_session_id}
home:{visit_session_id}
booth:{booth_id}:status:v{row_version}
availability:{participation_id}:{date}
route:{route_id}
rate-limit:{principal}:{api}
~~~

권장 초기 TTL:

| 데이터 | TTL |
|---|---|
| 익명 세션 | 서버 만료시각 이하 |
| 인증 세션 | 30분 sliding |
| 추천 결과 | expires_at 이하 |
| 추천 홈 | 2분 |
| 부스 상태 | 30초 |
| 상담 가능시간 | 30초 |
| 업체·제품 공개정보 | 30분 |
| 지도 | 행사 지도 버전 변경까지 |

Redis는 소스 오브 트루스가 아니다. 정책·업체 승인·제품 상태·상담예약 변경 시 versioned key 또는 명시적 무효화를 적용한다.

## 24. 보유·파기

고정 예시 기간을 DB 코드에 하드코딩하지 않는다. privacy.retention_policy의 목적별 버전으로 계산한다.

| 데이터 | 파기 방식 |
|---|---|
| 익명 세션 | 만료·정책 후 물리삭제 |
| 직접 식별정보 | 키 폐기와 물리삭제 |
| 프로파일 | 소유자 연결 제거·삭제 |
| 추천 결과 | 분석 필요 시 가명·집계 |
| 행동 이벤트 | user·guest 연결키 제거 후 집계 |
| 상담 | 목적 종료 후 식별정보·메모 분리삭제 |
| AI 실행 | 비식별 검증정보만 최소 보관 |
| 감사로그 | 승인된 보안정책에 따라 변경불가 보관 |

삭제 작업은 FK 순서, 분석 집계 완료 여부, 법적 보존 예외, 재시도 결과를 deletion_job에 기록한다.

## 25. MVP 테이블

필수:

- core.tenant
- identity.user_identity, authentication_method
- profile.user_account, role, user_role
- profile.guest_session, visit_session
- profile.consent_policy, user_consent
- profile.user_profile, profile_goal, profile_version
- profile.consumer_preference, preference_item
- profile.buyer_need, buyer_need_item
- exhibition.event, event_day, event_zone
- ontology.taxonomy_version, concept, concept_revision, concept_label, concept_synonym, concept_relation
- ontology.external_mapping, unknown_term_queue
- exhibition.exhibitor, exhibitor_participation, exhibitor_staff
- exhibition.product, event_product, product_attribute, product_image
- exhibition.trade_condition, trade_condition_term
- exhibition.booth, booth_status_history, booth_qr
- exhibition.recommendable
- interaction.availability_slot, meeting, meeting_slot_request
- interaction.meeting_contact_share, meeting_status_history
- interaction.favorite, check_in, feedback, interaction_event
- matching.match_policy_version, match_weight, filter_rule
- matching.recommendation_session, match_result, match_reason, filter_result
- ai.model_version, ai.ai_run, ai.object_embedding
- integration.source_system, external_reference, sync_job
- integration.idempotency_record, outbox_event
- privacy.privacy_request, retention_policy, deletion_job
- audit.audit_log

2차:

- 프로그램 예약
- 경로 최적화 상세
- 상담 outcome·follow-up
- preference_adjustment 자동 반영
- AI 추출 검수 UI
- 데이터 품질 자동검사
- 분석 데이터마트
- 다국어 임베딩
- A/B 실험

## 26. DB 검수 체크리스트

구조:

- tenant_id·event_id 복합 FK와 RLS가 적용되는가
- guest·user 주체의 exactly-one CHECK가 있는가
- 제품 마스터와 행사별 판매상태가 분리되는가
- 다형 참조가 recommendable FK로 통제되는가
- immutable 테이블에 update·soft delete를 허용하지 않는가

추천·AI:

- profile·policy·ranking·explanation·taxonomy·context 버전이 보존되는가
- reason evidence가 승인 데이터로 연결되는가
- 승인 전 AI 속성이 하드 필터에 사용되지 않는가
- 벡터 차원과 모델 인덱스가 혼합되지 않는가

행동·상담:

- 체크인과 상담 요청이 멱등한가
- 상담 슬롯·바이어·담당자 시간 충돌이 원자적으로 차단되는가
- 연락처 공개가 확정·동의·권한을 모두 검사하는가
- 이벤트 파티션 PK와 dedupe 전략이 PostgreSQL 제약에 맞는가

개인정보:

- 암호화값과 HMAC이 분리되는가
- 일반 추천 DB 역할이 identity를 직접 읽지 못하는가
- 동의 선택이 append-only로 남는가
- 보유기간 만료와 삭제 요청이 실행 가능한 작업으로 연결되는가
- 개인정보 조회·export·정책변경이 감사되는가

성능:

- 실제 추천 필터에 맞는 복합·부분 인덱스가 있는가
- 무분별한 JSONB GIN을 피했는가
- 이벤트 파티션과 BRIN이 수집량 테스트를 통과하는가
- HNSW 인덱스의 메모리·빌드·검색 품질을 검증했는가
- Redis 장애 시 DB 기반 최소 기능이 유지되는가

## 27. 다음 산출물 연결

AI 매칭엔진 상세설계는 다음 FK와 스냅샷을 기준으로 작성한다.

- profile_version_id
- policy_version_id
- taxonomy_version_id
- ranking_model_version_id
- recommendation_session.context_snapshot
- recommendable_id
- match_result의 구성요소 점수
- match_reason.evidence_refs
- filter_result
- interaction_event와 check_in·meeting·feedback

## 28. 제15단계 슬레이트·실제 노출 확장

`matching.match_result`는 11~14단계의 관련성·상황 점수 정본을 유지한다. 제15단계의 목록 단위 결정은 별도 append-only 테이블로 저장해 점수 품질과 노출 정책을 분리한다.

### 28.1 matching.slate_result

| 컬럼 | 형식 | 설명 |
|---|---|---|
| slate_result_id | UUID PK | 목록 구성 실행 |
| tenant_id, event_id | UUID FK | 행사 경계 |
| recommendation_session_id | UUID UNIQUE FK | 추천 세션당 하나의 슬레이트 |
| slate_policy_version_id | UUID FK | 게시된 `SLATE_POLICY` |
| slate_size | INTEGER | 최종 항목 수 |
| diversity_score, coverage_score | NUMERIC | ILD와 카테고리 커버리지 |
| exposure_fairness_score | NUMERIC NULL | 노출 이력이 있을 때 조건부 기회 공정성 |
| relevance_loss | NUMERIC NULL | 상위 10개 평균 관련성 손실 |
| input_fingerprint, score_fingerprint | CHAR(64) | 입력·결과 SHA-256 |
| metrics_json | JSONB | 업체 커버리지, Gini, HHI, 탐색·반복·광고 분리 지표 |

### 28.2 matching.slate_item

`slate_result_id`, `match_result_id`, `recommendable_id`, `exhibitor_id`, 보정 전후 순위·점수, MMR 점수, 다양성·공정성·탐색 보정, 반복·집중도 감점, 슬롯 유형, 이유 코드, 관련 제품 묶음, 항목별 입력·결과 지문을 저장한다. `(slate_result_id, final_rank)`와 `match_result_id`는 각각 UNIQUE다.

### 28.3 interaction.recommendation_impression

추천 응답 수가 아니라 실제 가시 카드만 기록하는 정규화 projection이다. 원본 `interaction_event`, 슬레이트·항목, 추천 대상, 업체, 당시 순위·슬롯, 가시 시간과 사용자·게스트·방문 세션을 연결한다. 사용자·게스트·방문 세션 및 업체별 시간 인덱스로 반복 노출과 행사 전체 노출 편중을 조회하며 UPDATE·DELETE는 금지한다.
