# tests/integration/

QA_SECURITY 트랙 소유. 여러 앱/서비스를 함께 기동해야 하는 통합 시나리오(예: user-web → API → DB 왕복). 단일 백엔드 프로세스 내부 통합은 `backend/tests/test_orchestrator_integration.py`(기존 11개)가 이미 담당하므로 중복하지 않는다 - 여기는 프로세스 경계를 넘는 시나리오 전용.
