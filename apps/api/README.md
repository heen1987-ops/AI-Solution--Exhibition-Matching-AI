# apps/api/

**의도적으로 비어 있음.** 이 저장소의 FastAPI 앱 정본은 `backend/`다 - 여기에 중복 앱을 만들지 않는다(`.harness/assumptions.md` ASSUMPTION-005). `backend/`는 8개 Alembic 마이그레이션과 94개 테스트를 가진 기존 구현이며, 이를 `apps/api`로 강제 이동하면 상대경로 참조·이중 `pyproject.toml`·`netlify.toml`의 루트 `package.json` 의존 등 여러 곳이 동시에 깨진다.

실행 방법은 `DEVELOPMENT.md`, API 상세는 `backend/README.md` 참고.
