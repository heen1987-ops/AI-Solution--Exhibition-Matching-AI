# tests/e2e/

QA_SECURITY 트랙 소유. Playwright로 브라우저에서 실제 화면 흐름을 검증한다.

## WEB_ONLY Smoke

`web-only-smoke.spec.ts`는 CR-001 이후 MVP 채널 전략인 WEB_ONLY 기준만 검증한다.

- user-web 등록 사용자 surface: `/home` -> `/recommendations` -> `/favorites` -> `/buyer-matching`
- user-web 게스트 웹 모바일 surface: `/search?q=목재&mode=GUEST_WEB` -> `/companies/c-001`
- admin 운영 surface: `/console`, content approval/booth status live forms and contract-pending panels

전용 kiosk 모듈은 CR-001 이후 MVP E2E 대상이 아니다.

포트 3000/3100/3200은 로컬의 다른 개발 서버와 충돌하기 쉬워 E2E 전용 포트
3300/3320을 사용한다. 기존 서버 재사용도 끈다.
