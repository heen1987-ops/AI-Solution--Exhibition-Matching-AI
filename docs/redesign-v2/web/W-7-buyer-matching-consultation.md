# W-7. 웹 초개인화 모듈 - 바이어 매칭·간단 상담

근거 문서: `docs/redesign-v2/00-master-spec-v1.md`(§14~16), `docs/redesign-v2/01-module-split-plan.md`(§4-A W-7, §56 제외목록). [W-2 §2](W-2-user-journey.md)/[W-2 §4-2](W-2-user-journey.md)에서 확인한 `backend/app/models/meeting.py`의 과대 스펙(7개 테이블)을 MVP 범위로 확정한다.

## 1. MVP에 포함하는 테이블 (3개)

| 테이블 | 역할 | §16 대응 |
| --- | --- | --- |
| `interaction.Meeting` | 상담 요청 루트(요청자·대상 부스·상태) | 상담 요청 |
| `interaction.MeetingStatusHistory` | 상태 변경 이력(append-only) | 수락·거절 상태 추적 |
| `interaction.MeetingContactShare` | 연락처 공유(동의 연동, [W-6 §4](W-6-information-delivery-policy.md)) | 연락처 공유 |

`Meeting.status`는 요청(`REQUESTED`) → 수락(`CONFIRMED`) 또는 거절(`DECLINED`/`CANCELLED` 계열) 두 갈래만 웹 모듈 화면(S-6)에서 노출한다 - 기존 `MEETING_STATUSES` 전체 어휘 중 실제 화면이 필요로 하는 부분만 노출하고, 어휘 자체(CHECK 제약)는 바꾸지 않는다(다른 소비자가 있을 수 있으므로).

## 2. MVP에서 노출하지 않는 테이블 (4개, 삭제하지 않음)

| 테이블 | 제외 사유 |
| --- | --- |
| `AvailabilitySlot` | §56 "대규모 상담장 자동배정" 제외 대상. 시간 슬롯 예약 없이 "요청 → 수락"만으로 충분 |
| `MeetingSlotRequest` | 위와 동일 - 슬롯이 없으면 슬롯 요청도 필요 없음 |
| `MeetingOutcome` | §56 "장기 거래 CRM" 제외 대상(영업 리드 상태 추적) |
| `FollowUpAction` | 위와 동일(후속 조치 CRM) |

이 4개는 **스키마에서 제거하지 않는다** - 기존 자산이고, 이번 재설계 방침(01-module-split-plan.md §6 "기존 설계 결과는 모듈별 참고자료로 재분류")에 따라 향후 CRM 확장 시 재사용 가능성이 있다. W-7 결정은 "이번 MVP API·화면이 이 4개 테이블에 대한 CRUD를 제공하지 않는다"는 범위 결정일 뿐, 스키마 변경 결정이 아니다.

## 3. 상담 요청 → 수락/거절 → 연락처 공유 흐름

```text
1. BUYER_REGISTERED가 S-6(바이어 매칭)에서 업체 선택 → 상담 요청
   → Meeting(status=REQUESTED) 생성, topic_concept_id에 관심분야 연결(선택)
2. 참가업체(EXHIBITOR_ADMIN, 관리자 포털)가 요청 확인 → 수락/거절
   → MeetingStatusHistory에 전이 기록, Meeting.status 갱신
3. 수락(CONFIRMED) 시:
   a. MeetingContactShare 행 생성, consent_policy_id = BUYER_CONTACT_SHARE 동의건 참조
   b. 바이어가 사전에 BUYER_CONTACT_SHARE 동의를 하지 않았다면 이 시점에 동의 요청 화면을 띄운다
   c. 동의 완료(accepted_at 기록) 후에만 disclosed_at/disclosed_to_user_id를 채워 실제 연락처 노출
4. 거절 시: MeetingStatusHistory만 기록, MeetingContactShare 생성 안 함
```

- **핵심 규칙(기존 코드 주석에 이미 명시됨)**: "accepted_at만으로 연락처를 공개하지 않는다 - `meeting.status = CONFIRMED`와 `disclosed` 권한 검사를 함께 적용한다." 이 규칙은 서비스 계층에서 그대로 재사용한다.
- [W-6 §5](W-6-information-delivery-policy.md)의 미결정 사항(동의 철회 시 소급 삭제 여부): `disclosed_at`이 이미 기록된 건은 소급 삭제하지 않는다(이미 공개된 정보를 되돌릴 수 없으므로) - 철회는 "향후 신규 상담 건에 대해 자동 동의 요청 화면을 다시 띄운다"는 의미로 한정한다.

## 4. 업체 비교 (§14.2, 관심 저장과의 관계)

- S-6 내 "업체 비교"는 별도 테이블이 필요 없다 - `profile.saved_recommendable`([W-4 §6](W-4-profile-model.md))에 저장된 항목들을 나란히 조회하는 화면 기능일 뿐이다. 비교 상태를 서버에 별도로 저장하지 않는다(무상태 - 클라이언트가 관심목록에서 선택한 N개를 매번 조회).

## 5. W-8로 넘기는 질문

1. 상담 요청 API가 `Meeting.staff_id`(특정 담당자 지정)를 요구하는지, 아니면 부스 단위로만 요청하고 담당자 배정은 참가업체 쪽에서 하는지 - 후자가 §56 "상담장 자동배정 제외" 원칙에 더 부합하므로 기본값으로 채택하되 W-8에서 API 계약으로 확정.
2. `topic_concept_id`(상담 주제)를 요청 시 필수로 받을지 선택으로 둘지.
