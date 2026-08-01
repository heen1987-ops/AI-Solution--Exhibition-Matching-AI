# 제9단계. 후보검색·검색 인덱스 설계

문제를 다시 정의하면, 전체 전시 대상에서 추천 가능성이 있는 후보군을 빠르고 넓게 확보하는 검색 계층을 설계하는 단계이다. 이 단계의 목표는 최종 순위를 정하는 것이 아니라, 정답 후보를 빠뜨리지 않으면서 계산 가능한 규모로 줄이는 것이다. 검색 단계에서 후보를 놓치면 뒤의 AI가 아무리 영리해도 없는 후보를 창조할 수는 없다 (환각).

## 1. 단계 목적

본 단계의 목적은 전체 참가업체·제품·부스·프로그램·상담 가능 대상 중에서 사용자 요구와 관련성이 있는 후보를 빠르게 탐색하여, 후속 필수조건 필터와 매칭점수 계산에 전달할 고재현율 후보군을 생성하는 데 있다.

후보검색 계층은 다음 기능을 수행한다.

- 사용자 프로파일과 검색 의도 해석
- 구조화 속성 기반 후보검색
- 키워드·전문검색
- 임베딩 기반 의미검색
- 인기·신규·탐색 후보 생성
- 사용자 행동 기반 후보 생성
- 복수 검색결과 병합
- 중복 제거 및 후보 수 조절
- 실시간 운영상태를 반영한 기본 제외
- 검색 실패 시 대체 후보 제공
- 검색결과와 검색근거 저장

## 2. 핵심 설계 원칙

### 2.1 후보검색과 최종추천 분리

후보검색은 관련성이 있을 가능성이 있는 대상을 넓게 확보하는 단계이며, 최종 추천순위를 결정하지 않는다.

```
후보검색 → 관련 후보 100~300개 확보
필수조건 필터 → 불가능 후보 제거
매칭점수 계산 → 적합도 산정
상황 재정렬 → 최종 노출순위 결정
```

후보검색 결과의 순위를 그대로 사용자에게 노출하지 않는다.

### 2.2 재현율 우선

후보검색은 정확도보다 재현율을 우선한다.

예시: 실제 적합 후보 20개 중 후보검색이 18개를 포함하면 재현율 90%. 8개만 포함하면 이후 점수모델이 좋아도 최대 8개만 추천 가능하다.

초기 목표는 최종 적합 후보의 95% 이상을 후보군에 포함하는 것이다.

### 2.3 다중 검색채널 결합

| 검색방식 | 강점 | 한계 |
|---|---|---|
| 구조화 필터 | 정확한 조건 검색 | 자유로운 표현 대응 부족 |
| 키워드 검색 | 제품명·지역·원료 검색 | 유사표현 해석 제한 |
| 벡터 검색 | 의미·맥락 유사성 | 필수조건 판단 부적합 |
| 행동 기반 | 개인 관심 반영 | 신규 사용자에 약함 |
| 인기 기반 | 기본 품질 확보 | 인기 편중 발생 |
| 신규 탐색 | 신규업체 노출 | 적합도 보장 어려움 |
| 관계 기반 | 연관 제품·업체 탐색 | 관계 데이터 필요 |

### 2.4 일반 관람객과 바이어 후보검색 분리

- 일반 관람객: 제품, 부스, 시음·체험 프로그램, 지역·브랜드 콘텐츠
- 바이어: 참가업체, 제품, 거래조건, 상담 가능 담당자, 상담 슬롯

동일 검색 인덱스를 공유할 수는 있지만, 검색문서·필드 가중치·후보 병합정책은 분리한다.

### 2.5 검색 대상과 행동 분리

검색 대상과 사용자에게 권고할 행동을 구분한다. 후보검색은 대상을 찾고, 권고 행동(지금 방문/관심 저장/유사 제품 비교/상담 요청)은 후속 재정렬 단계에서 결정한다.

## 3. 후보검색 전체 아키텍처

```
[추천 요청]
→ ① Query & Profile Resolver
→ ② Retrieval Plan Builder
   ├─ 구조화 검색
   ├─ 키워드 검색
   ├─ 벡터 검색
   ├─ 행동 기반 검색
   ├─ 인기·품질 후보
   └─ 신규·탐색 후보
→ ③ Parallel Candidate Retrieval
→ ④ Candidate Normalizer
→ ⑤ Duplicate Resolver
→ ⑥ Candidate Fusion
→ ⑦ Lightweight Eligibility Check
→ ⑧ Candidate Pool Controller
→ ⑨ Candidate Store & Logger
→ [Hard Filter Engine]
```

## 4. 검색 요청 객체

후보검색은 사용자 원본 프로파일 전체를 직접 사용하지 않고, 검색에 필요한 정보만 정규화한 검색 요청 객체를 사용한다.

### 4.1 일반 관람객 검색 객체

```json
{
  "user_type": "GENERAL_VISITOR",
  "target_types": ["PRODUCT", "BOOTH", "PROGRAM"],
  "goals": ["GOAL.GIFT_SEARCH", "GOAL.TASTING"],
  "preferred_categories": ["ALCOHOL.DISTILLED"],
  "preferred_attributes": ["TASTE.DRY", "TASTE.SMOOTH", "FEATURE.DESIGN"],
  "price_range": { "min": 20000, "max": 50000 },
  "required_services": ["SERVICE.TASTING", "SERVICE.PURCHASE"],
  "free_text_query": "부모님 선물용으로 너무 달지 않은 술",
  "context": { "event_id": "event_2026", "current_zone": "ZONE_A" }
}
```

### 4.2 바이어 검색 객체

```json
{
  "user_type": "BUYER",
  "target_types": ["EXHIBITOR", "PRODUCT", "MEETING_SLOT"],
  "business_goals": ["BIZ_GOAL.NEW_PRODUCT", "BIZ_GOAL.DISTRIBUTION"],
  "required_categories": ["ALCOHOL.DISTILLED"],
  "required_channels": ["CHANNEL.BOTTLE_SHOP"],
  "preferred_regions": ["REGION.KR.SEOUL", "REGION.KR.GYEONGGI"],
  "order_volume": { "min": 100, "max": 300, "unit": "BOTTLE" },
  "target_price": { "max": 50000, "basis": "RETAIL_PRICE" },
  "free_text_query": "서울 바틀샵에 정기 납품할 증류주 업체",
  "context": { "event_id": "event_2026", "meeting_required": true }
}
```

## 5. 검색계획 생성

검색계획 생성기는 사용자 프로파일 완성도, 검색대상, 자유입력 여부에 따라 사용할 검색채널과 후보 수를 결정한다.

### 5.1 검색계획 예시

```json
{
  "retrieval_plan_id": "rp_001",
  "channels": [
    { "type": "STRUCTURED", "limit": 120, "weight": 1.0 },
    { "type": "VECTOR", "limit": 80, "weight": 0.8 },
    { "type": "KEYWORD", "limit": 50, "weight": 0.6 },
    { "type": "BEHAVIOR", "limit": 30, "weight": 0.5 },
    { "type": "EXPLORATION", "limit": 20, "weight": 0.3 }
  ],
  "target_candidate_count": 150
}
```

### 5.2 프로파일 완성도별 계획

| 프로파일 상태 | 주요 검색방식 |
|---|---|
| 완성도 높음 | 구조화 검색 중심 |
| 자유서술 풍부 | 벡터·키워드 검색 강화 |
| 행동데이터 풍부 | 행동 기반 후보 추가 |
| 신규 사용자 | 인기·다양성·탐색 후보 확대 |
| 바이어 필수조건 다수 | 구조화 검색 비중 확대 |
| 정보 부족 | 넓은 상위 카테고리 검색 |

## 6. 구조화 속성 검색

### 6.1 검색필드

- 일반 관람객: 주종, 맛·향, 도수, 가격, 원료, 용도, 시음 가능, 현장구매 가능, 지역, 제품 차별성
- 바이어: 제품군, 유통채널, 공급지역, MOQ, 생산량, 가격, OEM·PB, 수출, 거래유형, 상담주제

### 6.2 구조화 검색 예시

```sql
SELECT DISTINCT p.product_id
FROM exhibition.product p
JOIN exhibition.product_attribute pa ON p.product_id = pa.product_id
JOIN exhibition.product_event pe ON p.product_id = pe.product_id
WHERE pe.event_id = :event_id
  AND p.category_code IN ('ALCOHOL.DISTILLED')
  AND p.retail_price BETWEEN 20000 AND 50000
  AND pe.tasting_available = TRUE
  AND pe.purchase_available = TRUE
  AND p.approval_status = 'APPROVED';
```

### 6.3 상위·하위 개념 확장

사용자가 상위 분류를 선택한 경우 하위 개념까지 확장한다.

```
사용자 선택: ALCOHOL.TRADITIONAL_KOREAN
검색 확장: ALCOHOL.TAKJU, ALCOHOL.YAKJU, ALCOHOL.CHEONGJU, ALCOHOL.DISTILLED, ALCOHOL.FRUIT_WINE
```

확장 깊이와 관계가중치는 온톨로지 버전에 따라 관리한다.

### 6.4 필수조건과 선호조건

- `REQUIRED` → 검색조건에 우선 적용
- `PREFERRED` → 후보 확대와 점수 보조
- `EXCLUDED` → 후보검색 단계에서 제외 가능
- `UNKNOWN` → 검색조건 미사용

단, 복잡한 조건 충족 여부는 제10단계 Hard Filter에서 최종 검증한다.

## 7. 키워드·전문검색

### 7.1 적용 대상

제품명, 업체명, 브랜드명, 지역명, 원료명, 자유서술 제품소개, 업체소개, 거래조건 설명, 상담주제, 프로그램명

### 7.2 검색 필드 가중치

**일반 관람객**: 제품명 5.0, 브랜드명 4.0, 주종·제품분류 4.0, 제품요약 3.0, 맛·향 키워드 3.0, 업체명 2.0, 업체 이야기 1.5

**바이어**: 거래조건 5.0, 유통채널 5.0, 제품군 4.0, 공급지역 4.0, 업체 역량 3.5, 업체명 2.0, 브랜드 이야기 1.0

### 7.3 검색어 정규화 예시

```
원문: "서울 바틀샵 납품 가능한 전통소주"
정규화: 서울 / 바틀샵 / 납품 / 전통 소주 / 증류주
온톨로지 코드: REGION.KR.SEOUL, CHANNEL.BOTTLE_SHOP, TRADE.REGULAR_SUPPLY, ALCOHOL.DISTILLED
```

### 7.4 오탈자·유사어 처리

막걸리 ↔ 탁주, 전통소주 ↔ 증류식 소주, 바틀샵 ↔ 주류 전문점, 자체브랜드 ↔ PB, 납품 ↔ 공급·정기공급, 달지 않은 ↔ 드라이, 목 넘김 좋은 ↔ 부드러운. 유사어 사전과 형태소 분석을 병행한다.

## 8. 벡터 의미검색

### 8.1 역할

사용자의 자연어 요구와 업체·제품의 설명이 의미적으로 유사한 후보를 검색한다.

예시: "술을 잘 모르는 사람에게 선물하기 좋고 포장이 예쁜 술" → 직접 일치(선물용, 디자인 특화) + 의미검색(프리미엄 패키지, 선물세트, 브랜드 스토리, 입문자 친화 제품)

### 8.2 검색용 임베딩 분리

| 임베딩 유형 | 검색 대상 |
|---|---|
| PRODUCT_CONSUMER | 일반 소비자 제품 탐색 |
| PRODUCT_TRADE | B2B 제품 조건 탐색 |
| EXHIBITOR_CAPABILITY | 업체 사업역량 탐색 |
| EXHIBITOR_STORY | 브랜드·지역 이야기 |
| PROGRAM_CONTENT | 프로그램·체험 |
| BUYER_REQUIREMENT | 바이어 자연어 요구 |

### 8.3 벡터 검색 예시

```sql
SELECT object_id, 1 - (embedding <=> :query_embedding) AS similarity
FROM ai.object_embedding
WHERE object_type = 'PRODUCT'
  AND content_type = 'PRODUCT_CONSUMER'
  AND active = TRUE
ORDER BY embedding <=> :query_embedding
LIMIT 80;
```

### 8.4 벡터 유사도 사용 원칙

- 후보 생성에만 사용
- 가격·MOQ·공급지역 판단에 사용 금지
- 낮은 유사도 후보는 병합 단계에서 제외
- 검색문서 버전과 임베딩 모델 버전 저장
- 승인되지 않은 거래조건을 검색문서에 포함하지 않음

## 9. 행동 기반 후보검색

### 9.1 활용 행동

제품 상세조회, 관심 저장, 비교, 경로 추가, 부스 방문, 시음, 구매, 상담 요청, 긍정 피드백, 추천 제외

### 9.2 예시

```
최근 행동: 증류주 3개 조회, 쌀 원료 제품 2개 저장, 프리미엄 선물 제품 방문
후보 생성: 증류주 / 쌀 원료 / 선물용 / 유사 가격대 / 아직 방문하지 않은 업체
```

### 9.3 부정 행동 처리

- 제외 사유가 혼잡이면 → 동일 제품군 후보 유지, 혼잡한 부스 후보만 감점
- 제외 사유가 가격이면 → 유사 제품 중 낮은 가격대 검색
- 제외 사유가 맛이면 → 반대 맛 속성 후보 확대

### 9.4 행동 기반 후보 수 제한

권장 초기 비율은 전체 후보의 10~20%. 반복 행동만 따라가면 사용자가 이미 본 것과 비슷한 것만 추천하는 폐쇄적 루프가 발생한다.

## 10. 인기·품질 기반 후보

### 10.1 지표

상세조회율, 관심 저장률, QR 방문전환율, 긍정 피드백, 상담 완료율, 데이터 완성도, 검증상태, 운영상태, 최근성

### 10.2 인기와 품질 분리

인기(많이 조회·방문된 정도)와 품질(데이터 완성도·긍정 전환·운영 신뢰성)은 다르다. 인기가 높다고 항상 적합하거나 품질이 높은 것은 아니다.

### 10.3 인기 편향 방지

전체 노출 수로 정규화, 행사일·시간대별 비교, 업체 규모별 보정, 신규 업체 별도 후보군 유지, 스폰서 노출 데이터 제외, 직원·운영자 트래픽 제외

## 11. 신규·탐색 후보

### 11.1 목적

신규 참가업체 노출, 이용자 취향 확장, 특정 인기 업체 편중 완화, 데이터 수집을 위한 탐색

### 11.2 대상 기준

신규 참가업체, 노출 수가 적은 업체, 데이터 완성도가 높은 미노출 제품, 사용자 선호와 인접한 카테고리, 운영자가 지정한 전략 분야

### 11.3 탐색 후보 제한

권장 초기 비율은 전체 후보의 5~10%. 탐색 후보는 최종 노출을 보장하지 않으며, 이후 점수·상황·다양성 보정을 통과해야 한다.

## 12. 관계 기반 후보검색

동일 업체 다른 제품, 동일 주종 다른 지역 제품, 동일 원료 제품, 유사 맛·향 제품, 동일 유통채널 대응 업체, 보완 프로그램, 유사 상담주제 담당자 등 제품·업체·지역·프로그램 간 관계를 활용한다.

## 13. 관리자 지정 후보

### 13.1 적용 사례

공식 프로그램, 운영상 공지 대상, 지역 공동관, 긴급 대체 부스, 데이터 검증용 실험 후보, 행사 핵심 테마

### 13.2 통제 원칙

- 관리자 지정 후보임을 내부적으로 구분
- AI 개인화 점수와 혼합하지 않음
- 광고·협찬 후보는 별도 라벨
- 지정 사유와 유효기간 기록
- 후보군에 포함하더라도 최종 추천을 보장하지 않음

## 14. 검색 대상별 인덱스

### 14.1 제품 인덱스

product_id, product_name, brand_name, category_code, ingredient_codes, taste_vector, aroma_vector, alcohol_percentage, retail_price, event_price, usage_codes, feature_codes, tasting_available, purchase_available, inventory_status, approval_status, event_ids, booth_id, embedding_consumer, embedding_trade

### 14.2 업체 인덱스

exhibitor_id, company_name, business_type, region_codes, supported_channels, supply_regions, trade_types, oem_status, private_label_status, export_status, monthly_capacity, available_capacity, trade_readiness, data_trust_score, approval_status, embedding_capability, embedding_story

### 14.3 부스 인덱스

booth_id, event_id, exhibitor_id, zone_id, booth_number, operating_status, congestion_level, estimated_wait_minutes, tasting_status, sales_status, meeting_status, location_coordinates

### 14.4 프로그램 인덱스

program_id, event_id, program_name, program_type, category_codes, target_user_types, start_at, end_at, zone_id, capacity, remaining_capacity, reservation_required, status, embedding_content

### 14.5 상담 슬롯 인덱스

availability_slot_id, event_id, exhibitor_id, staff_id, topic_codes, product_ids, start_at, end_at, capacity, reserved_count, status, booth_id

## 15. 실시간 인덱스와 기준정보 분리

- 기준정보: 제품명, 주종, 원료, 맛·향, 업체 소개, 거래조건, 공급지역
- 실시간 정보: 부스 운영상태, 혼잡도, 재고, 상담 가능시간, 프로그램 잔여좌석, 담당자 상태

실시간 정보는 Redis 또는 별도 운영상태 저장소에서 조회하고, 검색 인덱스 전체를 매번 재구축하지 않는다.

## 16. 병렬 후보검색

각 검색채널은 병렬로 실행한다.

### 16.1 타임아웃 기준

| 검색채널 | 권장 타임아웃 |
|---|---|
| 구조화 검색 | 200ms |
| 키워드 검색 | 300ms |
| 벡터 검색 | 400ms |
| 행동 기반 | 200ms |
| 인기·신규 | 100ms |

일부 채널이 실패해도 성공한 결과로 후보검색을 계속한다.

## 17. 후보 결과 공통구조

```json
{
  "candidate_id": "cand_001",
  "object_type": "PRODUCT",
  "object_id": "product_001",
  "retrieval_sources": [
    { "channel": "STRUCTURED", "rank": 3, "score": 0.92 },
    { "channel": "VECTOR", "rank": 7, "score": 0.84 }
  ],
  "matched_attributes": ["ALCOHOL.DISTILLED", "TASTE.DRY", "USE.GIFT"],
  "retrieval_score": 0.88
}
```

## 18. 검색점수 정규화

검색채널별 점수 범위가 다르므로 직접 합산하지 않는다.

### 18.1 정규화 방식

Min-Max 정규화, Z-score 정규화, 순위 기반 정규화, 채널별 백분위, 캘리브레이션 모델

MVP에서는 순위 기반 정규화 또는 백분위 방식을 권장한다.

### 18.2 순위 기반 점수 예시

```
1위 = 1.00, 2위 = 0.95, 3위 = 0.90, 10위 = 0.60, 50위 = 0.20
```

검색 결과 수와 채널 특성에 따라 함수값을 조정한다.

## 19. 후보 병합

### 19.1 Reciprocal Rank Fusion

```
RRF Score = Σ 1 / (k + rank_i)
```

rank_i는 검색채널별 순위, k는 상위순위 과도한 영향 방지 상수. 초기값으로 k=60을 검토한다.

### 19.2 가중 RRF

```
Weighted RRF = Σ channel_weight_i × 1 / (k + rank_i)
```

바이어 예시: 구조화 검색 1.0, 벡터 검색 0.6, 키워드 검색 0.5, 행동 검색 0.4, 신규 후보 0.2

### 19.3 병합 원칙

- 복수 채널에서 발견된 후보 가점
- 단일 채널 고득점 후보도 유지
- 미승인 정보 기반 검색점수 제한
- 구조화 필수조건 일치 후보 우선
- 벡터 검색 단독 후보는 후속 검증 강화

## 20. 중복 제거

### 20.1 중복 유형

동일 제품의 여러 검색문서, 동일 업체의 여러 제품, 동일 부스에 속한 여러 제품, 동일 프로그램의 다국어 문서, 외부 시스템 중복 등록, 업체명·브랜드명 표기 차이

### 20.2 중복 제거 키

제품 후보는 product_id, 업체 후보는 exhibitor_id, 부스 후보는 booth_id, 프로그램 후보는 program_id. 외부 ID는 내부 표준 ID로 변환한 후 중복을 제거한다.

### 20.3 업체·제품 중복 정책

일반 관람객 추천에서는 동일 업체의 제품을 여러 개 후보로 유지할 수 있다. 단, 후보군이 특정 업체 제품으로 과도하게 채워지지 않도록 업체별 최대 후보 수를 둔다. 권장 초기값은 업체별 최대 제품 후보 5개.

## 21. 경량 적격성 검사

### 21.1 제거 대상

승인되지 않은 제품·업체, 행사 미참가, 참가 취소, 폐쇄된 부스, 삭제·비활성 대상, 현재 행사와 무관한 프로그램, 사용자가 명시적으로 차단한 대상

### 21.2 후속 Hard Filter로 이관

MOQ, 공급지역, 생산역량, 가격 절대조건, OEM·PB, 수출국, 일정 충돌, 접근성, 남은 시간은 제10단계에서 정밀하게 판단한다. 후보검색 단계에서 복잡한 필터를 과도하게 적용하면 재현율이 낮아질 수 있다.

## 22. 후보 수 제어

### 22.1 권장 후보 수

| 추천 유형 | 초기 후보군 |
|---|---|
| 제품 추천 | 100~200개 |
| 부스 추천 | 50~100개 |
| 업체 B2B 매칭 | 100~300개 |
| 프로그램 추천 | 20~50개 |
| 상담 추천 | 20~50개 |

행사 참가업체 수와 제품 수에 따라 조정한다.

### 22.2 최소·최대 후보 수

최소 미달 시 검색범위 단계적 확장, 최대 초과 시 검색점수·신뢰도 기준 절단

### 22.3 단계적 검색범위 확장

1단계 정확한 조건 일치 → 2단계 선호조건 일부 완화 → 3단계 상위 카테고리 확장 → 4단계 의미 유사 후보 추가 → 5단계 인기·신규 후보 추가

사용자의 필수조건은 자동으로 완화하지 않는다.

## 23. 후보 부족 대응

### 23.1 일반 관람객

정확히 일치하는 제품 부족 → 가격·맛 선호 범위 확대 → 유사 주종 제안 → 탐색형 추천 추가

### 23.2 바이어

필수조건 충족 업체 부족 → 필수조건 유지, 미확인 업체 별도 후보, 조건 협의 가능 업체 표시, 사용자에게 조건 완화 선택권 제공

### 23.3 후보 없음 응답 예시

```json
{
  "candidate_count": 0,
  "reason_codes": ["NO_EXACT_MATCH"],
  "relaxation_options": [
    { "field": "supply_region", "current": "SEOUL_ONLY", "suggested": "CAPITAL_REGION" },
    { "field": "moq_max", "current": 100, "suggested": 200 }
  ]
}
```

## 24. 검색 실패·장애 대응

- 벡터 검색 실패: 구조화·키워드 검색 사용, 인기·품질 후보 보완, 최근 정상 벡터 결과 재사용 가능, 장애로그 기록
- 검색엔진 장애: PostgreSQL 기본검색 전환, Redis 캐시 후보 제공, 카테고리별 기본 후보 제공, 사용자에게 시스템 오류 대신 제한추천 안내
- 행동 데이터 장애: 명시적 프로파일 중심 검색, 행동 채널만 제외, 추천 자체는 계속 제공

## 25. 인덱스 생성 파이프라인

```
업체·제품 데이터 생성·수정
→ 승인상태 확인
→ 온톨로지 코드 정규화
→ 검색문서 생성
→ 키워드 인덱스 갱신
→ 임베딩 생성
→ 벡터 인덱스 갱신
→ 인덱스 버전 활성화
```

## 26. 인덱스 갱신 방식

- 즉시 갱신: 승인상태 변경, 부스 운영 종료, 제품 품절, 참가 취소, 검색 노출 제한
- 준실시간 갱신: 제품 설명 수정, 가격 변경, 거래조건 변경, 상담 가능시간 변경
- 배치 갱신: 인기점수, 품질점수, 행동 기반 연관도, 신규·탐색 후보, 임베딩 전체 재생성

## 27. 인덱스 버전관리

### 27.1 저장 정보

인덱스 버전, 온톨로지 버전, 검색문서 템플릿 버전, 임베딩 모델 버전, 생성시간, 대상 데이터 기준시점, 문서 수, 오류 수

### 27.2 무중단 교체

```
index_v1 활성 → index_v2 생성·검증 → alias 변경 → index_v2 활성 → index_v1 보관·삭제
```

## 28. 검색 캐시

### 28.1 캐시 키

```
candidate:{event_id}:{profile_version}:{query_hash}:{context_bucket}:{retrieval_plan_version}
```

### 28.2 TTL

| 후보 유형 | 권장 TTL |
|---|---|
| 제품·업체 후보 | 5~10분 |
| 부스 후보 | 1~2분 |
| 상담 후보 | 30초 |
| 프로그램 후보 | 1분 |
| 인기 후보 | 5분 |

### 28.3 캐시 무효화

프로파일 변경, 행사 운영상태 변경, 제품 품절, 업체 승인 변경, 추천정책 변경, 인덱스 버전 변경

## 29. 후보검색 API

### 29.1 내부 후보검색 API

`POST /internal/v1/candidates/search`

요청

```json
{
  "event_id": "event_2026",
  "profile_id": "pf_001",
  "profile_version": 7,
  "user_type": "BUYER",
  "target_types": ["EXHIBITOR", "PRODUCT"],
  "retrieval_plan_version": "buyer-retrieval-v1",
  "limit": 200
}
```

응답

```json
{
  "candidate_search_id": "cs_001",
  "retrieval_plan_version": "buyer-retrieval-v1",
  "index_version": "index-2026.10.09.01",
  "total_candidates": 158,
  "channel_results": {
    "structured": 120,
    "keyword": 44,
    "vector": 73,
    "behavior": 20,
    "exploration": 10
  },
  "candidates": [
    { "object_type": "EXHIBITOR", "object_id": "ex_001", "retrieval_score": 0.87, "retrieval_sources": ["STRUCTURED", "VECTOR"] }
  ]
}
```

## 30. 후보검색 저장구조

### 30.1 matching.candidate_search

| 필드 | 설명 |
|---|---|
| candidate_search_id | 후보검색 ID |
| event_id | 행사 |
| profile_id | 프로파일 |
| profile_version_id | 프로파일 버전 |
| user_type | 사용자 유형 |
| retrieval_plan_version | 검색계획 버전 |
| index_version | 인덱스 버전 |
| query_snapshot | 검색 요청 |
| total_candidates | 최종 후보 수 |
| latency_ms | 처리시간 |
| status | 성공·부분성공·실패 |
| created_at | 생성일 |

### 30.2 matching.candidate_result

| 필드 | 설명 |
|---|---|
| candidate_result_id | 후보결과 ID |
| candidate_search_id | 검색 ID |
| object_type | 대상유형 |
| object_id | 대상 ID |
| retrieval_score | 병합 검색점수 |
| retrieval_rank | 후보순위 |
| source_channels | 검색채널 |
| matched_codes | 일치 온톨로지 |
| source_score_json | 채널별 점수 |
| created_at | 생성일 |

## 31. 후보검색 이벤트

CANDIDATE_SEARCH_STARTED, STRUCTURED_SEARCH_COMPLETED, KEYWORD_SEARCH_COMPLETED, VECTOR_SEARCH_COMPLETED, BEHAVIOR_SEARCH_COMPLETED, CANDIDATE_RESULTS_MERGED, CANDIDATE_POOL_EXPANDED, CANDIDATE_SEARCH_COMPLETED, CANDIDATE_SEARCH_PARTIAL_FAILURE, CANDIDATE_SEARCH_FAILED

## 32. 성능 목표

| 항목 | 목표 |
|---|---|
| 구조화 검색 | P95 200ms 이내 |
| 키워드 검색 | P95 300ms 이내 |
| 벡터 검색 | P95 400ms 이내 |
| 병합·중복제거 | P95 100ms 이내 |
| 전체 후보검색 | P95 600ms 이내 |
| 캐시 적중 시 | P95 100ms 이내 |
| 부분 장애 시 대체검색 | 1초 이내 |

## 33. 후보검색 품질지표

### 33.1 핵심 지표

Recall@K, Candidate Precision, Channel Coverage, Multi-source Rate, Zero-result Rate, Expansion Rate, Search Latency, Index Freshness, Candidate Diversity, Failure Recovery Rate

### 33.2 목표값 예시

| 지표 | MVP 목표 |
|---|---|
| Recall@100 | 95% 이상 |
| 후보 없음 비율 | 5% 이하 |
| 부분 장애 복구율 | 99% 이상 |
| 인덱스 최신성 | 99% 이상 |
| 전체 검색 P95 | 600ms 이내 |
| 단일 업체 후보 편중 | 20% 이하 |

## 34. A/B 테스트 항목

구조화 검색 단독 vs 하이브리드 검색, 벡터 후보 수(30·50·80개), RRF 상수값, 채널별 가중치, 행동 기반 후보 비율, 신규업체 후보 비율, 상위·하위 온톨로지 확장 깊이, 후보 풀(100·150·200개), 검색 캐시 TTL, B2C·B2B 검색문서 분리 효과

## 35. 테스트 시나리오

1. **명확한 소비자 조건**: 증류주, 드라이, 5만 원 이하, 시음 가능 → 구조화 검색이 주요 후보 확보, 벡터 검색이 선물·깔끔함 관련 후보 보완, 미전시·품절·미승인 제품 제외, 후보 수 100개 내외
2. **추상적인 소비자 요구**: "술을 잘 모르는 사람에게 선물하기 좋은 제품" → 자연어를 선물·입문자·패키지 속성으로 변환, 벡터 의미검색 비중 확대, 인기·품질 후보 보완, 가격 미입력으로 가격필터 미적용
3. **명확한 바이어 조건**: 서울 바틀샵, 증류주, 월 100~300병, 정기납품 → 제품군·채널·지역 구조화 검색, 공급역량·업체역량 벡터 후보 보완, MOQ 정밀 검증은 Hard Filter로 전달, 미확인 거래조건 후보 별도 표시
4. **필수조건이 과도한 바이어**: MOQ 50병 이하, 서울 당일배송, PB 가능, 해외수출 경험 필수 → 정확조건 후보검색, 결과 부족 시 필수조건 자동 완화 금지, 조건부·미확인 후보 별도 후보군 생성, 사용자에게 완화 가능 항목 제안
5. **검색채널 장애**: 벡터 검색 서비스 장애 → 구조화·키워드·인기 검색 정상 실행, 부분 성공 상태 저장, 추천서비스 지속, 장애 채널과 대체결과 기록

## 36. 보안·개인정보 기준

- 검색문서에 성명·전화번호·이메일 미포함
- 바이어 자유입력에서 개인정보 마스킹
- 비공개 거래가격은 권한별 인덱스 분리
- 상담 수락 전 담당자 연락처 검색 제외
- 외부 검색엔진 사용 시 개인정보 전송 금지
- 검색 로그에는 비식별 프로파일 ID 사용
- 관리자 검색결과 조회도 감사로그 기록
- 임베딩 원문에 민감정보 포함 여부 검사

## 37. 단계별 책임 경계

본 단계에서 확정하는 사항: 후보검색 아키텍처, 검색 요청 객체, 검색계획 생성방식, 구조화·키워드·벡터·행동 검색, 인기·신규·관계 후보, 병합·정규화·중복 제거, 후보 수 조정, 검색 인덱스·버전·캐시, 후보검색 API와 저장구조, 검색 성능·품질지표.

| 후속 단계 | 상세 내용 |
|---|---|
| 제10단계 | Hard Filter 및 제외규칙 |
| 제11단계 | 일반 관람객 점수산식 |
| 제12단계 | 바이어 점수산식 |
| 제14단계 | 현장상황 재정렬 |
| 제16단계 | 콜드스타트 후보전략 |
| 제21단계 | 임베딩·벡터검색·RAG 상세 |
| 제23단계 | 검색 인덱스 데이터 파이프라인 |
| 제29단계 | 후보검색 품질 시험 |

## 38. 제9단계 검수 기준

**구조**
- 후보검색과 최종순위가 분리되어 있는가
- B2C와 B2B 검색계획이 분리되는가
- 복수 검색채널을 병렬 실행하는가
- 검색점수를 정규화하여 병합하는가
- 검색 대상별 인덱스가 구분되는가

**검색품질**
- 구조화 조건과 자연어를 함께 처리하는가
- 상위·하위 온톨로지 확장이 가능한가
- 단일 행동을 과도하게 반영하지 않는가
- 인기·신규 후보의 편중을 통제하는가
- 후보 없음 시 단계적 확장이 가능한가

**운영**
- 승인되지 않은 대상이 검색되지 않는가
- 실시간 운영상태가 반영되는가
- 인덱스 버전과 기준시점이 기록되는가
- 검색채널 장애 시 부분 결과를 제공하는가
- 광고·관리자 후보와 AI 후보를 구분하는가

**성능**
- 후보검색 P95 600ms 이내가 가능한가
- 검색 인덱스 갱신 지연을 측정하는가
- 캐시 무효화 조건이 정의되어 있는가
- 후보검색 로그로 재현 가능한가
- Recall@K 평가가 가능한가

## 39. 제9단계 확정사항

- 후보검색과 최종 추천순위 분리
- 재현율 우선의 고재현율 후보군 생성
- 구조화·키워드·벡터·행동·인기·신규 검색 결합
- 일반 관람객과 바이어 검색계획 분리
- 사용자 프로파일을 검색 요청 객체로 정규화
- 검색계획에 채널별 후보 수와 가중치 적용
- 벡터 검색은 후보 생성에만 사용
- 검색채널 결과를 정규화한 후 RRF 방식 병합
- 내부 표준 ID 기준 중복 제거
- 업체별 제품 후보 수 상한 적용
- 후보 수 부족 시 단계적 검색범위 확장
- 필수조건은 자동 완화하지 않음
- 검색채널 장애 시 부분 성공·대체검색 적용
- 검색 인덱스·온톨로지·임베딩 모델 버전 저장
- 제품·업체·부스·프로그램·상담 인덱스 분리
- B2C·B2B 검색문서와 임베딩 분리
- 추천 당시 후보검색 결과와 채널별 근거 저장
- 후보검색 품질을 Recall@K 중심으로 평가

**진행 현황**: 전체 30단계 중 완료 9단계 (진행률 30.0%)

다음 단계는 제10단계 필수조건 필터·제외규칙 설계로, 승인·운영상태·가격·MOQ·공급지역·생산량·일정·접근성·사용자 제외조건을 Hard Filter와 Soft Constraint로 구분하고 제외 사유와 조건 완화 절차까지 정의한다.
