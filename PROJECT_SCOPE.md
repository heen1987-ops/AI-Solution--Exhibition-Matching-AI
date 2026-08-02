# PROJECT_SCOPE.md

단일 기준 문서: `docs/redesign-v2/00-master-spec-v1.md`. 이 문서는 그 요약이며 충돌 시 원문이 우선한다.

## 모듈 범위

### A. 웹 초개인화 모듈
대상: 사전등록 일반 사용자, 사전등록 바이어. 핵심 기능: 사전등록 데이터 연계, 행사별 사용자 프로파일, 관심영역 기반 업체·부스 추천, 자연어 추가검색, 관심 업체 저장, 바이어 업체 매칭, 간단 상담 요청·수락·거절, 행사 전·중·후 맞춤정보. 상세: `docs/redesign-v2/web/W-1~W-10`.

### B. 키오스크 이식형 검색모듈
대상: 현장 비등록 방문객, 익명 게스트. 핵심 기능: 익명 단기 세션, 다국어 시작화면, 자연어·카테고리 검색, 관련 업체·부스 목록, 업체 상세, 부스 지도, QR 모바일 인계, 자동 세션 초기화, 기본 로컬 캐시. 상세: `docs/redesign-v2/kiosk/K-1~K-8`.

**키오스크에 절대 구현하지 않는 것**: 회원가입, 전화번호·이메일 입력, 장기 사용자 프로파일, 장기 행동학습, 결제, 장기 상담 CRM, 개인별 알림, 지속 위치추적.

### C. 공통 AI·데이터 플랫폼
행사·업체·제품·서비스·부스 데이터, 관심영역 온톨로지, 업체자료 AI 구조화, 자연어 의도·조건 추출, 구조화·키워드·벡터 하이브리드 검색, 웹 초개인화 추천, B2B 바이어 매칭, 추천·검색 이유 생성, 업체정보 승인, 기본 운영 통계, 권한·감사로그. 상세: `docs/redesign-v2/common/C-1~C-8`.

## 명시적 제외범위 (개발하지 않음)

정밀 실내 내비게이션, 실시간 혼잡 예측모델, 실시간 제품별 재고관리, 키오스크 사용자 로그인, 키오스크 장기 개인화, 장기 영업 CRM, 견적·계약·정산, 샘플 배송관리, 마케팅 자동화 플랫폼, 실시간 온라인 학습, Multi-Armed Bandit, 전용 벡터 데이터베이스(pgvector로 충분), Kafka, 복잡한 마이크로서비스 분리, 대규모 데이터웨어하우스, 자동 모델 재학습·자동 승격.

새 기능 발견 시 `.harness/expansion-candidates.md`에 `EXPANSION-XXX`로만 기록하고 구현하지 않는다.

## 범위 감시 질문 (매 작업 종료 전)

"이 변경은 사전등록 사용자 추천, 현장 키오스크 검색, 공통 업체·부스 데이터, 간단 바이어 상담 중 하나에 직접 필요한가?" - 아니오면 제거하고 확장후보로 이동한다.

다음 표현이 등장하면 범위 확장을 의심한다: 장기 CRM, 자동 계약, 실시간 재고, 정밀 실내경로, 마케팅 자동화, 대규모 데이터 플랫폼, 실시간 학습, 전용 벡터 DB, 복잡한 이벤트 스트리밍.

## 이번 재설계에서 확정된 축소 (참고)

`interaction.meeting` 도메인 7테이블 중 `Meeting`/`MeetingStatusHistory`/`MeetingContactShare` 3개만 MVP에 노출 - 나머지(`AvailabilitySlot`/`MeetingSlotRequest`/`MeetingOutcome`/`FollowUpAction`)는 삭제하지 않되 API·화면에 노출하지 않는다(`docs/redesign-v2/web/W-7-buyer-matching-consultation.md` §1~2, `.harness/expansion-candidates.md` EXPANSION-002/003).

## Scope Status

`LOCKED` - `.harness/state.json.scope_status` 참고. 범위를 바꾸려면 이 문서를 먼저 갱신하고 `.harness/decisions.md`에 근거를 남긴다.
