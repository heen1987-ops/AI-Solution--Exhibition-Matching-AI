# 04. 통합 아키텍처·개발 로드맵 (4차)

근거 문서: `docs/redesign-v2/01-module-split-plan.md`(§7 "4차: 통합 아키텍처·개발 로드맵"). [W-1~W-10](web/), [K-1~K-8](kiosk/), [C-1~C-8](common/) 26개 설계 문서에서 나온 모든 실행 항목을 의존관계 순서로 종합한 단일 구현 계획이다. 이 문서 자체는 새로운 결정을 내리지 않는다 - 각 항목 뒤에 그 결정이 내려진 원문서를 표기했다.

## 0. 실행 순서 원칙

의존관계가 없는 항목을 먼저, 다른 항목의 산출물(신규 테이블·신규 정책 객체)에 의존하는 항목을 나중에 배치했다. 각 단계는 이전 단계 완료를 전제하지 않고 병렬 진행 가능한 경우 그렇게 표시했다.

## 1단계 - 스키마 마이그레이션 (선행 의존성 없음, 병렬 가능)

| # | 마이그레이션 | 근거 |
| --- | --- | --- |
| 1-A | `profile.saved_recommendable` 신규 테이블 | [W-8 §4](web/W-8-api-and-db-changes.md) |
| 1-B | `ai.source_document` / `ai.extracted_attribute` / `ai.content_approval` / `ai.ai_execution_log` 신규 테이블(신규 `ai` 스키마) | [C-2 §2](common/C-2-content-collection-ai-structuring.md) |
| 1-C | `pgvector` 확장 활성화 + `ai.embedding_document` / `ai.embedding_vector` 신규 테이블 | [C-4 §3](common/C-4-search-recommendation-engine.md) |

세 항목 모두 서로 다른 테이블에 대한 독립 마이그레이션이라 순서 제약이 없다 - 동시에 작업 가능.

## 2단계 - 코드 전용 변경 (스키마 변경 없음, 1단계와 병렬 가능)

| # | 변경 | 근거 |
| --- | --- | --- |
| 2-A | API 응답 레이어 `user_type`/`role_code` 매핑(`GENERAL_VISITOR→GENERAL_REGISTERED` 등) | [W-8 §2](web/W-8-api-and-db-changes.md) |
| 2-B | `ScoringPolicy.weights` 재조정(`CONSUMER_SCORE_V1`/`BUYER_SCORE_V1`, §57 비율 반영) | [W-5 §3](web/W-5-recommendation-logic.md) |
| 2-C | 관리자 인가 스코프 매핑 코드(EVENT_ADMIN 기본 전체, DATA_REVIEWER는 신규 role_code 아님) | [C-6 §1](common/C-6-privacy-and-authorization.md) |
| 2-D | 게스트 전환 시 `VisitSession`/`ContextProfile` FK 승계 서비스 로직(guest_session_id→user_id) | [W-8 §6](web/W-8-api-and-db-changes.md) |

## 3단계 - 검색·점수 엔진 확장 (1단계 완료 후)

| # | 작업 | 의존 | 근거 |
| --- | --- | --- | --- |
| 3-A | 키워드 검색(FTS) 채널 구현 | 없음(기존 텍스트 컬럼 대상) | [C-4 §3](common/C-4-search-recommendation-engine.md) |
| 3-B | 벡터 검색 채널 구현 + 임베딩 생성 잡 | 1-C | [C-4 §3](common/C-4-search-recommendation-engine.md) |
| 3-C | 자연어 의도 추출(LLM 호출) | 1-B(`ai_execution_log` 기록 대상) | [C-4 §3](common/C-4-search-recommendation-engine.md) |
| 3-D | `KIOSK_SEARCH_SCORE_V1` 신규 `ScoringPolicy` 추가 | 3-A/3-B(Semantic/Keyword 컴포넌트 데이터 소스) | [C-4 §2](common/C-4-search-recommendation-engine.md) |
| 3-E | `feature_builder.py`에 `current_query` 컴포넌트 추가 | 3-A/3-B/3-C | [W-5 §3](web/W-5-recommendation-logic.md), [K-4 §5](kiosk/K-4-natural-language-search-logic.md) |
| 3-F | `Recommendable` 레지스트리 사전 승인 게이트(미승인 업체 등록 차단) | 1-B(`content_approval`이 게이트 트리거) | [C-4 §4](common/C-4-search-recommendation-engine.md) |

## 4단계 - API 엔드포인트 (1~3단계 대상 순차 완료 후 해당 엔드포인트 착수)

| # | 엔드포인트 | 의존 | 근거 |
| --- | --- | --- | --- |
| 4-A | `POST/GET/DELETE /saved-recommendables` | 1-A | [W-8 §5](web/W-8-api-and-db-changes.md) |
| 4-B | `POST /common/content-approvals` | 1-B, 2-C | [C-5 §1](common/C-5-common-api.md) |
| 4-C | `POST /common/search`, `POST /common/recommendations`(profile_id 유무 분기) | 2-B, 3-D, 3-F | [C-5 §1](common/C-5-common-api.md) |
| 4-D | `POST /common/qr-sessions` | 없음(`GuestSession.entry_code` 재사용) | [C-5 §3](common/C-5-common-api.md), [K-5 §5](kiosk/K-5-map-location-qr.md) |
| 4-E | `POST /buyer/matches/{id}/meetings`, `PATCH /meetings/{id}/status` (`Meeting`/`MeetingStatusHistory`/`MeetingContactShare` 3테이블만) | 없음(기존 스키마) | [W-7 §1](web/W-7-buyer-matching-consultation.md) |
| 4-F | `POST /guest/convert` | 2-D | [W-8 §5](web/W-8-api-and-db-changes.md) |

## 5단계 - 비동기 워커 (해당 트리거 대상 API 완료 후)

| # | 워커 잡 | 트리거 | 근거 |
| --- | --- | --- | --- |
| 5-A | 임베딩 재계산 | 4-B(승인 확정) | [C-5 §2](common/C-5-common-api.md), [C-7 §2](common/C-7-common-infrastructure.md) |
| 5-B | 행사 후 정적 알림 발송 | `visit_session.session_status→COMPLETED` | [W-6 §3](web/W-6-information-delivery-policy.md), [C-7 §2](common/C-7-common-infrastructure.md) |
| 5-C | 사전등록 배치 임포트 | 관리자 트리거/스케줄 | [W-2 §1-1](web/W-2-user-journey.md), [C-7 §2](common/C-7-common-infrastructure.md) |

## 6단계 - 프론트엔드 (백엔드 API 완료 대상부터 순차 착수 가능)

- 웹(`apps/user-web`): [W-3](web/W-3-screen-ia.md) S-1~S-8 - 4-A/4-C/4-E/4-F 완료된 순서대로 해당 화면 착수 가능.
- 키오스크(`apps/kiosk`): [K-3](kiosk/K-3-screen-ia.md) K-S1~K-S8 - 4-C/4-D 완료 후.
- 관리자(`apps/admin`): [W-9](web/W-9-admin-operations.md) 범위 - 4-B/2-C 완료 후.

## 7단계 - 검증 (전 구현 완료 후)

- [W-10](web/W-10-validation-and-mvp-scope.md) §1~4(웹 시나리오·정확도·사용성·개인정보), [K-8](kiosk/K-8-validation-and-mvp-scope.md) §1~6(키오스크), [C-8](common/C-8-integration-testing-deployment.md) §1~5(웹·키오스크 데이터/검색 일치, 행사별 설정, 배포, 통계)를 순서대로 실행한다.
- 기존 테스트(이전 세션 기준 94개: 83 유닛 + 11 DB 통합)를 회귀 기준선으로 삼아, 2-B(가중치 변경) 이후 반드시 재실행해 점수 계산 관련 assertion이 새 가중치를 반영해 업데이트됐는지 확인한다.

## 8. 이번 재설계로 스키마에서 실제로 삭제되는 것

**없음.** 이번 재설계 전체에서 기존 테이블·컬럼을 삭제하기로 결정한 항목은 하나도 없다 - `AvailabilitySlot`/`MeetingSlotRequest`/`MeetingOutcome`/`FollowUpAction`([W-7 §2](web/W-7-buyer-matching-consultation.md))도 "이번 MVP API에서 노출하지 않는다"이지 삭제가 아니다. 이는 01-module-split-plan.md §6("기존 설계 결과는 모듈별 참고자료로 재분류")의 방침을 스키마 레벨에서 일관되게 지킨 결과다.

## 9. 재설계 완료

`docs/redesign-v2/01-module-split-plan.md` §4("설계 진행순서")·§7("새로운 진행 기준")이 요구한 4단계(1차 웹 → 2차 키오스크 → 3차 공통 플랫폼 → 4차 통합)가 모두 완료되었다. 다음 작업은 이 문서의 1단계부터 실제 구현에 착수하는 것이다.
