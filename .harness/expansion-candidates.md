# Expansion Candidates

범위 밖이지만 가치 있는 아이디어. 현재 구현하지 않는다.

## EXPANSION-001

**질문**: 키오스크 음성입력이 필요한가?
**분류**: POST_MVP
**근거**: 화면 키보드와 카테고리 탐색으로 MVP 검증 가능
**재검토 조건**: 외국어·고령 사용자 테스트에서 입력 실패율 20% 이상

## EXPANSION-002

**질문**: `backend/`+`frontend/`를 `apps/api`+`apps/user-web`로 물리적 리네임할 것인가?
**분류**: NEXT_WAVE
**근거**: ASSUMPTION-001 — 지금 하기엔 위험 대비 이득이 적음
**재검토 조건**: KIOSK/ADMIN 트랙 골격이 안정화된 뒤, 또는 사용자가 명시적으로 요청할 때
