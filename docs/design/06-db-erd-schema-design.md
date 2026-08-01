# 백주대간 초개인화 AI 매칭서비스 — DB ERD 상세설계 및 테이블 정의서

## 1. 설계 개요

### 1.1 설계 목적

- 일반 관람객·바이어·참가업체 데이터 통합 관리
- 개인정보와 추천·행동정보 분리
- 사용자 프로파일 버전 및 추천 결과 재현
- 실시간 추천·상담·부스 운영 지원
- AI 임베딩 검색 및 구조화 속성 검색 병행
- 행사 종료 후 방문·상담·유효리드 성과 분석
- 데이터 삭제·동의철회·보유기간 정책 적용
- 향후 타 전시·박람회 확장 가능한 멀티이벤트 구조 확보

### 1.2 권장 기술구성

| 영역 | 권장 기술 | 주요 용도 |
|---|---|---|
| 운영 DB | PostgreSQL | 사용자, 업체, 제품, 상담, 추천 결과 |
| 캐시 | Redis | 세션, 추천 캐시, 동시성 제어 |
| 벡터 검색 | PostgreSQL pgvector 또는 OpenSearch | 업체·제품·자유서술 의미검색 |
| 이벤트 수집 | Kafka 또는 Redis Streams | 사용자 행동 이벤트 |
| 분석 저장소 | PostgreSQL 별도 스키마 또는 BigQuery | KPI·성과 분석 |
| 파일 저장소 | S3 호환 Object Storage | 제품·업체 이미지, 첨부자료 |
| 검색엔진 | OpenSearch 선택 | 복합 필터·전문검색·통계 |
| 감사로그 | 별도 Append-only 저장소 | 관리자 접근·변경 이력 |

MVP에서는 PostgreSQL, Redis, pgvector 조합으로 시작하고, 이벤트 규모가 커질 경우 Kafka·분석 데이터웨어하우스를 추가하는 방식이 적절하다.

## 2. 데이터 영역 구분

```
┌───────────────────────────────────────────────┐
│ 1. 개인정보 영역 identity                    │
│ 이름·휴대전화·이메일·인증정보                 │
└─────────────────────┬─────────────────────────┘
                      │ user_id
┌─────────────────────▼─────────────────────────┐
│ 2. 사용자·프로파일 영역 profile              │
│ 사용자유형·방문목적·취향·바이어 요구조건       │
└─────────────────────┬─────────────────────────┘
                      │ profile_id
┌─────────────────────▼─────────────────────────┐
│ 3. 행사·전시 영역 exhibition                 │
│ 행사·업체·제품·부스·프로그램·거래조건          │
└─────────────────────┬─────────────────────────┘
                      │ object_id
┌─────────────────────▼─────────────────────────┐
│ 4. 매칭·추천 영역 matching                   │
│ 추천세션·후보점수·순위·추천근거·모델버전       │
└─────────────────────┬─────────────────────────┘
                      │ match_result_id
┌─────────────────────▼─────────────────────────┐
│ 5. 행동·상담 영역 interaction                │
│ 조회·저장·방문·QR·상담·피드백·리드            │
└─────────────────────┬─────────────────────────┘
                      │ event_id
┌─────────────────────▼─────────────────────────┐
│ 6. AI·검색 영역 ai                           │
│ 임베딩·속성추출·분류결과·프롬프트·모델실행      │
└─────────────────────┬─────────────────────────┘
                      │ batch/event
┌─────────────────────▼─────────────────────────┐
│ 7. 분석 영역 analytics                       │
│ 전환율·상담성과·업체별 리드·추천품질           │
└───────────────────────────────────────────────┘
```

## 3. 전체 논리 ERD

```
EVENT
 ├─< EVENT_DAY
 ├─< EVENT_ZONE
 ├─< BOOTH
 ├─< PROGRAM
 ├─< VISIT_SESSION
 └─< EXHIBITOR_PARTICIPATION >─ EXHIBITOR
                                  ├─< PRODUCT
                                  ├─< TRADE_CONDITION
                                  ├─< EXHIBITOR_STAFF
                                  └─< AVAILABILITY_SLOT

USER_ACCOUNT
 ├─1 USER_IDENTITY
 ├─< USER_PROFILE
 │    ├─< PROFILE_GOAL
 │    ├─1 CONSUMER_PREFERENCE
 │    ├─1 BUYER_NEED
 │    └─< PROFILE_VERSION
 ├─< VISIT_SESSION
 ├─< CONSENT
 ├─< FAVORITE
 ├─< MEETING
 └─< INTERACTION_EVENT

USER_PROFILE
 └─< RECOMMENDATION_SESSION
      └─< MATCH_RESULT
           ├─< MATCH_REASON
           ├─0..1 FAVORITE
           ├─0..1 CHECK_IN
           ├─0..1 FEEDBACK
           └─0..1 MEETING

BOOTH
 ├─< BOOTH_STATUS_HISTORY
 ├─< BOOTH_QR
 ├─< CHECK_IN
 └─< ROUTE_ITEM

PRODUCT
 ├─< PRODUCT_ATTRIBUTE
 ├─< PRODUCT_IMAGE
 ├─< PRODUCT_INVENTORY_STATUS
 └─< AI_EMBEDDING

MEETING
 ├─< MEETING_SLOT_REQUEST
 ├─< MEETING_STATUS_HISTORY
 ├─0..1 MEETING_OUTCOME
 └─< FOLLOW_UP_ACTION
```

## 4. 공통 설계 기준

### 4.1 기본 키

- 내부 기본 키는 UUID v7 사용 권장
- 외부 노출용 ID는 별도 공개 식별자 사용 가능
- 사용자·업체·제품 ID는 의미 없는 식별자로 구성
- 전화번호·사업자번호 등을 기본 키로 사용하지 않음

### 4.2 공통 컬럼

대부분의 운영 테이블에 다음 필드를 적용한다.

| 필드 | 형식 | 설명 |
|---|---|---|
| created_at | TIMESTAMPTZ | 생성일시 |
| created_by | UUID | 생성 사용자·시스템 |
| updated_at | TIMESTAMPTZ | 최종 수정일시 |
| updated_by | UUID | 수정 사용자·시스템 |
| deleted_at | TIMESTAMPTZ | 논리삭제 일시 |
| row_version | BIGINT | 낙관적 잠금 버전 |

### 4.3 삭제정책

- 일반 운영정보: 논리삭제
- 개인정보: 보유기간 종료 시 물리삭제 또는 비식별화
- 감사로그: 원본 변경 금지
- 행동로그: 개인식별자 제거 후 통계용 보존 가능
- 추천 결과: 프로파일 삭제 시 사용자 연결키 제거

### 4.4 코드 관리

상태·유형값은 문자열 Enum 또는 공통 코드 테이블로 관리한다.

MVP 권장:
- 자주 변경되지 않는 상태값: DB Enum 또는 애플리케이션 Enum
- 운영자가 추가·수정할 분류: 코드 테이블
- AI 분류 라벨: 버전형 분류체계 테이블

## 5. 개인정보 영역

### 5.1 identity.user_identity

사용자의 직접 식별정보를 저장한다.

| 필드 | 형식 | 필수 | 설명 |
|---|---|---|---|
| identity_id | UUID PK | Y | 개인정보 식별자 |
| user_id | UUID UQ | Y | 사용자 계정 ID |
| name_enc | BYTEA | N | 암호화 성명 |
| phone_enc | BYTEA | N | 암호화 휴대전화 |
| phone_hash | CHAR(64) | N | 중복검사용 HMAC |
| email_enc | BYTEA | N | 암호화 이메일 |
| email_hash | CHAR(64) | N | 중복검사용 HMAC |
| birth_year_enc | BYTEA | N | 필요한 경우 암호화 출생연도 |
| age_verified | BOOLEAN | Y | 만 19세 이상 확인 |
| phone_verified_at | TIMESTAMPTZ | N | 휴대전화 인증일시 |
| email_verified_at | TIMESTAMPTZ | N | 이메일 인증일시 |
| retention_until | DATE | N | 보유 종료일 |
| created_at | TIMESTAMPTZ | Y | 생성일시 |
| updated_at | TIMESTAMPTZ | Y | 수정일시 |
| deleted_at | TIMESTAMPTZ | N | 삭제일시 |

인덱스
- Unique: user_id
- Unique Partial: phone_hash WHERE deleted_at IS NULL
- Index: retention_until

보안
- 애플리케이션 수준 컬럼 암호화
- 키는 KMS 또는 Vault에서 관리
- 운영 DB 계정이 평문 복호화 권한을 갖지 않도록 분리
- 일반 추천서비스는 본 테이블 직접 조회 금지

### 5.2 identity.authentication

사용자 인증수단을 저장한다.

| 필드 | 형식 | 설명 |
|---|---|---|
| auth_id | UUID PK | 인증수단 ID |
| user_id | UUID FK | 사용자 ID |
| auth_type | VARCHAR | PHONE_OTP, EMAIL, SOCIAL |
| provider | VARCHAR | 인증사업자 |
| provider_subject | VARCHAR | 외부 식별값 |
| last_authenticated_at | TIMESTAMPTZ | 마지막 인증 |
| failed_count | INTEGER | 실패횟수 |
| locked_until | TIMESTAMPTZ | 잠금 종료 |
| created_at | TIMESTAMPTZ | 생성일시 |

## 6. 사용자 계정 및 권한

### 6.1 profile.user_account

| 필드 | 형식 | 설명 |
|---|---|---|
| user_id | UUID PK | 사용자 ID |
| account_type | VARCHAR | GUEST, VERIFIED, BUYER, EXHIBITOR, OPERATOR, ADMIN |
| account_status | VARCHAR | ACTIVE, SUSPENDED, WITHDRAWN |
| default_language | VARCHAR(10) | 기본 언어 |
| timezone | VARCHAR(50) | 기본 시간대 |
| last_login_at | TIMESTAMPTZ | 마지막 로그인 |
| created_at | TIMESTAMPTZ | 생성일시 |
| updated_at | TIMESTAMPTZ | 수정일시 |
| deleted_at | TIMESTAMPTZ | 탈퇴일시 |

### 6.2 profile.role

| 필드 | 형식 | 설명 |
|---|---|---|
| role_id | UUID PK | 역할 ID |
| role_code | VARCHAR UQ | 역할 코드 |
| role_name | VARCHAR | 역할명 |
| description | TEXT | 설명 |

### 6.3 profile.user_role

| 필드 | 형식 | 설명 |
|---|---|---|
| user_id | UUID FK | 사용자 |
| role_id | UUID FK | 역할 |
| event_id | UUID FK | 행사별 권한 |
| valid_from | TIMESTAMPTZ | 유효 시작 |
| valid_until | TIMESTAMPTZ | 유효 종료 |

복합 기본 키: `user_id + role_id + event_id`

## 7. 세션 및 방문 영역

### 7.1 profile.guest_session

| 필드 | 형식 | 설명 |
|---|---|---|
| guest_session_id | UUID PK | 비회원 세션 |
| session_token_hash | CHAR(64) | 토큰 해시 |
| event_id | UUID FK | 행사 |
| entry_channel | VARCHAR | QR, WEB, KIOSK |
| entry_code | VARCHAR | 진입 위치 코드 |
| device_type | VARCHAR | MOBILE_WEB, DESKTOP, KIOSK |
| language | VARCHAR | 언어 |
| expires_at | TIMESTAMPTZ | 만료일시 |
| converted_user_id | UUID FK | 회원 전환 사용자 |
| created_at | TIMESTAMPTZ | 생성일시 |

### 7.2 profile.visit_session

사용자의 실제 행사 방문 단위를 저장한다.

| 필드 | 형식 | 설명 |
|---|---|---|
| visit_session_id | UUID PK | 방문 세션 |
| event_id | UUID FK | 행사 |
| user_id | UUID FK | 사용자 |
| guest_session_id | UUID FK | 비회원 세션 |
| profile_id | UUID FK | 적용 프로파일 |
| visit_date | DATE | 방문일 |
| entry_at | TIMESTAMPTZ | 입장시간 |
| exit_at | TIMESTAMPTZ | 퇴장시간 |
| available_minutes | INTEGER | 예상 체류시간 |
| remaining_minutes | INTEGER | 남은 시간 |
| current_zone_id | UUID FK | 현재 구역 |
| route_preference | VARCHAR | 추천경로 기준 |
| session_status | VARCHAR | PLANNED, ACTIVE, COMPLETED, CANCELLED |
| created_at | TIMESTAMPTZ | 생성일시 |
| updated_at | TIMESTAMPTZ | 수정일시 |

제약조건
- user_id 또는 guest_session_id 중 하나 이상 필수
- available_minutes > 0
- exit_at >= entry_at

## 8. 동의관리

### 8.1 profile.consent_policy

| 필드 | 형식 | 설명 |
|---|---|---|
| consent_policy_id | UUID PK | 동의정책 ID |
| consent_type | VARCHAR | 동의유형 |
| version | VARCHAR | 버전 |
| title | VARCHAR | 제목 |
| body | TEXT | 전문 |
| required | BOOLEAN | 필수 여부 |
| effective_from | TIMESTAMPTZ | 시행일 |
| effective_until | TIMESTAMPTZ | 종료일 |
| created_at | TIMESTAMPTZ | 생성일시 |

### 8.2 profile.user_consent

| 필드 | 형식 | 설명 |
|---|---|---|
| consent_id | UUID PK | 동의 ID |
| user_id | UUID FK | 사용자 |
| guest_session_id | UUID FK | 비회원 |
| consent_policy_id | UUID FK | 정책 |
| agreed | BOOLEAN | 동의 여부 |
| agreed_at | TIMESTAMPTZ | 동의일시 |
| withdrawn_at | TIMESTAMPTZ | 철회일시 |
| source_channel | VARCHAR | WEB, QR, KIOSK |
| ip_hash | CHAR(64) | 접속 IP 해시 |
| created_at | TIMESTAMPTZ | 생성일시 |

필수 동의유형
- AGE_CONFIRMATION
- PERSONALIZED_RECOMMENDATION
- BEHAVIOR_DATA
- CONTACT_SHARING
- MARKETING
- THIRD_PARTY_PROVISION

## 9. 사용자 프로파일

### 9.1 profile.user_profile

| 필드 | 형식 | 설명 |
|---|---|---|
| profile_id | UUID PK | 프로파일 ID |
| user_id | UUID FK | 사용자 |
| event_id | UUID FK | 행사 |
| user_type | VARCHAR | GENERAL_VISITOR, BUYER |
| profile_status | VARCHAR | DRAFT, COMPLETE, INACTIVE |
| primary_goal_code | VARCHAR | 최우선 목적 |
| profile_completeness | NUMERIC(5,2) | 완성도 |
| current_version | INTEGER | 현재 버전 |
| created_at | TIMESTAMPTZ | 생성일시 |
| updated_at | TIMESTAMPTZ | 수정일시 |
| deleted_at | TIMESTAMPTZ | 삭제일시 |

유일성: `user_id + event_id + user_type + deleted_at IS NULL`

### 9.2 profile.profile_goal

| 필드 | 형식 | 설명 |
|---|---|---|
| profile_goal_id | UUID PK | 목적 ID |
| profile_id | UUID FK | 프로파일 |
| goal_code | VARCHAR | TASTING, PURCHASE, BUSINESS 등 |
| priority | SMALLINT | 우선순위 |
| source | VARCHAR | USER_SELECTED, AI_EXTRACTED |
| confidence | NUMERIC(4,3) | AI 추출 신뢰도 |
| created_at | TIMESTAMPTZ | 생성일시 |

제약
- 사용자 선택 목적은 신뢰도 1.0
- AI 추출 목적은 원문과 모델 실행 ID 저장
- 동일 프로파일 내 priority 중복 금지

### 9.3 profile.consumer_preference

| 필드 | 형식 | 설명 |
|---|---|---|
| profile_id | UUID PK/FK | 프로파일 |
| alcohol_min | NUMERIC(5,2) | 최소 도수 |
| alcohol_max | NUMERIC(5,2) | 최대 도수 |
| price_min | INTEGER | 최소가격 |
| price_max | INTEGER | 최대가격 |
| currency | CHAR(3) | 통화 |
| purchase_intent | VARCHAR | NONE, POSSIBLE, LIKELY |
| preferred_distance_m | INTEGER | 선호 이동거리 |
| avoid_congestion | BOOLEAN | 혼잡 회피 |
| updated_at | TIMESTAMPTZ | 수정일시 |

### 9.4 profile.preference_item

다중 선택형 취향을 저장한다.

| 필드 | 형식 | 설명 |
|---|---|---|
| preference_item_id | UUID PK | 항목 ID |
| profile_id | UUID FK | 프로파일 |
| attribute_group | VARCHAR | PRODUCT_CATEGORY, TASTE, ACTIVITY |
| attribute_code | VARCHAR | DISTILLED, DRY, TASTING |
| preference_level | SMALLINT | 선호 강도 1~5 |
| source | VARCHAR | USER, BEHAVIOR, AI |
| confidence | NUMERIC(4,3) | 신뢰도 |
| valid_from | TIMESTAMPTZ | 적용 시작 |
| valid_until | TIMESTAMPTZ | 적용 종료 |

### 9.5 profile.buyer_need

| 필드 | 형식 | 설명 |
|---|---|---|
| profile_id | UUID PK/FK | 바이어 프로파일 |
| organization_type | VARCHAR | 조직유형 |
| target_price_min | INTEGER | 목표가격 하한 |
| target_price_max | INTEGER | 목표가격 상한 |
| price_basis | VARCHAR | RETAIL, WHOLESALE |
| monthly_units_min | INTEGER | 월 최소수량 |
| monthly_units_max | INTEGER | 월 최대수량 |
| decision_timeline | VARCHAR | 의사결정 시점 |
| business_email_verified | BOOLEAN | 업무 이메일 인증 |
| company_verified | BOOLEAN | 소속 검증 |
| updated_at | TIMESTAMPTZ | 수정일시 |

### 9.6 profile.buyer_need_item

| 필드 | 형식 | 설명 |
|---|---|---|
| buyer_need_item_id | UUID PK | 요구항목 |
| profile_id | UUID FK | 바이어 프로파일 |
| need_group | VARCHAR | CATEGORY, CHANNEL, REGION, INTEREST |
| need_code | VARCHAR | 제품군·채널·지역 |
| required | BOOLEAN | 필수조건 여부 |
| priority | SMALLINT | 우선순위 |
| created_at | TIMESTAMPTZ | 생성일시 |

## 10. 프로파일 버전관리

### 10.1 profile.profile_version

추천 시점의 사용자 조건을 재현하기 위해 스냅샷을 저장한다.

| 필드 | 형식 | 설명 |
|---|---|---|
| profile_version_id | UUID PK | 버전 ID |
| profile_id | UUID FK | 프로파일 |
| version_number | INTEGER | 버전 |
| snapshot_json | JSONB | 전체 프로파일 스냅샷 |
| change_reason | VARCHAR | USER_UPDATE, FEEDBACK, AI_EXTRACTION |
| source_event_id | UUID | 변경 원인 이벤트 |
| created_at | TIMESTAMPTZ | 생성일시 |

인덱스
- Unique: profile_id, version_number
- GIN: snapshot_json

원칙
- 추천 생성 시 반드시 profile_version_id 참조
- 현재 테이블 값이 변경되어도 과거 추천결과 재현 가능
- 프로파일 변경 후 기존 추천세션은 만료 처리

## 11. 행사 및 공간

### 11.1 exhibition.event

| 필드 | 형식 | 설명 |
|---|---|---|
| event_id | UUID PK | 행사 ID |
| event_code | VARCHAR UQ | 행사 코드 |
| event_name | VARCHAR | 행사명 |
| venue_name | VARCHAR | 장소 |
| timezone | VARCHAR | 시간대 |
| start_date | DATE | 시작일 |
| end_date | DATE | 종료일 |
| event_status | VARCHAR | PREPARING, OPEN, CLOSED |
| created_at | TIMESTAMPTZ | 생성일시 |

### 11.2 exhibition.event_day

| 필드 | 형식 | 설명 |
|---|---|---|
| event_day_id | UUID PK | 행사일 ID |
| event_id | UUID FK | 행사 |
| event_date | DATE | 날짜 |
| open_at | TIMESTAMPTZ | 개장 |
| close_at | TIMESTAMPTZ | 폐장 |
| status | VARCHAR | OPEN, CLOSED, CANCELLED |

### 11.3 exhibition.event_zone

| 필드 | 형식 | 설명 |
|---|---|---|
| zone_id | UUID PK | 구역 ID |
| event_id | UUID FK | 행사 |
| zone_code | VARCHAR | 구역 코드 |
| zone_name | VARCHAR | 구역명 |
| floor | VARCHAR | 층 |
| map_x | NUMERIC | 지도 X |
| map_y | NUMERIC | 지도 Y |
| parent_zone_id | UUID FK | 상위 구역 |
| zone_type | VARCHAR | ENTRANCE, BOOTH_AREA, STAGE, REST |

## 12. 참가업체

### 12.1 exhibition.exhibitor

| 필드 | 형식 | 설명 |
|---|---|---|
| exhibitor_id | UUID PK | 업체 ID |
| company_name | VARCHAR | 업체명 |
| business_registration_hash | CHAR(64) | 사업자번호 해시 |
| company_summary | TEXT | 업체 소개 |
| business_type | VARCHAR | 양조장, 유통사, 기술기업 |
| region_code | VARCHAR | 소재지 |
| website_url | TEXT | 홈페이지 |
| approval_status | VARCHAR | DRAFT, SUBMITTED, APPROVED, REJECTED |
| data_completeness_score | NUMERIC(5,2) | 데이터 완성도 |
| profile_version | INTEGER | 업체 프로파일 버전 |
| created_at | TIMESTAMPTZ | 생성 |
| updated_at | TIMESTAMPTZ | 수정 |

### 12.2 exhibition.exhibitor_participation

업체의 행사 참가 단위를 관리한다.

| 필드 | 형식 | 설명 |
|---|---|---|
| participation_id | UUID PK | 참가 ID |
| event_id | UUID FK | 행사 |
| exhibitor_id | UUID FK | 업체 |
| participation_status | VARCHAR | APPLIED, APPROVED, CANCELLED |
| exhibition_categories | JSONB | 전시분야 |
| promotion_summary | TEXT | 현장 프로모션 |
| consultation_enabled | BOOLEAN | 상담 가능 |
| approved_at | TIMESTAMPTZ | 승인일 |

### 12.3 exhibition.exhibitor_staff

| 필드 | 형식 | 설명 |
|---|---|---|
| staff_id | UUID PK | 담당자 ID |
| exhibitor_id | UUID FK | 업체 |
| user_id | UUID FK | 사용자 계정 |
| display_name | VARCHAR | 노출명 |
| position_name | VARCHAR | 직책 |
| consultation_topics | JSONB | 상담 가능분야 |
| active | BOOLEAN | 활성 여부 |

## 13. 제품 및 속성

### 13.1 exhibition.product

| 필드 | 형식 | 설명 |
|---|---|---|
| product_id | UUID PK | 제품 ID |
| exhibitor_id | UUID FK | 업체 |
| product_name | VARCHAR | 제품명 |
| category_code | VARCHAR | 주종 |
| product_summary | TEXT | 소개 |
| alcohol_percentage | NUMERIC(5,2) | 도수 |
| retail_price | INTEGER | 소비자가 |
| event_price | INTEGER | 현장가격 |
| currency | CHAR(3) | 통화 |
| main_ingredients | JSONB | 주요 원료 |
| production_method | TEXT | 제조방식 |
| tasting_available | BOOLEAN | 시음 |
| purchase_available | BOOLEAN | 구매 |
| inventory_status | VARCHAR | AVAILABLE, LOW, SOLD_OUT |
| approval_status | VARCHAR | 승인상태 |
| created_at | TIMESTAMPTZ | 생성 |
| updated_at | TIMESTAMPTZ | 수정 |

### 13.2 exhibition.product_attribute

제품의 다중 속성을 구조화한다.

| 필드 | 형식 | 설명 |
|---|---|---|
| product_attribute_id | UUID PK | 속성 ID |
| product_id | UUID FK | 제품 |
| attribute_group | VARCHAR | TASTE, AROMA, USE, CERTIFICATION |
| attribute_code | VARCHAR | DRY, SWEET 등 |
| attribute_value | NUMERIC | 강도값 |
| source | VARCHAR | EXHIBITOR, AI, OPERATOR |
| confidence | NUMERIC(4,3) | 신뢰도 |
| approved | BOOLEAN | 승인여부 |

### 13.3 exhibition.product_image

| 필드 | 형식 | 설명 |
|---|---|---|
| product_image_id | UUID PK | 이미지 ID |
| product_id | UUID FK | 제품 |
| storage_key | TEXT | 파일 경로 |
| image_type | VARCHAR | MAIN, DETAIL |
| display_order | INTEGER | 순서 |
| alt_text | VARCHAR | 대체텍스트 |
| approved | BOOLEAN | 승인 |

## 14. 거래조건

### 14.1 exhibition.trade_condition

| 필드 | 형식 | 설명 |
|---|---|---|
| trade_condition_id | UUID PK | 거래조건 ID |
| exhibitor_id | UUID FK | 업체 |
| product_id | UUID FK | 제품 |
| min_order_quantity | INTEGER | 최소수량 |
| max_order_quantity | INTEGER | 최대수량 |
| monthly_capacity | INTEGER | 월 생산가능량 |
| wholesale_price_min | INTEGER | 도매가격 하한 |
| wholesale_price_max | INTEGER | 도매가격 상한 |
| oem_available | BOOLEAN | OEM 가능 |
| private_label_available | BOOLEAN | PB 가능 |
| exclusive_distribution | BOOLEAN | 독점유통 검토 |
| export_available | BOOLEAN | 수출 가능 |
| lead_time_days | INTEGER | 납기 |
| valid_from | DATE | 유효 시작 |
| valid_until | DATE | 유효 종료 |
| approval_status | VARCHAR | 승인상태 |

### 14.2 exhibition.trade_condition_item

| 필드 | 형식 | 설명 |
|---|---|---|
| condition_item_id | UUID PK | 조건 항목 |
| trade_condition_id | UUID FK | 거래조건 |
| condition_group | VARCHAR | CHANNEL, REGION, COUNTRY |
| condition_code | VARCHAR | 유통채널·공급지역 |
| preferred | BOOLEAN | 선호 여부 |
| required | BOOLEAN | 필수 여부 |

## 15. 부스 및 운영상태

### 15.1 exhibition.booth

| 필드 | 형식 | 설명 |
|---|---|---|
| booth_id | UUID PK | 부스 ID |
| event_id | UUID FK | 행사 |
| participation_id | UUID FK | 참가업체 |
| zone_id | UUID FK | 구역 |
| booth_number | VARCHAR | 부스번호 |
| map_x | NUMERIC | 좌표 X |
| map_y | NUMERIC | 좌표 Y |
| operating_status | VARCHAR | OPEN, PAUSED, CLOSED |
| congestion_level | VARCHAR | LOW, MEDIUM, HIGH |
| estimated_wait_minutes | INTEGER | 예상대기시간 |
| tasting_status | VARCHAR | AVAILABLE, PAUSED, ENDED |
| sales_status | VARCHAR | AVAILABLE, LIMITED, ENDED |
| updated_at | TIMESTAMPTZ | 수정일 |

인덱스
- Unique: event_id, booth_number
- Index: event_id, operating_status
- Index: zone_id, congestion_level

### 15.2 exhibition.booth_status_history

| 필드 | 형식 | 설명 |
|---|---|---|
| status_history_id | UUID PK | 이력 ID |
| booth_id | UUID FK | 부스 |
| operating_status | VARCHAR | 운영상태 |
| congestion_level | VARCHAR | 혼잡도 |
| estimated_wait_minutes | INTEGER | 대기시간 |
| changed_by | UUID | 변경자 |
| change_reason | VARCHAR | 변경사유 |
| created_at | TIMESTAMPTZ | 변경일 |

### 15.3 exhibition.booth_qr

| 필드 | 형식 | 설명 |
|---|---|---|
| booth_qr_id | UUID PK | QR ID |
| booth_id | UUID FK | 부스 |
| qr_token_hash | CHAR(64) | QR 토큰 해시 |
| valid_from | TIMESTAMPTZ | 유효 시작 |
| valid_until | TIMESTAMPTZ | 유효 종료 |
| status | VARCHAR | ACTIVE, REVOKED |
| created_at | TIMESTAMPTZ | 생성일 |

## 16. 행사 프로그램

### 16.1 exhibition.program

| 필드 | 형식 | 설명 |
|---|---|---|
| program_id | UUID PK | 프로그램 ID |
| event_id | UUID FK | 행사 |
| zone_id | UUID FK | 장소 |
| program_name | VARCHAR | 프로그램명 |
| program_type | VARCHAR | TASTING, SEMINAR, EVENT |
| description | TEXT | 설명 |
| start_at | TIMESTAMPTZ | 시작 |
| end_at | TIMESTAMPTZ | 종료 |
| capacity | INTEGER | 정원 |
| reservation_required | BOOLEAN | 예약 필요 |
| status | VARCHAR | SCHEDULED, OPEN, FULL, CANCELLED |

## 17. 상담 가능시간

### 17.1 interaction.availability_slot

| 필드 | 형식 | 설명 |
|---|---|---|
| availability_slot_id | UUID PK | 가능시간 ID |
| event_id | UUID FK | 행사 |
| exhibitor_id | UUID FK | 업체 |
| staff_id | UUID FK | 담당자 |
| booth_id | UUID FK | 장소 |
| topic_code | VARCHAR | 상담주제 |
| start_at | TIMESTAMPTZ | 시작 |
| end_at | TIMESTAMPTZ | 종료 |
| capacity | SMALLINT | 동시 상담수 |
| reserved_count | SMALLINT | 예약건수 |
| status | VARCHAR | OPEN, FULL, BLOCKED |
| row_version | BIGINT | 동시성 제어 |

예약 처리
1. Slot 조회
2. SELECT FOR UPDATE 또는 낙관적 잠금
3. reserved_count < capacity 확인
4. meeting 생성
5. reserved_count 증가
6. 트랜잭션 커밋

## 18. 추천 세션

### 18.1 matching.recommendation_session

| 필드 | 형식 | 설명 |
|---|---|---|
| recommendation_session_id | UUID PK | 추천세션 |
| event_id | UUID FK | 행사 |
| profile_id | UUID FK | 프로파일 |
| profile_version_id | UUID FK | 적용 버전 |
| visit_session_id | UUID FK | 방문세션 |
| recommendation_type | VARCHAR | BOOTH, PRODUCT, MEETING, MIXED |
| model_version_id | UUID FK | 모델버전 |
| policy_version_id | UUID FK | 정책버전 |
| context_snapshot | JSONB | 당시 상황 |
| candidate_count | INTEGER | 후보 수 |
| filtered_count | INTEGER | 필터 후 수 |
| status | VARCHAR | ACTIVE, EXPIRED, INVALIDATED |
| generated_at | TIMESTAMPTZ | 생성일 |
| expires_at | TIMESTAMPTZ | 만료일 |
| latency_ms | INTEGER | 처리시간 |

context_snapshot 예시

```json
{
  "current_zone_id": "zone-001",
  "remaining_minutes": 70,
  "current_time": "2026-10-09T14:20:00+09:00",
  "visited_booth_ids": ["booth-003"],
  "congestion_version": 21,
  "booth_status_version": 38
}
```

## 19. 매칭 결과

### 19.1 matching.match_result

| 필드 | 형식 | 설명 |
|---|---|---|
| match_result_id | UUID PK | 매칭결과 |
| recommendation_session_id | UUID FK | 추천세션 |
| object_type | VARCHAR | BOOTH, PRODUCT, EXHIBITOR, PROGRAM |
| object_id | UUID | 대상 ID |
| raw_score | NUMERIC(8,5) | 원점수 |
| normalized_score | NUMERIC(5,2) | 정규화 |
| rank | INTEGER | 순위 |
| hard_filter_passed | BOOLEAN | 필수조건 통과 |
| preference_score | NUMERIC(8,5) | 취향점수 |
| goal_score | NUMERIC(8,5) | 목적점수 |
| trade_score | NUMERIC(8,5) | 거래점수 |
| context_score | NUMERIC(8,5) | 상황점수 |
| behavior_score | NUMERIC(8,5) | 행동점수 |
| diversity_adjustment | NUMERIC(8,5) | 다양성 보정 |
| trust_score | NUMERIC(8,5) | 데이터 신뢰도 |
| recommended_action | VARCHAR | VISIT_NOW, SAVE, REQUEST_MEETING |
| created_at | TIMESTAMPTZ | 생성일 |

인덱스
- recommendation_session_id, rank
- object_type, object_id
- normalized_score DESC

### 19.2 matching.match_reason

| 필드 | 형식 | 설명 |
|---|---|---|
| match_reason_id | UUID PK | 근거 ID |
| match_result_id | UUID FK | 결과 |
| reason_code | VARCHAR | TASTE_MATCH 등 |
| reason_text | VARCHAR | 사용자 노출문 |
| source_attribute | VARCHAR | 사용자 속성 |
| target_attribute | VARCHAR | 대상 속성 |
| contribution_score | NUMERIC(8,5) | 점수 기여 |
| display_order | SMALLINT | 노출순서 |
| generated_by | VARCHAR | TEMPLATE, LLM |
| ai_run_id | UUID FK | AI 실행 ID |
| approved | BOOLEAN | 검증 여부 |

## 20. 필수조건 필터 이력

### 20.1 matching.filter_result

추천 후보가 제외된 이유를 저장한다.

| 필드 | 형식 | 설명 |
|---|---|---|
| filter_result_id | UUID PK | 필터결과 |
| recommendation_session_id | UUID FK | 추천세션 |
| object_type | VARCHAR | 대상유형 |
| object_id | UUID | 대상 |
| filter_code | VARCHAR | PRICE_MISMATCH, BOOTH_CLOSED 등 |
| passed | BOOLEAN | 통과 여부 |
| rule_version | VARCHAR | 규칙버전 |
| details_json | JSONB | 판단근거 |
| created_at | TIMESTAMPTZ | 생성일 |

운영자와 개발자는 추천되지 않은 이유를 추적할 수 있어야 한다. 사용자에게는 내부 필터 전체를 노출하지 않는다.

## 21. 관심목록

### 21.1 interaction.favorite

| 필드 | 형식 | 설명 |
|---|---|---|
| favorite_id | UUID PK | 관심 ID |
| user_id | UUID FK | 사용자 |
| event_id | UUID FK | 행사 |
| object_type | VARCHAR | BOOTH, PRODUCT, PROGRAM |
| object_id | UUID | 대상 |
| source | VARCHAR | SEARCH, RECOMMENDATION |
| match_result_id | UUID FK | 추천결과 |
| created_at | TIMESTAMPTZ | 생성일 |
| deleted_at | TIMESTAMPTZ | 해제일 |

Unique Partial: `user_id + event_id + object_type + object_id WHERE deleted_at IS NULL`

## 22. QR 체크인

### 22.1 interaction.check_in

| 필드 | 형식 | 설명 |
|---|---|---|
| check_in_id | UUID PK | 체크인 |
| event_id | UUID FK | 행사 |
| visit_session_id | UUID FK | 방문세션 |
| user_id | UUID FK | 사용자 |
| guest_session_id | UUID FK | 비회원 |
| booth_id | UUID FK | 부스 |
| match_result_id | UUID FK | 추천결과 |
| check_in_method | VARCHAR | QR, MANUAL, STAFF |
| activities | JSONB | 시음·구매·상담 |
| checked_in_at | TIMESTAMPTZ | 체크인 |
| created_at | TIMESTAMPTZ | 생성일 |

중복 기준
- 동일 방문세션·부스에서 5분 이내 중복 방지
- 재방문은 별도 이벤트로 허용
- QR 토큰 검증결과 저장

## 23. 피드백

### 23.1 interaction.feedback

| 필드 | 형식 | 설명 |
|---|---|---|
| feedback_id | UUID PK | 피드백 |
| user_id | UUID FK | 사용자 |
| visit_session_id | UUID FK | 방문세션 |
| object_type | VARCHAR | 대상유형 |
| object_id | UUID | 대상 |
| match_result_id | UUID FK | 추천결과 |
| rating | VARCHAR | VERY_RELEVANT, NEUTRAL, IRRELEVANT |
| positive_reasons | JSONB | 긍정사유 |
| negative_reasons | JSONB | 부정사유 |
| comment | TEXT | 의견 |
| created_at | TIMESTAMPTZ | 생성일 |

학습 적용
- 원본 피드백은 변경하지 않음
- 프로파일 보정결과는 별도 테이블에 저장
- 혼잡·품절 등 상황요인은 취향 학습에서 제외

### 23.2 profile.preference_adjustment

| 필드 | 형식 | 설명 |
|---|---|---|
| adjustment_id | UUID PK | 보정 ID |
| profile_id | UUID FK | 프로파일 |
| source_feedback_id | UUID FK | 피드백 |
| attribute_group | VARCHAR | TASTE, PRICE 등 |
| attribute_code | VARCHAR | DRY 등 |
| adjustment_value | NUMERIC | 증감값 |
| applied | BOOLEAN | 반영 여부 |
| applied_at | TIMESTAMPTZ | 반영일 |

## 24. 상담

### 24.1 interaction.meeting

| 필드 | 형식 | 설명 |
|---|---|---|
| meeting_id | UUID PK | 상담 ID |
| event_id | UUID FK | 행사 |
| buyer_profile_id | UUID FK | 바이어 |
| exhibitor_id | UUID FK | 업체 |
| staff_id | UUID FK | 담당자 |
| booth_id | UUID FK | 장소 |
| topic_code | VARCHAR | 상담주제 |
| message | TEXT | 요청내용 |
| status | VARCHAR | REQUESTED, CONFIRMED 등 |
| confirmed_start | TIMESTAMPTZ | 확정 시작 |
| confirmed_end | TIMESTAMPTZ | 확정 종료 |
| contact_share_consent | BOOLEAN | 연락처 공유동의 |
| match_result_id | UUID FK | 추천결과 |
| created_at | TIMESTAMPTZ | 생성일 |
| updated_at | TIMESTAMPTZ | 수정일 |

### 24.2 interaction.meeting_slot_request

| 필드 | 형식 | 설명 |
|---|---|---|
| slot_request_id | UUID PK | 요청시간 |
| meeting_id | UUID FK | 상담 |
| start_at | TIMESTAMPTZ | 시작 |
| end_at | TIMESTAMPTZ | 종료 |
| preference_order | SMALLINT | 희망순위 |
| status | VARCHAR | REQUESTED, ACCEPTED, REJECTED |

### 24.3 interaction.meeting_status_history

| 필드 | 형식 | 설명 |
|---|---|---|
| meeting_status_history_id | UUID PK | 상태이력 |
| meeting_id | UUID FK | 상담 |
| previous_status | VARCHAR | 이전 |
| new_status | VARCHAR | 신규 |
| changed_by | UUID | 변경자 |
| reason | TEXT | 사유 |
| created_at | TIMESTAMPTZ | 변경일 |

### 24.4 interaction.meeting_outcome

| 필드 | 형식 | 설명 |
|---|---|---|
| meeting_id | UUID PK/FK | 상담 |
| lead_status | VARCHAR | QUALIFIED, UNQUALIFIED |
| outcome_code | VARCHAR | FOLLOW_UP_REQUIRED 등 |
| estimated_value | NUMERIC | 예상거래금액 |
| estimated_probability | NUMERIC(5,2) | 성사확률 |
| notes | TEXT | 결과 |
| completed_at | TIMESTAMPTZ | 등록일 |

### 24.5 interaction.follow_up_action

| 필드 | 형식 | 설명 |
|---|---|---|
| follow_up_action_id | UUID PK | 후속조치 |
| meeting_id | UUID FK | 상담 |
| action_code | VARCHAR | SAMPLE, QUOTE, MEETING |
| owner_user_id | UUID FK | 담당자 |
| due_date | DATE | 예정일 |
| status | VARCHAR | OPEN, DONE, CANCELLED |
| completed_at | TIMESTAMPTZ | 완료일 |

## 25. 행동 이벤트

### 25.1 interaction.interaction_event

대량 이벤트 테이블로, 일자 단위 파티셔닝을 권장한다.

| 필드 | 형식 | 설명 |
|---|---|---|
| event_log_id | UUID | 이벤트 로그 ID |
| event_id | UUID FK | 행사 |
| event_type | VARCHAR | 이벤트 유형 |
| user_id | UUID | 사용자 |
| guest_session_id | UUID | 비회원 |
| visit_session_id | UUID | 방문세션 |
| object_type | VARCHAR | 대상유형 |
| object_id | UUID | 대상 |
| recommendation_session_id | UUID | 추천세션 |
| match_result_id | UUID | 추천결과 |
| rank_at_event | INTEGER | 당시순위 |
| screen_code | VARCHAR | 화면 |
| context_json | JSONB | 상황정보 |
| occurred_at | TIMESTAMPTZ | 발생시각 |
| received_at | TIMESTAMPTZ | 서버수신 |
| event_date | DATE | 파티션 키 |

파티셔닝
- `PARTITION BY RANGE(event_date)`
- 행사기간에는 일 단위, 장기 운영 시 월 단위 파티션 적용

주요 인덱스
- event_date, event_type
- user_id, occurred_at DESC
- object_type, object_id, occurred_at
- recommendation_session_id
- BRIN: occurred_at

## 26. 방문경로

### 26.1 interaction.route

| 필드 | 형식 | 설명 |
|---|---|---|
| route_id | UUID PK | 경로 ID |
| visit_session_id | UUID FK | 방문세션 |
| optimization_type | VARCHAR | DISTANCE, CONGESTION, RECOMMENDATION |
| total_minutes | INTEGER | 총시간 |
| walking_minutes | INTEGER | 이동시간 |
| route_status | VARCHAR | DRAFT, ACTIVE, COMPLETED |
| context_snapshot | JSONB | 계산조건 |
| created_at | TIMESTAMPTZ | 생성일 |
| updated_at | TIMESTAMPTZ | 수정일 |

### 26.2 interaction.route_item

| 필드 | 형식 | 설명 |
|---|---|---|
| route_item_id | UUID PK | 경로항목 |
| route_id | UUID FK | 경로 |
| sequence | INTEGER | 순서 |
| object_type | VARCHAR | BOOTH, PROGRAM, MEETING |
| object_id | UUID | 대상 |
| planned_arrival_at | TIMESTAMPTZ | 예정 도착 |
| planned_duration_minutes | INTEGER | 예정 체류 |
| actual_arrival_at | TIMESTAMPTZ | 실제 도착 |
| status | VARCHAR | PLANNED, VISITED, SKIPPED |

## 27. AI 구조화 및 모델 실행

### 27.1 ai.ai_model_version

| 필드 | 형식 | 설명 |
|---|---|---|
| model_version_id | UUID PK | 모델버전 |
| model_type | VARCHAR | EMBEDDING, LLM, RANKING |
| model_name | VARCHAR | 모델명 |
| provider | VARCHAR | 제공자 |
| version | VARCHAR | 버전 |
| config_json | JSONB | 파라미터 |
| deployed_at | TIMESTAMPTZ | 배포일 |
| retired_at | TIMESTAMPTZ | 종료일 |
| status | VARCHAR | TEST, ACTIVE, RETIRED |

### 27.2 ai.ai_run

AI 호출·처리 이력을 저장한다.

| 필드 | 형식 | 설명 |
|---|---|---|
| ai_run_id | UUID PK | 실행 ID |
| model_version_id | UUID FK | 모델 |
| task_type | VARCHAR | ATTRIBUTE_EXTRACTION, EXPLANATION |
| input_reference_type | VARCHAR | PRODUCT, PROFILE, MATCH |
| input_reference_id | UUID | 입력 대상 |
| input_hash | CHAR(64) | 입력 해시 |
| prompt_version | VARCHAR | 프롬프트 버전 |
| output_json | JSONB | 결과 |
| validation_status | VARCHAR | VALID, INVALID, REVIEW |
| latency_ms | INTEGER | 지연 |
| token_input | INTEGER | 입력토큰 |
| token_output | INTEGER | 출력토큰 |
| estimated_cost | NUMERIC | 비용 |
| error_code | VARCHAR | 오류 |
| created_at | TIMESTAMPTZ | 실행일 |

개인정보 통제
- AI 입력에 이름·전화번호·이메일 제외
- 입력 원문이 개인정보를 포함할 수 있으면 사전 마스킹
- 외부 모델 사용 시 처리위탁·국외이전 여부 검토
- 전체 프롬프트 원문 대신 해시·비식별 입력 저장 가능

## 28. 임베딩

### 28.1 ai.object_embedding

| 필드 | 형식 | 설명 |
|---|---|---|
| embedding_id | UUID PK | 임베딩 ID |
| object_type | VARCHAR | EXHIBITOR, PRODUCT |
| object_id | UUID | 대상 |
| content_type | VARCHAR | SUMMARY, TRADE, PRODUCT |
| content_text | TEXT | 임베딩 기준문 |
| content_hash | CHAR(64) | 변경검사 |
| embedding | VECTOR | 벡터 |
| model_version_id | UUID FK | 임베딩 모델 |
| language | VARCHAR | 언어 |
| active | BOOLEAN | 활성 |
| created_at | TIMESTAMPTZ | 생성일 |

pgvector 인덱스 예시

```sql
CREATE INDEX idx_object_embedding_hnsw
ON ai.object_embedding
USING hnsw (embedding vector_cosine_ops);
```

재생성 조건
- 업체·제품 설명 변경
- 속성 승인 변경
- 거래조건 변경
- 임베딩 모델 버전 변경
- 언어별 설명 추가

## 29. AI 속성추출

### 29.1 ai.extracted_attribute

| 필드 | 형식 | 설명 |
|---|---|---|
| extracted_attribute_id | UUID PK | 추출 ID |
| object_type | VARCHAR | PRODUCT, EXHIBITOR |
| object_id | UUID | 대상 |
| attribute_group | VARCHAR | TASTE, CHANNEL 등 |
| attribute_code | VARCHAR | DRY, EXPORT |
| attribute_value | JSONB | 값 |
| confidence | NUMERIC(4,3) | 신뢰도 |
| ai_run_id | UUID FK | 실행 |
| review_status | VARCHAR | PENDING, APPROVED, REJECTED |
| reviewed_by | UUID | 검수자 |
| reviewed_at | TIMESTAMPTZ | 검수일 |

AI 추출결과는 승인 전 추천 필수조건으로 사용하지 않는다. 자유서술문에서 '수출 가능'이라는 표현을 봤다고 실제 수출계약 조건이 완비된 것은 아니기 때문이다.

## 30. 추천 정책 및 가중치

### 30.1 matching.match_policy_version

| 필드 | 형식 | 설명 |
|---|---|---|
| policy_version_id | UUID PK | 정책버전 |
| event_id | UUID FK | 행사 |
| user_type | VARCHAR | GENERAL_VISITOR, BUYER |
| version | VARCHAR | 버전 |
| status | VARCHAR | DRAFT, ACTIVE, RETIRED |
| effective_from | TIMESTAMPTZ | 시작 |
| effective_until | TIMESTAMPTZ | 종료 |
| created_at | TIMESTAMPTZ | 생성 |

### 30.2 matching.match_weight

| 필드 | 형식 | 설명 |
|---|---|---|
| match_weight_id | UUID PK | 가중치 ID |
| policy_version_id | UUID FK | 정책 |
| score_component | VARCHAR | TASTE, GOAL, PRICE 등 |
| weight_value | NUMERIC(8,5) | 가중치 |
| min_score | NUMERIC | 최소 |
| max_score | NUMERIC | 최대 |
| config_json | JSONB | 상세설정 |

### 30.3 matching.filter_rule

| 필드 | 형식 | 설명 |
|---|---|---|
| filter_rule_id | UUID PK | 필터규칙 |
| policy_version_id | UUID FK | 정책 |
| rule_code | VARCHAR | BOOTH_OPEN, MOQ_MATCH |
| rule_order | INTEGER | 실행순서 |
| rule_type | VARCHAR | HARD, SOFT |
| rule_config | JSONB | 규칙설정 |
| active | BOOLEAN | 활성 |

## 31. 관리자 감사로그

### 31.1 audit.audit_log

Append-only 방식으로 저장한다.

| 필드 | 형식 | 설명 |
|---|---|---|
| audit_log_id | UUID PK | 감사로그 |
| actor_user_id | UUID | 행위자 |
| actor_role | VARCHAR | 역할 |
| action_type | VARCHAR | VIEW, CREATE, UPDATE, DELETE, EXPORT |
| resource_type | VARCHAR | 대상 테이블·기능 |
| resource_id | UUID | 대상 ID |
| before_hash | CHAR(64) | 변경 전 해시 |
| after_hash | CHAR(64) | 변경 후 해시 |
| reason_code | VARCHAR | 변경·조회 사유 |
| request_id | UUID | 요청추적 ID |
| ip_hash | CHAR(64) | IP 해시 |
| occurred_at | TIMESTAMPTZ | 발생일 |

반드시 기록할 행위
- 개인정보 조회
- 참가업체 정보 승인·반려
- 바이어 연락처 조회
- 데이터 엑셀 다운로드
- 추천 가중치 변경
- 추천결과 수동 조정
- 부스 운영상태 변경
- 사용자 데이터 삭제

## 32. 데이터 동기화

### 32.1 integration.source_system

| 필드 | 형식 | 설명 |
|---|---|---|
| source_system_id | UUID PK | 외부시스템 |
| system_code | VARCHAR | BACKJU_WEB |
| system_name | VARCHAR | 시스템명 |
| sync_type | VARCHAR | API, CSV, DB_VIEW |
| active | BOOLEAN | 활성 |

### 32.2 integration.external_reference

기존 사이트 ID와 신규 플랫폼 ID를 연결한다.

| 필드 | 형식 | 설명 |
|---|---|---|
| external_reference_id | UUID PK | 연결 ID |
| source_system_id | UUID FK | 외부시스템 |
| object_type | VARCHAR | USER, EXHIBITOR, PRODUCT |
| external_id | VARCHAR | 기존 ID |
| internal_id | UUID | 신규 ID |
| last_synced_at | TIMESTAMPTZ | 동기화일 |
| source_updated_at | TIMESTAMPTZ | 원본 수정일 |
| sync_status | VARCHAR | SYNCED, FAILED, CONFLICT |

### 32.3 integration.sync_job

| 필드 | 형식 | 설명 |
|---|---|---|
| sync_job_id | UUID PK | 작업 ID |
| source_system_id | UUID FK | 외부시스템 |
| job_type | VARCHAR | FULL, INCREMENTAL |
| object_type | VARCHAR | 대상 |
| started_at | TIMESTAMPTZ | 시작 |
| ended_at | TIMESTAMPTZ | 종료 |
| total_count | INTEGER | 전체 |
| success_count | INTEGER | 성공 |
| failure_count | INTEGER | 실패 |
| status | VARCHAR | RUNNING, SUCCESS, FAILED |
| error_summary | TEXT | 오류요약 |

## 33. 데이터 품질

### 33.1 quality.data_quality_issue

| 필드 | 형식 | 설명 |
|---|---|---|
| issue_id | UUID PK | 품질이슈 |
| object_type | VARCHAR | EXHIBITOR, PRODUCT |
| object_id | UUID | 대상 |
| issue_code | VARCHAR | MISSING_PRICE, INVALID_MOQ |
| severity | VARCHAR | LOW, MEDIUM, HIGH |
| detected_by | VARCHAR | RULE, AI, OPERATOR |
| status | VARCHAR | OPEN, RESOLVED, IGNORED |
| resolution_note | TEXT | 처리내용 |
| created_at | TIMESTAMPTZ | 생성일 |
| resolved_at | TIMESTAMPTZ | 해결일 |

### 33.2 업체 데이터 완성도

```
업체 완성도 =
기본정보 20%
제품정보 25%
거래조건 25%
현장운영정보 15%
상담가능시간 10%
검수상태 5%
```

완성도가 일정 기준 이하인 업체는 B2B 추천 상위 노출에서 제외하거나 신뢰도 점수를 감점한다.

## 34. 분석 데이터마트

### 34.1 analytics.fact_recommendation

| 필드 | 설명 |
|---|---|
| event_date | 기준일 |
| event_id | 행사 |
| recommendation_session_id | 추천세션 |
| match_result_id | 추천결과 |
| user_type | 사용자유형 |
| object_type | 대상 |
| object_id | 대상 ID |
| rank | 순위 |
| score | 점수 |
| impression_count | 노출 |
| click_count | 클릭 |
| favorite_count | 저장 |
| checkin_count | 방문 |
| meeting_request_count | 상담요청 |
| meeting_complete_count | 상담완료 |

### 34.2 analytics.fact_meeting

- 행사 / 업체 / 바이어 유형 / 상담주제 / 요청일 / 확정 여부 / 완료 여부 / 유효리드 여부 / 후속조치 / 예상 거래금액

### 34.3 analytics.dim_exhibitor

- 업체 / 지역 / 업종 / 제품군 / 부스구역 / 데이터 완성도

### 34.4 주요 산출지표

```
추천 클릭률 = 추천 클릭 수 / 추천 노출 수
추천 방문전환율 = 추천 대상 QR 체크인 수 / 추천 클릭 수
상담요청 전환율 = 상담요청 수 / 바이어 업체상세 조회 수
상담완료율 = 완료 상담 수 / 확정 상담 수
유효리드율 = 유효 리드 수 / 완료 상담 수
```

## 35. 인덱스 설계

### 35.1 사용자·프로파일

```sql
CREATE INDEX idx_profile_user_event
ON profile.user_profile(user_id, event_id);

CREATE INDEX idx_profile_user_type
ON profile.user_profile(event_id, user_type, profile_status);
```

### 35.2 제품

```sql
CREATE INDEX idx_product_category
ON exhibition.product(category_code, approval_status);

CREATE INDEX idx_product_price
ON exhibition.product(retail_price)
WHERE approval_status = 'APPROVED';

CREATE INDEX idx_product_attributes
ON exhibition.product_attribute(attribute_group, attribute_code);
```

### 35.3 바이어 거래조건

```sql
CREATE INDEX idx_trade_region
ON exhibition.trade_condition_item(condition_group, condition_code);

CREATE INDEX idx_trade_moq
ON exhibition.trade_condition(min_order_quantity, monthly_capacity);
```

### 35.4 추천

```sql
CREATE INDEX idx_match_session_rank
ON matching.match_result(recommendation_session_id, rank);

CREATE INDEX idx_match_object
ON matching.match_result(object_type, object_id);
```

### 35.5 상담

```sql
CREATE INDEX idx_meeting_exhibitor_time
ON interaction.meeting(exhibitor_id, confirmed_start);

CREATE INDEX idx_meeting_buyer_time
ON interaction.meeting(buyer_profile_id, confirmed_start);
```

## 36. 캐시 설계

### 36.1 Redis Key

```
session:guest:{guest_session_id}
session:user:{user_id}
profile:{profile_id}:v{version}
recommendation:{recommendation_session_id}
home:{visit_session_id}
booth:{booth_id}:status
availability:{exhibitor_id}:{date}
route:{route_id}
rate-limit:{user_id}:{api}
```

### 36.2 TTL 기준

| 데이터 | TTL |
|---|---|
| 비회원 세션 | 24시간 |
| 사용자 세션 | 30분 슬라이딩 |
| 추천 결과 | 10분 |
| 추천 홈 | 2분 |
| 부스 상태 | 30초 |
| 상담 가능시간 | 30초 |
| 업체·제품 기본정보 | 30분 |
| 지도정보 | 행사기간 전체 |

### 36.3 캐시 무효화

- 프로파일 수정
- 부스 운영상태 변경
- 제품 품절
- 상담시간 예약
- 추천정책 변경
- 업체정보 승인·수정

## 37. 동시성 및 트랜잭션

### 37.1 상담예약

필수 원자성: 상담 가능시간 확인 + 상담 생성 + 예약수 증가 + 상태이력 생성을 하나의 DB 트랜잭션으로 처리한다.

### 37.2 QR 체크인

- 동일 Idempotency-Key 재요청 시 기존 결과 반환
- QR 검증과 체크인 저장을 단일 트랜잭션 처리
- 이벤트 로그는 Outbox Pattern으로 비동기 발행

### 37.3 Outbox 테이블

`integration.outbox_event`

| 필드 | 설명 |
|---|---|
| outbox_event_id | 이벤트 ID |
| aggregate_type | 엔터티 유형 |
| aggregate_id | 엔터티 ID |
| event_type | 이벤트 유형 |
| payload_json | 메시지 |
| status | PENDING, PUBLISHED, FAILED |
| created_at | 생성일 |
| published_at | 발행일 |

## 38. 데이터 보유 및 파기

| 데이터 | 보유기간 기준 | 파기방식 |
|---|---|---|
| 비회원 세션 | 행사 종료 후 30일 | 물리삭제 |
| 직접 식별정보 | 동의 목적기간 | 암호화키 폐기·물리삭제 |
| 프로파일 | 동의 유지기간 | 사용자 ID 제거·삭제 |
| 추천결과 | 행사 종료 후 분석기간 | 가명처리 |
| 행동로그 | 가명처리 후 통계기간 | 개인 연결키 삭제 |
| 상담정보 | 후속상담 목적기간 | 식별정보 분리삭제 |
| 감사로그 | 보안정책 기간 | 변경불가 보관 |
| AI 입력·출력 | 품질검증 최소기간 | 개인정보 제거 후 보관 |

## 39. 테이블 우선 구축 범위

### MVP 필수

- user_account
- user_identity
- guest_session
- visit_session
- user_consent
- user_profile
- profile_goal
- consumer_preference
- preference_item
- buyer_need
- buyer_need_item
- event
- event_zone
- exhibitor
- exhibitor_participation
- product
- product_attribute
- trade_condition
- booth
- recommendation_session
- match_result
- match_reason
- favorite
- check_in
- feedback
- meeting
- interaction_event
- ai_model_version
- object_embedding
- audit_log

### 2차 확장

- 프로그램 예약
- 경로 최적화 상세
- 리드 후속관리
- AI 구조화 검수
- 분석 데이터마트
- 동기화 관리
- 데이터품질 자동검사
- 다국어 임베딩
- 모델 A/B 테스트

## 40. 핵심 무결성 규칙

- 승인되지 않은 업체·제품은 추천 대상 제외
- 운영 종료 부스는 실시간 추천 대상 제외
- 품절 제품은 구매 추천 대상 제외
- 바이어 필수조건과 업체 거래조건 불일치 시 필터링
- 추천 결과는 프로파일·모델·정책 버전과 함께 저장
- 상담 연락처는 공유 동의와 상담 수락 후 제공
- 행동동의 철회 후 개인화 학습 이벤트 생성 중지
- 개인정보 삭제 후 추천·행동로그에서 직접 식별 연결 제거
- AI 추출속성은 승인 전 필수조건 판단에 사용 금지
- 추천결과 수동 변경 시 변경자·사유·전후 상태 기록

## 41. DB 검수 체크리스트

**구조**
- 개인정보 스키마와 운영 스키마 분리
- 모든 주요 테이블 PK·FK 지정
- 논리삭제 기준 일관성 확보
- 행사별 데이터 분리 가능
- 추천 버전 재현 가능

**성능**
- 추천 필터 주요컬럼 인덱스 적용
- 이벤트 로그 파티셔닝
- 벡터 검색 인덱스 적용
- 실시간 부스상태 Redis 캐시
- 상담예약 동시성 테스트

**보안**
- 개인정보 암호화
- 해시값과 암호화값 분리
- 관리자 다운로드 로그
- 바이어 연락처 접근통제
- 감사로그 변경 방지

**AI**
- 임베딩 모델 버전 저장
- AI 결과 JSON Schema 검증
- AI 추출정보 승인상태 관리
- 추천근거와 실제 입력속성 연결
- 모델 변경 전후 성능비교 가능

**분석**
- 추천 노출부터 방문까지 동일 ID 연결
- 상담요청부터 유효리드까지 상태 추적
- 일반 관람객과 바이어 KPI 분리
- 추천 실패·후보 없음 원인 집계
- 업체별 추천 편중 분석 가능

## 42. 최종 권고 구조

본 서비스의 DB는 단순히 참가자와 업체 정보를 저장하는 형태가 아니라 다음 네 가지 역할을 동시에 수행해야 한다.

1. 거래·취향 조건의 구조화 저장소
2. 추천 판단 당시 상태를 재현하는 버전 저장소
3. 추천부터 방문·상담까지 연결하는 이벤트 저장소
4. AI 추출정보와 사람이 승인한 정보를 구분하는 신뢰 저장소

최종 권장 구성은 다음과 같다.

```
PostgreSQL
├─ identity
├─ profile
├─ exhibition
├─ matching
├─ interaction
├─ ai
├─ integration
├─ audit
└─ analytics

Redis
├─ 세션
├─ 추천 캐시
├─ 부스 실시간 상태
├─ 상담 슬롯 잠금
└─ 요청 제한

Object Storage
├─ 제품 이미지
├─ 업체 자료
└─ 운영 첨부파일

pgvector
├─ 제품 임베딩
├─ 업체 임베딩
└─ 바이어 요구사항 임베딩
```

다음 산출물은 **AI 초개인화 매칭엔진 상세설계서**로 진행하며, 후보검색·필수조건 필터·가중치 계산·양면 적합도·다양성 보정·실시간 재정렬·추천 설명·평가 지표를 구체화한다.
