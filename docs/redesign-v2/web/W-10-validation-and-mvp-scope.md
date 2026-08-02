# W-10. 웹 초개인화 모듈 - 검증·MVP 범위

근거 문서: `docs/redesign-v2/00-master-spec-v1.md`(§54 Phase별 완료기준, §56 제외목록), `docs/redesign-v2/01-module-split-plan.md`(§4-A W-10). W-1~W-9를 종합해 웹 모듈 설계를 마감한다. 이 문서를 끝으로 재설계 진행순서(§7)의 "1차: 웹 초개인화 모듈"이 완료되고, "2차: 키오스크 이식모듈(K-1~K-8)"로 넘어간다.

## 1. 사용자 시나리오 (W-2 여정의 End-to-End 재확인)

| 시나리오 | 경로 | 검증 포인트 |
| --- | --- | --- |
| GENERAL_REGISTERED 표준 여정 | [W-2 §1](W-2-user-journey.md) 1~9단계 전체 | 사전등록→로그인→프로파일 완성→추천→저장→행사당일→후속정보 각 단계 전이가 끊기지 않는지 |
| BUYER_REGISTERED 매칭 여정 | [W-2 §2](W-2-user-journey.md) + [W-7](W-7-buyer-matching-consultation.md) | 상담 요청부터 연락처 공유까지 동의 체크가 정확한 시점(수락 이후)에 걸리는지 |
| GUEST_WEB 여정 | [W-2 §3](W-2-user-journey.md) | 회원 전환 전까지 관심 저장·MY정보 화면이 정확히 차단되는지([W-3 §0](W-3-screen-ia.md) 접근 표) |
| 게스트→회원 전환 | [W-8 §6](W-8-api-and-db-changes.md) | 위치 데이터만 승계되고 관심 신호는 승계되지 않는지 |
| 동의 철회 | [W-6 §4](W-6-information-delivery-policy.md) | `PERSONALIZED_RECOMMENDATION` 철회 시 콜드스타트 경로로 정확히 폴백하는지 |

## 2. 추천 정확도 검증 방향

- W-5에서 재조정하기로 한 `ScoringPolicy.weights`([W-5 §3](W-5-recommendation-logic.md))의 실제 수치는 이 문서에서 검증 기준을 만들 수 없다 - **정성적 검증**(추천 상위 N개가 사용자 관심분야와 명백히 무관하지 않은지, 하드필터로 걸러야 할 후보가 실제로 걸러지는지)까지만 W-10 범위로 하고, 정량적 정확도(클릭률·전환율)는 실제 운영 데이터가 쌓인 뒤(행사 이후)에나 측정 가능하므로 MVP 검증 항목에서 제외한다.
- `current_query` 컴포넌트([W-5 §3](W-5-recommendation-logic.md))는 C-4 완료 전까지 검증 대상이 아니다.

## 3. 사용성 검증

- S-1~S-8([W-3](W-3-screen-ia.md)) 전 화면에서 사용자 유형별 접근 제어(W-3 §0 표)가 프론트엔드가 아니라 **API 레벨에서** 강제되는지 확인한다 - 화면을 숨기는 것만으로는 불충분하고, GUEST_WEB 계정으로 `GET /profile/me`나 `POST /saved-recommendables`를 직접 호출했을 때 403이 반환되어야 한다([W-8 §5](W-8-api-and-db-changes.md) API 표 기준).

## 4. 개인정보 검증

- [W-6 §4](W-6-information-delivery-policy.md)의 3개 동의 목적(`EVENT_INFO_NOTIFICATION`/`PERSONALIZED_RECOMMENDATION`/`BUYER_CONTACT_SHARE`)이 각각 독립적으로 켜고 끌 수 있는지, 하나를 철회했을 때 다른 목적의 처리까지 함께 중단되지 않는지 확인한다.
- GUEST_WEB의 "지속 프로파일 없음" 원칙([W-1 §3](W-1-scope-and-user-types.md))이 실제로 지켜지는지: 회원 전환을 하지 않은 GUEST_WEB 세션이 종료된 뒤 해당 `guest_session_id` 소유의 `UserProfile`/`VisitSession` 행에 개인 식별 가능 정보가 전혀 없는지 점검한다(애초에 이 행들은 익명 소유이므로 개인정보 자체가 없음을 스키마 차원에서 재확인).

## 5. 개발 우선순위 (구현 착수 시 참고)

W-1~W-9에서 나온 실제 작업 항목을 의존관계 순서로 재배열한다.

```text
1. profile.saved_recommendable 마이그레이션 (W-8 §1/§4) - 다른 항목 대부분이 이 테이블에 의존
2. API 응답 레이어 user_type/role_code 매핑 (W-8 §2) - 스키마 변경 없이 착수 가능
3. ScoringPolicy.weights 재조정 (W-5 §3, W-8 §1) - 기존 테스트(94개) 재실행으로 회귀 확인 필요
4. 상담 흐름(Meeting 3테이블) API 구현 (W-7) - AvailabilitySlot 등 4테이블은 건드리지 않음
5. 관리자 포털 권한 세분화(EVENT_ADMIN 내부 DATA_REVIEWER 스코프) (W-9 §1)
6. current_query 컴포넌트 - C-4(공통 검색엔진) 완료 후 착수
```

## 6. MVP 제외 최종 확인 (W-1~W-9 전체 재확인)

[W-1 §5](W-1-scope-and-user-types.md), [W-2 §2](W-2-user-journey.md)(주석), [W-7 §2](W-7-buyer-matching-consultation.md)에서 개별적으로 확인한 제외 항목을 한 곳에 모은다 - 구현 중 "이거 만들어야 하나?"라는 질문이 생기면 이 목록부터 확인한다.

- 장기 거래 CRM, 견적·계약·정산, 샘플 배송관리 (`MeetingOutcome`/`FollowUpAction` 미사용)
- 상담장 자동배정 (`AvailabilitySlot`/`MeetingSlotRequest` 미사용)
- 실시간 온라인 학습형 랭킹, 복잡한 공정성 최적화
- 정밀 위치추적, 복잡한 경로 최적화, 실시간 혼잡 예측모델 (zone 단위 위치로 대체)
- 독립 마케팅 자동화 플랫폼 (1회성 정적 알림만, [W-6 §2](W-6-information-delivery-policy.md))
- 문자(SMS) 발송 ([W-6 §3](W-6-information-delivery-policy.md), 규제 이슈로 확장 항목 분류)
- GUEST_WEB의 자체 자연어 검색 (기본 비활성, [W-3 §2](W-3-screen-ia.md))

## 7. 웹 모듈 설계 완료 선언

W-1([사용자 구분](W-1-scope-and-user-types.md))부터 W-9([관리자 운영](W-9-admin-operations.md))까지 모든 미결정 항목이 해소되었다(각 문서의 "다음 단계로 넘기는 질문" 절이 다음 문서에서 실제로 답변된 것을 확인). 다음 작업은 `docs/redesign-v2/01-module-split-plan.md` §7의 순서에 따라 **K-1(키오스크 서비스 범위)**부터 시작한다.
