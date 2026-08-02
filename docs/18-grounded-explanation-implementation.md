# 18단계 구현 — 근거 기반 추천 이유

## 구현 결과

추천 결과마다 사용자에게 노출할 이유와 그 이유를 재현할 수 있는 계보를 함께 저장한다. 생성형 모델이 자유롭게 이유를 만들어 내는 방식은 사용하지 않으며, 승인된 특성 키에 대응하는 템플릿만 허용한다.

핵심 계약은 다음과 같다.

- 일반 관람객과 바이어의 허용 근거 템플릿을 분리한다.
- 성별·연령·스폰서 여부 등 허용 목록 밖의 신호는 설명에 사용하지 않는다.
- 각 이유에 사용자 프로파일 버전과 추천 대상 속성의 근거 참조를 연결한다.
- 정책 버전과 SHA-256 입력 지문을 저장해 동일한 설명을 재현한다.
- 이유가 없는 결과는 저장하지 않는다.
- 직접 일치 근거가 없으면 적합하다고 단정하지 않고 `EXPLORATION_CANDIDATE`로 표시한다.
- 사용자 화면에는 기여도가 높은 이유를 최대 세 개만 노출한다.

## 구현 위치

- 생성 정책: `backend/app/services/matching/explanation_generator.py`
- 파이프라인 계약: `backend/app/services/matching/types.py`
- 저장 검증·영속화: `backend/app/services/matching/result_store.py`
- 영속 모델: `backend/app/models/matching.py`
- 마이그레이션: `backend/alembic/versions/20260802_0014_explanation_lineage.py`
- 정책·근거 테스트: `backend/tests/test_explanation_generator.py`
- 저장 계약 테스트: `backend/tests/test_result_store_contract.py`

## 영속 데이터

`matching.match_reason`에 다음 필드를 추가했다.

| 필드 | 의미 |
|---|---|
| `explanation_policy_version` | 이유를 만든 게시 정책 버전 |
| `input_fingerprint` | 코드·문장·근거·기여도·생성방식의 SHA-256 지문 |

기존 레코드는 마이그레이션에서 레거시 버전과 고정 지문으로 이관하고, 신규 레코드는 두 필드를 필수로 저장한다.

## 실패 차단

결과 저장 직전에 다음 조건을 검증한다.

- 추천 결과마다 최소 한 개의 이유가 있는가
- 현재 게시된 설명 정책 버전과 일치하는가
- 입력 지문이 64자리인가
- 최소 한 개의 근거 참조가 있는가
- LLM 생성 이유라면 검증된 `ai_run_id`가 있는가

하나라도 충족하지 않으면 추천 세션을 성공으로 기록하지 않는다.

## 검증 범위

- 소비자용 특성 근거 및 프로파일 버전 연결
- 바이어용 거래 근거 템플릿 분리
- 민감·광고 신호 비노출
- 전역 기여도 정렬과 최대 세 개 제한
- 근거 부족 시 탐색 후보 표현
- 정책 버전·입력 지문의 DB 저장
- Alembic 단일 헤드와 오프라인 SQL 생성
