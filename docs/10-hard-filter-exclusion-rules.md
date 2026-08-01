# 10단계. 필수조건 필터·제외규칙 설계

> 문서 상태: 30단계 통합 설계 로드맵 — 10단계 산출물
> 로드맵: [30단계 통합 설계 로드맵](./00-roadmap.md)
> 선행 계약: [9단계 후보검색·검색 인덱스 설계](./09-candidate-search-design.md), [6단계 매칭 분류체계·온톨로지](./06-matching-ontology.md). 이 문서의 속성 코드 표기는 API·규칙 가독성을 위한 코드 표현이며, DB·필터 평가에서는 해당 버전의 `(taxonomy_version_id, concept_id)`를 함께 참조한다.

# 1. 단계 목적

본 단계의 목적은 후보검색에서 확보된 참가업체·제품·부스·프로그램·상담 후보 중에서 사용자 요구조건, 행사 운영상태, 거래 가능성, 시간·공간 제약을 충족하지 못하는 대상을 제거하거나 제한하는 필터 체계를 정의하는 데 있다.

필수조건 필터는 높은 점수를 받은 후보라도 추천이 불가능하거나 부적절한 경우 최종 노출을 차단하는 역할을 수행한다.

본 단계에서는 다음 사항을 설계한다.

* Hard Filter와 Soft Constraint 구분
* 공통·소비자·바이어·현장 필터 정의
* 가격·MOQ·생산량·공급지역 검증
* 운영상태·품절·상담가능성 검증
* 시간·거리·접근성 검증
* 정보 미등록·미검증 처리
* 제외 사유 코드와 저장구조
* 조건 완화 제안 절차
* 필터 우선순위와 실행순서
* 관리자 예외처리 및 감사로그
* 필터 성능·정확도 검증

# 2. 핵심 설계 원칙

## 2.1 Hard Filter와 Soft Constraint 분리

모든 불일치 조건을 동일하게 제거하지 않는다.

| 구분 | 의미 | 처리 |
|---|---|---|
| Hard Filter | 반드시 충족해야 하는 조건 | 후보 제거 |
| Soft Constraint | 선호 또는 조건부 요구 | 점수 감점 |
| Warning | 정보 부족·주의 필요 | 후보 유지, 경고 표시 |
| Context Block | 현재 상황에서만 불가능 | 현재 추천 제외 |
| Policy Block | 운영·법적 정책상 제외 | 전체 추천 차단 |

예시:

```
사용자 필수조건: 현장구매 가능 → 구매 불가 제품 제거
사용자 선호조건: 대기시간 10분 이하 → 15분 대기 부스는 감점
사용자 정보: OEM 가능 업체 선호 → OEM 미지원 업체 감점
사용자 필수조건: OEM 가능 업체만 → OEM 미지원 업체 제거
```

## 2.2 사용자가 명시한 필수조건 우선

시스템이 임의로 필수조건을 생성하지 않는다. 필수조건의 출처는 다음으로 제한한다.

* 사용자가 직접 `필수`로 지정
* 서비스 이용에 필요한 법적·운영 조건
* 확정된 일정·시간 제약
* 행사 운영자가 정의한 안전·운영정책
* 검증된 거래 불가능 조건

행동추론이나 AI 자연어 해석만으로 후보를 Hard Filter 처리하지 않는다.

## 2.3 정보 없음과 조건 불충족 분리

```
NO          조건 불충족
UNKNOWN     정보 미등록
UNVERIFIED  정보 있으나 미검증
CONDITIONAL 조건부 가능
```

`UNKNOWN`을 `NO`로 간주하면 잠재적으로 적합한 후보를 과도하게 제외한다. 반대로 `UNKNOWN`을 `YES`로 간주하면 허위 추천이 된다.

따라서 정보 미등록 후보는 사용자 조건과 중요도에 따라 다음 중 하나로 처리한다: 후보 제거, 조건 확인 필요 후보, 감점 후 유지, 상담 전 확인 필요 표시.

## 2.4 필터 결과 재현 가능성 확보

모든 제외 판단은 다음 정보를 저장한다: 후보 ID, 적용 필터 코드, 필터 버전, 입력 사용자 조건, 후보의 비교값, 판단 결과, 제외사유, 판단 시점, 데이터 기준시점, 예외처리 여부.

추천되지 않은 이유까지 추적할 수 있어야 한다.

## 2.5 실시간 상황과 상시 조건 분리

| 조건 | 성격 |
|---|---|
| 제품 주종 | 상시 |
| 업체 공급지역 | 중기 |
| MOQ | 중기 |
| 부스 운영상태 | 실시간 |
| 제품 재고 | 실시간 |
| 상담 담당자 상태 | 실시간 |
| 혼잡도 | 실시간 |
| 사용자 남은시간 | 세션 |

실시간 조건은 캐시와 운영상태 저장소를 우선 조회하며, 오래된 상태정보는 낮은 신뢰도로 처리한다.

# 3. 필터 전체 구조

```
[후보검색 결과]
→ ① Policy & Security Filter
→ ② Approval & Data Status Filter
→ ③ Event Eligibility Filter
→ ④ User Explicit Exclusion Filter
→ ⑤ Product & Service Filter
→ ⑥ Price & Quantity Filter
→ ⑦ Trade Capability Filter
→ ⑧ Region & Channel Filter
→ ⑨ Time & Schedule Filter
→ ⑩ Location & Accessibility Filter
→ ⑪ Real-time Operation Filter
→ ⑫ Information Trust Filter
→ [통과 후보]
```

# 4. 필터 결과 유형

| 결과 코드 | 의미 |
|---|---|
| PASS | 조건 충족 |
| FAIL | 조건 불충족 |
| UNKNOWN | 정보 부족 |
| CONDITIONAL_PASS | 조건부 통과 |
| MANUAL_REVIEW | 운영자 확인 필요 |
| TEMPORARY_BLOCK | 현재 상황에서 일시 제외 |
| POLICY_BLOCK | 정책상 차단 |
| USER_EXCLUDED | 사용자 명시 제외 |

# 5. 필터 공통 데이터 구조

```json
{
  "filter_code": "MOQ_MATCH",
  "filter_type": "HARD",
  "result": "FAIL",
  "user_condition": { "max_moq": 100, "unit": "BOTTLE" },
  "candidate_value": { "min_order_quantity": 500, "unit": "BOTTLE" },
  "reason_code": "MOQ_EXCEEDS_BUYER_LIMIT",
  "message": "최소주문수량이 바이어의 최대 주문 가능수량을 초과합니다.",
  "rule_version": "buyer-filter-v1.2",
  "evaluated_at": "2026-10-09T14:10:00+09:00"
}
```

# 6. 정책·법적 필터

## 6.1 연령확인

적용 대상: 주류 제품 추천, 시음 프로그램, 주류 구매 기능

```
만 19세 이상 확인 완료 → 추천 허용
미확인 → 일반 행사정보만 제공, 주류 제품·시음 추천 제한
```

필터 코드: `AGE_VERIFICATION_REQUIRED`, `AGE_NOT_ELIGIBLE`

연령은 추천 적격성 판단에만 사용하고 제품 취향점수에는 사용하지 않는다.

## 6.2 개인정보 동의

| 동의 | 미동의 시 처리 |
|---|---|
| 개인화 추천 | 일반 검색만 제공 |
| 행동정보 활용 | 행동학습 제외 |
| 연락처 공유 | 상담 수락 후에도 연락처 미공유 |
| 제3자 제공 | 참가업체 정보전달 제한 |
| 마케팅 | 추천 기능과 무관 |

## 6.3 관리자 정책 차단

다음 대상은 정책상 추천을 차단할 수 있다: 참가 자격 상실 업체, 허위정보 확인 업체, 운영정책 위반 업체, 민원 조사 중 업체, 안전 문제 발생 부스, 판매중지 제품, 법적 분쟁·리콜 대상.

필터 코드: `ADMIN_BLOCKED`, `SAFETY_BLOCKED`, `COMPLIANCE_BLOCKED`, `PRODUCT_RECALL`, `EXHIBITOR_SUSPENDED`

관리자 차단에는 사유, 적용기간, 승인자를 기록한다.

# 7. 승인·데이터 상태 필터

## 7.1 승인상태

```
APPROVED  → 정상 추천
DRAFT / SUBMITTED / REJECTED / EXPIRED / SUSPENDED → 추천 제외
```

## 7.2 적용 대상

참가업체, 제품, 거래조건, 수상·인증, 행사 참가정보, 상담 담당자

## 7.3 필터 코드

`EXHIBITOR_NOT_APPROVED`, `PRODUCT_NOT_APPROVED`, `TRADE_CONDITION_NOT_APPROVED`, `PARTICIPATION_NOT_APPROVED`, `STAFF_NOT_ACTIVE`

# 8. 행사 적격성 필터

## 8.1 행사 참가 여부

해당 행사 참가 승인, 행사일과 추천일 일치, 부스 배정 여부, 전시제품 지정 여부, 참가 취소 여부

## 8.2 현장 추천

현장 추천에서는 반드시 다음 조건을 충족해야 한다: 행사 참가 승인 + 해당 행사 전시제품 + 부스 배정 + 부스 운영시간

## 8.3 사전 바이어 매칭

행사 전 B2B 매칭에서는 부스 미배정 업체도 포함할 수 있다. 조건: 참가 승인 완료, 상담 참여 동의, 거래 프로파일 완료, 행사 전 상담 가능

필터 코드: `EVENT_NOT_MATCHED`, `NOT_EXHIBITED_AT_EVENT`, `PARTICIPATION_CANCELLED`, `BOOTH_NOT_ASSIGNED`, `OUTSIDE_EVENT_DATE`

# 9. 사용자 명시 제외 필터

## 9.1 제외 수준

| 수준 | 적용범위 |
|---|---|
| SESSION | 현재 방문 |
| EVENT | 해당 행사 |
| OBJECT | 특정 제품·업체 |
| CATEGORY | 특정 제품군 |
| ATTRIBUTE | 특정 맛·도수·가격 |
| PERMANENT | 장기 제외 |

## 9.2 제외 대상

특정 제품, 특정 업체, 특정 부스, 이미 방문한 부스, 특정 주종, 특정 가격대, 특정 거래형태, 특정 지역, 혼잡 부스, 상담 거절 업체

## 9.3 필터 코드

`USER_EXCLUDED_OBJECT`, `USER_EXCLUDED_CATEGORY`, `USER_EXCLUDED_ATTRIBUTE`, `ALREADY_VISITED`, `MEETING_PREVIOUSLY_REJECTED`

이미 방문한 부스는 사용자가 재방문을 허용한 경우 후보로 유지할 수 있다.

# 10. 제품·서비스 필터

## 10.1 제품군 필수조건

```
사용자 필수: ALCOHOL.DISTILLED
후보: ALCOHOL.TAKJU → FAIL
```

상위·하위 개념 관계는 6단계 온톨로지의 `concept_revision` 계층을 사용한다.

## 10.2 시음·구매 필터

| 사용자 조건 | 후보 상태 | 처리 |
|---|---|---|
| 시음 필수 | 시음 가능 | 통과 |
| 시음 필수 | 일시중지 | 일시 제외 |
| 시음 필수 | 종료 | 제거 |
| 구매 필수 | 재고 있음 | 통과 |
| 구매 필수 | 품절 | 제거 |
| 구매 선호 | 품절 | 감점·저장 추천 |

## 10.3 제품 상태 필터

판매중, 한정판매, 품절임박, 품절, 판매종료, 단종, 리콜

필터 코드: `CATEGORY_MISMATCH`, `TASTING_UNAVAILABLE`, `PURCHASE_UNAVAILABLE`, `PRODUCT_SOLD_OUT`, `PRODUCT_DISCONTINUED`, `PRODUCT_NOT_DISPLAYED`

# 11. 맛·향·도수 필터

## 11.1 기본 원칙

맛·향은 대부분 Soft Constraint로 처리한다. Hard Filter 적용 가능 조건: 사용자가 명시적으로 제외, 알레르기·성분상 안전조건, 특정 도수 범위를 절대조건으로 설정, 무알코올 필수

## 11.2 도수 범위

```
사용자 필수범위: 5% 이상 15% 이하
제품: 25% → FAIL
```

## 11.3 맛 제외

```
사용자: 단맛 강한 제품 제외
제품: TASTE.SWEET = 5 → FAIL 또는 강한 감점
```

필터 코드: `ALCOHOL_LEVEL_OUT_OF_RANGE`, `EXCLUDED_TASTE_ATTRIBUTE`, `EXCLUDED_AROMA_ATTRIBUTE`, `INGREDIENT_EXCLUDED`

# 12. 원료·성분 필터

## 12.1 적용 조건

특정 원료 필수, 특정 원료 제외, 알레르기 관련 제외, 종교·식이 요구, 지역원료 필수, 유기농 인증 필수

## 12.2 처리 기준

일반 취향(쌀 원료 선호 → Soft Constraint) vs 안전·필수 조건(특정 원료 알레르기 → Hard Filter)

## 12.3 검증되지 않은 성분정보

성분정보가 미등록이면: 안전조건인 경우 제거, 일반 선호인 경우 감점, 사용자에게 정보 미확인 표시

필터 코드: `REQUIRED_INGREDIENT_MISSING`, `EXCLUDED_INGREDIENT_FOUND`, `INGREDIENT_INFORMATION_UNKNOWN`, `CERTIFICATION_REQUIRED`

# 13. 가격 필터

## 13.1 가격 기준 유형

소비자가, 행사 판매가, 도매가, 공급가, 샘플가, OEM 예상가. 사용자 조건과 후보 가격의 기준이 같아야 한다.

```
사용자 목표: 소비자가 5만 원 이하
후보정보: 도매가 4만 원 → 직접 비교 금지
```

## 13.2 가격 조건 수준

| 사용자 입력 | 처리 |
|---|---|
| 5만 원 이하 필수 | Hard Filter |
| 5만 원 이하 선호 | Soft Constraint |
| 가격보다 품질 | 필터 미적용 |
| 협의 가능 | 범위 확대 |
| 가격 미입력 | 필터 미적용 |

## 13.3 가격 구간 비교

```
사용자 최대가격 >= 후보 최소가격 → 조건부 통과 가능
사용자 최대가격 < 후보 최소가격 → 불일치
```

## 13.4 가격 정보 없음

| 조건 | 처리 |
|---|---|
| 가격 필수 | 제거 또는 확인필요 |
| 가격 선호 | 감점 |
| 바이어 협의 가능 | 조건부 통과 |

필터 코드: `PRICE_ABOVE_MAXIMUM`, `PRICE_BELOW_MINIMUM`, `PRICE_BASIS_MISMATCH`, `PRICE_INFORMATION_UNKNOWN`, `PRICE_EXPIRED`, `NEGOTIATION_REQUIRED`

# 14. MOQ 필터

## 14.1 비교 구조

```
바이어: 최대 MOQ 100병
업체: MOQ 300병
결과: FAIL
```

## 14.2 단위 정규화

MOQ 비교 전 단위를 통일한다 (병, 박스, 팩, 리터, 팔레트, 금액).

```
업체 MOQ: 10박스 × 12병 = 120병
```

## 14.3 협의 가능

```
업체 MOQ 300병, negotiable = true
바이어 최대 200병 → CONDITIONAL_PASS
```

## 14.4 MOQ 정보 없음

필수조건이면 제거 또는 확인필요, 선택조건이면 감점, 상담 추천 시 "MOQ 확인 필요" 표시

필터 코드: `MOQ_EXCEEDS_BUYER_LIMIT`, `MOQ_UNIT_MISMATCH`, `MOQ_INFORMATION_UNKNOWN`, `MOQ_NEGOTIABLE`, `MOQ_CONDITIONAL_MATCH`

# 15. 생산·공급역량 필터

## 15.1 비교 대상

월 예상 주문량, 업체 월 잔여 생산량, 최소·최대 공급량, 성수기 제한, 신규 계약 가능 여부, 납기, 재고

## 15.2 잔여 생산능력 기준

전체 생산량이 아니라 신규계약에 사용할 수 있는 생산량을 비교한다.

```
월 총 생산량: 10,000병
기존 계약물량: 9,500병
잔여 생산량: 500병
바이어 요구량: 1,000병 → FAIL
```

## 15.3 증설 가능성

```
현재 잔여 생산량 부족, 확장 가능, 확장 소요 60일
바이어 도입시점 90일 → CONDITIONAL_PASS
```

## 15.4 필터 코드

`INSUFFICIENT_CAPACITY`, `CAPACITY_INFORMATION_UNKNOWN`, `LEAD_TIME_TOO_LONG`, `CAPACITY_AVAILABLE_AFTER_EXPANSION`, `NEW_ORDER_NOT_AVAILABLE`, `SEASONAL_CAPACITY_LIMIT`

# 16. 유통채널 필터

## 16.1 바이어 채널과 업체 지원상태 비교

| 업체 상태 | 처리 |
|---|---|
| ACTIVE | 통과 |
| AVAILABLE | 통과 |
| PREFERRED | 가점 |
| CONDITIONAL | 조건부 통과 |
| NOT_AVAILABLE | 제거 |
| UNKNOWN | 확인필요 |

## 16.2 예시

```
바이어: 편의점 유통 필수
업체: 편의점 공급 불가 → FAIL
```

필터 코드: `CHANNEL_NOT_SUPPORTED`, `CHANNEL_CONDITIONAL`, `CHANNEL_INFORMATION_UNKNOWN`, `CHANNEL_EXCLUDED_BY_EXHIBITOR`

# 17. 공급지역 필터

## 17.1 지역 관계

정확 지역 일치, 상위 권역 일치, 전국 공급, 조건부 공급, 미지원, 미확인

## 17.2 예시

```
바이어: 서울 공급 필수 / 업체: 경기만 공급 → FAIL
업체: 수도권 공급 / 바이어: 서울 → PASS
```

## 17.3 해외수출

국가 코드, 인증, 물류 가능 여부를 함께 검증한다.

필터 코드: `REGION_NOT_SUPPORTED`, `COUNTRY_NOT_SUPPORTED`, `EXPORT_CERTIFICATION_MISSING`, `REGION_INFORMATION_UNKNOWN`, `NATIONWIDE_SUPPLY_AVAILABLE`

# 18. OEM·PB·독점유통 필터

## 18.1 상태값

`YES`, `NO`, `CONDITIONAL`, `NEGOTIABLE`, `UNKNOWN`

## 18.2 OEM 필수조건

```
바이어: OEM 필수 / 업체: OEM NO → FAIL
업체: OEM NEGOTIABLE → CONDITIONAL_PASS
업체: OEM UNKNOWN → MANUAL_REVIEW 또는 FAIL
```

## 18.3 독점유통 충돌

기존 독점계약 지역, 기존 독점채널, 신규 독점 검토 가능, 최소매출조건

필터 코드: `OEM_NOT_AVAILABLE`, `PB_NOT_AVAILABLE`, `EXCLUSIVE_CONFLICT`, `COOPERATION_CONDITIONAL`, `COOPERATION_INFORMATION_UNKNOWN`

# 19. 수출조건 필터

## 19.1 검증항목

수출 가능 여부, 대상국, 영문 라벨, 해외 인증, MOQ, 인코텀즈, 수출 실적, 독점계약, 유통기한, 냉장·상온 물류

## 19.2 적용 원칙

수출 가능 문구만으로 수출 적격 후보로 판단하지 않는다.

```
수출 가능: YES / 대상국 인증: 미확인 / 바이어 국가: 일본
→ CONDITIONAL_PASS 또는 MANUAL_REVIEW
```

필터 코드: `EXPORT_NOT_AVAILABLE`, `TARGET_COUNTRY_NOT_SUPPORTED`, `EXPORT_DOCUMENT_MISSING`, `LABEL_REQUIREMENT_NOT_MET`, `EXPORT_CONDITION_UNKNOWN`

# 20. 상담 가능성 필터

## 20.1 상담 대상 조건

업체 상담 참여 여부, 담당자 존재, 상담주제 일치, 상담 슬롯 존재, 사용자 가능시간, 담당자 가능시간, 부스 운영시간, 이동시간

## 20.2 시간 겹침

```
바이어 가능시간 15:00~16:00, 업체 가능시간 16:30~17:00 → FAIL
```

## 20.3 담당자 주제 불일치

```
상담주제: 수출 / 담당자: 국내 유통만 담당
→ 해당 담당자 제외, 다른 담당자 검색
```

필터 코드: `MEETING_NOT_ENABLED`, `NO_AVAILABLE_STAFF`, `TOPIC_NOT_SUPPORTED`, `NO_COMMON_TIME_SLOT`, `MEETING_CAPACITY_FULL`, `STAFF_UNAVAILABLE`

# 21. 일정충돌 필터

## 21.1 사용자 일정

확정 상담, 프로그램 예약, 방문경로, 퇴장 예정시간, 이동시간

## 21.2 시간 계산

```
현재 위치 → 상담 부스 이동 10분, 기존 일정 종료 14:50, 상담 시작 15:00 → 통과
이동 15분, 기존 일정 종료 14:50, 상담 시작 15:00 → FAIL
```

## 21.3 버퍼

상담 전후 기본 버퍼를 설정할 수 있다: 이동 버퍼, 등록·대기 버퍼, 상담 종료 지연 버퍼

필터 코드: `SCHEDULE_CONFLICT`, `INSUFFICIENT_TRAVEL_TIME`, `OUTSIDE_VISIT_TIME`, `INSUFFICIENT_TIME_REMAINING`

# 22. 위치·거리 필터

## 22.1 적용 조건

최대 이동거리 필수, 접근성 경로 필수, 특정 구역 제외, 행사 종료 전 도달 가능 여부

## 22.2 거리 데이터

지도 좌표, 구역 간 거리, 실제 경로 거리, 예상 이동시간, 혼잡 보정 이동시간

## 22.3 처리

```
사용자 최대 이동: 도보 10분, 후보: 예상 14분
필수조건이면 FAIL, 선호조건이면 감점
```

필터 코드: `DISTANCE_EXCEEDS_LIMIT`, `ACCESSIBLE_ROUTE_UNAVAILABLE`, `ZONE_EXCLUDED`, `LOCATION_INFORMATION_UNKNOWN`

# 23. 접근성 필터

## 23.1 접근성 조건

휠체어 접근 가능, 계단 없는 경로, 엘리베이터 필요, 휴식공간, 좌석 제공, 청각·시각 안내, 외국어 지원

## 23.2 적용 원칙

안전·접근성 필수조건은 Hard Filter로 처리한다. 정보가 미등록인 경우: 필수조건이면 제거, 운영자 확인 가능하면 수동 검토, 사용자에게 미확인 표시

필터 코드: `ACCESSIBILITY_REQUIREMENT_NOT_MET`, `ACCESSIBILITY_INFORMATION_UNKNOWN`, `LANGUAGE_SUPPORT_UNAVAILABLE`

# 24. 부스 운영상태 필터

## 24.1 상태 우선순위

```
CLOSED → 제거
PAUSED → 일시 제외
OPEN → 통과
CONGESTED → 통과 또는 상황 감점
UNKNOWN → 마지막 정상값 또는 경고
```

## 24.2 데이터 최신성

운영상태가 일정시간 이상 갱신되지 않으면 신뢰도를 낮춘다.

```
마지막 갱신: 30분 전, 실시간 기준: 5분 → STALE_STATUS
```

필터 코드: `BOOTH_CLOSED`, `BOOTH_TEMPORARILY_PAUSED`, `BOOTH_STATUS_STALE`, `BOOTH_STATUS_UNKNOWN`

# 25. 재고·시음 상태 필터

## 25.1 제품 재고

충분, 부족, 품절임박, 품절, 미확인

## 25.2 행동별 처리

| 행동 | 품절 시 처리 |
|---|---|
| 현장구매 | 제거 |
| 시음 | 시음 재고 별도 확인 |
| 관심저장 | 유지 |
| 바이어 상담 | 유지 가능 |
| 향후구매 | 유지 가능 |

제품 자체 적합도와 현재 가능한 행동을 분리한다.

```
제품 적합도 높음, 현장재고 품절
추천 행동: VISIT_NOW 제외, SAVE_FOR_LATER 가능, REQUEST_MEETING 가능
```

필터 코드: `RETAIL_STOCK_OUT`, `TASTING_STOCK_OUT`, `INVENTORY_INFORMATION_UNKNOWN`, `LIMITED_STOCK`

# 26. 혼잡도 필터

## 26.1 혼잡도는 기본적으로 Soft Constraint

사용자가 혼잡회피를 필수조건으로 지정한 경우에만 Hard Filter를 적용한다.

```
사용자: 대기 10분 이하 필수 / 부스: 예상 대기 25분 → TEMPORARY_BLOCK
```

## 26.2 혼잡 상태 변화

혼잡은 빠르게 변경되므로 영구 제외하지 않는다.

필터 코드: `WAIT_TIME_EXCEEDS_LIMIT`, `CONGESTION_TOO_HIGH`, `CONGESTION_INFORMATION_STALE`

# 27. 데이터 신뢰도 필터

## 27.1 최소 신뢰도

| 추천 유형 | 최소 신뢰도 예시 |
|---|---:|
| 일반 제품 탐색 | 0.50 |
| 현장구매 추천 | 0.70 |
| 바이어 거래추천 | 0.80 |
| 수출·독점 추천 | 0.90 |

## 27.2 처리

```
신뢰도 기준 이상 → 통과
기준 미달 → 감점 또는 제외
핵심 거래조건 미검증 → 조건부·수동확인
```

필터 코드: `DATA_TRUST_TOO_LOW`, `CRITICAL_FIELD_UNVERIFIED`, `DATA_COMPLETENESS_TOO_LOW`, `STALE_TRADE_INFORMATION`

# 28. 필터 실행 우선순위

비용이 낮고 제거효과가 큰 필터를 먼저 실행한다.

```
1. 정책·보안
2. 승인상태
3. 행사 참가
4. 사용자 제외
5. 제품·서비스 상태
6. 거래 필수조건
7. 시간·일정
8. 위치·접근성
9. 실시간 운영상태
10. 데이터 신뢰도
```

벡터 계산이나 복잡한 경로 계산 전에 명백한 부적격 후보를 제거한다.

# 29. 단락회로 평가

필터 실패가 확정되면 이후 필터를 생략할 수 있다.

```
업체 승인 취소 → 즉시 FAIL → MOQ·공급지역 비교 생략
```

다만 디버깅·분석 목적에서는 모든 필터를 실행하는 평가모드를 제공할 수 있다.

| 모드 | 처리 |
|---|---|
| PRODUCTION | 최초 실패 시 중단 가능 |
| EXPLAIN | 주요 필터 전체 평가 |
| AUDIT | 모든 필터 평가 |
| TEST | 규칙별 상세출력 |

# 30. 필터 규칙 정의 구조

```json
{
  "rule_code": "MOQ_MATCH",
  "rule_type": "HARD",
  "applies_to": ["BUYER_MATCHING"],
  "priority": 410,
  "enabled": true,
  "condition": { "buyer_requirement": "REQUIRED" },
  "unknown_policy": "MANUAL_REVIEW",
  "failure_action": "EXCLUDE",
  "version": "1.2"
}
```

# 31. 조건 완화 정책

## 31.1 자동 완화 금지 대상

연령·법적 조건, 사용자 명시 제외, 알레르기·안전, 필수 제품군, 필수 공급지역, 필수 OEM·PB, 최대 주문 가능수량, 확정 일정, 접근성 필수조건

## 31.2 제안 가능한 완화

가격 상한, 선호 맛, 최대 이동거리, 혼잡도, 비필수 지역, 도수 범위, 상담시간, 신규업체 허용, MOQ 협의 가능 범위

## 31.3 완화 제안 형식

```json
{
  "reason": "NO_EXACT_MATCH",
  "relaxation_options": [
    { "condition": "PRICE_MAX", "current": 50000, "suggested": 60000, "expected_candidate_increase": 4 },
    { "condition": "WAIT_TIME_MAX", "current": 10, "suggested": 20, "expected_candidate_increase": 6 }
  ]
}
```

# 32. 후보 부족 시 처리

## 32.1 일반 관람객

```
1. 필수조건 유지
2. 선호조건 감점형 전환
3. 상위 제품군 확장
4. 유사 맛·향 확대
5. 탐색 후보 추가
6. 사용자에게 조건 완화 제안
```

## 32.2 바이어

```
1. 필수 거래조건 유지
2. 조건부 가능 업체 별도 분리
3. 미확인 업체는 확인필요 후보로 분리
4. 협의 가능 업체 제시
5. 완화 시 증가 후보 수 안내
```

# 33. 제외사유 사용자 표현

내부 필터 코드를 그대로 노출하지 않는다.

| 내부 코드 | 사용자 표현 |
|---|---|
| MOQ_EXCEEDS_BUYER_LIMIT | 희망 주문수량과 최소주문수량이 맞지 않습니다. |
| REGION_NOT_SUPPORTED | 요청하신 지역에 현재 공급하지 않습니다. |
| BOOTH_CLOSED | 해당 부스의 운영이 종료되었습니다. |
| PRODUCT_SOLD_OUT | 현장 구매 가능한 재고가 없습니다. |
| NO_COMMON_TIME_SLOT | 양측이 가능한 상담시간이 없습니다. |
| PRICE_ABOVE_MAXIMUM | 희망 가격 범위를 초과합니다. |
| OEM_NOT_AVAILABLE | OEM 생산을 지원하지 않습니다. |

# 34. 관리자 예외처리

## 34.1 허용 대상

데이터 오류 정정, 임시 부스 이동, 상담 담당자 대체, 재고상태 복구, 잘못된 미승인 상태 해제, 운영상 긴급추천

## 34.2 금지 대상

연령·법적 조건 우회, 사용자 명시 제외 무시, 개인정보 동의 우회, 허위 거래조건 강제 통과, 광고비를 이유로 필수조건 무시

## 34.3 감사로그

예외처리자, 사유, 대상, 기존 결과, 변경 결과, 유효기간, 승인자

# 35. 필터 API

## 35.1 내부 필터 평가 API

`POST /internal/v1/matching/filters/evaluate`

요청

```json
{
  "candidate_search_id": "cs_001",
  "profile_id": "pf_001",
  "profile_version": 7,
  "policy_version": "buyer-filter-v1.2",
  "candidate_ids": ["ex_001", "ex_002"],
  "evaluation_mode": "PRODUCTION"
}
```

응답

```json
{
  "filter_evaluation_id": "fe_001",
  "total_candidates": 158,
  "passed_candidates": 47,
  "failed_candidates": 91,
  "conditional_candidates": 20,
  "results": [
    { "object_id": "ex_001", "overall_result": "PASS", "filter_results": [] },
    { "object_id": "ex_002", "overall_result": "FAIL", "primary_reason": "MOQ_EXCEEDS_BUYER_LIMIT" }
  ]
}
```

# 36. 필터 DB 구조

## 36.1 matching.filter_policy

| 필드 | 설명 |
|---|---|
| filter_policy_id | 정책 ID |
| event_id | 행사 |
| user_type | 사용자 유형 |
| recommendation_type | 추천유형 |
| version | 버전 |
| status | 상태 |
| effective_from | 적용 시작 |
| effective_until | 적용 종료 |

## 36.2 matching.filter_rule

| 필드 | 설명 |
|---|---|
| filter_rule_id | 규칙 ID |
| filter_policy_id | 정책 |
| rule_code | 규칙 코드 |
| rule_type | HARD·SOFT·WARNING |
| rule_order | 실행순서 |
| unknown_policy | UNKNOWN 처리 |
| failure_action | 제외·감점·수동확인 |
| config_json | 상세설정 |
| active | 활성 |

## 36.3 matching.filter_evaluation

| 필드 | 설명 |
|---|---|
| filter_evaluation_id | 평가 ID |
| candidate_search_id | 후보검색 |
| profile_version_id | 프로파일 버전 |
| filter_policy_id | 필터정책 |
| total_candidates | 전체 후보 |
| passed_count | 통과 |
| failed_count | 실패 |
| conditional_count | 조건부 |
| latency_ms | 처리시간 |
| evaluated_at | 평가일 |

## 36.4 matching.filter_result

| 필드 | 설명 |
|---|---|
| filter_result_id | 결과 ID |
| filter_evaluation_id | 평가 |
| object_type | 대상 유형 |
| object_id | 대상 |
| rule_code | 적용 규칙 |
| result | 결과 |
| user_value_json | 사용자 조건 |
| candidate_value_json | 후보값 |
| reason_code | 사유 |
| details_json | 상세 |
| evaluated_at | 판단일 |

# 37. 필터 캐시

## 37.1 캐시 대상

승인상태, 행사 참가상태, 제품 기본상태, 거래조건, 공급지역, 유통채널, 사용자 제외목록

## 37.2 실시간 미캐시 또는 짧은 TTL

부스 운영상태, 제품 재고, 상담 슬롯, 혼잡도, 담당자 상태

## 37.3 캐시 키 예시

```
filter:{event_id}:{profile_version}:{candidate_id}:{filter_policy_version}:{operation_snapshot_version}
```

# 38. 필터 성능 목표

| 항목 | 목표 |
|---|---:|
| 100개 후보 공통필터 | P95 50ms 이내 |
| 300개 후보 B2B 필터 | P95 150ms 이내 |
| 실시간 상태 조회 | P95 100ms 이내 |
| 전체 필터 처리 | P95 250ms 이내 |
| 캐시 적중률 | 80% 이상 |
| 필터 오류율 | 0.1% 이하 |

# 39. 필터 품질지표

| 지표 | 설명 |
|---|---|
| False Exclusion Rate | 적합 후보를 잘못 제외한 비율 |
| False Pass Rate | 부적합 후보를 통과시킨 비율 |
| Unknown Rate | 정보 부족 판단 비율 |
| Conditional Pass Rate | 조건부 후보 비율 |
| Rule Hit Rate | 규칙별 적용 빈도 |
| Zero Candidate Rate | 필터 후 후보 없음 비율 |
| Manual Review Rate | 수동확인 비율 |
| Stale Data Failure | 오래된 정보로 인한 오류 |
| Override Rate | 관리자 예외처리 비율 |
| Filter Latency | 필터 처리시간 |

# 40. 목표 기준

| 지표 | MVP 목표 |
|---|---:|
| False Pass Rate | 1% 이하 |
| False Exclusion Rate | 3% 이하 |
| Unknown Rate | 15% 이하 |
| 수동확인 비율 | 10% 이하 |
| 필터 후 후보 없음 | 5% 이하 |
| 필터 결과 재현율 | 100% |
| 실시간 상태 반영률 | 99% 이상 |

# 41. 테스트 시나리오

1. **소비자 가격 필수**: 선물용 증류주, 5만 원 이하 필수 / 제품 행사가 65,000원 → `PRICE_ABOVE_MAXIMUM`, 후보 제외
2. **현장 품절**: 현장구매 필수 / 제품 적합도 높음, 재고 품절 → 현장구매 추천 제외, 관심저장·상담 추천 가능
3. **바이어 MOQ 불일치**: 바이어 최대 100병 주문 가능 / 업체 MOQ 500병, 협의 불가 → `MOQ_EXCEEDS_BUYER_LIMIT`, 업체 제외
4. **MOQ 협의 가능**: 업체 MOQ 300병 협의 가능 / 바이어 최대 200병 → `CONDITIONAL_PASS`, 상담 전 MOQ 확인 표시
5. **공급지역 미확인**: 바이어 서울 공급 필수 / 업체 공급지역 UNKNOWN → `REGION_INFORMATION_UNKNOWN`, 자동 일치 금지, 수동확인 또는 제외
6. **상담 일정 충돌**: 사용자 15:00 기존 상담 / 신규 상담 14:50~15:10 → `SCHEDULE_CONFLICT`, 해당 시간 제외, 대체시간 제안
7. **운영상태 지연**: 부스 마지막 상태갱신 40분 전, 운영상태 OPEN → `BOOTH_STATUS_STALE`, 마지막 상태 신뢰도 감점, 운영자 확인 또는 경고

# 42. 완료 조건

* Hard Filter와 Soft Constraint가 분리되는가
* 필터 결과에 PASS·FAIL·UNKNOWN·CONDITIONAL이 존재하는가
* 사용자 명시조건과 AI 추론조건이 구분되는가
* 상시조건과 실시간조건이 구분되는가
* 필터별 실행순서와 우선순위가 정의되는가
* 사용자 조건과 후보값을 함께 저장하는가
* 제외사유와 규칙버전을 저장하는가
* 정보 미등록과 불충족을 구분하는가
* 가격·수량 단위를 정규화하는가
* 실시간 상태 기준시점을 기록하는가
* 높은 점수라도 필수조건 실패 시 제외되는가
* 사용자 필수조건을 자동 완화하지 않는가
* 조건부 후보를 일반 통과와 구분하는가
* 제품 적합도와 현재 행동 가능성을 분리하는가
* 바이어와 업체의 거래 가능성을 정량 검증하는가
* 관리자 예외처리 사유가 기록되는가
* 법적·안전 필터는 우회할 수 없는가
* 필터 결과를 재현할 수 있는가
* 후보 없음 시 완화 대안을 제시하는가
* 미확인 정보가 과도하게 자동 통과하지 않는가
* 후보 300개를 250ms 이내에 평가 가능한가
* 실시간 상태 조회 실패 시 대체정책이 있는가
* 필터 캐시 무효화가 정의되는가
* 규칙별 오류율을 측정하는가
* False Pass와 False Exclusion을 평가하는가

# 43. 확정사항

1. Hard Filter·Soft Constraint·Warning·Policy Block 분리
2. 사용자 직접 지정 필수조건만 Hard Filter 우선 적용
3. 정책·법적·승인 필터를 최우선 실행
4. 일반 관람객과 바이어 필터정책 분리
5. 미등록·불가능·조건부·미검증 상태 구분
6. 가격 기준과 가격 유형 일치 후 비교
7. MOQ 수량·단위·포장조건 정규화
8. 전체 생산량이 아닌 잔여 생산능력 기준 비교
9. 공급지역·유통채널·OEM·PB·수출조건 구조화 검증
10. 상담주제·담당자·시간·이동거리 통합 검증
11. 제품 적합도와 현재 구매·시음 가능행동 분리
12. 운영 종료·품절·상담마감 실시간 차단
13. 혼잡·대기시간은 원칙적으로 상황 제약으로 처리
14. 접근성·안전조건은 정보 미등록 시 자동 통과 금지
15. 모든 제외 판단에 조건·후보값·사유·규칙버전 저장
16. 사용자 동의 없는 필수조건 자동 완화 금지
17. 조건부 후보와 미확인 후보 별도 관리
18. 관리자 예외처리에 사유·기간·승인·감사로그 적용
19. 필터 결과를 사용자 설명문으로 변환
20. False Pass와 False Exclusion을 핵심 품질지표로 관리

다음 단계는 11단계 일반 관람객 초개인화 매칭점수 설계이며, 방문목적·주종·맛·향·도수·가격·구매조건·체험·거리·혼잡·행동·데이터 신뢰도를 정량화하고 최종 B2C 점수 산식과 보정규칙을 정의한다.
