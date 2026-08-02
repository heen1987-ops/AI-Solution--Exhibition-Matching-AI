# K-4. 키오스크 이식형 검색모듈 - 자연어 검색 로직

근거 문서: `docs/redesign-v2/00-master-spec-v1.md`(§19~21), `docs/redesign-v2/01-module-split-plan.md`(§4-B K-4). [K-3 §4](K-3-screen-ia.md)의 미결정 사항(최소 추가질문 트리거 조건)을 확정하고, 검색 로직의 기존 자산 재사용 범위를 정리한다.

## 0. 기존 자산 대조 결과: 절반은 있고 절반은 없다

`backend/app/services/matching/candidate_generator.py`를 확인한 결과:

- **이미 있음**: `reciprocal_rank_fusion`(여러 검색 채널의 결과를 순위 기반으로 융합하는 RRF), `structured_search_exhibitors`/`structured_search_products`(온톨로지 concept_id 기반 구조화 검색), `enforce_object_owner_cap`(한 업체가 결과를 독점하지 않도록 캡을 씌우는 로직).
- **아직 없음**: 자연어 문장 → 의도/조건 추출(§19), 키워드 검색(FTS), 벡터 검색 - 이전 세션에서 이미 "vector/behavior/popularity search는 `ai.object_embedding` 등 인프라 부재로 막혀 있다"고 확인된 바 있다.

**결론**: K-4는 "새 검색 로직을 설계"하는 것이 아니라, **RRF 융합 프레임워크에 새 채널(자연어 의도 추출 → 키워드/벡터 검색)을 추가하는 작업**이다. 이 신규 채널 자체의 구현은 C-4(공통 검색·추천 엔진)의 책임이며, K-4는 "키오스크가 그 채널을 어떻게 호출·소비하는지"만 정의한다.

## 1. 관심영역 추출

- 자연어 문장에서 관심분야(온톨로지 concept)를 추출하는 것은 C-4의 책임. 키오스크는 추출된 concept_id 목록을 받아 `structured_search_exhibitors`/`structured_search_products`(이미 구현됨)에 그대로 넘긴다 - **키오스크 전용 추출 로직을 별도로 만들지 않는다.**
- [K-2 §3](K-2-user-flow.md)에서 이미 "카테고리 선택 = concept_id를 직접 지정한 자연어 검색"으로 통일했으므로, 카테고리 선택 경로는 추출 단계를 건너뛰고 바로 구조화 검색으로 들어간다.

## 2. 업체·제품·부스 검색

- `structured_search_exhibitors`/`structured_search_products`를 그대로 재사용한다. 부스 검색은 이 함수들이 반환하는 업체·제품 결과에서 소속 부스를 조인하는 것으로 충분 - 별도의 "부스 검색" 채널을 새로 만들 필요가 없다(부스는 업체의 속성이지 독립된 검색 축이 아니다).
- **웹 모듈과의 차이**: [W-5 §5](../web/W-5-recommendation-logic.md)에서 확인했듯 웹은 여기에 사용자 프로파일 컴포넌트를 추가로 결합하지만, 키오스크는 결합하지 않는다 - `enforce_object_owner_cap`까지의 순수 RRF 결과가 곧 최종 결과다.

## 3. 검색결과 랭킹

- 기존 `reciprocal_rank_fusion`의 랭킹 방식(순위 기반 융합)을 그대로 사용한다. 마스터 스펙 §57의 "Kiosk Search Score"(0.45 Semantic + 0.30 Keyword + 0.15 Category + 0.05 Data Quality + 0.05 Booth Availability)는 **RRF와 다른 방식(가중합)**이다 - 두 방식을 어떻게 통합할지가 미결정 사항이다(§5).

## 4. 결과 없음 처리 · 최소 추가질문 - 트리거 조건 확정

[K-3 §4](K-3-screen-ia.md)에서 넘긴 질문에 답한다.

- **결과 0건**: 추출된 concept이 너무 좁거나 오타 등으로 매칭이 없는 경우 - 온톨로지 상위 개념으로 자동 확장 1단계(예: 특정 제품 하위 카테고리 → 상위 카테고리)를 먼저 시도하고, 그래도 0건이면 "최소 추가질문"(선택지 2~3개)을 1회 노출한다.
- **결과 과다(예: 50건 초과)**: 추가질문을 띄우지 않는다 - 상위 N개(K-3 결과목록 화면의 페이지네이션/캡)만 보여주고 사용자가 스스로 좁히도록 둔다. 결과가 많다는 것은 검색이 실패한 것이 아니라 성공적으로 넓은 카테고리를 찾은 것이므로, 인위적으로 질문을 끼워 넣지 않는다.
- 즉 "최소 추가질문"은 **결과 0건일 때만** 트리거된다 - [K-3 §2-1](K-3-screen-ia.md)에서 "empty state의 한 형태"로 분류한 것과 일치한다.

## 5. C-4로 넘기는 질문

1. RRF(순위 기반 융합)와 마스터 스펙 §57의 가중합 방식(Semantic/Keyword/Category/Data Quality/Booth Availability) 중 어느 것을 최종 채택할지 - 두 방식을 유지한 채 특정 채널(예: 부스 가용성)만 후처리로 반영할지, 아니면 RRF 자체를 가중합으로 대체할지는 C-4(검색·추천 공통엔진) 설계 시점에 결정한다. **이 결정은 웹 모듈([W-5](../web/W-5-recommendation-logic.md))의 점수식과도 연동되므로, C-4에서 웹·키오스크 양쪽에 미치는 영향을 함께 검토해야 한다.**
2. 온톨로지 상위 개념 자동 확장(§4 "결과 0건" 처리)의 구체적 알고리즘(몇 단계까지 확장할지) - C-4에서.
