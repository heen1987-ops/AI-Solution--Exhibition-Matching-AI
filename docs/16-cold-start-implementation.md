# 16단계 콜드스타트 구현

## 구현 범위

초기 사용자·바이어와 신규 업체를 별도 상태로 판정하되 기존 관련성 점수를 바꾸지 않는 정책 오버레이를 구현했다.

- 사용자 상태: `COLD`, `WARMING`, `STABLE`, `RESET`
- 일반 관람객·바이어별 안정화 조건과 탐색 비율
- 추천 신뢰도 상한과 사용자에게 제시할 다음 질문 코드
- 신규 제품·업체의 승인·정보 완성도·거래 준비도·운영상태 품질 게이트
- 탐색 슬롯과 취향 학습 슬롯을 다양성 슬레이트에 전달
- 정책 버전, 입력 지문, 상태, 품질, 사유, 추천 신뢰도 영속화

관련 구현:

- `backend/app/services/matching/cold_start_policy.py`
- `backend/app/services/matching/cold_start_runtime.py`
- `backend/app/models/cold_start.py`
- `backend/alembic/versions/20260802_0012_cold_start.py`
- `backend/app/api/v1/routers/adaptive.py`

## 파이프라인 위치

```text
기본 점수·양면 적합도
→ 상황 재정렬
→ 콜드스타트 상태·신뢰도·탐색 후보 주석
→ 다양성·공정성 슬레이트
→ 결과·계보 저장
```

콜드스타트 정책은 `final_score`를 변경하지 않는다. 추천 신뢰도와 탐색 자격만 주석으로 추가하며, 최종 슬레이트가 정책상 허용된 탐색 개수와 업체별 상한을 적용한다.

## API

- `GET /api/v1/profiles/{profile_id}/cold-start`
- `POST /api/v1/profiles/{profile_id}/cold-start/answers`
- `GET /api/v1/profiles/{profile_id}/next-best-question`
- 추천 결과의 `recommendation_confidence`, `cold_start_status`, `cold_start_reason_codes`

서명된 사이트 컨텍스트의 `profile_id`와 URL의 `profile_id`가 다르면 403을 반환한다. 버전 충돌은 409, 비활성 질문은 422로 구분한다.

## 검증

- 신규·안정 사용자와 바이어별 탐색 상한
- 신규 업체 품질 게이트
- 관련성 점수 불변
- 최종 탐색 주석까지 포함한 입력 지문
- 정보이득 계산과 베이지안 사전 검증
- Alembic 단일 head 및 오프라인 SQL 생성

테스트: `backend/tests/test_cold_start_policy.py`, `backend/tests/test_result_store_contract.py`

## 운영 제한

- 밴딧 온라인 학습은 비활성화한다.
- 인기순은 후보 부족 시 보완 수단으로만 사용한다.
- 민감·보호 속성을 추론하지 않는다.
- 미확인 신규 업체는 관련성이 높아도 품질 탐색 슬롯에 넣지 않는다.
