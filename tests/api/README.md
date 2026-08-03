# tests/api/

QA_SECURITY 트랙 소유. `backend/tests/`(백엔드 유닛·서비스계층 테스트)와는 다른 층위 두 가지를 담는다:

1. **계약(contract) 내용 검증** (QAS-003, `infra/scripts/validate-harness`가 검사하는
   "하네스 자체"와는 다른 층위 - 이쪽은 `.harness/contracts/*.yaml` 파일의 실제 내용을
   검사한다):
   - `test_openapi_syntax.py` - `.harness/contracts/openapi.yaml`이 문법적으로 유효한
     OpenAPI 3.x 문서인지(`openapi-spec-validator` 사용, 없으면 skip).
   - `test_openapi_operation_ids.py` - 모든 경로에 걸쳐 `operationId` 중복이 없는지.
   - `test_openapi_schema_refs.py` - 모든 `$ref`가 문서 내에서 실제로 해석되는지.
   - `test_openapi_error_envelope.py` - 2xx가 아닌 모든 응답이
     `{error:{code,message,request_id,details}}` 구조를 따르는지.
   - `test_ontology_contract.py` - `.harness/contracts/ontology.yaml`이 파싱되고, 코드마다
     라벨(ko/en)·설명·상위코드 유효성·상태·버전 필드를 갖는지.
   - `test_event_catalog_contract.py` - `.harness/contracts/event-catalog.yaml`이 파싱되고
     이벤트 이름 중복이 없는지.
   - `test_error_codes_contract.py` - `.harness/contracts/error-codes.yaml`이 파싱되고
     코드 중복이 없는지.
   - `test_db_migrations.py` - `cd backend && alembic upgrade head` →
     `downgrade -1` → `upgrade head` 왕복 성공 여부(`TEST_DATABASE_URL` env-gated,
     `backend/tests/conftest.py`와 동일한 관례 - DB 없으면 FAIL이 아니라 SKIP).
   - `_contracts.py` - 위 테스트들이 공유하는 YAML 로더 · `$ref` 리졸버 (테스트 파일
     아님, `test_*.py` 패턴이 아니라 pytest가 수집하지 않음).

   CTR-002/003/004/005/008이 아직 완료되지 않은 시점(DRAFT placeholder)에 작성됐다 -
   내용이 비어 있는 계약 파일에 대해서는 거짓 PASS를 보고하는 대신 명시적으로
   `pytest.skip`한다. CTR-002 등이 완료되면 반드시 재실행할 것 (`.harness/handoffs/qa/
   QAS-003.md` 참고).

2. **API 계약 테스트(향후)**: 실제 배포된 API 엔드포인트가 `openapi.yaml`과 일치하는지
   검증하는 테스트 - 실제 엔드포인트가 아직 없어(`known_gap` 참고, `.harness/state.json`)
   이번 QAS-003 범위에는 포함하지 않았다.

**생성 타입 일치성(Generated-type consistency)은 이번 범위에서 제외**: `packages/
api-client`의 openapi.yaml → TS 타입 코드젠 파이프라인이 아직 없다(Wave 2 예정) - 존재하지
않는 코드젠 산출물을 검사하는 가짜 테스트를 만드는 대신 후속 작업으로 남긴다.
