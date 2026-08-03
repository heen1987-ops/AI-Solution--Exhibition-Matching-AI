# C-6. 공통 AI·데이터 플랫폼 - 개인정보·권한

근거 문서: `docs/redesign-v2/00-master-spec-v1.md`(§24~25, §45.2), `docs/redesign-v2/01-module-split-plan.md`(§4-C C-6). [C-5 §4](C-5-common-api.md)의 인가 메커니즘 질문을 확정하고, W/K 시리즈 전체에 흩어져 있던 개인정보 원칙을 한 곳에 모아 최종 정합성을 확인한다.

## 1. 인가(Authorization) 메커니즘 - 결정

[C-5 §4](C-5-common-api.md)에서 넘긴 질문, [W-9 §1](../web/W-9-admin-operations.md)의 "DATA_REVIEWER는 신규 role_code가 아니라 권한 스코프"라는 결정을 실제로 구현하는 방식을 정의한다.

**결정**: `profile.UserRole`(role_id로 role_code 참조)에 더해, 서비스 계층에 role_code별 **권한 스코프 상수 매핑**을 둔다(신규 테이블 아님 - 코드 상수).

```text
EVENT_ADMIN(OPERATOR) 기본 권한: 전체(사전등록 연계 조회, 바이어 검증, 통계)
EVENT_ADMIN + DATA_REVIEWER 스코프 플래그: 업체정보 승인(content-approval)만 추가 허용
EXHIBITOR(EXHIBITOR_ADMIN): 자사 데이터 한정(exhibitor_id 일치 검사)
```

`DATA_REVIEWER` 스코프 플래그를 어디에 저장할지: `profile.UserRole`에 이미 있는 컬럼만으로는 표현할 수 없으므로(role_id 하나만 참조), **가장 간단한 방법은 `DATA_REVIEWER` 권한만 담당하는 소수 인원에게는 `EVENT_ADMIN` role_id를 부여하는 것 자체를 좁은 스코프의 대체 수단으로 쓰는 것**이다 - 즉 실제로는 "모든 EVENT_ADMIN이 업체정보 승인 권한도 가진다"는 단순화를 채택하고, 승인 권한만 별도로 좁히는 요구가 실제 운영에서 나타나면 그때 세분화 컬럼을 추가한다(YAGNI - [W-9 §1](../web/W-9-admin-operations.md)에서 이미 "확인할 기존 동작이 없다"고 밝힌 것처럼, 아직 검증되지 않은 세분화 요구를 미리 설계하지 않는다).

## 2. 웹 사용자 동의 - 재확인

[W-6 §4](../web/W-6-information-delivery-policy.md)에서 확정한 3개 동의 목적(`EVENT_INFO_NOTIFICATION`/`PERSONALIZED_RECOMMENDATION`/`BUYER_CONTACT_SHARE`)을 그대로 채택 - 추가 변경 없음.

## 3. 키오스크 무수집 - 재확인

[K-1 §1](../kiosk/K-1-service-scope.md)/[K-8 §4](../kiosk/K-8-validation-and-mvp-scope.md)에서 이미 스키마 차원(`GuestSession`에 개인정보 컬럼 없음, `KIOSK_GUEST`에 `UserProfile` 미생성)으로 보장했다 - C-6에서 추가로 강제할 규칙은 없다.

## 4. 바이어 정보공개

- [W-7 §3](../web/W-7-buyer-matching-consultation.md)의 "동의 완료 후에만 연락처 노출"(`MeetingContactShare`) 원칙을 그대로 재확인 - `disclosed_at`/`disclosed_to_user_id`가 실제 노출 권한 검사의 근거.
- 바이어의 `BuyerNeed`(거래조건) 자체는 참가업체에게 어디까지 공개되는지가 마스터 스펙에 명시돼 있지 않다 - **결정**: 상담 요청이 발생하기 전까지는 참가업체가 바이어 개별 프로파일을 열람할 수 없다(추천 대상으로만 시스템 내부에서 매칭되고, 사람이 사람을 직접 조회하지는 못함). 상담 요청이 오면 그 시점부터 요청자의 `BuyerNeed` 요약만 노출한다.

## 5. 업체 공개범위

- [W-3 §5](../web/W-3-screen-ia.md)에서 "업체 상세는 3개 사용자 유형 모두 접근 가능한 공개 데이터"로 확정 - `master_approval_status = 'APPROVED'`([C-4 §4](C-4-search-recommendation-engine.md)) 업체의 승인된 속성만 공개 대상이다. `ai.extracted_attribute`가 아직 `PENDING`/`REJECTED` 상태인 속성은 어떤 사용자에게도 노출하지 않는다([C-2 §3](C-2-content-collection-ai-structuring.md) 흐름의 4단계 이전 데이터).

## 6. 로그·감사

- 마스터 스펙이 요구하는 로그·감사는 `ai.ai_execution_log`([C-2](C-2-content-collection-ai-structuring.md), AI 호출 감사)와 기존 `audit.audit_log`(스키마에 이미 존재, 이전 세션 확인 완료) 두 계층으로 나눈다 - AI 호출은 전용 로그, 그 외 데이터 변경(승인·역할 배정 등)은 기존 감사 로그를 재사용한다. 신규 통합 로그 테이블은 만들지 않는다.

## 7. C-7로 넘기는 질문

없음 - 이 문서에서 모든 항목을 확정했다.
