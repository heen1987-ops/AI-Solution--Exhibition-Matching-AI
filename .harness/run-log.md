# Run Log

## 2026-08-02 — WAVE 0 Bootstrap

- 하네스 디렉터리 구조 생성(`.harness/contracts`, `handoffs/{7개 트랙}`, `reports/{5개 영역}`)
- `AGENTS.md`에 하네스 규칙 병합(기존 ChatGPT 스레드 참조·불변조건은 보존)
- `PROJECT_SCOPE.md` 신규 작성
- `.harness/state.json`, `backlog.yaml`(28개 작업), `locks.yaml`(7개 트랙 소유권),
  `quality-gates.yaml`(4개 게이트 현황), `assumptions.md`(2건), `decisions.md`(3건),
  `risks.md`(5건), `expansion-candidates.md`(2건) 작성
- 기존 구현(backend/ 48엔드포인트·15마이그레이션, frontend/ 20라우트 빌드검증)을 소급 DONE
  처리 — 실제 코드 변경 없음, 상태 기록만
- 다음 작업으로 CONTRACT-002(비공식 계약을 .harness/contracts/**로 승격) 선정 —
  KIOSK-001은 CONTRACT-003(API 경로 조정)에 막혀 있고, CONTRACT-003은 CONTRACT-002에 막혀 있다

FND-001 완료. ARCHITECTURE.md(FND-002)는 다음 사이클로 이월.

## 2026-08-02 — CONTRACT-002

- backend/를 재설치(pip install -e .)해 동시작업 반영 최신화 → 실제 FastAPI 앱에서
  openapi() 스키마 추출, .harness/contracts/openapi.json 저장 (51개 경로)
- .harness/contracts/domain-model.md 작성 (15개 모델 파일 → 스키마 매핑, 공통 컨벤션,
  RISK-005 참조)
- .harness/contracts/error-codes.yaml 작성 (grep 기반, 25개 이상 오류코드 수집 — 완전하지 않음)
- .harness/contracts/ontology.yaml 작성 (259개 개념 카탈로그 메타데이터 스냅샷)
- **중요 발견**: 온톨로지 이중화 문제 — 기존 259개 개념 카탈로그(주류 도메인 특화)와
  재설계 문서 §30 예시 코드(일반 산업박람회용으로 보임)가 다른 도메인처럼 보임.
  CONTRACT-003을 진행하기 전에 사용자 확인 필요(Blocker Score >= 7 판정) — 자동 진행하지 않음.

## 2026-08-02 — 온톨로지 결정 확인 + CONTRACT-003

- 사용자 확인: 기존 259개 개념 카탈로그 유지, 재설계 §30 코드는 템플릿 예시로 폐기 (DECISION-004)
- CONTRACT-003: 재설계 §40과 실제 51개 엔드포인트 대조 완료 (DECISION-005)
  - 네이밍 차이 3건은 기존 유지로 확정
  - 진짜 기능 공백 발견: 공개 업체·부스 조회/검색 API 없음(BACKEND-008 신설, KIOSK-002 최우선 블로커),
    관심목록 API 없음(BACKEND-009 신설)
- G1_CONTRACT_FREEZE 사실상 통과 — contract_status를 FROZEN으로 갱신

## 2026-08-02 — DECISION-006: pnpm+apps/* 모노레포 전환

- backend/ -> apps/api, frontend/ -> apps/user-web 물리 이동 (git mv 아님, 다수 미추적
  파일 때문에 plain mv 사용 — git add는 아직 안 함, 커밋 요청 없었음)
- pnpm-workspace.yaml 신규, 루트 package.json을 워크스페이스 루트로 전환
- 하드코딩 경로 버그 2건 발견·수정(alembic DDL 파일 경로, pytest ROOT 상수) — 상세는 DECISION-006
- 재검증: 백엔드 51 라우트/15마이그레이션(86테이블)/pytest 87+1skip 전부 통과,
  프런트 typecheck 0에러/build 21라우트 통과
- AGENTS.md, PROJECT_SCOPE.md, .harness/locks.yaml, .harness/backlog.yaml(owned_paths),
  README.md, apps/api/README.md, apps/user-web/README.md 경로 참조 갱신
- run-log.md/decisions.md/assumptions.md/risks.md/expansion-candidates.md 등 과거 로그성
  기록은 당시 사실을 그대로 보존(append-only 원칙) — ASSUMPTION-001만 SUPERSEDED 주석 추가

## 2026-08-02 — WAVE 2 공개검색·키오스크 수직 슬라이스

- BACKEND-008 완료: 공개 행사/업체/제품/부스/지도 7개 GET과 익명 검색 POST/GET을
  `/api/v1`에 등록. 승인·활성 필터, 온톨로지 구조화 필터, PostgreSQL FTS, 키워드 fallback,
  WEB/KIOSK 채널별 Redis 검색 세션을 구현했다.
- BACKEND-006 완료: 60~120초 Redis TTL 익명 키오스크 세션, 검색, 서명·만료 QR 발급,
  서버측 handoff 레코드 해시 결합 검증, 게스트 resolve, 명시 종료 API를 구현했다.
  `kiosk.kiosk_session`/`kiosk.kiosk_qr_handoff`에는 PII 컬럼이 없고 Alembic 단일 head는
  `0016_kiosk_session`이다.
- KIOSK-001~004 완료: 별도 `apps/kiosk` Next.js 앱에 K00~K10, 4개 언어, 화면 키보드,
  자연어/카테고리 검색, 결과, 업체상세, 부스지도, QR, 무결과·네트워크 오류·세션종료 화면을
  연결했다. QR 게스트 도착점은 `apps/user-web/app/kiosk-handoff`로 구현했다.
- 계약 갱신: `.harness/contracts/openapi.json` 66경로, domain-model 93테이블,
  error-codes 공개검색·키오스크 항목으로 갱신. G1_CONTRACT_FREEZE를 PASSED로 기록했다.
- 검증: backend pytest 148 passed/2 skipped, 변경범위 Ruff 통과, Alembic single head 확인,
  kiosk Vitest 3 passed + typecheck + production build(12 페이지), user-web typecheck +
  production build(20 페이지), harness JSON/YAML/OpenAPI 파싱 통과.
- 로컬 제약: Google Drive 동기화 경로의 pnpm symlink/rename이 반복 실패해, 잠금파일은
  `pnpm --lockfile-only` 해석 결과를 사용하고 Next.js 검증은 깨끗한 임시 디렉터리 npm 설치로
  수행했다. CI/일반 로컬 디스크에서는 표준 pnpm 명령으로 재검증할 수 있다.

## 2026-08-02 — Canonical root materialization and verification

- Materialized the live project snapshot at `G:/내 드라이브/CODE/Meet AI` while preserving
  `.claude/` and excluding linked-worktree metadata, dependencies, virtual environments, and caches.
- Initialized an independent Git boundary at the requested root on
  `codex/backju-ontology-ai-gateway`; the parent Google Drive repository is no longer selected.
- Fixed four monorepo path/version defects: pytest `../../src`, API editable-install `../..`,
  exhibition DDL output root `parents[3]`, and the live PostgreSQL test head `0016_kiosk_session`.
- Fixed the stale `lib/` ignore rule and restored 19 required `apps/{user-web,kiosk,admin}/lib`
  modules that contain API clients, shared types, auth state, and kiosk session logic.
- Rebuilt the pnpm lock against the active supply-chain policy (Rollup `4.62.3`) and limited
  dependency install scripts to `esbuild` and `unrs-resolver`.
- Evidence: backend `148 passed, 2 skipped`; root/AI `177 passed`; Alembic single head;
  ontology 259 concepts; OpenAPI exact snapshot match (66 paths, 171 schemas); kiosk Vitest
  `3 passed`; all three apps typecheck and production-build (12/13/20 pages); frozen pnpm install
  passes supply-chain verification.
- Remaining external checks: live PostgreSQL/Redis and pgvector semantic retrieval. Full-repo Ruff
  also retains pre-existing style/FastAPI-rule debt and is not a G3-green signal yet.
