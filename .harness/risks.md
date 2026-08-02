# Risks

## RISK-001: 경로 이원화 (backend/frontend vs apps/*)

ASSUMPTION-001로 인해 저장소가 당분간 `backend/`+`frontend/`(레거시) / `apps/kiosk`+`apps/admin`
(신규) 두 명명 체계로 공존한다. 새로 합류하는 워커가 혼동해 잘못된 경로에 파일을 만들 위험.
완화: AGENTS.md와 locks.yaml에 명시, 각 워커 프롬프트가 시작 전 두 파일을 읽도록 강제.

### 2026-08-02 update — RESOLVED

DECISION-006으로 모든 앱이 canonical `apps/*` 구조로 이동해 이 위험은 해소됐다. 위 본문은
ASSUMPTION-001 당시 상태를 보존한다.

## RISK-002: Google Drive 동기화 경로에서의 로컬 개발 이슈

이 저장소가 `G:\내 드라이브\...`(Google Drive 동기화)에 있어 `npm install`이 tar 압축해제
중 깨질 수 있다(재현 확인됨, frontend/README.md에 문서화). CI 러너는 영향 없음 — 로컬
개발자 경험 이슈.

## RISK-003: 인증이 전부 임시 헤더 스텁

`backend/`의 모든 라우터가 `X-Actor-User-Id`류 헤더로 주체를 임시 수신한다. 실제 세션/JWT
인증이 구현되기 전까지 G3_MVP_RELEASE의 권한시험 게이트를 통과할 수 없다. AUTH 관련 CONTRACT
작업이 명시적으로 backlog에 없음 — 다음 "다음" 사이클에서 우선순위 재검토 필요.

### 2026-08-02 update — OPEN

경로 이동 후 재감사 결과, `X-Actor-User-Id`는 `apps/api/app/api/v1/routers/partner.py`에만
직접 사용된다. 다만 profile/recommendations/meetings 등 보호 대상 API도 검증된 세션 principal이
아닌 호출자 제공 식별 헤더에 의존한다. 해결 경로로 CONTRACT-006과 BACKEND-010을 백로그에
추가했으며, 실제 세션/JWT·RBAC·관리자 MFA 적용과 헤더 스텁 제거 전에는 G3 승인을 금지한다.

### 2026-08-03 update — CONTRACT MITIGATED / IMPLEMENTATION OPEN

CR-006과 OpenAPI 0.2.0이 서버 세션·서비스 JWT 검증, tenant/event/resource scope, 역할표,
관리자 AAL2·복구, 개인 링크 교환, 신뢰 헤더 제거 절차를 동결했다. BACKEND-010은 READY로
전환됐지만 구현은 아직 없으므로 위험은 닫지 않는다. 특히 현재 DB 인증수단 enum은
WebAuthn/TOTP/복구를 저장하지 못하며, 검토된 0018 마이그레이션과 spoofing 회귀시험 전에는
보호 API·관리자 기능·G3 권한시험을 완료 처리할 수 없다.

### 2026-08-03 update — IMPLEMENTATION MITIGATED / LIVE VALIDATION PENDING

BACKEND-010과 ADMIN-001이 0018 credential/session 저장소, opaque 링크 교환, 검증된 세션/JWT
principal, event/exhibitor 범위 RBAC, WebAuthn/TOTP/복구, 역할별 관리자 화면을 구현했다. 보호
라우터는 호출자 제공 identity 헤더를 principal로 사용하지 않으며, 쿠키 기반 변경 요청은 허용
Origin과 세션 결합 CSRF를 함께 검증한다. 자동 회귀시험과 OpenAPI/Alembic 검증은 통과했다.
실제 PostgreSQL·실제 WebAuthn RP/브라우저·운영 키 회전 검증은 배포 환경이 준비될 때까지
남아 있으므로 G3 출시 위험을 완전히 닫지는 않는다.

## RISK-004: 매칭 점수 산식 이중화

기존 12단계 문서(바이어 B2B 매칭점수, 10요소 상세 가중치)와 재설계 §34~35(단순화된 웹
개인화점수/바이어매칭점수)가 서로 다른 산식을 제시한다. CONTRACT-003에서 결정하기 전까지는
`backend/app/services/matching/`이 어느 쪽도 확정 반영하지 못한 상태(균등가중치 TODO).

### 2026-08-02 update — OPEN

CONTRACT-003은 API 경로만 결정했다. canonical 경로는 `apps/api/app/services/matching/`이며,
두 산식 중 선택은 AISEARCH-003에서 별도 Change Request 필요 여부부터 판단한다.

## RISK-005: 온톨로지 위치 불일치

`app/models/matching.py`의 `taxonomy_version_id` FK가 한때 `exhibition.taxonomy_version`을
가리키도록 잘못 작성됐다가 다른 동시 작업 에이전트가 `ontology.taxonomy_version`으로 수정한
이력이 journal에 남아있다(models-match-interaction 에이전트 보고). 재확인 권장.

### 2026-08-02 update — RESOLVED

`apps/api/app/models/matching.py`의 FK가 `ontology.taxonomy_version`을 참조하고,
`test_profile_foundation.py`가 잘못된 `exhibition.taxonomy_version` 참조 부재를 검증한다.

## RISK-006: 외부 검색 임베딩 운영 검증 미완료

직접 OpenAI 임베딩 호출은 별도 키, 비용, 외부 egress, 공급자 지연/장애 위험이 있다. 구현은 기본
비활성이고 승인 공개 카탈로그만 백필하며 질의·벡터를 로그에 남기지 않는다. 공급자/pgvector 장애는
semantic=0 fallback으로 격리했다. 다만 실제 키를 사용한 backfill, 비용·지연 측정, PostgreSQL
pgvector 0.8+ SUMMARY partial-HNSW EXPLAIN 및 exact-vs-ANN 회수율, semantic relevance gold set
검증 전에는 G3 승인을 금지한다. 공개 OPEN-event 검색은 의미검색 활성화 시 유료 공급자를 호출하므로
gateway/WAF rate limit 없이 `SEARCH_EMBEDDING_ENABLED=true`로 전환하지 않는다.

### 2026-08-02 update — CODE MITIGATED / LIVE VALIDATION PENDING

집계 SUMMARY가 미승인·삭제 또는 변경된 제품 원문을 계속 사용하는 위험은 0017의 원본/membership
invalidation trigger와 최종 백필이 공유하는 짧은 전역 catalog advisory lock으로 fail-closed 처리했다.
원본 테이블의 `BEFORE STATEMENT` trigger가 행 변경·FK cascade 전에 lock을 획득해 잠금 순서도 고정한다.
긴 첫 제품 설명이 뒤 제품명을 밀어내지 않도록 업체명·제품명을 우선 보존하고 설명 예산을 공정
배분한다. 실제 PostgreSQL에서 trigger 동작과 동시성 경합을 확인하는 통합 검증은 위 G3 운영 항목에
남긴다.
