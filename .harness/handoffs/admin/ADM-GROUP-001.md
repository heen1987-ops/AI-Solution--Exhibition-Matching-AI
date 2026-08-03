# ADM-GROUP-001 Admin Handoff

상태: DONE

## 구현

- `apps/admin/app/console/page.tsx`
  - `/console`을 예정 목록에서 운영 콘솔로 전환.
  - API/fallback 상태 배너, W-9 기본 통계 3종 fallback, 운영 영역 상태 목록 표시.
  - API 사용 화면이 빌드 시점 fallback으로 고정되지 않도록 `force-dynamic` 적용.
- `apps/admin/app/console/AdminOperationsPanel.tsx`
  - 업체정보 승인 폼: `POST /api/v1/admin/content-approvals`.
  - 부스 운영상태 폼: `PATCH /api/v1/admin/booths/{booth_id}/status`.
  - 바이어 검증과 운영 통계 집계는 현재 frozen API 미노출 상태를 계약 대기 패널로 표시.
- `apps/admin/lib/admin-api.ts`
  - admin API base URL, operator headers, content approval, booth status, console snapshot loader 추가.
- `apps/admin/lib/admin-areas.ts`
  - 14개 관리 영역을 `LIVE` / `CONTRACT_PENDING` / `PLANNED` 상태로 재분류.
- `apps/admin/.env.example`
  - admin API 호출용 base URL과 로컬 운영자 헤더 환경변수 추가.
- `.gitignore`
  - `apps/admin/lib/**`와 `apps/user-web/lib/**`가 루트 Python `lib/` ignore 규칙에 묻히지 않도록 예외 추가.

## 동작 계약

- 실제로 frozen OpenAPI에 존재하는 admin 쓰기 API만 호출한다.
- operator 권한은 `X-MeetAI-Actor-Role=OPERATOR`와 `X-MeetAI-User-Id` 헤더를 사용한다.
- 바이어 검증 플래그(`BuyerNeed.business_email_verified`, `company_verified`) 갱신 API와
  W-9 기본 통계 집계 API는 아직 계약에 없으므로 화면에서 계약 대기로 드러낸다.
- 미승인 업체가 검색·추천에 노출되지 않는 정책은 content approval 운영 흐름의 전제로 유지한다.

## 검증

- `cd apps/admin && npm run lint`
- `cd apps/admin && npm run typecheck`
- `cd apps/admin && npm test`: 5 files, 8 tests passed.
- `cd apps/admin && npm run build`
- Playwright smoke:
  - `/console` desktop open.
  - mobile viewport 390x844 screenshot 확인.
  - console log는 React DevTools/HMR 정보만 존재.

## 후속

- `QAS-GROUP-001`: user-web/admin WEB_ONLY 통합 E2E, 권한/계약/접근성/모바일 smoke를 묶어 검증.
- 필요 시 후속 CHANGE_REQUEST 또는 BAC 작업:
  - admin buyer verification endpoint.
  - admin aggregate statistics endpoint.
