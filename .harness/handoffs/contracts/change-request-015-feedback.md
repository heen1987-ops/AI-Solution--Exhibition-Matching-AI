# 변경 요청 CR-015 — 방문 피드백 영속 모델·마이그레이션 계약 게시 (소급)

상태: **APPROVED (소급 승인)**
작성일: 2026-08-13
승인일: 2026-08-13 (사용자 명시적 요청: "BACKEND-016/017 소급 Change Request 작성해줘")

## 이 CR이 "소급"인 이유, 그리고 CR-014(BACKEND-016)보다 한 단계 더 심각했던 이유

CR-014와 같은 근본 원인이다: BACKEND-017의 `.harness/backlog.yaml` `owned_paths`는 라우터·스키마
경로만 나열했고("apps/api/app/api/v1/routers/feedback.py", "apps/api/app/schemas/feedback.py")
선행 CONTRACTS 작업이 없는 상태에서 `app/models/feedback.py`와 `apps/api/alembic/versions/
20260813_0034_feedback.py`를 같은 작업에서 함께 게시했다(BACKEND-016의 판단을 그대로 인용해
"동일한 판단 패턴"이라고 스스로 문서화 — `app/models/feedback.py` 모듈 docstring의 "Scope note
(BACKEND-017)" 절 참고).

2026-08-13 코드 리뷰가 CR-014 대상과 함께 이것도 **CONFIRMED**로 지적했는데, 검증 결과 BACKEND-017
쪽이 더 심각했다: BACKEND-016은 최소한 자신의 `owned_paths` 필드를 사후에 확장해 무엇을
건드렸는지 기록으로 남겼지만, **BACKEND-017은 그 필드조차 갱신하지 않았다** — `.harness/
backlog.yaml`의 BACKEND-017 `owned_paths`는 지금도 라우터·스키마 경로만 나열하고 있고, 실제로
생성한 모델·마이그레이션 파일은 `evidence` 필드의 산문 설명에만 등장한다. 즉 백로그 레코드 자체가
실제로 만들어진 것과 불일치한 상태였다.

**이 CR의 목적**: CR-014와 동일 — 이미 배포되어 검증된 스키마를 되돌리지 않고, CONTRACTS
트랙의 공식 승인 기록을 사후에 남기며, `owned_paths` 불일치를 바로잡고, `.harness/contracts/
domain-model.md`를 실제 상태로 갱신한다.

- 요청 트랙: CONTRACTS (소급)
- 관련 작업: BACKEND-017 (이미 완료·DONE), 본 CR
- 현재 계약: `docs/db-erd-table-spec.md` §16.3 "interaction.feedback"이 컬럼·정책을 텍스트로
  명시하고 있었으나, 이 CR 이전에는 어떤 CONTRACTS 산출물도 `interaction.feedback`을 승인한
  기록이 없었다.
- 실제 변경 (이미 배포됨, 이 CR은 추인 + 백로그 레코드 정정만 한다):
  - `apps/api/app/models/feedback.py` — `Feedback` ORM 모델 (스키마 `interaction`, 테이블
    `feedback`)
  - `apps/api/alembic/versions/20260813_0034_feedback.py` — `down_revision = "0033_check_in"`
    위에 체인, `CREATE TABLE interaction.feedback`
  - `.harness/backlog.yaml`의 BACKEND-017 `owned_paths` 필드를 실제로 건드린 경로로 정정
    (아래 "백로그 레코드 정정" 절)
  - `.harness/contracts/domain-model.md` — 이 CR과 함께 갱신
- 변경하지 않을 경우 문제: CR-014와 동일 + 백로그 자체가 "무엇을 승인했는지"를 잘못 기록한 채로
  남아, 향후 이 테이블의 소유권을 추적하려는 사람이 `owned_paths`만 보고는 모델·마이그레이션의
  존재를 아예 알 수 없다.
- 영향 트랙: CONTRACTS(본 CR), BACKEND(BACKEND-017, 이미 완료)
- 마이그레이션 필요: 아니오 — `0034_feedback`은 이미 배포·검증되었다.
- 하위호환 가능 여부: 예 — 순수 가법적 테이블 1개.
- 승인된 소유경로 확장 (소급): `apps/api/app/models/feedback.py`, `apps/api/alembic/versions/
  20260813_0034_feedback.py`, `apps/api/tests/test_feedback_model.py`,
  `apps/api/app/models/__init__.py`(등록 갱신) — CR-014와 동일한 근거로 CONTRACTS 트랙 관점에서
  정식 승인한다.
- 임시 우회 여부: 없음.

## 테이블 설계 요약 (db-erd §16.3와 대조, `app/models/feedback.py` 실제 구현 기준)

- **소유자는 컬럼으로 중복 저장하지 않는다** — `CheckIn`과 동일하게 `visit_session_id`만
  주체 링크.
- **경계 FK**: `(tenant_id, event_id)` → `exhibition.event`, `(tenant_id, event_id,
  visit_session_id)` → `profile.visit_session`, `(tenant_id, event_id, recommendable_id)` →
  `exhibition.recommendable` — `Favorite`(CR-005)와 동일한 3컬럼 복합 FK 관례.
- **`rating IN ('VERY_RELEVANT','RELEVANT','NOT_RELEVANT')`** CHECK — 닫힌집합, DB 레벨 강제.
  `positive_reasons`/`negative_reasons`(JSONB 배열)는 원소 단위 CHECK 없이 스키마 계층
  (`app/schemas/feedback.py::FeedbackReasonCode`)에서 닫힌집합을 강제 — `CheckIn.activities`와
  동일하게 이 리포에 JSONB 배열 원소를 CHECK로 검증하는 기존 선례가 없어서 내린 판단이다.
- **선호(preference) vs 상황(situational) 원인 분리는 구조적으로 문서화되어 있으나, 이 CR
  시점까지 API 스키마 레이어에서 소비되지 않고 있었다**: `PREFERENCE_REASON_CODES`(`TASTE`,
  `PRICE`), `SITUATIONAL_REASON_CODES`(`CONGESTION`, `SOLD_OUT_OR_CLOSED`),
  `REVIEW_QUEUE_REASON_CODES`(`EXPLANATION_ERROR`)로 상수 분리는 되어 있었지만, 2026-08-13 코드
  리뷰가 이를 별개의 CONFIRMED 발견(schemas/feedback.py의 `FeedbackReasonCode` Literal이 이
  상수들과 별도로 손으로 중복 작성되어 있었고, 세 상수 자체는 테스트 외에는 어디서도 import되지
  않는 죽은 코드)으로 지적했다. 이 발견은 이 CR과 같은 리뷰 세션에서 **이미 수정 완료**됐다
  (`FeedbackReasonCode = Literal[*FEEDBACK_REASON_CODES]`로 파생, 커밋 `96cac08`) — 계약 자체는
  변경되지 않았고(허용되는 값 5개는 동일), 계약과 구현이 어긋나지 않도록 보장하는 방식만
  바뀌었으므로 이 CR의 범위에 포함하지 않는다.
- **`comment`는 평문 저장 금지, 기존 봉투암호화 재사용** — `app/core/auth.py::encrypt_secret`/
  `decrypt_secret`을 `purpose="feedback-comment"`로 재사용 (`app/models/meeting.py`의
  `message_enc`/`memo_enc`/`note_enc`와 동일 메커니즘, 새 암호를 발명하지 않음). 2026-08-13 리뷰는
  이 래퍼가 `app/services/meeting/buyer_matching.py::encrypt_meeting_text`/
  `decrypt_meeting_text`와 로직이 사실상 동일함(재사용 미흡, reuse 카테고리 CONFIRMED)을
  별도로 지적했으나, 이는 스키마/계약 문제가 아니라 서비스 레이어 리팩터링 문제이므로 이 CR의
  범위 밖이다 — 이미 배포된 여러 호출부를 건드리는 변경이라 별도의 검토된 작업으로 남겨둔다.
- **수정/삭제 엔드포인트 없음 — append-only**: `updated_at`/`deleted_at` 컬럼 자체가 없다
  (`Favorite.deleted_at`의 소프트 삭제와 대조). db-erd §16.3 "원본 피드백은 수정하지 않는다"를
  구조적으로 강제.

## 백로그 레코드 정정

`.harness/backlog.yaml`의 BACKEND-017 항목 `owned_paths`가 실제로 생성된 파일과 불일치했던
문제를 이 CR과 함께 바로잡는다 — `apps/api/app/models/feedback.py`,
`apps/api/alembic/versions/20260813_0034_feedback.py`, `apps/api/tests/test_feedback_model.py`를
`owned_paths`에 추가하고, 이 CR을 참조하는 각주를 evidence에 남긴다(별도 diff에서 처리).

## 계약 문서 갱신

`.harness/contracts/domain-model.md`를 CR-014와 함께 실제 상태(checkin.py, feedback.py,
0035_check_constraint_naming_fix 마이그레이션 반영: 35개 마이그레이션, 단일 head
`0035_check_constraint_naming_fix`, 138개 테이블)로 갱신한다.

## 롤백 절차

이미 배포·검증된 스키마이므로 이 CR 자체는 롤백 대상이 아니다. 스키마 롤백이 필요하면
`alembic downgrade 0033_check_in`으로 `feedback` 테이블과 인덱스를 역순 제거한다 — 단,
`app/services/feedback/service.py`가 이미 쓰기 시작했다면 먼저 데이터 보존 여부를 결정해야 한다
(append-only 감사 테이블 성격이라 downgrade가 무조건 `DROP TABLE`한다).

## 선택 근거 (사후 정당화)

- `CheckIn`(CR-014)과 동일한 소유권-비저장·복합FK 관례를 그대로 재사용해 이 리포에 새로운 패턴을
  발명하지 않았다.
- 암호화 컬럼은 기존 `meeting.py`의 봉투암호화 컬럼과 동일한 `LargeBinary` + 목적 태그 방식을
  재사용했다.
