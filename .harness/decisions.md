# Decisions

## DECISION-001 (2026-08-02)

기존 30단계 순차 설계 트랙(1~12단계 완료)을 12단계에서 중단하고, 웹 초개인화/키오스크 검색/
공통 AI플랫폼 3모듈 재설계로 전환한다. 상세: [docs/redesign-web-kiosk-split.md](../docs/redesign-web-kiosk-split.md)

## DECISION-002 (2026-08-02)

병렬개발 하네스(`.harness/`)를 이 저장소에 도입하고, Claude(이 세션)도 오케스트레이터/워커
역할을 함께 수행한다(Codex 전용이 아님) — 사용자 명시적 지시.

## DECISION-003 (2026-08-02)

ASSUMPTION-001, ASSUMPTION-002 참고 — 기존 `backend/`+`frontend/`를 유지하고 신규 트랙만
canonical 경로(`apps/*`)로 만든다.

## DECISION-004 (2026-08-02) — 사용자 확인됨 (Blocker Score >= 7)

기존 259개 개념 온톨로지 카탈로그(`src/meet_ai/ontology/catalog.v1.json`, 백주대간 주류
도메인 특화)를 그대로 유지한다. 재설계 문서(`docs/vibe-coding-master-spec-v1.md` §30)의
`INDUSTRY.MANUFACTURING`/`TECH.AI` 등 예시 코드는 원본 프롬프트 템플릿(범용 산업박람회)에서
가져온 예시일 뿐, 실제 구현 스펙이 아닌 것으로 확정. 앞으로 온톨로지 관련 모든 작업은
259개 카탈로그를 유일한 소스로 취급한다.

## DECISION-006 (2026-08-02) — 사용자 확인됨: pnpm+apps/* 정식 모노레포 전환

`backend/`→`apps/api`, `frontend/`→`apps/user-web` 물리 이동 완료. `pnpm-workspace.yaml`
(`apps/*`, `packages/*`) 추가, 루트 `package.json`을 워크스페이스 루트로 전환(기존 Netlify
Functions 의존성은 유지). ASSUMPTION-001은 이 결정으로 SUPERSEDED.

이동 중 발견·수정한 실제 버그(2건, 둘 다 `Path(__file__).resolve().parents[N]`의 하드코딩된
깊이가 `apps/` 한 단계 추가로 어긋난 것):
- `apps/api/alembic/versions/20260801_0001_0002_ontology.py`, `..._0004_0005_exhibition.py`:
  `parents[3]` → `parents[4]`로 수정(원본 SQL 계약 파일 경로 재계산).
- `apps/api/tests/test_profile_foundation.py`, `test_exhibitor_models.py`: `ROOT` 계산과
  하드코딩된 `"backend"` 문자열 세그먼트를 정리(`APP_ROOT`/`REPO_ROOT`로 분리).

재검증 결과: 백엔드 51개 API 정상 임포트, 15단계 마이그레이션 SQL 컴파일 정상(86 테이블),
pytest 87 passed/1 skipped. 프런트 typecheck 0 에러, `next build` 21개 라우트 정상(로컬 C:
드라이브 사본에서 검증 — Google Drive 경로 이슈는 여전함, RISK-002 참고).

## DECISION-005 (2026-08-02) — CONTRACT-003 API 경로 대조 결과

재설계 문서 §40의 API 경로 목록과 실제 구현된 51개 엔드포인트(`.harness/contracts/openapi.json`)를
대조한 결과, 대부분은 "경로 이름이 다른" 문제가 아니라 "기능 자체가 아직 없는" 진짜 공백이었다.

**네이밍만 다른 것(그대로 둠, 재설계 쪽 이름으로 안 바꿈 — ASSUMPTION-002 연장)**:
- `/me/event-profile` (재설계) ↔ `/profiles/me` (기존, 유지)
- `/buyer/matches` (재설계) ↔ `/recommendations`(user_type=BUYER로 처리, 기존 유지)
- `/events/{id}/registration/sync` (재설계) ↔ `/admin/imports/visitors`(관리자 배치, 기존 유지 — 사용자 자가연동 흐름은 없음, 필요시 별도 검토)

**진짜 기능 공백(신규 작업으로 backlog에 추가)**:
- 공개 업체·부스 목록/상세 조회 API 없음 (`GET /events/{id}/exhibitors`, `GET /booths/{id}` 등) — 지금은 파트너 인증 컨텍스트의 `/exhibitors/{id}/profile`만 있음. 웹·키오스크 모두 필요 → **BACKEND-008**
- 자연어/카테고리 "검색" API 없음 — `/recommendations`는 개인화 추천이지 검색이 아님. 키오스크는 프로파일이 없으므로 검색 전용 엔드포인트가 반드시 필요 → **BACKEND-008**에 포함
- 관심목록(즐겨찾기) API 없음 — `/interactions/batch`로 이벤트는 기록되지만 CRUD가 없음 → **BACKEND-009**
- 관리자 승인/반려/분석 API 없음 (`/admin/exhibitors/{id}/approve` 등) — `/partner/exhibitors/{id}/submit`(제출)까지만 있고 운영자 승인 액션이 없음 → 기존 **BACKEND-007**로 충분히 커버됨(범위 갱신)
- 키오스크 세션 API 전체 없음 → 기존 **BACKEND-006** 그대로
