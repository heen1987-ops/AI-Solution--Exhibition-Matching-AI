# Future Wave Prompts (received early, not yet started)

사용자가 Wave 1 작업이 끝나기 전에 WAVE 2B, WAVE 2C 실행 프롬프트를 미리 전달했다. 두 프롬프트 모두 자체 진입조건("G2A/G2B_..._COMPLETE = PASS")을 명시하고 있고, 그 조건이 충족되지 않으면 시작하지 않는다고 스스로 규정한다 - 아직 G1_CONTRACT_FREEZE도 통과하지 못한 시점이므로 착수하지 않았다(`.harness/decisions.md` 참고). 이 문서는 그 두 프롬프트의 핵심 내용을 다음 세션/컨텍스트에서도 복원 가능하도록 보존한다.

**중요한 구조적 격차**: 두 프롬프트 모두 파일 소유권을 `apps/api/src/modules/{module}/**` 형태로 가정한다. 이 저장소는 `apps/api`를 만들지 않고 `backend/`를 API 정본으로 유지하기로 했다(ASSUMPTION-005). 이 Wave들을 실제로 시작할 때, `backend/app/services/{module}/**` 또는 `backend/app/api/v1/endpoints/{module}.py` 형태로 경로를 재매핑해야 한다 - `.harness/worker-prompts.md`의 경로 재매핑표와 동일한 패턴을 적용한다.

---

## WAVE 2B: 사전등록 사용자 프로파일·웹 초개인화 추천

- Gate: `G2B_PERSONALIZATION_COMPLETE`. 진입조건: `G2A_CATALOG_SEARCH_COMPLETE = PASS`(이 저장소 게이트 체계에는 아직 없음 - G1_CONTRACT_FREEZE와 G2_FEATURE_COMPLETE 사이에 신설이 필요할 수도, 혹은 G2_FEATURE_COMPLETE의 하위 마일스톤으로 흡수할 수도 있음 - 착수 시점에 결정), `contract_status = FROZEN_V1`.
- 핵심 시나리오: 사전등록 연계 → 프로파일 생성 → 관심분야 확인·수정 → 개인화 추천 생성 → 이유 표시 → 관심 저장 → 자연어 추가검색 → 명시적 피드백.
- 제외: 바이어 매칭·상담(Wave 2C), 이메일·문자 자동발송, 암묵적 장기학습, 실시간 위치, 광고 슬롯.
- 병렬 트랙(10개): CONTRACTS-PERSONALIZATION, BACKEND-REGISTRATION/PROFILE/FAVORITE/RECOMMENDATION, AI-PERSONALIZATION, USER-WEB-PROFILE/RECOMMENDATION, ADMIN-REGISTRATION, QA-PERSONALIZATION.
- 핵심 계약: `POST /api/v1/events/{event_id}/registration/sync`, `GET|PATCH /api/v1/me/event-profile`, `POST /api/v1/recommendations`+`GET .../{id}`, `GET|POST|DELETE /api/v1/me/favorites`, (신규 가능성) `POST /api/v1/recommendations/{result_id}/feedback`, `GET|POST /api/v1/admin/registration-imports`.
- 신규 DB 후보: `registered_users, external_references, user_event_profiles, profile_interests, consent_records, favorites, recommendation_sessions, recommendation_results, recommendation_feedback` - CTR-008(Wave 1)이 이미 이 목록의 상당수를 기존 스키마(`profile.user_profile`, `profile.saved_recommendable` 등)와 대조하는 중이므로, Wave 2B 착수 전 CTR-008 결과를 먼저 반영해야 진짜 신규분만 추가하게 된다.
- 점수식(마스터스펙 W-5와 동일): `0.35 User Interest + 0.25 Current Query + 0.15 Visit Goal + 0.10 Explicit Behavior + 0.10 Data Quality + 0.05 Booth Availability` - `docs/redesign-v2/web/W-5-recommendation-logic.md`가 이미 다룬 것과 동일 공식, 재조정 대상은 이미 `04-integration-roadmap.md` 2단계 2-B.
- 프로파일 상태: `IMPORTED/CONFIRMED/UPDATED/DISABLED`, 관심 출처 우선순위 `EXPLICIT > CONFIRMED > IMPORTED > INFERRED`, `REJECTED`는 입력 제외.
- 개인화 중지 시 행동기반 추론 금지, 기본 검색형 결과로 폴백.
- 상세 API 예시·테스트 목록·성능 목표(P95)는 이 대화의 사용자 메시지 원문에 있음 - 착수 시 그 메시지를 다시 참고하거나, 사용자에게 재전달을 요청한다.

## WAVE 2C: 바이어 매칭·간단 상담 연결

- Gate: `G2C_BUYER_MATCHING_COMPLETE`. 진입조건: `G2B_PERSONALIZATION_COMPLETE = PASS`.
- 핵심 시나리오: 바이어 검증 확인 → 거래 프로파일 → Hard Filter → 매칭 → 업체 비교(최대 4개) → 상담 요청 → 업체 수락/거절/시간제안 → 수락+동의 후에만 제한적 연락처 공유.
- 제외: 견적·계약·발주·정산·샘플배송, 장기 CRM/리드 점수, 상담장 자동배정, 외부 캘린더, 화상회의, 자유채팅, 키오스크 상담, AI 단독 승인/거절.
- 병렬 트랙(11개): CONTRACTS-BUYER, BACKEND-BUYER-PROFILE/EXHIBITOR-PREFERENCE/BUYER-MATCH/MEETING, AI-BUYER-MATCH, USER-WEB-BUYER/MEETING, ADMIN-BUYER, EXHIBITOR-MEETING, QA-BUYER.
- 바이어 검증상태: `UNVERIFIED/PENDING/VERIFIED/LIMITED/REJECTED/SUSPENDED/EXPIRED` - 권한 매트릭스(업체매칭/상담요청/연락처공유)는 원문 §9.3 표 참고.
- 거래조건 상태값: `YES/NO/CONDITIONAL/NEGOTIABLE/UNKNOWN` - 기존 `TRADE_AVAILABILITY_STATUSES`(이전 세션에서 확인)와 이름이 다르나 값 집합은 사실상 동일(UNKNOWN 포함 5종) - Wave 2C 착수 시 그대로 재사용 가능할 것으로 추정, 재확인 필요.
- B2E 점수식: `0.20 Product·Tech + 0.15 Business Goal + 0.15 Channel + 0.15 Order Scale·MOQ + 0.10 Region + 0.10 Cooperation + 0.10 Trade Readiness + 0.05 Data Trust` - `docs/redesign-v2/web/W-5-recommendation-logic.md` §2의 Buyer Match Score와 동일 공식(이미 기존 `BUYER_SCORE_V1`과 대조·재계량 대상으로 식별돼 있음).
- E2B 점수식과 Mutual(조화평균)은 이미 `docs/redesign-v2/common/C-4-search-recommendation-engine.md`가 다룬 것과 개념적으로 동일 - 기존 `RECIPROCAL_SCORE_V1`(`calculate_reciprocal_score`)이 이미 조화평균 기반 상호점수를 구현하고 있음(이전 세션에서 확인) - 재구현이 아니라 재사용 가능성 높음, 착수 시 재확인.
- 매칭 등급 임계값: `HIGH>=80, MEDIUM>=65, POSSIBLE>=50, LOW<50`.
- 연락처 공개 조건: `meeting.status=ACCEPTED AND buyer.contact_share_consent=true AND exhibitor_contact.enabled=true` - 기존 `MeetingContactShare` 스키마(W-7 §3에서 이미 검증한 "accepted_at만으로 공개하지 않는다" 규칙)와 정확히 같은 원칙, 그대로 재사용 가능할 것으로 추정.
- 상담 상태전이: `REQUESTED→{ACCEPTED,TIME_PROPOSED,REJECTED,CANCELLED}`, `TIME_PROPOSED→{ACCEPTED,TIME_PROPOSED,REJECTED,CANCELLED}`, `ACCEPTED→{COMPLETED,CANCELLED}` - 기존 `Meeting.status` 10종 어휘와 대조 필요(이름이 정확히 일치하지 않음 - 예: 기존엔 `VIEWED`/`COUNTER_PROPOSED`/`NO_SHOW`가 있고 이 프롬프트엔 없음).
- 상세 API 예시·테스트 목록·성능 목표는 사용자 메시지 원문 참고.

## 착수 순서 재확인

`01-module-split-plan.md` §4/§7이 이미 확정한 "웹 → 키오스크 → 공통" 순서와, 이번에 받은 Wave 2B(개인화)→2C(바이어매칭)→2D(AI 구조화) 순서는 서로 호환된다 - 둘 다 "일반 사용자 개인화 먼저, 바이어 매칭 나중"이라는 같은 우선순위를 공유한다. 실제 착수는 Wave 1(G1_CONTRACT_FREEZE)이 끝난 뒤다.
