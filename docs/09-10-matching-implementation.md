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
| `hard_filter_engine.py` | 10단계 Hard Filter | 평가 엔진(실행순서, PRODUCTION 단락회로/EXPLAIN 전체평가, UNKNOWN 정책, filter_result 행 변환)은 완전히 구현. 규칙은 가격 상한·필수 서비스 가능여부·MOQ 상한에 더해 생산·공급역량(15절)·유통채널(16절)·공급지역(17절)·OEM/PB/수출 가용상태(18~19절, `rule_availability_status` 하나로 세 규칙을 만든다)까지 9종을 제공한다. 상담 가능성(20절)·일정충돌(21절)·위치·거리(22절)는 프로파일·일정 데이터가 아직 없어 남겨뒀다 |
| `feature_builder.py` | Feature Builder | `CONSUMER_SCORE_V1`(category/price/goal/sensory/alcohol/usage)·`BUYER_SCORE_V1`(product/price/moq/business_goal/channel/region) 구성요소를 채운다. goal/sensory/alcohol/usage/business_goal/channel/region은 `profile_attribute.attribute_code` 접두어(GOAL/TASTE·AROMA/ALCOHOL_LEVEL/USE/BIZ_GOAL/CHANNEL/REGION, docs/06-matching-ontology.md 5.1/8~14절)를 `_COMPONENT_BY_CODE_PREFIX`로 해석해 후보 쪽 concept_id 집합(product_attribute, trade_condition_term)과 교집합 비교한다. service/capacity/cooperation/meeting/behavior/trust는 concept 교집합이 아니라 각각 다른 데이터(상태값 비교, 숫자 비교, 행동 이벤트, 신뢰도 모델)가 필요해 여전히 `None`이다(모듈 docstring 참고) |
| `profile_resolver.py` | Profile Resolver | UserProfile + 최신 ProfileVersion + BuyerNeed + 활성 ProfileAttribute 조회. concept_type 해석은 feature_builder.py가 담당한다(이 모듈은 원본 행만 돌려준다) |
| `context_resolver.py` | Context Resolver | VisitSession + 최신 ContextProfile 조회, recommendation_session.context_snapshot 스냅샷 생성 |
| `request_validator.py` | Request Validator | 사용자 유형·추천 유형 정합성, limit 범위만 검증한다. 연령확인·개인화 동의 검증(profile.user_consent 조회)은 TODO로 남겨두었다 |
| `orchestrator.py` | 파이프라인 오케스트레이션 | GENERAL_VISITOR/PRODUCT 경로(`generate_general_visitor_recommendations`)와 BUYER/EXHIBITOR 경로(`generate_buyer_recommendations`, `calculate_reciprocal_score` 연결 포함) 모두 구조화 검색부터 RecommendationSession/MatchResult/MatchReason/FilterResult 영속화까지 연결했다. GENERAL_VISITOR 경로에는 14단계 상황 재정렬(`context_reranker.py`)과 18단계 추천 이유 생성(`reason_generator.py`)도 연결했다. BUYER 경로는 이유 생성만 아직 템플릿이다(아래 "서비스 계층" 표의 reason_generator.py 행 참고) |
| `context_reranker.py` | 14단계 상황 인지 재정렬 | 기본 적합도(normalized_score)는 그대로 두고 상황 신호로 최종 순위만 다시 매긴다(05단계 5.9절 "기본 적합도와 '지금 방문할 가치'는 분리해 저장한다"). `context_resolver.py`가 실제로 제공하는 신호(남은 체류시간, 다음 확정 일정)만 구현했다 - 부스 대기시간·품절 임박·프로그램 시작시간은 혼잡도 스트림·재고 이벤트가 아직 없어 `ContextSignals`에 훅만 남겼다. 재정렬은 배제가 아니므로 상황이 아무리 나빠도 기본점수의 최소 절반은 남는다(`_CONTEXT_FLOOR`) |
| `reason_generator.py` | 18단계 추천 이유 생성 | `DirectionalScoreResult.contributions`(GENERAL_VISITOR 경로만) 기여도 상위 구성요소를, 내부 점수·구성요소 코드명을 노출하지 않는 정적 템플릿 문구로 바꿔 최대 3개까지 생성한다(05단계 5.11절 "금지 근거"). `ReciprocalScoreResult`(BUYER 경로)는 contributions 필드 자체가 없어 아직 연결하지 못했다 - orchestrator.py의 기존 match_status 기반 템플릿을 유지한다 |

## 검증

- 단위 테스트(`backend/tests/test_candidate_generator.py`, `test_hard_filter_engine.py`,
  `test_feature_builder.py`, `test_context_reranker.py`, `test_reason_generator.py`):
  RRF 병합의 다중채널 가점, 업체별 상한, 후보 풀 절단, PRODUCTION 단락회로 vs EXPLAIN
  전체평가, UNKNOWN 정책, 가격/카테고리/MOQ 구성요소 계산, "정보 없음은 None이지 0이
  아니다", 생산·공급역량/유통채널/공급지역/OEM·PB·수출 가용상태 규칙의 PASS/FAIL/
  CONDITIONAL_PASS 분기, attribute_code 접두어 -> 구성요소 매핑과 그 결과로
  goal/sensory/alcohol/usage/business_goal/channel/region 구성요소가 실제로 교집합
  매칭되는지, 상황 재정렬이 기본점수 높은 후보를 상황이 나쁘면 밀어내면서도 절대
  0점으로 만들지 않는지, 추천 이유가 기여도 순으로 생성되고 내부 구성요소 이름을
  문장에 노출하지 않는지를 모두 확인한다. DB 없이 실행 가능하다.
- DB 통합테스트(`backend/tests/conftest.py`, `test_orchestrator_integration.py`):
  이전에는 수동 스크립트로만 GENERAL_VISITOR/BUYER 경로를 검증했고 정식 pytest에는
  올리지 않았다 - 비동기 DB 통합테스트 conftest/fixture 관례가 이 저장소에 없었기
  때문이다. 이번에 그 관례를 도입해 두 스크립트를 정식 테스트로 옮겼다:
  - `TEST_DATABASE_URL`(기본값 `postgresql+asyncpg://postgres@127.0.0.1:5432/backju_test`)에
    연결할 수 없으면 관련 테스트를 자동으로 건너뛴다 - throwaway Postgres가 없는 환경(CI
    포함)에서도 나머지 스위트는 그대로 통과한다.
  - 연결 가능하면 세션당 한 번 `alembic upgrade head`를 실행한다.
  - `db_session` fixture는 SAVEPOINT 기반 자동 롤백(SQLAlchemy 공식 레시피)을 먼저
    시도했지만 이 스택(SQLAlchemy 2.0 async + asyncpg + greenlet)에서 ORM의 내부
    bind-connection 관리가 greenlet_spawn 밖에서 `conn.begin_nested()`를 호출하는
    경로가 있어 `MissingGreenlet`으로 계속 깨졌다 - 그래서 단순히 커밋하는 세션을
    쓰고, 테스트가 UNIQUE 컬럼에 유니크 접미사를 붙여 충돌을 피하는 방식을 택했다
    (conftest.py/test_orchestrator_integration.py 모듈 docstring에 이유를 남겼다).
  - GENERAL_VISITOR 경로(RecommendationSession 1건, MatchResult 1건, `VISIT_NOW`,
    100.00점, context_score 채워짐), BUYER 경로(`REQUEST_MEETING`), 카테고리 일치
    시나리오가 카테고리 불일치 시나리오보다 raw_score가 높다는 것(구조화 검색의
    category_concept_ids 보정, 위 "제품 카테고리 연결" 참고), sensory(TASTE.*)·
    channel(CHANNEL.*) concept 매칭 시나리오가 불일치 시나리오보다 raw_score가 높다는
    것(feature_builder의 concept 기반 구성요소 연결), 그리고 기여 구성요소마다
    MatchReason이 기여도 순으로 따로 생성되고 내부 이름을 노출하지 않는다는 것(18단계
    reason_generator.py 연결)까지 여섯 시나리오를 검증한다.

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
2. ~~나머지 Hard Filter 규칙(공급지역, 유통채널, OEM/PB, 수출조건, 상담시간, 접근성 등,
   10단계 6~27절)을 `HardFilterRule` 계약으로 추가한다.~~ 부분 완료: 실제 DB 필드가 이미
   있는 생산·공급역량(15절)·유통채널(16절)·공급지역(17절, 지역계층 조회는 온톨로지
   카탈로그 선행 필요)·OEM/PB/수출 가용상태(18~19절)를 추가했다. 상담 가능성(20절)·
   일정충돌(21절)·위치·거리(22절)는 프로파일·일정 데이터 조회 계층이 아직 없어 남아있다.
3. ~~`profile_resolver`가 돌려주는 ProfileAttribute를 온톨로지 concept_type과 함께 해석해
   `feature_builder`의 나머지 구성요소(goal/sensory/alcohol/service/usage/behavior/trust,
   business_goal/channel/capacity/region/cooperation/meeting)를 채운다.~~ 부분 완료:
   attribute_code 접두어 해석으로 goal/sensory/alcohol/usage(CONSUMER)와 business_goal/
   channel/region(BUYER)을 연결했다(위 "서비스 계층" 표 feature_builder.py 행 참고).
   service/capacity/cooperation/meeting/behavior/trust는 concept 교집합이 아닌 다른
   데이터(상태값·숫자 비교, 행동 이벤트, 신뢰도 모델)가 필요해 여전히 미구현이다.
4. ~~BUYER/EXHIBITOR 경로와 `calculate_reciprocal_score`(양면 적합도)를 오케스트레이터에
   연결한다.~~ 완료 (위 "BUYER/EXHIBITOR 경로 구현 메모" 참고).
5. ~~비동기 DB 통합테스트 conftest/fixture 관례를 정하고, 이번 수동 검증 스크립트들(일반
   관람객·바이어 양쪽)을 정식 테스트로 옮긴다.~~ 완료 (`backend/tests/conftest.py`,
   `test_orchestrator_integration.py`, 위 "검증" 절 참고).
6. ~~14단계(상황 재정렬)와 18단계(추천 이유 생성)를 오케스트레이터의 해당 자리에
   연결한다.~~ 부분 완료: GENERAL_VISITOR 경로에 `context_reranker.py`(14단계)와
   `reason_generator.py`(18단계)를 연결했다(위 "서비스 계층" 표 참고). 14단계는
   05단계 5.9절이 언급하는 부스 대기시간·품절 임박·프로그램 시작시간 신호가 아직
   context_resolver.py/스키마에 없어 남은 체류시간·다음 일정만 반영한다. 18단계는
   BUYER 경로(`ReciprocalScoreResult`에 contributions가 없다)에는 아직 연결하지
   못했다.
7. ~~`matching.match_result.recommended_action` CHECK 제약을 5단계 7.2절 어휘와
   `calculate_reciprocal_score`의 상담 어휘(REQUEST_INFORMATION/CONFIRM_TRADE_CONDITION)의
   합집합으로 넓히는 마이그레이션을 추가하고, `_RECIPROCAL_ACTION_MAP`의 손실 있는 매핑을
   제거한다.~~ 완료 (`0008_widen_recommended_action`, 위 "recommended_action 두 어휘
   체계" 참고).
8. ~~`structured_search_exhibitors`가 제품 카테고리(category_concept_ids)를 채우도록
   event_product/product 조인을 추가해, `build_buyer_components`의 `product` 구성요소가
   항상 None이 되는 현재 한계를 없앤다.~~ 완료 (위 "제품 카테고리 연결" 참고).
