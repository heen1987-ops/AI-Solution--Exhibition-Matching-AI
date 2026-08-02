# C-3. 공통 AI·데이터 플랫폼 - 관심분야 온톨로지

근거 문서: `docs/redesign-v2/00-master-spec-v1.md`(§6, §57), `docs/redesign-v2/01-module-split-plan.md`(§4-C C-3, §6 "6단계 온톨로지"). [C-2 §5](C-2-content-collection-ai-structuring.md)의 미결정 사항을 확정한다.

## 0. 핵심 결론: C-1/C-2와 반대로, 여기는 이미 성숙한 자산이 있다

`src/meet_ai/ontology/catalog.py`를 확인한 결과, 온톨로지 시스템은 이미 다음을 갖추고 있다: `concept_type`(개념 유형 분류), `taxonomy_version`(semantic_version/status/default_locale/checksum으로 버전 관리), `concept_synonym`(locale·synonym_text·normalized_text·context_type·priority·approval_status·source_type을 갖는 다국어 유사어), `resolve_synonym()`(locale 기반 유사어 해석 함수). **C-2·C-4가 신규 구현 영역인 것과 반대로, C-3은 W-1~W-9·K-1~K-8 전체가 이미 이 자산에 의존해온 안정된 기반이다.**

## 1. 마스터 스펙 §6 카테고리 → 기존 `concept_type`/`attribute_code` 접두어 매핑

이전 세션(웹 모듈 매칭 서비스 구현)에서 실제로 사용된 `attribute_code` 접두어(`_COMPONENT_BY_CODE_PREFIX`, `backend/app/services/matching/feature_builder.py`)를 근거로 매핑한다.

| 마스터 스펙 §6 카테고리 | 기존 접두어/체계 | 비고 |
| --- | --- | --- |
| 산업 | `CATEGORY.*` | [W-5 §1](../web/W-5-recommendation-logic.md)의 `category` 컴포넌트 |
| 기술 | `USE.*` | 활용 기술·용도 |
| 제품·서비스 | `SERVICE.*`(TASTING/PURCHASE 등, [W-4 §6](../web/W-4-profile-model.md)) | |
| 활용목적 | `GOAL.*`/`BIZ_GOAL.*` | [W-4 §3](../web/W-4-profile-model.md) "방문목적" |
| 바이어 거래유형 | `TRADE.*`(OEM/PB/EXPORT), `BUYER.*` | [W-4 §4](../web/W-4-profile-model.md) 거래조건 |
| 유사어·다국어 | `ontology.concept_synonym` | 이미 구현됨(§0) |

**결론**: 마스터 스펙 §6의 6개 카테고리는 전부 이미 존재하는 접두어 체계로 커버된다 - **신규 concept_type이나 신규 테이블이 필요 없다.**

## 2. C-2 미결정 사항 답변

[C-2 §5](C-2-content-collection-ai-structuring.md)에서 넘긴 질문: "`ai.extracted_attribute`가 참조하는 온톨로지 코드가 사용자 프로파일과 완전히 동일한 체계인지" - **답: 그렇다, 완전히 동일한 체계다.** `ontology.concept`/`concept_revision`은 스키마 전체(사용자 프로파일·업체 속성·바이어 거래조건)에 걸쳐 단일 정본(source of truth)이며, `attribute_code`는 어느 쪽에서 쓰이든 같은 `ontology.concept.concept_code`를 정규화한 것이다(이전 세션에서 확인한 `concept_code` CHECK 정규식이 전 도메인에 공통 적용됨). 업체 전용 하위 집합은 없다 - 다만 특정 접두어(`TRADE.*` 등)가 실제로는 바이어·업체 양쪽 맥락에서만 쓰이는 것은 "하위 집합"이 아니라 "그 개념이 그 도메인에만 의미가 있기 때문"일 뿐이다.

## 3. 다국어와 K-6의 관계

[K-6 §1](../kiosk/K-6-i18n-accessibility.md)에서 결정한 지원언어(한국어+영어)는 이미 `concept_synonym.locale` 컬럼이 임의의 locale 값을 다국어로 지원하도록 설계돼 있어 스키마 변경 없이 그대로 수용된다 - K-6에서 신규 유사어 데이터(영어 유사어)를 추가하는 것은 데이터 작업이지 스키마 작업이 아니다.

## 4. C-4로 넘기는 질문

없음 - 온톨로지는 이미 완성된 자산이므로 이 문서에서 모든 항목을 확정했다. C-4(검색·추천 공통엔진)는 이 자산을 소비하기만 하면 된다.
