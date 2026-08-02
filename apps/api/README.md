# Backju AI Matching Service - Backend

FastAPI 기반 백엔드. 설계 근거는 다음 문서를 따른다.

- API 계약: `docs/frontend-backend-ai-interface-spec.md`
- DB 정의: `docs/db-erd-table-spec.md`
- 온톨로지 계약: `docs/06-matching-ontology.md`
- 도메인 상세: `docs/07-user-profile-model.md`, `docs/08-exhibitor-product-profile-model.md` 등 단계별 문서

## 요구 사항

- Python 3.11 이상
- Docker / Docker Compose (로컬 PostgreSQL·Redis 실행용)

## 로컬 실행

1. 인프라(PostgreSQL + pgvector, Redis) 기동

   ```bash
   docker-compose up -d
   ```

   레포 루트에서 실행한다 (`docker-compose.yml`이 루트에 있음).

2. 환경변수 설정

   ```bash
   cd apps/api
   cp .env.example .env
   # 필요시 .env 값 수정
   ```

3. 의존성 설치 (가상환경 권장)

   ```bash
   python -m venv .venv
   source .venv/bin/activate   # Windows: .venv\Scripts\activate
   pip install -e "../.." -e ".[dev]"
   ```

4. DB 마이그레이션 적용

   ```bash
   alembic upgrade head
   ```

   최초 마이그레이션은 논리 스키마를 만들고, 다음 마이그레이션은 버전형 온톨로지 테이블과
   불변성 트리거를 생성한다. 카탈로그 시드는 루트에서 `meet-ai-ontology emit-sql`로 생성한다.

5. 서버 실행

   ```bash
   uvicorn app.main:app --reload
   ```

   - 헬스체크: `GET http://localhost:8000/healthz`
   - API 문서: `http://localhost:8000/docs`
   - API 기본 경로: `/api/v1` (`docs/frontend-backend-ai-interface-spec.md` 4.1절)
   - 온톨로지: `GET http://localhost:8000/api/v1/ontology`
   - 공개 행사·업체·부스: `GET /api/v1/events/{event_id}`, `GET /api/v1/events/{event_id}/exhibitors`
   - 익명 검색: `POST /api/v1/search`
   - 키오스크: `GET /api/v1/kiosk/config/{kiosk_id}`, `POST /api/v1/kiosk/sessions`

## 디렉터리 구조

```text
apps/api/
  app/
    core/config.py      # pydantic-settings 기반 환경설정
    db/session.py       # SQLAlchemy async 엔진/세션 (지연 초기화)
    db/base.py           # DeclarativeBase, 스키마 규약
    api/v1/api.py         # v1 라우터 애그리게이터 (각 도메인 라우터가 여기 include_router)
    main.py                # FastAPI 앱 생성, CORS, /healthz, /api/v1 마운트
  alembic/                  # DB 마이그레이션
  pyproject.toml
  .env.example
```

## 설계 메모

- DB 연결은 앱 임포트 시점이 아니라 요청 처리 중 `Depends(get_db)`가 호출되는 시점에 이루어진다.
  즉 PostgreSQL/Redis가 떠 있지 않아도 `uvicorn app.main:app`을 기동하거나
  `import app.main`을 하는 것 자체는 실패하지 않는다 (다만 실제 DB를 쓰는 요청은 실패한다).
- `app/api/v1/api.py`의 `api_router`와 `app/main.py`는 여러 에이전트가 함께 채워나가는 공용
  파일이다. 새 도메인 라우터를 추가할 때는 `api_router.include_router(...)` 한 줄만 더하고,
  기존 구조(APIRouter 생성부, FastAPI 앱 생성부)는 건드리지 않는다.
- 매칭 코드값은 Python enum으로 복제하지 않고 `ontology.taxonomy_version`과
  `ontology.concept_revision`으로 버전화한다. 정본 v1 카탈로그는
  `src/meet_ai/ontology/catalog.v1.json`이며 CLI가 검증과 결정적 SQL 생성을 담당한다.
