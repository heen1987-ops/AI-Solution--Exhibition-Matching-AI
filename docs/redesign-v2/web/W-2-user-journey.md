# W-2. 웹 초개인화 모듈 - 사용자 여정

근거 문서: `docs/redesign-v2/00-master-spec-v1.md`(§8~16), `docs/redesign-v2/01-module-split-plan.md`(§4-A W-2). [W-1](W-1-scope-and-user-types.md)에서 확정한 사용자 구분(`GENERAL_REGISTERED`/`BUYER_REGISTERED`/`GUEST_WEB`)과 행사 전·중·후 제공범위를 실제 화면 흐름 단위로 전개한다.

## 0. 여정을 나누는 기준

마스터 스펙 §4(설계 진행순서)의 항목("사전등록 연계, 최초 로그인, 프로파일 확인, 추천 확인, 관심 저장, 행사 당일 활용, 행사 후 후속정보")을 그대로 단계로 삼되, `GUEST_WEB`은 "사전등록 연계"가 없으므로 별도 여정으로 분리한다([W-1](W-1-scope-and-user-types.md) §4 참고).

## 1. GENERAL_REGISTERED / BUYER_REGISTERED 공통 여정

```text
[행사 전]
 1. 사전등록 연계 → 2. 최초 로그인 → 3. 프로파일 확인·보완 → 4. 사전 추천 확인
[행사 중]
 5. 개인화 홈 진입 → 6. 추천 확인·자연어 추가검색 → 7. 관심 저장 → 8. 행사 당일 활용(위치·동선)
[행사 후]
 9. 후속정보 수신
```

### 1-1. 사전등록 연계 (행사 전)

- **트리거**: 행사 주최측이 보유한 사전등록 명단(외부 등록 시스템)에서 이메일/전화번호 등 식별자가 웹 모듈로 연계된다.
- **기존 스키마 대응**: `identity.UserIdentity`/`AuthenticationMethod`로 계정을 생성하고, `profile.UserProfile`을 `user_type IN ('GENERAL_VISITOR','BUYER')`로 미리 생성해둘 수 있다(W-1 §6-1의 리네이밍 여부와 별개로 로우 자체는 사전 생성 가능).
- **결정 필요(→ W-8)**: 사전등록 연계가 "실시간 API 동기화"인지 "배치 CSV 임포트"인지는 마스터 스펙에 구체적으로 명시되어 있지 않다. MVP 범위에서는 배치 임포트로 가정하고, 실시간 연동은 확장 항목으로 둔다.

### 1-2. 최초 로그인 (행사 전 또는 행사 당일)

- 사전등록 시 사용한 식별자(이메일 등)로 본인확인 후 계정을 활성화한다.
- 이 시점에 `profile.consent_policy`/`user_consent`(수신동의) 체크가 발생한다 - W-6(정보전달 정책)에서 상세 정의. `consent_policy.purpose`가 자유 문자열이라는 점(이전 세션에서 확인)은 W-6에서 실제 목적 문자열 목록을 서비스 정책으로 확정해야 함을 의미한다.
- **최초 로그인 = 프로파일 완성의 시작점**이지, 로그인만으로 추천이 바로 완성되지는 않는다 (다음 단계 참고).

### 1-3. 프로파일 확인·보완 (행사 전)

- 사전등록 데이터에서 넘어온 정보(관심분야 등 있으면)를 `profile.ProfileAttribute`에 반영하고, 사용자가 직접 확인·수정할 수 있는 화면을 제공한다(§9.3).
- `profile.UserProfile.completeness_score`(0~100)를 이 단계의 진행률 지표로 재사용한다 - 새 필드를 만들 필요 없이 기존 CHECK 제약(`completeness_score_range`)이 이미 존재한다.
- BUYER는 이 단계에서 `profile.BuyerNeed`(거래조건)도 함께 확인한다(§14.1) - GENERAL_REGISTERED에는 해당 없음.

### 1-4. 사전 추천 확인 (행사 전)

- 완성된 프로파일을 근거로 "행사 전 미리보기" 추천을 제공한다 - 실제 추천 로직은 W-5에서 정의하되, 이 시점에는 `visit_session`이 아직 없으므로(방문 세션은 행사장 진입 시 생성) `context_profile`(위치·잔여시간 등 상황정보) 없이 프로파일 기반 점수만으로 계산해야 한다.
- **W-5로 넘기는 질문**: 상황정보가 없는 "행사 전" 추천과, 상황정보가 있는 "행사 중" 추천이 같은 점수식을 쓰는지, 아니면 가중치를 다르게 하는지(예: 부스 대기시간 컴포넌트는 행사 전에는 의미가 없으므로 제외) - W-5에서 결정한다.

### 1-5. 개인화 홈 진입 (행사 중)

- 로그인 후 진입하는 첫 화면. `profile.VisitSession`을 이 시점에 생성(또는 재개)한다 - 기존 스키마의 `visit_session_status IN ('PLANNED','ACTIVE','COMPLETED','CANCELLED')`가 이 여정과 정확히 대응한다: 행사 전 단계는 `PLANNED`, 개인화 홈 진입 시 `ACTIVE`로 전이.
- `profile.ContextProfile`(현재 구역, 잔여시간, 혼잡회피 여부 등)을 이 시점부터 스냅샷으로 쌓기 시작한다.

### 1-6. 추천 확인·자연어 추가검색 (행사 중)

- 개인화 홈의 추천 목록 + 자연어로 "지금 이 순간의 추가 요구"를 검색하는 기능(§12) - 키오스크의 자연어 검색(K-4)과 검색 엔진(공통 플랫폼 C-4)은 공유하지만, 웹은 여기에 사용자 프로파일을 추가로 결합한다는 점이 다르다(01-module-split-plan.md §2.3 "웹 = 프로파일+현재 요구+업체정보").

### 1-7. 관심 저장 (행사 중)

- **스키마 공백 확인**: 현재 `backend/app/models/*.py` 전체를 검색한 결과 "관심 업체 저장(즐겨찾기)"에 해당하는 테이블이 **존재하지 않는다**. `exhibition.recommendable`(추천 후보 레지스트리)까지는 있지만, 사용자가 특정 후보를 "저장"했다는 사실을 기록하는 테이블이 없다.
- 이는 W-4(프로파일 모델)/W-8(웹 API·DB)에서 새 테이블(가칭 `profile.saved_recommendable`: `profile_id`/`user_id` + `recommendable_id` + `saved_at`, unique 제약)을 추가해야 한다는 뜻이며, 이번 W-2 시점에는 "저장이 필요하다"는 여정상의 사실만 확정해 둔다.
- 관심 저장은 §34.1(행동학습 4종) 중 하나이므로, 저장 즉시 `inferred_preference`에 강한 가중치로 반영할지, 아니면 관심목록은 관심목록대로 별도 테이블로 유지하고 `inferred_preference`는 약한 신호로만 갱신할지는 W-5에서 결정한다.

### 1-8. 행사 당일 활용 (행사 중)

- 부스 위치 확인·동선 안내. 기존 `VisitSession.current_zone_id`/`ContextProfile.remaining_minutes`/`max_walk_minutes`/`avoid_congestion`이 이미 이 여정을 위해 설계돼 있다 - 재설계 없이 그대로 재사용한다.
- 마스터 스펙 §56 제외목록(정밀 위치추적, 복잡한 경로 최적화, 실시간 혼잡 예측모델)에 따라, `current_zone_id`는 "구역 단위" 위치이지 GPS 좌표가 아니며, 동선 안내는 "기본 부스 위치·지도 표시" 수준까지만이다 - 기존 스키마가 애초에 좌표가 아닌 zone 단위로 설계돼 있어 이 제약과 이미 정합적이다.

### 1-9. 행사 후 후속정보 (행사 후)

- `VisitSession.session_status`가 `COMPLETED`로 전이된 이후 시점.
- BUYER_REGISTERED는 여기서 상담 상태 확인(§16.2)이 추가된다.
- 발송 채널(이메일·문자)과 마케팅 자동화의 경계는 [W-1 §6-4](W-1-scope-and-user-types.md)에서 이미 미결정 사항으로 남겨뒀다 - W-6에서 확정.

## 2. BUYER_REGISTERED 전용 분기 (바이어 매칭·상담)

공통 여정의 6번(추천 확인) 단계 이후, BUYER_REGISTERED만 다음 분기가 추가된다(§14~16, W-7에서 상세화).

```text
업체 매칭 추천 확인 → 업체 비교 → 관심 저장(공통 7번과 동일 메커니즘 재사용)
   → 상담 요청 → (업체측) 수락/거절 → 연락처 공유
```

- 상담 요청·수락/거절은 기존 `meeting.py`(`backend/app/models/meeting.py`)의 모델을 그대로 재사용할 수 있는지 W-7에서 확인한다 - 이번 W-2에서는 파일 존재만 확인했고 내용은 아직 대조하지 않았다.
- 마스터 스펙 §56 제외목록: 상담장 자동배정, 견적·계약·정산, 샘플 배송관리는 이 분기에 포함하지 않는다 - "요청 → 수락/거절 → 연락처 공유"에서 끝난다.

## 3. GUEST_WEB 여정 (사전등록 없음)

```text
(키오스크에서 QR 스캔) → 모바일 웹 진입 → 결과 열람(목록·상세·지도)
   → [선택] 회원 전환 → GENERAL_REGISTERED/BUYER_REGISTERED 여정으로 합류
```

- GUEST_WEB은 "사전등록 연계"·"최초 로그인"·"프로파일 확인" 단계 자체가 없다 - QR 인계 시점에 이미 키오스크 세션(K-5)에서 검색된 결과를 이어받는다.
- `profile.UserProfile`은 `guest_session_id` 소유로 생성되지만(W-1 §3 규칙), `VisitSession` 역시 `guest_session_id` 소유로 생성 가능함을 스키마에서 이미 확인했다(`num_nonnulls(user_id, guest_session_id) = 1`) - 즉 GUEST_WEB도 "행사 당일 활용"(구역 위치 확인)까지는 기존 스키마로 커버되지만, "관심 저장"은 회원 전환 전까지는 제공하지 않는다(§3의 "지속 프로파일 없음" 원칙과 연결 - 저장은 지속 데이터이므로 게스트 단계에서는 제공하지 않는 것이 원칙에 부합한다. **W-3 화면 IA에서 이 제약을 화면 단위로 확정**).
- 회원 전환 시점에 `guest_session_id` 소유 로우를 `user_id` 소유로 승계하는 절차(마이그레이션이 아니라 서비스 로직)가 필요하다 - W-8에서 API로 정의한다.

## 4. 이 문서가 W-3 이전에 남기는 미결정 사항

1. GUEST_WEB의 회원 전환 시 기존 게스트 데이터(방문세션·상황정보) 승계 범위 - 전부 승계할지, 위치정보만 승계하고 관심 신호는 승계하지 않을지 (W-3/W-8).
2. ~~`meeting.py` 기존 모델이 §16(간단 상담)의 "요청→수락/거절→연락처 공유" 흐름을 그대로 커버하는지~~ **[대조 완료, 축소 필요]** `backend/app/models/meeting.py`를 확인한 결과 `AvailabilitySlot`(슬롯 용량·시간대), `Meeting`, `MeetingSlotRequest`, `MeetingContactShare`(CONFIRMED 상태 + 별도 disclosed 플래그 이후에만 공개), `MeetingStatusHistory`, `MeetingOutcome`(영업 리드 상태), `FollowUpAction`까지 7개 테이블로 구성된, 마스터 스펙 §56이 명시적으로 제외한 "상담장 자동배정"(`AvailabilitySlot`/`MeetingSlotRequest`)과 "장기 거래 CRM 성격의 리드 추적"(`MeetingOutcome`/`FollowUpAction`)에 해당하는 기능까지 이미 구현돼 있다. §16의 MVP는 "요청→수락/거절→연락처 공유"만 필요하므로, `Meeting`+`MeetingStatusHistory`+`MeetingContactShare` 3개만 웹 모듈이 그대로 재사용하고, `AvailabilitySlot`/`MeetingSlotRequest`/`MeetingOutcome`/`FollowUpAction`은 이번 MVP API·화면에서 노출하지 않는 방향으로 W-7에서 확정한다(테이블 자체를 삭제할지, 그대로 두되 미사용으로 남길지는 별도 결정 - 기존 자산이므로 삭제는 신중히 판단).
3. "관심 저장" 신규 테이블의 정확한 스키마(단순 저장 목록인지, 저장 시점의 컨텍스트도 함께 남기는지) - W-4.
4. 사전등록 연계가 실시간 API인지 배치인지 - W-8.
