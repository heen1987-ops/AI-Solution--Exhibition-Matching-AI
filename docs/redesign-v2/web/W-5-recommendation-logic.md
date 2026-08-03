# W-5. 웹 초개인화 모듈 - 개인화 추천 로직

근거 문서: `docs/redesign-v2/00-master-spec-v1.md`(§17~22, §57 점수식), `docs/redesign-v2/01-module-split-plan.md`(§4-A W-5, §6 "B2C·B2B 점수 → 웹 모듈에 재사용"). [W-4](W-4-profile-model.md)에서 확정한 프로파일 필드를 실제 점수 계산에 연결한다.

## 0. 핵심 결론: 재설계가 아니라 재계량(recalibration) 문제다

기존에 구현된 `src/meet_ai/scoring/engine.py`(`ScoringPolicy`/`ReciprocalPolicy`)와 `backend/app/services/matching/*`(candidate_generator → hard_filter_engine → feature_builder → orchestrator → context_reranker → reason_generator) 파이프라인 전체를 코드 레벨에서 확인했다. 마스터 스펙 §57이 요구하는 "웹 개인화 점수"·"바이어 매칭 점수" 공식은 **완전히 새로운 알고리즘이 아니라, 이미 존재하는 `CONSUMER_SCORE_V1`/`BUYER_SCORE_V1`과 컴포넌트 어휘가 거의 동일하고 가중치만 다르다.** 즉 W-5의 작업은 "새로 만들기"가 아니라 "가중치 재조정 + 컴포넌트 재그룹 여부 결정"이다.

## 1. 웹 개인화 점수(B2C) - 가중치 대조

| 마스터 스펙 §57 컴포넌트 | 가중치(신규) | 기존 `CONSUMER_SCORE_V1` 대응 컴포넌트 | 가중치(기존) |
| --- | --- | --- | --- |
| User Interest(사용자 관심) | 0.35 | `goal` + `sensory` + `usage`(합산 0.20+0.18+0.06=0.44에 근접) | 0.20 / 0.18 / 0.06 |
| Current Query(현재 검색) | 0.25 | 대응 컴포넌트 없음 - **신규 컴포넌트 필요** | - |
| Visit Goal(방문목적) | 0.15 | `goal` 일부 중복 가능성 | 0.20 |
| Explicit Behavior(명시적 행동) | 0.10 | `behavior` | 0.04 |
| Data Quality(데이터 품질) | 0.10 | `trust` | 0.05 |
| Booth Availability(부스 가용성) | 0.05 | `service`(운영중 여부와 유사하나 정확히 같지 않음) | 0.09 |

**발견한 구조적 차이**: 신규 스펙의 "Current Query"(0.25, 두 번째로 큰 비중)는 [W-2 §1-6](W-2-user-journey.md)의 자연어 추가검색 결과를 정적 프로파일 점수에 실시간으로 섞는 컴포넌트인데, 기존 `CONSUMER_SCORE_V1`에는 이런 컴포넌트가 없다 - `category`(0.18)가 검색 결과 카테고리 매칭과 부분적으로 겹치지만, "지금 이 순간의 질의"라는 실시간성은 기존 엔진에 없는 개념이다.

## 2. 바이어 매칭 점수(B2B) - 가중치 대조

| 마스터 스펙 §57 컴포넌트 | 가중치(신규) | 기존 `BUYER_SCORE_V1` 대응 컴포넌트 | 가중치(기존) |
| --- | --- | --- | --- |
| Product·Tech(제품·기술) | 0.20 | `product` | 0.15 |
| Business Goal(사업목표) | 0.15 | `business_goal` | 0.12 |
| Channel(유통채널) | 0.15 | `channel` | 0.12 |
| Order Scale·MOQ(주문규모) | 0.15 | `price` + `moq` + `capacity`(합산 0.10+0.12+0.10=0.32) | 0.10 / 0.12 / 0.10 |
| Region(지역) | 0.10 | `region` | 0.08 |
| Cooperation Type(협력유형) | 0.10 | `cooperation` | 0.08 |
| Trade Readiness(거래준비도) | 0.10 | `meeting`(상담 준비도와 유사) | 0.05 |
| Data Trust(데이터 신뢰) | 0.05 | `trust` | 0.08 |

**발견한 구조적 차이**: 신규 스펙은 8개 컴포넌트로 그룹화(가중치 합 1.00)하는데, 기존 엔진은 10개로 더 세분화돼 있다(`price`/`moq`/`capacity`를 분리) - 신규 스펙의 "Order Scale·MOQ" 하나가 기존 3개를 합친 개념이다. `EXHIBITOR_SCORE_V1`(9개 컴포넌트, 상호 방향)은 마스터 스펙 §57에 별도로 명시되어 있지 않으나, "상호 점수 = 방향성 점수들의 조화평균"(§57 Mutual Score) 원칙은 기존 `RECIPROCAL_SCORE_V1`의 `calculate_reciprocal_score`가 정확히 그 역할을 이미 수행하고 있다.

## 3. 결정 사항

1. **컴포넌트 재그룹은 하지 않는다.** `price`/`moq`/`capacity`를 물리적으로 하나의 `order_scale` 컴포넌트로 합치면 이미 구현된 `feature_builder.py`의 `_cooperation_match`/`_verification_score` 등 세분화된 로직을 다시 풀어써야 한다. 대신 **API 응답 레벨**에서 3개를 묶어 "주문규모" 하나로 보여주는 정도로 충분하다 - 계산은 세분화된 채로, 표시만 마스터 스펙 어휘에 맞춘다.
2. **가중치는 `ScoringPolicy.weights` 값을 마스터 스펙 §57 비율에 맞춰 재조정한다** - 이는 코드 한 곳(`engine.py`의 `CONSUMER_SCORE_V1`/`BUYER_SCORE_V1` 선언)만 바꾸면 되는 작업이며, `feature_builder.py`/`orchestrator.py`/`hard_filter_engine.py`는 컴포넌트 키 이름이 그대로 유지되는 한 전혀 손댈 필요가 없다. **실제 가중치 값 변경은 W-5 문서가 아니라 코드 변경 작업(별도 커밋)으로 진행한다** - 이 문서는 "무엇을 몇으로 바꿀지"까지만 결정하고 실행은 다음 작업 항목으로 넘긴다.
3. **"Current Query" 신규 컴포넌트가 필요하다.** 이는 [W-2 §1-6](W-2-user-journey.md) 자연어 검색 결과를 점수에 반영하는 통로가 현재 전혀 없다는 뜻이다 - `feature_builder.py`에 `current_query` 컴포넌트를 추가하고, 자연어 검색 엔진(C-4, 아직 미착수)이 반환하는 관련도 점수를 이 컴포넌트 값으로 매핑해야 한다. **이 항목은 C-4(공통 검색엔진) 설계가 선행되어야 구현 가능** - W-5에서는 "컴포넌트 자리만 예약"하고 실제 구현은 C-4 이후로 미룬다.

## 4. Hard Filter·컨텍스트 재랭킹·추천 이유 생성 - 그대로 재사용

- `hard_filter_engine.py`(§10, 필수조건 평가)는 마스터 스펙 §18("필수조건")과 개념적으로 동일 - 변경 없이 재사용.
- `context_reranker.py`(§14, 상황 재랭킹 - 부스 대기시간·잔여시간 등)는 §57의 "Booth Availability" 컴포넌트와 일부 중복되나, 재랭킹은 "점수 계산 이후 순서 조정" 단계이고 Booth Availability는 "점수 계산 자체의 한 컴포넌트"라는 위상 차이가 있다 - 두 메커니즘을 모두 유지하되 이중 반영(같은 신호를 컴포넌트에도 넣고 재랭킹에도 또 넣어 과대 반영)하지 않도록 W-8(API 설계)에서 책임 분리를 명시한다.
- `reason_generator.py`(§18, 추천 이유 생성)는 마스터 스펙 §22("추천 이유")와 그대로 대응 - 변경 없이 재사용.

## 5. GUEST_WEB·GENERAL_REGISTERED·BUYER_REGISTERED 경로 분리

- BUYER_REGISTERED: §2(바이어 매칭 점수) 경로. 기존 오케스트레이터의 BUYER 분기를 그대로 사용.
- GENERAL_REGISTERED: §1(웹 개인화 점수) 경로. 기존 오케스트레이터의 CONSUMER(`GENERAL_VISITOR`) 분기를 그대로 사용 - `audience="GENERAL_VISITOR"`라는 기존 문자열은 [W-1 §6-1](W-1-scope-and-user-types.md)의 리네이밍 결정과 함께 다뤄야 한다(정책 버전 문자열까지 바꾸면 과거 계산 결과의 `policy_version` 비교가 깨질 수 있으므로 신중히 - 새 정책 버전을 발급하는 방식을 권장).
- GUEST_WEB: [W-1 §4](W-1-scope-and-user-types.md)에서 이미 "자체 검색·추천 없음(키오스크 결과 열람만)"으로 정리했으므로, 이 사용자 유형은 W-5 점수식을 아예 타지 않는다 - 키오스크 검색모듈(K-4)의 결과를 그대로 인계받는다.

## 6. W-6/C-4로 넘기는 질문

1. `ScoringPolicy.weights`를 실제로 몇으로 바꿀지의 최종 수치 확정과 마이그레이션 여부(정책 버전 문자열을 새로 발급할지) - 별도 구현 작업으로.
2. `current_query` 컴포넌트의 실제 데이터 소스(자연어 검색 엔진의 관련도 점수 스케일 0~1 정규화 방법) - C-4에서.
3. 컨텍스트 재랭킹과 Booth Availability 컴포넌트의 이중 반영 방지 규칙 - W-8에서 API 계약으로 명시.
