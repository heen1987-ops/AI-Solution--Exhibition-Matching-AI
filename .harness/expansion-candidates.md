# Expansion Candidates

범위 밖이지만 가치가 있을 수 있는 아이디어. 현재 구현하지 않는다.

---

## EXPANSION-001

질문: 키오스크 음성입력이 필요한가?

분류: POST_MVP

근거: 화면 키보드와 카테고리 탐색으로 MVP 검증 가능(`docs/redesign-v2/kiosk/K-6-i18n-accessibility.md` §3)

재검토 조건: 외국어·고령 사용자 현장 테스트에서 텍스트 입력 실패율 20% 이상

---

## EXPANSION-002

질문: 상담 시간 슬롯 예약(`AvailabilitySlot`/`MeetingSlotRequest`)을 웹 모듈에 다시 노출해야 하는가?

분류: NEXT_WAVE

근거: 테이블은 이미 구현돼 있으나 이번 MVP는 "요청→수락/거절"만으로 충분하다고 판단(`docs/redesign-v2/web/W-7-buyer-matching-consultation.md` §2)

재검토 조건: 참가업체 상담 담당자가 다수(스태프 여러 명)인 행사에서 무작위 시간 충돌 신고가 발생

---

## EXPANSION-003

질문: 영업 리드 추적(`MeetingOutcome`/`FollowUpAction`)을 되살려야 하는가?

분류: POST_MVP

근거: 장기 거래 CRM은 명시적 제외범위(`docs/redesign-v2/00-master-spec-v1.md` §56, 메타프롬프트 §3)

재검토 조건: 참가업체가 상담 이후 거래 성사 여부를 시스템에서 추적해달라는 요구가 반복 접수됨

---

## EXPANSION-004

질문: SMS(문자) 알림 발송이 필요한가?

분류: NEXT_WAVE

근거: 별도 발신번호·사업자 등록 등 규제 이슈로 이메일만 MVP 포함(`docs/redesign-v2/web/W-6-information-delivery-policy.md` §3)

재검토 조건: 행사 주최측이 SMS 발신 자격을 이미 보유하고 있음을 확인

---

## EXPANSION-005

질문: 정밀 실내 내비게이션(좌표 기반 경로 안내)이 필요한가?

분류: REJECTED_SCOPE

근거: 메타프롬프트 §3 명시적 제외항목이며, 기존 스키마도 애초에 zone(구역) 단위로만 설계되어 좌표 데이터 자체가 없다(`docs/redesign-v2/kiosk/K-5-map-location-qr.md` §2)

재검토 조건: 없음(서비스 목적과 맞지 않는 것으로 판단, 좌표 인프라 도입 자체가 별도 대형 프로젝트)
