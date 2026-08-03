# ai/

AI_SEARCH 트랙 소유(`.harness/locks.yaml`). 자연어 검색·추천 관련 "코드가 아닌 아티팩트"(프롬프트, 스키마, 평가셋, 폴백 설정)를 담는다 - 실제 검색·매칭 로직 코드는 `backend/app/services/matching/**`와 `src/meet_ai/scoring/**`에 있다(경로 재매핑 - `.harness/worker-prompts.md`).

- `prompts/` - 자연어 의도 추출 등에 쓰는 LLM 프롬프트 템플릿(C-4). 아직 비어 있음 - C-4/AIS-GROUP-001(Wave 2)에서 채운다.
- `schemas/` - AI 출력 JSON Schema(허용 온톨로지 코드만 사용하도록 검증, AGENTS.md §5 "AI" 규칙). AIS-005에서 `query_output.py`(Pydantic `QueryInterpretation`/`ConceptCondition`)로 채웠다 - 자연어 질의 **해석**만 표현하고 검색 결과·순위는 다루지 않는다. `schemas/tests/`에 이 스키마와(AIS-006의) `SearchProvider`/`MockSearchProvider` 유닛 테스트가 함께 있다(위치 근거는 각 테스트 파일 상단 docstring 참고 - `backend/tests/**`·루트 `tests/**`는 QA_SECURITY 전속 경로라 그쪽에 두지 않았다).
- `evaluation/` - Gold Set·평가 결과(AIS-001, Intent Accuracy/Recall@K/Precision@K/Hallucination Rate 등). AIS-001에서 `queries/{guest-web-ko,consumer-ko,buyer-ko,multilingual}.jsonl`(15건) + `expected/{intent,ontology-mapping,search-relevance}.jsonl` + `schemas/*.schema.json`(Gold Set 형식 검증용, `ai/schemas/`의 런타임 AI 출력 스키마와는 별개)으로 채웠다. `validate_gold_set.py`로 스키마·id 대응·온톨로지 코드 실재 여부를 기계적으로 검증한다.
- `fallback/` - AI 장애 시 폴백 설정(예: 벡터 검색 실패 시 키워드 검색 유지 - 통합 완료조건 "AI 장애 시 키워드 검색 유지"). 아직 비어 있음 - AIS-003(Wave 1, 별도 태스크)에서 채운다.

**금지**: 이 디렉터리에 미승인 업체 데이터, 개인정보, 실제 프로덕션 프롬프트 응답 로그를 저장하지 않는다(AGENTS.md §8).
