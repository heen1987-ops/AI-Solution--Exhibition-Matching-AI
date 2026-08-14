# 백주대간 초개인화 AI 매칭서비스

기존 `backju.kr`와 CSV·API·웹훅으로 연결되는 독립형 전시회 매칭 플랫폼이다. 모바일 웹 중심(CR-009)
REGISTERED_WEB·GUEST_WEB·BUYER_WEB·ADMIN_PARTNER_WEB 네 채널이 하나의 결정론적 AI 매칭·검색
엔진을 공유하며, 후보검색·필터·점수·양면 적합도·상황 재정렬·다양성/공정성 노출제어 실행 기반은 물론
검증바이어 매칭, 미팅 3게이트 연락처 공개, 업체 문서 업로드→AI추출→확인→승인 파이프라인, 상호작용
분석, 인앱 알림함, Alimtalk 우선 발송함, 운영자 대시보드까지 포함한다. 전용 키오스크(`apps/kiosk`)는
CR-009로 MVP/v1.x 범위에서 제외된 비활성 호환 자산이다.

> `1~15단계` 순차 설계 문서는 2026-08-02 DECISION-001로 중단되고 웹/키오스크 재설계 →
> DECISION-014의 web-first 전환으로 대체됐다. 현재 상태의 유일한 근거는 실제 코드와
> [`.harness/state.json`](./.harness/state.json)이며, 이 문단이 그 문서들과 다르면 이 문단이 진실이다.

## 현재 구현

- FastAPI 모듈러 모놀리스(`apps/api`) — 프로파일/동의/추천/상담/검증바이어매칭/문서구조화/
  상호작용분석/알림/운영자 API, `/healthz`
- Next.js `apps/user-web`(등록방문객/게스트/바이어), `apps/admin`(운영자·업체 파트너), `apps/kiosk`
  (비활성 호환 자산)
- `apps/worker` — 문서파싱·검색색인·분석집계·알림발송큐 비동기 작업 서비스
- 온톨로지 조회·동의어 해석·수치 구간 API `/api/v1/ontology/*`, 259개 v1 개념 정본
- PostgreSQL(`apps/api/alembic/**`, 단일 선형 Alembic 체인)·pgvector 실 의미검색·Redis
- Netlify AI Gateway 기반 자연어 속성 구조화 내부 함수(`netlify/functions/`)

## 빠른 검증

```powershell
# 공통 엔진(src/meet_ai) + 루트 tests/
python -m pip install -e .
python -m pytest -q

# 백엔드(apps/api) — 별도 pyproject, 별도 가상환경/편집설치 필요
cd apps/api
python -m pytest -q

meet-ai-ontology validate
```

FastAPI 실행과 DB 적용 방법은 [`apps/api/README.md`](./apps/api/README.md), 사용자 웹은
[`apps/user-web/README.md`](./apps/user-web/README.md), 관리자 웹은 `apps/admin/`(별도 README 없음,
`apps/user-web/README.md`와 동일한 Next.js/pnpm 실행 방식), 비동기 워커는
[`apps/worker/README.md`](./apps/worker/README.md), 현장 키오스크(비활성 호환 자산)는
[`apps/kiosk/README.md`](./apps/kiosk/README.md), 전체 진행상태는
[`docs/00-roadmap.md`](./docs/00-roadmap.md)와 [`.harness/state.json`](./.harness/state.json)을
참조한다. 이 저장소는 pnpm workspace(`apps/*`, `packages/*`) 모노레포다 — `pnpm install`로
전체 JS/TS 패키지를 설치한다.
