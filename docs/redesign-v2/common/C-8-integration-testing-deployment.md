# C-8. 공통 AI·데이터 플랫폼 - 통합시험·배포

근거 문서: `docs/redesign-v2/00-master-spec-v1.md`(§54), `docs/redesign-v2/01-module-split-plan.md`(§4-C C-8, §7). C-1~C-7을 종합해 공통 플랫폼 설계를 마감한다. 이 문서를 끝으로 재설계 진행순서(§7)의 "3차: 공통 AI·데이터 플랫폼"이 완료되고, "4차: 통합 아키텍처·개발 로드맵"으로 넘어간다 - 즉 W-1부터 시작한 이번 재설계 전체(§C-8-1)가 여기서 마무리된다.

## 1. 웹·키오스크 데이터 일치 검증

- [C-5 §1](C-5-common-api.md)에서 "엔드포인트를 이중화하지 않는다"고 결정했으므로, 데이터 불일치 자체가 구조적으로 발생하기 어렵다 - 검증 대상은 "같은 업체를 웹에서 조회한 결과와 키오스크에서 조회한 결과가 (프로파일 결합분을 제외하면) 동일한 승인된 속성을 보여주는지"다.

## 2. 검색결과 일치 검증

- [C-4 §1](C-4-search-recommendation-engine.md)의 "1단계 RRF 공유, 2단계 점수식만 분리" 구조가 실제로 지켜지는지: 동일 자연어 질의를 웹(프로파일 있음)과 키오스크(프로파일 없음)로 각각 넣었을 때, 하드필터로 제외되는 후보 집합은 동일해야 하고(프로파일 무관 규칙만 적용되므로), 순위만 달라야 한다.

## 3. 행사별 설정 검증

- [K-7](../kiosk/K-7-portable-package-structure.md)의 "설정 파일 하나로 재배포" 원칙이 실제로 코드 변경 없이 동작하는지 - 두 번째 행사를 세팅할 때 `kiosk-config.json`만 교체해 배포가 끝나는지가 이 항목의 유일한 검증 기준(§56 "이식형"이라는 이름의 존재 이유).

## 4. 운영배포

- 마스터 스펙 §56의 "복잡한 MLOps 제외" 원칙에 따라, 표준적인 CI/CD(테스트 통과 → 배포) 이상의 정교한 배포 전략(카나리·블루그린 등)은 MVP 범위 밖으로 재확인한다([K-7 §6](../kiosk/K-7-portable-package-structure.md), [K-8 §6](../kiosk/K-8-validation-and-mvp-scope.md)와 동일 원칙의 재적용).

## 5. 로그·통계

- [C-6 §6](C-6-privacy-and-authorization.md)의 이원 로그 체계(`ai_execution_log` + 기존 `audit_log`)와 [C-7 §4](C-7-common-infrastructure.md)의 모니터링 항목이 실제로 [W-9 §5](../web/W-9-admin-operations.md)의 "웹 모듈 기본 통계 3종"(사전등록 연계 건수, 프로파일 완성도 분포, 상담 요청/수락 건수)을 산출하기에 충분한 원본 데이터를 남기는지 확인한다.

## 6. 재설계 전체 완료 선언

`docs/redesign-v2/01-module-split-plan.md` §7이 정의한 순서 - "1차: 웹 초개인화 모듈 W-1~W-10 / 2차: 키오스크 이식모듈 K-1~K-8 / 3차: 공통 AI·데이터 플랫폼 C-1~C-8" - 이 모두 완료되었다.

**각 시리즈가 서로에게 넘긴 미결정 사항이 실제로 다음 시리즈에서 해소됐는지 재추적**: [W-1](../web/W-1-scope-and-user-types.md)의 `DATA_REVIEWER` 질문 → [W-9](../web/W-9-admin-operations.md) → [C-6](C-6-privacy-and-authorization.md)에서 최종 스코프 방식으로 확정. [W-5](../web/W-5-recommendation-logic.md)/[K-4](../kiosk/K-4-natural-language-search-logic.md)의 RRF·가중합 질문 → [C-4](C-4-search-recommendation-engine.md)에서 2계층 구조로 확정. [C-2](C-2-content-collection-ai-structuring.md)의 신규 AI 스키마 → [C-3](C-3-ontology.md)에서 기존 온톨로지와의 정합성 확인, [C-4](C-4-search-recommendation-engine.md)/[C-5](C-5-common-api.md)에서 소비 방식 확정. 미해소로 남은 항목은 없다.

**남은 것은 실제 구현이다** - 설계 문서 26개([W-1~W-10](../web/) 10개, [K-1~K-8](../kiosk/) 8개, [C-1~C-8](.) 8개)에서 나온 실행 항목을 [W-10 §5](../web/W-10-validation-and-mvp-scope.md)의 우선순위 목록을 시작점으로 삼아 구현 착수 순서를 정하고, 마스터 스펙 §7이 예고한 "4차: 통합 아키텍처·개발 로드맵" 문서에서 W/K/C 26개 문서의 실행 항목을 하나의 실행 계획으로 종합한다.
