# 17단계 행동학습·피드백 구현

## 구현 범위

조회·저장·방문·구매·피드백·상담 이벤트를 사용자 유형별 신호로 해석하고, 동의와 유효성이 확인된 증거만 제한적으로 프로파일에 반영하는 파이프라인을 구현했다.

- 관람객·바이어 이벤트 별칭과 신호 강도
- 시간 감쇠, 반복 증거 신뢰도, 노출 위치 보정
- 봇·직원·테스트·광고·중복·미동의 이벤트 제외
- 혼잡·재고·일정 등 상황 원인과 장기 취향 원인의 분리
- 명시 입력과 충돌하는 추론은 자동 적용하지 않고 확인 대기
- 이벤트 단일 갱신 상한과 속성 계층별 전파 상한
- 원본 행동, 속성 증거, 추론, 조정, 프로파일 버전의 append-only 계보
- 동일 이벤트 재처리 시 멱등 응답

관련 구현:

- `backend/app/services/learning_policy.py`
- `backend/app/services/behavior_learning.py`
- `backend/app/models/learning.py`
- `backend/alembic/versions/20260802_0013_behavior_learning.py`
- `backend/app/api/v1/routers/adaptive.py`

## 처리 흐름

```text
행동 이벤트
→ 테넌트·행사·프로파일 범위 확인
→ 동의·봇·중복·실제 노출 검증
→ 신호 정규화·시간 감쇠
→ 원인 범위 분리
→ 제한적 속성 전파
→ 명시 선호 충돌 검사
→ 증거·추론·조정 저장
→ 적용된 경우에만 프로파일 새 버전 생성
```

## API

- `POST /api/v1/internal/learning/events/process`
- `POST /api/v1/profiles/{profile_id}/inferences/{inference_id}/confirm`
- `DELETE /api/v1/profiles/{profile_id}/inferences/{inference_id}`

프로파일 추론은 삭제 시 물리 삭제하지 않고 상태와 삭제 시점을 남긴다. 사용자가 확정한 속성은 행동 추론보다 우선한다.

## 검증

- 학습 동의 없는 이벤트의 적용 차단
- 명시 선호 충돌 시 확인 대기
- 혼잡 피드백이 맛 선호로 전파되지 않음
- 피드백 없는 시음은 중립 처리
- 바이어 단일 이벤트 갱신 상한
- 점진 갱신과 성과 보상값 범위 제한
- 정책·증거 테이블과 Alembic 단일 head

테스트: `backend/tests/test_learning_policy.py`, `backend/tests/test_exhibitor_models.py`

## 운영 제한

- 전역 추천정책은 온라인으로 자동 갱신하지 않는다.
- 일일 자동 갱신 총량과 모델 재학습은 후속 MLOps 단계에서 배치 관문으로 통제한다.
- 연락처·식별정보와 원문 행동 로그는 모델 입력에 포함하지 않는다.
