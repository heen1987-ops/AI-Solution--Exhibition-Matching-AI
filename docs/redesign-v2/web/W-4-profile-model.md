# W-4. 웹 초개인화 모듈 - 프로파일 모델

근거 문서: `docs/redesign-v2/00-master-spec-v1.md`(§9~10, §34), `docs/redesign-v2/01-module-split-plan.md`(§4-A W-4). [W-3](W-3-screen-ia.md)에서 확정한 화면이 실제로 읽고 쓰는 프로파일 필드를 확정한다. 마스터 스펙 §4의 하위 항목("등록정보, 관심분야, 방문목적, 바이어 거래조건, 사용자가 수정한 정보, 행사 내 제한적 행동정보") 순서를 그대로 따른다.

## 0. 기존 스키마 재사용 원칙

01-module-split-plan.md §6("자연어 프로파일링 → 웹용으로 축소", "행동학습 → 웹 등록 사용자만 제한 적용")에 따라, **새 테이블을 만들기보다 기존 5개 프로파일 테이블(`UserProfile`/`ProfileAttribute`/`InferredPreference`/`ProfileVersion`/`BuyerNeed`)의 활용 범위를 좁히는 방향**으로 설계한다. 아래 각 절에서 "그대로 재사용" vs "축소 적용" vs "신규 필요"를 명시한다.

## 1. 등록정보

- **테이블**: `profile.UserProfile`(루트) - `user_type`, `profile_status`, `completeness_score`.
- **재사용**: 그대로. `user_type IN ('GENERAL_VISITOR','BUYER')` CHECK는 [W-1 §6-1](W-1-scope-and-user-types.md)에서 리네이밍 여부가 아직 미결정이므로 이번 W-4에서는 값을 바꾸지 않고 API 레이어 매핑을 기본 가정으로 둔다.
- **사전등록 연계 데이터**([W-2 §1-1](W-2-user-journey.md))가 채우는 필드는 `user_type`, `event_id`뿐이다 - 이름·연락처 등 식별정보는 `identity` 스키마(별도 도메인)에 있으므로 W-4 범위 밖.

## 2. 관심분야

- **테이블**: `profile.ProfileAttribute` (`attribute_code`, `value_json`, `requirement_level`, `source_type`, `confidence`).
- **재사용**: 그대로. 단, 웹 모듈은 `source_type` 11종 전체를 다 쓰지 않고 다음 4종만 채우면 충분하다: `USER_SELECTED`(S-7에서 사용자가 직접 선택), `REGISTRATION`(사전등록 연계), `BEHAVIOR_SINGLE`(단일 행동 관찰), `AI_EXTRACTED`(자연어 검색·상세조회 로그에서 AI가 추출) - 마스터 스펙 §34.1이 웹의 행동 신호를 "관심 저장/상세조회/검색 클릭/명시적 제외" 4종으로 한정하기 때문. `BEHAVIOR_AGGREGATED`/`FEEDBACK`/`OPERATOR_CONFIRMED`/`DEFAULT`/`EXTERNAL_SYNC`/`USER_TYPED`/`USER_EDITED`는 이번 MVP 웹 모듈에서 채우지 않는다(축소 적용) - 스키마에서 제거하지 않고 단순히 미사용으로 남긴다.
- `requirement_level`(`REQUIRED`/`PREFERRED`/`ACCEPTABLE`/`EXCLUDED`)은 S-7(MY 정보)에서 사용자가 직접 조정 가능한 필드로 그대로 노출한다.

## 3. 방문목적

- 마스터 스펙에 "방문목적"이 별도 테이블로 명시돼 있지 않다 - 기존 스키마에서 가장 가까운 대응은 `ProfileAttribute`의 `attribute_code`가 `GOAL.*`/`BIZ_GOAL.*` 접두어를 갖는 행이다(이전 세션에서 구현한 `feature_builder.py`의 `_COMPONENT_BY_CODE_PREFIX`가 이미 이 접두어들을 인식하도록 만들어져 있음).
- **결론**: 방문목적은 별도 테이블이 아니라 관심분야와 동일한 `ProfileAttribute` 메커니즘으로 저장하되, `attribute_code`의 온톨로지 분류(`GOAL`/`BIZ_GOAL`)로 구분한다. 신규 테이블 불필요.

## 4. 바이어 거래조건

- **테이블**: `profile.BuyerNeed` (1:1 확장, `profile_id`가 PK이자 FK).
- **재사용**: 그대로. `target_price_min/max_amount`+`currency`+`price_basis`(§14.1 "목표 가격대"), `monthly_units_min/max`(§14.1 "월 주문 규모"), `decision_timeline`(§14.1 "의사결정 시기"), `business_email_verified`/`company_verified`(§14.1 "바이어 검증" - W-9 관리자 운영과 연동)까지 마스터 스펙 §14.1의 요구 항목과 필드 단위로 정확히 대응한다 - 변경 불필요.
- BUYER_REGISTERED만 이 테이블 로우를 가지며, GENERAL_REGISTERED/GUEST_WEB은 갖지 않는다([W-1 §1](W-1-scope-and-user-types.md) 사용자 구분과 일치).

## 5. 사용자가 수정한 정보

- S-7(MY 정보) 화면에서 사용자가 직접 프로파일을 수정하면 `ProfileAttribute.source_type`이 `USER_EDITED`가 되어야 하나, §2에서 웹 모듈이 채우는 4종에는 `USER_EDITED`를 포함하지 않았다 - **정정**: 최초 선택은 `USER_SELECTED`, 이후 수정은 `USER_EDITED`이므로 실제로는 5종(`USER_SELECTED`/`USER_EDITED`/`REGISTRATION`/`BEHAVIOR_SINGLE`/`AI_EXTRACTED`)이 필요하다. §2의 목록을 이 문서 기준으로 정정한다.
- 수정 시점마다 `profile.ProfileVersion`에 스냅샷을 남긴다(기존 설계 그대로) - `change_reason`이 자유 문자열이므로 `"USER_UPDATE"`를 웹 모듈의 표준값으로 채택한다(db-erd 예시값과 일치, 별도 CHECK 제약 없음을 이미 확인함).

## 6. 행사 내 제한적 행동정보

마스터 스펙 §34.1의 4가지 행동을 기존 스키마에 매핑한다.

| §34.1 행동 | 저장 위치 | 비고 |
| --- | --- | --- |
| 관심 저장 | **신규 테이블 필요** - `profile.saved_recommendable`([W-2 §1-7](W-2-user-journey.md)에서 이미 공백으로 확인) | 저장 자체는 목록이고, 그 신호가 `InferredPreference`에도 반영되는지는 아래 참고 |
| 상세조회 | `InferredPreference` 갱신 트리거(직접 저장 테이블 없이 조회 이벤트 → 즉시 반영) | 상세조회 자체를 개별 로그로 영구 저장할지는 이번 W-4에서 결정하지 않음(§7 미결정) |
| 검색 클릭 | 위와 동일 | 자연어 검색(S-3) 결과 클릭 |
| 명시적 제외 | `ProfileAttribute.requirement_level = 'EXCLUDED'` | 이미 존재하는 값이므로 신규 테이블 불필요 - "제외"는 관심분야 테이블의 상태값으로 표현 |

- **"제한적"의 의미**: 마스터 스펙 §56의 "실시간 온라인 학습형 랭킹"·"복잡한 공정성 최적화" 제외 원칙에 따라, 이 4가지 행동은 `InferredPreference.inferred_score`를 단순 가중 갱신(반복성 카운트 증가)하는 수준에 그치고, 세션 중 실시간으로 추천 랭킹 모델 자체를 재학습하지 않는다. `positive_evidence_count`/`negative_evidence_count`가 이미 이 "단순 누적" 방식을 위해 설계돼 있다.
- **GUEST_WEB 예외**: [W-1 §3](W-1-scope-and-user-types.md) 원칙에 따라 GUEST_WEB에는 이 4가지 행동 중 어떤 것도 `InferredPreference`/`ProfileAttribute`에 반영하지 않는다(지속 프로파일 없음). 회원 전환 이후 행동부터 반영을 시작한다.

## 7. W-5로 넘기는 질문 (이번 W-4에서 결정하지 않음)

1. 상세조회·검색 클릭을 개별 이벤트 로그로 영구 저장할지(감사·재계산 근거용) 여부 - 저장한다면 `interaction.interaction_event`(파티션 테이블, `ProfileVersion.source_event_id`가 이미 참조를 예비해둔 대상)를 그대로 쓸 수 있는지 W-8에서 확인.
2. `saved_recommendable` 신규 테이블의 정확한 컬럼: `profile_id` + `recommendable_id`(exhibition.recommendable 참조) + `saved_at` 최소 구성인지, 저장 시점 컨텍스트(zone, 검색어)를 추가로 남길지 - [W-3 §3](W-3-screen-ia.md)에서 이미 제기한 동일 질문.
3. §2 정정 목록(`USER_SELECTED`/`USER_EDITED`/`REGISTRATION`/`BEHAVIOR_SINGLE`/`AI_EXTRACTED` 5종)이 W-5의 점수식(컴포넌트별 가중치)에서 `source_type`별로 다른 신뢰도 가중을 두는지, 아니면 `confidence` 컬럼 하나로 충분한지.
