# 백주 AI 셀파 프론트엔드·백엔드·AI 인터페이스 명세

> 문서 상태: MVP 구현 기준안 v1.0  
> 기준일: 2026-08-01  
> 상위 문서: [통합 서비스 설계안](./2026-backju-ai-matching-service-design.md)  
> 화면 기준: [사용자 화면 IA·와이어프레임](./user-ia-wireframes.md)
> DB 기준: [ERD 상세설계 및 테이블 정의서](./db-erd-table-spec.md)  
> 매칭 처리 기준: [5단계 AI 매칭엔진 아키텍처](./05-ai-matching-engine-architecture.md)
> 코드 의미체계: [6단계 매칭 분류체계·온톨로지](./06-matching-ontology.md)

## 1. 목적과 적용 범위

이 문서는 모바일 웹, 데스크톱 웹, 키오스크, 참가업체 포털, 운영자 화면이 백엔드 및 AI 계층과 통신하는 계약을 정의한다.

- 익명 세션·휴대전화 인증·역할별 권한
- 사용자 프로파일, 업체·제품·부스, 일정·상담 데이터
- 후보검색, 규칙 점수, 재정렬, 추천 이유 생성
- 저장, 경로, QR 방문, 상담, 피드백 이벤트
- 동의, 식별정보 분리, 감사로그
- 현장 운영상태와 추천 결과 갱신
- 외부 원천 시스템과 CSV·API·웹훅 연계

기존 `backju.kr` 회원체계와 완전 통합하지 않는 독립형 연계 MVP를 전제로 한다. 원천 사전등록·참가업체 데이터는 CSV, 읽기 전용 API 또는 서버 간 웹훅으로 동기화한다.

온톨로지 조회·정규화의 구현 계약은 `GET /api/v1/ontology`, `GET /api/v1/ontology/concepts`, `GET /api/v1/ontology/concepts/{concept_code}`, `POST /api/v1/ontology/resolve`, `POST /api/v1/ontology/derive-band`다. 자연어 AI 구조화는 공개 API가 아니라 내부 `POST /internal/ai/ontology/extract` 경계에서만 호출한다.

## 2. 규범적 설계 결정

### 2.1 역할 분리

- 프론트엔드는 입력·표시·로컬 재시도·사용자 행동 수집을 담당한다.
- BFF/API는 인증, 소유권, 동의, 유효성, 멱등성, 운영조건을 통제한다.
- 추천 오케스트레이터는 후보검색, 하드 필터, 점수, 재정렬, 다양성 보정을 수행한다.
- 생성형 AI는 자연어 구조화와 근거 기반 설명만 수행한다.
- 원천 사실은 관계형 DB와 승인된 검색 인덱스가 제공한다. LLM 출력은 원천 사실이 아니다.

### 2.2 인증 상태와 역할

인증 상태와 업무 역할을 하나의 enum으로 섞지 않는다.

```text
authentication_state: GUEST | PHONE_VERIFIED | ACCOUNT_AUTHENTICATED
actor_role: VISITOR | BUYER | EXHIBITOR | OPERATOR | ADMIN
```

예를 들어 휴대전화 인증을 마친 바이어는 `PHONE_VERIFIED + BUYER`다. 참가업체 담당자는 `ACCOUNT_AUTHENTICATED + EXHIBITOR`다.

### 2.3 식별자

| 식별자 | 의미 |
|---|---|
| `tenant_id` | 주최사·운영조직 |
| `event_id` | 전시회 |
| `user_id` | 가명 내부 사용자 |
| `identity_id` | 식별정보 보관소 레코드 |
| `guest_session_id` | 익명 브라우저 세션 |
| `visit_session_id` | 행사 방문 단위 |
| `profile_id` | 추천 프로파일 |
| `recommendation_session_id` | 추천 실행·버전 단위 |
| `match_result_id` | 개별 추천 결과 |
| `interaction_event_id` | 행동 이벤트 레코드 |
| `exhibitor_id`, `product_id`, `booth_id` | 전시 객체 |
| `meeting_id` | 상담 요청·일정 |

행사를 뜻하는 `event_id`와 행동 이벤트의 ID를 혼용하지 않는다.

### 2.4 시간·문자열·금액

- JSON은 UTF-8과 `snake_case`를 사용한다.
- 서버는 시간을 UTC로 저장·응답하고, UI는 `Asia/Seoul`로 표시한다.
- 일정 입력은 ISO 8601 offset 포함 값을 허용하지만 저장 전 UTC로 정규화한다.
- 날짜만 의미하는 행사일·후속연락일은 `YYYY-MM-DD`로 저장한다.
- 금액은 정수 최소 통화단위와 ISO 4217 통화코드로 표현한다.
- 거리·시간은 `meters`, `minutes`처럼 단위를 필드명에 포함한다.

## 3. 전체 시스템 경계

```text
[모바일웹 · 키오스크 · 파트너 · 운영자]
                    │
                    ▼
              [API Gateway/BFF]
                    │
     ┌──────────────┼───────────────┐
     ▼              ▼               ▼
[인증·동의]    [프로파일·전시]    [상담·일정·행동]
     │              │               │
     └──────────────┼───────────────┘
                    ▼
        [Recommendation Orchestrator]
                    │
       ┌────────────┼─────────────┐
       ▼            ▼             ▼
   후보검색      규칙·점수      AI 구조화·설명
                    │
                    ▼
 [식별정보 DB · 업무 DB · 이벤트 저장소 · 벡터 인덱스]
```

브라우저는 내부 추천·AI 서비스에 직접 접근하지 않는다. 모든 내부 서비스 호출은 BFF 또는 오케스트레이터를 통과한다.

## 4. API 공통 계약

### 4.1 기본 규격

| 항목 | 기준 |
|---|---|
| 통신 | HTTPS |
| 외부 API | REST JSON |
| 기본 경로 | `/api/v1` |
| 인증 | Secure HttpOnly 세션 쿠키 우선, 비브라우저는 Bearer Token |
| 익명 세션 | Secure HttpOnly guest cookie 우선 |
| 페이지 처리 | 불투명 Cursor Pagination |
| 요청 추적 | `X-Request-ID` |
| 중복 방지 | 변경 요청의 `Idempotency-Key` |
| 동시 수정 | `ETag` / `If-Match` 또는 명시적 `version` |
| 캐시 검증 | `ETag`, `Last-Modified` |

브라우저가 같은 출처의 BFF를 사용할 때 토큰을 JavaScript 접근 가능한 저장소에 보관하지 않는다. `Authorization`과 익명 세션 헤더는 동시에 보내지 않는다. 서버는 인증 세션을 우선하며 주체가 충돌하면 `401 PRINCIPAL_CONFLICT`를 반환한다.

### 4.2 요청 헤더

```http
X-Request-ID: 6bd74d93-06df-4dc9-8607-9f0d27f4de63
Idempotency-Key: aaef0fd5-1239-4244-a457-ce91ab56ec6e
Accept-Language: ko-KR
If-Match: "profile-v4"
```

- `Idempotency-Key`는 POST 등 외부 효과가 있는 요청에만 사용한다.
- 같은 키·같은 주체·같은 경로·같은 요청 본문은 최초 결과를 재사용한다.
- 같은 키로 다른 본문을 보내면 `409 IDEMPOTENCY_KEY_REUSED`를 반환한다.
- 서버는 클라이언트 요청 ID를 검증하고, 누락 시 새 ID를 생성한다.

### 4.3 성공 응답

```json
{
  "success": true,
  "data": {},
  "meta": {
    "request_id": "req_123456",
    "server_time": "2026-10-09T05:30:00Z"
  }
}
```

목록 응답:

```json
{
  "success": true,
  "data": {
    "items": [],
    "next_cursor": "opaque-or-null"
  },
  "meta": {
    "request_id": "req_123456",
    "server_time": "2026-10-09T05:30:00Z"
  }
}
```

### 4.4 오류 응답

```json
{
  "success": false,
  "error": {
    "code": "PROFILE_INCOMPLETE",
    "message": "추천에 필요한 방문 목적을 선택해 주세요.",
    "field_errors": [
      {"field": "visit_goals", "reason": "required"}
    ],
    "retryable": false,
    "retry_after_seconds": null
  },
  "meta": {
    "request_id": "req_123456",
    "server_time": "2026-10-09T05:30:00Z"
  }
}
```

운영 로그에는 내부 예외와 스택을 기록할 수 있지만 외부 응답에는 DB 키, 프롬프트, 공급자 오류 원문, 개인정보를 노출하지 않는다.

## 5. 권한·스코프

| 기능 | 필요 상태·역할 |
|---|---|
| 일반 탐색·지도 | GUEST + VISITOR |
| 개인화 추천 | 연령확인 + 개인화 선택 + 최소 프로파일 |
| 로컬 저장 | GUEST 가능 |
| 서버 저장·일정 | PHONE_VERIFIED |
| 상담 요청 | PHONE_VERIFIED + BUYER |
| 상담 수락·결과 | ACCOUNT_AUTHENTICATED + EXHIBITOR + 해당 업체 소속 |
| 운영정보 변경 | OPERATOR + 이벤트 스코프 |
| 권한·정책·감사 | ADMIN + 별도 민감 작업 권한 |

모든 리소스 조회는 역할뿐 아니라 `tenant_id`, `event_id`, 소유권 또는 업체 소속을 검사한다.

## 6. 화면·API 매핑

| 화면 | 주요 외부 API |
|---|---|
| U-01 시작 | `POST /sessions` |
| U-02 유형 | `PATCH /profiles/me/user-type` |
| U-03 자격·동의 | `PUT /consents/me` |
| U-04 목적 | `PUT /profiles/me/goals` |
| U-05 취향 | `PUT /profiles/me/consumer-preferences` |
| U-06 바이어 조건 | `PUT /profiles/me/buyer-needs` |
| U-07 방문계획 | `PUT /visit-sessions/current/plan` |
| U-08 홈 | `GET /home` |
| U-09 추천목록 | `GET /recommendation-sessions/{id}/items` |
| U-10 부스 | `GET /booths/{id}` |
| U-11 제품 | `GET /products/{id}` |
| U-13 경로 | `POST /routes`, `POST /routes/{id}/recalculate` |
| U-14~15 상담 | `/meetings` |
| U-16 체크인 | `POST /check-ins` |
| U-17 피드백 | `POST /feedback` |
| U-18 일정 | `GET /schedule` |
| U-19 저장 | `/favorites` |
| U-20 조건 수정 | `PATCH /profiles/me` |
| U-22 동의·권리 | `/consents/me`, `/privacy-requests` |
| E-01~04 파트너 | `/partner/*` |

프론트는 다른 사용자의 `profile_id`를 직접 지정하지 않는다. `/me` 또는 현재 세션 경로를 사용하고 서버가 인증 주체에 속한 프로파일을 해석한다.

## 7. 세션·인증·동의 API

### 7.1 익명 세션 생성

```http
POST /api/v1/sessions
```

```json
{
  "event_id": "evt_backju_2026",
  "entry_channel": "QR",
  "entry_code": "GATE_A",
  "device_type": "MOBILE_WEB",
  "language": "ko-KR"
}
```

```json
{
  "success": true,
  "data": {
    "guest_session_id": "gs_001",
    "visit_session_id": "vs_001",
    "profile_id": "pf_001",
    "event_status": "OPEN",
    "service_available": true,
    "minimum_age": 19,
    "expires_at": "2026-10-10T05:00:00Z"
  },
  "meta": {"request_id": "req_1", "server_time": "2026-10-09T05:00:00Z"}
}
```

브라우저에는 서명된 guest cookie를 설정한다. 응답 JSON에 재사용 가능한 원문 세션 토큰을 노출하지 않는 방식을 우선한다.

### 7.2 휴대전화 인증

```text
POST /auth/phone/challenges
POST /auth/phone/challenges/{challenge_id}/verify
POST /sessions/current/merge
```

- OTP 요청·검증은 IP, 전화번호 HMAC, 장치 단위로 속도 제한한다.
- 성공 시 익명 저장·프로파일·일정을 사용자의 서버 계정으로 합칠지 확인한다.
- 이미 다른 계정에 연결된 데이터를 자동 병합하지 않는다.

### 7.3 사용자 유형

```http
PATCH /api/v1/profiles/me/user-type
If-Match: "profile-v1"
```

```json
{"user_type": "GENERAL_VISITOR"}
```

허용값은 `GENERAL_VISITOR`, `BUYER`다. 변경 시 질문 분기와 추천 세션 무효화 여부를 반환한다.

### 7.4 자격·동의

```http
PUT /api/v1/consents/me
```

```json
{
  "consents": [
    {
      "purpose": "AGE_CONFIRMATION",
      "document_version": "2026.1",
      "accepted": true
    },
    {
      "purpose": "PERSONALIZED_RECOMMENDATION",
      "document_version": "2026.1",
      "accepted": true
    },
    {
      "purpose": "BEHAVIOR_PERSONALIZATION",
      "document_version": "2026.1",
      "accepted": false
    },
    {
      "purpose": "MARKETING_MESSAGES",
      "document_version": "2026.1",
      "accepted": false
    }
  ]
}
```

- 연령확인은 마케팅 동의가 아니라 서비스 적격 확인이다.
- 개인화 미선택자는 일반 탐색을 이용한다.
- 행동 개인화 미선택자는 운영상 필요한 최소 이벤트만 비개인 분석 또는 보안 목적으로 처리하고 추천 학습에 사용하지 않는다.
- 연락처 공유는 상담 요청별로 별도 기록한다.
- 동의 변경은 현재 상태와 불변 이력을 모두 남긴다.

## 8. 프로파일 API

### 8.1 방문 목적

```http
PUT /api/v1/profiles/me/goals
If-Match: "profile-v2"
```

```json
{
  "visit_goals": [
    {"code": "TASTING", "priority": 1},
    {"code": "PURCHASE", "priority": 2},
    {"code": "GIFT_SEARCH", "priority": 3}
  ],
  "free_text_goal": "부모님 선물용 전통주를 찾고 있습니다."
}
```

응답은 저장된 사용자 선택과 AI 보조 추출을 분리한다.

```json
{
  "profile_version": 3,
  "selected_goals": [],
  "suggested_attributes": [
    {
      "attribute": "usage",
      "value": "GIFT",
      "confidence": 0.94,
      "evidence_text": "부모님 선물용"
    }
  ],
  "confirmation_required": true
}
```

AI 추출은 사용자의 명시적 선택을 덮어쓰지 않는다. 신뢰도 기준을 통과해도 사용자가 확인하지 않은 값은 하드 필터로 사용하지 않는다.

### 8.2 관람객 취향

```http
PUT /api/v1/profiles/me/consumer-preferences
```

```json
{
  "product_categories": ["DISTILLED_LIQUOR", "YAKJU_CHEONGJU"],
  "taste_preferences": ["DRY", "AROMATIC", "SMOOTH"],
  "alcohol_percentage": {"min": 10, "max": 30},
  "price": {"min_amount": 20000, "max_amount": 50000, "currency": "KRW"},
  "purchase_intent": "LIKELY",
  "preferred_activities": ["TASTING", "ON_SITE_PURCHASE"]
}
```

`잘 모르겠음`은 빈 배열과 다르다. `preference_certainty: UNKNOWN`처럼 명시해 질문 누락과 구분한다.

### 8.3 바이어 조건

```http
PUT /api/v1/profiles/me/buyer-needs
```

```json
{
  "organization_type": "BOTTLE_SHOP",
  "distribution_channels": ["OFFLINE_RETAIL", "ONLINE_MALL"],
  "desired_categories": ["DISTILLED_LIQUOR"],
  "target_price": {
    "min_amount": 20000,
    "max_amount": 50000,
    "basis": "RETAIL_PRICE",
    "currency": "KRW"
  },
  "expected_order_volume": {
    "type": "REGULAR_SMALL",
    "monthly_units_min": 100,
    "monthly_units_max": 500
  },
  "supply_regions": ["SEOUL", "GYEONGGI"],
  "business_interests": ["DISTRIBUTION", "EXCLUSIVE_SALES"],
  "decision_timeline": "WITHIN_3_MONTHS"
}
```

상담 요청 전 소속기관, 담당업무, 업무용 이메일, 연락처를 확인한다. 이 정보는 추천 점수용 프로파일과 식별정보 보관소에 목적별로 분리한다.

### 8.4 방문 계획

```http
PUT /api/v1/visit-sessions/current/plan
```

```json
{
  "visit_date": "2026-10-09",
  "entry_time": "2026-10-09T14:00:00+09:00",
  "available_minutes": 90,
  "route_preference": "LOW_CONGESTION",
  "walking_constraints": {
    "minimize_distance": true,
    "accessible_route": false
  },
  "meeting_available_slots": [
    {
      "start": "2026-10-09T15:00:00+09:00",
      "end": "2026-10-09T16:30:00+09:00"
    }
  ]
}
```

## 9. 추천 API

### 9.1 추천 생성

```http
POST /api/v1/recommendations
Idempotency-Key: 1ca4bbca-7acf-42e5-82e2-d8a07d2461ef
```

```json
{
  "recommendation_type": "MIXED",
  "context": {
    "current_zone": "ENTRANCE_A",
    "remaining_minutes": 90,
    "exclude_visited": true,
    "include_meetings": true
  },
  "limit": 10
}
```

서버는 현재 인증·익명 세션에서 `profile_id`, `visit_session_id`, `event_id`를 파생한다. 클라이언트가 다른 프로파일 ID를 지정할 수 없다. `current_time`은 서버 시각을 기준으로 하고 클라이언트 값은 진단용으로만 받을 수 있다.

`recommendation_type`은 `BOOTH`, `PRODUCT`, `EXHIBITOR`, `PROGRAM`, `MIXED` 중 하나다. 상담과 경로는 추천 항목의 `recommended_action`을 실행해 생성하며 추천 대상 유형으로 사용하지 않는다.

처리 순서:

1. 주체·세션·이벤트 확인
2. 연령·개인화 선택·프로파일 완성도 확인
3. 승인된 업체·제품 후보 검색
4. 운영중단·품절·상담마감과 사용자 절대조건 필터
5. 관람객 또는 바이어 점수
6. 위치·혼잡·남은시간·상담 가능성 재정렬
7. 다양성·노출 상한·수용량 보정
8. 허용 근거코드 결정
9. AI 또는 템플릿 추천 이유 생성
10. 입력 스냅샷과 버전 포함 결과 저장

```json
{
  "recommendation_session_id": "rs_001",
  "generated_at": "2026-10-09T05:10:02Z",
  "expires_at": "2026-10-09T05:20:02Z",
  "profile_version": 4,
  "ranking_version": "match-v1.3",
  "explanation_version": "explain-v1.1",
  "policy_version": "policy-2026.10.1",
  "items": [
    {
      "match_result_id": "mr_001",
      "rank": 1,
      "object_type": "BOOTH",
      "object_id": "booth_012",
      "exhibitor_id": "ex_031",
      "match_level": "VERY_HIGH",
      "reasons": [
        {
          "code": "TASTE_MATCH",
          "text": "선호한 드라이한 증류주 조건과 일치합니다.",
          "evidence_refs": ["product:p_14:taste_attributes"]
        },
        {
          "code": "PRICE_MATCH",
          "text": "희망 가격대에서 현장 구매할 수 있는 제품이 있습니다.",
          "evidence_refs": ["product:p_14:on_site_price"]
        }
      ],
      "distance_meters": 120,
      "estimated_walk_minutes": 3,
      "estimated_wait_minutes": 5,
      "status_observed_at": "2026-10-09T05:09:00Z",
      "availability": {
        "open": true,
        "tasting": true,
        "purchase": true,
        "meeting": true
      },
      "recommended_action": "VISIT_NOW"
    }
  ]
}
```

내부 점수는 외부 사용자 API에 기본 제공하지 않는다. 운영자 권한의 설명 API에서만 원점수·보정값·정책 근거를 조회한다.

### 9.2 추천 실행 저장

`recommendation_session`은 다음을 보존한다.

- 프로파일·방문 세션과 프로파일 버전
- 랭킹·설명·정책·택소노미 버전
- 위치·시간·혼잡·운영상태 스냅샷 ID
- 전체 후보, 필터 통과, 최종 노출 수
- 생성·만료시각
- 실패·대체전략 여부

`match_result`는 내부 원점수, 정규화 점수, 순위, 근거코드, 필터 결과, 다양성·현장 보정값을 저장한다. 과거 결과를 덮어쓰지 않는다.

### 9.3 홈

```http
GET /api/v1/home
```

`GET /home`은 CR-011에 따라 계산과 분리된 전달 전용 조회다. 서버 세션에서 파생한
tenant·event·profile에 속한 최신 `ACTIVE recommendation_session`과 저장된 결과를 반환하며,
매칭 오케스트레이터·LLM·외부 AI 공급자를 호출하지 않는다. 만료 결과는 `stale=true`로
표시할 수 있지만 `INVALIDATED` 결과는 반환하지 않는다.

추천 생성과 재계산은 `POST /recommendations` 또는 동일한 명령 계약을 사용하는 승인된
배치 Worker가 담당한다. 전달 가능한 Snapshot이 없으면 `404 RECOMMENDATION_NOT_READY`를
반환하며 조회 요청이 암묵적으로 계산이나 조건 완화를 시작하지 않는다.

### 9.4 추천 목록

```http
GET /api/v1/recommendation-sessions/{id}/items?type=BOOTH&sort=RECOMMENDED&cursor=...&limit=20
```

세션 소유권을 검사한다. 만료된 추천은 조회할 수 있으나 `stale: true`와 새 추천 액션을 반환한다.

## 10. 전시정보 API

### 10.1 부스 상세

```http
GET /api/v1/booths/{booth_id}?match_result_id=mr_001
```

`match_result_id`는 선택이며 소유권이 확인될 때만 개인화 이유를 포함한다. 일반 조회에는 공개 업체·부스 정보만 제공한다.

```json
{
  "booth_id": "booth_012",
  "booth_number": "B-12",
  "exhibitor": {
    "exhibitor_id": "ex_031",
    "name": "A양조장",
    "summary": "지역 쌀을 활용한 증류주 생산"
  },
  "location": {"zone": "B", "x": 320, "y": 140},
  "operating_status": "OPEN",
  "status_observed_at": "2026-10-09T05:09:00Z",
  "estimated_wait_minutes": 5,
  "services": {"tasting": true, "purchase": true, "meeting": true},
  "products": [],
  "recommendation_context": {
    "match_result_id": "mr_001",
    "reasons": []
  }
}
```

### 10.2 제품 상세

```http
GET /api/v1/products/{product_id}
```

공개 응답에는 제품명, 업체, 주종, 원료, 도수, 맛, 공개 가격, 현장 시음·구매·재고, 승인상태를 포함할 수 있다. MOQ, 출고가, 생산량 등 민감한 B2B 조건은 인증된 바이어에게도 업체 공개정책과 상담 단계에 따라 별도 `buyer_terms` 리소스로 제공한다.

## 11. 저장·경로 API

### 11.1 관심 저장

```text
POST   /favorites
DELETE /favorites/{favorite_id}
GET    /favorites?object_type=BOOTH&cursor=...
```

```json
{
  "object_type": "BOOTH",
  "object_id": "booth_012",
  "source": "RECOMMENDATION",
  "match_result_id": "mr_001"
}
```

익명 저장은 로컬 우선이며 서버 저장 요청 시 현재 guest session에 귀속한다. 인증 병합 시 충돌 규칙을 적용한다.

### 11.2 경로 생성

```http
POST /api/v1/routes
```

```json
{
  "start_location": {"type": "ZONE", "id": "ENTRANCE_A"},
  "targets": [
    {
      "object_type": "BOOTH",
      "object_id": "booth_012",
      "priority": 1,
      "expected_duration_minutes": 15
    },
    {
      "object_type": "MEETING",
      "object_id": "mt_001"
    }
  ],
  "constraints": {
    "available_minutes": 90,
    "avoid_congestion": true,
    "minimize_walking": true,
    "accessible_route": false
  }
}
```

상담의 확정시간은 서버의 일정 데이터에서 읽으며 클라이언트가 `fixed_time`을 덮어쓰지 못한다.

재계산 조건:

- 현재 구역·남은시간 변경
- 방문 완료·건너뛰기
- 상담 확정·변경·취소
- 부스 운영중단 또는 혼잡 임계 초과

## 12. 상담 API

### 12.1 상태 모델

```text
DRAFT
  → REQUESTED
  → CONFIRMED → COMPLETED
  → COUNTER_PROPOSED → CONFIRMED
  → REJECTED
  → CANCELLED_BY_BUYER
  → CANCELLED_BY_EXHIBITOR
  → NO_SHOW
```

`VIEWED`는 상담 상태가 아니라 `viewed_at` 메타데이터다. `FOLLOW_UP`은 상담 후속조치 상태이며 상담 예약 상태와 분리한다.

### 12.2 가능시간

```http
GET /api/v1/exhibitors/{exhibitor_id}/availability?date=2026-10-09&topic=DISTRIBUTION
```

응답 슬롯에는 `slot_id`, 시작·종료, 정원, 최신 버전을 포함한다. 상담 요청 시 `slot_id`를 보내고 서버가 다시 유효성을 검사한다.

### 12.3 상담 요청

```http
POST /api/v1/meetings
Idempotency-Key: 6b7426d4-7655-46cf-8fe3-b22de4aa61c1
```

```json
{
  "exhibitor_id": "ex_031",
  "topic": "DISTRIBUTION",
  "requested_slot_ids": ["slot_1500", "slot_1600"],
  "message": "서울 지역 바틀샵 입점 조건을 상담하고 싶습니다.",
  "contact_share": {
    "accepted": true,
    "document_version": "meeting-share-2026.1",
    "fields": ["NAME", "PHONE", "BUSINESS_EMAIL"]
  },
  "match_result_id": "mr_001"
}
```

서버는 바이어 주체에서 프로파일을 파생한다. 요청 전 바이어의 기존 일정, 업체 담당자 일정, 부스 운영시간, 프로그램, 이동시간을 검사한다.

연락처 공유 동의는 요청 시 기록하지만 실제 공개는 상담 확정 후다.

### 12.4 업체 응답

```http
POST /api/v1/partner/meetings/{meeting_id}/decision
```

```json
{"action": "ACCEPT", "slot_id": "slot_1500", "version": 2}
```

또는:

```json
{"action": "COUNTER_PROPOSE", "slot_id": "slot_1530", "version": 2}
```

상태 전이는 DB 트랜잭션에서 일정 점유와 함께 원자적으로 수행한다. 낙관적 잠금 충돌은 `409 MEETING_VERSION_CONFLICT`로 반환한다.

## 13. QR 체크인·피드백 API

### 13.1 체크인

```http
POST /api/v1/check-ins
Idempotency-Key: 4b18b8b5-91d7-4e49-817c-85434f81e7ca
```

```json
{
  "qr_token": "signed-opaque-token",
  "activities": ["TASTING", "PURCHASE"],
  "match_result_id": "mr_001",
  "client_event_id": "client_evt_001",
  "occurred_at": "2026-10-09T05:31:12Z"
}
```

서버는 QR 서명·행사·부스·만료·운영시간·세션을 검사한 뒤 체크인을 원자적으로 저장한다. 미리보기용 검증 API를 제공하더라도 등록 시 모든 조건을 다시 검사한다.

중복 기준은 `event_id + booth_id + visit_session_id + dedupe_window`로 정의한다. 중복이면 오류만 반환하지 않고 기존 체크인 ID와 시각을 제공한다.

### 13.2 피드백

```http
POST /api/v1/feedback
```

```json
{
  "object_type": "BOOTH",
  "object_id": "booth_012",
  "match_result_id": "mr_001",
  "rating": "VERY_RELEVANT",
  "positive_reasons": ["TASTE", "PRICE"],
  "negative_reasons": [],
  "comment": null,
  "client_event_id": "client_evt_002"
}
```

피드백 원인을 사용자 선호와 현장 상황으로 분리한다.

| 원인 | 처리 |
|---|---|
| 맛·제품 불일치 | 선호 가설 검토·보정 |
| 가격 불일치 | 가격 범위 재확인 |
| 혼잡·대기 | 상황 점수에 반영, 취향에는 미반영 |
| 품절·운영종료 | 운영 품질 지표, 취향에는 미반영 |
| 추천 설명 오류 | 데이터·설명 품질 검수 큐 |

온라인 행동 하나로 영구 가중치를 즉시 변경하지 않는다. 반복 신호와 사용자의 명시적 조건 수정을 우선한다.

## 14. 프로파일 갱신

```http
PATCH /api/v1/profiles/me
If-Match: "profile-v4"
```

```json
{
  "taste_preferences": {"add": ["SWEET"], "remove": ["DRY"]},
  "price": {"min_amount": 30000, "max_amount": 80000, "currency": "KRW"}
}
```

남은 체류시간은 프로파일이 아니라 `visit_session`에 수정한다.

```json
{
  "profile_version": 5,
  "recommendation_refresh_required": true,
  "invalidated_recommendation_session_ids": ["rs_001"]
}
```

## 15. 참가업체 포털 API

```text
GET   /partner/dashboard
GET   /partner/meetings?status=REQUESTED&cursor=...
GET   /partner/meetings/{meeting_id}/buyer-summary
POST  /partner/meetings/{meeting_id}/decision
POST  /partner/meetings/{meeting_id}/outcome
PATCH /partner/booths/{booth_id}/status
```

바이어 요약 제공:

- 소속 유형·업무, 유통채널
- 희망 제품군·가격 기준·예상 규모·공급지역
- 상담주제
- 확정 후 공유에 동의한 연락처

미제공:

- 전체 방문·검색 이력
- 다른 업체 상담내역
- 상세 행동로그
- 동의하지 않은 식별정보
- 내부 추천 점수·다른 업체와의 상대 순위

상담결과 메모는 추천 모델 학습 입력에 자동 사용하지 않는다. 별도 검수·비식별 처리 없이 LLM 프롬프트나 분석 이벤트로 전달하지 않는다.

## 16. 행동 이벤트 API

### 16.1 수집

```http
POST /api/v1/interactions/batch
Idempotency-Key: batch-uuid
```

```json
{
  "events": [
    {
      "client_event_id": "ce_001",
      "event_type": "RECOMMENDATION_OPENED",
      "object_type": "BOOTH",
      "object_id": "booth_012",
      "recommendation_session_id": "rs_001",
      "match_result_id": "mr_001",
      "rank_at_event": 1,
      "screen": "HOME",
      "zone": "ENTRANCE_A",
      "occurred_at": "2026-10-09T05:15:00Z",
      "consent_snapshot_id": "cs_004"
    }
  ]
}
```

서버가 `user_id`, `guest_session_id`, `visit_session_id`, `event_id`를 세션에서 추가한다. 클라이언트가 보낸 주체 ID를 신뢰하지 않는다.

### 16.2 표준 이름

```text
SERVICE_STARTED
USER_TYPE_SELECTED
CONSENT_CHOICE_RECORDED
PROFILE_QUESTION_VIEWED
PROFILE_ANSWER_SELECTED
PROFILE_QUESTION_SKIPPED
MINIMUM_PROFILE_COMPLETED
RECOMMENDATION_IMPRESSION
RECOMMENDATION_OPENED
RECOMMENDATION_SAVED
RECOMMENDATION_DISMISSED
ROUTE_ITEM_ADDED
ROUTE_STARTED
BOOTH_CHECKED_IN
VISIT_OUTCOME_SELECTED
FEEDBACK_SUBMITTED
MEETING_REQUEST_STARTED
MEETING_REQUEST_SUBMITTED
MEETING_REQUEST_DECIDED
MEETING_COMPLETED
```

직접 식별정보, 자유메모 원문, OTP, 토큰, 전체 URL query string을 이벤트 속성에 넣지 않는다.

## 17. AI 내부 인터페이스

AI API는 외부에 노출하지 않는다. 오케스트레이터가 승인된 데이터와 최소 속성만 전달한다.

### 17.1 자연어 의도 구조화

```json
{
  "request_id": "req_123",
  "schema_version": "intent-v1",
  "locale": "ko-KR",
  "text": "부모님 선물용으로 5만원 이하의 드라이한 술을 찾고 있어요.",
  "allowed_taxonomy": {
    "goals": ["GIFT_SEARCH", "PURCHASE"],
    "taste": ["DRY", "SWEET", "SMOOTH"]
  }
}
```

```json
{
  "schema_version": "intent-v1",
  "attributes": [
    {
      "name": "usage",
      "value": "GIFT",
      "confidence": 0.96,
      "evidence_text": "부모님 선물용"
    },
    {
      "name": "price_max",
      "value": 50000,
      "confidence": 0.99,
      "evidence_text": "5만원 이하"
    }
  ],
  "unknown_terms": [],
  "safety_flags": []
}
```

출력은 JSON Schema로 검증한다. 허용 택소노미 밖 값은 저장하지 않고 `unknown_terms`로 보낸다.

### 17.2 업체·제품 속성 추출

- 입력 텍스트는 신뢰할 수 없는 데이터로 취급한다.
- 소개문 안의 명령은 실행하거나 시스템 지시로 해석하지 않는다.
- 추출값은 원문 근거 위치와 confidence를 가진다.
- 업체 또는 운영자 승인 전 공개·하드 필터·추천 이유 근거로 사용하지 않는다.

### 17.3 추천 이유 생성

입력:

```json
{
  "schema_version": "explanation-v1",
  "locale": "ko-KR",
  "allowed_reason_codes": ["TASTE_MATCH", "PRICE_MATCH", "LOW_WAIT"],
  "facts": [
    {"ref": "user:preference:taste", "name": "taste", "value": ["DRY"]},
    {"ref": "product:p14:taste", "name": "taste", "value": ["DRY", "AROMATIC"]},
    {"ref": "product:p14:price", "name": "price", "value": 45000},
    {"ref": "context:wait", "name": "wait_minutes", "value": 5}
  ],
  "selected_matches": [
    {
      "reason_code": "TASTE_MATCH",
      "evidence_refs": ["user:preference:taste", "product:p14:taste"]
    },
    {
      "reason_code": "PRICE_MATCH",
      "evidence_refs": ["product:p14:price"]
    }
  ]
}
```

출력:

```json
{
  "schema_version": "explanation-v1",
  "reasons": [
    {
      "code": "TASTE_MATCH",
      "text": "선호하신 드라이한 맛과 일치합니다.",
      "evidence_refs": ["user:preference:taste", "product:p14:taste"]
    }
  ]
}
```

검증:

- 입력에 없는 사실·숫자·혜택 거부
- 인구통계 추론 이유 거부
- 광고·후원 노출을 개인화 근거로 위장 금지
- 내부 점수·비공개 거래조건 금지
- evidence reference가 없는 문장 제거
- 금칙어·길이·한국어 품질 검사

설명 서비스가 시간초과·스키마 오류를 내면 reason code별 검수된 템플릿을 사용한다. 추천 순위 생성은 실패하지 않는다.

### 17.4 버전·관측

모든 AI 호출에 공급자와 독립적인 `schema_version`, 내부 `explanation_version`, 템플릿 버전을 기록한다. 원문 프롬프트와 응답 보관은 개인정보·보유정책을 적용하며 운영 로그에 무제한 저장하지 않는다.

## 18. 원천 데이터 연계

### 18.1 배치 import

```text
POST /admin/imports/visitors
POST /admin/imports/exhibitors
POST /admin/imports/products
GET  /admin/imports/{import_id}
GET  /admin/imports/{import_id}/errors
```

- 파일 전체 checksum, 행별 원천 ID, 원천 수정시각을 기록한다.
- 행별 멱등 upsert와 오류 격리를 적용한다.
- import 원본 파일은 접근통제·악성파일 검사·보유기간을 적용한다.
- 원천값, 정규화값, 승인값을 구분한다.

### 18.2 웹훅

```http
X-Webhook-ID: wh_001
X-Webhook-Timestamp: 1785480000
X-Webhook-Signature: v1=hex-hmac
```

- HMAC 서명과 timestamp 허용범위를 검사한다.
- `webhook_id`로 중복을 제거한다.
- 2xx만 성공으로 간주하고 지수 백오프 재시도·실패보관함을 운영한다.
- 웹훅 비밀키는 이벤트·연동처별로 분리하고 순환 가능해야 한다.

## 19. 오류 코드

| HTTP | 코드 | UI 처리 |
|---|---|---|
| 400 | `VALIDATION_FAILED` | 필드 오류 표시 |
| 401 | `AUTH_REQUIRED` | 인증 시작 |
| 401 | `SESSION_EXPIRED` | 익명 세션 복구·재시작 |
| 403 | `AGE_CONFIRMATION_REQUIRED` | 연령확인 이동 |
| 403 | `PERSONALIZATION_DISABLED` | 일반 탐색 제공 |
| 403 | `RESOURCE_FORBIDDEN` | 접근 불가 안내 |
| 409 | `PROFILE_VERSION_CONFLICT` | 최신값 재조회·병합 |
| 409 | `MEETING_CONFLICT` | 대체시간 제공 |
| 409 | `MEETING_VERSION_CONFLICT` | 최신상태 재조회 |
| 409 | `DUPLICATE_CHECKIN` | 기존 방문 표시 |
| 409 | `IDEMPOTENCY_KEY_REUSED` | 새 키 생성 전 사용자 확인 |
| 422 | `PROFILE_INCOMPLETE` | 누락 질문 이동 |
| 422 | `NO_CANDIDATE` | 조건 완화·직접 탐색 |
| 422 | `INVALID_QR` | 재스캔·코드입력 |
| 423 | `BOOTH_CLOSED` | 대체 부스 추천 |
| 423 | `PRODUCT_SOLD_OUT` | 유사제품 추천 |
| 429 | `RATE_LIMITED` | `Retry-After` 후 재시도 |
| 503 | `SERVICE_TEMPORARILY_UNAVAILABLE` | 캐시 결과·대체 탐색 |

`CONSENT_REQUIRED`라는 단일 오류로 모든 목적을 묶지 않는다. 필요한 목적과 일반 탐색 가능 여부를 구분한다.

## 20. 성능·가용성

| 기능 | 서버 P95 목표 |
|---|---|
| 기본정보 조회 | 500ms 이내 |
| 프로파일 저장 | 800ms 이내 |
| 최초 추천 | 2.5초 이내 |
| 현장 재정렬 | 1초 이내 |
| 상담 요청 | 1초 이내 |
| QR 체크인 | 800ms 이내 |
| 파트너 대시보드 | 1.5초 이내 |

- AI 설명은 제한시간 내 완료되지 않으면 템플릿으로 대체한다.
- 부스·제품 기본정보와 최근 추천을 브라우저에 제한적으로 캐시한다.
- 개인정보·동의문 원문·토큰은 서비스 워커 캐시에 저장하지 않는다.
- 체크인·피드백은 오프라인 큐 재전송을 허용한다.
- 상담 요청은 장시간 오프라인 후 재전송 전 시간·업체·공유정보를 재확인한다.
- 추천엔진 장애 시 승인된 카테고리·목적 기반 탐색 결과를 명시적으로 `기본 탐색`으로 제공한다.

## 21. 보안·개인정보

- 식별정보 암호화와 검색용 HMAC을 분리한다.
- 키는 애플리케이션 DB와 분리된 키 관리 서비스에서 관리한다.
- 브라우저 토큰은 HttpOnly, Secure, SameSite 정책을 적용한다.
- CSRF, XSS, 콘텐츠 보안정책, 파일 업로드 검사를 적용한다.
- 파트너·운영자에는 MFA와 세션 시간 제한을 적용한다.
- 역할·테넌트·이벤트·리소스 소유권을 매 요청 검사한다.
- 참가업체의 바이어 연락처 열람은 상담 확정·동의·권한을 모두 검사한다.
- 개인정보 다운로드는 권한, 목적, 행위자, 대상, 시각을 기록한다.
- 추천·AI 입력에는 이름, 전화번호, 이메일을 포함하지 않는다.
- 동의 철회 후 신규 개인화 사용을 즉시 중단하고 비동기 삭제 작업 상태를 제공한다.
- 보유기간은 예시 숫자로 고정하지 않고 확정된 처리목적·법적 근거·동의 버전에 연결한다.

## 22. 관측성·감사

모든 외부 요청과 내부 추천 실행은 다음 상관관계를 유지한다.

```text
request_id
  → recommendation_session_id
  → match_result_id
  → interaction_event_id
  → check_in_id / meeting_id / feedback_id
```

운영 메트릭:

- API 지연·오류·속도 제한
- 추천 후보수·필터수·결과수·대체전략 사용률
- AI 스키마 오류·시간초과·템플릿 대체율
- 데이터 최신성·업체 프로파일 완성도
- 추천 노출 편중·업체별 수용량
- 체크인 중복·상담 충돌·오프라인 재전송 실패
- 권한 거부·개인정보 열람·다운로드·삭제 처리

감사로그는 일반 분석 이벤트와 분리하며 수정·삭제가 제한된 저장소에 보관한다.

## 23. 완료 검수 기준

### 프로파일

- 관람객·바이어 분기가 정상 작동한다.
- 최소정보 누락은 구체적 필드와 함께 차단한다.
- 선택정보가 없어도 구조화 기본 추천이 가능하다.
- AI 보조 추출과 사용자 확정값이 분리된다.
- 동시 수정 충돌에서 데이터가 조용히 덮어써지지 않는다.

### 추천

- 취소·운영종료·품절·절대조건 불일치가 제외된다.
- 모든 개인화 설명은 허용 reason code와 evidence reference를 가진다.
- 사용자 API에 내부 점수와 민감 거래조건이 노출되지 않는다.
- 동일 업체·주종 편중과 수용량을 통제한다.
- 당시 프로파일·정책·랭킹·설명·현장 스냅샷으로 결과를 재현할 수 있다.

### 방문·상담

- QR 위변조·중복·오프라인 재전송을 처리한다.
- 추천 결과와 저장·경로·방문·피드백이 연결된다.
- 상담 요청·결정은 멱등하고 일정 점유와 원자적이다.
- 확정·동의 전 연락처가 공개되지 않는다.
- 상담결과와 후속조치는 예약 상태와 분리된다.

### 보안·권리

- 다른 사용자의 profile·추천·일정을 ID 변경으로 조회할 수 없다.
- 다른 업체의 바이어·상담·리드를 조회할 수 없다.
- 분석 이벤트·캐시·AI 입력에 직접 식별정보가 없다.
- 동의 변경·연락처 열람·관리자 수정·다운로드가 감사로그에 남는다.
- 삭제·철회 요청의 접수·처리·실패 상태를 확인할 수 있다.

## 24. 개발 순서

1. 세션·인증·동의·권한 골격
2. 원천 import와 업체·제품·부스 승인 데이터
3. 관람객 프로파일과 규칙 추천
4. 추천 홈·상세·저장·행동 이벤트
5. QR 체크인·피드백·현장 재정렬
6. 지도·경로·일정 충돌
7. 바이어 프로파일·상담·파트너 포털
8. AI 자연어 구조화·임베딩·근거 설명
9. 운영 대시보드·감사·권리 요청

다음 산출물인 ERD와 테이블 정의서는 본 문서의 소유권, 상태, 버전, 동의, 멱등성 계약을 그대로 반영해야 한다.

## 25. 제15단계 슬레이트·노출 API 확장

`POST /api/v1/recommendations`의 선택 입력 `context.slate_preference`는 `BALANCED`, `ACCURACY_FIRST`, `DIVERSE`, `NEARBY_FIRST`, `NEW_DISCOVERY` 중 하나다. 응답 항목에는 내부 점수 대신 `slot_type`과 동일 업체의 관련 제품 공개 ID인 `related_object_ids`를 제공한다.

실제 카드 노출은 다음처럼 행동 배치 API로 보낸다.

```json
{
  "events": [{
    "client_event_id": "00000000-0000-0000-0000-000000000003",
    "event_type": "RECOMMENDATION_IMPRESSION",
    "recommendation_session_id": "00000000-0000-0000-0000-000000000001",
    "match_result_id": "00000000-0000-0000-0000-000000000002",
    "rank_at_event": 2,
    "visible_duration_ms": 1250,
    "occurred_at": "2026-10-09T05:15:00Z"
  }]
}
```

클라이언트는 응답 수신 시점이 아니라 카드가 뷰포트 노출 기준을 충족한 시점에 전송한다. `client_event_id`는 한 렌더링의 같은 카드를 재전송해도 동일하게 유지한다. 서버는 멱등키, 세션 소유권, `match_result_id`, 저장된 `slate_item.final_rank`를 검증하고 통과한 이벤트만 `interaction.recommendation_impression`에 append-only로 투영한다. 광고·협찬은 이 개인 추천 이벤트와 별도 콘텐츠 유형·슬롯·성과지표를 사용한다.
