# 변경 요청 CR-005 — 관심목록(즐겨찾기) 영속 모델·마이그레이션 계약 게시

상태: **APPROVED**
승인일: 2026-08-13
승인 근거: Blocker Score 낮음(영향도 2 + 되돌리기 쉬움 0 + 보안·개인정보 0 + 기존정보 충분 0) —
새 테이블 1개를 추가하는 순수 가법적(additive) 변경이며, 기존 테이블·API·정책을 변경하지 않는다.
CRUD API(BACKEND-009)는 이 CR이 게시하는 모델을 그대로 소비만 하도록 별도 작업으로 분리되어
있어 재작업 비용도 낮다.

- 요청 트랙: CONTRACTS
- 관련 작업: CONTRACT-005 (본 작업), 인계 대상: BACKEND-009
- 현재 계약: `docs/db-erd-table-spec.md` §16.1 "interaction.favorite"가 컬럼·CHECK 정책을
  이미 텍스트로 명시하고 있었으나, ORM 모델·Alembic 마이그레이션이 아직 게시되지 않아
  `app/models/**`·`alembic/**`에는 이 테이블이 존재하지 않았다(0031까지의 컴파일된 SQL에
  `interaction.favorite`는 0건).
- 필요 변경:
  - `app/models/favorite.py`에 `Favorite` ORM 모델(스키마 `interaction`, 테이블명 `favorite`)을
    게시한다.
  - `apps/api/alembic/versions/20260813_0032_favorite.py`로 `0031_integration_source_sync` 위에
    체인을 연결해 실제 `CREATE TABLE interaction.favorite`를 만든다(단일 head 유지).
  - `.harness/contracts/domain-model.md`에 이 테이블을 요약 등재한다.
- 변경하지 않을 경우 문제: BACKEND-009가 시작할 모델·마이그레이션 소유권이 없어 착수할 수 없고,
  db-erd §16.1이 문서로만 남아 실제 스키마와 괴리(drift)된 상태가 지속된다.
- 영향 트랙: CONTRACTS(본 CR), BACKEND(BACKEND-009가 다음 단계로 소비)
- 마이그레이션 필요: 예 — `0032_favorite` (하위 없음, `0031_integration_source_sync` 이후 유일한
  head)
- 하위호환 가능 여부: 예 — 완전히 새로운 테이블만 추가하며 기존 테이블·컬럼·API 응답 형식을
  변경하지 않는다.
- 권장안: 아래 "소유자·행사·recommendable 경계", "중복 방지 정책", "소프트 삭제 정책" 절 참고.
- 임시 우회 여부: 없음. 이 CR은 게시 전용이며 어떤 기능도 이 테이블을 아직 참조하지 않는다
  (CRUD 라우터가 없으므로 런타임 영향이 0이다).
- 승인된 소유경로 확장: 없음 — `.harness/backlog.yaml`의 CONTRACT-005 `owned_paths`를 그대로
  사용했다 (`apps/api/app/models/favorite.py`, `apps/api/alembic/**`,
  `.harness/contracts/domain-model.md`, 본 문서). 예외적으로 `apps/api/app/models/__init__.py`와
  `apps/api/tests/test_favorite_model.py` / `apps/api/tests/test_exhibitor_models.py`를 추가로
  건드렸다 — 사유는 아래 "owned_paths 밖 판단" 절 참고.

## 소유자·행사·recommendable 경계 (BACKEND-009가 반드시 지켜야 할 계약)

- **소유자(exactly-one)**: `CHECK num_nonnulls(user_id, guest_session_id) = 1`. 인증 사용자
  (`user_id` → `profile.user_account.user_id`)와 익명 게스트(`guest_session_id` →
  `profile.guest_session.guest_session_id`) 중 **정확히 하나**만 채워야 한다 — 둘 다 NULL이거나
  둘 다 채워진 행은 DB가 거부한다. (`InteractionEvent.subject_at_most_one`의 `<= 1`과 다르다 —
  즐겨찾기는 시스템 이벤트 개념이 없으므로 소유자 없는 행을 허용하지 않는다.)
- **행사 경계**: `(tenant_id, event_id)` → `exhibition.event(tenant_id, event_id)` 복합 FK.
- **대상(recommendable) 경계**: `(tenant_id, event_id, recommendable_id)` → 세 컬럼 복합 FK로
  `exhibition.recommendable(tenant_id, event_id, recommendable_id)`를 참조한다 — 이 리포에서
  `exhibition.recommendable`을 참조하는 모든 기존 테이블(`matching.match_result`,
  `interaction.interaction_event`, `interaction.recommendation_impression` — 전부
  `app/models/matching.py`)과 **동일한 형태**다. `recommendable_id` 단일 컬럼 FK를 새로 발명하지
  않았다.
- **기원(origin) 표시**: `source VARCHAR(20)`는 `('SEARCH', 'RECOMMENDATION')`만 허용
  (db-erd §16.1). `match_result_id`는 **nullable** 단일 컬럼 FK → `matching.match_result
  .match_result_id` — 모든 즐겨찾기가 특정 추천 결과에서 비롯되는 것은 아니다(예: 자유검색으로
  찾은 업체를 저장하는 경우 `source='SEARCH'`, `match_result_id=NULL`). `match_result_id`가
  이미 그 자체로 PK(전역 유일)이므로 tenant/event 복합 경계 FK는 불필요하다 — `MatchResult
  .directional_policy_version_id`가 다른 PK-only 컬럼을 참조할 때 쓰는 것과 같은 패턴이다.

## 중복 방지 정책 (BACKEND-009의 POST 핸들러가 반드시 지켜야 할 계약)

db-erd §16.1: "인증·익명 각각 활성 partial unique를 적용한다." 하나의 UniqueConstraint 대신
**두 개의 partial UNIQUE 인덱스**를 각각 다음 조건으로 건다:

- `uq_favorite_active_user_recommendable` — `(tenant_id, event_id, user_id, recommendable_id)`
  UNIQUE WHERE `deleted_at IS NULL AND user_id IS NOT NULL`
- `uq_favorite_active_guest_recommendable` — `(tenant_id, event_id, guest_session_id,
  recommendable_id)` UNIQUE WHERE `deleted_at IS NULL AND guest_session_id IS NOT NULL`

즉, 같은 사용자(또는 같은 게스트 세션)가 같은 `recommendable_id`를 **활성 상태로 두 번**
저장할 수 없다 — BACKEND-009는 POST에서 이 제약 위반(unique violation)을 애플리케이션
계층의 "이미 저장됨" 응답으로 변환해야 하며, INSERT 전에 SELECT로 존재 여부를 먼저 확인하는
방식에 의존해서는 안 된다(경쟁 조건에 취약).

## 소프트 삭제 정책 (BACKEND-009의 DELETE 핸들러가 반드시 지켜야 할 계약)

`favorite_id` 행을 물리 삭제(hard delete)하지 않는다 — `deleted_at`에 타임스탬프를 쓰는
소프트 삭제만 한다. 위 partial unique 인덱스 두 개가 전부 `deleted_at IS NULL` 조건으로
스코프되어 있으므로:

- 소프트 삭제된 행(`deleted_at IS NOT NULL`)은 partial unique 인덱스에 아예 잡히지 않는다.
- 따라서 사용자가 "즐겨찾기 해제" 후 같은 대상을 **다시 즐겨찾기**해도, 이전 삭제된 행과 새
  INSERT되는 활성 행이 unique violation 없이 공존한다 — BACKEND-009는 "UPDATE 기존 행의
  deleted_at을 NULL로 되돌리는" 방식과 "새 행을 INSERT하는" 방식 중 하나를 선택할 수 있으며,
  이 스키마는 두 방식 모두를 지원한다(단, 후자를 택하면 같은 owner+recommendable 쌍에 대해
  삭제 이력이 여러 행으로 남는다는 점을 감안해야 한다).

## owned_paths 밖 판단 (스코프 이탈 근거)

- `apps/api/app/models/__init__.py`: 이 파일이 Alembic autogenerate/`app.models` 등록의 유일한
  진입점이다(`alembic/env.py`가 `import app.models`만 수행). 새 모델 파일을 여기 등록하지
  않으면 `tests/test_alembic_orm_parity.py`(기존에 이미 존재하는 가드 테스트)가 즉시 실패한다
  — 이 테스트가 정확히 "ORM에는 선언됐지만 등록되지 않아 아무 마이그레이션도 만들지 않는 테이블"
  부류의 드리프트를 잡기 위해 만들어졌다(2026-08-11 WAVE2C/2D/2E 병합 사고 재발 방지, 파일
  docstring 참고). 이 판단은 자신의 새 파일 1개만 등록하는 가역적·저위험 변경이다.
- `apps/api/tests/test_favorite_model.py`: 작업 지시의 "모델 레벨 테스트 최소 1개 작성" 요구를
  충족하기 위한 신규 파일.
- `apps/api/tests/test_exhibitor_models.py`: 기존 두 개의 하드코딩된 기준값
  (`Base.metadata.sorted_tables` 개수 135, `alembic heads` 기대값
  `["0031_integration_source_sync"]`)이 새 테이블·새 head 추가로 인해 자동으로 깨진다. 두 값을
  각각 136 / `["0032_favorite"]`로 갱신했다 — 다른 assertion·다른 테스트는 건드리지 않았다. 이
  갱신을 하지 않으면 이 CR과 무관한 기존 회귀 테스트가 실패해 `python -m pytest apps/api/tests
  -q`가 깨진 채로 남는다.

## 롤백 절차

1. 이 테이블을 아직 아무도 참조하지 않으므로(라우터·서비스 없음), 배포 환경에서는 코드
   롤백만으로 충분하다 — 별도 feature flag가 없다.
2. 스키마까지 되돌려야 하고 이후 마이그레이션이 `0032_favorite`에 의존하지 않는 경우
   `alembic downgrade 0031_integration_source_sync`를 실행한다. `downgrade()`는 두 개의
   partial unique 인덱스, 두 개의 조회 인덱스, 테이블 자체를 역순으로 제거한다.
3. BACKEND-009가 이미 이 테이블에 행을 쓰기 시작한 뒤 downgrade가 필요하면, 데이터 보존
   여부를 먼저 결정해야 한다 — 이 마이그레이션의 `downgrade()`는 무조건 `DROP TABLE`한다
   (append-only 감사 테이블이 아니므로 `object_embedding`류의 "참조 행이 있으면 중단" 가드를
   두지 않았다).

## 선택 근거

- `exhibition.recommendable` 복합 FK 패턴을 재사용해 이 리포의 기존 관례와 어긋나는 새로운
  FK 모양을 만들지 않았다.
- CHECK/partial-unique 제약 이름은 `app/db/base.py`의 `NAMING_CONVENTION`을 그대로 따른다
  (`ck_favorite_subject_exactly_one`, `ck_favorite_source_allowed`) — 마이그레이션 파일에서는
  `op.f()`로 감싸 Alembic이 동일 이름을 이중으로 변환(더블 프리픽스)하지 않도록 했다. 이
  더블 프리픽스 현상은 `0030_event_ingestion_failure`의 컴파일된 SQL에서 실제로 재현되는
  이 리포의 기존 잠재 버그이며(`op.f()`를 쓰지 않은 탓), 본 CR은 그 버그를 새로 반복하지 않되
  기존 마이그레이션은 별도 스코프이므로 고치지 않았다.
