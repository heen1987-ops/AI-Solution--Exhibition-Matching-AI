# TESTING.md

## 현재 테스트 자산 (이전 세션 기준 - 신규 코드 추가 시 재검증 필요)

- 유닛 테스트: `backend/tests/test_*.py` 9개 파일(피처빌더·하드필터·컨텍스트재랭킹·이유생성·온톨로지 API 등).
- DB 통합 테스트: `backend/tests/test_orchestrator_integration.py` - 실제 Postgres 대상, `conftest.py`가 세션별 커밋 방식(SAVEPOINT 자동 롤백 방식은 SQLAlchemy 2.0 async+asyncpg+greenlet 조합에서 `MissingGreenlet` 오류로 채택하지 않음 - 대신 유니크 접미사 기반 테스트 데이터 사용).
- 루트 `tests/`: `unittest` 기반, `meet_ai` 패키지(온톨로지 카탈로그 등) 대상.

## 실행 방법

```bash
# 백엔드
cd backend && pytest

# meet_ai 코어
python -m unittest discover -s tests -v
meet-ai-ontology validate
```

## 완료조건 (AGENTS.md §9, quality-gates.yaml과 연동)

- Lint(ruff)/Type Check 통과 없이 작업 완료 처리 금지.
- 관련 Unit/Integration Test 통과 없이 작업 완료 처리 금지.
- 테스트 실패를 무시하고 완료 처리하지 않는다 - 실패 시 원인분석 후 재시도하거나 태스크를 `blocked`로 표시한다.

## DB 통합 테스트 환경변수

`backend/tests/conftest.py`가 요구하는 테스트 DB URL 환경변수를 확인한다(env-gated) - 로컬 `docker compose up -d` 기동 후 `alembic upgrade head`가 세션 시작 시 자동 실행된다.

## 신규 태스크 착수 전 회귀 기준선

`ScoringPolicy.weights` 재조정(`CTR` 이후 Wave 2)처럼 점수 계산 로직을 바꾸는 태스크는 반드시 변경 직후 전체 테스트를 재실행하고, 실패한 assertion이 "버그"가 아니라 "새 가중치를 반영한 기대값 갱신"인지 구분해 기록한다(`.harness/risks.md` RSK-003).

## AI Gold Set (Wave 1 `AIS-001` 이후)

`backend/tests/fixtures/gold_set/`에 질의-기대결과 쌍을 저장하고, G3_MVP_RELEASE의 "AI Gold Set 기준 통과"는 이 셋 기준으로 판정한다.

## 리포트 저장 위치

Lint/테스트/보안/성능/통합 결과는 `.harness/reports/{lint,tests,security,performance,integration}/`에 저장한다(사람이 손으로 편집하지 않음).
