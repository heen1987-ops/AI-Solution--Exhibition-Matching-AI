# W-8. 웹 초개인화 모듈 - 웹 API·DB

근거 문서: `docs/redesign-v2/00-master-spec-v1.md`(§59 API 목록), `docs/redesign-v2/01-module-split-plan.md`(§4-A W-8). W-1~W-7에서 누적된 미결정 사항을 여기서 확정하고, 실제 스키마 변경 목록(마이그레이션 대상)을 정리한다. **이 문서는 결정만 하며, 실제 마이그레이션 코드는 별도 구현 작업으로 진행한다.**

## 1. 스키마 변경이 필요한 항목 (마이그레이션 대상)

| # | 변경 | 근거 | 우선순위 |
| --- | --- | --- | --- |
| 1 | `profile.saved_recommendable` 신규 테이블 | [W-2 §1-7](W-2-user-journey.md), [W-4 §6](W-4-profile-model.md) - 관심 저장 기능 자체가 현재 스키마에 없음 | 높음(S-4/S-6 화면이 이 테이블 없이는 동작 불가) |
| 2 | `profile.role.role_code_allowed` CHECK 확장 여부 검토 | [W-1 §6-3](W-1-scope-and-user-types.md) - 현재 `VISITOR/BUYER/EXHIBITOR/OPERATOR/ADMIN`, `DATA_REVIEWER` 없음 | 중간 - §2에서 최종 결정 |
| 3 | `feature_builder.py`에 `current_query` 컴포넌트 추가 | [W-5 §3](W-5-recommendation-logic.md) - C-4(검색엔진) 선행 필요 | 낮음(C-4 이후) |
| 4 | `ScoringPolicy.weights` 재조정(`CONSUMER_SCORE_V1`/`BUYER_SCORE_V1`) | [W-5 §3](W-5-recommendation-logic.md) | 중간 |

## 2. `user_type`/`role_code` 리네이밍 여부 - 최종 결정

[W-1 §6-1](W-1-scope-and-user-types.md), [W-1 §6-3](W-1-scope-and-user-types.md)에서 미뤄온 결정.

**결정: DB 값은 바꾸지 않고, API 응답 레이어에서만 매핑한다.**

이유:
- `user_type IN ('GENERAL_VISITOR','BUYER')` CHECK와 `role_code IN ('VISITOR','BUYER','EXHIBITOR','OPERATOR','ADMIN')` CHECK는 이미 매칭 서비스 계층(`orchestrator.py`, `feature_builder.py`) 곳곳에서 리터럴 문자열로 참조되고 있어(`POLICY_USER_TYPES`, `audience="GENERAL_VISITOR"` 등), DB 값을 바꾸면 그 모든 참조를 함께 바꿔야 하는 반면 실질적 이득이 없다(API 소비자 입장에서는 응답 필드 값이 `GENERAL_REGISTERED`로 보이기만 하면 충분).
- API 레이어(FastAPI 응답 스키마)에 다음 매핑 테이블 하나만 두면 된다: `GENERAL_VISITOR→GENERAL_REGISTERED`, `BUYER→BUYER_REGISTERED`(user_type); `VISITOR→GENERAL_REGISTERED`, `EXHIBITOR→EXHIBITOR_ADMIN`, `OPERATOR→EVENT_ADMIN`, `ADMIN→EVENT_ADMIN`(role_code, `ADMIN`과 `OPERATOR`를 동일값으로 매핑하는 것이 맞는지는 §3에서 재검토).
- `DATA_REVIEWER`만 예외 - 매핑할 기존 값 자체가 없으므로, `role_code_allowed` CHECK에 `'DATA_REVIEWER'`를 추가하는 마이그레이션이 실제로 필요하다(§1의 항목 2). 이는 이전 세션에서 `RECOMMENDED_ACTIONS` CHECK를 확장했던 것과 동일한 패턴(`op.f()`로 제약명 감싸기)을 재사용할 수 있다.

## 3. `ADMIN`과 `OPERATOR`의 관계 재검토

기존 스키마는 `OPERATOR`와 `ADMIN`을 별도 role_code로 두고 있는데, 마스터 스펙은 `EVENT_ADMIN` 하나만 정의한다(§7). 두 기존 값의 실제 권한 차이가 무엇인지는 이번 문서 작성 시점의 코드베이스(모델 정의)만으로는 알 수 없다 - **W-9(관리자 운영)에서 실제 권한 분기 로직(있다면 서비스 계층 어딘가에 있을 것)을 확인한 뒤 최종 매핑을 정한다.** 잠정적으로는 `OPERATOR→EVENT_ADMIN`, `ADMIN→(테넌트 최상위 권한, 마스터 스펙 범위 밖)`으로 구분해 둔다.

## 4. `saved_recommendable` 테이블 설계 (확정)

[W-3 §3](W-3-screen-ia.md), [W-4 §7](W-4-profile-model.md)에서 반복적으로 미뤄온 컬럼 설계를 여기서 확정한다.

```text
profile.saved_recommendable
  saved_recommendable_id  UUID PK
  profile_id              UUID FK -> profile.user_profile.profile_id
  recommendable_id        UUID FK -> exhibition.recommendable.recommendable_id
  saved_at                TIMESTAMPTZ
  saved_context_json      JSONB NULL   -- 저장 시점 zone/검색어 등, 선택적
  UNIQUE(profile_id, recommendable_id)
```

- `saved_context_json`을 선택적(nullable)으로 둔 이유: [W-4 §7-2](W-4-profile-model.md)에서 "컨텍스트를 남길지"가 미결정이었는데, 필수 컬럼으로 만들면 나중에 컨텍스트를 안 남기기로 결정해도 되돌리기 어렵다 - nullable로 시작하고 실제로 채울지는 서비스 로직에서 점진적으로 결정한다.
- `UNIQUE(profile_id, recommendable_id)`: 같은 후보를 중복 저장하지 않는다(저장/해제 토글 UI를 전제).

## 5. API 표면 (§59 대응, 목록 수준)

마스터 스펙 §59가 요구하는 API를 W-3 화면과 대응해 목록만 확정한다(요청/응답 스키마 상세는 이 문서 범위 밖 - 구현 시 OpenAPI로 정의).

| API | 대응 화면 | 비고 |
| --- | --- | --- |
| `POST /auth/login` | 로그인 | 기존 `identity` 인증 재사용 |
| `GET /profile/me` | S-7 | `UserProfile`+`ProfileAttribute`+`BuyerNeed`(BUYER만) 조합 |
| `PATCH /profile/me/attributes` | S-7 | `source_type=USER_EDITED`로 기록, `ProfileVersion` 스냅샷 트리거 |
| `GET /recommendations` | S-1/S-2 | 기존 오케스트레이터 그대로 재사용 |
| `POST /search` | S-3 | GUEST_WEB은 기본 403(비활성, [W-3 §2](W-3-screen-ia.md)) |
| `POST /saved-recommendables` / `DELETE .../{id}` | S-4/S-5 저장 버튼 | §4 신규 테이블 |
| `GET /saved-recommendables` | S-4 | - |
| `POST /buyer/matches/{exhibitor_id}/meetings` | S-6 | [W-7](W-7-buyer-matching-consultation.md) 흐름 1단계 |
| `PATCH /meetings/{id}/status` | S-6(참가업체 측은 관리자 포털) | [W-7](W-7-buyer-matching-consultation.md) 흐름 2단계 |
| `POST /guest/convert` | S-8 | 게스트→회원 전환, [W-2 §4-1](W-2-user-journey.md) 승계 로직 포함 |

## 6. 게스트 전환 시 데이터 승계 범위 - 최종 결정

[W-2 §4-1](W-2-user-journey.md)에서 미뤄온 결정: **위치·방문세션 데이터는 승계하고, 관심 신호(`InferredPreference`)는 승계하지 않는다.**

이유: [W-1 §3](W-1-scope-and-user-types.md) 원칙("게스트 단계에서는 `EXPLICIT`/`CONFIRMED` 관심사를 강하게 쌓지 않는다")에 따라 애초에 게스트 상태에서는 `InferredPreference`를 채우지 않기로 했으므로([W-4 §6](W-4-profile-model.md) "GUEST_WEB 예외"), 승계할 관심 신호 자체가 존재하지 않는다. `VisitSession`/`ContextProfile`(위치·잔여시간)만 `guest_session_id` 소유에서 `user_id` 소유로 FK를 갱신하면 된다 - 스키마 변경 없이 UPDATE 문 하나로 처리 가능한 서비스 로직.

## 7. W-9로 넘기는 질문

1. `ADMIN`/`OPERATOR` 실제 권한 차이 확인(§3).
2. `role_code_allowed`에 `DATA_REVIEWER` 추가 마이그레이션의 실제 작성.
