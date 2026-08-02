# C-4. 공통 AI·데이터 플랫폼 - 검색·추천 공통엔진

근거 문서: `docs/redesign-v2/00-master-spec-v1.md`(§19~22, §57), `docs/redesign-v2/01-module-split-plan.md`(§4-C C-4). [W-5 §6](../web/W-5-recommendation-logic.md), [K-4 §5](../kiosk/K-4-natural-language-search-logic.md), [C-2 §6](C-2-content-collection-ai-structuring.md)에서 이관된 질문을 여기서 모두 확정한다 - 이 문서가 재설계 전체에서 가장 많은 미결정 사항이 모이는 지점이다.

## 1. RRF vs 가중합 - 최종 결정

[W-5 §6-1](../web/W-5-recommendation-logic.md)/[K-4 §5-1](../kiosk/K-4-natural-language-search-logic.md)에서 이관된 질문. **결정: 두 메커니즘을 다른 계층에 배치해 공존시킨다 - 대체하지 않는다.**

```text
1단계(후보 검색, C-4 책임): 여러 채널(구조화 검색·키워드·벡터)을 RRF로 융합
   → "관련 있을 법한 후보 풀"을 순위 매겨 추출
2단계(점수 계산, W-5/K-4 책임): 후보별로 컴포넌트 가중합 점수 계산
   → 웹은 CONSUMER_SCORE_V1/BUYER_SCORE_V1(W-5), 키오스크는 §57 Kiosk Search Score
```

이유: RRF는 "서로 다른 채널의 순위를 어떻게 공정하게 합칠지"에 대한 답이고, 가중합은 "하나로 합쳐진 후보 각각을 실제로 어떻게 채점할지"에 대한 답이다 - 질문 자체가 다르므로 하나가 다른 하나를 대체할 수 없다. 기존 `reciprocal_rank_fusion`(`candidate_generator.py`)은 1단계 그대로 유지하고, §57의 가중합 공식은 2단계(웹은 이미 `ScoringPolicy`, 키오스크는 §2에서 신규 정의)에 적용한다.

## 2. 키오스크 검색 점수(Kiosk Search Score) - 신규 정의

웹은 이미 `ScoringPolicy`(`ScoringPolicy` 재사용, [W-5](../web/W-5-recommendation-logic.md))가 있지만 키오스크는 점수 계산 자체가 없었다([K-4 §0](../kiosk/K-4-natural-language-search-logic.md) "RRF만 있고 가중합 없음"). §57의 구성(0.45 Semantic + 0.30 Keyword + 0.15 Category + 0.05 Data Quality + 0.05 Booth Availability)을 `meet_ai.scoring`에 `KIOSK_SEARCH_SCORE_V1`(신규 `ScoringPolicy`)로 추가한다 - **웹의 `CONSUMER_SCORE_V1`과 나란히 두는 것이지, 그것을 변형해 재사용하는 것이 아니다** - 키오스크는 사용자 프로파일이 없으므로(`GENERAL_REGISTERED`용 `goal`/`sensory` 같은 프로파일 기반 컴포넌트가 원천적으로 성립하지 않음, [W-1 §1](../web/W-1-scope-and-user-types.md)), 완전히 별개의 정책 객체가 맞다.

| 컴포넌트 | 데이터 소스 |
| --- | --- |
| Semantic(0.45) | 벡터 검색 채널의 유사도 점수(§3 신규 구현) |
| Keyword(0.30) | 키워드(FTS) 채널의 랭크 점수(§3 신규 구현) |
| Category(0.15) | 구조화 검색(기존 `structured_search_exhibitors`)의 concept 일치 여부 |
| Data Quality(0.05) | [C-2](C-2-content-collection-ai-structuring.md)의 `data_completeness_percent`(기존 컬럼, 신규 아님) |
| Booth Availability(0.05) | [W-2 §1-8](../web/W-2-user-journey.md)/기존 `context_reranker.py`가 이미 계산하는 대기시간 신호 재사용 |

## 3. 신규 구현이 필요한 검색 채널

- **키워드 검색(FTS)**: PostgreSQL Full-Text Search를 `Product`/`Exhibitor`의 텍스트 컬럼(업체소개, 제품명 등)에 적용 - 마스터 스펙 §5(기술 스택)가 이미 "PostgreSQL+FTS"를 명시하고 있으므로 별도 검색엔진(Elasticsearch 등) 도입 없이 구현 가능.
- **벡터 검색**: 마스터 스펙 §5가 명시한 pgvector 확장을 사용. `ai.embedding_document`/`ai.embedding_vector`(§6 데이터 모델, [C-2](C-2-content-collection-ai-structuring.md)와 마찬가지로 현재 스키마에 없는 신규 테이블) - 업체·제품 설명 텍스트를 임베딩해 저장하고, 자연어 질의 임베딩과 코사인 유사도로 비교.
- **자연어 의도 추출**: 사용자 자연어 문장 → concept_id 목록 - LLM 호출 1회로 처리(마스터 스펙 §5 AI 스택 참고). 추출 결과는 `ai.ai_execution_log`([C-2 §2](C-2-content-collection-ai-structuring.md))에 기록.

## 4. 미승인 업체 차단 메커니즘 - 최종 결정

[C-2 §4](C-2-content-collection-ai-structuring.md)에서 넘긴 질문. **결정: `Recommendable` 레지스트리 등록 시점에 `master_approval_status = 'APPROVED'` 조건을 만족한 업체·제품만 레지스트리 행을 생성한다(사후 비활성 플래그 방식이 아니라 사전 등록 게이트 방식).**

이유: 사후 비활성 플래그 방식은 "일단 다 등록하고 검색 쿼리마다 필터링"인데, 이는 검색 성능(모든 쿼리에 조인 조건 추가)과 실수 위험(필터를 빠뜨린 신규 쿼리 경로가 생기면 미승인 데이터가 새어나감) 양쪽에서 불리하다. 사전 게이트 방식은 승인 전에는 애초에 검색 대상 풀에 존재하지 않으므로 구조적으로 안전하다. `master_approval_status`가 `APPROVED`에서 다른 상태로 되돌아가는 경우(재검토 등)에는 레지스트리 행을 비활성화(삭제가 아니라 soft-delete)하는 서비스 로직이 필요하다.

## 5. 관련성 랭킹·추천 이유 - 재사용 재확인

- 하드필터(`hard_filter_engine.py`)·컨텍스트 재랭킹(`context_reranker.py`)·추천 이유 생성(`reason_generator.py`)은 [W-5 §4](../web/W-5-recommendation-logic.md)에서 이미 "그대로 재사용"으로 확정했다 - 키오스크도 동일 엔진을 공유한다(01-module-split-plan.md §2.3 원칙). 단, 키오스크는 하드필터 평가 시 "사용자 프로파일" 입력이 없으므로, 하드필터 규칙 중 프로파일 필요 규칙(예: 바이어 전용 규칙)은 애초에 키오스크 경로에서 평가 대상이 아니다 - 이는 새 예외 처리가 아니라 "필요한 입력이 없으니 해당 규칙이 적용되지 않는다"는 자연스러운 결과다.

## 6. C-5로 넘기는 질문

1. 벡터 임베딩 재계산 트리거(업체 정보 수정 시 즉시 재임베딩인지, 배치인지) - C-5(공통 API)/C-7(공통 인프라)에서 워커 설계와 함께 결정.
