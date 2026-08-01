# 프론트엔드-백엔드-AI 인터페이스 명세서

## 1. 목적 및 범위

### 1.1 목적

사용자 화면 IA를 기준으로 다음 요소를 일관된 인터페이스로 정의한다.

- 모바일웹 사용자 화면과 백엔드 API 연계
- 일반 관람객·바이어·참가업체 사용자 구분
- 사용자 프로파일·참가업체·제품·부스 데이터 관리
- AI 추천 생성·재정렬·추천 이유 제공
- 부스 방문·QR 체크인·상담·피드백 데이터 수집
- 개인정보·동의·감사로그 관리
- 행사 운영상태와 추천 결과 실시간 연계

### 1.2 적용 채널

모바일웹, 데스크톱웹, 현장 키오스크, 참가업체 파트너 포털, 운영자 관리자 시스템

### 1.3 기본 가정

- 기존 백주대간 홈페이지 회원체계와 완전 통합하지 않고 별도 매칭서비스로 구축
- 기존 사전등록 정보는 API 또는 CSV 방식으로 동기화
- 최초 이용자는 비회원 세션으로 서비스 이용 가능
- 일정 저장·상담요청·연락처 공유 시 휴대전화 인증 수행
- 모든 시간 데이터는 서버에 UTC로 저장하고 화면에서는 Asia/Seoul 기준으로 표시
- 개인정보 DB와 추천·행동정보 DB를 논리적으로 분리

## 2. 전체 시스템 구성

```
[모바일웹·파트너포털]
          │
          ▼
[API Gateway / BFF]
          │
 ┌────────┼─────────┬─────────┐
 ▼        ▼         ▼         ▼
인증     프로파일   전시정보   상담·일정
서비스   서비스     서비스     서비스
          │
          ▼
[Recommendation Orchestrator]
          │
 ┌────────┼──────────┬──────────┐
 ▼        ▼          ▼          ▼
후보검색  필수필터   점수계산   AI 설명생성
          │
          ▼
[데이터 계층]
 ├─ 개인정보 DB
 ├─ 운영·거래 DB
 ├─ 행동 이벤트 저장소
 ├─ 검색·벡터 인덱스
 └─ 분석 데이터마트
```

## 3. API 공통 기준

### 3.1 기본 규격

| 항목 | 기준 |
|---|---|
| 통신방식 | HTTPS |
| API 형태 | REST JSON |
| 기본 경로 | `/api/v1` |
| 문자 인코딩 | UTF-8 |
| 시간 형식 | ISO 8601 |
| 서버 저장시간 | UTC |
| 인증 | Bearer Token |
| 비회원 식별 | Guest Session Token |
| 페이지 처리 | Cursor Pagination |
| 요청 추적 | `X-Request-ID` |
| 중복 요청 방지 | `Idempotency-Key` |
| API 버전 | URL 버전 방식 |

### 3.2 공통 요청 헤더

```json
{
  "Authorization": "Bearer {access_token}",
  "X-Guest-Session": "{guest_session_token}",
  "X-Request-ID": "{uuid}",
  "Idempotency-Key": "{uuid}",
  "Accept-Language": "ko-KR"
}
```

### 3.3 공통 성공 응답

```json
{
  "success": true,
  "data": {},
  "meta": {
    "request_id": "req_123456",
    "timestamp": "2026-10-09T05:30:00Z"
  }
}
```

### 3.4 공통 오류 응답

```json
{
  "success": false,
  "error": {
    "code": "PROFILE_INCOMPLETE",
    "message": "추천 생성을 위한 방문 목적 정보가 필요합니다.",
    "field": "visit_goals",
    "retryable": false
  },
  "meta": { "request_id": "req_123456" }
}
```

## 4. 사용자 및 인증 상태

### 4.1 사용자 상태

| 상태 | 설명 | 이용 가능 기능 |
|---|---|---|
| GUEST | 비회원 세션 | 프로파일링, 추천 조회, 지도 |
| VERIFIED | 휴대전화 인증 사용자 | 저장, 일정, 상담요청 |
| BUYER | 바이어 인증 사용자 | B2B 조건 입력, 상담요청 |
| EXHIBITOR | 참가업체 담당자 | 상담 수락, 리드 관리 |
| OPERATOR | 행사 운영자 | 검수, 운영상태, 모니터링 |
| ADMIN | 시스템 관리자 | 권한·정책·감사관리 |

### 4.2 핵심 식별자

| 식별자 | 용도 |
|---|---|
| `user_id` | 사용자 내부 식별자 |
| `identity_id` | 개인정보 DB 식별자 |
| `guest_session_id` | 비회원 세션 |
| `visit_session_id` | 행사 방문 세션 |
| `profile_id` | 추천용 프로파일 |
| `recommendation_session_id` | 추천 생성 단위 |
| `match_result_id` | 개별 추천 결과 |
| `exhibitor_id` | 참가업체 |
| `product_id` | 제품 |
| `booth_id` | 부스 |
| `meeting_id` | 상담 |
| `event_id` | 행동 이벤트 |

## 5. 화면별 API 매핑

### 5.1 U-01 서비스 시작

세션 생성: `POST /api/v1/sessions`

요청

```json
{
  "entry_channel": "QR",
  "entry_code": "GATE_A",
  "device_type": "MOBILE_WEB",
  "language": "ko-KR"
}
```

응답

```json
{
  "guest_session_id": "gs_001",
  "guest_session_token": "token",
  "event_status": "OPEN",
  "service_available": true,
  "minimum_age": 19
}
```

DB 처리: `guest_sessions` 생성, `visit_sessions` 임시 생성, 진입 경로 저장

이벤트: `SERVICE_ENTERED`, `SESSION_CREATED`

### 5.2 U-02 사용자 유형 선택

`PATCH /api/v1/profiles/{profile_id}/user-type`

요청

```json
{ "user_type": "GENERAL_VISITOR" }
```

또는

```json
{ "user_type": "BUYER" }
```

DB 처리: `user_profiles.user_type`, `user_profiles.profile_status`

이벤트: `USER_TYPE_SELECTED`, `USER_TYPE_CHANGED`

### 5.3 U-03 연령 및 개인화 동의

`POST /api/v1/consents`

요청

```json
{
  "consents": [
    { "consent_type": "AGE_CONFIRMATION", "consent_version": "2026.1", "agreed": true },
    { "consent_type": "PERSONALIZED_RECOMMENDATION", "consent_version": "2026.1", "agreed": true },
    { "consent_type": "BEHAVIOR_DATA", "consent_version": "2026.1", "agreed": false }
  ]
}
```

처리 기준: 연령확인 미동의 시 주류 추천서비스 제한, 개인화 추천 미동의 시 일반 부스 검색만 제공, 행동정보 동의 미제공 시 개인별 재학습 제외, 동의 철회 시 이후 이벤트의 개인화 활용 중지

DB 처리: `consents`, `consent_history`, `audit_logs`

### 5.4 U-04 방문 목적

`PUT /api/v1/profiles/{profile_id}/goals`

요청

```json
{
  "visit_goals": [
    { "code": "TASTING", "priority": 1 },
    { "code": "PURCHASE", "priority": 2 },
    { "code": "GIFT_SEARCH", "priority": 3 }
  ],
  "free_text_goal": "부모님 선물용 전통주를 찾고 있습니다."
}
```

AI 처리: 자유입력 내용이 있는 경우 다음 구조로 변환한다.

```json
{
  "intent": "PURCHASE",
  "usage": "GIFT",
  "target_recipient": "PARENTS",
  "product_category": null,
  "price_max": null
}
```

처리 원칙: AI 추출 결과는 사용자 선택값을 덮어쓰지 않음, 추출값은 보조 프로파일로 저장, 신뢰도 0.7 미만 항목은 추천 필수조건으로 사용하지 않음

### 5.5 U-05 관람객 취향 진단

`PUT /api/v1/profiles/{profile_id}/consumer-preferences`

요청

```json
{
  "product_categories": ["DISTILLED_LIQUOR", "YAKJU_CHEONGJU"],
  "taste_preferences": ["DRY", "AROMATIC", "SMOOTH"],
  "alcohol_level": { "min": 10, "max": 30 },
  "price_range": { "min": 20000, "max": 50000, "currency": "KRW" },
  "purchase_intent": "LIKELY",
  "preferred_activities": ["TASTING", "ON_SITE_PURCHASE"]
}
```

DB 처리: `consumer_preferences`, `profile_attributes`, `profile_version`

이벤트: `PREFERENCE_SELECTED`, `PREFERENCE_SKIPPED`, `PROFILE_COMPLETED`

### 5.6 U-06 바이어 거래조건 진단

`PUT /api/v1/profiles/{profile_id}/buyer-needs`

요청

```json
{
  "organization_type": "BOTTLE_SHOP",
  "distribution_channels": ["OFFLINE_RETAIL", "ONLINE_MALL"],
  "desired_categories": ["DISTILLED_LIQUOR"],
  "target_price": { "min": 20000, "max": 50000, "basis": "RETAIL_PRICE" },
  "expected_order_volume": { "type": "REGULAR_SMALL", "monthly_units_min": 100, "monthly_units_max": 500 },
  "supply_regions": ["SEOUL", "GYEONGGI"],
  "business_interests": ["DISTRIBUTION", "EXCLUSIVE_SALES"],
  "decision_timeline": "WITHIN_3_MONTHS"
}
```

추가 인증: 상담요청 전 다음 항목 확인 필요 — 소속기관, 담당부서, 직책, 업무용 이메일, 연락처, 개인정보 공유 동의

### 5.7 U-07 방문시간 및 조건

`PUT /api/v1/visit-sessions/{visit_session_id}/plan`

요청

```json
{
  "visit_date": "2026-10-09",
  "entry_time": "2026-10-09T14:00:00+09:00",
  "available_minutes": 90,
  "route_preference": "LOW_CONGESTION",
  "walking_constraints": { "minimize_distance": true, "accessible_route": false },
  "meeting_available_slots": [
    { "start": "2026-10-09T15:00:00+09:00", "end": "2026-10-09T16:30:00+09:00" }
  ]
}
```

처리 결과: 추천 대상 수 제한, 경로 최적화 기준 설정, 상담 가능시간 후보 생성

## 6. AI 추천 API

### 6.1 추천 생성

`POST /api/v1/recommendations/generate`

요청

```json
{
  "profile_id": "pf_001",
  "visit_session_id": "vs_001",
  "recommendation_type": "MIXED",
  "context": {
    "current_zone": "ENTRANCE_A",
    "remaining_minutes": 90,
    "current_time": "2026-10-09T14:10:00+09:00",
    "exclude_visited": true,
    "include_meetings": true
  },
  "limit": 10
}
```

추천 처리 순서

```
1. 사용자 프로파일 조회
2. 동의·연령·서비스 상태 확인
3. 참가업체·제품 후보 검색
4. 운영중단·품절·상담마감 제외
5. 사용자 조건 기반 필수필터
6. 일반 관람객 또는 바이어 점수 계산
7. 거리·혼잡·시간 기반 재정렬
8. 추천 편중 및 다양성 보정
9. 추천 이유 생성
10. 결과·모델·정책 버전 저장
```

응답

```json
{
  "recommendation_session_id": "rs_001",
  "generated_at": "2026-10-09T05:10:02Z",
  "expires_at": "2026-10-09T05:20:02Z",
  "profile_version": 4,
  "model_version": "match-v1.3",
  "policy_version": "policy-2026.10.1",
  "items": [
    {
      "match_result_id": "mr_001",
      "rank": 1,
      "object_type": "BOOTH",
      "object_id": "booth_012",
      "exhibitor_id": "ex_031",
      "match_level": "VERY_HIGH",
      "display_score": 92,
      "reasons": [
        { "code": "TASTE_MATCH", "text": "선호한 드라이한 증류주 조건과 일치합니다." },
        { "code": "PRICE_MATCH", "text": "희망 가격대의 현장구매 제품이 있습니다." },
        { "code": "LOW_WAIT", "text": "현재 예상 대기시간이 짧습니다." }
      ],
      "distance_meters": 120,
      "estimated_walk_minutes": 3,
      "estimated_wait_minutes": 5,
      "availability": { "open": true, "tasting": true, "purchase": true, "meeting": true },
      "recommended_action": "VISIT_NOW"
    }
  ]
}
```

### 6.2 추천 세션 저장 필드

| 필드 | 설명 |
|---|---|
| recommendation_session_id | 추천 실행 식별자 |
| profile_id | 사용 프로파일 |
| profile_version | 프로파일 버전 |
| model_version | 매칭모델 버전 |
| policy_version | 추천정책 버전 |
| context_snapshot | 당시 위치·시간·혼잡 |
| candidate_count | 필터 전 후보 수 |
| filtered_count | 필터 후 후보 수 |
| generated_at | 생성시간 |
| expires_at | 추천 유효시간 |

### 6.3 개별 추천 저장 필드

| 필드 | 설명 |
|---|---|
| match_result_id | 결과 식별자 |
| object_type | 부스·제품·업체·행사 |
| object_id | 추천 대상 |
| raw_score | 내부 원점수 |
| normalized_score | 정규화 점수 |
| rank | 추천순위 |
| reason_codes | 추천근거 코드 |
| hard_filter_passed | 필수조건 통과 |
| diversity_adjustment | 다양성 보정값 |
| context_adjustment | 현장상황 보정값 |

## 7. 추천 홈 API

### U-08 AI 추천 홈

`GET /api/v1/home?visit_session_id={id}`

응답 구성

```json
{
  "user_summary": { "display_name": "김희섭", "user_type": "BUYER" },
  "current_context": { "zone": "ENTRANCE_A", "remaining_minutes": 80 },
  "next_best_action": { "type": "VISIT_BOOTH", "match_result_id": "mr_001" },
  "recommended_route": { "route_id": "route_001", "total_minutes": 55, "booth_count": 4 },
  "upcoming_meeting": { "meeting_id": "mt_001", "start_at": "2026-10-09T15:30:00+09:00" },
  "recommendations": []
}
```

처리 기준: 기존 추천 세션이 유효하면 재사용, 위치·운영상태·남은시간이 변경되면 재정렬, 프로파일이 변경되면 새 추천 세션 생성, 부스 운영종료·품절 시 즉시 대체 추천 제공

## 8. 추천 목록 및 상세 API

### 8.1 추천 목록

`GET /api/v1/recommendations/{recommendation_session_id}/items`

조회 파라미터: `type=BOOTH`, `sort=RECOMMENDED`, `category=DISTILLED_LIQUOR`, `tasting=true`, `purchase=true`, `cursor={cursor}`, `limit=20`

### 8.2 부스 상세

`GET /api/v1/booths/{booth_id}`

응답

```json
{
  "booth_id": "booth_012",
  "booth_number": "B-12",
  "exhibitor": { "exhibitor_id": "ex_031", "name": "A양조장", "summary": "지역 쌀을 활용한 증류주 생산" },
  "location": { "zone": "B", "x": 320, "y": 140 },
  "operating_status": "OPEN",
  "estimated_wait_minutes": 5,
  "services": { "tasting": true, "purchase": true, "meeting": true },
  "products": [],
  "recommendation_context": { "match_result_id": "mr_001", "reasons": [] }
}
```

### 8.3 제품 상세

`GET /api/v1/products/{product_id}`

주요 응답 필드: 제품명, 참가업체, 주종, 주요 원료, 도수, 맛 속성, 가격, 현장 판매가, 시음 가능 여부, 재고상태, 수상·인증정보, 유통·거래조건, 유사제품

## 9. 관심목록 API

- 관심 저장: `POST /api/v1/favorites` — `{ "object_type": "BOOTH", "object_id": "booth_012", "source": "RECOMMENDATION", "match_result_id": "mr_001" }`
- 관심 해제: `DELETE /api/v1/favorites/{favorite_id}`
- 관심목록 조회: `GET /api/v1/favorites?object_type=BOOTH`

이벤트: `FAVORITE_ADDED`, `FAVORITE_REMOVED`, `FAVORITE_REOPENED`

## 10. 추천 경로 API

### 10.1 경로 생성

`POST /api/v1/routes/optimize`

요청

```json
{
  "visit_session_id": "vs_001",
  "start_location": { "type": "ZONE", "id": "ENTRANCE_A" },
  "targets": [
    { "object_type": "BOOTH", "object_id": "booth_012", "priority": 1, "expected_duration_minutes": 15 },
    { "object_type": "MEETING", "object_id": "mt_001", "fixed_time": "2026-10-09T15:30:00+09:00" }
  ],
  "constraints": { "available_minutes": 90, "avoid_congestion": true, "minimize_walking": true }
}
```

응답

```json
{
  "route_id": "route_001",
  "total_minutes": 68,
  "walking_minutes": 13,
  "visit_minutes": 55,
  "items": [
    { "sequence": 1, "object_type": "BOOTH", "object_id": "booth_012", "arrival_at": "2026-10-09T14:18:00+09:00", "stay_minutes": 15 }
  ]
}
```

### 10.2 경로 재계산 조건

사용자의 현재 구역 변경, 방문 완료 또는 건너뛰기, 상담시간 변경, 부스 운영중단, 혼잡도 임계치 초과, 남은 체류시간 변경

## 11. 상담 API

### 11.1 상담 가능시간 조회

`GET /api/v1/exhibitors/{exhibitor_id}/availability` — 파라미터: `date=2026-10-09`, `topic=DISTRIBUTION`

### 11.2 상담 요청

`POST /api/v1/meetings`

```json
{
  "exhibitor_id": "ex_031",
  "buyer_profile_id": "pf_001",
  "topic": "DISTRIBUTION",
  "requested_slots": [
    { "start": "2026-10-09T15:00:00+09:00", "end": "2026-10-09T15:20:00+09:00" },
    { "start": "2026-10-09T16:00:00+09:00", "end": "2026-10-09T16:20:00+09:00" }
  ],
  "message": "서울 지역 바틀샵 입점 조건을 상담하고 싶습니다.",
  "contact_share_consent": true,
  "match_result_id": "mr_001"
}
```

### 11.3 상담 상태

```
REQUESTED → VIEWED → ACCEPTED → RESCHEDULE_PROPOSED → CONFIRMED → COMPLETED → FOLLOW_UP
```

예외 상태: `REJECTED`, `CANCELLED_BY_BUYER`, `CANCELLED_BY_EXHIBITOR`, `NO_SHOW`

### 11.4 업체 응답

`POST /api/v1/meetings/{meeting_id}/responses`

```json
{
  "action": "ACCEPT",
  "confirmed_slot": { "start": "2026-10-09T15:00:00+09:00", "end": "2026-10-09T15:20:00+09:00" }
}
```

### 11.5 일정 충돌 처리

상담 확정 전 다음 항목 검증: 구매자 기존 일정, 업체 담당자 기존 상담, 부스 운영시간, 행사 프로그램 일정, 이동시간 확보 여부

## 12. QR 체크인 API

### 12.1 QR 검증

`POST /api/v1/check-ins/validate`

```json
{ "qr_token": "encoded-token", "visit_session_id": "vs_001" }
```

검증항목: QR 유효기간, 부스·행사 코드 존재, 위변조 서명, 중복 체크인, 행사 운영시간, 사용자 세션 상태

### 12.2 체크인 등록

`POST /api/v1/check-ins`

```json
{
  "booth_id": "booth_012",
  "visit_session_id": "vs_001",
  "activities": ["TASTING", "PURCHASE"],
  "match_result_id": "mr_001"
}
```

DB 처리: `booth_checkins`, `interaction_events`, `visit_session_progress`, `match_conversion`

이벤트: `BOOTH_CHECKED_IN`, `TASTING_RECORDED`, `PURCHASE_INTENT_RECORDED`, `RECOMMENDATION_CONVERTED`

## 13. 피드백 API

`POST /api/v1/feedback`

```json
{
  "object_type": "BOOTH",
  "object_id": "booth_012",
  "match_result_id": "mr_001",
  "rating": "VERY_RELEVANT",
  "positive_reasons": ["TASTE", "PRICE"],
  "negative_reasons": [],
  "comment": null
}
```

추천 반영 기준

| 피드백 | 처리 |
|---|---|
| 매우 적합 | 유사 속성 가중치 강화 |
| 보통 | 직접 가중치 변경 없음 |
| 부적합 | 해당 불일치 속성 감점 |
| 가격 불일치 | 가격 범위 재확인 |
| 맛 불일치 | 맛 선호 보정 |
| 혼잡 | 부스가 아닌 상황요인으로 처리 |

혼잡 때문에 부적합했던 부스를 취향 불일치로 학습하면 모델이 매우 열심히 틀리게 된다. 피드백 원인을 분리해야 한다.

## 14. 프로파일 수정 및 추천 재생성

### 14.1 프로파일 수정

`PATCH /api/v1/profiles/{profile_id}`

```json
{
  "taste_preferences": { "add": ["SWEET"], "remove": ["DRY"] },
  "price_range": { "min": 30000, "max": 80000 },
  "remaining_minutes": 45
}
```

### 14.2 처리 결과

```json
{
  "profile_version": 5,
  "recommendation_refresh_required": true,
  "invalidated_recommendation_session_ids": ["rs_001"]
}
```

추천 세션 갱신 조건: 방문목적 변경, 주종·가격·맛 조건 변경, 바이어 거래조건 변경, 체류시간 20% 이상 변경, 명시적 추천 제외, 주요 피드백 등록

## 15. 참가업체 포털 API

### 15.1 업체 대시보드

`GET /api/v1/partner/dashboard`

```json
{
  "today": {
    "meeting_requested": 3,
    "meeting_confirmed": 4,
    "meeting_completed": 2,
    "checkin_count": 48,
    "qualified_lead_count": 12
  },
  "booth_status": "OPEN",
  "inventory_alerts": [],
  "new_requests": []
}
```

### 15.2 상담 요청 목록

`GET /api/v1/partner/meetings?status=REQUESTED`

### 15.3 바이어 요약

`GET /api/v1/partner/buyers/{buyer_profile_id}/summary`

제공 범위: 소속유형, 유통채널, 희망 제품군, 예상 거래규모, 공급 희망지역, 상담 주제, 개인정보 공유 동의 시 연락처

미제공 범위: 사용자의 전체 방문이력, 다른 업체와의 상담내역, 상세 행동로그, 동의하지 않은 개인식별정보

### 15.4 상담결과 등록

`POST /api/v1/partner/meetings/{meeting_id}/outcome`

```json
{
  "lead_status": "QUALIFIED",
  "outcome": "FOLLOW_UP_REQUIRED",
  "follow_up_actions": ["SEND_SAMPLE", "SEND_QUOTE"],
  "next_contact_date": "2026-10-15",
  "notes": "증류주 2종 견적 전달 필요"
}
```

## 16. 핵심 DB 테이블

> 본 절은 초기 인터페이스 설계 시점의 요약 테이블 목록이며, 정식 스키마와 필드 정의는 [DB ERD 상세설계 및 테이블 정의서](06-db-erd-schema-design.md)를 따른다.

### 16.1 개인정보 영역 — `user_identities`

| 필드 | 형식 | 설명 |
|---|---|---|
| identity_id | UUID | 식별정보 키 |
| user_id | UUID | 내부 사용자 키 |
| name_enc | VARCHAR | 암호화 성명 |
| phone_enc | VARCHAR | 암호화 휴대전화 |
| email_enc | VARCHAR | 암호화 이메일 |
| phone_hash | VARCHAR | 중복검사용 해시 |
| verified_at | TIMESTAMP | 인증일시 |
| created_at | TIMESTAMP | 생성일시 |

### 16.2 프로파일 영역

**`user_profiles`**

| 필드 | 설명 |
|---|---|
| profile_id | 프로파일 ID |
| user_id | 사용자 ID |
| user_type | 일반 관람객·바이어 |
| profile_status | 작성중·완료·비활성 |
| current_version | 프로파일 버전 |
| primary_goal | 최우선 방문목적 |
| created_at | 생성일시 |
| updated_at | 수정일시 |

**`consumer_preferences`**: profile_id, product_categories, taste_preferences, alcohol_min, alcohol_max, price_min, price_max, purchase_intent, activity_preferences

**`buyer_needs`**: profile_id, organization_type, distribution_channels, desired_categories, target_price_min, target_price_max, expected_volume_min, expected_volume_max, supply_regions, business_interests, decision_timeline

### 16.3 전시 데이터 영역

**`exhibitors`**: exhibitor_id, company_name, company_summary, business_type, approval_status, data_completeness_score, profile_version

**`products`**: product_id, exhibitor_id, product_name, category, alcohol_percentage, price, ingredients, taste_attributes, production_method, tasting_available, purchase_available, inventory_status, approval_status

**`trade_conditions`**: exhibitor_id, product_id, min_order_quantity, monthly_capacity, supply_regions, distribution_channels, oem_available, private_label_available, export_available

**`booths`**: booth_id, exhibitor_id, booth_number, zone, x_coordinate, y_coordinate, operating_status, estimated_wait_minutes, congestion_level

### 16.4 추천 영역

**`recommendation_sessions`**: recommendation_session_id, profile_id, visit_session_id, profile_version, model_version, policy_version, context_snapshot, candidate_count, generated_at, expires_at

**`match_results`**: match_result_id, recommendation_session_id, object_type, object_id, raw_score, normalized_score, rank, reason_codes, hard_filter_passed, diversity_adjustment, context_adjustment

### 16.5 행동 및 성과 영역

**`interaction_events`**: event_id, user_id, guest_session_id, visit_session_id, event_type, object_type, object_id, match_result_id, recommendation_session_id, rank_at_event, event_context, occurred_at

**`meetings`**: meeting_id, buyer_profile_id, exhibitor_id, topic, status, requested_slots, confirmed_start, confirmed_end, contact_share_consent, outcome, created_at

## 17. 행동 이벤트 표준

### 17.1 공통 이벤트 구조

```json
{
  "event_id": "evt_001",
  "event_type": "RECOMMENDATION_CLICKED",
  "user_id": "user_001",
  "guest_session_id": null,
  "visit_session_id": "vs_001",
  "object_type": "BOOTH",
  "object_id": "booth_012",
  "recommendation_session_id": "rs_001",
  "match_result_id": "mr_001",
  "rank_at_event": 1,
  "context": { "screen": "HOME", "zone": "ENTRANCE_A" },
  "occurred_at": "2026-10-09T05:15:00Z"
}
```

### 17.2 주요 이벤트

**프로파일 이벤트**: `PROFILE_STARTED`, `USER_TYPE_SELECTED`, `GOAL_SELECTED`, `PREFERENCE_SELECTED`, `QUESTION_SKIPPED`, `PROFILE_COMPLETED`, `PROFILE_UPDATED`

**추천 이벤트**: `RECOMMENDATION_GENERATED`, `RECOMMENDATION_IMPRESSION`, `RECOMMENDATION_CLICKED`, `RECOMMENDATION_DISMISSED`, `RECOMMENDATION_REFRESHED`

**행동 이벤트**: `FAVORITE_ADDED`, `ROUTE_ADDED`, `ROUTE_STARTED`, `BOOTH_CHECKED_IN`, `PRODUCT_VIEWED`, `MEETING_REQUESTED`, `MEETING_CONFIRMED`, `FEEDBACK_SUBMITTED`

## 18. AI 파이프라인 인터페이스

### 18.1 AI 적용 영역

| 기능 | AI 사용 | 통제방식 |
|---|---|---|
| 자유입력 의도분석 | 사용 | JSON Schema 검증 |
| 참가업체 설명 구조화 | 사용 | 업체·관리자 승인 |
| 후보 검색 | 임베딩 보조 | 카테고리 필터 병행 |
| 최종 점수 | 규칙·ML | LLM 직접 결정 금지 |
| 추천 이유 | LLM 사용 | 허용된 근거만 제공 |
| 피드백 반영 | 통계·학습 | 편향·오류 모니터링 |

### 18.2 추천 이유 생성 입력

```json
{
  "user_attributes": { "goals": ["GIFT_SEARCH"], "taste": ["DRY"], "price_max": 50000 },
  "matched_attributes": {
    "category": "DISTILLED_LIQUOR",
    "taste": ["DRY", "AROMATIC"],
    "price": 45000,
    "tasting_available": true
  },
  "context": { "walking_minutes": 3, "wait_minutes": 5 }
}
```

### 18.3 추천 이유 생성 출력

```json
{
  "reasons": [
    { "code": "TASTE_MATCH", "text": "선호하신 드라이한 증류주 조건과 일치합니다." },
    { "code": "PRICE_MATCH", "text": "희망 가격대 안에서 현장구매가 가능합니다." }
  ]
}
```

금지사항: 입력 데이터에 없는 사실 생성, 인구통계 기반 추정 이유 제공, 업체 우수성을 객관적 사실처럼 표현, 광고업체를 개인화 추천으로 위장, 내부 점수 또는 민감한 거래조건 노출

## 19. 추천 점수 처리 구조

### 19.1 일반 관람객

```
기본 적합도 = 취향 30 + 방문목적 20 + 가격·구매조건 15 + 시간·거리·혼잡 15 + 행동관심도 10 + 다양성 5 + 데이터 신뢰도 5
```

### 19.2 바이어

```
기본 적합도 = 거래목적 25 + 제품군 20 + 유통채널 15 + 가격·MOQ 15 + 공급지역·생산역량 10 + 상호선호 5 + 상담가능시간 5 + 데이터 신뢰도 5
```

### 19.3 점수와 추천 이유 분리

- 내부 점수는 순위 산정에 사용
- 사용자 화면에는 점수보다 일치조건 제공
- 점수 1~2점 차이를 과도한 정밀도로 표현하지 않음
- 추천 근거가 2개 미만인 경우 추천 설명 대신 '탐색 추천' 표시

## 20. 오류코드

| 코드 | 설명 | 사용자 처리 |
|---|---|---|
| AUTH_REQUIRED | 인증 필요 | 휴대전화 인증 이동 |
| AGE_CONFIRMATION_REQUIRED | 연령확인 필요 | 연령확인 화면 이동 |
| CONSENT_REQUIRED | 개인화 동의 필요 | 동의화면 이동 |
| PROFILE_INCOMPLETE | 프로파일 부족 | 누락 질문 표시 |
| NO_CANDIDATE | 추천 후보 없음 | 조건 완화 제안 |
| BOOTH_CLOSED | 부스 운영 종료 | 대체 부스 추천 |
| PRODUCT_SOLD_OUT | 제품 품절 | 유사제품 추천 |
| MEETING_CONFLICT | 일정 충돌 | 대체시간 제안 |
| MEETING_UNAVAILABLE | 상담 불가 | 다른 업체 추천 |
| INVALID_QR | QR 오류 | 재스캔 안내 |
| DUPLICATE_CHECKIN | 중복 체크인 | 기존 체크인 표시 |
| RATE_LIMITED | 요청 과다 | 잠시 후 재시도 |
| SERVICE_TEMPORARILY_UNAVAILABLE | 일시 장애 | 최근 결과 표시 |

## 21. 성능 목표

| 기능 | 목표 응답시간 |
|---|---|
| 화면 기본정보 조회 | P95 500ms 이내 |
| 프로파일 저장 | P95 800ms 이내 |
| 최초 추천 생성 | P95 2.5초 이내 |
| 추천 재정렬 | P95 1초 이내 |
| 부스·제품 상세 | P95 500ms 이내 |
| 상담 요청 | P95 1초 이내 |
| QR 체크인 | P95 800ms 이내 |
| 파트너 대시보드 | P95 1.5초 이내 |

장애 대응: 추천 결과 10분 캐시, 부스·제품 기본정보 로컬 캐시, 상담·체크인 요청 임시저장 후 재전송, AI 설명 생성 실패 시 템플릿 기반 추천 이유 제공, 추천엔진 장애 시 인기·카테고리 기반 대체 추천 제공

## 22. 보안 및 개인정보 처리

### 22.1 필수 통제

개인정보 필드 암호화, 연락처 해시 기반 중복검사, 사용자·참가업체·운영자 권한 분리, 참가업체의 바이어 개인정보 조회 제한, 연락처 공유는 상담 수락 이후 허용, 다운로드 기능 권한 및 사유 기록, 관리자 수정·삭제·승인 감사로그 기록, 추천 모델 입력에서 불필요한 식별정보 제외

### 22.2 데이터 보유정책 예시

| 데이터 | 보유 기준 |
|---|---|
| 비회원 세션 | 행사 종료 후 단기 삭제 |
| 추천 프로파일 | 사용자 동의기간 |
| 상담정보 | 후속조치 목적기간 |
| 행동로그 | 가명처리 후 분석기간 |
| 감사로그 | 내부 보안정책 기간 |
| 연락처 | 동의 철회 또는 목적달성 시 삭제 |

## 23. 주요 시퀀스

### 23.1 최초 추천

```
사용자 → 세션 생성 → 사용자 유형 선택 → 동의 등록 → 방문목적·취향 저장
→ 추천 생성 요청 → 후보검색 → 필수조건 필터 → 점수·재정렬 → 추천 이유 생성 → 추천 홈 표시
```

### 23.2 현장 방문 후 재추천

```
부스 QR 스캔 → 체크인 검증 → 방문행동 저장 → 피드백 입력 → 프로파일 보정
→ 기존 추천세션 만료 → 다음 추천 재생성 → 경로 재계산
```

### 23.3 바이어 상담

```
바이어 업체 상세 조회 → 상담 가능시간 조회 → 상담 요청 → 참가업체 알림
→ 수락 또는 시간 변경 → 일정 충돌 검증 → 상담 확정 → 연락처 공유 → 상담 완료 → 후속조치 등록
```

## 24. 개발 우선순위

**1단계: 필수 기반** — 세션·인증, 동의관리, 사용자 프로파일, 참가업체·제품·부스 DB, 추천 후보검색, 규칙 기반 매칭, 추천 홈·상세

**2단계: 현장 전환** — 지도·경로, QR 체크인, 방문 피드백, 추천 재정렬, 운영상태 관리

**3단계: B2B 상담** — 바이어 프로파일, 양면 매칭, 상담요청·수락, 일정충돌 검증, 업체 리드관리

**4단계: AI 고도화** — 자유서술 속성추출, 임베딩 검색, 행동기반 가중치 조정, 추천 설명 생성, 성과 기반 모델 평가

## 25. 완료 검수 기준

**사용자 프로파일**
- 일반 관람객과 바이어 분기 정상 작동
- 필수정보 누락 시 추천 생성 차단
- 선택정보 미입력 시에도 기본 추천 제공
- 프로파일 수정 후 추천세션 갱신

**추천**
- 운영중단·품절 부스 추천 제외
- 가격·MOQ 등 필수조건 불일치 제외
- 모든 추천에 최소 1개 이상 근거 제공
- 동일 업체·주종 과다 노출 방지
- 추천 버전과 당시 조건 재현 가능

**방문·행동**
- QR 체크인 중복 방지
- 추천 결과와 실제 방문 연결
- 체크인 후 다음 추천 갱신
- 피드백 원인별 프로파일 보정

**상담**
- 양측 일정 중복 방지
- 참가업체 수락 전 연락처 비공개
- 상담 상태 변경 이력 관리
- 상담 완료 후 리드성과 등록

**보안**
- 개인정보와 행동정보 분리
- 권한 없는 업체의 바이어 정보 조회 차단
- 관리자 데이터 변경 이력 기록
- 동의 철회 후 추천 활용 중단

## 26. 최종 구현 기준

본 인터페이스는 다음 원칙으로 구현한다.

1. 프론트엔드는 추천 결과를 표시하고 사용자 행동을 수집하는 역할 수행
2. 백엔드는 인증·동의·운영조건·데이터 정합성을 통제
3. 추천엔진은 구조화 조건과 현장상황을 기반으로 순위 결정
4. 생성형 AI는 자연어 해석과 추천 이유 설명에 제한적으로 활용
5. DB는 추천 결과뿐 아니라 당시 프로파일·정책·모델 버전을 함께 저장
6. 모든 추천·방문·상담 결과를 동일한 이벤트 체계로 연결
7. 행사 종료 후 방문전환율·상담완료율·유효리드율까지 측정 가능하도록 설계

다음 산출물은 본 명세를 기준으로 한 [DB ERD 상세설계 및 테이블 정의서](06-db-erd-schema-design.md)로 구성한다.
