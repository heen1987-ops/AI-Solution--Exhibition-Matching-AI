"""AI_SEARCH 트랙 canonical 패키지 (.harness/locks.yaml: AI_SEARCH -> "ai/**").

이 패키지는 자연어 질의 구조화(QueryInterpreter)와 키워드 검색(KeywordRetriever)을 담는다.
packages/search/는 TypeScript 클라이언트 몫이며 이 패키지와는 별개다.

온톨로지 소스는 항상 src/meet_ai/ontology/catalog.v1.json 하나뿐이다(DECISION-004,
.harness/contracts/ontology.yaml). docs/vibe-coding-master-spec-v1.md §30의
INDUSTRY.MANUFACTURING/TECH.AI 같은 예시 코드는 이 패키지 어디에서도 참조하지 않는다.
"""

from __future__ import annotations
