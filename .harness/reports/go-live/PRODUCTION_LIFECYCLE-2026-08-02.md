# PRODUCTION Lifecycle Decision - 2026-08-02

## 판정

`PRODUCTION_BLOCKED`

첨부된 PRODUCTION 실행 프롬프트는 정식 운영 전환, 집중 모니터링, 출시 후 회고,
v1.1 계획까지의 운영 라이프사이클을 요구한다. 현재 `.harness/state.json` 기준
프로젝트는 `current_wave: 1`, `current_gate: G1_CONTRACT_FREEZE`,
`gate_status: IN_PROGRESS` 상태다. G2_FEATURE_COMPLETE, G3_MVP_RELEASE,
파일럿/RC/정식 배포 상태가 아직 존재하지 않으므로 운영 전환 작업은 실행하지 않는다.

## 차단 근거

- G0_BOOTSTRAP: Docker 기반 health check가 이 환경에서 NOT_RUN으로 남아 있다.
- G1_CONTRACT_FREEZE: 계약/스키마 작업은 상당 부분 완료됐으나 QAS-004/QAS-006 검증이 남아 있다.
- G2_FEATURE_COMPLETE: NOT_STARTED.
- G3_MVP_RELEASE: NOT_STARTED.
- 파일럿/RC/릴리스 상태: `.harness/state.json`에 `release_status`, `pilot_status`,
  `rc_status`, production version 정보가 없다.
- 필수 운영 산출물: `CHANGELOG.md`가 존재하지 않는다.
- 작업트리: 기존 미커밋 변경이 다수 있어 배포 기준 commit_sha를 특정할 수 없다.

## NOT_RUN

- 정식 배포 실행: G2/G3/RC 미충족으로 NOT_RUN.
- DB production migration: 배포 대상/릴리스 버전/승인된 migration window 부재로 NOT_RUN.
- OpenAPI/클라이언트 production compatibility freeze: G1 잔여 검증 미완료로 NOT_RUN.
- 검색 인덱스/AI 프롬프트/feature flag 전환: Wave 2 구현 미착수로 NOT_RUN.
- 집중 모니터링/incident watch: production URL, SLO baseline, telemetry target 부재로 NOT_RUN.
- 출시 후 회고 및 v1.1 계획 확정: 출시 이벤트가 없으므로 NOT_RUN.

## 실제 수행한 복구 작업

- QAS-005를 완료했다.
- `infra/scripts/scope-violation-check`에 키오스크 개인정보 입력필드 정적 검사를 추가했다.
- 읽기 전용 업체정보 표시와 사용자 입력 요소를 구분하기 위해
  `<input>`, `<textarea>`, `<select>` 속성만 검사한다.
- 테스트/fixture 경로는 제외해 반증 테스트가 정적 검사에 걸리지 않도록 했다.
- `QAS-004` 상태를 READY로 정리하고 다음 추천 작업을 `QAS-004`, `QAS-006`으로 갱신했다.
- 묶음 작업 handoff가 하네스 파일명 규칙에 걸리지 않도록 태스크별 pointer handoff를 추가했다.

## 검증

- `python3 -m py_compile infra/scripts/scope-violation-check` 통과.
- `./.venv/bin/ruff check infra/scripts/scope-violation-check` 통과.
- `infra/scripts/scope-violation-check` 통과.
- 키오스크 정적 검사 self-test 통과:
  - 개인정보 입력 fixture는 탐지.
  - 읽기 전용 `exhibitor.name` + 검색 입력은 통과.
  - 테스트 fixture 경로는 제외.
- `cd apps/kiosk && npm test -- --run` 통과: 3 files, 29 tests.
- `infra/scripts/validate-harness` 통과.

## 다음 권장 작업

- `QAS-004`: user-web/kiosk/admin Playwright smoke E2E 하네스.
- `QAS-006`: BAC-001 health API 테스트를 backend/tests에 반영.
- `FND-004`: Docker 사용 가능 환경에서 postgres/redis/backend health 재검증.
- 이후 G1 통과 판정이 가능해지면 Wave 2 기능 구현으로 이동한다.
