# SECURITY.md

## 개인정보 절대 원칙

1. **키오스크는 개인정보를 수집하지 않는다.** 회원가입·전화번호·이메일 입력·장기 프로파일을 추가하지 않는다. `profile.GuestSession`은 개인 식별 컬럼을 갖지 않도록 설계돼 있다(`docs/redesign-v2/kiosk/K-1-service-scope.md` §1) - 이 불변식을 깨는 컬럼 추가는 어떤 이유로도 승인하지 않는다.
2. **상담 연락처는 수락 후에만 공개한다.** `meeting.status = CONFIRMED`와 `MeetingContactShare.disclosed_at` 권한 검사를 함께 적용한다 - `accepted_at`만으로 공개하지 않는다(`docs/redesign-v2/web/W-7-buyer-matching-consultation.md` §3).
3. **미승인 업체는 검색·추천 대상에서 원천 제외한다.** `Recommendable` 레지스트리는 `master_approval_status = 'APPROVED'` 시점에만 등록한다(사전 게이트 방식, 사후 필터링 아님 - `docs/redesign-v2/common/C-4-search-recommendation-engine.md` §4).
4. **원문 토큰을 저장하지 않는다.** `GuestSession.session_token_hmac`처럼 세션 토큰은 해시만 저장한다.
5. **동의(consent)는 목적별로 독립적으로 관리한다.** `EVENT_INFO_NOTIFICATION`/`PERSONALIZED_RECOMMENDATION`/`BUYER_CONTACT_SHARE` 중 하나를 철회해도 다른 목적의 처리가 함께 중단되지 않아야 한다(`docs/redesign-v2/web/W-6-information-delivery-policy.md` §4).

## 권한(Authorization)

- `profile.UserRole`(role_id로 `profile.role.role_code` 참조)이 정본이다. 현재 `role_code_allowed`는 `VISITOR/BUYER/EXHIBITOR/OPERATOR/ADMIN`으로 제한된다 - `DATA_REVIEWER`는 신규 role_code가 아니라 `EVENT_ADMIN` 내부 서비스 스코프로 처리한다(`.harness/decisions.md` DEC-008).
- 다른 트랙 소유 파일에 대한 인가 로직을 임의로 추가하지 않는다 - 인가 매핑의 정본은 `.harness/contracts/`(CTR 완료 후)와 `docs/redesign-v2/common/C-6-privacy-and-authorization.md`다.

## AI 출력 검증

- AI(자연어 추출·구조화) 출력은 JSON Schema로 검증한 뒤에만 사용한다.
- 허용된 온톨로지 코드(`ontology.concept.concept_code`)만 사용 - 원문에 없는 조건을 생성하지 않는다.
- AI 출력값을 검증 없이 DB에 저장하지 않는다 - `ai.extracted_attribute`는 `PENDING` 상태로 먼저 들어가고, 운영자 승인(`ai.content_approval`) 후에만 정본 데이터에 반영한다(`docs/redesign-v2/common/C-2-content-collection-ai-structuring.md` §3).
- 최종 필터·순위는 규칙엔진(하드필터·컨텍스트재랭킹)이 담당한다 - AI가 최종 노출 여부를 직접 결정하지 않는다.

## 감사로그

- AI 호출은 `ai.ai_execution_log`, 그 외 데이터 변경(승인·역할배정 등)은 기존 `audit.audit_log`(`backend/app/models/consent.py`)를 사용한다. 신규 통합 로그 테이블을 만들지 않는다(`docs/redesign-v2/common/C-6-privacy-and-authorization.md` §6).

## 시크릿 관리

- `.env` 등 비밀값을 커밋하지 않는다. `.gitignore`에 이미 등록된 패턴을 확인 없이 되돌리지 않는다.
- 신규 의존성 추가는 ADR이 필요하다(`AGENTS.md` §3).

## G3 릴리스 전 필수 검증 (quality-gates.yaml과 연동)

개인정보 로그 노출 0건, 키오스크 세션 잔존 0건, 권한시험 성공 - 이 3개는 다른 게이트 항목과 달리 "부분 통과"를 허용하지 않는다.
