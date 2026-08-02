# 공통 개발 명령. 기존 패키지 관리자(backend: pip/pyproject, 루트 TS: npm, meet_ai: pip)를
# 그대로 감싼다 - Makefile 자체가 새 도구를 강제하지 않는다(DEVELOPMENT.md 참고).
# apps/user-web, apps/kiosk, apps/admin, apps/worker는 아직 스캐폴딩 중이라 일부
# 타겟은 해당 앱이 실제로 생기기 전까지 조건부로 건너뛴다(있으면 실행, 없으면 스킵).

.PHONY: setup dev infra-up infra-down lint typecheck test test-integration smoke check

setup:
	python -m pip install -e . && \
	cd backend && python -m pip install -e ".[dev]"

dev:
	@echo "backend: cd backend && uvicorn app.main:app --reload"
	@echo "user-web/kiosk/admin: 각 apps/*/ 에서 개별 dev 서버 실행 (앱 생성 후 사용 가능)"

infra-up:
	docker compose up -d

infra-down:
	docker compose down

lint:
	cd backend && ruff check .
	@if [ -f package.json ]; then npm run lint --if-present; fi

typecheck:
	@if [ -f package.json ]; then npm run typecheck --if-present; fi
	@echo "Python: 타입힌트는 코드 리뷰로 확인 (mypy 미도입 - AGENTS.md §3, ADR 필요)"

test:
	python -m unittest discover -s tests -v
	cd backend && pytest

test-integration:
	@echo "backend/tests/test_orchestrator_integration.py는 TEST_DATABASE_URL이 설정된 경우에만 실행된다 (TESTING.md 참고)"
	cd backend && pytest tests/test_orchestrator_integration.py -v

smoke:
	python infra/scripts/validate-harness
	@echo "API 헬스체크: cd backend && uvicorn app.main:app & sleep 1 && curl -sf http://localhost:8000/health/live"

check: lint typecheck test
	python infra/scripts/validate-harness
	python infra/scripts/scope-violation-check
