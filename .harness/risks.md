# Risks

| ID | 위험 | 영향 | 완화 |
| --- | --- | --- | --- |
| RSK-001 | `backend/app/services/matching/*`가 API로 노출된 적이 없어(현재 `/api/v1/ontology/*`만 존재) 서비스 계층 설계 당시 가정이 실제 HTTP 계약과 어긋날 수 있다 | G2 지연 | CTR-002(OpenAPI)에서 기존 서비스 계층 함수 시그니처를 1차 근거로 삼아 계약-구현 괴리를 조기에 드러낸다 |
| RSK-002 | Redis가 스키마·설계 문서 전반에서 언급되지만 실제 소비 코드가 없다(캐시 미구현) | G0 판정 왜곡 가능 | `quality-gates.yaml` g0-4를 UNVERIFIED로 명시, FND-004에서 실제 연결만 확인하고 "사용 중"이라고 오판하지 않는다 |
| RSK-003 | `ScoringPolicy.weights` 재조정(`docs/redesign-v2/web/W-5-recommendation-logic.md` §3)이 기존 94개 테스트의 점수 assertion을 깨뜨릴 수 있다 | Wave 2 회귀 | 가중치 변경을 별도 태스크로 분리하고 변경 직후 전체 테스트 재실행을 필수 검증 단계로 고정 |
| RSK-004 | 모노레포 물리 구조(ASSUMPTION-001)와 메타프롬프트 원문 경로 예시가 달라, 향후 다른 협업자가 원문 그대로 `apps/api`를 찾다가 혼동할 수 있다 | 온보딩 비용 | `AGENTS.md`/`ARCHITECTURE.md`에 실제 경로 매핑을 명시적으로 문서화 |
| RSK-005 | `ai.*` 신규 스키마(문서·추출·승인·임베딩)가 완전히 그린필드라 설계 문서만 있고 구현 난이도를 실측하지 못했다 | Wave 2 일정 리스크 | AIS-GROUP-001 착수 전 스파이크(pgvector 성능, LLM 호출 비용) 선행 권장 - Wave 2 세부 분해 시 반영 |
| RSK-006 | npm workspaces에서 `apps/user-web`이 다른 앱과 다른 vitest 메이저 버전을 호이스팅 문제로 참조하는 정황을 WEB-001 작업 중 발견(`.rejects.toThrow(string)` 비호환) | 테스트 결과가 앱마다 미묘하게 달라질 수 있음 | Wave 1 마무리 시점에 FOUNDATION이 각 apps/*/package.json의 vitest 버전을 점검·고정(예: 루트 devDependency로 통일) |
