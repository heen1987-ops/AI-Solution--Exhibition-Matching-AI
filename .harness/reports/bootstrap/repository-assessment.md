# Repository Assessment (BOOT-001)

> 이 프롬프트(§2)의 원칙에 따라: 기존 구현이 존재하므로 삭제·전면 재작성하지 않는다. 이 저장소는
> "빈 저장소"가 아니라 "기존 코드가 상당히 존재"하는 케이스다. 아래는 실제 발견 내용이다.

## 발견된 기술스택 (요청받은 기본 가정과 대조)

| 영역 | 요청 프롬프트의 기본값 | 실제 발견 | 일치 여부 |
|---|---|---|---|
| JS 패키지관리 | Node 22+, **pnpm workspace** | 루트 `package.json`은 pnpm이 아니라 순수 npm(`type: module`, Netlify Functions용 최소 TS 프로젝트). `frontend/`도 독립 npm 프로젝트(Next.js 14) — workspace 아님 | **불일치** |
| Python | Python 3.12, **uv**, Ruff, mypy | 루트 `pyproject.toml`은 `meet_ai` 온톨로지 패키지(setuptools). `backend/pyproject.toml`은 별도 FastAPI 패키지(setuptools, pip로 설치 확인됨). uv 사용 흔적 없음. Ruff 설정은 `.ruff_cache/` 존재로 사용 중으로 보임 | **부분 일치** |
| 백엔드 프레임워크 | FastAPI/Pydantic/SQLAlchemy/Alembic | 동일 — `backend/`에 이미 구현, 51개 엔드포인트, 15개 마이그레이션(86 테이블) | **일치** |
| DB | PostgreSQL+pgvector | `docker-compose.yml`에 `pgvector/pgvector:pg16` 이미지 이미 구성됨 | **일치** |
| Redis | Redis | `docker-compose.yml`에 `redis:7-alpine` 이미 구성됨 | **일치** |
| Object Storage | S3호환(MinIO 등) | **없음** — docker-compose.yml에 미포함 | **공백** |
| 앱 구조 | `apps/api`, `apps/user-web`, `apps/kiosk`, `apps/admin`, `apps/worker` monorepo | `backend/`(FastAPI, 독립), `frontend/`(Next.js, 독립). `apps/kiosk`, `apps/admin`, `apps/worker`는 존재하지 않음 | **불일치(부분)** |

## 기존 코드 (보존 대상)

- `backend/` — FastAPI 앱. 51개 엔드포인트, SQLAlchemy 모델 15개 파일, Alembic 마이그레이션 15단계(86 테이블). `npm`/`pip install -e .`로 정상 설치, OpenAPI 스키마 정상 추출 확인(`.harness/contracts/openapi.json`).
- `frontend/` — Next.js 14 앱. 20개 라우트, `npm run build` 성공, `npm run typecheck` 에러 0건 확인(단, Google Drive 동기화 경로에서 `npm install`이 깨지는 이슈 있음 — `frontend/README.md` 참고).
- `src/meet_ai/ontology/` — 259개 개념 온톨로지 카탈로그(`catalog.v1.json` + `catalog.py`), `meet-ai-ontology` CLI.
- `netlify/functions/` — TypeScript Netlify Functions(AI 추출 경계, `ontology-extract.ts`).
- `db/migrations/` — 원본 SQL 계약(예: `0001_ontology.sql`, `0002_exhibition.sql`) — Alembic 마이그레이션과 쌍을 이루는 별도 정본.
- `adapters/` — 존재 확인, 상세 내용 미조사(이번 조사 범위 밖).
- `tests/` — 루트 레벨 테스트 디렉터리 존재.
- `docker-compose.yml` — postgres(pgvector) + redis만 구성, MinIO 없음.
- `.harness/` — **이번 세션에서 이미 부트스트랩됨**(FND-001~003, CONTRACT-001~003 진행, BACKEND-008 대기 중). state.json, backlog.yaml, locks.yaml, quality-gates.yaml, assumptions.md(2건), decisions.md(5건), risks.md(5건), expansion-candidates.md(2건), contracts/{openapi.json, domain-model.md, error-codes.yaml, ontology.yaml} 모두 존재.
- `AGENTS.md` — 기존 ChatGPT 스레드 참조 + 이번 세션에서 병합한 하네스 규칙.
- `docs/` — 30단계 설계 로드맵 + 재설계 문서 + 이번 프롬프트 팩 전부 저장되어 있음(`docs/00-roadmap.md`가 인덱스).

## 재사용 대상

- `backend/` → 이 프롬프트의 `apps/api` 역할을 이미 수행 중(ASSUMPTION-001).
- `frontend/` → `apps/user-web` 역할을 이미 수행 중.
- `.harness/**` → 이미 존재. 이번 프롬프트의 BOOT-* 작업 ID 체계가 아니라 FND-*/CONTRACT-*/BACKEND-* 체계로 이미 여러 작업이 DONE 상태.
- `docker-compose.yml` → postgres+redis는 재사용, MinIO만 추가하면 됨.

## 충돌 가능성 (핵심)

1. **모노레포 구조**: 이 프롬프트는 `apps/api`, `apps/user-web`을 명시적으로 요구하지만, 이미
   `backend/`, `frontend/`가 그 역할로 굳어져 있고 여러 동시 작업 에이전트가 그 경로를 참조해
   작업했다(`.harness/decisions.md` DECISION-003, `assumptions.md` ASSUMPTION-001 참고).
   이제 와서 물리적으로 리네임하면 SQLAlchemy 임포트 경로, Alembic 체인, 이미 검증된 빌드
   상태를 다시 검증해야 하는 비용이 크다.
2. **패키지 매니저**: pnpm workspace로 전환하면 `frontend/`와 루트 `package.json`(Netlify
   Functions용)을 워크스페이스 하위 패키지로 재편해야 한다 — 가능하지만 별도 작업.
3. **작업 ID 체계 중복**: 이 프롬프트의 BOOT-001~010이 내가 이미 완료한 FND-001~003,
   CONTRACT-002~003, BACKEND-001~005, USERWEB-001~004와 상당 부분 같은 작업을 가리킨다.
   두 체계를 병행하면 backlog.yaml이 혼란스러워진다.

## 적용한 가정 (이번 조사에서)

- 이번 프롬프트를 "처음부터 새로 만들라"는 지시가 아니라 "누락된 부분(health/live·ready,
  MinIO, harness 검증 스크립트, CI)을 채우고 구조 결정은 재확인하라"는 지시로 해석했다 —
  §2의 "기존 코드가 사용 가능 → 하네스와 구조를 기존 코드에 맞춰 추가" 원칙에 근거.
- 모노레포 구조(BOOT-003, apps/* 전면 전환) 여부는 자동 진행하지 않고 사용자에게 확인한다
  (ASSUMPTION-001을 뒤집는 결정이라 Blocker Score 높음).

## 보존한 파일

`backend/**`, `frontend/**`, `.harness/**`(기존 내용), `docs/**`, `src/meet_ai/**`,
`netlify/**`, `db/**`, `AGENTS.md`, `docker-compose.yml` — 전부 유지, 삭제 없음.

## 새로 생성한 파일 (이번 조사 자체)

`.harness/reports/bootstrap/repository-assessment.md` (본 파일)
