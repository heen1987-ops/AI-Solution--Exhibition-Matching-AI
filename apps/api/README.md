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

   의미검색은 기본 비활성이다. 승인된 공개 카탈로그의 pgvector 검색을 사용할 때만
   `.env`의 `SEARCH_EMBEDDING_ENABLED=true`와 전용 공급자 키를 설정하고, 마이그레이션 후
   다음 명령으로 이벤트별 벡터를 백필·활성화한다. 공개 검색의 유료 질의 임베딩 호출에는
   배포 gateway/WAF rate limit을 먼저 적용한다.

   PostgreSQL의 `vector` 확장은 필터드 HNSW iterative scan을 위해 0.8.0 이상이어야 한다.

   ```bash
   python scripts/backfill_catalog_embeddings.py --event-id <EVENT_UUID> --activate
   ```

   현재 카탈로그 필드는 언어별로 분리되어 있지 않으므로 기본 언어 태그는 `und`이며, 모든 키오스크
   세션 언어가 이 공용 벡터를 fallback으로 조회한다. 검색용 SUMMARY에는 해당 참가사의 승인 제품
   공개 텍스트가 포함되며, HNSW 후보 검색은 SUMMARY 행만 사용한다. 8,000-byte 입력 안에서는
   업체명과 모든 제품명을 설명보다 먼저 보존하고, 설명 예산은 제품별로 공정하게 나눈다.

   공급자 또는 벡터 채널이 실패해도 공개 검색은 기존 FTS·키워드·카테고리 경로로 계속된다.
   백필은 공급자 호출 동안 DB 연결을 점유하지 않고, 완료된 배치를 비활성 상태로 커밋한 뒤
   마지막에 전역 catalog source lock 안에서 승인 스냅샷을 재검증하여 활성 포인터만 원자적으로
   교체한다. 업체·참가·제품·행사제품 또는 recommendable membership이 이후 변경되면 DB trigger가
   같은 참가사의 활성 catalog vector를 즉시 비활성화하므로, 다음 백필 전까지 의미 채널은
   fail-closed 상태가 된다. 각 원본 테이블의 `BEFORE STATEMENT` trigger가 행 변경·FK cascade보다 먼저
   전역 catalog advisory lock을 획득하며, 최종 백필도 같은 lock을 사용해 승인 전환 phantom과 활성
   포인터 교체의 순서를 직렬화한다.

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
