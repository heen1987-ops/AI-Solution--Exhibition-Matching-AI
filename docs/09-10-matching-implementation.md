# 9~10단계 후보검색·Hard Filter 구현 기록

## 기준

- 설계 산출물: [9단계 상세설계](./09-candidate-search-design.md), [10단계 상세설계](./10-hard-filter-exclusion-rules.md)
- 1차 스키마 근거: [DB ERD·테이블 정의서](./db-erd-table-spec.md) 13.3절(exhibition.recommendable), 15절(matching.match_policy_version/match_weight/filter_rule/recommendation_session/match_result/match_reason/filter_result)
- 상위 원칙: `docs/05-ai-matching-engine-architecture.md`, [11~13단계 점수 코어 구현 기록](./11-13-scoring-implementation.md)

이 구현은 9단계(후보검색)와 10단계(Hard Filter)의 설계를 실제 코드로 연결하고,
11~13단계 결정론적 점수 코어(`meet_ai.scoring`)에 넘길 입력을 만든다. AGENTS.md의 충돌
해소 순서(인터페이스 명세 > DB 정의서 > 해당 단계 상세설계)에 따라, 설계 문서와 DB
정의서가 어긋나는 지점은 DB 정의서를 따르고 이 문서에 보정 근거를 남긴다.

## 스키마 보정: candidate_search/filter_policy → recommendable + db-erd 15절

9·10단계 상세설계는 각각 `matching.candidate_search`/`candidate_result`,
`matching.filter_policy`/`filter_evaluation` 테이블을 제안했다. 하지만 db-erd-table-spec.md
는 이미 다른 스키마를 확정해 두었다:

- 다형 FK(object_type + object_id)를 쓰지 않고 `exhibition.recommendable` 레지스트리로
  대체한다(13.3절). `backend/app/models/exhibitor.py`의 여러 곳(Booth/EventProduct/
  ExhibitorParticipation/Program)이 이미 "matching 도메인이 recommendable을 정의할 것"이라고
  가정하고 있었다 - 실제로는 이 커밋에서 처음 만들었다.
- 후보 자체(구조화/키워드/벡터/행동 채널이 만든 중간 결과)는 영속화하지 않는다. 후보검색과
  후보 풀 크기·필터 통과 수는 `matching.recommendation_session.candidate_count/
  filtered_count/result_count` 집계값으로만 남고, 최종 통과 후보만 `matching.match_result`에,
  배제된 후보의 근거만 `matching.filter_result`에 저장한다(15.3/15.5절).
- 정책·가중치·규칙은 `matching.match_policy_version`/`match_weight`/`filter_rule` 3개
  테이블로 나뉜다(15.1절). 10단계 문서의 `filter_policy`/`filter_evaluation`은 이 3개
  테이블과 `matching.recommendation_session`으로 흡수된다.

따라서 `backend/app/models/matching.py`는 db-erd 스키마를 그대로 구현했다. 9·10단계
상세설계가 제공한 것 중 스키마가 아닌 부분(채널 결합 전략, RRF 병합 공식, 필터 결과유형
8종, 재현성 원칙, 조건 완화 정책, unknown_policy/failure_action 개념)은 그대로
서비스 계층에 구현했다 - 문서 자체를 무효화하는 것이 아니라 저장 방식만 db-erd에 맞춘
것이다.

## DB 마이그레이션

`backend/alembic/versions/20260801_1319_0006_matching.py`는 `0005_exhibition` 위에
8개 테이블(exhibition.recommendable, matching.match_policy_version/match_weight/
filter_rule/recommendation_session/match_result/match_reason/filter_result)을 추가한다.
0004_profile_domain의 수기 작성 관례 대신 `alembic revision --autogenerate` + 수기 검토
방식을 택했다 - 복합 FK와 부분 UNIQUE 인덱스가 많아 손으로 옮기다 제약 이름을 놓치는
위험이 autogenerate보다 크다고 판단했다.

검증: throwaway PostgreSQL 17 + pgvector 인스턴스에 0001~0006을 순서대로 적용, `alembic
check`로 모델·DB 드리프트 없음을 확인, `alembic downgrade -1` 후 재적용까지 모두 통과했다.

autogenerate는 이 작업과 무관한 기존 갭도 하나 감지했다: `backend/app/models/exhibitor.py`의
`SupplyProfileAttribute` 모델이 선언하는 `fk_supply_profile_attribute_concept_code`
복합 FK가 `0005_exhibition`의 원본 SQL에는 빠져 있다. exhibition 도메인 소유자가 확인해야
할 사안이라 이 마이그레이션에는 포함하지 않았다(`0006_matching.py` 모듈 docstring에도
같은 메모를 남겼다).

`backend/tests/test_exhibitor_models.py`의 전역 하드코딩 값 2개(`Base.metadata.
sorted_tables` 개수, alembic head)도 이번 커밋으로 갱신했다 - 어느 도메인이든 테이블·
마이그레이션을 추가하면 다음에도 갱신해야 하는 값이다.

## 서비스 계층 (`backend/app/services/matching/`)

`docs/11-13-scoring-implementation.md`가 명시한 역할 분담을 따른다: 이 디렉터리가
요청 검증·프로파일 해석·상황 해석·파이프라인 오케스트레이션을 담당하고, 순수 점수 계산은
전부 `meet_ai.scoring`을 호출한다 - 서비스 계층에서 점수 산식을 다시 구현하지 않는다.

| 모듈 | 역할 | 구현 범위 |
|---|---|---|
| `candidate_generator.py` | 9단계 후보검색 | 순위 기반 정규화·가중 RRF 병합·업체별 상한·후보 풀 크기 제어는 순수 함수로 완전히 구현. 구조화 검색(SQL) 채널 하나만 실제로 동작한다. 키워드·벡터·행동·인기·신규 채널은 미구현(각 모듈 docstring 참고 - 벡터 인덱스·행동 이벤트 파이프라인이 아직 없다) |
| `hard_filter_engine.py` | 10단계 Hard Filter | 평가 엔진(실행순서, PRODUCTION 단락회로/EXPLAIN 전체평가, UNKNOWN 정책, filter_result 행 변환)은 완전히 구현. 대표 규칙 3종(가격 상한, 필수 서비스 가능여부, MOQ 상한)만 예시로 제공하며 나머지 규칙은 같은 `HardFilterRule` 계약으로 추가하면 된다 |
| `feature_builder.py` | Feature Builder | `CONSUMER_SCORE_V1`/`BUYER_SCORE_V1` 구성요소 중 계산 가능한 것(category, price, moq)만 채우고 나머지는 `None`을 반환한다. `meet_ai.scoring.calculate_directional_score`는 `None`을 "정보 없음"으로 처리해 가중치 분모에서 제외하므로, 데이터가 없는 구성요소를 지어내지 않는 것이 계산 계약에 맞다 |
| `profile_resolver.py` | Profile Resolver | UserProfile + 최신 ProfileVersion + BuyerNeed + 활성 ProfileAttribute 조회. 어떤 속성이 "제품군 요구조건"인지 같은 의미 해석(concept_type 조회)은 온톨로지 조회 계층과 함께 다음 커밋에서 연결한다 |
| `context_resolver.py` | Context Resolver | VisitSession + 최신 ContextProfile 조회, recommendation_session.context_snapshot 스냅샷 생성 |
| `request_validator.py` | Request Validator | 사용자 유형·추천 유형 정합성, limit 범위만 검증한다. 연령확인·개인화 동의 검증(profile.user_consent 조회)은 TODO로 남겨두었다 |
| `orchestrator.py` | 파이프라인 오케스트레이션 | GENERAL_VISITOR/PRODUCT 경로(`generate_general_visitor_recommendations`)와 BUYER/EXHIBITOR 경로(`generate_buyer_recommendations`, `calculate_reciprocal_score` 연결 포함) 모두 구조화 검색부터 RecommendationSession/MatchResult/MatchReason/FilterResult 영속화까지 연결했다. 14단계 상황 재정렬, 18단계 추천 이유 생성(지금은 템플릿)은 다음 구현 순서로 남긴다 |

## 검증

- 단위 테스트(`backend/tests/test_candidate_generator.py`, `test_hard_filter_engine.py`,
  `test_feature_builder.py`): RRF 병합의 다중채널 가점, 업체별 상한, 후보 풀 절단,
  PRODUCTION 단락회로 vs EXPLAIN 전체평가, UNKNOWN 정책, 가격/카테고리/MOQ 구성요소
  계산, "정보 없음은 None이지 0이 아니다"를 모두 확인한다. DB 없이 실행 가능하다.
- 수동 종단 검증: throwaway Postgres에 tenant/event/exhibitor/product/event_product/
  recommendable/profile/profile_version/policy_version을 직접 심고
  `generate_general_visitor_recommendations`를 실제로 호출해 RecommendationSession
  1건과 MatchResult 1건(점수 100.00, `VISIT_NOW`)이 정확히 생성되는 것까지 확인했다.
  다만 이 스크립트는 정식 pytest 스위트에 올리지 않았다 - 비동기 DB 통합테스트를 위한
  conftest/fixture 관례가 이 저장소에 아직 없고(기존 테스트는 전부 메타데이터 검사 또는
  DB 없이 동작), 그 관례를 이 커밋에서 임의로 정하기보다 다음 구현에서 다른 도메인과
  합의하는 편이 낫다고 판단했다. 이 갭은 다음 구현 순서 목록에 남겨둔다.

## 발견된 별도 갭: interaction.meeting 도메인 (app/models/meeting.py)

9·10단계와 무관하지만 이 서비스 계층 작업 중 다른 단계 문서/모델을 감사하다가 발견해서
같은 브랜치에 커밋했다: `app/models/exhibitor.py`가 "interaction.availability_slot은
app/models/meeting.py가 이미 정의했다"고 가정하고 있었는데, 그 파일 자체가 존재하지
않았다 - `exhibition.recommendable`과 같은 종류의 갭이다. db-erd-table-spec.md 14절
전체(availability_slot/meeting/meeting_slot_request/meeting_contact_share/
meeting_status_history/meeting_outcome/follow_up_action, 마이그레이션 0007_meeting)를
구현해서 채웠다. 상세 근거는 `app/models/meeting.py`와
`backend/alembic/versions/20260801_1500_0007_meeting.py` 모듈 docstring 참고.

같은 감사 과정에서 `app/models/identity.py`의 오래된 주석(`user_role.exhibitor_id`에
FK가 없다고 적혀 있었지만 실제로는 `fk_user_role_exhibitor_boundary` 복합 FK가 이미
존재)도 바로잡았다 - 기능 변경은 없다.

## BUYER/EXHIBITOR 경로 구현 메모

`generate_buyer_recommendations`(오케스트레이터)는 GENERAL_VISITOR 경로와 같은 구조로
동작하되 마지막 점수 계산 단계에서 `calculate_directional_score`를 두 번(바이어->업체
`BUYER_SCORE_V1`, 업체->바이어 `EXHIBITOR_SCORE_V1`) 호출한 뒤 `calculate_reciprocal_score`
로 합친다.

- **구조화 검색**: `candidate_generator.structured_search_exhibitors`가
  exhibition.recommendable(EXHIBITOR) + exhibitor_participation + trade_condition(업체
  공통조건, event_product_id IS NULL)을 조인한다. 거래조건이 아직 없는 업체는 이 채널에서
  제외된다 - "미확인 업체 별도 후보"(9단계 23.2절)는 별도 채널에서 다뤄야 한다(미구현).
- **신뢰도 대리지표**: `calculate_reciprocal_score`는 buyer_confidence/exhibitor_confidence를
  필수 값으로 요구하는데 아직 실제 신뢰도 모델(08단계 16절)이 연결되지 않았다.
  `feature_builder.component_confidence()`가 "채워진 구성요소 비율"을 임시 대리지표로
  쓴다 - 지어낸 값이 아니라 명시적으로 낮은 근거를 반영하는 값이라는 점은 유지한다.
- **recommended_action 두 어휘 체계**: `calculate_reciprocal_score`의 recommended_action
  (DO_NOT_PUSH/REQUEST_INFORMATION/CONFIRM_TRADE_CONDITION/REQUEST_MEETING)은
  matching.match_result의 CHECK 제약(5단계 7.2절 어휘)과 다른 값 체계였다.
  `20260802_0900_0008_widen_recommended_action.py` 마이그레이션으로 CHECK 제약을 두
  어휘의 합집합으로 넓혀 손실 있는 매핑(`_RECIPROCAL_ACTION_MAP`)을 제거했다 - 이제
  `reciprocal_result.recommended_action`을 그대로 저장한다. 다만 DO_NOT_PUSH는 값 자체는
  저장 가능해졌어도 "밀지 말라"는 스코어링 코어의 판단이므로 여전히 최종 결과(top-N)에는
  올리지 않는다(`_EXCLUDED_RECIPROCAL_ACTIONS`) - 이는 어휘 제약이 아니라 추천 정책
  결정이다.
- **제품 카테고리 연결**: `structured_search_exhibitors`가 이제 업체가 출품한 승인된
  event_product들의 category_concept_id 집합을 `ChannelHit.matched_concept_ids`로 채운다
  (`_exhibitor_category_concept_ids`). 이전에는 이 값이 항상 빈 집합이라
  `build_buyer_components`의 `product` 구성요소가 실질적으로 항상 불일치(0점)로 계산됐다.
- **검증**: throwaway Postgres에 tenant/event/exhibitor/participation/trade_condition/
  recommendable(EXHIBITOR)/profile(BUYER)/buyer_need를 심고 종단 호출 - MOQ 100 <= 200
  통과, 상호 적합도 91.43점, `REQUEST_MEETING` 정확히 생성 확인. GENERAL_VISITOR 경로와
  같은 이유로 정식 pytest에는 아직 올리지 않았다.

## 다음 구현 순서

1. 벡터 검색(9단계 8절)·행동 기반 검색(9절)·인기/신규 탐색 후보(10·11절) 채널을 후보검색에
   연결한다 - `ai.object_embedding`과 행동 이벤트 파이프라인이 선행되어야 한다.
2. 나머지 Hard Filter 규칙(공급지역, 유통채널, OEM/PB, 수출조건, 상담시간, 접근성 등,
   10단계 6~27절)을 `HardFilterRule` 계약으로 추가한다.
3. `profile_resolver`가 돌려주는 ProfileAttribute를 온톨로지 concept_type과 함께 해석해
   `feature_builder`의 나머지 구성요소(goal/sensory/alcohol/service/usage/behavior/trust,
   business_goal/channel/capacity/region/cooperation/meeting)를 채운다.
4. ~~BUYER/EXHIBITOR 경로와 `calculate_reciprocal_score`(양면 적합도)를 오케스트레이터에
   연결한다.~~ 완료 (위 "BUYER/EXHIBITOR 경로 구현 메모" 참고).
5. 비동기 DB 통합테스트 conftest/fixture 관례를 정하고, 이번 수동 검증 스크립트들(일반
   관람객·바이어 양쪽)을 정식 테스트로 옮긴다.
6. 14단계(상황 재정렬)와 18단계(추천 이유 생성)를 오케스트레이터의 해당 자리에 연결한다.
7. ~~`matching.match_result.recommended_action` CHECK 제약을 5단계 7.2절 어휘와
   `calculate_reciprocal_score`의 상담 어휘(REQUEST_INFORMATION/CONFIRM_TRADE_CONDITION)의
   합집합으로 넓히는 마이그레이션을 추가하고, `_RECIPROCAL_ACTION_MAP`의 손실 있는 매핑을
   제거한다.~~ 완료 (`0008_widen_recommended_action`, 위 "recommended_action 두 어휘
   체계" 참고).
8. ~~`structured_search_exhibitors`가 제품 카테고리(category_concept_ids)를 채우도록
   event_product/product 조인을 추가해, `build_buyer_components`의 `product` 구성요소가
   항상 None이 되는 현재 한계를 없앤다.~~ 완료 (위 "제품 카테고리 연결" 참고).
