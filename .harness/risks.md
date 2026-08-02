# Risks

## RISK-001: 경로 이원화 (backend/frontend vs apps/*)

ASSUMPTION-001로 인해 저장소가 당분간 `backend/`+`frontend/`(레거시) / `apps/kiosk`+`apps/admin`
(신규) 두 명명 체계로 공존한다. 새로 합류하는 워커가 혼동해 잘못된 경로에 파일을 만들 위험.
완화: AGENTS.md와 locks.yaml에 명시, 각 워커 프롬프트가 시작 전 두 파일을 읽도록 강제.

## RISK-002: Google Drive 동기화 경로에서의 로컬 개발 이슈

이 저장소가 `G:\내 드라이브\...`(Google Drive 동기화)에 있어 `npm install`이 tar 압축해제
중 깨질 수 있다(재현 확인됨, frontend/README.md에 문서화). CI 러너는 영향 없음 — 로컬
개발자 경험 이슈.

## RISK-003: 인증이 전부 임시 헤더 스텁

`backend/`의 모든 라우터가 `X-Actor-User-Id`류 헤더로 주체를 임시 수신한다. 실제 세션/JWT
인증이 구현되기 전까지 G3_MVP_RELEASE의 권한시험 게이트를 통과할 수 없다. AUTH 관련 CONTRACT
작업이 명시적으로 backlog에 없음 — 다음 "다음" 사이클에서 우선순위 재검토 필요.

## RISK-004: 매칭 점수 산식 이중화

기존 12단계 문서(바이어 B2B 매칭점수, 10요소 상세 가중치)와 재설계 §34~35(단순화된 웹
개인화점수/바이어매칭점수)가 서로 다른 산식을 제시한다. CONTRACT-003에서 결정하기 전까지는
`backend/app/services/matching/`이 어느 쪽도 확정 반영하지 못한 상태(균등가중치 TODO).

## RISK-005: 온톨로지 위치 불일치

`app/models/matching.py`의 `taxonomy_version_id` FK가 한때 `exhibition.taxonomy_version`을
가리키도록 잘못 작성됐다가 다른 동시 작업 에이전트가 `ontology.taxonomy_version`으로 수정한
이력이 journal에 남아있다(models-match-interaction 에이전트 보고). 재확인 권장.
