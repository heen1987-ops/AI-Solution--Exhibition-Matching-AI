# 변경 요청 CR-014 — QR 체크인 영속 모델·마이그레이션 계약 게시 (소급)

상태: **APPROVED (소급 승인)**
작성일: 2026-08-13
승인일: 2026-08-13 (사용자 명시적 요청: "BACKEND-016/017 소급 Change Request 작성해줘")

## 이 CR이 "소급(retroactive)"인 이유

이 CR은 CONTRACT-005(CR-005, `favorite.py`)와 달리 **구현 이전이 아니라 이후에** 작성되었다.
BACKEND-016은 2026-08-13 시간별 자동 개선 루틴에서 `.harness/backlog.yaml`의 `owned_paths`가
라우터·스키마 경로만 나열하고("apps/api/app/api/v1/routers/checkin.py",
"apps/api/app/services/checkin/**") 선행 CONTRACTS 작업이 존재하지 않는 상태에서, "모델·마이그레이션
없이는 기능 자체가 무의미하다"는 낮은 Blocker Score 판단으로 `app/models/checkin.py`와
`apps/api/alembic/versions/20260813_0033_check_in.py`를 같은 작업에서 함께 게시하고 자신의
`owned_paths`를 사후 확장했다(코드 자체의 판단 근거는 `app/models/checkin.py` 모듈 docstring의
"Scope note (BACKEND-016)" 절 참고).

2026-08-13 설계정합성 코드 리뷰(8개 관점 파인더 + 1표 검증)가 이를 **CONFIRMED** 거버넌스 위반으로
지적했다: `AGENTS.md`는 "Never modify files outside your assigned owned_paths"와 "Never modify
shared contracts without a Change Request... approved before implementing"를 명시하고,
`.harness/locks.yaml`은 `apps/api/app/models/**`·`apps/api/alembic/**`를 CONTRACTS 트랙 전용으로
할당한다. BACKEND-016은 이 두 규칙을 모두 어겼다 — Change Request 없이, `.harness/locks.yaml`
갱신 없이 진행했다.

**이 CR의 목적**: 이미 배포되어 34개 테스트로 검증된 스키마를 되돌리는 것이 아니라(그럴 이유가
없다 — 스키마 자체는 db-erd §16.2와 정확히 일치하고 독립적으로 재검증됨), **기록을 사실과 일치시키는
것**이다 — CONTRACTS 트랙이 이 테이블의 존재와 설계를 공식적으로 인지·승인했다는 계약 문서를
사후에 남기고, `.harness/contracts/domain-model.md`(CONTRACTS 소유 계약 문서, 리뷰가 지적한 대로
0032_favorite/136 테이블 시점에 멈춰 있어 checkin/feedback/0035 마이그레이션을 전혀 반영하지
못하고 있었다)를 실제 상태로 갱신한다.

- 요청 트랙: CONTRACTS (소급)
- 관련 작업: BACKEND-016 (이미 완료·DONE), 본 CR
- 현재 계약: `docs/db-erd-table-spec.md` §16.2 "interaction.check_in"이 컬럼·정책을 텍스트로
  명시하고 있었으나, 이 CR 이전에는 어떤 CONTRACTS 산출물도 `interaction.check_in`을 승인한
  기록이 없었다(`.harness/handoffs/contracts/`에 checkin 관련 파일 없음, `.harness/locks.yaml`은
  여전히 `apps/api/app/models/**`를 CONTRACTS 전용으로만 표시).
- 실제 변경 (이미 배포됨, 이 CR은 추인만 한다):
  - `apps/api/app/models/checkin.py` — `CheckIn` ORM 모델 (스키마 `interaction`, 테이블 `check_in`)
  - `apps/api/alembic/versions/20260813_0033_check_in.py` — `down_revision = "0032_favorite"`
    위에 체인, `CREATE TABLE interaction.check_in`
  - `.harness/contracts/domain-model.md` — 이 CR과 함께 갱신 (아래 "계약 문서 갱신" 절)
- 변경하지 않을 경우 문제: 스키마는 이미 존재하고 정상 동작하지만, CONTRACTS의 계약 문서가
  실제 스키마와 계속 괴리(drift)된 채로 남는다 — 향후 CONTRACTS 작업이 이 문서만 보고 판단하면
  `interaction.check_in`의 존재 자체를 놓칠 수 있다.
- 영향 트랙: CONTRACTS(본 CR), BACKEND(BACKEND-016, 이미 완료)
- 마이그레이션 필요: 아니오 — `0033_check_in`은 이미 배포·검증되었다. 이 CR은 마이그레이션을
  새로 만들지 않는다.
- 하위호환 가능 여부: 예 — 순수 가법적 테이블 1개, 기존 스키마 변경 없음.
- 승인된 소유경로 확장 (소급): `apps/api/app/models/checkin.py`, `apps/api/alembic/versions/
  20260813_0033_check_in.py`, `apps/api/tests/test_checkin_model.py`,
  `apps/api/app/models/__init__.py`(등록 갱신) — BACKEND-016이 이미 자신의 `owned_paths`를 이
  범위로 확장해 두었으므로(`.harness/backlog.yaml` BACKEND-016 항목 `note` 필드), 이 CR은 그
  확장을 CONTRACTS 트랙 관점에서 정식 승인한다.
- 임시 우회 여부: 없음.

## 테이블 설계 요약 (db-erd §16.2와 대조, `app/models/checkin.py` 실제 구현 기준)

- **소유자는 컬럼으로 중복 저장하지 않는다**: `Favorite`(CR-005)와 달리 이 테이블은
  `user_id`/`guest_session_id` 컬럼이 아예 없다. `visit_session_id` 하나만 주체 링크이며,
  "누구의 체크인인가"는 항상 `profile.visit_session`을 조인해서 판단한다 —
  `profile.visit_session` 자신이 이미 `exactly_one_owner` CHECK를 갖고 있으므로 이중으로 강제할
  필요가 없다는 것이 db-erd §16.2의 명시적 설계다.
- **경계 FK 3종**: `(tenant_id, event_id)` → `exhibition.event`, `(tenant_id, event_id,
  visit_session_id)` → `profile.visit_session`, `(tenant_id, event_id, booth_id)` →
  `exhibition.booth` — 전부 이 리포의 기존 3컬럼 복합 FK 관례(`fk_favorite_recommendable_boundary`
  등)를 그대로 따른다.
- **`check_in_method IN ('QR','MANUAL','STAFF')`** CHECK — `Favorite.source`와 동일한
  패턴의 DB 레벨 닫힌집합 강제.
- **`qr_id`/`qr_key_version`은 QR 경로만 채운다** — 나머지 두 경로(MANUAL/STAFF)는 NULL. 키
  로테이션 이후에도 "그 체크인이 검증받은 시점의 키 버전"이 불변으로 남도록
  `qr_key_version`을 별도 스냅샷한다.
- **5분 중복방지 창은 스키마 제약이 아니라 런타임 쿼리 패턴**이다(고정값 UNIQUE로 표현할 수 없는
  시간 상대적 규칙이므로) — `pg_advisory_xact_lock` + `ix_check_in_session_booth_time` 인덱스
  기반 범위 조회로 구현되며, 실제 잠금·조회 로직은 `app/services/checkin/service.py`가 소유한다.
  **주의**: 2026-08-13 코드 리뷰는 이 창이 클라이언트가 보낸 `occurred_at`에만 근거해 서버 시간
  검증이 없어 우회 가능하다는 별개의 CONFIRMED 발견을 냈다 — 이는 이 CR이 다루는 스키마/계약
  문제가 아니라 서비스 레이어의 런타임 로직 문제이며, 모듈 자체 docstring이 이를 의도된 설계로
  문서화하고 있어 별도의 제품/보안 판단이 필요하다(고의로 이 CR의 범위 밖에 둔다).
- **Idempotency-Key가 1차 중복방지, `client_event_id` partial-unique는 2차 안전망** — 기존
  `integration.idempotency_record`(webhooks.py가 이미 사용)를 재사용하며 새 메커니즘을
  발명하지 않는다.

## 계약 문서 갱신

`.harness/contracts/domain-model.md`를 이 CR과 함께 실제 상태로 갱신한다(checkin.py/feedback.py/
0035 마이그레이션 반영 — 별도 커밋에서 CR-014/CR-015와 함께 처리, 상세는
`change-request-015-feedback.md` 참고).

## 롤백 절차

이미 배포·검증된 스키마이므로 이 CR 자체는 롤백 대상이 아니다. 스키마 롤백이 필요하면:
1. `app/services/checkin/service.py`/`app/api/v1/routers/checkin.py`가 이미 이 테이블에 쓰기
   시작했으므로, 데이터 보존 여부를 먼저 결정해야 한다.
2. `alembic downgrade 0032_favorite`로 `check_in` 테이블과 그 인덱스 전체를 역순 제거한다
   (마이그레이션의 `downgrade()`가 무조건 `DROP TABLE`한다).

## 선택 근거 (사후 정당화, BACKEND-016의 실제 판단을 그대로 인용)

- `profile.visit_session`에서 파생되는 소유권을 이 테이블에 중복 저장하지 않은 것은 db-erd
  §16.2의 명시적 지시를 따른 것이며, `CheckIn`을 최소한으로 유지해 소유권 로직이 두 곳에서
  갈라질 위험을 없앤다.
- 기존 복합 FK·닫힌집합 CHECK·partial-unique 관례를 전부 재사용해 이 리포에 새로운 FK/제약
  모양을 발명하지 않았다.
