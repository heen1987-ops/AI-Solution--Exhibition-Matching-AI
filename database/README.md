# database/

**리다이렉트**: 이 저장소의 실제 DB 마이그레이션 정본은 여기가 아니라 `backend/alembic/versions/**`다(`.harness/assumptions.md` ASSUMPTION-005). `migrations/`/`seeds/`/`views/` 하위 디렉터리는 구조 표준화를 위해 존재하지만 실제 SQL을 두지 않는다 - 새 마이그레이션은 항상 `backend/alembic`로 만든다(`cd backend && alembic revision ...`).

- `migrations/` → `backend/alembic/versions/**` (CONTRACTS 트랙 소유, `.harness/locks.yaml`)
- `seeds/` → `meet-ai-ontology` CLI의 SQL 시드 생성 기능(`src/meet_ai/ontology/catalog.py`)이 이미 이 역할을 한다
- `views/` → 아직 DB 뷰가 없음. 필요해지면 `backend/alembic/versions/**`에 마이그레이션으로 추가한다
